"""Hybrid retrieval: dense FAISS + BM25 lexical, optional CrossEncoder rerank."""
from __future__ import annotations

from langchain_core.documents import Document

from agent.config import settings
from agent.ingest import _tokenize, load_bm25, load_vectorstore
from agent.logger import get_logger, timed
from agent.state import AgentState

log = get_logger("retrieve")


_STORE = None
_BM25_PAYLOAD = None
_RERANKER = None


def _ensure_loaded():
    global _STORE, _BM25_PAYLOAD
    if _STORE is None:
        _STORE = load_vectorstore()
    if _BM25_PAYLOAD is None:
        _BM25_PAYLOAD = load_bm25()


def reset_retriever() -> None:
    """Drop all cached handles so the on-disk store can be safely rewritten."""
    global _STORE, _BM25_PAYLOAD, _RERANKER
    _STORE = None
    _BM25_PAYLOAD = None
    _RERANKER = None


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.0] * len(values)
    span = hi - lo
    return [(v - lo) / span for v in values]


def _rerank(query: str, docs: list[Document], top_k: int) -> list[Document]:
    global _RERANKER
    if not docs:
        return docs
    if _RERANKER is None:
        from sentence_transformers import CrossEncoder
        _RERANKER = CrossEncoder(settings.reranker_model, max_length=512)
    pairs = [(query, d.page_content) for d in docs]
    scores = _RERANKER.predict(pairs)
    order = sorted(range(len(docs)), key=lambda i: float(scores[i]), reverse=True)
    return [docs[i] for i in order[:top_k]]


def hybrid_search(query: str, k: int | None = None) -> list[Document]:
    """0.7 * dense + 0.3 * BM25, union of candidates, top-k."""
    _ensure_loaded()
    if _STORE is None:
        log.warning("no vectorstore on disk — empty retrieval")
        return []

    k = k or settings.top_k
    fetch_k = max(k * 5, 20)
    semantic_w = max(0.0, min(1.0, settings.semantic_weight))
    bm25_w = 1.0 - semantic_w

    # Dense
    dense_hits = _STORE.similarity_search_with_score(query, k=fetch_k)
    # FAISS score is L2 distance — smaller is better. Invert for similarity ranking.
    dense_ranked = [(doc, 1.0 / (1.0 + float(dist))) for doc, dist in dense_hits]

    # BM25
    bm25_by_text: dict[str, float] = {}
    if _BM25_PAYLOAD and _BM25_PAYLOAD.get("bm25") is not None:
        bm25 = _BM25_PAYLOAD["bm25"]
        texts = _BM25_PAYLOAD["texts"]
        metas = _BM25_PAYLOAD.get("metadatas", [{}] * len(texts))
        tokens = _tokenize(query)
        if tokens:
            scores = bm25.get_scores(tokens)
            # Top-N BM25 by score
            ranked = sorted(range(len(texts)), key=lambda i: float(scores[i]), reverse=True)[:fetch_k]
            for i in ranked:
                bm25_by_text[texts[i]] = float(scores[i])
            # Make sure dense hits that aren't in the BM25 top-N still get a raw score
            for doc, _ in dense_ranked:
                if doc.page_content not in bm25_by_text:
                    # BM25 score for this specific doc
                    try:
                        idx = texts.index(doc.page_content)
                        bm25_by_text[doc.page_content] = float(scores[idx])
                    except ValueError:
                        bm25_by_text[doc.page_content] = 0.0

    # Normalize each signal independently (0..1)
    all_candidates: dict[str, Document] = {}
    sem_scores: dict[str, float] = {}
    bm_scores: dict[str, float] = {}

    for doc, s in dense_ranked:
        key = doc.page_content
        all_candidates[key] = doc
        sem_scores[key] = s
    for text, s in bm25_by_text.items():
        if text not in all_candidates:
            # Build a Document for BM25-only hits
            meta = {}
            if _BM25_PAYLOAD:
                try:
                    idx = _BM25_PAYLOAD["texts"].index(text)
                    meta = _BM25_PAYLOAD.get("metadatas", [{}] * len(_BM25_PAYLOAD["texts"]))[idx] or {}
                except ValueError:
                    pass
            all_candidates[text] = Document(page_content=text, metadata=meta)
        bm_scores[text] = s

    keys = list(all_candidates.keys())
    sem_norm = _minmax([sem_scores.get(k, 0.0) for k in keys])
    bm_norm = _minmax([bm_scores.get(k, 0.0) for k in keys])

    combined = [
        (keys[i], semantic_w * sem_norm[i] + bm25_w * bm_norm[i])
        for i in range(len(keys))
    ]
    combined.sort(key=lambda x: x[1], reverse=True)

    top = [all_candidates[k] for k, _ in combined[:max(k * 3, k)]]

    if settings.use_reranking and top:
        try:
            top = _rerank(query, top, top_k=k)
        except Exception as e:
            log.warning("rerank failed (falling back to hybrid top-k): %s", e)
            top = top[:k]
    else:
        top = top[:k]

    return top


def retrieve_policy(state: AgentState) -> dict:
    query = state.get("query") or _last_user_text(state) or ""
    log.info("node=retrieve_policy query=%r", query[:120])
    if not query.strip():
        log.warning("empty query — skipping retrieval")
        return {"policy_context": []}
    try:
        with timed(log, f"hybrid_search(k={settings.top_k}) '{query[:60]}'"):
            docs: list[Document] = hybrid_search(query)
        log.info(
            "retrieved %d chunk(s) (semantic_w=%.2f · rerank=%s)",
            len(docs), settings.semantic_weight, settings.use_reranking,
        )
        for i, d in enumerate(docs, 1):
            src = d.metadata.get("source") or d.metadata.get("file_path") or "?"
            page = d.metadata.get("page")
            loc = f"{src}" + (f":p{page + 1}" if isinstance(page, int) else "")
            log.info("  [%d] %s — %d chars", i, loc, len(d.page_content))
    except Exception as e:
        log.exception("retrieval failed: %s", e)
        docs = []
    return {"policy_context": docs, "query": query}


def _last_user_text(state: AgentState) -> str | None:
    for msg in reversed(state.get("messages", [])):
        if getattr(msg, "type", None) == "human":
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return None
