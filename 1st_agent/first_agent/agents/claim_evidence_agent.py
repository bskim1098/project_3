"""GraphRAG 없이 동작하는 규칙 기반 주장-차트 검증 에이전트."""

from __future__ import annotations

from typing import Any, Mapping, cast

from common.state.news_chart_check_state import NewsChartCheckState
from first_agent.guardrails.claim_evidence_guardrails import (
    validate_ce_output,
    validate_state_update,
)
from first_agent.nodes.chart_extraction_node import extract_chart_facts
from first_agent.nodes.claim_chart_compare_node import compare_claim_to_chart
from first_agent.nodes.claim_extraction_node import summarize_claim
from first_agent.nodes.draft_judgement_node import (
    build_draft_summary,
    decide_draft_judgement,
)
from first_agent.nodes.strong_expression_node import (
    RISK_RULES,
    STRONG_EXPRESSION_KEYWORDS,
    detect_risk_flags,
    extract_strong_expressions,
)
from first_agent.schemas.claim_evidence_output import (
    ALLOWED_CE_JUDGEMENTS,
    ClaimEvidenceOutput,
)


def _to_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def run_claim_evidence_agent(state: NewsChartCheckState) -> NewsChartCheckState:
    """input_을 읽고 검증된 ce_ 결과만 state에 추가한다."""
    title = _to_text(state.get("input_news_title"))
    body = _to_text(state.get("input_news_body"))
    chart_text = _to_text(state.get("input_chart_text"))
    source_text = _to_text(state.get("input_source_text"))

    comparison = compare_claim_to_chart(title, body, chart_text)
    chart_facts = comparison.chart_facts or extract_chart_facts(chart_text)
    strong_expressions = extract_strong_expressions(title, body)
    risk_flags = detect_risk_flags(
        title, body, chart_text, source_text, strong_expressions
    )
    for flag in comparison.risk_flags:
        if flag not in risk_flags:
            risk_flags.append(flag)

    judgement = decide_draft_judgement(
        chart_facts, strong_expressions, risk_flags, comparison.status
    )
    output = validate_ce_output(
        {
            "ce_chart_facts": chart_facts,
            "ce_claim_summary": summarize_claim(title, body),
            "ce_strong_expressions": strong_expressions,
            "ce_risk_flags": risk_flags,
            "ce_draft_judgement": judgement,
            "ce_draft_summary": build_draft_summary(judgement, comparison.summary),
        }
    )
    result = {**state, **output.model_dump()}
    validate_state_update(state, result)
    return cast(NewsChartCheckState, result)


def pick_ce_only(state: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in state.items() if key.startswith("ce_")}


__all__ = [
    "ALLOWED_CE_JUDGEMENTS",
    "ClaimEvidenceOutput",
    "RISK_RULES",
    "STRONG_EXPRESSION_KEYWORDS",
    "build_draft_summary",
    "decide_draft_judgement",
    "detect_risk_flags",
    "extract_chart_facts",
    "extract_strong_expressions",
    "pick_ce_only",
    "run_claim_evidence_agent",
    "summarize_claim",
]
