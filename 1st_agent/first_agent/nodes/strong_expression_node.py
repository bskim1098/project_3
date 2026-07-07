"""강한 표현과 기사-차트 비교의 위험 신호를 규칙 기반으로 탐지한다."""

import re


STRONG_EXPRESSION_KEYWORDS = (
    "폭증", "급증", "급락", "압도적", "역대급", "완전 회복",
    "최고", "최저", "최대", "최소", "때문에", "원인", "영향",
    "반드시", "명백히",
)
CAUSAL_KEYWORDS = ("때문에", "원인", "영향으로", "결과로", "탓")
PERIOD_GENERALIZATION_KEYWORDS = ("역대", "사상", "항상", "전례 없는")

RISK_RULES = {
    "missing_chart_text": "차트 텍스트가 부족해 수치 확인이 제한됩니다.",
    "missing_source": "출처 또는 차트 설명이 부족합니다.",
    "causal_claim": "기사에 인과를 단정하는 표현이 있어 주의가 필요합니다.",
    "strong_expression": "기사에 강한 표현이 있어 차트 근거와 비교가 필요합니다.",
    "missing_unit": "차트 수치의 단위가 부족할 수 있습니다.",
    "missing_period": "차트의 비교 기간이 부족할 수 있습니다.",
    "period_generalization": "제시된 기간보다 넓게 일반화하는 표현이 있어 주의가 필요합니다.",
    "visual_distortion": "축 생략 또는 축 범위 설명이 있어 시각적 왜곡 가능성을 추가로 확인해야 합니다.",
}


def extract_strong_expressions(title: str, body: str) -> list[str]:
    text = f"{title}\n{body}"
    return [word for word in STRONG_EXPRESSION_KEYWORDS if word in text]


def detect_risk_flags(
    title: str,
    body: str,
    chart_text: str,
    source_text: str,
    strong_expressions: list[str],
) -> list[str]:
    flags: list[str] = []
    article = f"{title}\n{body}"
    if not chart_text.strip():
        flags.append(RISK_RULES["missing_chart_text"])
    if not source_text.strip():
        flags.append(RISK_RULES["missing_source"])
    if strong_expressions:
        flags.append(RISK_RULES["strong_expression"])
    if any(word in article for word in CAUSAL_KEYWORDS):
        flags.append(RISK_RULES["causal_claim"])

    if chart_text.strip():
        has_unit = bool(re.search(r"%포인트|%p|％|%|원|달러|명|건|배", chart_text))
        has_period = bool(re.search(r"(?:19|20)\d{2}\s*년?|\d+\s*(?:월|분기)", chart_text))
        if not has_unit:
            flags.append(RISK_RULES["missing_unit"])
        if not has_period:
            flags.append(RISK_RULES["missing_period"])
        periods = set(re.findall(r"(?:19|20)\d{2}", chart_text))
        if any(word in article for word in PERIOD_GENERALIZATION_KEYWORDS) and len(periods) < 5:
            flags.append(RISK_RULES["period_generalization"])
        if any(word in chart_text for word in ("축 생략", "축 범위", "절단축")):
            flags.append(RISK_RULES["visual_distortion"])
    return flags
