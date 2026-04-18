"""
EAA V4 - Permission Rules
==========================
Defines the rule engine for the EAA permission system.

This module establishes:
  - Tool categories (read_only, write, destructive, network, system, etc.)
  - Predefined permission rules (allowlist, denylist, sandbox restrictions)
  - Path-based restrictions (sandbox directories, protected paths)
  - Risk escalation rules (tool+arg pattern matching)
  - User-configurable permission profiles (strict, balanced, permissive)

Architecture:
  Permission rules are evaluated BEFORE the dry-run protocol. If a rule
  hard-blocks an action, it never reaches the dry-run table. If a rule
  requires additional review, the dry-run protocol handles it with
  elevated risk levels.

Integration with Phase 0:
  - plan_formatter.assess_risk() → basic regex risk assessment
  - permissions.PermissionManager → full rule engine (extends risk with rules)
  - safety_classifier.SafetyClassifier → AI-powered deep analysis (Phase 1)

Rule evaluation order:
  1. Hard denylist (immediate block, no exceptions)
  2. Path sandbox enforcement
  3. Tool category defaults
  4. User allowlist overrides
  5. Permission profile defaults
  6. Escalation to safety classifier (if enabled)
"""

import re
import os
import fnmatch
import logging
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL CATEGORIES
# ═══════════════════════════════════════════════════════════════════════════════

class ToolCategory(Enum):
    """Categories of tools with different default permission levels."""
    READ_ONLY = "read_only"         # No side effects, always safe
    WRITE = "write"                 # Modifies files/data, medium risk
    DESTRUCTIVE = "destructive"     # Can delete/destroy, high risk
    NETWORK = "network"             # External network access
    SYSTEM = "system"               # System-level operations (processes, env)
    EXECUTION = "execution"         # Code/shell execution, highest risk
    BROWSER = "browser"             # Browser automation
    DOCUMENT = "document"           # Document creation/modification


# Full mapping of every EAA tool to its category
TOOL_CATEGORIES: Dict[str, ToolCategory] = {
    # --- Coder tools ---
    "read_file": ToolCategory.READ_ONLY,
    "list_files": ToolCategory.READ_ONLY,
    "file_exists": ToolCategory.READ_ONLY,
    "glob": ToolCategory.READ_ONLY,
    "grep": ToolCategory.READ_ONLY,
    "git_status": ToolCategory.READ_ONLY,
    "git_diff": ToolCategory.READ_ONLY,
    "git_log": ToolCategory.READ_ONLY,
    "git_branch": ToolCategory.READ_ONLY,
    "write_file": ToolCategory.WRITE,
    "append_file": ToolCategory.WRITE,
    "create_directory": ToolCategory.WRITE,
    "delete_file": ToolCategory.DESTRUCTIVE,
    "code_run": ToolCategory.EXECUTION,
    "code_lint": ToolCategory.READ_ONLY,
    "code_format": ToolCategory.WRITE,
    "code_test": ToolCategory.EXECUTION,
    "python": ToolCategory.EXECUTION,
    "git_commit": ToolCategory.WRITE,
    "git_push": ToolCategory.NETWORK,

    # --- Shadow tools ---
    "shell": ToolCategory.EXECUTION,
    "screenshot": ToolCategory.READ_ONLY,
    "clipboard_read": ToolCategory.READ_ONLY,
    "clipboard_write": ToolCategory.WRITE,
    "process_list": ToolCategory.READ_ONLY,
    "process_kill": ToolCategory.DESTRUCTIVE,
    "system_info": ToolCategory.READ_ONLY,
    "app_launch": ToolCategory.SYSTEM,
    "env_get": ToolCategory.READ_ONLY,
    "env_set": ToolCategory.SYSTEM,
    "datetime": ToolCategory.READ_ONLY,
    "calculator": ToolCategory.READ_ONLY,
    "web_search": ToolCategory.NETWORK,
    "web_fetch": ToolCategory.NETWORK,

    # --- Analyst tools ---
    "json_parse": ToolCategory.READ_ONLY,
    "csv_read": ToolCategory.READ_ONLY,
    "csv_write": ToolCategory.WRITE,
    "database_query": ToolCategory.EXECUTION,
    "api_call": ToolCategory.NETWORK,
    "hash_text": ToolCategory.READ_ONLY,
    "hash_file": ToolCategory.READ_ONLY,
    "pdf_read": ToolCategory.READ_ONLY,
    "pdf_info": ToolCategory.READ_ONLY,
    "docx_read": ToolCategory.READ_ONLY,
    "xlsx_read": ToolCategory.READ_ONLY,

    # --- Browser tools ---
    "browser_open": ToolCategory.BROWSER,
    "browser_click": ToolCategory.BROWSER,
    "browser_type": ToolCategory.BROWSER,
    "browser_screenshot": ToolCategory.READ_ONLY,
    "browser_scroll": ToolCategory.BROWSER,
    "browser_get_text": ToolCategory.READ_ONLY,
    "browser_close": ToolCategory.BROWSER,

    # --- Document tools ---
    "pdf_create": ToolCategory.DOCUMENT,
    "docx_create": ToolCategory.DOCUMENT,
    "xlsx_create": ToolCategory.DOCUMENT,
    "pptx_create": ToolCategory.DOCUMENT,

    # --- System tools ---
    "schedule_task": ToolCategory.SYSTEM,
    "schedule_list": ToolCategory.READ_ONLY,
    "schedule_cancel": ToolCategory.SYSTEM,
    "schedule_info": ToolCategory.READ_ONLY,
    "email_send": ToolCategory.NETWORK,
    "notify_send": ToolCategory.SYSTEM,

    # --- Memory tools ---
    "memory_recall": ToolCategory.READ_ONLY,
    "memory_list": ToolCategory.READ_ONLY,
    "memory_search": ToolCategory.READ_ONLY,
    "memory_store": ToolCategory.WRITE,
}


# ═══════════════════════════════════════════════════════════════════════════════
# PERMISSION OUTCOMES
# ═══════════════════════════════════════════════════════════════════════════════

class PermissionOutcome(Enum):
    """Result of evaluating a permission rule."""
    ALLOW = "allow"                  # Explicitly allowed
    DENY = "deny"                    # Hard blocked
    REVIEW_REQUIRED = "review"       # Needs human review (→ dry-run)
    RESTRICTED = "restricted"        # Allowed but with modified scope


@dataclass
class RuleMatch:
    """
    Result of matching a tool+args against permission rules.
    Contains the outcome plus metadata about which rule matched.
    """
    outcome: PermissionOutcome
    rule_id: str = ""
    reason: str = ""
    risk_override: Optional[str] = None     # Override risk level for dry-run
    modified_args: Optional[Dict] = None    # If RESTRICTED, modified args
    requires_classifier: bool = False       # Needs AI classifier review

    def to_dict(self) -> Dict:
        return {
            "outcome": self.outcome.value,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "risk_override": self.risk_override,
            "requires_classifier": self.requires_classifier,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PATH SANDBOX RULES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SandboxConfig:
    """
    Path-based sandbox configuration.
    Controls which directories tools can access.
    """
    # Directories where write operations are allowed
    allowed_write_paths: List[str] = field(default_factory=list)

    # Directories that are completely protected (no read or write)
    protected_paths: List[str] = field(default_factory=lambda: [
        "/etc/", "/var/log/", "/boot/", "/usr/", "/bin/", "/sbin/",
        "C:\\Windows\\", "C:\\Program Files\\",
        "C:\\Program Files (x86)\\",
    ])

    # Paths that require explicit approval for write
    restricted_paths: List[str] = field(default_factory=lambda: [
        "~/.ssh/", "~/.gnupg/", "~/.aws/",
        "/home/*/.ssh/", "/home/*/.gnupg/",
    ])

    # Whether to enforce sandbox (can be disabled for trusted environments)
    enabled: bool = True

    def is_path_allowed(self, path: str, is_write: bool = True) -> Tuple[bool, str]:
        """
        Check if a file path is within the sandbox.

        Returns: (allowed, reason)
        """
        if not self.enabled:
            return True, "Sandbox disabled"

        # Normalize path
        norm_path = os.path.normpath(os.path.expanduser(path))

        # Check protected paths (only for write operations)
        if is_write:
            for protected in self.protected_paths:
                prot_norm = os.path.normpath(os.path.expanduser(protected))
                if norm_path.startswith(prot_norm):
                    return False, f"Path is protected: {protected}"

        # For write operations, check allowed write paths
        if is_write and self.allowed_write_paths:
            in_allowed = False
            for allowed in self.allowed_write_paths:
                allowed_norm = os.path.normpath(os.path.expanduser(allowed))
                if norm_path.startswith(allowed_norm):
                    in_allowed = True
                    break
            if not in_allowed:
                return False, (
                    f"Write path not in allowed directories. "
                    f"Path: {norm_path}"
                )

        # Check restricted paths (needs review)
        for restricted in self.restricted_paths:
            # Support glob patterns
            if fnmatch.fnmatch(norm_path, restricted) or \
               norm_path.startswith(os.path.normpath(os.path.expanduser(
                   restricted.replace("*", "")))):
                if is_write:
                    return False, f"Restricted path (needs explicit approval): {restricted}"

        return True, "Path allowed"


# ═══════════════════════════════════════════════════════════════════════════════
# PERMISSION PROFILES
# ═══════════════════════════════════════════════════════════════════════════════

class PermissionProfile(Enum):
    """
    Predefined permission profiles that users can select.
    Each profile defines a default behavior for each tool category.
    """
    STRICT = "strict"          # Block everything except read-only; review all writes
    BALANCED = "balanced"      # Default: allow reads, review writes, block dangerous
    PERMISSIVE = "permissive"  # Allow most things, only block destructive+critical
    DEVELOPER = "developer"    # Like balanced but with wider write access
    UNRESTRICTED = "unrestricted"  # No permission checks (testing/dangerous)


# Profile defaults: tool_category → default PermissionOutcome
PROFILE_DEFAULTS: Dict[PermissionProfile, Dict[ToolCategory, PermissionOutcome]] = {
    PermissionProfile.STRICT: {
        ToolCategory.READ_ONLY: PermissionOutcome.ALLOW,
        ToolCategory.WRITE: PermissionOutcome.REVIEW_REQUIRED,
        ToolCategory.DESTRUCTIVE: PermissionOutcome.DENY,
        ToolCategory.NETWORK: PermissionOutcome.REVIEW_REQUIRED,
        ToolCategory.SYSTEM: PermissionOutcome.REVIEW_REQUIRED,
        ToolCategory.EXECUTION: PermissionOutcome.DENY,
        ToolCategory.BROWSER: PermissionOutcome.REVIEW_REQUIRED,
        ToolCategory.DOCUMENT: PermissionOutcome.REVIEW_REQUIRED,
    },
    PermissionProfile.BALANCED: {
        ToolCategory.READ_ONLY: PermissionOutcome.ALLOW,
        ToolCategory.WRITE: PermissionOutcome.REVIEW_REQUIRED,
        ToolCategory.DESTRUCTIVE: PermissionOutcome.REVIEW_REQUIRED,
        ToolCategory.NETWORK: PermissionOutcome.ALLOW,
        ToolCategory.SYSTEM: PermissionOutcome.REVIEW_REQUIRED,
        ToolCategory.EXECUTION: PermissionOutcome.REVIEW_REQUIRED,
        ToolCategory.BROWSER: PermissionOutcome.ALLOW,
        ToolCategory.DOCUMENT: PermissionOutcome.REVIEW_REQUIRED,
    },
    PermissionProfile.PERMISSIVE: {
        ToolCategory.READ_ONLY: PermissionOutcome.ALLOW,
        ToolCategory.WRITE: PermissionOutcome.ALLOW,
        ToolCategory.DESTRUCTIVE: PermissionOutcome.REVIEW_REQUIRED,
        ToolCategory.NETWORK: PermissionOutcome.ALLOW,
        ToolCategory.SYSTEM: PermissionOutcome.ALLOW,
        ToolCategory.EXECUTION: PermissionOutcome.REVIEW_REQUIRED,
        ToolCategory.BROWSER: PermissionOutcome.ALLOW,
        ToolCategory.DOCUMENT: PermissionOutcome.ALLOW,
    },
    PermissionProfile.DEVELOPER: {
        ToolCategory.READ_ONLY: PermissionOutcome.ALLOW,
        ToolCategory.WRITE: PermissionOutcome.ALLOW,
        ToolCategory.DESTRUCTIVE: PermissionOutcome.REVIEW_REQUIRED,
        ToolCategory.NETWORK: PermissionOutcome.ALLOW,
        ToolCategory.SYSTEM: PermissionOutcome.ALLOW,
        ToolCategory.EXECUTION: PermissionOutcome.ALLOW,
        ToolCategory.BROWSER: PermissionOutcome.ALLOW,
        ToolCategory.DOCUMENT: PermissionOutcome.ALLOW,
    },
    PermissionProfile.UNRESTRICTED: {
        ToolCategory.READ_ONLY: PermissionOutcome.ALLOW,
        ToolCategory.WRITE: PermissionOutcome.ALLOW,
        ToolCategory.DESTRUCTIVE: PermissionOutcome.ALLOW,
        ToolCategory.NETWORK: PermissionOutcome.ALLOW,
        ToolCategory.SYSTEM: PermissionOutcome.ALLOW,
        ToolCategory.EXECUTION: PermissionOutcome.ALLOW,
        ToolCategory.BROWSER: PermissionOutcome.ALLOW,
        ToolCategory.DOCUMENT: PermissionOutcome.ALLOW,
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# ARGUMENT PATTERN RULES (predefined denylist patterns)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ArgPatternRule:
    """
    A rule that matches specific argument patterns for a tool.
    If the pattern matches, the rule's outcome is applied.
    """
    rule_id: str
    tool_name: str
    arg_pattern: str              # Regex pattern to match against args JSON
    outcome: PermissionOutcome
    reason: str
    risk_override: Optional[str] = None


# Hard denylist: patterns that are ALWAYS blocked regardless of profile
HARD_DENYLIST: List[ArgPatternRule] = [
    ArgPatternRule(
        rule_id="deny_rm_rf_root",
        tool_name="shell",
        arg_pattern=r"rm\s+(-\w*\s+)?(/|~)",
        outcome=PermissionOutcome.DENY,
        reason="rm on root/home directory is always blocked",
        risk_override="critical",
    ),
    ArgPatternRule(
        rule_id="deny_format_fs",
        tool_name="shell",
        arg_pattern=r"(mkfs|format)[\s.]",
        outcome=PermissionOutcome.DENY,
        reason="Filesystem format is always blocked",
        risk_override="critical",
    ),
    ArgPatternRule(
        rule_id="deny_fork_bomb",
        tool_name="shell",
        arg_pattern=r":\(\)\s*\{.*\}",
        outcome=PermissionOutcome.DENY,
        reason="Fork bomb is always blocked",
        risk_override="critical",
    ),
    ArgPatternRule(
        rule_id="deny_device_write",
        tool_name="shell",
        arg_pattern=r">\s*/dev/(sd|nvme|loop)",
        outcome=PermissionOutcome.DENY,
        reason="Direct device write is always blocked",
        risk_override="critical",
    ),
    ArgPatternRule(
        rule_id="deny_shutdown",
        tool_name="shell",
        arg_pattern=r"(shutdown|reboot|halt|poweroff)\s",
        outcome=PermissionOutcome.DENY,
        reason="System shutdown/reboot is always blocked",
        risk_override="critical",
    ),
    ArgPatternRule(
        rule_id="deny_ssh_key_overwrite",
        tool_name="write_file",
        arg_pattern=r"[~\\\/]\.ssh\/",
        outcome=PermissionOutcome.DENY,
        reason="SSH key directory is protected",
        risk_override="critical",
    ),
    ArgPatternRule(
        rule_id="deny_credential_files",
        tool_name="write_file",
        arg_pattern=r"\.(env|pem|key|p12|pfx|jks)[\"']",
        outcome=PermissionOutcome.DENY,
        reason="Credential files are protected from overwrite",
        risk_override="critical",
    ),
    ArgPatternRule(
        rule_id="deny_dd_disk",
        tool_name="shell",
        arg_pattern=r"dd\s+if=.*of=/dev/",
        outcome=PermissionOutcome.DENY,
        reason="dd to device is always blocked",
        risk_override="critical",
    ),
    ArgPatternRule(
        rule_id="deny_chmod_777",
        tool_name="shell",
        arg_pattern=r"chmod\s+(-\w*\s+)?777",
        outcome=PermissionOutcome.DENY,
        reason="chmod 777 is always blocked",
        risk_override="high",
    ),
    ArgPatternRule(
        rule_id="deny_kill_system",
        tool_name="shell",
        arg_pattern=r"kill\s+(-\w*\s+)?1\b",
        outcome=PermissionOutcome.DENY,
        reason="kill -1 (init) is always blocked",
        risk_override="critical",
    ),
]

# Escalation rules: patterns that elevate risk but don't block
ESCALATION_RULES: List[ArgPatternRule] = [
    ArgPatternRule(
        rule_id="escalate_sudo",
        tool_name="shell",
        arg_pattern=r"sudo\s",
        outcome=PermissionOutcome.REVIEW_REQUIRED,
        reason="sudo commands require elevated review",
        risk_override="critical",
    ),
    ArgPatternRule(
        rule_id="escalate_pip_install",
        tool_name="shell",
        arg_pattern=r"pip\s+(install|uninstall)",
        outcome=PermissionOutcome.REVIEW_REQUIRED,
        reason="Package installation requires review",
        risk_override="high",
    ),
    ArgPatternRule(
        rule_id="escalate_apt",
        tool_name="shell",
        arg_pattern=r"(apt|yum|dnf|brew)\s+(install|remove|update)",
        outcome=PermissionOutcome.REVIEW_REQUIRED,
        reason="System package manager requires review",
        risk_override="high",
    ),
    ArgPatternRule(
        rule_id="escalate_git_push",
        tool_name="git_push",
        arg_pattern=r".*",
        outcome=PermissionOutcome.REVIEW_REQUIRED,
        reason="Git push requires review",
        risk_override="high",
    ),
    ArgPatternRule(
        rule_id="escalate_network_exec",
        tool_name="code_run",
        arg_pattern=r"(requests|urllib|httpx|aiohttp)\.",
        outcome=PermissionOutcome.REVIEW_REQUIRED,
        reason="Code execution with network access requires review",
        risk_override="high",
    ),
    ArgPatternRule(
        rule_id="escalate_email",
        tool_name="email_send",
        arg_pattern=r".*",
        outcome=PermissionOutcome.REVIEW_REQUIRED,
        reason="Email sending requires review",
        risk_override="high",
    ),
    ArgPatternRule(
        rule_id="escalate_process_kill",
        tool_name="process_kill",
        arg_pattern=r".*",
        outcome=PermissionOutcome.REVIEW_REQUIRED,
        reason="Process termination requires review",
        risk_override="high",
    ),
    ArgPatternRule(
        rule_id="escalate_database_write",
        tool_name="database_query",
        arg_pattern=r"(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\s",
        outcome=PermissionOutcome.REVIEW_REQUIRED,
        reason="Database write operations require review",
        risk_override="high",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# RULE ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class RuleEngine:
    """
    Evaluates tool+args against the full rule set.

    Evaluation order (first match wins for DENY, otherwise best match):
    1. Hard denylist → immediate DENY
    2. Path sandbox → DENY or ALLOW
    3. Escalation rules → REVIEW_REQUIRED with risk override
    4. Tool category → profile default
    5. User overrides → custom rules

    Usage:
        engine = RuleEngine(profile=PermissionProfile.BALANCED)
        match = engine.evaluate("shell", {"command": "ls -la"})
        if match.outcome == PermissionOutcome.DENY:
            # Block execution
        elif match.outcome == PermissionOutcome.REVIEW_REQUIRED:
            # Send to dry-run
    """

    def __init__(
        self,
        profile: PermissionProfile = PermissionProfile.BALANCED,
        sandbox: Optional[SandboxConfig] = None,
        custom_allowlist: Optional[Set[str]] = None,
        custom_denylist: Optional[Set[str]] = None,
    ):
        self.profile = profile
        self.sandbox = sandbox or SandboxConfig()
        self.custom_allowlist = custom_allowlist or set()
        self.custom_denylist = custom_denylist or set()

        self._deny_rules = HARD_DENYLIST.copy()
        self._escalation_rules = ESCALATION_RULES.copy()
        self._custom_rules: List[ArgPatternRule] = []

        logger.info(
            f"[RuleEngine] Initialized: profile={profile.value}, "
            f"sandbox={'enabled' if self.sandbox.enabled else 'disabled'}"
        )

    def add_custom_rule(self, rule: ArgPatternRule):
        """Add a custom rule (evaluated before profile defaults)."""
        self._custom_rules.append(rule)
        logger.debug(f"[RuleEngine] Added custom rule: {rule.rule_id}")

    def evaluate(
        self,
        tool_name: str,
        tool_args: Dict,
        worker_id: str = "",
    ) -> RuleMatch:
        """
        Evaluate a tool+args against all rules.

        Args:
            tool_name: Name of the tool being called
            tool_args: Arguments for the tool
            worker_id: ID of the worker calling the tool

        Returns:
            RuleMatch with the outcome and metadata
        """
        args_json = str(tool_args).lower()

        # Step 1: Hard denylist (always checked, regardless of profile)
        for rule in self._deny_rules:
            if rule.tool_name == tool_name:
                if re.search(rule.arg_pattern, args_json, re.IGNORECASE):
                    logger.warning(
                        f"[RuleEngine] HARD DENY: {rule.rule_id} "
                        f"for {tool_name}: {rule.reason}"
                    )
                    return RuleMatch(
                        outcome=PermissionOutcome.DENY,
                        rule_id=rule.rule_id,
                        reason=rule.reason,
                        risk_override=rule.risk_override,
                    )

        # Step 2: Custom denylist
        if tool_name in self.custom_denylist:
            return RuleMatch(
                outcome=PermissionOutcome.DENY,
                rule_id="custom_denylist",
                reason=f"Tool '{tool_name}' is in user denylist",
            )

        # Step 3: Custom allowlist (overrides everything except hard deny)
        if tool_name in self.custom_allowlist:
            return RuleMatch(
                outcome=PermissionOutcome.ALLOW,
                rule_id="custom_allowlist",
                reason=f"Tool '{tool_name}' is in user allowlist",
            )

        # Step 4: Path sandbox check (for file operations)
        path = self._extract_path(tool_name, tool_args)
        if path:
            is_write = tool_name in (
                "write_file", "append_file", "delete_file", "create_directory"
            )
            allowed, reason = self.sandbox.is_path_allowed(path, is_write)
            if not allowed:
                return RuleMatch(
                    outcome=PermissionOutcome.DENY,
                    rule_id="sandbox",
                    reason=reason,
                    risk_override="high",
                )

        # Step 5: Escalation rules
        for rule in self._escalation_rules:
            if rule.tool_name == tool_name:
                if re.search(rule.arg_pattern, args_json, re.IGNORECASE):
                    return RuleMatch(
                        outcome=rule.outcome,
                        rule_id=rule.rule_id,
                        reason=rule.reason,
                        risk_override=rule.risk_override,
                        requires_classifier=True,
                    )

        # Step 6: Custom rules
        for rule in self._custom_rules:
            if rule.tool_name == tool_name:
                if re.search(rule.arg_pattern, args_json, re.IGNORECASE):
                    return RuleMatch(
                        outcome=rule.outcome,
                        rule_id=rule.rule_id,
                        reason=rule.reason,
                        risk_override=rule.risk_override,
                    )

        # Step 7: Profile defaults (based on tool category)
        category = TOOL_CATEGORIES.get(tool_name, ToolCategory.EXECUTION)
        profile_defaults = PROFILE_DEFAULTS.get(self.profile, {})
        default_outcome = profile_defaults.get(
            category, PermissionOutcome.REVIEW_REQUIRED
        )

        return RuleMatch(
            outcome=default_outcome,
            rule_id=f"profile_{self.profile.value}",
            reason=f"Default {self.profile.value} profile for {category.value}",
        )

    def _extract_path(self, tool_name: str, tool_args: Dict) -> Optional[str]:
        """Extract file path from tool arguments."""
        path_keys = ["path", "file", "filepath", "file_path", "filename"]
        for key in path_keys:
            if key in tool_args and isinstance(tool_args[key], str):
                return tool_args[key]

        # For shell commands, try to extract path from common patterns
        if tool_name == "shell":
            cmd = tool_args.get("command", "")
            # Match patterns like "cat /path/to/file" or "> /path/to/file"
            path_match = re.search(r'(?:<|>)?\s*(/\S+|~?\S+\.\w+)', cmd)
            if path_match:
                return path_match.group(1)

        return None

    def get_tool_category(self, tool_name: str) -> ToolCategory:
        """Get the category for a tool."""
        return TOOL_CATEGORIES.get(tool_name, ToolCategory.EXECUTION)

    def list_rules(self) -> Dict:
        """List all active rules for display."""
        return {
            "profile": self.profile.value,
            "hard_deny_rules": len(self._deny_rules),
            "escalation_rules": len(self._escalation_rules),
            "custom_rules": len(self._custom_rules),
            "custom_allowlist": list(self.custom_allowlist),
            "custom_denylist": list(self.custom_denylist),
            "sandbox_enabled": self.sandbox.enabled,
            "sandbox_protected": self.sandbox.protected_paths,
            "sandbox_allowed_writes": self.sandbox.allowed_write_paths,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_rule_engine(
    profile: str = "balanced",
    allowed_paths: Optional[List[str]] = None,
) -> RuleEngine:
    """
    Create a RuleEngine with common defaults.

    Args:
        profile: Permission profile name (strict/balanced/permissive/developer)
        allowed_paths: Directories where write operations are allowed
    """
    sandbox = SandboxConfig()
    if allowed_paths:
        sandbox.allowed_write_paths = [
            os.path.normpath(os.path.expanduser(p)) for p in allowed_paths
        ]

    return RuleEngine(
        profile=PermissionProfile(profile),
        sandbox=sandbox,
    )


__all__ = [
    "ToolCategory",
    "TOOL_CATEGORIES",
    "PermissionOutcome",
    "RuleMatch",
    "SandboxConfig",
    "PermissionProfile",
    "PROFILE_DEFAULTS",
    "ArgPatternRule",
    "HARD_DENYLIST",
    "ESCALATION_RULES",
    "RuleEngine",
    "create_rule_engine",
]
