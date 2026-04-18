"""
session_memory.py — Rolling Markdown Notes Compaction (Phase 7)

Zero-API-call compaction mechanism that maintains a running summary of
the current session state as Markdown notes.  Updated heuristically
(every 5K tokens or on error/file-edit detection) without calling an
LLM, keeping overhead near zero.

The notes are designed to be injected into the prompt via the Phase 4
PromptAssembler as a lightweight context summary.

Key features:
    - Automatic regeneration when token threshold (5K) is exceeded
    - Immediate regeneration on detected errors or file edits
    - Heuristic extraction of file paths, errors, and task descriptions
    - get_token_count() for budget-aware prompt injection
    - Clean Markdown rendering for direct prompt inclusion

Reference: Blueprint Section 4.2 — Session Memory Notes
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

__all__ = ["SessionMemory"]

# Threshold in accumulated tokens before triggering a regeneration
DEFAULT_UPDATE_THRESHOLD = 5000

# Number of recent messages to scan for heuristics
MAX_MESSAGES_TO_SCAN = 20

# Maximum extracted file paths to display
MAX_FILES_DISPLAY = 10

# Maximum error snippets to retain
MAX_ERROR_SNIPPETS = 3

# Keywords that trigger immediate regeneration
_IMMEDIATE_TRIGGER_KEYWORDS = [
    "syntaxerror",
    "traceback",
    "error:",
    "file written",
    "created file",
]

# Keywords indicating error content for extraction
_ERROR_KEYWORDS = ["error", "traceback", "exception"]


class SessionMemory:
    """
    Rolling Markdown notes that summarize session state without LLM calls.

    The notes track three sections:
        - **Current State**: Active file paths and most recent task
        - **Errors**: Recent error snippets (last 3)
        - **Workflow**: Cumulative message count

    Regeneration is triggered by:
        1. Accumulated token count exceeding the threshold (5K default)
        2. Detection of error keywords or file write indicators

    Usage::

        sm = SessionMemory()
        sm.update(messages, new_tokens=500)
        notes = sm.get_notes()  # Markdown string
        tokens = sm.get_token_count()

    Args:
        project_root: Project directory (reserved for future scoping)
        update_threshold: Tokens to accumulate before auto-regeneration
    """

    def __init__(
        self,
        project_root: str = "",
        update_threshold: int = DEFAULT_UPDATE_THRESHOLD,
    ) -> None:
        self.project_root = project_root
        self.current_state: str = ""
        self.errors: str = "No recent errors"
        self.workflow: str = ""
        self._token_counter: int = 0
        self._update_threshold: int = update_threshold
        self._total_messages_processed: int = 0
        logger.debug(
            "[SessionMemory] Initialized: threshold=%d", update_threshold
        )

    # ── Public API ──────────────────────────────────────────────────────

    def update(self, messages: List[Dict[str, Any]], new_tokens: int) -> None:
        """
        Check if notes regeneration is needed and regenerate if so.

        Triggers regeneration when:
            - Accumulated token count >= threshold
            - Any message contains error or file-edit keywords

        Args:
            messages: List of message dicts with "role" and "content" keys
            new_tokens: Tokens contributed by the latest batch of messages
        """
        self._token_counter += new_tokens
        self._total_messages_processed += len(messages)

        # Check threshold
        needs_update = self._token_counter >= self._update_threshold

        # Check for immediate triggers
        if not needs_update:
            for msg in messages:
                content = (
                    msg.get("content", "")
                    if isinstance(msg, dict)
                    else str(msg)
                )
                if any(
                    kw in content.lower()
                    for kw in _IMMEDIATE_TRIGGER_KEYWORDS
                ):
                    needs_update = True
                    break

        if needs_update:
            self._regenerate(messages)
            self._token_counter = 0
            logger.debug("[SessionMemory] Regenerated notes")

    def get_notes(self) -> str:
        """
        Render the current session notes as a Markdown string.

        Returns:
            Markdown-formatted notes with Current State, Errors, and
            Workflow sections
        """
        return (
            f"# Session Memory\n"
            f"## Current State\n{self.current_state}\n"
            f"## Errors\n{self.errors}\n"
            f"## Workflow\n{self.workflow}"
        )

    def get_token_count(self) -> int:
        """
        Estimate token count for the rendered notes (4 chars ≈ 1 token).

        Uses the same heuristic as Phase 3's estimate_tokens() for
        consistency with the rest of the system.

        Returns:
            Estimated token count (minimum 1)
        """
        return max(1, len(self.get_notes()) // 4)

    # ── Internal regeneration ───────────────────────────────────────────

    def _regenerate(self, messages: List[Dict[str, Any]]) -> None:
        """
        Regenerate notes by heuristic extraction (NO LLM call).

        Scans the last N messages for:
            - File paths (.py, .ts, .js, .json extensions)
            - Error snippets (containing error-related keywords)
            - Task descriptions (from user-role messages)

        Args:
            messages: List of message dicts to extract from
        """
        files: set = set()
        errors_found: List[str] = []
        tasks: List[str] = []

        for msg in messages[-MAX_MESSAGES_TO_SCAN:]:
            content = (
                msg.get("content", "")
                if isinstance(msg, dict)
                else str(msg)
            )

            # Extract file paths
            paths = re.findall(
                r"[\w./~-]+\.(?:py|ts|js|json)", content
            )
            files.update(paths[:5])

            # Extract errors
            if any(
                kw in content.lower() for kw in _ERROR_KEYWORDS
            ):
                errors_found.append(content[:200])

            # Extract tasks (from user messages)
            if isinstance(msg, dict) and msg.get("role") == "user":
                tasks.append(content[:200])

        # Build Current State
        file_list = ", ".join(list(files)[:MAX_FILES_DISPLAY])
        latest_task = tasks[-1] if tasks else "N/A"
        self.current_state = f"Files: {file_list}\nRecent task: {latest_task}"

        # Build Errors
        self.errors = (
            "\n".join(errors_found[-MAX_ERROR_SNIPPETS:])
            if errors_found
            else "No recent errors"
        )

        # Build Workflow
        self.workflow = (
            f"Steps tracked: {self._total_messages_processed} "
            f"messages processed"
        )
