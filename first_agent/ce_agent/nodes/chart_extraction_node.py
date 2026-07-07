"""이미 제공된 차트 텍스트에서 확인 가능한 수치만 추출한다."""

import re


_NUMBER_WITH_CONTEXT = re.compile(
    r"[가-힣A-Za-z_]*\s*[+-]?\d[\d,]*(?:\.\d+)?\s*"
    r"(?:%포인트|%p|％|%|억달러|조원|억원|만원|원|만명|천명|명|건|배|년|월|일)?"
)


def extract_chart_facts(chart_text: str, limit: int = 8) -> list[str]:
    """텍스트에 명시된 표현만 반환하며 수치 의미를 추론하지 않는다."""
    if not chart_text.strip():
        return []
    found: list[str] = []
    for match in _NUMBER_WITH_CONTEXT.finditer(chart_text):
        value = " ".join(match.group().split())
        if value and value not in found:
            found.append(value)
        if len(found) >= limit:
            break
    if not found:
        return ["차트 텍스트는 있으나 명확한 수치 표현을 찾지 못했습니다."]
    return [f"차트에서 '{value}' 값을 확인했습니다." for value in found]
