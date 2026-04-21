from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.logger import get_logger, timed
from agent.models import build_chat_model
from agent.prompts import COMPOSER_SYSTEM
from agent.state import AgentState
from agent.text_utils import message_to_text

log = get_logger("compose")


def _recent_history(state: AgentState, max_turns: int = 6) -> str:
    msgs = state.get("messages", []) or []
    prior = msgs[:-1][-max_turns:]
    if not prior:
        return "(no prior turns)"
    lines = []
    for m in prior:
        role = "user" if getattr(m, "type", "") == "human" else "assistant"
        content = m.content if isinstance(m.content, str) else str(m.content)
        content = content.replace("\n", " ").strip()
        if len(content) > 300:
            content = content[:300] + "…"
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def compose_answer(state: AgentState) -> dict:
    query = state["query"]
    intent = state.get("intent")
    db_result = state.get("db_result") or []
    exec_answer = state.get("answer") or ""
    policy_ctx = state.get("policy_context", [])
    history = _recent_history(state)

    log.info(
        "node=compose_answer policy_chunks=%d db_tool_results=%d exec_answer_chars=%d",
        len(policy_ctx), len(db_result), len(exec_answer),
    )

    policy_snippets = "\n\n---\n\n".join(
        d.page_content for d in policy_ctx
    ) or "(none retrieved)"

    user_block = (
        f"RECENT CONVERSATION (most recent last):\n{history}\n\n"
        f"CURRENT USER QUESTION:\n{query}\n\n"
        f"POLICY SNIPPETS:\n{policy_snippets}\n\n"
        f"INTENT:\n{intent.model_dump_json(indent=2) if intent else '(none)'}\n\n"
        f"DB TOOL RESULT:\n{json.dumps(db_result, default=str, indent=2)}\n\n"
        f"EXECUTOR SUMMARY:\n{exec_answer}"
    )

    model = build_chat_model()
    with timed(log, "composer.invoke"):
        reply = model.invoke(
            [SystemMessage(content=COMPOSER_SYSTEM), HumanMessage(content=user_block)]
        )
    content = message_to_text(reply.content)
    log.info("final answer: %d chars — %r…", len(content), content[:160])
    return {
        "answer": content,
        "messages": [AIMessage(content=content)],
    }
