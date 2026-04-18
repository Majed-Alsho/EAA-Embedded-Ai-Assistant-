"""
EAA Enhanced Tool Executor - Smart execution with chaining, OpenAI format, history.
This is the master integration module that ties all tool modules together.
"""

import os
import sys
import json
import time
import traceback
import logging
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

# Import the base tools
try:
    from eaa_agent_tools import ToolResult, ToolRegistry, create_tool_registry
except ImportError:
    raise ImportError("eaa_agent_tools.py not found. This file must be in the same directory.")

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL CATEGORIES
# ═══════════════════════════════════════════════════════════════════════════════

TOOL_CATEGORIES = {
    "file": [
        "read_file",
        "write_file",
        "append_file",
        "list_files",
        "file_exists",
        "create_directory",
        "delete_file",
        "glob",
        "grep",
    ],
    "web": ["web_search", "web_fetch"],
    "memory": [
        "memory_save",
        "memory_recall",
        "memory_list",
        "memory_search",
        "memory_clear",
        "memory_export",
        "memory_import",
        "memory_stats",
    ],
    "code": [
        "code_run",
        "code_lint",
        "code_format",
        "code_test",
        "python",
        "git_status",
        "git_commit",
        "git_diff",
        "git_log",
        "git_branch",
    ],
    "document": [
        "pdf_read",
        "pdf_info",
        "pdf_create",
        "docx_read",
        "docx_create",
        "xlsx_read",
        "xlsx_create",
        "pptx_read",
        "pptx_create",
    ],
    "system": [
        "shell",
        "screenshot",
        "clipboard_read",
        "clipboard_write",
        "process_list",
        "process_kill",
        "system_info",
        "app_launch",
        "env_get",
        "env_set",
        "datetime",
        "calculator",
    ],
    "multimodal": [
        "image_analyze",
        "image_describe",
        "ocr_extract",
        "image_generate",
        "image_info",
        "image_convert",
        "image_resize",
    ],
    "browser": [
        "browser_open",
        "browser_click",
        "browser_type",
        "browser_screenshot",
        "browser_scroll",
        "browser_get_text",
        "browser_close",
    ],
    "communication": ["email_send", "notify_send", "sms_send"],
    "data": [
        "json_parse",
        "csv_read",
        "csv_write",
        "database_query",
        "api_call",
        "hash_text",
        "hash_file",
    ],
    "audio_video": [
        "audio_transcribe",
        "audio_generate",
        "audio_info",
        "audio_convert",
        "video_analyze",
        "video_info",
    ],
    "scheduler": ["schedule_task", "schedule_list", "schedule_cancel", "schedule_info"],
    "context": ["context_save", "context_load", "context_list", "context_delete"],
}


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTION HISTORY
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ToolExecution:
    """Record of a single tool execution."""

    tool_name: str
    arguments: Dict[str, Any]
    success: bool
    output: str
    error: Optional[str] = None
    duration_ms: float = 0
    timestamp: str = ""
    category: str = ""

    def to_dict(self):
        return asdict(self)


class ExecutionHistory:
    """Tracks all tool executions."""

    def __init__(self, max_entries: int = 1000):
        self._entries: List[ToolExecution] = []
        self.max_entries = max_entries

    def add(self, entry: ToolExecution):
        entry.timestamp = datetime.now().isoformat()
        self._entries.append(entry)
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries :]

    def get_recent(self, count: int = 10) -> List[Dict]:
        return [e.to_dict() for e in self._entries[-count:]]

    def get_by_tool(self, tool_name: str) -> List[Dict]:
        return [e.to_dict() for e in self._entries if e.tool_name == tool_name]

    def get_by_category(self, category: str) -> List[Dict]:
        return [e.to_dict() for e in self._entries if e.category == category]

    def stats(self) -> Dict:
        total = len(self._entries)
        success = sum(1 for e in self._entries if e.success)
        tools_used = set(e.tool_name for e in self._entries)
        return {
            "total_executions": total,
            "successful": success,
            "failed": total - success,
            "success_rate": f"{(success / total * 100):.1f}%" if total > 0 else "N/A",
            "unique_tools_used": len(tools_used),
            "tools": sorted(list(tools_used)),
        }

    def clear(self):
        self._entries.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL CHAIN EXECUTOR
# ═══════════════════════════════════════════════════════════════════════════════


class ToolChainExecutor:
    """
    Execute multiple tools in sequence, with output referencing between steps.
    Use $result_N.field to reference output from previous steps.
    """

    def __init__(self, registry: ToolRegistry, history: ExecutionHistory = None):
        self.registry = registry
        self.history = history or ExecutionHistory()

    def execute_chain(self, steps: List[Dict]) -> List[Dict]:
        """
        Execute a chain of tool calls.
        steps: [{"tool": "web_search", "args": {"query": "AI news"}}, {"tool": "web_fetch", "args": {"url": "$result_0"}}]
        """
        results = []

        for i, step in enumerate(steps):
            tool_name = step.get("tool")
            args = dict(step.get("args", {}))

            # Replace $result_N references
            args = self._resolve_references(args, results)

            # Execute
            start_time = time.time()
            result = self.registry.execute(tool_name, **args)
            duration = (time.time() - start_time) * 1000

            # Record
            execution = ToolExecution(
                tool_name=tool_name,
                arguments=args,
                success=result.success,
                output=result.output,
                error=result.error,
                duration_ms=duration,
                category=self._get_category(tool_name),
            )
            self.history.add(execution)

            result_dict = {
                "step": i,
                "tool": tool_name,
                "success": result.success,
                "output": result.output[:500] if result.success else None,
                "error": result.error,
                "duration_ms": round(duration, 1),
            }
            results.append(result_dict)

        return results

    def _resolve_references(self, args: Dict, results: List[Dict]) -> Dict:
        """Replace $result_N references with actual values."""
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str) and value.startswith("$result_"):
                parts = value.split(".")
                idx = int(parts[0].split("_")[1])
                if idx < len(results):
                    ref = results[idx]
                    if len(parts) > 1:
                        field = parts[1]
                        resolved[key] = ref.get(field, value)
                    else:
                        resolved[key] = ref.get("output", value)
                else:
                    resolved[key] = value
            else:
                resolved[key] = value
        return resolved

    def _get_category(self, tool_name: str) -> str:
        for cat, tools in TOOL_CATEGORIES.items():
            if tool_name in tools:
                return cat
        return "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# OPENAI FUNCTION CALLING FORMAT
# ═══════════════════════════════════════════════════════════════════════════════


def get_tools_for_llm(registry: ToolRegistry) -> List[Dict]:
    """
    Get tools in OpenAI function calling format.
    Compatible with OpenAI, Claude, and other LLMs.
    Extracts parameter info from function signatures automatically.
    """
    import inspect

    TYPE_MAP = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
        List: "array",
        Dict: "object",
        Optional: "string",
        Any: "string",
    }

    tools = []
    all_tools = registry.list_tools()
    descriptions = registry._descriptions

    for tool_name in all_tools:
        desc = descriptions.get(tool_name, "")
        func = registry._tools.get(tool_name)

        properties = {}
        required = []

        if func:
            try:
                sig = inspect.signature(func)
                for param_name, param in sig.parameters.items():
                    if param_name in ("self", "kwargs"):
                        continue
                    param_type = "string"
                    if param.annotation != inspect.Parameter.empty:
                        for py_type, json_type in TYPE_MAP.items():
                            if param.annotation == py_type or (
                                hasattr(param.annotation, "__origin__")
                                and param.annotation.__origin__ == py_type
                            ):
                                param_type = json_type
                                break
                        else:
                            param_type = str(param.annotation).replace("typing.", "")
                    properties[param_name] = {"type": param_type}
                    if param.default == inspect.Parameter.empty:
                        required.append(param_name)
            except (ValueError, TypeError):
                pass

        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": desc,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
        )

    return tools


def get_tools_prompt(registry: ToolRegistry) -> str:
    """Get all tools formatted as a system prompt for the LLM brain."""
    all_tools = registry.list_tools()
    descriptions = registry._descriptions

    lines = ["## Available Tools\n"]
    for tool_name in all_tools:
        desc = descriptions.get(tool_name, "No description")
        category = "unknown"
        for cat, tools in TOOL_CATEGORIES.items():
            if tool_name in tools:
                category = cat
                break
        lines.append(f"- **{tool_name}** [{category}]: {desc}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# MASTER REGISTRY CREATOR
# ═══════════════════════════════════════════════════════════════════════════════


def create_enhanced_registry() -> ToolRegistry:
    """
    Create the enhanced tool registry with ALL tools from all modules.
    This is the main entry point - import and call this function.
    Returns: (ToolRegistry, ExecutionHistory, ToolChainExecutor)
    """
    # Start with base tools
    registry = create_tool_registry()
    history = ExecutionHistory()

    # Import and register module tools
    module_imports = [
        ("eaa_multimodal_tools", "register_multimodal_tools"),
        ("eaa_document_tools", "register_document_tools"),
        ("eaa_system_tools", "register_system_tools"),
        ("eaa_code_tools", "register_code_tools"),
        ("eaa_browser_tools", "register_browser_tools"),
        ("eaa_communication_tools", "register_communication_tools"),
        ("eaa_memory_enhanced", "register_memory_tools"),
        ("eaa_data_tools", "register_data_tools"),
        ("eaa_audio_video_tools", "register_audio_video_tools"),
        ("eaa_scheduler_tools", "register_scheduler_tools"),
        ("eaa_agent_tools_advanced", "register_advanced_tools"),
    ]

    loaded = []
    failed = []

    for module_name, func_name in module_imports:
        try:
            module = __import__(module_name, fromlist=[func_name])
            register_func = getattr(module, func_name)
            register_func(registry)
            loaded.append(module_name)
        except ImportError as e:
            failed.append(f"{module_name}: {e}")
        except Exception as e:
            failed.append(f"{module_name}: {e}")

    # Wrap registry.execute to track history
    original_execute = registry.execute

    def tracked_execute(tool_name: str, **kwargs) -> ToolResult:
        """Execute tool with history tracking. Bypasses ToolRegistry.execute to avoid 'name' param collision."""
        start_time = time.time()
        # Call the tool function directly from registry._tools to avoid
        # name collision with ToolRegistry.execute(self, name, **kwargs)
        func = registry._tools.get(tool_name)
        if func is None:
            result = ToolResult(False, "", f"Unknown tool: {tool_name}")
        else:
            try:
                result = func(**kwargs)
            except Exception as e:
                result = ToolResult(False, "", str(e))
        duration = (time.time() - start_time) * 1000
        category = "unknown"
        for cat, tools in TOOL_CATEGORIES.items():
            if tool_name in tools:
                category = cat
                break
        history.add(
            ToolExecution(
                tool_name=tool_name,
                arguments=kwargs,
                success=result.success,
                output=result.output,
                error=result.error,
                duration_ms=round(duration, 1),
                category=category,
            )
        )
        return result

    registry.execute = tracked_execute

    # Create chain executor
    chain_executor = ToolChainExecutor(registry, history)

    # Print summary
    all_tools = registry.list_tools()
    print(f"[EAA Enhanced Tools] Loaded {len(all_tools)} tools from {len(loaded)} modules")
    if failed:
        print(f"[EAA Enhanced Tools] Failed modules: {failed}")
    print(f"[EAA Enhanced Tools] Modules: {', '.join(loaded)}")
    print(f"[EAA Enhanced Tools] Tools: {', '.join(all_tools)}")

    return registry, history, chain_executor


__all__ = [
    "create_enhanced_registry",
    "ToolChainExecutor",
    "ExecutionHistory",
    "ToolExecution",
    "get_tools_for_llm",
    "get_tools_prompt",
    "TOOL_CATEGORIES",
]
