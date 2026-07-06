# 1st_agent 구현 상태 및 3rd_agent 비교

> 문서 역할: 1st_agent의 구조·기능·테스트 완성도를 3rd_agent와 비교하고 다음 구현 우선순위를 기록합니다.

점검 기준일: 2026-07-06

## 1. 결론

1st_agent는 담당 역할과 파일 구조는 잘 설계되어 있지만, 실행 가능한 기능은 아직 구현되지 않았다.

- 구조 준비도: 약 90%
- 문서 준비도: 약 40%
- 핵심 기능 구현도: 0%
- 테스트 구현도: 0%
- GraphRAG 구현도: 0%
- 프론트·Supervisor 통합도: 0%
- 전체 완성도 추정: 약 15~20%

전체 업무의 **60%**를 담당하는 핵심 에이전트이지만, 현재 Python 파일에는 함수, 클래스, import 또는 실행 로직이 없고 TODO 주석만 존재한다.

## 2. 정량 비교

| 항목 | 1st_agent | 3rd_agent |
|---|---:|---:|
| Python 파일 | 30개 | 15개 |
| 전체 Python 줄 | 45줄 | 2,176줄 |
| 주석 제외 코드 | **0줄** | **1,818줄** |
| 함수·클래스 | 0개 | 다수 |
| 실행되는 테스트 | **0개** | **55개** |
| LangChain | 미적용 | 적용 |
| LangGraph | 미적용 | 적용 |
| GraphRAG | 구조만 존재 | 담당 범위 아님 |
| 실제 프론트 연결 | 미연결 | 연결됨 |

파일 개수만 보면 1st_agent가 더 크지만, 대부분 역할과 위치를 나타내는 placeholder다. 파일 개수는 현재 구현 완성도를 의미하지 않는다.

## 3. 영역별 상태

| 영역 | 1st_agent | 3rd_agent |
|---|---|---|
| 폴더 분리 | 역할별로 잘 구성됨 | 구성됨 |
| 에이전트 | placeholder | 실제 LLM 실행 |
| 노드 | 위치만 준비 | 실제 검토 노드 구현 |
| 프롬프트 | 제목과 TODO만 존재 | 실제 프롬프트 존재 |
| State | placeholder | TypedDict 계약 구현 |
| Schema | placeholder | Pydantic structured output 구현 |
| 가드레일 | 위치만 준비 | 실제 보정 로직과 테스트 존재 |
| 테스트 | 파일명만 존재 | 55개 통과 |
| 샘플 | TODO HTML·JSON | 실제 파서 fixture |
| GraphRAG | 모듈 위치만 존재 | 미적용 |
| Supervisor 연동 | 미연결 | 현재 프론트에서 직접 실행 |

## 4. 잘 준비된 부분

- 준영님 담당과 전체 업무의 60% 책임이 문서에 명시되어 있다.
- `agents`, `nodes`, `parsers`, `prompts`, `state`, `schemas`가 분리되어 있다.
- 일반 테스트와 가드레일 테스트의 위치가 분리되어 있다.
- GraphRAG가 별도 패키지로 분리되어 있다.
- `provenance.py`를 통해 기사 내부 근거와 GraphRAG 검색 근거를 구분할 위치가 준비되어 있다.
- 3rd_agent로 결과를 전달할 문서 위치가 준비되어 있다.
- `first_agent` Python 패키지로 import할 수 있다.
- placeholder 파일 때문에 컴파일 오류가 발생하지 않는다.

## 5. 미구현 핵심 파일

다음 파일에는 현재 역할 주석만 있으며 실행 로직은 없다.

- `first_agent/agents/claim_evidence_agent.py`
- `first_agent/state/claim_evidence_state.py`
- `first_agent/schemas/claim_evidence_output.py`
- `first_agent/nodes/chart_extraction_node.py`
- `first_agent/nodes/claim_extraction_node.py`
- `first_agent/nodes/strong_expression_node.py`
- `first_agent/nodes/claim_chart_compare_node.py`
- `first_agent/nodes/draft_judgement_node.py`
- `first_agent/graphrag/graph_builder.py`
- `first_agent/graphrag/retriever.py`
- `first_agent/graphrag/provenance.py`
- `first_agent/guardrails/claim_evidence_guardrails.py`

다음 계약 문서도 아직 TODO 상태다.

- `docs/ce_state_contract.md`
- `docs/handoff_to_vc_agent.md`

## 6. 현재 테스트 상태

```text
1st_agent/tests:      0 tests
1st_agent/guardrails: 0 tests
Python compileall:    성공
```

컴파일 성공은 문법 오류가 없다는 뜻일 뿐 기능이 구현됐다는 의미는 아니다. 현재 테스트 파일에도 테스트 클래스나 테스트 함수가 없다.

## 7. 권장 구현 순서

```text
1. ce_ State 계약 확정
2. Pydantic structured output Schema 구현
3. 기사·차트 입력 Parser 구현
4. 차트 정보 추출 노드 구현
5. 기사 주장 추출 노드 구현
6. 강한 표현 탐지 노드 구현
7. 주장-차트 비교 노드 구현
8. 보수적인 1차 판정 노드 구현
9. LangChain 프롬프트와 structured output 연결
10. LangGraph로 claim_evidence_agent 구성
11. ce_ 전용 가드레일 구현
12. 실제 fixture와 회귀 테스트 작성
13. 기본 주장-차트 비교가 안정된 후 GraphRAG 구현
14. Supervisor와 공용 프론트에 연결
```

## 8. GraphRAG 적용 순서

GraphRAG 폴더가 존재하더라도 기본 `ce_` 파이프라인보다 먼저 구현하면 안 된다.

먼저 다음 항목이 확정되어야 한다.

- 기사 핵심 주장 표현 방식
- 차트 사실 표현 방식
- 비교 대상, 기간, 단위, 방향의 데이터 구조
- `ce_` 출력 필드
- 기사 내부 근거와 외부 검색 근거의 구분 방식
- 검색 출처와 신뢰 범위 기록 방식

이 계약이 확정된 후 GraphRAG가 검색한 관계와 출처 정보를 `ce_` 판정의 보조 근거로 연결한다.

## 9. 최종 평가

1st_agent는 협업자가 바로 구현을 시작할 수 있는 설계 골격까지는 준비되어 있다. 하지만 현재는 기능이 동작하는 주장-근거 검증 에이전트가 아니다.

전체 프로젝트에서 60%를 담당하는 핵심 경로이므로, 향후 개발 우선순위는 GraphRAG보다 `ce_` 계약, 기본 추출·비교 노드, 가드레일, 실제 테스트 구현에 두어야 한다.
