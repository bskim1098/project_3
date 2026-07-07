"""URL/HTML 자동 입력의 사용자용 처리 상태를 구성한다.

이 상태는 뉴스 진위나 최종 판정이 아니라 프론트 전처리 결과만 설명한다.
LangGraph state에는 추가하지 않고 Streamlit session_state에서만 사용한다.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping, TypedDict


IngestionStatus = Literal[
    "success",
    "uncertain",
    "access_restricted",
    "fetch_failed",
]


class IngestionOutcome(TypedDict):
    status: IngestionStatus
    message: str
    prefill: dict[str, str]
    summary: dict[str, Any]


def classify_extraction_outcome(
    prefill: Mapping[str, object],
    summary: Mapping[str, Any],
) -> IngestionOutcome:
    """확보한 HTML의 추출 품질을 성공 또는 불확실로 분류한다."""
    normalized_prefill = {str(key): str(value) for key, value in prefill.items()}
    normalized_summary = dict(summary)
    title = normalized_prefill.get("news_title", "").strip()
    body = normalized_prefill.get("news_body", "").strip()
    body_count = int(normalized_summary.get("body_paragraph_count", 0) or 0)
    image_count = int(normalized_summary.get("image_candidate_count", 0) or 0)
    confidence = str(normalized_summary.get("extraction_confidence", "낮음"))

    # 이미지가 없는 텍스트 기사도 있으므로 이미지·출처 누락은 성공 여부를
    # 낮추지 않는다. 제목과 유효 본문, 적응형 후보의 높은 신뢰도만 사용한다.
    is_success = bool(
        title
        and body
        and body_count >= 1
        and len(body) >= 40
        and confidence == "높음"
    )
    if is_success:
        return {
            "status": "success",
            "message": (
                f"자동 입력 성공 · 기사 본문 {body_count}개 문단과 "
                f"이미지 후보 {image_count}개를 확인했습니다."
            ),
            "prefill": normalized_prefill,
            "summary": normalized_summary,
        }

    return {
        "status": "uncertain",
        "message": (
            "자동 입력 결과를 확인해주세요 · 본문 후보 간 차이가 있거나 "
            "추출 내용이 부족합니다."
        ),
        "prefill": normalized_prefill,
        "summary": normalized_summary,
    }


def build_failure_outcome(
    status: Literal["access_restricted", "fetch_failed"],
    message: str,
) -> IngestionOutcome:
    """HTML을 확보하지 못한 요청도 동일한 프론트 계약으로 종료한다."""
    return {
        "status": status,
        "message": message,
        "prefill": {},
        "summary": {},
    }
