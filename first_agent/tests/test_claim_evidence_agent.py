import unittest

from first_agent.ce_agent.agents.claim_evidence_agent import (
    ClaimSummaryOutput,
    CE_OUTPUT_FIELDS,
    build_claim_evidence_graph,
    pick_ce_only,
    run_claim_evidence_agent,
)
from frontend.streamlit_app import make_input_state


class ClaimEvidenceAgentTests(unittest.TestCase):
    class StructuredLLM:
        def __init__(self, result):
            self.result = result
            self.requested_schema = None

        def with_structured_output(self, schema):
            self.requested_schema = schema
            return self

        def invoke(self, _messages):
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    def test_graph_contains_expected_langgraph_nodes(self):
        nodes = set(build_claim_evidence_graph().get_graph().nodes)
        self.assertTrue(
            {"chart_extraction", "claim_extraction", "compare_and_judge", "guardrail"}
            <= nodes
        )

    def test_pick_ce_only_returns_exact_six_field_contract(self):
        state = {
            "ce_chart_facts": [],
            "ce_claim_summary": "주장",
            "ce_strong_expressions": [],
            "ce_risk_flags": [],
            "ce_draft_judgement": "검증 제한",
            "ce_draft_summary": "이유",
            "ce_internal_debug": "전달 금지",
            "vc_revision_needed": False,
        }
        output = pick_ce_only(state)
        self.assertEqual(CE_OUTPUT_FIELDS, tuple(output))
        self.assertNotIn("ce_internal_debug", output)

    def test_llm_structured_summary_is_used_but_rule_judgement_is_preserved(self):
        llm = self.StructuredLLM(
            {"ce_claim_summary": "기사는 수출이 감소했다고 주장합니다."}
        )
        state = make_input_state(
            news_title="올해 수출 증가",
            news_body="올해 수출이 증가했다고 밝혔다.",
            chart_text="2024년 수출 100억달러\n2025년 수출 92억달러",
            source_text="출처: 산업연구원, 기간: 2024~2025년, 단위: 억달러",
        )

        output = pick_ce_only(run_claim_evidence_agent(state, llm))

        self.assertIs(ClaimSummaryOutput, llm.requested_schema)
        self.assertEqual("기사는 수출이 감소했다고 주장합니다.", output["ce_claim_summary"])
        self.assertEqual("왜곡 가능성 높음", output["ce_draft_judgement"])

    def test_llm_failure_falls_back_to_rule_summary(self):
        llm = self.StructuredLLM(RuntimeError("temporary API error"))
        state = make_input_state(
            news_title="고용 증가",
            news_body="고용이 전년보다 증가했다.",
            chart_text="2024년 고용 100만명\n2025년 고용 110만명",
            source_text="출처: 통계청, 단위: 만명",
        )

        output = pick_ce_only(run_claim_evidence_agent(state, llm))

        self.assertIn("고용 증가", output["ce_claim_summary"])

    def test_invalid_structured_output_falls_back(self):
        llm = self.StructuredLLM({"ce_claim_summary": "", "vc_result": "금지"})
        state = make_input_state(news_title="물가 상승", news_body="물가가 올랐다.")

        output = pick_ce_only(run_claim_evidence_agent(state, llm))

        self.assertIn("물가 상승", output["ce_claim_summary"])
        self.assertTrue(all(key.startswith("ce_") for key in output))

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
