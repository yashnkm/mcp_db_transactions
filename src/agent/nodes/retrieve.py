from __future__ import annotations

from langchain_core.documents import Document

from agent.ingest import load_vectorstore
from agent.state import AgentState


_RETRIEVER = None


def _retriever():
    global _RETRIEVER
    if _RETRIEVER is None:
        store = load_vectorstore()
        _RETRIEVER = store.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 4, "fetch_k": 20, "lambda_mult": 0.5},
        )
    return _RETRIEVER


def retrieve_policy(state: AgentState) -> dict:
    query = state.get("query") or _last_user_text(state) or ""
    if not query.strip():
        return {"policy_context": []}
    try:
        docs: list[Document] = _retriever().invoke(query)
    except Exception:
        docs = []
    return {"policy_context": docs, "query": query}


def _last_user_text(state: AgentState) -> str | None:
    for msg in reversed(state.get("messages", [])):
        if getattr(msg, "type", None) == "human":
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return None
