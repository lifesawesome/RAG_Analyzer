from dataclasses import asdict
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.contracts import AccessContext, Evidence, permitted


def load_manifest(data_dir: Path) -> list[dict]:
    path = data_dir / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def document_path(data_dir: Path, entry: dict) -> Path:
    path = (data_dir / entry["path"]).resolve()
    if not path.is_relative_to(data_dir.resolve()):
        raise ValueError("Document path escapes the data directory.")
    return path


def build_chunks(data_dir: Path) -> list[Evidence]:
    manifest = load_manifest(data_dir)
    if not manifest:
        return []
    fingerprint = hashlib.sha256(json.dumps({
        "manifest": manifest,
        "files": [hashlib.sha256(document_path(data_dir, entry).read_bytes()).hexdigest() for entry in manifest],
        "splitter": "characters-600-overlap-80-v1",
    }, sort_keys=True).encode()).hexdigest()
    cache_path = data_dir / "chunks-cache.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached["fingerprint"] == fingerprint:
                return [Evidence(**entry) for entry in cached["chunks"]]
        except (ValueError, KeyError, TypeError, OSError):
            pass
    splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=80)
    chunks = []
    for entry in manifest:
        for page_number, page in enumerate(PdfReader(document_path(data_dir, entry)).pages, start=1):
            for position, text in enumerate(splitter.split_text(page.extract_text() or "")):
                chunk_id = hashlib.sha256(f"{entry['doc_id']}:{entry['sha256']}:{page_number}:{position}".encode()).hexdigest()
                chunks.append(Evidence(
                    chunk_id=chunk_id, doc_id=entry["doc_id"], title=entry["title"],
                    text=text, page_number=page_number, document_version=entry["document_version"],
                    effective_date=entry["effective_date"], tenant_id=entry["tenant_id"],
                    acl_group=entry["acl_group"], classification=entry["classification"],
                    source_url=entry.get("source_url", ""),
                ))
    cache_path.write_text(json.dumps({"fingerprint": fingerprint, "chunks": [asdict(item) for item in chunks]}), encoding="utf-8")
    return chunks


class LocalSearch:
    def __init__(self, chunks: list[Evidence]):
        self.chunks = {item.chunk_id: item for item in chunks}
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.execute("CREATE VIRTUAL TABLE evidence USING fts5(chunk_id UNINDEXED, text, tenant UNINDEXED, acl UNINDEXED, effective UNINDEXED)")
        self.connection.executemany("INSERT INTO evidence VALUES (?, ?, ?, ?, ?)", [
            (item.chunk_id, item.text, item.tenant_id, item.acl_group, item.effective_date) for item in chunks
        ])

    def search(self, query: str, context: AccessContext, as_of: date, top_k: int = 6) -> list[Evidence]:
        tokens = re.findall(r"\w+", query, flags=re.UNICODE)[:24]
        if not tokens or not context.acl_groups:
            return []
        expression = " OR ".join(f'"{token}"' for token in tokens)
        placeholders = ",".join("?" for _ in context.acl_groups)
        rows = self.connection.execute(
            f"SELECT chunk_id, bm25(evidence) FROM evidence WHERE evidence MATCH ? AND tenant = ? AND acl IN ({placeholders}) AND effective <= ? ORDER BY bm25(evidence) LIMIT ?",
            [expression, context.tenant_id, *context.acl_groups, as_of.isoformat(), top_k],
        ).fetchall()
        return [Evidence(**{**asdict(self.chunks[chunk_id]), "score": -float(score)})
                for chunk_id, score in rows if permitted(self.chunks[chunk_id], context, as_of)]
