"""EAA Agent Tools - Fixed version with better timeout handling"""

import os
import sys
import json
import re
import subprocess
import shutil
import glob as glob_module
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import traceback
import threading

try:
    from duckduckgo_search import DDGS
    HAS_DUCKDUCKGO = True
except ImportError:
    HAS_DUCKDUCKGO = False

@dataclass
class ToolResult:
    success: bool
    output: str
    error: Optional[str] = None
    def to_dict(self): return {"success": self.success, "output": self.output, "error": self.error}

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, callable] = {}
        self._descriptions: Dict[str, str] = {}
    def register(self, name: str, func: callable, description: str = ""):
        self._tools[name] = func
        self._descriptions[name] = description
    def execute(self, name: str, **kwargs) -> ToolResult:
        if name not in self._tools:
            return ToolResult(False, "", f"Unknown tool: {name}")
        try:
            return self._tools[name](**kwargs)
        except Exception as e:
            return ToolResult(False, "", str(e))
    def get_all_descriptions(self) -> str:
        return "\n".join([f"- {n}: {d}" for n, d in self._descriptions.items()])
    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

def tool_read_file(path: str, offset: int = 0, limit: int = 2000) -> ToolResult:
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path): return ToolResult(False, "", f"File not found: {path}")
        with open(path, "r", encoding="utf-8", errors="replace") as f: lines = f.readlines()
        start, end = max(0, offset), min(len(lines), offset + limit) if limit > 0 else len(lines)
        output = "".join([f"{i:6}\t{line}" for i, line in enumerate(lines[start:end], start + 1)])
        if len(lines) > end: output += f"\n... ({len(lines) - end} more lines)"
        return ToolResult(True, output)
    except Exception as e: return ToolResult(False, "", str(e))

def tool_write_file(path: str, content: str) -> ToolResult:
    try:
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f: f.write(content)
        return ToolResult(True, f"Wrote {content.count(chr(10)) + 1} lines to {path}")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_append_file(path: str, content: str) -> ToolResult:
    try:
        path = os.path.expanduser(path)
        with open(path, "a", encoding="utf-8") as f: f.write(content)
        return ToolResult(True, f"Appended to {path}")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_list_files(path: str = ".") -> ToolResult:
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path): return ToolResult(False, "", f"Directory not found: {path}")
        entries = [f"DIR  {e}/" if os.path.isdir(os.path.join(path, e)) else f"FILE {e} ({os.path.getsize(os.path.join(path, e))} bytes)" for e in sorted(os.listdir(path))]
        return ToolResult(True, "\n".join(entries))
    except Exception as e: return ToolResult(False, "", str(e))

def tool_file_exists(path: str) -> ToolResult:
    path = os.path.expanduser(path)
    exists = os.path.exists(path)
    return ToolResult(True, f"File exists: {path} ({os.path.getsize(path)} bytes)" if exists else f"File not found: {path}")

def tool_create_directory(path: str) -> ToolResult:
    try:
        os.makedirs(os.path.expanduser(path), exist_ok=True)
        return ToolResult(True, f"Created directory: {path}")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_delete_file(path: str) -> ToolResult:
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path): return ToolResult(False, "", f"Path not found: {path}")
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        return ToolResult(True, f"Deleted: {path}")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_glob(pattern: str, path: str = ".") -> ToolResult:
    try:
        path = os.path.expanduser(path)
        matches = glob_module.glob(os.path.join(path, "**", pattern), recursive=True)
        return ToolResult(True, "\n".join([m.replace(path + os.sep, "") for m in matches[:100]]) or "No matches")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_grep(pattern: str, path: str = ".") -> ToolResult:
    try:
        path, regex, results = os.path.expanduser(path), re.compile(pattern, re.IGNORECASE), []
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in ["node_modules", ".git", "__pycache__", "venv"]]
            for f in files:
                if f.endswith((".py", ".js", ".ts", ".json", ".md", ".txt")):
                    try:
                        with open(os.path.join(root, f), "r", errors="ignore") as file:
                            for i, line in enumerate(file, 1):
                                if regex.search(line): results.append(f"{f}:{i}: {line.strip()[:100]}")
                    except: pass
        return ToolResult(True, "\n".join(results[:50]) or "No matches")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_shell(command: str, timeout: int = 30) -> ToolResult:
    """Execute shell command with proper timeout - FIXED VERSION"""
    # Blocked dangerous commands
    for blocked in ["rm -rf /", "rm -rf ~", "mkfs", "dd if=", ":(){:|:&};:", "format"]:
        if blocked in command.lower():
            return ToolResult(False, "", "Blocked dangerous command")
    
    try:
        # Use subprocess with timeout
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd()
        )
        
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        
        # Truncate very long output
        if len(output) > 5000:
            output = output[:5000] + "\n...[output truncated]"
        
        if result.returncode != 0:
            return ToolResult(False, output, f"Exit code: {result.returncode}")
        
        return ToolResult(True, output)
        
    except subprocess.TimeoutExpired:
        return ToolResult(False, "", f"Command timed out after {timeout} seconds. Try a shorter command or increase timeout.")
    except Exception as e:
        return ToolResult(False, "", f"Error: {str(e)}")

def tool_web_search(query: str, num_results: int = 5) -> ToolResult:
    if not HAS_DUCKDUCKGO: return ToolResult(False, "", "Install: pip install duckduckgo-search")
    try:
        with DDGS() as ddgs:
            results = [f"- {r.get('title', '')}\n  {r.get('href', '')}\n  {r.get('body', '')[:200]}" for r in ddgs.text(query, max_results=num_results)]
        return ToolResult(True, "\n\n".join(results))
    except Exception as e: return ToolResult(False, "", str(e))

def tool_web_fetch(url: str) -> ToolResult:
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = re.sub(r"<[^>]+>", " ", resp.read().decode("utf-8", errors="replace"))
            return ToolResult(True, re.sub(r"\s+", " ", content).strip()[:10000])
    except Exception as e: return ToolResult(False, "", str(e))

MEMORY_FILE = "eaa_agent_memory.json"
def tool_memory_save(key: str, value: str) -> ToolResult:
    try:
        mem = json.load(open(MEMORY_FILE)) if os.path.exists(MEMORY_FILE) else {}
        mem[key] = {"value": value, "timestamp": datetime.now().isoformat()}
        json.dump(mem, open(MEMORY_FILE, "w"), indent=2)
        return ToolResult(True, f"Saved: {key}")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_memory_recall(key: str = None) -> ToolResult:
    try:
        mem = json.load(open(MEMORY_FILE)) if os.path.exists(MEMORY_FILE) else {}
        if key: return ToolResult(True, f"{key}: {mem.get(key, {}).get('value', 'Not found')}")
        return ToolResult(True, json.dumps(mem, indent=2))
    except Exception as e: return ToolResult(False, "", str(e))

def tool_memory_list() -> ToolResult:
    try:
        mem = json.load(open(MEMORY_FILE)) if os.path.exists(MEMORY_FILE) else {}
        return ToolResult(True, f"Keys ({len(mem)}):\n" + "\n".join(mem.keys()))
    except Exception as e: return ToolResult(False, "", str(e))

def tool_datetime() -> ToolResult:
    now = datetime.now()
    return ToolResult(True, f"Date/Time: {now.strftime('%Y-%m-%d %H:%M:%S')}\nDay: {now.strftime('%A')}")

def tool_calculator(expression: str) -> ToolResult:
    try:
        if not all(c in "0123456789+-*/.() " for c in expression): return ToolResult(False, "", "Invalid chars")
        return ToolResult(True, f"{expression} = {eval(expression)}")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_python(code: str) -> ToolResult:
    try:
        ns = {"__builtins__": __builtins__, "json": json, "os": os}
        exec(code, ns)
        return ToolResult(True, str(ns.get("result", "Done")))
    except Exception as e: return ToolResult(False, "", str(e))

def create_tool_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register("read_file", tool_read_file, "Read file. Args: path")
    r.register("write_file", tool_write_file, "Write file. Args: path, content")
    r.register("append_file", tool_append_file, "Append to file. Args: path, content")
    r.register("list_files", tool_list_files, "List directory. Args: path")
    r.register("file_exists", tool_file_exists, "Check file. Args: path")
    r.register("create_directory", tool_create_directory, "Create dir. Args: path")
    r.register("delete_file", tool_delete_file, "Delete. Args: path")
    r.register("glob", tool_glob, "Find files. Args: pattern, path")
    r.register("grep", tool_grep, "Search text. Args: pattern, path")
    r.register("shell", tool_shell, "Run command. Args: command, timeout (default 30)")
    r.register("web_search", tool_web_search, "Search web. Args: query")
    r.register("web_fetch", tool_web_fetch, "Fetch URL. Args: url")
    r.register("memory_save", tool_memory_save, "Save memory. Args: key, value")
    r.register("memory_recall", tool_memory_recall, "Recall memory. Args: key")
    r.register("memory_list", tool_memory_list, "List memory keys")
    r.register("datetime", tool_datetime, "Get date/time")
    r.register("calculator", tool_calculator, "Do math. Args: expression")
    r.register("python", tool_python, "Run Python. Args: code")
    return r

__all__ = ["ToolResult", "ToolRegistry", "create_tool_registry"]
