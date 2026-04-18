"""
EAA V4 - System Memory
======================
Persistent memory block for compressed conversation summaries.

From the blueprint (Section 8.3):
  "The system takes only the oldest unsummarized 20% of the conversation,
   asks the model to summarize just that chunk, and appends the summary
   to a running <system_memory> block at the beginning of the conversation."

This module manages the system_memory block that accumulates summaries
from Rolling Chunk Compaction (Layer 5/6 of the cascade).

Architecture:
  - Ordered list of memory entries (timestamped summaries)
  - Disk persistence (survives across sessions)
  - Size-aware management (prevents memory block from growing too large)
  - Section-tagged summaries (tool_usage, code_changes, decisions, errors)
  - Compact/format for injection into system prompt or first user message

Integration:
  conversation_compactor.py -> system_memory.py (append summaries)
  context_manager.py -> system_memory.py (inject into context)
  system_prompt.py -> system_memory.py (render as <system_memory> tag)
"""

import os
import json
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY SECTION TYPES
# ═══════════════════════════════════════════════════════════════════════════════

class MemorySection(Enum):
    """Categorization tags for memory entries."""
    TOOL_USAGE = "tool_usage"           # Tool execution summaries
    CODE_CHANGES = "code_changes"       # File edits, creations
    DECISIONS = "decisions"             # Key decisions and rationale
    ERRORS = "errors"                   # Errors encountered and fixes
    CONTEXT = "context"                 # General context (user preferences, project info)
    TASK_SUMMARY = "task_summary"       # High-level task progress


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY ENTRY
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MemoryEntry:
    """
    A single entry in the system memory block.

    Each entry represents a compressed summary of a conversation chunk,
    tagged with its section type for organized retrieval.
    """
    section: str                        # MemorySection value
    content: str                        # The summary text
    timestamp: float                    # When this summary was created
    original_tokens: int = 0            # Tokens of the original chunk
    summary_tokens: int = 0             # Tokens of the compressed summary
    chunk_id: str = ""                  # Identifier of the summarized chunk
    message_range: Tuple[int, int] = (0, 0)  # Original message range

    def to_dict(self) -> Dict:
        return {
            "section": self.section,
            "content": self.content,
            "timestamp": self.timestamp,
            "original_tokens": self.original_tokens,
            "summary_tokens": self.summary_tokens,
            "chunk_id": self.chunk_id,
            "message_range": list(self.message_range),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "MemoryEntry":
        return cls(
            section=data["section"],
            content=data["content"],
            timestamp=data["timestamp"],
            original_tokens=data.get("original_tokens", 0),
            summary_tokens=data.get("summary_tokens", 0),
            chunk_id=data.get("chunk_id", ""),
            message_range=tuple(data.get("message_range", (0, 0))),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM MEMORY MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

# Default limits
DEFAULT_MAX_MEMORY_ENTRIES = 100
DEFAULT_MAX_MEMORY_CHARS = 40_000       # Claude Code limit (Section 10.3)
DEFAULT_MAX_SECTION_CHARS = 10_000      # Per-section limit


class SystemMemory:
    """
    Manages the persistent system memory block.

    From the blueprint (Section 8.3 - Rolling Chunk Compaction):
      "Appends the summary to a running <system_memory> block at the
       beginning of the conversation."

    The memory block accumulates compressed summaries from conversation
    chunks that have been compacted. It provides:
      - Ordered append of new summaries
      - Section-based retrieval and filtering
      - Size-aware management to prevent unbounded growth
      - Disk persistence for cross-session survival
      - Formatted rendering for injection into prompts

    Usage:
        memory = SystemMemory(project_dir="/project")
        memory.add_summary(
            section="code_changes",
            content="Modified router.py to add fuzzy matching support",
            original_tokens=5000,
            summary_tokens=200,
            chunk_id="chunk_001",
        )
        prompt_block = memory.render_for_prompt()
    """

    def __init__(
        self,
        project_dir: str = "",
        max_entries: int = DEFAULT_MAX_MEMORY_ENTRIES,
        max_chars: int = DEFAULT_MAX_MEMORY_CHARS,
        max_section_chars: int = DEFAULT_MAX_SECTION_CHARS,
    ):
        self._entries: List[MemoryEntry] = []
        self.max_entries = max_entries
        self.max_chars = max_chars
        self.max_section_chars = max_section_chars
        self.project_dir = project_dir

        # Persistence file
        self._persist_path = ""
        if project_dir:
            os.makedirs(project_dir, exist_ok=True)
            self._persist_path = os.path.join(
                project_dir, ".eaa", "system_memory.json"
            )

        # Stats
        self._total_summaries_added = 0
        self._total_original_tokens = 0
        self._total_summary_tokens = 0
        self._eviction_count = 0

        # Load from disk if available
        if self._persist_path and os.path.exists(self._persist_path):
            self._load_from_disk()

        logger.info(
            f"[SystemMemory] Initialized: max_entries={max_entries}, "
            f"max_chars={max_chars}, entries_loaded={len(self._entries)}"
        )

    def add_summary(
        self,
        section: str,
        content: str,
        original_tokens: int = 0,
        summary_tokens: int = 0,
        chunk_id: str = "",
        message_range: Tuple[int, int] = (0, 0),
    ) -> MemoryEntry:
        """
        Add a new summary entry to the system memory.

        Args:
            section: MemorySection value or custom section name
            content: The summary text
            original_tokens: Token count of the original chunk
            summary_tokens: Token count of this summary
            chunk_id: Identifier for the summarized chunk
            message_range: (start, end) message indices of original

        Returns:
            The created MemoryEntry
        """
        # Validate section
        if section not in [s.value for s in MemorySection]:
            logger.warning(
                f"[SystemMemory] Unknown section '{section}', "
                f"treating as 'context'"
            )
            section = MemorySection.CONTEXT.value

        entry = MemoryEntry(
            section=section,
            content=content,
            timestamp=time.time(),
            original_tokens=original_tokens,
            summary_tokens=summary_tokens,
            chunk_id=chunk_id,
            message_range=message_range,
        )

        self._entries.append(entry)

        # Update stats
        self._total_summaries_added += 1
        self._total_original_tokens += original_tokens
        self._total_summary_tokens += summary_tokens

        # Enforce limits
        self._enforce_limits()

        # Persist to disk
        self._save_to_disk()

        logger.info(
            f"[SystemMemory] Added summary [{section}]: "
            f"{len(content)} chars, compression ratio="
            f"{summary_tokens/max(original_tokens,1):.2f}x" if original_tokens > 0 else
            f"[SystemMemory] Added summary [{section}]: {len(content)} chars"
        )

        return entry

    def get_entries(
        self,
        section: Optional[str] = None,
        since: Optional[float] = None,
        limit: int = 0,
    ) -> List[MemoryEntry]:
        """
        Retrieve memory entries with optional filtering.

        Args:
            section: Filter by section type (None = all)
            since: Only entries after this timestamp
            limit: Max entries to return (0 = no limit)

        Returns:
            Filtered list of MemoryEntry objects
        """
        entries = self._entries

        if section:
            entries = [e for e in entries if e.section == section]

        if since:
            entries = [e for e in entries if e.timestamp >= since]

        if limit > 0:
            entries = entries[-limit:]

        return entries

    def get_section_summaries(self) -> Dict[str, str]:
        """
        Get a consolidated summary per section.

        Returns:
            Dict mapping section name to combined content text
        """
        sections: Dict[str, List[str]] = {}
        for entry in self._entries:
            if entry.section not in sections:
                sections[entry.section] = []
            sections[entry.section].append(entry.content)

        return {
            section: "\n".join(contents)
            for section, contents in sections.items()
        }

    def render_for_prompt(self, max_chars: int = 0) -> str:
        """
        Render the entire memory block for injection into a prompt.

        From Claude Code's approach (Section 10.3):
          "Injected into the first user message as a <system-reminder> tag"

        Format:
          <system_memory>
          [TOOL_USAGE]
          - Used smart_edit.py to modify router.py (chunk_001)
          [CODE_CHANGES]
          - Modified router.py: added fuzzy matching (chunk_001)
          - Created new file context_manager.py (chunk_002)
          [DECISIONS]
          - Chose rolling chunk compaction over full auto-compact
          </system_memory>

        Args:
            max_chars: Maximum chars for the rendered output (0 = use self.max_chars)

        Returns:
            Formatted string ready for prompt injection
        """
        effective_max = max_chars or self.max_chars

        if not self._entries:
            return ""

        # Group by section, respecting per-section limits
        sections = self.get_section_summaries()

        parts = ["<system_memory>"]

        # Priority order for sections
        priority_order = [
            MemorySection.DECISIONS.value,
            MemorySection.CODE_CHANGES.value,
            MemorySection.TOOL_USAGE.value,
            MemorySection.ERRORS.value,
            MemorySection.TASK_SUMMARY.value,
            MemorySection.CONTEXT.value,
        ]

        total_chars = len(parts[0]) + len("</system_memory>")

        for section in priority_order:
            if section not in sections:
                continue

            content = sections[section]

            # Truncate section if too long
            if len(content) > self.max_section_chars:
                content = content[:self.max_section_chars] + "\n... [section truncated]"

            section_header = f"[{section.upper()}]"
            section_text = f"{section_header}\n{content}"

            if total_chars + len(section_text) > effective_max:
                # Find how much we can fit
                remaining = effective_max - total_chars - len(section_header) - 10
                if remaining > 100:
                    content = content[:remaining] + "\n... [truncated]"
                    section_text = f"{section_header}\n{content}"
                    parts.append(section_text)
                break

            parts.append(section_text)
            total_chars += len(section_text)

        # Add any sections not in priority order
        for section in sections:
            if section not in priority_order:
                content = sections[section][:500]  # Small limit for custom sections
                if total_chars + len(content) + 20 < effective_max:
                    parts.append(f"[{section.upper()}]\n{content}")
                    total_chars += len(content) + 20

        parts.append("</system_memory>")
        return "\n".join(parts)

    def get_total_chars(self) -> int:
        """Get total character count of all entries."""
        return sum(len(e.content) for e in self._entries)

    def get_total_tokens(self) -> int:
        """Get total token estimate of all entries."""
        from token_tracker import estimate_tokens
        return sum(estimate_tokens(e.content) for e in self._entries)

    def clear(self) -> int:
        """
        Clear all memory entries.

        Returns:
            Number of entries cleared
        """
        count = len(self._entries)
        self._entries.clear()
        self._save_to_disk()
        logger.info(f"[SystemMemory] Cleared {count} entries")
        return count

    def remove_chunk(self, chunk_id: str) -> bool:
        """
        Remove all entries associated with a specific chunk.

        Returns:
            True if any entries were removed
        """
        original_len = len(self._entries)
        self._entries = [e for e in self._entries if e.chunk_id != chunk_id]
        removed = original_len - len(self._entries)

        if removed > 0:
            self._save_to_disk()
            logger.info(
                f"[SystemMemory] Removed {removed} entries for chunk '{chunk_id}'"
            )

        return removed > 0

    def get_compression_ratio(self) -> float:
        """
        Get the overall compression ratio (original / summary tokens).

        Returns:
            Compression ratio (higher = more compression)
        """
        if self._total_summary_tokens == 0:
            return 0.0
        return self._total_original_tokens / self._total_summary_tokens

    def _enforce_limits(self) -> None:
        """Enforce entry count and character limits."""
        # Evict oldest entries if over max_entries
        while len(self._entries) > self.max_entries:
            self._entries.pop(0)
            self._eviction_count += 1

        # Truncate content of oldest entries if over max_chars
        total = self.get_total_chars()
        while total > self.max_chars and len(self._entries) > 0:
            evicted = self._entries.pop(0)
            total -= len(evicted.content)
            self._eviction_count += 1

    def _save_to_disk(self) -> None:
        """Persist memory to disk."""
        if not self._persist_path:
            return

        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            data = {
                "entries": [e.to_dict() for e in self._entries],
                "stats": {
                    "total_summaries_added": self._total_summaries_added,
                    "total_original_tokens": self._total_original_tokens,
                    "total_summary_tokens": self._total_summary_tokens,
                    "eviction_count": self._eviction_count,
                },
            }
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[SystemMemory] Failed to save: {e}")

    def _load_from_disk(self) -> None:
        """Load memory from disk."""
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._entries = [
                MemoryEntry.from_dict(e) for e in data.get("entries", [])
            ]
            stats = data.get("stats", {})
            self._total_summaries_added = stats.get("total_summaries_added", 0)
            self._total_original_tokens = stats.get("total_original_tokens", 0)
            self._total_summary_tokens = stats.get("total_summary_tokens", 0)
            self._eviction_count = stats.get("eviction_count", 0)

            logger.info(
                f"[SystemMemory] Loaded {len(self._entries)} entries from disk"
            )
        except Exception as e:
            logger.error(f"[SystemMemory] Failed to load: {e}")
            self._entries = []

    def get_stats(self) -> Dict:
        """Return comprehensive memory statistics."""
        return {
            "total_entries": len(self._entries),
            "total_chars": self.get_total_chars(),
            "total_tokens": self.get_total_tokens(),
            "total_summaries_added": self._total_summaries_added,
            "total_original_tokens": self._total_original_tokens,
            "total_summary_tokens": self._total_summary_tokens,
            "compression_ratio": round(self.get_compression_ratio(), 2),
            "eviction_count": self._eviction_count,
            "max_entries": self.max_entries,
            "max_chars": self.max_chars,
            "entries_per_section": self._count_per_section(),
        }

    def _count_per_section(self) -> Dict[str, int]:
        """Count entries per section."""
        counts: Dict[str, int] = {}
        for e in self._entries:
            counts[e.section] = counts.get(e.section, 0) + 1
        return counts


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY
# ═══════════════════════════════════════════════════════════════════════════════

def create_system_memory(
    project_dir: str = "",
    max_chars: int = DEFAULT_MAX_MEMORY_CHARS,
) -> SystemMemory:
    """
    Factory function for creating a SystemMemory instance.

    Args:
        project_dir: Project root directory for persistence
        max_chars: Maximum character budget for memory block

    Returns:
        Configured SystemMemory instance
    """
    return SystemMemory(
        project_dir=project_dir,
        max_entries=DEFAULT_MAX_MEMORY_ENTRIES,
        max_chars=max_chars,
    )
