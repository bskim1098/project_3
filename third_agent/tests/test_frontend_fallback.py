import unittest

from frontend.streamlit_app import (
    is_vc_fallback_result,
    make_input_state,
    make_temp_ig_state,
    run_claim_evidence,
    run_verdict_critic_graph,
)
from third_agent.vc_agent.nodes.report_merge_node import build_service_report


class FrontendFallbackRegressionTests(unittest.TestCase):
    class BrokenStructuredOutputLLM:
        def with_structured_output(self, _schema):
            raise RuntimeError("structured output unavailable")

    def make_state(self):
        input_state = make_input_state(
            news_title="고용률이 폭증했다",
            news_body="고용률이 2023년 60%에서 2024년 61%로 증가했다.",
            chart_text="2023년 60%, 2024년 61%",
            source_text="통계청, 단위 %",
        )
        ce_state = run_claim_evidence(input_state, llm=None)
        ig_state = make_temp_ig_state("통계청, 단위 %")
        return {**input_state, **ce_state, **ig_state}

    def test_missing_llm_reaches_agent_fallback_and_report_merge(self):
        state = self.make_state()

        vc_result = run_verdict_critic_graph(None, state)
        merged = build_service_report({**state, **vc_result})

        self.assertEqual("검증 제한", vc_result["vc_recommended_judgement"])
        self.assertTrue(is_vc_fallback_result(vc_result))
        self.assertEqual("검증 제한", merged["merge_user_facing_judgement"])
        self.assertIn("merge_final_report", merged)

    def test_normal_limited_result_is_not_mislabeled_as_model_fallback(self):
        result = {
            "vc_recommended_judgement": "검증 제한",
            "vc_revision_reason": "기간과 출처 정보가 부족해 추가 검증이 필요합니다.",
        }

        self.assertFalse(is_vc_fallback_result(result))

    def test_model_setup_failure_is_renderable_as_fallback(self):
        state = self.make_state()

        vc_result = run_verdict_critic_graph(
            self.BrokenStructuredOutputLLM(), state
        )

        self.assertTrue(is_vc_fallback_result(vc_result))
        self.assertEqual("검증 제한", vc_result["vc_recommended_judgement"])


if __name__ == "__main__":
    unittest.main()
