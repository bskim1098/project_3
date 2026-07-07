"""LangGraph로 구성한 주장-차트 검증 에이전트.

LLM은 기사 주장 요약만 보조한다. 차트 사실, 위험 신호, 수치 비교와 판정은
결정론적 규칙이 담당하며 LLM 실패 시 기존 규칙 기반 요약으로 복귀한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph

from common.state.news_chart_check_state import NewsChartCheckState
from ce_agent.guardrails.claim_evidence_guardrails import (
    validate_ce_output,
    validate_state_update,
)
from ce_agent.nodes.chart_extraction_node import extract_chart_facts
from ce_agent.nodes.claim_chart_compare_node import compare_claim_to_chart
from ce_agent.nodes.claim_extraction_node import summarize_claim
from ce_agent.nodes.draft_judgement_node import (
    build_draft_summary,
    decide_draft_judgement,
)
from ce_agent.nodes.strong_expression_node import (
    RISK_RULES,
    STRONG_EXPRESSION_KEYWORDS,
    detect_risk_flags,
    extract_strong_expressions,
)
from ce_agent.schemas.claim_evidence_output import (
    ALLOWED_CE_JUDGEMENTS,
    ClaimEvidenceOutput,
    ClaimSummaryOutput,
)


def _to_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def load_claim_extraction_prompt() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "claim_extraction_prompt.md"
    return prompt_path.read_text(encoding="utf-8")


def build_claim_input(state: NewsChartCheckState) -> str:
    """LLM에 기사 입력만 전달하고 차트·다른 에이전트 결과는 전달하지 않는다."""
    return (
        "[기사 제목]\n"
        f"{_to_text(state.get('input_news_title'))}\n\n"
        "[기사 본문]\n"
        f"{_to_text(state.get('input_news_body'))}"
    )


def chart_extraction_graph_node(state: NewsChartCheckState) -> dict[str, Any]:
    chart_text = _to_text(state.get("input_chart_text"))
    comparison = compare_claim_to_chart(
        _to_text(state.get("input_news_title")),
        _to_text(state.get("input_news_body")),
        chart_text,
    )
    return {"ce_chart_facts": comparison.chart_facts or extract_chart_facts(chart_text)}


def make_claim_extraction_graph_node(llm: BaseChatModel | Any | None):
    """structured output 실패를 규칙 기반 요약으로 흡수하는 노드를 만든다."""
    prompt = ChatPromptTemplate.from_messages(
        [("system", load_claim_extraction_prompt()), ("human", "{article_input}")]
    )

    def claim_extraction_graph_node(state: NewsChartCheckState) -> dict[str, Any]:
        fallback = summarize_claim(
            _to_text(state.get("input_news_title")),
            _to_text(state.get("input_news_body")),
        )
        if llm is None:
            return {"ce_claim_summary": fallback}
        try:
            structured_llm = llm.with_structured_output(ClaimSummaryOutput)
            messages = prompt.invoke({"article_input": build_claim_input(state)})
            result = structured_llm.invoke(messages)
            validated = ClaimSummaryOutput.model_validate(result)
            return {"ce_claim_summary": validated.ce_claim_summary.strip()}
        except Exception:
            return {"ce_claim_summary": fallback}

    return claim_extraction_graph_node


def compare_and_judge_graph_node(state: NewsChartCheckState) -> dict[str, Any]:
    title = _to_text(state.get("input_news_title"))
    body = _to_text(state.get("input_news_body"))
    chart_text = _to_text(state.get("input_chart_text"))
    source_text = _to_text(state.get("input_source_text"))
    chart_facts = list(state.get("ce_chart_facts", []))
    comparison = compare_claim_to_chart(title, body, chart_text)
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
    return {
        "ce_strong_expressions": strong_expressions,
        "ce_risk_flags": risk_flags,
        "ce_draft_judgement": judgement,
        "ce_draft_summary": build_draft_summary(judgement, comparison.summary),
    }


def guardrail_graph_node(state: NewsChartCheckState) -> dict[str, Any]:
    output = validate_ce_output(
        {key: value for key, value in state.items() if key.startswith("ce_")}
    )
    return output.model_dump()


def build_claim_evidence_graph(llm: BaseChatModel | Any | None = None):
    """규칙 기반 fallback을 항상 포함하는 컴파일된 LangGraph를 반환한다."""
    graph = StateGraph(NewsChartCheckState)
    graph.add_node("chart_extraction", chart_extraction_graph_node)
    graph.add_node("claim_extraction", make_claim_extraction_graph_node(llm))
    graph.add_node("compare_and_judge", compare_and_judge_graph_node)
    graph.add_node("guardrail", guardrail_graph_node)
    graph.add_edge(START, "chart_extraction")
    graph.add_edge("chart_extraction", "claim_extraction")
    graph.add_edge("claim_extraction", "compare_and_judge")
    graph.add_edge("compare_and_judge", "guardrail")
    graph.add_edge("guardrail", END)
    return graph.compile()


def run_claim_evidence_agent(
    state: NewsChartCheckState,
    llm: BaseChatModel | Any | None = None,
) -> NewsChartCheckState:
    result = cast(NewsChartCheckState, build_claim_evidence_graph(llm).invoke(state))
    validate_state_update(state, result)
    validate_ce_output(pick_ce_only(result))
    return result


def pick_ce_only(state: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in state.items() if key.startswith("ce_")}


__all__ = [
    "ALLOWED_CE_JUDGEMENTS",
    "ClaimEvidenceOutput",
    "ClaimSummaryOutput",
    "RISK_RULES",
    "STRONG_EXPRESSION_KEYWORDS",
    "build_claim_evidence_graph",
    "build_claim_input",
    "pick_ce_only",
    "run_claim_evidence_agent",
]
