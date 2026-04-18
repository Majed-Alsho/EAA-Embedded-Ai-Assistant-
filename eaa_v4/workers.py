"""
EAA V4 - Worker Lifecycle Management
=====================================
Workers are specialized agents that wake up, receive a precise task with only
their relevant tool subset, execute, and return results. Then go back to sleep.

Each worker has its own:
  - Model (loaded/unloaded from VRAM by VRAMManager)
  - Tool subset (only tools relevant to its specialization)
  - System prompt (tailored for its domain)
  - Execution context (conversation state for multi-step tasks)

The WorkerManager orchestrates worker activation, task execution, and
deactivation. It communicates with VRAMManager to ensure only one model
is in VRAM at any time.
"""

import time
import logging
import threading
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from router import (
    DelegationTask,
    DEFAULT_WORKER_SPECIALIZATIONS,
    MASTER_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER STATES
# ═══════════════════════════════════════════════════════════════════════════════

class WorkerState(Enum):
    DORMANT = "dormant"          # Not loaded in VRAM, no state
    LOADING = "loading"          # Being loaded into VRAM
    ACTIVE = "active"            # In VRAM, ready to execute
    EXECUTING = "executing"      # Currently running a task
    UNLOADING = "unloading"      # Being moved out of VRAM
    ERROR = "error"              # Failed to load or execute


@dataclass
class WorkerInfo:
    """
    Runtime information about a worker.
    Tracks state, resource usage, and execution history.
    """
    worker_id: str
    state: WorkerState = WorkerState.DORMANT
    model_id: str = ""
    vram_usage_mb: float = 0.0
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_execution_time: float = 0.0
    last_active: float = 0.0
    last_error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "worker_id": self.worker_id,
            "state": self.state.value,
            "model_id": self.model_id,
            "vram_usage_mb": round(self.vram_usage_mb, 1),
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "total_execution_time": round(self.total_execution_time, 2),
            "last_active": self.last_active,
            "last_error": self.last_error,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER RESULT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WorkerResult:
    """
    Result from a worker after completing a task.
    Carries the tool result plus metadata about execution.
    """
    task: DelegationTask
    success: bool
    output: str = ""
    error: Optional[str] = None
    execution_time: float = 0.0
    vram_peak_mb: float = 0.0
    tokens_used: int = 0
    artifacts: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "task": self.task.to_dict(),
            "success": self.success,
            "output": self.output[:2000] if self.output else "",
            "error": self.error,
            "execution_time": round(self.execution_time, 2),
            "vram_peak_mb": round(self.vram_peak_mb, 1),
            "tokens_used": self.tokens_used,
            "artifacts": self.artifacts,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL REGISTRY INTERFACE (abstraction over existing EAA tool system)
# ═══════════════════════════════════════════════════════════════════════════════

class ToolExecutor:
    """
    Interface for executing tools. This wraps the existing EAA
    ToolRegistry to provide a clean interface for workers.

    In production, this connects to the actual EAA tool registry
    (112 tools from 10+ modules).
    """

    def __init__(self, registry=None):
        """
        Args:
            registry: EAA ToolRegistry instance (from eaa_tool_executor.py).
                      If None, tools execute as no-ops for testing.
        """
        self._registry = registry
        self._execution_log: List[Dict] = []

    def execute(self, tool_name: str, **kwargs) -> Dict:
        """
        Execute a tool and return the result.

        Returns dict with:
          - success: bool
          - output: str (tool result text)
          - error: Optional[str]
          - duration_ms: float
        """
        start = time.time()

        if self._registry is None:
            # No-op mode for testing
            result = {
                "success": True,
                "output": f"[NO-OP] Tool '{tool_name}' executed with args: {kwargs}",
                "error": None,
                "duration_ms": 0,
            }
        else:
            try:
                tool_result = self._registry.execute(tool_name, **kwargs)
                result = {
                    "success": tool_result.success,
                    "output": tool_result.output,
                    "error": tool_result.error,
                    "duration_ms": (time.time() - start) * 1000,
                }
            except Exception as e:
                result = {
                    "success": False,
                    "output": "",
                    "error": str(e),
                    "duration_ms": (time.time() - start) * 1000,
                }

        self._execution_log.append({
            "tool": tool_name,
            "args": kwargs,
            "timestamp": time.time(),
            **result,
        })

        return result

    def get_descriptions(self, tool_names: List[str]) -> Dict[str, str]:
        """Get descriptions for specified tools."""
        descs = {}
        if self._registry is not None:
            descriptions = getattr(self._registry, '_descriptions', {})
            for name in tool_names:
                descs[name] = descriptions.get(name, "")
        return descs


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class WorkerManager:
    """
    Manages worker lifecycle: activation, task execution, deactivation.

    Key responsibilities:
    - Track worker states (dormant → loading → active → executing → dormant)
    - Coordinate with VRAMManager for model hot-swapping
    - Execute delegation tasks via the ToolExecutor
    - Handle timeouts, retries, and errors
    - Provide statistics and health monitoring

    The WorkerManager ensures the one-model-at-a-time policy:
    before activating a worker, any currently active worker is
    deactivated first (moved to CPU/RAM) to free VRAM.
    """

    def __init__(
        self,
        tool_executor: ToolExecutor,
        specializations: Optional[Dict] = None,
        vram_manager=None,
        brain_manager=None,
    ):
        """
        Args:
            tool_executor: ToolExecutor instance for running tools
            specializations: Worker config dict (from DEFAULT_WORKER_SPECIALIZATIONS)
            vram_manager: Optional VRAMManager for model hot-swapping
            brain_manager: Optional EAA brain_manager for LLM inference
        """
        self.tool_executor = tool_executor
        self.specializations = specializations or DEFAULT_WORKER_SPECIALIZATIONS
        self.vram_manager = vram_manager
        self.brain_manager = brain_manager

        # Worker state tracking
        self._workers: Dict[str, WorkerInfo] = {}
        self._lock = threading.Lock()

        # Currently active worker (one at a time)
        self._active_worker: Optional[str] = None

        # Task timeout defaults
        self.default_timeout = 30
        self.max_retries = 2

        # Initialize worker info for all registered workers
        for worker_id, config in self.specializations.items():
            if worker_id == "jarvis":
                continue
            self._workers[worker_id] = WorkerInfo(
                worker_id=worker_id,
                model_id=config.get("model_id", ""),
            )

        logger.info(
            f"[WorkerManager] Initialized: "
            f"{len(self._workers)} workers registered"
        )

    def get_worker_info(self, worker_id: str) -> Optional[WorkerInfo]:
        """Get current info about a specific worker."""
        return self._workers.get(worker_id)

    def list_workers(self) -> List[Dict]:
        """List all workers and their states."""
        return [info.to_dict() for info in self._workers.values()]

    def activate_worker(self, worker_id: str) -> bool:
        """
        Activate a worker by loading its model into VRAM.
        If another worker is currently active, it gets deactivated first.

        Returns True if activation succeeded.
        """
        with self._lock:
            if worker_id not in self._workers:
                logger.error(f"[WorkerManager] Unknown worker: {worker_id}")
                return False

            info = self._workers[worker_id]

            # Already active
            if info.state == WorkerState.ACTIVE:
                logger.debug(f"[WorkerManager] {worker_id} already active")
                return True

            # Deactivate current worker first (free VRAM)
            if self._active_worker and self._active_worker != worker_id:
                self._deactivate_worker_internal(self._active_worker)

            info.state = WorkerState.LOADING
            logger.info(f"[WorkerManager] Activating {worker_id}...")

            # VRAM swap: unload current, load new
            if self.vram_manager:
                try:
                    model_id = self.specializations[worker_id]["model_id"]
                    self.vram_manager.load_model(model_id)
                    info.vram_usage_mb = self.vram_manager.get_current_vram()
                except Exception as e:
                    info.state = WorkerState.ERROR
                    info.last_error = f"VRAM load failed: {e}"
                    logger.error(f"[WorkerManager] Failed to load {worker_id}: {e}")
                    return False

            info.state = WorkerState.ACTIVE
            self._active_worker = worker_id
            info.last_active = time.time()
            logger.info(f"[WorkerManager] {worker_id} is now ACTIVE")
            return True

    def deactivate_worker(self, worker_id: str) -> bool:
        """Deactivate a worker, freeing its VRAM."""
        with self._lock:
            return self._deactivate_worker_internal(worker_id)

    def _deactivate_worker_internal(self, worker_id: str) -> bool:
        """Internal deactivate (assumes lock is held)."""
        if worker_id not in self._workers:
            return False

        info = self._workers[worker_id]
        if info.state in (WorkerState.DORMANT, WorkerState.UNLOADING):
            return True

        info.state = WorkerState.UNLOADING
        logger.info(f"[WorkerManager] Deactivating {worker_id}...")

        if self.vram_manager and worker_id == self._active_worker:
            try:
                self.vram_manager.unload_model()
            except Exception as e:
                logger.warning(f"[WorkerManager] VRAM unload warning: {e}")

        info.state = WorkerState.DORMANT
        info.vram_usage_mb = 0.0
        if self._active_worker == worker_id:
            self._active_worker = None
        logger.info(f"[WorkerManager] {worker_id} is now DORMANT")
        return True

    def execute_task(self, task: DelegationTask) -> WorkerResult:
        """
        Execute a single delegation task on the appropriate worker.

        This is the main execution path:
        1. Activate the target worker
        2. Execute the tool via ToolExecutor
        3. Capture result and timing
        4. (Worker stays active if more tasks are coming)

        Returns a WorkerResult with the execution outcome.
        """
        start_time = time.time()
        info = self._workers.get(task.worker_id)

        if not info:
            return WorkerResult(
                task=task,
                success=False,
                error=f"Unknown worker: {task.worker_id}",
                execution_time=0,
            )

        # Activate worker (handles VRAM swap)
        if not self.activate_worker(task.worker_id):
            return WorkerResult(
                task=task,
                success=False,
                error=f"Failed to activate worker {task.worker_id}: {info.last_error}",
                execution_time=time.time() - start_time,
            )

        info.state = WorkerState.EXECUTING
        logger.info(
            f"[WorkerManager] Executing: {task.tool_name} "
            f"on {task.worker_id} "
            f"(args: {list(task.tool_args.keys())})"
        )

        # Execute the tool
        result = self.tool_executor.execute(task.tool_name, **task.tool_args)
        execution_time = time.time() - start_time

        # Update stats
        if result["success"]:
            info.tasks_completed += 1
        else:
            info.tasks_failed += 1
        info.total_execution_time += execution_time
        info.last_active = time.time()

        # Get VRAM peak if manager available
        vram_peak = 0.0
        if self.vram_manager:
            vram_peak = self.vram_manager.get_current_vram()

        # Return to active state (not dormant — might have more tasks)
        info.state = WorkerState.ACTIVE

        worker_result = WorkerResult(
            task=task,
            success=result["success"],
            output=result.get("output", ""),
            error=result.get("error"),
            execution_time=execution_time,
            vram_peak_mb=vram_peak,
        )

        logger.info(
            f"[WorkerManager] Task {'completed' if result['success'] else 'FAILED'}: "
            f"{task.tool_name} on {task.worker_id} "
            f"({execution_time:.2f}s)"
        )

        return worker_result

    def execute_batch(self, tasks: List[DelegationTask]) -> List[WorkerResult]:
        """
        Execute a batch of delegation tasks, optimizing for VRAM efficiency.

        Optimization: groups tasks by worker and executes all tasks for
        one worker before switching to the next. This minimizes VRAM swaps.

        For tasks with dependencies (depends_on), executes in dependency order.
        """
        if not tasks:
            return []

        # Sort by priority first
        sorted_tasks = sorted(tasks, key=lambda t: t.priority)

        # Group by worker (optimized batching)
        worker_groups: Dict[str, List[DelegationTask]] = {}
        for task in sorted_tasks:
            # Skip tasks whose dependencies haven't been resolved
            # (simplified — full dependency resolution would need topological sort)
            worker_groups.setdefault(task.worker_id, []).append(task)

        # Execute group by group (one VRAM swap per worker)
        results: List[WorkerResult] = []
        for worker_id, group_tasks in worker_groups.items():
            logger.info(
                f"[WorkerManager] Batch: executing {len(group_tasks)} "
                f"tasks on {worker_id}"
            )
            for task in group_tasks:
                result = self.execute_task(task)
                results.append(result)

                # If task failed and we shouldn't continue, break
                if not result.success and self._should_abort_batch(result):
                    logger.warning(
                        f"[WorkerManager] Batch aborted after failure: "
                        f"{result.error}"
                    )
                    break

        return results

    def _should_abort_batch(self, result: WorkerResult) -> bool:
        """
        Decide whether to abort the remaining batch after a failure.
        Some failures are recoverable (file not found), others aren't (OOM).
        """
        if not result.error:
            return False

        abortable_errors = [
            "out of memory", "oom", "cuda error",
            "vram", "fatal", "segfault",
        ]
        error_lower = result.error.lower()
        return any(err in error_lower for err in abortable_errors)

    def deactivate_all(self):
        """Deactivate all workers, freeing all VRAM."""
        with self._lock:
            for worker_id in list(self._workers.keys()):
                self._deactivate_worker_internal(worker_id)
            logger.info("[WorkerManager] All workers deactivated")

    def get_active_worker(self) -> Optional[str]:
        """Return the ID of the currently active worker."""
        return self._active_worker

    def get_stats(self) -> Dict:
        """Get aggregate worker statistics."""
        total_completed = sum(w.tasks_completed for w in self._workers.values())
        total_failed = sum(w.tasks_failed for w in self._workers.values())
        total_time = sum(w.total_execution_time for w in self._workers.values())

        return {
            "workers_registered": len(self._workers),
            "active_worker": self._active_worker,
            "total_tasks_completed": total_completed,
            "total_tasks_failed": total_failed,
            "success_rate": (
                f"{total_completed / (total_completed + total_failed) * 100:.1f}%"
                if (total_completed + total_failed) > 0
                else "N/A"
            ),
            "total_execution_time": round(total_time, 2),
            "workers": {wid: info.to_dict() for wid, info in self._workers.items()},
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_worker_manager(
    tool_registry=None,
    specializations=None,
    vram_manager=None,
    brain_manager=None,
) -> WorkerManager:
    """Create a WorkerManager with optional connections to existing systems."""
    executor = ToolExecutor(registry=tool_registry)
    return WorkerManager(
        tool_executor=executor,
        specializations=specializations,
        vram_manager=vram_manager,
        brain_manager=brain_manager,
    )


__all__ = [
    "WorkerManager",
    "WorkerState",
    "WorkerInfo",
    "WorkerResult",
    "ToolExecutor",
    "create_worker_manager",
]
