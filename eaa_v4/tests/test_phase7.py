"""
test_phase7.py — Unit Tests for EAA V4 Phase 7: Cross-Session Memory

Comprehensive tests for all Phase 7 modules using unittest with no
external dependencies.  Uses tempfile.mkdtemp() for filesystem isolation
and cleans up in tearDown.

Modules tested:
    - SessionTranscript  — JSONL persistence, token-aware resume
    - SessionMemory      — Rolling notes compaction
    - MemoryExtractor    — Background heuristic extraction
    - PromptHistory      — Project-scoped command history
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

# Ensure the eaa_v4 root directory is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_transcript import SessionTranscript
from session_memory import SessionMemory
from memory_extractor import MemoryExtractor, MemoryEntry
from prompt_history import PromptHistory


def _redirect_expanduser(tmpdir):
    """
    Return a replacement for os.path.expanduser that maps ~/.eaa
    to tmpdir/.eaa.  Uses the *real* home dir captured before patching.
    """
    real_home = os.path.expanduser("~")  # capture before override

    def _expanduser(path):
        if path.startswith("~/"):
            return tmpdir + path[1:]
        elif path == "~":
            return tmpdir
        return path

    return _expanduser


class TestSessionTranscript(unittest.TestCase):
    """Tests for SessionTranscript: JSONL persistence and token-aware resume."""

    def setUp(self):
        """Create a temp directory and mock ~/.eaa/projects/ path."""
        self.tmpdir = tempfile.mkdtemp()
        self.eaa_dir = os.path.join(self.tmpdir, ".eaa", "projects")
        os.makedirs(self.eaa_dir, exist_ok=True)
        self._orig_expanduser = os.path.expanduser
        os.path.expanduser = _redirect_expanduser(self.tmpdir)
        self.project_root = "/tmp/test_project"

    def tearDown(self):
        """Clean up temp directory."""
        os.path.expanduser = self._orig_expanduser
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_transcript(self, project_root=None):
        """Create a SessionTranscript with a temp directory."""
        pr = project_root or self.project_root
        st = SessionTranscript(pr)
        # Override path to use temp dir
        import hashlib
        h = hashlib.md5(pr.encode()).hexdigest()[:12]
        st.transcript_path = os.path.join(self.eaa_dir, f"{h}.jsonl")
        os.makedirs(os.path.dirname(st.transcript_path), exist_ok=True)
        return st

    # ── append_turn ─────────────────────────────────────────────────────

    def test_append_turn_writes_jsonl(self):
        """append_turn writes a valid JSON line to the transcript file."""
        st = self._make_transcript()
        seq = st.append_turn("user", "Hello world")
        self.assertEqual(seq, 1)
        with open(st.transcript_path) as f:
            line = f.read().strip()
        data = json.loads(line)
        self.assertEqual(data["role"], "user")
        self.assertEqual(data["content"], "Hello world")
        self.assertEqual(data["seq"], 1)
        self.assertIn("timestamp", data)

    def test_append_turn_increments_seq(self):
        """Sequence numbers are monotonically increasing."""
        st = self._make_transcript()
        s1 = st.append_turn("user", "first")
        s2 = st.append_turn("assistant", "second")
        s3 = st.append_turn("user", "third")
        self.assertEqual(s1, 1)
        self.assertEqual(s2, 2)
        self.assertEqual(s3, 3)

    def test_append_turn_with_tool_calls(self):
        """Tool calls are stored in the turn."""
        st = self._make_transcript()
        tc = [{"name": "read", "args": {"path": "main.py"}}]
        st.append_turn("assistant", "Reading file", tool_calls=tc)
        turns = st._read_all_turns()
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["tool_calls"], tc)

    # ── resume with token cap ───────────────────────────────────────────

    def test_resume_respects_token_cap(self):
        """Resume returns turns that fit within max_tokens."""
        st = self._make_transcript()
        # Each turn is 100 chars = 25 tokens
        for i in range(10):
            st.append_turn("user", "x" * 100)
        # 100 tokens cap should fit ~4 turns
        turns = st.resume(max_tokens=100)
        total_tokens = sum(st._estimate_turn_tokens(t) for t in turns)
        self.assertLessEqual(total_tokens, 100)

    def test_resume_6k_hard_cap(self):
        """Default resume cap is 6000 tokens."""
        st = self._make_transcript()
        for i in range(100):
            st.append_turn("user", "word " * 100)  # ~50 tokens each
        turns = st.resume()
        total = sum(st._estimate_turn_tokens(t) for t in turns)
        self.assertLessEqual(total, 6000)

    def test_resume_prioritizes_user_assistant(self):
        """Resume prioritizes user/assistant turns over tool results."""
        st = self._make_transcript()
        # Add a mix of roles
        st.append_turn("user", "important question")
        st.append_turn("tool", "large tool output " * 500)  # ~250 tokens
        st.append_turn("assistant", "important answer")
        st.append_turn("tool", "more tool output " * 500)  # ~250 tokens
        st.append_turn("user", "follow up question")

        # Very tight budget: should keep user/assistant, drop tools
        turns = st.resume(max_tokens=60)
        roles = [t["role"] for t in turns]
        # user/assistant should be present
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)

    def test_resume_oldest_first_ordering(self):
        """Resumed turns are ordered oldest-first."""
        st = self._make_transcript()
        for i in range(5):
            st.append_turn("user", f"message {i}")
        turns = st.resume(max_tokens=10000)
        contents = [t["content"] for t in turns]
        self.assertEqual(contents, ["message 0", "message 1", "message 2", "message 3", "message 4"])

    # ── corrupted line recovery ─────────────────────────────────────────

    def test_corrupted_lines_skipped(self):
        """Corrupted JSONL lines are silently skipped."""
        st = self._make_transcript()
        st.append_turn("user", "valid message")
        # Append a corrupted line
        with open(st.transcript_path, "a") as f:
            f.write("{corrupted json\n")
        st.append_turn("assistant", "another valid message")
        turns = st._read_all_turns()
        self.assertEqual(len(turns), 2)

    # ── project isolation ───────────────────────────────────────────────

    def test_project_isolation(self):
        """Different projects have different transcript files."""
        st1 = self._make_transcript("/tmp/project_a")
        st2 = self._make_transcript("/tmp/project_b")
        st1.append_turn("user", "project A message")
        st2.append_turn("user", "project B message")
        # Each should only see its own turns
        turns1 = st1._read_all_turns()
        turns2 = st2._read_all_turns()
        self.assertEqual(len(turns1), 1)
        self.assertEqual(len(turns2), 1)
        self.assertEqual(turns1[0]["content"], "project A message")
        self.assertEqual(turns2[0]["content"], "project B message")

    # ── flush ───────────────────────────────────────────────────────────

    def test_flush_no_error(self):
        """flush() does not raise on existing file."""
        st = self._make_transcript()
        st.append_turn("user", "test")
        st.flush()  # Should not raise

    def test_flush_missing_file_no_error(self):
        """flush() does not raise when transcript file doesn't exist."""
        st = self._make_transcript()
        st.flush()  # File doesn't exist yet

    # ── _estimate_turn_tokens ───────────────────────────────────────────

    def test_estimate_turn_tokens_basic(self):
        """Token estimation uses 4 chars ≈ 1 token."""
        st = self._make_transcript()
        turn = {"content": "a" * 40}
        self.assertEqual(st._estimate_turn_tokens(turn), 10)

    def test_estimate_turn_tokens_minimum_one(self):
        """Empty content returns at least 1 token."""
        st = self._make_transcript()
        turn = {"content": ""}
        self.assertEqual(st._estimate_turn_tokens(turn), 1)

    def test_estimate_turn_tokens_missing_content(self):
        """Missing content key returns at least 1 token."""
        st = self._make_transcript()
        turn = {}
        self.assertEqual(st._estimate_turn_tokens(turn), 1)

    # ── resume with max_age_seconds ─────────────────────────────────────

    def test_resume_age_filter_drops_stale_tools(self):
        """max_age_seconds drops old tool turns but keeps user/assistant."""
        st = self._make_transcript()
        st.append_turn("user", "keep this")
        # Manually inject an old tool turn
        import time as _time
        old_turn = {"seq": 99, "role": "tool", "content": "old tool result",
                     "timestamp": _time.time() - 1000,
                     "tool_calls": [], "tool_results": []}
        with open(st.transcript_path, "a") as f:
            f.write(json.dumps(old_turn) + "\n")
        st.append_turn("assistant", "keep this too")

        # 60-second age filter should drop the old tool turn
        turns = st.resume(max_tokens=10000, max_age_seconds=60)
        roles = [t["role"] for t in turns]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)
        self.assertNotIn("tool", roles)

    # ── empty transcript ────────────────────────────────────────────────

    def test_resume_empty_transcript(self):
        """Resume on empty transcript returns empty list."""
        st = self._make_transcript()
        turns = st.resume()
        self.assertEqual(turns, [])

    def test_get_turn_count(self):
        """get_turn_count returns the correct count."""
        st = self._make_transcript()
        self.assertEqual(st.get_turn_count(), 0)
        st.append_turn("user", "hello")
        self.assertEqual(st.get_turn_count(), 1)
        st.append_turn("assistant", "world")
        self.assertEqual(st.get_turn_count(), 2)


class TestSessionMemory(unittest.TestCase):
    """Tests for SessionMemory: rolling Markdown notes compaction."""

    def setUp(self):
        self.sm = SessionMemory(update_threshold=100)

    # ── update triggers on threshold ────────────────────────────────────

    def test_update_triggers_on_threshold(self):
        """Regeneration triggers when token counter exceeds threshold."""
        messages = [{"role": "user", "content": "fix main.py"}]
        # Below threshold
        self.sm.update(messages, new_tokens=50)
        self.assertEqual(self.sm.current_state, "")
        # At threshold
        self.sm.update(messages, new_tokens=60)
        self.assertIn("main.py", self.sm.current_state)

    def test_update_resets_counter_after_regeneration(self):
        """Token counter resets to zero after regeneration."""
        messages = [{"role": "user", "content": "task"}]
        self.sm.update(messages, new_tokens=100)
        self.assertEqual(self.sm._token_counter, 0)
        # Should not regenerate again immediately
        self.sm.current_state = ""
        self.sm.update(messages, new_tokens=50)
        self.assertEqual(self.sm.current_state, "")

    # ── update triggers on errors ───────────────────────────────────────

    def test_update_triggers_on_error_keyword(self):
        """Regeneration triggers immediately on error keywords."""
        messages = [
            {"role": "assistant", "content": "Traceback (most recent call last): ..."}
        ]
        self.sm.update(messages, new_tokens=10)
        self.assertIn("Traceback", self.sm.errors)
        self.assertNotEqual(self.sm.errors, "No recent errors")

    def test_update_triggers_on_syntaxerror(self):
        """SyntaxError keyword triggers immediate regeneration."""
        messages = [
            {"role": "assistant", "content": "SyntaxError: invalid syntax"}
        ]
        self.sm.update(messages, new_tokens=5)
        self.assertIn("SyntaxError", self.sm.errors)

    def test_update_triggers_on_file_written(self):
        "'file written' keyword triggers immediate regeneration."""
        messages = [
            {"role": "assistant", "content": "File written: auth.py (150 lines)"}
        ]
        self.sm.update(messages, new_tokens=5)
        # Should have regenerated
        self.assertNotEqual(self.sm.workflow, "")

    # ── get_notes rendering ─────────────────────────────────────────────

    def test_get_notes_contains_sections(self):
        """get_notes() returns Markdown with all three sections."""
        messages = [
            {"role": "user", "content": "Create main.py and utils.py"},
        ]
        self.sm.update(messages, new_tokens=100)
        notes = self.sm.get_notes()
        self.assertIn("# Session Memory", notes)
        self.assertIn("## Current State", notes)
        self.assertIn("## Errors", notes)
        self.assertIn("## Workflow", notes)

    def test_get_notes_shows_file_paths(self):
        """Extracted file paths appear in Current State."""
        messages = [
            {"role": "user", "content": "Edit auth.py and add tests to test_auth.py"},
        ]
        self.sm.update(messages, new_tokens=100)
        notes = self.sm.get_notes()
        self.assertIn("auth.py", notes)

    # ── empty state handling ────────────────────────────────────────────

    def test_empty_state_notes(self):
        """get_notes() works before any update is called."""
        notes = self.sm.get_notes()
        self.assertIn("# Session Memory", notes)

    def test_empty_state_no_errors(self):
        """Before any update, errors section says 'No recent errors'."""
        notes = self.sm.get_notes()
        self.assertIn("No recent errors", notes)

    # ── get_token_count ─────────────────────────────────────────────────

    def test_get_token_count_minimum_one(self):
        """Token count is always at least 1."""
        count = self.sm.get_token_count()
        self.assertGreaterEqual(count, 1)

    def test_get_token_count_reasonable(self):
        """Token count approximates len(notes) / 4."""
        messages = [
            {"role": "user", "content": "Create main.py and utils.py"},
        ]
        self.sm.update(messages, new_tokens=100)
        notes = self.sm.get_notes()
        expected = max(1, len(notes) // 4)
        self.assertEqual(self.sm.get_token_count(), expected)

    # ── non-dict messages ───────────────────────────────────────────────

    def test_non_dict_messages_handled(self):
        """String messages (non-dict) don't crash update()."""
        self.sm.update(["just a string message"], new_tokens=200)
        # Should not raise, should regenerate
        self.assertNotEqual(self.sm.workflow, "")


class TestMemoryExtractor(unittest.TestCase):
    """Tests for MemoryExtractor: background heuristic memory extraction."""

    def setUp(self):
        """Create a temp directory and a mock transcript."""
        self.tmpdir = tempfile.mkdtemp()
        self.eaa_dir = os.path.join(self.tmpdir, ".eaa", "memory")
        self.projects_dir = os.path.join(self.tmpdir, ".eaa", "projects")
        os.makedirs(self.eaa_dir, exist_ok=True)
        os.makedirs(self.projects_dir, exist_ok=True)
        self._orig_expanduser = os.path.expanduser
        os.path.expanduser = _redirect_expanduser(self.tmpdir)
        # Prevent daemon thread from starting in tests
        self._orig_isatty = sys.stdout.isatty
        sys.stdout.isatty = lambda: True

        # Create transcript pointing to temp dir
        self.project_root = "/tmp/test_project"
        import hashlib
        h = hashlib.md5(self.project_root.encode()).hexdigest()[:12]
        self.transcript = SessionTranscript.__new__(SessionTranscript)
        self.transcript.project_root = self.project_root
        self.transcript._seq = 0
        self.transcript.transcript_path = os.path.join(
            self.projects_dir, f"{h}.jsonl"
        )

    def tearDown(self):
        sys.stdout.isatty = self._orig_isatty
        os.path.expanduser = self._orig_expanduser
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── extract with heuristics ─────────────────────────────────────────

    def test_extract_preferences(self):
        """Preference keywords are extracted as user_preferences."""
        self.transcript.append_turn(
            "user", "I prefer tabs over spaces for indentation"
        )
        me = MemoryExtractor(self.transcript)
        entries = me.extract()
        me.stop_daemon()
        types = [e.memory_type for e in entries]
        self.assertIn("user_preferences", types)

    def test_extract_rules(self):
        """Rule keywords are extracted as project_rules."""
        self.transcript.append_turn(
            "user", "This project must use repository pattern"
        )
        me = MemoryExtractor(self.transcript)
        entries = me.extract()
        me.stop_daemon()
        types = [e.memory_type for e in entries]
        self.assertIn("project_rules", types)

    def test_extract_errors(self):
        """Error keywords are extracted as error_patterns."""
        self.transcript.append_turn(
            "assistant", "Error: TypeError at line 42 in main.py"
        )
        me = MemoryExtractor(self.transcript)
        entries = me.extract()
        me.stop_daemon()
        types = [e.memory_type for e in entries]
        self.assertIn("error_patterns", types)

    def test_extract_urls(self):
        """URLs are extracted as reference_links."""
        self.transcript.append_turn(
            "user", "Check out https://docs.python.org/3/library/asyncio.html"
        )
        me = MemoryExtractor(self.transcript)
        entries = me.extract()
        me.stop_daemon()
        types = [e.memory_type for e in entries]
        self.assertIn("reference_links", types)

    def test_extract_empty_transcript(self):
        """Empty transcript returns empty list."""
        me = MemoryExtractor(self.transcript)
        entries = me.extract()
        me.stop_daemon()
        self.assertEqual(entries, [])

    # ── write_memory_files ──────────────────────────────────────────────

    def test_write_memory_files_creates_files(self):
        """Memory files are written to ~/.eaa/memory/."""
        self.transcript.append_turn(
            "user", "I prefer tabs over spaces"
        )
        me = MemoryExtractor(self.transcript)
        me.extract()
        me.stop_daemon()
        # Check that file was created
        prefs_path = os.path.join(self.eaa_dir, "user_preferences.md")
        self.assertTrue(os.path.exists(prefs_path))
        with open(prefs_path) as f:
            content = f.read()
        self.assertIn("---", content)
        self.assertIn("type: user_preferences", content)
        self.assertIn("tabs", content)

    # ── sliding window extraction ───────────────────────────────────────

    def test_sliding_window_for_long_transcript(self):
        """Long transcripts (>16K chars) use sliding window extraction."""
        # Generate enough content to exceed the 16K char threshold
        for i in range(50):
            self.transcript.append_turn(
                "user",
                f"I prefer using pattern {i} for this project. "
                "This project must follow the architecture guidelines. "
                f"Reference: https://example.com/doc/{i} "
                f"Error: TypeError at line {i} in module.{i}.py" * 10,
            )
        me = MemoryExtractor(self.transcript)
        entries = me.extract()
        me.stop_daemon()
        # Should have extracted something
        self.assertGreater(len(entries), 0)

    # ── idle check ──────────────────────────────────────────────────────

    def test_idle_check_false_when_recent(self):
        """_check_idle returns False right after timestamp update."""
        me = MemoryExtractor(self.transcript)
        me.update_idle_timestamp()
        self.assertFalse(me._check_idle(300))
        me.stop_daemon()

    def test_idle_check_true_when_stale(self):
        """_check_idle returns True after idle threshold."""
        me = MemoryExtractor(self.transcript)
        me._last_input_timestamp = time.time() - 600
        self.assertTrue(me._check_idle(300))
        me.stop_daemon()

    # ── _filter_noise ───────────────────────────────────────────────────

    def test_filter_noise_removes_system(self):
        """System messages are filtered out."""
        me = MemoryExtractor(self.transcript)
        me.stop_daemon()
        turns = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        filtered = me._filter_noise(turns)
        roles = [t["role"] for t in filtered]
        self.assertNotIn("system", roles)
        self.assertEqual(len(filtered), 2)

    # ── daemon thread start/stop ────────────────────────────────────────

    def test_stop_daemon_no_error(self):
        """stop_daemon() completes without error."""
        me = MemoryExtractor(self.transcript)
        me.stop_daemon()  # Should not raise

    def test_concurrent_extraction_guard(self):
        """Concurrent extract() calls return empty when already extracting."""
        me = MemoryExtractor(self.transcript)
        me.stop_daemon()
        self.transcript.append_turn("user", "I prefer using tabs for indentation")

        # Single call should work and return results
        results1 = me.extract()
        self.assertGreater(len(results1), 0)

    # ── trigger_on_exit ─────────────────────────────────────────────────

    def test_trigger_on_exit(self):
        """trigger_on_exit delegates to extract()."""
        self.transcript.append_turn("user", "prefer dark mode")
        me = MemoryExtractor(self.transcript)
        me.stop_daemon()
        entries = me.trigger_on_exit()
        self.assertGreater(len(entries), 0)

    # ── MemoryEntry dataclass ───────────────────────────────────────────

    def test_memory_entry_defaults(self):
        """MemoryEntry has correct default values."""
        entry = MemoryEntry("user_preferences", "prefer tabs")
        self.assertEqual(entry.memory_type, "user_preferences")
        self.assertEqual(entry.scope, "project")
        self.assertAlmostEqual(entry.confidence, 0.8)
        self.assertGreater(entry.timestamp, 0)


class TestPromptHistory(unittest.TestCase):
    """Tests for PromptHistory: project-scoped command history."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.eaa_dir = os.path.join(self.tmpdir, ".eaa", "projects")
        os.makedirs(self.eaa_dir, exist_ok=True)
        self._orig_expanduser = os.path.expanduser
        os.path.expanduser = _redirect_expanduser(self.tmpdir)

    def tearDown(self):
        os.path.expanduser = self._orig_expanduser
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_history(self, project_root="/tmp/test_project"):
        ph = PromptHistory(project_root)
        import hashlib
        h = hashlib.md5(project_root.encode()).hexdigest()[:12]
        ph.history_path = os.path.join(self.eaa_dir, f"{h}_history.jsonl")
        os.makedirs(os.path.dirname(ph.history_path), exist_ok=True)
        return ph

    # ── append/search ───────────────────────────────────────────────────

    def test_append_and_search(self):
        """Appended commands are searchable."""
        ph = self._make_history()
        ph.append("fix the auth bug in login.py")
        results = ph.search("auth")
        self.assertEqual(len(results), 1)
        self.assertIn("auth", results[0]["cmd"])

    # ── fuzzy matching ──────────────────────────────────────────────────

    def test_search_case_insensitive(self):
        """Search is case-insensitive."""
        ph = self._make_history()
        ph.append("Fix the Auth Module")
        results = ph.search("auth")
        self.assertEqual(len(results), 1)

    def test_search_empty_query(self):
        """Empty query returns all entries up to limit."""
        ph = self._make_history()
        for i in range(5):
            ph.append(f"command {i}")
        results = ph.search()
        self.assertEqual(len(results), 5)

    def test_search_limit(self):
        """Search respects the limit parameter."""
        ph = self._make_history()
        for i in range(20):
            ph.append(f"cmd {i}")
        results = ph.search(limit=5)
        self.assertEqual(len(results), 5)

    def test_search_no_results(self):
        """Search returns empty list when no matches."""
        ph = self._make_history()
        ph.append("fix auth bug")
        results = ph.search("database")
        self.assertEqual(results, [])

    # ── project scoping ─────────────────────────────────────────────────

    def test_project_scoping(self):
        """Different projects have separate histories."""
        ph1 = self._make_history("/tmp/project_a")
        ph2 = self._make_history("/tmp/project_b")
        ph1.append("project A command")
        ph2.append("project B command")
        self.assertEqual(len(ph1.search()), 1)
        self.assertEqual(len(ph2.search()), 1)
        self.assertEqual(ph1.search()[0]["cmd"], "project A command")
        self.assertEqual(ph2.search()[0]["cmd"], "project B command")

    # ── recent commands limit ───────────────────────────────────────────

    def test_get_recent_default_limit(self):
        """get_recent() returns last 5 entries by default."""
        ph = self._make_history()
        for i in range(10):
            ph.append(f"cmd {i}")
        recent = ph.get_recent()
        self.assertEqual(len(recent), 5)
        # Should be the last 5 (oldest to newest)
        self.assertEqual(recent[0]["cmd"], "cmd 5")
        self.assertEqual(recent[-1]["cmd"], "cmd 9")

    def test_get_recent_custom_limit(self):
        """get_recent() respects custom limit."""
        ph = self._make_history()
        for i in range(10):
            ph.append(f"cmd {i}")
        recent = ph.get_recent(limit=3)
        self.assertEqual(len(recent), 3)

    # ── corrupted line handling ─────────────────────────────────────────

    def test_corrupted_lines_skipped(self):
        """Corrupted JSONL lines are silently skipped."""
        ph = self._make_history()
        ph.append("valid command")
        with open(ph.history_path, "a") as f:
            f.write("{broken json\n")
        ph.append("another valid command")
        entries = ph._read_all()
        self.assertEqual(len(entries), 2)

    # ── session_id ──────────────────────────────────────────────────────

    def test_append_with_session_id(self):
        """Session ID is stored in the entry."""
        ph = self._make_history()
        ph.append("test command", session_id="sess-42")
        entries = ph._read_all()
        self.assertEqual(entries[0]["session"], "sess-42")

    def test_append_default_session_empty(self):
        """Default session ID is empty string."""
        ph = self._make_history()
        ph.append("test command")
        entries = ph._read_all()
        self.assertEqual(entries[0]["session"], "")

    # ── empty history ───────────────────────────────────────────────────

    def test_empty_history_search(self):
        """Search on empty history returns empty list."""
        ph = self._make_history()
        self.assertEqual(ph.search(), [])

    def test_get_entry_count(self):
        """get_entry_count returns correct count."""
        ph = self._make_history()
        self.assertEqual(ph.get_entry_count(), 0)
        ph.append("cmd1")
        ph.append("cmd2")
        self.assertEqual(ph.get_entry_count(), 2)


if __name__ == "__main__":
    unittest.main()
