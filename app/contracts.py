from dataclasses import dataclass
from datetime import date
import json


@dataclass(frozen=True)
class AccessContext:
    tenant_id: str
    acl_groups: tuple[str, ...]
    classifications: tuple[str, ...] = ("public", "synthetic", "confidential")


@dataclass(frozen=True)
class Evidence:
    chunk_id: str
    doc_id: str
    title: str
    text: str
    page_number: int
    document_version: str
    effective_date: str
    tenant_id: str
    acl_group: str
    classification: str
    source_url: str = ""
    score: float = 0.0


def permitted(evidence: Evidence, context: AccessContext, as_of: date) -> bool:
    return (
        evidence.tenant_id == context.tenant_id
        and evidence.acl_group in context.acl_groups
        and evidence.classification in context.classifications
        and bool(evidence.acl_group)
        and date.fromisoformat(evidence.effective_date) <= as_of
    )


def search_filters(context: AccessContext, as_of: date) -> dict:
    if not context.tenant_id or not context.acl_groups:
        raise ValueError("A server-owned tenant and at least one group are required.")
    return {
        "tenant_id": context.tenant_id,
        "acl_group": list(context.acl_groups),
        "classification": list(context.classifications),
        "effective_date <=": as_of.isoformat(),
    }


def grounding_payload(evidence: list[Evidence]) -> str:
    return json.dumps(
        [
            {
                "evidence_id": f"E{position}",
                "title": item.title,
                "page": item.page_number,
                "version": item.document_version,
                "text": item.text,
            }
            for position, item in enumerate(evidence, start=1)
        ],
        ensure_ascii=True,
    )


def validate_answer(answer: dict, evidence: list[Evidence]) -> dict:
    if not isinstance(answer, dict) or set(answer) != {"answer", "citations"}:
        raise ValueError("The answer must contain answer and citations only.")
    if not isinstance(answer["answer"], str) or not answer["answer"].strip():
        raise ValueError("The answer text is missing.")
    citations = answer["citations"]
    allowed = {f"E{position}" for position in range(1, len(evidence) + 1)}
    if not isinstance(citations, list) or any(
        not isinstance(citation, str) or citation not in allowed
        for citation in citations
    ):
        raise ValueError("The model returned an unknown citation.")
    if evidence and not citations:
        raise ValueError("An evidence-based answer must cite retrieved evidence.")
    return answer
