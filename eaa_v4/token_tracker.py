"""
EAA V4 - Token Tracker
======================
Per-message token counting and budget enforcement.

From the blueprint (Section 8.1):
  Layer 1: "Tool Result Truncation - Per-tool result > 50K chars,
           truncate to 50K per tool, 200K per message aggregate"

Also tracks context window usage for the 6-layer cascade triggers
(Section 8.3: Rolling Chunk Compaction triggers at 80%).

Architecture:
  - Character-based estimation (4 chars ≈ 1 token for English/code)
  - Per-tool result budget: 50,000 characters
  - Per-message aggregate budget: 200,000 characters
  - Context window threshold tracking (80% and 90% for Layers 5/4)
  - Stats tracking for VRAM-aware operations
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TOKEN ESTIMATION
# ═══════════════════════════════════════════════════════════════════════════════

# Approximate chars-per-token ratios for different content types
CHARS_PER_TOKEN_CODE = 3.5      # Code is more token-dense
CHARS_PER_TOKEN_TEXT = 4.0      # Natural language
CHARS_PER_TOKEN_DEFAULT = 3.8   # Mixed content

# Budget limits from Claude Code (Section 8.1)
DEFAULT_TOOL_RESULT_BUDGET = 50_000      # 50K chars per tool result
DEFAULT_MESSAGE_BUDGET = 200_000         # 200K chars per message aggregate
DEFAULT_CONTEXT_WINDOW = 32_000          # 32K tokens for Qwen2.5-7B
DEFAULT_OUTPUT_BUDGET = 4_096            # Conservative output budget


def estimate_tokens(text: str, content_type: str = "default") -> int:
    """
    Estimate token count from text using character ratios.

    For local models without a proper tokenizer, we use character-based
    estimation. This is intentionally conservative (over-estimates) to
    prevent context overflow.

    Args:
        text: The text to estimate tokens for
        content_type: "code", "text", or "default"

    Returns:
        Estimated token count (always rounds up)
    """
    if not text:
        return 0

    ratios = {
        "code": CHARS_PER_TOKEN_CODE,
        "text": CHARS_PER_TOKEN_TEXT,
        "default": CHARS_PER_TOKEN_DEFAULT,
    }
    ratio = ratios.get(content_type, CHARS_PER_TOKEN_DEFAULT)
    return max(1, int(len(text) / ratio))


def tokens_to_chars(token_count: int, content_type: str = "default") -> int:
    """Convert estimated token count back to character count."""
    ratios = {
        "code": CHARS_PER_TOKEN_CODE,
        "text": CHARS_PER_TOKEN_TEXT,
        "default": CHARS_PER_TOKEN_DEFAULT,
    }
    ratio = ratios.get(content_type, CHARS_PER_TOKEN_DEFAULT)
    return int(token_count * ratio)


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT THRESHOLD LEVELS
# ═══════════════════════════════════════════════════════════════════════════════

class ContextLevel(Enum):
    """Context window usage levels that trigger different cascade actions."""
    NORMAL = "normal"               # < 70% - no action needed
    ELEVATED = "elevated"           # 70-80% - start watching
    COMPACT_WARNING = "compact_warning"  # 80% - Layer 5 trigger (Session Memory)
    COLLAPSE_WARNING = "collapse_warning"  # 90% - Layer 4 trigger (Context Collapse)
    CRITICAL = "critical"           # 95% - Layer 6 trigger (Rolling Chunk Compact)
    OVERFLOW = "overflow"           # > 100% - emergency truncation


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL RESULT TRUNCATOR
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TruncationResult:
    """Result of a truncation operation."""
    content: str
    original_length: int
    truncated_length: int
    was_truncated: bool
    tool_name: str = ""
    truncation_reason: str = ""


class ToolResultTruncator:
    """
    Enforces per-tool and per-message budget limits on tool results.

    From Claude Code's Layer 1 (Section 8.1):
      "Truncate to 50K per tool, 200K per message aggregate"

    This ensures that no single tool result can dominate the context
    window, and that the total tool output per turn stays manageable.
    """

    def __init__(
        self,
        per_tool_budget: int = DEFAULT_TOOL_RESULT_BUDGET,
        message_budget: int = DEFAULT_MESSAGE_BUDGET,
    ):
        self.per_tool_budget = per_tool_budget
        self.message_budget = message_budget

        # Stats
        self._total_truncations = 0
        self._total_chars_truncated = 0
        self._tool_truncation_counts: Dict[str, int] = {}

    def truncate_tool_result(self, tool_name: str, content: str) -> TruncationResult:
        """
        Truncate a single tool result if it exceeds the per-tool budget.

        Args:
            tool_name: Name of the tool that produced the result
            content: The tool output content

        Returns:
            TruncationResult with potentially truncated content
        """
        if not content or len(content) <= self.per_tool_budget:
            return TruncationResult(
                content=content or "",
                original_length=len(content or ""),
                truncated_length=len(content or ""),
                was_truncated=False,
                tool_name=tool_name,
            )

        truncated = content[:self.per_tool_budget]
        truncation_msg = (
            f"\n\n... [Result truncated: {len(content)} -> "
            f"{self.per_tool_budget} chars ({tool_name})]"
        )
        final = truncated + truncation_msg

        self._total_truncations += 1
        self._total_chars_truncated += len(content) - len(final)
        self._tool_truncation_counts[tool_name] = (
            self._tool_truncation_counts.get(tool_name, 0) + 1
        )

        logger.info(
            f"[TokenTracker] Truncated {tool_name}: "
            f"{len(content)} -> {len(final)} chars"
        )

        return TruncationResult(
            content=final,
            original_length=len(content),
            truncated_length=len(final),
            was_truncated=True,
            tool_name=tool_name,
            truncation_reason="per_tool_budget_exceeded",
        )

    def enforce_message_budget(
        self, results: List[TruncationResult]
    ) -> List[TruncationResult]:
        """
        Enforce aggregate message budget across multiple tool results.

        If the total size of all results exceeds the message budget,
        proportionally truncate the largest results first.

        Args:
            results: List of TruncationResult objects

        Returns:
            Updated list with aggregate budget enforced
        """
        total_size = sum(len(r.content) for r in results)
        if total_size <= self.message_budget:
            return results

        # Sort by size descending - truncate largest first
        sorted_results = sorted(
            results, key=lambda r: len(r.content), reverse=True
        )

        remaining_budget = self.message_budget
        updated = []
        for result in sorted_results:
            if len(result.content) <= remaining_budget:
                updated.append(result)
                remaining_budget -= len(result.content)
            else:
                # Proportionally truncate
                ratio = remaining_budget / max(len(result.content), 1)
                new_length = max(100, int(len(result.content) * ratio))
                truncated_content = result.content[:new_length]
                truncation_msg = f"\n\n... [Aggregate budget truncation]"
                final = truncated_content + truncation_msg

                updated.append(TruncationResult(
                    content=final,
                    original_length=result.original_length,
                    truncated_length=len(final),
                    was_truncated=True,
                    tool_name=result.tool_name,
                    truncation_reason="aggregate_message_budget_exceeded",
                ))

                self._total_truncations += 1
                self._total_chars_truncated += len(result.content) - len(final)
                remaining_budget = 0
                break

        return updated

    def get_stats(self) -> Dict:
        """Return truncation statistics."""
        return {
            "total_truncations": self._total_truncations,
            "total_chars_truncated": self._total_chars_truncated,
            "per_tool_budget": self.per_tool_budget,
            "message_budget": self.message_budget,
            "tool_truncation_counts": dict(self._tool_truncation_counts),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# MESSAGE TOKEN COUNTER
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MessageTokenCount:
    """Token count breakdown for a single message."""
    role: str                          # "user", "assistant", "system", "tool"
    content_tokens: int
    overhead_tokens: int               # Role markers, formatting overhead
    total_tokens: int
    char_count: int
    is_truncated: bool = False
    truncation_savings_tokens: int = 0


class TokenTracker:
    """
    Tracks token usage across the entire conversation.

    From the blueprint (Section 8.2):
      "The output token budget starts at 8,000 (to avoid over-reserving)
       and escalates to 64K on repeated hits."

    For local models with 32K context (Qwen2.5-7B), we use:
      - Input budget: ~28K tokens (leaving room for output)
      - Output budget: 4K tokens (conservative for 7B model)
      - Layer 5 trigger: 80% of context window
      - Layer 4 trigger: 90% of context window
      - Layer 6 trigger: 95% of context window
    """

    def __init__(
        self,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        output_budget: int = DEFAULT_OUTPUT_BUDGET,
        input_reserve_ratio: float = 0.88,  # 88% for input, 12% for output
    ):
        self.context_window = context_window
        self.output_budget = output_budget
        self.input_reserve_ratio = input_reserve_ratio

        # Effective input budget (context - output reserve)
        self.input_budget = int(context_window * input_reserve_ratio)

        # Thresholds as fractions of input budget
        self.layer5_threshold = 0.80   # Session Memory Compact
        self.layer4_threshold = 0.90   # Context Collapse
        self.layer6_threshold = 0.95   # Rolling Chunk Compact

        # Running totals
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._message_counts: Dict[str, int] = {}
        self._message_history: List[MessageTokenCount] = []

        logger.info(
            f"[TokenTracker] Initialized: context={context_window}, "
            f"input_budget={self.input_budget}, output_budget={output_budget}"
        )

    def count_message(
        self, role: str, content: str, content_type: str = "default"
    ) -> MessageTokenCount:
        """
        Count tokens for a single message and add to running total.

        Args:
            role: Message role (user, assistant, system, tool)
            content: Message content
            content_type: "code", "text", or "default"

        Returns:
            MessageTokenCount with detailed breakdown
        """
        content_tokens = estimate_tokens(content, content_type)
        overhead_tokens = estimate_tokens(f"[{role}]: ", "text")
        total = content_tokens + overhead_tokens

        count = MessageTokenCount(
            role=role,
            content_tokens=content_tokens,
            overhead_tokens=overhead_tokens,
            total_tokens=total,
            char_count=len(content),
        )

        self._total_input_tokens += total
        self._message_counts[role] = self._message_counts.get(role, 0) + 1
        self._message_history.append(count)

        return count

    def get_context_level(self) -> ContextLevel:
        """
        Determine current context usage level.

        Returns:
            ContextLevel indicating which cascade layer should trigger
        """
        usage = self._total_input_tokens / max(self.input_budget, 1)

        if usage >= 1.0:
            return ContextLevel.OVERFLOW
        elif usage >= self.layer6_threshold:
            return ContextLevel.CRITICAL
        elif usage >= self.layer4_threshold:
            return ContextLevel.COLLAPSE_WARNING
        elif usage >= self.layer5_threshold:
            return ContextLevel.COMPACT_WARNING
        elif usage >= 0.70:
            return ContextLevel.ELEVATED
        else:
            return ContextLevel.NORMAL

    def get_usage_fraction(self) -> float:
        """Get current context usage as a fraction (0.0 to 1.0+)."""
        return self._total_input_tokens / max(self.input_budget, 1)

    def get_usage_percentage(self) -> float:
        """Get current context usage as a percentage."""
        return self.get_usage_fraction() * 100

    def get_remaining_tokens(self) -> int:
        """Get remaining input tokens before hitting budget."""
        return max(0, self.input_budget - self._total_input_tokens)

    def add_output_tokens(self, count: int) -> None:
        """Record output tokens from the model."""
        self._total_output_tokens += count

    def subtract_tokens(self, count: int) -> int:
        """
        Subtract tokens (after compaction removes old messages).

        Returns:
            Actual tokens removed (capped at total)
        """
        removed = min(count, self._total_input_tokens)
        self._total_input_tokens -= removed
        return removed

    def reset(self) -> None:
        """Reset all counters (e.g., after full compaction)."""
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._message_counts.clear()
        self._message_history.clear()

    def get_stats(self) -> Dict:
        """Return comprehensive token statistics."""
        return {
            "context_window": self.context_window,
            "input_budget": self.input_budget,
            "output_budget": self.output_budget,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "usage_fraction": round(self.get_usage_fraction(), 4),
            "usage_percentage": round(self.get_usage_percentage(), 2),
            "remaining_tokens": self.get_remaining_tokens(),
            "context_level": self.get_context_level().value,
            "message_counts": dict(self._message_counts),
            "total_messages": sum(self._message_counts.values()),
            "layer5_trigger_tokens": int(self.input_budget * self.layer5_threshold),
            "layer4_trigger_tokens": int(self.input_budget * self.layer4_threshold),
            "layer6_trigger_tokens": int(self.input_budget * self.layer6_threshold),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY
# ═══════════════════════════════════════════════════════════════════════════════

def create_token_tracker(
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    model_name: str = "qwen2.5-7b",
) -> TokenTracker:
    """
    Factory function for creating a TokenTracker with model-specific defaults.

    Args:
        context_window: Model's context window size in tokens
        model_name: Model identifier for selecting defaults

    Returns:
        Configured TokenTracker instance
    """
    # Model-specific output budgets (Section 8.2)
    output_budgets = {
        "qwen2.5-7b": 4_096,
        "qwen2.5-7b-instruct": 4_096,
        "qwen2.5-coder-7b": 4_096,
        "qwen2.5-14b": 4_096,
        "qwen2.5-32b": 4_096,
        "claude-3-opus": 4_096,
        "claude-3.5-sonnet": 8_192,
        "claude-sonnet-4-6": 32_768,
        "claude-opus-4-6": 64_000,
    }

    output_budget = output_budgets.get(model_name, DEFAULT_OUTPUT_BUDGET)

    return TokenTracker(
        context_window=context_window,
        output_budget=output_budget,
    )


def create_truncator(
    per_tool_budget: int = DEFAULT_TOOL_RESULT_BUDGET,
    message_budget: int = DEFAULT_MESSAGE_BUDGET,
) -> ToolResultTruncator:
    """Factory function for creating a ToolResultTruncator."""
    return ToolResultTruncator(
        per_tool_budget=per_tool_budget,
        message_budget=message_budget,
    )
