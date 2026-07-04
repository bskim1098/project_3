# state/news_chart_check_state.py

"""
news_chart_check_state.py

역할:
- 뉴스 차트 검증 LangGraph 전체에서 공유할 State 구조를 정의한다.

중요:
- input_ 값은 프론트 파서가 만든다.
- ce_ 값은 claim_evidence_agent가 만든다.
- ig_ 값은 info_gap_agent가 만든다.
- vc_ 값은 verdict_critic_agent가 만든다.
- merge_ 값은 report_merge_node가 만든다.

이 파일은 값을 생성하는 파일이 아니라,
'어떤 키들이 state에 들어갈 수 있는지' 타입 구조만 정의하는 파일이다.
"""

from typing import Any, NotRequired, TypedDict


class NewsChartCheckState(TypedDict):
    """
    뉴스 차트 검증 전체 파이프라인에서 공유되는 State.

    TypedDict를 쓰는 이유:
    - LangGraph의 StateGraph에서 state 구조를 명확히 하기 위해서다.
    - dict처럼 사용할 수 있으면서도,
      어떤 키가 들어갈 수 있는지 코드상으로 확인하기 쉽다.

    NotRequired를 쓰는 이유:
    - 처음부터 모든 값이 채워지는 것은 아니기 때문이다.
    - 예를 들어 input_은 시작부터 있지만,
      ce_, ig_, vc_는 각 에이전트가 실행된 뒤에 채워진다.
    """

    # ============================================================
    # 1. input_ : 프론트 파서가 만드는 원본 입력
    # ============================================================

    input_news_title: str
    input_news_body: str
    input_chart_image_path: str
    input_chart_image_paths: NotRequired[list[str]]
    input_chart_text: str
    input_source_text: str

    # ============================================================
    # 2. ce_ : claim_evidence_agent 결과
    # ============================================================

    ce_chart_facts: NotRequired[str]
    ce_claim_summary: NotRequired[str]
    ce_strong_expressions: NotRequired[list[str]]
    ce_risk_flags: NotRequired[list[str]]
    ce_draft_judgement: NotRequired[str]
    ce_draft_summary: NotRequired[str]

    # ============================================================
    # 3. ig_ : info_gap_agent 결과
    # ============================================================

    ig_metadata_status: NotRequired[str]
    ig_found_info: NotRequired[str]
    ig_missing_info: NotRequired[list[str] | str]
    ig_limitation_reason: NotRequired[str]
    ig_questions: NotRequired[list[str]]

    # ============================================================
    # 4. vc_ : verdict_critic_agent 결과
    # ============================================================

    vc_recommended_judgement: NotRequired[str]
    vc_unsafe_expressions: NotRequired[list[str]]
    vc_revision_needed: NotRequired[bool]
    vc_revision_reason: NotRequired[str]
    vc_safe_expression: NotRequired[str]
    vc_critic_notes: NotRequired[str]

    # ============================================================
    # 5. merge_ : report_merge_node 결과
    # ============================================================
    # 아직 report_merge_node를 만들지 않았더라도,
    # 나중에 최종 리포트 결과를 담기 위해 자리를 열어둘 수 있다.

    merge_user_facing_judgement: NotRequired[str]
    merge_judgement_tone: NotRequired[str]
    merge_headline: NotRequired[str]
    merge_summary: NotRequired[str]
    merge_issue_cards: NotRequired[list[dict[str, Any]]]
    merge_evidence_cards: NotRequired[list[dict[str, Any]]]
    merge_missing_info_cards: NotRequired[list[dict[str, Any]]]
    merge_recommendations: NotRequired[list[str]]
    merge_final_report: NotRequired[str]

    # ============================================================
    # 6. runtime_ : 실행 중 상태 또는 디버깅용
    # ============================================================
    # verdict_critic_agent는 runtime_ 값을 작성하면 안 된다.
    # 다만 전체 State 타입에는 포함될 수 있다.

    runtime_errors: NotRequired[list[str]]
    runtime_warnings: NotRequired[list[str]]

    # ============================================================
    # 7. 기타 확장용
    # ============================================================
    # 나중에 예상하지 못한 보조 값을 넣어야 할 수도 있다.
    # 지금 당장은 없어도 되지만, 테스트 편의상 남겨둘 수 있다.

    extra: NotRequired[dict[str, Any]]
