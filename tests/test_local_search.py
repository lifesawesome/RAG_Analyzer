from dataclasses import replace
from datetime import date
import unittest

from app.contracts import AccessContext, Evidence
from app.local_search import LocalSearch


class LocalSearchTests(unittest.TestCase):
    def setUp(self):
        self.base = Evidence("allowed", "doc-1", "Policy", "Commercial lending requires independent approval.", 1, "1", "2026-01-01", "us-commercial", "compliance-analysts", "synthetic")
        self.search = LocalSearch([
            self.base,
            replace(self.base, chunk_id="restricted", acl_group="risk-leads"),
            replace(self.base, chunk_id="foreign", tenant_id="another-tenant"),
            replace(self.base, chunk_id="future", effective_date="2027-01-01"),
        ])
        self.context = AccessContext("us-commercial", ("compliance-analysts",))

    def tearDown(self):
        self.search.connection.close()

    def test_only_authorized_current_evidence_is_returned(self):
        results = self.search.search("commercial lending", self.context, date(2026, 11, 9))
        self.assertEqual([item.chunk_id for item in results], ["allowed"])

    def test_search_syntax_is_not_executed(self):
        results = self.search.search('" OR tenant:* --', self.context, date(2026, 11, 9))
        self.assertEqual(results, [])

    def test_empty_query_returns_no_evidence(self):
        self.assertEqual(self.search.search("?!", self.context, date(2026, 11, 9)), [])

    def test_historical_query_excludes_later_evidence(self):
        self.assertEqual(self.search.search("lending", self.context, date(2025, 1, 1)), [])


if __name__ == "__main__":
    unittest.main()