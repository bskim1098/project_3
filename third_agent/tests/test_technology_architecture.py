import unittest

from frontend.technology_architecture import (
    format_technology_architectures,
    get_technology_architectures,
)


class TechnologyArchitectureTests(unittest.TestCase):
    def test_statuses_match_the_actual_project_scope(self):
        architectures = {
            item["name"]: item for item in get_technology_architectures()
        }

        self.assertEqual("도입 예정", architectures["GraphRAG"]["status"])
        self.assertEqual("적용됨", architectures["LangGraph"]["status"])
        self.assertEqual("적용됨", architectures["LangChain"]["status"])
        self.assertIn("claim_extraction", architectures["LangGraph"]["flow"])
        self.assertIn("verdict_critic", architectures["LangGraph"]["flow"])

    def test_text_output_contains_status_flow_and_handoff(self):
        output = format_technology_architectures()

        self.assertIn("[GraphRAG] 도입 예정", output)
        self.assertIn("chart_extraction → claim_extraction", output)
        self.assertIn("vc: START → verdict_critic → vc: END", output)
        self.assertIn("ChatPromptTemplate → ChatOpenAI", output)
        self.assertIn("인계:", output)


if __name__ == "__main__":
    unittest.main()
