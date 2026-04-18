"""
EAA V4 Phase 6 — Comprehensive Test Suite
==========================================
Tests all public methods across error_handler, validation_hooks,
and concurrent_isolation modules.

Run with:
    python -m pytest test_phase6.py -v
    or
    python test_phase6.py
"""

import json
import os
import sys
import tempfile
import time
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

# Add the eaa_v4 root directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from error_handler import (
    RecoveryAction,
    RecoveryResult,
    ErrorHandler,
    create_error_handler,
)
from validation_hooks import (
    ValidationFailure,
    ValidationHook,
    PythonSyntaxHook,
    ValidationHookRegistry,
    HealingSpinner,
    create_validation_registry,
)
from concurrent_isolation import (
    TaskStatus,
    SiblingGroup,
    ConcurrentIsolationController,
    CRITICAL_ERROR_PATTERNS,
    create_isolation_controller,
    _is_critical_error,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ERROR HANDLER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestErrorHandler(unittest.TestCase):
    """Tests for ErrorHandler: 3-tier recovery, JSONDecodeError, prompt compaction."""

    def setUp(self):
        self.handler = ErrorHandler()

    def test_tier1_double_tokens(self):
        """Tier 1: finish_reason='length' → DOUBLE_TOKENS, should_retry=True."""
        result = self.handler.handle_truncation("truncated...", "length")
        self.assertEqual(result.action, RecoveryAction.DOUBLE_TOKENS)
        self.assertEqual(result.tier_reached, 1)
        self.assertTrue(result.should_retry)
        self.assertIsNone(result.error)
        self.assertEqual(self.handler.tier, 1)

    def test_tier2_inject_continuation(self):
        """Tier 2: After tier 1, → INJECT_CONTINUATION with continuation prompt."""
        # First call sets tier to 1
        self.handler.handle_truncation("truncated...", "length")
        # Second call → tier 2
        result = self.handler.handle_truncation("truncated...", "length")
        self.assertEqual(result.action, RecoveryAction.INJECT_CONTINUATION)
        self.assertEqual(result.tier_reached, 2)
        self.assertTrue(result.should_retry)
        self.assertIn("[CONTINUATION REQUIRED]", result.content)

    def test_tier3_abort(self):
        """Tier 3: After tier 2, → ABORT with error message."""
        self.handler.handle_truncation("truncated...", "length")  # tier 1
        self.handler.handle_truncation("truncated...", "length")  # tier 2
        # Third call → tier 3
        result = self.handler.handle_truncation("truncated...", "length")
        self.assertEqual(result.action, RecoveryAction.ABORT)
        self.assertEqual(result.tier_reached, 3)
        self.assertFalse(result.should_retry)
        self.assertIsNotNone(result.error)
        self.assertIn("Escalating to Master", result.error)

    def test_finish_reason_stop_no_recovery(self):
        """finish_reason='stop' → no recovery needed, tier resets."""
        self.handler.tier = 1  # Pretend we're mid-recovery
        result = self.handler.handle_truncation("complete output", "stop")
        self.assertEqual(result.action, RecoveryAction.ABORT)
        self.assertEqual(result.tier_reached, 0)
        self.assertFalse(result.should_retry)
        self.assertEqual(self.handler.tier, 0)  # tier was reset

    def test_finish_reason_end_turn_no_recovery(self):
        """finish_reason='end_turn' → no recovery."""
        result = self.handler.handle_truncation("done", "end_turn")
        self.assertFalse(result.should_retry)
        self.assertEqual(self.handler.tier, 0)

    def test_handle_prompt_too_long_no_context_manager(self):
        """Without ContextManager, falls back to keeping system + last 3."""
        messages = [
            {"role": "system", "content": "You are Jarvis."},
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "resp1"},
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "resp2"},
            {"role": "user", "content": "msg3"},
            {"role": "assistant", "content": "resp3"},
            {"role": "user", "content": "msg4"},
            {"role": "assistant", "content": "resp4"},
        ]
        result = self.handler.handle_prompt_too_long(messages)
        # Should keep system + last 3 non-system messages
        self.assertEqual(len(result), 4)  # 1 system + 3 non-system
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(result[-1]["content"], "resp4")

    def test_handle_prompt_too_long_with_context_manager(self):
        """With ContextManager, uses the cascade for compaction."""
        mock_cm = MagicMock()
        mock_cm.evaluate_cascade.return_value = MagicMock(tokens_saved=5000)
        mock_cm.get_context_for_model.return_value = [
            {"role": "system", "content": "compacted"},
            {"role": "user", "content": "last msg"},
        ]
        handler = ErrorHandler(context_manager=mock_cm)
        messages = [{"role": "user", "content": "msg"}] * 50
        result = handler.handle_prompt_too_long(messages)
        mock_cm.evaluate_cascade.assert_called_once()
        mock_cm.get_context_for_model.assert_called_once()
        self.assertEqual(len(result), 2)

    def test_handle_prompt_too_long_context_manager_exception(self):
        """If ContextManager raises, falls back to manual truncation."""
        mock_cm = MagicMock()
        mock_cm.evaluate_cascade.side_effect = RuntimeError("cascade failed")
        handler = ErrorHandler(context_manager=mock_cm)
        messages = [
            {"role": "user", "content": f"msg{i}"} for i in range(10)
        ]
        result = handler.handle_prompt_too_long(messages)
        # Fallback: system (0) + last 3 non-system
        self.assertLessEqual(len(result), 3)

    def test_wrap_error_as_tool_result_string(self):
        """Wraps a string error as is_error: true tool result."""
        result = self.handler.wrap_error_as_tool_result("file not found", "read_file")
        self.assertEqual(result["role"], "tool")
        self.assertTrue(result["is_error"])
        self.assertIn("[is_error: true]", result["content"])
        self.assertIn("read_file", result["content"])
        self.assertIn("file not found", result["content"])

    def test_wrap_error_as_tool_result_exception(self):
        """Wraps an Exception as is_error: true tool result."""
        result = self.handler.wrap_error_as_tool_result(
            FileNotFoundError("no such file"), "write_file"
        )
        self.assertTrue(result["is_error"])
        self.assertIn("write_file", result["content"])
        self.assertIn("no such file", result["content"])

    def test_wrap_error_as_tool_result_none(self):
        """Wraps None error as 'Unknown error'."""
        result = self.handler.wrap_error_as_tool_result(None, "shell")
        self.assertIn("Unknown error", result["content"])

    def test_intercept_json_decode_valid_json(self):
        """Valid JSON returns parsed dict, no tier increment."""
        self.handler.tier = 0
        raw = '{"tool": "read_file", "args": {"path": "/tmp/test.py"}}'
        result = self.handler.intercept_json_decode(raw, "read_file")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["tool"], "read_file")
        self.assertEqual(self.handler.tier, 0)  # No increment

    def test_intercept_json_decode_invalid_json(self):
        """Invalid JSON wraps as is_error: true and increments tier."""
        self.handler.tier = 0
        raw = '{"tool": "read_file", "args": {broken json'
        result = self.handler.intercept_json_decode(raw, "read_file")
        self.assertEqual(result["role"], "tool")
        self.assertTrue(result["is_error"])
        self.assertIn("JSON parse error", result["content"])
        self.assertEqual(self.handler.tier, 1)  # Tier incremented

    def test_intercept_json_decode_truncates_long_output(self):
        """Raw output > 200 chars gets truncated in error message."""
        long_raw = '{"tool": "read_file", "args": {"path": "' + "x" * 300 + '"}}'
        result = self.handler.intercept_json_decode(long_raw + "broken", "read_file")
        # The content should contain the truncated raw output
        self.assertIn("...", result["content"])

    def test_reset_tier(self):
        """reset_tier() sets tier back to 0."""
        self.handler.tier = 3
        self.handler.reset_tier()
        self.assertEqual(self.handler.tier, 0)

    def test_get_current_max_tokens(self):
        """get_current_max_tokens doubles at each tier."""
        self.assertEqual(self.handler.get_current_max_tokens(), 2048)
        self.handler.tier = 1
        self.assertEqual(self.handler.get_current_max_tokens(), 4096)
        self.handler.tier = 2
        self.assertEqual(self.handler.get_current_max_tokens(), 8192)
        self.handler.tier = 3
        self.assertEqual(self.handler.get_current_max_tokens(), 16384)

    def test_is_exhausted(self):
        """is_exhausted returns True when tier >= max_tiers."""
        self.assertFalse(self.handler.is_exhausted())
        self.handler.tier = 1
        self.assertFalse(self.handler.is_exhausted())
        self.handler.tier = 2
        self.assertFalse(self.handler.is_exhausted())
        self.handler.tier = 3
        self.assertTrue(self.handler.is_exhausted())

    def test_recovery_result_to_dict(self):
        """RecoveryResult.to_dict() produces correct structure."""
        result = RecoveryResult(
            action=RecoveryAction.DOUBLE_TOKENS,
            content="test content",
            tier_reached=1,
            should_retry=True,
        )
        d = result.to_dict()
        self.assertEqual(d["action"], "double_tokens")
        self.assertEqual(d["tier_reached"], 1)
        self.assertTrue(d["should_retry"])
        self.assertIsNone(d["error"])

    def test_recovery_result_to_dict_truncates_long_content(self):
        """to_dict() truncates content > 200 chars."""
        result = RecoveryResult(
            action=RecoveryAction.ABORT,
            content="x" * 300,
            tier_reached=3,
            should_retry=False,
        )
        d = result.to_dict()
        self.assertTrue(d["content"].endswith("..."))

    def test_create_error_handler(self):
        """Factory function creates ErrorHandler instance."""
        handler = create_error_handler()
        self.assertIsInstance(handler, ErrorHandler)
        self.assertEqual(handler.tier, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. VALIDATION HOOKS TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPythonSyntaxHook(unittest.TestCase):
    """Tests for PythonSyntaxHook: py_compile success/failure, non-Python skip."""

    def setUp(self):
        self.hook = PythonSyntaxHook()

    def test_valid_python_file(self):
        """Valid Python file returns None (no failure)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("x = 42\nprint(x)\n")
            path = f.name
        try:
            result = self.hook.validate("write_file", path, None)
            self.assertIsNone(result)
        finally:
            os.unlink(path)

    def test_invalid_python_syntax(self):
        """Python file with syntax error returns ValidationFailure."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("def foo(\n")  # Incomplete function
            path = f.name
        try:
            result = self.hook.validate("write_file", path, None)
            self.assertIsNotNone(result)
            self.assertIsInstance(result, ValidationFailure)
            self.assertEqual(result.tool_name, "write_file")
            self.assertEqual(result.file_path, path)
            self.assertTrue(len(result.stderr) > 0)
        finally:
            os.unlink(path)

    def test_non_python_file_skipped(self):
        """Non-.py files are skipped (returns None)."""
        result = self.hook.validate("write_file", "/tmp/test.txt", None)
        self.assertIsNone(result)

    def test_non_python_js_skipped(self):
        """Non-.py files like .js are skipped."""
        result = self.hook.validate("write_file", "/tmp/app.js", None)
        self.assertIsNone(result)

    def test_nonexistent_file_returns_failure(self):
        """Nonexistent file returns a ValidationFailure."""
        result = self.hook.validate("write_file", "/tmp/nonexistent_file_xyz.py", None)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, ValidationFailure)


class TestValidationHookRegistry(unittest.TestCase):
    """Tests for ValidationHookRegistry: register, run_hooks, _wrap_as_error."""

    def setUp(self):
        self.registry = ValidationHookRegistry()

    def test_register_and_list(self):
        """Registering a hook makes it appear in get_registered_hooks."""
        hook = PythonSyntaxHook()
        self.registry.register("write_file", hook)
        names = self.registry.get_registered_hooks("write_file")
        self.assertEqual(names, ["PythonSyntaxHook"])

    def test_register_multiple_hooks(self):
        """Multiple hooks for same tool are registered in order."""
        hook1 = PythonSyntaxHook()
        hook2 = PythonSyntaxHook()
        self.registry.register("write_file", hook1)
        self.registry.register("write_file", hook2)
        names = self.registry.get_registered_hooks("write_file")
        self.assertEqual(len(names), 2)

    def test_unregister_all(self):
        """Unregister with no class removes all hooks for a tool."""
        self.registry.register("write_file", PythonSyntaxHook())
        self.registry.register("write_file", PythonSyntaxHook())
        removed = self.registry.unregister("write_file")
        self.assertEqual(removed, 2)
        self.assertEqual(self.registry.get_registered_hooks("write_file"), [])

    def test_unregister_specific_class(self):
        """Unregister with class only removes hooks of that class."""
        class DummyHook(ValidationHook):
            def validate(self, tool_name, file_path, result):
                return None

        self.registry.register("write_file", PythonSyntaxHook())
        self.registry.register("write_file", DummyHook())
        removed = self.registry.unregister("write_file", PythonSyntaxHook)
        self.assertEqual(removed, 1)
        names = self.registry.get_registered_hooks("write_file")
        self.assertEqual(names, ["DummyHook"])

    def test_run_hooks_no_hooks_registered(self):
        """Running hooks for unregistered tool returns None."""
        result = self.registry.run_hooks("shell", "/tmp/test.py", None)
        self.assertIsNone(result)

    def test_run_hooks_all_pass(self):
        """All hooks passing returns None."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("x = 1\n")
            path = f.name
        try:
            self.registry.register("write_file", PythonSyntaxHook())
            result = self.registry.run_hooks("write_file", path, None)
            self.assertIsNone(result)
        finally:
            os.unlink(path)

    def test_run_hooks_failure_short_circuits(self):
        """First failing hook short-circuits and returns error."""
        call_order = []

        class AlwaysFailHook(ValidationHook):
            def validate(self, tool_name, file_path, result):
                call_order.append("fail")
                return ValidationFailure(
                    tool_name=tool_name,
                    file_path=file_path,
                    stderr="Always fails",
                )

        class NeverReachedHook(ValidationHook):
            def validate(self, tool_name, file_path, result):
                call_order.append("never_reached")
                return None

        self.registry.register("edit_file", AlwaysFailHook())
        self.registry.register("edit_file", NeverReachedHook())
        result = self.registry.run_hooks("edit_file", "/tmp/test.py", None)

        self.assertIsNotNone(result)
        self.assertTrue(result["is_error"])
        self.assertEqual(call_order, ["fail"])  # Second hook never called

    def test_run_hooks_exception_caught(self):
        """Hook that raises an exception is caught and wrapped as error."""
        class CrashingHook(ValidationHook):
            def validate(self, tool_name, file_path, result):
                raise RuntimeError("hook crashed!")

        self.registry.register("edit_file", CrashingHook())
        result = self.registry.run_hooks("edit_file", "/tmp/test.py", None)

        self.assertIsNotNone(result)
        self.assertTrue(result["is_error"])
        self.assertIn("hook crashed!", result["content"])

    def test_wrap_as_error_format(self):
        """_wrap_as_error produces correct is_error: true format."""
        failure = ValidationFailure(
            tool_name="write_file",
            file_path="/tmp/test.py",
            stderr="SyntaxError: invalid syntax",
        )
        result = self.registry._wrap_as_error(failure)
        self.assertEqual(result["role"], "tool")
        self.assertTrue(result["is_error"])
        self.assertIn("[is_error: true]", result["content"])
        self.assertIn("write_file", result["content"])
        self.assertIn("/tmp/test.py", result["content"])
        self.assertIn("validation_failure", result)

    def test_create_validation_registry(self):
        """Factory function pre-registers hooks."""
        hooks = {
            "write_file": [PythonSyntaxHook()],
            "edit_file": [PythonSyntaxHook()],
        }
        registry = create_validation_registry(hooks)
        self.assertEqual(
            len(registry.get_registered_hooks("write_file")), 1
        )
        self.assertEqual(
            len(registry.get_registered_hooks("edit_file")), 1
        )
        self.assertEqual(
            len(registry.get_registered_hooks("shell")), 0
        )


class TestValidationFailure(unittest.TestCase):
    """Tests for ValidationFailure dataclass."""

    def test_to_dict(self):
        """to_dict() produces correct structure."""
        failure = ValidationFailure(
            tool_name="write_file",
            file_path="/tmp/test.py",
            stderr="SyntaxError: invalid syntax on line 1",
        )
        d = failure.to_dict()
        self.assertEqual(d["tool_name"], "write_file")
        self.assertEqual(d["file_path"], "/tmp/test.py")
        self.assertEqual(d["stderr"], "SyntaxError: invalid syntax on line 1")

    def test_to_dict_truncates_long_stderr(self):
        """to_dict() truncates stderr > 500 chars."""
        failure = ValidationFailure(
            tool_name="write_file",
            file_path="/tmp/test.py",
            stderr="E" * 600,
        )
        d = failure.to_dict()
        self.assertTrue(d["stderr"].endswith("..."))


# ═══════════════════════════════════════════════════════════════════════════════
# 3. HEALING SPINNER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealingSpinner(unittest.TestCase):
    """Tests for HealingSpinner: start/stop, success/fail messages."""

    def test_start_and_stop_success(self):
        """Spinner starts, stops, and writes success message."""
        spinner = HealingSpinner("coder", max_attempts=3)

        # Mock stderr to capture output
        with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
            spinner.start(attempt=1)
            time.sleep(0.3)  # Let spinner run a few frames
            spinner.stop(success=True)

            output = mock_stderr.getvalue()
            self.assertIn("[OK]", output)
            self.assertIn("coder", output)
            self.assertIn("Attempt 1/3", output)

    def test_start_and_stop_failure(self):
        """Spinner stop with success=False writes failure/escalation message."""
        spinner = HealingSpinner("shadow", max_attempts=5)

        with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
            spinner.start(attempt=3)
            time.sleep(0.3)
            spinner.stop(success=False)

            output = mock_stderr.getvalue()
            self.assertIn("[FAIL]", output)
            self.assertIn("Escalating to Master", output)
            self.assertIn("5 attempts", output)

    def test_is_spinning(self):
        """is_spinning returns correct state."""
        spinner = HealingSpinner("analyst", max_attempts=2)

        with patch("sys.stderr", new_callable=StringIO):
            self.assertFalse(spinner.is_spinning)
            spinner.start(attempt=1)
            self.assertTrue(spinner.is_spinning)
            spinner.stop(success=True)
            self.assertFalse(spinner.is_spinning)

    def test_braille_chars_defined(self):
        """BRAILLE_CHARS should have 8 entries."""
        self.assertEqual(len(HealingSpinner.BRAILLE_CHARS), 8)

    def test_multiple_start_stop_cycles(self):
        """Spinner can be started and stopped multiple times."""
        spinner = HealingSpinner("coder", max_attempts=3)

        with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
            for attempt in range(1, 4):
                spinner.start(attempt=attempt)
                time.sleep(0.15)
                spinner.stop(success=(attempt < 3))

            output = mock_stderr.getvalue()
            # Should have 2 [OK] and 1 [FAIL]
            ok_count = output.count("[OK]")
            fail_count = output.count("[FAIL]")
            self.assertEqual(ok_count, 2)
            self.assertEqual(fail_count, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CONCURRENT ISOLATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestConcurrentIsolation(unittest.TestCase):
    """Tests for ConcurrentIsolationController: batch, failure, cancellation."""

    def setUp(self):
        self.controller = ConcurrentIsolationController()

    def _make_tasks(self, count=3):
        """Create mock DelegationTask-like objects for testing."""
        tasks = []
        for i in range(count):
            task = MagicMock()
            task.tool_name = f"tool_{i}"
            task.priority = i
            tasks.append(task)
        return tasks

    def test_register_batch(self):
        """Registering a batch creates a sibling group with correct task count."""
        tasks = self._make_tasks(3)
        group_id = self.controller.register_batch(tasks)

        self.assertIsNotNone(group_id)
        self.assertIn("batch_", group_id)

        status = self.controller.get_group_status(group_id)
        self.assertIsNotNone(status)
        self.assertEqual(status["pending_count"], 3)
        self.assertEqual(len(status["task_ids"]), 3)

    def test_register_batch_with_dicts(self):
        """Batch can also accept dicts with tool_name key."""
        tasks = [
            {"tool_name": "read_file"},
            {"tool_name": "write_file"},
        ]
        group_id = self.controller.register_batch(tasks)
        status = self.controller.get_group_status(group_id)
        self.assertEqual(status["pending_count"], 2)

    def test_report_completion(self):
        """Reporting completion moves task from PENDING to COMPLETED."""
        tasks = self._make_tasks(2)
        group_id = self.controller.register_batch(tasks)

        task_id = "tool_0_0"
        self.controller.report_completion(group_id, task_id)

        status = self.controller.get_group_status(group_id)
        self.assertEqual(status["completed_count"], 1)
        self.assertEqual(status["pending_count"], 1)
        self.assertEqual(status["status"][task_id], "completed")

    def test_report_failure_non_critical(self):
        """Non-critical failure only affects the failed task."""
        tasks = self._make_tasks(3)
        group_id = self.controller.register_batch(tasks)

        self.controller.report_failure(
            group_id, "tool_1_1", "File not found", critical=False
        )

        status = self.controller.get_group_status(group_id)
        self.assertEqual(status["failed_count"], 1)
        self.assertEqual(status["pending_count"], 2)
        # Siblings should NOT be cancelled
        self.assertEqual(status["cancelled_count"], 0)
        self.assertIsNone(status["critical_error"])

    def test_report_failure_critical_cancels_siblings(self):
        """Critical failure cancels all remaining siblings."""
        tasks = self._make_tasks(4)
        group_id = self.controller.register_batch(tasks)

        # Complete one task
        self.controller.report_completion(group_id, "tool_0_0")
        # Critically fail another
        self.controller.report_failure(
            group_id, "tool_1_1", "CUDA out of memory", critical=True
        )

        status = self.controller.get_group_status(group_id)
        self.assertEqual(status["failed_count"], 1)
        self.assertEqual(status["completed_count"], 1)
        # Remaining 2 should be cancelled
        self.assertEqual(status["cancelled_count"], 2)
        self.assertIsNotNone(status["critical_error"])
        self.assertIn("CUDA out of memory", status["critical_error"])

    def test_check_cancelled_false(self):
        """Non-cancelled task returns False."""
        tasks = self._make_tasks(2)
        group_id = self.controller.register_batch(tasks)

        self.assertFalse(self.controller.check_cancelled("tool_0_0"))
        self.assertFalse(self.controller.check_cancelled("tool_1_1"))

    def test_check_cancelled_true_after_critical(self):
        """Cancelled task returns True after critical failure."""
        tasks = self._make_tasks(3)
        group_id = self.controller.register_batch(tasks)

        self.controller.report_failure(
            group_id, "tool_0_0", "OOM", critical=True
        )

        # Failed task itself should NOT be in cancelled set
        self.assertFalse(self.controller.check_cancelled("tool_0_0"))
        # But siblings should be
        self.assertTrue(self.controller.check_cancelled("tool_1_1"))
        self.assertTrue(self.controller.check_cancelled("tool_2_2"))

    def test_check_cancelled_unknown_task(self):
        """Unknown task returns False."""
        self.assertFalse(self.controller.check_cancelled("nonexistent"))

    def test_cleanup_group(self):
        """Cleaning up removes group and clears cancelled tasks."""
        tasks = self._make_tasks(2)
        group_id = self.controller.register_batch(tasks)

        self.controller.report_failure(
            group_id, "tool_0_0", "OOM", critical=True
        )
        self.assertTrue(self.controller.check_cancelled("tool_1_1"))

        self.controller.cleanup_group(group_id)

        # Group should be gone
        self.assertIsNone(self.controller.get_group_status(group_id))
        # Cancelled tasks should be cleared
        self.assertFalse(self.controller.check_cancelled("tool_1_1"))

    def test_cleanup_unknown_group_no_error(self):
        """Cleaning up unknown group doesn't raise."""
        self.controller.cleanup_group("nonexistent_group")

    def test_is_group_finished_all_completed(self):
        """Group is finished when all tasks are completed."""
        tasks = self._make_tasks(2)
        group_id = self.controller.register_batch(tasks)

        self.controller.report_completion(group_id, "tool_0_0")
        self.assertFalse(self.controller.is_group_finished(group_id))

        self.controller.report_completion(group_id, "tool_1_1")
        self.assertTrue(self.controller.is_group_finished(group_id))

    def test_is_group_finished_after_critical(self):
        """Group is finished after critical failure (all cancelled)."""
        tasks = self._make_tasks(2)
        group_id = self.controller.register_batch(tasks)

        self.controller.report_failure(
            group_id, "tool_0_0", "fatal", critical=True
        )
        self.assertTrue(self.controller.is_group_finished(group_id))

    def test_is_group_finished_unknown_group(self):
        """Unknown group is considered finished."""
        self.assertTrue(self.controller.is_group_finished("nonexistent"))

    def test_get_stats(self):
        """get_stats returns correct summary."""
        tasks = self._make_tasks(2)
        self.controller.register_batch(tasks)

        stats = self.controller.get_stats()
        self.assertEqual(stats["active_groups"], 1)
        self.assertEqual(stats["total_cancelled_tasks"], 0)

    def test_report_completion_unknown_group(self):
        """Reporting completion for unknown group doesn't raise."""
        self.controller.report_completion("nonexistent", "task_1")

    def test_report_failure_unknown_group(self):
        """Reporting failure for unknown group doesn't raise."""
        self.controller.report_failure("nonexistent", "task_1", "error")

    def test_report_failure_unknown_task(self):
        """Reporting failure for unknown task doesn't raise."""
        tasks = self._make_tasks(1)
        group_id = self.controller.register_batch(tasks)
        self.controller.report_failure(
            group_id, "nonexistent_task", "error"
        )

    def test_create_isolation_controller(self):
        """Factory function creates controller instance."""
        controller = create_isolation_controller()
        self.assertIsInstance(controller, ConcurrentIsolationController)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. INTEGRATION / CROSS-MODULE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossModuleIntegration(unittest.TestCase):
    """Integration tests combining multiple Phase 6 components."""

    def test_error_handler_intercept_json_then_truncation_tier_carryover(self):
        """JSONDecodeError increments tier, affecting subsequent truncation."""
        handler = ErrorHandler()

        # JSON decode failure increments tier to 1
        handler.intercept_json_decode("not json at all", "read_file")
        self.assertEqual(handler.tier, 1)

        # Next truncation call should be at tier 2 (inject continuation)
        result = handler.handle_truncation("truncated...", "length")
        self.assertEqual(result.tier_reached, 2)
        self.assertEqual(result.action, RecoveryAction.INJECT_CONTINUATION)

    def test_validation_failure_wrapped_same_as_error_handler(self):
        """ValidationHookRegistry._wrap_as_error produces same format as ErrorHandler."""
        registry = ValidationHookRegistry()
        handler = ErrorHandler()

        # Compare formats
        failure = ValidationFailure(
            tool_name="write_file",
            file_path="/tmp/test.py",
            stderr="SyntaxError",
        )
        validation_result = registry._wrap_as_error(failure)
        error_result = handler.wrap_error_as_tool_result(
            "Validation failed for /tmp/test.py\nSyntaxError",
            "write_file",
        )

        self.assertEqual(validation_result["role"], error_result["role"])
        self.assertEqual(validation_result["is_error"], error_result["is_error"])
        self.assertIn("[is_error: true]", validation_result["content"])
        self.assertIn("[is_error: true]", error_result["content"])

    def test_full_self_healing_flow(self):
        """Simulate: edit → syntax error → validation failure → retry → success."""
        registry = ValidationHookRegistry()
        registry.register("write_file", PythonSyntaxHook())
        handler = ErrorHandler()
        spinner = HealingSpinner("coder", max_attempts=2)

        # Attempt 1: Write invalid Python
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("def broken(\n")  # Syntax error
            path = f.name

        try:
            # Validation catches the syntax error
            failure_result = registry.run_hooks("write_file", path, None)
            self.assertIsNotNone(failure_result)
            self.assertTrue(failure_result["is_error"])

            # Start spinner for self-correction
            with patch("sys.stderr", new_callable=StringIO):
                spinner.start(attempt=1)

                # Simulate correction: fix the file
                with open(path, "w") as f:
                    f.write("def fixed():\n    return 42\n")

                # Re-validate
                retry_result = registry.run_hooks("write_file", path, None)
                self.assertIsNone(retry_result)  # Fixed!

                spinner.stop(success=True)

            # Verify tier was not affected by validation
            self.assertEqual(handler.tier, 0)
        finally:
            os.unlink(path)


class TestCriticalErrorPatterns(unittest.TestCase):
    """Tests for the _is_critical_error helper function."""

    def test_oom_is_critical(self):
        self.assertTrue(_is_critical_error("CUDA out of memory"))
        self.assertTrue(_is_critical_error("OOM error occurred"))
        self.assertTrue(_is_critical_error("Process ran out of memory"))

    def test_cuda_error_is_critical(self):
        self.assertTrue(_is_critical_error("CUDA runtime error"))
        self.assertTrue(_is_critical_error("cuda error: device assert"))

    def test_segfault_is_critical(self):
        self.assertTrue(_is_critical_error("Segmentation fault (core dumped)"))
        self.assertTrue(_is_critical_error("segfault at address 0x0"))

    def test_non_critical_errors(self):
        self.assertFalse(_is_critical_error("File not found"))
        self.assertFalse(_is_critical_error("Permission denied"))
        self.assertFalse(_is_critical_error("Invalid argument"))
        self.assertFalse(_is_critical_error("Connection refused"))

    def test_empty_string_not_critical(self):
        self.assertFalse(_is_critical_error(""))
        self.assertFalse(_is_critical_error("   "))


class TestSiblingGroup(unittest.TestCase):
    """Tests for SiblingGroup dataclass."""

    def test_to_dict(self):
        """to_dict() produces correct structure."""
        group = SiblingGroup(
            group_id="test_group",
            task_ids=["task_1", "task_2"],
            status={
                "task_1": TaskStatus.COMPLETED,
                "task_2": TaskStatus.PENDING,
            },
        )
        d = group.to_dict()
        self.assertEqual(d["group_id"], "test_group")
        self.assertEqual(d["task_ids"], ["task_1", "task_2"])
        self.assertEqual(d["status"]["task_1"], "completed")
        self.assertEqual(d["status"]["task_2"], "pending")
        self.assertEqual(d["completed_count"], 1)
        self.assertEqual(d["pending_count"], 1)
        self.assertEqual(d["cancelled_count"], 0)

    def test_default_values(self):
        """Default values are sensible."""
        group = SiblingGroup(group_id="default_test")
        self.assertEqual(group.group_id, "default_test")
        self.assertEqual(group.task_ids, [])
        self.assertEqual(group.status, {})
        self.assertIsNone(group.critical_error)
        self.assertGreater(group.created_at, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
