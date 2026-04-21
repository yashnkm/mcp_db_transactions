"""Transaction Analysis — slick POC UI.

Tabs:
    1. Chat       - talk to the agent; trace panel shows RAG sources + intent + tool
    2. Policies   - drag-drop ingest, vector-store stats, file list
    3. Database   - schema explorer + live sample rows per table

Usage:
    python scripts/ui.py
    python scripts/ui.py --port 7860 --share
"""
from __future__ import annotations

import argparse
import html
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import gradio as gr  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

from agent.config import settings  # noqa: E402
from agent.graph import build_graph  # noqa: E402
from agent.ingest import (  # noqa: E402
    add_files,
    list_policy_files,
    rebuild_from_policies_dir,
    vectorstore_stats,
)
from agent.inspect_db import TABLES, list_columns, row_count, sample_rows  # noqa: E402


GRAPH = build_graph()
APP_TITLE = "Transaction Analysis"
TAGLINE = "Policy-aware RAG over the payment-transaction database."

EXAMPLE_QUERIES = [
    "Is account 4111%3344 on 2026-04-10 PB-secured?",
    "Show me the details of recap R00010",
    "How many declines happened last week by MCC?",
    "Explain what auth_type_code = 2 means per our policies",
]


# ---------- helpers ------------------------------------------------------------


def _new_thread() -> str:
    return f"ui-{uuid.uuid4().hex[:8]}"


def _db_counts() -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for t in TABLES:
        try:
            out[t] = row_count(t)
        except Exception:
            out[t] = None
    return out


def _total_db_rows(counts: dict[str, int | None]) -> int | None:
    values = [v for v in counts.values() if isinstance(v, int)]
    return sum(values) if values else None


def _chip(label: str, value: str, tone: str = "primary") -> str:
    return (
        f"<span class='chip chip-{tone}'>"
        f"<span class='chip-label'>{html.escape(label)}</span>"
        f"<span class='chip-value'>{html.escape(value)}</span>"
        f"</span>"
    )


def _header_html() -> str:
    counts = _db_counts()
    total = _total_db_rows(counts)
    vstats = vectorstore_stats()
    chips = [
        _chip("LLM", f"{settings.llm_provider}:{settings.llm_model}"),
        _chip("Embeddings", f"{settings.embeddings_provider}:{settings.embeddings_model}"),
        _chip(
            "DB rows",
            f"{total:,}" if total is not None else "unreachable",
            "success" if total else "warn",
        ),
        _chip(
            "Policy chunks",
            f"{vstats['chunks']:,}" if vstats.get("ok") else "0",
            "success" if vstats.get("ok") and vstats["chunks"] else "warn",
        ),
    ]
    return (
        "<div class='hero'>"
        f"<h1>{html.escape(APP_TITLE)}</h1>"
        f"<p class='tagline'>{html.escape(TAGLINE)}</p>"
        f"<div class='chip-row'>{''.join(chips)}</div>"
        "</div>"
    )


def _stat_card(label: str, value: str, hint: str = "") -> str:
    return (
        "<div class='stat-card'>"
        f"<div class='stat-label'>{html.escape(label)}</div>"
        f"<div class='stat-value'>{html.escape(value)}</div>"
        + (f"<div class='stat-hint'>{html.escape(hint)}</div>" if hint else "")
        + "</div>"
    )


def _db_stats_html() -> str:
    counts = _db_counts()
    cards = []
    for t in TABLES:
        n = counts.get(t)
        cards.append(_stat_card(t, f"{n:,}" if isinstance(n, int) else "—", "rows"))
    return f"<div class='stat-grid'>{''.join(cards)}</div>"


def _policies_stats_html() -> str:
    files = list_policy_files()
    vstats = vectorstore_stats()
    chunks = f"{vstats['chunks']:,}" if vstats.get("ok") else "error"
    cards = [
        _stat_card("Source files", str(len(files)), "in ./policies/"),
        _stat_card("Vector chunks", chunks, "indexed in Chroma"),
        _stat_card(
            "Embedding model",
            settings.embeddings_model,
            settings.embeddings_provider,
        ),
    ]
    return f"<div class='stat-grid'>{''.join(cards)}</div>"


def _policies_files_html() -> str:
    files = list_policy_files()
    if not files:
        return "<div class='empty-state'>No files yet — upload some above.</div>"
    rows = "".join(
        f"<tr><td><code>{html.escape(f['name'])}</code></td>"
        f"<td class='num'>{f['size_kb']:.1f} KB</td></tr>"
        for f in files
    )
    return (
        "<table class='file-table'>"
        "<thead><tr><th>File</th><th class='num'>Size</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


# ---------- Chat ---------------------------------------------------------------


def _format_sources(docs) -> str:
    if not docs:
        return "<div class='empty-state small'>No policy snippets retrieved for this turn.</div>"
    cards = []
    for i, d in enumerate(docs, 1):
        src = d.metadata.get("source") or d.metadata.get("file_path") or "unknown"
        page = d.metadata.get("page")
        loc = Path(src).name + (f" · page {page + 1}" if isinstance(page, int) else "")
        snippet = d.page_content[:420] + ("…" if len(d.page_content) > 420 else "")
        cards.append(
            f"<div class='trace-card sources'>"
            f"<div class='trace-meta'><span class='trace-index'>{i}</span>"
            f"<span class='trace-loc'>{html.escape(loc)}</span></div>"
            f"<div class='trace-body'>{html.escape(snippet)}</div>"
            f"</div>"
        )
    return "".join(cards)


def _format_intent(intent) -> str:
    if intent is None:
        return "<div class='empty-state small'>No intent produced.</div>"
    rows = [
        ("action", intent.action),
        ("target_table", intent.target_table),
        ("entities", str(intent.entities) if intent.entities else "—"),
    ]
    kv = "".join(
        f"<div class='kv'><span class='k'>{html.escape(k)}</span>"
        f"<span class='v'>{html.escape(str(v))}</span></div>"
        for k, v in rows
    )
    if intent.policy_constraints:
        pol = "".join(
            f"<li>{html.escape(c)}</li>" for c in intent.policy_constraints
        )
        kv += (
            "<div class='kv'><span class='k'>policy_constraints</span></div>"
            f"<ul class='pc'>{pol}</ul>"
        )
    if intent.needs_clarification:
        kv += (
            "<div class='kv warn'><span class='k'>clarify</span>"
            f"<span class='v'>{html.escape(intent.clarification_question or '')}</span></div>"
        )
    return f"<div class='trace-card intent'>{kv}</div>"


def _format_tool(tool_used: str) -> str:
    if not tool_used:
        return "<div class='empty-state small'>No DB tool called.</div>"
    return (
        "<div class='trace-card tool'>"
        f"<code class='tool-name'>{html.escape(tool_used)}</code>"
        "</div>"
    )


def respond(message, history, thread_id):
    if not message or not message.strip():
        return history, thread_id, "", gr.update(), gr.update(), gr.update()

    tid = thread_id or _new_thread()
    config = {"configurable": {"thread_id": tid}}

    try:
        result = GRAPH.invoke(
            {"query": message, "messages": [HumanMessage(content=message)]},
            config=config,
        )
        answer = result.get("answer") or "(no answer)"
        sources_md = _format_sources(result.get("policy_context", []))
        intent_md = _format_intent(result.get("intent"))
        tool_md = _format_tool(result.get("db_tool_used") or "")
    except Exception as e:
        answer = f"Error: {type(e).__name__}: {e}"
        sources_md = _format_sources([])
        intent_md = _format_intent(None)
        tool_md = _format_tool("")

    history = (history or []) + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": answer},
    ]
    return history, tid, "", sources_md, intent_md, tool_md


def reset_thread():
    return (
        [],
        _new_thread(),
        "",
        _format_sources([]),
        _format_intent(None),
        _format_tool(""),
    )


def fill_example(example_text: str):
    return example_text


# ---------- Policies -----------------------------------------------------------


def ui_upload_and_ingest(files):
    if not files:
        return (
            _policies_stats_html(),
            _policies_files_html(),
            "<div class='log warn'>Select at least one .pdf / .md / .txt file first.</div>",
        )
    paths = [f if isinstance(f, str) else f.name for f in files]
    try:
        result = add_files(paths)
    except Exception as e:
        return (
            _policies_stats_html(),
            _policies_files_html(),
            f"<div class='log err'>Ingest failed: {html.escape(type(e).__name__)}: {html.escape(str(e))}</div>",
        )
    added = result["chunks_added"]
    copied = ", ".join(result["copied"]) or "—"
    skipped = result["skipped"]
    log = (
        f"<div class='log ok'><b>+{added:,}</b> chunks indexed from "
        f"{len(result['copied'])} file(s): <code>{html.escape(copied)}</code></div>"
    )
    if skipped:
        log += f"<div class='log warn'>Skipped: {html.escape(', '.join(skipped))}</div>"
    return _policies_stats_html(), _policies_files_html(), log


def ui_rebuild():
    try:
        result = rebuild_from_policies_dir()
    except Exception as e:
        return (
            _policies_stats_html(),
            _policies_files_html(),
            f"<div class='log err'>Rebuild failed: {html.escape(type(e).__name__)}: {html.escape(str(e))}</div>",
        )
    return (
        _policies_stats_html(),
        _policies_files_html(),
        f"<div class='log ok'>Rebuilt: <b>{result['chunks']:,}</b> chunks from "
        f"<b>{result['files']}</b> source documents.</div>",
    )


def ui_refresh_policies():
    return _policies_stats_html(), _policies_files_html()


# ---------- Database -----------------------------------------------------------


def _column_names(table: str) -> list[str]:
    try:
        return [c["name"] for c in list_columns(table)]
    except Exception:
        return ["(DB unreachable)"]


def _safe_fetch(table: str):
    try:
        cols = list_columns(table)
        _, data = sample_rows(table, limit=5)
        count = row_count(table)
        chips = "".join(
            f"<span class='col-chip'><code>{html.escape(c['name'])}</code>"
            f"<span class='col-type'>{html.escape(str(c['type']))}</span>"
            + ("" if c["nullable"] else "<span class='col-req'>NOT NULL</span>")
            + "</span>"
            for c in cols
        )
        header = (
            f"<div class='tbl-head'>"
            f"<span class='tbl-name'>{html.escape(table)}</span>"
            f"<span class='tbl-meta'>{count:,} row{'s' if count != 1 else ''} · {len(cols)} columns</span>"
            f"</div>"
        )
        col_html = f"<div class='col-chip-row'>{chips}</div>"
        return header, col_html, data
    except Exception as e:
        msg = (
            f"<div class='tbl-head err'><span class='tbl-name'>{html.escape(table)}</span>"
            f"<span class='tbl-meta'>error: {html.escape(type(e).__name__)}: {html.escape(str(e))}</span>"
            f"</div>"
        )
        return msg, "", []


def refresh_all_tables():
    outputs = [gr.update(value=_db_stats_html())]
    for t in TABLES:
        header_html, col_html, data = _safe_fetch(t)
        outputs.extend(
            [gr.update(value=header_html), gr.update(value=col_html), gr.update(value=data)]
        )
    return outputs


# ---------- CSS ----------------------------------------------------------------


CSS = """
:root {
  --ink: #0f172a;
  --muted: #64748b;
  --line: #e2e8f0;
  --bg-soft: #f8fafc;
  --brand: #6366f1;
  --brand-2: #4f46e5;
  --ok: #059669;
  --warn: #d97706;
  --err: #dc2626;
  --cyan: #0891b2;
  --emerald: #10b981;
}
.gradio-container { max-width: 1320px !important; margin: 0 auto; }
footer { display: none !important; }

/* ---- hero header ---- */
.hero {
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 45%, #4338ca 100%);
  color: #fff;
  padding: 28px 32px;
  border-radius: 18px;
  margin: 4px 0 18px;
  box-shadow: 0 18px 50px -20px rgba(67, 56, 202, 0.55);
}
.hero h1 { color: #fff; margin: 0; font-size: 30px; font-weight: 700; letter-spacing: -0.02em; }
.hero .tagline { margin: 6px 0 16px; opacity: 0.82; font-size: 14px; }
.chip-row { display: flex; gap: 10px; flex-wrap: wrap; }
.chip {
  display: inline-flex; align-items: center; gap: 8px;
  background: rgba(255,255,255,0.10);
  border: 1px solid rgba(255,255,255,0.16);
  padding: 6px 12px; border-radius: 999px;
  font-size: 12px; font-weight: 500;
  backdrop-filter: blur(8px);
}
.chip-label { text-transform: uppercase; letter-spacing: 0.08em; opacity: 0.7; font-size: 10px; }
.chip-value { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.chip-success .chip-value { color: #6ee7b7; }
.chip-warn .chip-value { color: #fcd34d; }

/* ---- stat cards ---- */
.stat-grid {
  display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  margin: 8px 0 16px;
}
.stat-card {
  background: #fff; border: 1px solid var(--line); border-radius: 14px;
  padding: 14px 16px; box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}
.stat-label {
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.09em;
  color: var(--muted); font-weight: 700;
}
.stat-value {
  font-size: 24px; font-weight: 700; color: var(--ink);
  margin-top: 4px; line-height: 1.1;
  font-feature-settings: "tnum";
}
.stat-hint { font-size: 11px; color: var(--muted); margin-top: 2px; }

/* ---- trace cards (chat right-rail) ---- */
.trace-card {
  background: var(--bg-soft);
  border: 1px solid var(--line);
  border-left: 3px solid var(--brand);
  border-radius: 10px;
  padding: 12px 14px;
  margin: 0 0 10px;
  font-size: 13px; color: var(--ink);
}
.trace-card.intent { border-left-color: var(--cyan); }
.trace-card.tool { border-left-color: var(--emerald); }
.trace-meta { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.trace-index {
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 6px;
  background: var(--brand); color: #fff; font-size: 11px; font-weight: 700;
}
.trace-loc { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px; color: var(--muted); }
.trace-body { font-size: 12.5px; line-height: 1.5; color: #334155; white-space: pre-wrap; }
.tool-name {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #ecfdf5; color: #065f46; padding: 3px 8px; border-radius: 6px; font-size: 12px;
}
.kv { display: flex; gap: 10px; padding: 3px 0; font-size: 12.5px; }
.kv .k { color: var(--muted); min-width: 110px; text-transform: uppercase; font-size: 10px;
  letter-spacing: 0.06em; font-weight: 700; padding-top: 2px; }
.kv .v { color: var(--ink); font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px; word-break: break-word; }
.kv.warn .v { color: var(--warn); }
.pc { margin: 2px 0 6px 120px; padding-left: 14px; font-size: 12px; color: #334155; }

/* ---- empty states ---- */
.empty-state {
  border: 1px dashed var(--line); border-radius: 10px;
  padding: 16px; text-align: center; color: var(--muted);
  font-size: 13px; background: var(--bg-soft);
}
.empty-state.small { padding: 10px; font-size: 12px; }

/* ---- DB columns ---- */
.tbl-head { display: flex; align-items: baseline; gap: 12px; padding: 4px 2px 8px; }
.tbl-name { font-weight: 700; color: var(--ink); font-size: 15px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.tbl-meta { color: var(--muted); font-size: 12px; }
.tbl-head.err .tbl-meta { color: var(--err); }
.col-chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.col-chip {
  display: inline-flex; align-items: center; gap: 6px;
  background: #fff; border: 1px solid var(--line);
  padding: 3px 8px; border-radius: 8px; font-size: 11.5px;
}
.col-chip code { color: var(--ink); font-size: 11.5px; }
.col-type { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; }
.col-req { color: var(--err); font-size: 9px; font-weight: 700; letter-spacing: 0.08em; }

/* ---- policies tab ---- */
.file-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.file-table th, .file-table td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); }
.file-table th { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; }
.file-table td.num, .file-table th.num { text-align: right; font-variant-numeric: tabular-nums; }
.log { padding: 10px 12px; border-radius: 8px; font-size: 13px; margin-top: 8px; }
.log.ok { background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }
.log.warn { background: #fffbeb; color: #92400e; border: 1px solid #fde68a; }
.log.err { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }

/* ---- chatbot tweaks ---- */
.gradio-container .message-wrap { border-radius: 14px !important; }

/* ---- example chip buttons ---- */
.example-row button {
  font-size: 12px !important;
  padding: 6px 12px !important;
  border-radius: 999px !important;
  font-weight: 500 !important;
}
"""


# ---------- Layout -------------------------------------------------------------


def build_ui() -> gr.Blocks:
    with gr.Blocks(title=APP_TITLE) as demo:
        gr.HTML(_header_html())

        with gr.Tabs():
            # ---- Chat -----------------------------------------------------
            with gr.Tab("Chat"):
                thread_state = gr.State(_new_thread())
                with gr.Row(equal_height=False):
                    with gr.Column(scale=2):
                        chatbot = gr.Chatbot(
                            height=560,
                            show_label=False,
                        )
                        with gr.Row():
                            msg = gr.Textbox(
                                placeholder="Ask about auth status, recaps, PB-secured checks, a specific acct/date…",
                                show_label=False,
                                scale=8,
                                autofocus=True,
                                container=False,
                            )
                            send = gr.Button("Send", variant="primary", scale=1)
                            reset = gr.Button("New thread", scale=1)

                        gr.Markdown("**Try one:**")
                        with gr.Row(elem_classes=["example-row"]):
                            ex_buttons = [
                                gr.Button(q, size="sm", variant="secondary")
                                for q in EXAMPLE_QUERIES
                            ]
                        for btn, q in zip(ex_buttons, EXAMPLE_QUERIES):
                            btn.click(lambda q=q: q, None, msg)

                    with gr.Column(scale=1):
                        gr.Markdown("### Pipeline trace")
                        gr.Markdown(
                            "_Updates with every turn — retrieval ➜ intent ➜ DB tool._",
                            elem_classes=["tagline-sub"],
                        )
                        with gr.Accordion("Retrieved policy snippets", open=True):
                            sources_html = gr.HTML(_format_sources([]))
                        with gr.Accordion("Parsed intent", open=False):
                            intent_html = gr.HTML(_format_intent(None))
                        with gr.Accordion("DB tool used", open=False):
                            tool_html = gr.HTML(_format_tool(""))

                submit_inputs = [msg, chatbot, thread_state]
                submit_outputs = [
                    chatbot,
                    thread_state,
                    msg,
                    sources_html,
                    intent_html,
                    tool_html,
                ]
                msg.submit(respond, submit_inputs, submit_outputs)
                send.click(respond, submit_inputs, submit_outputs)
                reset.click(
                    reset_thread,
                    None,
                    [
                        chatbot,
                        thread_state,
                        msg,
                        sources_html,
                        intent_html,
                        tool_html,
                    ],
                )

            # ---- Policies -------------------------------------------------
            with gr.Tab("Policies"):
                stats_html = gr.HTML(_policies_stats_html())
                with gr.Row():
                    with gr.Column(scale=2):
                        gr.Markdown("#### Ingest new policy documents")
                        uploader = gr.File(
                            file_count="multiple",
                            file_types=[".pdf", ".md", ".txt"],
                            label="Drag & drop or browse — .pdf / .md / .txt",
                        )
                        with gr.Row():
                            ingest_btn = gr.Button(
                                "Ingest uploaded files", variant="primary"
                            )
                            rebuild_btn = gr.Button(
                                "Rebuild store from ./policies/", variant="secondary"
                            )
                            refresh_pol = gr.Button("Refresh", size="sm")
                        ingest_log = gr.HTML(
                            "<div class='log ok'>Ready. Upload files, then click Ingest.</div>"
                        )
                    with gr.Column(scale=1):
                        gr.Markdown("#### Files in `./policies/`")
                        files_html = gr.HTML(_policies_files_html())

                ingest_btn.click(
                    ui_upload_and_ingest,
                    uploader,
                    [stats_html, files_html, ingest_log],
                )
                rebuild_btn.click(
                    ui_rebuild, None, [stats_html, files_html, ingest_log]
                )
                refresh_pol.click(ui_refresh_policies, None, [stats_html, files_html])

            # ---- Database -------------------------------------------------
            with gr.Tab("Database"):
                db_stats_html = gr.HTML(_db_stats_html())
                with gr.Row():
                    gr.Markdown(
                        "#### Tables &nbsp;·&nbsp; schema + 5 sample rows each",
                    )
                    refresh_db = gr.Button("Refresh", size="sm", variant="secondary")

                db_section_outputs = [db_stats_html]
                for t in TABLES:
                    with gr.Accordion(t, open=(t == "authstattab")):
                        header_html = gr.HTML(f"<div class='tbl-head'><span class='tbl-name'>{t}</span></div>")
                        cols_html = gr.HTML("")
                        col_names = _column_names(t)
                        df = gr.Dataframe(
                            headers=col_names,
                            column_count=(len(col_names), "fixed"),
                            value=[],
                            interactive=False,
                            wrap=True,
                        )
                        db_section_outputs.extend([header_html, cols_html, df])

                refresh_db.click(refresh_all_tables, None, db_section_outputs)
                demo.load(refresh_all_tables, None, db_section_outputs)

    return demo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true", help="Create a public Gradio link")
    args = parser.parse_args()

    build_ui().launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        theme=gr.themes.Soft(primary_hue="indigo", neutral_hue="slate"),
        css=CSS,
    )


if __name__ == "__main__":
    main()
