"""
EAA Scheduler Tools - Phase 10
Task scheduling with persistent storage.
All tools use the existing ToolResult pattern from eaa_agent_tools.py.
"""

import os
import json
import time
import threading
import traceback
from typing import Optional, Dict, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime

try:
    from eaa_agent_tools import ToolResult
except ImportError:
    @dataclass
    class ToolResult:
        success: bool
        output: str
        error: Optional[str] = None
        def to_dict(self):
            return {"success": self.success, "output": self.output, "error": self.error}

# Scheduler storage
SCHEDULE_DIR = os.path.join(os.path.dirname(__file__), "..", "EAA_Data", "scheduler")
SCHEDULE_FILE = os.path.join(SCHEDULE_DIR, "tasks.json")

# In-memory task store
_tasks: Dict[str, Dict] = {}
_scheduler_thread = None
_running = False


def _ensure_dirs():
    os.makedirs(SCHEDULE_DIR, exist_ok=True)


def _load_tasks() -> Dict[str, Dict]:
    global _tasks
    _ensure_dirs()
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                _tasks = json.load(f)
        except Exception:
            _tasks = {}
    return _tasks


def _save_tasks():
    _ensure_dirs()
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(_tasks, f, indent=2, ensure_ascii=False)


def _next_id() -> str:
    return f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 10000}"


# ─── SCHEDULE TASK ────────────────────────────────────────────────────────────
def tool_schedule_task(
    name: str,
    run_at: str,
    command: str,
    description: str = "",
    repeat: str = "once"
) -> ToolResult:
    """
    Schedule a task for later execution.
    name: Task name/label
    run_at: When to run - ISO format datetime ('2026-04-04T15:30:00') or relative ('in 30m', 'in 2h', 'at 15:30')
    command: Shell command or Python code to execute
    description: Task description
    repeat: 'once' (default), 'hourly', 'daily'
    """
    try:
        _load_tasks()

        # Parse run_at
        run_time = _parse_time(run_at)
        if run_time is None:
            return ToolResult(False, "", f"Invalid time format: {run_at}\nUse ISO format (2026-04-04T15:30:00) or relative (in 30m, in 2h, at 15:30)")

        task = {
            "id": _next_id(),
            "name": name,
            "run_at": run_time.isoformat(),
            "command": command,
            "description": description,
            "repeat": repeat,
            "status": "scheduled",
            "created_at": datetime.now().isoformat(),
            "result": None,
            "error": None,
        }

        _tasks[task["id"]] = task
        _save_tasks()

        return ToolResult(True, f"Scheduled task: {name}\nID: {task['id']}\nRun at: {run_time.strftime('%Y-%m-%d %H:%M:%S')}\nRepeat: {repeat}\nCommand: {command[:100]}")

    except Exception as e:
        return ToolResult(False, "", f"Schedule task failed: {str(e)}")


# ─── SCHEDULE LIST ────────────────────────────────────────────────────────────
def tool_schedule_list(status_filter: str = None) -> ToolResult:
    """List scheduled tasks."""
    try:
        _load_tasks()
        tasks = list(_tasks.values())

        if status_filter:
            tasks = [t for t in tasks if t.get("status") == status_filter]

        if not tasks:
            return ToolResult(True, f"No scheduled tasks" + (f" with status '{status_filter}'" if status_filter else ""))

        lines = [f"Scheduled Tasks ({len(tasks)}):\n"]
        lines.append(f"{'ID':<35} {'Name':<20} {'Status':<12} {'Run At':<20}")
        lines.append("-" * 95)

        for t in tasks:
            tid = t.get("id", "?")[:34]
            name = t.get("name", "?")[:19]
            status = t.get("status", "?")
            run_at = t.get("run_at", "?")[:19]
            lines.append(f"{tid:<35} {name:<20} {status:<12} {run_at:<20}")

        return ToolResult(True, "\n".join(lines))

    except Exception as e:
        return ToolResult(False, "", f"Schedule list failed: {str(e)}")


# ─── SCHEDULE CANCEL ──────────────────────────────────────────────────────────
def tool_schedule_cancel(task_id: str = None, name: str = None) -> ToolResult:
    """Cancel a scheduled task by ID or name."""
    try:
        _load_tasks()

        if task_id:
            if task_id in _tasks:
                _tasks[task_id]["status"] = "cancelled"
                _save_tasks()
                return ToolResult(True, f"Cancelled task: {_tasks[task_id]['name']} ({task_id})")
            return ToolResult(False, "", f"Task not found: {task_id}")

        if name:
            cancelled = []
            for tid, task in _tasks.items():
                if task.get("name") == name and task.get("status") == "scheduled":
                    task["status"] = "cancelled"
                    cancelled.append(tid)
            if cancelled:
                _save_tasks()
                return ToolResult(True, f"Cancelled {len(cancelled)} tasks matching '{name}'")
            return ToolResult(False, "", f"No scheduled tasks found with name: {name}")

        return ToolResult(False, "", "Specify task_id or name")

    except Exception as e:
        return ToolResult(False, "", f"Schedule cancel failed: {str(e)}")


# ─── SCHEDULE INFO ────────────────────────────────────────────────────────────
def tool_schedule_info(task_id: str) -> ToolResult:
    """Get detailed info about a scheduled task."""
    try:
        _load_tasks()

        if task_id not in _tasks:
            return ToolResult(False, "", f"Task not found: {task_id}")

        return ToolResult(True, json.dumps(_tasks[task_id], indent=2))

    except Exception as e:
        return ToolResult(False, "", f"Schedule info failed: {str(e)}")


# ─── TIME HELPER ──────────────────────────────────────────────────────────────
def _parse_time(time_str: str) -> Optional[datetime]:
    """Parse various time formats into datetime."""
    now = datetime.now()

    # ISO format
    try:
        return datetime.fromisoformat(time_str)
    except (ValueError, TypeError):
        pass

    # Relative: "in 30m", "in 2h", "in 1d"
    match = __import__("re").match(r"in\s+(\d+)\s*(m|h|d|s)", time_str.lower().strip())
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit == "s":
            return now.replace(second=now.second + amount)
        elif unit == "m":
            return now.replace(minute=now.minute + amount)
        elif unit == "h":
            return now.replace(hour=now.hour + amount)
        elif unit == "d":
            return now.replace(day=now.day + amount)

    # "at HH:MM"
    match = __import__("re").match(r"at\s+(\d{1,2}):(\d{2})", time_str.lower().strip())
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

def register_scheduler_tools(registry) -> None:
    """Register all scheduler tools with the existing ToolRegistry."""
    registry.register("schedule_task", tool_schedule_task, "Schedule a task. Args: name, run_at, command, repeat (once/hourly/daily)")
    registry.register("schedule_list", tool_schedule_list, "List scheduled tasks. Args: status_filter (optional)")
    registry.register("schedule_cancel", tool_schedule_cancel, "Cancel task. Args: task_id or name")
    registry.register("schedule_info", tool_schedule_info, "Get task details. Args: task_id")

__all__ = [
    "register_scheduler_tools",
    "tool_schedule_task", "tool_schedule_list", "tool_schedule_cancel", "tool_schedule_info",
]
