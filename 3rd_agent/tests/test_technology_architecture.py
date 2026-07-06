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
        self.assertEqual(
            ("START", "verdict_critic", "END"),
            architectures["LangGraph"]["flow"],
        )

    def test_text_output_contains_status_flow_and_handoff(self):
        output = format_technology_architectures()

        self.assertIn("[GraphRAG] 도입 예정", output)
        self.assertIn("START → verdict_critic → END", output)
        self.assertIn("ChatPromptTemplate → ChatOpenAI", output)
        self.assertIn("인계:", output)


if __name__ == "__main__":
    unittest.main()
