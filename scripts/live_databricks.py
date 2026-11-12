import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from uuid import UUID

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service import catalog, jobs, workspace
import nbformat


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings


def schema_marker(subscription):
    subscription_id = str(UUID(subscription))
    return f"Regulatory RAG demo / subscription {subscription_id[:8]}"


class RunTerminated(Exception):
    def __init__(self, run):
        self.run = run
        super().__init__("The job reported terminal status.")


def save_receipt(name, payload):
    path = ROOT / "artifacts" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def execution_notebook(path, args):
    notebook = nbformat.read(path, as_version=4)
    prepared_cells = []
    for cell in notebook.cells:
        if cell.cell_type != "code":
            prepared_cells.append(cell)
            continue
        if cell.source.lstrip().startswith("%pip install"):
            cell.source = cell.source.rstrip() + " typing-extensions==4.16.0\n"
            prepared_cells.append(cell)
            prepared_cells.append(nbformat.v4.new_code_cell(
                "dbutils.library.restartPython()",
                id="restart-dependencies",
                metadata={"language": "python", "id": "restart-dependencies"},
            ))
            continue
        cell.source = cell.source.replace("('catalog', 'rag_demo')", f"('catalog', {args.catalog!r})")
        cell.source = cell.source.replace(
            "spark.sql(f'CREATE CATALOG IF NOT EXISTS {catalog}')",
            f"if catalog != {args.catalog!r}:\n    raise ValueError('Use the approved existing demo catalog.')\n"
            "spark.sql(f'USE CATALOG {catalog}')",
        )
        cell.source = "\n".join(
            f"print('DATABRICKS_HOST=' + {args.host!r})" if "spark.conf.get('spark.databricks.workspaceUrl')" in line else line
            for line in cell.source.splitlines()
        )
        prepared_cells.append(cell)
    notebook.cells = prepared_cells
    notebook.cells.append(nbformat.v4.new_code_cell(
        "dbutils.notebook.exit(json.dumps(receipt, default=str))",
        id="live-receipt",
        metadata={"language": "python", "id": "live-receipt"},
    ))
    return notebook


def prepare(client, args):
    marker = schema_marker(args.subscription)
    manifest_path = ROOT / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest or len({item["doc_id"] for item in manifest}) != len(manifest):
        raise ValueError("The source manifest must contain unique documents.")
    client.catalogs.get(args.catalog)
    schema_name = f"{args.catalog}.rag"
    try:
        schema = client.schemas.get(schema_name)
        if schema.comment != marker:
            raise ValueError("The existing rag schema is not marked as this demo; do not overwrite it.")
    except NotFound:
        client.schemas.create("rag", args.catalog, comment=marker)
    volume_name = f"{schema_name}.raw_pdfs"
    try:
        volume = client.volumes.read(volume_name)
        if volume.comment != marker:
            raise ValueError("The existing raw_pdfs Volume is not marked as this demo.")
    except NotFound:
        client.volumes.create(args.catalog, "rag", "raw_pdfs", catalog.VolumeType.MANAGED, comment=marker)
    volume_path = f"/Volumes/{args.catalog}/rag/raw_pdfs"
    client.files.create_directory(f"{volume_path}/pdfs")
    for entry in manifest:
        path = (ROOT / "data" / entry["path"]).resolve()
        if not path.is_relative_to((ROOT / "data").resolve()) or path.suffix.lower() != ".pdf":
            raise ValueError("The manifest contains an invalid source path.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Source hash mismatch: {entry['doc_id']}")
        with path.open("rb") as stream:
            client.files.upload(f"{volume_path}/pdfs/{path.name}", stream, overwrite=True, use_parallel=False)
        print(f"Uploaded {entry['doc_id']}", flush=True)
    with manifest_path.open("rb") as stream:
        client.files.upload(f"{volume_path}/manifest.json", stream, overwrite=True, use_parallel=False)

    notebook = execution_notebook(ROOT / "notebooks" / "01_databricks_rag.ipynb", args)
    content = nbformat.writes(notebook).encode()
    version = hashlib.sha256(content).hexdigest()[:12]
    folder = "/Shared/regulatory_rag_demo"
    path = f"{folder}/01_databricks_rag_{version}"
    client.workspace.mkdirs(folder)
    try:
        client.workspace.get_status(path)
    except NotFound:
        client.workspace.import_(path, content=base64.b64encode(content).decode(), format=workspace.ImportFormat.JUPYTER, overwrite=False)
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(), "host": args.host,
        "catalog": args.catalog, "volume": volume_path, "documents_uploaded": len(manifest),
        "public_documents": sum(bool(item.get("source_url")) for item in manifest),
        "notebook_path": path, "index_name": f"{schema_name}.policy_chunks_index",
        "source_notebook_modified": False,
    }
    save_receipt("live-databricks-prepared.json", report)
    return report


def execute(client, args, prepared):
    request = client.jobs.submit(
        run_name="Regulatory RAG live ingestion and search",
        timeout_seconds=args.timeout,
        performance_target=jobs.PerformanceTarget.STANDARD,
        tasks=[jobs.SubmitTask(
            task_key="regulatory_rag",
            timeout_seconds=args.timeout,
            max_retries=0,
            notebook_task=jobs.NotebookTask(
                notebook_path=prepared["notebook_path"],
                source=jobs.Source.WORKSPACE,
                base_parameters={
                    "catalog": args.catalog, "schema": "rag", "volume": "raw_pdfs",
                    "embedding_model": args.embedding_model,
                    "search_endpoint": "regulatory-rag-search",
                    "parser": "pypdf", "confirm_paid_search": "yes",
                },
            ),
        )],
    )
    run_id = request.run_id
    report = {**prepared, "run_id": run_id, "status": "submitted", "timeout_seconds": args.timeout}
    save_receipt("live-databricks-run.json", report)
    print(f"Submitted actual serverless job {run_id}", flush=True)
    previous = None

    def progress(run):
        nonlocal previous
        state = run.state.as_dict() if run.state else {}
        key = json.dumps(state, sort_keys=True)
        if key != previous:
            print(json.dumps({"run_id": run_id, "state": state}), flush=True)
            previous = key
        status = run.status.as_dict() if run.status else {}
        if status.get("state") == "TERMINATED":
            raise RunTerminated(run)

    try:
        try:
            run = client.jobs.wait_get_run_job_terminated_or_skipped(run_id, timeout=timedelta(seconds=args.timeout + 120), callback=progress)
        except RunTerminated as completed:
            run = completed.run
        report["state"] = run.state.as_dict() if run.state else {}
        report["run_page_url"] = run.run_page_url
        report["status"] = "completed"
        if not run.tasks:
            raise RuntimeError("The completed job did not contain the expected task.")
        output = client.jobs.get_run_output(run.tasks[0].run_id)
        report["notebook_result"] = json.loads(output.notebook_output.result) if output.notebook_output and output.notebook_output.result else None
        report["error"] = output.error
        save_receipt("live-databricks-run.json", report)
        print(json.dumps(report, indent=2, default=str), flush=True)
        if output.error or report["notebook_result"] is None:
            raise RuntimeError("The remote notebook did not return a successful retrieval receipt.")
    except Exception as error:
        run = client.jobs.get_run(run_id)
        report["status"] = "failed_or_incomplete"
        report["state"] = run.state.as_dict() if run.state else {}
        report["run_page_url"] = run.run_page_url
        report["error_type"] = type(error).__name__
        if run.tasks:
            output = client.jobs.get_run_output(run.tasks[0].run_id)
            report["task_error"] = output.error
            report["task_error_trace"] = output.error_trace
        save_receipt("live-databricks-run.json", report)
        print(json.dumps(report, indent=2, default=str), flush=True)
        raise


def main():
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description="Prepare and optionally execute the authorized live Databricks demonstration.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--catalog", default=settings.databricks_index.split(".")[0])
    parser.add_argument("--embedding-model", default="databricks-qwen3-embedding-0-6b")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--execute", action="store_true", help="Run paid serverless processing and create the triggered search index.")
    args = parser.parse_args()
    if not settings.databricks_host or not settings.azure_tenant_id:
        raise ValueError("Set DATABRICKS_HOST and AZURE_TENANT_ID in the local environment before running ingestion.")
    if args.host != settings.databricks_host or args.tenant != settings.azure_tenant_id:
        raise ValueError("This runner is scoped to the workspace and tenant configured in the local environment.")
    schema_marker(args.subscription)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.catalog) or not 60 <= args.timeout <= 3600:
        raise ValueError("Invalid catalog identifier or execution timeout.")
    client = WorkspaceClient(host=args.host, azure_tenant_id=args.tenant, auth_type="azure-cli")
    prepared = prepare(client, args)
    print(json.dumps(prepared, indent=2), flush=True)
    if args.execute:
        execute(client, args, prepared)


if __name__ == "__main__":
    main()