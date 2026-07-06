# Multi-Agent Supervisor

1st_agent와 3rd_agent를 연결하는 협업용 오케스트레이션 작업 공간이다.

작업 폴더는 `supervisor`, Python import 패키지는 `multi_agent_supervisor`다. 폴더와 패키지 이름을 분리해 namespace 충돌을 방지한다.

현재는 구조와 책임 계약만 제공하며 실제 에이전트 로직은 구현하지 않는다. 전체 업무의 60%를 담당하는 1st_agent가 `ce_`를 생성한 뒤 3rd_agent가 `vc_` 최종 검토를 수행하는 순서를 기준으로 한다.
