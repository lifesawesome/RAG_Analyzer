import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import ROOT


PUBLIC_REPORTS = [
    ("bcbs189", "https://www.bis.org/publ/bcbs189.pdf"),
    ("bcbs238", "https://www.bis.org/publ/bcbs238.pdf"),
    ("d295", "https://www.bis.org/bcbs/publ/d295.pdf"),
    ("d309", "https://www.bis.org/bcbs/publ/d309.pdf"),
    ("d350", "https://www.bis.org/bcbs/publ/d350.pdf"),
    ("d356", "https://www.bis.org/bcbs/publ/d356.pdf"),
    ("d368", "https://www.bis.org/bcbs/publ/d368.pdf"),
    ("d374", "https://www.bis.org/bcbs/publ/d374.pdf"),
    ("d400", "https://www.bis.org/bcbs/publ/d400.pdf"),
    ("d403", "https://www.bis.org/bcbs/publ/d403.pdf"),
    ("d404", "https://www.bis.org/bcbs/publ/d404.pdf"),
    ("d424", "https://www.bis.org/bcbs/publ/d424.pdf"),
    ("d430", "https://www.bis.org/bcbs/publ/d430.pdf"),
    ("d431", "https://www.bis.org/bcbs/publ/d431.pdf"),
    ("d444", "https://www.bis.org/bcbs/publ/d444.pdf"),
    ("d450", "https://www.bis.org/bcbs/publ/d450.pdf"),
    ("d453", "https://www.bis.org/bcbs/publ/d453.pdf"),
    ("d457", "https://www.bis.org/bcbs/publ/d457.pdf"),
    ("d462", "https://www.bis.org/bcbs/publ/d462.pdf"),
    ("d475", "https://www.bis.org/bcbs/publ/d475.pdf"),
]

SAMPLE_POLICIES = [
    ("Commercial lending policy", "Elevated-risk commercial lending requires enhanced due diligence, an independent credit review and approval by the senior credit committee before funds are committed. The relationship manager cannot self-approve an exception."),
    ("Credit approval authority", "Commercial exposures above the delegated limit require senior credit committee approval. Exceptions need a documented rationale, compensating controls and an expiry date. The risk owner reviews open exceptions every quarter."),
    ("Collateral valuation standard", "Collateral for elevated-risk borrowers is independently valued before approval. The credit officer records valuation date, haircut assumptions and legal enforceability. Material market changes trigger a fresh valuation."),
    ("Enhanced due diligence procedure", "Analysts verify beneficial ownership, sanctions screening, source of funds and adverse media for elevated-risk customers. Unresolved red flags are escalated to compliance before onboarding or credit renewal."),
    ("Liquidity coverage procedure", "Treasury monitors high-quality liquid assets against stressed net cash outflows over a thirty-day horizon. A breach of the internal liquidity buffer is escalated to the asset-liability committee on the same business day."),
    ("Stable funding policy", "The funding team compares available stable funding with required stable funding over a one-year horizon. Long-dated assets must be supported by appropriately stable liabilities. Treasury reports concentrations monthly."),
    ("Regulatory change management", "Compliance maps each regulatory change to affected policies, assigns an accountable owner and records effective dates. Policy owners perform a gap assessment and preserve the prior approved version for historical analysis."),
    ("Customer agreement controls", "Commercial customer agreements identify the borrower, permitted purpose, covenants and remedies. Material covenant waivers require independent legal review and credit approval. Executed agreements are retained with the credit file."),
    ("Financial disclosure standard", "Published disclosures must reconcile to approved financial records. The finance controller signs off on risk-weighted asset disclosures and material changes. Draft disclosures are not treated as final approved evidence."),
    ("Internal audit findings", "Audit identified incomplete evidence of independent approval in a sample of elevated-risk lending files. Remediation requires a second-line review, a documented owner and closure evidence before the audit issue is marked resolved."),
]


def manifest_entry(doc_id: str, title: str, path: Path, source_url: str = "", **updates):
    entry = {
        "doc_id": doc_id, "title": title, "path": f"pdfs/{path.name}",
        "source_url": source_url, "document_version": "1.0",
        "effective_date": "2026-01-01", "tenant_id": "us-commercial",
        "acl_group": "compliance-analysts", "classification": "public" if source_url else "synthetic",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "governance_is_demo": True,
    }
    entry.update(updates)
    return entry


def create_samples(data_dir: Path) -> list[dict]:
    folder = data_dir / "pdfs"
    folder.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    entries = []
    for position in range(20):
        title, body = SAMPLE_POLICIES[position % len(SAMPLE_POLICIES)]
        version = "1.0" if position < 10 else "2.0"
        doc_id = f"demo-policy-{position + 1:02d}"
        path = folder / f"{doc_id}.pdf"
        effective = "2025-01-01" if position < 10 else "2026-01-01"
        if position == 19:
            effective = "2027-01-01"
        scope = "risk-leads" if position in {9, 19} else "compliance-analysts"
        content = [
            Paragraph("NORTHSTAR BANK / SYNTHETIC DEMO", styles["Title"]),
            Spacer(1, 0.25 * inch), Paragraph(title, styles["Heading1"]),
            Paragraph(f"Document: {doc_id} | Version: {version} | Effective: {effective}", styles["Normal"]),
            Spacer(1, 0.2 * inch), Paragraph("1. Scope and requirements", styles["Heading2"]),
            Paragraph(body, styles["BodyText"]), Spacer(1, 0.15 * inch),
            Paragraph("2. Control evidence", styles["Heading2"]),
            Paragraph("Retain the assessment, independent review, approval decision and source references. This fictional document is for demonstration only and is not legal advice or a statement of actual regulatory requirements.", styles["BodyText"]),
            Spacer(1, 0.2 * inch),
        ]
        table = Table([["Control", "Accountable owner", "Review"], ["Evidence completeness", "Policy owner", "Quarterly"], ["Independent approval", "Second line", "Before release"]], colWidths=[180, 160, 120])
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15564a")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey), ("PADDING", (0, 0), (-1, -1), 8)]))
        content.append(table)
        SimpleDocTemplate(str(path), title=title, author="Synthetic demonstration", invariant=1).build(content)
        entries.append(manifest_entry(doc_id, title, path, document_version=version, effective_date=effective, acl_group=scope))
    return entries


class PDFLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        href = values.get("href", "")
        if tag == "a" and urlparse(href).path.lower().endswith(".pdf"):
            self.links.append(href)


def fetch_public_pdf(client: httpx.Client, url: str) -> tuple[bytes, str]:
    def read(target):
        with client.stream("GET", target) as response:
            response.raise_for_status()
            content = bytearray()
            for block in response.iter_bytes():
                content.extend(block)
                if len(content) > 100 * 1024 * 1024:
                    raise ValueError("PDF exceeds 100 MB")
            return bytes(content), str(response.url)

    content, resolved_url = read(url)
    if content.startswith(b"%PDF"):
        return content, resolved_url
    links = PDFLinks()
    links.feed(content.decode("utf-8", errors="replace"))
    for href in dict.fromkeys(links.links):
        target = urljoin(resolved_url, href)
        parsed = urlparse(target)
        if parsed.scheme != "https" or parsed.hostname not in {"bis.org", "www.bis.org"}:
            continue
        candidate, final_url = read(target)
        if candidate.startswith(b"%PDF"):
            return candidate, final_url
    raise ValueError("Publication page did not expose a valid public PDF download.")


def download_public(data_dir: Path) -> list[dict]:
    folder = data_dir / "pdfs"
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "RegulatoryRAG-PoC/1.0 (document research demo)"}) as client:
        for report_id, url in PUBLIC_REPORTS:
            path = folder / f"bis-{report_id}.pdf"
            try:
                source_url = url
                if not path.exists():
                    content, source_url = fetch_public_pdf(client, url)
                    path.write_bytes(content)
                reader = PdfReader(path)
                title = str((reader.metadata or {}).get("/Title", "")).strip() or f"Basel Committee report {report_id}"
                entries.append(manifest_entry(f"bis-{report_id}", title, path, source_url))
                print(f"Downloaded/verified {report_id}: {len(reader.pages)} pages")
            except (httpx.HTTPError, ValueError, OSError) as error:
                print(f"Unavailable {report_id}: {type(error).__name__}: {error}")
    return entries


def main():
    parser = argparse.ArgumentParser(description="Create synthetic demo PDFs and optionally download public BIS reports.")
    parser.add_argument("--public", action="store_true", help="Download and validate 20 public Basel Committee reports in addition to the synthetic corpus.")
    args = parser.parse_args()
    data_dir = ROOT / "data"
    entries = create_samples(data_dir)
    if args.public:
        entries.extend(download_public(data_dir))
    (data_dir / "manifest.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    print(f"Manifest ready: {len(entries)} PDFs ({sum(bool(entry['source_url']) for entry in entries)} public reports)")


if __name__ == "__main__":
    main()
