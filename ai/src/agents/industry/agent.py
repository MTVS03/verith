"""Step 6 — LangGraph agent: classify -> generate_cypher -> execute -> answer.

Step 5 (:mod:`retrieve`) already has the three primitives working. This step
wires them into a LangGraph state machine so a single question flows through
automatically (the Step 6 DoD) *and* — the part a plain function chain can't do
— retries when a query comes back empty or errors.

    classify --(relational/factual)--> generate_cypher -> execute_cypher --(ok)--> generate_answer -> END
        |             ^                        |
        |             └──(empty/error, retries left: inject hint)──┘
        └──(global)──> structural_overview ─────────────────────────────> generate_answer

Design decisions (see memory / the Step 6 A/B test):

* **thinking OFF everywhere.** The A/B test showed ``enable_thinking=True`` gives
  no quality gain (sometimes worse Cypher) at 10-40x latency, so there is no
  "relational -> thinking ON" branch. The agent's real value is the re-query
  loop, which catches exactly the empty/wrong-Cypher failure mode.
* **``classify`` branches only for the *global* question.** Relational and
  factual questions both take the same single-Cypher path (splitting them buys
  nothing). But a whole-structure summary (benchmark Q5) can't be served by one
  NL->Cypher query — the model over-constrains and returns nothing. So the
  ``global`` label routes to :func:`_structural_overview`, which runs a fixed set
  of aggregate queries (competition degree, industry membership, supply hubs) and
  hands the combined structure to the answerer. This is the MVP stand-in for
  community detection; GDS Louvain is the documented next step if needed.
* **``generate_cypher`` and ``execute_cypher`` are separate nodes.** The retry
  edge targets only the LLM step, and the DB side-effect stays isolated so a
  loop can't accidentally re-run a successful write.

Run:
    uv run python -m src.agents.industry.agent "삼성SDI와 경쟁하는 기업은?"
    uv run python -m src.agents.industry.agent --trace "..."   # per-node log
"""

from __future__ import annotations

import argparse
from typing import TypedDict

from langgraph.graph import END, StateGraph

from .companies import COMPANIES
from .config import get_chat_llm, get_neo4j_graph
from .retrieve import MAX_CONTEXT_ROWS, generate_answer, generate_cypher
from .schema import CYPHER_SCHEMA
from .vector_retrieve import vector_search

# Up to this many Cypher generations per question (1 initial + retries). Small on
# purpose: if two re-queries with failure hints still return nothing, the honest
# answer is "no connection found", not more spins.
MAX_ATTEMPTS = 3


class AgentState(TypedDict, total=False):
    """State threaded through the graph. ``total=False`` so early nodes needn't
    pre-populate downstream keys."""

    question: str      # the user's Korean question (immutable input)
    label: str         # classify output: "relational" | "factual" (observability)
    cypher: str        # latest generated Cypher
    rows: list[dict]   # latest query result
    chunks: list[dict] # vector-retrieved source chunks for qualitative/fallback answers
    error: str         # execute_cypher failure message, "" on success (retry hint)
    attempts: int      # Cypher generations so far (retry counter)
    stalled: bool      # regeneration converged to the same Cypher -> stop retrying
    answer: str        # final grounded Korean answer


# --- classify ----------------------------------------------------------------
# A tiny, thinking-OFF LLM call that tags the question. It does NOT change the
# route (both labels flow to the same Cypher path); it exists so the DoD's
# "classify" stage is real and so traces show what kind of question came in.
_CLASSIFY_PROMPT = """\
다음 질문을 세 유형 중 하나로 분류하고 라벨 한 단어만 출력하라.
- global: 산업 전체의 구조·경쟁 구도·세력권을 통째로 요약/조감하라는 질문
- qualitative: 경쟁 포지션, 강점/약점, 전망, 리스크처럼 원문 설명을 종합해야 하는 정성 질문
- relational: 특정 기업 간 관계·공급망·경쟁·지분·산업/정책 연결을 묻는 질문
- factual: 단일 사실 조회

질문: {question}
라벨:"""


def _classify(state: AgentState, *, llm) -> AgentState:
    resp = llm.invoke(_CLASSIFY_PROMPT.format(question=state["question"]))
    text = resp.content.lower()
    if "global" in text:
        label = "global"
    elif "qualitative" in text:
        label = "qualitative"
    elif "factual" in text:
        label = "factual"
    else:
        label = "relational"
    return {"label": label}


def _is_hub_question(question: str) -> bool:
    hub_markers = ("허브", "핵심 공급자", "중심 공급자", "공통으로 의존", "공통으로 연결")
    graph_scope_markers = (
        "이 산업",
        "산업 전체",
        "여러 기업",
        "다수 기업",
        "공통",
        "전체",
        "전반",
        "공급망 전체",
    )
    return any(marker in question for marker in hub_markers) and any(
        marker in question for marker in graph_scope_markers
    )


def _route_after_classify(state: AgentState) -> str:
    """A global/whole-structure question skips NL->Cypher for the fixed overview."""
    if state.get("label") == "global" or _is_hub_question(state["question"]):
        return "overview"
    if state.get("label") == "qualitative":
        return "vector"
    return "cypher"


# --- structural_overview (global questions only) -----------------------------
# One NL->Cypher query can't summarize a whole graph — the answer *is* the
# community structure. These three aggregate queries approximate it without GDS:
# who competes with the most rivals (competition hubs / rival camps), which
# industries hold the most companies (membership clusters), and who supplies the
# most customers (dependency hubs). Their combined output is enough for the
# answerer to sketch the industry's power blocs and cross-cutting nodes.
_OVERVIEW_QUERIES = {
    "경쟁_상위": (
        "MATCH (a:Company)-[:COMPETES_WITH]-(b:Company) "
        "WITH a, count(DISTINCT b) AS deg RETURN a.name AS company, deg "
        "ORDER BY deg DESC LIMIT 10"
    ),
    "산업별_소속": (
        "MATCH (c:Company)-[:BELONGS_TO]->(i:Industry) "
        "WITH i, collect(c.name) AS members, count(*) AS n WHERE n >= 2 "
        "RETURN i.name AS industry, n, members[0..6] AS sample "
        "ORDER BY n DESC LIMIT 10"
    ),
    "공급_허브": (
        "MATCH (s:Company)-[:SUPPLIES]->(c:Company) "
        "WITH s, count(DISTINCT c) AS deg WHERE deg >= 3 "
        "RETURN s.name AS supplier, deg ORDER BY deg DESC LIMIT 10"
    ),
}


def _structural_overview(state: AgentState, *, graph) -> AgentState:
    """Run the fixed aggregate queries and pack them as a single context row for
    the answerer. Threaded through the same ``rows``/``cypher`` state keys so
    ``generate_answer`` and ``--trace`` work unchanged."""
    overview = {view: graph.query(q) for view, q in _OVERVIEW_QUERIES.items()}
    combined_cypher = "\n".join(f"// {view}\n{q}" for view, q in _OVERVIEW_QUERIES.items())
    return {"rows": [overview], "cypher": combined_cypher, "error": "", "attempts": 1}


# --- generate_cypher ---------------------------------------------------------
# Wraps retrieve.generate_cypher. On a retry (attempts > 0 with a prior failure)
# it augments the question with the previous Cypher + why it failed, so the model
# corrects rather than regenerating the same dead query.
_RETRY_HINT = """\
[재시도 안내] 직전 시도가 실패했다. 아래를 참고해 **다른** Cypher를 작성하라.
- 직전 Cypher: {cypher}
- 실패 원인: {reason}
스키마의 라벨/관계 방향을 다시 확인하고, 산업·정책은 CONTAINS 키워드로 매칭했는지 점검하라."""


def _augmented_question(state: AgentState) -> str:
    """Base question, plus a correction hint when the previous attempt failed."""
    if not state.get("attempts"):
        return state["question"]
    reason = state.get("error") or "조회 결과가 비어 있었다 (0 rows)."
    hint = _RETRY_HINT.format(cypher=state.get("cypher", ""), reason=reason)
    return f"{state['question']}\n\n{hint}"


def _generate_cypher(state: AgentState, *, schema: str, llm) -> AgentState:
    cypher = generate_cypher(_augmented_question(state), schema=schema, llm=llm)
    # If a retry regenerates the exact same query, the model has converged and
    # more retries can't help — flag it so _should_retry stops (an empty result
    # then means the data genuinely isn't there, not a fixable bad query).
    prev = state.get("cypher")
    stalled = bool(state.get("attempts")) and cypher == prev
    return {"cypher": cypher, "attempts": state.get("attempts", 0) + 1, "stalled": stalled}


# --- execute_cypher ----------------------------------------------------------
# Pure DB step, isolated from the LLM. Records rows on success, or the error
# message (and empties rows) on failure — either way the retry edge reads state.
def _execute_cypher(state: AgentState, *, graph) -> AgentState:
    try:
        rows = graph.query(state["cypher"])
        return {"rows": rows, "error": ""}
    except Exception as exc:  # invalid Cypher, syntax, etc. -> feed back as hint
        return {"rows": [], "error": str(exc).splitlines()[0][:200]}


def _should_retry(state: AgentState) -> str:
    """Route after execution: retry the Cypher, or go answer."""
    if state.get("stalled"):  # regeneration converged; retrying is futile
        return "vector"
    failed = bool(state.get("error")) or len(state.get("rows", [])) == 0
    if failed and state.get("attempts", 0) < MAX_ATTEMPTS:
        return "retry"
    if failed:
        return "vector"
    return "answer"


# --- retrieve_chunks ---------------------------------------------------------
def _mentioned_company(question: str) -> str | None:
    for company in COMPANIES:
        names = [company.canonical, *company.aliases, company.stock_code]
        if any(name and name in question for name in names):
            return company.canonical
    return None


def _retrieve_chunks(state: AgentState, *, graph) -> AgentState:
    company = _mentioned_company(state["question"])
    chunks = vector_search(state["question"], k=5, company=company, graph=graph)
    return {"chunks": chunks, "error": state.get("error", "")}


# --- generate_answer ---------------------------------------------------------
def _generate_answer(state: AgentState, *, llm) -> AgentState:
    answer = generate_answer(
        state["question"],
        state.get("rows", []),
        state.get("chunks", []),
        llm=llm,
    )
    return {"answer": answer}


def build_agent(graph, *, classify_llm=None, cypher_llm=None, qa_llm=None):
    """Compile the LangGraph app, closing over ``graph`` and the LLMs.

    LangGraph nodes are functions of state alone, so the graph handle and the
    (reused) LLM clients are bound here rather than threaded through state.
    All LLMs default to ``enable_thinking=False`` per the A/B finding.
    """
    schema = CYPHER_SCHEMA
    classify_llm = classify_llm or get_chat_llm(enable_thinking=False, max_tokens=16)
    cypher_llm = cypher_llm or get_chat_llm(enable_thinking=False, max_tokens=1024)
    qa_llm = qa_llm or get_chat_llm(enable_thinking=False, max_tokens=1500)

    builder = StateGraph(AgentState)
    builder.add_node("classify", lambda s: _classify(s, llm=classify_llm))
    builder.add_node(
        "generate_cypher", lambda s: _generate_cypher(s, schema=schema, llm=cypher_llm)
    )
    builder.add_node("execute_cypher", lambda s: _execute_cypher(s, graph=graph))
    builder.add_node(
        "structural_overview", lambda s: _structural_overview(s, graph=graph)
    )
    builder.add_node("retrieve_chunks", lambda s: _retrieve_chunks(s, graph=graph))
    builder.add_node("generate_answer", lambda s: _generate_answer(s, llm=qa_llm))

    builder.set_entry_point("classify")
    builder.add_conditional_edges(
        "classify",
        _route_after_classify,
        {"overview": "structural_overview", "vector": "retrieve_chunks", "cypher": "generate_cypher"},
    )
    builder.add_edge("structural_overview", "generate_answer")
    builder.add_edge("retrieve_chunks", "generate_answer")
    builder.add_edge("generate_cypher", "execute_cypher")
    builder.add_conditional_edges(
        "execute_cypher",
        _should_retry,
        {"retry": "generate_cypher", "vector": "retrieve_chunks", "answer": "generate_answer"},
    )
    builder.add_edge("generate_answer", END)
    return builder.compile()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Step 6: answer a Korean question via the LangGraph agent."
    )
    parser.add_argument("question", help="자연어 질문 (한국어)")
    parser.add_argument("--trace", action="store_true",
                        help="노드별 진행 상황(분류/Cypher/행수/재시도)을 출력")
    args = parser.parse_args()

    graph = get_neo4j_graph()
    try:
        app = build_agent(graph)
        final = app.invoke({"question": args.question})

        if args.trace:
            print(f"--- 분류 --- {final.get('label')}")
            print(f"--- Cypher (시도 {final.get('attempts')}회) ---")
            print(final.get("cypher"))
            rows = final.get("rows", [])
            print(f"\n--- 조회 결과 ({len(rows)} rows) ---")
            for row in rows[:MAX_CONTEXT_ROWS]:
                print(row)
            if len(rows) > MAX_CONTEXT_ROWS:
                print(f"  ... ({len(rows) - MAX_CONTEXT_ROWS} more)")
            chunks = final.get("chunks", [])
            print(f"\n--- 벡터 청크 ({len(chunks)} chunks) ---")
            for i, chunk in enumerate(chunks[:5], 1):
                score = chunk.get("score")
                score_text = f"{score:.3f}" if isinstance(score, float) else "n/a"
                print(f"[V{i}] {chunk.get('company')} · {chunk.get('section')} · {score_text}")
            print("\n--- 답변 ---")
        print(final.get("answer"))
    finally:
        graph.close()


if __name__ == "__main__":
    main()
