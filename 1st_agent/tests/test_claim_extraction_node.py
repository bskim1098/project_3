import unittest

from first_agent.nodes.claim_extraction_node import summarize_claim


class ClaimExtractionNodeTests(unittest.TestCase):
    def test_title_is_preserved_without_inventing_claims(self):
        result = summarize_claim("고용 3% 증가", "조사 결과 고용이 늘었다.")
        self.assertIn("고용 3% 증가", result)
        self.assertIn("조사 결과 고용이 늘었다", result)

    def test_empty_article_reports_limitation(self):
        self.assertIn("부족", summarize_claim("", ""))


if __name__ == "__main__":
    unittest.main()
