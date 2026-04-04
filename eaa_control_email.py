"""
EAA CONTROL SYSTEM - BULLETPROOF WITH EMAIL NOTIFICATIONS
==========================================================
NEVER CRASHES - AUTO-RESTART - EMAIL ALERTS
- Screenshot, Mouse, Keyboard control
- File operations, Shell access
- System monitoring, Process management
- EAA AI integration with AUTO-RESTART
- Auto-restart tunnel if it dies
- EMAIL notification when tunnel restarts (new URL + credentials)
- Watchdog monitors everything
- Can restart EAA brains remotely
- Session token security
- Comprehensive error handling EVERYWHERE

Auth: X-Control-Key header OR X-Secret header OR JSON body
"""

import os
import sys
import time
import secrets
import threading
import subprocess
import json
import base64
import traceback
import re
import io
import shutil
import signal
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import urllib.request
import urllib.error

# ============================================
# EMAIL CONFIGURATION
# ============================================

EMAIL_ENABLED = True
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_FROM = "majed1.alshoghri@gmail.com"
EMAIL_TO = "majed1.alshoghri@gmail.com"
EMAIL_PASSWORD = "vqgeblnuxfqsxbxn"  # Gmail App Password

def send_email_notification(subject, body):
    """Send email notification - never crashes server"""
    if not EMAIL_ENABLED:
        return False
    
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        log(f"[EMAIL] Sent: {subject}")
        return True
    except Exception as e:
        log(f"[EMAIL] Failed: {e}")
        return False

def send_tunnel_notification(url, api_key, secret, reason="Tunnel Restarted"):
    """Send email with new tunnel credentials"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    subject = f"EAA Control - {reason}"
    
    body = f"""
{'='*50}
   EAA CONTROL SYSTEM - NOTIFICATION
{'='*50}

{reason.upper()}

{'='*50}
   NEW CONNECTION INFO
{'='*50}

URL: {url}
API Key: {api_key}
Secret: {secret}

{'='*50}
   COPY THIS TO SUPER Z:
{'='*50}

URL: {url}
Key: {api_key}
Secret: {secret}

Timestamp: {timestamp}

Your AI assistant Super Z needs this to reconnect!
{'='*50}
"""
    
    return send_email_notification(subject, body)

def send_startup_notification(url, api_key, secret):
    """Send email on server startup"""
    return send_tunnel_notification(url, api_key, secret, "Server Started")

# ============================================
# BULLETPROOF SETTINGS
# ============================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(SCRIPT_DIR, "tools")
CLOUDFLARED_PATH = os.path.join(TOOLS_DIR, "cloudflared.exe")
ALLOWED_PATH = r"C:\Users\offic"
PORT = 8001
EAA_SCRIPT = os.path.join(SCRIPT_DIR, "run_eaa_agent_v3.py")
EAA_BACKEND_URL = "http://localhost:8000"

# Auto-restart settings
EAA_AUTO_RESTART = True
TUNNEL_AUTO_RESTART = True
WATCHDOG_INTERVAL = 10  # Check every 10 seconds

# Generate credentials
API_KEY = secrets.token_urlsafe(32)
SECRET_PHRASE = secrets.choice([
    "alpha-bravo-charlie", "delta-echo-foxtrot", "golf-hotel-india",
    "juliet-kilo-lima", "mike-november-oscar", "papa-quebec-romeo",
    "sierra-tango-uniform", "victor-whiskey-xray", "yankee-zulu-alpha"
])

# Session
SESSION_TIMEOUT = 60  # 1 minute timeout (easier to reconnect)
session_token = None
session_time = 0

# ============================================
# LOG CAPTURE - SEE EVERYTHING
# ============================================

class LogCapture:
    def __init__(self):
        self.logs = []
        self.lock = threading.Lock()
        self.max_lines = 1000
    
    def add(self, line):
        try:
            with self.lock:
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.logs.append(f"[{timestamp}] {line}")
                if len(self.logs) > self.max_lines:
                    self.logs = self.logs[-self.max_lines:]
        except:
            pass
    
    def get(self, last_n=200):
        try:
            with self.lock:
                return "\n".join(self.logs[-last_n:])
        except:
            return ""
    
    def clear(self):
        try:
            with self.lock:
                self.logs = []
        except:
            pass

log_capture = LogCapture()

def log(msg):
    """Print and capture - NEVER fails"""
    try:
        print(msg)
    except:
        pass
    try:
        log_capture.add(msg)
    except:
        pass

# ============================================
# DEPENDENCIES - SAFE LOADING
# ============================================

HAS_PYAUTOGUI = False
HAS_PIL = False
HAS_PSUTIL = False
HAS_WIN32 = False
HAS_WIN32GUI = False

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    HAS_PYAUTOGUI = True
    log("[OK] pyautogui loaded")
except Exception as e:
    log(f"[WARN] pyautogui not available: {e}")

try:
    from PIL import Image
    HAS_PIL = True
    log("[OK] Pillow loaded")
except Exception as e:
    log(f"[WARN] Pillow not available: {e}")

try:
    import psutil
    HAS_PSUTIL = True
    log("[OK] psutil loaded")
except Exception as e:
    log(f"[WARN] psutil not available: {e}")

try:
    import win32clipboard
    import win32con
    HAS_WIN32 = True
except:
    pass

try:
    import win32gui
    import win32api
    HAS_WIN32GUI = True
except:
    pass

# ============================================
# GLOBAL STATE - THREAD SAFE
# ============================================

class ServerState:
    """Thread-safe state management"""
    def __init__(self):
        self._lock = threading.Lock()
        self._eaa_process = None
        self._eaa_pid = None
        self._tunnel_process = None
        self._tunnel_url = None
        self._scheduled_tasks = []
        self._running = True
    
    @property
    def eaa_process(self):
        with self._lock:
            return self._eaa_process
    
    @eaa_process.setter
    def eaa_process(self, val):
        with self._lock:
            self._eaa_process = val
            if val:
                try:
                    self._eaa_pid = val.pid
                except:
                    pass
    
    @property
    def eaa_pid(self):
        with self._lock:
            return self._eaa_pid
    
    @property
    def tunnel_process(self):
        with self._lock:
            return self._tunnel_process
    
    @tunnel_process.setter
    def tunnel_process(self, val):
        with self._lock:
            self._tunnel_process = val
    
    @property
    def tunnel_url(self):
        with self._lock:
            return self._tunnel_url
    
    @tunnel_url.setter
    def tunnel_url(self, val):
        with self._lock:
            self._tunnel_url = val
    
    @property
    def scheduled_tasks(self):
        with self._lock:
            return self._scheduled_tasks.copy()
    
    def add_task(self, task):
        with self._lock:
            self._scheduled_tasks.append(task)
    
    def remove_task(self, name):
        with self._lock:
            self._scheduled_tasks = [t for t in self._scheduled_tasks if t.get("name") != name]
    
    @property
    def running(self):
        with self._lock:
            return self._running
    
    @running.setter
    def running(self, val):
        with self._lock:
            self._running = val
    
    def eaa_is_alive(self):
        """Check if EAA is running"""
        with self._lock:
            if self._eaa_process is None:
                return False
            try:
                return self._eaa_process.poll() is None
            except:
                return False
    
    def tunnel_is_alive(self):
        """Check if tunnel is running"""
        with self._lock:
            if self._tunnel_process is None:
                return False
            try:
                return self._tunnel_process.poll() is None
            except:
                return False

state = ServerState()

# ============================================
# RATE LIMITER
# ============================================

class RateLimiter:
    def __init__(self, max_req=200, window=60):
        self.max_req = max_req
        self.window = window
        self.requests = {}
        self.lock = threading.Lock()
    
    def check(self, ip):
        try:
            with self.lock:
                now = time.time()
                if ip not in self.requests:
                    self.requests[ip] = []
                self.requests[ip] = [t for t in self.requests[ip] if now - t < self.window]
                if len(self.requests[ip]) >= self.max_req:
                    return False
                self.requests[ip].append(now)
                return True
        except:
            return True

rate_limiter = RateLimiter()

# ============================================
# HELPER FUNCTIONS - ALL SAFE
# ============================================

def verify_api_key(key):
    try:
        if not key:
            return False
        import hmac
        return hmac.compare_digest(str(key), str(API_KEY))
    except:
        return False

def verify_secret(secret):
    try:
        return str(secret) == str(SECRET_PHRASE)
    except:
        return False

def validate_path(path):
    try:
        if not path:
            return False
        abs_path = os.path.abspath(path)
        return abs_path.startswith(ALLOWED_PATH)
    except:
        return False

def check_session_timeout():
    global session_token, session_time
    try:
        if session_token and SESSION_TIMEOUT > 0:
            if time.time() - session_time > SESSION_TIMEOUT:
                session_token = None
                log("[SESSION] Timeout - session cleared")
    except:
        pass

def safe_take_screenshot():
    """Screenshot that never crashes"""
    if not HAS_PYAUTOGUI or not HAS_PIL:
        return None, "Dependencies not available"
    try:
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode(), None
    except Exception as e:
        return None, str(e)

def safe_get_system_info():
    try:
        info = {"timestamp": datetime.now().isoformat()}
        if HAS_PSUTIL:
            try:
                info["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            except:
                info["cpu_percent"] = 0
            try:
                info["ram_percent"] = psutil.virtual_memory().percent
            except:
                info["ram_percent"] = 0
            try:
                info["disk_percent"] = psutil.disk_usage('C:\\').percent
            except:
                info["disk_percent"] = 0
            try:
                info["uptime"] = int(time.time() - psutil.boot_time())
            except:
                info["uptime"] = 0
        return info
    except:
        return {"timestamp": datetime.now().isoformat()}

def safe_get_processes():
    if not HAS_PSUTIL:
        return []
    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                procs.append({
                    "pid": p.info['pid'],
                    "name": p.info.get('name', 'unknown'),
                    "cpu": round(p.info.get('cpu_percent') or 0, 1),
                    "memory": round(p.info.get('memory_percent') or 0, 1),
                })
            except:
                pass
        return sorted(procs, key=lambda x: x['cpu'], reverse=True)[:50]
    except:
        return []

def safe_get_windows():
    if not HAS_WIN32GUI:
        return []
    try:
        windows = []
        def enum_cb(hwnd, ctx):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title:
                        windows.append({
                            "hwnd": hwnd,
                            "title": title,
                            "active": hwnd == win32gui.GetForegroundWindow()
                        })
            except:
                pass
        win32gui.EnumWindows(enum_cb, None)
        return windows
    except:
        return []

def safe_get_clipboard():
    if not HAS_WIN32:
        return None, "win32 not available"
    try:
        win32clipboard.OpenClipboard()
        data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()
        return data, None
    except Exception as e:
        try:
            win32clipboard.CloseClipboard()
        except:
            pass
        return None, str(e)

def safe_set_clipboard(content):
    if not HAS_WIN32:
        return False, "win32 not available"
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(str(content), win32con.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()
        return True, None
    except Exception as e:
        try:
            win32clipboard.CloseClipboard()
        except:
            pass
        return False, str(e)

def safe_run_shell(cmd, timeout=60, cwd=None):
    """Shell command that never crashes the server"""
    try:
        result = subprocess.run(
            str(cmd), shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd or ALLOWED_PATH
        )
        log(f"[SHELL] {cmd[:50]}... -> {result.returncode}")
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Timeout", "returncode": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1}

# ============================================
# EAA MANAGEMENT - NEVER FAILS
# ============================================

def start_eaa():
    """Start EAA - returns PID or None"""
    try:
        if not os.path.exists(EAA_SCRIPT):
            log(f"[EAA] Script not found: {EAA_SCRIPT}")
            return None
        
        # Kill any existing EAA
        stop_eaa()
        time.sleep(1)
        
        state.eaa_process = subprocess.Popen(
            [sys.executable, EAA_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=SCRIPT_DIR
        )
        
        log(f"[EAA] Started (PID: {state.eaa_pid})")
        
        # Start output reader
        threading.Thread(target=read_eaa_output, daemon=True).start()
        
        return state.eaa_pid
    except Exception as e:
        log(f"[EAA] Failed to start: {e}")
        return None

def stop_eaa():
    """Stop EAA - always succeeds"""
    try:
        proc = state.eaa_process
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except:
                try:
                    proc.kill()
                except:
                    pass
            state.eaa_process = None
            log("[EAA] Stopped")
    except Exception as e:
        log(f"[EAA] Stop error (ignored): {e}")

def restart_eaa():
    """Restart EAA"""
    log("[EAA] Restarting...")
    stop_eaa()
    time.sleep(2)
    return start_eaa()

def read_eaa_output():
    """Read EAA output - never crashes"""
    while state.running:
        try:
            proc = state.eaa_process
            if proc and proc.poll() is None:
                line = proc.stdout.readline()
                if line:
                    log(f"[EAA] {line.strip()}")
            else:
                time.sleep(1)
        except:
            time.sleep(1)

# ============================================
# TUNNEL MANAGEMENT - NEVER FAILS
# ============================================

def start_tunnel():
    """Start tunnel - returns URL or None"""
    try:
        if not os.path.exists(CLOUDFLARED_PATH):
            log(f"[TUNNEL] cloudflared not found: {CLOUDFLARED_PATH}")
            return None
        
        # Kill existing tunnel
        stop_tunnel()
        time.sleep(1)
        
        state.tunnel_process = subprocess.Popen(
            [CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{PORT}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # Wait for URL
        for _ in range(30):
            try:
                line = state.tunnel_process.stdout.readline()
                if "trycloudflare.com" in line:
                    match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
                    if match:
                        state.tunnel_url = match.group(0)
                        log(f"[TUNNEL] Started: {state.tunnel_url}")
                        
                        # SEND EMAIL NOTIFICATION!
                        threading.Thread(
                            target=send_tunnel_notification,
                            args=(state.tunnel_url, API_KEY, SECRET_PHRASE, "Tunnel Restarted"),
                            daemon=True
                        ).start()
                        
                        return state.tunnel_url
            except:
                pass
        
        log("[TUNNEL] Failed to get URL")
        return None
    except Exception as e:
        log(f"[TUNNEL] Failed to start: {e}")
        return None

def stop_tunnel():
    """Stop tunnel - always succeeds"""
    try:
        proc = state.tunnel_process
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except:
                try:
                    proc.kill()
                except:
                    pass
            state.tunnel_process = None
            state.tunnel_url = None
            log("[TUNNEL] Stopped")
    except Exception as e:
        log(f"[TUNNEL] Stop error (ignored): {e}")

def restart_tunnel():
    """Restart tunnel"""
    log("[TUNNEL] Restarting...")
    stop_tunnel()
    time.sleep(2)
    return start_tunnel()

# ============================================
# WATCHDOG - KEEPS EVERYTHING ALIVE
# ============================================

def watchdog():
    """Monitor and auto-restart EAA and tunnel"""
    log("[WATCHDOG] Started")
    
    while state.running:
        try:
            # Check EAA
            if EAA_AUTO_RESTART and not state.eaa_is_alive():
                log("[WATCHDOG] EAA died - restarting...")
                start_eaa()
            
            # Check tunnel
            if TUNNEL_AUTO_RESTART and not state.tunnel_is_alive():
                log("[WATCHDOG] Tunnel died - restarting...")
                start_tunnel()  # This sends email notification!
            
            # Check scheduled tasks
            check_scheduled_tasks()
            
        except Exception as e:
            log(f"[WATCHDOG] Error (ignored): {e}")
        
        time.sleep(WATCHDOG_INTERVAL)

def check_scheduled_tasks():
    """Run scheduled tasks when time comes"""
    try:
        now = datetime.now()
        for task in state.scheduled_tasks:
            try:
                exec_time = datetime.fromisoformat(task.get("time", ""))
                if now >= exec_time and not task.get("executed"):
                    cmd = task.get("command", "")
                    safe_run_shell(cmd)
                    task["executed"] = True
                    log(f"[SCHEDULE] Executed: {task.get('name')}")
            except:
                pass
    except:
        pass

# ============================================
# REQUEST HANDLER - BULLETPROOF
# ============================================

class BulletproofHandler(BaseHTTPRequestHandler):
    """Handler that NEVER crashes"""
    
    def log_message(self, fmt, *args):
        try:
            msg = str(args[0]) if args else str(fmt)
            log(f"[HTTP] {msg[:100]}")
        except:
            pass
    
    def send_json(self, data, status=200):
        try:
            body = json.dumps(data, indent=2).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            log(f"[HTTP] Send error: {e}")
    
    def get_client_ip(self):
        try:
            return self.client_address[0]
        except:
            return "unknown"
    
    def check_auth(self, data=None):
        """Auth check - never fails"""
        global session_token, session_time
        
        try:
            check_session_timeout()
            
            # Get credentials from headers or body
            key = self.headers.get("X-Control-Key", "")
            secret = self.headers.get("X-Secret", "")
            provided_session = self.headers.get("X-Session-Token", "")
            
            if not key and not secret and data:
                key = data.get("api_key", "")
                secret = data.get("secret", "")
                provided_session = data.get("session_token", "")
            
            # Verify
            auth_valid = verify_api_key(key) or verify_secret(secret)
            
            if not auth_valid:
                return False, "Invalid API key", None
            
            # Session logic
            if session_token is None:
                session_token = "SESS_" + secrets.token_urlsafe(32)
                session_time = time.time()
                log(f"[SESSION] Created: {session_token[:15]}...")
                return True, None, session_token
            
            if provided_session == session_token:
                session_time = time.time()
                return True, None, session_token
            
            return False, "Session locked by another user", session_token  # Return current token so they know
            
        except Exception as e:
            log(f"[AUTH] Error: {e}")
            return False, str(e), None
    
    def do_OPTIONS(self):
        try:
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "X-Control-Key, X-Secret, X-Session-Token, Content-Type")
            self.end_headers()
        except:
            pass
    
    def do_GET(self):
        try:
            self._handle_request("GET")
        except Exception as e:
            log(f"[GET] Error: {e}")
            try:
                self.send_json({"suc": False, "err": str(e)}, 500)
            except:
                pass
    
    def do_POST(self):
        try:
            self._handle_request("POST")
        except Exception as e:
            log(f"[POST] Error: {e}")
            try:
                self.send_json({"suc": False, "err": str(e)}, 500)
            except:
                pass
    
    def _handle_request(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if not rate_limiter.check(self.get_client_ip()):
            self.send_json({"suc": False, "err": "Rate limit"}, 429)
            return
        
        # Read body for POST
        data = {}
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode() if length > 0 else "{}"
                data = json.loads(body)
            except:
                data = {}
        
        # === PUBLIC ENDPOINTS ===
        
        if path == "/health":
            self.send_json({
                "status": "online",
                "session_active": session_token is not None,
                "eaa_running": state.eaa_is_alive(),
                "tunnel_running": state.tunnel_is_alive(),
                "tunnel_url": state.tunnel_url,
                "remote_control": HAS_PYAUTOGUI,
                "screenshot": HAS_PIL
            })
            return
        
        # === AUTH ENDPOINT ===
        
        if path == "/auth" or path == "/authenticate":
            auth_ok, auth_err, sess = self.check_auth(data)
            if auth_ok:
                self.send_json({"suc": True, "session_token": sess})
            else:
                status = 401 if "Invalid" in str(auth_err) else 423
                self.send_json({"suc": False, "err": auth_err, "session_token": sess}, status)
            return
        
        # === AUTH REQUIRED ===
        
        auth_ok, auth_err, sess = self.check_auth(data)
        if not auth_ok:
            status = 401 if "Invalid" in str(auth_err) else 423
            self.send_json({"suc": False, "err": auth_err, "session_token": sess}, status)
            return
        
        resp = {"session_token": sess}
        
        # SCREENSHOT
        if path in ["/screenshot", "/screen"]:
            img, err = safe_take_screenshot()
            if err:
                self.send_json({"suc": False, "err": err, **resp})
            else:
                self.send_json({"suc": True, "image": img, **resp})
            return
        
        # SCREEN SIZE
        if path == "/screen/size":
            if HAS_PYAUTOGUI:
                try:
                    w, h = pyautogui.size()
                    self.send_json({"suc": True, "width": w, "height": h, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **resp})
            return
        
        # SYSTEM INFO
        if path == "/system/info":
            self.send_json({"suc": True, "system": safe_get_system_info(), **resp})
            return
        
        # PROCESS LIST
        if path == "/process/list":
            self.send_json({"suc": True, "processes": safe_get_processes(), **resp})
            return
        
        # WINDOWS LIST
        if path == "/windows/list":
            self.send_json({"suc": True, "windows": safe_get_windows(), **resp})
            return
        
        # MOUSE POSITION
        if path == "/mouse/position":
            if HAS_PYAUTOGUI:
                try:
                    x, y = pyautogui.position()
                    self.send_json({"suc": True, "x": x, "y": y, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **resp})
            return
        
        # CLIPBOARD GET
        if path == "/clipboard/get":
            content, err = safe_get_clipboard()
            if err:
                self.send_json({"suc": False, "err": err, **resp})
            else:
                self.send_json({"suc": True, "content": content, **resp})
            return
        
        # EAA STATUS
        if path == "/eaa/status":
            self.send_json({
                "suc": True,
                "running": state.eaa_is_alive(),
                "pid": state.eaa_pid,
                "tunnel": state.tunnel_url,
                **resp
            })
            return
        
        # TERMINAL OUTPUT - LOGS
        if path in ["/terminal/output", "/logs"]:
            self.send_json({
                "suc": True,
                "logs": log_capture.get(200),
                "eaa_running": state.eaa_is_alive(),
                "tunnel_running": state.tunnel_is_alive(),
                **resp
            })
            return
        
        # TERMINAL STATUS
        if path == "/terminal/status":
            self.send_json({
                "suc": True,
                "eaa_running": state.eaa_is_alive(),
                "eaa_pid": state.eaa_pid,
                "tunnel_running": state.tunnel_is_alive(),
                "tunnel_url": state.tunnel_url,
                **resp
            })
            return
        
        # SCHEDULE LIST
        if path == "/schedule/list":
            self.send_json({"suc": True, "tasks": state.scheduled_tasks, **resp})
            return
        
        # NETWORK INFO
        if path == "/network/info":
            if HAS_PSUTIL:
                try:
                    interfaces = []
                    for name, addrs in psutil.net_if_addrs().items():
                        for addr in addrs:
                            interfaces.append({"name": name, "address": addr.address})
                    self.send_json({"suc": True, "interfaces": interfaces, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "psutil not available", **resp})
            return
        
        # AI HEALTH
        if path == "/ai/health":
            try:
                req = urllib.request.urlopen(f"{EAA_BACKEND_URL}/ai/health", timeout=5)
                response = json.loads(req.read().decode())
                self.send_json({"suc": True, **response, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # AGENT TOOLS
        if path == "/v1/agent/tools":
            try:
                req = urllib.request.urlopen(f"{EAA_BACKEND_URL}/v1/agent/tools", timeout=10)
                response = json.loads(req.read().decode())
                self.send_json({**response, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # === POST-ONLY ENDPOINTS ===
        
        if method != "POST":
            self.send_json({"suc": False, "err": "Use POST", **resp})
            return
        
        # MOUSE MOVE
        if path in ["/mouse/move", "/mousemove"]:
            if HAS_PYAUTOGUI:
                try:
                    pyautogui.moveTo(data.get("x", 0), data.get("y", 0))
                    self.send_json({"suc": True, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **resp})
            return
        
        # MOUSE CLICK
        if path in ["/mouse/click", "/click"]:
            if HAS_PYAUTOGUI:
                try:
                    x, y = data.get("x"), data.get("y")
                    button = data.get("button", "left")
                    clicks = data.get("clicks", 1)
                    if x is not None and y is not None:
                        pyautogui.click(x, y, clicks=clicks, button=button)
                    else:
                        pyautogui.click(clicks=clicks, button=button)
                    log(f"[MOUSE] Click ({x},{y})")
                    self.send_json({"suc": True, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **resp})
            return
        
        # DOUBLE CLICK
        if path in ["/mouse/doubleclick", "/doubleclick"]:
            if HAS_PYAUTOGUI:
                try:
                    x, y = data.get("x"), data.get("y")
                    if x is not None and y is not None:
                        pyautogui.doubleClick(x, y)
                    else:
                        pyautogui.doubleClick()
                    self.send_json({"suc": True, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **resp})
            return
        
        # RIGHT CLICK
        if path in ["/mouse/rightclick", "/rightclick"]:
            if HAS_PYAUTOGUI:
                try:
                    x, y = data.get("x"), data.get("y")
                    if x is not None and y is not None:
                        pyautogui.rightClick(x, y)
                    else:
                        pyautogui.rightClick()
                    self.send_json({"suc": True, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **resp})
            return
        
        # SCROLL
        if path in ["/mouse/scroll", "/scroll"]:
            if HAS_PYAUTOGUI:
                try:
                    amount = data.get("amount", 3)
                    if data.get("direction", "down") == "up":
                        pyautogui.scroll(amount)
                    else:
                        pyautogui.scroll(-amount)
                    self.send_json({"suc": True, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **resp})
            return
        
        # KEYBOARD TYPE
        if path in ["/keyboard/type", "/type"]:
            if HAS_PYAUTOGUI:
                try:
                    text = str(data.get("text", ""))
                    pyautogui.typewrite(text, interval=data.get("interval", 0.02))
                    log(f"[KEYBOARD] Typed: {text[:30]}...")
                    self.send_json({"suc": True, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **resp})
            return
        
        # KEYBOARD PRESS
        if path in ["/keyboard/press", "/keyboard/key", "/key"]:
            if HAS_PYAUTOGUI:
                try:
                    key = str(data.get("key", "enter"))
                    pyautogui.press(key)
                    log(f"[KEYBOARD] Press: {key}")
                    self.send_json({"suc": True, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **resp})
            return
        
        # HOTKEY
        if path in ["/keyboard/hotkey", "/hotkey"]:
            if HAS_PYAUTOGUI:
                try:
                    keys = data.get("keys", [])
                    if keys:
                        pyautogui.hotkey(*keys)
                        log(f"[KEYBOARD] Hotkey: {'+'.join(keys)}")
                    self.send_json({"suc": True, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **resp})
            return
        
        # FILE READ
        if path in ["/file/read", "/read"]:
            file_path = data.get("path", "")
            if not validate_path(file_path):
                self.send_json({"suc": False, "err": "Access denied", **resp})
                return
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                self.send_json({"suc": True, "content": content, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # FILE WRITE
        if path in ["/file/write", "/write"]:
            file_path = data.get("path", "")
            content = data.get("content", "")
            if not validate_path(file_path):
                self.send_json({"suc": False, "err": "Access denied", **resp})
                return
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(str(content))
                log(f"[FILE] Wrote: {file_path}")
                self.send_json({"suc": True, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # FILE LIST
        if path in ["/file/list", "/list"]:
            dir_path = data.get("path", ALLOWED_PATH)
            if not validate_path(dir_path):
                self.send_json({"suc": False, "err": "Access denied", **resp})
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
                self.send_json({"suc": True, "items": items, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # FILE DELETE
        if path in ["/file/delete", "/delete"]:
            file_path = data.get("path", "")
            if not validate_path(file_path):
                self.send_json({"suc": False, "err": "Access denied", **resp})
                return
            try:
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                else:
                    os.remove(file_path)
                log(f"[FILE] Deleted: {file_path}")
                self.send_json({"suc": True, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # FILE MOVE
        if path in ["/file/move", "/move"]:
            src, dst = data.get("src", ""), data.get("dst", "")
            if not validate_path(src) or not validate_path(dst):
                self.send_json({"suc": False, "err": "Access denied", **resp})
                return
            try:
                shutil.move(src, dst)
                log(f"[FILE] Moved: {src} -> {dst}")
                self.send_json({"suc": True, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # FILE COPY
        if path in ["/file/copy", "/copy"]:
            src, dst = data.get("src", ""), data.get("dst", "")
            if not validate_path(src) or not validate_path(dst):
                self.send_json({"suc": False, "err": "Access denied", **resp})
                return
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                log(f"[FILE] Copied: {src} -> {dst}")
                self.send_json({"suc": True, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # SHELL
        if path in ["/shell", "/exec"]:
            cmd = data.get("command", "")
            timeout = data.get("timeout", 60)
            cwd = data.get("cwd")
            if cwd and not validate_path(cwd):
                cwd = None
            result = safe_run_shell(cmd, timeout, cwd)
            self.send_json({"suc": True, "result": result, **resp})
            return
        
        # CLIPBOARD SET
        if path == "/clipboard/set":
            ok, err = safe_set_clipboard(data.get("content", ""))
            if ok:
                self.send_json({"suc": True, **resp})
            else:
                self.send_json({"suc": False, "err": err, **resp})
            return
        
        # WINDOW FOCUS
        if path == "/window/focus":
            if HAS_WIN32GUI:
                try:
                    title = str(data.get("title", "")).lower()
                    def enum_cb(hwnd, ctx):
                        try:
                            if win32gui.IsWindowVisible(hwnd):
                                if title in win32gui.GetWindowText(hwnd).lower():
                                    win32gui.SetForegroundWindow(hwnd)
                        except:
                            pass
                    win32gui.EnumWindows(enum_cb, None)
                    log(f"[WINDOW] Focus: {title}")
                    self.send_json({"suc": True, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "win32 not available", **resp})
            return
        
        # WINDOW CLOSE
        if path == "/window/close":
            if HAS_WIN32GUI:
                try:
                    title = str(data.get("title", "")).lower()
                    def enum_cb(hwnd, ctx):
                        try:
                            if win32gui.IsWindowVisible(hwnd):
                                if title in win32gui.GetWindowText(hwnd).lower():
                                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                        except:
                            pass
                    win32gui.EnumWindows(enum_cb, None)
                    log(f"[WINDOW] Close: {title}")
                    self.send_json({"suc": True, **resp})
                except Exception as e:
                    self.send_json({"suc": False, "err": str(e), **resp})
            else:
                self.send_json({"suc": False, "err": "win32 not available", **resp})
            return
        
        # PROCESS KILL
        if path == "/process/kill":
            pid = data.get("pid")
            if not pid:
                self.send_json({"suc": False, "err": "pid required", **resp})
                return
            try:
                if HAS_PSUTIL:
                    psutil.Process(int(pid)).terminate()
                else:
                    subprocess.run(f"taskkill /pid {pid} /f", shell=True)
                log(f"[PROCESS] Killed: {pid}")
                self.send_json({"suc": True, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # PROCESS/APP START
        if path in ["/process/start", "/app/launch"]:
            path_arg = data.get("path", "") or data.get("app", "")
            if not path_arg:
                self.send_json({"suc": False, "err": "path/app required", **resp})
                return
            apps = {
                "chrome": "start chrome", "firefox": "start firefox",
                "edge": "start msedge", "vscode": "code",
                "notepad": "notepad", "explorer": "explorer",
                "spotify": "start spotify", "discord": "start discord",
                "calculator": "calc", "paint": "mspaint",
            }
            cmd = apps.get(str(path_arg).lower(), f'"{path_arg}"')
            try:
                subprocess.Popen(cmd, shell=True)
                log(f"[PROCESS] Started: {path_arg}")
                self.send_json({"suc": True, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # BROWSER OPEN
        if path == "/browser/open":
            try:
                url = data.get("url", "https://google.com")
                subprocess.run(f'start "" "{url}"', shell=True)
                log(f"[BROWSER] Open: {url}")
                self.send_json({"suc": True, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # BROWSER SEARCH
        if path == "/browser/search":
            try:
                query = data.get("query", "")
                subprocess.run(f'start "" "https://www.google.com/search?q={query}"', shell=True)
                log(f"[BROWSER] Search: {query}")
                self.send_json({"suc": True, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # NOTIFICATION
        if path == "/notify":
            try:
                title = str(data.get("title", "EAA"))
                message = str(data.get("message", ""))
                ps_cmd = f'''
                Add-Type -AssemblyName System.Windows.Forms
                [System.Windows.Forms.MessageBox]::Show("{message}", "{title}")
                '''
                subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=10)
                log(f"[NOTIFY] {title}: {message}")
                self.send_json({"suc": True, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # SCHEDULE ADD
        if path == "/schedule/add":
            name = data.get("name", f"task_{int(time.time())}")
            exec_time = data.get("time", "")
            command = data.get("command", "")
            if not exec_time or not command:
                self.send_json({"suc": False, "err": "time and command required", **resp})
                return
            task = {"name": name, "time": exec_time, "command": command, "executed": False}
            state.add_task(task)
            log(f"[SCHEDULE] Added: {name}")
            self.send_json({"suc": True, "task": task, **resp})
            return
        
        # SCHEDULE REMOVE
        if path == "/schedule/remove":
            name = data.get("name", "")
            state.remove_task(name)
            self.send_json({"suc": True, **resp})
            return
        
        # === EAA CONTROL ENDPOINTS ===
        
        # START EAA
        if path == "/eaa/start":
            pid = start_eaa()
            if pid:
                self.send_json({"suc": True, "pid": pid, **resp})
            else:
                self.send_json({"suc": False, "err": "Failed to start EAA", **resp})
            return
        
        # STOP EAA
        if path == "/eaa/stop":
            stop_eaa()
            self.send_json({"suc": True, **resp})
            return
        
        # RESTART EAA
        if path in ["/eaa/restart", "/terminal/command"] and data.get("command") == "restart":
            pid = restart_eaa()
            if pid:
                self.send_json({"suc": True, "pid": pid, **resp})
            else:
                self.send_json({"suc": False, "err": "Failed to restart EAA", **resp})
            return
        
        # TERMINAL COMMAND
        if path == "/terminal/command":
            cmd = data.get("command", "")
            if cmd == "stop":
                stop_eaa()
                stop_tunnel()
                self.send_json({"suc": True, "message": "Stopped all", **resp})
            elif cmd == "restart":
                pid = restart_eaa()
                self.send_json({"suc": True, "pid": pid, **resp})
            elif cmd == "restart_tunnel":
                url = restart_tunnel()
                self.send_json({"suc": True, "url": url, **resp})
            else:
                self.send_json({"suc": False, "err": "Unknown command. Use: stop, restart, restart_tunnel", **resp})
            return
        
        # RESTART TUNNEL
        if path == "/tunnel/restart":
            url = restart_tunnel()
            if url:
                self.send_json({"suc": True, "url": url, **resp})
            else:
                self.send_json({"suc": False, "err": "Failed to restart tunnel", **resp})
            return
        
        # POWER ENDPOINTS
        if path == "/power/sleep":
            try:
                os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
                self.send_json({"suc": True, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        if path == "/power/restart":
            os.system("shutdown /r /t 10")
            log("[POWER] Restart in 10s")
            self.send_json({"suc": True, "message": "Restarting in 10s", **resp})
            return
        
        if path == "/power/shutdown":
            os.system("shutdown /s /t 10")
            log("[POWER] Shutdown in 10s")
            self.send_json({"suc": True, "message": "Shutting down in 10s", **resp})
            return
        
        if path == "/power/cancel":
            os.system("shutdown /a")
            log("[POWER] Cancelled")
            self.send_json({"suc": True, "message": "Cancelled", **resp})
            return
        
        # AI CHAT
        if path == "/ai/chat":
            try:
                req_data = json.dumps({
                    "message": data.get('message', ''),
                    "brain_type": data.get('brain_type', 'shadow'),
                    "max_tokens": data.get('max_tokens', 512)
                }).encode('utf-8')
                
                req = urllib.request.Request(
                    f"{EAA_BACKEND_URL}/ai/chat",
                    data=req_data,
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                
                response = urllib.request.urlopen(req, timeout=120)
                result = json.loads(response.read().decode())
                self.send_json({**result, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return
        
        # UNKNOWN
        self.send_json({"suc": False, "err": f"Unknown endpoint: {path}", **resp})

# ============================================
# SERVER - NEVER CRASHES
# ============================================

class BulletproofServer:
    def __init__(self, port):
        self.port = port
        self.server = None
    
    def start(self):
        while state.running:
            try:
                self.server = HTTPServer(("0.0.0.0", self.port), BulletproofHandler)
                log(f"[SERVER] Listening on port {self.port}")
                self.server.serve_forever()
            except Exception as e:
                log(f"[SERVER] Error: {e} - restarting in 3s...")
                time.sleep(3)
    
    def stop(self):
        try:
            if self.server:
                self.server.shutdown()
        except:
            pass

# ============================================
# MAIN
# ============================================

def cleanup():
    log("[STOP] Shutting down...")
    state.running = False
    stop_eaa()
    stop_tunnel()
    log("[BYE]")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))
    
    log("=" * 60)
    log("  EAA CONTROL - BULLETPROOF + EMAIL NOTIFICATIONS")
    log("  Never Crashes | Auto-Restart | Email Alerts")
    log("=" * 60)
    
    log(f"[KEY] API Key: {API_KEY}")
    log(f"[SECRET] Secret: {SECRET_PHRASE}")
    log(f"[EMAIL] Notifications: {EMAIL_TO}")
    
    log(f"[CONFIG] EAA Auto-Restart: {EAA_AUTO_RESTART}")
    log(f"[CONFIG] Tunnel Auto-Restart: {TUNNEL_AUTO_RESTART}")
    log(f"[CONFIG] Watchdog Interval: {WATCHDOG_INTERVAL}s")
    
    # Start EAA
    log("[START] Starting EAA...")
    start_eaa()
    time.sleep(2)
    
    # Start tunnel (sends email automatically)
    log("[START] Starting Tunnel...")
    url = start_tunnel()
    # Note: start_tunnel() already sends email, no need to send again
    
    # Start watchdog
    log("[START] Starting Watchdog...")
    threading.Thread(target=watchdog, daemon=True).start()
    
    log("=" * 60)
    log("  BULLETPROOF CONTROL ENABLED!")
    log("=" * 60)
    log(f"  URL: {state.tunnel_url or 'Tunnel starting...'}")
    log(f"  Key: {API_KEY}")
    log(f"  Secret: {SECRET_PHRASE}")
    log("")
    log("  >>> TELL SUPER Z <<<")
    log(f"    URL: {state.tunnel_url}")
    log(f"    Key: {API_KEY}")
    log(f"    Secret: {SECRET_PHRASE}")
    log("=" * 60)
    log("[READY] Server will NEVER crash. Press Ctrl+C to stop.")
    log("[EMAIL] You will receive email when tunnel restarts!")
    
    # Run server
    server = BulletproofServer(PORT)
    try:
        server.start()
    finally:
        cleanup()
