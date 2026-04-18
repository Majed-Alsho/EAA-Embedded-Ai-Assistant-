"""
EAA V4 - Context Manager
=========================
6-layer context management cascade with rolling chunk compaction.

From the blueprint (Section 8.1):
  "Claude Code implements a 6-layer context management cascade that
   progressively compresses conversation history to fit within the
   model's context window."

This is the central orchestrator that ties together:
  - token_tracker.py (Layers 1, budget tracking)
  - conversation_compactor.py (Layers 2-6, all compaction strategies)
  - system_memory.py (summary storage, persistence)

The 6-Layer Cascade (adapted for local models):

  Layer 1: Tool Result Truncation
    Trigger: Per-tool result > 50K chars
    Action: Truncate to 50K per tool, 200K per message aggregate
    Token Impact: Immediate reduction

  Layer 2: History Snip
    Trigger: Context > 70%, periodic
    Action: Remove oldest messages below importance threshold
    Token Impact: Moderate reduction

  Layer 3: Microcompact
    Trigger: Every turn, tool results > 60 min old
    Action: Clear old tool results, replace with placeholder
    Token Impact: Gradual cleanup

  Layer 4: Context Collapse
    Trigger: ~90% full
    Action: Summarize each conversation section independently
    Token Impact: Significant reduction

  Layer 5: Session Memory Compact (Rolling Chunk)
    Trigger: ~80% full (preemptive)
    Action: Summarize oldest 20% of uncompacted messages
    Token Impact: Preemptive reduction

  Layer 6: Rolling Chunk Compact (Emergency)
    Trigger: ~95% full or overflow
    Action: Summarize ALL uncompacted messages
    Token Impact: Maximum reduction

HMoE Adaptation (Section 8.3):
  Layers 5/6 use Rolling Chunk Compaction instead of Claude Code's
  Full Auto-Compact. This prevents OOM on local GPU by only processing
  a small fraction of the conversation per step (~5x less VRAM).
"""

import os
import time
import logging
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum

from token_tracker import (
    TokenTracker, ToolResultTruncator, TruncationResult,
    ContextLevel, estimate_tokens, create_token_tracker,
)
from conversation_compactor import (
    ConversationCompactor, CompactionLevel, CompactionResult,
    CompactionStrategy, Message, create_compactor,
)
from system_memory import (
    SystemMemory, MemorySection, MemoryEntry, create_system_memory,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# CASCADE ACTION TYPES
# ═══════════════════════════════════════════════════════════════════════════════

class CascadeAction(Enum):
    """Actions taken by the cascade."""
    NONE = "none"                       # No action needed
    TRUNCATE_TOOL = "truncate_tool"     # Layer 1: Truncate tool result
    TRUNCATE_MESSAGE = "truncate_message"  # Layer 1: Message budget
    SNIP_HISTORY = "snip_history"       # Layer 2: Remove old messages
    MICROCOMPACT = "microcompact"       # Layer 3: Clear old tool results
    CONTEXT_COLLAPSE = "context_collapse"  # Layer 4: Section summaries
    ROLLING_CHUNK = "rolling_chunk"     # Layer 5: Rolling 20% compact
    EMERGENCY_COMPACT = "emergency_compact"  # Layer 6: Full compact


@dataclass
class CascadeResult:
    """Result of a cascade evaluation pass."""
    actions_taken: List[str]
    layers_triggered: List[int]
    messages_removed: int
    messages_compacted: int
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    compaction_results: List[CompactionResult]
    truncation_results: List[TruncationResult]
    context_level_before: str
    context_level_after: str

    def to_dict(self) -> Dict:
        return {
            "actions_taken": self.actions_taken,
            "layers_triggered": self.layers_triggered,
            "messages_removed": self.messages_removed,
            "messages_compacted": self.messages_compacted,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_saved": self.tokens_saved,
            "context_level_before": self.context_level_before,
            "context_level_after": self.context_level_after,
            "compaction_count": len(self.compaction_results),
            "truncation_count": len(self.truncation_results),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

# Default thresholds
DEFAULT_LAYER2_THRESHOLD = 0.70        # History snip at 70%
DEFAULT_LAYER5_THRESHOLD = 0.80        # Rolling chunk at 80%
DEFAULT_LAYER4_THRESHOLD = 0.90        # Context collapse at 90%
DEFAULT_LAYER6_THRESHOLD = 0.95        # Emergency at 95%
DEFAULT_SNIP_KEEP_MIN = 10             # Always keep at least 10 messages
DEFAULT_SNIP_KEEP_SYSTEM = True        # Never snip system messages


class ContextManager:
    """
    Central context management orchestrator implementing the 6-layer cascade.

    From the blueprint (Section 8.1):
      "This system is critical for maintaining long-running coding sessions
       without losing important context or crashing due to token limits."

    The ContextManager coordinates all three subsystems:
      - TokenTracker: Monitors context usage, enforces tool result budgets
      - ConversationCompactor: Performs actual message compaction
      - SystemMemory: Stores and persists compressed summaries

    Usage:
        cm = ContextManager(context_window=32768, project_dir="/project")
        cm.add_message("user", "Hello, please modify router.py")
        cm.add_message("assistant", "I'll modify the router...")
        cm.add_tool_result("smart_edit", result_content, 50000)
        result = cm.evaluate_cascade()
        context = cm.get_context_for_model()
    """

    def __init__(
        self,
        context_window: int = 32768,
        project_dir: str = "",
        summarize_callback: Optional[Callable] = None,
        layer2_threshold: float = DEFAULT_LAYER2_THRESHOLD,
        layer5_threshold: float = DEFAULT_LAYER5_THRESHOLD,
        layer4_threshold: float = DEFAULT_LAYER4_THRESHOLD,
        layer6_threshold: float = DEFAULT_LAYER6_THRESHOLD,
        snip_keep_min: int = DEFAULT_SNIP_KEEP_MIN,
    ):
        # Core subsystems
        self.tracker = create_token_tracker(context_window=context_window)
        self.truncator = ToolResultTruncator()
        self.compactor = create_compactor(
            summarize_callback=summarize_callback,
        )
        self.memory = create_system_memory(
            project_dir=project_dir,
        )

        # Thresholds
        self.layer2_threshold = layer2_threshold
        self.layer5_threshold = layer5_threshold
        self.layer4_threshold = layer4_threshold
        self.layer6_threshold = layer6_threshold
        self.snip_keep_min = snip_keep_min

        # Message store
        self._messages: List[Message] = []
        self._message_counter = 0
        self._system_prompt_tokens = 0

        # Cascade history
        self._cascade_history: List[CascadeResult] = []
        self._total_cascade_runs = 0

        # Stats
        self._total_tokens_saved = 0

        logger.info(
            f"[ContextManager] Initialized: window={context_window}, "
            f"L2={layer2_threshold}, L5={layer5_threshold}, "
            f"L4={layer4_threshold}, L6={layer6_threshold}"
        )

    def add_message(
        self,
        role: str,
        content: str,
        content_type: str = "default",
    ) -> int:
        """
        Add a message to the conversation and track its tokens.

        Args:
            role: Message role (user, assistant, system, tool)
            content: Message content
            content_type: "code", "text", or "default" for token estimation

        Returns:
            Message ID (position in conversation)
        """
        self._message_counter += 1
        token_count = estimate_tokens(content, content_type)

        msg = Message(
            role=role,
            content=content,
            timestamp=time.time(),
            token_count=token_count,
            message_id=self._message_counter,
        )

        self._messages.append(msg)

        # Track tokens
        count = self.tracker.count_message(role, content, content_type)

        return self._message_counter

    def add_tool_result(
        self,
        tool_name: str,
        content: str,
        content_type: str = "default",
    ) -> Tuple[int, TruncationResult]:
        """
        Add a tool result with automatic Layer 1 truncation.

        From Claude Code (Section 8.1, Layer 1):
          "Per-tool result > 50K chars -> Truncate to 50K per tool"

        Args:
            tool_name: Name of the tool
            content: Tool output content
            content_type: Content type for token estimation

        Returns:
            (message_id, truncation_result)
        """
        # Layer 1: Per-tool truncation
        truncation = self.truncator.truncate_tool_result(tool_name, content)
        truncated_content = truncation.content

        msg_id = self.add_message("tool", truncated_content, content_type)

        return msg_id, truncation

    def set_system_prompt_tokens(self, token_count: int) -> None:
        """Set the system prompt token overhead."""
        self._system_prompt_tokens = token_count

    def get_context_for_model(self, include_memory: bool = True) -> List[Dict]:
        """
        Get the current context formatted for model input.

        Returns messages in the format expected by the model:
          [{"role": "system/user/assistant/tool", "content": "..."}]

        Optionally prepends the system_memory block.

        Args:
            include_memory: Whether to include system_memory summary

        Returns:
            List of message dicts ready for the model
        """
        messages = []

        # Prepend system memory if available
        if include_memory:
            memory_block = self.memory.render_for_prompt()
            if memory_block:
                messages.append({
                    "role": "system",
                    "content": memory_block,
                })

        # Add active (non-fully-compacted) messages
        for msg in self._messages:
            if msg.is_compacted and not msg.content:
                continue  # Skip fully cleared messages
            messages.append({
                "role": msg.role,
                "content": msg.content,
            })

        return messages

    def evaluate_cascade(self) -> CascadeResult:
        """
        Run the full 6-layer cascade evaluation.

        Evaluates context usage and applies appropriate compaction
        layers from lowest to highest severity.

        Returns:
            CascadeResult with detailed action log
        """
        self._total_cascade_runs += 1
        tokens_before = self.tracker._total_input_tokens
        level_before = self.tracker.get_context_level().value

        actions = []
        layers = []
        compaction_results = []
        truncation_results = []
        messages_removed = 0
        messages_compacted = 0

        # ── Layer 1: Tool Result Truncation ──
        # Already applied at add_tool_result() time
        # But check aggregate message budget
        tool_messages = [
            m for m in self._messages
            if m.role == "tool" and not m.is_compacted
        ]
        if tool_messages:
            tool_results = [
                TruncationResult(
                    content=m.content,
                    original_length=len(m.content),
                    truncated_length=len(m.content),
                    was_truncated=False,
                    tool_name="tool",
                )
                for m in tool_messages
            ]
            enforced = self.truncator.enforce_message_budget(tool_results)
            if any(r.was_truncated for r in enforced):
                actions.append(CascadeAction.TRUNCATE_MESSAGE.value)
                layers.append(1)
                truncation_results.extend([r for r in enforced if r.was_truncated])

        # ── Get current usage ──
        usage = self.tracker.get_usage_fraction()

        # ── Layer 2: History Snip ──
        if usage >= self.layer2_threshold:
            snipped = self._layer2_history_snip()
            if snipped > 0:
                actions.append(CascadeAction.SNIP_HISTORY.value)
                layers.append(2)
                messages_removed += snipped
                usage = self.tracker.get_usage_fraction()

        # ── Layer 3: Microcompact ──
        # Only run if there are old tool results (check before calling)
        has_old_tools = any(
            m.role == "tool" and not m.is_compacted
            and (time.time() - m.timestamp > self.compactor.microcompact_age)
            for m in self._messages
        )
        if has_old_tools:
            result_micro = self._layer3_microcompact()
            if result_micro.success:
                actions.append(CascadeAction.MICROCOMPACT.value)
                layers.append(3)
                compaction_results.append(result_micro)
                messages_compacted += result_micro.messages_compacted
                # Update tracker
                saved = result_micro.tokens_saved
                self.tracker.subtract_tokens(saved)
                usage = self.tracker.get_usage_fraction()

        # ── Layer 5: Rolling Chunk (triggers at 80%, BEFORE Layer 4) ──
        if usage >= self.layer5_threshold:
            result_chunk = self._layer5_rolling_chunk()
            if result_chunk.success:
                actions.append(CascadeAction.ROLLING_CHUNK.value)
                layers.append(5)
                compaction_results.append(result_chunk)
                messages_compacted += result_chunk.messages_compacted

                # Store summary in system memory
                self._store_compaction_summary(result_chunk)

                # Update tracker
                self.tracker.subtract_tokens(result_chunk.original_tokens)
                self.tracker.count_message(
                    "system", result_chunk.summary_text, "text"
                )
                usage = self.tracker.get_usage_fraction()

        # ── Layer 4: Context Collapse (at 90%) ──
        if usage >= self.layer4_threshold:
            result_collapse = self._layer4_context_collapse()
            if result_collapse.success:
                actions.append(CascadeAction.CONTEXT_COLLAPSE.value)
                layers.append(4)
                compaction_results.append(result_collapse)
                messages_compacted += result_collapse.messages_compacted

                self._store_compaction_summary(result_collapse)

                self.tracker.subtract_tokens(result_collapse.original_tokens)
                self.tracker.count_message(
                    "system", result_collapse.summary_text, "text"
                )
                usage = self.tracker.get_usage_fraction()

        # ── Layer 6: Emergency Compact (at 95%) ──
        if usage >= self.layer6_threshold:
            result_emergency = self._layer6_emergency()
            if result_emergency.success:
                actions.append(CascadeAction.EMERGENCY_COMPACT.value)
                layers.append(6)
                compaction_results.append(result_emergency)
                messages_compacted += result_emergency.messages_compacted

                self._store_compaction_summary(result_emergency)

                self.tracker.subtract_tokens(result_emergency.original_tokens)
                self.tracker.count_message(
                    "system", result_emergency.summary_text, "text"
                )
                usage = self.tracker.get_usage_fraction()

        tokens_after = self.tracker._total_input_tokens
        tokens_saved = max(0, tokens_before - tokens_after)
        self._total_tokens_saved += tokens_saved
        level_after = self.tracker.get_context_level().value

        if not actions:
            actions.append(CascadeAction.NONE.value)

        result = CascadeResult(
            actions_taken=actions,
            layers_triggered=layers,
            messages_removed=messages_removed,
            messages_compacted=messages_compacted,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            tokens_saved=tokens_saved,
            compaction_results=compaction_results,
            truncation_results=truncation_results,
            context_level_before=level_before,
            context_level_after=level_after,
        )

        self._cascade_history.append(result)

        if layers:
            logger.info(
                f"[ContextManager] Cascade run #{self._total_cascade_runs}: "
                f"layers={layers}, saved={tokens_saved} tokens, "
                f"{level_before} -> {level_after}"
            )

        return result

    # ── Layer Implementations ──

    def _layer2_history_snip(self) -> int:
        """
        Layer 2: History Snip.

        Remove oldest messages below importance threshold.
        Always keeps: system messages, last N messages, messages < 1 min old.
        """
        if len(self._messages) <= self.snip_keep_min:
            return 0

        now = time.time()
        snipped = 0
        to_remove = []

        for i, msg in enumerate(self._messages):
            # Never remove system messages
            if msg.role == "system":
                continue

            # Never remove recent messages (keep last snip_keep_min)
            if i >= len(self._messages) - self.snip_keep_min:
                continue

            # Never remove very recent messages (< 60s)
            if now - msg.timestamp < 60:
                continue

            # Remove old, low-importance messages
            if msg.role == "tool" and msg.is_compacted:
                to_remove.append(i)
            elif msg.role == "assistant" and msg.is_compacted:
                to_remove.append(i)

        # Remove from end to preserve indices
        for i in sorted(to_remove, reverse=True):
            removed_msg = self._messages.pop(i)
            self.tracker.subtract_tokens(removed_msg.token_count)
            snipped += 1

        return snipped

    def _layer3_microcompact(self) -> CompactionResult:
        """Layer 3: Clear old tool results (>60 min)."""
        return self.compactor.compact(
            self._messages,
            CompactionLevel.MICROCOMPACT,
            self.tracker._total_input_tokens,
        )

    def _layer4_context_collapse(self) -> CompactionResult:
        """Layer 4: Per-section summarization."""
        return self.compactor.compact(
            self._messages,
            CompactionLevel.CONTEXT_COLLAPSE,
            self.tracker._total_input_tokens,
        )

    def _layer5_rolling_chunk(self) -> CompactionResult:
        """Layer 5: Rolling 20% chunk compaction."""
        return self.compactor.compact(
            self._messages,
            CompactionLevel.ROLLING_CHUNK,
            self.tracker._total_input_tokens,
        )

    def _layer6_emergency(self) -> CompactionResult:
        """Layer 6: Emergency full compaction."""
        return self.compactor.compact(
            self._messages,
            CompactionLevel.FULL_COMPACT,
            self.tracker._total_input_tokens,
        )

    def _store_compaction_summary(self, result: CompactionResult) -> None:
        """Store a compaction result's summary in system memory."""
        if not result.summary_text:
            return

        # Determine section from strategy
        section_map = {
            CompactionStrategy.EXTRACTIVE.value: MemorySection.CONTEXT.value,
            CompactionStrategy.SECTION_BASED.value: MemorySection.CONTEXT.value,
            CompactionStrategy.HYBRID.value: MemorySection.TASK_SUMMARY.value,
            CompactionStrategy.ABRSTRACTIVE.value: MemorySection.TASK_SUMMARY.value,
            CompactionStrategy.TRUNCATION.value: MemorySection.CONTEXT.value,
        }

        section = section_map.get(result.strategy, MemorySection.CONTEXT.value)

        # Calculate message range
        msg_range = (0, 0)
        compacted_msgs = [
            m for m in self._messages if m.compacted_hash == result.chunk_id
        ]
        if compacted_msgs:
            msg_range = (
                compacted_msgs[0].message_id,
                compacted_msgs[-1].message_id,
            )

        self.memory.add_summary(
            section=section,
            content=result.summary_text,
            original_tokens=result.original_tokens,
            summary_tokens=result.summary_tokens,
            chunk_id=result.chunk_id,
            message_range=msg_range,
        )

    def get_usage(self) -> Dict:
        """Get current context usage information."""
        return {
            "usage_fraction": self.tracker.get_usage_fraction(),
            "usage_percentage": self.tracker.get_usage_percentage(),
            "context_level": self.tracker.get_context_level().value,
            "remaining_tokens": self.tracker.get_remaining_tokens(),
            "total_messages": len(self._messages),
            "compacted_messages": sum(1 for m in self._messages if m.is_compacted),
            "active_messages": sum(1 for m in self._messages if not m.is_compacted),
            "memory_entries": len(self.memory._entries),
            "system_prompt_tokens": self._system_prompt_tokens,
        }

    def get_messages(self) -> List[Message]:
        """Get all messages (including compacted)."""
        return list(self._messages)

    def clear(self) -> None:
        """Clear all messages and reset tracker."""
        self._messages.clear()
        self._message_counter = 0
        self.tracker.reset()
        logger.info("[ContextManager] Cleared all messages")

    def get_stats(self) -> Dict:
        """Return comprehensive context management statistics."""
        return {
            "total_cascade_runs": self._total_cascade_runs,
            "total_tokens_saved": self._total_tokens_saved,
            "total_messages_processed": self._message_counter,
            "current_usage": self.get_usage(),
            "token_tracker": self.tracker.get_stats(),
            "truncator": self.truncator.get_stats(),
            "compactor": self.compactor.get_stats(),
            "system_memory": self.memory.get_stats(),
            "cascade_history_length": len(self._cascade_history),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY
# ═══════════════════════════════════════════════════════════════════════════════

def create_context_manager(
    context_window: int = 32768,
    project_dir: str = "",
    model_name: str = "qwen2.5-7b",
    summarize_callback: Optional[Callable] = None,
) -> ContextManager:
    """
    Factory function for creating a ContextManager.

    Args:
        context_window: Model's context window size in tokens
        project_dir: Project directory for system memory persistence
        model_name: Model identifier for default selection
        summarize_callback: Optional model-based summarization function

    Returns:
        Fully configured ContextManager instance
    """
    return ContextManager(
        context_window=context_window,
        project_dir=project_dir,
        summarize_callback=summarize_callback,
    )
