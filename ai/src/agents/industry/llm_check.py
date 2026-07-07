"""Smoke-test the self-hosted LLM through the project's ``get_chat_llm`` factory.

Run it any time to confirm the llama-server is reachable and that the two
capabilities the GraphRAG pipeline relies on work end-to-end:

  1. plain chat (Step 5 answering), and
  2. structured / tool-call output (Step 3 extraction, Cypher generation).

    uv run python -m src.agents.industry.llm_check
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .config import get_chat_llm


class Relation(BaseModel):
    """A single extracted company relationship (mirrors the fixed schema)."""

    source: str = Field(description="관계의 출발 기업")
    relation: str = Field(description="SUPPLIES / COMPETES_WITH / OWNS_STAKE 등")
    target: str = Field(description="관계의 도착 기업")


def main() -> None:
    llm = get_chat_llm()

    print("=== 1) plain chat ===")
    resp = llm.invoke("삼성SDI와 LG에너지솔루션의 관계를 한 문장으로 설명해줘.")
    print(resp.content)

    print("\n=== 2) structured output (tool calling) ===")
    structured = llm.with_structured_output(Relation)
    rel = structured.invoke(
        "다음 문장에서 기업 간 관계를 추출해줘: "
        "'에코프로비엠은 삼성SDI에 양극재를 공급한다'"
    )
    print(rel)

    print("\nOK: LLM 연결 및 구조화 출력 정상 동작")


if __name__ == "__main__":
    main()
