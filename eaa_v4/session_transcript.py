"""
session_transcript.py — JSONL Persistence for Conversation Turns (Phase 7)

Persistent per-project transcript stored as JSONL (one JSON object per line).
Enables /resume functionality that reconstructs conversation context across
sessions with a strict 6K-token hard cap (Amendment 4).

Storage layout:
    ~/.eaa/projects/<project_hash>.jsonl

Key features:
    - WAL (Write-Ahead Logging) pattern for crash resilience
    - Monotonic sequence numbers for ordering
    - Token-aware resume prioritizes user/assistant over tool results
    - Graceful handling of corrupted JSONL lines (Amendment 5)
    - Filesystem sync via flush()

Reference: Blueprint Section 4.1 — Session Transcript & Resume
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["SessionTranscript"]

# Default token cap for /resume — Amendment 4
DEFAULT_RESUME_TOKEN_CAP = 6000


class SessionTranscript:
    """
    JSONL-backed conversation transcript with token-aware resume.

    Every conversation turn (user message, assistant reply, tool call,
    tool result) is appended as a single JSON line. On /resume the file
    is read back and filtered to fit within the token budget, with
    user/assistant turns prioritized over tool results.

    Usage::

        st = SessionTranscript("/home/user/my-project")
        st.append_turn("user", "Fix the auth bug", tool_calls=[])
        st.append_turn("assistant", "Looking at auth.py...", tool_results=[])
        turns = st.resume(max_tokens=6000)
        st.flush()

    Args:
        project_root: Absolute path to the project directory.  Used to
            derive the per-project JSONL file via MD5 hash (first 12 hex).
    """

    def __init__(self, project_root: str) -> None:
        self.project_root = project_root
        self.transcript_path = self._get_transcript_path()
        os.makedirs(os.path.dirname(self.transcript_path), exist_ok=True)
        self._seq = 0
        logger.debug(
            "[SessionTranscript] Initialized: path=%s", self.transcript_path
        )

    # ── Path helpers ────────────────────────────────────────────────────

    def _get_transcript_path(self) -> str:
        """Derive ~/.eaa/projects/<project_hash>.jsonl from project root."""
        h = hashlib.md5(self.project_root.encode()).hexdigest()[:12]
        return os.path.expanduser(f"~/.eaa/projects/{h}.jsonl")

    # ── Write operations ────────────────────────────────────────────────

    def _next_seq(self) -> int:
        """Return the next monotonic sequence number."""
        self._seq += 1
        return self._seq

    def append_turn(
        self,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_results: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """
        Append a conversation turn to the JSONL file (WAL pattern).

        Each turn is written as a single JSON line with a monotonic
        sequence number and Unix timestamp.

        Args:
            role: "user", "assistant", "system", or "tool"
            content: The text content of the turn
            tool_calls: Optional list of tool call dicts
            tool_results: Optional list of tool result dicts

        Returns:
            The sequence number assigned to this turn
        """
        seq = self._next_seq()
        turn: Dict[str, Any] = {
            "seq": seq,
            "role": role,
            "content": content,
            "timestamp": time.time(),
            "tool_calls": tool_calls or [],
            "tool_results": tool_results or [],
        }
        with open(self.transcript_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")
        logger.debug(
            "[SessionTranscript] Appended turn: seq=%d role=%s len=%d",
            seq, role, len(content),
        )
        return seq

    # ── Read / resume ───────────────────────────────────────────────────

    def _read_all_turns(self) -> List[Dict[str, Any]]:
        """
        Read all turns from the JSONL file.

        Corrupted lines are silently skipped (Amendment 5: JSONDecodeError
        intercept) rather than aborting the entire read.
        """
        turns: List[Dict[str, Any]] = []
        if not os.path.exists(self.transcript_path):
            return turns
        with open(self.transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    turns.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(
                        "[SessionTranscript] Skipping corrupted line in %s",
                        self.transcript_path,
                    )
                    continue  # Amendment 5: graceful corruption recovery
        return turns

    def _estimate_turn_tokens(self, turn: Dict[str, Any]) -> int:
        """
        Estimate token count for a single turn (4 chars ≈ 1 token).

        Uses the same heuristic as Phase 3's estimate_tokens() for
        consistency.  Returns at least 1 for any non-empty turn.
        """
        content = turn.get("content", "")
        return max(1, len(content) // 4)

    def resume(
        self,
        max_tokens: int = DEFAULT_RESUME_TOKEN_CAP,
        max_age_seconds: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Token-aware resume with 6K hard cap (Amendment 4).

        Reads the full transcript and selects turns that fit within
        *max_tokens*, prioritizing user and assistant turns over tool
        results.  Optionally filters by age.

        Algorithm:
            1. Read all turns chronologically
            2. If max_age_seconds set, mark stale tool results for dropping
            3. Walk turns in reverse (newest-first), greedily fitting
               user/assistant turns first
            4. Reverse the result so oldest-first ordering is preserved

        Args:
            max_tokens: Hard cap on total estimated tokens (default 6000)
            max_age_seconds: If set, tool results older than this are
                dropped unless they belong to user/assistant turns

        Returns:
            List of turn dicts ordered oldest-to-newest
        """
        turns = self._read_all_turns()

        # Age filter — drop stale tool results (keep user/assistant always)
        if max_age_seconds is not None:
            now = time.time()
            filtered: List[Dict[str, Any]] = []
            for t in turns:
                if t["role"] in ("user", "assistant"):
                    filtered.append(t)
                elif now - t.get("timestamp", now) < max_age_seconds:
                    filtered.append(t)
                # else: stale tool/system turn — dropped
            turns = filtered

        # Token-budget greedy selection (newest-first, then reverse)
        budget_remaining = max_tokens
        result: List[Dict[str, Any]] = []
        for turn in reversed(turns):
            est = self._estimate_turn_tokens(turn)
            if est > budget_remaining:
                continue
            result.append(turn)
            budget_remaining -= est

        result.reverse()  # oldest first
        logger.info(
            "[SessionTranscript] Resumed %d/%d turns (%d tokens budget, %d remaining)",
            len(result), len(turns), max_tokens, budget_remaining,
        )
        return result

    # ── Maintenance ─────────────────────────────────────────────────────

    def flush(self) -> None:
        """
        Force filesystem sync for the transcript file.

        Calls ``os.sync()`` when available (POSIX) to flush the
        kernel's write-back cache to durable storage.
        """
        if os.path.exists(self.transcript_path):
            if hasattr(os, "sync"):
                os.sync()
            logger.debug("[SessionTranscript] Flushed: %s", self.transcript_path)

    def get_turn_count(self) -> int:
        """Return the total number of turns in the transcript."""
        return len(self._read_all_turns())

    def clear(self) -> None:
        """Delete the transcript file."""
        if os.path.exists(self.transcript_path):
            os.remove(self.transcript_path)
            logger.info("[SessionTranscript] Cleared: %s", self.transcript_path)
