"""Policy Q&A agent built with a LangGraph StateGraph.

Flow:
    retrieve  ->  generate  ->  log

The agent answers HR policy questions via RAG over policy PDFs stored in
Qdrant. Tools ``qdrant_search`` and ``get_policy_doc`` are exposed and used by
the graph nodes. Every query and response is logged to the audit table.

If LangGraph is not installed the agent transparently falls back to a plain
sequential implementation with identical behaviour, so the system remains
runnable in lightweight environments.
"""

from __future__ import annotations

from typing import Any, TypedDict

from core.memory import memory
from core.vectorstore import vector_store
from pipelines.rag_pipeline import rag_pipeline

AGENT_NAME = "policy_qa_agent"


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def qdrant_search(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Tool: search the Qdrant policy collection.

    Args:
        query: Natural-language search query.
        top_k: Number of chunks to retrieve.

    Returns:
        Ranked list of chunk dicts.
    """
    return vector_store.search(query, top_k=top_k)


def get_policy_doc(doc_id: str) -> list[dict[str, Any]]:
    """Tool: fetch all chunks for a specific policy document.

    Args:
        doc_id: Document identifier.

    Returns:
        List of chunk dicts belonging to the document.
    """
    return vector_store.get_by_doc_id(doc_id)


# --------------------------------------------------------------------------- #
# Graph state
# --------------------------------------------------------------------------- #
class PolicyQAState(TypedDict, total=False):
    """State object threaded through the LangGraph nodes."""

    query: str
    contexts: list[dict[str, Any]]
    answer: str
    source_documents: list[dict[str, Any]]
    confidence_score: float


class PolicyQAAgent:
    """LangGraph-powered RAG agent for HR policy questions."""

    def __init__(self) -> None:
        """Build the compiled state graph (or fallback runner)."""
        self._graph = self._build_graph()

    # -- nodes ------------------------------------------------------------
    def _retrieve_node(self, state: PolicyQAState) -> PolicyQAState:
        """Graph node: retrieve relevant policy chunks via the search tool."""
        contexts = qdrant_search(state["query"])
        return {**state, "contexts": contexts}

    def _generate_node(self, state: PolicyQAState) -> PolicyQAState:
        """Graph node: synthesise an answer from retrieved contexts."""
        result = rag_pipeline.query(state["query"])
        return {
            **state,
            "answer": result["answer"],
            "source_documents": result["source_documents"],
            "confidence_score": result["confidence_score"],
        }

    # -- graph construction ----------------------------------------------
    def _build_graph(self):
        """Compile a LangGraph StateGraph, or return None to use the fallback."""
        try:
            from langgraph.graph import END, StateGraph

            graph = StateGraph(PolicyQAState)
            graph.add_node("retrieve", self._retrieve_node)
            graph.add_node("generate", self._generate_node)
            graph.set_entry_point("retrieve")
            graph.add_edge("retrieve", "generate")
            graph.add_edge("generate", END)
            return graph.compile()
        except Exception:  # noqa: BLE001 - LangGraph optional at runtime
            return None

    # -- public API -------------------------------------------------------
    async def run(self, query: str) -> dict[str, Any]:
        """Answer an HR policy question and log the interaction.

        Args:
            query: The employee's question.

        Returns:
            Dict with ``answer``, ``source_documents`` and ``confidence_score``.
        """
        await memory.upsert_agent(AGENT_NAME, status="running", last_action="policy query")

        # Prompt-injection defense: refuse + audit before retrieval/synthesis.
        from core.guardrails import REFUSAL_MESSAGE, detect_prompt_injection

        if detect_prompt_injection(query):
            blocked = {
                "answer": REFUSAL_MESSAGE,
                "source_documents": [],
                "confidence_score": 0.0,
                "needs_review": True,
            }
            await memory.log_audit(
                AGENT_NAME,
                "prompt_injection_blocked",
                {"query": query},
                blocked,
                "blocked",
            )
            await memory.upsert_agent(
                AGENT_NAME, status="idle", last_action="blocked injection attempt"
            )
            return blocked

        try:
            # Retrieval routes through the active vector backend (pgvector on
            # Postgres, else Qdrant, else degraded) via the RAG service.
            from services import rag

            result = await rag.query(query)

            await memory.log_audit(AGENT_NAME, "policy_query", {"query": query}, result, "success")
            await memory.upsert_agent(
                AGENT_NAME,
                status="idle",
                last_action="answered policy query",
                increment_runs=True,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            await memory.log_audit(
                AGENT_NAME,
                "policy_query",
                {"query": query},
                {"error": str(exc)},
                "error",
            )
            await memory.upsert_agent(AGENT_NAME, status="error", last_action=str(exc))
            raise


policy_qa_agent = PolicyQAAgent()
