import unittest

from pydantic import ValidationError

from first_agent.guardrails.claim_evidence_guardrails import (
    validate_ce_output,
    validate_state_update,
)


def valid_output():
    return {
        "ce_chart_facts": ["2025년 12%"],
        "ce_claim_summary": "기사는 증가를 주장합니다.",
        "ce_strong_expressions": [],
        "ce_risk_flags": [],
        "ce_draft_judgement": "믿어도 됨",
        "ce_draft_summary": "차트와 대체로 일치합니다.",
    }


class ClaimEvidenceGuardrailTests(unittest.TestCase):
    def test_rejects_non_ce_output_field(self):
        output = valid_output()
        output["vc_revision_needed"] = True
        with self.assertRaises(ValidationError):
            validate_ce_output(output)

    def test_rejects_unsupported_judgement(self):
        output = valid_output()
        output["ce_draft_judgement"] = "가짜 뉴스"
        with self.assertRaises(ValidationError):
            validate_ce_output(output)

    def test_rejects_unsafe_assertion(self):
        output = valid_output()
        output["ce_draft_summary"] = "이 기사는 조작입니다."
        with self.assertRaises(ValueError):
            validate_ce_output(output)

    def test_rejects_non_ce_state_mutation(self):
        with self.assertRaises(ValueError):
            validate_state_update(
                {"input_news_title": "원본"}, {"input_news_title": "변경"}
            )


if __name__ == "__main__":
    unittest.main()
