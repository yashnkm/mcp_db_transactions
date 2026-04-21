from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from agent.models import build_classifier_model
from agent.prompts import INTENT_SYSTEM
from agent.state import AgentState, Intent


def understand_query(state: AgentState) -> dict:
    query = state["query"]
    policy_snippets = "\n\n---\n\n".join(
        d.page_content for d in state.get("policy_context", [])
    ) or "(no policy snippets retrieved)"

    user_block = (
        f"USER QUESTION:\n{query}\n\n"
        f"POLICY SNIPPETS:\n{policy_snippets}"
    )

    model = build_classifier_model().with_structured_output(Intent)
    intent: Intent = model.invoke(
        [SystemMessage(content=INTENT_SYSTEM), HumanMessage(content=user_block)]
    )
    return {"intent": intent}
