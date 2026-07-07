# 실행:
# C:\THIRD_LLM에서 실행:
# uv run streamlit run frontend/streamlit_app.py

"""claim_evidence_agent와 verdict_critic_agent를 연결한 데이터 체커 데모."""

import logging
import sys
from hashlib import sha256
from html import escape
from pathlib import Path
from pprint import pformat
from textwrap import dedent
from typing import Any, Mapping
from uuid import uuid4


# 협업 프론트엔드는 저장소 최상위에 둔다. 실행 위치와 관계없이 공용 임시 파일과
# 설정의 기준이 C:\THIRD_LLM이 되도록 저장소 루트를 계산한다.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from common.state.news_chart_check_state import NewsChartCheckState
from first_agent.ce_agent.agents.claim_evidence_agent import (
    pick_ce_only,
    run_claim_evidence_agent,
)
from first_agent.ce_agent.nodes.claim_chart_compare_node import extract_chart_points
from third_agent.vc_agent.agents.verdict_critic_agent import (
    build_verdict_critic_graph,
    pick_vc_only,
)
from frontend.html_ingestion import (
    AccessRestrictedError,
    FormPrefill,
    ImageCandidate,
    download_image_from_url,
    select_chart_image_candidates,
    extract_text_blocks_from_html,
    fetch_html_from_url,
    get_ingestion_error_message,
    prefill_form_from_text_blocks,
    read_html_from_upload,
    summarize_extraction,
)
from frontend.ingestion_outcome import (
    IngestionOutcome,
    build_failure_outcome,
    classify_extraction_outcome,
)
from frontend.technology_architecture import get_technology_architectures
from third_agent.vc_agent.nodes.report_merge_node import build_service_report


LOGGER = logging.getLogger(__name__)


# verdict_critic_agent와 화면의 판정 선택지가 서로 달라지지 않도록
# 허용되는 네 가지 판정값을 한곳에서 관리한다.
JUDGEMENTS = (
    "대체로 뒷받침됨",
    "주의 필요",
    "검증 제한",
    "왜곡 가능성 높음",
)

FORM_FIELD_KEYS = {
    "news_title": "form_news_title",
    "news_body": "form_news_body",
    "chart_text": "form_chart_text",
    "source_text": "form_source_text",
    "draft_judgement": "form_draft_judgement",
    "claim_chart_summary": "form_draft_summary",
    "missing_info": "form_missing_info",
}


def apply_prefill_to_session(
    prefill: FormPrefill | Mapping[str, str],
) -> list[str]:
    """자동 추출값을 기존 위젯 상태에 넣고 비어 있는 필드명을 반환한다."""
    missing_fields = []
    for field, session_key in FORM_FIELD_KEYS.items():
        value = prefill.get(field, "")
        if field == "draft_judgement" and value not in JUDGEMENTS:
            value = "검증 제한"
        st.session_state[session_key] = value
        if not str(value).strip() and field not in {"claim_chart_summary", "missing_info"}:
            missing_fields.append(field)
    return missing_fields


def render_extraction_summary(summary: dict[str, Any]) -> None:
    """자동 추출 범위와 사용자가 확인할 누락 항목을 간단히 표시한다."""
    st.caption(
        "자동 추출 결과 · "
        f"본문 {summary.get('body_paragraph_count', 0)}개 문단 · "
        f"시각자료 관련 텍스트 {summary.get('visual_text_count', 0)}개 · "
        f"표·차트 후보 {summary.get('chart_candidate_count', summary.get('image_candidate_count', 0))}개 "
        f"(전체 이미지 {summary.get('image_candidate_count', 0)}개) · "
        f"출처·단위 후보 {summary.get('source_candidate_count', 0)}개 · "
        f"본문 추출 신뢰도 {summary.get('extraction_confidence', '낮음')}"
    )
    missing = summary.get("missing_fields", [])
    if missing:
        st.warning(
            "자동으로 확인하지 못한 항목: " + ", ".join(str(item) for item in missing)
            + ". 아래 입력 폼에서 직접 보완해주세요."
        )


def render_ingestion_outcome(outcome: IngestionOutcome) -> None:
    """자동 입력 상태를 네 가지 사용자 안내 중 하나로 표시한다."""
    status = outcome["status"]
    if status == "success":
        st.success(outcome["message"])
    elif status == "uncertain":
        st.warning(outcome["message"])
    else:
        # 접근 제한과 기술적 불러오기 실패는 문구로 구분하되 모두 오류로 표시한다.
        st.error(outcome["message"])


def _candidate_widget_key(url: str) -> str:
    return "article_image_candidate_" + sha256(url.encode("utf-8")).hexdigest()[:16]


def clear_article_image_candidate_state(candidates: list[ImageCandidate]) -> None:
    """새 원문을 불러올 때 이전 이미지 후보 선택 상태를 제거한다."""
    for candidate in candidates:
        st.session_state.pop(_candidate_widget_key(candidate["url"]), None)


def render_article_image_candidates(candidates: list[ImageCandidate]) -> list[str]:
    """규칙 기반으로 선별한 표·차트 후보와 선택 근거를 보여준다."""
    chart_candidates = select_chart_image_candidates(candidates)
    if not candidates:
        return []
    st.markdown("#### 기사에서 선별한 표·차트 후보")
    if not chart_candidates:
        st.info("기사 이미지에서 표·차트 후보를 찾지 못했습니다. 필요한 이미지는 직접 업로드해주세요.")
        return []
    st.info(
        "HTML의 캡션·대체텍스트·위치 정보를 이용해 사진·프로필·광고를 제외한 후보입니다. "
        "최종 검토할 시각자료를 선택해주세요."
    )
    selected_urls: list[str] = []
    columns = st.columns(min(3, len(chart_candidates)))
    for index, candidate in enumerate(chart_candidates):
        with columns[index % len(columns)]:
            st.image(
                candidate["url"],
                caption=candidate["label"],
                width="stretch",
            )
            if st.checkbox(
                f"시각자료 후보 {index + 1} 선택",
                key=_candidate_widget_key(candidate["url"]),
            ):
                selected_urls.append(candidate["url"])
            if candidate["caption"]:
                st.caption(candidate["caption"])
            reasons = candidate.get("selection_reasons", [])
            if reasons:
                st.caption("선별 이유: " + " ".join(reasons))
    return selected_urls


def make_real_llm() -> ChatOpenAI:
    """실제 verdict 검토에 사용할 OpenAI 모델을 생성한다.

    API 키를 인자로 직접 받지 않는 이유는 main()에서 load_dotenv()를 먼저
    호출한 뒤, ChatOpenAI가 환경 변수 OPENAI_API_KEY를 읽도록 하기 위해서다.
    GPT-5 계열 모델에서는 temperature=0이 지원되지 않아 값을 별도로 지정하지 않는다.
    """
    return ChatOpenAI(
        model="gpt-5.4-mini",
        temperature=0,
        max_retries=2,
    )


def run_verdict_critic_graph(llm: Any, state: dict[str, Any]) -> dict[str, Any]:
    """실제 앱과 테스트가 동일한 LangGraph 실행 경로를 사용하게 한다."""
    # 에이전트 빌더는 실행 가능한 LangGraph 객체를 반환하지만 외부 모듈의 반환
    # 타입이 선언되어 있지 않다. 여기서 Any로 경계를 명시해 Pylance가 그래프의
    # invoke 메서드를 Unknown으로 전파하지 않게 한다.
    graph: Any = build_verdict_critic_graph(llm)
    graph_result: dict[str, Any] = graph.invoke(state)
    # 컴파일된 그래프는 전체 state를 반환하므로 화면과 병합 노드에는 vc_만 전달한다.
    return pick_vc_only(graph_result)


def save_uploaded_chart_images(uploaded_files: list[Any] | None) -> list[str]:
    """업로드 이미지를 충돌하지 않는 이름으로 저장하고 경로 목록을 반환한다.

    저장된 경로는 이후 input_chart_image_paths와 ce_chart_facts에 전달된다.
    사용자가 같은 이름의 파일을 여러 번 올려도 덮어쓰지 않도록 UUID를 붙인다.
    """
    if not uploaded_files:
        return []

    # 실행 위치가 달라도 항상 저장소 공용 temp_uploads 아래에 저장한다.
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


def save_remote_chart_images(image_urls: list[str]) -> tuple[list[str], list[str]]:
    """사용자가 선택한 기사 이미지 후보를 안전하게 내려받아 저장한다."""
    if not image_urls:
        return [], []
    upload_dir = PROJECT_ROOT / "temp_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[str] = []
    errors: list[str] = []
    for index, url in enumerate(image_urls, start=1):
        try:
            downloaded = download_image_from_url(url)
            saved_path = upload_dir / (
                f"article_image_{index}_{uuid4().hex}{downloaded['suffix']}"
            )
            saved_path.write_bytes(downloaded["data"])
            saved_paths.append(str(saved_path))
        except Exception:
            LOGGER.warning("선택한 기사 이미지 다운로드 실패", exc_info=True)
            errors.append(f"시각자료 후보 {index}")
    return saved_paths, errors


def make_input_state(
    news_title: str = "",
    news_body: str = "",
    chart_text: str = "",
    source_text: str = "",
    chart_image_paths: list[str] | None = None,
) -> NewsChartCheckState:
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


def run_claim_evidence(
    state: NewsChartCheckState, llm: Any | None = None
) -> dict[str, Any]:
    """ce_agent LangGraph를 실행하고 다음 단계에 전달할 ce_만 반환한다."""
    return pick_ce_only(run_claim_evidence_agent(state, llm))


def get_chart_input_issues(chart_text: str) -> list[str]:
    """현재 first_agent가 비교하기 어려운 차트 입력 조건을 설명한다."""
    if not chart_text.strip():
        return [
            "현재는 이미지 OCR을 지원하지 않습니다. 차트에서 직접 읽은 연도·값·단위를 입력해주세요."
        ]

    points = extract_chart_points(chart_text)
    issues: list[str] = []
    if len(points) < 2:
        issues.append("비교하려면 연도와 값이 포함된 시점을 최소 2개 입력해야 합니다.")
    if points and any(not point.unit for point in points):
        issues.append("일부 수치의 단위가 없습니다. 각 값 뒤에 동일한 단위를 입력해주세요.")
    units = {point.unit for point in points if point.unit}
    if len(units) > 1:
        issues.append("시점별 단위가 서로 다릅니다. 같은 단위로 맞춰주세요.")
    return issues


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
        st.write("3. 축·범례·수치와 누락 정보를 보완하세요.")
        st.markdown("**현재 데모 한계**")
        st.caption(
            "claim_evidence_agent는 LangGraph와 gpt-5.4-mini structured output을 사용하며, "
            "수치 비교·판정은 규칙 기반으로 보호됩니다. "
            "info_gap_agent의 ig_만 사용자 입력 기반 임시 값입니다."
        )
        with st.expander("기술 아키텍처"):
            for architecture in get_technology_architectures():
                st.markdown(
                    f"**{architecture['name']} · {architecture['status']}**"
                )
                st.caption(architecture["purpose"])
                st.code(" → ".join(architecture["flow"]), language=None)
                st.caption("인계: " + architecture["handoff"])
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
    summary_tab, first_analysis_tab, issue_tab, evidence_tab, detail_tab = st.tabs(
        ["결과 요약", "first_agent 분석", "문제 지점", "시각자료 근거", "상세 데이터"]
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

    with first_analysis_tab:
        st.caption(
            "first_agent가 third_agent에 전달한 여섯 개의 ce_ 출력입니다. "
            "표시 순서는 출력 계약과 같습니다."
        )
        render_card(
            "1. 차트에서 확인한 사실",
            "\n".join(
                f"- {item}" for item in state.get("ce_chart_facts", [])
            ) or "차트에서 확인된 사실이 없습니다.",
        )
        render_card(
            "2. 기사 제목·본문의 핵심 주장",
            state.get("ce_claim_summary", "기사 핵심 주장을 확인하지 못했습니다."),
        )
        render_card(
            "3. 강한 표현",
            "\n".join(
                f"- {item}" for item in state.get("ce_strong_expressions", [])
            ) or "발견된 강한 표현이 없습니다.",
        )
        render_card(
            "4. 위험 신호",
            "\n".join(
                f"- {item}" for item in state.get("ce_risk_flags", [])
            ) or "표시할 위험 신호가 없습니다.",
        )
        render_card(
            "5. 1차 판정",
            state.get("ce_draft_judgement", "검증 제한"),
            "기사 주장과 입력된 시각자료를 비교한 first_agent의 보수적인 초안 판정입니다.",
        )
        render_card(
            "6. 1차 판정 이유",
            state.get("ce_draft_summary", "판정 이유를 생성하지 못했습니다."),
        )

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
    st.caption("현재 단계: claim_evidence_agent → verdict_critic_agent 연결 데모")
    st.info(
        "이 서비스는 기사 본문 수치를 외부 자료와 대조하는 팩트체크가 아닙니다. "
        "같은 뉴스 안에 삽입된 원본 표·차트·그래프·도표가 기사 주장을 "
        "뒷받침하는지 확인합니다."
    )

    st.subheader("0. 뉴스 원문 불러오기")
    st.caption(
        "뉴스 기사 URL 또는 스크랩 HTML 파일을 사용할 수 있습니다. 둘 다 입력하면 "
        "업로드한 HTML 파일을 우선하며, 자동 입력된 내용은 아래에서 직접 수정할 수 있습니다."
    )
    article_url = st.text_input(
        "뉴스 기사 URL",
        key="article_source_url",
        placeholder="https://news.example.com/article",
    )
    uploaded_html = st.file_uploader(
        "또는 스크랩 HTML 파일 업로드",
        type=["html", "htm"],
        key="article_html_upload",
    )
    load_article = st.button("기사 원문 불러오기", use_container_width=True)

    if load_article:
        # 이전 성공 결과가 새 실패 안내와 함께 남지 않도록 이번 요청 상태를 초기화한다.
        clear_article_image_candidate_state(
            st.session_state.get("latest_article_image_candidates", [])
        )
        st.session_state.pop("latest_prefill_source", None)
        st.session_state.pop("latest_extraction_summary", None)
        st.session_state.pop("latest_article_image_candidates", None)
        st.session_state.pop("latest_ingestion_outcome", None)
        if not uploaded_html and not article_url.strip():
            st.warning("뉴스 기사 URL을 입력하거나 스크랩 HTML 파일을 업로드해주세요.")
        else:
            try:
                with st.spinner("기사 HTML에서 입력 항목을 추출하고 있습니다..."):
                    # 변경: URL은 분석 텍스트로 사용하지 않는다. 업로드 HTML을 우선하고,
                    # URL만 있을 때에만 서버에서 HTML을 가져온 뒤 동일 파서에 전달한다.
                    html = (
                        read_html_from_upload(uploaded_html)
                        if uploaded_html
                        else fetch_html_from_url(article_url)
                    )
                    blocks = extract_text_blocks_from_html(
                        html,
                        base_url="" if uploaded_html else article_url,
                    )
                    prefill: FormPrefill = prefill_form_from_text_blocks(blocks)
                    extraction_summary = summarize_extraction(blocks)
                    outcome: IngestionOutcome = classify_extraction_outcome(
                        prefill,
                        extraction_summary,
                    )
                    # 분류 단계에서 문자열로 정규화된 값을 세션에도 동일하게 적용한다.
                    # 반환되는 누락 필드 목록은 outcome.summary가 사용자에게 안내한다.
                    _missing_form_fields = apply_prefill_to_session(outcome["prefill"])
                st.session_state["latest_prefill_source"] = (
                    "업로드한 HTML 파일" if uploaded_html else "뉴스 기사 URL의 HTML"
                )
                st.session_state["latest_extraction_summary"] = extraction_summary
                st.session_state["latest_ingestion_outcome"] = outcome
                st.session_state["latest_article_image_candidates"] = blocks.get(
                    "image_candidates", []
                )
            except Exception as error:
                # 현재 한계: 사이트별 차단·로그인·동적 렌더링 실패를 여기서 복구할 수
                # 없으므로 앱을 중단하지 않고 기존 수동 입력 흐름으로 되돌린다.
                # 세부 실패 유형과 향후 처리 방향은 docs/frontend_url_html_handoff.md 참조.
                # 사용자 화면에는 내부 주소나 예외 상세를 노출하지 않되, 운영자가
                # 실패 유형을 추적할 수 있도록 서버 로그에는 예외 정보를 남긴다.
                LOGGER.warning("기사 HTML 자동 입력 처리 실패", exc_info=True)
                message = get_ingestion_error_message(error)
                status = (
                    "access_restricted"
                    if isinstance(error, AccessRestrictedError)
                    else "fetch_failed"
                )
                st.session_state["latest_ingestion_outcome"] = build_failure_outcome(
                    status, message
                )

    latest_outcome = st.session_state.get("latest_ingestion_outcome")
    if latest_outcome:
        render_ingestion_outcome(latest_outcome)

    if st.session_state.get("latest_prefill_source"):
        st.info(f"최근 자동 입력 출처: {st.session_state['latest_prefill_source']}")
        render_extraction_summary(st.session_state.get("latest_extraction_summary", {}))

    selected_article_image_urls = render_article_image_candidates(
        st.session_state.get("latest_article_image_candidates", [])
    )

    # form 안의 위젯 변경은 분석을 실행하지 않는다. 아래 제출 버튼을 눌렀을 때만
    # submitted=True가 되어 이미지 저장과 LLM 호출 구간으로 진입한다.
    with st.form("verdict_critic_test_form"):
        st.subheader("1. 기사 정보")
        news_title = st.text_input(
            "기사 제목", key="form_news_title", help="뉴스 제목을 그대로 입력하세요."
        )
        news_body = st.text_area(
            "기사 본문 주장",
            key="form_news_body",
            help="기사 본문에서 글로 주장하는 내용을 입력하세요. 본문에 적힌 수치 서술도 포함합니다.",
            height=220,
        )

        st.subheader("2. 뉴스 내부 시각자료")
        st.warning(
            "외부 사이트에서 따로 찾은 자료가 아니라, 해당 뉴스에 실제 삽입된 원본 "
            "시각자료를 우선 업로드하세요. 보조 설명만으로도 테스트 실행은 가능합니다."
        )
        if selected_article_image_urls:
            st.markdown("**기사에서 선택한 원본 시각자료**")
            selected_columns = st.columns(min(3, len(selected_article_image_urls)))
            for index, image_url in enumerate(selected_article_image_urls):
                with selected_columns[index % len(selected_columns)]:
                    st.image(image_url, caption=f"기사에서 자동 입력된 시각자료 {index + 1}")
            st.caption(
                f"선택한 {len(selected_article_image_urls)}개 이미지는 분석 시 직접 업로드 파일과 함께 처리됩니다."
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
            "시각자료에서 읽은 수치/설명",
            key="form_chart_text",
            help=(
                "원본 시각자료에서 읽은 값을 '연도 + 항목 + 값 + 단위' 형식으로 "
                "최소 두 시점 입력하세요. 현재 이미지 OCR은 지원하지 않습니다."
            ),
            placeholder=(
                "차트 제목: 연도별 수출액\n"
                "2024년 수출 100억달러\n"
                "2025년 수출 92억달러"
            ),
            height=150,
        )
        chart_input_issues = get_chart_input_issues(chart_text)
        if chart_text.strip() and not chart_input_issues:
            parsed_points = extract_chart_points(chart_text)
            st.success(
                f"first_agent 비교 형식 확인 · {len(parsed_points)}개 시점 · "
                f"{parsed_points[0].unit} 단위"
            )
        elif chart_text.strip():
            for issue in chart_input_issues:
                st.warning(issue)
        else:
            st.caption(
                "입력 예: 2024년 수출 100억달러 / 2025년 수출 92억달러"
            )
        source_text = st.text_area(
            "시각자료 출처/주석/단위",
            key="form_source_text",
            help="차트 하단 출처, 단위, 기간, 축 설명, 범례, 표본 기준 등을 입력하세요.",
            placeholder=(
                "출처: 통계청 고용동향\n단위: %\n기간: 2022년~2024년\n"
                "축 설명: X축은 연도, Y축은 실업률"
            ),
            height=120,
        )

        st.subheader("3. 분석 보완 정보")
        st.caption(
            "1차 판정과 관계 요약은 first_agent가 자동 생성합니다. "
            "현재 미구현인 정보부족 에이전트를 대신해 누락 정보만 직접 입력합니다."
        )
        missing_info_text = st.text_input(
            "시각자료 해석에 부족한 정보",
            key="form_missing_info",
            help="원본 이미지, 차트 제목, 단위, 기간, 축, 범례, 표본 기준 등을 쉼표로 구분하세요.",
            placeholder="원본 차트 이미지, 차트 기간, 단위, 표본 기준, 축 설명, 범례",
        )

        st.subheader("4. 실행")
        submitted = st.form_submit_button(
            "기사 근거 검증하기", type="primary", use_container_width=True
        )

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
        if not chart_text.strip():
            st.error(
                "현재 first_agent는 이미지 OCR을 지원하지 않습니다. "
                "시각자료에서 읽은 연도·값·단위를 직접 입력해 주세요."
            )
            st.stop()

        # 쉼표 입력을 ig_missing_info가 사용하는 문자열 목록으로 정규화한다.
        missing_info = [item.strip() for item in missing_info_text.split(",") if item.strip()]

        # 검증을 통과한 뒤에만 업로드 파일을 로컬 임시 폴더에 저장한다.
        chart_image_paths = save_uploaded_chart_images(uploaded_files)
        remote_image_paths, remote_image_errors = save_remote_chart_images(
            selected_article_image_urls
        )
        chart_image_paths.extend(remote_image_paths)
        if remote_image_errors:
            st.warning(
                ", ".join(remote_image_errors)
                + " 이미지를 가져오지 못했습니다. 필요한 경우 파일로 직접 업로드해주세요."
            )

        input_state = make_input_state(
            news_title,
            news_body,
            chart_text,
            source_text,
            chart_image_paths,
        )
        ig_state = make_temp_ig_state(source_text, chart_image_paths, missing_info)

        # ce_agent와 vc_agent는 동일한 gpt-5.4-mini 인스턴스를 순서대로 사용한다.
        # 모델 초기화가 실패해도 ce_agent는 규칙 기반 fallback으로 실행한다.
        try:
            llm = make_real_llm()
        except Exception:
            LOGGER.exception("OpenAI 모델 초기화 실패")
            llm = None

        # first_agent의 ce_ 결과를 만든 뒤 동일 state를 third_agent에 전달한다.
        try:
            with st.spinner("기사 주장과 시각자료의 1차 관계를 분석하고 있습니다..."):
                ce_state = run_claim_evidence(input_state, llm)
        except Exception:
            LOGGER.exception("first_agent 주장-근거 분석 실패")
            st.error("1차 주장-근거 분석을 실행하지 못했습니다. 입력 내용을 확인해주세요.")
            st.stop()

        state = {**input_state, **ce_state, **ig_state}

        # 실제 비용이 발생할 수 있는 LLM 호출은 third_agent 단계에서 한 번만 수행한다.
        # API 키 누락, 모델 초기화 실패, 일시적인 네트워크 오류가 발생하더라도
        # Streamlit 앱 전체가 traceback과 함께 중단되지 않도록 실행 경계를 둔다.
        try:
            if llm is None:
                raise RuntimeError("OpenAI 모델을 초기화하지 못했습니다.")
            with st.spinner("기사 주장과 시각자료의 관계를 검토하고 있습니다..."):
                vc_result = run_verdict_critic_graph(llm, state)
        except Exception:
            LOGGER.exception("최종판정 검토 모델 실행 실패")
            st.error(
                "검토 모델을 실행하지 못했습니다. .env의 OPENAI_API_KEY와 "
                "네트워크 연결을 확인한 뒤 다시 시도해주세요."
            )
            st.stop()

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
