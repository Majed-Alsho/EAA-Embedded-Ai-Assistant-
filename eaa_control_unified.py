"""
EAA CONTROL SYSTEM - UNIFIED VERSION
=====================================
Full remote control with ALL endpoints:
- Screenshot, Mouse, Keyboard control
- File operations, Shell access
- System monitoring, Process management
- EAA AI integration
- Auto-start EAA + Cloudflare Tunnel

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
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import urllib.request
import urllib.error

# ============================================
# DEPENDENCIES
# ============================================

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    HAS_PYAUTOGUI = True
    print("[CONTROL] ✅ pyautogui loaded")
except ImportError:
    HAS_PYAUTOGUI = False
    print("[CONTROL] ⚠️ pyautogui not installed - pip install pyautogui")

try:
    from PIL import Image
    HAS_PIL = True
    print("[CONTROL] ✅ Pillow loaded")
except ImportError:
    HAS_PIL = False
    print("[CONTROL] ⚠️ Pillow not installed - pip install Pillow")

try:
    import psutil
    HAS_PSUTIL = True
    print("[CONTROL] ✅ psutil loaded")
except ImportError:
    HAS_PSUTIL = False
    print("[CONTROL] ⚠️ psutil not installed - pip install psutil")

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

# ============================================
# GLOBAL STATE
# ============================================

eaa_process = None
tunnel_process = None
tunnel_url = None
session_token = None

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
        })
    return info

def get_process_list():
    if not HAS_PSUTIL:
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

def run_shell(cmd, timeout=60):
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

def start_tunnel():
    """Start Cloudflare tunnel"""
    global tunnel_process, tunnel_url
    
    if not os.path.exists(CLOUDFLARED_PATH):
        print(f"[TUNNEL] ❌ cloudflared not found at {CLOUDFLARED_PATH}")
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
                    return tunnel_url
        
        return None
    except Exception as e:
        print(f"[TUNNEL] ❌ Error: {e}")
        return None

def start_eaa():
    """Start EAA server"""
    global eaa_process
    
    if not os.path.exists(EAA_SCRIPT):
        print(f"[EAA] ❌ Script not found: {EAA_SCRIPT}")
        return None
    
    try:
        eaa_process = subprocess.Popen(
            [sys.executable, EAA_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=SCRIPT_DIR
        )
        print(f"[EAA] ✅ Started (PID: {eaa_process.pid})")
        return eaa_process.pid
    except Exception as e:
        print(f"[EAA] ❌ Error: {e}")
        return None

# ============================================
# REQUEST HANDLER
# ============================================

class ControlHandler(BaseHTTPRequestHandler):
    
    def log_message(self, fmt, *args):
        """Log all requests"""
        print(f"[CONTROL] \"{args[0]}\"")
    
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
    
    def check_auth(self, data=None):
        """Check auth from headers OR JSON body"""
        # Try headers first
        key = self.headers.get("X-Control-Key", "")
        secret = self.headers.get("X-Secret", "")
        
        # If not in headers, try JSON body
        if not key and not secret and data:
            key = data.get("api_key", "")
            secret = data.get("secret", "")
        
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
        self.send_header("Access-Control-Allow-Headers", "X-Control-Key, X-Secret, Content-Type")
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
        
        auth_ok, auth_err = self.check_auth()
        if not auth_ok:
            self.send_json({"suc": False, "err": auth_err}, 401)
            return
        
        # Screenshot
        if path == "/screenshot" or path == "/screen":
            img, err = take_screenshot()
            if err:
                self.send_json({"suc": False, "err": err})
            else:
                self.send_json({"suc": True, "image": img})
            return
        
        # Screen size
        if path == "/screen/size":
            if HAS_PYAUTOGUI:
                w, h = pyautogui.size()
                self.send_json({"suc": True, "width": w, "height": h})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available"})
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
            if HAS_PYAUTOGUI:
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
            if HAS_PSUTIL:
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
                "tunnel": tunnel_url
            })
            return
        
        # AI health - forward to EAA
        if path == "/ai/health":
            try:
                req = urllib.request.urlopen(f"{EAA_BACKEND_URL}/ai/health", timeout=5)
                response = json.loads(req.read().decode())
                self.send_json({"suc": True, **response})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # Agent tools - forward to EAA
        if path == "/v1/agent/tools":
            try:
                req = urllib.request.urlopen(f"{EAA_BACKEND_URL}/v1/agent/tools", timeout=10)
                response = json.loads(req.read().decode())
                self.send_json(response)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
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
.header{background:linear-gradient(135deg,#1a1a2e,#16213e);padding:15px 30px;width:100%;display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #e94560}
.header h1{color:#e94560;font-size:1.5rem}
.status{display:flex;gap:20px;align-items:center}
.status-dot{width:12px;height:12px;border-radius:50%;background:#4CAF50;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.controls{display:flex;gap:10px;padding:15px;background:#1a1a1a;border-radius:10px;margin:15px 0;flex-wrap:wrap;justify-content:center}
button{background:linear-gradient(135deg,#e94560,#c73659);border:none;color:#fff;padding:10px 20px;border-radius:5px;cursor:pointer;font-size:14px;transition:all 0.3s}
button:hover{transform:scale(1.05);box-shadow:0 0 15px rgba(233,69,96,0.5)}
.screen-container{position:relative;border:3px solid #e94560;border-radius:10px;overflow:hidden;box-shadow:0 0 30px rgba(233,69,96,0.3);max-width:100%}
#screen{display:block;cursor:crosshair;max-width:100%;height:auto}
.info{display:flex;gap:30px;padding:10px 20px;background:#111;border-radius:5px;margin:10px 0;flex-wrap:wrap;justify-content:center}
.info span{color:#888}
.info .value{color:#e94560;font-weight:bold}
.input-area{display:flex;gap:10px;margin:15px 0;width:100%;max-width:800px;padding:0 20px}
input[type="text"]{flex:1;padding:12px 15px;border:2px solid #333;border-radius:5px;background:#1a1a1a;color:#fff;font-size:14px}
input[type="text"]:focus{outline:none;border-color:#e94560}
.log{width:100%;max-width:800px;height:80px;background:#0a0a0a;border:1px solid #333;border-radius:5px;padding:10px;overflow-y:auto;font-family:monospace;font-size:11px;color:#4CAF50;margin:15px 20px}
</style></head>
<body>
<div class="header"><h1>EAA Remote Desktop</h1>
<div class="status"><span class="status-dot"></span><span id="statusText">Connected</span></div></div>
<div class="controls">
<button onclick="refreshScreen()">Refresh</button>
<button onclick="autoRefresh()">Auto (2fps)</button>
<button onclick="pressKey('escape')">ESC</button>
<button onclick="pressKey('enter')">Enter</button>
<button onclick="pressKey('tab')">Tab</button>
<button onclick="typeText()">Type</button>
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
</div>
<div class="log" id="log"></div>
<script>
let url='', secret='', autoInterval=null;
function log(m){const el=document.getElementById('log');el.innerHTML='['+new Date().toLocaleTimeString()+'] '+m+'<br>'+el.innerHTML}
async function api(ep,method='GET',body=null){
 const opts={method,headers:{'Content-Type':'application/json','X-Secret':secret}};
 if(body)opts.body=JSON.stringify(body);
 return await fetch(url+ep,opts).then(r=>r.json())
}
async function refreshScreen(){
 try{
  const data=await fetch(url+'/screenshot',{headers:{'X-Secret':secret}}).then(r=>r.json());
  if(data.suc&&data.image){document.getElementById('screen').src='data:image/png;base64,'+data.image;}
 }catch(e){log('Error: '+e.message)}
}
function autoRefresh(){
 if(autoInterval){clearInterval(autoInterval);autoInterval=null;log('Auto stopped');}
 else{autoInterval=setInterval(refreshScreen,500);log('Auto started');}
}
async function handleClick(e){
 const img=e.target, rect=img.getBoundingClientRect();
 const x=Math.round((e.clientX-rect.left)*(img.naturalWidth/rect.width));
 const y=Math.round((e.clientY-rect.top)*(img.naturalHeight/rect.height));
 document.getElementById('lastClick').textContent=x+', '+y;
 try{
  const r=await api('/mouse/click','POST',{x,y,button:'left'});
  log('Click ('+x+','+y+'): '+(r.suc?'OK':r.err));
  setTimeout(refreshScreen,300);
 }catch(e){log('Error: '+e.message)}
}
async function pressKey(k){
 try{const r=await api('/keyboard/press','POST',{key:k});log('Key: '+k+' - '+(r.suc?'OK':r.err));setTimeout(refreshScreen,300)}catch(e){log('Error: '+e.message)}
}
async function typeText(){
 const t=document.getElementById('typeInput').value;if(!t)return;
 try{const r=await api('/keyboard/type','POST',{text:t});log('Typed: '+t+' - '+(r.suc?'OK':r.err));document.getElementById('typeInput').value='';setTimeout(refreshScreen,300)}catch(e){log('Error: '+e.message)}
}
function init(){
 const p=new URLSearchParams(window.location.search);
 url=p.get('url')||prompt('Enter tunnel URL:');
 secret=p.get('secret')||prompt('Enter Secret:');
 if(url&&secret){log('Connected to '+url);refreshScreen();}
}
init();
</script></body></html>'''
            self.wfile.write(html.encode())
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
        
        # Auth endpoint (special - returns session)
        if path == "/auth" or path == "/authenticate":
            auth_ok, _ = self.check_auth(data)
            if auth_ok:
                global session_token
                if session_token is None:
                    session_token = "SESS_" + secrets.token_urlsafe(16)
                self.send_json({"suc": True, "session_token": session_token})
            else:
                self.send_json({"suc": False, "err": "Invalid credentials"}, 401)
            return
        
        # Auth check for all other endpoints
        auth_ok, auth_err = self.check_auth(data)
        if not auth_ok:
            self.send_json({"suc": False, "err": auth_err}, 401)
            return
        
        # === MOUSE ENDPOINTS ===
        
        if path == "/mouse/move":
            if HAS_PYAUTOGUI:
                pyautogui.moveTo(data.get("x", 0), data.get("y", 0))
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available"})
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
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available"})
            return
        
        if path == "/mouse/scroll" or path == "/scroll":
            if HAS_PYAUTOGUI:
                amount = data.get("amount", 3)
                if data.get("direction", "down") == "up":
                    pyautogui.scroll(amount)
                else:
                    pyautogui.scroll(-amount)
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available"})
            return
        
        # === KEYBOARD ENDPOINTS ===
        
        if path == "/keyboard/type" or path == "/type":
            if HAS_PYAUTOGUI:
                pyautogui.typewrite(data.get("text", ""), interval=data.get("interval", 0.02))
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available"})
            return
        
        if path == "/keyboard/press" or path == "/keyboard/key" or path == "/key":
            if HAS_PYAUTOGUI:
                pyautogui.press(data.get("key", "enter"))
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available"})
            return
        
        if path == "/keyboard/hotkey" or path == "/hotkey":
            if HAS_PYAUTOGUI:
                keys = data.get("keys", [])
                if keys:
                    pyautogui.hotkey(*keys)
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available"})
            return
        
        # === FILE ENDPOINTS ===
        
        if path == "/file/read" or path == "/read":
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
        
        if path == "/file/write" or path == "/write":
            file_path = data.get("path", "")
            content = data.get("content", "")
            if not validate_path(file_path):
                self.send_json({"suc": False, "err": "Access denied"})
                return
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.send_json({"suc": True})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        if path == "/file/list" or path == "/list":
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
        
        if path == "/file/delete" or path == "/delete":
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
        
        # === SHELL ENDPOINT ===
        
        if path == "/shell" or path == "/exec":
            cmd = data.get("command", "")
            timeout = data.get("timeout", 60)
            result = run_shell(cmd, timeout)
            self.send_json({"suc": True, "result": result})
            return
        
        # === CLIPBOARD ENDPOINT ===
        
        if path == "/clipboard/set":
            ok, err = set_clipboard(data.get("content", ""))
            if ok:
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": err})
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
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": "win32 not available"})
            return
        
        if path == "/window/close":
            if HAS_WIN32GUI:
                title = data.get("title", "").lower()
                def enum_cb(hwnd, ctx):
                    if win32gui.IsWindowVisible(hwnd):
                        if title in win32gui.GetWindowText(hwnd).lower():
                            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                win32gui.EnumWindows(enum_cb, None)
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": "win32 not available"})
            return
        
        # === PROCESS ENDPOINTS ===
        
        if path == "/process/kill":
            pid = data.get("pid")
            if not pid:
                self.send_json({"suc": False, "err": "pid required"})
                return
            try:
                if HAS_PSUTIL:
                    psutil.Process(pid).terminate()
                else:
                    subprocess.run(f"taskkill /pid {pid}", shell=True)
                self.send_json({"suc": True})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
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
        
        # === BROWSER ENDPOINTS ===
        
        if path == "/browser/open":
            url = data.get("url", "https://google.com")
            subprocess.run(f'start "" "{url}"', shell=True)
            self.send_json({"suc": True})
            return
        
        if path == "/browser/search":
            query = data.get("query", "")
            subprocess.run(f'start "" "https://www.google.com/search?q={query}"', shell=True)
            self.send_json({"suc": True})
            return
        
        # === POWER ENDPOINTS ===
        
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
        
        # === AI CHAT - Forward to EAA ===
        
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
                self.send_json(result)
            except urllib.error.URLError:
                self.send_json({"suc": False, "err": "EAA backend not running"})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        self.send_json({"suc": False, "err": "Unknown endpoint"})

# ============================================
# MAIN
# ============================================

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), ControlHandler)
    server.serve_forever()

def cleanup():
    global eaa_process, tunnel_process
    print("\n[STOP] Stopping all processes...")
    for p in [eaa_process, tunnel_process]:
        if p and p.poll() is None:
            p.terminate()
    print("[BYE] All stopped!")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))
    
    print("\n" + "=" * 60)
    print("  EAA CONTROL SYSTEM - UNIFIED VERSION")
    print("  Full Remote Control + AI Integration")
    print("=" * 60)
    
    print(f"\n[KEY] API Key: {API_KEY}")
    print(f"[SECRET] Secret Phrase: {SECRET_PHRASE}")
    
    print("\n[CHECK] Dependencies:")
    print(f"  pyautogui: {'OK' if HAS_PYAUTOGUI else 'MISSING'}")
    print(f"  Pillow: {'OK' if HAS_PIL else 'MISSING'}")
    print(f"  psutil: {'OK' if HAS_PSUTIL else 'MISSING'}")
    print(f"  win32: {'OK' if HAS_WIN32 else 'MISSING'}")
    
    # Start EAA
    print("\n[START] Starting EAA AI Server...")
    start_eaa()
    time.sleep(2)  # Give EAA time to start
    
    # Start tunnel
    print("\n[START] Starting Cloudflare Tunnel...")
    url = start_tunnel()
    
    if url:
        print(f"\n[TUNNEL] OK {url}")
    else:
        print("[TUNNEL] WARNING Tunnel failed to start")
    
    print("\n" + "=" * 60)
    print("  FULL REMOTE CONTROL ENABLED!")
    print("=" * 60)
    print(f"\n  Control URL: {url or 'Tunnel failed'}")
    print(f"  API Key: {API_KEY}")
    print(f"  Secret: {SECRET_PHRASE}")
    print(f"\n  Viewer: {url}/viewer?url={url}&secret={SECRET_PHRASE}" if url else "")
    print("\n  >>> TELL SUPER Z <<<")
    print(f"    URL: {url}")
    print(f"    Key: {API_KEY}")
    print(f"    Secret: {SECRET_PHRASE}")
    print("=" * 60)
    print("\n[READY] Press Ctrl+C to stop\n")
    
    # Run server
    run_server()
