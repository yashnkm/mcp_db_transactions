from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.models import build_chat_model
from agent.prompts import COMPOSER_SYSTEM
from agent.state import AgentState
from agent.text_utils import message_to_text


def compose_answer(state: AgentState) -> dict:
    query = state["query"]
    intent = state.get("intent")
    policy_snippets = "\n\n---\n\n".join(
        d.page_content for d in state.get("policy_context", [])
    ) or "(none retrieved)"
    db_result = state.get("db_result") or []
    exec_answer = state.get("answer") or ""

    user_block = (
        f"USER QUESTION:\n{query}\n\n"
        f"POLICY SNIPPETS:\n{policy_snippets}\n\n"
        f"INTENT:\n{intent.model_dump_json(indent=2) if intent else '(none)'}\n\n"
        f"DB TOOL RESULT:\n{json.dumps(db_result, default=str, indent=2)}\n\n"
        f"EXECUTOR SUMMARY:\n{exec_answer}"
    )

    model = build_chat_model()
    reply = model.invoke(
        [SystemMessage(content=COMPOSER_SYSTEM), HumanMessage(content=user_block)]
    )
    content = message_to_text(reply.content)
    return {
        "answer": content,
        "messages": [AIMessage(content=content)],
    }
