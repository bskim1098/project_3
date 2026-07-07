"""기사에 실제로 적힌 핵심 주장을 보수적으로 축약한다."""


def summarize_claim(title: str, body: str) -> str:
    title = title.strip()
    body = " ".join(body.split())
    if title and body:
        return f"제목은 '{title}'이며, 본문은 '{body[:120]}' 내용을 중심으로 주장합니다."
    if title:
        return f"제목은 '{title}'입니다."
    if body:
        return f"본문은 '{body[:150]}' 내용을 중심으로 주장합니다."
    return "기사 제목과 본문 내용이 부족해 핵심 주장을 요약하기 어렵습니다."
