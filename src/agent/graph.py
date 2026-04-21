from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agent.config import settings
from agent.nodes.compose import compose_answer
from agent.nodes.execute import execute_db
from agent.nodes.retrieve import retrieve_policy
from agent.nodes.route import clarify_node, route_from_intent
from agent.nodes.understand import understand_query
from agent.state import AgentState


def _build_checkpointer():
    if settings.checkpointer == "postgres":
        if not settings.checkpointer_postgres_url:
            raise RuntimeError(
                "CHECKPOINTER=postgres but CHECKPOINTER_POSTGRES_URL is empty."
            )
        from langgraph.checkpoint.postgres import PostgresSaver

        saver = PostgresSaver.from_conn_string(settings.checkpointer_postgres_url)
        return saver
    return InMemorySaver()


def build_graph():
    builder = (
        StateGraph(AgentState)
        .add_node("retrieve_policy", retrieve_policy)
        .add_node("understand_query", understand_query)
        .add_node("execute_db", execute_db)
        .add_node("clarify", clarify_node)
        .add_node("compose_answer", compose_answer)
        .add_edge(START, "retrieve_policy")
        .add_edge("retrieve_policy", "understand_query")
        .add_conditional_edges(
            "understand_query",
            route_from_intent,
            ["execute_db", "clarify", "compose_answer"],
        )
        .add_edge("execute_db", "compose_answer")
        .add_edge("clarify", END)
        .add_edge("compose_answer", END)
    )
    return builder.compile(checkpointer=_build_checkpointer())
