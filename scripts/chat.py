"""Interactive CLI for the policy-aware DB query agent.

Usage:
    python scripts/chat.py
    python scripts/chat.py --thread my-session
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from langchain_core.messages import HumanMessage  # noqa: E402

from agent.graph import build_graph  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--thread", default=None, help="thread_id for conversation memory")
    args = parser.parse_args()

    thread_id = args.thread or f"cli-{uuid.uuid4().hex[:8]}"
    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    print(f"Agent ready. thread_id={thread_id}. Ctrl-C to exit.\n")

    while True:
        try:
            query = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue

        result = graph.invoke(
            {"query": query, "messages": [HumanMessage(content=query)]},
            config=config,
        )
        answer = result.get("answer") or "(no answer)"
        print(f"\nbot > {answer}\n")


if __name__ == "__main__":
    main()
