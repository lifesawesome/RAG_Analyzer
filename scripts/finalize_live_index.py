import argparse
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import re
import sys

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.sql import ExecuteStatementRequestOnWaitTimeout


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from scripts.live_databricks import schema_marker


COLUMNS = ["chunk_id", "doc_id", "title", "chunk_text", "page_number", "document_version", "tenant_id", "acl_group", "classification", "source_url"]


def projection_sql(catalog="rag_demo"):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", catalog):
        raise ValueError("Invalid catalog identifier.")
    return (
        f"CREATE TABLE IF NOT EXISTS {catalog}.rag.policy_chunks_dated "
        "TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true') AS "
        f"SELECT {', '.join(COLUMNS)}, CAST(effective_date AS DATE) AS effective_date "
        f"FROM {catalog}.rag.policy_chunks"
    )


def main():
    settings = replace(Settings.from_env(), mode="databricks")
    parser = argparse.ArgumentParser(description="Create a versioned DATE-typed Gold projection and search index without re-parsing PDFs.")
    parser.add_argument("--execute", action="store_true", help="Authorize the bounded SQL projection and versioned index creation.")
    parser.add_argument("--subscription", help="Approved Azure subscription ID used in the demo schema ownership marker.")
    parser.add_argument("--warehouse", help="Approved Databricks SQL warehouse ID.")
    parser.add_argument("--catalog", default=settings.databricks_index.split(".")[0])
    args = parser.parse_args()
    statement = projection_sql(args.catalog)
    if not args.execute:
        print(statement)
        return
    if not args.subscription or not args.warehouse:
        parser.error("--subscription and --warehouse are required with --execute.")
    marker = schema_marker(args.subscription)
    settings.validate_live()
    source = f"{args.catalog}.rag.policy_chunks_dated"
    index_name = f"{args.catalog}.rag.policy_chunks_index_dated"
    client = WorkspaceClient(
        host=settings.databricks_host,
        azure_tenant_id=settings.azure_tenant_id,
        auth_type="azure-cli",
    )
    schema = client.schemas.get(f"{args.catalog}.rag")
    if schema.comment != marker:
        raise ValueError("The target schema is not the approved demo schema.")
    was_stopped = client.warehouses.get(args.warehouse).state.value == "STOPPED"
    try:
        if was_stopped:
            print("Starting the demo warehouse for the bounded projection.", flush=True)
            client.warehouses.start(args.warehouse).result(timeout=timedelta(minutes=10))
        result = client.statement_execution.execute_statement(
            statement, args.warehouse, wait_timeout="50s",
            on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CANCEL,
        )
        if result.status.state.value != "SUCCEEDED":
            raise RuntimeError(f"Gold projection did not succeed: {result.status.as_dict()}")
        table = client.tables.get(source)
        effective = next(column for column in table.columns if column.name == "effective_date")
        if effective.type_name.value != "DATE" or table.properties.get("delta.enableChangeDataFeed") != "true":
            raise RuntimeError("The projected table is not DATE-typed with CDF enabled.")
    finally:
        if was_stopped:
            client.warehouses.stop(args.warehouse).result(timeout=timedelta(minutes=5))
            print("Stopped the warehouse started by this operation.", flush=True)
    try:
        index = client.vector_search_indexes.get_index(index_name)
    except NotFound:
        index = client.api_client.do("POST", "/api/2.0/vector-search/indexes", body={
            "name": index_name, "endpoint_name": "regulatory-rag-search",
            "primary_key": "chunk_id", "index_type": "DELTA_SYNC",
            "delta_sync_index_spec": {
                "source_table": source, "pipeline_type": "TRIGGERED",
                "embedding_source_columns": [{"name": "chunk_text", "embedding_model_endpoint_name": "databricks-qwen3-embedding-0-6b"}],
                "columns_to_sync": [*COLUMNS, "effective_date"],
            },
        })
    report = {"source_table": source, "index_name": index_name, "effective_date_type": "DATE", "original_index_deleted": False, "warehouse_started_and_stopped": was_stopped, "creation_response": index.as_dict() if hasattr(index, "as_dict") else index}
    output = ROOT / "artifacts" / "dated-index.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()