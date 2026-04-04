"""
EAA CONTROL STATION V5 - FULL REMOTE CONTROL
See screen + Click + Type = Complete control!
"""

import http.server
import socketserver
import json
import threading
import time
import secrets
import hashlib
import os
import subprocess
import urllib.parse
import urllib.request
import base64
import io
from pathlib import Path
from typing import Optional, Dict, Any

# Try to import screen control libraries
try:
    import pyautogui
    HAS_PYAUTOGUI = True
    pyautogui.FAILSAFE = True  # Move mouse to corner to abort
    pyautogui.PAUSE = 0.1  # Small pause between actions
    print("[CONTROL] ✅ pyautogui loaded - Full control enabled!")
except ImportError:
    HAS_PYAUTOGUI = False
    print("[CONTROL] ⚠️ pyautogui not installed - Install with: pip install pyautogui")

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("[CONTROL] ⚠️ PIL not installed - Install with: pip install Pillow")

# Configuration
PORT = 8001
MAX_REQUESTS_PER_MINUTE = 150
ALLOWED_BASE_PATH = r"C:\Users\offic"
EAA_BACKEND_URL = "http://localhost:8000"  # EAA AI backend


class SecureControlHandler(http.server.BaseHTTPRequestHandler):
    """Secure control handler with FULL REMOTE CONTROL"""
    
    # Class-level session storage (persists across requests)
    session_token: Optional[str] = None
    api_key: Optional[str] = None
    secret_phrase: Optional[str] = None
    request_times: list = []
    
    def log_message(self, format, *args):
        """Custom logging with [CONTROL] prefix"""
        print(f"[CONTROL] {args[0]}")
    
    def send_json(self, data: dict, status: int = 200):
        """Send JSON response"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def send_image(self, image_base64: str):
        """Send image as base64 JSON response"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        response = {
            "suc": True,
            "image": image_base64,
            "format": "png",
            "timestamp": time.time()
        }
        self.wfile.write(json.dumps(response).encode())
    
    def check_rate_limit(self) -> bool:
        """Check if request is within rate limits"""
        now = time.time()
        SecureControlHandler.request_times = [
            t for t in SecureControlHandler.request_times 
            if now - t < 60
        ]
        
        if len(SecureControlHandler.request_times) >= MAX_REQUESTS_PER_MINUTE:
            return False
        
        SecureControlHandler.request_times.append(now)
        return True
    
    def validate_path(self, path: str) -> bool:
        """Ensure path is within allowed directory"""
        try:
            abs_path = os.path.abspath(path)
            return abs_path.startswith(ALLOWED_BASE_PATH)
        except:
            return False
    
    def authenticate(self, data: dict) -> tuple:
        """Authenticate request - NO TIMEOUT CHECK"""
        api_key = data.get('api_key', '')
        if api_key != SecureControlHandler.api_key:
            return False, "Invalid API key"
        
        secret = data.get('secret', '')
        if secret != SecureControlHandler.secret_phrase:
            return False, "Invalid secret phrase"
        
        if SecureControlHandler.session_token is None:
            SecureControlHandler.session_token = f"SESS_{secrets.token_urlsafe(16)}"
            print(f"[AUTH] 🎫 Session token issued: {SecureControlHandler.session_token[:10]}...")
        
        return True, SecureControlHandler.session_token
    
    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-API-Key, X-Secret')
        self.end_headers()
    
    def do_GET(self):
        """Handle GET requests"""
        if not self.check_rate_limit():
            self.send_json({"suc": False, "err": "Rate limit exceeded"}, 429)
            return
        
        # Health check endpoint (no auth required)
        if self.path == '/health':
            self.send_json({
                "status": "online",
                "session_active": SecureControlHandler.session_token is not None,
                "remote_control": HAS_PYAUTOGUI,
                "screenshot": HAS_PIL
            })
            return
        
        # Status endpoint
        if self.path == '/status':
            self.send_json({
                "status": "online",
                "session_active": SecureControlHandler.session_token is not None,
                "api_key_set": SecureControlHandler.api_key is not None,
                "secret_set": SecureControlHandler.secret_phrase is not None,
                "remote_control": HAS_PYAUTOGUI,
                "screenshot": HAS_PIL
            })
            return
        
        # AI Health endpoint
        if self.path == '/ai/health':
            try:
                req = urllib.request.urlopen(f"{EAA_BACKEND_URL}/ai/health", timeout=5)
                response = json.loads(req.read().decode())
                self.send_json({"suc": True, **response})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # SCREENSHOT - Take a screenshot (no auth for speed)
        if self.path == '/screenshot' or self.path == '/screen':
            if not HAS_PYAUTOGUI or not HAS_PIL:
                self.send_json({"suc": False, "err": "pyautogui or PIL not installed. Run: pip install pyautogui Pillow"})
                return
            
            try:
                # Take screenshot
                screenshot = pyautogui.screenshot()
                
                # Resize for faster transfer (optional, comment out for full size)
                # screenshot = screenshot.resize((1280, 720), Image.LANCZOS)
                
                # Convert to base64
                buffer = io.BytesIO()
                screenshot.save(buffer, format='PNG', optimize=True)
                img_base64 = base64.b64encode(buffer.getvalue()).decode()
                
                self.send_image(img_base64)
                print(f"[SCREEN] 📸 Screenshot taken ({len(img_base64)} bytes)")
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # Get screen size
        if self.path == '/screen/size':
            if not HAS_PYAUTOGUI:
                self.send_json({"suc": False, "err": "pyautogui not installed"})
                return
            width, height = pyautogui.size()
            self.send_json({"suc": True, "width": width, "height": height})
            return
        
        # REMOTE DESKTOP VIEWER - Interactive web page
        if self.path == '/viewer' or self.path == '/remote':
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
.click-indicator{position:absolute;width:30px;height:30px;border:3px solid #0f0;border-radius:50%;pointer-events:none;transform:translate(-50%,-50%);animation:clickAnim 0.5s ease-out forwards}
@keyframes clickAnim{0%{transform:translate(-50%,-50%) scale(0);opacity:1}100%{transform:translate(-50%,-50%) scale(2);opacity:0}}
.info{display:flex;gap:30px;padding:10px 20px;background:#111;border-radius:5px;margin:10px 0;flex-wrap:wrap;justify-content:center}
.info span{color:#888}
.info .value{color:#e94560;font-weight:bold}
.input-area{display:flex;gap:10px;margin:15px 0;width:100%;max-width:800px;padding:0 20px}
input[type="text"]{flex:1;padding:12px 15px;border:2px solid #333;border-radius:5px;background:#1a1a1a;color:#fff;font-size:14px}
input[type="text"]:focus{outline:none;border-color:#e94560}
.log{width:100%;max-width:800px;height:80px;background:#0a0a0a;border:1px solid #333;border-radius:5px;padding:10px;overflow-y:auto;font-family:monospace;font-size:11px;color:#4CAF50;margin:15px 20px}
</style></head>
<body>
<div class="header"><h1>🖥️ EAA Remote Desktop</h1>
<div class="status"><span class="status-dot"></span><span id="statusText">Connected</span></div></div>
<div class="controls">
<button onclick="refreshScreen()">🔄 Refresh</button>
<button onclick="autoRefresh()">⚡ Auto (2fps)</button>
<button onclick="pressKey('escape')">⎋ ESC</button>
<button onclick="pressKey('enter')">↵ Enter</button>
<button onclick="pressKey('tab')">⇥ Tab</button>
<button onclick="pressWin()">⊞ Win</button>
<button onclick="typeText()">⌨️ Type</button>
</div>
<div class="info">
<span>Screen: <span class="value" id="screenSize">-</span></span>
<span>Click: <span class="value" id="lastClick">-</span></span>
<span>FPS: <span class="value" id="fps">-</span></span>
</div>
<div class="screen-container" id="screenContainer">
<img id="screen" src="" alt="Remote Screen" onclick="handleClick(event)">
</div>
<div class="input-area">
<input type="text" id="typeInput" placeholder="Type text here, then click Type button..." onkeypress="if(event.key==='Enter')typeText()">
</div>
<div class="log" id="log"></div>
<script>
let url='', apiKey='', secret='', autoInterval=null, frameCount=0, lastFps=Date.now();
function log(m){const el=document.getElementById('log');el.innerHTML=`[${new Date().toLocaleTimeString()}] ${m}<br>`+el.innerHTML}
async function api(ep,method='GET',body=null){
 const opts={method,headers:{'Content-Type':'application/json'}};
 if(body)opts.body=JSON.stringify({api_key:apiKey,secret:secret,...body});
 return await fetch(url+ep,opts).then(r=>r.json())
}
async function refreshScreen(){
 try{
  const data=await fetch(url+'/screenshot').then(r=>r.json());
  if(data.suc&&data.image){
   document.getElementById('screen').src='data:image/png;base64,'+data.image;
   frameCount++;
   const now=Date.now();
   if(now-lastFps>=1000){document.getElementById('fps').textContent=frameCount;frameCount=0;lastFps=now}
  }
 }catch(e){log('Error: '+e.message)}
}
function autoRefresh(){
 if(autoInterval){clearInterval(autoInterval);autoInterval=null;log('Auto refresh stopped');document.getElementById('statusText').textContent='Connected'}
 else{autoInterval=setInterval(refreshScreen,500);log('Auto refresh started');document.getElementById('statusText').textContent='Live (2 FPS)'}
}
async function handleClick(e){
 const img=e.target, rect=img.getBoundingClientRect();
 const scaleX=img.naturalWidth/rect.width, scaleY=img.naturalHeight/rect.height;
 const x=Math.round((e.clientX-rect.left)*scaleX), y=Math.round((e.clientY-rect.top)*scaleY);
 document.getElementById('lastClick').textContent=x+', '+y;
 const ind=document.createElement('div');ind.className='click-indicator';
 ind.style.left=(e.clientX-rect.left)+'px';ind.style.top=(e.clientY-rect.top)+'px';
 document.getElementById('screenContainer').appendChild(ind);setTimeout(()=>ind.remove(),500);
 try{
  const r=await api('/click','POST',{x,y,button:'left'});
  log(`Click (${x},${y}): ${r.suc?'OK':r.err}`);
  setTimeout(refreshScreen,300)
 }catch(e){log('Click error: '+e.message)}
}
async function pressKey(k){try{const r=await api('/key','POST',{key:k});log(`Key: ${k} - ${r.suc?'OK':r.err}`);setTimeout(refreshScreen,300)}catch(e){log('Error: '+e.message)}}
async function pressWin(){try{const r=await api('/key','POST',{key:'win'});log('Key: Win - '+(r.suc?'OK':r.err));setTimeout(refreshScreen,300)}catch(e){log('Error: '+e.message)}}
async function typeText(){
 const t=document.getElementById('typeInput').value;if(!t)return;
 try{const r=await api('/type','POST',{text:t});log(`Typed: "${t}" - ${r.suc?'OK':r.err}`);document.getElementById('typeInput').value='';setTimeout(refreshScreen,300)}catch(e){log('Error: '+e.message)}
}
async function getSize(){try{const d=await api('/screen/size','GET');if(d.suc)document.getElementById('screenSize').textContent=d.width+'x'+d.height}catch(e){}}
function init(){
 const p=new URLSearchParams(window.location.search);
 url=p.get('url')||prompt('Enter tunnel URL:');
 apiKey=p.get('key')||prompt('Enter API Key:');
 secret=p.get('secret')||prompt('Enter Secret:');
 if(url&&apiKey&&secret){log('Connected to '+url);refreshScreen();getSize()}
}
init();
</script></body></html>'''
            self.wfile.write(html.encode())
            return
        
        self.send_json({"suc": False, "err": "Unknown endpoint"}, 404)
    
    def do_POST(self):
        """Handle POST requests"""
        if not self.check_rate_limit():
            self.send_json({"suc": False, "err": "Rate limit exceeded"}, 429)
            return
        
        # Read request body
        content_length = int(self.headers.get('Content-Length', 0))
        try:
            body = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(body) if body else {}
        except Exception as e:
            self.send_json({"suc": False, "err": f"Invalid JSON: {str(e)}"}, 400)
            return
        
        # Parse path
        path = self.path.split('?')[0].rstrip('/')
        
        # === PUBLIC ENDPOINTS (no auth) ===
        
        if path == '/auth' or path == '/authenticate':
            valid, result = self.authenticate(data)
            if valid:
                self.send_json({
                    "suc": True,
                    "session_token": result,
                    "message": "Authentication successful - session active (no expiration)"
                })
            else:
                self.send_json({"suc": False, "err": result}, 401)
            return
        
        # === REMOTE CONTROL ENDPOINTS (require auth) ===
        
        # SCREENSHOT with auth
        if path == '/screenshot' or path == '/screen':
            valid, session_or_err = self.authenticate(data)
            if not valid:
                self.send_json({"suc": False, "err": session_or_err}, 401)
                return
            
            if not HAS_PYAUTOGUI or not HAS_PIL:
                self.send_json({"suc": False, "err": "pyautogui or PIL not installed. Run: pip install pyautogui Pillow"})
                return
            
            try:
                screenshot = pyautogui.screenshot()
                buffer = io.BytesIO()
                screenshot.save(buffer, format='PNG', optimize=True)
                img_base64 = base64.b64encode(buffer.getvalue()).decode()
                self.send_image(img_base64)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # CLICK - Click at coordinates
        if path == '/click' or path == '/mouse/click':
            valid, session_or_err = self.authenticate(data)
            if not valid:
                self.send_json({"suc": False, "err": session_or_err}, 401)
                return
            
            if not HAS_PYAUTOGUI:
                self.send_json({"suc": False, "err": "pyautogui not installed"})
                return
            
            try:
                x = data.get('x', 0)
                y = data.get('y', 0)
                button = data.get('button', 'left')  # left, right, middle
                clicks = data.get('clicks', 1)  # double click = 2
                
                pyautogui.click(x, y, clicks=clicks, button=button)
                self.send_json({"suc": True, "message": f"Clicked at ({x}, {y}) with {button} button"})
                print(f"[CLICK] 🖱️ Clicked at ({x}, {y})")
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # DOUBLE CLICK
        if path == '/doubleclick' or path == '/mouse/doubleclick':
            valid, session_or_err = self.authenticate(data)
            if not valid:
                self.send_json({"suc": False, "err": session_or_err}, 401)
                return
            
            if not HAS_PYAUTOGUI:
                self.send_json({"suc": False, "err": "pyautogui not installed"})
                return
            
            try:
                x = data.get('x')
                y = data.get('y')
                
                if x is not None and y is not None:
                    pyautogui.doubleClick(x, y)
                else:
                    pyautogui.doubleClick()
                
                self.send_json({"suc": True, "message": "Double clicked"})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # RIGHT CLICK
        if path == '/rightclick' or path == '/mouse/rightclick':
            valid, session_or_err = self.authenticate(data)
            if not valid:
                self.send_json({"suc": False, "err": session_or_err}, 401)
                return
            
            if not HAS_PYAUTOGUI:
                self.send_json({"suc": False, "err": "pyautogui not installed"})
                return
            
            try:
                x = data.get('x')
                y = data.get('y')
                
                if x is not None and y is not None:
                    pyautogui.rightClick(x, y)
                else:
                    pyautogui.rightClick()
                
                self.send_json({"suc": True, "message": "Right clicked"})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # MOUSE MOVE
        if path == '/mousemove' or path == '/mouse/move':
            valid, session_or_err = self.authenticate(data)
            if not valid:
                self.send_json({"suc": False, "err": session_or_err}, 401)
                return
            
            if not HAS_PYAUTOGUI:
                self.send_json({"suc": False, "err": "pyautogui not installed"})
                return
            
            try:
                x = data.get('x', 0)
                y = data.get('y', 0)
                duration = data.get('duration', 0.2)  # smooth movement
                
                pyautogui.moveTo(x, y, duration=duration)
                self.send_json({"suc": True, "message": f"Moved mouse to ({x}, {y})"})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # TYPE TEXT
        if path == '/type' or path == '/keyboard/type':
            valid, session_or_err = self.authenticate(data)
            if not valid:
                self.send_json({"suc": False, "err": session_or_err}, 401)
                return
            
            if not HAS_PYAUTOGUI:
                self.send_json({"suc": False, "err": "pyautogui not installed"})
                return
            
            try:
                text = data.get('text', '')
                interval = data.get('interval', 0.02)  # time between keystrokes
                
                pyautogui.typewrite(text, interval=interval)
                self.send_json({"suc": True, "message": f"Typed: {text[:50]}..."})
                print(f"[TYPE] ⌨️ Typed: {text[:50]}...")
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # PRESS KEY (special keys like enter, tab, escape, etc.)
        if path == '/key' or path == '/keyboard/press':
            valid, session_or_err = self.authenticate(data)
            if not valid:
                self.send_json({"suc": False, "err": session_or_err}, 401)
                return
            
            if not HAS_PYAUTOGUI:
                self.send_json({"suc": False, "err": "pyautogui not installed"})
                return
            
            try:
                key = data.get('key', 'enter')
                # Valid keys: enter, tab, escape, space, backspace, delete, etc.
                # Also: up, down, left, right, home, end, pageup, pagedown
                # Also: f1-f12, shift, ctrl, alt, win/command
                
                pyautogui.press(key)
                self.send_json({"suc": True, "message": f"Pressed key: {key}"})
                print(f"[KEY] 🔑 Pressed: {key}")
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # HOTKEY - Press combination (like ctrl+c, alt+tab, etc.)
        if path == '/hotkey' or path == '/keyboard/hotkey':
            valid, session_or_err = self.authenticate(data)
            if not valid:
                self.send_json({"suc": False, "err": session_or_err}, 401)
                return
            
            if not HAS_PYAUTOGUI:
                self.send_json({"suc": False, "err": "pyautogui not installed"})
                return
            
            try:
                keys = data.get('keys', [])  # e.g. ['ctrl', 'c'] or ['alt', 'tab']
                
                if keys:
                    pyautogui.hotkey(*keys)
                    self.send_json({"suc": True, "message": f"Pressed hotkey: {'+'.join(keys)}"})
                    print(f"[HOTKEY] 🔑 Pressed: {'+'.join(keys)}")
                else:
                    self.send_json({"suc": False, "err": "No keys provided"})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # SCROLL
        if path == '/scroll' or path == '/mouse/scroll':
            valid, session_or_err = self.authenticate(data)
            if not valid:
                self.send_json({"suc": False, "err": session_or_err}, 401)
                return
            
            if not HAS_PYAUTOGUI:
                self.send_json({"suc": False, "err": "pyautogui not installed"})
                return
            
            try:
                amount = data.get('amount', 3)  # positive = up, negative = down
                x = data.get('x')
                y = data.get('y')
                
                if x is not None and y is not None:
                    pyautogui.scroll(amount, x, y)
                else:
                    pyautogui.scroll(amount)
                
                direction = "up" if amount > 0 else "down"
                self.send_json({"suc": True, "message": f"Scrolled {direction}"})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # DRAG
        if path == '/drag' or path == '/mouse/drag':
            valid, session_or_err = self.authenticate(data)
            if not valid:
                self.send_json({"suc": False, "err": session_or_err}, 401)
                return
            
            if not HAS_PYAUTOGUI:
                self.send_json({"suc": False, "err": "pyautogui not installed"})
                return
            
            try:
                start_x = data.get('startX', 0)
                start_y = data.get('startY', 0)
                end_x = data.get('endX', 0)
                end_y = data.get('endY', 0)
                duration = data.get('duration', 0.5)
                button = data.get('button', 'left')
                
                pyautogui.moveTo(start_x, start_y)
                pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration, button=button)
                self.send_json({"suc": True, "message": f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # === FILE & SYSTEM ENDPOINTS ===
        
        valid, session_or_err = self.authenticate(data)
        if not valid:
            self.send_json({"suc": False, "err": session_or_err}, 401)
            return
        
        # READ FILE
        if path == '/read' or path == '/v1/remote/read':
            file_path = data.get('path', '')
            if not self.validate_path(file_path):
                self.send_json({"suc": False, "err": "Path not allowed"}, 403)
                return
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.send_json({"suc": True, "content": content})
            except FileNotFoundError:
                self.send_json({"suc": False, "err": "File not found"}, 404)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)}, 500)
            return
        
        # WRITE FILE
        if path == '/write' or path == '/v1/remote/write':
            file_path = data.get('path', '')
            content = data.get('content', '')
            
            if not self.validate_path(file_path):
                self.send_json({"suc": False, "err": "Path not allowed"}, 403)
                return
            
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.send_json({"suc": True, "message": f"Written to {file_path}"})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)}, 500)
            return
        
        # DELETE FILE
        if path == '/delete' or path == '/v1/remote/delete':
            file_path = data.get('path', '')
            
            if not self.validate_path(file_path):
                self.send_json({"suc": False, "err": "Path not allowed"}, 403)
                return
            
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    self.send_json({"suc": True, "message": f"Deleted {file_path}"})
                else:
                    self.send_json({"suc": False, "err": "File not found"}, 404)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)}, 500)
            return
        
        # LIST DIRECTORY
        if path == '/list' or path == '/v1/remote/list':
            dir_path = data.get('path', '')
            
            if not self.validate_path(dir_path):
                self.send_json({"suc": False, "err": "Path not allowed"}, 403)
                return
            
            try:
                items = []
                for item in os.listdir(dir_path):
                    full_path = os.path.join(dir_path, item)
                    items.append({
                        "name": item,
                        "type": "directory" if os.path.isdir(full_path) else "file",
                        "size": os.path.getsize(full_path) if os.path.isfile(full_path) else None
                    })
                self.send_json({"suc": True, "items": items})
            except FileNotFoundError:
                self.send_json({"suc": False, "err": "Directory not found"}, 404)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)}, 500)
            return
        
        # EXECUTE COMMAND
        if path == '/exec' or path == '/v1/remote/exec':
            cmd = data.get('command', '')
            cwd = data.get('cwd', r'C:\Users\offic\EAA')
            
            if not self.validate_path(cwd):
                self.send_json({"suc": False, "err": "Working directory not allowed"}, 403)
                return
            
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    timeout=60
                )
                self.send_json({
                    "suc": True,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode
                })
            except subprocess.TimeoutExpired:
                self.send_json({"suc": False, "err": "Command timed out (60s)"}, 500)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)}, 500)
            return
        
        # GET EAA LOGS
        if path == '/logs' or path == '/v1/remote/logs':
            log_file = r"C:\Users\offic\EAA\eaa_terminal.log"
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[-100:]
                self.send_json({"suc": True, "logs": "".join(lines)})
            except FileNotFoundError:
                self.send_json({"suc": False, "err": "Log file not found"}, 404)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)}, 500)
            return
        
        # AI CHAT - Forward to EAA backend
        if path == '/ai/chat':
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
        
        # UNKNOWN ENDPOINT
        self.send_json({"suc": False, "err": f"Unknown endpoint: {path}"}, 404)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Handle requests in separate threads"""
    allow_reuse_address = True
    daemon_threads = True


def set_credentials(api_key: str, secret_phrase: str):
    """Set authentication credentials"""
    SecureControlHandler.api_key = api_key
    SecureControlHandler.secret_phrase = secret_phrase
    SecureControlHandler.session_token = None
    print(f"[AUTH] Credentials set. Secret: '{secret_phrase[:3]}...{secret_phrase[-3:]}'")


def start_server():
    """Start the control station"""
    print("\n" + "=" * 60)
    print("  EAA CONTROL STATION V5 - FULL REMOTE CONTROL")
    print("=" * 60)
    print(f"  📸 Screenshot: {'✅ Enabled' if HAS_PIL else '❌ Install Pillow'}")
    print(f"  🖱️ Mouse Control: {'✅ Enabled' if HAS_PYAUTOGUI else '❌ Install pyautogui'}")
    print(f"  ⌨️ Keyboard Control: {'✅ Enabled' if HAS_PYAUTOGUI else '❌ Install pyautogui'}")
    print("=" * 60)
    
    if not HAS_PYAUTOGUI or not HAS_PIL:
        print("\n  ⚠️ Install for full control:")
        print("     pip install pyautogui Pillow")
        print()
    
    with ThreadedHTTPServer(("0.0.0.0", PORT), SecureControlHandler) as httpd:
        print(f"[CONTROL] 🚀 Control Station V5 listening on port {PORT}")
        if SecureControlHandler.secret_phrase:
            print(f"[CONTROL] 🔐 Secret phrase: '{SecureControlHandler.secret_phrase}'")
        print(f"[CONTROL] ⏰ Session timeout: DISABLED")
        httpd.serve_forever()


if __name__ == "__main__":
    test_key = secrets.token_urlsafe(32)
    test_secret = "test-secret-phrase"
    set_credentials(test_key, test_secret)
    print(f"\n[TEST] API Key: {test_key}")
    print(f"[TEST] Secret: {test_secret}\n")
    start_server()
