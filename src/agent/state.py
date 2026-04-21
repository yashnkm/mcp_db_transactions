from __future__ import annotations

import operator
from typing import Annotated, Any, Literal

from langchain_core.documents import Document
from langchain_core.messages import AnyMessage
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


TargetTable = Literal[
    "authstattab",
    "tranlogtab",
    "int_detail_tab",
    "int_control_tab",
    "clarify",
    "unknown",
]


class Intent(BaseModel):
    """Structured output from the understand_query node."""

    action: Literal["lookup", "aggregate", "compare", "explain"] = "lookup"
    target_table: TargetTable = "unknown"
    entities: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Extracted filter values keyed by canonical column names, e.g. "
            "{'acctnum': '4111...', 'txndate': '2026-04-20', 'recap_id': 'R123'}."
        ),
    )
    policy_constraints: list[str] = Field(
        default_factory=list,
        description="Constraints pulled from retrieved policy documents that must shape the query.",
    )
    needs_clarification: bool = False
    clarification_question: str | None = None


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], operator.add]
    query: str
    policy_context: list[Document]
    intent: Intent
    db_result: list[dict[str, Any]]
    db_tool_used: str
    answer: str
    error: str | None
