from __future__ import annotations

from typing import Literal

from agent.state import AgentState

RouteTarget = Literal["execute_db", "clarify", "compose_answer"]


def route_from_intent(state: AgentState) -> RouteTarget:
    intent = state.get("intent")
    if intent is None:
        return "compose_answer"
    if intent.needs_clarification or intent.target_table == "clarify":
        return "clarify"
    if intent.target_table == "unknown":
        return "compose_answer"
    return "execute_db"


def clarify_node(state: AgentState) -> dict:
    intent = state.get("intent")
    question = (
        intent.clarification_question
        if intent and intent.clarification_question
        else "Could you share the account number, transaction date, and amount?"
    )
    return {"answer": question}
