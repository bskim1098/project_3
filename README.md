# THIRD_LLM

뉴스 내부 표·차트가 기사 주장과 맞는지 검토하는 3차 프로젝트 저장소입니다.

현재 3번 에이전트는 LangChain으로 LLM·structured output을 구성하고, Streamlit의
실제 검증 실행도 `START → verdict_critic → END` LangGraph를 통과합니다.
GraphRAG는 전체 업무의 60%를 담당하는 1st_agent에 도입할 예정이며, 현재는 협업 구조만 준비돼 있습니다.

기술별 적용 상태와 실행 구조는 다음 명령으로 출력할 수 있습니다.

```powershell
uv run python -m frontend.technology_architecture
```

같은 내용은 Streamlit 사이드바의 `기술 아키텍처`에서도 확인할 수 있습니다.

## 디렉터리 구조

```text
C:\THIRD_LLM
├─ pyproject.toml          # 공용 Python 의존성과 패키징 설정
├─ uv.lock                # 공용 잠금 파일
├─ .venv                  # uv 공용 가상환경
├─ frontend\              # 팀 협업용 공용 Streamlit·URL/HTML 전처리
├─ temp_uploads\          # 프론트에서 선택한 이미지의 공용 임시 저장 위치
├─ 1st_agent\             # 1번 주장-근거 검증 작업 공간, 전체 역할 60%
├─ 2nd_agent\             # 2번 에이전트 작업 공간
├─ supervisor\            # 멀티에이전트 실행 순서·state 전달 총괄
└─ 3rd_agent\
   ├─ third_agent\        # 설치 가능한 Python 패키지
   │  ├─ agents\
   │  ├─ nodes\
   │  ├─ parsers\
   │  ├─ prompts\
   │  └─ state\
   ├─ tests\
   ├─ guardrails\
   ├─ test_samples\
   └─ docs\
```

각 숫자 작업 폴더는 담당자별 독립 공간입니다. Python import에는 숫자 폴더명이 아니라
`first_agent`, `third_agent`를 사용하고, 총괄 import 패키지는 `multi_agent_supervisor`를 사용합니다.

## 환경 설치

모든 명령은 저장소 루트 `C:\THIRD_LLM`에서 실행합니다.

```powershell
cd C:\THIRD_LLM
uv sync
```

## Streamlit 실행

```powershell
uv run streamlit run frontend/streamlit_app.py
```

URL/HTML 자동 입력은 뉴스 진위가 아니라 수집 상태를 다음 네 가지로 표시합니다.

- `성공`: 제목과 본문 품질이 기준을 충족하고 추출 후보가 합의함
- `불확실`: HTML은 확보했지만 본문이 짧거나 후보 충돌·동적 페이지가 의심됨
- `접근 제한`: 401·403·429·451 또는 명시적인 접근 제한 응답
- `불러오기 실패`: timeout, DNS, 404·410, 비HTML 응답 등 기술적 실패

어떤 상태에서도 HTML 업로드와 수동 입력 폼은 유지됩니다.

## 테스트

```powershell
uv run python -m unittest discover -s 3rd_agent/tests -v
uv run python -m unittest discover -s 3rd_agent/guardrails -v
uv run python -m compileall frontend 3rd_agent/third_agent 3rd_agent/tests 3rd_agent/guardrails
```
