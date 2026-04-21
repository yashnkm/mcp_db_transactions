"""Rebuild the policy vector store from POLICIES_DIR.

Usage:
    python scripts/ingest_policies.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.ingest import ingest  # noqa: E402


if __name__ == "__main__":
    ingest()
