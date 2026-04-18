"""
EAA V4 - Concurrent Isolation Controller (Phase 6, Component 3)
===============================================================
Sibling-aware failure containment for parallel tool executions.

From the blueprint (Section 3.3):
  When the Master dispatches multiple DelegationTasks in parallel (batch),
  a critical failure in one task (e.g., OOM, file lock conflict) can
  necessitate cancelling all sibling tasks to maintain consistency.

  The ConcurrentIsolationController tracks sibling groups — sets of tasks
  dispatched together — and provides:
    - Critical failure propagation: Cancel all siblings on OOM/fatal errors
    - Non-critical failure isolation: Individual task failures don't affect
      siblings unless explicitly marked critical
    - Cancellation checks: Workers poll check_cancelled() before each step
    - Group lifecycle management: Register, complete, fail, cleanup

  This prevents wasted VRAM/compute when a critical dependency fails
  and subsequent tasks would be operating on stale or inconsistent state.

Integration:
  - Uses DelegationTask from router.py for task identification
  - Thread-safe for use with concurrent worker execution
  - Designed to be called from WorkerManager.execute_batch()

Usage:
    controller = ConcurrentIsolationController()
    group_id = controller.register_batch(tasks)

    for task in tasks:
        if controller.check_cancelled(task_id):
            continue  # Skip cancelled task
        try:
            result = execute(task)
            controller.report_completion(group_id, task_id)
        except OOMError as e:
            controller.report_failure(group_id, task_id, str(e), critical=True)
            # All siblings automatically cancelled

    controller.cleanup_group(group_id)
"""

import time
import threading
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TASK STATUS TYPES
# ═══════════════════════════════════════════════════════════════════════════════

class TaskStatus(Enum):
    """Status of a task within a sibling group."""
    PENDING = "pending"        # Not yet started
    RUNNING = "running"        # Currently executing
    COMPLETED = "completed"    # Finished successfully
    FAILED = "failed"          # Failed (non-critical)
    CANCELLED = "cancelled"    # Cancelled due to sibling failure


# ═══════════════════════════════════════════════════════════════════════════════
# SIBLING GROUP
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SiblingGroup:
    """
    A group of tasks dispatched together as a batch.

    All tasks in a sibling group share a common fate: if one fails
    critically, all remaining tasks are cancelled.

    Attributes:
        group_id: Unique identifier for this sibling group.
        task_ids: List of task IDs belonging to this group.
        status: Dict mapping task_id to its current TaskStatus.
        created_at: Unix timestamp when the group was created.
        critical_error: The first critical error that triggered cancellation.
    """
    group_id: str
    task_ids: List[str] = field(default_factory=list)
    status: Dict[str, TaskStatus] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    critical_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "task_ids": self.task_ids,
            "status": {tid: s.value for tid, s in self.status.items()},
            "created_at": self.created_at,
            "critical_error": self.critical_error,
            "pending_count": sum(
                1 for s in self.status.values()
                if s == TaskStatus.PENDING
            ),
            "running_count": sum(
                1 for s in self.status.values()
                if s == TaskStatus.RUNNING
            ),
            "completed_count": sum(
                1 for s in self.status.values()
                if s == TaskStatus.COMPLETED
            ),
            "failed_count": sum(
                1 for s in self.status.values()
                if s == TaskStatus.FAILED
            ),
            "cancelled_count": sum(
                1 for s in self.status.values()
                if s == TaskStatus.CANCELLED
            ),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CONCURRENT ISOLATION CONTROLLER
# ═══════════════════════════════════════════════════════════════════════════════

# Error patterns that trigger critical (sibling-cancelling) failures.
CRITICAL_ERROR_PATTERNS = [
    "out of memory", "oom", "cuda error", "cuda runtime error",
    "vram", "fatal", "segfault", "segmentation fault",
    "kernel panic", "gpu error", "device-side assert",
]


class ConcurrentIsolationController:
    """
    Manages sibling groups for parallel task execution with failure containment.

    When the Master dispatches a batch of DelegationTasks, this controller:
      1. Registers all tasks as a sibling group
      2. Tracks individual task status (pending → running → completed/failed)
      3. On critical failure: cancels all remaining siblings
      4. Provides cancellation checks for workers to poll

    Thread Safety:
      All public methods are thread-safe via an internal threading.Lock.

    Critical vs Non-Critical Failures:
      - Critical (OOM, CUDA error, segfault): All siblings are cancelled
        because the GPU state is likely corrupted.
      - Non-critical (file not found, permission denied): Only the failing
        task is marked as failed; siblings continue independently.

    Usage:
        controller = ConcurrentIsolationController()

        # Register a batch of parallel tasks
        group_id = controller.register_batch(tasks)

        # Before executing each task, check cancellation
        for task in tasks:
            if controller.check_cancelled(task.tool_name + "_" + str(task.priority)):
                continue

            try:
                result = worker.execute(task)
                controller.report_completion(group_id, task.tool_name)
            except Exception as e:
                is_critical = "oom" in str(e).lower()
                controller.report_failure(
                    group_id, task.tool_name, str(e), critical=is_critical
                )

        # Clean up after batch completes
        controller.cleanup_group(group_id)
    """

    def __init__(self):
        self._groups: Dict[str, SiblingGroup] = {}
        self._cancelled_tasks: Set[str] = set()
        self._lock = threading.Lock()

        logger.debug("[ConcurrentIsolation] Controller initialized")

    def _extract_task_id(self, task: Any) -> str:
        """
        Extract a task ID from a DelegationTask-like object or dict.

        Args:
            task: Object with tool_name attribute, or dict with "tool_name" key.

        Returns:
            A string task identifier.
        """
        if hasattr(task, "tool_name"):
            name = getattr(task, "tool_name", "unknown")
            priority = getattr(task, "priority", 0)
            return f"{name}_{priority}"
        if isinstance(task, dict):
            return task.get("tool_name", str(task))
        return str(task)

    def register_batch(self, tasks: list) -> str:
        """
        Register a batch of tasks as a sibling group.

        Each task is expected to have a ``tool_name`` attribute (or be a dict
        with a "tool_name" key). A unique group_id is generated.

        Args:
            tasks: List of DelegationTask instances or dicts with tool_name.

        Returns:
            The group_id string for tracking this batch.
        """
        group_id = f"batch_{int(time.time() * 1000)}_{id(tasks)}"
        group = SiblingGroup(group_id=group_id)

        for task in tasks:
            task_id = self._extract_task_id(task)
            group.task_ids.append(task_id)
            group.status[task_id] = TaskStatus.PENDING

        with self._lock:
            self._groups[group_id] = group

        logger.info(
            f"[ConcurrentIsolation] Registered group '{group_id}' "
            f"with {len(group.task_ids)} tasks"
        )
        return group_id

    def report_completion(self, group_id: str, task_id: str) -> None:
        """
        Report that a task has completed successfully.

        Args:
            group_id: The sibling group identifier.
            task_id: The ID of the completed task.
        """
        with self._lock:
            group = self._groups.get(group_id)
            if group is None:
                logger.warning(
                    f"[ConcurrentIsolation] Unknown group '{group_id}' "
                    f"for completion report"
                )
                return

            if task_id in group.status:
                group.status[task_id] = TaskStatus.COMPLETED
                logger.debug(
                    f"[ConcurrentIsolation] Task '{task_id}' completed "
                    f"in group '{group_id}'"
                )

    def report_failure(
        self,
        group_id: str,
        task_id: str,
        error: str,
        critical: bool = False,
    ) -> None:
        """
        Report that a task has failed.

        If critical=True, all sibling tasks that are still PENDING or
        RUNNING will be marked as CANCELLED. This prevents wasted
        compute on tasks that depend on a now-inconsistent state.

        Args:
            group_id: The sibling group identifier.
            task_id: The ID of the failed task.
            error: Error message describing the failure.
            critical: If True, cancel all remaining sibling tasks.
        """
        with self._lock:
            group = self._groups.get(group_id)
            if group is None:
                logger.warning(
                    f"[ConcurrentIsolation] Unknown group '{group_id}' "
                    f"for failure report"
                )
                return

            if task_id not in group.status:
                logger.warning(
                    f"[ConcurrentIsolation] Unknown task '{task_id}' "
                    f"in group '{group_id}'"
                )
                return

            group.status[task_id] = TaskStatus.FAILED

            if critical:
                group.critical_error = error
                logger.warning(
                    f"[ConcurrentIsolation] CRITICAL failure on task "
                    f"'{task_id}' in group '{group_id}': {error}. "
                    f"Cancelling all siblings."
                )
                self._cancel_siblings(group_id, task_id)
            else:
                logger.info(
                    f"[ConcurrentIsolation] Non-critical failure on task "
                    f"'{task_id}' in group '{group_id}': {error}. "
                    f"Siblings unaffected."
                )

    def _cancel_siblings(self, group_id: str, failed_task_id: str) -> None:
        """
        Cancel all sibling tasks except the one that failed.

        Must be called with self._lock held.

        Args:
            group_id: The sibling group identifier.
            failed_task_id: The task that caused the cancellation.
        """
        group = self._groups.get(group_id)
        if group is None:
            return

        cancelled_count = 0
        for task_id, status in group.status.items():
            if task_id == failed_task_id:
                continue
            if status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                group.status[task_id] = TaskStatus.CANCELLED
                self._cancelled_tasks.add(task_id)
                cancelled_count += 1

        logger.info(
            f"[ConcurrentIsolation] Cancelled {cancelled_count} siblings "
            f"in group '{group_id}'"
        )

    def check_cancelled(self, task_id: str) -> bool:
        """
        Check if a task has been cancelled.

        Workers should call this before starting or continuing work on
        a task. If True, the worker should abort and return a cancelled result.

        Args:
            task_id: The ID of the task to check.

        Returns:
            True if the task has been cancelled.
        """
        with self._lock:
            return task_id in self._cancelled_tasks

    def get_group_status(self, group_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the full status of a sibling group.

        Args:
            group_id: The group identifier.

        Returns:
            Dict with group status details, or None if group not found.
        """
        with self._lock:
            group = self._groups.get(group_id)
            if group is None:
                return None
            return group.to_dict()

    def is_group_finished(self, group_id: str) -> bool:
        """
        Check if all tasks in a group have reached a terminal state.

        Terminal states: COMPLETED, FAILED, CANCELLED.

        Args:
            group_id: The group identifier.

        Returns:
            True if no PENDING or RUNNING tasks remain.
        """
        with self._lock:
            group = self._groups.get(group_id)
            if group is None:
                return True

            for status in group.status.values():
                if status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    return False
            return True

    def cleanup_group(self, group_id: str) -> None:
        """
        Remove a sibling group and its task IDs from tracking.

        Should be called after all tasks in the group have reached
        terminal states.

        Args:
            group_id: The group identifier to clean up.
        """
        with self._lock:
            group = self._groups.pop(group_id, None)
            if group is None:
                logger.warning(
                    f"[ConcurrentIsolation] Cannot cleanup unknown group "
                    f"'{group_id}'"
                )
                return

            # Remove task IDs from cancelled set
            for task_id in group.task_ids:
                self._cancelled_tasks.discard(task_id)

            logger.info(
                f"[ConcurrentIsolation] Cleaned up group '{group_id}' "
                f"({len(group.task_ids)} tasks)"
            )

    def get_stats(self) -> Dict[str, Any]:
        """
        Get controller statistics.

        Returns:
            Dict with active groups, total cancelled tasks, etc.
        """
        with self._lock:
            return {
                "active_groups": len(self._groups),
                "total_cancelled_tasks": len(self._cancelled_tasks),
                "groups": {
                    gid: g.to_dict()
                    for gid, g in self._groups.items()
                },
            }


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _is_critical_error(error: str) -> bool:
    """
    Determine if an error string indicates a critical failure.

    Critical errors warrant cancelling all sibling tasks.

    Args:
        error: The error message to evaluate.

    Returns:
        True if the error matches a critical pattern.
    """
    error_lower = error.lower()
    return any(pattern in error_lower for pattern in CRITICAL_ERROR_PATTERNS)


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_isolation_controller() -> ConcurrentIsolationController:
    """
    Create a ConcurrentIsolationController with default settings.

    Returns:
        New ConcurrentIsolationController instance.
    """
    return ConcurrentIsolationController()


__all__ = [
    "TaskStatus",
    "SiblingGroup",
    "ConcurrentIsolationController",
    "CRITICAL_ERROR_PATTERNS",
    "create_isolation_controller",
]
