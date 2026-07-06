# Collaboration Guide

## 소유권

| 영역 | 담당 | 비중 | 쓰기 namespace |
|---|---|---:|---|
| 1st_agent 주장-근거 검증 | 준영님 | **60%** | `ce_` |
| 2nd_agent 정보 부족 확인 | 추후 연결 | 20% | `ig_` |
| 3rd_agent 최종판정 검토 | 범수님 | 20% | `vc_` |
| supervisor | 공동 통합 | 조정 역할 | `runtime_` |
| frontend | 공동 관리 | 공용 UI | 분석 state 직접 생성 금지 |

## 폴더 원칙

- 에이전트 구현은 각 작업 공간의 설치 패키지 안에 둔다.
- 테스트, 가드레일 테스트, 문서, 샘플은 각 작업 공간 루트에서 분리한다.
- 공용 Streamlit과 URL/HTML 전처리는 최상위 `frontend`에 둔다.
- Supervisor는 실행 순서와 전달만 담당하며 각 에이전트의 판단을 대신하지 않는다.
- GraphRAG는 1st_agent 소유이며 현재는 도입 예정 구조만 존재한다.

## 통합 순서

1. `input_`을 읽어 1st_agent를 실행한다.
2. 1st_agent의 `ce_` 결과를 수집한다.
3. 2nd_agent가 준비되면 `ig_` 결과를 함께 수집한다.
4. `input_`, `ce_`, `ig_`를 3rd_agent에 전달한다.
5. 3rd_agent의 `vc_` 결과를 병합 노드에 전달한다.
