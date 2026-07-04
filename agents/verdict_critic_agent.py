# agents/verdict_critic_agent.py

"""
verdict_critic_agent.py

역할:
- claim_evidence_agent.py가 만든 ce_ 결과
- info_gap_agent.py가 만든 ig_ 결과
- 원본 input_ 정보

위 값들을 읽고,
최종 판정이 너무 강하게 단정되지 않았는지 검토한다.

중요:
- 이 파일은 vc_ 로 시작하는 변수만 작성해야 한다.
- input_, ce_, ig_ 값은 읽기만 한다.
- merge_, runtime_ 값도 작성하지 않는다.
"""

from __future__ import annotations

from pathlib import Path


from typing import Any

from pydantic import BaseModel, Field, ConfigDict
## ConfigDict : “모델 설정값”을 담는 도구(검사 규칙 묶음)
## BaseModel이 정의한 클래스의 데이터 구조를 어떤 규칙으로 검사하고 처리할지 정하는 설정을 저장한다.

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, START, END

# 프로젝트의 전체 State 타입을 가져온다.
# state/news_chart_check_state.py에 정의되어 있다.
from state.news_chart_check_state import NewsChartCheckState


# ============================================================
# 허용되는 최종 판정값
# ============================================================

# vc_에이전트가 추천할 수 있는 최종 판정은 반드시 아래 4개 중 하나여야 한다.
# 프롬프트 파일에 있는 규칙을 코드에서도 한 번 더 고정하는 것이다.
ALLOWED_JUDGEMENTS = {
    "대체로 뒷받침됨",
    "주의 필요",
    "검증 제한",
    "왜곡 가능성 높음",
}


# ============================================================
# 위험 표현 목록
# ============================================================

# 최종 사용자에게 그대로 보여주면 너무 강하게 단정하는 표현들이다.
# LLM이 실수로 이런 말을 생성했는지 후처리에서 검사한다.
UNSAFE_EXPRESSIONS = [
    "가짜 뉴스",
    "조작",
    "거짓",
    "사기",
    "완전히 틀림",
    "명백한 허위",
    "절대 믿으면 안 됨",
]


# 위험 표현을 더 안전한 표현으로 바꾸기 위한 매핑이다.
# 실제 출력에서는 이 표현들을 참고해서 vc_safe_expression을 만든다.
SAFE_EXPRESSION_MAP = {
    "가짜 뉴스": "주의가 필요한 주장",
    "조작": "왜곡 가능성",
    "거짓": "현재 근거만으로는 뒷받침하기 어려운 주장",
    "사기": "추가 검증이 필요한 주장",
    "완전히 틀림": "근거와 차이가 있을 가능성이 있는 주장",
    "명백한 허위": "현재 근거만으로는 확인하기 어려운 주장",
    "절대 믿으면 안 됨": "추가 검증이 필요한 주장",
}


# ============================================================
# LLM 출력 스키마
# ============================================================

class VerdictCriticOutput(BaseModel):
## 애이전트의 출력 형식을 이하와 같이 규정한다.
    """
    LLM이 반드시 이 구조로 답하게 만드는 출력 스키마.

    왜 필요한가?
    - LLM에게 그냥 "JSON으로 답해"라고 하면 형식이 깨질 수 있다.
    - Pydantic 스키마를 쓰면 필요한 필드가 빠지는 일을 줄일 수 있다.
    - 이후 report_merge_node.py에서 결과를 안정적으로 사용할 수 있다.
    """

    # ------------------------------------------------------------
    # Pydantic 엄격 검증 설정
    # ------------------------------------------------------------
    # 기본 Pydantic은 경우에 따라 타입을 자동 변환하려고 한다.
    #
    # 예:
    # - "false" 같은 문자열을 bool False로 바꾸려고 할 수 있음
    # - 숫자를 문자열로 바꾸려고 할 수 있음
    #
    # 하지만 이 에이전트는 최종 판정 검토용이므로,
    # 잘못된 타입은 억지로 고치기보다 fallback으로 보내는 편이 안전하다.

    
    model_config = ConfigDict(strict=True)
    ## ConfigDict 모듈로 해당 Pydantic 모델 전체를 “엄격 검사 모드”로 설정(strict=True)한다

    # 일부러 Literal이 아니라 str로 받는다.
    # LLM이 "대체로 맞음" 같은 허용되지 않은 판정명을 내더라도
    # 스키마 단계에서 바로 실패시키지 않고,
    # apply_vc_guardrails()에서 "검증 제한"으로 보정하기 위해서다.

    vc_recommended_judgement: str = Field(
        description=(
            "추천 최종 판정. "
            "대체로 뒷받침됨, 주의 필요, 검증 제한, 왜곡 가능성 높음 중 하나여야 한다."
        )
    )
    vc_unsafe_expressions: list[str] = Field(
        default_factory=list,
        description="초안이나 검토 과정에서 발견된 위험한 표현 목록"
    )

    vc_revision_needed: bool = Field(
        description="최종 판정 또는 문구 수정이 필요한지 여부"
    )

    vc_revision_reason: str = Field(
        description="수정이 필요한 이유"
    )

    vc_safe_expression: str = Field(
        description="더 안전하게 바꾼 표현"
    )

    vc_critic_notes: str = Field(
        description="최종판정 검토 메모"
    )

# ============================================================
# LLM 결과 정규화 함수
# ============================================================

def normalize_llm_result(result: Any) -> dict[str, Any]:
## LLM이 출력하는 구조화된 결과(result)를
## model_validate로 검증하고 (model_validate : Pydantic 모델(VerdictCriticOutput) 형식에 맞는지 검증)
## model_dump 메서드로 검증한 결과(result)를 일반 Python 딕셔너리로 꺼내기

    """
    LLM structured output 결과를 항상 같은 방식으로 검증하고 dict로 변환한다.

    왜 필요한가?
    - 이전 코드에서는 result가 Pydantic 객체면 model_dump()를 사용하고,
      result가 dict면 그대로 raw_output으로 사용했다.
    - 하지만 dict를 그대로 믿으면 잘못된 타입이 통과할 수 있다.

    예:
    {
        "vc_revision_needed": "false",   # 문자열이라 잘못된 타입
        "vc_unsafe_expressions": [{}]    # list[str]가 아니라 list[dict]
    }

    이런 값이 후처리로 넘어가면 ordered_unique() 등에서 오류가 날 수 있다.

    해결:
    - result가 Pydantic 객체든 dict든 상관없이
      VerdictCriticOutput.model_validate(result)를 반드시 통과시킨다.
    - 검증에 실패하면 예외가 발생한다.
    - 그 예외는 verdict_critic_node()의 try/except에서 잡혀 fallback으로 처리된다.
    """

    # Pydantic 모델인지 dict인지 직접 분기하지 않는다.
    # model_validate()가 가능한 입력을 검증해서 VerdictCriticOutput 객체로 바꿔준다.
    validated_result = VerdictCriticOutput.model_validate(result)

    # 이후 후처리 함수 apply_vc_guardrails()가 다루기 쉽도록 dict로 변환한다.
    return validated_result.model_dump()

# ============================================================
# LLM 실패 시 사용할 안전한 기본 출력
# ============================================================

def make_safe_fallback_output(reason: str) -> dict[str, Any]:
## LLM 호출이 실패해서 검증이 제한된다는 결과를 출력하는 함수
## 오류 발생으로 인한 검증 제한 이라는 내용의 이유를 받아
## 출력 형식 중 vc_revision_reason의 값으로 저장하고 결과 출력
    """
    LLM 호출 실패 또는 구조화 출력 실패 시 사용할 안전한 기본 결과.

    왜 필요한가?
    - LLM API 오류가 날 수 있다.
    - structured output 파싱이 실패할 수 있다.
    - 모델이 예상과 다른 형식으로 답할 수 있다.

    이때 노드 전체가 실패하면 LangGraph 실행이 중단된다.
    따라서 가장 보수적인 판정인 '검증 제한'으로 안전하게 대체한다.
    """

    return {
        # 실패 상황에서는 강한 판정을 내리면 안 되므로 '검증 제한'을 사용한다.
        "vc_recommended_judgement": "검증 제한",

        # LLM 호출 자체가 실패한 것이므로, 여기서는 위험 표현을 직접 발견한 것은 아니다.
        # 이후 apply_vc_guardrails()에서 ce_, input_의 위험 표현은 다시 검사한다.
        "vc_unsafe_expressions": [],

        # 정상 생성이 아니므로 수정 필요 True
        "vc_revision_needed": True,

        # 실패 이유를 사람이 이해할 수 있게 남긴다.
        "vc_revision_reason": reason,

        # 사용자에게 보여줄 수 있는 안전한 표현
        "vc_safe_expression": (
            "현재 제공된 정보만으로는 최종 판정을 안정적으로 생성하기 어렵습니다."
        ),

        # 내부 검토 메모
        "vc_critic_notes": (
            "LLM 호출 또는 구조화 출력 처리 중 문제가 발생해 "
            "안전한 기본 판정으로 대체했습니다."
        ),
    }


# ============================================================
# 프롬프트 파일 로딩
# ============================================================

def load_verdict_critic_prompt() -> str:
    """
    prompts/verdict_critic_prompt.md 파일을 읽어온다.

    현재 파일 위치:
    project-root/agents/verdict_critic_agent.py

    프롬프트 위치:
    project-root/prompts/verdict_critic_prompt.md

    따라서 __file__ 기준으로 부모 폴더를 따라 올라가서 prompts 폴더를 찾는다.
    """

    project_root = Path(__file__).resolve().parents[1]
    ## __file__ : 현재 코드가 들어 있는 파이썬 파일의 경로
    ## Path() : 경로 정보를 쉽게 다루기 위한 객체
    ## resolve() : 해당 경로를 절대 경로로 정리하는 메서드

    prompt_path = project_root / "prompts" / "verdict_critic_prompt.md"
    ## 여기서 / 는 경로 연결 연산자이다.

    return prompt_path.read_text(encoding="utf-8")
    ## prompt_path를 utf-8 로 읽어서 출력한다.


# ============================================================
# State에서 LLM에게 전달할 입력 만들기
# ============================================================

def build_verdict_input(state: NewsChartCheckState) -> str:
## NewsChartCheckState를 state로 선언하고 필요한 요소만 모아 문자열로 출력한다
## vc_에이전트가 읽어도 되는 값만을 필요한 요소로 정한다
## - input_ 변수의 값(원본 입력 정보)
## - ce_ 변수(claim_evidence_agent 결과)
## - ig_ 변수(info_gap_agent 결과)
## LLM이 vc_ 변수(verdict_critic_agent 결과)만 작성하도록 지시한다.

    """
    전체 state 중에서 vc_에이전트가 읽어도 되는 값만 모아
    LLM에게 전달할 텍스트를 만든다.

    중요:
    - 여기서는 input_, ce_, ig_ 값을 읽기만 한다.
    - 이 함수는 state를 수정하지 않는다.
    - vc_ 값도 여기서 만들지 않는다.
    """

    return f"""
[원본 입력 정보]

뉴스 제목:
{state.get("input_news_title", "")}

뉴스 본문:
{state.get("input_news_body", "")}

차트 이미지 경로:
{state.get("input_chart_image_path", "")}

차트에서 확인된 텍스트/수치:
{state.get("input_chart_text", "")}

출처 또는 차트 설명문:
{state.get("input_source_text", "")}


[claim_evidence_agent 결과]

차트에서 확인된 사실:
{state.get("ce_chart_facts", "")}

기사 주장 요약:
{state.get("ce_claim_summary", "")}

강한 표현:
{state.get("ce_strong_expressions", "")}

위험 플래그:
{state.get("ce_risk_flags", "")}

초안 판정:
{state.get("ce_draft_judgement", "")}

초안 요약:
{state.get("ce_draft_summary", "")}


[info_gap_agent 결과]

메타데이터 상태:
{state.get("ig_metadata_status", "")}

확인된 정보:
{state.get("ig_found_info", "")}

부족한 정보:
{state.get("ig_missing_info", "")}

검증 제한 사유:
{state.get("ig_limitation_reason", "")}

추가 확인 질문:
{state.get("ig_questions", "")}


[verdict_critic_agent 작업 지시]

위 정보를 바탕으로 최종 판정이 너무 강하게 단정되지 않았는지 검토하세요.

정보 부족은 핵심 부족과 보조 부족으로 구분하세요.
- 출처, 기간, 단위, 시각자료 수치, 비교 기준, 조사 대상, 표본 수, 차트 제목, 축 설명이 여러 개 부족하면 핵심 부족으로 볼 수 있습니다.
- 지역별 분포, 이용률, 세부 항목별 차이, 추가 세부 통계, 장기 시계열, 업종별 세부 자료만 부족한 경우에는 보조 부족입니다.
- 보조 부족 정보만 있다는 이유로 '대체로 뒷받침됨'을 '검증 제한'으로 낮추지 마세요.
- ig_limitation_reason에 일반적인 주의 문구가 있다는 사실만으로 검증 제한을 선택하지 말고, 실제 ig_missing_info와 차트 사실을 함께 확인하세요.

반드시 아래 vc_ 변수만 작성하세요.

- vc_recommended_judgement
- vc_unsafe_expressions
- vc_revision_needed
- vc_revision_reason
- vc_safe_expression
- vc_critic_notes
"""


# ============================================================
# 중복 제거 함수
# ============================================================

def ordered_unique(items: list[str]) -> list[str]:
    ## - items 내의 요소들을 중복만 제거하여 출력
    """
    list(set(...))을 쓰면 순서가 매번 달라질 수 있다.

    이 함수는 기존 순서를 유지하면서 중복만 제거한다.
    출력 결과가 테스트할 때마다 흔들리지 않게 하기 위해 사용한다.
    """

    result = []
    ## 출력할 결과 리스트 생성
    seen = set()
    ## 중복 여부를 확인할 세트 생성

    for item in items:
    ## items 내의 요소를 하나씩 item에 저장, 이하 내용을 반복
        if item not in seen:
        ## item이 seen 내에 없다면
        ## - item이 items내의 중복 요소가 아니라면
            result.append(item)
            ## result에 item 추가
            seen.add(item)
            ## seen에 item 추가

    return result


# ============================================================
# 위험 표현 탐지 함수
# ============================================================

def find_unsafe_expressions_in_text(text: Any) -> list[str]:
## 문자열 리스트를 생성한 후,
## UNSAFE_EXPRESSIONS 내의 단어가 입력받은 텍스트 내에 있으면
## 생성한 문자열 리스트에 추가하고 
## 문자열 리스트 출력
    """
    하나의 값 안에서 위험 표현을 찾는다.

    text가 문자열이 아닐 수도 있으므로 str()로 변환한다.
    예:
    - list[str]
    - None
    - dict
    - bool
    같은 값이 들어와도 에러가 나지 않게 한다.
    """

    if text is None:
        return []
    ## 입력값이 없으면 빈 리스트 출력

    text = str(text)
    ## 검사를 위해 입력값을 문자열로 저장

    found = []
    ## 출력용 리스트 생성

    for expression in UNSAFE_EXPRESSIONS:
        if expression in text:
            found.append(expression)

    return found

## ----------------------------------- -> 여기까지 코드 리뷰 완료

def find_unsafe_expressions(*values: Any) -> list[str]:
## 여러 개의 값을 받아 각각 위험 표현을 받는다.
    """
    여러 개의 값에서 위험 표현을 찾는다.

    예:
    find_unsafe_expressions(
        output["vc_revision_reason"],
        output["vc_critic_notes"],
        state["ce_draft_summary"],
    )
    """

    found = []

    for value in values:
        found.extend(find_unsafe_expressions_in_text(value))
        ## values 내 요소마다 find_unsafe_expressions_in_text 메서드에 입력하고 결과를 found에 추가

    return ordered_unique(found)

# ============================================================
# 6-3. 위험 표현 치환 함수
# ============================================================

def sanitize_text(text: Any) -> str:
    """
    sanitize_text

    기존 문제:
    - 위험 표현을 발견해도 vc_revision_reason, vc_critic_notes 안에 그대로 남을 수 있었다.

    개선:
    - 최종 vc_ 출력 필드에 들어가는 문자열은 이 함수를 거쳐 위험 표현을 제거한다.
    """

    if text is None:
        return ""

    sanitized = str(text)

    for unsafe, safe in SAFE_EXPRESSION_MAP.items():
        sanitized = sanitized.replace(unsafe, safe)

    return sanitized

# ============================================================
# 정보 부족 여부 판단 함수
# ============================================================

def has_meaningful_value(value: Any) -> bool:
    """
    ig_missing_info, ig_limitation_reason 등에 실제 의미 있는 값이 있는지 확인한다.

    기존 문제:
    str(None) -> "None"
    str([]) -> "[]"

    이렇게 되면 실제로는 빈 값인데 truthy로 처리될 수 있다.

    개선:
    - None은 False
    - 빈 문자열은 False
    - 빈 리스트/빈 딕셔너리는 False
    - "없음", "해당 없음", "N/A" 같은 표현도 False 처리
    """

    if value is None:
        return False

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized in {
            "",
            "none",
            "null",
            "[]",
            "{}",
            "없음",
            "해당 없음",
            "해당없음",
            "n/a",
            "na",
        }:
            return False

        return True

    if isinstance(value, list | tuple | set):
        # 리스트 안에 실제 의미 있는 값이 하나라도 있으면 True
        return any(has_meaningful_value(item) for item in value)

    if isinstance(value, dict):
        # 빈 dict는 False
        if not value:
            return False

        # dict 안의 값 중 의미 있는 값이 하나라도 있으면 True
        return any(has_meaningful_value(item) for item in value.values())

    # bool, int 등은 상황에 따라 애매하지만,
    # 이 필드에서는 보통 문자열/list/dict가 들어온다고 보고 기본 bool 처리
    return bool(value)


CORE_MISSING_INFO_KEYWORDS = (
    "출처",
    "기간",
    "단위",
    "시각자료 수치",
    "차트 수치",
    "비교 기준",
    "조사 대상",
    "표본 수",
    "표본수",
    "차트 제목",
    "축 설명",
)

AUXILIARY_MISSING_INFO_KEYWORDS = (
    "지역별 분포",
    "이용률",
    "세부 항목별",
    "추가 세부 통계",
    "장기 시계열",
    "업종별",
    "세부 자료",
)


def normalize_missing_info_items(value: Any) -> list[str]:
    """ig_missing_info를 비어 있지 않은 문자열 목록으로 정규화한다."""
    if isinstance(value, list | tuple | set):
        return [str(item).strip() for item in value if has_meaningful_value(item)]
    if has_meaningful_value(value):
        return [str(value).strip()]
    return []


def classify_missing_info(state: dict[str, Any]) -> tuple[list[str], list[str]]:
    """누락 항목을 핵심 검증 정보와 보조 확인 정보로 나눈다."""
    core_items: list[str] = []
    auxiliary_items: list[str] = []

    for item in normalize_missing_info_items(state.get("ig_missing_info")):
        # '장기 시계열'처럼 보조 항목에 명시된 표현은 일반적인 기간 관련
        # 표현보다 먼저 분류해 과도한 핵심 부족 판정을 피한다.
        if any(keyword in item for keyword in AUXILIARY_MISSING_INFO_KEYWORDS):
            auxiliary_items.append(item)
        elif any(keyword in item for keyword in CORE_MISSING_INFO_KEYWORDS):
            core_items.append(item)
        else:
            auxiliary_items.append(item)

    return core_items, auxiliary_items


def has_meaningful_chart_facts(state: dict[str, Any]) -> bool:
    """경로와 임시 레이블을 제외한 실제 차트 사실이 있는지 확인한다."""
    facts = str(state.get("ce_chart_facts") or "")
    removable_texts = [
        "원본 시각자료 이미지 경로:",
        "시각자료 보조 설명:",
        "업로드된 원본 이미지 없음",
        "입력된 보조 설명 없음",
    ]
    image_paths = state.get("input_chart_image_paths")
    if isinstance(image_paths, list):
        removable_texts.extend(str(path) for path in image_paths)
    else:
        removable_texts.extend(
            line.strip()
            for line in str(state.get("input_chart_image_path") or "").splitlines()
            if line.strip()
        )

    for text in removable_texts:
        facts = facts.replace(text, "")
    return bool(facts.strip())


def get_critical_info_gap_reasons(state: dict[str, Any]) -> list[str]:
    """최종 판정을 실제로 제한할 정도의 핵심 부족 사유만 반환한다."""
    reasons: list[str] = []
    metadata_status = str(state.get("ig_metadata_status") or "").strip()
    core_items, _ = classify_missing_info(state)
    chart_text = str(state.get("input_chart_text") or "").strip()
    image_paths = state.get("input_chart_image_paths")
    has_image_path = (
        any(str(path).strip() for path in image_paths)
        if isinstance(image_paths, list)
        else bool(str(state.get("input_chart_image_path") or "").strip())
    )

    if metadata_status == "검증 제한":
        reasons.append("메타정보 상태가 명시적으로 검증 제한입니다.")
    if len(core_items) >= 2:
        reasons.append("핵심 판단에 필요한 정보가 여러 개 부족합니다.")
    if not chart_text and has_image_path:
        reasons.append("이미지는 있으나 실제 수치를 확인할 보조 설명이 없습니다.")
    if not has_meaningful_chart_facts(state):
        reasons.append("의미 있는 차트 사실이 확인되지 않습니다.")

    foundational_keywords = ("출처", "기간", "단위", "비교 기준")
    missing_foundations = {
        keyword
        for keyword in foundational_keywords
        if any(keyword in item for item in core_items)
    }
    if len(missing_foundations) >= 3:
        reasons.append("출처·기간·단위·비교 기준 중 대부분이 부족합니다.")

    return ordered_unique(reasons)


def has_info_gap(state: dict[str, Any]) -> bool:
    """핵심 판단을 제한할 정도의 정보 부족이 있는지 반환한다."""
    return bool(get_critical_info_gap_reasons(state))

# ============================================================
# 7. LLM 결과 후처리
# ============================================================

def apply_vc_guardrails(
    output: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """
    LLM이 만든 vc_ 결과를 최종 검수하는 함수.

    이 함수의 목적:
    1. 허용되지 않은 판정값 보정
    2. vc_ 출력 안의 위험 표현 실제 제거
    3. ce_ 초안 결과 안의 위험 표현 직접 탐지
    4. 정보 부족 시 과한 판정 완화
    5. 최종적으로 vc_ 키만 반환
    """

    # ------------------------------------------------------------
    # 0. 입력 output 복사
    # ------------------------------------------------------------
    # 이 함수는 아래에서 output.setdefault(...), output["..."] = ...처럼
    # output 값을 여러 번 수정한다.
    #
    # 기존 문제:
    # - 함수로 전달받은 dict를 그대로 수정하면,
    #   호출한 쪽에서 들고 있던 raw_output도 같이 바뀔 수 있다.
    #
    # 예:
    # raw_output = {"vc_recommended_judgement": "이상한 판정"}
    # result = apply_vc_guardrails(raw_output, state)
    #
    # 이때 raw_output 자체도 "검증 제한"으로 바뀔 수 있다.
    #
    # 개선:
    # - 함수 시작 시 output을 복사한다.
    # - 이후 수정은 복사본에만 적용한다.
    # - 최종 결과만 return한다.
    #
    # dict(output)은 얕은 복사지만,
    # 현재 코드에서는 vc_unsafe_expressions도 나중에 새 리스트로 다시 대입하므로
    # 이 정도면 충분하다.
    output = dict(output)

    # ------------------------------------------------------------
    # 1. 필수 필드 기본값 보정
    # ------------------------------------------------------------
    # LLM 호출 결과에 특정 필드가 빠졌을 때를 대비한다.

    output.setdefault("vc_recommended_judgement", "검증 제한")
    output.setdefault("vc_unsafe_expressions", [])
    output.setdefault("vc_revision_needed", False)
    output.setdefault("vc_revision_reason", "")
    output.setdefault("vc_safe_expression", "")
    output.setdefault("vc_critic_notes", "")

    # ------------------------------------------------------------
    # 2. 판정값 검사
    # ------------------------------------------------------------
    # 판정은 반드시 4개 중 하나여야 한다.

    judgement = output.get("vc_recommended_judgement")

    if judgement not in ALLOWED_JUDGEMENTS:
        output["vc_recommended_judgement"] = "검증 제한"
        output["vc_revision_needed"] = True
        output["vc_revision_reason"] = (
            "허용되지 않은 판정값이 생성되어 '검증 제한'으로 보정했습니다."
        )
        output["vc_safe_expression"] = (
            "현재 제공된 근거만으로는 명확한 최종 판정을 내리기 어렵습니다."
        )

    # ------------------------------------------------------------
    # 3. LLM이 생성한 vc_ 출력 안의 위험 표현 탐지
    # ------------------------------------------------------------
    # 기존 코드의 핵심 문제:
    # - 위험 표현을 찾기는 했지만 실제 문자열에서는 제거하지 않았다.
    #
    # 개선:
    # - 위험 표현을 찾고
    # - vc_revision_reason, vc_safe_expression, vc_critic_notes에서 실제로 치환한다.

    unsafe_in_vc_output = find_unsafe_expressions(
        output.get("vc_revision_reason"),
        output.get("vc_safe_expression"),
        output.get("vc_critic_notes"),
    )

    if unsafe_in_vc_output:
        output["vc_revision_needed"] = True

        # 위험 표현이 발견되었으므로 이유도 명확히 보정한다.
        output["vc_revision_reason"] = (
            "최종 판정 또는 검토 문구에 단정적인 표현이 포함되어 더 안전한 표현으로 수정했습니다."
        )

    # 실제 vc_ 문자열 필드 정화
    output["vc_revision_reason"] = sanitize_text(output.get("vc_revision_reason"))
    output["vc_safe_expression"] = sanitize_text(output.get("vc_safe_expression"))
    output["vc_critic_notes"] = sanitize_text(output.get("vc_critic_notes"))

    # ------------------------------------------------------------
    # 4. ce_ 초안 결과 안의 위험 표현도 직접 검사
    # ------------------------------------------------------------
    # 기존 문제:
    # - ce_draft_summary나 ce_draft_judgement 안에 "가짜 뉴스", "조작" 등이 있어도
    #   LLM이 vc_unsafe_expressions에 적지 않으면 놓칠 수 있었다.
    #
    # 개선:
    # - 코드가 직접 ce_ 결과를 검사한다.
    #
    # 주의:
    # - input_news_title, input_news_body는 원문이므로 무조건 치환 대상은 아니다.
    # - 하지만 최종 report_merge_node가 원문을 그대로 노출한다면 그쪽에서도 별도 정화가 필요하다.

    unsafe_in_ce_state = find_unsafe_expressions(
        state.get("ce_strong_expressions"),
        state.get("ce_draft_judgement"),
        state.get("ce_draft_summary"),
    )

    # 원한다면 원문 제목/본문도 "탐지"만 할 수 있다.
    # 단, 원문 자체를 vc_에이전트에서 수정하는 것은 역할 범위를 넘을 수 있다.
    unsafe_in_input = find_unsafe_expressions(
        state.get("input_news_title"),
        state.get("input_news_body"),
    )

    # 기존 LLM 결과에 있던 위험 표현 목록
    existing_unsafe = output.get("vc_unsafe_expressions", [])

    if not isinstance(existing_unsafe, list):
        existing_unsafe = [str(existing_unsafe)]

    # 모든 위험 표현을 합치되, 순서를 유지하면서 중복 제거
    output["vc_unsafe_expressions"] = ordered_unique(
        existing_unsafe
        + unsafe_in_vc_output
        + unsafe_in_ce_state
        + unsafe_in_input
    )

    if unsafe_in_ce_state:
        output["vc_revision_needed"] = True

        # ce_ 초안에 위험 표현이 있었음을 검토 메모에 남긴다.
        output["vc_critic_notes"] = sanitize_text(
            output["vc_critic_notes"]
            + "\n초안 판정 또는 초안 요약에 단정적인 표현이 포함되어 완화가 필요합니다."
        )

    if unsafe_in_input:
        # 원문 제목/본문에 위험 표현이 있는 경우는
        # 원문 자체가 그런 표현을 포함한 것일 수 있으므로,
        # vc_에이전트가 원문을 수정하지는 않고 메모만 남긴다.
        output["vc_critic_notes"] = sanitize_text(
            output["vc_critic_notes"]
            + "\n원문 제목 또는 본문에 강한 표현이 포함되어 최종 리포트 작성 시 인용 방식에 주의가 필요합니다."
        )

    # ------------------------------------------------------------
    # 5. 정보 부족인데 판정이 너무 강한 경우 완화
    # ------------------------------------------------------------
    #
    # 기존 문제:
    # - 정보가 부족할 때 "왜곡 가능성 높음"만 "검증 제한"으로 낮췄다.
    # - 하지만 정보가 부족한데 "대체로 뒷받침됨"이라고 하는 것도
    #   근거 수준에 비해 너무 강한 긍정 판정일 수 있다.
    #
    # 개선 방향:
    # - 정보 부족이 있으면 확정적인 긍정/부정 판정 모두 완화한다.
    #
    # 완화 대상:
    # - "왜곡 가능성 높음"  → 강한 부정 판정
    # - "대체로 뒷받침됨"  → 강한 긍정 판정
    #
    # 유지 가능:
    # - "주의 필요" → 이미 조심스러운 판정이므로 유지 가능
    # - "검증 제한" → 이미 정보 부족을 반영한 판정이므로 유지

    critical_gap_reasons = get_critical_info_gap_reasons(state)
    if critical_gap_reasons:
        current_judgement = output.get("vc_recommended_judgement")

        # 정보 부족 상황에서는 양쪽 확신을 모두 낮춘다.
        # 즉, 너무 강한 부정도 낮추고, 너무 강한 긍정도 낮춘다.
        if current_judgement in {"왜곡 가능성 높음", "대체로 뒷받침됨"}:
            output["vc_recommended_judgement"] = "검증 제한"
            output["vc_revision_needed"] = True
            output["vc_revision_reason"] = (
                "핵심 검증에 필요한 정보가 부족해 확정적인 판정보다 "
                "'검증 제한'이 더 적절합니다."
            )
            output["vc_safe_expression"] = (
                "현재 제공된 표/차트 정보만으로는 기사 주장을 충분히 검증하기 어렵습니다."
            )
            output["vc_critic_notes"] = sanitize_text(
                output["vc_critic_notes"]
                + "\n핵심 정보 부족 사유: "
                + " ".join(critical_gap_reasons)
            )
    # ------------------------------------------------------------
    # 6. revision_needed와 reason의 모순 방지
    # ------------------------------------------------------------
    # 수정 필요가 True인데 이유가 비어 있으면 어색하다.
    # 최소한의 기본 이유를 넣는다.

    if output.get("vc_revision_needed") and not output.get("vc_revision_reason"):
        output["vc_revision_reason"] = (
            "최종 판정의 표현 강도 또는 근거 수준을 보수적으로 조정할 필요가 있습니다."
        )

    # ------------------------------------------------------------
    # 7. 안전 표현이 비어 있으면 기본 문구 제공
    # ------------------------------------------------------------

    if not output.get("vc_safe_expression"):
        output["vc_safe_expression"] = (
            "현재 근거만으로는 단정하기 어렵고, 추가 검증이 필요합니다."
        )

    # 마지막으로 한 번 더 정화한다.
    # 위에서 새로 붙인 문장에 위험 표현이 섞였을 가능성까지 방지한다.
    output["vc_revision_reason"] = sanitize_text(output.get("vc_revision_reason"))
    output["vc_safe_expression"] = sanitize_text(output.get("vc_safe_expression"))
    output["vc_critic_notes"] = sanitize_text(output.get("vc_critic_notes"))

    # ------------------------------------------------------------
    # 8. vc_ 키만 반환
    # ------------------------------------------------------------

    return pick_vc_only(output)


# ============================================================
# 8. vc_ 키만 남기는 함수
# ============================================================

def pick_vc_only(output: dict[str, Any]) -> dict[str, Any]:
    """
    최종적으로 LangGraph state에 업데이트할 값만 남긴다.

    매우 중요:
    - 이 에이전트는 vc_ 변수만 작성해야 한다.
    - 혹시 LLM이나 코드 실수로 input_, ce_, ig_, merge_, runtime_ 키가 섞이면 제거한다.
    """

    vc_keys = [
        "vc_recommended_judgement",
        "vc_unsafe_expressions",
        "vc_revision_needed",
        "vc_revision_reason",
        "vc_safe_expression",
        "vc_critic_notes",
    ]

    return {
        key: output.get(key)
        for key in vc_keys
    }



# ============================================================
# 10. LangGraph 노드 생성 함수
# ============================================================

def make_verdict_critic_node(llm):
    """
    verdict_critic 노드를 만드는 함수.

    왜 바로 node 함수를 만들지 않고 make_ 함수를 쓰는가?
    - llm 객체를 외부에서 주입받기 위해서다.
    - 이렇게 하면 OpenAI 모델, 로컬 모델, 테스트용 fake 모델로 쉽게 바꿀 수 있다.

    사용 예:
    graph = build_verdict_critic_graph(llm)
    """

    # ------------------------------------------------------------
    # 1. 시스템 프롬프트 로드
    # ------------------------------------------------------------
    # prompts/verdict_critic_prompt.md 내용을 읽어온다.
    # 이 프롬프트에는 vc_에이전트의 역할, 금지 표현, 판정 기준이 들어간다.
    system_prompt = load_verdict_critic_prompt()

    # ------------------------------------------------------------
    # 2. 프롬프트 체인 구성
    # ------------------------------------------------------------
    # system 메시지:
    # - 고정 규칙
    #
    # human 메시지:
    # - 매번 달라지는 뉴스 제목, 본문, 차트 정보, ce_ 결과, ig_ 결과
    #
    # 프롬프트 객체 생성 자체는 보통 실패 가능성이 낮다.
    # 그래서 먼저 prompt를 만든다.
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("human", "{verdict_input}"),
        ]
    )

    # ------------------------------------------------------------
    # 3. LLM 출력 형식 고정 + 체인 생성
    # ------------------------------------------------------------
    # 기존 문제:
    # - llm.with_structured_output(VerdictCriticOutput)이 try/except 밖에 있었다.
    # - structured output을 지원하지 않는 로컬 LLM이나 래퍼 모델이면
    #   make_verdict_critic_node() 단계에서 바로 실패할 수 있었다.
    #
    # 개선:
    # - structured_llm 생성과 chain 생성을 try/except 안에 넣는다.
    # - 실패해도 노드 생성 자체는 계속 되게 한다.
    # - 대신 chain_error에 오류를 저장해두고,
    #   실제 노드 실행 시 fallback으로 처리한다.
    try:
        structured_llm = llm.with_structured_output(VerdictCriticOutput)

        # prompt → structured_llm 순서로 실행되는 chain을 만든다.
        chain = prompt | structured_llm

        # chain 생성이 성공했으므로 초기화 오류는 없다.
        chain_error = None

    except Exception as e:
        # structured output 초기화가 실패한 경우
        # 예:
        # - 로컬 LLM 래퍼가 with_structured_output을 지원하지 않음
        # - 모델이 tool calling / JSON schema 출력을 지원하지 않음
        #
        # 여기서 바로 raise하지 않는다.
        # 그래야 build_verdict_critic_graph(llm) 자체가 죽지 않는다.
        chain = None
        chain_error = e
    # ------------------------------------------------------------
    # 4. 실제 LangGraph 노드 함수
    # ------------------------------------------------------------

    def verdict_critic_node(state: NewsChartCheckState) -> dict[str, Any]:
        """
        실제 LangGraph에서 실행되는 노드 함수.

        입력:
        - 전체 NewsChartCheckState

        처리:
        1. state에서 input_, ce_, ig_ 정보를 읽는다.
        2. LLM에게 최종판정 검토를 요청한다.
        3. LLM 결과를 dict로 바꾼다.
        4. LLM 실패 시 안전한 fallback 결과를 만든다.
        5. 성공/실패와 관계없이 규칙 기반 후처리를 적용한다.
        6. vc_ 변수만 반환한다.

        반환:
        - LangGraph가 state에 업데이트할 vc_ 값들
        """

        # --------------------------------------------------------
        # 4-1. state를 LLM 입력용 텍스트로 변환
        # --------------------------------------------------------
        # 이 함수는 input_, ce_, ig_ 값을 읽기만 한다.
        # state를 수정하지 않는다.
        verdict_input = build_verdict_input(state)

        # --------------------------------------------------------
        # 4-2. LLM 호출
        # --------------------------------------------------------
        # 기존 코드에서는 여기서 오류가 나면 전체 노드가 실패했다.
        # 수정 후에는 try/except로 감싸서 안전하게 처리한다.
        try:
            # ----------------------------------------------------
            # 4-2-1. 체인 초기화 실패 여부 확인
            # ----------------------------------------------------
            # make_verdict_critic_node() 단계에서
            # structured output 초기화에 실패했다면 chain은 None이다.
            #
            # 이 경우 chain.invoke()를 호출하면 AttributeError가 나므로,
            # 그 전에 명시적으로 RuntimeError를 발생시켜 fallback으로 보낸다.
            if chain is None or chain_error is not None:
                raise RuntimeError(
                    "structured output 초기화에 실패했습니다. "
                    f"오류 유형: {type(chain_error).__name__}"
                )

            # ----------------------------------------------------
            # 4-2-2. LLM 호출
            # ----------------------------------------------------
            # 여기까지 왔다는 것은 chain 생성이 정상적으로 끝났다는 뜻이다.
            result = chain.invoke(
                {
                    "verdict_input": verdict_input
                }
            )

            # ----------------------------------------------------
            # 4-3. structured output 결과를 검증 후 dict로 변환
            # ----------------------------------------------------
            # 1번 수정에서 추가한 normalize_llm_result()를 사용한다.
            # Pydantic 객체든 dict든 무조건 VerdictCriticOutput 검증을 거친다.
            raw_output = normalize_llm_result(result)

        except Exception as e:
            # ----------------------------------------------------
            # 4-4. LLM 호출 또는 구조화 출력 실패 시 fallback
            # ----------------------------------------------------
            # 실패했을 때는 가장 보수적인 판정인 '검증 제한'으로 간다.
            # 여기서 바로 return하지 않는 것이 중요하다.
            # 아래 apply_vc_guardrails()를 반드시 거쳐야
            # ce_ 초안 위험 표현, input_ 위험 표현 등을 추가로 검사할 수 있다.
            raw_output = make_safe_fallback_output(
                reason=(
                    "최종판정 검토 생성 중 오류가 발생해 "
                    "'검증 제한'으로 대체했습니다. "
                    f"오류 유형: {type(e).__name__}"
                )
            )

        # --------------------------------------------------------
        # 4-5. 규칙 기반 후처리
        # --------------------------------------------------------
        # LLM 성공/실패와 관계없이 반드시 실행한다.
        #
        # 여기서 하는 일:
        # - 위험 표현 실제 제거
        # - ce_ 초안 위험 표현 직접 검사
        # - 정보 부족 시 과한 판정 완화
        # - vc_ 키만 남기기
        final_output = apply_vc_guardrails(raw_output, state)

        # --------------------------------------------------------
        # 4-6. 최종 반환
        # --------------------------------------------------------
        # LangGraph는 이 dict를 기존 state에 업데이트한다.
        # 이 dict 안에는 반드시 vc_ 키만 있어야 한다.
        return final_output

    # make_verdict_critic_node()는 실제 실행 함수인 verdict_critic_node를 반환한다.
    return verdict_critic_node


# ============================================================
# 10. verdict_critic 전용 LangGraph 만들기
# ============================================================

def build_verdict_critic_graph(llm):
    """
    verdict_critic_agent 하나만 실행하는 작은 LangGraph를 만든다.

    구조:
    START
      ↓
    verdict_critic
      ↓
    END

    처음에는 이 정도로 충분하다.
    나중에 전체 그래프에서는 이 그래프를 서브그래프로 붙이거나,
    verdict_critic_node만 가져다가 전체 그래프에 추가해도 된다.
    """

    # 전체 state 구조를 사용하는 StateGraph를 만든다.
    graph = StateGraph(NewsChartCheckState)

    # verdict_critic 노드를 추가한다.
    graph.add_node(
        "verdict_critic",
        make_verdict_critic_node(llm)
    )

    # START에서 verdict_critic 노드로 이동한다.
    graph.add_edge(START, "verdict_critic")

    # verdict_critic 작업이 끝나면 END로 이동한다.
    graph.add_edge("verdict_critic", END)

    # 실행 가능한 그래프로 컴파일한다.
    return graph.compile()
