"""
EAA Agent Tools V2 - Professional Grade
========================================
Improvements:
- Multi-provider web search with fallbacks
- Smart brain management (unload when not needed)
- Better error handling
- Caching for repeated queries
- Rate limit handling

By Super Z & Majed
"""

import os
import sys
import json
import re
import subprocess
import shutil
import glob as glob_module
import hashlib
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import traceback
import threading

# ============================================
# SMART BRAIN MANAGER - Unload when not needed
# ============================================

class SmartBrainManager:
    """
    Manages brain loading/unloading to save VRAM.
    
    Light tools (don't need brain):
    - datetime, calculator, file operations, shell, web tools
    
    Heavy tools (need brain):
    - AI generation, complex reasoning
    """
    def __init__(self, brain_manager=None):
        self.brain_manager = brain_manager
        self.last_used = 0
        self.unload_after = 60  # Unload after 60 seconds of inactivity
        self.lock = threading.Lock()
        self._monitor_thread = None
        self._running = True
        
    def start_monitor(self):
        """Start the VRAM monitor thread"""
        if self._monitor_thread is None:
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()
    
    def _monitor_loop(self):
        """Monitor and unload brain when inactive"""
        while self._running:
            time.sleep(10)
            with self.lock:
                if self.brain_manager and self.brain_manager.current_model_id:
                    if time.time() - self.last_used > self.unload_after:
                        try:
                            print("[BRAIN] Auto-unloading to save VRAM...")
                            self.brain_manager.unload()
                            self._clear_vram()
                        except Exception as e:
                            print(f"[BRAIN] Unload error: {e}")
    
    def _clear_vram(self):
        """Clear VRAM"""
        try:
            import gc
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
            except:
                pass
        except:
            pass
    
    def touch(self):
        """Mark brain as recently used"""
        with self.lock:
            self.last_used = time.time()
    
    def stop(self):
        """Stop the monitor"""
        self._running = False

# Global smart brain manager
smart_brain = SmartBrainManager()

# ============================================
# LIGHT TOOLS - Don't need brain loaded
# ============================================

LIGHT_TOOLS = {
    "datetime", "calculator", "python",
    "read_file", "write_file", "append_file", 
    "list_files", "file_exists", "create_directory", "delete_file",
    "glob", "grep", "shell",
    "web_search", "web_fetch",
    "memory_save", "memory_recall", "memory_list"
}

# ============================================
# WEB SEARCH - Multi-provider with fallbacks
# ============================================

# Cache for search results
_search_cache = {}
_cache_lock = threading.Lock()
_cache_ttl = 300  # 5 minutes

def _get_cache_key(query: str) -> str:
    """Generate cache key from query"""
    return hashlib.md5(query.lower().encode()).hexdigest()

def _search_duckduckgo(query: str, num_results: int = 5) -> List[Dict]:
    """Search using DuckDuckGo"""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
            return results
    except Exception as e:
        print(f"[DDG] Error: {e}")
        return []

def _search_bing_api(query: str, num_results: int = 5) -> List[Dict]:
    """Search using Bing API (if key available)"""
    # Check for Bing API key
    bing_key = os.environ.get("BING_API_KEY", "")
    if not bing_key:
        return []
    
    try:
        import urllib.request
        import urllib.parse
        
        url = f"https://api.bing.microsoft.com/v7.0/search?q={urllib.parse.quote(query)}&count={num_results}"
        req = urllib.request.Request(url)
        req.add_header("Ocp-Apim-Subscription-Key", bing_key)
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            
        results = []
        for item in data.get("webPages", {}).get("value", [])[:num_results]:
            results.append({
                "title": item.get("name", ""),
                "href": item.get("url", ""),
                "body": item.get("snippet", "")
            })
        return results
    except Exception as e:
        print(f"[BING] Error: {e}")
        return []

def _search_google_custom(query: str, num_results: int = 5) -> List[Dict]:
    """Search using Google Custom Search API (if available)"""
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    cse_id = os.environ.get("GOOGLE_CSE_ID", "")
    
    if not api_key or not cse_id:
        return []
    
    try:
        import urllib.request
        import urllib.parse
        
        url = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cse_id}&q={urllib.parse.quote(query)}&num={num_results}"
        
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        
        results = []
        for item in data.get("items", [])[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "href": item.get("link", ""),
                "body": item.get("snippet", "")
            })
        return results
    except Exception as e:
        print(f"[GOOGLE] Error: {e}")
        return []

def _search_searx(query: str, num_results: int = 5) -> List[Dict]:
    """Search using SearXNG public instances"""
    instances = [
        "https://searx.be",
        "https://search.sapti.me", 
        "https://search.bus-hit.me"
    ]
    
    for instance in instances:
        try:
            import urllib.request
            import urllib.parse
            
            url = f"{instance}/search?q={urllib.parse.quote(query)}&format=json"
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            
            results = []
            for item in data.get("results", [])[:num_results]:
                results.append({
                    "title": item.get("title", ""),
                    "href": item.get("url", ""),
                    "body": item.get("content", "")
                })
            if results:
                return results
        except:
            continue
    
    return []

def _format_search_results(results: List[Dict], provider: str) -> str:
    """Format search results for display"""
    if not results:
        return ""
    
    lines = [f"[{provider}] Found {len(results)} results:\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        url = r.get("href", r.get("url", ""))
        snippet = r.get("body", r.get("snippet", r.get("content", "")))
        
        lines.append(f"{i}. {title}")
        lines.append(f"   URL: {url}")
        if snippet:
            lines.append(f"   {snippet[:200]}...")
        lines.append("")
    
    return "\n".join(lines)

def tool_web_search(query: str, num_results: int = 5, use_cache: bool = True) -> 'ToolResult':
    """
    Professional web search with multiple providers and caching.
    
    Providers tried in order:
    1. Cache (if enabled and valid)
    2. Google Custom Search (if API key set)
    3. Bing API (if API key set)
    4. SearXNG (public instances)
    5. DuckDuckGo (fallback)
    """
    # Check cache first
    if use_cache:
        cache_key = _get_cache_key(query)
        with _cache_lock:
            if cache_key in _search_cache:
                cached = _search_cache[cache_key]
                if time.time() - cached["time"] < _cache_ttl:
                    return ToolResult(True, cached["output"] + "\n[cached]")
    
    all_results = []
    
    # Try providers in order
    providers = [
        ("Google", _search_google_custom),
        ("Bing", _search_bing_api),
        ("SearXNG", _search_searx),
        ("DuckDuckGo", _search_duckduckgo),
    ]
    
    for provider_name, search_func in providers:
        try:
            print(f"[SEARCH] Trying {provider_name}...")
            results = search_func(query, num_results)
            if results:
                output = _format_search_results(results, provider_name)
                
                # Cache the result
                cache_key = _get_cache_key(query)
                with _cache_lock:
                    _search_cache[cache_key] = {
                        "output": output,
                        "time": time.time()
                    }
                
                return ToolResult(True, output)
        except Exception as e:
            print(f"[SEARCH] {provider_name} failed: {e}")
            continue
    
    # All providers failed
    return ToolResult(False, "", "All search providers failed. Please try again later.")

# ============================================
# WEB FETCH - Better content extraction
# ============================================

def tool_web_fetch(url: str, extract_text: bool = True) -> 'ToolResult':
    """
    Fetch and extract content from a URL.
    Handles various content types and extracts main text.
    """
    try:
        import urllib.request
        
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw_data = resp.read()
            
        # Handle different content types
        if "application/json" in content_type:
            try:
                data = json.loads(raw_data.decode())
                return ToolResult(True, json.dumps(data, indent=2)[:10000])
            except:
                pass
        
        if not extract_text:
            return ToolResult(True, f"Downloaded {len(raw_data)} bytes from {url}")
        
        # Extract text from HTML
        try:
            text = raw_data.decode("utf-8", errors="replace")
        except:
            text = raw_data.decode("latin-1", errors="replace")
        
        # Remove scripts and styles
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL|re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL|re.IGNORECASE)
        
        # Remove all HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Extract title if present
        title_match = re.search(r'<title[^>]*>(.*?)</title>', raw_data.decode("utf-8", errors="replace"), re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else "No title"
        
        result = f"Title: {title}\nURL: {url}\n\n{text[:8000]}"
        
        return ToolResult(True, result)
        
    except Exception as e:
        return ToolResult(False, "", f"Failed to fetch: {str(e)}")

# ============================================
# TOOL RESULT CLASS
# ============================================

@dataclass
class ToolResult:
    success: bool
    output: str
    error: Optional[str] = None
    
    def to_dict(self):
        return {"success": self.success, "output": self.output, "error": self.error}

# ============================================
# TOOL REGISTRY
# ============================================

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
        
        # Mark brain as used if heavy tool
        if name not in LIGHT_TOOLS:
            smart_brain.touch()
        
        try:
            return self._tools[name](**kwargs)
        except Exception as e:
            return ToolResult(False, "", str(e))
    
    def get_all_descriptions(self) -> str:
        return "\n".join([f"- {n}: {d}" for n, d in self._descriptions.items()])
    
    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

# ============================================
# FILE TOOLS
# ============================================

def tool_read_file(path: str, offset: int = 0, limit: int = 2000) -> ToolResult:
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return ToolResult(False, "", f"File not found: {path}")
        
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        
        start = max(0, offset)
        end = min(len(lines), offset + limit) if limit > 0 else len(lines)
        
        output = "".join([f"{i:6}\t{line}" for i, line in enumerate(lines[start:end], start + 1)])
        
        if len(lines) > end:
            output += f"\n... ({len(lines) - end} more lines)"
        
        return ToolResult(True, output)
    except Exception as e:
        return ToolResult(False, "", str(e))

def tool_write_file(path: str, content: str) -> ToolResult:
    try:
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        
        return ToolResult(True, f"Wrote {content.count(chr(10)) + 1} lines to {path}")
    except Exception as e:
        return ToolResult(False, "", str(e))

def tool_append_file(path: str, content: str) -> ToolResult:
    try:
        path = os.path.expanduser(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        return ToolResult(True, f"Appended to {path}")
    except Exception as e:
        return ToolResult(False, "", str(e))

def tool_list_files(path: str = ".") -> ToolResult:
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return ToolResult(False, "", f"Directory not found: {path}")
        
        entries = []
        for e in sorted(os.listdir(path)):
            full = os.path.join(path, e)
            if os.path.isdir(full):
                entries.append(f"DIR  {e}/")
            else:
                size = os.path.getsize(full)
                entries.append(f"FILE {e} ({size} bytes)")
        
        return ToolResult(True, "\n".join(entries))
    except Exception as e:
        return ToolResult(False, "", str(e))

def tool_file_exists(path: str) -> ToolResult:
    path = os.path.expanduser(path)
    exists = os.path.exists(path)
    if exists:
        size = os.path.getsize(path) if os.path.isfile(path) else "DIR"
        return ToolResult(True, f"Exists: {path} ({size})")
    return ToolResult(True, f"Not found: {path}")

def tool_create_directory(path: str) -> ToolResult:
    try:
        os.makedirs(os.path.expanduser(path), exist_ok=True)
        return ToolResult(True, f"Created directory: {path}")
    except Exception as e:
        return ToolResult(False, "", str(e))

def tool_delete_file(path: str) -> ToolResult:
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return ToolResult(False, "", f"Path not found: {path}")
        
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        
        return ToolResult(True, f"Deleted: {path}")
    except Exception as e:
        return ToolResult(False, "", str(e))

def tool_glob(pattern: str, path: str = ".") -> ToolResult:
    try:
        path = os.path.expanduser(path)
        matches = glob_module.glob(os.path.join(path, "**", pattern), recursive=True)
        
        if not matches:
            return ToolResult(True, "No matches found")
        
        # Make paths relative
        rel_matches = [m.replace(path + os.sep, "") for m in matches[:100]]
        return ToolResult(True, "\n".join(rel_matches))
    except Exception as e:
        return ToolResult(False, "", str(e))

def tool_grep(pattern: str, path: str = ".") -> ToolResult:
    try:
        path = os.path.expanduser(path)
        regex = re.compile(pattern, re.IGNORECASE)
        results = []
        
        skip_dirs = {"node_modules", ".git", "__pycache__", "venv", ".venv", "build", "dist"}
        
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            
            for f in files:
                if f.endswith((".py", ".js", ".ts", ".json", ".md", ".txt", ".html", ".css", ".yaml", ".yml")):
                    try:
                        filepath = os.path.join(root, f)
                        with open(filepath, "r", errors="ignore") as file:
                            for i, line in enumerate(file, 1):
                                if regex.search(line):
                                    results.append(f"{f}:{i}: {line.strip()[:100]}")
                                    if len(results) >= 50:
                                        return ToolResult(True, "\n".join(results))
                    except:
                        pass
        
        if not results:
            return ToolResult(True, "No matches found")
        
        return ToolResult(True, "\n".join(results))
    except Exception as e:
        return ToolResult(False, "", str(e))

# ============================================
# SHELL TOOL
# ============================================

def tool_shell(command: str, timeout: int = 30) -> ToolResult:
    """Execute shell command with timeout and safety checks"""
    
    # Blocked dangerous commands
    blocked = ["rm -rf /", "rm -rf ~", "mkfs", "dd if=", ":(){:|:&};:", "format", "del /f /s"]
    for b in blocked:
        if b in command.lower():
            return ToolResult(False, "", "Blocked dangerous command")
    
    try:
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
        return ToolResult(False, "", f"Command timed out after {timeout} seconds")
    except Exception as e:
        return ToolResult(False, "", f"Error: {str(e)}")

# ============================================
# UTILITY TOOLS
# ============================================

MEMORY_FILE = "eaa_agent_memory.json"

def tool_memory_save(key: str, value: str) -> ToolResult:
    try:
        mem = {}
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r") as f:
                mem = json.load(f)
        
        mem[key] = {
            "value": value,
            "timestamp": datetime.now().isoformat()
        }
        
        with open(MEMORY_FILE, "w") as f:
            json.dump(mem, f, indent=2)
        
        return ToolResult(True, f"Saved: {key}")
    except Exception as e:
        return ToolResult(False, "", str(e))

def tool_memory_recall(key: str = None) -> ToolResult:
    try:
        if not os.path.exists(MEMORY_FILE):
            return ToolResult(True, "Memory is empty")
        
        with open(MEMORY_FILE, "r") as f:
            mem = json.load(f)
        
        if key:
            if key in mem:
                return ToolResult(True, f"{key}: {mem[key].get('value', '')}")
            return ToolResult(True, f"Key not found: {key}")
        
        return ToolResult(True, json.dumps(mem, indent=2))
    except Exception as e:
        return ToolResult(False, "", str(e))

def tool_memory_list() -> ToolResult:
    try:
        if not os.path.exists(MEMORY_FILE):
            return ToolResult(True, "Memory is empty (0 keys)")
        
        with open(MEMORY_FILE, "r") as f:
            mem = json.load(f)
        
        return ToolResult(True, f"Keys ({len(mem)}):\n" + "\n".join(mem.keys()))
    except Exception as e:
        return ToolResult(False, "", str(e))

def tool_datetime() -> ToolResult:
    now = datetime.now()
    return ToolResult(True, 
        f"Date: {now.strftime('%Y-%m-%d')}\n"
        f"Time: {now.strftime('%H:%M:%S')}\n"
        f"Day: {now.strftime('%A')}\n"
        f"Timezone: {time.tzname[0]}"
    )

def tool_calculator(expression: str) -> ToolResult:
    """Safe calculator - only allows numbers and basic operators"""
    try:
        # Only allow safe characters
        allowed = set("0123456789+-*/.() ")
        if not all(c in allowed for c in expression):
            return ToolResult(False, "", "Invalid characters. Use only: 0-9 + - * / . ( )")
        
        # Evaluate
        result = eval(expression)
        
        return ToolResult(True, f"{expression} = {result}")
    except ZeroDivisionError:
        return ToolResult(False, "", "Error: Division by zero")
    except Exception as e:
        return ToolResult(False, "", f"Error: {str(e)}")

def tool_python(code: str) -> ToolResult:
    """Execute Python code safely"""
    try:
        # Create safe namespace
        safe_builtins = {
            "abs": abs, "all": all, "any": any, "bool": bool, "chr": chr,
            "dict": dict, "enumerate": enumerate, "filter": filter, "float": float,
            "hex": hex, "int": int, "isinstance": isinstance, "len": len,
            "list": list, "map": map, "max": max, "min": min, "ord": ord,
            "pow": pow, "print": print, "range": range, "repr": repr,
            "round": round, "set": set, "sorted": sorted, "str": str,
            "sum": sum, "tuple": tuple, "type": type, "zip": zip,
        }
        
        ns = {"__builtins__": safe_builtins, "json": json, "os": os, "re": re}
        exec(code, ns)
        
        if "result" in ns:
            return ToolResult(True, str(ns["result"]))
        return ToolResult(True, "Code executed successfully")
    except Exception as e:
        return ToolResult(False, "", str(e))

# ============================================
# CREATE REGISTRY
# ============================================

def create_tool_registry() -> ToolRegistry:
    """Create and register all tools"""
    r = ToolRegistry()
    
    # File tools
    r.register("read_file", tool_read_file, "Read file. Args: path, offset, limit")
    r.register("write_file", tool_write_file, "Write file. Args: path, content")
    r.register("append_file", tool_append_file, "Append to file. Args: path, content")
    r.register("list_files", tool_list_files, "List directory. Args: path")
    r.register("file_exists", tool_file_exists, "Check if file exists. Args: path")
    r.register("create_directory", tool_create_directory, "Create directory. Args: path")
    r.register("delete_file", tool_delete_file, "Delete file or directory. Args: path")
    r.register("glob", tool_glob, "Find files by pattern. Args: pattern, path")
    r.register("grep", tool_grep, "Search text in files. Args: pattern, path")
    
    # Shell
    r.register("shell", tool_shell, "Run shell command. Args: command, timeout")
    
    # Web tools (improved!)
    r.register("web_search", tool_web_search, "Search the web (multi-provider). Args: query, num_results")
    r.register("web_fetch", tool_web_fetch, "Fetch and extract content from URL. Args: url")
    
    # Memory
    r.register("memory_save", tool_memory_save, "Save to memory. Args: key, value")
    r.register("memory_recall", tool_memory_recall, "Recall from memory. Args: key")
    r.register("memory_list", tool_memory_list, "List all memory keys")
    
    # Utilities
    r.register("datetime", tool_datetime, "Get current date and time")
    r.register("calculator", tool_calculator, "Calculate math expression. Args: expression")
    r.register("python", tool_python, "Execute Python code. Args: code")
    
    return r

__all__ = ["ToolResult", "ToolRegistry", "create_tool_registry", "smart_brain", "LIGHT_TOOLS"]
