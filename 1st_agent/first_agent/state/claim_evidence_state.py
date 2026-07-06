"""claim_evidence_agent가 읽고 쓰는 state 타입을 정의할 모듈.

읽기 대상: input_ 공용 입력과 합의된 보조 정보.
쓰기 대상: ce_chart_facts, ce_claim_summary, ce_strong_expressions, ce_risk_flags, ce_draft_judgement, ce_draft_summary.
제약: input_, ig_, vc_, merge_, runtime_ 값은 작성하지 않는다.
구현 상태: TODO - 팀 합의 후 TypedDict 또는 동등한 타입으로 구현.
"""
