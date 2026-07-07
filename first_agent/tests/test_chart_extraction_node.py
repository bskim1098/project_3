import unittest

from ce_agent.nodes.chart_extraction_node import extract_chart_facts


class ChartExtractionNodeTests(unittest.TestCase):
    def test_extracts_only_values_present_in_chart_text(self):
        facts = extract_chart_facts("2024년 10%\n2025년 12%")
        joined = " ".join(facts)
        self.assertIn("2024년", joined)
        self.assertIn("12%", joined)
        self.assertNotIn("증가", joined)

    def test_empty_chart_has_no_facts(self):
        self.assertEqual([], extract_chart_facts(""))


if __name__ == "__main__":
    unittest.main()
