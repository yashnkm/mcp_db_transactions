from __future__ import annotations

import json

from langchain.agents import create_agent

from agent.models import build_chat_model
from agent.prompts import EXECUTOR_SYSTEM
from agent.state import AgentState
from agent.text_utils import message_to_text
from agent.tools import ALL_DB_TOOLS


_EXECUTOR = None


def _executor():
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = create_agent(
            model=build_chat_model(),
            tools=ALL_DB_TOOLS,
            system_prompt=EXECUTOR_SYSTEM,
        )
    return _EXECUTOR


def execute_db(state: AgentState) -> dict:
    intent = state["intent"]
    policy_snippets = "\n".join(f"- {c}" for c in intent.policy_constraints) or "(none)"
    brief = (
        f"User question: {state['query']}\n\n"
        f"Classified intent:\n"
        f"  action: {intent.action}\n"
        f"  target_table: {intent.target_table}\n"
        f"  entities: {json.dumps(intent.entities, default=str)}\n\n"
        f"Policy constraints:\n{policy_snippets}\n\n"
        f"Call the appropriate tool(s) and then summarize what you found. "
        f"If entities are missing, say so instead of guessing."
    )

    result = _executor().invoke(
        {"messages": [{"role": "user", "content": brief}]},
        config={"recursion_limit": 40},
    )
    messages = result.get("messages", [])

    tool_used = ""
    db_rows: list[dict] = []
    for msg in messages:
        if getattr(msg, "type", None) == "tool":
            tool_used = getattr(msg, "name", "") or tool_used
            db_rows.append({"tool": msg.name, "content": msg.content})

    final_text = message_to_text(messages[-1].content) if messages else ""
    return {
        "db_result": db_rows,
        "db_tool_used": tool_used,
        "answer": final_text,
    }
