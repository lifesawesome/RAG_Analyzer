from datetime import date
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import httpx

from app.cloud import create_agent, databricks_search, foundry_answer
from app.config import Settings
from app.contracts import AccessContext, Evidence


class CloudContractTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(mode="foundry", azure_tenant_id="00000000-0000-0000-0000-000000000000", databricks_host="https://adb-123.4.azuredatabricks.net", foundry_endpoint="https://new-demo.services.ai.azure.com/api/projects/demo")
        self.context = AccessContext("us-commercial", ("compliance-analysts",))
        self.evidence = Evidence("chunk", "doc", "Policy", "Independent approval required", 1, "1", "2026-01-01", "us-commercial", "compliance-analysts", "synthetic")

    def test_live_configuration_requires_an_explicit_tenant(self):
        settings = Settings(mode="databricks", databricks_host=self.settings.databricks_host)
        with self.assertRaisesRegex(ValueError, "AZURE_TENANT_ID"):
            settings.validate_live()

    @patch("app.cloud.AzureCliCredential")
    @patch("app.cloud.httpx.Client")
    def test_databricks_rest_payload_and_column_mapping(self, client_type, credential_type):
        credential_type.return_value.get_token.return_value.token = "not-a-real-token"
        names = ["chunk_id", "doc_id", "title", "chunk_text", "page_number", "document_version", "effective_date", "tenant_id", "acl_group", "classification", "source_url", "score"]
        row = ["chunk", "doc", "Policy", "Independent approval required", 1, "1", "2026-01-01", "us-commercial", "compliance-analysts", "synthetic", "", 0.9]
        client = client_type.return_value.__enter__.return_value
        client.post.return_value = httpx.Response(200, json={"manifest": {"columns": [{"name": name} for name in names]}, "result": {"data_array": [row]}})
        results = databricks_search(self.settings, "lending", self.context, date(2026, 11, 9))
        self.assertEqual(results[0].score, 0.9)
        body = client.post.call_args.kwargs["json"]
        self.assertEqual(body["query_type"], "HYBRID")
        self.assertEqual(json.loads(body["filters_json"])["tenant_id"], "us-commercial")
        self.assertIn("classification", json.loads(body["filters_json"]))

    @patch("app.cloud.AzureCliCredential")
    @patch("app.cloud.httpx.Client")
    def test_databricks_failure_does_not_return_synthetic_evidence(self, client_type, credential_type):
        credential_type.return_value.get_token.return_value.token = "not-a-real-token"
        client_type.return_value.__enter__.return_value.post.return_value = httpx.Response(403)
        with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
            databricks_search(self.settings, "lending", self.context, date(2026, 11, 9))

    @patch("app.cloud.project_client")
    def test_foundry_tool_loop_returns_only_validated_evidence(self, project_factory):
        project = project_factory.return_value.__enter__.return_value
        client = project.get_openai_client.return_value.__enter__.return_value
        client.conversations.create.return_value.id = "demo-conversation"
        call = SimpleNamespace(type="function_call", name="search_compliance_documents", arguments=json.dumps({"query": "lending"}), call_id="call-1")
        client.responses.create.side_effect = [
            SimpleNamespace(id="response-1", output=[call], output_text=""),
            SimpleNamespace(id="response-2", output=[], output_text=json.dumps({"answer": "Independent approval is required.", "citations": ["E1"]})),
        ]
        retrieve = MagicMock(return_value=[self.evidence])
        trace = []
        answer, evidence = foundry_answer(self.settings, "Question", retrieve, trace)
        self.assertEqual(answer["citations"], ["E1"])
        self.assertEqual(evidence, [self.evidence])
        retrieve.assert_called_once_with("lending")
        followup = client.responses.create.call_args_list[1].kwargs
        self.assertEqual(followup["conversation"], "demo-conversation")
        self.assertEqual(followup["input"][0]["type"], "function_call_output")
        self.assertNotIn("tenant_id", followup["input"][0]["output"])
        client.conversations.delete.assert_called_once_with(conversation_id="demo-conversation")

    @patch("app.cloud.project_client")
    def test_agent_definition_is_compatible_with_installed_sdk(self, project_factory):
        project = project_factory.return_value.__enter__.return_value
        project.agents.create_version.return_value = SimpleNamespace(name="demo", version="1", id="agent-1")
        result = create_agent(self.settings)
        self.assertEqual(result["id"], "agent-1")
        definition = project.agents.create_version.call_args.kwargs["definition"]
        self.assertEqual(definition.model, "gpt-4.1")
        self.assertEqual(definition.tools[0].name, "search_compliance_documents")


if __name__ == "__main__":
    unittest.main()