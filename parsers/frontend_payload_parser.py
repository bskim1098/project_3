# parsers/frontend_payload_parser.py

"""
frontend_payload_parser.py

역할:
- 프론트엔드에서 들어온 요청 데이터를
  LangGraph에서 사용할 input_ state 형태로 변환한다.

중요:
- 이 파서는 ce_, ig_, vc_, merge_, runtime_ 값을 만들지 않는다.
- 오직 input_ 값만 만든다.
- 실제 LLM이나 LangGraph는 실행하지 않는다.
"""

from typing import Any


def clean_text(value: Any) -> str:
    """
    프론트에서 들어온 값을 문자열로 정리한다.

    왜 필요한가?
    - 프론트에서 None, 숫자, 리스트 등이 들어올 수 있다.
    - LangGraph state에는 기본적으로 문자열을 넣는 편이 안전하다.

    예:
    None -> ""
    "  내용  " -> "내용"
    123 -> "123"
    """

    if value is None:
        return ""

    return str(value).strip()


def parse_frontend_payload(payload: dict[str, Any]) -> dict[str, str]:
    """
    프론트엔드 요청 payload를 input_ state로 변환한다.

    입력 예:
    {
        "newsTitle": "...",
        "newsBody": "...",
        "chartText": "...",
        "sourceText": "...",
        "chartImagePath": "..."
    }

    출력 예:
    {
        "input_news_title": "...",
        "input_news_body": "...",
        "input_chart_text": "...",
        "input_source_text": "...",
        "input_chart_image_path": "..."
    }
    """

    # 프론트에서 camelCase로 들어온 값을 백엔드 state 키로 변환한다.
    parsed_state = {
        "input_news_title": clean_text(payload.get("newsTitle")),
        "input_news_body": clean_text(payload.get("newsBody")),
        "input_chart_text": clean_text(payload.get("chartText")),
        "input_source_text": clean_text(payload.get("sourceText")),
        "input_chart_image_path": clean_text(payload.get("chartImagePath")),
    }

    return parsed_state


def validate_frontend_parsed_state(state: dict[str, str]) -> list[str]:
    """
    파싱된 input_ state에 문제가 있는지 간단히 검사한다.

    반환:
    - 문제가 없으면 빈 리스트 []
    - 문제가 있으면 경고 메시지 리스트 반환

    주의:
    - 건식 테스트용 검증이다.
    - 여기서 에러를 강하게 내기보다, 어떤 값이 비었는지 확인하는 용도다.
    """

    warnings = []

    if not state.get("input_news_title"):
        warnings.append("input_news_title이 비어 있습니다.")

    if not state.get("input_news_body"):
        warnings.append("input_news_body가 비어 있습니다.")

    if not state.get("input_chart_text") and not state.get("input_chart_image_path"):
        warnings.append(
            "input_chart_text와 input_chart_image_path가 모두 비어 있습니다. "
            "차트 검증이 제한될 수 있습니다."
        )

    if not state.get("input_source_text"):
        warnings.append("input_source_text가 비어 있습니다. 출처 검증이 제한될 수 있습니다.")

    # input_ 이외의 키가 섞였는지 확인한다.
    for key in state.keys():
        if not key.startswith("input_"):
            warnings.append(f"input_이 아닌 키가 포함되어 있습니다: {key}")

    return warnings