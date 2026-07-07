"""first_agent가 읽고 쓰는 최소 state 계약."""

from typing import NotRequired, TypedDict

from ce_agent.schemas.claim_evidence_output import CeJudgement


class ClaimEvidenceState(TypedDict):
    input_news_title: str
    input_news_body: str
    input_chart_image_path: str
    input_chart_text: str
    input_source_text: str

    ce_chart_facts: NotRequired[list[str]]
    ce_claim_summary: NotRequired[str]
    ce_strong_expressions: NotRequired[list[str]]
    ce_risk_flags: NotRequired[list[str]]
    ce_draft_judgement: NotRequired[CeJudgement]
    ce_draft_summary: NotRequired[str]
