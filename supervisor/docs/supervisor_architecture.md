# Supervisor Architecture

Supervisor는 개별 에이전트의 판단을 대신하지 않고 실행 순서와 state 전달만 관리한다.

## 책임 비중

- first_agent / 준영님 / 주장-근거 검증: **60%**
- second_agent / 정보 부족 확인: 20% (현재 구현 전)
- third_agent / 범수님 / 최종판정 검토: 20%

## 목표 실행 흐름

```text
START
  ↓
입력 계약 검사
  ↓
first_agent 주장-근거 검증 (60%)
  ↓ ce_
second_agent 정보 부족 확인 (구현 후 연결)
  ↓ ig_
third_agent 최종판정 검토
  ↓ vc_
결과 병합
  ↓
END
```

1번과 2번이 독립적으로 실행 가능해지면 LangGraph 병렬 분기로 구성하고, 두 결과가 모인 뒤 3번 에이전트를 실행한다.

## 경계

- Supervisor는 `ce_`, `ig_`, `vc_` 판단을 직접 생성하지 않는다.
- 각 에이전트는 자기 namespace만 작성한다.
- 공용 프론트엔드는 `C:\THIRD_LLM\frontend`에 둔다.
- 현재 third_agent에 있는 전체 state와 병합 노드는 동작 중인 데모 보호를 위해 즉시 이동하지 않는다. 통합 시 Supervisor 또는 공용 contracts 영역으로 이관한다.
