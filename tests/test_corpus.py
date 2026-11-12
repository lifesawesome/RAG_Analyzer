from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
import contextlib
import io

import httpx

from app.corpus import create_samples, fetch_public_pdf
from app.config import Settings
from app.local_search import build_chunks
from scripts import finalize_live_index, live_databricks
from scripts.live_databricks import execute, execution_notebook, ROOT, schema_marker
from scripts.finalize_live_index import projection_sql


class CorpusTests(unittest.TestCase):
    def test_sample_generation_is_reproducible(self):
        with TemporaryDirectory() as folder:
            first = create_samples(Path(folder))
            second = create_samples(Path(folder))
            self.assertEqual([entry["sha256"] for entry in first], [entry["sha256"] for entry in second])
            self.assertEqual(len(first), 20)

    def test_public_page_is_resolved_to_a_pdf_download(self):
        def handler(request):
            if request.url.path.endswith(".pdf"):
                return httpx.Response(200, content=b"%PDF-test-content")
            return httpx.Response(200, text='<a href="/reports/document.pdf">Download</a>')
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            content, source = fetch_public_pdf(client, "https://www.bis.org/publication")
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertEqual(source, "https://www.bis.org/reports/document.pdf")

    def test_cross_host_download_links_are_rejected(self):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text='<a href="https://untrusted.example/document.pdf">Download</a>'))) as client:
            with self.assertRaises(ValueError):
                fetch_public_pdf(client, "https://www.bis.org/publication")

    def test_unchanged_document_cache_avoids_reparsing(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            manifest = create_samples(directory)[:1]
            (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            first = build_chunks(directory)
            self.assertTrue(first)
            with patch("app.local_search.PdfReader") as reader:
                self.assertEqual(build_chunks(directory), first)
                reader.assert_not_called()

    def test_live_notebook_uses_existing_managed_catalog(self):
        args = SimpleNamespace(catalog="rag_demo", host="https://adb-123.4.azuredatabricks.net")
        notebook = execution_notebook(ROOT / "notebooks" / "01_databricks_rag.ipynb", args)
        setup = next(cell.source for cell in notebook.cells if "for name, default in" in cell.source)
        values = {}

        class Widgets:
            def text(self, name, default):
                values.setdefault(name, default)

            def dropdown(self, name, default, options):
                values.setdefault(name, default)

            def get(self, name):
                return values[name]

        sql = []
        fake_spark = SimpleNamespace(sql=sql.append)
        scope = {"dbutils": SimpleNamespace(widgets=Widgets()), "spark": fake_spark}
        exec(setup, scope)
        self.assertEqual(scope["catalog"], args.catalog)
        self.assertFalse(any("CREATE CATALOG" in statement for statement in sql))
        self.assertIn(f"USE CATALOG {args.catalog}", sql)
        self.assertTrue(any("CREATE SCHEMA" in statement for statement in sql))
        self.assertEqual(notebook.cells[-1].id, "live-receipt")
        dependency_position = next(position for position, cell in enumerate(notebook.cells) if cell.source.lstrip().startswith("%pip install"))
        self.assertIn("typing-extensions==4.16.0", notebook.cells[dependency_position].source)
        self.assertEqual(notebook.cells[dependency_position + 1].source, "dbutils.library.restartPython()")

    def test_failed_terminal_job_is_not_reported_as_success(self):
        client = MagicMock()
        client.jobs.submit.return_value.run_id = 42
        run = SimpleNamespace(
            state=SimpleNamespace(as_dict=lambda: {"life_cycle_state": "INTERNAL_ERROR", "result_state": "FAILED"}),
            status=SimpleNamespace(as_dict=lambda: {"state": "TERMINATED"}),
            run_page_url="https://example.invalid/run/42",
            tasks=[SimpleNamespace(run_id=43)],
        )

        def wait(run_id, timeout, callback):
            callback(run)
            self.fail("The terminal callback should stop waiting.")

        client.jobs.wait_get_run_job_terminated_or_skipped.side_effect = wait
        client.jobs.get_run.return_value = run
        client.jobs.get_run_output.return_value = SimpleNamespace(notebook_output=None, error="Test failure", error_trace="Test trace")
        args = SimpleNamespace(timeout=60, catalog="rag_demo", embedding_model="model")
        with patch("scripts.live_databricks.save_receipt") as save, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                execute(client, args, {"notebook_path": "/Shared/test"})
        self.assertEqual(save.call_args.args[1]["status"], "failed_or_incomplete")

    def test_versioned_projection_uses_a_real_date_without_dropping_data(self):
        statement = projection_sql()
        self.assertIn("CAST(effective_date AS DATE)", statement)
        self.assertIn("delta.enableChangeDataFeed", statement)
        self.assertIn("policy_chunks_dated", statement)
        self.assertNotIn("DROP", statement)
        self.assertNotIn("REPLACE", statement)

    def test_projection_uses_the_configured_catalog(self):
        statement = projection_sql("test_demo")
        self.assertIn("test_demo.rag.policy_chunks_dated", statement)
        self.assertIn("FROM test_demo.rag.policy_chunks", statement)
        with self.assertRaisesRegex(ValueError, "catalog"):
            projection_sql("invalid; DROP TABLE example")

    def test_schema_marker_uses_the_explicit_subscription(self):
        self.assertEqual(
            schema_marker("00000000-0000-0000-0000-000000000001"),
            "Regulatory RAG demo / subscription 00000000",
        )
        with self.assertRaises(ValueError):
            schema_marker("not-a-subscription")

    def test_ingestion_requires_a_locally_configured_destination(self):
        argv = ["live_databricks.py", "--host", "https://adb-123.4.azuredatabricks.net", "--tenant", "demo-tenant", "--subscription", "00000000-0000-0000-0000-000000000001"]
        with patch("sys.argv", argv), patch.object(live_databricks.Settings, "from_env", return_value=Settings()), patch.object(live_databricks, "WorkspaceClient") as client:
            with self.assertRaisesRegex(ValueError, "local environment"):
                live_databricks.main()
            client.assert_not_called()

    def test_ingestion_rejects_a_destination_outside_local_configuration(self):
        settings = Settings(azure_tenant_id="demo-tenant", databricks_host="https://adb-123.4.azuredatabricks.net")
        argv = ["live_databricks.py", "--host", "https://adb-999.4.azuredatabricks.net", "--tenant", settings.azure_tenant_id, "--subscription", "00000000-0000-0000-0000-000000000001"]
        with patch("sys.argv", argv), patch.object(live_databricks.Settings, "from_env", return_value=settings), patch.object(live_databricks, "WorkspaceClient") as client:
            with self.assertRaisesRegex(ValueError, "scoped"):
                live_databricks.main()
            client.assert_not_called()

    def test_ingestion_uses_the_configured_catalog_and_explicit_subscription(self):
        settings = Settings(azure_tenant_id="demo-tenant", databricks_host="https://adb-123.4.azuredatabricks.net", databricks_index="test_demo.rag.policy_chunks_index_dated")
        subscription = "00000000-0000-0000-0000-000000000001"
        argv = ["live_databricks.py", "--host", settings.databricks_host, "--tenant", settings.azure_tenant_id, "--subscription", subscription]
        with patch("sys.argv", argv), patch.object(live_databricks.Settings, "from_env", return_value=settings), patch.object(live_databricks, "WorkspaceClient") as client, patch.object(live_databricks, "prepare", return_value={}) as prepare, patch.object(live_databricks, "execute") as execute, contextlib.redirect_stdout(io.StringIO()):
            live_databricks.main()
            client.assert_called_once_with(host=settings.databricks_host, azure_tenant_id=settings.azure_tenant_id, auth_type="azure-cli")
            self.assertEqual(prepare.call_args.args[1].catalog, "test_demo")
            self.assertEqual(prepare.call_args.args[1].subscription, subscription)
            execute.assert_not_called()

    def test_finalization_requires_explicit_subscription_and_warehouse(self):
        with patch("sys.argv", ["finalize_live_index.py", "--execute"]), patch.object(finalize_live_index.Settings, "from_env", return_value=Settings()), patch.object(finalize_live_index, "WorkspaceClient") as client, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                finalize_live_index.main()
            self.assertEqual(error.exception.code, 2)
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()