"""
prompt_cache.py — Prompt Cache Splitting (Phase 4)

Splits the system prompt into cacheable blocks with different scopes,
mirroring Claude Code's splitSysPromptPrefix architecture.

Cache scopes:
    - "never":    Never cached (attribution, CLI prefix)
    - "global":   Cached once across all sessions (static instructions)
    - "org":      Cached at organization level (dynamic but shared)
    - "session":  Not cached (per-session dynamic content)

Reference: Blueprint Section 10.5 — Prompt Caching Architecture
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class CacheScope(Enum):
    NEVER = "never"
    GLOBAL = "global"
    ORG = "org"
    SESSION = "session"


@dataclass
class PromptBlock:
    """A single block of the system prompt with a cache scope."""
    content: str
    scope: CacheScope
    label: str = ""

    @property
    def token_estimate(self) -> int:
        """Rough token estimate: ~4 chars per token."""
        return len(self.content) // 4


@dataclass
class CacheSplitResult:
    """Result of splitting a system prompt into cacheable blocks."""
    blocks: List[PromptBlock] = field(default_factory=list)
    boundary_index: int = -1  # Index where cacheable/non-cacheable split

    @property
    def total_tokens(self) -> int:
        return sum(b.token_estimate for b in self.blocks)

    @property
    def cacheable_tokens(self) -> int:
        return sum(b.token_estimate for b in self.blocks if b.scope != CacheScope.NEVER and b.scope != CacheScope.SESSION)

    def get_prefix_blocks(self) -> List[PromptBlock]:
        """Get blocks before the boundary (typically cacheable)."""
        if self.boundary_index < 0:
            return list(self.blocks)
        return self.blocks[:self.boundary_index + 1]

    def get_suffix_blocks(self) -> List[PromptBlock]:
        """Get blocks after the boundary (typically dynamic)."""
        if self.boundary_index < 0:
            return []
        return self.blocks[self.boundary_index + 1:]


# Boundary marker used to split static from dynamic content
CACHE_BOUNDARY_MARKER = "<!-- EAA_CACHE_BOUNDARY -->"


def split_prompt_blocks(
    full_prompt: str,
    attribution_header: str = "",
    cli_prefix: str = "",
) -> CacheSplitResult:
    """
    Split a full system prompt into cacheable blocks following Claude Code's
    caching architecture.

    The prompt is split at the CACHE_BOUNDARY_MARKER. Content before the
    boundary is globally cacheable. Content after is session-scoped.

    Args:
        full_prompt: The complete assembled system prompt.
        attribution_header: Optional header (never cached).
        cli_prefix: Optional CLI prefix (org-scoped cache).

    Returns:
        CacheSplitResult with ordered blocks and boundary index.
    """
    blocks: List[PromptBlock] = []
    boundary_index = -1

    # Layer 0: Attribution header (never cached)
    if attribution_header.strip():
        blocks.append(PromptBlock(
            content=attribution_header.strip() + "\n\n",
            scope=CacheScope.NEVER,
            label="attribution"
        ))

    # CLI prefix (org-scoped cache)
    if cli_prefix.strip():
        blocks.append(PromptBlock(
            content=cli_prefix.strip() + "\n\n",
            scope=CacheScope.ORG,
            label="cli_prefix"
        ))

    # Split at boundary marker
    if CACHE_BOUNDARY_MARKER in full_prompt:
        before, after = full_prompt.split(CACHE_BOUNDARY_MARKER, 1)
    else:
        before = full_prompt
        after = ""

    # Static content before boundary (globally cacheable)
    if before.strip():
        blocks.append(PromptBlock(
            content=before.strip() + "\n",
            scope=CacheScope.GLOBAL,
            label="static_instructions"
        ))
        boundary_index = len(blocks) - 1

    # Dynamic content after boundary (session-scoped, not cached)
    if after.strip():
        blocks.append(PromptBlock(
            content=after.strip() + "\n",
            scope=CacheScope.SESSION,
            label="dynamic_content"
        ))

    return CacheSplitResult(blocks=blocks, boundary_index=boundary_index)


def create_cache_key(block: PromptBlock, session_id: str = "") -> str:
    """
    Create a deterministic cache key for a prompt block.

    Args:
        block: The prompt block to key.
        session_id: Optional session identifier for session-scoped blocks.

    Returns:
        A string cache key.
    """
    if block.scope == CacheScope.NEVER:
        return f"nocache:{block.label}"
    elif block.scope == CacheScope.GLOBAL:
        return f"global:{block.label}:{hash(block.content) % (2**32):08x}"
    elif block.scope == CacheScope.ORG:
        return f"org:{block.label}:{hash(block.content) % (2**32):08x}"
    else:
        return f"session:{session_id}:{block.label}"


class PromptCacheStore:
    """
    In-memory cache for prompt blocks. Tracks hits/misses and stores
    cached content by cache key.
    """

    def __init__(self):
        self._store: dict[str, str] = {}
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> str | None:
        """Retrieve cached content, tracking hit/miss."""
        if key in self._store:
            self._hits += 1
            return self._store[key]
        self._misses += 1
        return None

    def put(self, key: str, content: str) -> None:
        """Store content in cache."""
        self._store[key] = content

    def invalidate(self, scope: CacheScope | None = None) -> int:
        """
        Invalidate cached entries.

        Args:
            scope: If specified, only invalidate entries of this scope.

        Returns:
            Number of entries invalidated.
        """
        if scope is None:
            count = len(self._store)
            self._store.clear()
            return count

        keys_to_remove = [k for k in self._store if k.startswith(f"{scope.value}:")]
        for k in keys_to_remove:
            del self._store[k]
        return len(keys_to_remove)

    @property
    def stats(self) -> dict:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._store),
            "hit_rate": self._hits / max(self._hits + self._misses, 1)
        }
