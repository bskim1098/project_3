"""1st_agent가 작성할 수 있는 structured output 계약."""

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


CeJudgement: TypeAlias = Literal[
    "믿어도 됨",
    "주의 필요",
    "검증 제한",
    "왜곡 가능성 높음",
]

ALLOWED_CE_JUDGEMENTS: tuple[str, ...] = (
    "믿어도 됨",
    "주의 필요",
    "검증 제한",
    "왜곡 가능성 높음",
)


class ClaimEvidenceOutput(BaseModel):
    """ce_ 필드만 허용하는 엄격한 1st_agent 출력."""

    model_config = ConfigDict(strict=True, extra="forbid")

    ce_chart_facts: list[str] = Field(description="차트에서 확인한 사실 목록")
    ce_claim_summary: str = Field(description="기사 제목과 본문의 핵심 주장 요약")
    ce_strong_expressions: list[str] = Field(description="기사에서 발견한 강한 표현")
    ce_risk_flags: list[str] = Field(description="과장·인과·기간·근거 관련 위험 신호")
    ce_draft_judgement: CeJudgement = Field(description="보수적인 1차 판정")
    ce_draft_summary: str = Field(description="1차 판정 이유")
