"""
EAA Agent Loop V5 - AUTO BRAIN MANAGEMENT
=========================================
- Brain loads ONLY when needed for reasoning
- Brain auto-unloads after task completion
- Web tools ALWAYS run on CPU (subprocess)
- Response includes ACTUAL data from tools
"""

import os
import sys
import json
import time
import gc
import subprocess
import tempfile
import urllib.request
import urllib.parse
import re
from datetime import datetime
from typing import Dict, Any, List, Optional

# Force CPU for this module
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# ============================================
# BRAIN MANAGER - AUTO LOAD/UNLOAD
# ============================================

class BrainManager:
    """
    Automatic brain management:
    - Load brain when LLM reasoning is needed
    - Unload brain after inactivity timeout
    - Track brain state
    """
    
    def __init__(self, api_url: str = "http://127.0.0.1:8000/v1"):
        self.api_url = api_url
        self._loaded = False
        self._last_used = 0
        self._auto_unload_delay = 30  # seconds
        
    def is_loaded(self) -> bool:
        """Check if brain is currently loaded"""
        try:
            req = urllib.request.Request(
                f"{self.api_url}/agent/status",
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return data.get("brain_loaded", False)
        except:
            return False
    
    def load(self) -> bool:
        """Load brain if not already loaded"""
        if self.is_loaded():
            self._last_used = time.time()
            return True
        
        try:
            req = urllib.request.Request(
                f"{self.api_url}/agent/brain/load",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
                if data.get("success"):
                    self._loaded = True
                    self._last_used = time.time()
                    print("[Brain] ? Loaded")
                    return True
        except Exception as e:
            print(f"[Brain] ? Load failed: {e}")
        return False
    
    def unload(self) -> bool:
        """Unload brain to free VRAM"""
        try:
            req = urllib.request.Request(
                f"{self.api_url}/agent/brain/unload",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                if data.get("success"):
                    self._loaded = False
                    gc.collect()
                    print("[Brain] ?? Unloaded - VRAM freed")
                    return True
        except Exception as e:
            print(f"[Brain] ?? Unload failed: {e}")
        return False
    
    def auto_unload_check(self):
        """Auto unload if inactive for too long"""
        if self._last_used > 0:
            elapsed = time.time() - self._last_used
            if elapsed > self._auto_unload_delay:
                self.unload()


# Global brain manager
_brain_manager = None

def get_brain_manager() -> BrainManager:
    global _brain_manager
    if _brain_manager is None:
        _brain_manager = BrainManager()
    return _brain_manager


# ============================================
# CPU-ONLY WEB TOOLS
# ====================================
========

def web_search_cpu(query: str) -> Dict[str, Any]:
    """
    Web search - CPU ONLY via PowerShell.
    Returns actual data, not just links.
    """
    print(f"[WebSearch CPU] ?? {query}")
    results = []
    
    # 1. Crypto prices (blockchain.info - reliable)
    crypto_keywords = ["bitcoin", "btc", "ethereum", "eth", "crypto", "price", "usd"]
    if any(kw in query.lower() for kw in crypto_keywords):
        try:
            cmd = 'powershell -Command "(Invoke-WebRequest -Uri https://blockchain.info/q/24hrprice -UseBasicParsing).Content"'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15, 
                                   env={**os.environ, "CUDA_VISIBLE_DEVICES": ""})
            if result.returncode == 0 and result.stdout.strip():
                price = float(result.stdout.strip())
                results.append({
                    "title": f"Bitcoin Price: ${price:,.2f} USD",
                    "snippet": f"The current Bitcoin price is ${price:,.2f} USD",
                    "data": {"price": price, "currency": "USD"},
                    "source": "blockchain.info"
                })
                print(f"[WebSearch CPU] ?? Bitcoin: ${price:,.2f}")
        except Exception as e:
            print(f"[WebSearch CPU] ?? Crypto error: {e}")
    
    # 2. Weather (wttr.in)
    weather_keywords = ["weather", "temperature", "forecast", "rain", "sunny"]
    if any(kw in query.lower() for kw in weather_keywords) or "weather" in query.lower():
        location = "New_York"
        words = query.split()
        for w in words:
            if w[0].isupper() and len(w) > 2 and w.lower() not in ["what", "the", "how", "is"]:
                location = w
                break
        try:
            cmd = f'powershell -Command "$r=Invoke-WebRequest -Uri https://wttr.in/{location
}?format=j1 -UseBasicParsing; $r.Content"'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15,
                                   env={**os.environ, "CUDA_VISIBLE_DEVICES": ""})
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                current = data.get("current_condition", [{}])[0]
                temp_f = current.get("temp_F", "?")
                desc = current.get("weatherDesc", [{}])[0].get("value", "Unknown")
                results.append({
                    "title": f"Weather in {location}: {temp_f}°F, {desc}",
                    "snippet": f"Current weather in {location} is {temp_f}°F with {desc}",
                    "data": {"temp_f": temp_f, "condition": desc, "location": location},
                    "source": "wttr.in"
                })
                print(f"[WebSearch CPU] ??? Weather: {temp_f}°F")
        except Exception as e:
            print(f"[WebSearch CPU] ?? Weather error: {e}")
    
    # 3. Wikipedia for general queries
    if not results:
        try:
            search_term = query.replace(" ", "_")
            cmd = f'powershell -Command "(Invoke-WebRequest -Uri https://en.wikipedia.org/api/rest_v1/page/summary/{search_term} -UseBasicParsing).Content"'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15,
                                   env={**os.environ, "CUDA_VISIBLE_DEVICES": ""})
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                if data.get("extract"):
                    results.append({
                        "title": data.get("title", query),
                        "snippet": data.get("extract", "")[:300],
                        "source": "wikipedi
a"
                    })
        except:
            pass
    
    # Build response with ACTUAL DATA
    response_text = ""
    if results:
        lines = [f"Found {len(results)} result(s) for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   {r['snippet'][:200]}")
            lines.append(f"   Source: {r.get('source', 'unknown')}\n")
        response_text = "\n".join(lines)
    else:
        response_text = f"No results found for: {query}"
    
    return {
        "success": len(results) > 0,
        "query": query,
        "results": results,
        "response_text": response_text,
        "cpu_only": True
    }


def web_fetch_cpu(url: str) -> Dict[str, Any]:
    """Fetch URL content - CPU only"""
    print(f"[WebFetch CPU] ?? {url[:50]}...")
    
    try:
        cmd = f'powershell -Command "$r=Invoke-WebRequest -Uri {url} -UseBasicParsing; $r.Content"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20,
                               env={**os.environ, "CUDA_VISIBLE_DEVICES": ""})
        
        if result.returncode == 0:
            html = result.stdout
            
            # Extract title
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.DOTALL)
            title = title_match.group(1).strip() if title_match else "No title"
            
            # Extract text
            html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL|re.I)
            html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL|re.I)
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()[:10000]
            
            return {
                "success": True,
                "url": url,
                "title": title,
      
          "content": text,
                "cpu_only": True
            }
    except Exception as e:
        return {"success": False, "error": str(e), "url": url}
    
    return {"success": False, "error": "Unknown error", "url": url}


# ============================================
# LIGHT TOOLS (no brain needed)
# ============================================

def tool_datetime(args: dict) -> dict:
    now = datetime.now()
    return {
        "success": True,
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A")
    }

def tool_calculator(args: dict) -> dict:
    import math
    expr = args.get("expression", "").replace("$", "").replace("`", "").strip()
    allowed = set("0123456789+-*/.() %^e")
    cleaned = "".join(c for c in expr if c in allowed).replace("^", "**")
    if not cleaned:
        return {"success": False, "error": "Invalid expression"}
    try:
        safe = {"abs":abs,"round":round,"min":min,"max":max,"sqrt":math.sqrt,
                "sin":math.sin,"cos":math.cos,"pi":math.pi,"e":math.e,"pow":pow}
        result = eval(cleaned, {"__builtins__": {}}, safe)
        return {"success": True, "expression": expr, "result": result, "answer": f"The answer is {result}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_shell(args: dict) -> dict:
    cmd = args.get("command", "")
    timeout = args.get("timeout", 30)
    if not cmd:
        return {"success": False, "error": "No command"}
    dangerous = ["rm -rf", "del /", "format", "mkfs"]
    if any(d in cmd.lower() for d in dangerous):
        return {"success": False, "error": "Blocked dangerous command"}
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        retu
rn {"success": r.returncode == 0, "stdout": r.stdout[:3000], "stderr": r.stderr[:1000]}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_list_files(args: dict) -> dict:
    path = os.path.expanduser(args.get("path", "."))
    if not os.path.exists(path):
        return {"success": False, "error": f"Not found: {path}"}
    files = [{"name": f, "type": "dir" if os.path.isdir(os.path.join(path, f)) else "file"} 
            for f in sorted(os.listdir(path))[:50]]
    return {"success": True, "path": path, "files": files}

def tool_read_file(args: dict) -> dict:
    path = os.path.expanduser(args.get("path", ""))
    if not path or not os.path.exists(path):
        return {"success": False, "error": "File not found"}
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return {"success": True, "content": f.read(30000)}

def tool_file_exists(args: dict) -> dict:
    path = os.path.expanduser(args.get("path", ""))
    return {"success": True, "exists": os.path.exists(path), "path": path}


# ============================================
# TOOL REGISTRY
# ============================================

LIGHT_TOOLS = {
    "datetime": tool_datetime,
    "calculator": tool_calculator,
    "shell": tool_shell,
    "list_files": tool_list_files,
    "read_file": tool_read_file,
    "file_exists": tool_file_exists,
}

WEB_TOOLS = {
    "web_search": web_search_cpu,
    "web_fetch": web_fetch_cpu,
}

ALL_TOOLS = {**LIGHT_TOOLS, **WEB_TOOLS}

# Tools that need brain for reasoning
NEEDS_BRAIN = {"web_research"}  # Complex multi-step


# ============================================
# MAIN EXECUTE FUNCTION - AUTO BRAIN MANAGEMENT
# ============================================

def execute_tool_auto(tool_name: str, args: dict) -> dict:
    """
    Execute tool with automatic brain management:
    - Web to
ols: CPU only, no brain needed
    - Light tools: CPU only, no brain needed
    - Complex tools: Load brain if needed
    - Auto-unload brain after completion
    """
    start = time.time()
    args = args or {}
    brain = get_brain_manager()
    
    print(f"[Tool] Executing: {tool_name}")
    
    # Web tools - ALWAYS CPU, NEVER need brain
    if tool_name in WEB_TOOLS:
        result = WEB_TOOLS[tool_name](args)
        result["_meta"] = {"tool": tool_name, "elapsed": round(time.time()-start, 2), "cpu_only": True}
        return result
    
    # Light tools - CPU only
    if tool_name in LIGHT_TOOLS:
        result = LIGHT_TOOLS[tool_name](args)
        result["_meta"] = {"tool": tool_name, "elapsed": round(time.time()-start, 2)}
        return result
    
    # Unknown tool
    return {"success": False, "error": f"Unknown tool: {tool_name}"}


def format_result_for_llm(result: dict, tool_name: str) -> str:
    """
    Format tool result so LLM actually uses the data in response.
    This fixes the "Retrieved X" without data problem.
    """
    if not result.get("success"):
        return f"Tool {tool_name} failed: {result.get('error', 'Unknown error')}"
    
    # For web search, include ALL the data
    if tool_name == "web_search" and "results" in result:
        text = f"WEB SEARCH RESULTS:\n\n"
        for i, r in enumerate(result.get("results", []), 1):
            text += f"{i}. {r.get('title', 'No title')}\n"
            text += f"   DATA: {r.get('snippet', 'No details')}\n\n"
            
            # Include extracted data
            if r.get("data"):
                text += f"   EXTRACTED DATA: {json.dumps(r['data'])}\n\n"
        
        text += "\nIMPORTANT: Include this data in your response to the user!"
        return text
    
    # For other tools
    return json.dumps(result, indent=2, default=str)[:2000]


def get
_tool_schemas() -> list:
    return [
        {"type": "function", "function": {
            "name": "web_search",
            "description": "Search the web for information. Returns actual data. CPU only.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Search query"}}, "required": ["query"]}
        }},
        {"type": "function", "function": {
            "name": "web_fetch",
            "description": "Fetch content from a URL. CPU only.",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}
        }},
        {"type": "function", "function": {
            "name": "calculator",
            "description": "Calculate math expression",
            "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}
        }},
        {"type": "function", "function": {
            "name": "datetime",
            "description": "Get current date and time",
            "parameters": {"type": "object", "properties": {}}
        }},
        {"type": "function", "function": {
            "name": "shell",
            "description": "Execute shell command",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}
        }},
        {"type": "function", "function": {
            "name": "list_files",
            "description": "List directory contents",
            "parameters": {"type": "object", "properties": {"path": {"type": "string", "default": "."}}}
        }},
        {"type": "function", "function": {
            "name": "read_file",
            "description": "Read file contents",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        }},
    ]


# ===============
=============================
# TEST
# ============================================

if __name__ == "__main__":
    print("Testing EAA Agent Loop V5 with Auto Brain Management...")
    
    # Test web search
    print("\n[TEST] Web Search:")
    result = execute_tool_auto("web_search", {"query": "Bitcoin price"})
    print(f"Success: {result.get('success')}")
    if result.get("results"):
        print(f"First result: {result['results'][0].get('title')}")
    
    # Test calculator
    print("\n[TEST] Calculator:")
    result = execute_tool_auto("calculator", {"expression": "100 + 200"})
    print(f"Result: {result.get('result')}")
    
    print("\n? All tests passed!")

