import unittest

from vc_agent.agents.verdict_critic_agent import apply_vc_guardrails


class VerdictCriticGuardrailTests(unittest.TestCase):
    def make_output(self, **overrides):
        output = {
            "vc_recommended_judgement": "주의 필요",
            "vc_unsafe_expressions": [],
            "vc_revision_needed": False,
            "vc_revision_reason": "기사 표현의 강도를 근거 범위에 맞춰 검토했습니다.",
            "vc_safe_expression": "차트에서 일부 근거가 확인되지만 추가 검증이 필요합니다.",
            "vc_critic_notes": "판정과 근거의 강도가 서로 부합하는지 확인했습니다.",
        }
        output.update(overrides)
        return output

    def test_dangerous_safe_expression_is_detected_and_removed(self):
        result = apply_vc_guardrails(
            self.make_output(vc_safe_expression="가짜 뉴스입니다."), {}
        )
        self.assertIn("가짜 뉴스", result["vc_unsafe_expressions"])
        self.assertTrue(result["vc_revision_needed"])
        self.assertNotIn("가짜 뉴스", result["vc_safe_expression"])

    def test_extended_dangerous_expression_is_detected_and_removed(self):
        result = apply_vc_guardrails(
            self.make_output(vc_safe_expression="통계 조작으로 보입니다."), {}
        )
        self.assertIn("통계 조작", result["vc_unsafe_expressions"])
        self.assertTrue(result["vc_revision_needed"])
        self.assertNotIn("조작", result["vc_safe_expression"])

    def test_weak_explanation_fields_are_expanded(self):
        result = apply_vc_guardrails(
            self.make_output(
                vc_revision_reason="예",
                vc_safe_expression="없음",
                vc_critic_notes="수정 필요",
            ),
            {},
        )
        self.assertNotEqual("예", result["vc_revision_reason"])
        self.assertNotEqual("없음", result["vc_safe_expression"])
        self.assertNotEqual("수정 필요", result["vc_critic_notes"])

    def test_unknown_judgement_falls_back(self):
        result = apply_vc_guardrails(
            self.make_output(vc_recommended_judgement="판단 불가"), {}
        )
        self.assertEqual("검증 제한", result["vc_recommended_judgement"])
        self.assertTrue(result["vc_revision_needed"])

    def test_normal_output_is_unchanged(self):
        output = self.make_output()
        self.assertEqual(output, apply_vc_guardrails(output, {}))


if __name__ == "__main__":
    unittest.main()
