# test_samples/dry_run_verdict_critic_agent.py

"""
verdict_critic_agent 단독 건식 테스트

목적:
- 실제 프론트엔드 없이
- 실제 claim_evidence_agent 없이
- 실제 info_gap_agent 없이
- 실제 OpenAI/로컬 LLM 없이

프론트 파서 결과에 가짜 ce_ / ig_ 결과를 붙여서
verdict_critic_agent만 단독으로 실행해본다.
"""

from pprint import pprint

from langchain_core.runnables import RunnableLambda

from parsers.frontend_payload_parser import parse_frontend_payload
from agents.verdict_critic_agent import (
    VerdictCriticOutput,
    make_verdict_critic_node,
)


# ============================================================
# 1. 테스트용 Fake LLM
# ============================================================

class FakeLLM:
    """
    실제 LLM 대신 사용할 가짜 LLM.

    왜 필요한가?
    - 지금은 건식 테스트 단계다.
    - OpenAI API나 로컬 LLM을 실제로 호출할 필요가 없다.
    - 우리가 원하는 응답을 일부러 반환하게 해서
      verdict_critic_agent의 후처리가 잘 작동하는지 확인한다.

    make_verdict_critic_node() 내부에서는
    llm.with_structured_output(VerdictCriticOutput)을 호출한다.

    그래서 FakeLLM도 with_structured_output() 메서드를 갖고 있어야 한다.
    """

    def __init__(self, fake_response: dict):
        # LLM이 반환할 가짜 응답 dict
        self.fake_response = fake_response

    def with_structured_output(self, schema):
        """
        실제 LLM이라면 schema에 맞는 structured output을 생성한다.

        여기서는 RunnableLambda를 반환한다.
        그래야 prompt | structured_llm 구조에서 정상 작동한다.
        """

        def fake_invoke(_prompt_input):
            """
            _prompt_input에는 ChatPromptTemplate이 만든 메시지가 들어온다.
            하지만 건식 테스트에서는 실제 내용을 분석하지 않는다.
            미리 정해둔 fake_response만 반환한다.
            """

            # schema는 보통 VerdictCriticOutput이다.
            # model_validate()를 거치게 해서
            # fake_response도 실제 구조화 출력처럼 검증한다.
            return schema.model_validate(self.fake_response)

        return RunnableLambda(fake_invoke)


# ============================================================
# 2. 프론트 payload 예시
# ============================================================

def make_sample_frontend_payload() -> dict:
    """
    실제 프론트에서 들어올 데이터라고 가정한 샘플.

    프론트 키:
    - newsTitle
    - newsBody
    - chartText
    - sourceText
    - chartImagePath

    parser가 이걸 input_ state로 바꾼다.
    """

    return {
        "newsTitle": "청년 실업률 역대 최고",
        "newsBody": (
            "기사 본문에서는 최근 청년 실업률이 계속 상승하고 있으며 "
            "역대 최고 수준이라고 주장한다."
        ),
        "chartText": "2022년 6.4%, 2023년 6.1%, 2024년 5.9%",
        "sourceText": "통계청 고용동향 자료",
        "chartImagePath": "test_samples/sample_chart.png",
    }


# ============================================================
# 3. 가짜 ce_ 결과
# ============================================================

def make_fake_ce_result() -> dict:
    """
    claim_evidence_agent가 이미 실행됐다고 가정하고,
    그 결과를 가짜로 만든다.

    일부러 ce_draft_summary에 '가짜 뉴스' 같은 위험 표현을 넣는다.

    목적:
    - verdict_critic_agent가 ce_ 초안의 위험 표현을 탐지하는지 확인
    - 위험 표현을 vc_unsafe_expressions에 기록하는지 확인
    - vc_critic_notes에 완화 필요 메모를 남기는지 확인
    """

    return {
        "ce_chart_facts": (
            "차트 수치상 청년 실업률은 2022년 6.4%, 2023년 6.1%, "
            "2024년 5.9%로 하락하는 흐름이다."
        ),
        "ce_claim_summary": (
            "기사는 청년 실업률이 계속 상승해 역대 최고 수준이라고 주장한다."
        ),
        "ce_strong_expressions": ["역대 최고", "계속 상승"],
        "ce_risk_flags": ["차트 추세와 기사 표현이 어긋날 가능성"],
        "ce_draft_judgement": "왜곡 가능성 높음",
        "ce_draft_summary": (
            "차트에서는 하락 흐름이 보이므로 기사 주장을 가짜 뉴스라고 볼 수 있다."
        ),
    }


# ============================================================
# 4. 가짜 ig_ 결과
# ============================================================

def make_fake_ig_result() -> dict:
    """
    info_gap_agent가 이미 실행됐다고 가정하고,
    그 결과를 가짜로 만든다.

    여기서는 일부러 정보 부족을 넣는다.

    목적:
    - 정보 부족이 있을 때
      verdict_critic_agent가 강한 판정을 '검증 제한'으로 낮추는지 확인
    """

    return {
        "ig_metadata_status": "일부 부족",
        "ig_found_info": "출처명은 확인됨.",
        "ig_missing_info": ["차트 작성 기간", "표본 기준", "계절조정 여부"],
        "ig_limitation_reason": (
            "차트 수치의 기준과 기간이 충분히 명확하지 않아 강한 판정은 제한된다."
        ),
        "ig_questions": [
            "차트의 원자료 기간은 언제인가?",
            "실업률 기준은 전체 청년층인가, 특정 연령대인가?",
        ],
    }


# ============================================================
# 5. Fake LLM 응답
# ============================================================

def make_fake_llm_response() -> dict:
    """
    Fake LLM이 반환할 vc_ 응답.

    일부러 위험한 표현을 섞어둔다.
    일부러 강한 판정인 '왜곡 가능성 높음'을 반환한다.

    목적:
    - apply_vc_guardrails()가 위험 표현을 안전 표현으로 치환하는지 확인
    - 정보 부족이 있으면 '왜곡 가능성 높음'을 '검증 제한'으로 낮추는지 확인
    """

    return {
        "vc_recommended_judgement": "왜곡 가능성 높음",
        "vc_unsafe_expressions": [],
        "vc_revision_needed": False,
        "vc_revision_reason": "기사 표현은 조작이라고 단정할 수 있습니다.",
        "vc_safe_expression": "가짜 뉴스입니다.",
        "vc_critic_notes": "차트와 본문이 다르므로 명백한 허위라고 볼 수 있습니다.",
    }


# ============================================================
# 6. 전체 테스트 실행
# ============================================================

def main():
    # ------------------------------------------------------------
    # 6-1. 프론트 payload를 input_ state로 변환
    # ------------------------------------------------------------

    frontend_payload = make_sample_frontend_payload()
    input_state = parse_frontend_payload(frontend_payload)

    print("\n=== 1. 프론트 파서 결과 input_ state ===")
    pprint(input_state)

    # ------------------------------------------------------------
    # 6-2. 가짜 ce_ / ig_ 결과 생성
    # ------------------------------------------------------------

    fake_ce = make_fake_ce_result()
    fake_ig = make_fake_ig_result()

    print("\n=== 2. 가짜 ce_ 결과 ===")
    pprint(fake_ce)

    print("\n=== 3. 가짜 ig_ 결과 ===")
    pprint(fake_ig)

    # ------------------------------------------------------------
    # 6-3. 전체 state 조립
    # ------------------------------------------------------------
    # 실제 전체 그래프에서는:
    # input_ → ce_ → ig_ → vc_
    # 순서로 state가 채워진다.
    #
    # 지금은 건식 테스트이므로 우리가 직접 합친다.

    state = {
        **input_state,
        **fake_ce,
        **fake_ig,
    }

    print("\n=== 4. verdict_critic_agent에 넣을 전체 state ===")
    pprint(state)

    # ------------------------------------------------------------
    # 6-4. Fake LLM 준비
    # ------------------------------------------------------------
    # 실제 LLM 대신 우리가 정해둔 fake_response를 반환하게 한다.

    fake_llm = FakeLLM(make_fake_llm_response())

    # ------------------------------------------------------------
    # 6-5. verdict_critic_node 생성
    # ------------------------------------------------------------
    # make_verdict_critic_node()는 LangGraph 노드 함수를 반환한다.
    # 여기서는 전체 graph를 만들지 않고 노드 함수만 직접 실행한다.

    verdict_critic_node = make_verdict_critic_node(fake_llm)

    # ------------------------------------------------------------
    # 6-6. verdict_critic_node 단독 실행
    # ------------------------------------------------------------
    # 반환값은 vc_ 변수만 담은 dict여야 한다.

    vc_result = verdict_critic_node(state)

    print("\n=== 5. verdict_critic_agent 결과 vc_ ===")
    pprint(vc_result)

    # ------------------------------------------------------------
    # 6-7. 간단 검증
    # ------------------------------------------------------------
    # 사람이 눈으로 확인하기 쉽게 핵심 조건을 체크한다.

    print("\n=== 6. 간단 검증 ===")

    non_vc_keys = [
        key for key in vc_result.keys()
        if not key.startswith("vc_")
    ]

    if non_vc_keys:
        print(f"실패: vc_가 아닌 키가 포함됨: {non_vc_keys}")
    else:
        print("통과: vc_ 키만 반환됨")

    if vc_result.get("vc_recommended_judgement") == "검증 제한":
        print("통과: 정보 부족으로 강한 판정이 '검증 제한'으로 완화됨")
    else:
        print(
            "주의: 정보 부족 상황인데 판정이 검증 제한이 아님:",
            vc_result.get("vc_recommended_judgement"),
        )

    unsafe_text_joined = " ".join(
        str(vc_result.get(key, ""))
        for key in [
            "vc_revision_reason",
            "vc_safe_expression",
            "vc_critic_notes",
        ]
    )

    dangerous_words = [
        "가짜 뉴스",
        "조작",
        "거짓",
        "사기",
        "완전히 틀림",
        "명백한 허위",
        "절대 믿으면 안 됨",
    ]

    remaining_dangerous_words = [
        word for word in dangerous_words
        if word in unsafe_text_joined
    ]

    if remaining_dangerous_words:
        print("실패: vc_ 출력 문구에 위험 표현이 남아 있음:", remaining_dangerous_words)
    else:
        print("통과: vc_ 출력 문구에서 위험 표현이 제거됨")


if __name__ == "__main__":
    main()