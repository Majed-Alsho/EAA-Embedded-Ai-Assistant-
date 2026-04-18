"""
EAA V4 - Dry-Run Protocol
==========================
The safety net between planning and execution.

Before the Master (Jarvis) sends any delegation to a Worker, the Dry-Run
Protocol intercepts it and presents a human-readable execution plan for
approval. This gives the user supreme command over the agent swarm before
a single VRAM swap occurs.

Flow:
  1. Master produces delegation tasks (DelegationTask list)
  2. DryRunProtocol formats tasks into a readable plan (via PlanFormatter)
  3. Plan is displayed with [TARGET WORKER] | [TOOL] | [PROPOSED ACTION]
  4. User sees: "Execute Plan? (y/n/modify)"
  5. y → Execute all approved tasks
  6. n → Discard plan, ask Master to revise
  7. modify → User edits individual rows, then re-confirms

The protocol is designed to be:
  - Non-blocking in API mode (auto-approve configurable)
  - Interactive in CLI mode (always prompt)
  - Skippable for read-only operations (configurable threshold)
"""

import json
import logging
import time
from typing import Dict, List, Optional, Tuple, Callable, Any
from dataclasses import dataclass, field
from enum import Enum

from router import DelegationTask, RoutingResult
from plan_formatter import PlanFormatter, PlanRow, assess_risk

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# APPROVAL MODES
# ═══════════════════════════════════════════════════════════════════════════════

class ApprovalMode(Enum):
    INTERACTIVE = "interactive"    # Always prompt user
    AUTO_LOW_RISK = "auto_low"     # Auto-approve low/medium, prompt for high/critical
    AUTO_READONLY = "auto_readonly" # Auto-approve read-only tools only
    AUTO_ALL = "auto_all"          # Auto-approve everything (CI/headless mode)
    DENY_ALL = "deny_all"          # Block all delegations (debug mode)


# ═══════════════════════════════════════════════════════════════════════════════
# DRY RUN RESULT
# ═══════════════════════════════════════════════════════════════════════════════

class DryRunOutcome(Enum):
    APPROVED = "approved"          # User approved all tasks
    PARTIALLY_APPROVED = "partial" # User approved some, modified others
    REJECTED = "rejected"          # User rejected the plan
    MODIFIED = "modified"          # User wants to modify before approving
    AUTO_APPROVED = "auto"         # Auto-approved (no user interaction)


@dataclass
class DryRunResult:
    """
    Result of the dry-run approval process.
    Contains the approved (possibly modified) task list.
    """
    outcome: DryRunOutcome
    approved_tasks: List[DelegationTask] = field(default_factory=list)
    rejected_tasks: List[DelegationTask] = field(default_factory=list)
    user_message: str = ""
    modification_log: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "outcome": self.outcome.value,
            "approved_count": len(self.approved_tasks),
            "rejected_count": len(self.rejected_tasks),
            "approved_tasks": [t.to_dict() for t in self.approved_tasks],
            "rejected_tasks": [t.to_dict() for t in self.rejected_tasks],
            "user_message": self.user_message,
            "modifications": self.modification_log,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# DRY RUN CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DryRunConfig:
    """Configuration for the Dry-Run Protocol."""
    mode: ApprovalMode = ApprovalMode.INTERACTIVE
    show_args: bool = True                # Show full tool arguments
    show_reasons: bool = True             # Show task reasons
    max_plan_size: int = 50               # Max tasks before auto-batching
    timeout_seconds: int = 300            # Max time to wait for user input
    auto_approve_timeout: int = 0         # Auto-approve after N seconds (0=never)
    risk_threshold: str = "medium"        # Auto-approve up to this risk level
    confirm_destructive: bool = True      # Always confirm destructive ops

    # Read-only tools that can be auto-approved
    readonly_tools: set = field(default_factory=lambda: {
        "read_file", "list_files", "file_exists", "glob", "grep",
        "web_search", "web_fetch", "system_info", "process_list",
        "datetime", "calculator", "git_status", "git_diff", "git_log",
        "pdf_read", "pdf_info", "docx_read", "xlsx_read",
        "browser_screenshot", "browser_get_text",
        "memory_recall", "memory_list", "memory_search",
        "json_parse", "csv_read", "hash_text", "hash_file",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN DRY RUN PROTOCOL
# ═══════════════════════════════════════════════════════════════════════════════

class DryRunProtocol:
    """
    Intercepts delegation plans before execution and presents them for
    human approval.

    Usage:
        protocol = DryRunProtocol(config=DryRunConfig())
        result = protocol.review(tasks)

        if result.outcome in (DryRunOutcome.APPROVED, DryRunOutcome.PARTIALLY_APPROVED):
            # Execute result.approved_tasks
            pass
        elif result.outcome == DryRunOutcome.REJECTED:
            # Ask Master to revise
            pass
        elif result.outcome == DryRunOutcome.MODIFIED:
            # Re-present modified plan
            result = protocol.review(result.approved_tasks)
    """

    def __init__(
        self,
        config: DryRunConfig = None,
        formatter: PlanFormatter = None,
        input_callback: Optional[Callable] = None,
    ):
        """
        Args:
            config: DryRunConfig instance
            formatter: PlanFormatter for display (auto-created if None)
            input_callback: Custom input function (defaults to built-in input())
                           Useful for API/web interface integration.
        """
        self.config = config or DryRunConfig()
        self.formatter = formatter or PlanFormatter(mode="plain")
        self.input_callback = input_callback or self._default_input

        # Stats
        self._total_reviews = 0
        self._total_approved = 0
        self._total_rejected = 0
        self._total_modified = 0
        self._review_history: List[Dict] = []

        logger.info(
            f"[DryRun] Protocol initialized: mode={self.config.mode.value}"
        )

    def review(self, tasks: List[DelegationTask]) -> DryRunResult:
        """
        Review a delegation plan and get user approval.

        This is the main entry point. It:
        1. Formats the plan for display
        2. Checks auto-approval rules
        3. Prompts user if needed
        4. Returns approved/rejected tasks

        Args:
            tasks: List of DelegationTasks to review

        Returns:
            DryRunResult with outcome and filtered task lists
        """
        self._total_reviews += 1

        if not tasks:
            return DryRunResult(
                outcome=DryRunOutcome.APPROVED,
                user_message="No tasks to review",
            )

        # Step 1: Format and display the plan
        plan_display = self.formatter.format_plan(
            tasks, include_args=self.config.show_args
        )
        if isinstance(plan_display, str):
            print(plan_display)

        # Step 2: Check auto-approval rules
        auto_result = self._check_auto_approval(tasks)
        if auto_result:
            logger.info(f"[DryRun] Auto-approved: {len(tasks)} tasks")
            return auto_result

        # Step 3: Interactive approval
        if self.config.mode == ApprovalMode.INTERACTIVE:
            return self._interactive_review(tasks)
        elif self.config.mode == ApprovalMode.AUTO_LOW_RISK:
            return self._risk_based_review(tasks)
        elif self.config.mode == ApprovalMode.AUTO_READONLY:
            return self._readonly_review(tasks)
        elif self.config.mode == ApprovalMode.AUTO_ALL:
            return DryRunResult(
                outcome=DryRunOutcome.AUTO_APPROVED,
                approved_tasks=tasks,
                user_message="Auto-approved (AUTO_ALL mode)",
            )
        elif self.config.mode == ApprovalMode.DENY_ALL:
            return DryRunResult(
                outcome=DryRunOutcome.REJECTED,
                rejected_tasks=tasks,
                user_message="All tasks denied (DENY_ALL mode)",
            )
        else:
            return self._interactive_review(tasks)

    def _check_auto_approval(self, tasks: List[DelegationTask]) -> Optional[DryRunResult]:
        """
        Check if all tasks qualify for auto-approval.
        Returns None if user interaction is needed.
        """
        if self.config.mode == ApprovalMode.AUTO_ALL:
            return DryRunResult(
                outcome=DryRunOutcome.AUTO_APPROVED,
                approved_tasks=tasks,
                user_message="Auto-approved (AUTO_ALL mode)",
            )

        # Check if all tasks are low-risk and read-only
        all_readonly = all(
            t.tool_name in self.config.readonly_tools for t in tasks
        )
        all_low_risk = all(
            assess_risk(t) == "low" for t in tasks
        )

        if self.config.mode == ApprovalMode.AUTO_READONLY and all_readonly:
            return DryRunResult(
                outcome=DryRunOutcome.AUTO_APPROVED,
                approved_tasks=tasks,
                user_message=f"Auto-approved: all {len(tasks)} tasks are read-only",
            )

        risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        threshold = risk_order.get(self.config.risk_threshold, 1)

        if self.config.mode == ApprovalMode.AUTO_LOW_RISK:
            all_below_threshold = all(
                risk_order.get(assess_risk(t), 2) <= threshold
                for t in tasks
            )
            if all_below_threshold:
                return DryRunResult(
                    outcome=DryRunOutcome.AUTO_APPROVED,
                    approved_tasks=tasks,
                    user_message=(
                        f"Auto-approved: all tasks below "
                        f"{self.config.risk_threshold} risk threshold"
                    ),
                )

        return None  # User interaction needed

    def _interactive_review(self, tasks: List[DelegationTask]) -> DryRunResult:
        """
        Interactive review with y/n/modify prompt.
        """
        # Prompt user
        prompt = "\n  Execute Plan? (y/n/modify): "
        response = self.input_callback(prompt).strip().lower()

        if response in ("y", "yes", ""):
            # Approve all
            self._total_approved += 1
            self._record_review(tasks, DryRunOutcome.APPROVED)
            return DryRunResult(
                outcome=DryRunOutcome.APPROVED,
                approved_tasks=tasks,
                user_message="Approved by user",
            )

        elif response in ("n", "no"):
            # Reject all
            self._total_rejected += 1
            self._record_review(tasks, DryRunOutcome.REJECTED)
            return DryRunResult(
                outcome=DryRunOutcome.REJECTED,
                rejected_tasks=tasks,
                user_message="Rejected by user",
            )

        elif response in ("m", "modify"):
            # Enter modification mode
            return self._modification_mode(tasks)

        elif response == "v":
            # Toggle verbose mode
            self.config.show_args = not self.config.show_args
            return self.review(tasks)

        else:
            # Unknown response — re-prompt
            print(f"  Unknown response '{response}'. Please enter y, n, or modify.")
            return self._interactive_review(tasks)

    def _modification_mode(self, tasks: List[DelegationTask]) -> DryRunResult:
        """
        Allow user to modify individual tasks before approval.
        Supports: remove task, change worker, change args, change priority.
        """
        print("\n  --- MODIFICATION MODE ---")
        print("  Commands:")
        print("    remove N     - Remove task N from plan")
        print("    worker N ID  - Change task N's worker to ID")
        print("    args N JSON  - Change task N's arguments")
        print("    priority N P - Change task N's priority")
        print("    done         - Approve modified plan")
        print("    cancel       - Reject entire plan")
        print("")

        modified_tasks = list(tasks)
        modifications = []

        while True:
            cmd = self.input_callback("  modify> ").strip()

            if cmd == "done":
                self._total_approved += 1
                self._total_modified += len(modifications)
                self._record_review(modified_tasks, DryRunOutcome.MODIFIED)
                return DryRunResult(
                    outcome=DryRunOutcome.PARTIALLY_APPROVED,
                    approved_tasks=modified_tasks,
                    rejected_tasks=[t for t in tasks if t not in modified_tasks],
                    user_message=f"Modified and approved ({len(modifications)} changes)",
                    modification_log=modifications,
                )

            elif cmd == "cancel":
                self._total_rejected += 1
                self._record_review(tasks, DryRunOutcome.REJECTED)
                return DryRunResult(
                    outcome=DryRunOutcome.REJECTED,
                    rejected_tasks=tasks,
                    user_message="Cancelled during modification",
                )

            elif cmd.startswith("remove "):
                try:
                    idx = int(cmd.split()[1])
                    if 0 <= idx < len(modified_tasks):
                        removed = modified_tasks.pop(idx)
                        modifications.append(f"Removed task {idx}: {removed.tool_name}")
                        print(f"  Removed task {idx}")
                    else:
                        print(f"  Invalid index: {idx}")
                except (ValueError, IndexError):
                    print("  Usage: remove N")

            elif cmd.startswith("worker "):
                parts = cmd.split()
                try:
                    idx = int(parts[1])
                    new_worker = parts[2]
                    if 0 <= idx < len(modified_tasks):
                        old_worker = modified_tasks[idx].worker_id
                        # Create a new task with modified worker
                        task = modified_tasks[idx]
                        modified_tasks[idx] = DelegationTask(
                            worker_id=new_worker,
                            tool_name=task.tool_name,
                            tool_args=task.tool_args,
                            reason=task.reason,
                            priority=task.priority,
                            timeout=task.timeout,
                        )
                        modifications.append(
                            f"Task {idx}: worker {old_worker} → {new_worker}"
                        )
                        print(f"  Task {idx}: worker changed to {new_worker}")
                    else:
                        print(f"  Invalid index: {idx}")
                except (ValueError, IndexError):
                    print("  Usage: worker N WORKER_ID")

            elif cmd.startswith("args "):
                parts = cmd.split(None, 2)
                try:
                    idx = int(parts[1])
                    args_json = parts[2]
                    new_args = json.loads(args_json)
                    if 0 <= idx < len(modified_tasks):
                        old_args = modified_tasks[idx].tool_args.copy()
                        modified_tasks[idx].tool_args = new_args
                        modifications.append(
                            f"Task {idx}: args changed ({len(old_args)} → {len(new_args)} keys)"
                        )
                        print(f"  Task {idx}: arguments updated")
                    else:
                        print(f"  Invalid index: {idx}")
                except (ValueError, IndexError, json.JSONDecodeError) as e:
                    print(f"  Usage: args N {{json}}  (error: {e})")

            elif cmd.startswith("priority "):
                parts = cmd.split()
                try:
                    idx = int(parts[1])
                    new_priority = int(parts[2])
                    if 0 <= idx < len(modified_tasks):
                        old_priority = modified_tasks[idx].priority
                        modified_tasks[idx].priority = new_priority
                        modifications.append(
                            f"Task {idx}: priority {old_priority} → {new_priority}"
                        )
                        print(f"  Task {idx}: priority changed to {new_priority}")
                    else:
                        print(f"  Invalid index: {idx}")
                except (ValueError, IndexError):
                    print("  Usage: priority N P")

            elif cmd == "show":
                # Re-display current plan
                plan_display = self.formatter.format_plan(
                    modified_tasks, include_args=self.config.show_args
                )
                if isinstance(plan_display, str):
                    print(plan_display)

            elif cmd == "help":
                print("  Commands: remove N, worker N ID, args N JSON, priority N P, done, cancel, show, help")

            elif cmd:
                print(f"  Unknown command: {cmd}. Type 'help' for commands.")

    def _risk_based_review(self, tasks: List[DelegationTask]) -> DryRunResult:
        """Auto-approve low/medium risk, prompt for high/critical."""
        auto_approved = []
        needs_review = []

        risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        threshold = risk_order.get(self.config.risk_threshold, 1)

        for task in tasks:
            risk = assess_risk(task)
            if risk_order.get(risk, 2) <= threshold:
                auto_approved.append(task)
            else:
                needs_review.append(task)

        if not needs_review:
            return DryRunResult(
                outcome=DryRunOutcome.AUTO_APPROVED,
                approved_tasks=tasks,
                user_message=f"Auto-approved: all {len(tasks)} tasks within risk threshold",
            )

        # Show auto-approved tasks
        if auto_approved:
            print(f"\n  Auto-approved {len(auto_approved)} low-risk tasks:")
            for task in auto_approved:
                print(f"    [OK] {task.tool_name} → {task.worker_id}")

        # Prompt for remaining
        print(f"\n  Review required for {len(needs_review)} higher-risk tasks:")
        plan_display = self.formatter.format_plan(needs_review, include_args=True)
        if isinstance(plan_display, str):
            print(plan_display)

        response = self.input_callback(
            f"\n  Approve {len(needs_review)} high-risk tasks? (y/n/modify): "
        ).strip().lower()

        if response in ("y", "yes", ""):
            all_approved = auto_approved + needs_review
            return DryRunResult(
                outcome=DryRunOutcome.PARTIALLY_APPROVED,
                approved_tasks=all_approved,
                user_message=(
                    f"Approved: {len(auto_approved)} auto + "
                    f"{len(needs_review)} manual"
                ),
            )
        elif response in ("n", "no"):
            return DryRunResult(
                outcome=DryRunOutcome.PARTIALLY_APPROVED,
                approved_tasks=auto_approved,
                rejected_tasks=needs_review,
                user_message=f"Partial: {len(auto_approved)} approved, {len(needs_review)} rejected",
            )
        elif response in ("m", "modify"):
            # Modify just the high-risk tasks
            mod_result = self._modification_mode(needs_review)
            if mod_result.outcome in (DryRunOutcome.APPROVED, DryRunOutcome.PARTIALLY_APPROVED):
                mod_result.approved_tasks = auto_approved + mod_result.approved_tasks
                mod_result.outcome = DryRunOutcome.PARTIALLY_APPROVED
            return mod_result
        else:
            # Default: approve low-risk only
            return DryRunResult(
                outcome=DryRunOutcome.PARTIALLY_APPROVED,
                approved_tasks=auto_approved,
                rejected_tasks=needs_review,
                user_message="Partial: only low-risk tasks approved (default)",
            )

    def _readonly_review(self, tasks: List[DelegationTask]) -> DryRunResult:
        """Auto-approve read-only tools, prompt for write tools."""
        readonly_tasks = []
        write_tasks = []

        for task in tasks:
            if task.tool_name in self.config.readonly_tools:
                readonly_tasks.append(task)
            else:
                write_tasks.append(task)

        if not write_tasks:
            return DryRunResult(
                outcome=DryRunOutcome.AUTO_APPROVED,
                approved_tasks=tasks,
                user_message=f"Auto-approved: all {len(tasks)} tasks are read-only",
            )

        if readonly_tasks:
            print(f"\n  Auto-approved {len(readonly_tasks)} read-only tasks")

        print(f"\n  Write operations requiring approval ({len(write_tasks)}):")
        plan_display = self.formatter.format_plan(write_tasks, include_args=True)
        if isinstance(plan_display, str):
            print(plan_display)

        response = self.input_callback(
            f"\n  Approve {len(write_tasks)} write operations? (y/n/modify): "
        ).strip().lower()

        if response in ("y", "yes", ""):
            return DryRunResult(
                outcome=DryRunOutcome.PARTIALLY_APPROVED,
                approved_tasks=readonly_tasks + write_tasks,
                user_message=f"All approved ({len(readonly_tasks)} auto + {len(write_tasks)} manual)",
            )
        elif response in ("n", "no"):
            return DryRunResult(
                outcome=DryRunOutcome.PARTIALLY_APPROVED,
                approved_tasks=readonly_tasks,
                rejected_tasks=write_tasks,
                user_message=f"Partial: {len(readonly_tasks)} read-only approved, {len(write_tasks)} rejected",
            )
        elif response in ("m", "modify"):
            mod_result = self._modification_mode(write_tasks)
            if mod_result.outcome in (DryRunOutcome.APPROVED, DryRunOutcome.PARTIALLY_APPROVED):
                mod_result.approved_tasks = readonly_tasks + mod_result.approved_tasks
                mod_result.outcome = DryRunOutcome.PARTIALLY_APPROVED
            return mod_result
        else:
            return DryRunResult(
                outcome=DryRunOutcome.PARTIALLY_APPROVED,
                approved_tasks=readonly_tasks,
                rejected_tasks=write_tasks,
                user_message="Partial: only read-only tasks approved (default)",
            )

    def _record_review(self, tasks: List[DelegationTask], outcome):
        """Record a review decision for analytics."""
        self._review_history.append({
            "timestamp": time.time(),
            "task_count": len(tasks),
            "outcome": outcome.value,
            "tools": [t.tool_name for t in tasks],
            "workers": [t.worker_id for t in tasks],
        })
        if len(self._review_history) > 200:
            self._review_history = self._review_history[-200:]

    @staticmethod
    def _default_input(prompt: str) -> str:
        """Default input function (uses built-in input())."""
        return input(prompt)

    def set_input_callback(self, callback: Callable[[str], str]):
        """Set a custom input function for API/web integration."""
        self.input_callback = callback

    def get_stats(self) -> Dict:
        """Get dry-run statistics."""
        return {
            "total_reviews": self._total_reviews,
            "total_approved": self._total_approved,
            "total_rejected": self._total_rejected,
            "total_modified": self._total_modified,
            "mode": self.config.mode.value,
            "recent_reviews": self._review_history[-10:],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_dry_run(
    mode: str = "interactive",
    formatter_mode: str = "plain",
) -> DryRunProtocol:
    """Create a DryRunProtocol with the specified mode."""
    config = DryRunConfig(mode=ApprovalMode(mode))
    formatter = PlanFormatter(mode=formatter_mode)
    return DryRunProtocol(config=config, formatter=formatter)


__all__ = [
    "DryRunProtocol",
    "DryRunConfig",
    "DryRunResult",
    "DryRunOutcome",
    "ApprovalMode",
    "create_dry_run",
]
