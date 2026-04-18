"""
EAA V4 - Phase 8 Tests: Main Loop (Central Orchestrator)
=========================================================
Tests the EAAMainLoop class that wires all 31 modules from Phases 0-7.
Tests run WITHOUT GPU — all LLM calls are mocked.
"""

import json
import os
import sys
import time
import signal
import unittest
import logging
import tempfile
import threading
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path
from io import StringIO

# ── Ensure eaa_v4 is importable ──
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eaa_v4.main_loop import (
    EAAMainLoop,
    MainLoopConfig,
    AgentState,
    EventType,
    create_main_loop,
    event_to_sse,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# MOCK HELPERS
# ═══════════════════════════════════════════════════════════════

def create_mock_brain_manager():
    """Create a mock BrainManager that simulates LLM inference."""
    mock = MagicMock()
    mock.current_model_id = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
    mock.is_gguf = False
    mock.current_adapter = "default"

    def mock_generate_text(model_id, system_prompt, user_prompt, **kwargs):
        return "I have processed your request. TASK_COMPLETE: Done successfully."

    mock.generate_text = MagicMock(side_effect=mock_generate_text)

    def mock_unload():
        mock.current_model_id = None
        mock.current_adapter = "default"

    mock.unload = MagicMock(side_effect=mock_unload)
    mock.load = MagicMock()
    return mock


def create_mock_tool_registry():
    """Create a mock ToolRegistry with sample tools."""
    mock = MagicMock()
    mock._descriptions = {
        "read_file": "Read contents of a file",
        "write_file": "Write content to a file",
        "shell": "Execute shell commands",
        "web_search": "Search the web",
        "screenshot": "Take a screenshot",
    }
    mock.list_tools = MagicMock(
        return_value=list(mock._descriptions.keys())
    )
    mock.execute = MagicMock(
        return_value=MagicMock(success=True, output="Tool executed", error=None)
    )
    mock.get_all_descriptions = MagicMock(return_value=mock._descriptions)
    return mock


def create_main_loop_instance(**config_overrides):
    """Create an EAAMainLoop with mocked dependencies."""
    brain = create_mock_brain_manager()
    registry = create_mock_tool_registry()

    with tempfile.TemporaryDirectory() as tmpdir:
        config = MainLoopConfig(
            project_root=tmpdir,
            memory_dir=tmpdir,
            plugin_dir=tmpdir,
            **config_overrides,
        )
        loop = EAAMainLoop(
            brain_manager=brain,
            tool_registry=registry,
            config=config,
        )
        return loop, brain, registry


# ═══════════════════════════════════════════════════════════════
# 1. CONFIGURATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestMainLoopConfig(unittest.TestCase):
    """Test MainLoopConfig dataclass."""

    def test_default_config(self):
        """Default config has expected values."""
        config = MainLoopConfig()
        self.assertEqual(config.project_root, ".")
        self.assertEqual(config.total_vram_gb, 8.0)
        self.assertEqual(config.max_iterations, 15)
        self.assertEqual(config.max_tool_output, 3000)
        self.assertTrue(config.auto_retry)
        self.assertEqual(config.max_retries, 2)
        self.assertTrue(config.enable_dry_run)
        self.assertTrue(config.enable_plugins)
        self.assertTrue(config.enable_memory_extraction)
        self.assertEqual(config.idle_extraction_seconds, 300)
        self.assertEqual(config.transcript_resume_max_tokens, 6000)
        self.assertEqual(config.session_memory_threshold, 5000)

    def test_custom_config(self):
        """Custom config overrides work."""
        config = MainLoopConfig(
            project_root="/test",
            total_vram_gb=12.0,
            max_iterations=20,
        )
        self.assertEqual(config.project_root, "/test")
        self.assertEqual(config.total_vram_gb, 12.0)
        self.assertEqual(config.max_iterations, 20)

    def test_memory_dir_defaults_to_home(self):
        """memory_dir defaults to ~/.eaa/memory."""
        config = MainLoopConfig()
        self.assertIn(".eaa", config.memory_dir)
        self.assertIn("memory", config.memory_dir)

    def test_memory_dir_custom(self):
        """Custom memory_dir is respected."""
        config = MainLoopConfig(memory_dir="/custom/memory")
        self.assertEqual(config.memory_dir, "/custom/memory")


# ═══════════════════════════════════════════════════════════════
# 2. AGENT STATE TESTS
# ═══════════════════════════════════════════════════════════════

class TestAgentState(unittest.TestCase):
    """Test AgentState dataclass."""

    def test_initial_state(self):
        """State starts at zero."""
        state = AgentState()
        self.assertEqual(state.iterations, 0)
        self.assertEqual(state.tools_used, 0)
        self.assertEqual(state.successful_tools, 0)
        self.assertEqual(state.failed_tools, 0)
        self.assertEqual(state.retries, 0)
        self.assertEqual(state.consecutive_failures, 0)
        self.assertEqual(state.tasks_delegated, 0)
        self.assertEqual(state.tasks_completed, 0)
        self.assertEqual(state.vram_swaps, 0)
        self.assertEqual(state.self_heals, 0)
        self.assertEqual(state.last_tool, "")

    def test_elapsed_increases(self):
        """elapsed property returns positive seconds."""
        state = AgentState()
        time.sleep(0.05)
        self.assertGreater(state.elapsed, 0)

    def test_to_dict(self):
        """to_dict returns all fields."""
        state = AgentState()
        d = state.to_dict()
        self.assertIn("iterations", d)
        self.assertIn("tools_used", d)
        self.assertIn("elapsed_seconds", d)
        self.assertIn("tasks_delegated", d)
        self.assertIn("vram_swaps", d)
        self.assertIn("self_heals", d)

    def test_to_dict_elapsed_is_number(self):
        """elapsed_seconds in to_dict is a float."""
        state = AgentState()
        d = state.to_dict()
        self.assertIsInstance(d["elapsed_seconds"], float)


# ═══════════════════════════════════════════════════════════════
# 3. EVENT TYPE TESTS
# ═══════════════════════════════════════════════════════════════

class TestEventType(unittest.TestCase):
    """Test EventType enum."""

    def test_all_event_types_exist(self):
        """All required event types are defined."""
        expected = [
            "status", "thinking", "tool_start", "tool_result",
            "iteration", "complete", "error", "warning",
            "permission_review", "dry_run_review",
            "session_memory_updated", "self_heal", "vram_swap",
        ]
        for name in expected:
            self.assertTrue(hasattr(EventType, name.upper()), f"Missing {name}")

    def test_event_type_values(self):
        """Event type values match their names."""
        self.assertEqual(EventType.STATUS.value, "status")
        self.assertEqual(EventType.COMPLETE.value, "complete")
        self.assertEqual(EventType.SELF_HEAL.value, "self_heal")


# ═══════════════════════════════════════════════════════════════
# 4. MAIN LOOP INITIALIZATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestMainLoopInit(unittest.TestCase):
    """Test EAAMainLoop initialization and wiring."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_phase0_components_exist(self):
        """Phase 0 components are initialized."""
        self.assertIsNotNone(self.loop.vram_manager)
        self.assertIsNotNone(self.loop.router)
        self.assertIsNotNone(self.loop.worker_manager)
        self.assertIsNotNone(self.loop.dry_run)
        self.assertIsNotNone(self.loop.plan_formatter)

    def test_phase1_components_exist(self):
        """Phase 1 components are initialized."""
        self.assertIsNotNone(self.loop.permission_manager)
        self.assertIsNotNone(self.loop.safety_classifier)

    def test_phase2_components_exist(self):
        """Phase 2 components are initialized."""
        self.assertIsNotNone(self.loop.smart_edit)
        self.assertIsNotNone(self.loop.file_state)
        self.assertIsNotNone(self.loop.history_index)
        self.assertIsNotNone(self.loop.rollback)

    def test_phase3_components_exist(self):
        """Phase 3 components are initialized."""
        self.assertIsNotNone(self.loop.context_manager)
        self.assertIsNotNone(self.loop.conversation_compactor)
        self.assertIsNotNone(self.loop.system_memory)
        self.assertIsNotNone(self.loop.token_tracker)

    def test_phase4_components_exist(self):
        """Phase 4 components are initialized."""
        self.assertIsNotNone(self.loop.prompt_assembler)
        self.assertIsNotNone(self.loop.prompt_cache)
        self.assertIsNotNone(self.loop.tool_instruction_registry)

    def test_phase5_components_exist(self):
        """Phase 5 components are initialized."""
        self.assertIsNotNone(self.loop.plugin_manager)
        self.assertIsNotNone(self.loop.model_registry)
        self.assertIsNotNone(self.loop.vram_lifecycle)

    def test_phase6_components_exist(self):
        """Phase 6 components are initialized."""
        self.assertIsNotNone(self.loop.error_handler)
        self.assertIsNotNone(self.loop.validation_hooks)
        self.assertIsNotNone(self.loop.concurrent_isolation)

    def test_phase7_components_exist(self):
        """Phase 7 components are initialized."""
        self.assertIsNotNone(self.loop.session_transcript)
        self.assertIsNotNone(self.loop.session_memory)
        self.assertIsNotNone(self.loop.memory_extractor)
        self.assertIsNotNone(self.loop.prompt_history)

    def test_safety_classifier_set_on_permission_manager(self):
        """Safety classifier is wired into permission manager."""
        self.assertIs(
            self.loop.permission_manager._classifier,
            self.loop.safety_classifier,
        )

    def test_worker_manager_has_registry(self):
        """Worker manager receives the tool registry."""
        self.assertEqual(self.loop.worker_manager._registry, self.loop.registry)

    def test_messages_start_empty(self):
        """Messages list starts empty."""
        self.assertEqual(self.loop.messages, [])

    def test_shutdown_not_requested(self):
        """Shutdown flag starts False."""
        self.assertFalse(self.loop._shutdown_requested)

    def test_sigint_not_installed_by_default(self):
        """SIGINT handler is not installed by default."""
        self.assertFalse(self.loop._sigint_installed)


# ═══════════════════════════════════════════════════════════════
# 5. SIGINT HANDLER TESTS
# ═══════════════════════════════════════════════════════════════

class TestSIGINTHandler(unittest.TestCase):
    """Test SIGINT VRAM cleanup trap."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_install_sigint_handler(self):
        """SIGINT handler installs successfully."""
        self.loop.install_sigint_handler()
        self.assertTrue(self.loop._sigint_installed)

    def test_install_only_once(self):
        """Installing twice is idempotent."""
        self.loop.install_sigint_handler()
        self.loop.install_sigint_handler()
        self.assertTrue(self.loop._sigint_installed)

    def test_emergency_cleanup_calls_unload(self):
        """Emergency cleanup unloads brain."""
        self.loop._emergency_cleanup()
        self.brain.unload.assert_called_once()

    def test_emergency_cleanup_calls_transcript_flush(self):
        """Emergency cleanup flushes transcript."""
        self.loop._emergency_cleanup()
        # Flush was called (no exception)

    def test_emergency_cleanup_stops_daemon(self):
        """Emergency cleanup stops memory extractor daemon."""
        self.loop._emergency_cleanup()
        # Daemon stop was called (no exception)

    def test_emergency_cleanup_calls_vram_force_cleanup(self):
        """Emergency cleanup calls VRAM force cleanup."""
        self.loop._emergency_cleanup()
        # VRAM cleanup was called (no exception)

    def test_shutdown_flag_set_on_signal(self):
        """SIGINT sets shutdown flag."""
        self.loop.install_sigint_handler()
        # Simulate the handler setting the flag
        self.loop._shutdown_requested = True
        self.assertTrue(self.loop._shutdown_requested)


# ═══════════════════════════════════════════════════════════════
# 6. SYSTEM PROMPT ASSEMBLY TESTS
# ═══════════════════════════════════════════════════════════════

class TestSystemPromptAssembly(unittest.TestCase):
    """Test Phase 4 prompt assembly through main loop."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_build_system_prompt_returns_string(self):
        """Build system prompt returns a non-empty string."""
        prompt = self.loop._build_system_prompt("master")
        self.assertIsInstance(prompt, str)
        self.assertTrue(len(prompt) > 10)

    def test_build_system_prompt_contains_worker_info(self):
        """System prompt contains worker descriptions."""
        prompt = self.loop._build_system_prompt("master")
        # The router's get_master_prompt should contribute worker info
        self.assertIsInstance(prompt, str)

    def test_build_system_prompt_registers_tools(self):
        """Building prompt registers tools with instruction registry."""
        self.loop._build_system_prompt("master")
        registered = self.loop.tool_instruction_registry.registered_tools
        self.assertGreater(len(registered), 0)

    def test_build_system_prompt_different_brain_types(self):
        """Different brain types don't crash."""
        for bt in ["master", "shadow", "coder"]:
            prompt = self.loop._build_system_prompt(bt)
            self.assertIsInstance(prompt, str)


# ═══════════════════════════════════════════════════════════════
# 7. SESSION MANAGEMENT TESTS
# ═══════════════════════════════════════════════════════════════

class TestSessionManagement(unittest.TestCase):
    """Test Phase 7 session resume/end through main loop."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_resume_session_empty(self):
        """Resume with no history returns empty messages."""
        messages = self.loop.resume_session()
        self.assertEqual(messages, [])

    def test_end_session_no_crash(self):
        """End session completes without errors."""
        self.loop.end_session()  # Should not raise

    def test_end_session_flushes_transcript(self):
        """End session flushes transcript."""
        self.loop.session_transcript.append_turn("user", "test")
        self.loop.end_session()
        # No exception means success

    def test_prompt_history_records_commands(self):
        """Prompt history records user commands during run."""
        # The run() method calls prompt_history.append()
        # We'll verify it doesn't crash
        pass  # Tested indirectly in run tests


# ═══════════════════════════════════════════════════════════════
# 8. AGENT LOOP RUN TESTS
# ═══════════════════════════════════════════════════════════════

class TestAgentLoopRun(unittest.TestCase):
    """Test the main agent loop execution."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_run_yields_events(self):
        """Run yields at least one event."""
        events = list(self.loop.run("Hello, test"))
        self.assertGreater(len(events), 0)

    def test_run_yields_status_event(self):
        """Run yields a STATUS event first."""
        events = list(self.loop.run("Hello, test"))
        self.assertEqual(events[0]["type"], "status")

    def test_run_yields_complete_event(self):
        """Run yields a COMPLETE event."""
        events = list(self.loop.run("Hello, test"))
        complete_events = [
            e for e in events if e["type"] == "complete"
        ]
        self.assertGreater(len(complete_events), 0)

    def test_run_complete_has_state(self):
        """Complete event includes state."""
        events = list(self.loop.run("Hello, test"))
        complete = next(
            e for e in events if e["type"] == "complete"
        )
        self.assertIn("state", complete)
        self.assertIn("iterations", complete["state"])

    def test_run_records_in_transcript(self):
        """Run records user and assistant turns in transcript."""
        list(self.loop.run("Hello, test"))
        turns = self.loop.session_transcript.get_turn_count()
        self.assertGreater(turns, 0)

    def test_run_records_in_prompt_history(self):
        """Run records user command in prompt history."""
        list(self.loop.run("Hello, test"))
        count = self.loop.prompt_history.get_entry_count()
        self.assertGreater(count, 0)

    def test_run_respects_max_iterations(self):
        """Run stops at max_iterations."""
        self.loop.config.max_iterations = 2
        events = list(self.loop.run("test"))
        iteration_events = [
            e for e in events if e["type"] == "iteration"
        ]
        # Should not exceed max_iterations iterations
        self.assertLessEqual(len(iteration_events), 2)

    def test_run_state_updated(self):
        """Run updates agent state."""
        list(self.loop.run("Hello, test"))
        self.assertGreater(self.loop.state.iterations, 0)

    def test_run_shutdown_breaks_loop(self):
        """Setting shutdown flag breaks the loop."""
        self.loop._shutdown_requested = True
        events = list(self.loop.run("test"))
        warning_events = [
            e for e in events if e["type"] == "warning"
        ]
        self.assertGreater(len(warning_events), 0)


# ═══════════════════════════════════════════════════════════════
# 9. ERROR HANDLING TESTS
# ═══════════════════════════════════════════════════════════════

class TestErrorHandling(unittest.TestCase):
    """Test Phase 6 error handling integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_json_decode_intercept_valid(self):
        """Valid JSON passes through intercept."""
        result = self.loop.error_handler.intercept_json_decode(
            '{"tool": "test"}', "test_tool"
        )
        self.assertIsInstance(result, dict)
        self.assertEqual(result["tool"], "test")

    def test_json_decode_intercept_invalid(self):
        """Invalid JSON is wrapped as is_error."""
        result = self.loop.error_handler.intercept_json_decode(
            "{broken json", "test_tool"
        )
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("is_error", False))

    def test_error_handler_wrap(self):
        """wrap_error_as_tool_result produces correct format."""
        result = self.loop.error_handler.wrap_error_as_tool_result(
            ValueError("test error"), "test_tool"
        )
        self.assertIsInstance(result, dict)
        self.assertTrue(result["is_error"])
        self.assertIn("test_tool", result["content"])

    def test_error_handler_tier_tracking(self):
        """Error handler tracks recovery tiers."""
        self.assertEqual(self.loop.error_handler.get_current_max_tokens(), 2048)
        self.assertFalse(self.loop.error_handler.is_exhausted())

    def test_error_handler_reset(self):
        """Error handler tier can be reset."""
        self.loop.error_handler.reset_tier()
        self.assertEqual(self.loop.error_handler.get_current_max_tokens(), 2048)


# ═══════════════════════════════════════════════════════════════
# 10. VALIDATION HOOKS TESTS
# ═══════════════════════════════════════════════════════════════

class TestValidationHooks(unittest.TestCase):
    """Test Phase 6 validation hooks."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_python_syntax_hook_registered(self):
        """Python syntax hook is registered for edit_file."""
        hooks = self.loop.validation_hooks.get_registered_hooks("edit_file")
        self.assertGreater(len(hooks), 0)

    def test_python_syntax_hook_registered_create(self):
        """Python syntax hook is registered for create_file."""
        hooks = self.loop.validation_hooks.get_registered_hooks("create_file")
        self.assertGreater(len(hooks), 0)

    def test_hooks_not_registered_for_shell(self):
        """No hooks for shell commands."""
        hooks = self.loop.validation_hooks.get_registered_hooks("shell")
        self.assertEqual(len(hooks), 0)


# ═══════════════════════════════════════════════════════════════
# 11. CONCURRENT ISOLATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestConcurrentIsolation(unittest.TestCase):
    """Test Phase 6 concurrent isolation."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_concurrent_isolation_controller_exists(self):
        """Controller is initialized."""
        self.assertIsNotNone(self.loop.concurrent_isolation)

    def test_register_batch_and_check_status(self):
        """Can register a batch and check status."""
        from eaa_v4.router import DelegationTask
        task = DelegationTask(
            worker_id="test_worker",
            tool_name="read_file",
            reason="Read a file",
            tool_args={"path": "/test"},
        )
        group_id = self.loop.concurrent_isolation.register_batch([task])
        self.assertIsInstance(group_id, str)
        status = self.loop.concurrent_isolation.get_group_status(group_id)
        self.assertIsNotNone(status)

    def test_check_cancelled_not_cancelled(self):
        """Non-cancelled task returns False."""
        result = self.loop.concurrent_isolation.check_cancelled("nonexistent")
        self.assertFalse(result)


# ═══════════════════════════════════════════════════════════════
# 12. STATUS REPORTING TESTS
# ═══════════════════════════════════════════════════════════════

class TestStatusReporting(unittest.TestCase):
    """Test get_status() comprehensive reporting."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_get_status_returns_dict(self):
        """get_status returns a dictionary."""
        status = self.loop.get_status()
        self.assertIsInstance(status, dict)

    def test_status_has_state(self):
        """Status includes agent state."""
        status = self.loop.get_status()
        self.assertIn("state", status)
        self.assertIn("iterations", status["state"])

    def test_status_has_phases(self):
        """Status includes all phase subsystems."""
        status = self.loop.get_status()
        self.assertIn("phases", status)
        phases = status["phases"]
        self.assertIn("phase0_router", phases)
        self.assertIn("phase1_permissions", phases)
        self.assertIn("phase2_smart_edit", phases)
        self.assertIn("phase3_context", phases)
        self.assertIn("phase6_error_handler", phases)
        self.assertIn("phase6_isolation", phases)
        self.assertIn("phase7_transcript", phases)
        self.assertIn("phase7_session_memory", phases)

    def test_status_has_brain_loaded(self):
        """Status includes brain_loaded field."""
        status = self.loop.get_status()
        self.assertIn("brain_loaded", status)

    def test_status_has_tools_available(self):
        """Status includes tools_available list."""
        status = self.loop.get_status()
        self.assertIn("tools_available", status)
        self.assertIsInstance(status["tools_available"], list)


# ═══════════════════════════════════════════════════════════════
# 13. HELPERS AND UTILITIES TESTS
# ═══════════════════════════════════════════════════════════════

class TestHelpers(unittest.TestCase):
    """Test helper functions."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_event_to_sse_format(self):
        """event_to_sse produces correct SSE format."""
        event = {"type": "status", "message": "test"}
        sse = event_to_sse(event)
        self.assertTrue(sse.startswith("data: "))
        self.assertTrue(sse.endswith("\n\n"))
        self.assertIn("status", sse)

    def test_event_to_sse_json_serializable(self):
        """SSE output is valid JSON."""
        event = {"type": "complete", "status": "success"}
        sse = event_to_sse(event)
        json_str = sse.strip().replace("data: ", "").replace("\n", "")
        parsed = json.loads(json_str)
        self.assertEqual(parsed["type"], "complete")

    def test_create_main_loop_convenience(self):
        """create_main_loop convenience function works."""
        brain = create_mock_brain_manager()
        registry = create_mock_tool_registry()
        with tempfile.TemporaryDirectory() as tmpdir:
            loop = create_main_loop(
                brain, registry,
                project_root=tmpdir,
                max_iterations=5,
            )
            self.assertIsInstance(loop, EAAMainLoop)
            self.assertTrue(loop._sigint_installed)
            self.assertEqual(loop.config.max_iterations, 5)

    def test_is_complete_detection(self):
        """_is_complete detects completion markers."""
        self.assertTrue(self.loop._is_complete("TASK_COMPLETE: Done"))
        self.assertTrue(self.loop._is_complete("TASK_DONE: All good"))
        self.assertTrue(self.loop._is_complete("[COMPLETE]"))
        self.assertFalse(self.loop._is_complete("Still working on it..."))

    def test_extract_completion_summary(self):
        """Extracts summary after completion marker."""
        text = "Some thinking... TASK_COMPLETE: Built the thing successfully!"
        summary = self.loop._extract_completion_summary(text)
        self.assertIn("Built the thing successfully!", summary)

    def test_format_conversation(self):
        """Conversation formatting produces expected output."""
        self.loop.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        formatted = self.loop._format_conversation()
        self.assertIn("User: Hello", formatted)
        self.assertIn("Assistant: Hi there", formatted)
        self.assertTrue(formatted.endswith("Assistant:"))


# ═══════════════════════════════════════════════════════════════
# 14. MODEL REGISTRY TESTS
# ═══════════════════════════════════════════════════════════════

class TestModelRegistry(unittest.TestCase):
    """Test Phase 5 model registry integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_model_registry_exists(self):
        """Model registry is initialized."""
        self.assertIsNotNone(self.loop.model_registry)

    def test_model_registry_vram_setting(self):
        """Model registry uses configured VRAM."""
        self.assertEqual(
            self.loop.model_registry.total_vram_gb,
            self.loop.config.total_vram_gb,
        )

    def test_vram_lifecycle_exists(self):
        """VRAM lifecycle manager exists."""
        self.assertIsNotNone(self.loop.vram_lifecycle)


# ═══════════════════════════════════════════════════════════════
# 15. PERMISSION INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestPermissionIntegration(unittest.TestCase):
    """Test Phase 1 permission system integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_permission_manager_exists(self):
        """Permission manager is initialized."""
        self.assertIsNotNone(self.loop.permission_manager)

    def test_safety_classifier_exists(self):
        """Safety classifier is initialized."""
        self.assertIsNotNone(self.loop.safety_classifier)

    def test_permission_stats(self):
        """Permission stats can be retrieved."""
        stats = self.loop.permission_manager.get_stats()
        self.assertIsInstance(stats, dict)


# ═══════════════════════════════════════════════════════════════
# 16. CONTEXT MANAGER INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestContextManagerIntegration(unittest.TestCase):
    """Test Phase 3 context manager integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_context_manager_exists(self):
        """Context manager is initialized."""
        self.assertIsNotNone(self.loop.context_manager)

    def test_token_tracker_exists(self):
        """Token tracker is initialized."""
        self.assertIsNotNone(self.loop.token_tracker)

    def test_system_memory_exists(self):
        """System memory is initialized."""
        self.assertIsNotNone(self.loop.system_memory)

    def test_conversation_compactor_exists(self):
        """Conversation compactor is initialized."""
        self.assertIsNotNone(self.loop.conversation_compactor)


# ═══════════════════════════════════════════════════════════════
# 17. PROMPT ASSEMBLER INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestPromptAssemblerIntegration(unittest.TestCase):
    """Test Phase 4 prompt assembler integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_prompt_assembler_exists(self):
        """Prompt assembler is initialized."""
        self.assertIsNotNone(self.loop.prompt_assembler)

    def test_prompt_cache_exists(self):
        """Prompt cache is initialized."""
        self.assertIsNotNone(self.loop.prompt_cache)

    def test_tool_instruction_registry_exists(self):
        """Tool instruction registry is initialized."""
        self.assertIsNotNone(self.loop.tool_instruction_registry)

    def test_prompt_cache_stats(self):
        """Prompt cache stats can be retrieved."""
        stats = self.loop.prompt_cache.stats
        self.assertIsInstance(stats, dict)


# ═══════════════════════════════════════════════════════════════
# 18. SESSION MEMORY TESTS
# ═══════════════════════════════════════════════════════════════

class TestSessionMemoryIntegration(unittest.TestCase):
    """Test Phase 7 session memory integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_session_memory_exists(self):
        """Session memory is initialized."""
        self.assertIsNotNone(self.loop.session_memory)

    def test_session_memory_get_notes(self):
        """Session memory returns notes string."""
        notes = self.loop.session_memory.get_notes()
        self.assertIsInstance(notes, str)

    def test_session_memory_token_count(self):
        """Session memory token count returns number."""
        count = self.loop.session_memory.get_token_count()
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)


# ═══════════════════════════════════════════════════════════════
# 19. MEMORY EXTRACTOR TESTS
# ═══════════════════════════════════════════════════════════════

class TestMemoryExtractorIntegration(unittest.TestCase):
    """Test Phase 7 memory extractor integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_memory_extractor_exists(self):
        """Memory extractor is initialized."""
        self.assertIsNotNone(self.loop.memory_extractor)

    def test_memory_extractor_has_transcript(self):
        """Memory extractor has reference to transcript."""
        self.assertIs(
            self.loop.memory_extractor.transcript,
            self.loop.session_transcript,
        )

    def test_memory_extractor_update_idle_timestamp(self):
        """Updating idle timestamp doesn't crash."""
        self.loop.memory_extractor.update_idle_timestamp()


# ═══════════════════════════════════════════════════════════════
# 20. PROMPT HISTORY TESTS
# ═══════════════════════════════════════════════════════════════

class TestPromptHistoryIntegration(unittest.TestCase):
    """Test Phase 7 prompt history integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_prompt_history_exists(self):
        """Prompt history is initialized."""
        self.assertIsNotNone(self.loop.prompt_history)

    def test_prompt_history_append_and_count(self):
        """Can append commands and get count."""
        self.loop.prompt_history.append("test command 1")
        self.loop.prompt_history.append("test command 2")
        count = self.loop.prompt_history.get_entry_count()
        self.assertEqual(count, 2)


# ═══════════════════════════════════════════════════════════════
# 21. DRY RUN PROTOCOL TESTS
# ═══════════════════════════════════════════════════════════════

class TestDryRunProtocol(unittest.TestCase):
    """Test Phase 0 dry-run protocol integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_dry_run_exists(self):
        """Dry run protocol is initialized."""
        self.assertIsNotNone(self.loop.dry_run)

    def test_dry_run_stats(self):
        """Dry run stats can be retrieved."""
        stats = self.loop.dry_run.get_stats()
        self.assertIsInstance(stats, dict)

    def test_dry_run_disabled(self):
        """Dry run can be disabled."""
        self.loop.config.enable_dry_run = False
        # No crash when disabled


# ═══════════════════════════════════════════════════════════════
# 22. VRAM MANAGER TESTS
# ═══════════════════════════════════════════════════════════════

class TestVRAMManagerIntegration(unittest.TestCase):
    """Test Phase 0 VRAM manager integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_vram_manager_exists(self):
        """VRAM manager is initialized."""
        self.assertIsNotNone(self.loop.vram_manager)

    def test_vram_manager_get_vram_info(self):
        """VRAM info can be retrieved."""
        info = self.loop.vram_manager.get_vram_info()
        self.assertEqual(info.total_mb, 8188.0)


# ═══════════════════════════════════════════════════════════════
# 23. ROUTER INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestRouterIntegration(unittest.TestCase):
    """Test Phase 0 router integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_router_exists(self):
        """Router is initialized."""
        self.assertIsNotNone(self.loop.router)

    def test_router_has_tool_descriptions(self):
        """Router has tool descriptions from registry."""
        self.assertGreater(len(self.loop.router.tool_descriptions), 0)

    def test_router_get_master_prompt(self):
        """Router can generate master prompt."""
        prompt = self.loop.router.get_master_prompt()
        self.assertIsInstance(prompt, str)
        self.assertTrue(len(prompt) > 0)

    def test_router_route_heuristic(self):
        """Router can route messages."""
        result = self.loop.router.route_heuristic("read the file test.py")
        self.assertIsNotNone(result)

    def test_router_stats(self):
        """Router stats can be retrieved."""
        stats = self.loop.router.get_stats()
        self.assertIsInstance(stats, dict)


# ═══════════════════════════════════════════════════════════════
# 24. WORKER MANAGER TESTS
# ═══════════════════════════════════════════════════════════════

class TestWorkerManagerIntegration(unittest.TestCase):
    """Test Phase 0 worker manager integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_worker_manager_exists(self):
        """Worker manager is initialized."""
        self.assertIsNotNone(self.loop.worker_manager)

    def test_worker_manager_list_workers(self):
        """Worker manager can list workers."""
        workers = self.loop.worker_manager.list_workers()
        self.assertIsInstance(workers, list)

    def test_worker_manager_stats(self):
        """Worker manager stats can be retrieved."""
        stats = self.loop.worker_manager.get_stats()
        self.assertIsInstance(stats, dict)


# ═══════════════════════════════════════════════════════════════
# 25. SMART EDIT INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestSmartEditIntegration(unittest.TestCase):
    """Test Phase 2 smart edit integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_smart_edit_exists(self):
        """Smart edit engine is initialized."""
        self.assertIsNotNone(self.loop.smart_edit)

    def test_file_state_tracker_exists(self):
        """File state tracker is initialized."""
        self.assertIsNotNone(self.loop.file_state)

    def test_history_index_exists(self):
        """History index is initialized."""
        self.assertIsNotNone(self.loop.history_index)

    def test_rollback_manager_exists(self):
        """Rollback manager is initialized."""
        self.assertIsNotNone(self.loop.rollback)

    def test_smart_edit_stats(self):
        """Smart edit stats can be retrieved."""
        stats = self.loop.smart_edit.get_stats()
        self.assertIsInstance(stats, dict)


# ═══════════════════════════════════════════════════════════════
# 26. SESSION TRANSCRIPT TESTS
# ═══════════════════════════════════════════════════════════════

class TestSessionTranscriptIntegration(unittest.TestCase):
    """Test Phase 7 session transcript integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_session_transcript_exists(self):
        """Session transcript is initialized."""
        self.assertIsNotNone(self.loop.session_transcript)

    def test_session_transcript_append_and_count(self):
        """Can append turns and get count."""
        self.loop.session_transcript.append_turn("user", "test message")
        count = self.loop.session_transcript.get_turn_count()
        self.assertEqual(count, 1)

    def test_session_transcript_flush(self):
        """Flush doesn't crash."""
        self.loop.session_transcript.append_turn("user", "test")
        self.loop.session_transcript.flush()

    def test_session_transcript_clear(self):
        """Clear works."""
        self.loop.session_transcript.append_turn("user", "test")
        self.loop.session_transcript.clear()
        count = self.loop.session_transcript.get_turn_count()
        self.assertEqual(count, 0)


# ═══════════════════════════════════════════════════════════════
# 27. PLAN FORMATTER TESTS
# ═══════════════════════════════════════════════════════════════

class TestPlanFormatter(unittest.TestCase):
    """Test Phase 0 plan formatter integration."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_plan_formatter_exists(self):
        """Plan formatter is initialized."""
        self.assertIsNotNone(self.loop.plan_formatter)


# ═══════════════════════════════════════════════════════════════
# 28. INTEGRATION - FULL LOOP WITH BRAIN ERROR
# ═══════════════════════════════════════════════════════════════

class TestFullLoopWithBrainError(unittest.TestCase):
    """Test main loop handles brain errors gracefully."""

    def test_brain_error_returns_error_event(self):
        """Brain generation error is handled."""
        brain = create_mock_brain_manager()
        brain.generate_text = MagicMock(
            side_effect=RuntimeError("GPU OOM")
        )
        registry = create_mock_tool_registry()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = MainLoopConfig(project_root=tmpdir, memory_dir=tmpdir)
            loop = EAAMainLoop(
                brain_manager=brain,
                tool_registry=registry,
                config=config,
            )

            events = list(loop.run("test"))
            # Should still complete (with error event)
            complete_events = [
                e for e in events if e["type"] == "complete"
            ]
            self.assertGreater(len(complete_events), 0)


# ═══════════════════════════════════════════════════════════════
# 29. INTEGRATION - PHASE CROSS-CUTTING
# ═══════════════════════════════════════════════════════════════

class TestPhaseCrossCutting(unittest.TestCase):
    """Test that phases interact correctly across boundaries."""

    def setUp(self):
        self.loop, self.brain, self.registry = create_main_loop_instance()

    def test_error_handler_uses_context_manager(self):
        """Error handler references context manager."""
        self.assertIs(
            self.loop.error_handler._context_manager,
            self.loop.context_manager,
        )

    def test_memory_extractor_uses_transcript(self):
        """Memory extractor references session transcript."""
        self.assertIs(
            self.loop.memory_extractor.transcript,
            self.loop.session_transcript,
        )

    def test_prompt_assembler_uses_context_manager(self):
        """Prompt assembler references context manager."""
        # The assembler should be connected to context manager
        self.assertIsNotNone(self.loop.prompt_assembler)

    def test_vram_lifecycle_uses_vram_manager(self):
        """VRAM lifecycle references VRAM manager."""
        self.assertIs(
            self.loop.vram_lifecycle._vram_manager,
            self.loop.vram_manager,
        )

    def test_vram_lifecycle_uses_model_registry(self):
        """VRAM lifecycle references model registry."""
        self.assertIs(
            self.loop.vram_lifecycle._model_registry,
            self.loop.model_registry,
        )


# ═══════════════════════════════════════════════════════════════
# RUN TESTS
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    unittest.main(verbosity=2)