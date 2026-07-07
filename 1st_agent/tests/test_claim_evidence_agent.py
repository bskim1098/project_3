import unittest

from first_agent.agents.claim_evidence_agent import (
    pick_ce_only,
    run_claim_evidence_agent,
)
from frontend.streamlit_app import make_input_state


class ClaimEvidenceAgentTests(unittest.TestCase):
    def test_supported_comparison_produces_ce_only_handoff(self):
        state = make_input_state(
            news_title="올해 수출 8% 감소",
            news_body="올해 수출은 지난해보다 감소했다.",
            chart_text="2024년 수출 100억달러\n2025년 수출 92억달러",
            source_text="출처: 산업연구원, 기간: 2024~2025년, 단위: 억달러",
        )

        output = pick_ce_only(run_claim_evidence_agent(state))

        self.assertEqual("믿어도 됨", output["ce_draft_judgement"])
        self.assertTrue(all(key.startswith("ce_") for key in output))
        self.assertIn("대체로 일치", output["ce_draft_summary"])

    def test_clear_opposite_direction_can_use_high_distortion_risk(self):
        state = make_input_state(
            news_title="올해 수출 증가",
            news_body="올해 수출이 증가했다고 밝혔다.",
            chart_text="2024년 수출 100억달러\n2025년 수출 92억달러",
            source_text="출처: 산업연구원, 기간: 2024~2025년, 단위: 억달러",
        )

        output = pick_ce_only(run_claim_evidence_agent(state))

        self.assertEqual("왜곡 가능성 높음", output["ce_draft_judgement"])
        self.assertIn("증가", output["ce_draft_summary"])
        self.assertIn("감소", output["ce_draft_summary"])

    def test_missing_source_stays_limited_even_when_direction_conflicts(self):
        state = make_input_state(
            news_title="올해 수출 증가",
            news_body="올해 수출이 증가했다고 밝혔다.",
            chart_text="2024년 수출 100억달러\n2025년 수출 92억달러",
            source_text="",
        )

        output = pick_ce_only(run_claim_evidence_agent(state))

        self.assertEqual("검증 제한", output["ce_draft_judgement"])


if __name__ == "__main__":
    unittest.main()
