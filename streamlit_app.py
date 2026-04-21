"""Transaction Analysis — Streamlit POC UI.

Run:
    streamlit run streamlit_app.py
"""
from __future__ import annotations

# Silence transformers' lazy-module deprecation spam BEFORE any import.
import warnings
warnings.filterwarnings("ignore", message="Accessing `__path__`.*")
warnings.filterwarnings("ignore", category=UserWarning, module="transformers.*")

import sys
from pathlib import Path
from uuid import uuid4

# Make src/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import pandas as pd
import streamlit as st
from langchain_core.messages import HumanMessage

from agent.config import settings
from agent.graph import build_graph
from agent.logger import get_logger

_ui_log = get_logger("ui")
from agent.ingest import (
    add_files,
    list_policy_files,
    rebuild_from_policies_dir,
    vectorstore_stats,
)
from agent.inspect_db import TABLES, list_columns, row_count, sample_rows


# =============================================================================
# Page setup
# =============================================================================

st.set_page_config(
    page_title="Transaction Analysis",
    page_icon=":material/analytics:",
    layout="wide",
    initial_sidebar_state="expanded",
)


EXAMPLE_QUERIES = {
    ":material/shield: Is this account PB-secured?": "Is account 4111%3344 on 2026-04-10 PB-secured?",
    ":material/receipt_long: Show a recap batch": "Show me the details of recap R00010",
    ":material/analytics: Decline breakdown by MCC": "How many declines happened last week by MCC?",
    ":material/policy: What does auth_type_code mean?": "Explain what auth_type_code = 2 means per our policies",
}


# =============================================================================
# Cached resources
# =============================================================================


@st.cache_resource(show_spinner="Compiling agent graph…")
def get_graph():
    return build_graph()


@st.cache_data(ttl=30, show_spinner=False)
def cached_row_count(table: str) -> int | None:
    try:
        return row_count(table)
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def cached_columns(table: str):
    try:
        return list_columns(table)
    except Exception:
        return []


@st.cache_data(ttl=30, show_spinner=False)
def cached_sample(table: str):
    try:
        return sample_rows(table, limit=5)
    except Exception:
        return [], []


@st.cache_data(ttl=10, show_spinner=False)
def cached_vstore_stats():
    return vectorstore_stats()


@st.cache_data(ttl=10, show_spinner=False)
def cached_policy_files():
    return list_policy_files()


def invalidate_caches():
    cached_row_count.clear()
    cached_sample.clear()
    cached_vstore_stats.clear()
    cached_policy_files.clear()


# =============================================================================
# Session state
# =============================================================================

if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"ui-{uuid4().hex[:8]}"
if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_sources" not in st.session_state:
    st.session_state.last_sources = []
if "last_intent" not in st.session_state:
    st.session_state.last_intent = None
if "last_tool" not in st.session_state:
    st.session_state.last_tool = ""
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None


def reset_thread():
    st.session_state.thread_id = f"ui-{uuid4().hex[:8]}"
    st.session_state.messages = []
    st.session_state.last_sources = []
    st.session_state.last_intent = None
    st.session_state.last_tool = ""
    st.session_state.pending_prompt = None


# =============================================================================
# Sidebar
# =============================================================================

with st.sidebar:
    st.markdown("### :material/analytics: Transaction Analysis")

    with st.container(border=True):
        st.markdown("**:material/smart_toy: Model**")
        st.code(f"{settings.llm_provider}:{settings.llm_model}", language=None)

    with st.container(border=True):
        st.markdown("**:material/forum: Session**")
        st.code(st.session_state.thread_id, language=None)
        if st.button(
            "New thread",
            icon=":material/refresh:",
            width="stretch",
            type="secondary",
        ):
            reset_thread()
            st.rerun()

    with st.container(border=True):
        st.markdown("**:material/database: Schema**")
        for t in TABLES:
            n = cached_row_count(t)
            if n is None:
                st.markdown(f"- `{t}` :red-badge[unreachable]")
            else:
                st.markdown(f"- `{t}` :blue-badge[{n:,}]")


# =============================================================================
# Header + KPI row
# =============================================================================

st.title("Transaction analysis", anchor=False)


# =============================================================================
# Query processor (shared by chat input + suggestion pills)
# =============================================================================


def run_pipeline(prompt: str):
    """Invoke the graph once and stash outputs in session_state."""
    _ui_log.info(
        "━━━━ TURN START thread=%s prompt=%r",
        st.session_state.thread_id, prompt[:140],
    )
    try:
        result = get_graph().invoke(
            {"query": prompt, "messages": [HumanMessage(content=prompt)]},
            config={"configurable": {"thread_id": st.session_state.thread_id}},
        )
        answer = result.get("answer") or "(no answer)"
        st.session_state.last_sources = result.get("policy_context", []) or []
        st.session_state.last_intent = result.get("intent")
        st.session_state.last_tool = result.get("db_tool_used") or ""
        _ui_log.info(
            "━━━━ TURN END thread=%s answer_chars=%d tool=%s",
            st.session_state.thread_id, len(answer),
            st.session_state.last_tool or "-",
        )
    except Exception as e:
        _ui_log.exception("pipeline failed: %s", e)
        answer = f":red-badge[Error] `{type(e).__name__}: {e}`"
        st.session_state.last_sources = []
        st.session_state.last_intent = None
        st.session_state.last_tool = ""
    return answer


# =============================================================================
# Tabs
# =============================================================================

tab_chat, tab_policies, tab_db = st.tabs(
    [":material/chat: Chat", ":material/upload_file: Policies", ":material/database: Database"]
)


# ------------------------------------------------------------------------
# Chat tab
# ------------------------------------------------------------------------

with tab_chat:
    chat_col, trace_col = st.columns([2, 1], gap="large")

    with chat_col:
        # Render existing messages
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        typed_prompt = st.chat_input("Ask a question")
        prompt = st.session_state.pending_prompt or typed_prompt
        st.session_state.pending_prompt = None

        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner(":material/bolt: Retrieving · classifying · querying…"):
                    answer = run_pipeline(prompt)
                st.markdown(answer)
            st.session_state.messages.append({"role": "assistant", "content": answer})
            st.rerun()

    with trace_col:
        st.markdown("**:material/timeline: Pipeline trace**")

        with st.expander(":material/article: Retrieved policy snippets", expanded=True):
            if not st.session_state.last_sources:
                st.empty()
            else:
                for i, d in enumerate(st.session_state.last_sources, 1):
                    src = d.metadata.get("source") or d.metadata.get("file_path") or "unknown"
                    page = d.metadata.get("page")
                    loc = Path(src).name + (f" · p.{page + 1}" if isinstance(page, int) else "")
                    st.markdown(f":blue-badge[{i}] `{loc}`")
                    snippet = d.page_content[:420] + ("…" if len(d.page_content) > 420 else "")
                    st.caption(snippet)

        with st.expander(":material/psychology: Parsed intent", expanded=False):
            intent = st.session_state.last_intent
            if intent is None:
                st.empty()
            else:
                st.markdown(f"- **action** · `{intent.action}`")
                st.markdown(f"- **target_table** · `{intent.target_table}`")
                st.markdown(
                    f"- **entities** · `{intent.entities if intent.entities else '—'}`"
                )
                if intent.policy_constraints:
                    st.markdown("- **policy_constraints**")
                    for c in intent.policy_constraints:
                        st.markdown(f"  - {c}")
                if intent.needs_clarification:
                    st.warning(
                        f":material/help: {intent.clarification_question}",
                        icon=":material/help:",
                    )

        with st.expander(":material/database: DB tool used", expanded=False):
            if not st.session_state.last_tool:
                st.empty()
            else:
                st.markdown(f":green-badge[{st.session_state.last_tool}]")


# ------------------------------------------------------------------------
# Policies tab
# ------------------------------------------------------------------------

with tab_policies:
    files = cached_policy_files()
    vstats_now = cached_vstore_stats()

    pol_kpi = st.columns(3)
    with pol_kpi[0]:
        st.metric("Source files", str(len(files)), border=True)
    with pol_kpi[1]:
        st.metric(
            "Vector chunks",
            f"{vstats_now.get('chunks', 0):,}" if vstats_now.get("ok") else "error",
            border=True,
        )
    with pol_kpi[2]:
        st.metric(
            "Embedding model",
            settings.embeddings_model,
            border=True,
        )

    upload_col, files_col = st.columns([2, 1], gap="large")

    with upload_col:
        st.subheader("Ingest new documents", anchor=False)
        uploads = st.file_uploader(
            "Upload",
            type=["pdf", "md", "txt"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        btn_a, btn_b = st.columns(2)
        with btn_a:
            if st.button(
                "Ingest uploaded files",
                icon=":material/upload:",
                type="primary",
                width="stretch",
                disabled=not uploads,
            ):
                settings.policies_dir.mkdir(parents=True, exist_ok=True)
                saved: list[Path] = []
                for f in uploads:
                    dest = settings.policies_dir / f.name
                    dest.write_bytes(f.getvalue())
                    saved.append(dest)
                try:
                    with st.spinner("Embedding and indexing…"):
                        result = add_files([str(p) for p in saved])
                    invalidate_caches()
                    st.toast(
                        f"Indexed {result['chunks_added']:,} chunks from {len(result['copied'])} file(s)",
                        icon=":material/check_circle:",
                    )
                    if result["skipped"]:
                        st.warning(
                            f"Skipped: {', '.join(result['skipped'])}",
                            icon=":material/warning:",
                        )
                except Exception as e:
                    st.error(
                        f"Ingest failed: `{type(e).__name__}: {e}`",
                        icon=":material/error:",
                    )
        with btn_b:
            if st.button(
                "Rebuild from ./policies/",
                icon=":material/refresh:",
                type="secondary",
                width="stretch",
            ):
                try:
                    with st.spinner("Rebuilding vector store…"):
                        result = rebuild_from_policies_dir()
                    invalidate_caches()
                    st.toast(
                        f"Rebuilt: {result['chunks']:,} chunks from {result['files']} docs",
                        icon=":material/check_circle:",
                    )
                except Exception as e:
                    st.error(
                        f"Rebuild failed: `{type(e).__name__}: {e}`",
                        icon=":material/error:",
                    )

    with files_col:
        st.subheader("In `./policies/`", anchor=False)
        if not files:
            st.empty()
        else:
            df_files = pd.DataFrame(files).rename(
                columns={"name": "file", "size_kb": "size (KB)"}
            )
            st.dataframe(
                df_files,
                hide_index=True,
                width="stretch",
                column_config={
                    "file": st.column_config.TextColumn(width="large"),
                    "size (KB)": st.column_config.NumberColumn(format="%.1f", width="small"),
                },
            )


# ------------------------------------------------------------------------
# Database tab
# ------------------------------------------------------------------------

with tab_db:
    for t in TABLES:
        n = cached_row_count(t)
        header_label = f"**{t}** — " + (
            f"{n:,} rows" if isinstance(n, int) else ":red-badge[unreachable]"
        )
        with st.expander(header_label, expanded=(t == "authstattab"), icon=":material/table_chart:"):
            cols = cached_columns(t)
            if not cols:
                st.error("Could not read columns.", icon=":material/error:")
                continue

            # Column chips via badges
            badges = []
            for c in cols:
                badges.append(f":blue-badge[{c['name']}]&nbsp;`{c['type']}`")
            st.markdown(" &nbsp;·&nbsp; ".join(badges))

            headers, data = cached_sample(t)
            if not data:
                continue

            df = pd.DataFrame(data, columns=headers)
            st.dataframe(df, hide_index=True, width="stretch", height=220)
