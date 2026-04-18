"""
EAA V4 - Conversation Compactor
================================
Chunk-based summarization for local models (Rolling Chunk Compaction).

From the blueprint (Section 8.3):
  "When the context hits 80% capacity, instead of summarizing everything
   at once, the system takes only the oldest unsummarized 20% of the
   conversation, asks the model to summarize just that chunk, and appends
   the summary to a running <system_memory> block."

This replaces Claude Code's Layer 6 (Full Auto-Compact) which would OOM
a local GPU by feeding the entire conversation to the model at once.

Architecture:
  - Rolling window: always summarizes oldest 20% of unsummarized messages
  - Progressive compression: summaries accumulate in system_memory
  - VRAM-safe: each compaction step only processes a small chunk
  - Multiple compaction strategies: extractive, abstractive, section-based
  - Integration with SystemMemory for persistent summary storage
  - Truncation fallback when model summarization is unavailable

Integration:
  context_manager.py -> conversation_compactor.py (trigger compaction)
  conversation_compactor.py -> system_memory.py (store summaries)
  conversation_compactor.py -> token_tracker.py (update token counts)
"""

import os
import re
import time
import json
import logging
import hashlib
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# COMPACTION STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════════

class CompactionStrategy(Enum):
    """Different approaches to summarizing conversation chunks."""
    EXTRACTIVE = "extractive"          # Extract key lines (fast, no model needed)
    ABRSTRACTIVE = "abstractive"       # Model-generated summary (best quality)
    SECTION_BASED = "section_based"    # Per-section summarization
    TRUNCATION = "truncation"          # Simple truncation (fallback)
    HYBRID = "hybrid"                  # Extractive + truncation (balanced)


class CompactionLevel(Enum):
    """Severity levels of compaction."""
    MICROCOMPACT = "microcompact"      # Clear old tool results (>60min)
    CONTEXT_COLLAPSE = "context_collapse"  # Per-section summaries (~90% full)
    ROLLING_CHUNK = "rolling_chunk"    # Rolling 20% summarization (~80% full)
    FULL_COMPACT = "full_compact"      # Emergency full compaction


# ═══════════════════════════════════════════════════════════════════════════════
# MESSAGE TYPES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Message:
    """A conversation message with metadata."""
    role: str                          # "user", "assistant", "system", "tool"
    content: str
    timestamp: float = 0.0
    token_count: int = 0
    is_compacted: bool = False         # True if this message has been summarized
    compacted_hash: str = ""           # Hash to identify which compaction
    message_id: int = 0                # Position in conversation

    def to_dict(self) -> Dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "token_count": self.token_count,
            "is_compacted": self.is_compacted,
            "compacted_hash": self.compacted_hash,
            "message_id": self.message_id,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Message":
        return cls(**data)


# ═══════════════════════════════════════════════════════════════════════════════
# COMPACTION RESULT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CompactionResult:
    """Result of a compaction operation."""
    success: bool
    strategy: str
    level: str
    messages_compacted: int = 0
    original_tokens: int = 0
    summary_tokens: int = 0
    tokens_saved: int = 0
    summary_text: str = ""
    chunk_id: str = ""
    error_message: str = ""

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "strategy": self.strategy,
            "level": self.level,
            "messages_compacted": self.messages_compacted,
            "original_tokens": self.original_tokens,
            "summary_tokens": self.summary_tokens,
            "tokens_saved": self.tokens_saved,
            "summary_text": self.summary_text,
            "chunk_id": self.chunk_id,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# EXTRACTIVE SUMMARIZER
# ═══════════════════════════════════════════════════════════════════════════════

class ExtractiveSummarizer:
    """
    Fast, model-free summarization that extracts key information.

    Uses heuristics to identify important lines:
      - User messages (preserve user intent)
      - Error messages and exceptions
      - File paths and tool calls
      - Decision points and conclusions
      - First and last lines of long assistant responses
    """

    # Patterns that indicate important content
    IMPORTANT_PATTERNS = [
        r"error", r"exception", r"traceback", r"failed",
        r"TODO", r"FIXME", r"NOTE", r"IMPORTANT",
        r"decision", r"conclusion", r"summary",
        r"file", r"path", r"\.py", r"\.js",
        r"def ", r"class ", r"import ",
        r"created", r"modified", r"deleted",
    ]

    # Patterns for tool results to heavily compress
    TOOL_RESULT_PATTERNS = [
        r"^\s*\[",                      # Tool output markers
        r"^(True|False)$",              # Boolean results
        r"^\d+$",                        # Numeric-only results
        r"^None$",                       # None results
    ]

    def summarize(self, messages: List[Message]) -> str:
        """
        Extract key lines from a list of messages.

        Args:
            messages: List of Message objects to summarize

        Returns:
            Extracted key information as a formatted string
        """
        if not messages:
            return ""

        key_lines = []
        seen_content = set()

        for msg in messages:
            lines = msg.content.split("\n")

            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue

                # Skip duplicate content
                content_hash = hashlib.md5(stripped.encode()).hexdigest()[:8]
                if content_hash in seen_content:
                    continue

                # Always include user messages (they represent intent)
                if msg.role == "user" and len(key_lines) < 20:
                    key_lines.append(f"[User] {stripped}")
                    seen_content.add(content_hash)
                    continue

                # Check importance patterns
                is_important = any(
                    re.search(pat, stripped, re.IGNORECASE)
                    for pat in self.IMPORTANT_PATTERNS
                )

                # Skip tool result noise
                is_noise = any(
                    re.match(pat, stripped) for pat in self.TOOL_RESULT_PATTERNS
                )

                if is_important and not is_noise:
                    prefix = f"[{msg.role}] " if msg.role != "assistant" else ""
                    key_lines.append(f"{prefix}{stripped}")
                    seen_content.add(content_hash)

                # Include first and last lines of assistant responses
                elif msg.role == "assistant" and i < 2 and not is_noise:
                    if len(stripped) < 200:
                        key_lines.append(f"[Assistant] {stripped}")
                        seen_content.add(content_hash)

        # Limit total output
        if len(key_lines) > 50:
            key_lines = key_lines[:50]
            key_lines.append("... [additional content compacted]")

        return "\n".join(key_lines)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION-BASED SUMMARIZER
# ═══════════════════════════════════════════════════════════════════════════════

class SectionSummarizer:
    """
    Categorizes and summarizes messages by section type.

    From Claude Code's Layer 4 (Context Collapse):
      "Summarize each conversation section independently"

    Groups messages into: tool_usage, code_changes, decisions, errors, context.
    """

    SECTION_PATTERNS = {
        "tool_usage": [
            r"tool", r"function", r"called", r"executed",
            r"result", r"output", r"returned",
        ],
        "code_changes": [
            r"edit", r"create", r"modify", r"write", r"delete",
            r"\.py", r"\.js", r"\.ts", r"file",
            r"function", r"class", r"import", r"def ",
        ],
        "decisions": [
            r"decided", r"chose", r"selected", r"will use",
            r"plan", r"approach", r"strategy",
        ],
        "errors": [
            r"error", r"exception", r"traceback", r"failed",
            r"bug", r"fix", r"issue",
        ],
    }

    def summarize(self, messages: List[Message]) -> Tuple[str, str]:
        """
        Summarize messages by section and determine primary section.

        Returns:
            (summary_text, primary_section_name)
        """
        if not messages:
            return "", "context"

        sections: Dict[str, List[str]] = {
            "tool_usage": [],
            "code_changes": [],
            "decisions": [],
            "errors": [],
            "context": [],
        }

        for msg in messages:
            lines = msg.content.split("\n")[:10]  # First 10 lines per message

            for line in lines:
                stripped = line.strip()
                if not stripped or len(stripped) < 5:
                    continue

                categorized = False
                for section, patterns in self.SECTION_PATTERNS.items():
                    if any(
                        re.search(pat, stripped, re.IGNORECASE)
                        for pat in patterns
                    ):
                        sections[section].append(stripped)
                        categorized = True
                        break

                if not categorized:
                    sections["context"].append(stripped)

        # Find primary section (most content)
        primary = max(sections, key=lambda k: len(sections[k]))

        # Build summary
        parts = []
        for section_name, items in sections.items():
            if not items:
                continue
            # Deduplicate and limit
            unique = list(dict.fromkeys(items))[:10]
            section_text = f"[{section_name.upper()}]\n" + "\n".join(unique)
            parts.append(section_text)

        return "\n\n".join(parts), primary


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION COMPACTOR
# ═══════════════════════════════════════════════════════════════════════════════

# Default compaction parameters
DEFAULT_CHUNK_FRACTION = 0.20        # Summarize oldest 20%
DEFAULT_MIN_CHUNK_SIZE = 5           # Minimum messages to compact
DEFAULT_MICROCOMPACT_AGE = 3600      # 60 minutes (Section 8.1, Layer 3)
DEFAULT_SUMMARY_MAX_CHARS = 5_000    # Max chars per summary
DEFAULT_SUMMARIZE_CALLBACK = None    # Will use extractive by default


class ConversationCompactor:
    """
    Main compaction engine implementing Rolling Chunk Compaction.

    From the blueprint (Section 8.3):
      "The process repeats every time the context grows back to 80%,
       always summarizing only the oldest unsummarized portion."

    Compaction levels:
      1. MICROCOMPACT: Clear old tool results (>60 min)
      2. CONTEXT_COLLAPSE: Per-section summaries (~90% full)
      3. ROLLING_CHUNK: Rolling 20% summarization (~80% full)
      4. FULL_COMPACT: Emergency full compaction (overflow)
    """

    def __init__(
        self,
        chunk_fraction: float = DEFAULT_CHUNK_FRACTION,
        min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
        microcompact_age: float = DEFAULT_MICROCOMPACT_AGE,
        summary_max_chars: int = DEFAULT_SUMMARY_MAX_CHARS,
        summarize_callback: Optional[Callable] = None,
    ):
        self.chunk_fraction = chunk_fraction
        self.min_chunk_size = min_chunk_size
        self.microcompact_age = microcompact_age
        self.summary_max_chars = summary_max_chars
        self.summarize_callback = summarize_callback

        # Internal summarizers
        self._extractive = ExtractiveSummarizer()
        self._section = SectionSummarizer()

        # Compaction history
        self._compaction_history: List[CompactionResult] = []
        self._chunk_counter = 0

        # Stats
        self._total_messages_compacted = 0
        self._total_tokens_saved = 0
        self._total_compactions = 0

        logger.info(
            f"[Compactor] Initialized: chunk_fraction={chunk_fraction}, "
            f"microcompact_age={microcompact_age}s"
        )

    def compact(
        self,
        messages: List[Message],
        level: CompactionLevel,
        current_tokens: int = 0,
    ) -> CompactionResult:
        """
        Perform compaction at the specified level.

        Args:
            messages: Current conversation messages
            level: Compaction level to apply
            current_tokens: Current token count in context

        Returns:
            CompactionResult with details
        """
        if level == CompactionLevel.MICROCOMPACT:
            return self._microcompact(messages)
        elif level == CompactionLevel.CONTEXT_COLLAPSE:
            return self._context_collapse(messages)
        elif level == CompactionLevel.ROLLING_CHUNK:
            return self._rolling_chunk_compact(messages, current_tokens)
        elif level == CompactionLevel.FULL_COMPACT:
            return self._full_compact(messages)
        else:
            return CompactionResult(
                success=False,
                strategy="none",
                level=level.value,
                error_message=f"Unknown compaction level: {level}",
            )

    def _microcompact(self, messages: List[Message]) -> CompactionResult:
        """
        Layer 3: Clear old tool results.

        From Claude Code (Section 8.1):
          "Every turn, >60min old results - Clear old tool results,
           defer boundary messages"
        """
        now = time.time()
        cleared_count = 0
        tokens_cleared = 0

        for msg in messages:
            if msg.role == "tool" and not msg.is_compacted:
                age = now - msg.timestamp
                if age > self.microcompact_age:
                    # Replace content with short placeholder
                    msg.is_compacted = True
                    tokens_cleared += msg.token_count
                    msg.token_count = 0
                    msg.content = f"[Tool result compacted - {int(age)}s old]"
                    cleared_count += 1

        result = CompactionResult(
            success=True,
            strategy=CompactionStrategy.EXTRACTIVE.value,
            level=CompactionLevel.MICROCOMPACT.value,
            messages_compacted=cleared_count,
            original_tokens=tokens_cleared,
            summary_tokens=0,
            tokens_saved=tokens_cleared,
        )

        self._record_compaction(result)
        return result

    def _context_collapse(self, messages: List[Message]) -> CompactionResult:
        """
        Layer 4: Per-section summarization.

        From Claude Code (Section 8.1):
          "~90% full, per-section - Summarize each conversation section
           independently"
        """
        # Find oldest uncompacted block
        uncompacted = [m for m in messages if not m.is_compacted]
        if len(uncompacted) < self.min_chunk_size:
            return CompactionResult(
                success=False,
                strategy="none",
                level=CompactionLevel.CONTEXT_COLLAPSE.value,
                error_message=f"Not enough messages ({len(uncompacted)} < {self.min_chunk_size})",
            )

        # Take oldest 30% for section-based collapse
        chunk_size = max(self.min_chunk_size, int(len(uncompacted) * 0.30))
        chunk = uncompacted[:chunk_size]

        # Use section-based summarizer
        summary_text, primary_section = self._section.summarize(chunk)

        # If callback provided, try model summarization
        if self.summarize_callback:
            try:
                model_summary = self.summarize_callback(chunk)
                if model_summary and len(model_summary) > 10:
                    summary_text = model_summary
            except Exception as e:
                logger.warning(f"[Compactor] Model summarization failed: {e}")

        # Truncate if too long
        if len(summary_text) > self.summary_max_chars:
            summary_text = summary_text[:self.summary_max_chars] + "\n... [truncated]"

        # Mark messages as compacted
        original_tokens = sum(m.token_count for m in chunk)
        chunk_id = self._next_chunk_id()

        for msg in chunk:
            msg.is_compacted = True
            msg.compacted_hash = chunk_id

        from token_tracker import estimate_tokens
        summary_tokens = estimate_tokens(summary_text)

        result = CompactionResult(
            success=True,
            strategy=CompactionStrategy.SECTION_BASED.value,
            level=CompactionLevel.CONTEXT_COLLAPSE.value,
            messages_compacted=len(chunk),
            original_tokens=original_tokens,
            summary_tokens=summary_tokens,
            tokens_saved=original_tokens - summary_tokens,
            summary_text=summary_text,
            chunk_id=chunk_id,
        )

        self._record_compaction(result)
        return result

    def _rolling_chunk_compact(
        self, messages: List[Message], current_tokens: int
    ) -> CompactionResult:
        """
        Layer 5/6: Rolling Chunk Compaction (THE KEY HMoE ADAPTATION).

        From the blueprint (Section 8.3):
          "Instead of summarizing everything at once, the system takes
           only the oldest unsummarized 20% of the conversation, asks
           the model to summarize just that chunk."

        This is the critical difference from Claude Code's approach:
        - Claude: summarize ALL messages at once (OOM on local GPU)
        - EAA: summarize only 20% at a time (VRAM-safe)
        """
        uncompacted = [m for m in messages if not m.is_compacted]

        if len(uncompacted) < self.min_chunk_size:
            return CompactionResult(
                success=False,
                strategy="none",
                level=CompactionLevel.ROLLING_CHUNK.value,
                error_message=f"Not enough uncompacted messages ({len(uncompacted)})",
            )

        # Take the oldest N% of uncompacted messages
        chunk_size = max(
            self.min_chunk_size,
            int(len(uncompacted) * self.chunk_fraction)
        )
        chunk = uncompacted[:chunk_size]

        # Generate summary
        summary_text = self._summarize_chunk(chunk)
        chunk_id = self._next_chunk_id()

        # Truncate if needed
        if len(summary_text) > self.summary_max_chars:
            summary_text = summary_text[:self.summary_max_chars] + "\n... [truncated]"

        # Mark messages as compacted
        original_tokens = sum(m.token_count for m in chunk)
        for msg in chunk:
            msg.is_compacted = True
            msg.compacted_hash = chunk_id

        from token_tracker import estimate_tokens
        summary_tokens = estimate_tokens(summary_text)

        result = CompactionResult(
            success=True,
            strategy=CompactionStrategy.HYBRID.value,
            level=CompactionLevel.ROLLING_CHUNK.value,
            messages_compacted=len(chunk),
            original_tokens=original_tokens,
            summary_tokens=summary_tokens,
            tokens_saved=original_tokens - summary_tokens,
            summary_text=summary_text,
            chunk_id=chunk_id,
        )

        self._record_compaction(result)

        logger.info(
            f"[Compactor] Rolling chunk: {len(chunk)} messages "
            f"({original_tokens} -> {summary_tokens} tokens, "
            f"{result.tokens_saved} saved)"
        )

        return result

    def _full_compact(self, messages: List[Message]) -> CompactionResult:
        """
        Emergency full compaction (Layer 6 equivalent).

        Summarizes ALL uncompacted messages. Should rarely trigger
        because rolling chunk compaction keeps things under control.
        """
        uncompacted = [m for m in messages if not m.is_compacted]

        if not uncompacted:
            return CompactionResult(
                success=False,
                strategy="none",
                level=CompactionLevel.FULL_COMPACT.value,
                error_message="No messages to compact",
            )

        summary_text = self._summarize_chunk(uncompacted)
        chunk_id = self._next_chunk_id("emergency")

        if len(summary_text) > self.summary_max_chars * 2:
            summary_text = summary_text[:self.summary_max_chars * 2] + "\n... [truncated]"

        original_tokens = sum(m.token_count for m in uncompacted)
        for msg in uncompacted:
            msg.is_compacted = True
            msg.compacted_hash = chunk_id

        from token_tracker import estimate_tokens
        summary_tokens = estimate_tokens(summary_text)

        result = CompactionResult(
            success=True,
            strategy=CompactionStrategy.HYBRID.value,
            level=CompactionLevel.FULL_COMPACT.value,
            messages_compacted=len(uncompacted),
            original_tokens=original_tokens,
            summary_tokens=summary_tokens,
            tokens_saved=original_tokens - summary_tokens,
            summary_text=summary_text,
            chunk_id=chunk_id,
        )

        self._record_compaction(result)
        return result

    def _summarize_chunk(self, messages: List[Message]) -> str:
        """
        Summarize a chunk of messages using available strategy.

        Priority: model callback > extractive > truncation fallback
        """
        # Try model-based summarization first
        if self.summarize_callback:
            try:
                summary = self.summarize_callback(messages)
                if summary and len(summary) > 10:
                    return summary
            except Exception as e:
                logger.warning(f"[Compactor] Model summary failed: {e}")

        # Fall back to extractive
        summary = self._extractive.summarize(messages)
        if summary:
            return summary

        # Last resort: simple truncation summary
        content = "\n".join(
            f"[{m.role}] {m.content[:100]}"
            for m in messages[:10]
        )
        return content + "\n... [compact fallback]"

    def _next_chunk_id(self, prefix: str = "") -> str:
        """Generate a unique chunk identifier."""
        self._chunk_counter += 1
        ts = int(time.time()) % 10000
        return f"{prefix}chunk_{ts}_{self._chunk_counter:04d}" if prefix else f"chunk_{ts}_{self._chunk_counter:04d}"

    def _record_compaction(self, result: CompactionResult) -> None:
        """Record compaction result in history and update stats."""
        self._compaction_history.append(result)
        self._total_messages_compacted += result.messages_compacted
        self._total_tokens_saved += max(0, result.tokens_saved)
        self._total_compactions += 1

    def should_compact(
        self,
        usage_fraction: float,
        has_old_tool_results: bool = False,
    ) -> Optional[CompactionLevel]:
        """
        Determine if compaction is needed based on context usage.

        Args:
            usage_fraction: Current context usage (0.0 to 1.0+)
            has_old_tool_results: Whether there are tool results older than microcompact_age

        Returns:
            Recommended CompactionLevel or None if no compaction needed
        """
        if usage_fraction >= 0.95:
            return CompactionLevel.FULL_COMPACT
        elif usage_fraction >= 0.80:
            return CompactionLevel.ROLLING_CHUNK
        elif usage_fraction >= 0.90:
            return CompactionLevel.CONTEXT_COLLAPSE
        elif has_old_tool_results:
            return CompactionLevel.MICROCOMPACT
        return None

    def get_history(self, limit: int = 10) -> List[CompactionResult]:
        """Get recent compaction history."""
        return self._compaction_history[-limit:]

    def get_stats(self) -> Dict:
        """Return comprehensive compaction statistics."""
        return {
            "total_compactions": self._total_compactions,
            "total_messages_compacted": self._total_messages_compacted,
            "total_tokens_saved": self._total_tokens_saved,
            "chunk_fraction": self.chunk_fraction,
            "microcompact_age": self.microcompact_age,
            "history_length": len(self._compaction_history),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY
# ═══════════════════════════════════════════════════════════════════════════════

def create_compactor(
    chunk_fraction: float = DEFAULT_CHUNK_FRACTION,
    microcompact_age: float = DEFAULT_MICROCOMPACT_AGE,
    summarize_callback: Optional[Callable] = None,
) -> ConversationCompactor:
    """
    Factory function for creating a ConversationCompactor.

    Args:
        chunk_fraction: Fraction of oldest messages to summarize (0.0-1.0)
        microcompact_age: Age in seconds for microcompact trigger
        summarize_callback: Optional model-based summarization function

    Returns:
        Configured ConversationCompactor instance
    """
    return ConversationCompactor(
        chunk_fraction=chunk_fraction,
        microcompact_age=microcompact_age,
        summarize_callback=summarize_callback,
    )
