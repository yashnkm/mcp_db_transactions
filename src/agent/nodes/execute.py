"""Executor node — talks to the DB **via MCP**, not direct tool calls.

Launches `mcp_server.py` as a stdio subprocess, loads its tools through
`langchain-mcp-adapters`, and hands them to `create_agent()`. Nothing in this
module touches Postgres directly — everything goes through MCP.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

from agent.logger import get_logger, timed
from agent.models import build_executor_model
from agent.prompts import EXECUTOR_SYSTEM
from agent.state import AgentState
from agent.text_utils import message_to_text

log = get_logger("execute")


_REPO_ROOT = Path(__file__).resolve().parents[3]
_MCP_SERVER = str(_REPO_ROOT / "mcp_server.py")


_MCP_CLIENT: MultiServerMCPClient | None = None
_MCP_TOOLS = None
_EXECUTOR = None


def _run_async(coro):
    """Run an awaitable from sync code safely.

    Streamlit reruns don't carry a running loop into the script thread, so
    asyncio.run works. Fall back to a fresh loop if one is already attached
    (e.g. running under pytest-asyncio).
    """
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _mcp_tools():
    """Load the MCP tools once per process."""
    global _MCP_CLIENT, _MCP_TOOLS
    if _MCP_TOOLS is not None:
        return _MCP_TOOLS
    log.info("spawning MCP server subprocess: %s %s", sys.executable, _MCP_SERVER)
    _MCP_CLIENT = MultiServerMCPClient(
        {
            "payments_db": {
                "command": sys.executable,
                "args": [_MCP_SERVER],
                "transport": "stdio",
            }
        }
    )
    with timed(log, "MCP client.get_tools()"):
        _MCP_TOOLS = _run_async(_MCP_CLIENT.get_tools())
    log.info(
        "MCP tools loaded (%d): %s",
        len(_MCP_TOOLS),
        [t.name for t in _MCP_TOOLS],
    )
    return _MCP_TOOLS


def _executor():
    global _EXECUTOR
    if _EXECUTOR is None:
        log.info("building executor agent (create_agent) with MCP tools")
        _EXECUTOR = create_agent(
            model=build_executor_model(),
            tools=_mcp_tools(),
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
        f"Call the appropriate MCP tool(s) and then summarize what you found. "
        f"If entities are missing, say so instead of guessing."
    )

    with timed(log, "inner create_agent loop (via ainvoke)"):
        result = _run_async(
            _executor().ainvoke(
                {"messages": [{"role": "user", "content": brief}]},
                config={"recursion_limit": 40},
            )
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
