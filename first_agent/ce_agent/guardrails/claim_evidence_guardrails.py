"""first_agent 출력의 namespace, 스키마, 표현 안전성을 검증한다."""

from collections.abc import Mapping
from typing import Any

from first_agent.ce_agent.schemas.claim_evidence_output import ClaimEvidenceOutput


UNSAFE_ASSERTIONS = (
    "가짜 뉴스", "조작", "사기", "완전히 틀림", "명백한 허위", "절대 믿으면 안 됨",
)


def validate_ce_output(output: Mapping[str, Any]) -> ClaimEvidenceOutput:
    """필드·타입·판정값과 위험한 단정 표현을 검증한다."""
    model = ClaimEvidenceOutput.model_validate(dict(output))
    generated_text = "\n".join(
        [model.ce_claim_summary, model.ce_draft_summary, *model.ce_risk_flags]
    )
    used = [expression for expression in UNSAFE_ASSERTIONS if expression in generated_text]
    if used:
        raise ValueError(f"first_agent 출력에 허용되지 않은 단정 표현이 있습니다: {used}")
    return model


def validate_state_update(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> None:
    """기존 비-ce_ 값을 변경하거나 새 비-ce_ 값을 작성하지 않았는지 확인한다."""
    for key, value in after.items():
        if not key.startswith("ce_") and (key not in before or before[key] != value):
            raise ValueError(f"first_agent가 작성할 수 없는 필드입니다: {key}")
    missing = [key for key in before if key not in after]
    if missing:
        raise ValueError(f"first_agent가 기존 state 필드를 제거했습니다: {missing}")
