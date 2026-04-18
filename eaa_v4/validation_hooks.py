"""
EAA V4 - Validation Hooks (Phase 6, Component 2)
=================================================
Post-edit syntax validation + Transient UI Spinner for self-correction.

From the blueprint (Section 3.2):
  After a worker edits a file, validation hooks run automatically to check
  syntax, import integrity, and other post-edit invariants. If a hook fails,
  the error is fed back to the worker for self-correction.

From Amendment 1 (Section 3.2.5):
  Transient UI Spinner — a non-blocking stderr spinner thread that shows
  progress during self-correction attempts, providing visual feedback
  without blocking the main execution loop.

The ValidationHookRegistry allows registering per-tool hooks that run
after tool execution. Hooks return a ValidationFailure on error, which
gets wrapped as is_error: true and fed back to the worker.

Usage:
    registry = ValidationHookRegistry()
    registry.register("write_file", PythonSyntaxHook())

    failure = registry.run_hooks("write_file", "/tmp/test.py", result)
    if failure:
        # Feed back to worker for self-correction
        spinner = HealingSpinner("coder", max_attempts=3)
        spinner.start(attempt=1)
        # ... retry logic ...
        spinner.stop(success=True)
"""

import subprocess
import sys
import threading
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, List, Any, Callable

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION TYPES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ValidationFailure:
    """
    Represents a failed validation check on a tool result.

    Attributes:
        tool_name: Name of the tool that produced the result.
        file_path: Path of the file that failed validation.
        stderr: The error output from the validation check.
    """
    tool_name: str
    file_path: str
    stderr: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "tool_name": self.tool_name,
            "file_path": self.file_path,
            "stderr": self.stderr[:500] + "..." if len(self.stderr) > 500 else self.stderr,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION HOOK INTERFACE
# ═══════════════════════════════════════════════════════════════════════════════

class ValidationHook(ABC):
    """
    Abstract base class for post-edit validation hooks.

    Subclasses implement the validate() method to perform specific checks
    (syntax, imports, linting, etc.) on tool execution results.

    A hook returns None on success, or a ValidationFailure on error.
    """

    @abstractmethod
    def validate(
        self,
        tool_name: str,
        file_path: str,
        result: Any,
    ) -> Optional[ValidationFailure]:
        """
        Validate a tool execution result.

        Args:
            tool_name: Name of the tool that was executed.
            file_path: Path of the file affected by the tool.
            result: The tool execution result (any type).

        Returns:
            ValidationFailure if validation failed, None if passed.
        """
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# BUILT-IN HOOKS
# ═══════════════════════════════════════════════════════════════════════════════

class PythonSyntaxHook(ValidationHook):
    """
    Validates Python syntax by running py_compile on the target file.

    This is the primary post-edit validation hook. After any worker writes
    or edits a .py file, this hook checks that the resulting file is
    syntactically valid Python.

    Uses subprocess to run ``python -m py_compile`` with a 10-second timeout.
    """

    def __init__(self, timeout: int = 10):
        """
        Args:
            timeout: Maximum seconds to wait for py_compile to complete.
        """
        self.timeout = timeout

    def validate(
        self,
        tool_name: str,
        file_path: str,
        result: Any,
    ) -> Optional[ValidationFailure]:
        """
        Check if a Python file has valid syntax.

        Non-Python files are silently skipped (returns None).

        Args:
            tool_name: Name of the tool (e.g., "write_file", "edit_file").
            file_path: Path to the file to validate.
            result: The tool execution result (unused for syntax check).

        Returns:
            ValidationFailure if py_compile fails, None if valid or not Python.
        """
        if not file_path.endswith(".py"):
            return None

        try:
            proc = subprocess.run(
                ["python", "-m", "py_compile", file_path],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if proc.returncode != 0:
                logger.warning(
                    f"[PythonSyntaxHook] Syntax error in {file_path}: "
                    f"{proc.stderr.strip()[:200]}"
                )
                return ValidationFailure(
                    tool_name=tool_name,
                    file_path=file_path,
                    stderr=proc.stderr.strip(),
                )
            return None
        except subprocess.TimeoutExpired:
            logger.error(
                f"[PythonSyntaxHook] py_compile timed out for {file_path} "
                f"(timeout={self.timeout}s)"
            )
            return ValidationFailure(
                tool_name=tool_name,
                file_path=file_path,
                stderr=f"py_compile timed out after {self.timeout} seconds",
            )
        except Exception as e:
            logger.error(
                f"[PythonSyntaxHook] Unexpected error validating {file_path}: {e}"
            )
            return ValidationFailure(
                tool_name=tool_name,
                file_path=file_path,
                stderr=f"Validation error: {e}",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION HOOK REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

class ValidationHookRegistry:
    """
    Registry for per-tool validation hooks.

    Allows registering validation hooks that run after specific tool
    executions. Multiple hooks can be registered for the same tool;
    they run in registration order and short-circuit on first failure.

    Usage:
        registry = ValidationHookRegistry()
        registry.register("write_file", PythonSyntaxHook())
        registry.register("edit_file", PythonSyntaxHook())

        failure = registry.run_hooks("write_file", "/tmp/main.py", result)
        if failure:
            print(f"Validation failed: {failure.stderr}")
    """

    def __init__(self):
        self._hooks: Dict[str, List[ValidationHook]] = {}

    def register(self, tool_name: str, hook: ValidationHook) -> None:
        """
        Register a validation hook for a specific tool.

        Args:
            tool_name: Name of the tool to validate after.
            hook: ValidationHook instance to register.
        """
        if tool_name not in self._hooks:
            self._hooks[tool_name] = []
        self._hooks[tool_name].append(hook)
        logger.debug(
            f"[ValidationHookRegistry] Registered hook "
            f"{hook.__class__.__name__} for tool '{tool_name}'"
        )

    def unregister(self, tool_name: str, hook_class: type = None) -> int:
        """
        Remove hooks for a tool.

        Args:
            tool_name: Tool name to remove hooks for.
            hook_class: If specified, only remove hooks of this class.
                        If None, remove all hooks for the tool.

        Returns:
            Number of hooks removed.
        """
        if tool_name not in self._hooks:
            return 0

        if hook_class is None:
            count = len(self._hooks[tool_name])
            del self._hooks[tool_name]
            return count

        original = len(self._hooks[tool_name])
        self._hooks[tool_name] = [
            h for h in self._hooks[tool_name]
            if not isinstance(h, hook_class)
        ]
        return original - len(self._hooks[tool_name])

    def run_hooks(
        self,
        tool_name: str,
        file_path: str,
        result: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Run all registered hooks for a tool.

        Hooks run in registration order. If any hook returns a
        ValidationFailure, subsequent hooks are skipped and the
        failure is wrapped as an is_error: true tool result.

        Args:
            tool_name: Name of the tool that was executed.
            file_path: Path of the file affected by the tool.
            result: The tool execution result.

        Returns:
            None if all hooks passed, or a dict with is_error: true
            and the failure details if any hook failed.
        """
        hooks = self._hooks.get(tool_name, [])
        if not hooks:
            return None

        for hook in hooks:
            try:
                failure = hook.validate(tool_name, file_path, result)
                if failure is not None:
                    logger.warning(
                        f"[ValidationHookRegistry] Hook "
                        f"{hook.__class__.__name__} failed for "
                        f"'{tool_name}' on {file_path}: "
                        f"{failure.stderr[:200]}"
                    )
                    return self._wrap_as_error(failure)
            except Exception as e:
                logger.error(
                    f"[ValidationHookRegistry] Hook "
                    f"{hook.__class__.__name__} raised exception: {e}"
                )
                return self._wrap_as_error(
                    ValidationFailure(
                        tool_name=tool_name,
                        file_path=file_path,
                        stderr=f"Hook {hook.__class__.__name__} crashed: {e}",
                    )
                )

        logger.debug(
            f"[ValidationHookRegistry] All {len(hooks)} hooks passed "
            f"for '{tool_name}' on {file_path}"
        )
        return None

    def _wrap_as_error(self, failure: ValidationFailure) -> Dict[str, Any]:
        """
        Wrap a ValidationFailure as a Claude Code is_error: true result.

        Args:
            failure: The validation failure to wrap.

        Returns:
            Dict with role="tool", is_error=True, and formatted content.
        """
        return {
            "role": "tool",
            "content": (
                f"[is_error: true] {failure.tool_name}: "
                f"Validation failed for {failure.file_path}\n"
                f"{failure.stderr}"
            ),
            "is_error": True,
            "validation_failure": failure.to_dict(),
        }

    def get_registered_hooks(self, tool_name: str) -> List[str]:
        """
        Get the names of hooks registered for a tool.

        Args:
            tool_name: Tool name to query.

        Returns:
            List of hook class names.
        """
        return [
            h.__class__.__name__
            for h in self._hooks.get(tool_name, [])
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# TRANSIENT UI SPINNER [Amendment 1, Section 3.2.5]
# ═══════════════════════════════════════════════════════════════════════════════

class HealingSpinner:
    """
    Non-blocking spinner thread for stderr during self-correction.

    [Amendment 1, Section 3.2.5]:
      During self-correction attempts (e.g., syntax error → retry), a
      transient spinner provides visual feedback on stderr without
      blocking the main execution loop.

    The spinner uses Braille characters for a smooth animation effect,
    writing to stderr with ``\\r`` overwrite for in-place updates.

    Usage:
        spinner = HealingSpinner(worker_name="coder", max_attempts=3)
        spinner.start(attempt=1)
        # ... perform self-correction ...
        spinner.stop(success=True)
        # Output: [OK] Syntax error fixed by coder (Attempt 1/3)
    """

    BRAILLE_CHARS = [
        '\u2839', '\u2838', '\u2807', '\u280f',
        '\u281f', '\u283f', '\u282f', '\u2837',
    ]

    def __init__(self, worker_name: str, max_attempts: int = 3):
        """
        Args:
            worker_name: Name of the worker performing self-correction.
            max_attempts: Maximum correction attempts for display.
        """
        self.worker_name = worker_name
        self.max_attempts = max_attempts
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._current_attempt = 0

    def start(self, attempt: int) -> None:
        """
        Start the spinner for a given attempt number.

        Creates a daemon thread that writes Braille spinner frames to
        stderr. The thread auto-terminates when stop() is called.

        Args:
            attempt: Current attempt number (1-based).
        """
        self._current_attempt = attempt
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        logger.debug(
            f"[HealingSpinner] Started for {self.worker_name}, "
            f"attempt {attempt}/{self.max_attempts}"
        )

    def _spin(self) -> None:
        """
        Spin loop — writes Braille character frames to stderr with \\r overwrite.

        Runs at approximately 10 FPS (100ms per frame). Uses \\r to
        overwrite the current line, creating a smooth in-place animation.
        Stops when _stop_event is set by stop().
        """
        idx = 0
        while not self._stop_event.is_set():
            char = self.BRAILLE_CHARS[idx % len(self.BRAILLE_CHARS)]
            msg = (
                f"\r[ {char} ] Syntax error detected. "
                f"{self.worker_name} is self-correcting "
                f"(Attempt {self._current_attempt}/{self.max_attempts})..."
            )
            sys.stderr.write(msg)
            sys.stderr.flush()
            self._stop_event.wait(0.1)
            idx += 1
        # Clear the line on stop
        sys.stderr.write('\r' + ' ' * 100 + '\r')
        sys.stderr.flush()

    def stop(self, success: bool = False) -> None:
        """
        Stop the spinner and print a summary line.

        Args:
            success: If True, prints a success message.
                     If False, prints a failure/escalation message.
        """
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1)

        if success:
            msg = (
                f"[OK] Syntax error fixed by {self.worker_name} "
                f"(Attempt {self._current_attempt}/{self.max_attempts})\n"
            )
        else:
            msg = (
                f"[FAIL] Self-correction failed after "
                f"{self.max_attempts} attempts. "
                f"Escalating to Master.\n"
            )

        sys.stderr.write(msg)
        sys.stderr.flush()

        logger.debug(
            f"[HealingSpinner] Stopped for {self.worker_name}, "
            f"success={success}"
        )

    @property
    def is_spinning(self) -> bool:
        """
        Check if the spinner is currently active.

        Returns:
            True if the spinner thread is running.
        """
        return (
            self._thread is not None
            and self._thread.is_alive()
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_validation_registry(
    hooks: Optional[Dict[str, List[ValidationHook]]] = None,
) -> ValidationHookRegistry:
    """
    Create a ValidationHookRegistry with optional pre-registered hooks.

    Args:
        hooks: Dict mapping tool names to lists of ValidationHook instances.

    Returns:
        Configured ValidationHookRegistry instance.
    """
    registry = ValidationHookRegistry()
    if hooks:
        for tool_name, hook_list in hooks.items():
            for hook in hook_list:
                registry.register(tool_name, hook)
    return registry


__all__ = [
    "ValidationFailure",
    "ValidationHook",
    "PythonSyntaxHook",
    "ValidationHookRegistry",
    "HealingSpinner",
    "create_validation_registry",
]
