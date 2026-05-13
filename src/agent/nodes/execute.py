"""Executor node — in-process LangChain tools, no MCP subprocess.

The DB functions in `agent.tools.db_tools` are wrapped as LangChain tools
and handed to `create_agent()` directly. Everything runs in the same Python
process as Streamlit, so there is no subprocess spawn, no asyncio bridge,
and no ~15 s Python-startup cost per tool call.

`mcp_server.py` still exists at the repo root for Claude Desktop / Claude
Code integration; it imports the same plain functions. The two surfaces
share one implementation.
"""
from __future__ import annotations

import json

from langchain.agents import create_agent
from langchain_core.tools import StructuredTool

from agent.logger import get_logger, timed
from agent.models import build_executor_model
from agent.prompts import EXECUTOR_SYSTEM
from agent.state import AgentState
from agent.text_utils import message_to_text
from agent.tools.db_tools import ALL_DB_FUNCTIONS


log = get_logger("execute")


_TOOLS = None
_EXECUTOR = None


def _build_tools() -> list:
    """Wrap each plain Python function as a LangChain StructuredTool.

    `from_function` introspects type hints + docstring to build the JSON
    schema the LLM uses to call it. Same surface as @tool, but lets the
    functions stay decorator-free so `mcp_server.py` can also register
    them with FastMCP.
    """
    return [StructuredTool.from_function(fn) for fn in ALL_DB_FUNCTIONS]


def _tools():
    global _TOOLS
    if _TOOLS is None:
        _TOOLS = _build_tools()
        log.info(
            "in-process tools loaded (%d): %s",
            len(_TOOLS), [t.name for t in _TOOLS],
        )
    return _TOOLS


def _executor():
    global _EXECUTOR
    if _EXECUTOR is None:
        log.info("building executor agent (in-process tools, no MCP)")
        _EXECUTOR = create_agent(
            model=build_executor_model(),
            tools=_tools(),
            system_prompt=EXECUTOR_SYSTEM,
        )
    return _EXECUTOR


def execute_db(state: AgentState) -> dict:
    intent = state["intent"]
    log.info(
        "node=execute_db target=%s action=%s entities=%s",
        intent.target_table, intent.action, intent.entities,
    )
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

    with timed(log, "inner create_agent loop"):
        result = _executor().invoke(
            {"messages": [{"role": "user", "content": brief}]},
            config={"recursion_limit": 40},
        )
    messages = result.get("messages", [])

    tool_used = ""
    db_rows: list[dict] = []
    tool_calls = 0
    for msg in messages:
        kind = getattr(msg, "type", None)
        if kind == "ai":
            tc = getattr(msg, "tool_calls", None) or []
            for call in tc:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
                args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
                log.info("  → tool_call: %s args=%s", name, args)
        elif kind == "tool":
            tool_calls += 1
            tool_used = getattr(msg, "name", "") or tool_used
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            preview = content[:200] + ("…" if len(content) > 200 else "")
            log.info("  ← tool_result[%s] %s", msg.name, preview)
            db_rows.append({"tool": msg.name, "content": msg.content})

    final_text = message_to_text(messages[-1].content) if messages else ""
    log.info(
        "execute_db done: tool_calls=%d last_tool=%s answer_chars=%d",
        tool_calls, tool_used or "-", len(final_text),
    )
    return {
        "db_result": db_rows,
        "db_tool_used": tool_used,
        "answer": final_text,
    }
