"""
EAA V4 - Phase 2 Test Gate
============================
Phase gate testing: Phase 3 CANNOT start until Phase 2 tests all pass.

Phase 2 tests cover:
  - File State Manager (read-before-write, staleness, invalidation)
  - Smart Edit Engine (fuzzy matching, 3-layer normalization, atomic writes)
  - History Index (snapshot recording, lookup, garbage collection)
  - Rollback Manager (undo, multi-step undo, atomic restore)
  - Integration tests (full edit → backup → undo pipeline)

Run: python -m pytest tests/test_phase2.py -v
Or:  python tests/test_phase2.py
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

from file_state import (
    FileStateStatus, FileReadRecord, FileStateManager,
    create_file_state_manager,
)
from smart_edit import (
    EditErrorCode, EditResult, FuzzyMatchResult, FuzzyMatcher,
    SmartEditEngine, normalize_quotes, normalize_xml,
    strip_whitespace_blocks, compute_similarity, create_smart_edit,
)
from history_index import (
    SnapshotEntry, HistoryIndex, create_history_index,
)
from rollback import (
    RollbackResultStatus, RollbackResult, RollbackManager,
    create_rollback_manager,
)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

class TempDirTestCase(unittest.TestCase):
    """Base test class with a temporary directory."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="eaa_test_")
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)

    def _write_file(self, path: str, content: str) -> str:
        """Write a file and return its absolute path."""
        full_path = os.path.join(self.test_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return full_path

    def _read_file(self, path: str) -> str:
        """Read a file and return its content."""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


# ═══════════════════════════════════════════════════════════════════════════════
# FILE STATE MANAGER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileStateManager(TempDirTestCase):
    """Tests for the File State Manager."""

    def test_mark_read_creates_record(self):
        """Marking a file as read should create a FileReadRecord."""
        fsm = FileStateManager()
        path = self._write_file("test.py", "hello world\n")

        record = fsm.mark_read(path, "hello world\n")

        self.assertIsInstance(record, FileReadRecord)
        self.assertEqual(record.file_path, path)
        self.assertGreater(record.read_timestamp, 0)
        self.assertGreater(record.file_mtime, 0)
        self.assertEqual(record.file_size, os.path.getsize(path))
        self.assertNotEqual(record.content_hash, "")
        self.assertEqual(record.line_count, 1)

    def test_mark_read_file_not_found(self):
        """mark_read should raise FileNotFoundError for missing files."""
        fsm = FileStateManager()
        path = os.path.join(self.test_dir, "nonexistent.py")

        with self.assertRaises(FileNotFoundError):
            fsm.mark_read(path, "")

    def test_check_editable_current(self):
        """Freshly read file should be editable (CURRENT status)."""
        fsm = FileStateManager()
        path = self._write_file("test.py", "hello\n")

        fsm.mark_read(path, "hello\n")
        status, reason = fsm.check_editable(path)

        self.assertEqual(status, FileStateStatus.CURRENT)
        self.assertIn("up-to-date", reason)

    def test_check_editable_not_read(self):
        """Unread file should return NOT_READ."""
        fsm = FileStateManager()
        path = self._write_file("test.py", "hello\n")

        status, reason = fsm.check_editable(path)

        self.assertEqual(status, FileStateStatus.NOT_READ)

    def test_check_editable_stale(self):
        """File modified after read should be STALE."""
        fsm = FileStateManager()
        path = self._write_file("test.py", "original\n")

        fsm.mark_read(path, "original\n")

        # Modify the file externally
        time.sleep(0.01)  # Small delay for mtime difference
        with open(path, "w") as f:
            f.write("modified\n")
        # Force mtime update
        os.utime(path, (time.time(), time.time() + 1))

        status, reason = fsm.check_editable(path)

        self.assertEqual(status, FileStateStatus.STALE)
        self.assertIn("modified", reason)

    def test_check_editable_deleted(self):
        """Deleted file should return DELETED if previously read."""
        fsm = FileStateManager()
        path = self._write_file("test.py", "hello\n")

        fsm.mark_read(path, "hello\n")
        os.unlink(path)

        status, reason = fsm.check_editable(path)

        self.assertEqual(status, FileStateStatus.DELETED)

    def test_check_editable_file_not_found(self):
        """Non-existent file that was never read should return NOT_READ."""
        fsm = FileStateManager()
        path = os.path.join(self.test_dir, "nonexistent.py")

        status, _ = fsm.check_editable(path)

        self.assertEqual(status, FileStateStatus.NOT_READ)

    def test_mark_written_updates_state(self):
        """mark_written should reset the read state."""
        fsm = FileStateManager()
        path = self._write_file("test.py", "old\n")

        fsm.mark_read(path, "old\n")

        # Write new content
        with open(path, "w") as f:
            f.write("new content\n")

        fsm.mark_written(path, "new content\n")

        # Should now be editable (CURRENT)
        status, _ = fsm.check_editable(path)
        self.assertEqual(status, FileStateStatus.CURRENT)

    def test_invalidate_removes_entry(self):
        """invalidate should remove a file from cache."""
        fsm = FileStateManager()
        path = self._write_file("test.py", "hello\n")

        fsm.mark_read(path, "hello\n")
        self.assertTrue(fsm.is_read(path))

        fsm.invalidate(path)
        self.assertFalse(fsm.is_read(path))

    def test_invalidate_all_clears_cache(self):
        """invalidate_all should clear everything."""
        fsm = FileStateManager()
        path1 = self._write_file("a.py", "a\n")
        path2 = self._write_file("b.py", "b\n")

        fsm.mark_read(path1, "a\n")
        fsm.mark_read(path2, "b\n")

        fsm.invalidate_all()
        self.assertFalse(fsm.is_read(path1))
        self.assertFalse(fsm.is_read(path2))

    def test_stats_track_operations(self):
        """Stats should track reads, writes, rejects."""
        fsm = FileStateManager()
        path = self._write_file("test.py", "hello\n")

        fsm.mark_read(path, "hello\n")
        # check_editable on a path that doesn't exist in cache increments unread
        unread_path = self._write_file("unread.py", "content\n")
        fsm.check_editable(unread_path)  # File exists but not read

        stats = fsm.get_stats()
        self.assertEqual(stats["total_reads"], 1)
        self.assertGreaterEqual(stats["unread_rejects"], 1)

    def test_cache_eviction(self):
        """Cache should evict oldest entries when over limit."""
        fsm = FileStateManager(max_cache_entries=5)

        for i in range(10):
            path = self._write_file(f"file_{i}.py", f"content {i}\n")
            fsm.mark_read(path, f"content {i}\n")

        # Cache should be at most max_cache_entries * 1.25 (after eviction)
        self.assertLessEqual(len(fsm._cache), 8)


# ═══════════════════════════════════════════════════════════════════════════════
# STRING NORMALIZATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestStringNormalization(unittest.TestCase):
    """Tests for the three-layer string normalization."""

    def test_normalize_quotes_curly_to_straight(self):
        """Should convert curly quotes to straight quotes."""
        result = normalize_quotes("\u201chello\u201d \u201cworld\u201d")
        self.assertEqual(result, '"hello" "world"')

    def test_normalize_quotes_single(self):
        """Should convert curly single quotes."""
        result = normalize_quotes("\u2018hello\u2019")
        self.assertEqual(result, "'hello'")

    def test_normalize_quotes_no_change(self):
        """Should not change already-straight quotes."""
        result = normalize_quotes('"hello" \'world\'')
        self.assertEqual(result, '"hello" \'world\'')

    def test_normalize_xml_entities(self):
        """Should expand XML entities to characters."""
        result = normalize_xml("&lt;div&gt;hello &amp; world&lt;/div&gt;")
        self.assertEqual(result, "<div>hello & world</div>")

    def test_normalize_xml_quotes(self):
        """Should expand XML quote entities."""
        result = normalize_xml("&quot;hello&quot; &apos;world&apos;")
        self.assertEqual(result, '"hello" \'world\'')

    def test_strip_whitespace_blocks_leading(self):
        """Should strip leading blank lines."""
        result = strip_whitespace_blocks("\n\ncode\nmore code\n")
        self.assertEqual(result, "code\nmore code")

    def test_strip_whitespace_blocks_trailing(self):
        """Should strip trailing blank lines."""
        result = strip_whitespace_blocks("code\nmore code\n\n\n")
        self.assertEqual(result, "code\nmore code")

    def test_strip_whitespace_blocks_dedent(self):
        """Should dedent common indentation."""
        result = strip_whitespace_blocks("    line1\n    line2\n")
        self.assertEqual(result, "line1\nline2")

    def test_compute_similarity_identical(self):
        """Identical strings should have similarity 1.0."""
        sim = compute_similarity("hello world", "hello world")
        self.assertEqual(sim, 1.0)

    def test_compute_similarity_different(self):
        """Completely different strings should have low similarity."""
        sim = compute_similarity("hello world", "foo bar baz")
        self.assertLess(sim, 0.5)

    def test_compute_similarity_fuzzy(self):
        """Similar strings should have high similarity."""
        sim = compute_similarity(
            "def hello():\n    print('hi')\n",
            "def hello():\n        print('hi')\n"
        )
        self.assertGreater(sim, 0.7)


# ═══════════════════════════════════════════════════════════════════════════════
# FUZZY MATCHER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestFuzzyMatcher(unittest.TestCase):
    """Tests for the fuzzy matcher."""

    def test_exact_match(self):
        """Should find exact string matches."""
        matcher = FuzzyMatcher()
        content = "line1\nline2\nline3\n"
        result = matcher.find_match(content, "line2")

        self.assertTrue(result.found)
        self.assertEqual(result.start_line, 1)
        self.assertEqual(result.end_line, 2)
        self.assertEqual(result.similarity, 1.0)

    def test_exact_multiline_match(self):
        """Should find exact multi-line matches."""
        matcher = FuzzyMatcher()
        content = "def foo():\n    pass\n\ndef bar():\n    pass\n"
        result = matcher.find_match(content, "def bar():\n    pass")

        self.assertTrue(result.found)
        self.assertEqual(result.start_line, 3)

    def test_quote_normalized_match(self):
        """Should match with quote normalization (Layer 2)."""
        matcher = FuzzyMatcher()
        content = '\u201chello world\u201d'
        result = matcher.find_match(content, '"hello world"')

        self.assertTrue(result.found)
        self.assertGreaterEqual(result.similarity, 0.9)

    def test_xml_normalized_match(self):
        """Should match with XML normalization (Layer 3)."""
        matcher = FuzzyMatcher()
        content = "&lt;div&gt;content&lt;/div&gt;"
        result = matcher.find_match(content, "<div>content</div>")

        self.assertTrue(result.found)
        self.assertGreaterEqual(result.similarity, 0.9)

    def test_fuzzy_match_indentation(self):
        """Should find match with different indentation."""
        matcher = FuzzyMatcher(similarity_threshold=0.7)
        content = "    x = 1\n    y = 2\n"
        search = "x = 1\ny = 2\n"
        result = matcher.find_match(content, search)

        self.assertTrue(result.found)
        self.assertGreater(result.similarity, 0.7)

    def test_fuzzy_match_trailing_whitespace(self):
        """Should match despite trailing whitespace differences."""
        matcher = FuzzyMatcher(similarity_threshold=0.7)
        content = "line1\nline2\n"
        search = "line1  \nline2\n"
        result = matcher.find_match(content, search)

        self.assertTrue(result.found)

    def test_no_match_below_threshold(self):
        """Should not match when similarity is below threshold."""
        matcher = FuzzyMatcher(similarity_threshold=0.9)
        content = "completely different content\n"
        search = "search for something\n"
        result = matcher.find_match(content, search)

        self.assertFalse(result.found)
        self.assertLess(result.similarity, 0.9)

    def test_multiple_matches_error(self):
        """Should report multiple matches when replace_all is False."""
        # Use 3-line content so exact match can find 2 occurrences
        matcher = FuzzyMatcher(similarity_threshold=0.9)
        content = "repeat line\nother\nrepeat line\n"
        result = matcher.find_match(content, "repeat line", replace_all=False)

        # Multiple exact matches without replace_all → not found (error)
        self.assertFalse(result.found)
        self.assertEqual(result.total_matches, 2)

    def test_replace_all_multiple(self):
        """Should handle multiple matches when replace_all is True."""
        matcher = FuzzyMatcher(similarity_threshold=0.9)
        content = "repeat\nother\nrepeat\n"
        result = matcher.find_match(content, "repeat", replace_all=True)

        self.assertTrue(result.found)
        self.assertEqual(result.total_matches, 2)

    def test_empty_search_returns_not_found(self):
        """Empty search string should return not found."""
        matcher = FuzzyMatcher()
        result = matcher.find_match("content", "")

        self.assertFalse(result.found)

    def test_reports_best_match_on_failure(self):
        """Even when match fails, should report best match info."""
        matcher = FuzzyMatcher(similarity_threshold=0.99)  # Very high threshold
        content = "def foo():\n    return 42\n"
        search = "def bar():\n    return 99\n"
        result = matcher.find_match(content, search)

        self.assertFalse(result.found)
        self.assertGreater(result.similarity, 0.0)  # Best match reported
        self.assertGreaterEqual(result.start_line, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# SMART EDIT ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSmartEditEngine(TempDirTestCase):
    """Tests for the Smart Edit Engine."""

    def setUp(self):
        super().setUp()
        self.fsm = FileStateManager()
        self.engine = SmartEditEngine(file_state_manager=self.fsm)

    def test_successful_edit(self):
        """Should successfully edit a read file with exact match."""
        path = self._write_file("test.py", "old_line\nother_line\n")

        self.engine.file_state.mark_read(path, "old_line\nother_line\n")
        result = self.engine.edit(path, "old_line", "new_line")

        self.assertTrue(result.success)
        content = self._read_file(path)
        self.assertEqual(content, "new_line\nother_line\n")

    def test_edit_multiline_search_replace(self):
        """Should handle multi-line search and replace."""
        path = self._write_file("test.py", "def foo():\n    return 1\n\ndef bar():\n    return 2\n")

        self.engine.file_state.mark_read(path, self._read_file(path))
        result = self.engine.edit(
            path,
            "def foo():\n    return 1",
            "def foo():\n    return 42",
        )

        self.assertTrue(result.success)
        content = self._read_file(path)
        self.assertIn("return 42", content)

    def test_edit_fuzzy_indentation(self):
        """Should match despite indentation differences (fuzzy)."""
        path = self._write_file("test.py", "    x = 1\n    y = 2\n")

        self.engine.file_state.mark_read(path, "    x = 1\n    y = 2\n")
        result = self.engine.edit(path, "x = 1\ny = 2", "x = 10\ny = 20")

        self.assertTrue(result.success)
        content = self._read_file(path)
        self.assertIn("x = 10", content)

    def test_edit_updates_file_state(self):
        """After edit, file state should be updated to new content."""
        path = self._write_file("test.py", "old\n")

        self.engine.file_state.mark_read(path, "old\n")
        self.engine.edit(path, "old", "new")

        # File should still be editable
        status, _ = self.engine.file_state.check_editable(path)
        self.assertEqual(status, FileStateStatus.CURRENT)

    def test_error_read_before_write(self):
        """Should reject edit on unread file (Code 6)."""
        path = self._write_file("test.py", "content\n")

        result = self.engine.edit(path, "content", "new")

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, EditErrorCode.READ_BEFORE_WRITE)

    def test_error_stale_read(self):
        """Should reject edit on stale file (Code 7)."""
        path = self._write_file("test.py", "old\n")

        self.engine.file_state.mark_read(path, "old\n")

        # Modify externally
        time.sleep(0.01)
        with open(path, "w") as f:
            f.write("modified\n")
        os.utime(path, (time.time(), time.time() + 1))

        result = self.engine.edit(path, "old", "new")

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, EditErrorCode.STALE_READ)

    def test_error_noop_edit(self):
        """Should reject no-op edits (Code 1)."""
        path = self._write_file("test.py", "same\n")

        self.engine.file_state.mark_read(path, "same\n")
        result = self.engine.edit(path, "same", "same")

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, EditErrorCode.NOOP_EDIT)

    def test_error_file_not_found(self):
        """Should reject edit on non-existent file (Code 4)."""
        path = os.path.join(self.test_dir, "nonexistent.py")

        result = self.engine.edit(path, "x", "y")

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, EditErrorCode.FILE_NOT_FOUND)

    def test_error_protected_path(self):
        """Should reject edit on protected paths (Code 2)."""
        result = self.engine.edit("/etc/passwd", "root", "hacked")

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, EditErrorCode.PATH_DENIED)

    def test_error_notebook_redirect(self):
        """Should redirect .ipynb files (Code 5)."""
        path = self._write_file("test.ipynb", "{}")

        self.engine.file_state.mark_read(path, "{}")
        result = self.engine.edit(path, "{}", '{"cells": []}')

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, EditErrorCode.REDIRECT_NOTEBOOK)

    def test_error_string_not_found(self):
        """Should report string not found (Code 8)."""
        path = self._write_file("test.py", "actual content\n")

        self.engine.file_state.mark_read(path, "actual content\n")
        result = self.engine.edit(path, "completely wrong search", "new")

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, EditErrorCode.STRING_NOT_FOUND)
        self.assertIn("similarity", result.error_message)

    def test_create_file_success(self):
        """Should create a new file."""
        path = os.path.join(self.test_dir, "new_file.py")

        result = self.engine.create_file(path, "print('hello')\n")

        self.assertTrue(result.success)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self._read_file(path), "print('hello')\n")

    def test_create_file_reject_overwrite(self):
        """Should reject overwriting existing non-empty file (Code 3)."""
        path = self._write_file("existing.py", "old content\n")

        result = self.engine.create_file(path, "new content\n")

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, EditErrorCode.OVERWRITE_EXISTING)

    def test_create_file_allow_overwrite(self):
        """Should overwrite when allow_overwrite=True."""
        path = self._write_file("existing.py", "old content\n")

        result = self.engine.create_file(
            path, "new content\n", allow_overwrite=True
        )

        self.assertTrue(result.success)
        self.assertEqual(self._read_file(path), "new content\n")

    def test_replace_all(self):
        """Should replace all occurrences when replace_all=True."""
        path = self._write_file("test.py", "repeat\nother\nrepeat\n")

        self.engine.file_state.mark_read(path, self._read_file(path))
        result = self.engine.edit(path, "repeat", "replaced", replace_all=True)

        self.assertTrue(result.success)
        content = self._read_file(path)
        self.assertEqual(content.count("replaced"), 2)

    def test_stats_track_edits(self):
        """Stats should track successful and failed edits."""
        path = self._write_file("test.py", "old\n")
        self.engine.file_state.mark_read(path, "old\n")

        self.engine.edit(path, "old", "new")  # Success
        self.engine.edit(path, "nonexistent", "x")  # Fail (stale state)

        stats = self.engine.get_stats()
        self.assertGreater(stats["total_edits"], 0)
        self.assertGreater(stats["successful_edits"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# HISTORY INDEX TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestHistoryIndex(TempDirTestCase):
    """Tests for the History Index."""

    def test_record_snapshot(self):
        """Should create a snapshot entry and backup file."""
        index = HistoryIndex(project_root=self.test_dir)
        path = os.path.join(self.test_dir, "test.py")

        entry = index.record_snapshot(path, "original content", worker_id="coder")

        self.assertIsInstance(entry, SnapshotEntry)
        self.assertEqual(entry.file_path, path)
        self.assertEqual(entry.worker_id, "coder")
        self.assertGreater(entry.timestamp, 0)
        self.assertNotEqual(entry.original_hash, "")
        self.assertTrue(os.path.exists(entry.backup_path))

    def test_get_latest_snapshot(self):
        """Should return the most recent snapshot."""
        index = HistoryIndex(project_root=self.test_dir)
        path = os.path.join(self.test_dir, "test.py")

        index.record_snapshot(path, "v1")
        time.sleep(0.01)
        index.record_snapshot(path, "v2")
        time.sleep(0.01)
        index.record_snapshot(path, "v3")

        latest = index.get_latest_snapshot(path)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.line_count, 1)  # v3

    def test_get_n_latest_snapshot(self):
        """Should return the Nth-to-last snapshot."""
        index = HistoryIndex(project_root=self.test_dir)
        path = os.path.join(self.test_dir, "test.py")

        index.record_snapshot(path, "v1")
        time.sleep(0.01)
        index.record_snapshot(path, "v2")
        time.sleep(0.01)
        index.record_snapshot(path, "v3")

        # N=1 → latest (v3)
        n1 = index.get_n_latest_snapshot(path, n=1)
        self.assertIsNotNone(n1)

        # N=2 → second latest (v2)
        n2 = index.get_n_latest_snapshot(path, n=2)
        self.assertIsNotNone(n2)

        # N=5 → too far back
        n5 = index.get_n_latest_snapshot(path, n=5)
        self.assertIsNone(n5)

    def test_get_snapshots_for_file(self):
        """Should return only snapshots for the specified file."""
        index = HistoryIndex(project_root=self.test_dir)
        path1 = os.path.join(self.test_dir, "a.py")
        path2 = os.path.join(self.test_dir, "b.py")

        index.record_snapshot(path1, "a content")
        index.record_snapshot(path2, "b content")
        index.record_snapshot(path1, "a content v2")

        snapshots = index.get_snapshots(file_path=path1)
        self.assertEqual(len(snapshots), 2)
        for s in snapshots:
            self.assertEqual(s.file_path, path1)

    def test_get_all_snapshots(self):
        """Should return all snapshots when no file specified."""
        index = HistoryIndex(project_root=self.test_dir)
        path1 = os.path.join(self.test_dir, "a.py")
        path2 = os.path.join(self.test_dir, "b.py")

        index.record_snapshot(path1, "a")
        index.record_snapshot(path2, "b")
        index.record_snapshot(path1, "a2")

        all_snaps = index.get_snapshots()
        self.assertEqual(len(all_snaps), 3)

    def test_persists_to_disk(self):
        """Should persist index to JSON file on disk."""
        index = HistoryIndex(project_root=self.test_dir)
        path = os.path.join(self.test_dir, "test.py")

        index.record_snapshot(path, "content", worker_id="coder")

        # Reload index
        index2 = HistoryIndex(project_root=self.test_dir)
        latest = index2.get_latest_snapshot(path)

        self.assertIsNotNone(latest)
        self.assertEqual(latest.worker_id, "coder")

    def test_garbage_collection(self):
        """Should prune snapshots older than retention period."""
        index = HistoryIndex(project_root=self.test_dir, retention_days=0)
        path = os.path.join(self.test_dir, "test.py")

        entry = index.record_snapshot(path, "content")
        backup_path = entry.backup_path

        # With retention_days=0, GC should remove everything
        removed = index.garbage_collect()

        self.assertGreater(removed, 0)
        # Backup file should be deleted
        self.assertFalse(os.path.exists(backup_path))

    def test_remove_snapshot(self):
        """Should remove a specific snapshot and its backup."""
        index = HistoryIndex(project_root=self.test_dir)
        path = os.path.join(self.test_dir, "test.py")

        entry = index.record_snapshot(path, "content")
        backup_path = entry.backup_path

        result = index.remove_snapshot(entry.snapshot_id)

        self.assertTrue(result)
        self.assertFalse(os.path.exists(backup_path))
        self.assertIsNone(index.get_latest_snapshot(path))

    def test_stats(self):
        """Stats should return meaningful data."""
        index = HistoryIndex(project_root=self.test_dir)
        path = os.path.join(self.test_dir, "test.py")

        index.record_snapshot(path, "content")
        stats = index.get_stats()

        self.assertEqual(stats["project_root"], self.test_dir)
        self.assertGreater(stats["total_snapshots"], 0)
        self.assertGreater(stats["files_tracked"], 0)

    def test_get_all_edited_files(self):
        """Should list all files with edit history."""
        index = HistoryIndex(project_root=self.test_dir)
        path1 = os.path.join(self.test_dir, "a.py")
        path2 = os.path.join(self.test_dir, "b.py")

        index.record_snapshot(path1, "a")
        index.record_snapshot(path2, "b")

        files = index.get_all_edited_files()
        self.assertEqual(len(files), 2)


# ═══════════════════════════════════════════════════════════════════════════════
# ROLLBACK MANAGER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestRollbackManager(TempDirTestCase):
    """Tests for the Rollback Manager."""

    def setUp(self):
        super().setUp()
        self.fsm = FileStateManager()
        self.rollback = create_rollback_manager(
            project_root=self.test_dir,
            file_state_manager=self.fsm,
        )

    def test_backup_before_edit(self):
        """Should create a backup before edit."""
        path = os.path.join(self.test_dir, "test.py")
        original = "original content\n"

        entry = self.rollback.backup_before_edit(path, original, worker_id="coder")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.worker_id, "coder")
        self.assertTrue(os.path.exists(entry.backup_path))

        # Backup content should match original
        with open(entry.backup_path, "r") as f:
            self.assertEqual(f.read(), original)

    def test_undo_single_edit(self):
        """Should revert a single edit."""
        path = self._write_file("test.py", "original\n")

        # Backup original
        self.rollback.backup_before_edit(path, "original\n", worker_id="coder")

        # Edit the file
        with open(path, "w") as f:
            f.write("modified\n")

        # Undo
        result = self.rollback.undo(path)

        self.assertEqual(result.status, RollbackResultStatus.SUCCESS)
        self.assertEqual(result.edits_reverted, 1)
        self.assertEqual(self._read_file(path), "original\n")

    def test_undo_multiple_edits(self):
        """Should revert multiple edits with steps parameter."""
        path = self._write_file("test.py", "v1\n")

        self.rollback.backup_before_edit(path, "v1\n")
        self._write_file("test.py", "v2\n")

        self.rollback.backup_before_edit(path, "v2\n")
        self._write_file("test.py", "v3\n")

        self.rollback.backup_before_edit(path, "v3\n")
        self._write_file("test.py", "v4\n")

        # Undo 2 edits → should restore to v2
        result = self.rollback.undo(path, steps=2)

        self.assertEqual(result.status, RollbackResultStatus.SUCCESS)
        self.assertEqual(self._read_file(path), "v2\n")

    def test_undo_no_history(self):
        """Should report NO_HISTORY when no snapshots exist."""
        path = self._write_file("test.py", "content\n")

        result = self.rollback.undo(path)

        self.assertEqual(result.status, RollbackResultStatus.NO_HISTORY)

    def test_undo_updates_file_state(self):
        """After undo, file should be editable (not stale)."""
        path = self._write_file("test.py", "original\n")

        self.rollback.backup_before_edit(path, "original\n")
        self.fsm.mark_read(path, "original\n")

        with open(path, "w") as f:
            f.write("modified\n")

        self.rollback.undo(path)

        status, _ = self.fsm.check_editable(path)
        self.assertEqual(status, FileStateStatus.CURRENT)

    def test_list_history(self):
        """Should list edit history."""
        path = os.path.join(self.test_dir, "test.py")

        self.rollback.backup_before_edit(path, "v1", worker_id="coder")
        time.sleep(0.01)
        self.rollback.backup_before_edit(path, "v2", worker_id="coder")

        history = self.rollback.list_history(path)

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["worker"], "coder")

    def test_get_history_count(self):
        """Should count snapshots correctly."""
        path = os.path.join(self.test_dir, "test.py")

        self.assertEqual(self.rollback.get_history_count(path), 0)

        self.rollback.backup_before_edit(path, "v1")
        self.rollback.backup_before_edit(path, "v2")

        self.assertEqual(self.rollback.get_history_count(path), 2)

    def test_clear_history(self):
        """Should clear all history for a file."""
        path = os.path.join(self.test_dir, "test.py")

        entry = self.rollback.backup_before_edit(path, "content")
        self.rollback.clear_history(path)

        self.assertEqual(self.rollback.get_history_count(path), 0)
        self.assertFalse(os.path.exists(entry.backup_path))

    def test_garbage_collect(self):
        """Should prune old snapshots."""
        # Use negative retention to ensure everything is pruned
        self.rollback.index.retention_days = -1
        path = os.path.join(self.test_dir, "test.py")

        self.rollback.backup_before_edit(path, "content")
        removed = self.rollback.garbage_collect()

        self.assertGreater(removed, 0)

    def test_stats(self):
        """Stats should track backup and undo operations."""
        path = self._write_file("test.py", "original\n")

        self.rollback.backup_before_edit(path, "original\n")
        self.rollback.undo(path)

        stats = self.rollback.get_stats()
        self.assertGreater(stats["total_backups"], 0)
        self.assertGreater(stats["total_undos"], 0)
        self.assertGreater(stats["successful_undos"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPhase2Integration(TempDirTestCase):
    """Integration tests combining all Phase 2 components."""

    def test_full_edit_backup_undo_pipeline(self):
        """Full pipeline: read → backup → edit → undo → verify."""
        from smart_edit import create_smart_edit
        from rollback import create_rollback_manager

        # Setup
        fsm = FileStateManager()
        engine = create_smart_edit(file_state_manager=fsm)
        rm = create_rollback_manager(
            project_root=self.test_dir,
            file_state_manager=fsm,
        )

        # Step 1: Create a file
        path = os.path.join(self.test_dir, "main.py")
        original = (
            "def hello():\n"
            "    print('hello')\n"
            "\n"
            "def goodbye():\n"
            "    print('goodbye')\n"
        )
        with open(path, "w") as f:
            f.write(original)

        # Step 2: Read the file
        content = open(path).read()
        fsm.mark_read(path, content)

        # Step 3: Backup before edit
        rm.backup_before_edit(path, content, worker_id="coder")

        # Step 4: Perform edit
        result = engine.edit(
            path,
            "def hello():\n    print('hello')",
            "def hello():\n    print('HELLO WORLD')",
        )
        self.assertTrue(result.success)
        self.assertIn("HELLO WORLD", self._read_file(path))

        # Step 5: Undo the edit
        undo_result = rm.undo(path)
        self.assertEqual(undo_result.status, RollbackResultStatus.SUCCESS)

        # Step 6: Verify file is restored
        restored = self._read_file(path)
        self.assertEqual(restored, original)

    def test_multiple_edits_with_rollback(self):
        """Multiple sequential edits with rollback to different points."""
        fsm = FileStateManager()
        engine = create_smart_edit(file_state_manager=fsm)
        rm = create_rollback_manager(
            project_root=self.test_dir,
            file_state_manager=fsm,
        )

        path = os.path.join(self.test_dir, "counter.py")
        v1 = "count = 0\n"
        with open(path, "w") as f:
            f.write(v1)

        # Edit 1: count = 1
        fsm.mark_read(path, v1)
        rm.backup_before_edit(path, v1)
        engine.edit(path, "count = 0", "count = 1")
        self.assertIn("count = 1", self._read_file(path))

        # Edit 2: count = 2
        fsm.mark_read(path, self._read_file(path))
        rm.backup_before_edit(path, self._read_file(path))
        engine.edit(path, "count = 1", "count = 2")
        self.assertIn("count = 2", self._read_file(path))

        # Undo 1 edit → should be count = 1
        rm.undo(path)
        self.assertIn("count = 1", self._read_file(path))

        # Undo remaining edit → should be count = 0
        rm.undo(path)
        self.assertIn("count = 0", self._read_file(path))

    def test_edit_preserves_file_formatting(self):
        """Edit should preserve surrounding file formatting."""
        fsm = FileStateManager()
        engine = create_smart_edit(file_state_manager=fsm)

        path = os.path.join(self.test_dir, "format.py")
        content = (
            "# Header\n"
            "\n"
            "x = 1\n"
            "y = 2\n"
            "\n"
            "# Footer\n"
        )
        with open(path, "w") as f:
            f.write(content)

        fsm.mark_read(path, content)
        engine.edit(path, "x = 1", "x = 42")

        result = self._read_file(path)
        self.assertIn("# Header", result)
        self.assertIn("x = 42", result)
        self.assertIn("y = 2", result)
        self.assertIn("# Footer", result)

    def test_atomic_write_no_corruption(self):
        """Atomic write should not corrupt the file."""
        fsm = FileStateManager()
        engine = create_smart_edit(file_state_manager=fsm)

        path = os.path.join(self.test_dir, "critical.py")
        content = "CRITICAL_DATA = True\n"
        with open(path, "w") as f:
            f.write(content)

        fsm.mark_read(path, content)

        # Multiple rapid edits
        for i in range(10):
            fsm.mark_read(path, self._read_file(path))
            result = engine.edit(path, f"CRITICAL_DATA = {i != 9}", f"CRITICAL_DATA = {i}")
            self.assertTrue(result.success, f"Edit {i} failed: {result.error_message}")

        # File should have final value
        result_content = self._read_file(path)
        self.assertIn("CRITICAL_DATA = 9", result_content)

    def test_history_survives_across_sessions(self):
        """History index should persist across index reloads."""
        rm = create_rollback_manager(project_root=self.test_dir)
        path = os.path.join(self.test_dir, "persist.py")

        with open(path, "w") as f:
            f.write("original\n")

        rm.backup_before_edit(path, "original\n", worker_id="coder")

        # Create a NEW rollback manager (simulating session restart)
        rm2 = create_rollback_manager(project_root=self.test_dir)

        # Should still have the history
        count = rm2.get_history_count(path)
        self.assertEqual(count, 1)

        # And be able to undo
        with open(path, "w") as f:
            f.write("modified\n")

        result = rm2.undo(path)
        self.assertEqual(result.status, RollbackResultStatus.SUCCESS)


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def run_tests():
    """Run all Phase 2 tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Load all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestFileStateManager))
    suite.addTests(loader.loadTestsFromTestCase(TestStringNormalization))
    suite.addTests(loader.loadTestsFromTestCase(TestFuzzyMatcher))
    suite.addTests(loader.loadTestsFromTestCase(TestSmartEditEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestHistoryIndex))
    suite.addTests(loader.loadTestsFromTestCase(TestRollbackManager))
    suite.addTests(loader.loadTestsFromTestCase(TestPhase2Integration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print("\n" + "=" * 60)
    print(f"  PHASE 2 TEST GATE RESULTS")
    print("=" * 60)
    print(f"  Tests run: {result.testsRun}")
    print(f"  Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"  Failed: {len(result.failures)}")
    print(f"  Errors: {len(result.errors)}")
    print(f"  Phase 2: {'PASSED' if result.wasSuccessful() else 'FAILED'}")
    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
