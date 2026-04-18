"""
vram_lifecycle.py — VRAM Lifecycle Manager (Phase 5)

Implements graceful model hot-swapping with a strict one-model-at-a-time
policy to prevent OOM crashes on VRAM-constrained GPUs.

Key features:
    - Context manager API: with vram_swap('worker'): ...
    - VRAM usage monitoring (via callback)
    - Watchdog timer for hung swaps
    - CPU fallback when GPU VRAM is insufficient
    - Swap planning and validation

Architecture:
    1. Save current model state
    2. Unload current model from VRAM
    3. Load target model into VRAM
    4. Execute task
    5. Capture result
    6. Unload target model
    7. Reload original model
    8. Restore state with result appended

Reference: Blueprint Section 13 — VRAM Lifecycle Management
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from model_registry import ModelInfo, ModelRegistry


class SwapPhase(Enum):
    """Phases of a model hot-swap."""
    IDLE = "idle"
    SAVING_STATE = "saving_state"
    UNLOADING = "unloading"
    LOADING = "loading"
    EXECUTING = "executing"
    CAPTURING_RESULT = "capturing_result"
    UNLOADING_TARGET = "unloading_target"
    RELOADING = "reloading"
    RESTORING_STATE = "restoring_state"


class SwapError(Exception):
    """Error during model swap."""
    pass


class WatchdogTimeoutError(SwapError):
    """Swap exceeded watchdog timeout."""
    pass


class InsufficientVRAMError(SwapError):
    """Not enough VRAM for the target model."""
    pass


@dataclass
class SwapRecord:
    """Record of a completed swap operation."""
    source_model: str
    target_model: str
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    success: bool = False
    error: str = ""
    peak_vram_gb: float = 0.0

    def __post_init__(self):
        if self.end_time > 0:
            self.duration_ms = (self.end_time - self.start_time) * 1000


# Default watchdog timeout (seconds)
DEFAULT_WATCHDOG_TIMEOUT = 30.0

# VRAM safety margin (GB) — never use 100% of VRAM
VRAM_SAFETY_MARGIN_GB = 0.5


@dataclass
class VRAMMetrics:
    """Real-time VRAM metrics snapshot."""
    total_gb: float = 0.0
    used_gb: float = 0.0
    free_gb: float = 0.0
    timestamp: float = 0.0


@dataclass
class SwapStats:
    """Aggregate swap statistics."""
    total_swaps: int = 0
    successful_swaps: int = 0
    failed_swaps: int = 0
    total_swap_time_ms: float = 0.0
    cpu_fallback_count: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_swaps == 0:
            return 0.0
        return self.successful_swaps / self.total_swaps


class VRAMLifecycleManager:
    """
    Manages VRAM lifecycle for model hot-swapping.

    Implements a strict one-model-at-a-time policy to prevent OOM
    crashes when switching between Master and Worker models.

    Usage:
        manager = VRAMLifecycleManager(registry)

        # Context manager API
        with manager.swap("coder_worker") as ctx:
            result = execute_worker(ctx, task)

        # Manual API
        manager.begin_swap("coder_worker")
        try:
            result = execute_task()
            manager.commit_swap(result)
        except:
            manager.rollback_swap()
    """

    def __init__(
        self,
        registry: ModelRegistry,
        watchdog_timeout: float = DEFAULT_WATCHDOG_TIMEOUT,
        vram_monitor: Optional[Callable[[], VRAMMetrics]] = None,
        cpu_fallback: Optional[Callable[[str, Any], Any]] = None,
    ):
        self.registry = registry
        self.watchdog_timeout = watchdog_timeout

        # External callbacks
        self._vram_monitor = vram_monitor or self._default_vram_monitor
        self._cpu_fallback = cpu_fallback

        # Model load/unload callbacks (set by the runtime)
        self._load_callback: Optional[Callable[[str], None]] = None
        self._unload_callback: Optional[Callable[[str], None]] = None
        self._save_state_callback: Optional[Callable[[], Any]] = None
        self._restore_state_callback: Optional[Callable[[Any, Any], None]] = None

        # Swap state
        self._current_phase = SwapPhase.IDLE
        self._swap_lock = threading.RLock()
        self._is_swapping = False
        self._active_model: Optional[str] = None

        # Watchdog
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_cancel = threading.Event()

        # Statistics
        self._stats = SwapStats()
        self._history: List[SwapRecord] = []

    def set_load_callback(self, callback: Callable[[str], None]) -> None:
        """Set the model loading callback."""
        self._load_callback = callback

    def set_unload_callback(self, callback: Callable[[str], None]) -> None:
        """Set the model unloading callback."""
        self._unload_callback = callback

    def set_state_callbacks(
        self,
        save: Optional[Callable[[], Any]] = None,
        restore: Optional[Callable[[Any, Any], None]] = None,
    ) -> None:
        """Set state save/restore callbacks."""
        if save:
            self._save_state_callback = save
        if restore:
            self._restore_state_callback = restore

    @staticmethod
    def _default_vram_monitor() -> VRAMMetrics:
        """Default VRAM monitor — returns registry-based estimates."""
        return VRAMMetrics(
            total_gb=8.0,
            used_gb=0.0,
            free_gb=8.0,
            timestamp=time.time()
        )

    def get_vram_metrics(self) -> VRAMMetrics:
        """Get current VRAM metrics."""
        return self._vram_monitor()

    def get_swap_plan(self, target_name: str) -> Dict[str, Any]:
        """
        Validate and plan a swap to the target model.

        Returns:
            Plan dict with 'unload', 'load', 'fits', and metadata.
        """
        plan = self.registry.get_swap_plan(target_name)
        metrics = self.get_vram_metrics()
        plan["current_vram_total"] = metrics.total_gb
        plan["current_vram_free"] = metrics.free_gb
        return plan

    def _set_phase(self, phase: SwapPhase) -> None:
        """Set current swap phase."""
        self._current_phase = phase

    def _start_watchdog(self) -> None:
        """Start the watchdog timer thread."""
        self._watchdog_cancel.clear()

        def watchdog():
            if self._watchdog_cancel.wait(self.watchdog_timeout):
                return  # Cancelled normally
            # Timeout!
            if self._is_swapping:
                self._current_phase = SwapPhase.IDLE
                self._is_swapping = False

        self._watchdog_thread = threading.Thread(target=watchdog, daemon=True)
        self._watchdog_thread.start()

    def _stop_watchdog(self) -> None:
        """Stop the watchdog timer."""
        self._watchdog_cancel.set()
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=1.0)

    def begin_swap(self, target_model: str) -> SwapContext:
        """
        Begin a model swap to the target model.

        Steps:
            1. Validate target model
            2. Check VRAM availability
            3. Save current state
            4. Unload current model
            5. Load target model

        Returns:
            SwapContext for executing the task.

        Raises:
            InsufficientVRAMError: Target doesn't fit in VRAM.
            SwapError: Other swap failures.
        """
        with self._swap_lock:
            if self._is_swapping:
                raise SwapError("Swap already in progress")

            self._stats.total_swaps += 1
            start_time = time.time()
            source_model = self._active_model or "none"

            # Step 1: Validate
            target_info = self.registry.get(target_model)
            if target_info is None:
                self._stats.failed_swaps += 1
                raise SwapError(f"Unknown model: {target_model}")

            # Step 2: Check VRAM
            plan = self.registry.get_swap_plan(target_model)
            if not plan["fits"]:
                self._stats.failed_swaps += 1
                raise InsufficientVRAMError(
                    f"Cannot fit '{target_model}' ({target_info.vram_footprint_gb:.1f}GB) "
                    f"in {self.registry.get_available_vram():.1f}GB available VRAM"
                )

            # Start watchdog
            self._is_swapping = True
            self._start_watchdog()

            try:
                # Step 3: Save current state
                self._set_phase(SwapPhase.SAVING_STATE)
                saved_state = None
                if self._save_state_callback and self._active_model:
                    saved_state = self._save_state_callback()

                # Step 4: Unload current model
                self._set_phase(SwapPhase.UNLOADING)
                if self._active_model:
                    if self._unload_callback:
                        self._unload_callback(self._active_model)
                    self.registry.mark_unloaded(self._active_model)

                # Step 5: Load target model
                self._set_phase(SwapPhase.LOADING)
                if self._load_callback:
                    self._load_callback(target_model)
                self.registry.mark_loaded(target_model)
                self._active_model = target_model

                return SwapContext(
                    manager=self,
                    target_model=target_model,
                    source_model=source_model,
                    saved_state=saved_state,
                    start_time=start_time,
                )

            except Exception as e:
                self._is_swapping = False
                self._stop_watchdog()
                self._current_phase = SwapPhase.IDLE
                self._stats.failed_swaps += 1
                raise

    def commit_swap(self, context: SwapContext, result: Any = None) -> SwapRecord:
        """
        Complete a swap by unloading the target and restoring the source.

        Args:
            context: The SwapContext from begin_swap().
            result: Optional result to append to restored state.

        Returns:
            SwapRecord with timing and status info.
        """
        with self._swap_lock:
            self._set_phase(SwapPhase.CAPTURING_RESULT)
            peak_vram = self.get_vram_metrics().used_gb

            # Step 6: Unload target
            self._set_phase(SwapPhase.UNLOADING_TARGET)
            if self._unload_callback and context.target_model:
                self._unload_callback(context.target_model)
            self.registry.mark_unloaded(context.target_model)

            # Step 7: Reload source
            if context.source_model and context.source_model != "none":
                self._set_phase(SwapPhase.RELOADING)
                source_info = self.registry.get(context.source_model)
                if source_info and self._load_callback:
                    self._load_callback(context.source_model)
                    self.registry.mark_loaded(context.source_model)
                    self._active_model = context.source_model

            # Step 8: Restore state
            self._set_phase(SwapPhase.RESTORING_STATE)
            if self._restore_state_callback and context.saved_state is not None:
                self._restore_state_callback(context.saved_state, result)

            # Record
            end_time = time.time()
            self._stop_watchdog()
            self._is_swapping = False
            self._current_phase = SwapPhase.IDLE

            record = SwapRecord(
                source_model=context.source_model,
                target_model=context.target_model,
                start_time=context.start_time,
                end_time=end_time,
                success=True,
                peak_vram_gb=peak_vram,
            )

            self._stats.successful_swaps += 1
            self._history.append(record)
            return record

    def rollback_swap(self, context: SwapContext) -> None:
        """Rollback a failed swap — restore source model."""
        with self._swap_lock:
            self._set_phase(SwapPhase.UNLOADING_TARGET)
            if self._unload_callback and context.target_model:
                self._unload_callback(context.target_model)
            self.registry.mark_unloaded(context.target_model)

            if context.source_model and context.source_model != "none":
                self._set_phase(SwapPhase.RELOADING)
                if self._load_callback:
                    self._load_callback(context.source_model)
                self.registry.mark_loaded(context.source_model)
                self._active_model = context.source_model

            self._set_phase(SwapPhase.RESTORING_STATE)
            if self._restore_state_callback and context.saved_state is not None:
                self._restore_state_callback(context.saved_state, None)

            self._stop_watchdog()
            self._is_swapping = False
            self._current_phase = SwapPhase.IDLE

            end_time = time.time()
            record = SwapRecord(
                source_model=context.source_model,
                target_model=context.target_model,
                start_time=context.start_time,
                end_time=end_time,
                success=False,
                error="rolled_back",
            )
            self._history.append(record)

    @contextmanager
    def swap(self, target_model: str):
        """
        Context manager for model hot-swap.

        Usage:
            with manager.swap("coder") as ctx:
                result = do_work()
            # Original model is automatically restored

        If the body raises an exception, the swap is rolled back.
        """
        ctx = self.begin_swap(target_model)
        try:
            self._set_phase(SwapPhase.EXECUTING)
            yield ctx
            self.commit_swap(ctx)
        except Exception:
            self.rollback_swap(ctx)
            raise

    def execute_with_cpu_fallback(self, model_name: str, task: Any) -> Any:
        """
        Execute a task using CPU fallback when GPU VRAM is insufficient.

        Args:
            model_name: The model to use.
            task: The task data to process.

        Returns:
            Task result.
        """
        self._stats.cpu_fallback_count += 1
        if self._cpu_fallback:
            return self._cpu_fallback(model_name, task)
        raise SwapError("CPU fallback not configured")

    @property
    def current_phase(self) -> SwapPhase:
        return self._current_phase

    @property
    def is_swapping(self) -> bool:
        return self._is_swapping

    @property
    def active_model(self) -> Optional[str]:
        return self._active_model

    @property
    def stats(self) -> SwapStats:
        return self._stats

    @property
    def history(self) -> List[SwapRecord]:
        return list(self._history)


@dataclass
class SwapContext:
    """Context for an in-progress model swap."""
    manager: VRAMLifecycleManager
    target_model: str
    source_model: str
    saved_state: Any = None
    start_time: float = 0.0
