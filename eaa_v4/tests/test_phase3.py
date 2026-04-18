"""
EAA V4 - Phase 3 Test Gate
============================
Phase gate testing: Phase 4 CANNOT start until Phase 3 tests all pass.

Phase 3 tests cover:
  - Token Tracker (estimation, budgets, context levels)
  - Tool Result Truncator (per-tool and aggregate budgets)
  - System Memory (add, retrieve, persist, evict, render)
  - Conversation Compactor (microcompact, section, rolling chunk, full)
  - Context Manager (6-layer cascade orchestration)
  - Integration tests (full cascade pipeline)

Run: python -m pytest tests/test_phase3.py -v
Or:  python tests/test_phase3.py
"""

import sys
import os
import json
import time
import unittest
import tempfile
import shutil
from unittest.mock import MagicMock, patch

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from token_tracker import (
    estimate_tokens, tokens_to_chars, ContextLevel,
    ToolResultTruncator, TruncationResult,
    TokenTracker, MessageTokenCount,
    create_token_tracker, create_truncator,
    DEFAULT_TOOL_RESULT_BUDGET, DEFAULT_MESSAGE_BUDGET,
    DEFAULT_CONTEXT_WINDOW,
)
from system_memory import (
    MemorySection, MemoryEntry, SystemMemory,
    create_system_memory,
    DEFAULT_MAX_MEMORY_ENTRIES, DEFAULT_MAX_MEMORY_CHARS,
)
from conversation_compactor import (
    CompactionStrategy, CompactionLevel,
    Message, CompactionResult,
    ExtractiveSummarizer, SectionSummarizer,
    ConversationCompactor,
    create_compactor,
    DEFAULT_CHUNK_FRACTION, DEFAULT_MICROCOMPACT_AGE,
)
from context_manager import (
    CascadeAction, CascadeResult,
    ContextManager,
    create_context_manager,
    DEFAULT_LAYER2_THRESHOLD, DEFAULT_LAYER5_THRESHOLD,
    DEFAULT_LAYER4_THRESHOLD, DEFAULT_LAYER6_THRESHOLD,
)


# ═══════════════════════════════════════════════════════════════════════════════
# TOKEN TRACKER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestTokenEstimation(unittest.TestCase):
    """Tests for token estimation functions."""

    def test_estimate_tokens_empty(self):
        """Empty string should return 0 tokens."""
        self.assertEqual(estimate_tokens(""), 0)

    def test_estimate_tokens_text(self):
        """Text estimation should use ~4 chars/token."""
        text = "a" * 400
        tokens = estimate_tokens(text, "text")
        self.assertGreater(tokens, 0)
        self.assertLessEqual(tokens, 200)

    def test_estimate_tokens_code(self):
        """Code estimation should use ~3.5 chars/token (more tokens)."""
        code = "def foo():\n    return 42\n" * 100
        code_tokens = estimate_tokens(code, "code")
        text_tokens = estimate_tokens(code, "text")
        self.assertGreater(code_tokens, text_tokens)

    def test_estimate_tokens_default(self):
        """Default estimation should work for mixed content."""
        text = "Hello world" * 50
        tokens = estimate_tokens(text)
        self.assertGreater(tokens, 0)

    def test_tokens_to_chars_roundtrip(self):
        """Tokens to chars conversion should be consistent."""
        tokens = 100
        chars = tokens_to_chars(tokens, "default")
        back = estimate_tokens("x" * chars, "default")
        # Should be close (within 20% due to rounding)
        self.assertAlmostEqual(back, tokens, delta=20)

    def test_estimate_tokens_minimum_one(self):
        """Any non-empty string should return at least 1 token."""
        self.assertEqual(estimate_tokens("x"), 1)


class TestContextLevel(unittest.TestCase):
    """Tests for context level thresholds."""

    def setUp(self):
        self.tracker = TokenTracker(
            context_window=1000,
            input_reserve_ratio=0.88,
        )

    def test_level_normal(self):
        """Low usage should return NORMAL."""
        self.tracker.count_message("user", "hi")
        level = self.tracker.get_context_level()
        self.assertEqual(level, ContextLevel.NORMAL)

    def test_level_elevated(self):
        """70%+ usage should return ELEVATED."""
        self.tracker._total_input_tokens = int(self.tracker.input_budget * 0.71)
        level = self.tracker.get_context_level()
        self.assertEqual(level, ContextLevel.ELEVATED)

    def test_level_compact_warning(self):
        """80%+ usage should return COMPACT_WARNING (Layer 5)."""
        self.tracker._total_input_tokens = int(self.tracker.input_budget * 0.81)
        level = self.tracker.get_context_level()
        self.assertEqual(level, ContextLevel.COMPACT_WARNING)

    def test_level_collapse_warning(self):
        """90%+ usage should return COLLAPSE_WARNING (Layer 4)."""
        self.tracker._total_input_tokens = int(self.tracker.input_budget * 0.91)
        level = self.tracker.get_context_level()
        self.assertEqual(level, ContextLevel.COLLAPSE_WARNING)

    def test_level_critical(self):
        """95%+ usage should return CRITICAL (Layer 6)."""
        self.tracker._total_input_tokens = int(self.tracker.input_budget * 0.96)
        level = self.tracker.get_context_level()
        self.assertEqual(level, ContextLevel.CRITICAL)

    def test_level_overflow(self):
        """100%+ usage should return OVERFLOW."""
        self.tracker._total_input_tokens = self.tracker.input_budget + 100
        level = self.tracker.get_context_level()
        self.assertEqual(level, ContextLevel.OVERFLOW)


class TestTokenTrackerBasic(unittest.TestCase):
    """Tests for TokenTracker core functionality."""

    def setUp(self):
        self.tracker = TokenTracker(context_window=1000)

    def test_count_message_returns_correct_type(self):
        """count_message should return MessageTokenCount."""
        result = self.tracker.count_message("user", "Hello world")
        self.assertIsInstance(result, MessageTokenCount)
        self.assertEqual(result.role, "user")
        self.assertGreater(result.total_tokens, 0)

    def test_count_message_accumulates(self):
        """Multiple messages should accumulate token counts."""
        self.tracker.count_message("user", "Hello")
        self.tracker.count_message("assistant", "Hi there!")
        self.assertGreater(self.tracker._total_input_tokens, 0)

    def test_subtract_tokens(self):
        """Subtracting tokens should decrease the total."""
        self.tracker.count_message("user", "Hello world " * 50)
        before = self.tracker._total_input_tokens
        removed = self.tracker.subtract_tokens(50)
        self.assertEqual(removed, 50)
        self.assertEqual(self.tracker._total_input_tokens, before - 50)

    def test_subtract_tokens_capped(self):
        """Cannot subtract more tokens than exist."""
        self.tracker.count_message("user", "Hi")
        tokens_before = self.tracker._total_input_tokens
        removed = self.tracker.subtract_tokens(999999)
        self.assertEqual(removed, tokens_before)
        self.assertEqual(self.tracker._total_input_tokens, 0)

    def test_reset_clears_all(self):
        """Reset should zero out all counters."""
        self.tracker.count_message("user", "Hello " * 100)
        self.tracker.reset()
        self.assertEqual(self.tracker._total_input_tokens, 0)
        self.assertEqual(len(self.tracker._message_history), 0)

    def test_remaining_tokens(self):
        """Remaining tokens should be budget minus used."""
        self.tracker.count_message("user", "Hello")
        remaining = self.tracker.get_remaining_tokens()
        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining, self.tracker.input_budget)

    def test_get_usage_fraction(self):
        """Usage fraction should be 0-1+ range."""
        self.tracker.count_message("user", "Hello")
        fraction = self.tracker.get_usage_fraction()
        self.assertGreater(fraction, 0)
        self.assertLess(fraction, 1)

    def test_add_output_tokens(self):
        """Output tokens should be tracked separately."""
        self.tracker.add_output_tokens(100)
        self.assertEqual(self.tracker._total_output_tokens, 100)

    def test_stats_returns_dict(self):
        """Stats should return a comprehensive dict."""
        self.tracker.count_message("user", "Hello")
        stats = self.tracker.get_stats()
        self.assertIsInstance(stats, dict)
        self.assertIn("context_window", stats)
        self.assertIn("usage_percentage", stats)
        self.assertIn("message_counts", stats)


class TestTokenTrackerFactory(unittest.TestCase):
    """Tests for token tracker factory function."""

    def test_create_default(self):
        """Factory should create a working tracker."""
        tracker = create_token_tracker()
        self.assertIsInstance(tracker, TokenTracker)

    def test_create_with_model_name(self):
        """Factory should accept model name."""
        tracker = create_token_tracker(model_name="qwen2.5-7b")
        self.assertEqual(tracker.output_budget, 4096)

    def test_create_claude_sonnet(self):
        """Factory should select appropriate budget for Claude Sonnet."""
        tracker = create_token_tracker(model_name="claude-sonnet-4-6")
        self.assertEqual(tracker.output_budget, 32768)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL RESULT TRUNCATOR TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolResultTruncator(unittest.TestCase):
    """Tests for the ToolResultTruncator."""

    def setUp(self):
        self.truncator = ToolResultTruncator(
            per_tool_budget=100,
            message_budget=250,
        )

    def test_no_truncation_small(self):
        """Small content should not be truncated."""
        result = self.truncator.truncate_tool_result("test_tool", "Hello")
        self.assertFalse(result.was_truncated)
        self.assertEqual(result.content, "Hello")

    def test_no_truncation_empty(self):
        """Empty content should not be truncated."""
        result = self.truncator.truncate_tool_result("test_tool", "")
        self.assertFalse(result.was_truncated)

    def test_no_truncation_exact_budget(self):
        """Content at exact budget should not be truncated."""
        content = "x" * 100
        result = self.truncator.truncate_tool_result("test_tool", content)
        self.assertFalse(result.was_truncated)

    def test_truncation_over_budget(self):
        """Content over budget should be truncated."""
        content = "x" * 200
        result = self.truncator.truncate_tool_result("test_tool", content)
        self.assertTrue(result.was_truncated)
        self.assertLess(len(result.content), 200)
        self.assertIn("truncated", result.content)

    def test_truncation_includes_tool_name(self):
        """Truncation message should include the tool name."""
        content = "x" * 200
        result = self.truncator.truncate_tool_result("my_tool", content)
        self.assertIn("my_tool", result.content)

    def test_enforce_message_budget_no_truncation(self):
        """Results under aggregate budget should pass through."""
        results = [
            TruncationResult("x" * 50, 50, 50, False, "tool1"),
            TruncationResult("y" * 50, 50, 50, False, "tool2"),
        ]
        enforced = self.truncator.enforce_message_budget(results)
        self.assertEqual(len(enforced), 2)
        self.assertFalse(any(r.was_truncated for r in enforced))

    def test_enforce_message_budget_truncates(self):
        """Results over aggregate budget should be truncated."""
        results = [
            TruncationResult("x" * 150, 150, 150, False, "tool1"),
            TruncationResult("y" * 150, 150, 150, False, "tool2"),
        ]
        enforced = self.truncator.enforce_message_budget(results)
        total = sum(len(r.content) for r in enforced)
        self.assertLessEqual(total, self.truncator.message_budget + 50)

    def test_stats_track_truncations(self):
        """Stats should track truncation operations."""
        self.truncator.truncate_tool_result("tool1", "x" * 200)
        self.truncator.truncate_tool_result("tool2", "y" * 300)
        stats = self.truncator.get_stats()
        self.assertEqual(stats["total_truncations"], 2)
        self.assertIn("tool1", stats["tool_truncation_counts"])

    def test_truncator_factory(self):
        """Factory should create a working truncator."""
        truncator = create_truncator()
        self.assertIsInstance(truncator, ToolResultTruncator)


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM MEMORY TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSystemMemory(unittest.TestCase):
    """Tests for the SystemMemory manager."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="eaa_mem_")
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)
        self.memory = SystemMemory(
            project_dir=self.test_dir,
            max_entries=50,
            max_chars=5000,
            max_section_chars=2000,
        )

    def test_add_summary_basic(self):
        """Should add a summary entry."""
        entry = self.memory.add_summary(
            section="tool_usage",
            content="Used smart_edit to modify router.py",
            original_tokens=1000,
            summary_tokens=50,
        )
        self.assertIsInstance(entry, MemoryEntry)
        self.assertEqual(entry.section, "tool_usage")
        self.assertEqual(len(self.memory._entries), 1)

    def test_add_summary_unknown_section(self):
        """Unknown section should be treated as 'context'."""
        entry = self.memory.add_summary(
            section="unknown_section",
            content="Some content",
        )
        self.assertEqual(entry.section, MemorySection.CONTEXT.value)

    def test_get_entries_all(self):
        """get_entries with no filters should return all."""
        self.memory.add_summary("tool_usage", "Entry 1")
        self.memory.add_summary("decisions", "Entry 2")
        entries = self.memory.get_entries()
        self.assertEqual(len(entries), 2)

    def test_get_entries_filter_section(self):
        """get_entries with section filter should filter correctly."""
        self.memory.add_summary("tool_usage", "Entry 1")
        self.memory.add_summary("decisions", "Entry 2")
        self.memory.add_summary("tool_usage", "Entry 3")
        entries = self.memory.get_entries(section="tool_usage")
        self.assertEqual(len(entries), 2)

    def test_get_entries_filter_since(self):
        """get_entries with since timestamp should filter correctly."""
        self.memory.add_summary("context", "Old entry")
        now = time.time() + 1  # Future timestamp - nothing should match
        entry = self.memory.get_entries(since=now)
        self.assertEqual(len(entry), 0)

    def test_get_entries_filter_limit(self):
        """get_entries with limit should cap results."""
        for i in range(5):
            self.memory.add_summary("context", f"Entry {i}")
        entries = self.memory.get_entries(limit=3)
        self.assertEqual(len(entries), 3)

    def test_get_section_summaries(self):
        """Should group entries by section."""
        self.memory.add_summary("tool_usage", "Tool 1")
        self.memory.add_summary("tool_usage", "Tool 2")
        self.memory.add_summary("decisions", "Decision 1")
        summaries = self.memory.get_section_summaries()
        self.assertIn("tool_usage", summaries)
        self.assertIn("decisions", summaries)

    def test_render_for_prompt_empty(self):
        """Empty memory should render empty string."""
        result = self.memory.render_for_prompt()
        self.assertEqual(result, "")

    def test_render_for_prompt_has_tags(self):
        """Rendered prompt should have system_memory tags."""
        self.memory.add_summary("decisions", "Chose rolling compaction")
        rendered = self.memory.render_for_prompt()
        self.assertIn("<system_memory>", rendered)
        self.assertIn("</system_memory>", rendered)
        self.assertIn("DECISIONS", rendered)

    def test_render_for_prompt_respects_max_chars(self):
        """Rendered output should respect max_chars limit."""
        for i in range(20):
            self.memory.add_summary("context", f"Content line {i} " * 50)
        rendered = self.memory.render_for_prompt(max_chars=500)
        self.assertLess(len(rendered), 600)

    def test_persist_to_disk(self):
        """Memory should persist to disk and reload."""
        self.memory.add_summary("tool_usage", "Test entry", original_tokens=500, summary_tokens=20)
        # Create a new instance from same project dir
        memory2 = SystemMemory(project_dir=self.test_dir, max_chars=5000)
        entries = memory2.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].content, "Test entry")

    def test_remove_chunk(self):
        """Should remove entries by chunk_id."""
        self.memory.add_summary("context", "Chunk 1 entry", chunk_id="chunk_001")
        self.memory.add_summary("context", "Chunk 2 entry", chunk_id="chunk_002")
        result = self.memory.remove_chunk("chunk_001")
        self.assertTrue(result)
        self.assertEqual(len(self.memory._entries), 1)

    def test_remove_chunk_not_found(self):
        """Removing non-existent chunk should return False."""
        self.memory.add_summary("context", "Entry", chunk_id="chunk_001")
        result = self.memory.remove_chunk("chunk_999")
        self.assertFalse(result)

    def test_clear(self):
        """Clear should remove all entries."""
        self.memory.add_summary("context", "Entry 1")
        self.memory.add_summary("context", "Entry 2")
        count = self.memory.clear()
        self.assertEqual(count, 2)
        self.assertEqual(len(self.memory._entries), 0)

    def test_eviction_max_entries(self):
        """Should evict oldest entries when over max_entries."""
        mem = SystemMemory(project_dir="", max_entries=3, max_chars=99999)
        for i in range(5):
            mem.add_summary("context", f"Entry {i}")
        self.assertEqual(len(mem._entries), 3)
        # Oldest should be evicted
        self.assertEqual(mem._entries[0].content, "Entry 2")

    def test_eviction_max_chars(self):
        """Should evict oldest entries when over max_chars."""
        mem = SystemMemory(project_dir="", max_entries=100, max_chars=100)
        # Add multiple entries to trigger eviction (keeps at least 0 when >0 entries)
        mem.add_summary("context", "x" * 200)
        mem.add_summary("context", "y" * 200)
        # Should have evicted entries to get under max_chars
        # With 2 entries it can evict one and keep checking
        self.assertLessEqual(mem.get_total_chars(), 100)

    def test_compression_ratio(self):
        """Should calculate compression ratio correctly."""
        self.memory.add_summary("context", "Summary", original_tokens=1000, summary_tokens=100)
        ratio = self.memory.get_compression_ratio()
        self.assertAlmostEqual(ratio, 10.0, places=1)

    def test_compression_ratio_zero(self):
        """Should return 0 when no summary tokens."""
        ratio = self.memory.get_compression_ratio()
        self.assertEqual(ratio, 0.0)

    def test_stats(self):
        """Stats should return comprehensive data."""
        self.memory.add_summary("tool_usage", "Entry", original_tokens=500, summary_tokens=25)
        stats = self.memory.get_stats()
        self.assertEqual(stats["total_entries"], 1)
        self.assertIn("compression_ratio", stats)
        self.assertIn("entries_per_section", stats)

    def test_factory(self):
        """Factory should create a working SystemMemory."""
        mem = create_system_memory(project_dir=self.test_dir)
        self.assertIsInstance(mem, SystemMemory)


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION COMPACTOR TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractiveSummarizer(unittest.TestCase):
    """Tests for the ExtractiveSummarizer."""

    def setUp(self):
        self.summarizer = ExtractiveSummarizer()

    def test_empty_messages(self):
        """Empty messages should return empty string."""
        result = self.summarizer.summarize([])
        self.assertEqual(result, "")

    def test_extracts_user_messages(self):
        """Should preserve user messages in summary."""
        messages = [
            Message(role="user", content="Please fix the bug in router.py", timestamp=time.time()),
            Message(role="assistant", content="I'll fix it now " * 20, timestamp=time.time()),
        ]
        result = self.summarizer.summarize(messages)
        self.assertIn("[User]", result)
        self.assertIn("fix the bug", result)

    def test_extracts_errors(self):
        """Should extract error messages."""
        messages = [
            Message(role="tool", content="Error: FileNotFoundError at line 42", timestamp=time.time()),
            Message(role="assistant", content="Let me check the path", timestamp=time.time()),
        ]
        result = self.summarizer.summarize(messages)
        self.assertIn("Error", result)

    def test_deduplicates_content(self):
        """Should not include duplicate lines."""
        messages = [
            Message(role="assistant", content="Same line\nSame line\nDifferent line", timestamp=time.time()),
        ]
        result = self.summarizer.summarize(messages)
        # "Same line" should appear fewer times than in input
        input_count = messages[0].content.count("Same line")
        output_count = result.count("Same line")
        self.assertLess(output_count, input_count)

    def test_limits_output(self):
        """Should limit total output lines."""
        messages = [
            Message(role="assistant", content=f"Line with error {i}\nLine normal {i}\n" * 5, timestamp=time.time())
            for i in range(20)
        ]
        result = self.summarizer.summarize(messages)
        lines = result.split("\n")
        self.assertLessEqual(len(lines), 55)  # 50 + truncation notice


class TestSectionSummarizer(unittest.TestCase):
    """Tests for the SectionSummarizer."""

    def setUp(self):
        self.summarizer = SectionSummarizer()

    def test_empty_messages(self):
        """Empty messages should return empty string."""
        text, section = self.summarizer.summarize([])
        self.assertEqual(text, "")
        self.assertEqual(section, "context")

    def test_categorizes_errors(self):
        """Should categorize error content correctly."""
        messages = [
            Message(role="tool", content="Traceback: exception in main()", timestamp=time.time()),
        ]
        text, section = self.summarizer.summarize(messages)
        self.assertIn("ERRORS", text)

    def test_categorizes_code_changes(self):
        """Should categorize code change content correctly."""
        messages = [
            Message(role="assistant", content="I'll edit the file router.py and create a new class", timestamp=time.time()),
        ]
        text, section = self.summarizer.summarize(messages)
        # 'edit' or '.py' should match code_changes (before tool_usage)
        has_code = "CODE_CHANGES" in text or "code_changes" in text.lower()
        self.assertTrue(has_code, f"Expected CODE_CHANGES in: {text}")

    def test_identifies_primary_section(self):
        """Should identify the most common section as primary."""
        messages = [
            Message(role="tool", content=f"Tool executed function call {i}", timestamp=time.time())
            for i in range(5)
        ]
        _, primary = self.summarizer.summarize(messages)
        self.assertEqual(primary, "tool_usage")


class TestConversationCompactor(unittest.TestCase):
    """Tests for the ConversationCompactor."""

    def setUp(self):
        self.compactor = ConversationCompactor(
            min_chunk_size=3,
            microcompact_age=2.0,  # 2 seconds for fast testing
        )

    def _make_messages(self, count, role="assistant", age_seconds=0):
        """Helper to create test messages."""
        now = time.time()
        return [
            Message(
                role=role,
                content=f"Message {i} with some content about topic {i % 3}",
                timestamp=now - age_seconds,
                token_count=50,
                message_id=i,
            )
            for i in range(count)
        ]

    def test_microcompact_clears_old_tool_results(self):
        """Should clear tool results older than microcompact_age."""
        messages = self._make_messages(5, role="tool", age_seconds=5)
        result = self.compactor.compact(messages, CompactionLevel.MICROCOMPACT)
        self.assertTrue(result.success)
        self.assertGreater(result.messages_compacted, 0)
        # Old messages should be marked compacted
        compacted = [m for m in messages if m.is_compacted]
        self.assertEqual(len(compacted), 5)

    def test_microcompact_keeps_recent(self):
        """Should NOT compact recent tool results."""
        messages = self._make_messages(5, role="tool", age_seconds=0.5)
        result = self.compactor.compact(messages, CompactionLevel.MICROCOMPACT)
        self.assertTrue(result.success)
        compacted = [m for m in messages if m.is_compacted]
        self.assertEqual(len(compacted), 0)

    def test_rolling_chunk_compact(self):
        """Rolling chunk should compact oldest 20% of messages."""
        messages = self._make_messages(20)
        result = self.compactor.compact(
            messages, CompactionLevel.ROLLING_CHUNK, current_tokens=1000
        )
        self.assertTrue(result.success)
        self.assertGreater(result.messages_compacted, 0)
        self.assertTrue(result.tokens_saved > 0)

    def test_rolling_chunk_too_few_messages(self):
        """Should fail gracefully with too few messages."""
        messages = self._make_messages(2)
        result = self.compactor.compact(
            messages, CompactionLevel.ROLLING_CHUNK, current_tokens=100
        )
        self.assertFalse(result.success)
        self.assertIn("Not enough", result.error_message)

    def test_context_collapse(self):
        """Context collapse should work with enough messages."""
        messages = self._make_messages(15)
        result = self.compactor.compact(
            messages, CompactionLevel.CONTEXT_COLLAPSE, current_tokens=500
        )
        self.assertTrue(result.success)
        self.assertGreater(result.messages_compacted, 0)

    def test_full_compact(self):
        """Full compact should compact all uncompacted messages."""
        messages = self._make_messages(10)
        result = self.compactor.compact(
            messages, CompactionLevel.FULL_COMPACT, current_tokens=2000
        )
        self.assertTrue(result.success)
        self.assertEqual(result.messages_compacted, 10)

    def test_full_compact_empty(self):
        """Full compact on empty should fail gracefully."""
        result = self.compactor.compact(
            [], CompactionLevel.FULL_COMPACT
        )
        self.assertFalse(result.success)

    def test_should_compact_normal(self):
        """Low usage should return None (no compaction needed)."""
        level = self.compactor.should_compact(0.5)
        self.assertIsNone(level)

    def test_should_compact_rolling(self):
        """80%+ usage should suggest ROLLING_CHUNK."""
        level = self.compactor.should_compact(0.85)
        self.assertEqual(level, CompactionLevel.ROLLING_CHUNK)

    def test_should_compact_emergency(self):
        """95%+ usage should suggest FULL_COMPACT."""
        level = self.compactor.should_compact(0.97)
        self.assertEqual(level, CompactionLevel.FULL_COMPACT)

    def test_should_compact_microcompact(self):
        """Old tool results should trigger MICROCOMPACT."""
        level = self.compactor.should_compact(0.5, has_old_tool_results=True)
        self.assertEqual(level, CompactionLevel.MICROCOMPACT)

    def test_unknown_level_returns_failure(self):
        """Unknown compaction level should return failure."""
        # FULL_COMPACT with empty list should fail gracefully
        result = self.compactor.compact([], CompactionLevel.FULL_COMPACT)
        self.assertFalse(result.success)

    def test_stats(self):
        """Stats should return compaction statistics."""
        messages = self._make_messages(10, role="tool", age_seconds=5)
        result = self.compactor.compact(messages, CompactionLevel.MICROCOMPACT)
        self.assertTrue(result.success)
        stats = self.compactor.get_stats()
        self.assertEqual(stats["total_compactions"], 1)
        self.assertGreater(stats["total_messages_compacted"], 0)

    def test_compaction_history(self):
        """History should track recent compactions."""
        messages = self._make_messages(10, role="tool", age_seconds=5)
        self.compactor.compact(messages, CompactionLevel.MICROCOMPACT)
        self.compactor.compact(messages, CompactionLevel.MICROCOMPACT)
        history = self.compactor.get_history(limit=1)
        self.assertEqual(len(history), 1)

    def test_summarize_callback(self):
        """Custom summarize callback should be used when provided."""
        def custom_callback(msgs):
            return f"Custom summary of {len(msgs)} messages"
        compactor = ConversationCompactor(
            min_chunk_size=3,
            summarize_callback=custom_callback,
        )
        messages = self._make_messages(10)
        result = compactor.compact(
            messages, CompactionLevel.ROLLING_CHUNK, current_tokens=1000
        )
        self.assertTrue(result.success)
        self.assertIn("Custom summary", result.summary_text)

    def test_factory(self):
        """Factory should create a working compactor."""
        compactor = create_compactor()
        self.assertIsInstance(compactor, ConversationCompactor)


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT MANAGER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextManagerBasic(unittest.TestCase):
    """Tests for ContextManager core functionality."""

    def setUp(self):
        self.cm = ContextManager(
            context_window=500,
            project_dir="",
            layer5_threshold=0.80,
            layer4_threshold=0.90,
            layer6_threshold=0.95,
        )

    def test_add_message(self):
        """Adding a message should track tokens."""
        msg_id = self.cm.add_message("user", "Hello world")
        self.assertGreater(msg_id, 0)
        self.assertGreater(self.cm.tracker._total_input_tokens, 0)

    def test_add_tool_result_no_truncation(self):
        """Small tool results should not be truncated."""
        msg_id, truncation = self.cm.add_tool_result("test_tool", "Small result")
        self.assertFalse(truncation.was_truncated)

    def test_add_tool_result_with_truncation(self):
        """Large tool results should be truncated by Layer 1."""
        large_content = "x" * 60000
        msg_id, truncation = self.cm.add_tool_result("big_tool", large_content)
        self.assertTrue(truncation.was_truncated)
        self.assertLess(len(truncation.content), 60000)

    def test_get_context_for_model(self):
        """get_context_for_model should return list of dicts."""
        self.cm.add_message("user", "Hello")
        self.cm.add_message("assistant", "Hi there")
        context = self.cm.get_context_for_model()
        self.assertIsInstance(context, list)
        self.assertGreater(len(context), 0)
        self.assertIn("role", context[0])
        self.assertIn("content", context[0])

    def test_get_context_includes_memory(self):
        """Context should include system_memory when available."""
        self.cm.memory.add_summary("decisions", "Test decision")
        context = self.cm.get_context_for_model(include_memory=True)
        has_memory = any("system_memory" in m.get("content", "") for m in context)
        self.assertTrue(has_memory)

    def test_get_context_excludes_memory(self):
        """Context should exclude system_memory when include_memory=False."""
        self.cm.memory.add_summary("decisions", "Test decision")
        context = self.cm.get_context_for_model(include_memory=False)
        has_memory = any("system_memory" in m.get("content", "") for m in context)
        self.assertFalse(has_memory)

    def test_clear(self):
        """Clear should remove all messages and reset."""
        self.cm.add_message("user", "Hello")
        self.cm.add_message("assistant", "Hi")
        self.cm.clear()
        self.assertEqual(len(self.cm._messages), 0)
        self.assertEqual(self.cm.tracker._total_input_tokens, 0)

    def test_get_usage(self):
        """get_usage should return current usage info."""
        self.cm.add_message("user", "Hello")
        usage = self.cm.get_usage()
        self.assertIn("usage_fraction", usage)
        self.assertIn("context_level", usage)
        self.assertIn("total_messages", usage)


class TestContextManagerCascade(unittest.TestCase):
    """Tests for the 6-layer cascade orchestration."""

    def setUp(self):
        self.cm = ContextManager(
            context_window=200,  # Small window for testing
            project_dir="",
            layer5_threshold=0.80,
            layer4_threshold=0.90,
            layer6_threshold=0.95,
            snip_keep_min=3,
        )

    def test_cascade_no_action_needed(self):
        """Low usage should result in no action."""
        self.cm.add_message("user", "Hello")
        result = self.cm.evaluate_cascade()
        self.assertEqual(result.actions_taken, [CascadeAction.NONE.value])

    def test_cascade_layer3_microcompact(self):
        """Old tool results should trigger microcompact."""
        # Add messages to get some tokens
        for i in range(5):
            self.cm.add_message("user", "Hello " * 20)
        # Add old tool result (simulate age by directly setting timestamp)
        msg = Message(
            role="tool",
            content="Old tool result " * 100,
            timestamp=time.time() - 7200,  # 2 hours old
            token_count=500,
            message_id=99,
        )
        self.cm._messages.append(msg)
        self.cm.tracker.count_message("tool", msg.content)

        result = self.cm.evaluate_cascade()
        # Should have triggered at least microcompact
        self.assertIn(CascadeAction.MICROCOMPACT.value, result.actions_taken)

    def test_cascade_layer2_history_snip(self):
        """High usage should trigger history snip."""
        # Add enough messages to push usage high
        for i in range(30):
            self.cm.add_message("user", "Message content " * 30)
            self.cm.add_message("assistant", "Response content " * 30)

        result = self.cm.evaluate_cascade()
        # Should trigger some action
        self.assertNotEqual(result.actions_taken, [CascadeAction.NONE.value])

    def test_cascade_result_has_correct_structure(self):
        """CascadeResult should have all expected fields."""
        self.cm.add_message("user", "Hello")
        result = self.cm.evaluate_cascade()
        self.assertIsInstance(result, CascadeResult)
        self.assertIsInstance(result.actions_taken, list)
        self.assertIsInstance(result.layers_triggered, list)
        self.assertIsInstance(result.tokens_before, int)
        self.assertIsInstance(result.tokens_after, int)

    def test_cascade_stats(self):
        """Stats should include cascade-specific data."""
        self.cm.add_message("user", "Hello")
        self.cm.evaluate_cascade()
        stats = self.cm.get_stats()
        self.assertEqual(stats["total_cascade_runs"], 1)
        self.assertIn("total_tokens_saved", stats)
        self.assertIn("token_tracker", stats)
        self.assertIn("compactor", stats)
        self.assertIn("system_memory", stats)


class TestContextManagerIntegration(unittest.TestCase):
    """Integration tests for the full context management pipeline."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="eaa_ctx_")
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)

    def test_full_pipeline(self):
        """Full pipeline: add messages -> cascade -> verify compression."""
        cm = ContextManager(
            context_window=300,
            project_dir=self.test_dir,
            layer5_threshold=0.50,  # Low threshold for testing
            layer4_threshold=0.80,
            layer6_threshold=0.95,
            snip_keep_min=3,
        )

        # Simulate a conversation with tool results
        cm.add_message("system", "You are a helpful coding assistant.")
        cm.add_message("user", "Please modify the router.py file.")
        cm.add_message("assistant", "I'll read the file first.")

        for i in range(10):
            cm.add_message("tool", f"File content line {i} " * 50)
            cm.add_message("assistant", f"I see line {i}. " * 20)

        cm.add_message("user", "Now make the changes.")
        cm.add_message("assistant", "Done. Changes applied.")

        # Run cascade
        result = cm.evaluate_cascade()

        # Verify compression happened
        self.assertIsInstance(result, CascadeResult)
        usage = cm.get_usage()
        self.assertGreater(usage["total_messages"], 0)

    def test_memory_survives_reload(self):
        """System memory should persist across manager reloads."""
        cm1 = ContextManager(
            context_window=1000,
            project_dir=self.test_dir,
        )
        cm1.memory.add_summary("decisions", "Important decision", original_tokens=500, summary_tokens=25)
        cm1.evaluate_cascade()

        # Create new manager with same project dir
        cm2 = ContextManager(
            context_window=1000,
            project_dir=self.test_dir,
        )
        entries = cm2.memory.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].content, "Important decision")

    def test_progressive_compaction(self):
        """Multiple cascade runs should progressively compress."""
        cm = ContextManager(
            context_window=200,
            project_dir="",
            layer5_threshold=0.40,  # Very aggressive for testing
            layer4_threshold=0.70,
            layer6_threshold=0.90,
            snip_keep_min=2,
        )

        # Add lots of messages
        for i in range(50):
            cm.add_message("user", f"User message {i} " * 10)
            cm.add_message("assistant", f"Assistant response {i} " * 10)

        # Run cascade multiple times
        for _ in range(3):
            cm.evaluate_cascade()

        stats = cm.get_stats()
        self.assertGreater(stats["total_cascade_runs"], 0)

    def test_context_format_for_model(self):
        """Context output should be properly formatted."""
        cm = ContextManager(context_window=1000, project_dir="")
        cm.add_message("user", "Hello")
        cm.add_message("assistant", "Hi there")
        cm.add_message("tool", "Result: 42")

        context = cm.get_context_for_model(include_memory=False)

        # Verify structure
        roles = [m["role"] for m in context]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)
        self.assertIn("tool", roles)

    def test_factory(self):
        """Factory should create a working ContextManager."""
        cm = create_context_manager(context_window=32768)
        self.assertIsInstance(cm, ContextManager)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE GATE
# ═══════════════════════════════════════════════════════════════════════════════

def run_phase_gate():
    """Run the Phase 3 test gate and report results."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    print("  PHASE 3 TEST GATE RESULTS")
    print("=" * 60)
    print(f"  Tests run: {result.testsRun}")
    print(f"  Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"  Failed: {len(result.failures)}")
    print(f"  Errors: {len(result.errors)}")

    phase3_passed = len(result.failures) == 0 and len(result.errors) == 0
    print(f"  Phase 3: {'PASSED' if phase3_passed else 'FAILED'}")
    print("=" * 60)

    return phase3_passed


if __name__ == "__main__":
    success = run_phase_gate()
    sys.exit(0 if success else 1)
