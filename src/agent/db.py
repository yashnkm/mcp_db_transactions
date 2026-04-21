from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Row

from agent.config import settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


def qualified(table: str) -> str:
    """Return `schema.table`, honoring the configured schema."""
    schema = settings.db_schema
    return f"{schema}.{table}" if schema else table


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [_row_to_dict(r) for r in result]


def _row_to_dict(row: Row) -> dict[str, Any]:
    return dict(row._mapping)
