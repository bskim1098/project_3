import unittest

from first_agent.nodes.claim_chart_compare_node import compare_claim_to_chart


class ClaimChartCompareNodeTests(unittest.TestCase):
    def test_matching_direction_and_percent_change_is_supported(self):
        result = compare_claim_to_chart(
            "올해 수출 8% 감소",
            "올해 수출은 지난해보다 감소했다.",
            "2024년 수출 100억달러\n2025년 수출 92억달러",
        )

        self.assertEqual("supported", result.status)
        self.assertEqual([], result.risk_flags)
        self.assertIn("감소", result.chart_facts[-1])

    def test_opposite_direction_is_contradicted(self):
        result = compare_claim_to_chart(
            "올해 수출 증가",
            "수출이 증가했다고 밝혔다.",
            "2024년 수출 100억달러\n2025년 수출 92억달러",
        )

        self.assertEqual("contradicted", result.status)
        self.assertIn("어긋", result.risk_flags[0])

    def test_same_direction_but_different_amount_is_partial(self):
        result = compare_claim_to_chart(
            "올해 수출 20% 감소",
            "수출 감소가 이어졌다.",
            "2024년 수출 100억달러\n2025년 수출 92억달러",
        )

        self.assertEqual("partial", result.status)
        self.assertIn("변화량", result.summary)

    def test_missing_unit_is_limited(self):
        result = compare_claim_to_chart(
            "올해 수출 감소",
            "수출이 감소했다.",
            "2024년 수출 100\n2025년 수출 92",
        )

        self.assertEqual("limited", result.status)
        self.assertIn("단위", result.risk_flags[0])


if __name__ == "__main__":
    unittest.main()
