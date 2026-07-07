"""비교 결과로 보수적인 1차 판정과 이유를 생성한다."""

from ce_agent.nodes.claim_chart_compare_node import ComparisonStatus
from ce_agent.schemas.claim_evidence_output import CeJudgement


def decide_draft_judgement(
    chart_facts: list[str],
    strong_expressions: list[str],
    risk_flags: list[str],
    comparison_status: ComparisonStatus = "limited",
) -> CeJudgement:
    if not chart_facts:
        return "검증 제한"
    information_gap = any(
        marker in flag for flag in risk_flags for marker in ("부족", "제한")
    )
    if information_gap:
        return "검증 제한"
    if comparison_status == "contradicted":
        return "왜곡 가능성 높음"
    if comparison_status == "limited":
        return "검증 제한"
    if comparison_status == "partial" or strong_expressions or risk_flags:
        return "주의 필요"
    return "믿어도 됨"


def build_draft_summary(judgement: CeJudgement, comparison_summary: str = "") -> str:
    if judgement == "검증 제한":
        return "차트 수치, 출처, 기간, 단위 또는 비교 기준이 부족해 기사 주장을 충분히 검증하기 어렵습니다."
    if judgement == "주의 필요":
        return comparison_summary or "일부 근거는 확인되지만 강한 표현이나 인과 단정 가능성이 있어 주의가 필요합니다."
    if judgement == "왜곡 가능성 높음":
        return comparison_summary or "차트에서 확인되는 내용과 기사 주장이 명확히 어긋날 가능성이 있습니다."
    return comparison_summary or "차트에서 확인되는 수치가 기사 주장과 대체로 어긋나지 않습니다."
