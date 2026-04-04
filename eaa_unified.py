"""
EAA UNIFIED SERVER - Control + AI Tools on Same Port
=====================================================
Run: python eaa_unified.py
"""

import os, sys, time, secrets, threading, subprocess, json, base64, hmac, re, shutil, signal, gc
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

# Optional imports
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    PYAUTOGUI_AVAILABLE = True
except: PYAUTOGUI_AVAILABLE = False

try:
    from PIL import Image
    import io
    PIL_AVAILABLE = True
except: PIL_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except: PSUTIL_AVAILABLE = False

try:
    import win32clipboard, win32con, win32gui
    WIN32_AVAILABLE = True
    WIN32GUI_AVAILABLE = True
except: WIN32_AVAILABLE = WIN32GUI_AVAILABLE = False

try:
    import eaa_voice
    HAS_VOICE = True
except: HAS_VOICE = False

try:
    from duckduckgo_search import DDGS
    HAS_DUCKDUCKGO = True
except: HAS_DUCKDUCKGO = False

try:
    import torch, brain_manager
    HAS_BRAIN = True
except: HAS_BRAIN = False

# Config
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.getcwd()
TOOLS_DIR = os.path.join(SCRIPT_DIR, "tools")
CLOUDFLARED_PATH = os.path.join(TOOLS_DIR, "cloudflared.exe")
ALLOWED_PATH = r"C:\Users\offic"
PORT = 8001
API_KEY = secrets.token_urlsafe(32)
SECRET_PHRASE = secrets.choice(["alpha-bravo-charlie", "delta-echo-foxtrot", "golf-hotel-india", "juliet-kilo-lima", "mike-november-oscar", "papa-quebec-romeo", "sierra-tango-uniform", "victor-whiskey-xray", "yankee-zulu-alpha", "bravo-mike-steel", "shadow-zulu-mike"])

ID_MASTER = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
ID_LOGIC = "unsloth/DeepSeek-R1-Distill-Qwen-7B-unsloth-bnb-4bit"
ID_CODER = "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit"
ID_SHADOW = r"C:\Users\offic\EAA\brains\shadow_brain.gguf"

tunnel_process, tunnel_url, brain, brain_loaded = None, None, None, False

# Session Manager
class SessionManager:
    def __init__(self):
        self.session_token, self.last_activity, self.timeout, self.lock = None, 0, 0, threading.Lock()
    def get_or_create(self, provided=None):
        with self.lock:
            if self.session_token is None:
                self.session_token = "SESS_" + secrets.token_urlsafe(32)
                self.last_activity = time.time()
                return True, self.session_token, "new_session"
            if provided == self.session_token:
                self.last_activity = time.time()
                return True, self.session_token, "session_active"
            return False, None, "session_locked"
    def validate(self, provided):
        with self.lock:
            return self.session_token is None or provided == self.session_token

session_manager = SessionManager()

# Rate Limiter
class RateLimiter:
    def __init__(self, max_req=150, window=60):
        self.max_req, self.window, self.requests, self.lock = max_req, window, {}, threading.Lock()
    def check(self, ip):
        with self.lock:
            now = time.time()
            if ip not in self.requests: self.requests[ip] = []
            self.requests[ip] = [t for t in self.requests[ip] if now - t < self.window]
            if len(self.requests[ip]) >= self.max_req: return False
            self.requests[ip].append(now)
            return True

rate_limiter = RateLimiter()

# Tool System
@dataclass
class ToolResult:
    success: bool
    output: str
    error: Optional[str] = None
    def to_dict(self): return {"success": self.success, "output": self.output, "error": self.error}

class ToolRegistry:
    def __init__(self):
        self._tools, self._descriptions = {}, {}
    def register(self, name, func, desc=""):
        self._tools[name], self._descriptions[name] = func, desc
    def execute(self, name, **kwargs):
        if name not in self._tools: return ToolResult(False, "", f"Unknown tool: {name}")
        try: return self._tools[name](**kwargs)
        except Exception as e: return ToolResult(False, "", str(e))
    def list_tools(self): return list(self._tools.keys())

# Tool implementations
def tool_read_file(path, offset=0, limit=2000):
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path): return ToolResult(False, "", f"File not found: {path}")
        with open(path, "r", encoding="utf-8", errors="replace") as f: lines = f.readlines()
        start, end = max(0, offset), min(len(lines), offset + limit) if limit > 0 else len(lines)
        output = "".join([f"{i:6}\t{line}" for i, line in enumerate(lines[start:end], start + 1)])
        return ToolResult(True, output)
    except Exception as e: return ToolResult(False, "", str(e))

def tool_write_file(path, content):
    try:
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f: f.write(content)
        return ToolResult(True, f"Wrote to {path}")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_append_file(path, content):
    try:
        with open(os.path.expanduser(path), "a", encoding="utf-8") as f: f.write(content)
        return ToolResult(True, f"Appended to {path}")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_list_files(path="."):
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path): return ToolResult(False, "", f"Not found: {path}")
        entries = [f"DIR  {e}/" if os.path.isdir(os.path.join(path, e)) else f"FILE {e}" for e in sorted(os.listdir(path))]
        return ToolResult(True, "\n".join(entries))
    except Exception as e: return ToolResult(False, "", str(e))

def tool_file_exists(path):
    path = os.path.expanduser(path)
    return ToolResult(True, f"Exists: {path}" if os.path.exists(path) else f"Not found: {path}")

def tool_create_directory(path):
    try:
        os.makedirs(os.path.expanduser(path), exist_ok=True)
        return ToolResult(True, f"Created: {path}")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_delete_file(path):
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path): return ToolResult(False, "", f"Not found: {path}")
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        return ToolResult(True, f"Deleted: {path}")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_glob(pattern, path="."):
    try:
        import glob as g
        path = os.path.expanduser(path)
        matches = g.glob(os.path.join(path, "**", pattern), recursive=True)
        return ToolResult(True, "\n".join([m.replace(path + os.sep, "") for m in matches[:100]]) or "No matches")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_grep(pattern, path="."):
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

def tool_shell(command, timeout=30):
    for blocked in ["rm -rf /", "rm -rf ~", "mkfs", "dd if=", "format"]:
        if blocked in command.lower(): return ToolResult(False, "", "Blocked")
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
        output = result.stdout + (f"\nSTDERR:\n{result.stderr}" if result.stderr else "")
        if len(output) > 5000: output = output[:5000] + "\n...[truncated]"
        return ToolResult(result.returncode == 0, output, f"Exit: {result.returncode}" if result.returncode else None)
    except subprocess.TimeoutExpired: return ToolResult(False, "", f"Timeout {timeout}s")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_web_search(query, num_results=5):
    if not HAS_DUCKDUCKGO: return ToolResult(False, "", "pip install duckduckgo-search")
    try:
        with DDGS() as ddgs:
            results = [f"- {r.get('title','')}\n  {r.get('href','')}\n  {r.get('body','')[:200]}" for r in ddgs.text(query, max_results=num_results)]
        return ToolResult(True, "\n\n".join(results))
    except Exception as e: return ToolResult(False, "", str(e))

def tool_web_fetch(url):
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = re.sub(r"<[^>]+>", " ", resp.read().decode("utf-8", errors="replace"))
            return ToolResult(True, re.sub(r"\s+", " ", content).strip()[:10000])
    except Exception as e: return ToolResult(False, "", str(e))

MEMORY_FILE = "eaa_memory.json"
def tool_memory_save(key, value):
    try:
        mem = json.load(open(MEMORY_FILE)) if os.path.exists(MEMORY_FILE) else {}
        mem[key] = {"value": value, "timestamp": datetime.now().isoformat()}
        json.dump(mem, open(MEMORY_FILE, "w"), indent=2)
        return ToolResult(True, f"Saved: {key}")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_memory_recall(key=None):
    try:
        mem = json.load(open(MEMORY_FILE)) if os.path.exists(MEMORY_FILE) else {}
        if key: return ToolResult(True, f"{key}: {mem.get(key, {}).get('value', 'Not found')}")
        return ToolResult(True, json.dumps(mem, indent=2))
    except Exception as e: return ToolResult(False, "", str(e))

def tool_memory_list():
    try:
        mem = json.load(open(MEMORY_FILE)) if os.path.exists(MEMORY_FILE) else {}
        return ToolResult(True, f"Keys ({len(mem)}):\n" + "\n".join(mem.keys()))
    except Exception as e: return ToolResult(False, "", str(e))

def tool_datetime():
    now = datetime.now()
    return ToolResult(True, f"Date/Time: {now.strftime('%Y-%m-%d %H:%M:%S')}\nDay: {now.strftime('%A')}")

def tool_calculator(expression):
    try:
        if not all(c in "0123456789+-*/.() " for c in expression): return ToolResult(False, "", "Invalid")
        return ToolResult(True, f"{expression} = {eval(expression)}")
    except Exception as e: return ToolResult(False, "", str(e))

def tool_python(code):
    try:
        ns = {"__builtins__": __builtins__, "json": json, "os": os}
        exec(code, ns)
        return ToolResult(True, str(ns.get("result", "Done")))
    except Exception as e: return ToolResult(False, "", str(e))

def create_tool_registry():
    r = ToolRegistry()
    r.register("read_file", tool_read_file)
    r.register("write_file", tool_write_file)
    r.register("append_file", tool_append_file)
    r.register("list_files", tool_list_files)
    r.register("file_exists", tool_file_exists)
    r.register("create_directory", tool_create_directory)
    r.register("delete_file", tool_delete_file)
    r.register("glob", tool_glob)
    r.register("grep", tool_grep)
    r.register("shell", tool_shell)
    r.register("web_search", tool_web_search)
    r.register("web_fetch", tool_web_fetch)
    r.register("memory_save", tool_memory_save)
    r.register("memory_recall", tool_memory_recall)
    r.register("memory_list", tool_memory_list)
    r.register("datetime", tool_datetime)
    r.register("calculator", tool_calculator)
    r.register("python", tool_python)
    return r

tool_registry = create_tool_registry()

# Helpers
def verify_api_key(key): return key and hmac.compare_digest(key, API_KEY)
def verify_secret(secret): return secret == SECRET_PHRASE
def take_screenshot():
    if not PYAUTOGUI_AVAILABLE or not PIL_AVAILABLE: return None, "Not available"
    try:
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode(), None
    except Exception as e: return None, str(e)

def get_system_info():
    info = {"timestamp": datetime.now().isoformat()}
    if PSUTIL_AVAILABLE:
        info.update({"cpu": psutil.cpu_percent(0.1), "ram": psutil.virtual_memory().percent, "disk": psutil.disk_usage('C:\\').percent})
    return info

def get_clipboard():
    if not WIN32_AVAILABLE: return None, "Not available"
    try:
        win32clipboard.OpenClipboard()
        data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()
        return data, None
    except Exception as e: return None, str(e)

def set_clipboard(content):
    if not WIN32_AVAILABLE: return False, "Not available"
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(content, win32con.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()
        return True, None
    except Exception as e: return False, str(e)

def speak_text(text):
    if not HAS_VOICE: return False, "No voice"
    try: eaa_voice.speak(text); return True, None
    except Exception as e: return False, str(e)

def start_tunnel(port):
    global tunnel_process, tunnel_url
    if not os.path.exists(CLOUDFLARED_PATH): return None
    try:
        tunnel_process = subprocess.Popen([CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{port}"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for _ in range(30):
            line = tunnel_process.stdout.readline()
            if "trycloudflare.com" in line:
                m = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
                if m: tunnel_url = m.group(0); return tunnel_url
    except: pass
    return None

def load_brain_async():
    global brain, brain_loaded
    if not HAS_BRAIN: return
    try:
        brain = brain_manager.BrainManager()
        brain.load(ID_MASTER)
        brain_loaded = True
        print("[BRAIN] ✅ Loaded!")
    except Exception as e: print(f"[BRAIN] ❌ {e}")

def generate_ai_response(message, brain_type="master"):
    global brain, brain_loaded
    if not brain_loaded: return None, "Brain not loaded"
    try:
        brain_id = ID_MASTER if brain_type == "master" else ID_LOGIC if brain_type == "logic" else ID_CODER if brain_type == "coder" else ID_SHADOW
        sys_prompt = "You are EAA, a helpful AI."
        response = brain.generate_text(brain_id, sys_prompt, message, max_new_tokens=512, temperature=0.7)
        return response.strip(), None
    except Exception as e: return None, str(e)

# Request Handler
class UnifiedHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): print(f"[UNIFIED] {fmt % args}")
    
    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def check_auth(self):
        key, secret = self.headers.get("X-Control-Key", ""), self.headers.get("X-Secret", "")
        return (verify_api_key(key) or verify_secret(secret), None)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "X-Control-Key, X-Secret, X-Session-Token, Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if not rate_limiter.check(self.client_address[0]): self.send_json({"suc": False, "err": "Rate limit"}, 429); return

        if path == "/health":
            self.send_json({"status": "online", "version": "unified", "tools": len(tool_registry.list_tools()), "brain": brain_loaded, "tts": HAS_VOICE, "tunnel": tunnel_url}); return
        if path in ["/v1/tools", "/tools"]:
            self.send_json({"tools": tool_registry.list_tools(), "count": len(tool_registry.list_tools())}); return

        auth_ok, _ = self.check_auth()
        if not auth_ok: self.send_json({"suc": False, "err": "Invalid API key"}, 401); return

        session_token = self.headers.get("X-Session-Token", "")
        ok, token, _ = session_manager.get_or_create(session_token)
        if not ok: self.send_json({"suc": False, "err": "Session locked", "session_token": token}); return

        if path == "/screenshot":
            img, err = take_screenshot()
            self.send_json({"suc": not err, "image": img, "err": err, "session_token": token}); return
        if path == "/system/info":
            self.send_json({"suc": True, "system": get_system_info(), "session_token": token}); return
        if path == "/clipboard/get":
            content, err = get_clipboard()
            self.send_json({"suc": not err, "content": content, "err": err, "session_token": token}); return
        if path == "/mouse/position" and PYAUTOGUI_AVAILABLE:
            x, y = pyautogui.position()
            self.send_json({"suc": True, "x": x, "y": y, "session_token": token}); return

        self.send_json({"suc": False, "err": "Unknown endpoint"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not rate_limiter.check(self.client_address[0]): self.send_json({"suc": False, "err": "Rate limit"}, 429); return

        length = int(self.headers.get("Content-Length", 0))
        try: data = json.loads(self.rfile.read(length).decode()) if length > 0 else {}
        except: data = {}

        auth_ok, _ = self.check_auth()
        if not auth_ok: self.send_json({"suc": False, "err": "Invalid API key"}, 401); return

        session_token = self.headers.get("X-Session-Token", "")
        ok, token, _ = session_manager.get_or_create(session_token)
        if not ok: self.send_json({"suc": False, "err": "Session locked", "session_token": token}); return

        # Tool execution
        if path in ["/tool/execute", "/v1/tool/execute"]:
            result = tool_registry.execute(data.get("tool", ""), **data.get("args", {}))
            self.send_json({"suc": result.success, "output": result.output, "error": result.error, "session_token": token}); return

        # AI Chat
        if path in ["/ai/chat", "/v1/chat"]:
            response, err = generate_ai_response(data.get("message", ""), data.get("brain_type", "master"))
            self.send_json({"suc": not err, "response": response, "err": err, "session_token": token}); return

        # TTS
        if path in ["/speak", "/tts"]:
            ok, err = speak_text(data.get("text", ""))
            self.send_json({"suc": ok, "err": err, "session_token": token}); return

        # Mouse/Keyboard
        if path == "/mouse/move" and PYAUTOGUI_AVAILABLE:
            pyautogui.moveTo(data.get("x", 0), data.get("y", 0))
            self.send_json({"suc": True, "session_token": token}); return
        if path == "/mouse/click" and PYAUTOGUI_AVAILABLE:
            pyautogui.click(data.get("x"), data.get("y"), clicks=data.get("clicks", 1), button=data.get("button", "left"))
            self.send_json({"suc": True, "session_token": token}); return
        if path == "/keyboard/type" and PYAUTOGUI_AVAILABLE:
            pyautogui.typewrite(data.get("text", ""))
            self.send_json({"suc": True, "session_token": token}); return
        if path in ["/keyboard/press", "/keyboard/key"] and PYAUTOGUI_AVAILABLE:
            pyautogui.press(data.get("key", "enter"))
            self.send_json({"suc": True, "session_token": token}); return

        # Shell
        if path == "/shell":
            result = subprocess.run(data.get("command", ""), shell=True, capture_output=True, text=True, timeout=data.get("timeout", 30), cwd=ALLOWED_PATH)
            self.send_json({"suc": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr, "session_token": token}); return

        # Clipboard
        if path == "/clipboard/set":
            ok, err = set_clipboard(data.get("content", ""))
            self.send_json({"suc": ok, "err": err, "session_token": token}); return

        # Browser
        if path == "/browser/open":
            subprocess.run(f'start "" "{data.get("url", "https://google.com")}"', shell=True)
            self.send_json({"suc": True, "session_token": token}); return

        self.send_json({"suc": False, "err": "Unknown endpoint"})

# Main
if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: (print("\n[STOP]"), sys.exit(0)))
    
    print("=" * 60)
    print("  EAA UNIFIED SERVER")
    print("=" * 60)
    print(f"\n[KEY] {API_KEY}")
    print(f"[SECRET] {SECRET_PHRASE}")
    print(f"\n[TOOLS] {len(tool_registry.list_tools())}: {', '.join(tool_registry.list_tools())}")
    print(f"\n[CAPS] Screenshot:{'✅' if PIL_AVAILABLE else '❌'} Mouse:{'✅' if PYAUTOGUI_AVAILABLE else '❌'} TTS:{'✅' if HAS_VOICE else '❌'} Brain:{'✅' if HAS_BRAIN else '❌'} Web:{'✅' if HAS_DUCKDUCKGO else '❌'}")
    
    print("\n[TUNNEL] Starting...")
    url = start_tunnel(PORT)
    print(f"[TUNNEL] {url or 'Failed'}")
    
    if HAS_BRAIN:
        print("\n[BRAIN] Loading...")
        threading.Thread(target=load_brain_async, daemon=True).start()
    
    print("\n" + "=" * 60)
    print(f"  URL: {url}\n  Key: {API_KEY}\n  Secret: {SECRET_PHRASE}")
    print("=" * 60)
    
    HTTPServer(("0.0.0.0", PORT), UnifiedHandler).serve_forever()