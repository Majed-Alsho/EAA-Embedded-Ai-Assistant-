"""
EAA V4 - Plan Formatter
========================
Formats delegation plans for human-readable display.

Transforms the internal DelegationTask list into structured output
suitable for terminal display (Rich tables), logging, and modification.
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from router import DelegationTask


# ═══════════════════════════════════════════════════════════════════════════════
# PLAN DISPLAY DATA
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PlanRow:
    """
    A single row in the delegation plan table.
    This is the human-readable representation of a DelegationTask.
    """
    index: int
    worker_id: str
    tool_name: str
    action_summary: str     # Human-readable description of what will happen
    full_args: Dict[str, Any]
    reason: str
    risk_level: str = "low" # low, medium, high, critical
    is_approved: Optional[bool] = None

    def to_dict(self) -> Dict:
        return {
            "index": self.index,
            "worker_id": self.worker_id,
            "tool_name": self.tool_name,
            "action_summary": self.action_summary,
            "full_args": self.full_args,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "is_approved": self.is_approved,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# RISK ASSESSMENT
# ═══════════════════════════════════════════════════════════════════════════════

# Tools that modify or destroy data — higher risk
DESTRUCTIVE_TOOLS = {
    "write_file", "delete_file", "shell", "git_commit", "git_push",
    "email_send", "env_set", "schedule_task", "code_run",
    "pdf_create", "docx_create", "xlsx_create", "pptx_create",
    "browser_click", "browser_type",
}

# Tools that only read — low risk
READ_ONLY_TOOLS = {
    "read_file", "list_files", "file_exists", "glob", "grep",
    "web_search", "web_fetch", "system_info", "process_list",
    "datetime", "calculator", "git_status", "git_diff", "git_log",
    "pdf_read", "pdf_info", "docx_read", "xlsx_read",
    "browser_screenshot", "browser_get_text",
    "memory_recall", "memory_list", "memory_search",
    "json_parse", "csv_read", "hash_text", "hash_file",
}

# Tools with specific dangerous args patterns
DANGEROUS_ARG_PATTERNS = {
    "shell": [r"rm\s", r"sudo\s", r"chmod\s", r"del\s", r"format\s", r"mkfs"],
    "write_file": [r"\.py$", r"\.sh$", r"\.bat$", r"\.ps1$"],
    "code_run": [r"subprocess", r"os\.system", r"eval\s", r"exec\s"],
}


def assess_risk(task: DelegationTask) -> str:
    """
    Assess the risk level of a delegation task.

    Returns one of: "low", "medium", "high", "critical"

    Risk levels:
    - low: Read-only operation, no side effects
    - medium: Write operation but scoped to project files
    - high: System-level operation (shell, env vars, process management)
    - critical: Potentially destructive (rm, sudo, format, mass delete)
    """
    import re

    tool = task.tool_name
    args = json.dumps(task.tool_args, default=str).lower()

    # Check for critical patterns first
    critical_patterns = [
        r"rm\s+(-\w*\s+)?/",       # rm /
        r"sudo\s",                   # sudo
        r"format\s",                 # format
        r"mkfs",                     # mkfs
        r"dd\s+if=",                 # dd
        r"shutdown",                 # shutdown
        r"reboot",                   # reboot
        r":(){ :\|:& };:",          # fork bomb
        r">/dev/",                   # write to device
    ]
    for pattern in critical_patterns:
        if re.search(pattern, args):
            return "critical"

    # Check tool-specific dangerous args
    if tool in DANGEROUS_ARG_PATTERNS:
        for pattern in DANGEROUS_ARG_PATTERNS[tool]:
            if re.search(pattern, args):
                return "high"

    # Read-only tools are always low risk
    if tool in READ_ONLY_TOOLS:
        return "low"

    # Destructive tools default to medium-high
    if tool in DESTRUCTIVE_TOOLS:
        return "medium"

    # Unknown tools default to medium
    return "medium"


# ═══════════════════════════════════════════════════════════════════════════════
# ACTION SUMMARY GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

# Tool-specific summary generators
TOOL_SUMMARIES = {
    "read_file": lambda args: f"Read file: {args.get('path', '?')}",
    "write_file": lambda args: f"Write file: {args.get('path', '?')} ({len(args.get('content', ''))} chars)",
    "append_file": lambda args: f"Append to: {args.get('path', '?')}",
    "delete_file": lambda args: f"DELETE file: {args.get('path', '?')}",
    "list_files": lambda args: f"List directory: {args.get('path', '?')}",
    "file_exists": lambda args: f"Check file: {args.get('path', '?')}",
    "glob": lambda args: f"Glob pattern: {args.get('pattern', '?')}",
    "grep": lambda args: f"Search: '{args.get('pattern', '?')}' in {args.get('path', '?')}",
    "shell": lambda args: f"Execute shell: {args.get('command', '?')[:60]}",
    "web_search": lambda args: f"Web search: '{args.get('query', '?')}'",
    "web_fetch": lambda args: f"Fetch URL: {args.get('url', '?')[:60]}",
    "code_run": lambda args: f"Run code: {args.get('code', '?')[:50]}...",
    "python": lambda args: f"Run Python: {args.get('code', '?')[:50]}...",
    "git_commit": lambda args: f"Git commit: {args.get('message', '?')}",
    "git_diff": lambda args: f"Git diff on: {args.get('path', 'repo')}",
    "screenshot": lambda args: "Take screenshot",
    "system_info": lambda args: "Get system information",
    "email_send": lambda args: f"Send email to: {args.get('to', '?')}",
    "schedule_task": lambda args: f"Schedule: {args.get('task', '?')}",
    "browser_open": lambda args: f"Open browser: {args.get('url', '?')[:50]}",
    "browser_click": lambda args: f"Click element: {args.get('selector', '?')}",
    "browser_type": lambda args: f"Type into: {args.get('selector', '?')}",
}


def generate_action_summary(task: DelegationTask) -> str:
    """
    Generate a human-readable action summary for a DelegationTask.
    Falls back to generic description if no specific formatter exists.
    """
    formatter = TOOL_SUMMARIES.get(task.tool_name)
    if formatter:
        try:
            return formatter(task.tool_args)
        except (KeyError, TypeError):
            pass

    # Generic fallback
    args_summary = ", ".join(f"{k}={v}" for k, v in list(task.tool_args.items())[:3])
    return f"{task.tool_name}({args_summary})"


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PLAN FORMATTER
# ═══════════════════════════════════════════════════════════════════════════════

class PlanFormatter:
    """
    Formats delegation plans for display in the terminal.

    Supports multiple output modes:
    - rich_table: Rich library formatted table (production)
    - plain: Plain text table (fallback/no Rich)
    - json: JSON format (API/machine consumption)
    - compact: Single-line summary (logging)
    """

    def __init__(self, mode: str = "plain"):
        """
        Args:
            mode: Output format — "rich_table", "plain", "json", "compact"
        """
        self.mode = mode

    def format_plan(
        self,
        tasks: List[DelegationTask],
        include_args: bool = True,
    ) -> Any:
        """
        Format a list of DelegationTasks into a displayable plan.

        Args:
            tasks: List of delegation tasks to format
            include_args: Whether to include full tool arguments in output

        Returns:
            Formatted output (type depends on mode)
        """
        rows = self._build_rows(tasks)

        if self.mode == "rich_table":
            return self._format_rich_table(rows, include_args)
        elif self.mode == "json":
            return self._format_json(rows)
        elif self.mode == "compact":
            return self._format_compact(rows)
        else:
            return self._format_plain(rows, include_args)

    def _build_rows(self, tasks: List[DelegationTask]) -> List[PlanRow]:
        """Convert DelegationTasks to PlanRows with risk assessment."""
        rows = []
        for i, task in enumerate(tasks):
            rows.append(PlanRow(
                index=i,
                worker_id=task.worker_id,
                tool_name=task.tool_name,
                action_summary=generate_action_summary(task),
                full_args=task.tool_args,
                reason=task.reason,
                risk_level=assess_risk(task),
            ))
        return rows

    def _format_plain(self, rows: List[PlanRow], include_args: bool) -> str:
        """Format as plain text table."""
        if not rows:
            return "  (no tasks)"

        lines = []
        lines.append("")
        lines.append("=" * 78)
        lines.append("  EAA DELEGATION PLAN — DRY RUN")
        lines.append("=" * 78)
        lines.append("")
        lines.append(
            f"  {'#':>3}  | {'WORKER':<10} | {'TOOL':<18} | "
            f"{'ACTION':<30} | {'RISK':<8}"
        )
        lines.append(
            f"  {'---':>3}-+-{'-'*10}-+-{'-'*18}-+-{'-'*30}-+-{'-'*8}"
        )

        for row in rows:
            # Truncate action summary to fit
            action = row.action_summary[:28] + ".." if len(row.action_summary) > 30 else row.action_summary
            risk_indicator = {
                "low": "[LOW]",
                "medium": "[MED]",
                "high": "[HIGH]",
                "critical": "[CRIT]",
            }.get(row.risk_level, "[???]")

            lines.append(
                f"  {row.index:>3}  | {row.worker_id:<10} | {row.tool_name:<18} | "
                f"{action:<30} | {risk_indicator:<8}"
            )

        lines.append("-" * 78)

        # Include reasons
        if any(row.reason for row in rows):
            lines.append("")
            lines.append("  REASONS:")
            for row in rows:
                if row.reason:
                    lines.append(f"    [{row.index}] {row.reason}")

        # Include full args if requested
        if include_args and any(row.full_args for row in rows):
            lines.append("")
            lines.append("  FULL ARGUMENTS:")
            for row in rows:
                if row.full_args:
                    args_str = json.dumps(row.full_args, indent=2, default=str)
                    lines.append(f"    [{row.index}] {row.tool_name}: {args_str}")

        # Risk summary
        risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for row in rows:
            risk_counts[row.risk_level] = risk_counts.get(row.risk_level, 0) + 1

        lines.append("")
        lines.append(
            f"  Risk summary: "
            f"{risk_counts['low']} low, "
            f"{risk_counts['medium']} medium, "
            f"{risk_counts['high']} high, "
            f"{risk_counts['critical']} critical"
        )
        lines.append(f"  Total tasks: {len(rows)}")
        lines.append("")

        return "\n".join(lines)

    def _format_rich_table(self, rows: List[PlanRow], include_args: bool):
        """
        Format using Rich library table.
        Returns a Rich Table object (caller must print it).
        """
        try:
            from rich.console import Console
            from rich.table import Table
            from rich.panel import Panel
        except ImportError:
            # Fallback to plain if Rich not available
            return self._format_plain(rows, include_args)

        console = Console()

        # Risk color mapping
        risk_colors = {
            "low": "green",
            "medium": "yellow",
            "high": "red",
            "critical": "bold red",
        }

        table = Table(
            title="[bold]EAA DELEGATION PLAN — DRY RUN[/bold]",
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
            padding=(0, 1),
        )

        table.add_column("#", style="dim", width=3, justify="right")
        table.add_column("WORKER", style="bold magenta", width=10)
        table.add_column("TOOL", style="bold blue", width=18)
        table.add_column("PROPOSED ACTION", style="white", width=35)
        table.add_column("RISK", width=8, justify="center")

        for row in rows:
            action = row.action_summary
            if len(action) > 33:
                action = action[:31] + ".."

            risk_style = risk_colors.get(row.risk_level, "white")
            risk_text = row.risk_level.upper()

            table.add_row(
                str(row.index),
                row.worker_id,
                row.tool_name,
                action,
                f"[{risk_style}]{risk_text}[/{risk_style}]",
            )

        # Build full output with Rich Panel
        panel_content = console.render_str(table)
        return panel_content

    def _format_json(self, rows: List[PlanRow]) -> str:
        """Format as JSON string."""
        return json.dumps(
            [row.to_dict() for row in rows],
            indent=2,
            default=str,
        )

    def _format_compact(self, rows: List[PlanRow]) -> str:
        """Format as compact single-line summary."""
        if not rows:
            return "Plan: (empty)"

        worker_summary = {}
        for row in rows:
            worker_summary.setdefault(row.worker_id, []).append(row.tool_name)

        parts = []
        for worker, tools in worker_summary.items():
            tools_str = ", ".join(tools)
            parts.append(f"{worker}[{tools_str}]")

        return f"Plan: {'; '.join(parts)} ({len(rows)} tasks)"

    def format_single_row(self, row: PlanRow) -> str:
        """Format a single row for modification display."""
        return (
            f"  [{row.index}] worker={row.worker_id} | "
            f"tool={row.tool_name} | "
            f"action={row.action_summary} | "
            f"risk={row.risk_level}"
        )


__all__ = [
    "PlanFormatter",
    "PlanRow",
    "assess_risk",
    "generate_action_summary",
]
