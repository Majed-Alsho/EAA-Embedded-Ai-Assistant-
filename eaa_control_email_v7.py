"""
EAA CONTROL SYSTEM V7 - COMPLETE BULLETPROOF
=============================================
Combines:

V5 Bulletproof features (watchdog, email, auto-restart, session security)
V6 New features (audio, webcam, OCR, recording, GPU, network tools)
NEVER CRASHES - AUTO-RESTART - EMAIL ALERTS

Screenshot, Mouse, Keyboard control
File operations, Shell access
System monitoring, Process management
NEW: Audio control (volume, mute, TTS)
NEW: Webcam capture
NEW: Screen recording
NEW: OCR text recognition
NEW: File search
NEW: Network tools (ping, download, check_port)
NEW: Media control
NEW: GPU monitoring
NEW: Image operations
NEW: Quick actions
EAA AI integration with AUTO-RESTART
Auto-restart tunnel if it dies
EMAIL notification when tunnel restarts
Watchdog monitors everything
Session token security
Auth: X-Control-Key header OR X-Secret header OR JSON body

By Majed Al-Shoghri
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
import tempfile
import socket
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
EMAIL_PASSWORD = "jgdkcwuqcqnrlnya" # Gmail App Password

def send_email_notification(subject, body):
    """Send email notification - never crashes server, has timeout"""
    if not EMAIL_ENABLED:
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
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
    subject = f"EAA Control V7 - {reason}"

    body = f"""
{'='*60}
EAA CONTROL SYSTEM V7 - NOTIFICATION
{'='*60}

{reason.upper()}

{'='*60}
NEW CONNECTION INFO
{'='*60}

URL: {url}
API Key: {api_key}
Secret: {secret}

{'='*60}
COPY THIS TO SUPER Z:
{'='*60}

URL: {url}
Key: {api_key}
Secret: {secret}

{'='*60}
AVAILABLE FEATURES V7
{'='*60}

SCREENSHOT: GET {url}/screenshot
CLICK: POST {url}/mouse/click
TYPE: POST {url}/keyboard/type
KEY: POST {url}/keyboard/press
FILES: POST {url}/file/read, /file/write, /file/list
SHELL: POST {url}/shell
AUDIO: POST {url}/audio/volume/set, /audio/tts
WEBCAM: POST {url}/webcam/capture
OCR: POST {url}/ocr/screenshot
NETWORK: POST {url}/network/download, /network/ping
RECORDING: POST {url}/recording/start, /recording/stop
GPU: GET {url}/system/info (includes GPU)

Timestamp: {timestamp}

Your AI assistant Super Z needs this to reconnect!
{'='*60}
"""
    return send_email_notification(subject, body)

def send_startup_notification(url, api_key, secret):
    """Send email on server startup"""
    return send_tunnel_notification(url, api_key, secret, "Server Started")

def send_crash_notification(reason="Server Crashed"):
    """Send email when server crashes and restarts"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"🚨 EAA Control V7 - {reason}"

    body = f"""
{'='*60}
EAA CONTROL V7 - SUPERVISOR NOTIFICATION
{'='*60}

{reason.upper()}

The server has been automatically restarted!
New credentials will be in the next email.

{'='*60}
WHAT HAPPENED:
{'='*60}

Server crashed or was stopped
Supervisor detected it
Server was automatically restarted
New tunnel was created
You'll receive new credentials shortly
Timestamp: {timestamp}

{'='*60}
CHECK YOUR NEXT EMAIL FOR NEW CREDENTIALS!
{'='*60}
"""
    return send_email_notification(subject, body)

# ============================================
# BULLETPROOF SETTINGS
# ============================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(SCRIPT_DIR, "tools")
CLOUDFLARED_PATH = os.path.join(TOOLS_DIR, "cloudflared.exe")
ALLOWED_PATH = r"C:\Users\offic"
PORT = 8001
EAA_SCRIPT = os.path.join(SCRIPT_DIR, "run_eaa_v4.py")  # V4 bridge
EAA_BACKEND_URL = "http://localhost:8000"

# Auto-restart settings
EAA_AUTO_RESTART = True
TUNNEL_AUTO_RESTART = True
WATCHDOG_INTERVAL = 10 # Check every 10 seconds

# Generate credentials
API_KEY = secrets.token_urlsafe(32)
SECRET_PHRASE = secrets.choice([
"alpha-bravo-charlie", "delta-echo-foxtrot", "golf-hotel-india",
"juliet-kilo-lima", "mike-november-oscar", "papa-quebec-romeo",
"sierra-tango-uniform", "victor-whiskey-xray", "yankee-zulu-alpha",
"bravo-mike-steel", "shadow-zulu-mike"
])

# Session
SESSION_TIMEOUT = 60 # 1 minute timeout (easier to reconnect)
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
HAS_CV2 = False
HAS_PYTESSERACT = False
HAS_NUMPY = False
HAS_TTS = False
HAS_GPU = False

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
    import io
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

# V6 NEW DEPENDENCIES
try:
    import cv2
    HAS_CV2 = True
    log("[OK] opencv-python loaded - webcam enabled")
except Exception as e:
    log(f"[WARN] opencv-python not available - webcam disabled")

try:
    import pytesseract
    HAS_PYTESSERACT = True
    log("[OK] pytesseract loaded - OCR enabled")
except Exception as e:
    log(f"[WARN] pytesseract not available - OCR disabled")

try:
    import numpy as np
    HAS_NUMPY = True
except:
    pass

try:
    import eaa_voice
    HAS_TTS = True
    log("[OK] eaa_voice (Neural TTS) loaded - Christopher voice enabled")
except Exception as e:
    log(f"[WARN] eaa_voice not available - TTS disabled: {e}")

try:
    import GPUtil
    HAS_GPU = True
    log("[OK] GPUtil loaded - GPU monitoring enabled")
except Exception as e:
    log(f"[WARN] GPUtil not available - GPU monitoring disabled")

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

        # V6 NEW STATE
        self._recording = {
            "active": False,
            "frames": [],
            "start_time": None,
            "region": None,
            "fps": 10
        }
        self._clipboard_history = []

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

    @property
    def recording(self):
        with self._lock:
            return self._recording.copy()

    @recording.setter
    def recording(self, val):
        with self._lock:
            self._recording = val

    @property
    def clipboard_history(self):
        with self._lock:
            return self._clipboard_history.copy()

    def add_clipboard(self, content):
        with self._lock:
            self._clipboard_history.insert(0, {"content": content, "time": datetime.now().isoformat()})
            self._clipboard_history = self._clipboard_history[:50]

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
                info["ram_used_gb"] = round(psutil.virtual_memory().used / (1024**3), 2)
                info["ram_total_gb"] = round(psutil.virtual_memory().total / (1024**3), 2)
            except:
                pass
            try:
                info["disk_percent"] = psutil.disk_usage('C:\\').percent
            except:
                info["disk_percent"] = 0
            try:
                info["disk_free_gb"] = round(psutil.disk_usage('C:\\').free / (1024**3), 2)
            except:
                pass
            try:
                info["uptime"] = int(time.time() - psutil.boot_time())
            except:
                info["uptime"] = 0
            try:
                info["processes"] = len(psutil.pids())
            except:
                pass
            try:
                net = psutil.net_io_counters()
                info["network"] = {
                    "bytes_sent_mb": round(net.bytes_sent / (1024**2), 2),
                    "bytes_recv_mb": round(net.bytes_recv / (1024**2), 2),
                }
            except:
                pass

        # V6: GPU monitoring
        if HAS_GPU:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    info["gpu"] = [{
                        "name": g.name,
                        "load": round(g.load * 100, 1),
                        "memory_used": round(g.memoryUsed, 1),
                        "memory_total": round(g.memoryTotal, 1),
                        "temperature": g.temperature
                    } for g in gpus]
            except:
                pass

        return info
    except:
        return {"timestamp": datetime.now().isoformat()}
        
def safe_get_processes():
    if not HAS_PSUTIL:
        return []
    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'exe']):
            try:
                procs.append({
                    "pid": p.info['pid'],
                    "name": p.info.get('name', 'unknown'),
                    "cpu": round(p.info.get('cpu_percent') or 0, 1),
                    "memory": round(p.info.get('memory_percent') or 0, 1),
                    "exe": p.info.get('exe', '') or ""
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

        # V6: Add to clipboard history
        state.add_clipboard(str(content))

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
# V6 NEW FUNCTIONS - AUDIO
# ============================================
def set_volume(level):
    """Set system volume (0-100)"""
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(level / 100.0, None)
        return True, None
    except:
        # Fallback: use keyboard
        try:
            # Set to 0 first
            for _ in range(50):
                subprocess.run("powershell -command \"$wsh = New-Object -ComObject WScript.Shell; $wsh.SendKeys([char]174)\"", shell=True, capture_output=True)
            # Then increase to target
            steps = int(level / 2)
            for _ in range(steps):
                subprocess.run("powershell -command \"$wsh = New-Object -ComObject WScript.Shell; $wsh.SendKeys([char]175)\"", shell=True, capture_output=True)
            return True, "Volume adjusted (limited control - install pycaw for precise control)"
        except Exception as e:
            return False, str(e)
            
def get_volume():
    """Get current system volume"""
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        return round(volume.GetMasterVolumeLevelScalar() * 100), None
    except:
        return None, "pycaw not installed"
        
def set_mute(mute=True):
    """Mute/unmute system audio"""
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMute(1 if mute else 0, None)
        return True, None
    except Exception as e:
        return False, str(e)
        
def text_to_speech(text):
    """Speak text using Neural TTS (Christopher voice)"""
    if not HAS_TTS:
        return False, "eaa_voice not installed"
    try:
        eaa_voice.say(text)
        return True, None
    except Exception as e:
        return False, str(e)

def play_sound(sound_name="default"):
    """Play system sound"""
    sounds = {
        "default": "Windows Notify System",
        "asterisk": "Windows Background",
        "notification": "Windows Notify System",
        "error": "Windows Critical Stop",
        "question": "Windows Question",
        "warning": "Windows Exclamation",
    }
    try:
        sound = sounds.get(sound_name, "Windows Notify System")
        subprocess.run(f'powershell -command "(New-Object Media.SoundPlayer \'C:\\Windows\\Media\\{sound}.wav\').PlaySync()"', shell=True, capture_output=True)
        return True, None
    except Exception as e:
        return False, str(e)

# ============================================
# V6 NEW FUNCTIONS - WEBCAM
# ============================================
def capture_webcam():
    """Capture image from webcam"""
    if not HAS_CV2:
        return None, "opencv-python not installed"
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return None, "Cannot open webcam"

        ret, frame = cap.read()
        cap.release()

        if not ret:
            return None, "Failed to capture image"

        _, buffer = cv2.imencode('.png', frame)
        return base64.b64encode(buffer).decode(), None
    except Exception as e:
        return None, str(e)
        
def list_webcams():
    """List available webcams"""
    if not HAS_CV2:
        return [], "opencv-python not installed"
    cams = []
    for i in range(3):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            cams.append({"index": i, "available": True})
        cap.release()
    return cams, None

# ============================================
# V6 NEW FUNCTIONS - SCREEN RECORDING
# ============================================
def start_recording(region=None, fps=10):
    """Start screen recording"""
    rec = state.recording
    if rec["active"]:
        return False, "Already recording"

    state.recording = {
        "active": True,
        "frames": [],
        "start_time": time.time(),
        "region": region,
        "fps": fps
    }

    def record_loop():
        while state.recording["active"]:
            try:
                if state.recording["region"]:
                    x, y, w, h = state.recording["region"]
                    img = pyautogui.screenshot(region=(x, y, w, h))
                else:
                    img = pyautogui.screenshot()

                buf = io.BytesIO()
                img.save(buf, format="PNG")

                rec = state.recording
                rec["frames"].append(buf.getvalue())
                state.recording = rec

                time.sleep(1.0 / fps)
            except:
                break

    threading.Thread(target=record_loop, daemon=True).start()
    return True, None
    
def stop_recording(save_path=None):
    """Stop screen recording"""
    rec = state.recording
    if not rec["active"]:
        return None, "Not recording"

    state.recording = {k: (False if k == "active" else ([] if k == "frames" else None if k in ["start_time", "region"] else v)) for k, v in rec.items()}
    state.recording["fps"] = 10

    frames = rec["frames"]
    duration = time.time() - rec["start_time"] if rec["start_time"] else 0

    if not frames:
        return None, "No frames recorded"

    if save_path and HAS_CV2 and HAS_NUMPY:
        try:
            first_img = Image.open(io.BytesIO(frames[0]))
            width, height = first_img.size

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(save_path, fourcc, rec["fps"], (width, height))

            for frame_data in frames:
                img = Image.open(io.BytesIO(frame_data))
                img_array = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                out.write(img_array)

            out.release()
            return {"frames": len(frames), "duration": round(duration, 2), "saved_to": save_path}, None
        except Exception as e:
            return {"frames": len(frames), "duration": round(duration, 2)}, str(e)

    # Return sample frames as base64
    frames_b64 = [base64.b64encode(f).decode() for f in frames[:30]]
    return {"frames": len(frames), "duration": round(duration, 2), "sample_frames": frames_b64}, None
    
# ============================================
# V6 NEW FUNCTIONS - OCR
# ============================================
def ocr_screenshot(region=None):
    """OCR text from screenshot"""
    if not HAS_PYTESSERACT:
        return None, "pytesseract not installed"

    try:
        if region:
            x, y, w, h = region
            img = pyautogui.screenshot(region=(x, y, w, h))
        else:
            img = pyautogui.screenshot()

        text = pytesseract.image_to_string(img)
        return text.strip(), None
    except Exception as e:
        return None, str(e)
        
def ocr_image(image_base64):
    """OCR text from base64 image"""
    if not HAS_PYTESSERACT:
        return None, "pytesseract not installed"

    try:
        img_data = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(img_data))
        text = pytesseract.image_to_string(img)
        return text.strip(), None
    except Exception as e:
        return None, str(e)
        
# ============================================
# V6 NEW FUNCTIONS - FILE SEARCH
# ============================================
def search_files(query, path=None, max_results=50):
    """Search for files by name"""
    if path is None:
        path = ALLOWED_PATH

    if not validate_path(path):
        return [], "Access denied"

    results = []
    query_lower = query.lower()

    try:
        for root, dirs, files in os.walk(path):
            for name in files + dirs:
                if query_lower in name.lower():
                    full_path = os.path.join(root, name)
                    try:
                        results.append({
                            "path": full_path,
                            "name": name,
                            "is_dir": os.path.isdir(full_path),
                            "size": os.path.getsize(full_path) if os.path.isfile(full_path) else 0,
                            "modified": datetime.fromtimestamp(os.path.getmtime(full_path)).isoformat()
                        })
                    except:
                        pass

                    if len(results) >= max_results:
                        return results, None
        return results, None
    except Exception as e:
        return results, str(e)
        
def search_in_files(query, path=None, extensions=None, max_results=30):
    """Search for text inside files"""
    if path is None:
        path = ALLOWED_PATH

    if not validate_path(path):
        return [], "Access denied"

    if extensions is None:
        extensions = ['.txt', '.py', '.js', '.json', '.md', '.html', '.css', '.xml', '.log', '.csv', '.yaml', '.yml', '.cfg', '.ini']

    results = []
    query_lower = query.lower()

    try:
        for root, dirs, files in os.walk(path):
            for name in files:
                ext = os.path.splitext(name)[1].lower()
                if ext in extensions:
                    full_path = os.path.join(root, name)
                    try:
                        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                            for i, line in enumerate(f, 1):
                                if query_lower in line.lower():
                                    results.append({
                                        "path": full_path,
                                        "line": i,
                                        "content": line.strip()[:200]
                                    })
                                    if len(results) >= max_results:
                                        return results, None
                    except:
                        pass
        return results, None
    except Exception as e:
        return results, str(e)
        
# ============================================
# V6 NEW FUNCTIONS - NETWORK TOOLS
# ============================================
def download_file(url, save_path, timeout=60):
    """Download file from URL"""
    if not validate_path(save_path):
        return False, "Access denied"

    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            with open(save_path, 'wb') as f:
                f.write(response.read())

        return True, None
    except Exception as e:
        return False, str(e)
        
def ping_host(host, count=4):
    """Ping a host"""
    try:
        result = subprocess.run(
            f"ping -n {count} {host}",
            shell=True, capture_output=True, text=True, timeout=30
        )
        return {"output": result.stdout, "success": result.returncode == 0}, None
    except Exception as e:
        return None, str(e)

def check_port(host, port, timeout=5):
    """Check if a port is open"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return {"open": result == 0, "port": port, "host": host}, None
    except Exception as e:
        return {"open": False, "port": port, "host": host, "error": str(e)}, None

def get_public_ip():
    """Get public IP address"""
    try:
        req = urllib.request.urlopen("https://api.ipify.org?format=json", timeout=5)
        data = json.loads(req.read().decode())
        return data.get("ip"), None
    except Exception as e:
        return None, str(e)

# ============================================
# V6 NEW FUNCTIONS - MEDIA CONTROL
# ============================================
def media_control(action):
    """Control media playback"""
    try:
        if action == "play_pause":
            pyautogui.press('playpause')
        elif action == "next":
            pyautogui.press('nexttrack')
        elif action == "prev":
            pyautogui.press('prevtrack')
        elif action == "stop":
            pyautogui.press('stop')
        elif action == "volume_up":
            pyautogui.press('volumeup')
        elif action == "volume_down":
            pyautogui.press('volumedown')
        elif action == "mute":
            pyautogui.press('volumemute')
        else:
            return False, f"Unknown action: {action}"
        return True, None
    except Exception as e:
        return False, str(e)

# ============================================
# V6 NEW FUNCTIONS - IMAGE OPERATIONS
# ============================================
def resize_image(image_base64, width, height):
    """Resize an image"""
    if not HAS_PIL:
        return None, "Pillow not installed"

    try:
        img_data = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(img_data))
        img = img.resize((width, height), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode(), None
    except Exception as e:
        return None, str(e)
        
def convert_image(image_base64, fmt="JPEG"):
    """Convert image format"""
    if not HAS_PIL:
        return None, "Pillow not installed"

    try:
        img_data = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(img_data))

        if img.mode in ('RGBA', 'P') and fmt.upper() == 'JPEG':
            img = img.convert('RGB')

        buf = io.BytesIO()
        img.save(buf, format=fmt.upper())
        return base64.b64encode(buf.getvalue()).decode(), None
    except Exception as e:
        return None, str(e)
        
def get_image_info(image_base64):
    """Get image information"""
    if not HAS_PIL:
        return None, "Pillow not installed"

    try:
        img_data = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(img_data))

        return {
            "width": img.width,
            "height": img.height,
            "format": img.format,
            "mode": img.mode,
            "size_bytes": len(img_data)
        }, None
    except Exception as e:
        return None, str(e)
        
# ============================================
# V6 NEW FUNCTIONS - QUICK ACTIONS
# ============================================
def quick_action(action):
    """Execute quick system action"""
    actions = {
        "lock_screen": lambda: os.system("rundll32.exe user32.dll,LockWorkStation"),
        "task_manager": lambda: subprocess.run("taskmgr", shell=True),
        "file_explorer": lambda: subprocess.run("explorer", shell=True),
        "settings": lambda: subprocess.run("start ms-settings:", shell=True),
        "calculator": lambda: subprocess.run("calc", shell=True),
        "notepad": lambda: subprocess.run("notepad", shell=True),
        "paint": lambda: subprocess.run("mspaint", shell=True),
        "empty_trash": lambda: subprocess.run('powershell -command "Clear-RecycleBin -Force"', shell=True),
        "show_desktop": lambda: pyautogui.hotkey('win', 'd') if HAS_PYAUTOGUI else None,
        "open_run": lambda: pyautogui.hotkey('win', 'r') if HAS_PYAUTOGUI else None,
        "open_search": lambda: pyautogui.hotkey('win', 's') if HAS_PYAUTOGUI else None,
        "emoji_picker": lambda: pyautogui.hotkey('win', '.') if HAS_PYAUTOGUI else None,
        "clipboard_history_win": lambda: pyautogui.hotkey('win', 'v') if HAS_PYAUTOGUI else None,
        "screenshot_tool": lambda: pyautogui.hotkey('win', 'shift', 's') if HAS_PYAUTOGUI else None,
        "game_bar": lambda: pyautogui.hotkey('win', 'g') if HAS_PYAUTOGUI else None,
        "action_center": lambda: pyautogui.hotkey('win', 'a') if HAS_PYAUTOGUI else None,
    }

    if action not in actions:
        return False, f"Unknown action: {action}. Available: {list(actions.keys())}"

    try:
        actions[action]()
        return True, None
    except Exception as e:
        return False, str(e)
        
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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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

        import tempfile
        cf_log_path = os.path.join(tempfile.gettempdir(), "cf_tunnel.log")
        cf_log = open(cf_log_path, "w")
        state.tunnel_process = subprocess.Popen(
            [CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{PORT}", "--no-autoupdate"],
            stdout=cf_log,
            stderr=cf_log
        )

        # Wait for URL by reading log file (no pipe = no overflow)
        for _ in range(30):
            time.sleep(1)
            try:
                with open(cf_log_path, "r") as lf:
                    for line in lf:
                        if "trycloudflare.com" in line:
                            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                            if match:
                                state.tunnel_url = match.group(0)
                                log(f"[TUNNEL] Started: {state.tunnel_url}")

                                def _email_with_retry():
                                    for attempt in range(3):
                                        ok = send_tunnel_notification(
                                            state.tunnel_url, API_KEY, SECRET_PHRASE,
                                            "Tunnel Restarted" if attempt > 0 else "Server Started"
                                        )
                                        if ok:
                                            return
                                        time.sleep(3 * (attempt + 1))
                                    log("[EMAIL] All 3 email attempts failed")

                                threading.Thread(target=_email_with_retry, daemon=True).start()
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
                send_email_notification("EAA V7 - AI Server Restarted",
                    f"EAA AI Server died and was auto-restarted by watchdog.\n"
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"Tunnel URL: {state.tunnel_url or 'N/A'}\n"
                    f"API Key: {API_KEY}\nSecret: {SECRET_PHRASE}")
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
# REQUEST HANDLER - BULLETPROOF V7
# ============================================
class BulletproofHandler(BaseHTTPRequestHandler):
    """Handler that NEVER crashes - V7 with all features"""

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

            # Valid API key but different session = take over (same owner re-connecting)
            old_token = session_token
            session_token = "SESS_" + secrets.token_urlsafe(32)
            session_time = time.time()
            log(f"[SESSION] Overridden (was {old_token[:15]}...) → new: {session_token[:15]}...")
            return True, None, session_token

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
                "version": "v7",
                "session_active": session_token is not None,
                "eaa_running": state.eaa_is_alive(),
                "tunnel_running": state.tunnel_is_alive(),
                "tunnel_url": state.tunnel_url,
                "remote_control": HAS_PYAUTOGUI,
                "screenshot": HAS_PIL,
                "webcam": HAS_CV2,
                "ocr": HAS_PYTESSERACT,
                "tts": HAS_TTS,
                "gpu": HAS_GPU
            })
            return

        if path == "/version":
            self.send_json({
                "version": "7.0.0",
                "features": {
                    "screenshot": HAS_PIL,
                    "remote_control": HAS_PYAUTOGUI,
                    "webcam": HAS_CV2,
                    "ocr": HAS_PYTESSERACT,
                    "tts": HAS_TTS,
                    "gpu": HAS_GPU
                }
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

        # CLIPBOARD HISTORY
        if path == "/clipboard/history":
            self.send_json({"suc": True, "history": state.clipboard_history, **resp})
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
            rec = state.recording
            self.send_json({
                "suc": True,
                "eaa_running": state.eaa_is_alive(),
                "eaa_pid": state.eaa_pid,
                "tunnel_running": state.tunnel_is_alive(),
                "tunnel_url": state.tunnel_url,
                "recording": rec.get("active", False),
                "recording_frames": len(rec.get("frames", [])),
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

        # NETWORK PUBLIC IP
        if path == "/network/public_ip":
            ip, err = get_public_ip()
            if err:
                self.send_json({"suc": False, "err": err, **resp})
            else:
                self.send_json({"suc": True, "ip": ip, **resp})
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

        # === AI AGENT PROXY ENDPOINTS (Add after /v1/agent/tools) ===

        # AGENT CHAT - Let AI use tools
        if path == "/v1/agent/chat":
            try:
                req_data = json.dumps(data).encode()
                proxy_req = urllib.request.Request(
                    f"{EAA_BACKEND_URL}/v1/agent/chat",
                    data=req_data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(proxy_req, timeout=120) as resp_req:
                    response = json.loads(resp_req.read().decode())
                    self.send_json({**response, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return

        # AGENT RUN - Streaming AI execution
        if path == "/v1/agent/run":
            try:
                req_data = json.dumps(data).encode()
                proxy_req = urllib.request.Request(
                    f"{EAA_BACKEND_URL}/v1/agent/run",
                    data=req_data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(proxy_req, timeout=300) as resp_req:
                    # For streaming, just return the raw response
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    while True:
                        chunk = resp_req.read(1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return

        # AGENT STATUS
        if path == "/v1/agent/status":
            try:
                proxy_req = urllib.request.Request(
                    f"{EAA_BACKEND_URL}/v1/agent/status",
                    method="GET"
                )
                with urllib.request.urlopen(proxy_req, timeout=10) as resp_req:
                    response = json.loads(resp_req.read().decode())
                    self.send_json({**response, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return

        # AGENT STOP
        if path == "/v1/agent/stop":
            try:
                proxy_req = urllib.request.Request(
                    f"{EAA_BACKEND_URL}/v1/agent/stop",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(proxy_req, timeout=10) as resp_req:
                    response = json.loads(resp_req.read().decode())
                    self.send_json({**response, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return

        # AGENT VRAM
        if path == "/v1/agent/vram":
            try:
                proxy_req = urllib.request.Request(
                    f"{EAA_BACKEND_URL}/v1/agent/vram",
                    method="GET"
                )
                with urllib.request.urlopen(proxy_req, timeout=10) as resp_req:
                    response = json.loads(resp_req.read().decode())
                    self.send_json({**response, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return

        # === BIG FILE WRITE - For Super Z to send large content ===

        if path == "/file/write/big":
            """Write large text in chunks - for Super Z"""
            file_path = data.get("path", "")
            content = data.get("content", "")
            mode = data.get("mode", "w")  # "w" for write, "a" for append
            
            if not validate_path(file_path):
                self.send_json({"suc": False, "err": "Access denied", **resp})
                return
            
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, mode, encoding="utf-8") as f:
                    f.write(str(content))
                
                size = os.path.getsize(file_path)
                log(f"[FILE] Big write: {file_path} ({size} bytes)")
                self.send_json({"suc": True, "size": size, "path": file_path, **resp})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e), **resp})
            return

        # AUDIO VOLUME GET
        if path == "/audio/volume":
            level, err = get_volume()
            if err:
                self.send_json({"suc": False, "err": err, **resp})
            else:
                self.send_json({"suc": True, "volume": level, **resp})
            return

        # WEBCAM LIST
        if path == "/webcam/list":
            cams, err = list_webcams()
            self.send_json({"suc": True, "webcams": cams, **resp})
            return

        # RECORDING STATUS
        if path == "/recording/status":
            rec = state.recording
            self.send_json({
                "suc": True,
                "active": rec.get("active", False),
                "frames": len(rec.get("frames", [])),
                "duration": time.time() - rec["start_time"] if rec.get("active") and rec.get("start_time") else 0,
                **resp
            })
            return

        # === POST-ONLY ENDPOINTS ===

        if method != "POST":
            self.send_json({"suc": False, "err": "Use POST", **resp})
            return

        # MOUSE MOVE
        if path in ["/mouse/move", "/mousemove"]:
            if HAS_PYAUTOGUI:
                try:
                    pyautogui.moveTo(data.get("x", 0), data.get("y", 0), duration=data.get("duration", 0))
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

        # MOUSE DRAG
        if path == "/mouse/drag":
            if HAS_PYAUTOGUI:
                try:
                    start_x = data.get("startX", 0)
                    start_y = data.get("startY", 0)
                    end_x = data.get("endX", 0)
                    end_y = data.get("endY", 0)
                    pyautogui.moveTo(start_x, start_y)
                    pyautogui.drag(end_x - start_x, end_y - start_y, duration=data.get("duration", 0.5), button=data.get("button", "left"))
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

        # === V6 NEW AUDIO ENDPOINTS ===

        # AUDIO VOLUME SET
        if path == "/audio/volume/set":
            ok, err = set_volume(data.get("level", 50))
            if err:
                self.send_json({"suc": ok, "err": err, **resp})
            else:
                self.send_json({"suc": True, "volume": data.get("level", 50), **resp})
            return

        # AUDIO MUTE
        if path == "/audio/mute":
            ok, err = set_mute(True)
            if err:
                self.send_json({"suc": ok, "err": err, **resp})
            else:
                self.send_json({"suc": True, "muted": True, **resp})
            return

        # AUDIO UNMUTE
        if path == "/audio/unmute":
            ok, err = set_mute(False)
            if err:
                self.send_json({"suc": ok, "err": err, **resp})
            else:
                self.send_json({"suc": True, "muted": False, **resp})
            return

        # TEXT TO SPEECH
        if path in ["/audio/tts", "/speak"]:
            ok, err = text_to_speech(data.get("text", ""))
            if err:
                self.send_json({"suc": ok, "err": err, **resp})
            else:
                self.send_json({"suc": True, **resp})
            return

        # PLAY SOUND
        if path == "/audio/play":
            ok, err = play_sound(data.get("sound", "default"))
            if err:
                self.send_json({"suc": ok, "err": err, **resp})
            else:
                self.send_json({"suc": True, **resp})
            return

        # === V6 MEDIA CONTROL ===

        if path == "/media/control":
            ok, err = media_control(data.get("action", "play_pause"))
            if err:
                self.send_json({"suc": ok, "err": err, **resp})
            else:
                self.send_json({"suc": True, "action": data.get("action"), **resp})
            return

        # === V6 WEBCAM ===

        if path == "/webcam/capture":
            img, err = capture_webcam()
            if err:
                self.send_json({"suc": False, "err": err, **resp})
            else:
                self.send_json({"suc": True, "image": img, **resp})
            return

        # === V6 RECORDING ===

        if path == "/recording/start":
            ok, err = start_recording(data.get("region"), data.get("fps", 10))
            if err:
                self.send_json({"suc": ok, "err": err, **resp})
            else:
                self.send_json({"suc": True, "message": "Recording started", **resp})
            return

        if path == "/recording/stop":
            result, err = stop_recording(data.get("path"))
            if err and not result:
                self.send_json({"suc": False, "err": err, **resp})
            else:
                self.send_json({"suc": True, "result": result, "warning": err, **resp})
            return

        # === V6 OCR ===

        if path == "/ocr/screenshot":
            text, err = ocr_screenshot(data.get("region"))
            if err:
                self.send_json({"suc": False, "err": err, **resp})
            else:
                self.send_json({"suc": True, "text": text, **resp})
            return

        if path == "/ocr/image":
            text, err = ocr_image(data.get("image", ""))
            if err:
                self.send_json({"suc": False, "err": err, **resp})
            else:
                self.send_json({"suc": True, "text": text, **resp})
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
                        "modified": datetime.fromtimestamp(os.path.getmtime(full)).isoformat() if os.path.exists(full) else None
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

        # === V6 FILE SEARCH ===

        if path == "/file/search":
            results, err = search_files(data.get("query", ""), data.get("path"), data.get("max_results", 50))
            self.send_json({"suc": True, "results": results, "error": err, **resp})
            return

        if path == "/file/search_content":
            results, err = search_in_files(data.get("query", ""), data.get("path"), data.get("extensions"), data.get("max_results", 30))
            self.send_json({"suc": True, "results": results, "error": err, **resp})
            return

        # === V6 NETWORK TOOLS ===

        if path == "/network/download":
            url = data.get("url", "")
            save_path = data.get("path", "")
            if not url or not save_path:
                self.send_json({"suc": False, "err": "url and path required", **resp})
                return
            ok, err = download_file(url, save_path)
            if err:
                self.send_json({"suc": ok, "err": err, **resp})
            else:
                self.send_json({"suc": True, "saved_to": save_path, **resp})
            return

        if path == "/network/ping":
            result, err = ping_host(data.get("host", "google.com"), data.get("count", 4))
            if err:
                self.send_json({"suc": False, "err": err, **resp})
            else:
                self.send_json({"suc": True, "result": result, **resp})
            return

        if path == "/network/check_port":
            result, _ = check_port(data.get("host", "localhost"), data.get("port", 80))
            self.send_json({"suc": True, "result": result, **resp})
            return

        # === V6 IMAGE OPERATIONS ===

        if path == "/image/resize":
            result, err = resize_image(data.get("image", ""), data.get("width", 800), data.get("height", 600))
            if err:
                self.send_json({"suc": False, "err": err, **resp})
            else:
                self.send_json({"suc": True, "image": result, **resp})
            return

        if path == "/image/convert":
            result, err = convert_image(data.get("image", ""), data.get("format", "JPEG"))
            if err:
                self.send_json({"suc": False, "err": err, **resp})
            else:
                self.send_json({"suc": True, "image": result, "format": data.get("format", "JPEG"), **resp})
            return

        if path == "/image/info":
            result, err = get_image_info(data.get("image", ""))
            if err:
                self.send_json({"suc": False, "err": err, **resp})
            else:
                self.send_json({"suc": True, "info": result, **resp})
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
                    found = [False]
                    def enum_cb(hwnd, ctx):
                        try:
                            if win32gui.IsWindowVisible(hwnd):
                                if title in win32gui.GetWindowText(hwnd).lower():
                                    win32gui.SetForegroundWindow(hwnd)
                                    win32gui.ShowWindow(hwnd, 9)
                                    found[0] = True
                        except:
                            pass
                    win32gui.EnumWindows(enum_cb, None)
                    log(f"[WINDOW] Focus: {title}")
                    self.send_json({"suc": found[0], **resp})
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
                ps_cmd = f'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show("{message}", "{title}")'
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

        # === V6 QUICK ACTIONS ===

        if path == "/quick/action":
            ok, err = quick_action(data.get("action", ""))
            if err:
                self.send_json({"suc": ok, "err": err, **resp})
            else:
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
                if state.eaa_process:
                    stop_eaa()
                if state.tunnel_process:
                    stop_tunnel()
                self.send_json({"suc": True, "message": "Stopped", **resp})
            elif cmd == "restart":
                if state.eaa_process:
                    stop_eaa()
                time.sleep(1)
                start_eaa()
                self.send_json({"suc": True, "message": "Restarted", **resp})
            elif cmd == "restart_tunnel":
                restart_tunnel()
                self.send_json({"suc": True, "message": "Tunnel restarted", **resp})
            else:
                self.send_json({"suc": False, "err": "Unknown command", **resp})
            return

        # POWER CONTROLS
        if path == "/power/sleep":
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
            self.send_json({"suc": True, **resp})
            return

        if path == "/power/restart":
            os.system("shutdown /r /t 10")
            self.send_json({"suc": True, "message": "Restarting in 10s", **resp})
            return

        if path == "/power/shutdown":
            os.system("shutdown /s /t 10")
            self.send_json({"suc": True, "message": "Shutting down in 10s", **resp})
            return

        if path == "/power/cancel":
            os.system("shutdown /a")
            self.send_json({"suc": True, "message": "Cancelled", **resp})
            return

        # Unknown endpoint
        self.send_json({"suc": False, "err": f"Unknown endpoint: {path}", **resp})

# ============================================
# MAIN
# ============================================
def run_server():
    server = HTTPServer(("0.0.0.0", PORT), BulletproofHandler)
    server.serve_forever()

def cleanup():
    log("[STOP] Stopping all processes...")
    state.running = False
    for p in [state.eaa_process, state.tunnel_process]:
        if p and p.poll() is None:
            try:
                p.terminate()
            except:
                pass
    log("[BYE] All stopped!")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))

    print("=" * 60)
    print("  EAA CONTROL SYSTEM V7 - COMPLETE BULLETPROOF")
    print("  All V5 features + V6 new features!")
    print("=" * 60)

    log("[CHECK] Loading dependencies...")
    log(f"[OK] pyautogui: {HAS_PYAUTOGUI}")
    log(f"[OK] Pillow: {HAS_PIL}")
    log(f"[OK] psutil: {HAS_PSUTIL}")
    log(f"[OK] opencv (webcam): {HAS_CV2}")
    log(f"[OK] pytesseract (OCR): {HAS_PYTESSERACT}")
    log(f"[OK] pyttsx3 (TTS): {HAS_TTS}")
    log(f"[OK] GPUtil: {HAS_GPU}")

    print(f"\n[KEY] Generated API Key: {API_KEY}")
    print(f"[SECRET] Generated Secret Phrase: {SECRET_PHRASE}")

    print("\n[START] Starting Control Station V7...")

    print("\n" + "=" * 60)
    print("  EAA CONTROL STATION V7 - FULL REMOTE CONTROL")
    print("=" * 60)
    print(f"  📸 Screenshot: {'✅' if HAS_PIL else '❌'}")
    print(f"  🖱️ Mouse Control: {'✅' if HAS_PYAUTOGUI else '❌'}")
    print(f"  ⌨️ Keyboard Control: {'✅' if HAS_PYAUTOGUI else '❌'}")
    print(f"  🎤 Webcam: {'✅' if HAS_CV2 else '❌'}")
    print(f"  📝 OCR: {'✅' if HAS_PYTESSERACT else '❌'}")
    print(f"  🔊 TTS: {'✅' if HAS_TTS else '❌'}")
    print(f"  🎮 GPU Monitor: {'✅' if HAS_GPU else '❌'}")
    print("=" * 60)

    # Start EAA
    print("\n[START] Starting EAA AI Server...")
    start_eaa()

    # Start tunnel
    print("\n[START] Starting Cloudflare Tunnel...")
    url = start_tunnel()

    if url:
        print(f"\n[TUNNEL] ✅ {url}")
    else:
        print("[TUNNEL] ⚠️ Tunnel failed to start")

    # Start watchdog
    print("\n[WATCHDOG] Starting monitor thread...")
    threading.Thread(target=watchdog, daemon=True).start()

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