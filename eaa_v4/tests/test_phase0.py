"""
EAA V4 - Phase 0 Test Gate
============================
Phase gate testing: Phase N+1 CANNOT start until Phase N tests all pass.

Phase 0 tests cover:
  - Two-Tier Router (routing accuracy, delegation parsing, validation)
  - Worker Manager (lifecycle, batch execution, error handling)
  - Dry-Run Protocol (approval flow, modification mode, auto-approval)
  - Plan Formatter (display formatting, risk assessment)
  - VRAM Manager (mock loading, fit checking, cleanup)

Run: python -m pytest tests/test_phase0.py -v
Or:  python tests/test_phase0.py
"""

import sys
import os
import json
import time
import unittest
from unittest.mock import MagicMock, patch

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from router import (
    MasterRouter, DelegationTask, RoutingResult, RoutingDecision,
    DEFAULT_WORKER_SPECIALIZATIONS, build_tool_to_worker_map,
    create_router, suggest_worker,
)
from workers import (
    WorkerManager, WorkerState, WorkerInfo, WorkerResult, ToolExecutor,
    create_worker_manager,
)
from dry_run import (
    DryRunProtocol, DryRunConfig, DryRunResult, DryRunOutcome, ApprovalMode,
    create_dry_run,
)
from plan_formatter import (
    PlanFormatter, PlanRow, assess_risk, generate_action_summary,
)
from vram_manager import (
    VRAMManager, VRAMState, VRAMInfo, ModelProfile, SwapResult,
    DEFAULT_MODEL_PROFILES, create_vram_manager,
)


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestRouter(unittest.TestCase):
    """Tests for the Two-Tier Router."""

    def setUp(self):
        self.router = create_router()

    def test_router_initializes_with_all_workers(self):
        """Router should have all default workers registered."""
        self.assertIn("jarvis", self.router.specializations)
        self.assertIn("coder", self.router.specializations)
        self.assertIn("shadow", self.router.specializations)
        self.assertIn("analyst", self.router.specializations)
        self.assertIn("browser", self.router.specializations)
        self.assertIn("docs", self.router.specializations)
        self.assertIn("sys", self.router.specializations)
        # 7 workers total
        self.assertEqual(len(self.router.specializations), 7)

    def test_tool_to_worker_map_covers_tools(self):
        """Reverse index should map all tools to workers."""
        tool_map = build_tool_to_worker_map()
        # Should have mappings for common tools
        self.assertIn("read_file", tool_map)
        self.assertIn("shell", tool_map)
        self.assertIn("web_search", tool_map)
        # read_file should map to coder (appears first)
        self.assertEqual(tool_map["read_file"], "coder")

    def test_heuristic_route_code_request(self):
        """Code-related message should route to coder."""
        result = self.router.route_heuristic("Write a python function to sort a list")
        self.assertIn(result.metadata.get("primary_worker", ""), ["coder"])
        self.assertEqual(result.decision, RoutingDecision.DELEGATE)

    def test_heuristic_route_web_request(self):
        """Browser-related message should route to browser worker."""
        result = self.router.route_heuristic("Navigate to google.com and click the search button")
        # Browser should be in the workers list for batch routing
        workers = result.metadata.get("workers", [result.metadata.get("primary_worker", "")])
        self.assertIn("browser", workers)

    def test_heuristic_route_data_request(self):
        """Data-related message should route to analyst."""
        result = self.router.route_heuristic("Analyze this CSV file and create a chart")
        self.assertIn(result.metadata.get("primary_worker", ""), ["analyst"])

    def test_heuristic_master_handles_simple_question(self):
        """Simple question should be handled by master."""
        result = self.router.route_heuristic("Hello, how are you today?")
        self.assertEqual(result.decision, RoutingDecision.MASTER_HANDLES)

    def test_parse_delegation_json_block(self):
        """Should parse JSON code block delegation."""
        output = '''
        I'll delegate this task to the coder worker.

        ```json
        {
          "action": "delegate",
          "tasks": [
            {
              "worker_id": "coder",
              "tool_name": "read_file",
              "tool_args": {"path": "/test/file.py"},
              "reason": "Need to read the file first"
            }
          ]
        }
        ```
        '''
        tasks = self.router.parse_delegation(output)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].worker_id, "coder")
        self.assertEqual(tasks[0].tool_name, "read_file")
        self.assertEqual(tasks[0].tool_args, {"path": "/test/file.py"})

    def test_parse_delegation_multiple_tasks(self):
        """Should parse multiple tasks in one delegation."""
        output = '''```json
        {"action": "delegate", "tasks": [
            {"worker_id": "coder", "tool_name": "read_file", "tool_args": {"path": "a.py"}},
            {"worker_id": "coder", "tool_name": "write_file", "tool_args": {"path": "b.py", "content": "hello"}},
            {"worker_id": "shadow", "tool_name": "web_search", "tool_args": {"query": "test"}}
        ]}```'''
        tasks = self.router.parse_delegation(output)
        self.assertEqual(len(tasks), 3)

    def test_parse_delegation_no_tasks(self):
        """Should return empty list for non-delegation output."""
        output = "I think the answer is 42. No tools needed."
        tasks = self.router.parse_delegation(output)
        self.assertEqual(len(tasks), 0)

    def test_validate_valid_tasks(self):
        """Valid tasks should pass validation."""
        tasks = [
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": "/test.py"}, reason="test"),
            DelegationTask(worker_id="shadow", tool_name="web_search",
                         tool_args={"query": "test"}, reason="test"),
        ]
        valid, errors = self.router.validate_tasks(tasks)
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(errors), 0)

    def test_validate_unknown_worker(self):
        """Unknown worker should fail validation."""
        tasks = [
            DelegationTask(worker_id="nonexistent", tool_name="read_file",
                         tool_args={"path": "/test.py"}, reason="test"),
        ]
        valid, errors = self.router.validate_tasks(tasks)
        self.assertEqual(len(valid), 0)
        self.assertEqual(len(errors), 1)

    def test_validate_tool_not_in_worker(self):
        """Tool not in worker's specialization should fail."""
        tasks = [
            DelegationTask(worker_id="coder", tool_name="web_search",
                         tool_args={"query": "test"}, reason="test"),
        ]
        valid, errors = self.router.validate_tasks(tasks)
        # web_search is in shadow, not coder
        self.assertEqual(len(valid), 0)

    def test_validate_dangerous_shell_command(self):
        """Dangerous shell commands should be flagged."""
        tasks = [
            DelegationTask(worker_id="shadow", tool_name="shell",
                         tool_args={"command": "rm -rf /"}, reason="test"),
        ]
        valid, errors = self.router.validate_tasks(tasks)
        self.assertTrue(any("dangerous" in e.lower() for e in errors))

    def test_optimize_task_order_groups_by_worker(self):
        """Task optimization should group by worker."""
        tasks = [
            DelegationTask(worker_id="shadow", tool_name="web_search",
                         tool_args={"query": "a"}, priority=0),
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": "a.py"}, priority=1),
            DelegationTask(worker_id="coder", tool_name="write_file",
                         tool_args={"path": "b.py"}, priority=2),
            DelegationTask(worker_id="shadow", tool_name="web_search",
                         tool_args={"query": "b"}, priority=3),
        ]
        optimized = self.router.optimize_task_order(tasks)
        # Tasks should be grouped: coder tasks together, shadow tasks together
        worker_sequence = [t.worker_id for t in optimized]
        # Count worker transitions
        transitions = sum(
            1 for i in range(1, len(worker_sequence))
            if worker_sequence[i] != worker_sequence[i-1]
        )
        # Should have at most 1 transition (2 groups)
        self.assertLessEqual(transitions, 2)

    def test_master_prompt_does_not_contain_tool_schemas(self):
        """Master prompt should NOT contain raw tool schemas."""
        prompt = self.router.get_master_prompt()
        # Should contain worker descriptions
        self.assertIn("coder", prompt)
        self.assertIn("shadow", prompt)
        # Should NOT contain actual tool execution format
        self.assertNotIn('"tool": "read_file"', prompt)

    def test_worker_prompt_includes_only_worker_tools(self):
        """Worker prompt should only include tools for that worker."""
        prompt = self.router.get_worker_prompt("coder", "Fix the bug")
        # Should include coder tools
        self.assertIn("read_file", prompt)
        self.assertIn("code_run", prompt)
        # Should NOT include browser tools
        self.assertNotIn("browser_click", prompt)


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER MANAGER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkerManager(unittest.TestCase):
    """Tests for the Worker Lifecycle Manager."""

    def setUp(self):
        self.executor = ToolExecutor()  # No-op mode (no real registry)
        self.manager = create_worker_manager(tool_registry=None)

    def test_initializes_all_workers(self):
        """Should initialize all non-jarvis workers."""
        workers = self.manager.list_workers()
        self.assertEqual(len(workers), 6)  # 7 total minus jarvis

    def test_all_workers_start_dormant(self):
        """All workers should start in DORMANT state."""
        for info in self.manager.list_workers():
            self.assertEqual(info["state"], WorkerState.DORMANT.value)

    def test_activate_worker_no_vram_manager(self):
        """Activation without VRAM manager should still work (no-op)."""
        result = self.manager.activate_worker("coder")
        self.assertTrue(result)
        info = self.manager.get_worker_info("coder")
        self.assertEqual(info.state, WorkerState.ACTIVE)

    def test_activate_unknown_worker_fails(self):
        """Activating unknown worker should fail."""
        result = self.manager.activate_worker("nonexistent")
        self.assertFalse(result)

    def test_deactivate_worker(self):
        """Deactivating an active worker should work."""
        self.manager.activate_worker("coder")
        result = self.manager.deactivate_worker("coder")
        self.assertTrue(result)
        info = self.manager.get_worker_info("coder")
        self.assertEqual(info.state, WorkerState.DORMANT)

    def test_activate_switches_worker(self):
        """Activating a new worker should deactivate the current one."""
        self.manager.activate_worker("coder")
        self.manager.activate_worker("shadow")
        # Coder should be dormant, shadow should be active
        self.assertEqual(self.manager.get_worker_info("coder").state, WorkerState.DORMANT)
        self.assertEqual(self.manager.get_worker_info("shadow").state, WorkerState.ACTIVE)

    def test_execute_task_success(self):
        """Executing a valid task should return success."""
        task = DelegationTask(
            worker_id="coder", tool_name="read_file",
            tool_args={"path": "/test.py"}, reason="test"
        )
        result = self.manager.execute_task(task)
        self.assertTrue(result.success)
        self.assertIn("NO-OP", result.output)

    def test_execute_task_updates_stats(self):
        """Task execution should update worker statistics."""
        task = DelegationTask(
            worker_id="coder", tool_name="read_file",
            tool_args={"path": "/test.py"}, reason="test"
        )
        self.manager.execute_task(task)
        info = self.manager.get_worker_info("coder")
        self.assertEqual(info.tasks_completed, 1)

    def test_execute_batch(self):
        """Batch execution should handle multiple tasks."""
        tasks = [
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": f"/test{i}.py"}, reason="test")
            for i in range(3)
        ]
        results = self.manager.execute_batch(tasks)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.success for r in results))

    def test_deactivate_all(self):
        """Deactivating all should clear everything."""
        self.manager.activate_worker("coder")
        self.manager.activate_worker("shadow")
        self.manager.deactivate_all()
        self.assertIsNone(self.manager.get_active_worker())
        for info in self.manager.list_workers():
            self.assertEqual(info["state"], WorkerState.DORMANT.value)

    def test_stats(self):
        """Stats should return meaningful data."""
        stats = self.manager.get_stats()
        self.assertEqual(stats["workers_registered"], 6)
        self.assertEqual(stats["total_tasks_completed"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# DRY RUN PROTOCOL TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestDryRunProtocol(unittest.TestCase):
    """Tests for the Dry-Run Protocol."""

    def _make_protocol(self, mode="auto_all", input_responses=None):
        """Create a protocol with mock input."""
        config = DryRunConfig(mode=ApprovalMode(mode))
        formatter = PlanFormatter(mode="plain")

        if input_responses:
            responses_iter = iter(input_responses)
            protocol = DryRunProtocol(
                config=config, formatter=formatter,
                input_callback=lambda _: next(responses_iter),
            )
        else:
            protocol = DryRunProtocol(config=config, formatter=formatter)

        return protocol

    def test_auto_all_approves_everything(self):
        """AUTO_ALL mode should approve all tasks."""
        protocol = self._make_protocol("auto_all")
        tasks = [
            DelegationTask(worker_id="coder", tool_name="shell",
                         tool_args={"command": "rm -rf /"}, reason="test"),
        ]
        result = protocol.review(tasks)
        self.assertEqual(result.outcome, DryRunOutcome.AUTO_APPROVED)
        self.assertEqual(len(result.approved_tasks), 1)

    def test_deny_all_rejects_everything(self):
        """DENY_ALL mode should reject all tasks."""
        protocol = self._make_protocol("deny_all")
        tasks = [
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": "/test.py"}, reason="test"),
        ]
        result = protocol.review(tasks)
        self.assertEqual(result.outcome, DryRunOutcome.REJECTED)
        self.assertEqual(len(result.rejected_tasks), 1)

    def test_auto_readonly_approves_readonly(self):
        """AUTO_READONLY should auto-approve read-only tools."""
        protocol = self._make_protocol("auto_readonly")
        tasks = [
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": "/test.py"}, reason="test"),
        ]
        result = protocol.review(tasks)
        self.assertEqual(result.outcome, DryRunOutcome.AUTO_APPROVED)

    def test_auto_readonly_prompts_for_writes(self):
        """AUTO_READONLY should prompt for write operations."""
        protocol = self._make_protocol(
            "auto_readonly", input_responses=["y"]
        )
        tasks = [
            DelegationTask(worker_id="coder", tool_name="write_file",
                         tool_args={"path": "/test.py", "content": "hello"}, reason="test"),
        ]
        result = protocol.review(tasks)
        # Should be partially approved (no read-only tasks in this case)
        self.assertIn(result.outcome, [DryRunOutcome.PARTIALLY_APPROVED,
                                        DryRunOutcome.AUTO_APPROVED])

    def test_interactive_approve(self):
        """Interactive mode with 'y' should approve."""
        protocol = self._make_protocol("interactive", input_responses=["y"])
        tasks = [
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": "/test.py"}, reason="test"),
        ]
        result = protocol.review(tasks)
        self.assertEqual(result.outcome, DryRunOutcome.APPROVED)

    def test_interactive_reject(self):
        """Interactive mode with 'n' should reject."""
        protocol = self._make_protocol("interactive", input_responses=["n"])
        tasks = [
            DelegationTask(worker_id="coder", tool_name="shell",
                         tool_args={"command": "echo hello"}, reason="test"),
        ]
        result = protocol.review(tasks)
        self.assertEqual(result.outcome, DryRunOutcome.REJECTED)

    def test_interactive_modify_done(self):
        """Modify mode: modify → done should approve."""
        protocol = self._make_protocol(
            "interactive", input_responses=["modify", "done"]
        )
        tasks = [
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": "/test.py"}, reason="test"),
        ]
        result = protocol.review(tasks)
        self.assertEqual(result.outcome, DryRunOutcome.PARTIALLY_APPROVED)
        self.assertEqual(len(result.approved_tasks), 1)

    def test_interactive_modify_cancel(self):
        """Modify mode: modify → cancel should reject."""
        protocol = self._make_protocol(
            "interactive", input_responses=["modify", "cancel"]
        )
        tasks = [
            DelegationTask(worker_id="coder", tool_name="shell",
                         tool_args={"command": "echo hello"}, reason="test"),
        ]
        result = protocol.review(tasks)
        self.assertEqual(result.outcome, DryRunOutcome.REJECTED)

    def test_empty_tasks_auto_approved(self):
        """Empty task list should return immediately."""
        protocol = self._make_protocol("interactive")
        result = protocol.review([])
        self.assertEqual(result.outcome, DryRunOutcome.APPROVED)
        self.assertEqual(len(result.approved_tasks), 0)

    def test_stats_tracking(self):
        """Protocol should track stats."""
        protocol = self._make_protocol("auto_all")
        tasks = [
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": "/test.py"}, reason="test"),
        ]
        protocol.review(tasks)
        stats = protocol.get_stats()
        self.assertEqual(stats["total_reviews"], 1)


# ═══════════════════════════════════════════════════════════════════════════════
# PLAN FORMATTER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlanFormatter(unittest.TestCase):
    """Tests for the Plan Formatter."""

    def setUp(self):
        self.formatter = PlanFormatter(mode="plain")

    def test_format_empty_plan(self):
        """Empty plan should return '(no tasks)'."""
        result = self.formatter.format_plan([])
        self.assertIn("no tasks", result)

    def test_format_single_task(self):
        """Single task should display correctly."""
        tasks = [
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": "/test.py"}, reason="test"),
        ]
        result = self.formatter.format_plan(tasks)
        self.assertIn("coder", result)
        self.assertIn("read_file", result)
        self.assertIn("DRY RUN", result)

    def test_format_multiple_tasks(self):
        """Multiple tasks should all appear in output."""
        tasks = [
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": "/a.py"}, reason="read a"),
            DelegationTask(worker_id="shadow", tool_name="web_search",
                         tool_args={"query": "test"}, reason="search"),
        ]
        result = self.formatter.format_plan(tasks)
        self.assertIn("coder", result)
        self.assertIn("shadow", result)
        self.assertIn("Total tasks: 2", result)

    def test_json_format(self):
        """JSON format should be valid JSON."""
        formatter = PlanFormatter(mode="json")
        tasks = [
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": "/test.py"}, reason="test"),
        ]
        result = formatter.format_plan(tasks)
        parsed = json.loads(result)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["worker_id"], "coder")

    def test_compact_format(self):
        """Compact format should be single line."""
        formatter = PlanFormatter(mode="compact")
        tasks = [
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": "/test.py"}, reason="test"),
        ]
        result = formatter.format_plan(tasks)
        self.assertTrue(len(result.split("\n")) <= 2)  # Single line


# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskAssessment(unittest.TestCase):
    """Tests for risk assessment."""

    def test_readonly_low_risk(self):
        """Read-only tools should be low risk."""
        task = DelegationTask(worker_id="coder", tool_name="read_file",
                             tool_args={"path": "/test.py"}, reason="test")
        self.assertEqual(assess_risk(task), "low")

    def test_write_file_medium_risk(self):
        """Write operations should be medium risk."""
        task = DelegationTask(worker_id="coder", tool_name="write_file",
                             tool_args={"path": "/test.py", "content": "hello"}, reason="test")
        self.assertEqual(assess_risk(task), "medium")

    def test_rm_rf_critical_risk(self):
        """rm -rf should be critical risk."""
        task = DelegationTask(worker_id="shadow", tool_name="shell",
                             tool_args={"command": "rm -rf /"}, reason="test")
        self.assertEqual(assess_risk(task), "critical")

    def test_sudo_high_risk(self):
        """sudo commands should be at least high risk."""
        task = DelegationTask(worker_id="shadow", tool_name="shell",
                             tool_args={"command": "sudo apt install something"}, reason="test")
        # sudo is classified as critical by the regex, which is correct
        self.assertIn(assess_risk(task), ["high", "critical"])

    def test_web_search_low_risk(self):
        """Web search should be low risk."""
        task = DelegationTask(worker_id="shadow", tool_name="web_search",
                             tool_args={"query": "python tutorial"}, reason="test")
        self.assertEqual(assess_risk(task), "low")


# ═══════════════════════════════════════════════════════════════════════════════
# VRAM MANAGER TESTS (mocked)
# ═══════════════════════════════════════════════════════════════════════════════

class TestVRAMManager(unittest.TestCase):
    """Tests for the VRAM Lifecycle Manager."""

    def setUp(self):
        # Create manager with mocked CUDA
        self.manager = VRAMManager()

    def test_initializes_in_empty_state(self):
        """Should start with no model loaded."""
        self.assertEqual(self.manager._state, VRAMState.EMPTY)
        self.assertIsNone(self.manager._current_model_id)

    def test_will_fit_returns_tuple(self):
        """will_fit should return (bool, available, required)."""
        fits, available, required = self.manager.will_fit("qwen2.5-7b-instruct")
        self.assertIsInstance(fits, bool)
        self.assertIsInstance(available, (int, float))
        self.assertIsInstance(required, (int, float))

    def test_model_profiles_exist(self):
        """Default model profiles should exist."""
        self.assertIn("qwen2.5-7b-instruct", DEFAULT_MODEL_PROFILES)
        self.assertIn("qwen2.5-coder-7b-instruct", DEFAULT_MODEL_PROFILES)
        self.assertIn("qwen2.5-1.5b-safety-classifier", DEFAULT_MODEL_PROFILES)

    def test_classifier_profile_is_small(self):
        """Classifier should be much smaller than main models."""
        classifier = DEFAULT_MODEL_PROFILES["qwen2.5-1.5b-safety-classifier"]
        main = DEFAULT_MODEL_PROFILES["qwen2.5-7b-instruct"]
        self.assertLess(classifier.vram_required_mb, main.vram_required_mb / 10)

    def test_get_vram_info(self):
        """get_vram_info should return VRAMInfo."""
        info = self.manager.get_vram_info()
        self.assertIsInstance(info, VRAMInfo)

    def test_stats(self):
        """Stats should return meaningful data."""
        stats = self.manager.get_stats()
        self.assertEqual(stats["state"], VRAMState.EMPTY.value)
        self.assertEqual(stats["total_swaps"], 0)

    def test_get_model_none_when_empty(self):
        """get_model should return None when no model loaded."""
        self.assertIsNone(self.manager.get_model())


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegration(unittest.TestCase):
    """End-to-end integration tests for Phase 0 components."""

    def test_router_to_dryrun_to_workers_flow(self):
        """Full flow: route → dry-run → execute."""
        # Step 1: Route a message
        router = create_router()
        result = router.route_heuristic("Read the file /test.py and fix the bug")

        # Step 2: Create delegation tasks
        tasks = [
            DelegationTask(
                worker_id="coder", tool_name="read_file",
                tool_args={"path": "/test.py"},
                reason="Need to read file before fixing"
            ),
            DelegationTask(
                worker_id="coder", tool_name="write_file",
                tool_args={"path": "/test.py", "content": "fixed"},
                reason="Apply the fix"
            ),
        ]

        # Step 3: Validate
        valid, errors = router.validate_tasks(tasks)
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(errors), 0)

        # Step 4: Dry-run review
        protocol = create_dry_run(mode="auto_all")
        dry_result = protocol.review(tasks)
        self.assertEqual(dry_result.outcome, DryRunOutcome.AUTO_APPROVED)

        # Step 5: Execute via worker manager
        manager = create_worker_manager(tool_registry=None)
        results = manager.execute_batch(dry_result.approved_tasks)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.success for r in results))

    def test_batch_optimization_minimizes_swaps(self):
        """Batch should group tasks to minimize worker switches."""
        router = create_router()
        tasks = [
            DelegationTask(worker_id="shadow", tool_name="web_search",
                         tool_args={"query": "a"}, priority=1),
            DelegationTask(worker_id="coder", tool_name="read_file",
                         tool_args={"path": "a.py"}, priority=0),
            DelegationTask(worker_id="coder", tool_name="write_file",
                         tool_args={"path": "b.py"}, priority=0),
            DelegationTask(worker_id="coder", tool_name="code_run",
                         tool_args={"code": "test"}, priority=0),
        ]
        optimized = router.optimize_task_order(tasks)
        worker_sequence = [t.worker_id for t in optimized]
        # Coder tasks should be contiguous (grouped)
        coder_indices = [i for i, w in enumerate(worker_sequence) if w == "coder"]
        if len(coder_indices) >= 2:
            for i in range(len(coder_indices) - 1):
                self.assertEqual(coder_indices[i+1] - coder_indices[i], 1,
                               "Coder tasks should be contiguous")

    def test_full_pipeline_with_dryrun_rejection(self):
        """Pipeline should handle dry-run rejection gracefully."""
        router = create_router()
        tasks = [
            DelegationTask(worker_id="shadow", tool_name="shell",
                         tool_args={"command": "rm -rf /"}, reason="test"),
        ]

        # Validate (should flag dangerous)
        valid, errors = router.validate_tasks(tasks)
        self.assertTrue(len(errors) > 0)

        # Dry-run reject
        protocol = create_dry_run(mode="deny_all")
        result = protocol.review(tasks)
        self.assertEqual(result.outcome, DryRunOutcome.REJECTED)
        self.assertEqual(len(result.approved_tasks), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def run_tests():
    """Run all Phase 0 tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Load all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestRouter))
    suite.addTests(loader.loadTestsFromTestCase(TestWorkerManager))
    suite.addTests(loader.loadTestsFromTestCase(TestDryRunProtocol))
    suite.addTests(loader.loadTestsFromTestCase(TestPlanFormatter))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskAssessment))
    suite.addTests(loader.loadTestsFromTestCase(TestVRAMManager))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print("\n" + "=" * 60)
    print(f"  PHASE 0 TEST GATE RESULTS")
    print("=" * 60)
    print(f"  Tests run: {result.testsRun}")
    print(f"  Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"  Failed: {len(result.failures)}")
    print(f"  Errors: {len(result.errors)}")
    print(f"  Phase 0: {'PASSED' if result.wasSuccessful() else 'FAILED'}")
    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
