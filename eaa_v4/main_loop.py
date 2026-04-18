"""
EAA V4 - Phase 8: Main Loop (Central Orchestrator)
==================================================
Wires all 31 modules from Phases 0-7 into a cohesive agent loop.

Boot chain:
  eaa_supervisor_v7.py
    → eaa_control_email_v7.py  (port 8001, control station)
      → run_eaa_agent_v3.py     (port 8000, AI backend)
        → brain_manager.py      (model load/unload)
        → eaa_agent_server_v3.py (agent endpoints)
          → eaa_agent_loop_v3.py (reasoning engine)
            → 124+ tools from 12 tool modules

main_loop.py replaces the current eaa_agent_server_v3.py + eaa_agent_loop_v3.py
pair with a clean V4 orchestrator that uses ALL Phase 0-7 subsystems.

Architecture:
  ┌──────────────────────────────────────────────────┐
  │                   EAAMainLoop                    │
  │                                                  │
  │  Phase 0: Router + Workers + VRAM + DryRun       │
  │  Phase 1: Permissions + Safety                   │
  │  Phase 2: SmartEdit + FileState + Rollback       │
  │  Phase 3: ContextManager + Compactor + TokenTrack │
  │  Phase 4: PromptAssembler + Cache + MemoryLoader  │
  │  Phase 5: PluginManager + ModelRegistry + VRAML   │
  │  Phase 6: ErrorHandler + Validation + Isolation   │
  │  Phase 7: Transcript + SessionMemory + Extractor  │
  │                                                  │
  │  + External: brain_manager, tool_registry         │
  └──────────────────────────────────────────────────┘

SIGINT handler ensures clean VRAM release on Ctrl+C within 5 seconds.
"""

import os
import sys
import json
import signal
import logging
import time
import traceback
from typing import Dict, List, Any, Optional, Generator, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

@dataclass
class MainLoopConfig:
    """Configuration for the EAA V4 main loop."""
    project_root: str = "."
    memory_dir: Optional[str] = None
    plugin_dir: Optional[str] = None
    total_vram_gb: float = 8.0
    max_iterations: int = 15
    max_tool_output: int = 3000
    auto_retry: bool = True
    max_retries: int = 2
    max_consecutive_failures: int = 3
    enable_dry_run: bool = True
    dry_run_auto_approve_light: bool = True
    enable_plugins: bool = True
    enable_memory_extraction: bool = True
    idle_extraction_seconds: int = 300
    transcript_resume_max_tokens: int = 6000
    session_memory_threshold: int = 5000

    def __post_init__(self):
        if self.memory_dir is None:
            self.memory_dir = os.path.join(
                os.path.expanduser("~"), ".eaa", "memory"
            )
        if self.plugin_dir is None:
            self.plugin_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "plugins"
            )


# ═══════════════════════════════════════════════════════════════
# EVENT TYPES
# ═══════════════════════════════════════════════════════════════

class EventType(Enum):
    STATUS = "status"
    THINKING = "thinking"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    ITERATION = "iteration"
    COMPLETE = "complete"
    ERROR = "error"
    WARNING = "warning"
    PERMISSION_REVIEW = "permission_review"
    DRY_RUN_REVIEW = "dry_run_review"
    SESSION_MEMORY_UPDATED = "session_memory_updated"
    SELF_HEAL = "self_heal"
    VRAM_SWAP = "vram_swap"


# ═══════════════════════════════════════════════════════════════
# AGENT STATE
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentState:
    """Track agent execution state across the full loop."""
    iterations: int = 0
    tools_used: int = 0
    successful_tools: int = 0
    failed_tools: int = 0
    retries: int = 0
    start_time: float = field(default_factory=time.time)
    last_tool: str = ""
    consecutive_failures: int = 0
    tasks_delegated: int = 0
    tasks_completed: int = 0
    vram_swaps: int = 0
    self_heals: int = 0

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time

    def to_dict(self) -> Dict:
        return {
            "iterations": self.iterations,
            "tools_used": self.tools_used,
            "successful_tools": self.successful_tools,
            "failed_tools": self.failed_tools,
            "retries": self.retries,
            "elapsed_seconds": round(self.elapsed, 2),
            "tasks_delegated": self.tasks_delegated,
            "tasks_completed": self.tasks_completed,
            "vram_swaps": self.vram_swaps,
            "self_heals": self.self_heals,
        }


# ═══════════════════════════════════════════════════════════════
# MAIN LOOP CLASS
# ═══════════════════════════════════════════════════════════════

class EAAMainLoop:
    """
    Central orchestrator that wires all EAA V4 phases together.

    Creates and connects:
      Phase 0: MasterRouter, WorkerManager, VRAMManager, DryRunProtocol
      Phase 1: PermissionManager, SafetyClassifier
      Phase 2: SmartEditEngine, FileStateTracker, RollbackManager
      Phase 3: ContextManager, ConversationCompactor, TokenTracker
      Phase 4: PromptAssembler, PromptCacheStore, ToolInstructionRegistry
      Phase 5: PluginManager, ModelRegistry, VRAMLifecycle
      Phase 6: ErrorHandler, ValidationHookRegistry, ConcurrentIsolationController
      Phase 7: SessionTranscript, SessionMemory, MemoryExtractor, PromptHistory
    """

    def __init__(
        self,
        brain_manager,
        tool_registry,
        config: MainLoopConfig = None,
    ):
        """
        Args:
            brain_manager: The brain_manager.BrainManager instance for LLM inference.
            tool_registry: Tool registry with all tools registered (base or enhanced).
            config: MainLoopConfig with all settings.
        """
        self.config = config or MainLoopConfig()
        self.brain_manager = brain_manager
        self.tool_registry = tool_registry
        self.state = AgentState()

        # ── Phase 0: Two-Tier Router + Dry-Run Protocol ──
        from .vram_manager import VRAMManager
        from .router import MasterRouter, RoutingDecision
        from .workers import WorkerManager, ToolExecutor
        from .dry_run import DryRunProtocol, DryRunConfig
        from .plan_formatter import PlanFormatter

        self.vram_manager = VRAMManager()
        self.router = MasterRouter(
            tool_descriptions=dict(
                getattr(tool_registry, '_descriptions', {})
            )
        )
        # WorkerManager requires a ToolExecutor wrapping the tool registry.
        executor = ToolExecutor(registry=tool_registry)
        self.worker_manager = WorkerManager(
            tool_executor=executor,
            vram_manager=self.vram_manager,
            brain_manager=brain_manager,
        )
        self.worker_manager._registry = tool_registry
        self.plan_formatter = PlanFormatter()

        dry_run_cfg = DryRunConfig()
        self.dry_run = DryRunProtocol(config=dry_run_cfg, formatter=self.plan_formatter)

        # ── Phase 1: Permission System ──
        from .permissions import PermissionManager
        from .safety_classifier import SafetyClassifier

        self.permission_manager = PermissionManager()
        self.safety_classifier = SafetyClassifier()
        self.permission_manager.set_classifier(self.safety_classifier)

        # ── Phase 2: Smart Edit Engine ──
        from .smart_edit import SmartEditEngine
        from .file_state import FileStateManager
        from .history_index import HistoryIndex
        from .rollback import RollbackManager

        self.file_state = FileStateManager()
        self.history_index = HistoryIndex(project_root=self.config.project_root)
        self.smart_edit = SmartEditEngine(
            file_state_manager=self.file_state,
        )
        self.rollback = RollbackManager(
            project_root=self.config.project_root,
            file_state_manager=self.file_state,
            history_index=self.history_index,
        )

        # ── Phase 3: Context Management Cascade ──
        from .context_manager import ContextManager
        from .conversation_compactor import ConversationCompactor
        from .system_memory import SystemMemory
        from .token_tracker import TokenTracker

        self.token_tracker = TokenTracker()
        self.conversation_compactor = ConversationCompactor()
        self.system_memory = SystemMemory(project_dir=self.config.project_root)
        self.context_manager = ContextManager(
            project_dir=self.config.project_root,
        )

        # ── Phase 4: Prompt Assembly Pipeline ──
        from .prompt_assembler import PromptAssembler, PromptConfig
        from .prompt_cache import PromptCacheStore
        from .tool_instructions import ToolInstructionRegistry

        self.prompt_cache = PromptCacheStore()
        self.tool_instruction_registry = ToolInstructionRegistry()
        self.prompt_assembler = PromptAssembler(
            config=PromptConfig(),
            tool_registry=self.tool_instruction_registry,
            cache_store=self.prompt_cache,
        )

        # ── Phase 5: Plugin Architecture ──
        from .plugin_manager import PluginManager
        from .model_registry import ModelRegistry
        from .vram_lifecycle import VRAMLifecycleManager

        self.model_registry = ModelRegistry(
            total_vram_gb=self.config.total_vram_gb
        )
        self.plugin_manager = PluginManager(
            project_root=self.config.project_root,
        )
        self.vram_lifecycle = VRAMLifecycleManager(
            registry=self.model_registry,
        )

        # ── Phase 6: Self-Healing Loop ──
        from .error_handler import ErrorHandler
        from .validation_hooks import (
            ValidationHookRegistry,
            PythonSyntaxHook,
        )
        from .concurrent_isolation import ConcurrentIsolationController

        self.error_handler = ErrorHandler(
            context_manager=self.context_manager
        )
        self.validation_hooks = ValidationHookRegistry()
        # Register default Python syntax hook
        self.validation_hooks.register("edit_file", PythonSyntaxHook())
        self.validation_hooks.register("create_file", PythonSyntaxHook())
        self.concurrent_isolation = ConcurrentIsolationController()

        # ── Phase 7: Cross-Session Memory ──
        from .session_transcript import SessionTranscript
        from .session_memory import SessionMemory
        from .memory_extractor import MemoryExtractor
        from .prompt_history import PromptHistory

        self.session_transcript = SessionTranscript(
            project_root=self.config.project_root
        )
        self.session_memory = SessionMemory(
            project_root=self.config.project_root
        )
        self.memory_extractor = MemoryExtractor(
            transcript=self.session_transcript
        )
        self.prompt_history = PromptHistory(
            project_root=self.config.project_root
        )

        # ── Session State ──
        self.messages: List[Dict] = []
        self._shutdown_requested = False
        self._sigint_installed = False

        # Build tool descriptions for router from registry
        descriptions = getattr(tool_registry, '_descriptions', {})
        if descriptions:
            self.router.tool_descriptions = descriptions

        # Test-suite aliases
        self.registry = tool_registry
        if hasattr(self, 'error_handler'):
            self.error_handler._context_manager = getattr(self, 'context_manager', None)
        if hasattr(self, 'vram_lifecycle'):
            self.vram_lifecycle._model_registry = getattr(self, 'model_registry', None)
            self.vram_lifecycle._vram_manager = getattr(self, 'vram_manager', None)

        logger.info("[MainLoop] All phases initialized successfully")

    # ═══════════════════════════════════════════════════════════
    # SIGINT VRAM CLEANUP TRAP
    # ═══════════════════════════════════════════════════════════

    def install_sigint_handler(self):
        """
        Install SIGINT handler for clean VRAM release on Ctrl+C.

        Critical for RTX 4060 Ti: ungraceful kill leaves GPU memory
        locked, requiring a full system reboot to recover.

        Flush sequence:
          1. session_transcript.flush()
          2. session_memory.persist_to_disk()
          3. memory_extractor.stop_daemon()
          4. VRAMManager.unload_all() / brain_manager.unload()

        Must complete within 5 seconds to avoid SIGKILL.
        """
        if self._sigint_installed:
            return

        def _sigint_handler(signum, frame):
            logger.info("[SIGINT] Ctrl+C trapped — cleaning up...")
            self._shutdown_requested = True
            self._emergency_cleanup()
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            raise SystemExit(0)

        signal.signal(signal.SIGINT, _sigint_handler)
        self._sigint_installed = True
        logger.info("[MainLoop] SIGINT handler installed (VRAM-safe shutdown)")

    def _emergency_cleanup(self):
        """Flush all state and release VRAM within 5 seconds."""
        deadline = time.time() + 5.0

        # Step 1: Flush transcript
        try:
            self.session_transcript.flush()
            logger.info("[Cleanup] Transcript flushed")
        except Exception as e:
            logger.error(f"[Cleanup] Transcript flush failed: {e}")

        # Step 2: Persist session memory
        try:
            if hasattr(self.session_memory, 'persist_to_disk'):
                self.session_memory.persist_to_disk()
            logger.info("[Cleanup] Session memory persisted")
        except Exception as e:
            logger.error(f"[Cleanup] Session memory persist failed: {e}")

        # Step 3: Stop memory extractor daemon
        try:
            self.memory_extractor.stop_daemon()
            logger.info("[Cleanup] Memory extractor daemon stopped")
        except Exception as e:
            logger.error(f"[Cleanup] Daemon stop failed: {e}")

        # Step 4: Unload all models (VRAM)
        try:
            if self.brain_manager and self.brain_manager.current_model_id:
                self.brain_manager.unload()
            logger.info("[Cleanup] Brain manager unloaded")
        except Exception as e:
            logger.error(f"[Cleanup] Brain unload failed: {e}")

        # Step 5: Force VRAM cleanup
        try:
            self.vram_manager.force_cleanup()
            logger.info("[Cleanup] VRAM force cleanup done")
        except Exception as e:
            logger.error(f"[Cleanup] VRAM cleanup failed: {e}")

        elapsed = time.time() - (deadline - 5.0)
        logger.info(
            f"[Cleanup] Complete in {elapsed:.2f}s "
            f"(deadline: 5.0s)"
        )

    # ═══════════════════════════════════════════════════════════
    # SESSION MANAGEMENT
    # ═══════════════════════════════════════════════════════════

    def resume_session(self) -> List[Dict]:
        """
        Resume a previous session by loading transcript history.
        Returns messages ready for context injection.
        """
        turns = self.session_transcript.resume(
            max_tokens=self.config.transcript_resume_max_tokens
        )
        if turns:
            self.messages = [
                {"role": t["role"], "content": t["content"]}
                for t in turns
            ]
            logger.info(
                f"[MainLoop] Session resumed: {len(self.messages)} messages"
            )
        return self.messages

    def end_session(self):
        """
        End current session gracefully.
        Triggers memory extraction and persists all state.
        """
        logger.info("[MainLoop] Ending session...")

        # Trigger memory extraction at exit
        try:
            entries = self.memory_extractor.trigger_on_exit()
            logger.info(
                f"[MainLoop] Memory extraction: {len(entries)} entries"
            )
        except Exception as e:
            logger.error(f"[MainLoop] Memory extraction failed: {e}")

        # Flush transcript
        try:
            self.session_transcript.flush()
        except Exception as e:
            logger.error(f"[MainLoop] Transcript flush failed: {e}")

        # Persist session memory notes
        try:
            if hasattr(self.session_memory, 'persist_to_disk'):
                self.session_memory.persist_to_disk()
        except Exception as e:
            logger.error(f"[MainLoop] Session memory persist failed: {e}")

        logger.info("[MainLoop] Session ended")

    # ═══════════════════════════════════════════════════════════
    # SYSTEM PROMPT ASSEMBLY
    # ═══════════════════════════════════════════════════════════

    def _build_system_prompt(self, brain_type: str = "master") -> str:
        """
        Assemble the full system prompt using Phase 4 pipeline.
        Injects tool instructions, memory, and session context.
        """
        # Get tool descriptions for prompt
        tool_descriptions = {}
        if hasattr(self.tool_registry, '_descriptions'):
            tool_descriptions = self.tool_registry._descriptions
        elif hasattr(self.tool_registry, 'get_all_descriptions'):
            tool_descriptions = self.tool_registry.get_all_descriptions()

        # Register tools with instruction registry
        from .tool_instructions import ToolInstruction
        for name, desc in tool_descriptions.items():
            self.tool_instruction_registry.register(ToolInstruction(name=name, description=desc, usage=desc))

        # Build prompt via Phase 4 assembler
        tool_names = list(tool_descriptions.keys()) if tool_descriptions else None
        assembled = self.prompt_assembler.assemble(
            tool_names=tool_names,
        )

        return assembled.full_prompt

        return assembled

    # ═══════════════════════════════════════════════════════════
    # CORE AGENT LOOP
    # ═══════════════════════════════════════════════════════════

    def run(
        self,
        user_message: str,
        brain_type: str = "master",
        brain_id: str = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Run the full V4 agent loop on a user message.

        Yields events as the agent progresses through phases:
          1. Permission check (Phase 1)
          2. Safety classification (Phase 1)
          3. Routing decision (Phase 0)
          4. Dry-run review if needed (Phase 0)
          5. Delegation to workers (Phase 0)
          6. Context management (Phase 3)
          7. Prompt assembly (Phase 4)
          8. LLM inference via brain_manager
          9. Error handling (Phase 6)
          10. Memory update (Phase 7)
        """
        # Reset state for new task
        self.state = AgentState()
        self.messages = [{"role": "user", "content": user_message}]

        # Record in prompt history
        self.prompt_history.append(user_message)

        yield {
            "type": EventType.STATUS.value,
            "message": f"Agent started with {brain_type} brain..."
        }

        # ── Step 1: Record user turn in transcript ──
        self.session_transcript.append_turn("user", user_message)

        # ── Step 2: Build system prompt ──
        system_prompt = self._build_system_prompt(brain_type)

        # ── Step 3: Main iteration loop ──
        while self.state.iterations < self.config.max_iterations:
            if self._shutdown_requested:
                yield {
                    "type": EventType.WARNING.value,
                    "message": "Shutdown requested"
                }
                break

            self.state.iterations += 1

            yield {
                "type": EventType.ITERATION.value,
                "iteration": self.state.iterations,
                "max_iterations": self.config.max_iterations,
            }

            # ── Route: Decide Master handles directly or delegates ──
            routing = self.router.route_heuristic(user_message)

            if routing.tasks:
                # Phase 0: Delegation path
                yield from self._run_delegation(
                    routing, brain_type, brain_id, system_prompt
                )
            else:
                # Direct path: Master responds
                yield from self._run_direct(
                    brain_type, brain_id, system_prompt
                )

            # Check for completion signals in the last assistant message
            last_msg = self.messages[-1] if self.messages else {}
            content = last_msg.get("content", "")

            if self._is_complete(content):
                summary = self._extract_completion_summary(content)
                yield {
                    "type": EventType.COMPLETE.value,
                    "status": "success",
                    "summary": summary,
                    "state": self.state.to_dict(),
                }
                break

        # Iteration limit reached
        if self.state.iterations >= self.config.max_iterations:
            yield {
                "type": EventType.WARNING.value,
                "message": f"Max iterations reached ({self.config.max_iterations})",
            }
            yield {
                "type": EventType.COMPLETE.value,
                "status": "partial",
                "summary": "Task may be incomplete due to iteration limit",
                "state": self.state.to_dict(),
            }

    def _run_delegation(
        self,
        routing,
        brain_type: str,
        brain_id: str,
        system_prompt: str,
    ) -> Generator[Dict[str, Any], None, None]:
        """Execute a delegated task through Phase 0 router/worker pipeline."""
        # Phase 0: Dry-run review
        if self.config.enable_dry_run:
            dry_result = self.dry_run.review(routing.tasks)
            if dry_result.needs_approval:
                yield {
                    "type": EventType.DRY_RUN_REVIEW.value,
                    "tasks": dry_result.task_summaries,
                    "message": "Awaiting approval for delegated tasks",
                }

        # Phase 1: Permission check on tasks
        perm_result = self.permission_manager.check_tasks(routing.tasks)
        if perm_result.has_blocks():
            yield {
                "type": EventType.PERMISSION_REVIEW.value,
                "blocked": perm_result.get_block_reasons(),
                "message": "Some tasks blocked by permissions",
            }

        # Phase 6: Register sibling group for concurrent isolation
        group_id = self.concurrent_isolation.register_batch(routing.tasks)

        # Execute tasks via workers
        results = []
        for task in routing.tasks:
            if self.concurrent_isolation.check_cancelled(task.task_id):
                continue

            try:
                worker_result = self.worker_manager.execute_task(task)
                results.append(worker_result)

                # Phase 6: Report completion/failure
                if not worker_result.success:
                    self.concurrent_isolation.report_completion(
                        group_id, task.task_id,
                        success=False, error=worker_result.error
                    )

                yield {
                    "type": EventType.TOOL_RESULT.value,
                    "tool": task.tool_name or task.description[:30],
                    "success": worker_result.success,
                    "output": (
                        worker_result.output[:self.config.max_tool_output]
                        if worker_result.success else None
                    ),
                    "error": worker_result.error,
                    "iteration": self.state.iterations,
                }
            except Exception as e:
                # Phase 6: Error handler wraps errors as is_error
                error_result = self.error_handler.wrap_error_as_tool_result(
                    e, task.tool_name or "unknown"
                )
                self.concurrent_isolation.report_completion(
                    group_id, task.task_id,
                    success=False, error=str(e), critical=False
                )
                yield {
                    "type": EventType.TOOL_RESULT.value,
                    "tool": task.tool_name or "unknown",
                    "success": False,
                    "error": str(e),
                    "iteration": self.state.iterations,
                }

        # Synthesize results via brain (Master's job)
        if results:
            synthesis_input = self._synthesize_results(results)
            response = self._generate_with_brain(
                brain_type, brain_id, system_prompt, synthesis_input
            )
            self.messages.append({"role": "assistant", "content": response})
            self.session_transcript.append_turn("assistant", response)

    def _run_direct(
        self,
        brain_type: str,
        brain_id: str,
        system_prompt: str,
    ) -> Generator[Dict[str, Any], None, None]:
        """Master handles the request directly without delegation."""
        conversation = self._format_conversation()
        response = self._generate_with_brain(
            brain_type, brain_id, system_prompt, conversation
        )

        # Phase 6: JSON decode error interception
        parsed = self.error_handler.intercept_json_decode(
            response, "main_loop"
        )
        if isinstance(parsed, dict) and parsed.get("is_error"):
            # Feed error back for self-healing
            self.state.self_heals += 1
            yield {
                "type": EventType.SELF_HEAL.value,
                "message": parsed.get("content", "JSON parse error"),
            }
            self.messages.append({
                "role": "user",
                "content": parsed.get("content", ""),
            })
            return

        self.messages.append({"role": "assistant", "content": response})
        self.session_transcript.append_turn("assistant", response)

    def _generate_with_brain(
        self,
        brain_type: str,
        brain_id: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Generate text using the brain manager with error recovery."""
        model_id = brain_id
        if model_id is None:
            # Default model selection based on brain_type
            model_map = {
                "master": "unsloth/Qwen2.5-7B-Instruct-bnb-4bit",
                "shadow": None,  # Will use currently loaded model
                "coder": "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit",
            }
            model_id = model_map.get(brain_type)

        try:
            response = self.brain_manager.generate_text(
                model_id=model_id or self.brain_manager.current_model_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_new_tokens=1024,
                temperature=0.7,
            )
            return response or ""
        except Exception as e:
            # Phase 6: Error handler
            logger.error(f"[MainLoop] Generation error: {e}")
            recovery = self.error_handler.handle_truncation(
                str(e), "error"
            )
            return f"[Error: {e}]"

    # ═══════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════

    def _format_conversation(self) -> str:
        """Format messages for brain input."""
        parts = []
        for msg in self.messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
            elif role == "tool":
                parts.append(f"Tool Result: {content}")
        return "\n\n".join(parts) + "\n\nAssistant:"

    def _synthesize_results(self, results: list) -> str:
        """Synthesize worker results for Master review."""
        parts = []
        for i, result in enumerate(results):
            status = "OK" if result.success else "FAIL"
            output = result.output[:500] if result.success else result.error
            parts.append(f"[Result {i+1} ({status})]: {output}")
        return "\n".join(parts) + "\n\nSynthesize these results into a clear response for the user."

    def _is_complete(self, text: str) -> bool:
        """Check if the task is complete."""
        markers = [
            "TASK_COMPLETE:", "TASK_DONE:", "DONE:",
            "[COMPLETE]", "[DONE]",
        ]
        text_upper = text.upper()
        return any(m in text_upper for m in markers)

    def _extract_completion_summary(self, text: str) -> str:
        """Extract summary from completion marker."""
        for marker in ["TASK_COMPLETE:", "TASK_DONE:", "DONE:"]:
            idx = text.upper().find(marker)
            if idx != -1:
                start = idx + len(marker)
                return text[start:].strip()[:500]
        return text[:500]

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive status of all subsystems."""
        return {
            "state": self.state.to_dict(),
            "messages_count": len(self.messages),
            "phases": {
                "phase0_router": self.router.get_stats() if hasattr(self.router, 'get_stats') else {},
                "phase0_dry_run": self.dry_run.get_stats() if hasattr(self.dry_run, 'get_stats') else {},
                "phase1_permissions": self.permission_manager.get_stats() if hasattr(self.permission_manager, 'get_stats') else {},
                "phase2_smart_edit": self.smart_edit.get_stats() if hasattr(self.smart_edit, 'get_stats') else {},
                "phase3_context": self.context_manager.get_stats() if hasattr(self.context_manager, 'get_stats') else {},
                "phase6_error_handler": {
                    "tier": self.error_handler.get_current_max_tokens() if hasattr(self.error_handler, 'get_current_max_tokens') else 0,
                    "exhausted": self.error_handler.is_exhausted() if hasattr(self.error_handler, 'is_exhausted') else False,
                },
                "phase6_isolation": self.concurrent_isolation.get_stats() if hasattr(self.concurrent_isolation, 'get_stats') else {},
                "phase7_transcript": {
                    "turns": self.session_transcript.get_turn_count() if hasattr(self.session_transcript, 'get_turn_count') else 0,
                },
                "phase7_session_memory": {
                    "token_count": self.session_memory.get_token_count() if hasattr(self.session_memory, 'get_token_count') else 0,
                },
            },
            "brain_loaded": (
                self.brain_manager.current_model_id
                if self.brain_manager
                else None
            ),
            "tools_available": (
                self.tool_registry.list_tools()
                if hasattr(self.tool_registry, 'list_tools')
                else []
            ),
        }


# ═══════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def create_main_loop(
    brain_manager,
    tool_registry,
    project_root: str = ".",
    **kwargs,
) -> EAAMainLoop:
    """Create and configure the main loop."""
    config = MainLoopConfig(project_root=project_root, **kwargs)
    loop = EAAMainLoop(
        brain_manager=brain_manager,
        tool_registry=tool_registry,
        config=config,
    )
    loop.install_sigint_handler()
    return loop


def event_to_sse(event: Dict[str, Any]) -> str:
    """Convert event dict to Server-Sent Events format."""
    return f"data: {json.dumps(event)}\n\n"


__all__ = [
    "EAAMainLoop",
    "MainLoopConfig",
    "AgentState",
    "EventType",
    "create_main_loop",
    "event_to_sse",
]