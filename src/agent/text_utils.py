"""Helpers for normalizing LangChain/Gemini/Anthropic message content to plain text."""
from __future__ import annotations

from typing import Any


def message_to_text(content: Any) -> str:
    """Flatten AIMessage.content (str | list[dict|str]) to a single plain string.

    Gemini and Anthropic return `content` as a list of blocks like
    `[{"type": "text", "text": "..."}]`. Calling str() on that leaks the
    repr into the UI. This walks the blocks and joins the text pieces.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if "text" in block and isinstance(block["text"], str):
                    parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    continue  # skip tool-use payloads in final answer
            else:
                text_attr = getattr(block, "text", None)
                if isinstance(text_attr, str):
                    parts.append(text_attr)
        return "\n".join(p for p in parts if p).strip()
    return str(content)
