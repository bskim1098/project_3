import unittest

from ce_agent.nodes.strong_expression_node import (
    detect_risk_flags,
    extract_strong_expressions,
)


class StrongExpressionNodeTests(unittest.TestCase):
    def test_extracts_unique_strong_and_causal_expressions(self):
        found = extract_strong_expressions("수출 폭증", "정책 때문에 수출이 폭증했다")
        self.assertEqual(["폭증", "때문에"], found)

    def test_marks_causal_claim_and_period_generalization(self):
        strong = extract_strong_expressions("역대 최고, 정책 때문에 증가", "")
        flags = detect_risk_flags(
            "역대 최고, 정책 때문에 증가", "", "2024년 10%\n2025년 12%", "통계청", strong
        )
        self.assertTrue(any("인과" in flag for flag in flags))
        self.assertTrue(any("일반화" in flag for flag in flags))

    def test_separates_missing_unit_from_missing_period(self):
        flags = detect_risk_flags("증가", "", "2024년 100\n2025년 120", "통계청", [])
        self.assertTrue(any("단위" in flag for flag in flags))
        self.assertFalse(any("비교 기간" in flag for flag in flags))


if __name__ == "__main__":
    unittest.main()
