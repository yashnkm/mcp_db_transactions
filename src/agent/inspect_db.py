"""Helpers for the UI's DB inspector tab: column metadata + sample rows."""
from __future__ import annotations

from typing import Any

from sqlalchemy import inspect

from agent.config import settings
from agent.db import fetch_all, get_engine, qualified


TABLES = ["authstattab", "tranlogtab", "int_detail_tab", "int_control_tab"]


def list_columns(table: str) -> list[dict[str, Any]]:
    insp = inspect(get_engine())
    cols = insp.get_columns(table, schema=settings.db_schema or None)
    return [
        {
            "name": c["name"],
            "type": str(c["type"]),
            "nullable": bool(c.get("nullable", True)),
        }
        for c in cols
    ]


def sample_rows(table: str, limit: int = 5) -> tuple[list[str], list[list[Any]]]:
    rows = fetch_all(f"SELECT * FROM {qualified(table)} LIMIT :n", {"n": limit})
    if not rows:
        # Still want the header names even if the table is empty
        cols = [c["name"] for c in list_columns(table)]
        return cols, []
    headers = list(rows[0].keys())
    data = [[_to_display(r.get(h)) for h in headers] for r in rows]
    return headers, data


def row_count(table: str) -> int:
    rows = fetch_all(f"SELECT COUNT(*) AS n FROM {qualified(table)}")
    return int(rows[0]["n"]) if rows else 0


def _to_display(v: Any) -> Any:
    if v is None:
        return ""
    # Dates / times / decimals -> strings for Gradio dataframe
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v
