from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from agent.logger import get_logger, timed
from agent.models import build_classifier_model
from agent.prompts import INTENT_SYSTEM
from agent.state import AgentState, Intent

log = get_logger("understand")


def _recent_history(state: AgentState, max_turns: int = 6) -> str:
    """Render the last N messages (excluding the current query) as plain text."""
    msgs = state.get("messages", []) or []
    # The current turn's HumanMessage is already the last item; drop it.
    prior = msgs[:-1][-max_turns:]
    if not prior:
        return "(no prior turns)"
    lines = []
    for m in prior:
        role = "user" if getattr(m, "type", "") == "human" else "assistant"
        content = m.content if isinstance(m.content, str) else str(m.content)
        content = content.replace("\n", " ").strip()
        if len(content) > 300:
            content = content[:300] + "…"
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def understand_query(state: AgentState) -> dict:
    query = state["query"]
    policies = state.get("policy_context", [])
    history = _recent_history(state)
    log.info(
        "node=understand_query query=%r policy_chunks=%d history_turns=%d",
        query[:120],
        len(policies),
        0 if history.startswith("(no prior") else history.count("\n") + 1,
    )
    policy_snippets = "\n\n---\n\n".join(
        d.page_content for d in policies
    ) or "(no policy snippets retrieved)"

    user_block = (
        f"RECENT CONVERSATION (most recent last):\n{history}\n\n"
        f"CURRENT USER QUESTION:\n{query}\n\n"
        f"POLICY SNIPPETS:\n{policy_snippets}\n\n"
        f"Interpret the current question in light of the prior conversation. "
        f"If the user says things like 'how about X?' or 'same but for Y', "
        f"carry over the unchanged entities/filters from the previous turn."
    )

    model = build_classifier_model().with_structured_output(Intent)
    with timed(log, "classifier.invoke (structured Intent)"):
        intent: Intent = model.invoke(
            [SystemMessage(content=INTENT_SYSTEM), HumanMessage(content=user_block)]
        )
    log.info(
        "intent: action=%s target=%s entities=%s clarify=%s",
        intent.action,
        intent.target_table,
        intent.entities,
        intent.needs_clarification,
    )
    if intent.policy_constraints:
        for c in intent.policy_constraints:
            log.info("  policy_constraint: %s", c)
    return {"intent": intent}
