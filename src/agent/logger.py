"""Central logging setup so every component emits to the same stream.

Logs go to stderr (stdout is reserved for MCP's stdio JSON-RPC). Under systemd,
they land in journalctl; during local `streamlit run` they print to the terminal.

Format:
    HH:MM:SS.mmm | LEVEL | component | message
"""
from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import contextmanager

_CONFIGURED = False


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("agent")
    root.setLevel(os.environ.get("AGENT_LOG_LEVEL", "INFO").upper())
    root.propagate = False
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s.%(msecs)03d | %(levelname)-5s | %(name)-22s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger scoped under `agent.*`."""
    _configure()
    if not name.startswith("agent"):
        name = f"agent.{name}"
    return logging.getLogger(name)


@contextmanager
def timed(log: logging.Logger, label: str, level: int = logging.INFO):
    """Context manager that logs elapsed ms after the block."""
    t0 = time.perf_counter()
    log.log(level, "▶ %s", label)
    try:
        yield
    finally:
        ms = (time.perf_counter() - t0) * 1000
        log.log(level, "◀ %s — %.1fms", label, ms)
