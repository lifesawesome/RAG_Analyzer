from dataclasses import replace
from datetime import date
import json
import unittest

from app.contracts import (
    AccessContext,
    Evidence,
    grounding_payload,
    permitted,
    search_filters,
    validate_answer,
)


class RetrievalContractTests(unittest.TestCase):
    def setUp(self):
        self.context = AccessContext("us-commercial", ("compliance-analysts",))
        self.today = date(2026, 11, 9)
        self.evidence = Evidence(
            "chunk-1", "policy-1", "Policy", "Policy evidence", 2, "1.0",
            "2026-01-01", "us-commercial", "compliance-analysts", "public",
        )

    def test_server_owned_filters_include_tenant_group_and_date(self):
        self.assertEqual(search_filters(self.context, self.today), {
            "tenant_id": "us-commercial",
            "acl_group": ["compliance-analysts"],
            "classification": ["public", "synthetic", "confidential"],
            "effective_date <=": "2026-11-09",
        })

    def test_other_tenant_and_group_are_denied(self):
        self.assertFalse(permitted(replace(self.evidence, tenant_id="other"), self.context, self.today))
        self.assertFalse(permitted(replace(self.evidence, acl_group="risk-leads"), self.context, self.today))

    def test_missing_group_and_future_documents_are_denied(self):
        self.assertFalse(permitted(replace(self.evidence, acl_group=""), self.context, self.today))
        self.assertFalse(permitted(replace(self.evidence, effective_date="2027-01-01"), self.context, self.today))

    def test_empty_access_context_is_rejected(self):
        with self.assertRaises(ValueError):
            search_filters(AccessContext("us-commercial", ()), self.today)

    def test_disallowed_classification_is_denied(self):
        self.assertFalse(permitted(replace(self.evidence, classification="restricted"), self.context, self.today))

    def test_grounding_is_structured_data_with_page_and_version(self):
        payload = json.loads(grounding_payload([self.evidence]))
        self.assertEqual(payload[0]["evidence_id"], "E1")
        self.assertEqual(payload[0]["page"], 2)
        self.assertEqual(payload[0]["version"], "1.0")

    def test_fabricated_citation_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_answer({"answer": "Claim", "citations": ["E99"]}, [self.evidence])

    def test_valid_citation_is_accepted(self):
        answer = {"answer": "Evidence says this.", "citations": ["E1"]}
        self.assertEqual(validate_answer(answer, [self.evidence]), answer)


if __name__ == "__main__":
    unittest.main()