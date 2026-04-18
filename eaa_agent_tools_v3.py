"""
EAA Agent Tools V3 - PROFESSIONAL GRADE
=======================================
All 18 tools polished to perfection with:
- Better error handling & recovery
- Retry logic for flaky operations
- Result caching for performance
- Smart validation
- PRO-level web search with multi-provider
"""

import os
import sys
import json
import re
import subprocess
import shutil
import glob as glob_module
import time
import hashlib
import threading
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
import traceback
import logging

logger = logging.getLogger(__name__)

# ============================================
# RESULT CLASS
# ============================================

@dataclass
class ToolResult:
    """Standardized tool result"""
    success: bool
    output: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata
        }
    
    def __str__(self) -> str:
        if self.success:
            return f"✅ {self.output}"
        return f"❌ {self.error}"

# ============================================
# CACHING SYSTEM
# ============================================

class ResultCache:
    """Simple in-memory cache for tool results"""
    def __init__(self, max_size: int = 100, ttl_seconds: int = 300):
        self.cache: Dict[str, tuple] = {}
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
    
    def _hash(self, key: str) -> str:
        return hashlib.md5(key.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            h = self._hash(key)
            if h in self.cache:
                value, timestamp = self.cache[h]
                if time.time() - timestamp < self.ttl:
                    return value
                del self.cache[h]
        return None
    
    def set(self, key: str, value: Any):
        with self._lock:
            if len(self.cache) >= self.max_size:
                # Remove oldest
                oldest = min(self.cache.items(), key=lambda x: x[1][1])
                del self.cache[oldest[0]]
            self.cache[self._hash(key)] = (value, time.time())
    
    def clear(self):
        with self._lock:
            self.cache.clear()

# Global cache
_result_cache = ResultCache()

# ============================================
# RETRY DECORATOR
# ============================================

def with_retry(max_retries: int = 3, delay: float = 0.5, backoff: float = 2.0):
    """Decorator for retry logic"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            current_delay = delay
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        time.sleep(current_delay)
                        current_delay *= backoff
            
            # All retries failed
            raise last_error
        return wrapper
    return decorator

# ============================================
# TOOL REGISTRY
# ============================================

class ToolRegistry:
    """Enhanced tool registry with metadata and validation"""
    
    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._descriptions: Dict[str, str] = {}
        self._schemas: Dict[str, Dict] = {}
        self._categories: Dict[str, str] = {}
    
    def register(
        self, 
        name: str, 
        func: Callable, 
        description: str = "",
        schema: Dict = None,
        category: str = "general"
    ):
        """Register a tool with full metadata"""
        self._tools[name] = func
        self._descriptions[name] = description
        self._schemas[name] = schema or {}
        self._categories[name] = category
    
    def execute(self, name: str, **kwargs) -> ToolResult:
        """Execute a tool with validation and error handling"""
        if name not in self._tools:
            return ToolResult(False, "", f"Unknown tool: {name}")
        
        try:
            result = self._tools[name](**kwargs)
            if isinstance(result, ToolResult):
                return result
            # Legacy support for functions returning tuples
            if isinstance(result, tuple):
                success, output, error = result + (None,) * (3 - len(result))
                return ToolResult(success, output, error)
            return ToolResult(True, str(result))
        except TypeError as e:
            # Argument validation error
            return ToolResult(False, "", f"Invalid arguments: {e}")
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}\n{traceback.format_exc()}")
            return ToolResult(False, "", f"Error: {str(e)}")
    
    def get_all_descriptions(self) -> str:
        """Get formatted descriptions for all tools"""
        lines = []
        for name, desc in self._descriptions.items():
            schema = self._schemas.get(name, {})
            args = ", ".join(schema.get("args", {}).keys()) if schema else ""
            if args:
                lines.append(f"- {name}({args}): {desc}")
            else:
                lines.append(f"- {name}: {desc}")
        return "\n".join(lines)
    
    def list_tools(self) -> List[str]:
        return list(self._tools.keys())
    
    def get_tools_by_category(self) -> Dict[str, List[str]]:
        """Group tools by category"""
        categories = {}
        for name, cat in self._categories.items():
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(name)
        return categories

# ============================================
# FILE TOOLS
# ============================================

def tool_read_file(path: str, offset: int = 0, limit: int = 2000) -> ToolResult:
    """Read file content with line numbers"""
    try:
        path = os.path.expanduser(path)
        
        if not os.path.exists(path):
            return ToolResult(False, "", f"File not found: {path}")
        
        if not os.path.isfile(path):
            return ToolResult(False, "", f"Not a file: {path}")
        
        # Check file size
        size = os.path.getsize(path)
        if size > 10 * 1024 * 1024:  # 10MB limit
            return ToolResult(False, "", f"File too large ({size / 1024 / 1024:.1f}MB). Use shell commands for large files.")
        
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        start = max(0, offset)
        end = min(len(lines), offset + limit) if limit > 0 else len(lines)
        
        output_lines = []
        for i, line in enumerate(lines[start:end], start + 1):
            output_lines.append(f"{i:6}\t{line.rstrip()}")
        
        output = "\n".join(output_lines)
        
        metadata = {
            "total_lines": total_lines,
            "showing": f"lines {start + 1}-{end} of {total_lines}",
            "file_size": size
        }
        
        if end < total_lines:
            output += f"\n\n... ({total_lines - end} more lines)"
        
        return ToolResult(True, output, metadata=metadata)
    
    except Exception as e:
        return ToolResult(False, "", f"Failed to read file: {e}")


def tool_write_file(path: str, content: str, backup: bool = True) -> ToolResult:
    """Write content to file with optional backup"""
    try:
        path = os.path.expanduser(path)
        
        # Create backup if file exists
        if backup and os.path.exists(path):
            backup_path = f"{path}.backup.{int(time.time())}"
            shutil.copy2(path, backup_path)
        
        # Create directory if needed
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        
        lines = content.count("\n") + 1
        size = len(content)
        
        return ToolResult(True, f"Wrote {lines} lines ({size} bytes) to {path}")
    
    except Exception as e:
        return ToolResult(False, "", f"Failed to write file: {e}")


def tool_append_file(path: str, content: str) -> ToolResult:
    """Append content to file"""
    try:
        path = os.path.expanduser(path)
        
        # Create if doesn't exist
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        
        return ToolResult(True, f"Appended {len(content)} bytes to {path}")
    
    except Exception as e:
        return ToolResult(False, "", f"Failed to append: {e}")


def tool_list_files(path: str = ".", show_hidden: bool = False) -> ToolResult:
    """List directory contents"""
    try:
        path = os.path.expanduser(path)
        
        if not os.path.exists(path):
            return ToolResult(False, "", f"Directory not found: {path}")
        
        if not os.path.isdir(path):
            return ToolResult(False, "", f"Not a directory: {path}")
        
        entries = []
        for entry in sorted(os.listdir(path)):
            if not show_hidden and entry.startswith("."):
                continue
            
            full_path = os.path.join(path, entry)
            
            if os.path.isdir(full_path):
                entries.append(f"📁 DIR   {entry}/")
            else:
                size = os.path.getsize(full_path)
                if size < 1024:
                    size_str = f"{size}B"
                elif size < 1024 * 1024:
                    size_str = f"{size/1024:.1f}KB"
                else:
                    size_str = f"{size/1024/1024:.1f}MB"
                entries.append(f"📄 FILE  {entry} ({size_str})")
        
        if not entries:
            return ToolResult(True, "Directory is empty")
        
        output = f"Directory: {path}\n{'─' * 50}\n" + "\n".join(entries)
        
        return ToolResult(True, output, metadata={"count": len(entries)})
    
    except Exception as e:
        return ToolResult(False, "", f"Failed to list: {e}")


def tool_file_exists(path: str) -> ToolResult:
    """Check if file exists"""
    path = os.path.expanduser(path)
    
    if not os.path.exists(path):
        return ToolResult(True, f"❌ Not found: {path}")
    
    if os.path.isfile(path):
        size = os.path.getsize(path)
        mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
        return ToolResult(True, f"✅ File exists: {path}\n   Size: {size} bytes\n   Modified: {mtime}")
    else:
        return ToolResult(True, f"✅ Directory exists: {path}")


def tool_create_directory(path: str) -> ToolResult:
    """Create directory"""
    try:
        path = os.path.expanduser(path)
        os.makedirs(path, exist_ok=True)
        return ToolResult(True, f"✅ Created directory: {path}")
    except Exception as e:
        return ToolResult(False, "", f"Failed to create directory: {e}")


def tool_delete_file(path: str, force: bool = False) -> ToolResult:
    """Delete file or directory"""
    try:
        path = os.path.expanduser(path)
        
        if not os.path.exists(path):
            return ToolResult(False, "", f"Path not found: {path}")
        
        if os.path.isdir(path):
            if force:
                shutil.rmtree(path)
            else:
                os.rmdir(path)  # Only works if empty
            return ToolResult(True, f"✅ Deleted directory: {path}")
        else:
            os.remove(path)
            return ToolResult(True, f"✅ Deleted file: {path}")
    
    except OSError as e:
        if "not empty" in str(e).lower():
            return ToolResult(False, "", f"Directory not empty. Use force=True to delete recursively.")
        return ToolResult(False, "", f"Failed to delete: {e}")


def tool_glob(pattern: str, path: str = ".") -> ToolResult:
    """Find files matching pattern"""
    try:
        path = os.path.expanduser(path)
        pattern_path = os.path.join(path, "**", pattern)
        matches = glob_module.glob(pattern_path, recursive=True)
        
        if not matches:
            return ToolResult(True, f"No files matching: {pattern}")
        
        # Format results
        results = []
        for m in matches[:100]:  # Limit to 100
            rel_path = os.path.relpath(m, path)
            if os.path.isdir(m):
                results.append(f"📁 {rel_path}/")
            else:
                results.append(f"📄 {rel_path}")
        
        output = f"Found {len(matches)} matches for '{pattern}':\n" + "\n".join(results)
        if len(matches) > 100:
            output += f"\n\n... and {len(matches) - 100} more"
        
        return ToolResult(True, output, metadata={"count": len(matches)})
    
    except Exception as e:
        return ToolResult(False, "", f"Glob failed: {e}")


def tool_grep(pattern: str, path: str = ".", file_pattern: str = "*") -> ToolResult:
    """Search for text in files"""
    try:
        path = os.path.expanduser(path)
        regex = re.compile(pattern, re.IGNORECASE)
        results = []
        
        # File extensions to search
        extensions = {".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".md", ".txt", ".html", ".css", ".yaml", ".yml", ".xml", ".sh", ".bat"}
        
        ignore_dirs = {"node_modules", ".git", "__pycache__", "venv", ".venv", "env", ".env", "build", "dist", ".idea", ".vscode"}
        
        for root, dirs, files in os.walk(path):
            # Filter out ignored directories
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            
            for filename in files:
                # Check file pattern
                if not glob_module.fnmatch.fnmatch(filename, file_pattern):
                    continue
                
                # Check extension
                ext = os.path.splitext(filename)[1].lower()
                if ext not in extensions and file_pattern == "*":
                    continue
                
                file_path = os.path.join(root, filename)
                
                try:
                    with open(file_path, "r", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            if regex.search(line):
                                results.append(f"{filename}:{line_num}: {line.strip()[:120]}")
                                if len(results) >= 50:
                                    break
                except:
                    pass
                
                if len(results) >= 50:
                    break
            
            if len(results) >= 50:
                break
        
        if not results:
            return ToolResult(True, f"No matches found for: {pattern}")
        
        output = f"Found {len(results)} matches for '{pattern}':\n" + "\n".join(results)
        
        return ToolResult(True, output, metadata={"count": len(results)})
    
    except Exception as e:
        return ToolResult(False, "", f"Grep failed: {e}")

# ============================================
# SHELL TOOL
# ============================================

BLOCKED_COMMANDS = [
    "rm -rf /", "rm -rf ~", "mkfs", "dd if=", 
    ":(){:|:&};:", "format c:", "del /s /q",
    "shutdown", "reboot", "init 0", "init 6"
]

def tool_shell(command: str, timeout: int = 30, capture_stderr: bool = True) -> ToolResult:
    """Execute shell command safely"""
    
    # Check for blocked commands
    cmd_lower = command.lower()
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return ToolResult(False, "", f"🚫 Blocked dangerous command pattern: {blocked}")
    
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
        if capture_stderr and result.stderr:
            output += f"\n[STDERR]\n{result.stderr}"
        
        # Truncate if too long
        if len(output) > 8000:
            output = output[:8000] + "\n\n... [output truncated]"
        
        metadata = {
            "return_code": result.returncode,
            "timeout": timeout
        }
        
        if result.returncode != 0:
            return ToolResult(
                False, 
                output, 
                f"Command exited with code {result.returncode}",
                metadata
            )
        
        return ToolResult(True, output if output.strip() else "Command completed (no output)", metadata=metadata)
    
    except subprocess.TimeoutExpired:
        return ToolResult(False, "", f"⏱️ Command timed out after {timeout} seconds")
    
    except Exception as e:
        return ToolResult(False, "", f"Shell error: {e}")

# ============================================
# WEB TOOLS - PRO LEVEL
# ============================================

# Try to import web search libraries
HAS_DUCKDUCKGO = False
try:
    from duckduckgo_search import DDGS
    HAS_DUCKDUCKGO = True
except ImportError:
    pass

HAS_REQUESTS = False
try:
    import urllib.request
    import urllib.parse
    HAS_REQUESTS = True
except ImportError:
    pass

# Web search cache
_web_cache = ResultCache(max_size=50, ttl_seconds=300)

@with_retry(max_retries=3, delay=1.0)
def _search_duckduckgo(query: str, num_results: int = 5) -> List[Dict]:
    """Search using DuckDuckGo"""
    if not HAS_DUCKDUCKGO:
        raise ImportError("duckduckgo-search not installed")
    
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=num_results))
    
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "snippet": r.get("body", "")[:300]
        }
        for r in results
    ]


def _search_google_custom(query: str, api_key: str = None, cx: str = None, num_results: int = 5) -> List[Dict]:
    """Search using Google Custom Search API (if configured)"""
    if not api_key or not cx:
        return []
    
    try:
        url = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cx}&q={urllib.parse.quote(query)}&num={num_results}"
        
        req = urllib.request.Request(url, headers={"User-Agent": "EAA-Agent/3.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        
        items = data.get("items", [])
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", "")[:300]
            }
            for item in items
        ]
    except:
        return []


def tool_web_search(
    query: str, 
    num_results: int = 5,
    provider: str = "auto",
    google_api_key: str = None,
    google_cx: str = None
) -> ToolResult:
    """
    PRO-level web search with multiple providers.
    
    Providers:
    - auto: Try providers in order (Google → DuckDuckGo)
    - duckduckgo: Free, no API key needed
    - google: Google Custom Search (requires API key + CX)
    """
    
    # Check cache
    cache_key = f"search:{query}:{num_results}"
    cached = _web_cache.get(cache_key)
    if cached:
        return ToolResult(True, cached, metadata={"cached": True})
    
    results = []
    errors = []
    
    # Try Google first if configured
    if provider in ["auto", "google"]:
        if google_api_key and google_cx:
            try:
                results = _search_google_custom(query, google_api_key, google_cx, num_results)
                if results:
                    provider_used = "Google Custom Search"
            except Exception as e:
                errors.append(f"Google: {e}")
    
    # Fallback to DuckDuckGo
    if not results and provider in ["auto", "duckduckgo"] and HAS_DUCKDUCKGO:
        try:
            results = _search_duckduckgo(query, num_results)
            provider_used = "DuckDuckGo"
        except Exception as e:
            errors.append(f"DuckDuckGo: {e}")
    
    if not results:
        if not HAS_DUCKDUCKGO:
            return ToolResult(
                False, "", 
                "Web search unavailable. Install: pip install duckduckgo-search"
            )
        return ToolResult(
            False, "", 
            f"Search failed: {'; '.join(errors)}"
        )
    
    # Format results
    output_lines = [f"🔍 Search results for: \"{query}\""]
    output_lines.append(f"Provider: {provider_used}")
    output_lines.append("─" * 50)
    
    for i, r in enumerate(results, 1):
        output_lines.append(f"\n{i}. {r['title']}")
        output_lines.append(f"   🔗 {r['url']}")
        output_lines.append(f"   📝 {r['snippet']}")
    
    output = "\n".join(output_lines)
    
    # Cache results
    _web_cache.set(cache_key, output)
    
    return ToolResult(
        True, 
        output, 
        metadata={
            "provider": provider_used,
            "result_count": len(results),
            "query": query
        }
    )


def tool_web_fetch(url: str, timeout: int = 30, max_size: int = 50000) -> ToolResult:
    """Fetch and extract text from a webpage"""
    
    # Check cache
    cache_key = f"fetch:{url}"
    cached = _web_cache.get(cache_key)
    if cached:
        return ToolResult(True, cached, metadata={"cached": True})
    
    try:
        req = urllib.request.Request(
            url, 
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            
            # Check if it's HTML
            if "text/html" not in content_type and "text/plain" not in content_type:
                return ToolResult(
                    False, "", 
                    f"Not a webpage (Content-Type: {content_type})"
                )
            
            html = resp.read().decode("utf-8", errors="replace")
        
        # Extract text from HTML
        # Remove scripts and styles
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", html)
        
        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()
        
        # Truncate if needed
        if len(text) > max_size:
            text = text[:max_size] + "... [truncated]"
        
        # Try to extract title
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else "No title"
        
        output = f"📄 {title}\n🔗 {url}\n{'─' * 50}\n\n{text}"
        
        # Cache
        _web_cache.set(cache_key, output)
        
        return ToolResult(True, output, metadata={"title": title, "url": url})
    
    except urllib.error.HTTPError as e:
        return ToolResult(False, "", f"HTTP Error {e.code}: {e.reason}")
    
    except urllib.error.URLError as e:
        return ToolResult(False, "", f"URL Error: {e.reason}")
    
    except Exception as e:
        return ToolResult(False, "", f"Fetch failed: {e}")

# ============================================
# MEMORY TOOLS
# ============================================

MEMORY_FILE = "eaa_agent_memory.json"

def _load_memory() -> Dict:
    """Load memory from file"""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def _save_memory(mem: Dict):
    """Save memory to file"""
    with open(MEMORY_FILE, "w") as f:
        json.dump(mem, f, indent=2)


def tool_memory_save(key: str, value: str, category: str = "general") -> ToolResult:
    """Save a value to memory"""
    try:
        mem = _load_memory()
        mem[key] = {
            "value": value,
            "category": category,
            "timestamp": datetime.now().isoformat()
        }
        _save_memory(mem)
        
        return ToolResult(
            True, 
            f"✅ Saved to memory: {key}",
            metadata={"key": key, "category": category}
        )
    except Exception as e:
        return ToolResult(False, "", f"Failed to save: {e}")


def tool_memory_recall(key: str = None, category: str = None) -> ToolResult:
    """Recall value(s) from memory"""
    try:
        mem = _load_memory()
        
        if not mem:
            return ToolResult(True, "Memory is empty")
        
        if key:
            if key in mem:
                entry = mem[key]
                return ToolResult(
                    True,
                    f"📌 {key}:\n{entry.get('value', '')}\n\nSaved: {entry.get('timestamp', 'unknown')}",
                    metadata={"key": key, "found": True}
                )
            return ToolResult(True, f"❌ Key not found: {key}", metadata={"key": key, "found": False})
        
        if category:
            filtered = {k: v for k, v in mem.items() if v.get("category") == category}
            if not filtered:
                return ToolResult(True, f"No entries in category: {category}")
            keys = list(filtered.keys())
        else:
            keys = list(mem.keys())
        
        output = f"📚 Memory ({len(keys)} entries):\n"
        output += "\n".join([f"  • {k}" for k in sorted(keys)])
        
        return ToolResult(True, output, metadata={"count": len(keys)})
    
    except Exception as e:
        return ToolResult(False, "", f"Failed to recall: {e}")


def tool_memory_delete(key: str) -> ToolResult:
    """Delete a key from memory"""
    try:
        mem = _load_memory()
        
        if key not in mem:
            return ToolResult(True, f"❌ Key not found: {key}")
        
        del mem[key]
        _save_memory(mem)
        
        return ToolResult(True, f"✅ Deleted: {key}")
    
    except Exception as e:
        return ToolResult(False, "", f"Failed to delete: {e}")


def tool_memory_clear() -> ToolResult:
    """Clear all memory"""
    try:
        _save_memory({})
        return ToolResult(True, "✅ Memory cleared")
    except Exception as e:
        return ToolResult(False, "", f"Failed to clear: {e}")

# ============================================
# UTILITY TOOLS
# ============================================

def tool_datetime(format: str = None, timezone: str = None) -> ToolResult:
    """Get current date and time"""
    now = datetime.now()
    
    if format:
        try:
            formatted = now.strftime(format)
            return ToolResult(True, formatted, metadata={"format": format})
        except:
            return ToolResult(False, "", "Invalid format string")
    
    output = f"""📅 Date: {now.strftime('%Y-%m-%d')}
⏰ Time: {now.strftime('%H:%M:%S')}
📆 Day: {now.strftime('%A')}
🗓️ Week: {now.strftime('%U')}
🕐 Unix: {int(now.timestamp())}
"""
    return ToolResult(True, output.strip())


def tool_calculator(expression: str, precision: int = 10) -> ToolResult:
    """
    Safe calculator with math functions.
    Supports: +, -, *, /, **, (), sqrt, sin, cos, tan, log, exp, pi, e
    """
    
    # Clean expression
    expr = expression.strip()
    
    # Remove any non-math characters (safety)
    allowed = set("0123456789+-*/.() ,^")
    allowed.update("sqrtsincostanlogexpi")  # Function names
    
    # Check for suspicious content
    if any(word in expr.lower() for word in ["import", "exec", "eval", "__", "open", "file"]):
        return ToolResult(False, "", "🚫 Unsafe expression blocked")
    
    try:
        # Replace ^ with ** for exponent
        expr = expr.replace("^", "**")
        
        # Add math functions
        safe_dict = {
            "sqrt": lambda x: x ** 0.5,
            "sin": __import__("math").sin,
            "cos": __import__("math").cos,
            "tan": __import__("math").tan,
            "log": __import__("math").log10,
            "ln": __import__("math").log,
            "exp": __import__("math").exp,
            "abs": abs,
            "round": round,
            "pi": __import__("math").pi,
            "e": __import__("math").e,
        }
        
        result = eval(expr, {"__builtins__": {}}, safe_dict)
        
        # Round if it's a float
        if isinstance(result, float):
            result = round(result, precision)
        
        return ToolResult(
            True, 
            f"🧮 {expression} = {result}",
            metadata={"expression": expression, "result": result}
        )
    
    except ZeroDivisionError:
        return ToolResult(False, "", "❌ Division by zero")
    
    except SyntaxError as e:
        return ToolResult(False, "", f"❌ Syntax error: {e}")
    
    except Exception as e:
        return ToolResult(False, "", f"❌ Calculation error: {e}")


def tool_python(code: str, timeout: int = 5) -> ToolResult:
    """
    Execute Python code safely.
    Use 'result' variable to return a value.
    """
    
    # Safety checks
    dangerous = ["import os", "import sys", "import subprocess", "open(", "exec(", "eval(", "__"]
    for danger in dangerous:
        if danger in code:
            return ToolResult(False, "", f"🚫 Potentially unsafe code blocked: '{danger}' detected")
    
    try:
        # Create safe namespace
        safe_namespace = {
            "__builtins__": {
                "print": print,
                "len": len,
                "range": range,
                "list": list,
                "dict": dict,
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "sum": sum,
                "min": min,
                "max": max,
                "sorted": sorted,
                "enumerate": enumerate,
                "zip": zip,
                "map": map,
                "filter": filter,
                "abs": abs,
                "round": round,
                "type": type,
                "isinstance": isinstance,
            },
            "json": json,
            "math": __import__("math"),
            "datetime": datetime,
            "re": re,
        }
        
        # Execute
        exec(code, safe_namespace)
        
        # Get result
        result = safe_namespace.get("result", "✅ Code executed (no 'result' variable set)")
        
        return ToolResult(True, str(result))
    
    except Exception as e:
        return ToolResult(False, "", f"❌ Python error: {e}\n{traceback.format_exc()[:500]}")

# ============================================
# CREATE REGISTRY
# ============================================

def create_tool_registry() -> ToolRegistry:
    """Create and register all tools"""
    r = ToolRegistry()
    
    # File tools
    r.register(
        "read_file", tool_read_file,
        "Read file contents with line numbers",
        {"args": {"path": "str", "offset": "int=0", "limit": "int=2000"}},
        category="file"
    )
    r.register(
        "write_file", tool_write_file,
        "Write content to file",
        {"args": {"path": "str", "content": "str", "backup": "bool=True"}},
        category="file"
    )
    r.register(
        "append_file", tool_append_file,
        "Append content to file",
        {"args": {"path": "str", "content": "str"}},
        category="file"
    )
    r.register(
        "list_files", tool_list_files,
        "List directory contents",
        {"args": {"path": "str='.'", "show_hidden": "bool=False"}},
        category="file"
    )
    r.register(
        "file_exists", tool_file_exists,
        "Check if file or directory exists",
        {"args": {"path": "str"}},
        category="file"
    )
    r.register(
        "create_directory", tool_create_directory,
        "Create a directory",
        {"args": {"path": "str"}},
        category="file"
    )
    r.register(
        "delete_file", tool_delete_file,
        "Delete file or directory",
        {"args": {"path": "str", "force": "bool=False"}},
        category="file"
    )
    r.register(
        "glob", tool_glob,
        "Find files matching pattern",
        {"args": {"pattern": "str", "path": "str='.'"}},
        category="file"
    )
    r.register(
        "grep", tool_grep,
        "Search for text in files",
        {"args": {"pattern": "str", "path": "str='.'", "file_pattern": "str='*'"}},
        category="file"
    )
    
    # Shell
    r.register(
        "shell", tool_shell,
        "Execute shell command",
        {"args": {"command": "str", "timeout": "int=30"}},
        category="system"
    )
    
    # Web
    r.register(
        "web_search", tool_web_search,
        "Search the web (PRO level)",
        {"args": {"query": "str", "num_results": "int=5", "provider": "str='auto'"}},
        category="web"
    )
    r.register(
        "web_fetch", tool_web_fetch,
        "Fetch and extract text from webpage",
        {"args": {"url": "str", "timeout": "int=30"}},
        category="web"
    )
    
    # Memory
    r.register(
        "memory_save", tool_memory_save,
        "Save value to memory",
        {"args": {"key": "str", "value": "str", "category": "str='general'"}},
        category="memory"
    )
    r.register(
        "memory_recall", tool_memory_recall,
        "Recall value from memory",
        {"args": {"key": "str=None", "category": "str=None"}},
        category="memory"
    )
    r.register(
        "memory_delete", tool_memory_delete,
        "Delete key from memory",
        {"args": {"key": "str"}},
        category="memory"
    )
    r.register(
        "memory_clear", tool_memory_clear,
        "Clear all memory",
        {"args": {}},
        category="memory"
    )
    
    # Utilities
    r.register(
        "datetime", tool_datetime,
        "Get current date and time",
        {"args": {"format": "str=None"}},
        category="utility"
    )
    r.register(
        "calculator", tool_calculator,
        "Calculate mathematical expression",
        {"args": {"expression": "str", "precision": "int=10"}},
        category="utility"
    )
    r.register(
        "python", tool_python,
        "Execute Python code safely",
        {"args": {"code": "str", "timeout": "int=5"}},
        category="utility"
    )
    

    # ── Advanced Tools (24 new tools) ──
    try:
        from eaa_agent_tools_advanced import register_advanced_tools, ADVANCED_LIGHT_TOOLS
        register_advanced_tools(r)
        LIGHT_TOOLS.update(ADVANCED_LIGHT_TOOLS)
    except ImportError as e:
        pass  # Advanced tools optional

    return r


# ============================================
# LIGHT TOOLS - Don't need brain loaded
# ============================================

# These tools work without needing the AI brain loaded
LIGHT_TOOLS = {
    "datetime", "calculator", "list_files", "file_exists",
    "read_file", "glob", "grep", "shell", "memory_recall", 
    "memory_list", "web_search", "web_fetch"
}

def is_light_tool(tool_name: str) -> bool:
    """Check if a tool can run without brain loaded"""
    return tool_name in LIGHT_TOOLS


__all__ = [
    "ToolResult", "ToolRegistry", "create_tool_registry",
    "is_light_tool", "LIGHT_TOOLS",
    "ResultCache", "with_retry"
]
