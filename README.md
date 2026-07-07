# THIRD_LLM

뉴스 기사 안에 삽입된 표·차트가 기사 제목과 본문 주장을 뒷받침하는지 검토하는 Streamlit 기반 서비스입니다. 외부 자료와 기사 내용을 대조하는 일반적인 팩트체크가 아니라, 같은 기사 안의 주장과 시각자료 관계를 확인합니다.

## 현재 실행 구조

```text
Streamlit 입력
→ gpt-5.4-mini 생성
→ first_agent.ce_agent 실행
→ third_agent.vc_agent 실행
→ report merge
→ 최종 리포트 출력
```

CE agent는 LangGraph로 다음 단계를 실행합니다.

```text
START
→ chart_extraction
→ claim_extraction
→ compare_and_judge
→ guardrail
→ END
```

- LangChain과 structured output은 기사 핵심 주장 요약을 보조합니다.
- 차트 사실 추출, 위험 신호 탐지, 수치 비교, 1차 판정은 규칙 기반 로직을 유지합니다.
- LLM 호출이 실패하거나 LLM이 없어도 CE agent는 규칙 기반 fallback으로 동작합니다.
- VC agent는 최종판정의 강도와 위험 표현을 보수적으로 검토합니다.

## 프로젝트 구조

```text
THIRD_LLM
├─ common
│  └─ state
│     └─ news_chart_check_state.py
├─ first_agent
│  └─ ce_agent
│     ├─ agents
│     ├─ graphrag
│     ├─ guardrails
│     ├─ nodes
│     ├─ parsers
│     ├─ prompts
│     ├─ schemas
│     └─ state
├─ second_agent
│  └─ ig_agent
├─ third_agent
│  └─ vc_agent
│     ├─ agents
│     ├─ nodes
│     ├─ parsers
│     └─ prompts
├─ frontend
│  └─ streamlit_app.py
└─ supervisor
   └─ multi_agent_supervisor
```

정식 Python import 경로는 다음과 같습니다.

```python
from first_agent.ce_agent.agents.claim_evidence_agent import run_claim_evidence_agent
from second_agent.ig_agent import ...
from third_agent.vc_agent.agents.verdict_critic_agent import build_verdict_critic_graph
from common.state.news_chart_check_state import NewsChartCheckState
```

`ce_agent...`, `ig_agent...`, `vc_agent...` 형태의 짧은 import는 사용하지 않습니다.

## MVP 범위

현재 프런트는 URL 또는 HTML에서 기사와 이미지 후보를 추출하고, 사용자가 시각자료의 수치·기간·단위·출처를 직접 입력하는 방식입니다.

- 이미지 OCR: 아직 지원하지 않음
- GraphRAG: 구조만 준비된 향후 확장 기능
- Supervisor: 골격과 계약만 준비된 향후 확장 기능
- second_agent/ig_agent: 최소 패키지만 있으며 실제 에이전트는 구현 전

## 설치 및 실행

모든 명령은 저장소 루트 `C:\THIRD_LLM`에서 실행합니다.

```powershell
uv sync
uv run streamlit run frontend/streamlit_app.py
```

환경 변수 `OPENAI_API_KEY`는 `.env`에 설정합니다.

## 테스트

```powershell
uv run python -m unittest discover -s first_agent/tests -v
uv run python -m unittest discover -s first_agent/guardrails -v
uv run python -m unittest discover -s third_agent/tests -v
uv run python -m unittest discover -s third_agent/guardrails -v
uv run python -m compileall common first_agent second_agent third_agent frontend supervisor
```
