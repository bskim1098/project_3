# 팀 인수인계 전 독립 점검 보고서

점검일: 2026-07-06

## 1. 결론

현재 담당 범위인 URL/HTML 프론트 선작업과 `vc_` 최종판정 가드레일은 자동 검증 기준을 통과했다. 기획 범위를 벗어난 주장-근거 에이전트, OCR, 동적 페이지 크롤링은 구현하지 않았다.

코드상 인수인계를 막는 오류는 발견되지 않았다. 실제 브라우저 파일 선택기를 이용한 수동 업로드 확인과 승인된 API 키를 사용하는 실제 LLM 1회 확인은 사용자와 함께 수행할 항목으로 남아 있다.

### 저장소·패키지 재배치

- Git, `pyproject.toml`, `uv.lock`, `.venv` 기준 루트는 `C:\THIRD_LLM`이다.
- 팀 작업 폴더는 `C:\THIRD_LLM\3rd_agent`이고, 설치 가능한 Python 패키지는 `3rd_agent/third_agent`다.
- 숫자로 시작하는 디렉터리를 import 이름으로 사용하지 않고 모든 내부 import를 `third_agent.*`로 통일했다.
- 공용 `.venv`는 Python 3.14.3으로 재생성하고 루트 프로젝트를 editable package로 설치했다.
- Streamlit과 테스트 명령은 반드시 `C:\THIRD_LLM`에서 실행한다. 구체적인 명령은 루트 `README.md`를 기준으로 한다.

## 2. 변경 파일 인벤토리

수정 파일:

- `third_agent/agents/verdict_critic_agent.py`
- `frontend/streamlit_app.py`
- `third_agent/prompts/verdict_critic_prompt.md`
- `pyproject.toml`
- `uv.lock`

신규 파일:

- `frontend/html_ingestion.py`
- `frontend/ingestion_outcome.py`
- `frontend/technology_architecture.py`
- `docs/frontend_url_html_handoff.md`
- `docs/pre_handoff_check_report.md`
- `guardrails/test_verdict_critic_guardrails.py`
- `tests/test_html_ingestion.py`
- `tests/test_ingestion_outcome.py`
- `tests/test_frontend_manual_input.py`
- `tests/test_streamlit_ui.py`
- `test_samples/html/article_with_chart.html`
- `test_samples/html/article_with_table.html`
- `test_samples/html/article_without_metadata.html`
- `test_samples/html/generic_paragraph_article.html`
- `test_samples/html/json_ld_article.html`
- `test_samples/html/nate_article_structure.html`
- `test_samples/html/adaptive_multi_article.html`
- `test_samples/html/nate_br_article_structure.html`
- `test_samples/html/adaptive_competing_containers.html`
- `test_samples/html/mixed_paragraph_break_article.html`
- `test_samples/html/malformed_noscript_iframe_article.html`
- `test_samples/html/expected_extractions.json`

제외 확인:

- `.env`, `.venv`, Python cache, 테스트 cache, `temp_uploads`는 `.gitignore` 대상이다.
- DOM 범위 추출을 위해 `beautifulsoup4` 의존성을 추가했고 `pyproject.toml`, `uv.lock`을 갱신했다.
- 현재 변경사항은 아직 커밋되지 않았다.

## 3. 계약 무결성 점검

통과 항목:

- `vc_` 출력은 기존 6개만 유지한다.
- 새로운 `vc_` 변수나 state 필드를 추가하지 않았다.
- `third_agent/state/news_chart_check_state.py`는 내용 계약을 변경하지 않았다.
- `verdict_critic_agent`는 `input_`, `ce_`, `ig_`를 읽기만 하고 다른 접두사 변수를 작성하지 않는다.
- 최종 `vc_` 반환은 `pick_vc_only`를 거쳐 기존 key만 포함한다.
- URL 문자열은 LLM 입력으로 전달하지 않는다.
- URL은 HTML 확보에만 사용하고, 추출 후 사용자가 확인한 폼 값만 기존 state에 전달한다.
- URL과 HTML 파일이 함께 있으면 HTML 파일을 우선한다.
- 발견 이미지는 후보로만 표시하며 사용자가 선택한 이미지만 기존 `input_chart_image_paths` 흐름에 저장한다.
- 기존 수동 입력 경로와 `기사 근거 검증하기` 버튼을 유지한다.
- Streamlit의 실제 제출 경로가 컴파일된 LangGraph를 실행한다.
- 그래프 실행 결과는 `pick_vc_only`를 거쳐 `vc_` 여섯 필드만 후속 병합에 전달한다.

기존 `vc_` 계약:

```text
vc_recommended_judgement
vc_unsafe_expressions
vc_revision_needed
vc_revision_reason
vc_safe_expression
vc_critic_notes
```

## 4. 보안 및 사용자 문구 점검

확인된 URL 방어:

- HTTP/HTTPS만 허용
- URL 내 사용자명·비밀번호 차단
- localhost, 사설·루프백·링크 로컬 IP 차단
- DNS 결과의 사설 IPv4·IPv6 차단
- 리다이렉트 연결 전 대상 URL과 DNS 재검사
- 최종 응답 URL 재검사
- 12초 timeout과 5MB 응답 제한
- HTML 이외 응답 차단
- 선택 이미지에 12초 timeout, 10MB 제한, JPEG·PNG·WebP MIME 검사를 적용
- 사용자에게 안전한 오류 안내를 표시하고 상세 예외는 서버 로그에만 기록
- 401·403·429·451은 `접근 제한`, 404·410·timeout·DNS·비HTML은 `불러오기 실패`로 구분

사용자 화면 점검:

- `가짜뉴스 판독하기`, `조작 판정`, `허위 판정`과 같은 단정적 UI 문구가 없다.
- 실행 버튼은 `기사 근거 검증하기`다.
- 원문 입력 실패 후에도 기존 수동 입력을 계속 사용할 수 있다.
- HTML 확보 후 품질이 낮거나 후보가 충돌하면 잘못 확정하지 않고 `불확실`로 표시한다.
- 이미지 후보가 없는 텍스트 기사도 제목·본문 품질이 충분하면 `성공`으로 표시한다.

운영 환경 한계:

- DNS 검사와 실제 연결 사이의 DNS rebinding 가능성은 네트워크 egress 정책 또는 고정 프록시로 보완해야 한다.
- 로그인, 유료벽, 봇 차단, JavaScript 렌더링 페이지는 현재 범위에서 자동 우회하거나 렌더링하지 않는다.
- 이미지 픽셀 OCR과 차트 축·범례·수치 판독은 현재 URL/HTML 전처리 책임이 아니다.

## 5. 자동 검증 결과

실행 결과:

- 가드레일 테스트: 5개 통과
- fixture·HTML 파싱·수집 상태·기술 아키텍처·URL/이미지 보안·수동 입력·Streamlit UI 테스트: 50개 통과
- 가드레일 포함 전체 테스트: 55개 통과
- 전체 Python 컴파일: 성공
- Streamlit 서버 기동: 성공
- HTTP 응답: `200`, `text/html; charset=utf-8`
- 검증 후 서버 종료: 성공
- `git diff --check`: 오류 없음
- 실제 네이트 URL: 본문 26개 문단, 핫뉴스·기자 이메일 제거와 원본 이미지 후보 2개 추출 확인
- 중앙일보 제휴 네이트 URL: br 기반 본문 7개 문단과 이미지 후보 1개 추출, 일반 이미지 캡션·추천뉴스 제외 확인
- 실제 네이트 이미지: JPEG 37,715바이트 안전 다운로드 확인
- 실제 뉴스프리존 URL: 사이트 프로필 없이 본문 19개 문단, 표 이미지 1개, 시각자료·출처 후보 각 1개 추출 확인
- 실제 MBN URL: 비정상 noscript iframe 정규화 후 본문 11개 문단, 이미지 1개, 시각자료·출처 후보 각 2개 추출 확인
- 실제 상태 분류: 네이트·MBN은 `success`, 한국경제 HTTP 403은 `access_restricted` 확인

Streamlit UI 테스트 중 출력되는 `missing ScriptRunContext` 메시지는 AppTest의 bare mode 경고이며 테스트 실패가 아니다.

## 6. 사용자와 함께 확인할 항목

1. 실제 브라우저에서 `test_samples/html/nate_article_structure.html`을 선택해 업로드한다.
2. 자동 채움된 제목·본문과 이미지 후보 2개를 육안으로 확인한다.
3. 실제 검토할 이미지 후보를 선택하고 수치·축·단위를 직접 보완한다.
4. 자동 입력값을 수정한 뒤 값이 유지되는지 확인한다.
5. URL과 HTML 파일을 함께 입력해 HTML 파일이 우선되는지 확인한다.
6. 승인된 API 키와 비용 정책이 있으면 `기사 근거 검증하기`를 한 번 실행해 실제 결과 화면을 확인한다.
7. 검토 후 커밋 및 원격 저장소 반영 여부를 결정한다.

## 7. 팀원에게 인계할 작업

- `HTMLTextBlocks`를 입력으로 받는 주장-근거 검증 에이전트 구현
- 임시 `make_temp_ce_state`, `make_temp_ig_state` 교체
- 기존 `ce_` 출력 계약에 맞춘 기사 주장·차트 사실·1차 판정 생성
- OCR 담당 범위와 이미지 장기 저장 정책 결정
- 동적 페이지 지원 여부 결정
- 운영 환경 네트워크 egress 정책 결정
- 실제 뉴스 HTML 표본을 이용한 추출 정확도 평가

인계 범위에서 지켜야 할 경계:

- 실제 `ce_`·`ig_` 에이전트는 현재의 `make_temp_ce_state`, `make_temp_ig_state`를 교체하되 기존 state key를 유지한다.
- 전체 팀 LangGraph에서는 `make_verdict_critic_node(llm)`를 최종 검토 노드로 연결한다.
- 3번 에이전트는 `input_`, `ce_`, `ig_`를 읽고 `vc_`만 작성한다.
- GraphRAG, 외부 팩트 검색, OCR은 별도 책임과 데이터 정책이 합의되기 전 3번 에이전트에 추가하지 않는다.

자세한 연결 계약과 수동 확인 절차는 `docs/frontend_url_html_handoff.md`를 참조한다.
