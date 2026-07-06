"""1st_agent의 structured output 스키마를 정의할 모듈.

입력: LangChain structured output에 연결할 필드 정의.
출력: 허용된 ce_ 필드와 판정값만 포함하는 검증된 객체.
제약: 필수값, 리스트 타입, 허용 판정 네 종류를 스키마 단계에서 검증한다.
구현 상태: TODO - 준영님 담당 Pydantic 스키마 구현 예정.
"""
