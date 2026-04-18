"""
EAA V4 - Permission Manager
============================
The central permission checking system for EAA V4.

This module integrates:
  - RuleEngine (permission_rules.py) → regex/pattern-based rules
  - SafetyClassifier (safety_classifier.py) → AI-powered intent analysis
  - DryRunProtocol (dry_run.py) → human approval for risky operations

The PermissionManager sits between the Router and the Dry-Run Protocol
in the execution pipeline:

  Router → PermissionManager → DryRunProtocol → WorkerManager

Flow:
  1. Master delegates tasks (DelegationTask list)
  2. PermissionManager checks each task:
     a. Hard denylist → immediate block
     b. Path sandbox → deny if outside allowed paths
     c. Profile defaults → allow/review based on tool category
     d. AI classifier → deep intent analysis for ambiguous cases
  3. Allowed tasks pass through to DryRunProtocol
  4. Blocked tasks are returned with reasons
  5. Review-required tasks are flagged with elevated risk

Key Design Decisions:
  - PermissionManager caches results for identical tool+args (performance)
  - User can override per-session with "always allow tool X" commands
  - Permission decisions are logged for audit trail
  - The AI classifier is only invoked for REVIEW_REQUIRED cases (saves VRAM)
"""

import json
import time
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

from permission_rules import (
    RuleEngine, RuleMatch, PermissionOutcome, PermissionProfile,
    SandboxConfig, ToolCategory, TOOL_CATEGORIES,
    create_rule_engine,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# PERMISSION RESULT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PermissionResult:
    """
    Result of checking permissions for a single DelegationTask.
    Wraps the RuleMatch with additional context for the execution pipeline.
    """
    task_index: int
    allowed: bool                              # Can proceed to dry-run
    blocked: bool                              # Hard blocked, never execute
    needs_review: bool                         # Needs dry-run approval
    needs_classifier: bool                     # Needs AI classifier check
    rule_match: Optional[RuleMatch] = None     # The matching rule
    classifier_verdict: Optional[str] = None   # "safe" / "suspicious" / "dangerous"
    effective_risk: str = "low"                # Risk level for dry-run display

    def to_dict(self) -> Dict:
        return {
            "task_index": self.task_index,
            "allowed": self.allowed,
            "blocked": self.blocked,
            "needs_review": self.needs_review,
            "needs_classifier": self.needs_classifier,
            "rule_match": self.rule_match.to_dict() if self.rule_match else None,
            "classifier_verdict": self.classifier_verdict,
            "effective_risk": self.effective_risk,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH PERMISSION RESULT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class BatchPermissionResult:
    """
    Result of checking permissions for a batch of tasks.
    Splits tasks into: allowed, blocked, needs_review, needs_classifier.
    """
    results: List[PermissionResult] = field(default_factory=list)
    allowed_tasks: List[Any] = field(default_factory=list)       # DelegationTasks
    blocked_tasks: List[Any] = field(default_factory=list)       # Blocked tasks
    review_tasks: List[Any] = field(default_factory=list)        # Needs review
    classifier_tasks: List[Any] = field(default_factory=list)    # Needs AI check

    @property
    def has_blocks(self) -> bool:
        return len(self.blocked_tasks) > 0

    @property
    def has_reviews(self) -> bool:
        return len(self.review_tasks) > 0

    @property
    def has_classifier_checks(self) -> bool:
        return len(self.classifier_tasks) > 0

    def to_dict(self) -> Dict:
        return {
            "total": len(self.results),
            "allowed": len(self.allowed_tasks),
            "blocked": len(self.blocked_tasks),
            "needs_review": len(self.review_tasks),
            "needs_classifier": len(self.classifier_tasks),
            "results": [r.to_dict() for r in self.results],
        }

    def get_block_reasons(self) -> List[str]:
        """Get human-readable reasons for all blocked tasks."""
        reasons = []
        for r in self.results:
            if r.blocked and r.rule_match:
                reasons.append(f"Task {r.task_index}: {r.rule_match.reason}")
        return reasons


# ═══════════════════════════════════════════════════════════════════════════════
# PERMISSION CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PermissionConfig:
    """Configuration for the PermissionManager."""
    profile: PermissionProfile = PermissionProfile.BALANCED
    enable_sandbox: bool = True
    enable_classifier: bool = False        # Start disabled until Phase 1 done
    enable_caching: bool = True
    enable_audit_log: bool = True
    max_cache_size: int = 1000
    allowed_write_paths: List[str] = field(default_factory=list)
    protected_paths: List[str] = field(default_factory=list)
    session_allowlist: List[str] = field(default_factory=list)  # Runtime overrides
    session_denylist: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# PERMISSION MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class PermissionManager:
    """
    Central permission checking system.

    Integrates the RuleEngine with optional AI classifier
    to provide comprehensive permission checking for all
    DelegationTasks before they reach the Dry-Run Protocol.

    Usage:
        pm = PermissionManager(config=PermissionConfig())
        result = pm.check_tasks(tasks)
        if result.has_blocks:
            print("Blocked:", result.get_block_reasons())
        if result.has_classifier_checks:
            # Run AI classifier on result.classifier_tasks
            pass
        # result.allowed_tasks and result.review_tasks proceed to dry-run
    """

    def __init__(
        self,
        config: Optional[PermissionConfig] = None,
        rule_engine: Optional[RuleEngine] = None,
    ):
        self.config = config or PermissionConfig()

        # Build rule engine from config
        if rule_engine:
            self.rule_engine = rule_engine
        else:
            sandbox = SandboxConfig(
                enabled=self.config.enable_sandbox,
                allowed_write_paths=self.config.allowed_write_paths,
                protected_paths=self.config.protected_paths,
            )
            self.rule_engine = RuleEngine(
                profile=self.config.profile,
                sandbox=sandbox,
                custom_allowlist=set(self.config.session_allowlist),
                custom_denylist=set(self.config.session_denylist),
            )

        # Classifier reference (set later when Phase 1 classifier is ready)
        self._classifier = None

        # Cache: (tool_name, args_hash) → RuleMatch
        self._cache: Dict[str, RuleMatch] = {}
        self._cache_hits = 0
        self._cache_misses = 0

        # Audit log
        self._audit_log: List[Dict] = []

        # Stats
        self._total_checks = 0
        self._total_blocked = 0
        self._total_allowed = 0
        self._total_reviewed = 0

        logger.info(
            f"[Permissions] Manager initialized: "
            f"profile={self.config.profile.value}, "
            f"sandbox={self.config.enable_sandbox}, "
            f"classifier={self.config.enable_classifier}"
        )

    def set_classifier(self, classifier):
        """
        Set the AI safety classifier (injected after initialization).
        This allows the classifier to be loaded independently and
        connected when ready.
        """
        self._classifier = classifier
        self.config.enable_classifier = True
        logger.info("[Permissions] AI classifier connected")

    def check_task(
        self,
        task_index: int,
        tool_name: str,
        tool_args: Dict,
        worker_id: str = "",
    ) -> PermissionResult:
        """
        Check permissions for a single tool invocation.

        Args:
            task_index: Index of the task in the delegation batch
            tool_name: Name of the tool
            tool_args: Tool arguments
            worker_id: Worker making the call

        Returns:
            PermissionResult with allow/block/review decision
        """
        self._total_checks += 1

        # Check cache
        if self.config.enable_caching:
            cache_key = self._make_cache_key(tool_name, tool_args)
            if cache_key in self._cache:
                self._cache_hits += 1
                rule_match = self._cache[cache_key]
                return self._build_result(
                    task_index, rule_match, tool_name, tool_args
                )
            self._cache_misses += 1

        # Evaluate rules
        rule_match = self.rule_engine.evaluate(tool_name, tool_args, worker_id)

        # Cache result
        if self.config.enable_caching:
            self._cache[cache_key] = rule_match
            if len(self._cache) > self.config.max_cache_size:
                # Evict oldest entries (simple FIFO)
                keys_to_remove = list(self._cache.keys())[:100]
                for key in keys_to_remove:
                    del self._cache[key]

        result = self._build_result(task_index, rule_match, tool_name, tool_args)

        # Audit log
        if self.config.enable_audit_log:
            self._log_decision(tool_name, tool_args, worker_id, result)

        # Update counters
        if result.blocked:
            self._total_blocked += 1
        elif result.needs_review:
            self._total_reviewed += 1
        else:
            self._total_allowed += 1

        return result

    def check_tasks(self, tasks) -> BatchPermissionResult:
        """
        Check permissions for a batch of DelegationTasks.

        This is the main entry point used by the execution pipeline.
        It processes all tasks and splits them into categories:
        - allowed: safe to proceed (may still go through dry-run)
        - blocked: hard denied, never execute
        - review: needs human approval (→ dry-run with elevated risk)
        - classifier: needs AI analysis before decision

        Args:
            tasks: List of DelegationTask objects

        Returns:
            BatchPermissionResult with categorized tasks
        """
        batch_result = BatchPermissionResult()

        for i, task in enumerate(tasks):
            perm_result = self.check_task(
                task_index=i,
                tool_name=task.tool_name,
                tool_args=task.tool_args,
                worker_id=task.worker_id,
            )
            batch_result.results.append(perm_result)

            if perm_result.blocked:
                batch_result.blocked_tasks.append(task)
            elif perm_result.needs_classifier:
                batch_result.classifier_tasks.append(task)
                batch_result.review_tasks.append(task)  # Also goes to review
            elif perm_result.needs_review:
                batch_result.review_tasks.append(task)
            else:
                batch_result.allowed_tasks.append(task)

        logger.info(
            f"[Permissions] Batch check: "
            f"{len(batch_result.allowed_tasks)} allowed, "
            f"{len(batch_result.blocked_tasks)} blocked, "
            f"{len(batch_result.review_tasks)} review, "
            f"{len(batch_result.classifier_tasks)} classifier"
        )

        return batch_result

    def run_classifier_on_tasks(self, tasks) -> List[PermissionResult]:
        """
        Run the AI safety classifier on a list of tasks.
        Returns updated PermissionResults with classifier verdicts.
        """
        results = []
        for i, task in enumerate(tasks):
            perm_result = self.check_task(
                task_index=i,
                tool_name=task.tool_name,
                tool_args=task.tool_args,
                worker_id=task.worker_id,
            )

            if self._classifier and self.config.enable_classifier:
                try:
                    verdict = self._classifier.classify(
                        tool_name=task.tool_name,
                        tool_args=task.tool_args,
                        worker_id=task.worker_id,
                        reason=task.reason,
                    )
                    perm_result.classifier_verdict = verdict.label

                    # Classifier can escalate: suspicious → review, dangerous → block
                    if verdict.label == "dangerous":
                        perm_result.blocked = True
                        perm_result.allowed = False
                        perm_result.needs_review = False
                    elif verdict.label == "suspicious":
                        perm_result.needs_review = True
                        perm_result.effective_risk = "high"
                except Exception as e:
                    logger.error(
                        f"[Permissions] Classifier error for task {i}: {e}"
                    )
                    # On classifier error, default to review
                    perm_result.needs_review = True

            results.append(perm_result)

        return results

    def session_allow(self, tool_name: str):
        """
        Add a tool to the session allowlist (user override).
        This tool will be allowed for the rest of the session.
        """
        self.config.session_allowlist.append(tool_name)
        self.rule_engine.custom_allowlist.add(tool_name)
        self._cache.clear()  # Invalidate cache — overrides changed
        logger.info(f"[Permissions] Session allow: {tool_name}")

    def session_deny(self, tool_name: str):
        """
        Add a tool to the session denylist (user override).
        This tool will be blocked for the rest of the session.
        """
        self.config.session_denylist.append(tool_name)
        self.rule_engine.custom_denylist.add(tool_name)
        self._cache.clear()  # Invalidate cache — overrides changed
        logger.info(f"[Permissions] Session deny: {tool_name}")

    def clear_session_overrides(self):
        """Clear all session-level allow/deny overrides."""
        self.config.session_allowlist.clear()
        self.config.session_denylist.clear()
        self.rule_engine.custom_allowlist.clear()
        self.rule_engine.custom_denylist.clear()
        logger.info("[Permissions] Session overrides cleared")

    def set_profile(self, profile_name: str):
        """Change the permission profile at runtime."""
        try:
            profile = PermissionProfile(profile_name)
            self.config.profile = profile
            self.rule_engine.profile = profile
            # Clear cache since profile changed
            self._cache.clear()
            logger.info(f"[Permissions] Profile changed to: {profile_name}")
        except ValueError:
            logger.error(f"[Permissions] Unknown profile: {profile_name}")

    def add_allowed_path(self, path: str):
        """Add a directory to the write-allowed paths."""
        import os
        norm = os.path.normpath(os.path.expanduser(path))
        self.rule_engine.sandbox.allowed_write_paths.append(norm)
        self.config.allowed_write_paths.append(norm)
        self._cache.clear()  # Invalidate cache
        logger.info(f"[Permissions] Added allowed write path: {norm}")

    def _build_result(
        self,
        task_index: int,
        rule_match: RuleMatch,
        tool_name: str,
        tool_args: Dict,
    ) -> PermissionResult:
        """Build a PermissionResult from a RuleMatch."""
        allowed = rule_match.outcome == PermissionOutcome.ALLOW
        blocked = rule_match.outcome == PermissionOutcome.DENY
        needs_review = rule_match.outcome == PermissionOutcome.REVIEW_REQUIRED
        needs_classifier = rule_match.requires_classifier

        # Determine effective risk level
        from plan_formatter import assess_risk
        from router import DelegationTask

        base_risk = assess_risk(DelegationTask(
            worker_id="",
            tool_name=tool_name,
            tool_args=tool_args,
        ))

        risk_priority = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        effective_risk = base_risk
        if rule_match.risk_override:
            override_priority = risk_priority.get(rule_match.risk_override, 1)
            base_priority = risk_priority.get(base_risk, 0)
            if override_priority > base_priority:
                effective_risk = rule_match.risk_override

        # Escalate risk for review-required tasks
        if needs_review and risk_priority.get(effective_risk, 0) < 2:
            effective_risk = "medium"

        return PermissionResult(
            task_index=task_index,
            allowed=allowed,
            blocked=blocked,
            needs_review=needs_review,
            needs_classifier=needs_classifier,
            rule_match=rule_match,
            effective_risk=effective_risk,
        )

    def _make_cache_key(self, tool_name: str, tool_args: Dict) -> str:
        """Create a hashable cache key from tool+args."""
        args_str = json.dumps(tool_args, sort_keys=True, default=str)
        return f"{tool_name}:{hash(args_str)}"

    def _log_decision(
        self,
        tool_name: str,
        tool_args: Dict,
        worker_id: str,
        result: PermissionResult,
    ):
        """Log a permission decision to the audit log."""
        entry = {
            "timestamp": time.time(),
            "tool": tool_name,
            "worker": worker_id,
            "outcome": "block" if result.blocked else (
                "review" if result.needs_review else "allow"
            ),
            "risk": result.effective_risk,
            "rule": result.rule_match.rule_id if result.rule_match else None,
            "reason": result.rule_match.reason if result.rule_match else None,
        }
        self._audit_log.append(entry)

        # Keep audit log bounded
        if len(self._audit_log) > 5000:
            self._audit_log = self._audit_log[-3000:]

    def get_stats(self) -> Dict:
        """Get permission manager statistics."""
        return {
            "profile": self.config.profile.value,
            "total_checks": self._total_checks,
            "total_allowed": self._total_allowed,
            "total_blocked": self._total_blocked,
            "total_reviewed": self._total_reviewed,
            "cache_size": len(self._cache),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": (
                f"{self._cache_hits / max(1, self._cache_hits + self._cache_misses) * 100:.1f}%"
            ),
            "session_allowlist": self.config.session_allowlist,
            "session_denylist": self.config.session_denylist,
            "classifier_enabled": self.config.enable_classifier,
            "audit_entries": len(self._audit_log),
            "rule_engine": self.rule_engine.list_rules(),
        }

    def get_audit_log(self, limit: int = 50) -> List[Dict]:
        """Get recent audit log entries."""
        return self._audit_log[-limit:]

    def export_config(self) -> Dict:
        """Export current configuration for persistence."""
        return {
            "profile": self.config.profile.value,
            "enable_sandbox": self.config.enable_sandbox,
            "enable_classifier": self.config.enable_classifier,
            "allowed_write_paths": self.config.allowed_write_paths,
            "protected_paths": self.config.protected_paths,
            "session_allowlist": self.config.session_allowlist,
            "session_denylist": self.config.session_denylist,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_permission_manager(
    profile: str = "balanced",
    allowed_paths: Optional[List[str]] = None,
) -> PermissionManager:
    """
    Create a PermissionManager with common defaults.

    Args:
        profile: Permission profile (strict/balanced/permissive/developer)
        allowed_paths: Directories where write operations are allowed
    """
    config = PermissionConfig(
        profile=PermissionProfile(profile),
        allowed_write_paths=allowed_paths or [],
    )
    return PermissionManager(config=config)


__all__ = [
    "PermissionResult",
    "BatchPermissionResult",
    "PermissionConfig",
    "PermissionManager",
    "create_permission_manager",
]
