"""
EAA V4 - Two-Tier Router (Master/Worker Dynamic Routing)
==========================================================
The most fundamental change from Claude Code's architecture.

Claude Code assumes a single powerful model (Claude 3.5/4 Sonnet) that handles
everything: conversation, reasoning, tool selection, tool execution, error recovery.
On local hardware with 7B models and 8GB VRAM, this approach fails because the
model cannot hold all 112 tool schemas, conversation history, AND task context
simultaneously without degrading reasoning quality.

The Two-Tier Router separates concerns:
  - MASTER (Jarvis): Handles conversation, task planning, routing decisions.
    ONLY sees delegation tools — never sees actual tool schemas.
  - WORKERS (Qwen-Coder, Shadow, etc.): Specialized agents that wake up with
    a precise task description and only their relevant tool subset, execute,
    and return results. Then go back to sleep.

VRAM impact: Master prompt drops from ~10K tokens (112 tools) to ~1K tokens
(delegation interface only). Workers get ~2K tokens (10-15 relevant tools).
"""

import json
import re
import logging
import time
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTING DECISION TYPES
# ═══════════════════════════════════════════════════════════════════════════════

class RoutingDecision(Enum):
    MASTER_HANDLES = "master_handles"      # Simple response, no tools needed
    DELEGATE = "delegate"                  # Route to a specialized worker
    BATCH_DELEGATE = "batch_delegate"      # Multiple workers in sequence
    ESCALATE = "escalate"                  # Needs user intervention


@dataclass
class DelegationTask:
    """
    A single unit of work to be delegated from Master to Worker.
    This is the structured routing command that replaces raw tool calls.
    """
    task_id: str = ""                     # Unique task ID for tracking
    worker_id: str                          # Which worker to invoke
    tool_name: str                          # Which tool to use
    tool_args: Dict[str, Any]               # Tool parameters
    reason: str = ""                        # Why this delegation is needed
    priority: int = 0                       # Execution order (0 = first)
    timeout: int = 30                       # Max seconds for this task
    depends_on: List[str] = field(default_factory=list)  # Task IDs to wait for

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "reason": self.reason,
            "priority": self.priority,
            "timeout": self.timeout,
            "depends_on": self.depends_on,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "DelegationTask":
        return cls(
            task_id=data.get("task_id", ""),
            worker_id=data["worker_id"],
            tool_name=data["tool_name"],
            tool_args=data.get("tool_args", {}),
            reason=data.get("reason", ""),
            priority=data.get("priority", 0),
            timeout=data.get("timeout", 30),
            depends_on=data.get("depends_on", []),
        )


@dataclass
class RoutingResult:
    """
    Result of the Master's routing decision.
    Contains zero or more DelegationTasks to be executed.
    """
    decision: RoutingDecision
    tasks: List[DelegationTask] = field(default_factory=list)
    direct_response: Optional[str] = None   # If MASTER_HANDLES, the response
    confidence: float = 0.0                 # Routing confidence (0-1)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision.value,
            "tasks": [t.to_dict() for t in self.tasks],
            "direct_response": self.direct_response,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER REGISTRY — Maps tool categories to workers
# ═══════════════════════════════════════════════════════════════════════════════

# Default worker-to-category mappings.
# Workers are specialized: each one handles a subset of tools.
# This is the HMoE adaptation — instead of one giant model doing everything,
# smaller specialized models handle their domains.
DEFAULT_WORKER_SPECIALIZATIONS = {
    "jarvis": {
        "name": "Jarvis (Master)",
        "role": "conversation_planning",
        "description": "Handles conversation, task planning, and routing. Never directly executes tools.",
        "model_id": "qwen2.5-7b-instruct",
        "tools": [],  # Master NEVER holds tool schemas
        "delegation_tools": [
            "delegate_to_coder",
            "delegate_to_shadow",
            "delegate_to_analyst",
            "delegate_to_brows",  # short for browser
            "delegate_to_docs",
            "delegate_to_sys",
        ],
        "max_context_tokens": 2048,
    },
    "coder": {
        "name": "Qwen-Coder (Worker)",
        "role": "code_execution",
        "description": "Specialized in code generation, editing, execution, and git operations.",
        "model_id": "qwen2.5-coder-7b-instruct",
        "tools": [
            "read_file", "write_file", "append_file", "list_files", "file_exists",
            "create_directory", "delete_file", "glob", "grep",
            "code_run", "code_lint", "code_format", "code_test", "python",
            "git_status", "git_commit", "git_diff", "git_log", "git_branch",
        ],
        "max_context_tokens": 4096,
    },
    "shadow": {
        "name": "Shadow (Worker)",
        "role": "general_assistant",
        "description": "General-purpose worker for tasks not covered by specialists. Full tool access.",
        "model_id": "qwen2.5-7b-instruct",
        "tools": [
            "shell", "screenshot", "clipboard_read", "clipboard_write",
            "process_list", "process_kill", "system_info", "app_launch",
            "env_get", "env_set", "datetime", "calculator",
            "web_search", "web_fetch",
        ],
        "max_context_tokens": 4096,
    },
    "analyst": {
        "name": "Analyst (Worker)",
        "role": "data_analysis",
        "description": "Specialized in data processing, JSON/CSV manipulation, database queries.",
        "model_id": "qwen2.5-7b-instruct",
        "tools": [
            "json_parse", "csv_read", "csv_write", "database_query", "api_call",
            "hash_text", "hash_file", "calculator",
            "pdf_read", "pdf_info", "docx_read", "xlsx_read",
        ],
        "max_context_tokens": 4096,
    },
    "browser": {
        "name": "Browser (Worker)",
        "role": "web_automation",
        "description": "Handles browser automation: navigation, clicking, typing, scraping.",
        "model_id": "qwen2.5-7b-instruct",
        "tools": [
            "browser_open", "browser_click", "browser_type",
            "browser_screenshot", "browser_scroll", "browser_get_text", "browser_close",
            "web_search", "web_fetch",
        ],
        "max_context_tokens": 4096,
    },
    "docs": {
        "name": "Document (Worker)",
        "role": "document_creation",
        "description": "Specialized in creating and editing PDF, DOCX, XLSX, PPTX documents.",
        "model_id": "qwen2.5-7b-instruct",
        "tools": [
            "pdf_read", "pdf_info", "pdf_create",
            "docx_read", "docx_create",
            "xlsx_read", "xlsx_create",
            "pptx_read", "pptx_create",
        ],
        "max_context_tokens": 4096,
    },
    "sys": {
        "name": "System (Worker)",
        "role": "system_admin",
        "description": "System administration: process management, environment, scheduling.",
        "model_id": "qwen2.5-7b-instruct",
        "tools": [
            "shell", "process_list", "process_kill", "system_info",
            "app_launch", "env_get", "env_set", "datetime",
            "schedule_task", "schedule_list", "schedule_cancel", "schedule_info",
            "email_send", "notify_send",
        ],
        "max_context_tokens": 4096,
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL → WORKER MAPPING (reverse index for fast lookup)
# ═══════════════════════════════════════════════════════════════════════════════

def build_tool_to_worker_map(
    specializations: Optional[Dict] = None
) -> Dict[str, str]:
    """
    Build a reverse index: tool_name → worker_id.
    Used by the router to instantly know which worker handles a given tool.
    If multiple workers handle the same tool, the first one wins.
    """
    specs = specializations or DEFAULT_WORKER_SPECIALIZATIONS
    tool_to_worker: Dict[str, str] = {}

    for worker_id, config in specs.items():
        for tool_name in config.get("tools", []):
            if tool_name not in tool_to_worker:
                tool_to_worker[tool_name] = worker_id

    return tool_to_worker


# ═══════════════════════════════════════════════════════════════════════════════
# MASTER SYSTEM PROMPT — The delegation interface
# ═══════════════════════════════════════════════════════════════════════════════

MASTER_SYSTEM_PROMPT = """You are Jarvis, the Master Agent of EAA (Extensible AI Agent).

## Your Role
You are the coordinator. You NEVER execute tools directly. Instead, you PLAN and DELEGATE
tasks to specialized Workers. Each Worker is an expert in its domain and has access to
only the tools relevant to its specialty.

## Available Workers
{worker_list}

## How to Delegate
When you need to accomplish a task, output a JSON delegation block:

```json
{{
  "action": "delegate",
  "tasks": [
    {{
      "worker_id": "coder",
      "tool_name": "read_file",
      "tool_args": {{"path": "/path/to/file.py"}},
      "reason": "Need to read the source file before editing"
    }},
    {{
      "worker_id": "coder",
      "tool_name": "write_file",
      "tool_args": {{"path": "/path/to/file.py", "content": "..."}},
      "reason": "Applying the fix for the reported bug"
    }}
  ]
}}
```

## Batching Strategy
Group related operations into a single delegation block to minimize VRAM swaps.
For example, read_file + edit + test should be ONE delegation to the coder worker,
not three separate delegations.

## Simple Responses
If the user asks a question that doesn't require any tools (greetings, general knowledge,
clarification), respond directly without a delegation block.

## Error Handling
If a Worker fails, analyze the error and either:
1. Retry with corrected arguments
2. Delegate to a different Worker
3. Ask the user for guidance

## Task Completion
When all delegated tasks are complete, summarize what was accomplished.
"""

MASTER_CONVERSATION_PROMPT = """You are Jarvis, the Master Agent of EAA. A conversation is in progress.

## Current Context
User said: "{user_message}"

## Worker Results
{worker_results}

Respond to the user. If you need to take action, output a delegation block.
If the task is complete, summarize the results clearly.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER SYSTEM PROMPT TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════════

WORKER_SYSTEM_PROMPT_TEMPLATE = """You are {worker_name}, a specialized Worker Agent in the EAA system.

## Your Specialization: {role}
{description}

## Your Tools
{tool_list}

## How to Use Tools
Output a JSON block in this EXACT format:
```json
{{"tool": "tool_name", "args": {{"arg1": "value1"}}}}
```

## Important Rules
1. You were delegated a SPECIFIC task. Complete it efficiently.
2. Use only the tools listed above.
3. If a tool fails, explain what went wrong — do not retry endlessly.
4. When done, output your result clearly.
5. Keep responses concise — your output will be relayed to the Master.

## Task from Master
{task_description}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# KEYWORD-BASED ROUTING HEURISTICS
# ═══════════════════════════════════════════════════════════════════════════════

# Maps user intent keywords to preferred workers.
# Used by the fast heuristic router (no LLM call needed).
INTENT_KEYWORDS = {
    "coder": [
        "code", "python", "javascript", "typescript", "function", "class",
        "debug", "bug", "error", "compile", "build", "test", "lint",
        "git", "commit", "push", "pull", "branch", "merge", "repository",
        "edit file", "create file", "refactor", "implement",
        "write code", "fix code", "read code", "review code",
    ],
    "shadow": [
        "search", "find", "look up", "information", "help",
        "explain", "what is", "how to", "why does", "calculate",
        "screenshot", "system", "process", "clipboard",
    ],
    "analyst": [
        "data", "csv", "json", "database", "sql", "query",
        "analyze", "chart", "graph", "statistics", "parse",
        "pdf", "excel", "spreadsheet", "report", "invoice",
        "hash", "api", "convert",
    ],
    "browser": [
        "browse", "website", "url", "webpage", "click", "navigate",
        "scrape", "crawl", "fill form", "login", "open browser",
        "google", "search online", "fetch page",
    ],
    "docs": [
        "create pdf", "create document", "create spreadsheet",
        "create presentation", "docx", "xlsx", "pptx", "word",
        "powerpoint", "document", "report", "invoice",
    ],
    "sys": [
        "schedule", "timer", "alarm", "remind", "email", "send",
        "notify", "environment", "process", "service", "install",
        "kill process", "restart", "cron", "task",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ROUTER CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class MasterRouter:
    """
    The Two-Tier Router sits between the user and the tool execution layer.

    Flow:
    1. User sends message → MasterRouter receives it
    2. Router analyzes message → determines if Master can handle directly
       or if delegation to Worker(s) is needed
    3. If delegation: builds DelegationTask list, sends to DryRunProtocol
    4. After approval: executes tasks via WorkerManager (which handles VRAM)
    5. Worker results come back → Master synthesizes final response

    The Master never sees actual tool schemas. It only sees the delegation
    interface, keeping its context window tiny and its reasoning sharp.
    """

    def __init__(
        self,
        specializations: Optional[Dict] = None,
        tool_descriptions: Optional[Dict[str, str]] = None,
    ):
        self.specializations = specializations or DEFAULT_WORKER_SPECIALIZATIONS
        self.tool_descriptions = tool_descriptions or {}

        # Build reverse index
        self.tool_to_worker = build_tool_to_worker_map(self.specializations)

        # Stats
        self._total_routes = 0
        self._route_history: List[Dict] = []
        self._delegation_count = 0

        logger.info(
            f"[Router] Initialized: {len(self.specializations)} workers, "
            f"{len(self.tool_to_worker)} tool mappings"
        )

    def get_master_prompt(self) -> str:
        """
        Build the Master's system prompt with worker descriptions.
        This is the ONLY thing the Master sees besides conversation.
        No tool schemas — just delegation interface.
        """
        worker_lines = []
        for worker_id, config in self.specializations.items():
            if worker_id == "jarvis":
                continue  # Skip master itself
            tools_str = ", ".join(config["tools"][:5])
            if len(config["tools"]) > 5:
                tools_str += f" (+{len(config['tools']) - 5} more)"
            worker_lines.append(
                f"- **{worker_id}** ({config['name']}): {config['description']}\n"
                f"  Tools: {tools_str}"
            )

        return MASTER_SYSTEM_PROMPT.format(
            worker_list="\n".join(worker_lines)
        )

    def get_worker_prompt(
        self,
        worker_id: str,
        task_description: str,
        tool_descriptions: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Build a Worker's system prompt for a specific task.
        Only includes tools relevant to this worker's specialization.
        """
        config = self.specializations.get(worker_id)
        if not config:
            raise ValueError(f"Unknown worker: {worker_id}")

        descs = tool_descriptions or self.tool_descriptions
        tool_lines = []
        for tool_name in config["tools"]:
            desc = descs.get(tool_name, "No description available")
            tool_lines.append(f"- **{tool_name}**: {desc}")

        return WORKER_SYSTEM_PROMPT_TEMPLATE.format(
            worker_name=config["name"],
            role=config["role"],
            description=config["description"],
            tool_list="\n".join(tool_lines),
            task_description=task_description,
        )

    def route_heuristic(self, user_message: str) -> RoutingResult:
        """
        Fast keyword-based routing without LLM call.
        Used as a first pass — if confidence is high enough, skip LLM routing.

        Returns a RoutingResult with recommended worker(s) and confidence.
        """
        msg_lower = user_message.lower()

        # Score each worker by keyword matches
        worker_scores: Dict[str, int] = {}
        for worker_id, keywords in INTENT_KEYWORDS.items():
            if worker_id == "jarvis":
                continue
            score = sum(1 for kw in keywords if kw in msg_lower)
            if score > 0:
                worker_scores[worker_id] = score

        if not worker_scores:
            # No tool-related keywords found — Master handles directly
            return RoutingResult(
                decision=RoutingDecision.MASTER_HANDLES,
                confidence=0.9,
                metadata={"method": "heuristic", "reason": "no_tool_keywords"},
            )

        # Sort by score
        best_worker = max(worker_scores, key=worker_scores.get)
        best_score = worker_scores[best_worker]

        # Confidence based on how dominant the best match is
        total_score = sum(worker_scores.values())
        confidence = best_score / total_score if total_score > 0 else 0.5

        # High confidence single-worker delegation
        if confidence > 0.7 and best_score >= 2:
            return RoutingResult(
                decision=RoutingDecision.DELEGATE,
                confidence=confidence,
                metadata={
                    "method": "heuristic",
                    "primary_worker": best_worker,
                    "score": best_score,
                },
            )

        # Multiple workers needed (medium confidence)
        if len(worker_scores) > 1:
            sorted_workers = sorted(
                worker_scores, key=worker_scores.get, reverse=True
            )
            return RoutingResult(
                decision=RoutingDecision.BATCH_DELEGATE,
                confidence=confidence,
                metadata={
                    "method": "heuristic",
                    "workers": sorted_workers,
                    "scores": worker_scores,
                },
            )

        # Low confidence — need LLM routing
        return RoutingResult(
            decision=RoutingDecision.MASTER_HANDLES,
            confidence=confidence,
            metadata={
                "method": "heuristic_low_confidence",
                "suggested_worker": best_worker,
                "score": best_score,
            },
        )

    def parse_delegation(self, model_output: str) -> List[DelegationTask]:
        """
        Parse the Master's JSON delegation block from its output.
        The Master outputs a structured delegation block with one or more tasks.

        Supports:
        - JSON code blocks: ```json {...} ```
        - Inline JSON: {"action": "delegate", "tasks": [...]}
        - Multiple delegation blocks in one output
        """
        tasks = []

        # Try JSON code block format
        json_pattern = r'```json\s*(\{.*?\})\s*```'
        for match in re.finditer(json_pattern, model_output, re.DOTALL):
            try:
                data = json.loads(match.group(1))
                tasks.extend(self._extract_tasks(data))
            except json.JSONDecodeError:
                logger.warning(f"[Router] Failed to parse JSON block: {match.group(1)[:100]}")
                continue

        # Try inline JSON if no code blocks found
        if not tasks:
            inline_pattern = r'\{\s*"action"\s*:\s*"delegate".*?\}'
            for match in re.finditer(inline_pattern, model_output, re.DOTALL):
                try:
                    data = json.loads(match.group(0))
                    tasks.extend(self._extract_tasks(data))
                except json.JSONDecodeError:
                    continue

        # Try bare task list format: [{"worker_id": "...", "tool_name": "..."}]
        if not tasks:
            array_pattern = r'\[\s*\{.*?"worker_id".*?\}\s*\]'
            for match in re.finditer(array_pattern, model_output, re.DOTALL):
                try:
                    data = json.loads(match.group(0))
                    for item in data:
                        if "worker_id" in item and "tool_name" in item:
                            tasks.append(DelegationTask.from_dict(item))
                except json.JSONDecodeError:
                    continue

        self._delegation_count += len(tasks)
        return tasks

    def _extract_tasks(self, data: Dict) -> List[DelegationTask]:
        """Extract DelegationTasks from parsed JSON data."""
        tasks = []

        if data.get("action") == "delegate":
            for task_data in data.get("tasks", []):
                if "worker_id" in task_data and "tool_name" in task_data:
                    tasks.append(DelegationTask.from_dict(task_data))
                else:
                    logger.warning(
                        f"[Router] Malformed task: {json.dumps(task_data)[:100]}"
                    )
        return tasks

    def validate_tasks(self, tasks: List[DelegationTask]) -> Tuple[List[str], List[str]]:
        """
        Validate delegation tasks before execution.
        Returns: (valid_indices, errors)
        """
        errors = []
        valid_indices = []

        for i, task in enumerate(tasks):
            # Check worker exists
            if task.worker_id not in self.specializations:
                errors.append(f"Task {i}: Unknown worker '{task.worker_id}'")
                continue

            # Check tool is in worker's specialization
            config = self.specializations[task.worker_id]
            if task.tool_name not in config.get("tools", []):
                errors.append(
                    f"Task {i}: Tool '{task.tool_name}' not in "
                    f"'{task.worker_id}' worker's toolset"
                )
                continue

            # Check for dangerous patterns (basic pre-check)
            if task.tool_name == "shell":
                cmd = task.tool_args.get("command", "")
                if self._is_obviously_dangerous(cmd):
                    errors.append(
                        f"Task {i}: Shell command flagged as dangerous: {cmd[:80]}"
                    )

            valid_indices.append(str(i))

        return valid_indices, errors

    def _is_obviously_dangerous(self, command: str) -> bool:
        """
        Quick heuristic check for obviously dangerous shell commands.
        This is a first-pass filter — the full safety classifier
        runs later in the permission pipeline (Phase 1).
        """
        dangerous_patterns = [
            r"rm\s+(-\w*\s+)?/",       # rm / or rm -rf /
            r"mkfs",                     # format filesystem
            r"dd\s+if=",                 # disk dump
            r">\s*/dev/",               # write to device
            r"chmod\s+777",             # world-writable
            r"shutdown",                 # system shutdown
            r"reboot",                   # system reboot
            r":(){ :\|:& };:",          # fork bomb
        ]
        for pattern in dangerous_patterns:
            if re.search(pattern, command):
                return True
        return False

    def optimize_task_order(self, tasks: List[DelegationTask]) -> List[DelegationTask]:
        """
        Optimize task execution order to minimize VRAM swaps.
        Groups tasks by worker and sorts by priority.
        This is the "aggressive task batching" from the blueprint.
        """
        if not tasks:
            return []

        # Group by worker
        worker_groups: Dict[str, List[DelegationTask]] = {}
        for task in tasks:
            worker_groups.setdefault(task.worker_id, []).append(task)

        # Sort within each group by priority
        for worker_id in worker_groups:
            worker_groups[worker_id].sort(key=lambda t: t.priority)

        # Sort groups by total priority (highest first)
        sorted_workers = sorted(
            worker_groups.items(),
            key=lambda x: max(t.priority for t in x[1]),
            reverse=True,
        )

        # Flatten into ordered list
        optimized = []
        for worker_id, group_tasks in sorted_workers:
            optimized.extend(group_tasks)

        return optimized

    def get_stats(self) -> Dict:
        """Get routing statistics."""
        return {
            "total_routes": self._total_routes,
            "total_delegations": self._delegation_count,
            "workers_registered": len(self.specializations) - 1,  # exclude jarvis
            "tools_mapped": len(self.tool_to_worker),
            "recent_routes": self._route_history[-20:],
        }

    def record_route(self, result: RoutingResult):
        """Record a routing decision for analytics."""
        self._total_routes += 1
        self._route_history.append({
            "timestamp": time.time(),
            "decision": result.decision.value,
            "confidence": result.confidence,
            "task_count": len(result.tasks),
            "metadata": result.metadata,
        })
        # Keep last 200 routes
        if len(self._route_history) > 200:
            self._route_history = self._route_history[-200:]


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def create_router(
    specializations: Optional[Dict] = None,
    tool_descriptions: Optional[Dict[str, str]] = None,
) -> MasterRouter:
    """Create a MasterRouter with optional custom configuration."""
    return MasterRouter(
        specializations=specializations,
        tool_descriptions=tool_descriptions,
    )


def suggest_worker(message: str) -> str:
    """
    Quick single-function to get the best worker for a message.
    Useful for testing and debugging the router.
    """
    router = MasterRouter()
    result = router.route_heuristic(message)
    if result.metadata.get("primary_worker"):
        return result.metadata["primary_worker"]
    if result.metadata.get("suggested_worker"):
        return result.metadata["suggested_worker"]
    return "jarvis"


__all__ = [
    "MasterRouter",
    "DelegationTask",
    "RoutingResult",
    "RoutingDecision",
    "DEFAULT_WORKER_SPECIALIZATIONS",
    "build_tool_to_worker_map",
    "create_router",
    "suggest_worker",
]
