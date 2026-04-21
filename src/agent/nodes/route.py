from __future__ import annotations

from typing import Literal

from agent.logger import get_logger
from agent.state import AgentState

log = get_logger("route")

RouteTarget = Literal["execute_db", "clarify", "compose_answer"]


def route_from_intent(state: AgentState) -> RouteTarget:
    intent = state.get("intent")
    if intent is None:
        log.warning("node=route no intent -> compose_answer")
        return "compose_answer"
    if intent.needs_clarification or intent.target_table == "clarify":
        log.info("node=route decision=clarify")
        return "clarify"
    if intent.target_table == "unknown":
        log.info("node=route decision=compose_answer (unknown target)")
        return "compose_answer"
    log.info("node=route decision=execute_db target=%s", intent.target_table)
    return "execute_db"


def clarify_node(state: AgentState) -> dict:
    intent = state.get("intent")
    question = (
        intent.clarification_question
        if intent and intent.clarification_question
        else "Could you share the account number, transaction date, and amount?"
    )
    log.info("node=clarify question=%r", question)
    return {"answer": question}
