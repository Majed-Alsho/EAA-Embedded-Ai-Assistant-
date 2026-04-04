"""
EAA CONTROL SYSTEM - COMPLETE VERSION
======================================
Full remote control with ALL features:
- Screenshot, Mouse, Keyboard control
- File operations, Shell access
- System monitoring, Process management
- EAA AI integration
- Auto-start EAA + Cloudflare Tunnel
- REAL-TIME LOGS (see everything I see)
- Session token security
- Remote terminal output

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
import hashlib
import hmac
import re
import io
import shutil
import signal
import queue
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import urllib.request
import urllib.error

# ============================================
# LOG CAPTURE SYSTEM - See everything!
# ============================================

class LogCapture:
    """Captures all terminal output so Super Z can see it"""
    def __init__(self):
        self.logs = []
        self.lock = threading.Lock()
        self.max_lines = 500
    
    def add(self, line):
        with self.lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{timestamp}] {line}")
            if len(self.logs) > self.max_lines:
                self.logs = self.logs[-self.max_lines:]
    
    def get(self, last_n=100):
        with self.lock:
            return "\n".join(self.logs[-last_n:])
    
    def clear(self):
        with self.lock:
            self.logs = []

log_capture = LogCapture()

def log_print(msg):
    """Print and capture"""
    print(msg)
    log_capture.add(msg)

# ============================================
# DEPENDENCIES
# ============================================

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    HAS_PYAUTOGUI = True
    log_print("[OK] pyautogui loaded")
except ImportError:
    HAS_PYAUTOGUI = False
    log_print("[WARN] pyautogui not installed - pip install pyautogui")

try:
    from PIL import Image
    HAS_PIL = True
    log_print("[OK] Pillow loaded")
except ImportError:
    HAS_PIL = False
    log_print("[WARN] Pillow not installed - pip install Pillow")

try:
    import psutil
    HAS_PSUTIL = True
    log_print("[OK] psutil loaded")
except ImportError:
    HAS_PSUTIL = False
    log_print("[WARN] psutil not installed - pip install psutil")

try:
    import win32clipboard
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import win32gui
    import win32api
    HAS_WIN32GUI = True
except ImportError:
    HAS_WIN32GUI = False

# ============================================
# CONFIGURATION
# ============================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(SCRIPT_DIR, "tools")
CLOUDFLARED_PATH = os.path.join(TOOLS_DIR, "cloudflared.exe")
ALLOWED_PATH = r"C:\Users\offic"
PORT = 8001
EAA_SCRIPT = os.path.join(SCRIPT_DIR, "run_eaa_agent_v3.py")
EAA_BACKEND_URL = "http://localhost:8000"

# Generate credentials
API_KEY = secrets.token_urlsafe(32)
SECRET_PHRASE = secrets.choice([
    "alpha-bravo-charlie", "delta-echo-foxtrot", "golf-hotel-india",
    "juliet-kilo-lima", "mike-november-oscar", "papa-quebec-romeo",
    "sierra-tango-uniform", "victor-whiskey-xray", "yankee-zulu-alpha"
])

# Session management
SESSION_TIMEOUT = 300  # 5 minutes
session_token = None
session_time = 0

# ============================================
# GLOBAL STATE
# ============================================

eaa_process = None
eaa_logs = queue.Queue()
tunnel_process = None
tunnel_url = None
scheduled_tasks = []

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

def validate_path(path):
    if not path:
        return False
    try:
        abs_path = os.path.abspath(path)
        return abs_path.startswith(ALLOWED_PATH)
    except:
        return False

def check_session_timeout():
    """Check and handle session timeout"""
    global session_token, session_time
    if session_token and SESSION_TIMEOUT > 0:
        if time.time() - session_time > SESSION_TIMEOUT:
            session_token = None
            log_print("[SESSION] Timeout - session cleared")

def take_screenshot():
    if not HAS_PYAUTOGUI or not HAS_PIL:
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
    if HAS_PSUTIL:
        info.update({
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('C:\\').percent,
            "uptime": int(time.time() - psutil.boot_time()),
            "cpu_temp": get_cpu_temp(),
        })
    return info

def get_cpu_temp():
    try:
        import wmi
        w = wmi.WMI()
        temp = w.MSAcpi_ThermalZoneTemperature()[0].CurrentTemperature
        return (temp / 10) - 273.15
    except:
        return None

def get_process_list():
    if not HAS_PSUTIL:
        return []
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'exe']):
        try:
            procs.append({
                "pid": p.info['pid'],
                "name": p.info['name'],
                "cpu": round(p.info['cpu_percent'] or 0, 1),
                "memory": round(p.info['memory_percent'] or 0, 1),
                "exe": p.info.get('exe', ''),
            })
        except:
            pass
    return sorted(procs, key=lambda x: x['cpu'], reverse=True)[:50]

def get_windows_list():
    if not HAS_WIN32GUI:
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

def get_clipboard():
    if not HAS_WIN32:
        return None, "win32 not available"
    try:
        win32clipboard.OpenClipboard()
        data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()
        return data, None
    except Exception as e:
        return None, str(e)

def set_clipboard(content):
    if not HAS_WIN32:
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
    """Send Windows notification"""
    try:
        ps_cmd = f'''
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
        $template = @"<toast><visual><binding template="ToastText02"><text id="1">{title}</text><text id="2">{message}</text></binding></visual></toast>"@
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($template)
        $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("EAA Control").Show($toast)
        '''
        subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=10)
        return True, None
    except Exception as e:
        return False, str(e)

def run_shell(cmd, timeout=60, cwd=None):
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd or ALLOWED_PATH
        )
        output = result.stdout + result.stderr
        log_capture.add(f"[SHELL] {cmd[:50]}... -> {result.returncode}")
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Timeout", "returncode": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1}

def read_eaa_output():
    """Read EAA process output into log queue"""
    global eaa_process
    while eaa_process and eaa_process.poll() is None:
        try:
            line = eaa_process.stdout.readline()
            if line:
                eaa_logs.put(line.strip())
                log_capture.add(f"[EAA] {line.strip()}")
        except:
            break

def start_tunnel():
    """Start Cloudflare tunnel"""
    global tunnel_process, tunnel_url
    
    if not os.path.exists(CLOUDFLARED_PATH):
        log_print(f"[TUNNEL] ERROR cloudflared not found at {CLOUDFLARED_PATH}")
        return None
    
    try:
        tunnel_process = subprocess.Popen(
            [CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{PORT}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        for _ in range(30):
            line = tunnel_process.stdout.readline()
            if "trycloudflare.com" in line:
                match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
                if match:
                    tunnel_url = match.group(0)
                    log_print(f"[TUNNEL] OK {tunnel_url}")
                    return tunnel_url
        
        log_print("[TUNNEL] ERROR Failed to get URL")
        return None
    except Exception as e:
        log_print(f"[TUNNEL] ERROR {e}")
        return None

def start_eaa():
    """Start EAA server"""
    global eaa_process
    
    if not os.path.exists(EAA_SCRIPT):
        log_print(f"[EAA] ERROR Script not found: {EAA_SCRIPT}")
        return None
    
    try:
        eaa_process = subprocess.Popen(
            [sys.executable, EAA_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=SCRIPT_DIR
        )
        log_print(f"[EAA] OK Started (PID: {eaa_process.pid})")
        
        # Start output reader thread
        threading.Thread(target=read_eaa_output, daemon=True).start()
        
        return eaa_process.pid
    except Exception as e:
        log_print(f"[EAA] ERROR {e}")
        return None

def schedule_task(name, execute_time, command):
    """Schedule a task for later execution"""
    global scheduled_tasks
    task = {
        "name": name,
        "time": execute_time,
        "command": command,
        "created": datetime.now().isoformat()
    }
    scheduled_tasks.append(task)
    log_print(f"[SCHEDULE] Added: {name} for {execute_time}")
    return task

# ============================================
# REQUEST HANDLER
# ============================================

class ControlHandler(BaseHTTPRequestHandler):
    
    def log_message(self, fmt, *args):
        """Log all requests"""
        msg = f"{args[0]}" if args else fmt
        log_capture.add(f"[HTTP] {msg}")
    
    def send_json(self, data, status=200):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
    
    def get_client_ip(self):
        return self.client_address[0]
    
    def check_auth(self, data=None):
        """Check auth from headers OR JSON body"""
        global session_token, session_time
        
        # Check session timeout first
        check_session_timeout()
        
        # Try headers first
        key = self.headers.get("X-Control-Key", "")
        secret = self.headers.get("X-Secret", "")
        provided_session = self.headers.get("X-Session-Token", "")
        
        # If not in headers, try JSON body
        if not key and not secret and data:
            key = data.get("api_key", "")
            secret = data.get("secret", "")
            provided_session = data.get("session_token", "")
        
        # Verify API key or secret
        auth_valid = verify_api_key(key) or verify_secret(secret)
        
        if not auth_valid:
            return False, "Invalid API key", None
        
        # Session token logic
        if session_token is None:
            # First connection - create session
            session_token = "SESS_" + secrets.token_urlsafe(32)
            session_time = time.time()
            log_print(f"[SESSION] Created: {session_token[:15]}...")
            return True, None, session_token
        
        # Session exists - verify it
        if provided_session == session_token:
            session_time = time.time()
            return True, None, session_token
        
        # Wrong session token
        return False, "Session locked by another user", None
    
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
        
        # === PUBLIC ENDPOINTS ===
        
        if path == "/health":
            self.send_json({
                "status": "online",
                "session_active": session_token is not None,
                "remote_control": HAS_PYAUTOGUI,
                "screenshot": HAS_PIL,
                "tunnel": tunnel_url
            })
            return
        
        # === AUTH REQUIRED ENDPOINTS ===
        
        auth_ok, auth_err, sess = self.check_auth()
        if not auth_ok:
            self.send_json({"suc": False, "err": auth_err, "session_token": sess}, 401 if "Invalid" in auth_err else 423)
            return
        
        response_data = {"session_token": sess}
        
        # Screenshot
        if path == "/screenshot" or path == "/screen":
            img, err = take_screenshot()
            if err:
                self.send_json({"suc": False, "err": err, **response_data})
            else:
                self.send_json({"suc": True, "image": img, **response_data})
            return
        
        # Screen size
        if path == "/screen/size":
            if HAS_PYAUTOGUI:
                w, h = pyautogui.size()
                self.send_json({"suc": True, "width": w, "height": h, **response_data})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **response_data})
            return
        
        # System info
        if path == "/system/info":
            self.send_json({"suc": True, "system": get_system_info(), **response_data})
            return
        
        # Process list
        if path == "/process/list":
            self.send_json({"suc": True, "processes": get_process_list(), **response_data})
            return
        
        # Windows list
        if path == "/windows/list":
            self.send_json({"suc": True, "windows": get_windows_list(), **response_data})
            return
        
        # Mouse position
        if path == "/mouse/position":
            if HAS_PYAUTOGUI:
                x, y = pyautogui.position()
                self.send_json({"suc": True, "x": x, "y": y, **response_data})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **response_data})
            return
        
        # Clipboard get
        if path == "/clipboard/get":
            content, err = get_clipboard()
            if err:
                self.send_json({"suc": False, "err": err, **response_data})
            else:
                self.send_json({"suc": True, "content": content, **response_data})
            return
        
        # Network info
        if path == "/network/info":
            if HAS_PSUTIL:
                interfaces = []
                for name, addrs in psutil.net_if_addrs().items():
                    for addr in addrs:
                        interfaces.append({"name": name, "address": addr.address})
                self.send_json({"suc": True, "interfaces": interfaces, **response_data})
            else:
                self.send_json({"suc": False, "err": "psutil not available", **response_data})
            return
        
        # EAA status
        if path == "/eaa/status":
            self.send_json({
                "suc": True,
                "running": eaa_process is not None and eaa_process.poll() is None,
                "tunnel": tunnel_url,
                **response_data
            })
            return
        
        # TERMINAL OUTPUT - See what I see!
        if path == "/terminal/output" or path == "/logs":
            self.send_json({
                "suc": True,
                "logs": log_capture.get(100),
                "eaa_running": eaa_process is not None and eaa_process.poll() is None,
                "tunnel_running": tunnel_process is not None and tunnel_process.poll() is None,
                **response_data
            })
            return
        
        # Terminal status
        if path == "/terminal/status":
            self.send_json({
                "suc": True,
                "eaa_running": eaa_process is not None and eaa_process.poll() is None,
                "eaa_pid": eaa_process.pid if eaa_process else None,
                "tunnel_running": tunnel_process is not None and tunnel_process.poll() is None,
                "tunnel_url": tunnel_url,
                **response_data
            })
            return
        
        # Schedule list
        if path == "/schedule/list":
            self.send_json({"suc": True, "tasks": scheduled_tasks, **response_data})
            return
        
        # AI health - forward to EAA
        if path == "/ai/health":
            try:
                req = urllib.request.urlopen(f"{EAA_BACKEND_URL}/ai/health", timeout=5)
                response = json.loads(req.read().decode())
                self.send_json({"suc": True, **response, **response_data})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **response_data})
            return
        
        # Agent tools - forward to EAA
        if path == "/v1/agent/tools":
            try:
                req = urllib.request.urlopen(f"{EAA_BACKEND_URL}/v1/agent/tools", timeout=10)
                response = json.loads(req.read().decode())
                self.send_json({**response, **response_data})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **response_data})
            return
        
        # Remote viewer page
        if path == "/viewer" or path == "/remote":
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            html = '''<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EAA Remote Desktop</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0a;color:#fff;font-family:Segoe UI,sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center}
.header{background:linear-gradient(135deg,#1a1a2e,#16213e);padding:15px;width:100%;display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #e94560}
.header h1{color:#e94560;font-size:1.2rem}
.status{display:flex;gap:10px;align-items:center;font-size:12px}
.status-dot{width:10px;height:10px;border-radius:50%;background:#4CAF50;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.controls{display:flex;gap:5px;padding:10px;background:#1a1a1a;border-radius:8px;margin:10px;flex-wrap:wrap;justify-content:center}
button{background:linear-gradient(135deg,#e94560,#c73659);border:none;color:#fff;padding:8px 12px;border-radius:4px;cursor:pointer;font-size:12px}
button:hover{transform:scale(1.05)}
.screen-container{position:relative;border:2px solid #e94560;border-radius:8px;overflow:hidden;max-width:100%;margin:5px}
#screen{display:block;cursor:crosshair;max-width:100%;height:auto}
.info{display:flex;gap:15px;padding:8px 15px;background:#111;border-radius:4px;margin:5px;font-size:11px;flex-wrap:wrap;justify-content:center}
.info span{color:#888}
.info .value{color:#e94560;font-weight:bold}
.input-area{display:flex;gap:5px;margin:10px;width:100%;max-width:600px;padding:0 10px}
input[type="text"]{flex:1;padding:10px;border:2px solid #333;border-radius:4px;background:#1a1a1a;color:#fff;font-size:12px}
input:focus{outline:none;border-color:#e94560}
.log-box{width:100%;max-width:600px;height:150px;background:#000;border:1px solid #333;border-radius:4px;padding:8px;overflow-y:auto;font-family:monospace;font-size:10px;color:#0f0;margin:10px;white-space:pre-wrap}
.tabs{display:flex;gap:5px;margin:5px}
.tab{padding:8px 15px;background:#333;border:none;color:#fff;cursor:pointer;border-radius:4px 4px 0 0}
.tab.active{background:#e94560}
</style></head>
<body>
<div class="header"><h1>EAA Remote Control</h1>
<div class="status"><span class="status-dot"></span><span id="statusText">Connected</span></div></div>
<div class="tabs">
<button class="tab active" onclick="showTab('screen')">Screen</button>
<button class="tab" onclick="showTab('logs')">Logs</button>
<button class="tab" onclick="showTab('shell')">Shell</button>
</div>
<div id="screenTab">
<div class="controls">
<button onclick="refreshScreen()">Refresh</button>
<button onclick="autoRefresh()">Auto</button>
<button onclick="pressKey('escape')">ESC</button>
<button onclick="pressKey('enter')">Enter</button>
<button onclick="pressKey('tab')">Tab</button>
<button onclick="pressKey('win')">Win</button>
</div>
<div class="info">
<span>Screen: <span class="value" id="screenSize">-</span></span>
<span>Click: <span class="value" id="lastClick">-</span></span>
</div>
<div class="screen-container" id="screenContainer">
<img id="screen" src="" alt="Remote Screen" onclick="handleClick(event)">
</div>
<div class="input-area">
<input type="text" id="typeInput" placeholder="Type text here..." onkeypress="if(event.key==='Enter')typeText()">
<button onclick="typeText()">Type</button>
</div>
</div>
<div id="logsTab" style="display:none">
<div class="log-box" id="logBox"></div>
<div class="controls">
<button onclick="refreshLogs()">Refresh Logs</button>
<button onclick="autoLogs()">Auto Refresh</button>
</div>
</div>
<div id="shellTab" style="display:none">
<div class="log-box" id="shellOutput"></div>
<div class="input-area">
<input type="text" id="shellInput" placeholder="Enter command..." onkeypress="if(event.key==='Enter')runShell()">
<button onclick="runShell()">Run</button>
</div>
</div>
<script>
let url='', secret='', session='', autoInt=null, logInt=null;
function log(m){document.getElementById('logBox').innerText+='\\n'+m;document.getElementById('logBox').scrollTop=9999}
async function api(ep,method='GET',body=null){
 const opts={method,headers:{'Content-Type':'application/json','X-Secret':secret}};
 if(body)opts.body=JSON.stringify(body);
 const r=await fetch(url+ep,opts).then(r=>r.json());
 if(r.session_token)session=r.session_token;
 return r;
}
function showTab(t){
 document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
 event.target.classList.add('active');
 document.getElementById('screenTab').style.display=t==='screen'?'block':'none';
 document.getElementById('logsTab').style.display=t==='logs'?'block':'none';
 document.getElementById('shellTab').style.display=t==='shell'?'block':'none';
}
async function refreshScreen(){
 try{
  const d=await fetch(url+'/screenshot',{headers:{'X-Secret':secret}}).then(r=>r.json());
  if(d.suc&&d.image){document.getElementById('screen').src='data:image/png;base64,'+d.image;}
 }catch(e){}
}
function autoRefresh(){
 if(autoInt){clearInterval(autoInt);autoInt=null;document.getElementById('statusText').innerText='Connected';}
 else{autoInt=setInterval(refreshScreen,500);document.getElementById('statusText').innerText='Live (2 FPS)';}
}
async function handleClick(e){
 const img=e.target, rect=img.getBoundingClientRect();
 const x=Math.round((e.clientX-rect.left)*(img.naturalWidth/rect.width));
 const y=Math.round((e.clientY-rect.top)*(img.naturalHeight/rect.height));
 document.getElementById('lastClick').textContent=x+','+y;
 await api('/mouse/click','POST',{x,y,button:'left'});
 setTimeout(refreshScreen,300);
}
async function pressKey(k){await api('/keyboard/press','POST',{key:k});setTimeout(refreshScreen,300)}
async function typeText(){
 const t=document.getElementById('typeInput').value;if(!t)return;
 await api('/keyboard/type','POST',{text:t});
 document.getElementById('typeInput').value='';
 setTimeout(refreshScreen,300);
}
async function refreshLogs(){
 const d=await api('/terminal/output');
 if(d.suc)document.getElementById('logBox').innerText=d.logs;
 document.getElementById('logBox').scrollTop=9999;
}
function autoLogs(){
 if(logInt){clearInterval(logInt);logInt=null;}
 else{logInt=setInterval(refreshLogs,2000);}
}
async function runShell(){
 const c=document.getElementById('shellInput').value;if(!c)return;
 document.getElementById('shellOutput').innerText='$ '+c+'\\n';
 const r=await api('/shell','POST',{command:c});
 document.getElementById('shellOutput').innerText+=r.result.stdout||r.result.stderr||'Done';
 document.getElementById('shellInput').value='';
}
async function getSize(){
 const d=await api('/screen/size');
 if(d.suc)document.getElementById('screenSize').textContent=d.width+'x'+d.height;
}
function init(){
 const p=new URLSearchParams(window.location.search);
 url=p.get('url')||prompt('Enter tunnel URL:');
 secret=p.get('secret')||prompt('Enter Secret:');
 if(url&&secret){refreshScreen();getSize();refreshLogs();}
}
init();
</script></body></html>'''
            self.wfile.write(html.encode())
            return
        
        self.send_json({"suc": False, "err": "Unknown endpoint", **response_data})
    
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
        
        # Auth endpoint
        if path == "/auth" or path == "/authenticate":
            auth_ok, auth_err, sess = self.check_auth(data)
            if auth_ok:
                self.send_json({"suc": True, "session_token": sess})
            else:
                self.send_json({"suc": False, "err": auth_err, "session_token": sess}, 401 if "Invalid" in auth_err else 423)
            return
        
        # Auth check for all other endpoints
        auth_ok, auth_err, sess = self.check_auth(data)
        if not auth_ok:
            self.send_json({"suc": False, "err": auth_err, "session_token": sess}, 401 if "Invalid" in auth_err else 423)
            return
        
        response_data = {"session_token": sess}
        
        # === MOUSE ENDPOINTS ===
        
        if path == "/mouse/move":
            if HAS_PYAUTOGUI:
                pyautogui.moveTo(data.get("x", 0), data.get("y", 0))
                self.send_json({"suc": True, **response_data})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **response_data})
            return
        
        if path == "/mouse/click" or path == "/click":
            if HAS_PYAUTOGUI:
                x, y = data.get("x"), data.get("y")
                button = data.get("button", "left")
                clicks = data.get("clicks", 1)
                if x is not None and y is not None:
                    pyautogui.click(x, y, clicks=clicks, button=button)
                else:
                    pyautogui.click(clicks=clicks, button=button)
                log_capture.add(f"[MOUSE] Click ({x},{y}) {button}")
                self.send_json({"suc": True, **response_data})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **response_data})
            return
        
        if path == "/mouse/doubleclick" or path == "/doubleclick":
            if HAS_PYAUTOGUI:
                x, y = data.get("x"), data.get("y")
                if x is not None and y is not None:
                    pyautogui.doubleClick(x, y)
                else:
                    pyautogui.doubleClick()
                self.send_json({"suc": True, **response_data})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **response_data})
            return
        
        if path == "/mouse/rightclick" or path == "/rightclick":
            if HAS_PYAUTOGUI:
                x, y = data.get("x"), data.get("y")
                if x is not None and y is not None:
                    pyautogui.rightClick(x, y)
                else:
                    pyautogui.rightClick()
                self.send_json({"suc": True, **response_data})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **response_data})
            return
        
        if path == "/mouse/scroll" or path == "/scroll":
            if HAS_PYAUTOGUI:
                amount = data.get("amount", 3)
                if data.get("direction", "down") == "up":
                    pyautogui.scroll(amount)
                else:
                    pyautogui.scroll(-amount)
                self.send_json({"suc": True, **response_data})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **response_data})
            return
        
        # === KEYBOARD ENDPOINTS ===
        
        if path == "/keyboard/type" or path == "/type":
            if HAS_PYAUTOGUI:
                text = data.get("text", "")
                pyautogui.typewrite(text, interval=data.get("interval", 0.02))
                log_capture.add(f"[KEYBOARD] Typed: {text[:30]}...")
                self.send_json({"suc": True, **response_data})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **response_data})
            return
        
        if path == "/keyboard/press" or path == "/keyboard/key" or path == "/key":
            if HAS_PYAUTOGUI:
                key = data.get("key", "enter")
                pyautogui.press(key)
                log_capture.add(f"[KEYBOARD] Press: {key}")
                self.send_json({"suc": True, **response_data})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **response_data})
            return
        
        if path == "/keyboard/hotkey" or path == "/hotkey":
            if HAS_PYAUTOGUI:
                keys = data.get("keys", [])
                if keys:
                    pyautogui.hotkey(*keys)
                    log_capture.add(f"[KEYBOARD] Hotkey: {'+'.join(keys)}")
                self.send_json({"suc": True, **response_data})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available", **response_data})
            return
        
        # === FILE ENDPOINTS ===
        
        if path == "/file/read" or path == "/read":
            file_path = data.get("path", "")
            if not validate_path(file_path):
                self.send_json({"suc": False, "err": "Access denied", **response_data})
                return
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                self.send_json({"suc": True, "content": content, **response_data})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **response_data})
            return
        
        if path == "/file/write" or path == "/write":
            file_path = data.get("path", "")
            content = data.get("content", "")
            if not validate_path(file_path):
                self.send_json({"suc": False, "err": "Access denied", **response_data})
                return
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                log_capture.add(f"[FILE] Wrote: {file_path}")
                self.send_json({"suc": True, **response_data})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **response_data})
            return
        
        if path == "/file/list" or path == "/list":
            dir_path = data.get("path", ALLOWED_PATH)
            if not validate_path(dir_path):
                self.send_json({"suc": False, "err": "Access denied", **response_data})
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
                self.send_json({"suc": True, "items": items, **response_data})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **response_data})
            return
        
        if path == "/file/delete" or path == "/delete":
            file_path = data.get("path", "")
            if not validate_path(file_path):
                self.send_json({"suc": False, "err": "Access denied", **response_data})
                return
            try:
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                else:
                    os.remove(file_path)
                log_capture.add(f"[FILE] Deleted: {file_path}")
                self.send_json({"suc": True, **response_data})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **response_data})
            return
        
        if path == "/file/move" or path == "/move":
            src, dst = data.get("src", ""), data.get("dst", "")
            if not validate_path(src) or not validate_path(dst):
                self.send_json({"suc": False, "err": "Access denied", **response_data})
                return
            try:
                shutil.move(src, dst)
                log_capture.add(f"[FILE] Moved: {src} -> {dst}")
                self.send_json({"suc": True, **response_data})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **response_data})
            return
        
        if path == "/file/copy" or path == "/copy":
            src, dst = data.get("src", ""), data.get("dst", "")
            if not validate_path(src) or not validate_path(dst):
                self.send_json({"suc": False, "err": "Access denied", **response_data})
                return
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                log_capture.add(f"[FILE] Copied: {src} -> {dst}")
                self.send_json({"suc": True, **response_data})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **response_data})
            return
        
        # === SHELL ENDPOINT ===
        
        if path == "/shell" or path == "/exec":
            cmd = data.get("command", "")
            timeout = data.get("timeout", 60)
            cwd = data.get("cwd")
            if cwd and not validate_path(cwd):
                cwd = None
            result = run_shell(cmd, timeout, cwd)
            self.send_json({"suc": True, "result": result, **response_data})
            return
        
        # === CLIPBOARD ENDPOINTS ===
        
        if path == "/clipboard/set":
            ok, err = set_clipboard(data.get("content", ""))
            if ok:
                self.send_json({"suc": True, **response_data})
            else:
                self.send_json({"suc": False, "err": err, **response_data})
            return
        
        # === WINDOW ENDPOINTS ===
        
        if path == "/window/focus":
            if HAS_WIN32GUI:
                title = data.get("title", "").lower()
                def enum_cb(hwnd, ctx):
                    if win32gui.IsWindowVisible(hwnd):
                        if title in win32gui.GetWindowText(hwnd).lower():
                            win32gui.SetForegroundWindow(hwnd)
                win32gui.EnumWindows(enum_cb, None)
                log_capture.add(f"[WINDOW] Focus: {title}")
                self.send_json({"suc": True, **response_data})
            else:
                self.send_json({"suc": False, "err": "win32 not available", **response_data})
            return
        
        if path == "/window/close":
            if HAS_WIN32GUI:
                title = data.get("title", "").lower()
                def enum_cb(hwnd, ctx):
                    if win32gui.IsWindowVisible(hwnd):
                        if title in win32gui.GetWindowText(hwnd).lower():
                            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                win32gui.EnumWindows(enum_cb, None)
                log_capture.add(f"[WINDOW] Close: {title}")
                self.send_json({"suc": True, **response_data})
            else:
                self.send_json({"suc": False, "err": "win32 not available", **response_data})
            return
        
        # === PROCESS ENDPOINTS ===
        
        if path == "/process/kill":
            pid = data.get("pid")
            if not pid:
                self.send_json({"suc": False, "err": "pid required", **response_data})
                return
            try:
                if HAS_PSUTIL:
                    psutil.Process(pid).terminate()
                else:
                    subprocess.run(f"taskkill /pid {pid}", shell=True)
                log_capture.add(f"[PROCESS] Killed: {pid}")
                self.send_json({"suc": True, **response_data})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **response_data})
            return
        
        if path == "/process/start" or path == "/app/launch":
            path_arg = data.get("path", "") or data.get("app", "")
            if not path_arg:
                self.send_json({"suc": False, "err": "path/app required", **response_data})
                return
            
            # Common apps
            apps = {
                "chrome": "start chrome", "firefox": "start firefox",
                "edge": "start msedge", "vscode": "code",
                "notepad": "notepad", "explorer": "explorer",
                "spotify": "start spotify", "discord": "start discord",
                "calculator": "calc", "paint": "mspaint",
                "word": "winword", "excel": "excel", "powerpoint": "powerpnt",
            }
            
            cmd = apps.get(path_arg.lower(), f'"{path_arg}"')
            try:
                subprocess.Popen(cmd, shell=True)
                log_capture.add(f"[PROCESS] Started: {path_arg}")
                self.send_json({"suc": True, **response_data})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **response_data})
            return
        
        # === BROWSER ENDPOINTS ===
        
        if path == "/browser/open":
            url = data.get("url", "https://google.com")
            subprocess.run(f'start "" "{url}"', shell=True)
            log_capture.add(f"[BROWSER] Open: {url}")
            self.send_json({"suc": True, **response_data})
            return
        
        if path == "/browser/search":
            query = data.get("query", "")
            subprocess.run(f'start "" "https://www.google.com/search?q={query}"', shell=True)
            log_capture.add(f"[BROWSER] Search: {query}")
            self.send_json({"suc": True, **response_data})
            return
        
        # === NOTIFICATION ===
        
        if path == "/notify":
            title = data.get("title", "EAA")
            message = data.get("message", "")
            ok, err = send_notification(title, message)
            if ok:
                log_capture.add(f"[NOTIFY] {title}: {message}")
                self.send_json({"suc": True, **response_data})
            else:
                self.send_json({"suc": False, "err": err, **response_data})
            return
        
        # === SCHEDULE ENDPOINTS ===
        
        if path == "/schedule/add":
            name = data.get("name", f"task_{int(time.time())}")
            exec_time = data.get("time", "")
            command = data.get("command", "")
            if not exec_time or not command:
                self.send_json({"suc": False, "err": "time and command required", **response_data})
                return
            task = schedule_task(name, exec_time, command)
            self.send_json({"suc": True, "task": task, **response_data})
            return
        
        if path == "/schedule/remove":
            name = data.get("name", "")
            global scheduled_tasks
            scheduled_tasks = [t for t in scheduled_tasks if t["name"] != name]
            self.send_json({"suc": True, **response_data})
            return
        
        # === TERMINAL COMMAND ===
        
        if path == "/terminal/command":
            cmd = data.get("command", "")
            if cmd == "stop":
                if eaa_process:
                    eaa_process.terminate()
                if tunnel_process:
                    tunnel_process.terminate()
                self.send_json({"suc": True, "message": "Stopped", **response_data})
            elif cmd == "restart":
                if eaa_process:
                    eaa_process.terminate()
                time.sleep(1)
                start_eaa()
                self.send_json({"suc": True, "message": "Restarted", **response_data})
            else:
                self.send_json({"suc": False, "err": "Unknown command", **response_data})
            return
        
        # === POWER ENDPOINTS ===
        
        if path == "/power/sleep":
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
            self.send_json({"suc": True, **response_data})
            return
        
        if path == "/power/restart":
            os.system("shutdown /r /t 10")
            log_capture.add("[POWER] Restart in 10s")
            self.send_json({"suc": True, "message": "Restarting in 10s", **response_data})
            return
        
        if path == "/power/shutdown":
            os.system("shutdown /s /t 10")
            log_capture.add("[POWER] Shutdown in 10s")
            self.send_json({"suc": True, "message": "Shutting down in 10s", **response_data})
            return
        
        if path == "/power/cancel":
            os.system("shutdown /a")
            log_capture.add("[POWER] Cancelled")
            self.send_json({"suc": True, "message": "Cancelled", **response_data})
            return
        
        # === AI CHAT ===
        
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
                self.send_json({**result, **response_data})
            except urllib.error.URLError:
                self.send_json({"suc": False, "err": "EAA backend not running", **response_data})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **response_data})
            return
        
        self.send_json({"suc": False, "err": "Unknown endpoint", **response_data})

# ============================================
# MAIN
# ============================================

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), ControlHandler)
    server.serve_forever()

def cleanup():
    global eaa_process, tunnel_process
    log_print("[STOP] Stopping all processes...")
    for p in [eaa_process, tunnel_process]:
        if p and p.poll() is None:
            p.terminate()
    log_print("[BYE] All stopped!")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))
    
    log_print("=" * 60)
    log_print("  EAA CONTROL SYSTEM - COMPLETE VERSION")
    log_print("  Full Remote Control + Logs + Session Security")
    log_print("=" * 60)
    
    log_print(f"[KEY] API Key: {API_KEY}")
    log_print(f"[SECRET] Secret Phrase: {SECRET_PHRASE}")
    
    log_print("[CHECK] Dependencies:")
    log_print(f"  pyautogui: {'OK' if HAS_PYAUTOGUI else 'MISSING'}")
    log_print(f"  Pillow: {'OK' if HAS_PIL else 'MISSING'}")
    log_print(f"  psutil: {'OK' if HAS_PSUTIL else 'MISSING'}")
    log_print(f"  win32: {'OK' if HAS_WIN32 else 'MISSING'}")
    
    # Start EAA
    log_print("[START] Starting EAA AI Server...")
    start_eaa()
    time.sleep(2)
    
    # Start tunnel
    log_print("[START] Starting Cloudflare Tunnel...")
    url = start_tunnel()
    
    log_print("=" * 60)
    log_print("  FULL REMOTE CONTROL ENABLED!")
    log_print("=" * 60)
    log_print(f"  Control URL: {url or 'Tunnel failed'}")
    log_print(f"  API Key: {API_KEY}")
    log_print(f"  Secret: {SECRET_PHRASE}")
    log_print(f"  Viewer: {url}/viewer?url={url}&secret={SECRET_PHRASE}" if url else "")
    log_print("")
    log_print("  >>> TELL SUPER Z <<<")
    log_print(f"    URL: {url}")
    log_print(f"    Key: {API_KEY}")
    log_print(f"    Secret: {SECRET_PHRASE}")
    log_print("=" * 60)
    log_print("[READY] Press Ctrl+C to stop")
    
    run_server()
