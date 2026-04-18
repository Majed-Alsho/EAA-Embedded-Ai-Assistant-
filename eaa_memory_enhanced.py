"""
EAA Advanced Memory Tools - Phase 7
Enhanced memory with search, export/import, and conversation context.
All tools use the existing ToolResult pattern from eaa_agent_tools.py.
"""

import os
import json
import re
import shutil
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
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

# Memory storage location
MEMORY_DIR = os.path.join(os.path.dirname(__file__), "..", "EAA_Data", "memory")
MEMORY_FILE = os.path.join(MEMORY_DIR, "memory.json")
CONTEXT_DIR = os.path.join(MEMORY_DIR, "contexts")


def _ensure_dirs():
    """Ensure memory directories exist."""
    os.makedirs(MEMORY_DIR, exist_ok=True)
    os.makedirs(CONTEXT_DIR, exist_ok=True)


def _load_memory() -> Dict:
    """Load memory from file."""
    _ensure_dirs()
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_memory(mem: Dict):
    """Save memory to file."""
    _ensure_dirs()
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mem, f, indent=2, ensure_ascii=False)


# ─── MEMORY SEARCH ────────────────────────────────────────────────────────────
def tool_memory_search(query: str, case_sensitive: bool = False) -> ToolResult:
    """Search memory by content (keys and values)."""
    try:
        mem = _load_memory()
        if not mem:
            return ToolResult(True, "[Memory is empty]")

        query = query.lower() if not case_sensitive else query
        results = []

        for key, entry in mem.items():
            key_match = (query in key.lower()) if not case_sensitive else (query in key)
            value = entry.get("value", "") if isinstance(entry, dict) else str(entry)
            value_match = (query in value.lower()) if not case_sensitive else (query in value)

            if key_match or value_match:
                ts = entry.get("timestamp", "unknown") if isinstance(entry, dict) else "unknown"
                preview = value[:200] + "..." if len(value) > 200 else value
                results.append(f"[{ts}] {key}: {preview}")

        if not results:
            return ToolResult(True, f"No matches for '{query}' in memory")

        return ToolResult(True, f"Found {len(results)} matches for '{query}':\n\n" + "\n".join(results))

    except Exception as e:
        return ToolResult(False, "", f"Memory search failed: {str(e)}")


# ─── MEMORY CLEAR ─────────────────────────────────────────────────────────────
def tool_memory_clear(confirm: str = "yes") -> ToolResult:
    """Clear all memory. Requires confirm='yes'."""
    try:
        if confirm != "yes":
            return ToolResult(False, "", "Memory clear requires confirm='yes' parameter for safety")

        # Backup first
        if os.path.exists(MEMORY_FILE):
            backup_path = MEMORY_FILE + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(MEMORY_FILE, backup_path)

        mem = _load_memory()
        count = len(mem)
        _save_memory({})
        return ToolResult(True, f"Cleared {count} memory entries.\nBackup saved to: {backup_path}")

    except Exception as e:
        return ToolResult(False, "", f"Memory clear failed: {str(e)}")


# ─── MEMORY EXPORT ────────────────────────────────────────────────────────────
def tool_memory_export(file_path: str = None, format: str = "json") -> ToolResult:
    """Export memory to a file."""
    try:
        mem = _load_memory()
        if not mem:
            return ToolResult(True, "[Memory is empty, nothing to export]")

        if file_path is None:
            file_path = os.path.join(
                os.path.dirname(__file__), "..", "outputs",
                f"memory_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{format}"
            )

        file_path = os.path.expanduser(file_path)
        os.makedirs(os.path.dirname(file_path) if os.path.dirname(file_path) else ".", exist_ok=True)

        if format == "json":
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(mem, f, indent=2, ensure_ascii=False)
        elif format == "txt":
            with open(file_path, "w", encoding="utf-8") as f:
                for key, entry in mem.items():
                    ts = entry.get("timestamp", "") if isinstance(entry, dict) else ""
                    val = entry.get("value", entry) if isinstance(entry, dict) else entry
                    f.write(f"[{ts}] {key}:\n{val}\n{'='*50}\n")
        else:
            return ToolResult(False, "", f"Unsupported format: {format}. Use 'json' or 'txt'")

        return ToolResult(True, f"Exported {len(mem)} entries to: {file_path}")

    except Exception as e:
        return ToolResult(False, "", f"Memory export failed: {str(e)}")


# ─── MEMORY IMPORT ────────────────────────────────────────────────────────────
def tool_memory_import(file_path: str, merge: bool = True) -> ToolResult:
    """Import memory from a JSON file."""
    try:
        file_path = os.path.expanduser(file_path)
        if not os.path.exists(file_path):
            return ToolResult(False, "", f"File not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            imported = json.load(f)

        if not isinstance(imported, dict):
            return ToolResult(False, "", "Import file must be a JSON object/dict")

        mem = _load_memory() if merge else {}

        # Add imported entries with timestamp
        for key, value in imported.items():
            if isinstance(value, dict) and "value" in value:
                mem[key] = value
            else:
                mem[key] = {"value": str(value), "timestamp": datetime.now().isoformat(), "imported": True}

        _save_memory(mem)
        return ToolResult(True, f"Imported {len(imported)} entries (total: {len(mem)})\nMerge: {merge}")

    except Exception as e:
        return ToolResult(False, "", f"Memory import failed: {str(e)}")


# ─── MEMORY STATS ─────────────────────────────────────────────────────────────
def tool_memory_stats() -> ToolResult:
    """Get memory statistics."""
    try:
        mem = _load_memory()
        total_entries = len(mem)

        if not mem:
            return ToolResult(True, "Memory is empty")

        total_size = sum(len(json.dumps(v, ensure_ascii=False)) for v in mem.values())
        keys = list(mem.keys())

        # Most recent entries
        recent = sorted(mem.items(), key=lambda x: x[1].get("timestamp", "") if isinstance(x[1], dict) else "", reverse=True)[:5]

        stats = {
            "total_entries": total_entries,
            "total_size_bytes": total_size,
            "total_size_kb": f"{total_size / 1024:.1f}",
            "keys": keys,
        }

        output = json.dumps(stats, indent=2)
        output += "\n\nMost Recent Entries:"
        for key, entry in recent:
            ts = entry.get("timestamp", "unknown") if isinstance(entry, dict) else "unknown"
            output += f"\n  [{ts}] {key}"

        return ToolResult(True, output)

    except Exception as e:
        return ToolResult(False, "", f"Memory stats failed: {str(e)}")


# ─── CONTEXT SAVE ─────────────────────────────────────────────────────────────
def tool_context_save(name: str, messages: str = None) -> ToolResult:
    """
    Save a conversation context for later use.
    messages: JSON array of message objects, e.g. '[{"role": "user", "content": "..."}, ...]'
    """
    try:
        _ensure_dirs()

        context = {
            "name": name,
            "saved_at": datetime.now().isoformat(),
            "messages": json.loads(messages) if isinstance(messages, str) else messages or [],
        }

        context_path = os.path.join(CONTEXT_DIR, f"{name}.json")
        with open(context_path, "w", encoding="utf-8") as f:
            json.dump(context, f, indent=2, ensure_ascii=False)

        msg_count = len(context["messages"])
        return ToolResult(True, f"Saved context '{name}' with {msg_count} messages")

    except Exception as e:
        return ToolResult(False, "", f"Context save failed: {str(e)}")


# ─── CONTEXT LOAD ─────────────────────────────────────────────────────────────
def tool_context_load(name: str) -> ToolResult:
    """Load a saved conversation context."""
    try:
        context_path = os.path.join(CONTEXT_DIR, f"{name}.json")
        if not os.path.exists(context_path):
            # List available contexts
            available = [f.replace(".json", "") for f in os.listdir(CONTEXT_DIR) if f.endswith(".json")] if os.path.exists(CONTEXT_DIR) else []
            return ToolResult(False, "", f"Context '{name}' not found.\nAvailable: {', '.join(available) or 'none'}")

        with open(context_path, "r", encoding="utf-8") as f:
            context = json.load(f)

        return ToolResult(True, json.dumps(context, indent=2, ensure_ascii=False))

    except Exception as e:
        return ToolResult(False, "", f"Context load failed: {str(e)}")


# ─── CONTEXT LIST ─────────────────────────────────────────────────────────────
def tool_context_list() -> ToolResult:
    """List all saved conversation contexts."""
    try:
        _ensure_dirs()
        contexts = []
        for f in sorted(os.listdir(CONTEXT_DIR)):
            if f.endswith(".json"):
                path = os.path.join(CONTEXT_DIR, f)
                with open(path, "r") as fp:
                    data = json.load(fp)
                contexts.append({
                    "name": data.get("name", f.replace(".json", "")),
                    "saved_at": data.get("saved_at", "unknown"),
                    "messages": len(data.get("messages", []))
                })

        if not contexts:
            return ToolResult(True, "No saved contexts")

        output = f"Saved Contexts ({len(contexts)}):\n"
        for ctx in contexts:
            output += f"\n  - {ctx['name']} ({ctx['messages']} msgs, saved: {ctx['saved_at'][:19]})"

        return ToolResult(True, output)

    except Exception as e:
        return ToolResult(False, "", f"Context list failed: {str(e)}")


# ─── CONTEXT DELETE ───────────────────────────────────────────────────────────
def tool_context_delete(name: str) -> ToolResult:
    """Delete a saved conversation context."""
    try:
        context_path = os.path.join(CONTEXT_DIR, f"{name}.json")
        if not os.path.exists(context_path):
            return ToolResult(False, "", f"Context '{name}' not found")

        os.remove(context_path)
        return ToolResult(True, f"Deleted context: {name}")

    except Exception as e:
        return ToolResult(False, "", f"Context delete failed: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

def register_memory_tools(registry) -> None:
    """Register all advanced memory tools with the existing ToolRegistry."""
    registry.register("memory_search", tool_memory_search, "Search memory content. Args: query, case_sensitive")
    registry.register("memory_clear", tool_memory_clear, "Clear all memory. Args: confirm='yes'")
    registry.register("memory_export", tool_memory_export, "Export memory to file. Args: file_path, format (json/txt)")
    registry.register("memory_import", tool_memory_import, "Import memory from file. Args: file_path, merge (default True)")
    registry.register("memory_stats", tool_memory_stats, "Get memory statistics. Args: none")
    registry.register("context_save", tool_context_save, "Save conversation context. Args: name, messages (JSON)")
    registry.register("context_load", tool_context_load, "Load saved context. Args: name")
    registry.register("context_list", tool_context_list, "List saved contexts. Args: none")
    registry.register("context_delete", tool_context_delete, "Delete saved context. Args: name")

__all__ = [
    "register_memory_tools",
    "tool_memory_search", "tool_memory_clear", "tool_memory_export", "tool_memory_import",
    "tool_memory_stats", "tool_context_save", "tool_context_load", "tool_context_list",
    "tool_context_delete",
]
