"""
EAA V4 - Error Handler (Phase 6, Component 1)
==============================================
3-tier max_output_tokens recovery cascade + JSONDecodeError intercept.

From the blueprint (Section 3.1):
  When a worker model hits max_output_tokens, output gets truncated mid-JSON.
  This handler implements a 3-tier cascade:
    Tier 1: Double the max_output_tokens and retry
    Tier 2: Inject a continuation prompt to resume generation
    Tier 3: Abort with structured error (escalate to Master)

From Amendment 5 (Section 3.1.5):
  JSONDecodeError Intercept — catch JSON parse failures on tool results,
  wrap as is_error: true following Claude Code's error signalling pattern.

The ErrorHandler integrates with ContextManager for emergency prompt compaction
when the prompt itself is too long (prompt_too_long API error).
"""

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# RECOVERY TYPES
# ═══════════════════════════════════════════════════════════════════════════════

class RecoveryAction(Enum):
    """Actions available in the recovery cascade."""
    DOUBLE_TOKENS = "double_tokens"          # Tier 1: Double max_output_tokens
    INJECT_CONTINUATION = "inject_continuation"  # Tier 2: Append continuation prompt
    ABORT = "abort"                          # Tier 3: Give up, escalate to Master


@dataclass
class RecoveryResult:
    """
    Result of a recovery attempt.

    Attributes:
        action: The recovery action taken.
        content: The (possibly modified) content to use for retry.
        tier_reached: Which tier of the cascade was reached (1-3).
        should_retry: Whether the caller should retry with the returned content.
        error: Optional error message if recovery failed.
    """
    action: RecoveryAction
    content: str
    tier_reached: int
    should_retry: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "content": self.content[:200] + "..." if len(self.content) > 200 else self.content,
            "tier_reached": self.tier_reached,
            "should_retry": self.should_retry,
            "error": self.error,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ERROR HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

# Import for type annotation only — avoids hard dependency at runtime.
try:
    from context_manager import ContextManager as _ContextManager
except ImportError:
    _ContextManager = None  # type: ignore[assignment,misc]


class ErrorHandler:
    """
    Handles output truncation and JSON decode errors from worker models.

    The 3-tier recovery cascade:
      Tier 1 (DOUBLE_TOKENS):
        When finish_reason == "length" (max_output_tokens hit), double the
        token budget and return the truncated output for a retry.
      Tier 2 (INJECT_CONTINUATION):
        If tier 1 was already tried (tier counter > 0), inject a
        continuation prompt so the model can resume where it left off.
      Tier 3 (ABORT):
        If both tiers exhausted, return a structured error wrapped as
        is_error: true for the Master to handle.

    The handler also provides:
      - Emergency prompt compaction via ContextManager for prompt_too_long
      - JSONDecodeError interception with automatic tier increment
      - Claude Code-style is_error: true wrapping

    Usage:
        handler = ErrorHandler(context_manager=cm)
        result = handler.handle_truncation(output, "length")
        if result.should_retry:
            # Retry with doubled tokens
            retry(messages, max_tokens=handler.default_max_tokens * 2)
    """

    def __init__(self, context_manager=None):
        """
        Args:
            context_manager: Optional ContextManager instance for emergency
                             prompt compaction. If None, prompt-too-long
                             errors are returned as-is.
        """
        self.context_manager = context_manager
        self.tier = 0
        self.max_tiers = 3
        self.default_max_tokens = 2048

        logger.debug(
            f"[ErrorHandler] Initialized: max_tiers={self.max_tiers}, "
            f"default_max_tokens={self.default_max_tokens}"
        )

    def handle_truncation(self, truncated_output: str, finish_reason: str) -> RecoveryResult:
        """
        3-tier cascade for handling truncated output.

        Triggered when the model's finish_reason is "length", indicating
        max_output_tokens was reached and output was cut off mid-stream.

        Tier 1: DOUBLE_TOKENS — double the token budget, suggest retry.
        Tier 2: INJECT_CONTINUATION — append a continuation suffix so the
                model can pick up where it left off.
        Tier 3: ABORT — all recovery exhausted, escalate to Master.

        Args:
            truncated_output: The incomplete output from the model.
            finish_reason: The API finish_reason (e.g., "length", "stop").

        Returns:
            RecoveryResult with the recommended action and retry content.
        """
        self.tier += 1

        # If finish_reason is "stop", output is complete — no recovery needed.
        if finish_reason != "length":
            self.tier = 0
            return RecoveryResult(
                action=RecoveryAction.ABORT,
                content=truncated_output,
                tier_reached=0,
                should_retry=False,
            )

        logger.info(
            f"[ErrorHandler] Truncation detected (finish_reason=length), "
            f"attempting recovery at tier {self.tier}/{self.max_tiers}"
        )

        # ── Tier 1: Double max_output_tokens ──
        if self.tier == 1:
            new_tokens = self.default_max_tokens * 2
            logger.info(
                f"[ErrorHandler] Tier 1: Doubling max_output_tokens to {new_tokens}"
            )
            return RecoveryResult(
                action=RecoveryAction.DOUBLE_TOKENS,
                content=truncated_output,
                tier_reached=1,
                should_retry=True,
            )

        # ── Tier 2: Inject continuation prompt ──
        if self.tier == 2:
            continuation_prompt = (
                "\n\n[CONTINUATION REQUIRED] The previous output was truncated. "
                "Please continue from exactly where you left off, completing "
                "any incomplete JSON, code blocks, or text."
            )
            combined = truncated_output + continuation_prompt
            logger.info(
                f"[ErrorHandler] Tier 2: Injecting continuation prompt "
                f"(content length: {len(combined)})"
            )
            return RecoveryResult(
                action=RecoveryAction.INJECT_CONTINUATION,
                content=combined,
                tier_reached=2,
                should_retry=True,
            )

        # ── Tier 3: Abort and escalate ──
        logger.warning(
            f"[ErrorHandler] Tier 3: Recovery exhausted after {self.tier} attempts. "
            f"Escalating to Master."
        )
        return RecoveryResult(
            action=RecoveryAction.ABORT,
            content=truncated_output,
            tier_reached=3,
            should_retry=False,
            error=(
                f"Output truncation could not be resolved after {self.max_tiers} "
                f"recovery attempts. Output length: {len(truncated_output)} chars. "
                f"Escalating to Master for handling."
            ),
        )

    def handle_prompt_too_long(self, messages: list) -> list:
        """
        Emergency compaction for prompt-too-long API errors.

        When the prompt exceeds the model's context window, this method
        delegates to the ContextManager's compaction cascade to reduce
        message count and token usage.

        If no ContextManager is available, falls back to simple truncation:
        keeps only the system prompt and the last 3 messages.

        Args:
            messages: List of message dicts [{"role": ..., "content": ...}].

        Returns:
            Compacted message list, or a minimally truncated list as fallback.
        """
        logger.warning(
            f"[ErrorHandler] Prompt too long detected "
            f"({len(messages)} messages). Attempting compaction."
        )

        if self.context_manager is not None:
            try:
                # Run the full 6-layer cascade
                cascade_result = self.context_manager.evaluate_cascade()
                compacted = self.context_manager.get_context_for_model()
                logger.info(
                    f"[ErrorHandler] ContextManager compaction: "
                    f"{cascade_result.tokens_saved} tokens saved, "
                    f"{len(compacted)} messages remaining"
                )
                return compacted
            except Exception as e:
                logger.error(
                    f"[ErrorHandler] ContextManager compaction failed: {e}. "
                    f"Falling back to manual truncation."
                )

        # Fallback: keep system messages + last 3 messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        kept = non_system[-3:] if len(non_system) > 3 else non_system
        result = system_msgs + kept

        logger.info(
            f"[ErrorHandler] Manual truncation: "
            f"{len(messages)} -> {len(result)} messages"
        )
        return result

    def wrap_error_as_tool_result(self, error, tool_name: str) -> dict:
        """
        Wrap an error as a Claude Code-style tool result with is_error: true.

        From Claude Code's error signalling pattern:
          When a tool fails, the result includes is_error: true so the
          model knows to interpret the content as an error message and
          attempt recovery or inform the user.

        Args:
            error: The error (Exception instance or string).
            tool_name: Name of the tool that failed.

        Returns:
            Dict with role="tool", is_error=True, and formatted content.
        """
        error_str = str(error) if error else "Unknown error"
        content = f"[is_error: true] {tool_name}: {error_str}"
        logger.debug(
            f"[ErrorHandler] Wrapped error as tool result: "
            f"tool={tool_name}, error={error_str[:100]}"
        )
        return {
            "role": "tool",
            "content": content,
            "is_error": True,
        }

    def intercept_json_decode(self, raw_output: str, tool_name: str) -> dict:
        """
        Catch JSONDecodeError and wrap as is_error: true.

        [Amendment 5, Section 3.1.5]:
          When a worker model produces malformed JSON (e.g., truncated tool
          call arguments), instead of crashing, intercept the parse error
          and return it as a structured is_error: true result.

        Also increments the tier counter so that repeated JSON failures
          contribute to the overall recovery budget.

        Args:
            raw_output: The raw string output to parse as JSON.
            tool_name: Name of the tool whose output is being parsed.

        Returns:
            Parsed JSON dict if valid, or an is_error: true tool result dict.
        """
        try:
            parsed = json.loads(raw_output)
            return parsed
        except json.JSONDecodeError as e:
            self.tier += 1
            truncated = raw_output[:200] + "..." if len(raw_output) > 200 else raw_output
            logger.warning(
                f"[ErrorHandler] JSONDecodeError intercepted for '{tool_name}': "
                f"{e}. Tier incremented to {self.tier}. "
                f"Raw output (truncated): {truncated}"
            )
            return self.wrap_error_as_tool_result(
                f"JSON parse error: {e}. Raw output: {truncated}",
                tool_name,
            )

    def reset_tier(self):
        """
        Reset the recovery tier counter to zero.

        Should be called when a new task begins or after a successful
        recovery to allow the full cascade for subsequent errors.
        """
        old_tier = self.tier
        self.tier = 0
        logger.debug(
            f"[ErrorHandler] Tier reset: {old_tier} -> 0"
        )

    def get_current_max_tokens(self) -> int:
        """
        Get the current effective max_output_tokens based on recovery tier.

        Returns:
            Token count: default_max_tokens * 2^(tier-1) for active tiers.
        """
        if self.tier == 0:
            return self.default_max_tokens
        multiplier = 2 ** min(self.tier, self.max_tiers)
        return self.default_max_tokens * multiplier

    def is_exhausted(self) -> bool:
        """
        Check whether all recovery tiers have been exhausted.

        Returns:
            True if tier >= max_tiers, False otherwise.
        """
        return self.tier >= self.max_tiers


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_error_handler(context_manager=None) -> ErrorHandler:
    """
    Create an ErrorHandler with optional ContextManager for emergency compaction.

    Args:
        context_manager: Optional ContextManager instance.

    Returns:
        Configured ErrorHandler instance.
    """
    return ErrorHandler(context_manager=context_manager)


__all__ = [
    "RecoveryAction",
    "RecoveryResult",
    "ErrorHandler",
    "create_error_handler",
]
