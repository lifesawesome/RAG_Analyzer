import argparse
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys

from databricks.sdk import WorkspaceClient
from databricks.sdk.retries import retried


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.cloud import databricks_search, foundry_answer
from app.config import Settings
from app.contracts import AccessContext, search_filters


class IndexNotReady(RuntimeError):
    pass


def main():
    parser = argparse.ArgumentParser(description="Verify the configured DATE-typed retrieval and one grounded Foundry tool call.")
    parser.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args()
    settings = replace(Settings.from_env(), mode="foundry")
    settings.validate_live()
    client = WorkspaceClient(host=settings.databricks_host, azure_tenant_id=settings.azure_tenant_id, auth_type="azure-cli")

    @retried(on=[IndexNotReady], timeout=timedelta(minutes=15))
    def ready_index():
        index = client.vector_search_indexes.get_index(settings.databricks_index)
        status = index.status.as_dict() if index.status else {}
        if not status.get("ready") or status.get("indexed_row_count", 0) < 1:
            raise IndexNotReady("The versioned index is still provisioning.")
        return status

    print("Checking bounded index readiness.", flush=True)
    index_status = ready_index()
    context = AccessContext("us-commercial", ("compliance-analysts",))
    as_of = date(2026, 11, 11)
    question = "What approvals and due diligence apply to elevated-risk commercial lending? Distinguish the synthetic bank policies from public regulatory material."
    evidence = databricks_search(settings, question, context, as_of)
    if not evidence:
        raise RuntimeError("The authorized live query did not return evidence.")
    denials = {
        "unknown_group": (AccessContext("us-commercial", ("nonexistent-demo-cohort",)), as_of),
        "other_tenant": (AccessContext("unrelated-tenant", ("compliance-analysts",)), as_of),
        "historical_date": (context, date(2024, 1, 1)),
    }
    for label, (denied_context, denied_date) in denials.items():
        if databricks_search(settings, question, denied_context, denied_date):
            raise RuntimeError(f"Live denial check failed: {label}")
    trace = []

    def retrieve(query):
        result = databricks_search(settings, query, context, as_of)
        trace.append({"stage": "Databricks hybrid search", "detail": f"{len(result)} actual authorized passages", "milliseconds": 0, "status": "ok", "filters": search_filters(context, as_of)})
        return result

    answer, grounded_evidence = foundry_answer(settings, question, retrieve, trace)
    if not grounded_evidence or not answer["citations"]:
        raise RuntimeError("Foundry did not produce a cited answer from actual Databricks evidence.")
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_id": settings.azure_tenant_id,
        "index_name": settings.databricks_index,
        "index_status": index_status,
        "question": question, "as_of": as_of.isoformat(),
        "filters": search_filters(context, as_of),
        "direct_retrieval_count": len(evidence),
        "denial_checks": {label: "passed" for label in denials},
        **answer,
        "evidence": [asdict(item) for item in grounded_evidence],
        "trace": trace,
        "actual_databricks_query": True,
        "actual_foundry_tool_call": True,
        "offline_fallback_used": False,
    }
    output = ROOT / "artifacts" / "live-rag-receipt.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "evidence"}, indent=2, default=str), flush=True)
    print(f"Live evidence receipt: {output}", flush=True)


if __name__ == "__main__":
    main()