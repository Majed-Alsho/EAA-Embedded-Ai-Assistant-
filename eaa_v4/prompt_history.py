"""
prompt_history.py — Global Project-Scoped Command History (Phase 7)

Persistent command-line history stored per-project in JSONL format.
Each entry records the command text, Unix timestamp, and optional
session ID for cross-session correlation.

Storage layout:
    ~/.eaa/projects/<project_hash>_history.jsonl

Key features:
    - Project-scoped isolation (different hash per project root)
    - Case-insensitive substring search via search()
    - Recent command retrieval with configurable limit
    - Graceful handling of corrupted lines (JSONDecodeError)
    - JSONL append-only for safe concurrent access

Reference: Blueprint Section 4.4 — Prompt History
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["PromptHistory"]

# Default limits
DEFAULT_SEARCH_LIMIT = 20
DEFAULT_RECENT_LIMIT = 5


class PromptHistory:
    """
    Per-project command history backed by JSONL.

    Each command is stored as a JSON line with the following schema::

        {"ts": 1700000000.0, "cmd": "fix the auth bug", "session": "abc123"}

    Usage::

        ph = PromptHistory("/home/user/my-project")
        ph.append("fix the auth bug", session_id="sess-001")
        results = ph.search("auth")
        recent = ph.get_recent(limit=10)

    Args:
        project_root: Absolute path to the project directory.  Used to
            derive the per-project history file via MD5 hash (first 12
            hex chars).
    """

    def __init__(self, project_root: str) -> None:
        self.project_root = project_root
        self.history_path = self._get_history_path()
        os.makedirs(os.path.dirname(self.history_path), exist_ok=True)
        logger.debug(
            "[PromptHistory] Initialized: path=%s", self.history_path
        )

    # ── Path helpers ────────────────────────────────────────────────────

    def _get_history_path(self) -> str:
        """Derive ~/.eaa/projects/<project_hash>_history.jsonl."""
        h = hashlib.md5(self.project_root.encode()).hexdigest()[:12]
        return os.path.expanduser(
            f"~/.eaa/projects/{h}_history.jsonl"
        )

    # ── Write ───────────────────────────────────────────────────────────

    def append(self, command: str, session_id: str = "") -> None:
        """
        Append a command to the history file.

        Args:
            command: The user's prompt/command text
            session_id: Optional session identifier for cross-session
                correlation
        """
        entry: Dict[str, Any] = {
            "ts": time.time(),
            "cmd": command,
            "session": session_id,
        }
        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.debug(
            "[PromptHistory] Appended: %s", command[:50]
        )

    # ── Read ────────────────────────────────────────────────────────────

    def _read_all(self) -> List[Dict[str, Any]]:
        """
        Read all entries from the history file.

        Corrupted lines (JSONDecodeError) are silently skipped.
        """
        entries: List[Dict[str, Any]] = []
        if not os.path.exists(self.history_path):
            return entries
        with open(self.history_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(
                        "[PromptHistory] Skipping corrupted line in %s",
                        self.history_path,
                    )
                    continue
        return entries

    def search(
        self, query: str = "", limit: int = DEFAULT_SEARCH_LIMIT
    ) -> List[Dict[str, Any]]:
        """
        Search history entries with case-insensitive substring matching.

        Args:
            query: Substring to search for in command text.  Empty string
                matches all entries.
            limit: Maximum number of results to return (most recent first)

        Returns:
            List of entry dicts, ordered by timestamp (newest last)
        """
        entries = self._read_all()
        if query:
            entries = [
                e for e in entries
                if query.lower() in e["cmd"].lower()
            ]
        return entries[-limit:]

    def get_recent(
        self, limit: int = DEFAULT_RECENT_LIMIT
    ) -> List[Dict[str, Any]]:
        """
        Get the most recent history entries.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of entry dicts, ordered oldest-to-newest
        """
        return self.search(limit=limit)

    def get_entry_count(self) -> int:
        """Return the total number of entries in the history."""
        return len(self._read_all())

    def clear(self) -> None:
        """Delete the history file."""
        if os.path.exists(self.history_path):
            os.remove(self.history_path)
            logger.info("[PromptHistory] Cleared: %s", self.history_path)
