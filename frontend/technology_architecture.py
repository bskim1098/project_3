"""프로젝트에서 사용하는 LLM 기술의 실제 적용 구조를 설명한다.

아키텍처 설명은 실행 코드와 분리해 테스트와 Streamlit 화면에서 함께 사용한다.
GraphRAG처럼 아직 적용하지 않은 기술은 구성된 것처럼 표시하지 않는다.
"""

from __future__ import annotations

from typing import Literal, TypedDict


TechnologyStatus = Literal["적용됨", "도입 예정", "미적용"]


class TechnologyArchitecture(TypedDict):
    name: str
    status: TechnologyStatus
    purpose: str
    flow: tuple[str, ...]
    handoff: str


def get_technology_architectures() -> tuple[TechnologyArchitecture, ...]:
    """현재 저장소 코드와 일치하는 기술별 아키텍처를 반환한다."""
    return (
        {
            "name": "GraphRAG",
            "status": "도입 예정",
            "purpose": "전체 업무의 60%를 담당하는 first_agent의 관계·출처 보조 검색에 적용할 예정입니다.",
            "flow": ("graph builder", "retriever", "provenance", "ce_ 보조 근거"),
            "handoff": "준영님이 검색 출처와 기사 내부 근거를 구분하는 정책과 함께 구현합니다.",
        },
        {
            "name": "LangGraph",
            "status": "적용됨",
            "purpose": "ce_agent의 단계별 검증과 vc_agent의 최종 검토 실행 순서를 관리합니다.",
            "flow": (
                "ce: START",
                "chart_extraction",
                "claim_extraction",
                "compare_and_judge",
                "guardrail",
                "ce: END",
                "vc: START",
                "verdict_critic",
                "vc: END",
            ),
            "handoff": "동일 state와 gpt-5.4-mini 인스턴스를 ce_agent에서 vc_agent 순서로 전달합니다.",
        },
        {
            "name": "LangChain",
            "status": "적용됨",
            "purpose": "프롬프트, OpenAI 모델 호출, structured output을 구성합니다.",
            "flow": (
                "ChatPromptTemplate",
                "ChatOpenAI",
                "structured output",
                "ce_ structured summary",
                "ce_·vc_ guardrails",
            ),
            "handoff": "모델을 교체해도 ce_와 vc_의 structured output 계약을 유지합니다.",
        },
    )


def format_technology_architectures() -> str:
    """터미널·문서에서도 확인할 수 있는 평문 아키텍처를 만든다."""
    sections = []
    for architecture in get_technology_architectures():
        flow = " → ".join(architecture["flow"])
        sections.append(
            "\n".join(
                (
                    f"[{architecture['name']}] {architecture['status']}",
                    architecture["purpose"],
                    f"구조: {flow}",
                    f"인계: {architecture['handoff']}",
                )
            )
        )
    return "\n\n".join(sections)


if __name__ == "__main__":
    print(format_technology_architectures())
