"""
memory_extractor.py — Background Heuristic Memory Extraction (Phase 7)

Extracts structured memory entries from the session transcript using
purely heuristic (regex-based) methods — no LLM calls required.

Features:
    - Daemon thread idle trigger (Amendment 2): polls every 30s, extracts
      after 300s of user inactivity
    - Sliding window 4K chunk extraction (Amendment 6): handles long
      transcripts by processing overlapping windows with rolling fact context
    - YAML frontmatter Markdown output to ~/.eaa/memory/
    - Extraction triggered on /exit or idle timeout

Memory entry types:
    - user_preferences  — coding style, naming conventions, stated preferences
    - project_rules     — architectural rules, requirements, patterns
    - reference_links   — URLs extracted from conversation
    - error_patterns    — recurring errors and their solutions

Reference: Blueprint Section 4.3 — Background Memory Extraction
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from session_transcript import SessionTranscript

logger = logging.getLogger(__name__)

__all__ = ["MemoryEntry", "MemoryExtractor"]

# ── Constants ────────────────────────────────────────────────────────────

MEMORY_DIR = "~/.eaa/memory"

# Daemon thread settings (Amendment 2)
DAEMON_POLL_INTERVAL = 30       # seconds between idle checks
DEFAULT_IDLE_THRESHOLD = 300    # seconds of inactivity before extraction

# Sliding window settings (Amendment 6)
WINDOW_TOKENS = 4000            # ~16K chars per window
OVERLAP_TOKENS = 1000           # ~4K chars overlap between windows
MAX_ROLLING_FACTS = 50          # rolling context cap

# Keyword lists for heuristic extraction
_PREFERENCE_KEYWORDS = [
    "prefer", "always use", "style guide", "naming convention",
]
_RULE_KEYWORDS = [
    "must", "required", "architecture", "pattern",
]
_ERROR_KEYWORDS = [
    "error:", "traceback", "syntaxerror", "exception",
]

# URL regex (simplified, matches http/https)
_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"{}|\\^`\[\]]+"
)


@dataclass
class MemoryEntry:
    """
    A single extracted memory item.

    Attributes:
        memory_type: One of "user_preferences", "project_rules",
            "reference_links", or "error_patterns"
        content: The extracted text content
        scope: Scope of the memory ("project" or "user")
        confidence: Confidence score 0.0–1.0
        timestamp: Unix timestamp of extraction
    """

    memory_type: str
    content: str
    scope: str = "project"
    confidence: float = 0.8
    timestamp: float = field(default_factory=time.time)


class MemoryExtractor:
    """
    Background heuristic memory extraction from session transcripts.

    Runs as a daemon thread that monitors user idle time and extracts
    structured memory entries when the user has been inactive for the
    configured threshold.  Also supports manual extraction via
    ``extract()`` or ``trigger_on_exit()``.

    For long transcripts (>4K tokens), uses a sliding window approach
    (Amendment 6) that processes overlapping windows with a rolling
    fact context to maintain coherence across chunks.

    Usage::

        transcript = SessionTranscript("/home/user/project")
        me = MemoryExtractor(transcript)
        entries = me.extract()
        me.stop_daemon()

    Args:
        transcript: The SessionTranscript to extract from
    """

    def __init__(self, transcript: SessionTranscript) -> None:
        self.transcript = transcript
        self._is_extracting: bool = False
        self._last_input_timestamp: float = time.time()
        self._daemon_thread: Optional[threading.Thread] = None
        self._daemon_running: bool = False
        self._start_daemon()
        logger.debug("[MemoryExtractor] Initialized")

    # ── Daemon thread (Amendment 2) ─────────────────────────────────────

    def _start_daemon(self) -> None:
        """
        Start daemon thread that polls for idle.

        Amendment 2: The daemon polls every DAEMON_POLL_INTERVAL seconds
        and triggers extraction after DEFAULT_IDLE_THRESHOLD seconds of
        inactivity.  Not started in interactive (TTY) mode.
        """
        if sys.stdout.isatty():
            logger.debug(
                "[MemoryExtractor] Skipping daemon in interactive mode"
            )
            return
        self._daemon_running = True
        self._daemon_thread = threading.Thread(
            target=self._daemon_loop, daemon=True,
        )
        self._daemon_thread.start()
        logger.info("[MemoryExtractor] Daemon thread started")

    def _daemon_loop(self) -> None:
        """
        Poll every 30s, trigger extraction if idle > 300s.

        Runs until ``stop_daemon()`` sets ``_daemon_running`` to False.
        """
        while self._daemon_running:
            time.sleep(DAEMON_POLL_INTERVAL)
            if not self._daemon_running:
                break
            if not self._is_extracting and self._check_idle(
                DEFAULT_IDLE_THRESHOLD
            ):
                logger.info(
                    "[MemoryExtractor] Idle threshold reached, "
                    "triggering extraction"
                )
                self.extract()

    def _check_idle(self, idle_seconds: int) -> bool:
        """Check if user has been idle longer than *idle_seconds*."""
        return (time.time() - self._last_input_timestamp) > idle_seconds

    def update_idle_timestamp(self) -> None:
        """
        Called by main loop on every user message.

        Resets the idle timer so the daemon won't trigger extraction
        prematurely.
        """
        self._last_input_timestamp = time.time()

    def stop_daemon(self) -> None:
        """Stop the daemon thread gracefully."""
        self._daemon_running = False
        if self._daemon_thread and self._daemon_thread.is_alive():
            self._daemon_thread.join(timeout=5)
        logger.info("[MemoryExtractor] Daemon thread stopped")

    # ── Extraction pipeline ─────────────────────────────────────────────

    def extract(self) -> List[MemoryEntry]:
        """
        Run the full extraction pipeline.

        For long transcripts (>~4K tokens / 16K chars), delegates to
        the sliding-window extractor (Amendment 6).  Otherwise processes
        all turns in a single pass.

        Returns:
            List of extracted MemoryEntry objects
        """
        if self._is_extracting:
            logger.debug("[MemoryExtractor] Extraction already in progress")
            return []

        self._is_extracting = True
        try:
            turns = self.transcript._read_all_turns()
            if not turns:
                logger.debug("[MemoryExtractor] No turns to extract from")
                return []

            filtered = self._filter_noise(turns)

            # Amendment 6: sliding window for long transcripts
            total_chars = sum(len(t.get("content", "")) for t in filtered)
            if total_chars > WINDOW_TOKENS * 4:
                logger.info(
                    "[MemoryExtractor] Long transcript (%d chars), "
                    "using sliding window",
                    total_chars,
                )
                return self._extract_with_sliding_window(filtered)

            # Standard single-pass extraction
            heuristics = self._heuristic_extract(filtered)
            structured = self._heuristic_to_entries(heuristics)
            self._write_memory_files(structured)
            logger.info(
                "[MemoryExtractor] Extracted %d entries", len(structured)
            )
            return structured
        finally:
            self._is_extracting = False

    def trigger_on_exit(self) -> List[MemoryEntry]:
        """
        Called at /exit or session end.

        Convenience wrapper around ``extract()`` for session cleanup.
        """
        return self.extract()

    def trigger_on_idle(self, idle_seconds: int = 300) -> List[MemoryEntry]:
        """
        Manual idle check with extraction.

        Amendment 2: Primarily called by the daemon thread now, but
        kept for backward compatibility and manual use.

        Args:
            idle_seconds: Idle threshold in seconds

        Returns:
            Extracted entries if idle threshold met, otherwise empty list
        """
        if self._check_idle(idle_seconds) and not self._is_extracting:
            return self.extract()
        return []

    # ── Amendment 6: Sliding window ─────────────────────────────────────

    def _extract_with_sliding_window(
        self, turns: List[Dict[str, Any]]
    ) -> List[MemoryEntry]:
        """
        4K-token sliding window with 1K overlap and rolling fact context.

        Processes the transcript in overlapping windows of ~4K tokens
        (~16K chars), maintaining a rolling list of previously extracted
        facts that gets prepended to each window for coherence.

        Args:
            turns: Pre-filtered transcript turns

        Returns:
            All extracted entries across all windows
        """
        entries: List[MemoryEntry] = []
        rolling_facts: List[str] = []
        window_chars = WINDOW_TOKENS * 4  # Convert token budget to chars
        i = 0

        while i < len(turns):
            window: List[Dict[str, Any]] = []
            chars = 0
            j = i

            # Fill window up to char budget
            while j < len(turns) and chars < window_chars:
                content_len = len(turns[j].get("content", ""))
                if chars + content_len > window_chars and window:
                    break
                window.append(turns[j])
                chars += content_len
                j += 1

            if not window:
                break

            # Prepend rolling fact context as a synthetic system turn
            if rolling_facts:
                context_text = "## Previously Extracted Facts\n" + "\n".join(
                    f"- {f}" for f in rolling_facts[-20:]
                )
                window_with_context = [
                    {"role": "system", "content": context_text}
                ] + window
            else:
                window_with_context = window

            heuristics = self._heuristic_extract(window_with_context)
            new_entries = self._heuristic_to_entries(heuristics)
            entries.extend(new_entries)

            # Update rolling facts
            for e in new_entries:
                rolling_facts.append(e.content[:100])
            if len(rolling_facts) > MAX_ROLLING_FACTS:
                rolling_facts = rolling_facts[-MAX_ROLLING_FACTS:]

            # Advance by overlap amount
            avg_content_len = max(1, chars // max(1, len(window)))
            overlap_chars = OVERLAP_TOKENS * 4
            i = max(i + 1, j - (overlap_chars // avg_content_len))

        self._write_memory_files(entries)
        logger.info(
            "[MemoryExtractor] Sliding window extracted %d entries",
            len(entries),
        )
        return entries

    # ── Heuristic extraction ────────────────────────────────────────────

    def _filter_noise(
        self, turns: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Remove system messages and low-value content.

        System messages are excluded because they contain static prompt
        text that doesn't represent user intent or project knowledge.

        Args:
            turns: Raw transcript turns

        Returns:
            Filtered turns with system messages removed
        """
        return [t for t in turns if t.get("role") not in ("system",)]

    def _heuristic_extract(
        self, turns: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """
        Extract patterns using regex (no LLM).

        Categorizes content into four buckets:
            - preferences: style guides, naming conventions, stated prefs
            - rules: architectural requirements, patterns
            - errors: error messages and traces
            - references: URLs

        Args:
            turns: Transcript turns to process

        Returns:
            Dict with keys "preferences", "rules", "errors", "references"
        """
        prefs: List[str] = []
        rules: List[str] = []
        errors: List[str] = []
        refs: List[str] = []

        for turn in turns:
            content = turn.get("content", "")

            # Preferences
            if any(
                kw in content.lower() for kw in _PREFERENCE_KEYWORDS
            ):
                prefs.append(content[:500])

            # Rules
            if any(
                kw in content.lower() for kw in _RULE_KEYWORDS
            ):
                rules.append(content[:500])

            # Errors
            if any(
                kw in content.lower() for kw in _ERROR_KEYWORDS
            ):
                errors.append(content[:500])

            # References (URLs)
            urls = _URL_PATTERN.findall(content)
            refs.extend(urls[:5])

        return {
            "preferences": prefs,
            "rules": rules,
            "errors": errors,
            "references": refs,
        }

    def _heuristic_to_entries(
        self, heuristics: Dict[str, List[str]]
    ) -> List[MemoryEntry]:
        """
        Convert heuristic extraction results to MemoryEntry objects.

        Args:
            heuristics: Dict from ``_heuristic_extract()``

        Returns:
            List of MemoryEntry objects (one per non-empty category)
        """
        entries: List[MemoryEntry] = []

        if heuristics.get("preferences"):
            entries.append(MemoryEntry(
                "user_preferences",
                "\n".join(heuristics["preferences"][:10]),
            ))

        if heuristics.get("rules"):
            entries.append(MemoryEntry(
                "project_rules",
                "\n".join(heuristics["rules"][:10]),
            ))

        if heuristics.get("errors"):
            entries.append(MemoryEntry(
                "error_patterns",
                "\n".join(heuristics["errors"][:10]),
            ))

        if heuristics.get("references"):
            entries.append(MemoryEntry(
                "reference_links",
                "\n".join(heuristics["references"][:20]),
            ))

        return entries

    # ── Persistence ─────────────────────────────────────────────────────

    def _write_memory_files(self, entries: List[MemoryEntry]) -> None:
        """
        Write YAML frontmatter Markdown to ~/.eaa/memory/.

        Each memory type gets its own file: ``user_preferences.md``,
        ``project_rules.md``, ``error_patterns.md``, ``reference_links.md``.

        Args:
            entries: MemoryEntry objects to persist
        """
        if not entries:
            return

        mem_dir = os.path.expanduser(MEMORY_DIR)
        os.makedirs(mem_dir, exist_ok=True)

        # Group entries by type
        type_files: Dict[str, List[MemoryEntry]] = {}
        for entry in entries:
            if entry.memory_type not in type_files:
                type_files[entry.memory_type] = []
            type_files[entry.memory_type].append(entry)

        for mem_type, type_entries in type_files.items():
            frontmatter = (
                f"---\ntype: {mem_type}\nscope: project\n"
                f"auto_extracted: true\n---\n"
            )
            content = "\n\n".join(e.content for e in type_entries)
            filepath = os.path.join(mem_dir, f"{mem_type}.md")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(frontmatter + content)
            logger.debug(
                "[MemoryExtractor] Wrote %s (%d entries)",
                filepath, len(type_entries),
            )
