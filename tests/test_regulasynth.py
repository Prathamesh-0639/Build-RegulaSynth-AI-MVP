import tempfile
import unittest
from pathlib import Path

from backend import database, services
from backend.utils.rag_tools import extract_requirements, retrieve_policy_evidence, TextChunk


class RegulaSynthTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DATABASE_PATH = Path(self.temp_dir.name) / "test.db"
        database.initialize_database()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_extracts_obligation_and_page_reference(self):
        text = (
            "[Page 1]\nThe organization shall notify the regulator within 72 hours "
            "after discovering a personal data breach."
        )
        requirements = extract_requirements(text)
        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0].page, 1)
        self.assertIn("within 72 hours", requirements[0].text)

    def test_policy_retrieval_prefers_relevant_evidence(self):
        candidates = [
            TextChunk("P1", 1, "The organization notifies the regulator within 72 hours of a breach."),
            TextChunk("P2", 2, "All employees receive annual office safety training."),
        ]
        matches = retrieve_policy_evidence(
            "The organization shall notify the regulator within 72 hours after a data breach.",
            candidates,
        )
        self.assertEqual(matches[0][0].chunk_id, "P1")
        self.assertGreater(matches[0][1], matches[1][1])

    def test_local_analysis_persists_findings_and_review_audit(self):
        regulation = {
            "kind": "regulation",
            "name": "regulation.pdf",
            "page_count": 1,
            "text": "[Page 1]\nThe organization shall notify the regulator within 72 hours "
            "after discovering a personal data breach.",
        }
        policy = {
            "kind": "policy",
            "name": "policy.pdf",
            "page_count": 1,
            "text": "[Page 1]\nThe organization must notify the regulator within 72 hours "
            "after discovering a personal data breach.",
        }
        case_id = services.create_case("Test case", regulation, [policy])
        case = services.run_analysis(case_id, "local")
        self.assertEqual(case["status"], "complete")
        self.assertEqual(len(case["findings"]), 1)
        finding = case["findings"][0]
        self.assertEqual(finding["status"], "Likely covered")

        services.review_finding(case_id, finding["finding_id"], "confirmed", "Reviewed")
        reviewed_case = services.get_case(case_id)
        self.assertEqual(reviewed_case["findings"][0]["decision"], "confirmed")
        self.assertEqual(
            database.fetch_one("SELECT COUNT(*) AS count FROM audits")["count"], 1
        )


if __name__ == "__main__":
    unittest.main()
