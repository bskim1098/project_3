"""기사 주장과 입력된 차트 수치를 보수적으로 비교한다.

현재 범위는 두 개 이상의 연도별 수치가 명시된 텍스트다. 이미지 OCR이나
원인 추론은 하지 않으며, 기간·단위·방향을 확정할 수 없으면 비교 제한을 반환한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


ComparisonStatus = Literal["supported", "partial", "contradicted", "limited"]
Direction = Literal["increase", "decrease", "flat"]

_DIRECTION_WORDS: dict[str, Direction] = {
    "증가": "increase",
    "상승": "increase",
    "늘": "increase",
    "확대": "increase",
    "상향": "increase",
    "증가했다": "increase",
    "감소": "decrease",
    "하락": "decrease",
    "줄": "decrease",
    "축소": "decrease",
    "하향": "decrease",
    "내려": "decrease",
}

_VALUE_PATTERN = re.compile(
    r"(?P<value>[+-]?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>%포인트|%p|％|%|조원|억원|억달러|만명|천명|명|건|배|원|달러)?"
)
_PERIOD_PATTERN = re.compile(r"(?P<period>(?:19|20)\d{2})\s*년?")
_GLOBAL_UNIT_PATTERN = re.compile(
    r"단위\s*[:：]?\s*(?P<unit>%포인트|%p|％|%|조원|억원|억달러|만명|천명|명|건|배|원|달러)"
)


@dataclass(frozen=True)
class ChartPoint:
    period: int
    value: float
    unit: str
    label: str


@dataclass(frozen=True)
class ClaimSignal:
    direction: Direction
    amount: float | None = None
    amount_unit: str = ""


@dataclass(frozen=True)
class ClaimChartComparison:
    status: ComparisonStatus
    chart_facts: list[str]
    risk_flags: list[str]
    summary: str


def _normalize_unit(unit: str | None) -> str:
    normalized = (unit or "").strip().replace("％", "%")
    return "%포인트" if normalized == "%p" else normalized


def extract_chart_points(chart_text: str) -> list[ChartPoint]:
    """연도와 값이 함께 있는 행만 구조화한다."""
    global_unit_match = _GLOBAL_UNIT_PATTERN.search(chart_text)
    global_unit = _normalize_unit(
        global_unit_match.group("unit") if global_unit_match else ""
    )
    points: list[ChartPoint] = []

    for raw_line in chart_text.splitlines():
        line = " ".join(raw_line.split())
        period_match = _PERIOD_PATTERN.search(line)
        if not line or not period_match:
            continue

        # 연도 숫자를 값으로 다시 선택하지 않도록 연도 표현 뒤쪽만 파싱한다.
        value_matches = list(_VALUE_PATTERN.finditer(line[period_match.end() :]))
        if not value_matches:
            continue
        value_match = value_matches[-1]
        unit = _normalize_unit(value_match.group("unit")) or global_unit
        value = float(value_match.group("value").replace(",", ""))
        label = line[: period_match.start()].strip(" :-")
        points.append(
            ChartPoint(
                period=int(period_match.group("period")),
                value=value,
                unit=unit,
                label=label,
            )
        )

    unique = {(point.period, point.value, point.unit, point.label): point for point in points}
    return sorted(unique.values(), key=lambda point: point.period)


def extract_claim_signal(title: str, body: str) -> ClaimSignal | None:
    """기사 제목을 우선해 증가·감소 주장과 명시된 변화량을 찾는다."""
    for text in (title, body[:600]):
        for word, direction in _DIRECTION_WORDS.items():
            word_index = text.find(word)
            if word_index < 0:
                continue
            nearby = text[max(0, word_index - 24) : word_index + len(word) + 8]
            amounts = list(_VALUE_PATTERN.finditer(nearby[: nearby.find(word)]))
            amount = amounts[-1] if amounts else None
            return ClaimSignal(
                direction=direction,
                amount=float(amount.group("value").replace(",", "")) if amount else None,
                amount_unit=_normalize_unit(amount.group("unit")) if amount else "",
            )
    return None


def _direction(first: float, last: float) -> Direction:
    if last > first:
        return "increase"
    if last < first:
        return "decrease"
    return "flat"


def _direction_text(direction: Direction) -> str:
    return {"increase": "증가", "decrease": "감소", "flat": "변화 없음"}[direction]


def _observed_amount(first: ChartPoint, last: ChartPoint, claim: ClaimSignal) -> float | None:
    if claim.amount is None:
        return None
    if claim.amount_unit == "%" and first.unit != "%":
        if first.value == 0:
            return None
        return abs((last.value - first.value) / first.value * 100)
    if claim.amount_unit == "%포인트" and first.unit == "%":
        return abs(last.value - first.value)
    if not claim.amount_unit or claim.amount_unit == first.unit:
        return abs(last.value - first.value)
    return None


def compare_claim_to_chart(title: str, body: str, chart_text: str) -> ClaimChartComparison:
    """확인 가능한 두 시점의 방향과 변화량을 기사 주장에 비교한다."""
    points = extract_chart_points(chart_text)
    facts = [
        f"차트에서 {point.period}년 값 {point.value:g}{point.unit}을 확인했습니다."
        for point in points
    ]
    if len(points) < 2:
        return ClaimChartComparison(
            status="limited",
            chart_facts=facts,
            risk_flags=["비교 가능한 두 시점의 차트 수치가 부족합니다."],
            summary="두 시점의 수치를 확인할 수 없어 기사 주장과 차트 방향을 비교하기 어렵습니다.",
        )

    first, last = points[0], points[-1]
    if not first.unit or not last.unit or first.unit != last.unit:
        return ClaimChartComparison(
            status="limited",
            chart_facts=facts,
            risk_flags=["차트 수치의 단위가 없거나 서로 달라 직접 비교하기 어렵습니다."],
            summary="차트의 단위가 명확하게 일치하지 않아 기사 주장과 직접 비교하기 어렵습니다.",
        )

    claim = extract_claim_signal(title, body)
    if claim is None:
        return ClaimChartComparison(
            status="limited",
            chart_facts=facts,
            risk_flags=["기사에서 비교할 증가·감소 주장을 명확히 찾지 못했습니다."],
            summary="기사에서 수치 방향 주장을 명확히 찾지 못해 차트와 직접 비교하기 어렵습니다.",
        )

    observed_direction = _direction(first.value, last.value)
    direction_fact = (
        f"차트는 {first.period}년 {first.value:g}{first.unit}에서 "
        f"{last.period}년 {last.value:g}{last.unit}으로 {_direction_text(observed_direction)}했습니다."
    )
    facts.append(direction_fact)

    if observed_direction != claim.direction:
        return ClaimChartComparison(
            status="contradicted",
            chart_facts=facts,
            risk_flags=["기사의 수치 방향과 차트에서 확인되는 방향이 명확히 어긋납니다."],
            summary=(
                f"기사는 {_direction_text(claim.direction)} 방향을 주장하지만, "
                f"차트는 {_direction_text(observed_direction)} 방향을 보여줍니다."
            ),
        )

    observed_amount = _observed_amount(first, last, claim)
    if claim.amount is not None:
        if observed_amount is None:
            return ClaimChartComparison(
                status="limited",
                chart_facts=facts,
                risk_flags=["기사와 차트의 변화량 단위가 달라 수치를 직접 비교하기 어렵습니다."],
                summary="기사와 차트의 방향은 같지만 변화량 단위가 달라 수치 일치 여부는 제한됩니다.",
            )
        tolerance = max(0.2, claim.amount * 0.05)
        if abs(observed_amount - claim.amount) > tolerance:
            return ClaimChartComparison(
                status="partial",
                chart_facts=facts,
                risk_flags=["기사와 차트의 방향은 같지만 제시된 변화량에는 차이가 있습니다."],
                summary=(
                    f"기사와 차트의 {_direction_text(claim.direction)} 방향은 같지만, "
                    f"기사 변화량 {claim.amount:g}{claim.amount_unit}과 "
                    f"차트 계산값 {observed_amount:g}{claim.amount_unit}은 차이가 있습니다."
                ),
            )

    return ClaimChartComparison(
        status="supported",
        chart_facts=facts,
        risk_flags=[],
        summary="기사의 수치 방향과 차트에서 확인되는 변화가 대체로 일치합니다.",
    )
