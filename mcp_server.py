"""MCP server exposing the payment-transaction DB tools over stdio.

Run it directly to use from Claude Desktop / Code / any MCP client:

    python mcp_server.py

The LangGraph executor (`src/agent/nodes/execute.py`) launches this file as a
subprocess over stdio via `langchain-mcp-adapters`, so the Streamlit app talks
to Postgres through MCP — no direct tool calls inside the graph.
"""
from __future__ import annotations

# Silence transformers' lazy-module deprecation spam.
import warnings
warnings.filterwarnings("ignore", message="Accessing `__path__`.*")
warnings.filterwarnings("ignore", category=UserWarning, module="transformers.*")

import functools
import sys
import time
from pathlib import Path

# Make src/ importable when run as `python mcp_server.py` from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from agent.logger import get_logger  # noqa: E402
from agent.tools.db_tools import ALL_DB_FUNCTIONS  # noqa: E402

log = get_logger("mcp_server")

mcp = FastMCP("payments-db")


def _logged(fn):
    """Wrap a DB function so every MCP tool invocation is logged with timing."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        log.info("TOOL %s kwargs=%s", fn.__name__, kwargs)
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            log.exception("TOOL %s FAILED after %.1fms: %s", fn.__name__, ms, e)
            raise
        ms = (time.perf_counter() - t0) * 1000
        size = len(result) if isinstance(result, (list, tuple)) else 1
        log.info("TOOL %s ok in %.1fms (rows/items=%s)", fn.__name__, ms, size)
        return result

    return wrapper


for fn in ALL_DB_FUNCTIONS:
    mcp.tool()(_logged(fn))


if __name__ == "__main__":
    log.info("MCP server starting: tools=%s", [f.__name__ for f in ALL_DB_FUNCTIONS])
    mcp.run()
