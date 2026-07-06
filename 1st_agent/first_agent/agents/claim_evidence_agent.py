from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from common.state.news_chart_check_state import NewsChartCheckState


# ============================================================
# 1st_agent: 주장-근거 검증 에이전트
# ============================================================
#
# 이 파일의 목적:
# - 뉴스 제목/본문(input_news_title, input_news_body)
# - 차트 텍스트(input_chart_text)
# - 출처/설명(input_source_text)
# 를 읽고,
#
# 3rd_agent가 참고할 수 있는 ce_ 결과를 생성한다.
#
# 중요한 원칙:
# - input_ 변수는 읽기만 한다.
# - ce_ 변수만 작성한다.
# - ig_, vc_, merge_, runtime_ 변수는 절대 작성하지 않는다.
# - 뉴스가 가짜라고 단정하지 않는다.
# - 차트에서 확인할 수 없는 내용은 만들지 않는다.
#
# 현재 버전은 LLM을 붙이기 전에도 동작하는 "규칙 기반 fallback"이다.
# 즉, 완성형 분석기는 아니지만 팀원이 이어받기 좋은 최소 실행 골격이다.
# ============================================================


# ce_draft_judgement에 들어갈 수 있는 값 목록.
# 프롬프트에서 정한 4개 판정만 허용한다.
ALLOWED_CE_JUDGEMENTS = (
    "믿어도 됨",
    "주의 필요",
    "검증 제한",
    "왜곡 가능성 높음",
)


# 기사 제목/본문에서 찾을 강한 표현 목록.
# 이런 표현이 있으면 차트 근거가 충분한지 더 조심해서 봐야 한다.
STRONG_EXPRESSION_KEYWORDS = (
    "폭증",
    "급증",
    "급락",
    "압도적",
    "역대급",
    "완전 회복",
    "최고",
    "최저",
    "최대",
    "최소",
    "때문에",
    "원인",
    "영향",
    "반드시",
    "명백히",
)


# 위험 신호 문구를 한곳에 모아둔다.
# 나중에 팀원이 문구를 수정하거나 추가하기 쉽게 하기 위한 구조다.
RISK_RULES = {
    "missing_chart_text": "차트 텍스트가 부족해 수치 확인이 제한됩니다.",
    "missing_source": "출처 또는 차트 설명이 부족합니다.",
    "causal_claim": "기사에 인과를 단정하는 표현이 있어 주의가 필요합니다.",
    "strong_expression": "기사에 강한 표현이 있어 차트 근거와 비교가 필요합니다.",
    "missing_unit_or_period": "단위, 기간, 비교 기준이 부족할 수 있습니다.",
}


class ClaimEvidenceOutput(BaseModel):
    """
    1st_agent의 최종 출력 스키마.

    이 클래스의 역할:
    - ce_로 시작하는 출력값만 허용한다.
    - ce_draft_judgement는 정해진 4개 판정만 허용한다.
    - 3rd_agent가 읽을 수 있는 형태로 결과를 고정한다.

    model_config = ConfigDict(strict=True)의 의미:
    - 타입을 느슨하게 바꿔서 받아들이지 않는다.
    - 예를 들어 list[str] 자리에 문자열 하나가 들어오는 식의 실수를 줄인다.
    """

    model_config = ConfigDict(strict=True)

    ce_chart_facts: list[str] = Field(
        description="차트에서 확인한 사실 목록"
    )

    ce_claim_summary: str = Field(
        description="기사 제목과 본문의 핵심 주장 요약"
    )

    ce_strong_expressions: list[str] = Field(
        description="기사 제목/본문에서 발견한 강한 표현 목록"
    )

    ce_risk_flags: list[str] = Field(
        description="과장, 인과 단정, 기간 일반화, 출처 부족 등 위험 신호 목록"
    )

    ce_draft_judgement: Literal[
        "믿어도 됨",
        "주의 필요",
        "검증 제한",
        "왜곡 가능성 높음",
    ] = Field(
        description="1차 판정"
    )

    ce_draft_summary: str = Field(
        description="1차 판정 이유"
    )


def _to_text(value: Any) -> str:
    """
    입력값을 안전하게 문자열로 바꾸는 보조 함수.

    필요한 이유:
    - state에서 값이 None으로 들어올 수 있다.
    - 숫자나 다른 타입이 들어올 수도 있다.
    - strip()을 바로 쓰면 None일 때 에러가 난다.

    예:
    None      -> ""
    "  abc "  -> "abc"
    123       -> "123"
    """

    if value is None:
        return ""

    return str(value).strip()


def extract_chart_facts(chart_text: str) -> list[str]:
    """
    차트 텍스트에서 확인 가능한 수치 표현을 뽑는다.

    입력:
    - input_chart_text

    출력:
    - ce_chart_facts에 들어갈 후보 목록

    현재 방식:
    - 정규식으로 숫자, 퍼센트, 명, 건, 원, 년, 월 같은 표현을 찾는다.
    - OCR이나 차트 해석 모델이 아니라, 이미 추출된 chart_text를 대상으로만 동작한다.

    한계:
    - 수치의 의미를 완벽히 이해하지는 못한다.
    - 예: "2024년 58%"를 보고 자동으로 전년 대비 하락이라고 계산하지는 않는다.
    - 다만 팀원에게 넘기기 위한 최소 기반으로는 충분하다.
    """

    chart_text = _to_text(chart_text)

    # 차트 텍스트 자체가 없으면, 확인 가능한 사실도 없다.
    if not chart_text:
        return []

    # 숫자와 단위를 함께 찾기 위한 단순 정규식.
    # 예:
    # - 2023년
    # - 58%
    # - 1,200명
    # - 3.5배
    # - 10억원
    number_patterns = re.findall(
        r"[\w가-힣%％.,+-]*\s*\d[\d,]*(?:\.\d+)?\s*(?:%|％|명|건|원|억원|조원|배|년|월|일)?",
        chart_text,
    )

    facts: list[str] = []

    # 너무 많은 값을 넣으면 3rd_agent가 읽기 부담스러우므로 상위 8개만 사용한다.
    for item in number_patterns[:8]:
        cleaned = item.strip()

        # 빈 문자열과 중복값은 제외한다.
        if cleaned and cleaned not in facts:
            facts.append(f"차트에서 '{cleaned}' 값을 확인했습니다.")

    # chart_text는 있는데 숫자 패턴이 안 잡힌 경우.
    # 이 경우도 "검증 제한"으로 갈 가능성이 높다.
    if not facts:
        facts.append("차트 텍스트는 있으나 명확한 수치 표현을 찾지 못했습니다.")

    return facts


def summarize_claim(title: str, body: str) -> str:
    """
    기사 제목과 본문을 바탕으로 핵심 주장을 간단히 요약한다.

    입력:
    - input_news_title
    - input_news_body

    출력:
    - ce_claim_summary

    현재 방식:
    - LLM 요약이 아니라 단순 문자열 요약이다.
    - 제목을 우선 사용하고, 본문 앞부분을 잘라 붙인다.

    나중에 개선할 부분:
    - LLM을 붙이면 여기서 진짜 핵심 주장 추출을 하도록 바꾸면 된다.
    """

    title = _to_text(title)
    body = _to_text(body)

    if title and body:
        # 본문 전체를 넣으면 너무 길어질 수 있으므로 앞부분만 사용한다.
        short_body = body[:120].replace("\n", " ")
        return f"제목은 '{title}'이며, 본문은 '{short_body}' 내용을 중심으로 주장합니다."

    if title:
        return f"제목은 '{title}'입니다."

    if body:
        short_body = body[:150].replace("\n", " ")
        return f"본문은 '{short_body}' 내용을 중심으로 주장합니다."

    return "기사 제목과 본문 내용이 부족해 핵심 주장을 요약하기 어렵습니다."


def extract_strong_expressions(title: str, body: str) -> list[str]:
    """
    기사 제목/본문에서 강한 표현을 찾는다.

    입력:
    - input_news_title
    - input_news_body

    출력:
    - ce_strong_expressions

    강한 표현 예:
    - 폭증
    - 급락
    - 압도적
    - 역대급
    - 완전 회복
    - 때문에
    - 원인

    이런 표현이 있으면:
    - 차트가 단순 수치만 보여주는지
    - 기사에서 과장하거나 인과를 단정하는지
    를 추가로 봐야 한다.
    """

    text = f"{_to_text(title)}\n{_to_text(body)}"
    found: list[str] = []

    for keyword in STRONG_EXPRESSION_KEYWORDS:
        if keyword in text and keyword not in found:
            found.append(keyword)

    return found


def detect_risk_flags(
    title: str,
    body: str,
    chart_text: str,
    source_text: str,
    strong_expressions: list[str],
) -> list[str]:
    """
    기사와 차트 사이의 위험 신호를 찾는다.

    입력:
    - 제목
    - 본문
    - 차트 텍스트
    - 출처/설명
    - 강한 표현 목록

    출력:
    - ce_risk_flags

    현재 감지하는 위험 신호:
    1. 차트 텍스트 부족
    2. 출처/설명 부족
    3. 강한 표현 존재
    4. 인과 단정 표현 존재
    5. 단위/기간/기준 부족 가능성
    """

    flags: list[str] = []

    title = _to_text(title)
    body = _to_text(body)
    chart_text = _to_text(chart_text)
    source_text = _to_text(source_text)

    # 차트 텍스트가 없으면 수치 검증 자체가 어렵다.
    if not chart_text:
        flags.append(RISK_RULES["missing_chart_text"])

    # 출처나 차트 설명이 없으면 신뢰도 판단이 어렵다.
    if not source_text:
        flags.append(RISK_RULES["missing_source"])

    # 강한 표현이 있으면 과장 가능성을 표시한다.
    if strong_expressions:
        flags.append(RISK_RULES["strong_expression"])

    # 인과 단정 표현을 찾는다.
    # 차트는 보통 상관관계나 추세를 보여줄 뿐,
    # 원인을 직접 증명하지 못하는 경우가 많다.
    causal_keywords = ("때문에", "원인", "영향으로", "결과로", "탓")
    if any(keyword in f"{title}\n{body}" for keyword in causal_keywords):
        flags.append(RISK_RULES["causal_claim"])

    # 차트 텍스트에 단위, 기간, 기준 관련 단서가 너무 부족한 경우.
    # 단순한 규칙이지만 "검증 제한" 판단에 도움이 된다.
    metadata_keywords = ("단위", "기간", "출처", "기준", "년", "월", "%", "명", "건")
    if chart_text and not any(keyword in chart_text for keyword in metadata_keywords):
        flags.append(RISK_RULES["missing_unit_or_period"])

    return flags


def decide_draft_judgement(
    chart_facts: list[str],
    strong_expressions: list[str],
    risk_flags: list[str],
) -> Literal["믿어도 됨", "주의 필요", "검증 제한", "왜곡 가능성 높음"]:
    """
    ce_draft_judgement를 결정한다.

    입력:
    - 차트에서 확인한 사실
    - 강한 표현 목록
    - 위험 신호 목록

    출력:
    - 믿어도 됨
    - 주의 필요
    - 검증 제한
    - 왜곡 가능성 높음

    현재 버전의 판단 원칙:
    - 정보가 부족하면 검증 제한
    - 강한 표현이나 위험 신호가 있으면 주의 필요
    - 별다른 위험 신호가 없으면 믿어도 됨

    왜곡 가능성 높음에 대해서:
    - 지금 규칙 기반 버전에서는 거의 사용하지 않는다.
    - 이유는 "명확히 어긋남"을 자동 판정하려면 수치 방향 비교 로직이 더 필요하기 때문이다.
    - 괜히 강하게 판정하면 3rd_agent의 보수적 검토 원칙과 충돌할 수 있다.
    """

    # 차트에서 확인한 사실이 없으면 판단이 어렵다.
    if not chart_facts:
        return "검증 제한"

    # 위험 신호 중 "부족", "제한"이 들어가면 정보 부족으로 본다.
    # 예: 차트 텍스트 부족, 출처 부족, 단위/기간 부족
    if any("부족" in flag or "제한" in flag for flag in risk_flags):
        return "검증 제한"

    # 강한 표현이 있거나 위험 신호가 있으면 보수적으로 "주의 필요".
    if strong_expressions or risk_flags:
        return "주의 필요"

    # 수치가 있고, 강한 표현도 없고, 위험 신호도 없으면 대체로 무난한 상태로 본다.
    return "믿어도 됨"


def build_draft_summary(
    judgement: str,
    chart_facts: list[str],
    strong_expressions: list[str],
    risk_flags: list[str],
) -> str:
    """
    ce_draft_summary를 만든다.

    입력:
    - 1차 판정
    - 차트 사실 목록
    - 강한 표현 목록
    - 위험 신호 목록

    출력:
    - 사람이 읽을 수 있는 1차 판정 이유

    주의:
    - 이 함수도 뉴스가 가짜라고 단정하지 않는다.
    - 가능한 한 "주의", "검증 제한", "가능성" 중심으로 표현한다.
    """

    if judgement == "검증 제한":
        return (
            "차트 수치, 출처, 기간, 단위 또는 비교 기준이 부족해 "
            "기사 주장을 충분히 검증하기 어렵습니다."
        )

    if judgement == "주의 필요":
        return (
            "차트에서 일부 근거는 확인되지만, 기사에 강한 표현이나 "
            "인과 단정 가능성이 있어 주의가 필요합니다."
        )

    if judgement == "왜곡 가능성 높음":
        return (
            "차트에서 확인되는 내용과 기사 주장이 명확히 어긋날 가능성이 있습니다."
        )

    return "차트에서 확인되는 수치가 기사 주장과 대체로 어긋나지 않습니다."


def run_claim_evidence_agent(state: NewsChartCheckState) -> NewsChartCheckState:
    """
    1st_agent의 메인 실행 함수.

    입력:
    - NewsChartCheckState

    읽는 값:
    - input_news_title
    - input_news_body
    - input_chart_text
    - input_source_text

    쓰는 값:
    - ce_chart_facts
    - ce_claim_summary
    - ce_strong_expressions
    - ce_risk_flags
    - ce_draft_judgement
    - ce_draft_summary

    반환:
    - ce_ 필드가 추가된 NewsChartCheckState

    주의:
    - input_ 값은 읽기만 한다.
    - ig_, vc_, merge_, runtime_ 값은 작성하지 않는다.
    """

    # input_ 값 읽기
    title = _to_text(state.get("input_news_title"))
    body = _to_text(state.get("input_news_body"))
    chart_text = _to_text(state.get("input_chart_text"))
    source_text = _to_text(state.get("input_source_text"))

    # ce_ 결과 생성
    chart_facts = extract_chart_facts(chart_text)
    claim_summary = summarize_claim(title, body)
    strong_expressions = extract_strong_expressions(title, body)

    risk_flags = detect_risk_flags(
        title=title,
        body=body,
        chart_text=chart_text,
        source_text=source_text,
        strong_expressions=strong_expressions,
    )

    draft_judgement = decide_draft_judgement(
        chart_facts=chart_facts,
        strong_expressions=strong_expressions,
        risk_flags=risk_flags,
    )

    draft_summary = build_draft_summary(
        judgement=draft_judgement,
        chart_facts=chart_facts,
        strong_expressions=strong_expressions,
        risk_flags=risk_flags,
    )

    # Pydantic으로 ce_ 출력값 검증
    output = ClaimEvidenceOutput(
        ce_chart_facts=chart_facts,
        ce_claim_summary=claim_summary,
        ce_strong_expressions=strong_expressions,
        ce_risk_flags=risk_flags,
        ce_draft_judgement=draft_judgement,
        ce_draft_summary=draft_summary,
    )

    # 기존 state를 복사한 뒤 ce_ 결과만 추가한다.
    # 이렇게 해야 input_ 값이나 다른 에이전트 결과를 지우지 않는다.
    return {
        **state,
        **output.model_dump(),
    }


def pick_ce_only(state: dict[str, Any]) -> dict[str, Any]:
    """
    state에서 ce_로 시작하는 값만 골라낸다.

    용도:
    - 테스트할 때 1st_agent가 ce_만 작성했는지 확인할 수 있다.
    - supervisor나 merge 단계에서 ce_ 결과만 따로 넘기고 싶을 때 쓸 수 있다.

    예:
    {
        "input_news_title": "...",
        "ce_chart_facts": [...],
        "vc_recommended_judgement": "..."
    }

    위 state가 들어오면 결과는:

    {
        "ce_chart_facts": [...]
    }
    """

    return {
        key: value
        for key, value in state.items()
        if key.startswith("ce_")
    }