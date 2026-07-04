# 실행:
# uv run --active streamlit run frontend/streamlit_app.py

"""verdict_critic_agent 기반 데이터 체커 서비스형 데모."""

import sys
from html import escape
from pathlib import Path
from pprint import pformat
from textwrap import dedent
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from agents.verdict_critic_agent import make_verdict_critic_node
from nodes.report_merge_node import build_service_report


# verdict_critic_agent와 화면의 판정 선택지가 서로 달라지지 않도록
# 허용되는 네 가지 판정값을 한곳에서 관리한다.
JUDGEMENTS = (
    "대체로 뒷받침됨",
    "주의 필요",
    "검증 제한",
    "왜곡 가능성 높음",
)


def make_real_llm() -> ChatOpenAI:
    """실제 verdict 검토에 사용할 OpenAI 모델을 생성한다.

    API 키를 인자로 직접 받지 않는 이유는 main()에서 load_dotenv()를 먼저
    호출한 뒤, ChatOpenAI가 환경 변수 OPENAI_API_KEY를 읽도록 하기 위해서다.
    temperature=0은 같은 입력에서 판정 문구가 불필요하게 흔들리는 것을 줄인다.
    """
    return ChatOpenAI(
        model="gpt-5.4-mini",
        temperature=0,
        max_retries=2,
    )


def save_uploaded_chart_images(uploaded_files: list[Any] | None) -> list[str]:
    """업로드 이미지를 충돌하지 않는 이름으로 저장하고 경로 목록을 반환한다.

    저장된 경로는 이후 input_chart_image_paths와 ce_chart_facts에 전달된다.
    사용자가 같은 이름의 파일을 여러 번 올려도 덮어쓰지 않도록 UUID를 붙인다.
    """
    if not uploaded_files:
        return []

    # 실행 위치가 달라도 항상 project-root/temp_uploads 아래에 저장한다.
    upload_dir = PROJECT_ROOT / "temp_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[str] = []

    for uploaded_file in uploaded_files:
        # 브라우저가 보낸 파일명에서 디렉터리 부분을 제거해 경로 조작을 방지한다.
        original_name = Path(uploaded_file.name).name
        suffix = Path(original_name).suffix.lower()
        safe_stem = Path(original_name).stem[:80] or "chart"
        # 원래 이름은 사람이 알아볼 수 있게 남기고 UUID로 충돌을 방지한다.
        saved_path = upload_dir / f"{safe_stem}_{uuid4().hex}{suffix}"
        saved_path.write_bytes(uploaded_file.getvalue())
        saved_paths.append(str(saved_path))

    return saved_paths


def make_input_state(
    news_title: str = "",
    news_body: str = "",
    chart_text: str = "",
    source_text: str = "",
    chart_image_paths: list[str] | None = None,
) -> dict[str, object]:
    """사용자 입력을 에이전트가 읽는 input_ state로 변환한다.

    기존 단일 이미지용 input_chart_image_path를 없애지 않고 유지하면서,
    새 다중 이미지용 input_chart_image_paths를 함께 제공한다.
    """
    paths = chart_image_paths or []
    return {
        # 기사 작성자가 글로 제시한 제목과 본문 주장이다.
        "input_news_title": news_title,
        "input_news_body": news_body,
        # 이미지에서 사용자가 직접 읽어 보조로 입력한 수치·축·범례·추세다.
        "input_chart_text": chart_text,
        # 시각자료의 단위, 기간, 출처, 주석 등 해석용 메타정보다.
        "input_source_text": source_text,
        # 기존 단일 경로 키는 여러 경로를 줄바꿈한 문자열로 유지한다.
        "input_chart_image_path": "\n".join(paths),
        "input_chart_image_paths": paths,
    }


def make_temp_ce_state(
    news_title: str = "",
    news_body: str = "",
    chart_text: str = "",
    chart_image_paths: list[str] | None = None,
    draft_judgement: str = "검증 제한",
    draft_summary: str = "",
) -> dict[str, object]:
    """미구현 claim_evidence_agent를 대신할 임시 ce_ state를 만든다.

    현재 프론트는 이미지 자체를 판독하지 않는다. 따라서 사용자가 입력한
    시각자료 설명과 관계 요약을 실제 ce_ 분석 결과처럼 임시 전달한다.
    """
    paths = chart_image_paths or []
    path_text = "\n".join(paths) or "업로드된 원본 이미지 없음"
    return {
        # 현재는 claim_evidence_agent가 없기 때문에 실제 이미지 판독 대신 사용자가
        # 입력한 시각자료 설명과 관계 요약을 임시 ce_ 결과로 사용한다.
        "ce_chart_facts": (
            f"원본 시각자료 이미지 경로:\n{path_text}\n"
            f"시각자료 보조 설명:\n{chart_text or '입력된 보조 설명 없음'}"
        ),
        "ce_claim_summary": f"기사 제목: {news_title}\n기사 본문 주장: {news_body}",
        "ce_strong_expressions": [],
        "ce_risk_flags": [],
        "ce_draft_judgement": draft_judgement,
        "ce_draft_summary": draft_summary,
    }


def make_temp_ig_state(
    source_text: str = "",
    chart_image_paths: list[str] | None = None,
    missing_info: list[str] | None = None,
) -> dict[str, object]:
    """시각자료 원본 해석에 필요한 정보 부족을 임시 ig_ state로 만든다.

    외부 통계 사이트를 검색하기 위한 정보가 아니라, 현재 업로드된 차트의
    기간·단위·축·범례 등을 올바르게 읽는 데 필요한 누락 정보를 나타낸다.
    """
    paths = chart_image_paths or []
    missing = missing_info or []
    has_metadata = bool(source_text.strip())
    # 원본 이미지, 메타정보, 사용자가 표시한 누락 항목 중 하나라도 부족하면
    # verdict_critic_agent가 강한 판정을 완화할 수 있도록 제한 사유를 만든다.
    has_limit = bool(missing or not paths or not has_metadata)
    return {
        "ig_metadata_status": (
            "시각자료 메타정보 입력됨" if has_metadata else "시각자료 메타정보 없음"
        ),
        "ig_found_info": source_text,
        "ig_missing_info": missing,
        "ig_limitation_reason": (
            "시각자료의 원본 이미지, 기간, 단위, 축 설명, 표본 기준, 범례 등이 부족하면 "
            "강한 판정은 제한될 수 있습니다."
            if has_limit
            else ""
        ),
        "ig_questions": [
            "뉴스 내부 원본 시각자료가 업로드되었는가?",
            "시각자료의 기간은 명확한가?",
            "시각자료의 단위와 축 설명은 명확한가?",
            "표본 기준이나 조사 대상은 명확한가?",
            "차트 하단 출처나 주석은 확인되는가?",
        ],
    }


def render_tone_message(tone: str, message: str) -> None:
    """merge_judgement_tone을 Streamlit 상태 메시지 색상으로 변환한다."""
    renderer = {
        "success": st.success,
        "warning": st.warning,
        "error": st.error,
        "info": st.info,
    }.get(tone, st.info)
    renderer(message)


def render_sidebar() -> None:
    """서비스 목적, 입력 방법, 현재 데모의 한계를 사이드바에 표시한다."""
    with st.sidebar:
        st.header("📊 데이터 체커")
        st.markdown("**서비스 목적**")
        st.write("기사 주장과 같은 뉴스 안의 원본 시각자료가 서로 맞는지 확인합니다.")
        st.markdown("**입력 가이드**")
        st.write("1. 기사 제목과 본문 주장을 입력하세요.")
        st.write("2. 뉴스 내부 원본 시각자료를 업로드하세요.")
        st.write("3. 축·범례·수치와 관계 요약을 보완하세요.")
        st.markdown("**현재 데모 한계**")
        st.caption("claim_evidence_agent와 info_gap_agent가 없어 ce_/ig_는 사용자 입력 기반 임시 값입니다.")
        st.divider()
        st.caption("사용 모델: gpt-5.4-mini")
        st.caption("API 키는 코드가 아닌 .env의 OPENAI_API_KEY에서 읽습니다.")


def render_card(title: str, body: str, caption: str = "") -> None:
    """문제·근거·요약을 동일한 모양으로 보여주는 재사용 카드다."""
    with st.container(border=True):
        st.markdown(f"#### {title}")
        st.write(body or "표시할 내용이 없습니다.")
        if caption:
            st.caption(caption)


def get_chart_image_paths(state: dict[str, Any]) -> list[str]:
    """state에서 비어 있지 않은 업로드 이미지 경로를 우선순위대로 가져온다."""
    image_paths = state.get("input_chart_image_paths")
    if isinstance(image_paths, list):
        normalized_paths = [str(path).strip() for path in image_paths if str(path).strip()]
        if normalized_paths:
            return normalized_paths

    image_path_text = state.get("input_chart_image_path")
    if isinstance(image_path_text, str):
        return [path.strip() for path in image_path_text.splitlines() if path.strip()]
    return []


def render_uploaded_chart_images(state: dict[str, Any]) -> None:
    """업로드된 원본 시각자료를 절대 경로 노출 없이 2열로 렌더링한다."""
    image_paths = get_chart_image_paths(state)
    if not image_paths:
        st.info("업로드된 원본 시각자료가 없습니다.")
        return

    for row_start in range(0, len(image_paths), 2):
        image_columns = st.columns(2)
        for column_offset, image_path in enumerate(image_paths[row_start : row_start + 2]):
            image_number = row_start + column_offset + 1
            path = Path(image_path)
            with image_columns[column_offset]:
                if path.exists():
                    st.image(
                        str(path),
                        caption=f"업로드된 뉴스 내부 원본 시각자료 {image_number}",
                        use_container_width=True,
                    )
                else:
                    file_label = path.name or f"이미지 {image_number}"
                    st.warning(f"이미지 파일을 찾을 수 없습니다: {file_label}")


def render_top_summary_cards(cards: dict[str, Any]) -> None:
    """상단 요약 카드 세 개를 같은 높이의 반응형 그리드로 표시한다."""
    card_html = []
    for card_key in ("judgement", "revision", "confidence"):
        card = cards.get(card_key, {})
        card_html.append(
            dedent(
                """\
                <section class="summary-card">
                  <div class="summary-card-title">{title}</div>
                  <div class="summary-card-status">{status}</div>
                  <div class="summary-card-description">{description}</div>
                </section>
                """
            ).format(
                title=escape(str(card.get("title", ""))),
                status=escape(str(card.get("status", ""))),
                description=escape(str(card.get("description", ""))),
            )
        )

    summary_cards_html = dedent(
        """\
        <style>
          .summary-card-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 16px;
            align-items: stretch;
            margin: 0.5rem 0 1.25rem;
          }
          .summary-card {
            box-sizing: border-box;
            height: 100%;
            min-height: 160px;
            padding: 18px 20px;
            border: 1px solid #e5e7eb;
            border-radius: 14px;
            background: #ffffff;
            box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
            overflow-wrap: anywhere;
          }
          .summary-card-title {
            margin-bottom: 12px;
            color: #64748b;
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.02em;
          }
          .summary-card-status {
            margin-bottom: 12px;
            color: #0f172a;
            font-size: 1.35rem;
            font-weight: 750;
            line-height: 1.3;
          }
          .summary-card-description {
            color: #475569;
            font-size: 0.95rem;
            line-height: 1.65;
          }
          @media (max-width: 900px) {
            .summary-card-grid {
              grid-template-columns: 1fr;
            }
          }
        </style>
        <div class="summary-card-grid">CARD_CONTENT</div>
        """
    ).replace("CARD_CONTENT", "".join(card_html))

    st.markdown(
        summary_cards_html,
        unsafe_allow_html=True,
    )


def render_service_report(state: dict[str, Any], vc_result: dict[str, Any]) -> None:
    """merge_ 중심의 사용자 리포트와 디버깅용 상세 데이터를 렌더링한다.

    일반 사용자 화면에서는 내부 키 이름을 숨기고 친숙한 제목을 사용한다.
    원본 vc_ 결과와 전체 state는 마지막 탭의 expander에서만 노출한다.
    """
    judgement = state.get("merge_user_facing_judgement", "검증 제한")
    tone = state.get("merge_judgement_tone", "info")
    headline = state.get("merge_headline", "현재 정보만으로는 판단이 제한됩니다.")

    st.divider()
    st.subheader("분석 결과")
    render_tone_message(tone, f"{judgement} · {headline}")

    render_top_summary_cards(state.get("merge_top_summary_cards", {}))

    # 결과를 목적별로 나눠 긴 보고서를 한 화면에서 훑어보기 쉽게 만든다.
    summary_tab, issue_tab, evidence_tab, detail_tab = st.tabs(
        ["결과 요약", "문제 지점", "시각자료 근거", "상세 데이터"]
    )

    with summary_tab:
        render_card("핵심 요약", state.get("merge_summary", ""))
        render_card(
            "안전한 표현",
            vc_result.get("vc_safe_expression", ""),
            "근거 수준을 넘어서 단정하지 않도록 다듬은 표현입니다.",
        )
        st.markdown("#### 권장 확인사항")
        for recommendation in state.get("merge_recommendations", []):
            st.markdown(f"- {recommendation}")
        with st.expander("완성된 Markdown 리포트 보기"):
            st.markdown(state.get("merge_final_report", ""))

    with issue_tab:
        issue_cards = state.get("merge_issue_cards", [])
        if not issue_cards:
            st.success("별도로 표시할 문제 지점이 없습니다.")
        for index, card in enumerate(issue_cards, start=1):
            with st.container(border=True):
                st.markdown(f"#### 문제 지점 {index} · {card.get('title', '기사 주장과 시각자료의 관계')}")
                st.caption(f"중요도: {card.get('severity', '주의')}")
                st.markdown("**기사 주장**")
                st.write(card.get("claim", "표시할 기사 주장이 없습니다."))
                st.markdown("**시각자료 근거**")
                st.write(card.get("visual_evidence", "표시할 시각자료 근거가 없습니다."))
                st.markdown("**판단**")
                st.write(card.get("judgement", "추가 확인이 필요합니다."))
                st.markdown("**권장 조치**")
                st.write(card.get("recommendation", "원본 시각자료를 다시 확인하세요."))

        st.markdown("#### 부족한 정보")
        missing_cards = state.get("merge_missing_info_cards", [])
        if not missing_cards:
            st.success("사용자가 표시한 부족 정보가 없습니다.")
        for card in missing_cards:
            with st.container(border=True):
                st.markdown(f"##### {card.get('title', '추가 확인 필요')}")
                for item in card.get("items", []):
                    st.markdown(f"- {item}")
                if card.get("reason"):
                    st.caption(card["reason"])

        if any(card.get("is_truncated") for card in missing_cards):
            st.info("일반 화면에는 핵심 항목만 표시했습니다. 상세 데이터에서 전체 목록을 확인할 수 있습니다.")

    with evidence_tab:
        st.subheader("뉴스 내부 원본 시각자료")
        render_uploaded_chart_images(state)

        st.subheader("시각자료 해석")
        evidence_cards = [
            card
            for card in state.get("merge_evidence_cards", [])
            if not str(card.get("title", "")).startswith("뉴스 내부 원본 시각자료")
        ]
        if not evidence_cards:
            st.info("추가로 표시할 시각자료 해석이 없습니다.")
        for card in evidence_cards:
            render_card(
                card.get("title", "시각자료 근거"),
                card.get("evidence", ""),
                card.get("interpretation", ""),
            )

    with detail_tab:
        st.markdown("#### 검토 메모")
        st.write(vc_result.get("vc_critic_notes", ""))
        with st.expander("전체 vc_ 결과 보기"):
            st.code(pformat(vc_result, sort_dicts=False), language="python")
        with st.expander("전달된 전체 state 보기"):
            st.code(pformat(state, sort_dicts=False), language="python")


def main() -> None:
    """입력 폼 구성부터 LLM 검토, 리포트 병합, 결과 표시까지 실행한다."""
    # ChatOpenAI 객체를 만들기 전에 사용자가 관리하는 .env를 읽는다.
    load_dotenv()
    # set_page_config는 다른 Streamlit 화면 요소를 만들기 전에 호출해야 한다.
    st.set_page_config(page_title="데이터 체커", page_icon="📊", layout="wide")
    render_sidebar()

    st.title("📊 데이터 체커")
    st.markdown("### 기사 주장과 뉴스 내부 원본 시각자료의 관계를 확인합니다")
    st.caption("현재 단계: verdict_critic_agent 기반 서비스형 데모")
    st.info(
        "이 서비스는 기사 본문 수치를 외부 자료와 대조하는 팩트체크가 아닙니다. "
        "같은 뉴스 안에 삽입된 원본 표·차트·그래프·도표가 기사 주장을 "
        "뒷받침하는지 확인합니다."
    )

    # form 안의 위젯 변경은 분석을 실행하지 않는다. 아래 제출 버튼을 눌렀을 때만
    # submitted=True가 되어 이미지 저장과 LLM 호출 구간으로 진입한다.
    with st.form("verdict_critic_test_form"):
        st.subheader("1. 기사 정보")
        news_title = st.text_input("기사 제목", help="뉴스 제목을 그대로 입력하세요.")
        news_body = st.text_area(
            "기사 본문 주장",
            help="기사 본문에서 글로 주장하는 내용을 입력하세요. 본문에 적힌 수치 서술도 포함합니다.",
            height=220,
        )

        st.subheader("2. 뉴스 내부 시각자료")
        st.warning(
            "외부 사이트에서 따로 찾은 자료가 아니라, 해당 뉴스에 실제 삽입된 원본 "
            "시각자료를 우선 업로드하세요. 보조 설명만으로도 테스트 실행은 가능합니다."
        )
        uploaded_files = st.file_uploader(
            "뉴스 내부 시각자료 원본 업로드",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            help="뉴스 안에 실제로 삽입된 표·차트·그래프·도표 이미지를 업로드하세요.",
        )
        if uploaded_files:
            # 한 행에 최대 세 장씩 배치하고, 이미지가 더 많으면 열을 순환해 표시한다.
            preview_columns = st.columns(min(3, len(uploaded_files)))
            for index, uploaded_file in enumerate(uploaded_files):
                with preview_columns[index % len(preview_columns)]:
                    st.image(
                        uploaded_file,
                        caption=f"업로드된 뉴스 내부 원본 시각자료 {index + 1}",
                    )

        chart_text = st.text_area(
            "선택 사항: 시각자료에서 읽은 수치/설명",
            help=(
                "원본 시각자료에서 읽은 수치, 축, 범례, 추세를 입력하세요. "
                "기사 본문의 수치를 복사하는 칸이 아닙니다."
            ),
            placeholder=(
                "차트 제목: 연도별 청년 실업률\n단위: %\n2022년 6.4\n"
                "2023년 6.1\n2024년 5.9\n그래프는 2022년부터 2024년까지 하락 흐름을 보임"
            ),
            height=150,
        )
        source_text = st.text_area(
            "시각자료 출처/주석/단위",
            help="차트 하단 출처, 단위, 기간, 축 설명, 범례, 표본 기준 등을 입력하세요.",
            placeholder=(
                "출처: 통계청 고용동향\n단위: %\n기간: 2022년~2024년\n"
                "축 설명: X축은 연도, Y축은 실업률"
            ),
            height=120,
        )

        st.subheader("3. 임시 분석 정보")
        draft_judgement = st.selectbox("임시 초안 판정", JUDGEMENTS)
        draft_summary = st.text_area(
            "기사 주장과 시각자료의 관계 요약",
            help="기사 본문 주장이 업로드한 원본 시각자료와 어떻게 맞거나 어긋나는지 입력하세요.",
            placeholder=(
                "기사 본문은 청년 실업률이 상승했다고 표현하지만, 업로드한 차트는 "
                "2022년 6.4%, 2023년 6.1%, 2024년 5.9%로 하락 흐름을 보여줍니다."
            ),
            height=120,
        )
        missing_info_text = st.text_input(
            "시각자료 해석에 부족한 정보",
            help="원본 이미지, 차트 제목, 단위, 기간, 축, 범례, 표본 기준 등을 쉼표로 구분하세요.",
            placeholder="원본 차트 이미지, 차트 기간, 단위, 표본 기준, 축 설명, 범례",
        )

        st.subheader("4. 실행")
        submitted = st.form_submit_button("분석 실행", type="primary", use_container_width=True)

    # 이 블록 밖에서는 make_real_llm()과 verdict_critic_node()를 호출하지 않는다.
    # 따라서 파일 선택이나 텍스트 입력으로 발생한 일반 rerun은 비용을 발생시키지 않는다.
    if submitted:
        # 필수 입력을 먼저 검사해야 잘못된 요청에서 파일 저장이나 LLM 호출이 일어나지 않는다.
        if not news_title.strip():
            st.error("기사 제목을 입력해 주세요.")
            st.stop()
        if not news_body.strip():
            st.error("기사 본문 주장을 입력해 주세요.")
            st.stop()
        if not uploaded_files and not chart_text.strip():
            st.error("뉴스 내부 시각자료를 업로드하거나 시각자료 보조 설명을 입력해 주세요.")
            st.stop()

        # 쉼표 입력을 ig_missing_info가 사용하는 문자열 목록으로 정규화한다.
        missing_info = [item.strip() for item in missing_info_text.split(",") if item.strip()]

        # 검증을 통과한 뒤에만 업로드 파일을 로컬 임시 폴더에 저장한다.
        chart_image_paths = save_uploaded_chart_images(uploaded_files)

        # 에이전트별 책임을 구분하기 위해 input_, 임시 ce_, 임시 ig_ state를
        # 각각 만든 다음 하나의 전체 state로 병합한다.
        input_state = make_input_state(
            news_title,
            news_body,
            chart_text,
            source_text,
            chart_image_paths,
        )
        ce_state = make_temp_ce_state(
            news_title,
            news_body,
            chart_text,
            chart_image_paths,
            draft_judgement,
            draft_summary,
        )
        ig_state = make_temp_ig_state(source_text, chart_image_paths, missing_info)
        state = {**input_state, **ce_state, **ig_state}

        # 실제 비용이 발생할 수 있는 LLM 호출은 제출된 이 지점에서 한 번만 수행한다.
        llm = make_real_llm()
        verdict_critic_node = make_verdict_critic_node(llm)
        with st.spinner("기사 주장과 시각자료의 관계를 검토하고 있습니다..."):
            vc_result = verdict_critic_node(state)

        # verdict_critic_agent는 vc_ 키만 반환한다. 이를 전체 state에 합친 뒤,
        # deterministic 병합 노드가 사용자용 merge_ 리포트를 생성한다.
        state = {**state, **vc_result}
        merge_result = build_service_report(state)
        state = {**state, **merge_result}
        # Streamlit은 위젯 조작 때마다 스크립트를 다시 실행한다. 결과를 session_state에
        # 보관하면 탭 이동이나 입력 수정 후에도 LLM을 다시 호출하지 않고 결과를 유지한다.
        st.session_state["latest_analysis"] = {
            "state": state,
            "vc_result": vc_result,
        }

    # 이번 실행에서 새 분석이 없더라도 이전에 성공한 최신 리포트를 다시 그린다.
    latest_analysis = st.session_state.get("latest_analysis")
    if latest_analysis:
        render_service_report(
            latest_analysis["state"],
            latest_analysis["vc_result"],
        )


if __name__ == "__main__":
    main()
