from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import Evidence
from app.corpus import create_samples


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.directory.name))
        self.evidence = Evidence("chunk", "doc", "Policy", "Independent lending approval required", 1, "1", "2026-01-01", "us-commercial", "compliance-analysts", "synthetic")

    def tearDown(self):
        self.directory.cleanup()

    def client(self):
        from app.main import create_app
        return TestClient(create_app(self.settings))

    def test_request_cannot_supply_identity_or_filters(self):
        with patch("app.main.build_chunks", return_value=[self.evidence]), self.client() as client:
            response = client.post("/api/ask", json={"query": "lending", "tenant_id": "another", "filters": {}})
            self.assertEqual(response.status_code, 422)

    def test_offline_response_explicitly_reports_no_model(self):
        with patch("app.main.build_chunks", return_value=[self.evidence]), self.client() as client:
            response = client.post("/api/ask", json={"query": "lending", "as_of": "2026-11-09"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["mode"], "offline")
            self.assertIn("not a model-generated", response.json()["answer"])
            self.assertEqual(response.json()["citations"], ["E1"])

    def test_cross_origin_request_is_denied(self):
        with patch("app.main.build_chunks", return_value=[]), self.client() as client:
            response = client.post("/api/ask", headers={"Origin": "https://untrusted.example"}, json={"query": "lending"})
            self.assertEqual(response.status_code, 403)

    def test_cloud_configuration_never_falls_back_to_local(self):
        self.settings = replace(self.settings, mode="foundry")
        with self.client() as client:
            response = client.post("/api/ask", json={"query": "lending"})
            self.assertEqual(response.status_code, 503)
            self.assertIn("DATABRICKS_HOST", response.json()["detail"])

    def test_caller_header_cannot_escalate_access(self):
        restricted = replace(self.evidence, acl_group="risk-leads")
        with patch("app.main.build_chunks", return_value=[restricted]), self.client() as client:
            response = client.post("/api/ask", headers={"X-Caller-Identity": "risk-leads"}, json={"query": "lending", "as_of": "2026-11-09"})
            self.assertEqual(response.json()["evidence"], [])

    def test_source_preview_renders_pdf_pixels_and_checks_page_bounds(self):
        manifest = create_samples(self.settings.data_dir)[:1]
        (self.settings.data_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with patch("app.main.build_chunks", return_value=[]), self.client() as client:
            response = client.get(f"/api/documents/{manifest[0]['doc_id']}/preview/1")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.startswith(b"\x89PNG"))
            self.assertEqual(response.headers["X-Page-Count"], "1")
            self.assertEqual(client.get(f"/api/documents/{manifest[0]['doc_id']}/preview/999").status_code, 404)

    def test_source_preview_does_not_bypass_document_access(self):
        manifest = create_samples(self.settings.data_dir)[9:10]
        (self.settings.data_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with patch("app.main.build_chunks", return_value=[]), self.client() as client:
            self.assertEqual(client.get(f"/api/documents/{manifest[0]['doc_id']}/preview/1").status_code, 404)


if __name__ == "__main__":
    unittest.main()