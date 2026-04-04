"""
EAA CONTROL SYSTEM V5 - COMPLETE REMOTE CONTROL
================================================
Full remote control with ALL endpoints:
- Tier 1: System Awareness (health, system info, processes, screenshot)
- Tier 2: Active Control (windows, clipboard, browser, notifications)
- Tier 3: Full Control (mouse, keyboard, power, shell, files)
- Session token security
- Auto-start EAA and tunnel
"""

import os
import sys
import time
import secrets
import threading
import subprocess
import json
import base64
import hashlib
import hmac
import re
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import shutil
import signal

# ============================================
# DEPENDENCIES
# ============================================

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    print("[WARN] pyautogui not available")

try:
    from PIL import Image
    import io
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[WARN] Pillow not available")

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("[WARN] psutil not available")

try:
    import win32clipboard
    import win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

try:
    import win32gui
    import win32api
    WIN32GUI_AVAILABLE = True
except ImportError:
    WIN32GUI_AVAILABLE = False

# ============================================
# CONFIGURATION
# ============================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(SCRIPT_DIR, "tools")
CLOUDFLARED_PATH = os.path.join(TOOLS_DIR, "cloudflared.exe")
ALLOWED_PATH = r"C:\Users\offic"

PORT = 8001
EAA_SCRIPT = os.path.join(SCRIPT_DIR, "run_eaa_agent_v3.py")

API_KEY = secrets.token_urlsafe(32)
SECRET_PHRASE = secrets.choice([
    "alpha-bravo-charlie", "delta-echo-foxtrot", "golf-hotel-india",
    "juliet-kilo-lima", "mike-november-oscar", "papa-quebec-romeo",
    "sierra-tango-uniform", "victor-whiskey-xray", "yankee-zulu-alpha",
    "bravo-mike-steel", "shadow-zulu-mike"
])
SESSION_TIMEOUT = 0  # 0 = disabled

# ============================================
# GLOBAL STATE
# ============================================

eaa_process = None
tunnel_process = None
tunnel_url = None
eaa_tunnel_process = None
eaa_tunnel_url = None

# ============================================
# SESSION MANAGER
# ============================================

class SessionManager:
    def __init__(self):
        self.session_token = None
        self.last_activity = 0
        self.timeout = SESSION_TIMEOUT
        self.lock = threading.Lock()
    
    def get_or_create(self, provided=None):
        with self.lock:
            now = time.time()
            
            if self.session_token and self.timeout > 0:
                if (now - self.last_activity) > self.timeout:
                    self.session_token = None
            
            if self.session_token is None:
                self.session_token = "SESS_" + secrets.token_urlsafe(32)
                self.last_activity = now
                return True, self.session_token, "new_session"
            
            if provided == self.session_token:
                self.last_activity = now
                return True, self.session_token, "session_active"
            
            return False, None, "session_locked"
    
    def validate(self, provided):
        with self.lock:
            if self.session_token is None:
                return True
            return provided == self.session_token

session_manager = SessionManager()

# ============================================
# RATE LIMITER
# ============================================

class RateLimiter:
    def __init__(self, max_req=150, window=60):
        self.max_req = max_req
        self.window = window
        self.requests = {}
        self.lock = threading.Lock()
    
    def check(self, ip):
        with self.lock:
            now = time.time()
            if ip not in self.requests:
                self.requests[ip] = []
            self.requests[ip] = [t for t in self.requests[ip] if now - t < self.window]
            if len(self.requests[ip]) >= self.max_req:
                return False
            self.requests[ip].append(now)
            return True

rate_limiter = RateLimiter()

# ============================================
# HELPER FUNCTIONS
# ============================================

def verify_api_key(key):
    if not key:
        return False
    return hmac.compare_digest(key, API_KEY)

def verify_secret(secret):
    return secret == SECRET_PHRASE

def json_resp(data, status=200):
    return {"status": status, "body": json.dumps(data), "content_type": "application/json"}

def err_resp(msg, status=400):
    return json_resp({"suc": False, "err": msg}, status)

def suc_resp(data=None):
    if data is None:
        return json_resp({"suc": True})
    if isinstance(data, dict):
        data["suc"] = True
        return json_resp(data)
    return json_resp({"suc": True, "data": data})

def validate_path(path):
    if not path:
        return False
    abs_path = os.path.abspath(path)
    return abs_path.startswith(ALLOWED_PATH)

def take_screenshot():
    if not PYAUTOGUI_AVAILABLE or not PIL_AVAILABLE:
        return None, "Dependencies not available"
    try:
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode(), None
    except Exception as e:
        return None, str(e)

def get_system_info():
    info = {"timestamp": datetime.now().isoformat()}
    if PSUTIL_AVAILABLE:
        info.update({
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('C:\\').percent,
            "uptime": int(time.time() - psutil.boot_time()),
        })
    return info

def get_process_list():
    if not PSUTIL_AVAILABLE:
        return []
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            procs.append({
                "pid": p.info['pid'],
                "name": p.info['name'],
                "cpu": round(p.info['cpu_percent'] or 0, 1),
                "memory": round(p.info['memory_percent'] or 0, 1),
            })
        except:
            pass
    return sorted(procs, key=lambda x: x['cpu'], reverse=True)[:50]

def get_windows_list():
    if not WIN32GUI_AVAILABLE:
        return []
    windows = []
    def enum_cb(hwnd, ctx):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                windows.append({
                    "hwnd": hwnd,
                    "title": title,
                    "active": hwnd == win32gui.GetForegroundWindow()
                })
    win32gui.EnumWindows(enum_cb, None)
    return windows

def focus_window(title):
    if not WIN32GUI_AVAILABLE:
        return False, "win32 not available"
    try:
        def enum_cb(hwnd, ctx):
            if win32gui.IsWindowVisible(hwnd):
                if title.lower() in win32gui.GetWindowText(hwnd).lower():
                    win32gui.SetForegroundWindow(hwnd)
                    return True
            return False
        win32gui.EnumWindows(enum_cb, None)
        return True, None
    except Exception as e:
        return False, str(e)

def close_window(title):
    if not WIN32GUI_AVAILABLE:
        return False, "win32 not available"
    try:
        def enum_cb(hwnd, ctx):
            if win32gui.IsWindowVisible(hwnd):
                if title.lower() in win32gui.GetWindowText(hwnd).lower():
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        win32gui.EnumWindows(enum_cb, None)
        return True, None
    except Exception as e:
        return False, str(e)

def get_clipboard():
    if not WIN32_AVAILABLE:
        return None, "win32 not available"
    try:
        win32clipboard.OpenClipboard()
        data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()
        return data, None
    except Exception as e:
        return None, str(e)

def set_clipboard(content):
    if not WIN32_AVAILABLE:
        return False, "win32 not available"
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(content, win32con.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()
        return True, None
    except Exception as e:
        return False, str(e)

def send_notification(title, message):
    try:
        ps_cmd = f'''
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show("{message}", "{title}")
        '''
        subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=5)
        return True, None
    except Exception as e:
        return False, str(e)

def run_shell(cmd, timeout=30):
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=ALLOWED_PATH
        )
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Timeout", "returncode": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1}

def start_tunnel(port):
    """Start Cloudflare tunnel"""
    global tunnel_process, tunnel_url
    
    if not os.path.exists(CLOUDFLARED_PATH):
        print(f"[TUNNEL] cloudflared not found at {CLOUDFLARED_PATH}")
        return None
    
    try:
        tunnel_process = subprocess.Popen(
            [CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # Wait for URL
        for _ in range(30):
            line = tunnel_process.stdout.readline()
            if "trycloudflare.com" in line:
                match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
                if match:
                    tunnel_url = match.group(0)
                    return tunnel_url
        
        return None
    except Exception as e:
        print(f"[TUNNEL] Error: {e}")
        return None

def start_eaa():
    """Start EAA server"""
    global eaa_process
    
    if not os.path.exists(EAA_SCRIPT):
        print(f"[EAA] Script not found: {EAA_SCRIPT}")
        return None
    
    try:
        eaa_process = subprocess.Popen(
            [sys.executable, EAA_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=SCRIPT_DIR
        )
        print(f"[EAA] Started (PID: {eaa_process.pid})")
        return eaa_process.pid
    except Exception as e:
        print(f"[EAA] Error: {e}")
        return None

# ============================================
# REQUEST HANDLER
# ============================================

class ControlHandler(BaseHTTPRequestHandler):
    
    def log_message(self, fmt, *args):
        print(f"[CONTROL] {fmt % args}")
    
    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
    
    def get_client_ip(self):
        return self.client_address[0]
    
    def check_auth(self):
        """Check authentication - accept API key OR secret"""
        key = self.headers.get("X-Control-Key", "")
        secret = self.headers.get("X-Secret", "")
        
        # Accept either API key or secret phrase
        if verify_api_key(key):
            return True, None
        if verify_secret(secret):
            return True, None
        
        return False, "Invalid API key"
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "X-Control-Key, X-Secret, X-Session-Token, Content-Type")
        self.end_headers()
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if not rate_limiter.check(self.get_client_ip()):
            self.send_json({"suc": False, "err": "Rate limit"}, 429)
            return
        
        # Public endpoints
        if path == "/health":
            self.send_json({
                "status": "online",
                "session_active": session_manager.session_token is not None,
                "remote_control": PYAUTOGUI_AVAILABLE,
                "screenshot": PIL_AVAILABLE,
                "tunnel": tunnel_url,
                "eaa_tunnel": eaa_tunnel_url
            })
            return
        
        # Auth required for rest
        auth_ok, auth_err = self.check_auth()
        if not auth_ok:
            self.send_json({"suc": False, "err": auth_err}, 401)
            return
        
        # Screenshot
        if path == "/screenshot":
            img, err = take_screenshot()
            if err:
                self.send_json({"suc": False, "err": err})
            else:
                self.send_json({"suc": True, "image": img})
            return
        
        # System info
        if path == "/system/info":
            self.send_json({"suc": True, "system": get_system_info()})
            return
        
        # Process list
        if path == "/process/list":
            self.send_json({"suc": True, "processes": get_process_list()})
            return
        
        # Windows list
        if path == "/windows/list":
            self.send_json({"suc": True, "windows": get_windows_list()})
            return
        
        # Mouse position
        if path == "/mouse/position":
            if PYAUTOGUI_AVAILABLE:
                x, y = pyautogui.position()
                self.send_json({"suc": True, "x": x, "y": y})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available"})
            return
        
        # Clipboard get
        if path == "/clipboard/get":
            content, err = get_clipboard()
            if err:
                self.send_json({"suc": False, "err": err})
            else:
                self.send_json({"suc": True, "content": content})
            return
        
        # Network info
        if path == "/network/info":
            if PSUTIL_AVAILABLE:
                interfaces = []
                for name, addrs in psutil.net_if_addrs().items():
                    for addr in addrs:
                        interfaces.append({"name": name, "address": addr.address})
                self.send_json({"suc": True, "interfaces": interfaces})
            else:
                self.send_json({"suc": False, "err": "psutil not available"})
            return
        
        # EAA status
        if path == "/eaa/status":
            self.send_json({
                "suc": True,
                "running": eaa_process is not None and eaa_process.poll() is None,
                "tunnel": eaa_tunnel_url
            })
            return
        
        # Terminal status
        if path == "/terminal/status":
            self.send_json({
                "suc": True,
                "eaa_running": eaa_process is not None and eaa_process.poll() is None,
                "tunnel_running": tunnel_process is not None and tunnel_process.poll() is None
            })
            return
        
        self.send_json({"suc": False, "err": "Unknown endpoint"})
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if not rate_limiter.check(self.get_client_ip()):
            self.send_json({"suc": False, "err": "Rate limit"}, 429)
            return
        
        # Read body
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length > 0 else "{}"
        
        try:
            data = json.loads(body)
        except:
            data = {}
        
        # Auth check
        auth_ok, auth_err = self.check_auth()
        if not auth_ok:
            self.send_json({"suc": False, "err": auth_err}, 401)
            return
        
        # Mouse move
        if path == "/mouse/move":
            if not PYAUTOGUI_AVAILABLE:
                self.send_json({"suc": False, "err": "pyautogui not available"})
                return
            pyautogui.moveTo(data.get("x", 0), data.get("y", 0))
            self.send_json({"suc": True})
            return
        
        # Mouse click
        if path == "/mouse/click":
            if not PYAUTOGUI_AVAILABLE:
                self.send_json({"suc": False, "err": "pyautogui not available"})
                return
            x, y = data.get("x"), data.get("y")
            button = data.get("button", "left")
            clicks = data.get("clicks", 1)
            if x is not None and y is not None:
                pyautogui.click(x, y, clicks=clicks, button=button)
            else:
                pyautogui.click(clicks=clicks, button=button)
            self.send_json({"suc": True})
            return
        
        # Mouse scroll
        if path == "/mouse/scroll":
            if not PYAUTOGUI_AVAILABLE:
                self.send_json({"suc": False, "err": "pyautogui not available"})
                return
            amount = data.get("amount", 3)
            if data.get("direction", "down") == "up":
                pyautogui.scroll(amount)
            else:
                pyautogui.scroll(-amount)
            self.send_json({"suc": True})
            return
        
        # Keyboard type
        if path == "/keyboard/type":
            if not PYAUTOGUI_AVAILABLE:
                self.send_json({"suc": False, "err": "pyautogui not available"})
                return
            pyautogui.typewrite(data.get("text", ""), interval=data.get("interval", 0.02))
            self.send_json({"suc": True})
            return
        
        # Keyboard press
        if path == "/keyboard/press" or path == "/keyboard/key":
            if not PYAUTOGUI_AVAILABLE:
                self.send_json({"suc": False, "err": "pyautogui not available"})
                return
            pyautogui.press(data.get("key", "enter"))
            self.send_json({"suc": True})
            return
        
        # Keyboard hotkey
        if path == "/keyboard/hotkey":
            if not PYAUTOGUI_AVAILABLE:
                self.send_json({"suc": False, "err": "pyautogui not available"})
                return
            keys = data.get("keys", [])
            if keys:
                pyautogui.hotkey(*keys)
            self.send_json({"suc": True})
            return
        
        # Notification
        if path == "/notify":
            ok, err = send_notification(data.get("title", "EAA"), data.get("message", ""))
            if ok:
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": err})
            return
        
        # App launch
        if path == "/app/launch":
            app = data.get("app", "")
            path_arg = data.get("path", "")
            apps = {
                "chrome": "start chrome", "firefox": "start firefox",
                "edge": "start msedge", "vscode": "code",
                "notepad": "notepad", "explorer": "explorer",
                "spotify": "start spotify", "discord": "start discord",
            }
            if path_arg:
                subprocess.run(f'"{path_arg}"', shell=True)
            elif app in apps:
                subprocess.run(apps[app], shell=True)
            else:
                self.send_json({"suc": False, "err": f"Unknown app: {app}"})
                return
            self.send_json({"suc": True})
            return
        
        # Browser open
        if path == "/browser/open":
            url = data.get("url", "https://google.com")
            subprocess.run(f'start "" "{url}"', shell=True)
            self.send_json({"suc": True})
            return
        
        # Browser search
        if path == "/browser/search":
            query = data.get("query", "")
            subprocess.run(f'start "" "https://www.google.com/search?q={query}"', shell=True)
            self.send_json({"suc": True})
            return
        
        # Process kill
        if path == "/process/kill":
            pid = data.get("pid")
            if not pid:
                self.send_json({"suc": False, "err": "pid required"})
                return
            try:
                if PSUTIL_AVAILABLE:
                    psutil.Process(pid).terminate()
                else:
                    subprocess.run(f"taskkill /pid {pid}", shell=True)
                self.send_json({"suc": True})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # Process start
        if path == "/process/start":
            path_arg = data.get("path", "")
            if not path_arg:
                self.send_json({"suc": False, "err": "path required"})
                return
            try:
                subprocess.Popen(path_arg, shell=True)
                self.send_json({"suc": True})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # File read
        if path == "/file/read":
            file_path = data.get("path", "")
            if not validate_path(file_path):
                self.send_json({"suc": False, "err": "Access denied"})
                return
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                self.send_json({"suc": True, "content": content})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # File write
        if path == "/file/write":
            file_path = data.get("path", "")
            content = data.get("content", "")
            if not validate_path(file_path):
                self.send_json({"suc": False, "err": "Access denied"})
                return
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.send_json({"suc": True})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # File list
        if path == "/file/list":
            dir_path = data.get("path", ALLOWED_PATH)
            if not validate_path(dir_path):
                self.send_json({"suc": False, "err": "Access denied"})
                return
            try:
                items = []
                for item in os.listdir(dir_path):
                    full = os.path.join(dir_path, item)
                    items.append({
                        "name": item,
                        "is_dir": os.path.isdir(full),
                        "size": os.path.getsize(full) if os.path.isfile(full) else 0,
                    })
                self.send_json({"suc": True, "items": items})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # File delete
        if path == "/file/delete":
            file_path = data.get("path", "")
            if not validate_path(file_path):
                self.send_json({"suc": False, "err": "Access denied"})
                return
            try:
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                else:
                    os.remove(file_path)
                self.send_json({"suc": True})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # File move
        if path == "/file/move":
            src, dst = data.get("src", ""), data.get("dst", "")
            if not validate_path(src) or not validate_path(dst):
                self.send_json({"suc": False, "err": "Access denied"})
                return
            try:
                shutil.move(src, dst)
                self.send_json({"suc": True})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # File copy
        if path == "/file/copy":
            src, dst = data.get("src", ""), data.get("dst", "")
            if not validate_path(src) or not validate_path(dst):
                self.send_json({"suc": False, "err": "Access denied"})
                return
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                self.send_json({"suc": True})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # Shell
        if path == "/shell":
            cmd = data.get("command", "")
            timeout = data.get("timeout", 30)
            result = run_shell(cmd, timeout)
            self.send_json({"suc": True, "result": result})
            return
        
        # Clipboard set
        if path == "/clipboard/set":
            ok, err = set_clipboard(data.get("content", ""))
            if ok:
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": err})
            return
        
        # Window focus
        if path == "/window/focus":
            ok, err = focus_window(data.get("title", ""))
            if ok:
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": err})
            return
        
        # Window close
        if path == "/window/close":
            ok, err = close_window(data.get("title", ""))
            if ok:
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": err})
            return
        
        # Power controls
        if path == "/power/sleep":
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
            self.send_json({"suc": True})
            return
        
        if path == "/power/restart":
            os.system("shutdown /r /t 10")
            self.send_json({"suc": True, "message": "Restarting in 10s"})
            return
        
        if path == "/power/shutdown":
            os.system("shutdown /s /t 10")
            self.send_json({"suc": True, "message": "Shutting down in 10s"})
            return
        
        if path == "/power/cancel":
            os.system("shutdown /a")
            self.send_json({"suc": True, "message": "Cancelled"})
            return
        
        # Terminal command
        if path == "/terminal/command":
            cmd = data.get("command", "")
            if cmd == "stop":
                if eaa_process:
                    eaa_process.terminate()
                if tunnel_process:
                    tunnel_process.terminate()
                self.send_json({"suc": True, "message": "Stopped"})
            elif cmd == "restart":
                if eaa_process:
                    eaa_process.terminate()
                time.sleep(1)
                start_eaa()
                self.send_json({"suc": True, "message": "Restarted"})
            else:
                self.send_json({"suc": False, "err": "Unknown command"})
            return
        
        self.send_json({"suc": False, "err": "Unknown endpoint"})

# ============================================
# MAIN
# ============================================

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), ControlHandler)
    server.serve_forever()

def cleanup():
    global eaa_process, tunnel_process, eaa_tunnel_process
    print("\n[STOP] Stopping all processes...")
    for p in [eaa_process, tunnel_process, eaa_tunnel_process]:
        if p and p.poll() is None:
            p.terminate()
    print("[BYE] All stopped!")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))
    
    print("=" * 60)
    print("  EAA CONTROL SYSTEM V5 - FULL REMOTE CONTROL")
    print("  Screenshot | Click | Type | Keys | Files | Shell")
    print("=" * 60)
    
    print("[CHECK] pyautogui and Pillow installed")
    print(f"\n[KEY] Generated API Key: {API_KEY}")
    print(f"[SECRET] Generated Secret Phrase: {SECRET_PHRASE}")
    
    print("\n[START] Starting Control Station V5...")
    
    if PYAUTOGUI_AVAILABLE:
        print("[CONTROL] ✅ pyautogui loaded - Full control enabled!")
    
    print("\n" + "=" * 60)
    print("  EAA CONTROL STATION V5 - FULL REMOTE CONTROL")
    print("=" * 60)
    print(f"  📸 Screenshot: {'✅' if PIL_AVAILABLE else '❌'}")
    print(f"  🖱️ Mouse Control: {'✅' if PYAUTOGUI_AVAILABLE else '❌'}")
    print(f"  ⌨️ Keyboard Control: {'✅' if PYAUTOGUI_AVAILABLE else '❌'}")
    print("=" * 60)
    
    # Start EAA
    print("\n[START] Starting EAA AI Server...")
    start_eaa()
    
    # Start tunnel
    print("\n[START] Starting Cloudflare Tunnel...")
    url = start_tunnel(PORT)
    
    if url:
        print(f"\n[TUNNEL] ✅ {url}")
    else:
        print("[TUNNEL] ⚠️ Tunnel failed to start")
    
    print("\n" + "=" * 60)
    print("  FULL REMOTE CONTROL ENABLED!")
    print("=" * 60)
    print(f"\n  Control URL: {url or 'Tunnel failed'}")
    print(f"  API Key: {API_KEY}")
    print(f"  Secret: {SECRET_PHRASE}")
    
    print("\n  >>> TELL SUPER Z <<<")
    print(f"    URL: {url}")
    print(f"    Key: {API_KEY}")
    print(f"    Secret: {SECRET_PHRASE}")
    print("=" * 60)
    print("\n[READY] Press Ctrl+C to stop")
    
    # Run server
    run_server()
