# URL/HTML 프론트 선작업 인수인계

최종 독립 점검 결과는 `docs/pre_handoff_check_report.md`에 기록한다.

## 1. 작업 목적

기존 수동 입력형 Streamlit 화면 위에 뉴스 기사 URL 또는 스크랩 HTML 파일을 받는 단계를 추가했다. URL은 LLM 분석 문자열이 아니라 HTML을 확보하기 위한 위치 정보로만 사용한다. 확보한 HTML에서 확인되는 텍스트를 기존 폼에 자동 입력하고, 사용자가 수정한 뒤 기존 `vc_` 검토를 실행한다.

최종 목표 흐름은 다음과 같다.

```text
URL 또는 HTML 파일
→ HTML 확보·파싱
→ 기사 제목/본문/시각자료 주변 텍스트 추출
→ 주장-근거 검증 에이전트
→ 1차 판정과 관계 요약
→ vc_ 최종판정 검토 에이전트
→ 결과 병합
```

## 2. 이번 단계에서 변경된 파일과 책임

- `frontend/html_ingestion.py`
  - `fetch_html_from_url`: URL에서 실제 HTML을 가져온다.
  - `read_html_from_upload`: 업로드 파일의 HTML을 읽고 한글 인코딩 fallback을 적용한다.
  - `extract_text_blocks_from_html`: 표준 DOM과 적응형 후보 점수로 제목, 본문, 표·차트 텍스트, 이미지 후보를 추출한다.
  - `download_image_from_url`: 사용자가 선택한 기사 이미지 후보만 URL 보안 검사를 거쳐 내려받는다.
  - `prefill_form_from_html_content`: 추출값을 기존 일곱 개 폼 필드 계약으로 변환한다.
- `frontend/ingestion_outcome.py`
  - URL/HTML 자동 입력을 `success`, `uncertain`, `access_restricted`, `fetch_failed`로 분류한다.
  - 이 상태는 뉴스 진위나 최종 판정이 아니라 프론트 전처리 결과만 뜻한다.
- `frontend/technology_architecture.py`
  - GraphRAG·LangGraph·LangChain의 실제 적용 상태, 실행 흐름, 팀 인계 지점을 구조화해 반환한다.
  - 터미널 출력과 Streamlit 사이드바가 같은 데이터를 사용한다.
- `frontend/streamlit_app.py`
  - `0. 뉴스 원문 불러오기` UI와 두 입력 경로를 추가했다.
  - URL과 HTML이 모두 있으면 HTML 파일을 우선한다.
  - 자동 입력값은 Streamlit session state에 저장되어 사용자가 수정할 수 있다.
  - 기사 본문 안에서 찾은 이미지를 후보로 보여주고 사용자가 실제 검토할 시각자료를 선택한다.
  - 실패해도 수동 입력 폼과 `기사 근거 검증하기` 흐름은 유지한다.
  - 제출 시 `run_verdict_critic_graph`가 컴파일된 LangGraph를 실행하고 결과에서 `vc_` 여섯 필드만 추린다.
- `tests/test_html_ingestion.py`
  - HTML fixture 추출, 폼 key 계약, 인코딩, URL 보안과 HTTP 상태 분류를 검증한다.
- `tests/test_ingestion_outcome.py`
  - 이미지 유무와 분리된 성공 조건, 낮은 신뢰도·짧은 본문의 불확실 처리, 실패 시 빈 prefill 계약을 검증한다.
- `test_samples/html/`
  - article, 미등록 div 경쟁, p·br 혼합 및 br 직접 텍스트, 비정상 noscript iframe 복구, table, JSON-LD, 네이트 `#articleContetns`·`#realArtcContents`, 다중 article 적응형 선택, 메타정보 누락 구조의 고정 HTML과 기대 결과를 보관한다.
- `tests/test_frontend_manual_input.py`
  - URL/HTML 없이 기존 입력을 state로 변환하는 수동 입력 경로를 회귀 검증한다.
- `guardrails/test_verdict_critic_guardrails.py`
  - 위험 표현, 단답형 설명, 비허용 판정 보정을 검증한다.

## 3. 유지한 계약

다음 `vc_` 출력은 추가하거나 이름을 변경하지 않았다.

```text
vc_recommended_judgement
vc_unsafe_expressions
vc_revision_needed
vc_revision_reason
vc_safe_expression
vc_critic_notes
```

`NewsChartCheckState`에도 URL/HTML 전용 필드를 추가하지 않았다. URL과 원본 HTML은 전처리 과정에서만 사용하고, 확인·수정된 결과만 기존 `input_`, 임시 `ce_`, 임시 `ig_` 흐름에 들어간다.

자동 폼 채움 반환 key 계약은 다음과 같다.

```text
news_title
news_body
chart_text
source_text
draft_judgement
claim_chart_summary
missing_info
```

주장-근거 검증 에이전트를 연결할 때도 이 반환 계약을 유지하면 프론트 위젯을 변경할 필요가 없다.

### URL/HTML 자동 입력 상태 계약

새 LangGraph state는 만들지 않고 Streamlit 전처리 내부의 `IngestionOutcome`으로 관리한다.

```text
success            제목·본문과 추출 신뢰도가 충분함
uncertain          HTML은 확보했지만 본문 품질 또는 후보 합의가 부족함
access_restricted  HTTP 401·403·429·451처럼 명시적인 접근 제한
fetch_failed       timeout, DNS, 404·410, 비HTML 등 기술적 실패
```

이미지 후보나 출처·단위 후보가 없다는 이유만으로 기사 본문 추출 성공을 실패로 낮추지 않는다. 불확실 상태의 추출 텍스트는 폐기하지 않고 수정 가능한 폼에 보존한다. 실패 상태에서는 빈 자동 입력값으로 기존 수동 입력을 덮어쓰지 않는다.

## 4. 단일 에이전트 단계의 한계

### 주장-근거 분석

현재 연결된 실제 LLM 에이전트는 `vc_` 최종판정 검토 에이전트뿐이다. 기사 주장 추출, 이미지 수치 판독, 기사 주장과 차트의 비교는 구현되어 있지 않다. 따라서 현재 화면의 `ce_`와 `ig_` 값은 사용자가 확인한 폼 입력으로 만든 임시 값이다.

이 때문에 자동 채움은 HTML에서 직접 확인되는 문자열만 옮긴다. 근거 없이 관계 요약이나 1차 판정을 생성하지 않으며 `draft_judgement`는 보수적으로 `검증 제한`을 사용한다.

### HTML 수집

- 로그인, 유료벽, robots 정책, 봇 차단이 있는 사이트는 요청이 실패할 수 있다.
- JavaScript 실행 후 본문이 생기는 페이지는 초기 HTML만으로 본문을 얻지 못할 수 있다.
- URL 내 사용자명·비밀번호, localhost, 직접 입력된 사설·루프백·링크 로컬 IP를 차단한다.
- 도메인의 DNS 해석 결과가 사설·루프백 주소인 경우 IPv4와 IPv6 모두 차단한다.
- 리다이렉트 대상에 연결하기 전에 새 URL과 DNS를 검사하고, 최종 응답 URL도 다시 검사한다.
- DNS 검사와 실제 연결 사이에 주소가 바뀌는 DNS rebinding 가능성은 애플리케이션 코드만으로 완전히 제거되지 않는다. 운영 배포 시 네트워크 egress 정책 또는 고정 프록시가 필요하다.
- 응답 크기는 5MB, 요청 시간은 12초로 제한했다.
- URL 실패 시 자동으로 다른 크롤링 수단을 시도하지 않고 HTML 업로드 또는 수동 입력을 안내한다.

### HTML 파싱과 시각자료

- BeautifulSoup 실행 전에 noscript 내부에 iframe 시작 태그만 있고 닫는 iframe 태그가 없는 추적용 비정상 블록을 파싱 복사본에서 제거한다. 정상 noscript와 noscript 밖 iframe은 보존한다.
- 원본 HTML이나 LangGraph state는 변경하지 않으며, 정규화된 문자열만 DOM 파싱에 사용한다.
- BeautifulSoup 공통 DOM 추출기가 `itemprop=articleBody`, 본문 class/id, 모든 `main`·`article`·`section`·본문 구조가 있는 `div`, JSON-LD `NewsArticle.articleBody`를 동일한 내부 `ArticleCandidate`로 평가한다.
- 공통 `article`이 발견되어도 미등록 class/id의 일반 컨테이너를 함께 비교한다. 본문 길이·문단 수·문장성·링크 비율·메타데이터 문단·표준 속성을 점수화해 가장 기사다운 후보를 선택한다.
- 각 후보에는 p 문단 추출과 br/혼합 DOM 추출을 독립 적용하고, 품질 점수가 높은 결과를 사용한다. br이 없는 일반 기사에서는 DOM 줄 분해가 표 셀·제목을 과분할하지 않도록 p 방식을 유지한다.
- 넓은 페이지 wrapper가 거의 같은 본문을 가진 좁은 자식 후보를 포함하면 중첩 범위와 추가 블록 수에 따라 감점한다. 과도하게 잘게 나뉜 문단도 감점한다.
- 사이트별 예외는 공통 파서와 분리한 `SITE_PROFILES`에 둔다. 현재 네이트의 `#realArtcContents`, `#articleContetns`, `GoImg(...)` 원본 이미지 구조를 후보 가점으로 지원한다. 프로필 선택자도 즉시 확정하지 않고 본문 품질을 평가한다.
- 신뢰도는 선택자 존재만으로 높게 표시하지 않는다. 추출량, 상위 후보 간 점수 차이, 후보 본문 간 합의, p·br 추출 결과 간 합의를 함께 보고 높음·보통·낮음을 정한다.
- 짧은 본문은 삭제하지 않고 낮은 신뢰도로 폼에 보존해 사용자가 원문과 비교할 수 있게 한다.
- p 캡션이 일부 존재해도 br 기반 직접 텍스트가 더 풍부하면 br 문단을 사용한다. `기사 이미지` 같은 일반 캡션은 기사 본문에서 제외한다.
- 광고·공유·랭킹·추천 기사·댓글·푸터를 제거하고 저작권 문구 이후 DOM은 본문과 이미지 후보에서 제외한다.
- 본문 안 표·figcaption·차트성 img alt를 수집하고, 일반 기사 사진은 자동으로 차트 텍스트로 간주하지 않는다.
- `(표=대신증권)` 형태의 짧은 캡션은 시각자료·출처 후보로 인식한다.
- 발견 이미지는 후보로만 표시한다. 사용자가 선택한 이미지만 10MB 제한과 MIME 검사를 거쳐 `temp_uploads`에 저장한다.
- 이미지 픽셀 OCR과 차트 수치·축·범례 판독은 수행하지 않는다.
- 차트 안에 픽셀로만 존재하는 수치·축·범례는 추출할 수 없다.
- 출처 후보는 `출처`, `자료`, `단위`, `주석`, `source`, `caption`, `통계` 키워드 기반이다.

### 화면 및 실행 검증

- 가드레일 5개와 fixture·전처리·상태 분류·기술 아키텍처·보안·수동 입력·Streamlit UI 테스트 50개, 총 55개가 통과했다.
- Python 전체 컴파일, Streamlit 서버 기동과 HTTP 200까지 확인했다.
- Streamlit 자체 UI 테스트로 두 버튼명, 빈 원문 입력 안내, 자동 채움값의 사용자 수정 가능 상태를 확인했다.
- 자동 브라우저 조작 도구가 세션에 노출되지 않아 OS 파일 선택기를 통한 실제 HTML 업로드 E2E는 수행하지 못했다. HTML 업로드 읽기와 폼 매핑 자체는 단위 테스트로 검증했다.
- 실제 OpenAI 호출은 API 비용과 키가 필요한 외부 동작이므로 이 선작업의 자동 테스트에서는 실행하지 않았다.
- 기존 실제 네이트 URL에서 더 좁은 본문 선택자 `#realArtcContents`, 본문 26개 문단, 핫뉴스·기자 이메일 제외, 원본 이미지 후보 2개 추출을 확인했다.
- 중앙일보 제휴 네이트 URL에서 br 기반 본문 7개 문단과 이미지 후보 1개를 추출하고, `기사 이미지` 캡션과 `이 시각 많이 본 뉴스` 이후를 본문에서 제외했다.
- 실제 네이트 원본 이미지 1개를 안전 다운로드하여 JPEG 37,715바이트 응답을 확인했다.
- 실제 뉴스프리존 URL에서 사이트 프로필 없이 `[itemprop='articleBody']`를 선택해 본문 19개 문단, 표 이미지 1개, 시각자료·출처 후보 각 1개를 추출했다.
- 실제 MBN URL에서 비정상 noscript iframe을 정규화한 뒤 `[itemprop='articleBody']`, 본문 11개 문단, 이미지 1개, 시각자료·출처 후보 각 2개를 추출했다.
- 네이트와 MBN 실제 URL은 `success`, HTTP 403을 반환한 한국경제 실제 URL은 `access_restricted`로 종료되는 것을 확인했다.
- HTTP 200이라도 명시적인 로그인·구독·차단 안내만 담긴 짧은 HTML은 `access_restricted`로 분류한다. 정상 기사 안에서 같은 문구를 인용한 경우의 오탐 방지 테스트도 포함한다.

### 가드레일 계약 정리

`guardrails/test_verdict_critic_guardrails.py`가 기대하는 단답형 보정 계약에 맞춰 `WEAK_SHORT_ANSWERS` 후처리를 복구했다. `예`, `없음`, `수정 필요` 같은 값은 기존 `vc_revision_reason`, `vc_safe_expression`, `vc_critic_notes` 안에서 설명형 문장으로 교체된다. 새 `vc_` 변수나 state 필드는 추가하지 않았다.

### 기술 적용 경계

- LangChain: `ChatOpenAI`, `ChatPromptTemplate`, structured output 구성에 실제 사용한다.
- LangGraph: Streamlit의 실제 제출 경로가 `START → verdict_critic → END` 컴파일 그래프를 실행한다.
- GraphRAG: 현재 실행 코드에는 적용되지 않았으며, 전체 업무의 60%를 담당하는 first_agent에 관계·출처 보조 검색으로 도입할 예정이다.

## 5. 준영님 주장-근거 검증 에이전트 연결 지점

1. `extract_text_blocks_from_html(html)`의 결과를 입력으로 받는다. URL 문자열 자체는 넘기지 않는다.
2. `image_candidates` 중 사용자가 선택해 저장된 이미지 경로를 멀티모달/OCR 입력으로 연결한다.
3. 기사 핵심 주장, 차트 사실, 강한 표현, 위험 플래그, 1차 판정, 관계 요약을 생성한다.
4. 생성 결과를 기존 `ce_` 필드에 맞춘다.
5. `prefill_form_from_html_content`의 `claim_chart_summary`, `draft_judgement`, `missing_info`를 에이전트 결과로 채우되 사용자가 수정할 수 있게 유지한다.
6. 사용자가 확정한 결과와 실제 `ce_` 결과를 `vc_` 에이전트에 전달한다.

권장되는 교체 단위는 `make_temp_ce_state`와 `make_temp_ig_state`다. `make_input_state`, `make_verdict_critic_node`, `build_service_report`의 호출 계약은 유지하는 편이 통합 위험이 작다.

팀원이 전체 그래프에 통합할 때는 `make_verdict_critic_node(llm)`를 기존 전체 `StateGraph`의 노드로 추가할 수 있다. 독립 실행이 필요하면 `build_verdict_critic_graph(llm)`를 그대로 사용한다. 두 방식 모두 이 에이전트가 쓰는 값은 `vc_` 여섯 필드뿐이어야 한다.

## 6. 다음 작업 우선순위

1. 실제 브라우저에서 HTML 업로드 → 자동 채움 → 사용자 수정 → 검증 버튼 흐름을 E2E로 확인한다.
2. 준영님 에이전트가 `HTMLTextBlocks`를 받아 기존 `ce_` 결과를 반환하도록 구현한다.
3. 추가 뉴스 HTML 표본은 적응형 후보 점수의 정확도 평가에 사용하고, 범용 점수로 해결되지 않는 경우에만 사이트 프로필을 추가한다.
4. 동적 페이지·유료벽·로그인 페이지의 브라우저 렌더링 지원 여부와 운영 환경의 URL 보안 정책을 결정한다.
5. 차트 OCR의 책임 주체와 장기 이미지 저장 정책을 정한다.

## 7. 실제 브라우저 수동 확인 체크리스트

자동 브라우저 조작 도구가 없는 환경에서는 다음 순서로 확인한다.

1. 저장소 루트 `C:\THIRD_LLM`에서 `uv run streamlit run frontend/streamlit_app.py`로 앱을 연다.
2. `test_samples/html/nate_article_structure.html`을 업로드한다.
3. `기사 원문 불러오기`를 누르고 제목과 본문 2개 문단이 채워지는지 확인한다.
4. 랭킹·공유·푸터 문구가 본문에 포함되지 않고 이미지 후보 2개가 표시되는지 확인한다.
5. 이미지 후보 하나를 선택하고 차트 수치·축·단위를 직접 보완한다.
6. 자동 입력된 기사 제목을 수정해 값이 유지되는지 확인한다.
7. URL과 HTML을 함께 입력했을 때 HTML 내용이 우선되는지 확인한다.
8. 빈 입력으로 원문 불러오기를 눌러도 수동 입력 폼이 유지되는지 확인한다.
9. 수동 입력만 작성한 뒤 `기사 근거 검증하기`가 기존 `vc_` 결과 화면으로 이어지는지 확인한다.
10. 실제 LLM 검증은 승인된 API 키와 비용 정책이 있는 환경에서만 수행한다.

## 8. 검증 명령

```powershell
uv run python -m unittest discover -s third_agent/tests -p test_html_ingestion.py -v
uv run python -m unittest discover -s third_agent/tests -p test_ingestion_outcome.py -v
uv run python -m unittest discover -s third_agent/tests -p test_frontend_manual_input.py -v
uv run python -m unittest discover -s third_agent/tests -p test_streamlit_ui.py -v
uv run python -m unittest discover -s third_agent/guardrails -v
uv run python -m compileall third_agent/vc_agent third_agent/tests third_agent/guardrails
uv run streamlit run frontend/streamlit_app.py
```
