"""에이전트 state를 사용자 친화적인 서비스 리포트로 병합한다.

이 모듈은 외부 검색이나 LLM 호출 없이 input_, ce_, ig_, vc_ 값을 읽고
merge_ 키만 생성한다.
"""

from __future__ import annotations

from typing import Any


TONE_BY_JUDGEMENT = {
    "대체로 뒷받침됨": "success",
    "주의 필요": "warning",
    "검증 제한": "info",
    "왜곡 가능성 높음": "error",
}

HEADLINE_BY_JUDGEMENT = {
    "대체로 뒷받침됨": "기사의 핵심 주장은 제공된 시각자료와 대체로 일치합니다.",
    "주의 필요": "일부 근거는 확인되지만 표현 범위나 해석에 주의가 필요합니다.",
    "검증 제한": "현재 시각자료 정보만으로는 기사 주장을 충분히 판단하기 어렵습니다.",
    "왜곡 가능성 높음": "기사 주장과 시각자료 사이에 뚜렷한 불일치 가능성이 있습니다.",
}

CONFIDENCE_BY_JUDGEMENT = {
    "대체로 뒷받침됨": (
        "충분한 근거",
        "입력된 시각자료가 기사 주장의 핵심 범위를 비교적 잘 뒷받침합니다.",
    ),
    "주의 필요": (
        "제한적 검토",
        "일부 주장은 확인되지만, 표현의 강도나 범위를 판단하려면 추가 확인이 필요합니다.",
    ),
    "검증 제한": (
        "추가 정보 필요",
        "현재 입력된 시각자료와 보조 설명만으로는 충분한 판단이 어렵습니다.",
    ),
    "왜곡 가능성 높음": (
        "충돌 가능성 높음",
        "기사 표현과 시각자료가 보여주는 내용 사이에 뚜렷한 차이가 있을 수 있습니다.",
    ),
}

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


def _as_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [text for item in value if (text := _as_text(item))]
    text = _as_text(value)
    return [text] if text else []


def _missing_info_level(state: dict[str, Any]) -> str:
    """상단 신뢰도 카드용으로 누락 정보를 없음·보조·핵심으로 구분한다."""
    items = _as_string_list(state.get("ig_missing_info"))
    if not items:
        return "none"

    has_core = False
    for item in items:
        if any(keyword in item for keyword in AUXILIARY_MISSING_INFO_KEYWORDS):
            continue
        if any(keyword in item for keyword in CORE_MISSING_INFO_KEYWORDS):
            has_core = True
            break
    return "core" if has_core else "auxiliary"


def _image_paths(state: dict[str, Any]) -> list[str]:
    paths = state.get("input_chart_image_paths")
    if isinstance(paths, list):
        return [str(path) for path in paths if str(path).strip()]
    return [line.strip() for line in _as_text(state.get("input_chart_image_path")).splitlines() if line.strip()]


def _redact_image_paths(value: Any, state: dict[str, Any]) -> str:
    """일반 사용자용 문구에서 업로드 이미지의 로컬 경로를 제거한다."""
    text = _as_text(value)
    for path in _image_paths(state):
        text = text.replace(path, "")

    # 현재 임시 ce_ 값에 붙는 개발자용 레이블도 사용자 화면에서는 숨긴다.
    public_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and line.strip() != "원본 시각자료 이미지 경로:"
    ]
    return "\n".join(public_lines)


def _public_visual_evidence(state: dict[str, Any]) -> str:
    """경로 대신 보조 설명과 업로드 개수를 사용한 사용자용 근거를 만든다."""
    paths = _image_paths(state)
    chart_text = _redact_image_paths(state.get("input_chart_text"), state)
    if chart_text:
        if paths:
            return f"업로드된 원본 시각자료 {len(paths)}개와 보조 설명을 기준으로 검토했습니다.\n{chart_text}"
        return chart_text

    chart_facts = _redact_image_paths(state.get("ce_chart_facts"), state)
    chart_facts = chart_facts.replace("시각자료 보조 설명:", "").strip()
    chart_facts = chart_facts.replace("입력된 보조 설명 없음", "").strip()
    if chart_facts:
        return chart_facts
    if paths:
        return f"업로드된 원본 시각자료 {len(paths)}개를 기준으로 검토했습니다. 세부 수치와 추세에 대한 보조 설명은 입력되지 않았습니다."
    return "구체적으로 정리된 시각자료 근거가 없습니다."


def _first_sentence(value: Any) -> str:
    """요약문에서 상단 카드에 사용할 첫 문장만 반환한다."""
    text = _as_text(value)
    if not text:
        return ""
    for marker in (". ", "。", "\n"):
        if marker in text:
            first, _ = text.split(marker, 1)
            return f"{first.strip()}." if marker == ". " else first.strip()
    return text


def build_top_summary_cards(state: dict[str, Any]) -> dict[str, dict[str, str]]:
    """일반 사용자용 상단 요약 카드 세 개를 만든다."""
    judgement = (
        _as_text(state.get("vc_recommended_judgement"))
        or _as_text(state.get("merge_user_facing_judgement"))
        or "검증 제한"
    )
    if judgement not in HEADLINE_BY_JUDGEMENT:
        judgement = "검증 제한"

    judgement_description = (
        _first_sentence(state.get("merge_headline"))
        or _first_sentence(state.get("merge_summary"))
        or HEADLINE_BY_JUDGEMENT[judgement]
    )

    if judgement == "검증 제한":
        revision_status = "신중한 표현 필요"
        revision_description = "시각자료의 기간, 단위, 표본 기준 등이 부족해 단정적인 표현은 피하는 것이 좋습니다."
    elif state.get("vc_revision_needed") is True:
        revision_status = "표현 완화 권장"
        revision_description = "기사 제목이나 본문의 표현이 시각자료가 보여주는 범위보다 강해, 더 중립적인 표현으로 조정하는 것이 좋습니다."
    else:
        revision_status = "추가 조정 불필요"
        revision_description = "현재 표현은 입력된 시각자료의 범위와 크게 충돌하지 않습니다."

    confidence_status, confidence_description = CONFIDENCE_BY_JUDGEMENT[judgement]
    missing_info_level = _missing_info_level(state)
    if judgement == "대체로 뒷받침됨" and missing_info_level == "auxiliary":
        confidence_status = "보조 정보 확인 권장"
        confidence_description = (
            "핵심 주장은 시각자료로 확인되지만, 세부 해석을 위해 추가 정보 확인이 권장됩니다."
        )
    elif judgement == "대체로 뒷받침됨" and missing_info_level == "core":
        confidence_status = "핵심 정보 일부 확인 필요"
        confidence_description = (
            "시각자료가 핵심 방향을 뒷받침하지만, 일부 핵심 조건은 추가로 확인하는 것이 좋습니다."
        )
    return {
        "judgement": {
            "title": "권장 판정",
            "status": judgement,
            "description": judgement_description,
        },
        "revision": {
            "title": "문구 조정",
            "status": revision_status,
            "description": revision_description,
        },
        "confidence": {
            "title": "검증 신뢰도",
            "status": confidence_status,
            "description": confidence_description,
        },
    }


def build_issue_cards(state: dict[str, Any]) -> list[dict[str, str]]:
    """판정 이유를 사용자가 빠르게 훑을 수 있는 구조화 카드로 정리한다."""
    cards: list[dict[str, str]] = []
    judgement = _as_text(state.get("vc_recommended_judgement")) or "검증 제한"
    claim = _as_text(state.get("ce_claim_summary")) or _as_text(state.get("input_news_title"))
    visual_evidence = _public_visual_evidence(state)
    draft_summary = _as_text(state.get("ce_draft_summary"))
    revision_reason = _as_text(state.get("vc_revision_reason"))
    safe_expression = _as_text(state.get("vc_safe_expression"))
    critic_notes = _as_text(state.get("vc_critic_notes"))

    severity = {
        "왜곡 가능성 높음": "높음",
        "검증 제한": "제한",
    }.get(judgement, "주의")

    # 자동 문장 분해를 과신하지 않고, 현재 확보된 관계 요약을 먼저 한 장의
    # 공통 카드로 만든다. 값이 부족해도 아래 fallback 문구로 필드를 유지한다.
    cards.append(
        {
            "title": "기사 주장과 시각자료의 관계",
            "severity": severity,
            "claim": claim or "구체적으로 정리된 기사 주장이 없습니다.",
            "visual_evidence": visual_evidence,
            "judgement": revision_reason or draft_summary or critic_notes or "현재 입력만으로는 문제 지점을 세부적으로 구분하기 어렵습니다.",
            "recommendation": safe_expression or "기사 표현이 시각자료의 기간과 범위를 넘지 않는지 확인하세요.",
        }
    )

    # 강한 표현과 위험 신호가 입력된 경우 별도 카드로 분리해 긴 문단에
    # 묻히지 않게 한다. 현재 임시 입력 단계이므로 최대 네 개까지만 확장한다.
    issue_labels = _as_string_list(state.get("ce_strong_expressions"))
    issue_labels.extend(_as_string_list(state.get("ce_risk_flags")))
    unique_labels = list(dict.fromkeys(issue_labels))[:4]
    for label in unique_labels:
        cards.append(
            {
                "title": f"표현 또는 위험 신호 점검: {label}",
                "severity": "주의" if severity != "높음" else "높음",
                "claim": label,
                "visual_evidence": visual_evidence or "관련 시각자료 근거가 구체적으로 입력되지 않았습니다.",
                "judgement": draft_summary or revision_reason or "해당 표현이 시각자료의 근거 범위를 넘는지 확인해야 합니다.",
                "recommendation": safe_expression or "근거가 보여주는 범위에 맞춰 표현을 중립적으로 조정하세요.",
            }
        )

    return cards


def build_evidence_cards(state: dict[str, Any]) -> list[dict[str, str]]:
    """업로드 이미지와 보조 설명에서 확인 가능한 근거를 카드로 정리한다."""
    cards: list[dict[str, str]] = []
    paths = _image_paths(state)
    chart_text = _as_text(state.get("input_chart_text"))
    source_text = _as_text(state.get("input_source_text"))

    if paths:
        cards.append(
            {
                "title": f"뉴스 내부 원본 시각자료 {len(paths)}개",
                "evidence": f"업로드된 원본 시각자료 {len(paths)}개를 확인 대상으로 사용했습니다.",
                "interpretation": "원본 이미지는 시각자료 근거 탭에서 확인할 수 있으며, 로컬 파일 경로는 상세 데이터에만 표시됩니다.",
            }
        )
    if chart_text:
        cards.append(
            {
                "title": "시각자료에서 읽은 수치와 추세",
                "evidence": _redact_image_paths(chart_text, state),
                "interpretation": "사용자가 원본 시각자료에서 읽어 입력한 보조 근거입니다.",
            }
        )
    if source_text:
        cards.append(
            {
                "title": "출처·주석·단위",
                "evidence": _redact_image_paths(source_text, state),
                "interpretation": "기간, 단위, 축, 범례와 출처는 수치의 의미와 비교 가능 범위를 결정합니다.",
            }
        )
    return cards


MISSING_INFO_GROUPS = (
    (
        "지표 정의 확인",
        ("정의", "차이", "성공률", "생존율"),
        "지표 정의가 불명확하면 기사 주장과 시각자료를 정확히 비교하기 어렵습니다.",
    ),
    (
        "산정 기준 확인",
        ("기준", "산정", "표본", "조사 대상", "연령"),
        "산정 방식과 조사 대상이 불명확하면 수치의 의미와 적용 범위를 판단하기 어렵습니다.",
    ),
    (
        "비교 기간 확인",
        ("기간", "전후", "비교", "시계열", "연도"),
        "비교 기간이 명확해야 변화의 방향과 크기를 같은 기준에서 해석할 수 있습니다.",
    ),
    (
        "시각자료 표기 확인",
        ("단위", "축", "범례", "주석"),
        "단위와 축·범례·주석이 없으면 수치와 시각적 차이를 잘못 해석할 수 있습니다.",
    ),
    (
        "출처 확인",
        ("출처", "원본", "자료"),
        "원본과 출처를 확인해야 시각자료의 맥락과 신뢰 범위를 점검할 수 있습니다.",
    ),
)


def group_missing_info_items(items: list[str]) -> list[dict[str, Any]]:
    """누락 정보를 키워드 기준으로 묶고 일반 화면용 크기로 압축한다."""
    unique_items = list(dict.fromkeys(item.strip() for item in items if item.strip()))
    grouped: dict[str, list[str]] = {title: [] for title, _, _ in MISSING_INFO_GROUPS}
    grouped["추가 확인 필요"] = []

    for item in unique_items:
        group_title = "추가 확인 필요"
        for title, keywords, _ in MISSING_INFO_GROUPS:
            if any(keyword in item for keyword in keywords):
                group_title = title
                break
        grouped[group_title].append(item)

    reasons = {title: reason for title, _, reason in MISSING_INFO_GROUPS}
    reasons["추가 확인 필요"] = "그 밖의 누락 정보도 최종 판정 전에 원본 시각자료와 함께 확인할 필요가 있습니다."

    populated_groups = [(title, values) for title, values in grouped.items() if values]
    group_overflow = len(populated_groups) > 5
    cards: list[dict[str, Any]] = []
    for title, values in populated_groups[:5]:
        cards.append(
            {
                "title": title,
                "items": values[:4],
                "reason": reasons[title],
                "is_truncated": group_overflow or len(values) > 4,
            }
        )
    return cards


def build_missing_info_cards(state: dict[str, Any]) -> list[dict[str, Any]]:
    """판정을 제한하는 누락 정보를 최대 다섯 개 그룹 카드로 정리한다."""
    missing_items = _as_string_list(state.get("ig_missing_info"))
    if not _image_paths(state):
        missing_items.insert(0, "뉴스 내부 원본 시각자료")
    if not _as_text(state.get("input_source_text")):
        missing_items.append("시각자료 출처·주석·단위")
    return group_missing_info_items(missing_items)


def _build_recommendations(state: dict[str, Any], missing_cards: list[dict[str, Any]]) -> list[str]:
    recommendations = [
        "기사 제목과 본문의 표현이 시각자료가 보여주는 기간과 범위를 넘어서는지 확인하세요.",
        "원본 차트의 축 단위, 범례, 조사 기간과 하단 주석을 함께 확인하세요.",
    ]
    for card in missing_cards:
        recommendation = f"‘{card['title']}’ 항목을 확인하세요."
        if recommendation not in recommendations:
            recommendations.append(recommendation)
    if state.get("vc_revision_needed"):
        recommendations.append("최종 문구에는 검토 결과의 안전한 표현을 우선 사용하세요.")
    return recommendations


def _build_markdown_report(
    judgement: str,
    headline: str,
    summary: str,
    issues: list[dict[str, str]],
    evidence: list[dict[str, str]],
    missing: list[dict[str, Any]],
    recommendations: list[str],
) -> str:
    lines = [f"# 데이터 체커 분석 리포트", "", f"## {judgement}", "", f"**{headline}**", "", summary]
    lines.extend(["", "## 문제 지점"])
    for card in issues:
        lines.extend(
            [
                f"### {card['title']}",
                f"- **기사 주장**: {card['claim']}",
                f"- **시각자료 근거**: {card['visual_evidence']}",
                f"- **판단**: {card['judgement']}",
                f"- **권장 조치**: {card['recommendation']}",
            ]
        )
    lines.extend(["", "## 시각자료 근거"])
    lines.extend([f"- **{card['title']}**: {card['evidence']}" for card in evidence] or ["- 확인 가능한 시각자료 근거가 없습니다."])
    lines.extend(["", "## 부족한 정보"])
    for card in missing:
        lines.append(f"### {card['title']}")
        lines.extend(f"- {item}" for item in card["items"])
        lines.append(f"- **확인 이유**: {card['reason']}")
    if not missing:
        lines.append("- 사용자가 표시한 부족 정보가 없습니다.")
    lines.extend(["", "## 권장 확인사항"])
    lines.extend([f"- {item}" for item in recommendations])
    return "\n".join(lines)


def build_service_report(state: dict[str, Any]) -> dict[str, Any]:
    """전체 state를 deterministic 서비스형 리포트의 merge_ 키로 변환한다."""
    judgement = _as_text(state.get("vc_recommended_judgement")) or "검증 제한"
    tone = TONE_BY_JUDGEMENT.get(judgement, "info")
    headline = HEADLINE_BY_JUDGEMENT.get(judgement, HEADLINE_BY_JUDGEMENT["검증 제한"])
    limitation = _as_text(state.get("ig_limitation_reason"))
    safe_expression = _as_text(state.get("vc_safe_expression"))

    summary_parts = [f"최종 검토 결과는 ‘{judgement}’입니다."]
    if safe_expression:
        summary_parts.append(safe_expression)
    # 일반적인 보조 정보 안내가 긍정 판정을 다시 제한적으로 보이게 하지 않도록,
    # 제한 사유는 실제 최종 판정이 검증 제한인 경우에만 핵심 요약에 포함한다.
    if limitation and judgement == "검증 제한":
        summary_parts.append(limitation)
    summary = " ".join(summary_parts[:4])

    issues = build_issue_cards(state)
    evidence = build_evidence_cards(state)
    missing = build_missing_info_cards(state)
    recommendations = _build_recommendations(state, missing)

    top_summary_cards = build_top_summary_cards(
        {
            **state,
            "merge_user_facing_judgement": judgement,
            "merge_headline": headline,
            "merge_summary": summary,
        }
    )

    return {
        "merge_user_facing_judgement": judgement,
        "merge_judgement_tone": tone,
        "merge_headline": headline,
        "merge_summary": summary,
        "merge_issue_cards": issues,
        "merge_evidence_cards": evidence,
        "merge_missing_info_cards": missing,
        "merge_recommendations": recommendations,
        "merge_top_summary_cards": top_summary_cards,
        "merge_final_report": _build_markdown_report(
            judgement,
            headline,
            summary,
            issues,
            evidence,
            missing,
            recommendations,
        ),
    }
