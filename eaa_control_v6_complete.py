"""
EAA CONTROL SYSTEM V6 - COMPLETE REMOTE CONTROL
================================================
Full remote control with ALL endpoints:
- Tier 1: System Awareness (health, system info, processes, screenshot)
- Tier 2: Active Control (windows, clipboard, browser, notifications)
- Tier 3: Full Control (mouse, keyboard, power, shell, files)
- NEW Tier 4: Audio Control (volume, mute, TTS)
- NEW Tier 5: Media Control (play/pause, next/prev)
- NEW Tier 6: Webcam & Recording
- NEW Tier 7: OCR Text Recognition
- NEW Tier 8: Enhanced Search & Network
- Email notifications when tunnel starts
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
import shutil
import signal
import smtplib
import urllib.request
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

# NEW DEPENDENCIES
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("[WARN] opencv-python not available - webcam disabled")

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False
    print("[WARN] pytesseract not available - OCR disabled")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False
    print("[WARN] pyttsx3 not available - TTS disabled")

try:
    import GPUtil
    GPU_AVAILABLE = True
except ImportError:
    GPU_AVAILABLE = False
    print("[WARN] GPUtil not available - GPU monitoring disabled")

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

# EMAIL CONFIGURATION
EMAIL_ENABLED = True
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_FROM = "majed1.alshoghri@gmail.com"
EMAIL_TO = "majed1.alshoghri@gmail.com"
EMAIL_PASSWORD = "vqgeblnuxfqsxbxn"

# ============================================
# GLOBAL STATE
# ============================================

eaa_process = None
tunnel_process = None
tunnel_url = None
eaa_tunnel_process = None
eaa_tunnel_url = None
email_sent = False

# Recording state
recording_state = {
    "active": False,
    "frames": [],
    "start_time": None,
    "region": None,
    "fps": 10
}

# Clipboard history
clipboard_history = []
MAX_CLIPBOARD_HISTORY = 50

# ============================================
# EMAIL FUNCTIONS (NEW)
# ============================================

def send_email(subject, body):
    """Send email notification"""
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
        
        print(f"[EMAIL] Sent: {subject}")
        return True
    except Exception as e:
        print(f"[EMAIL] Failed: {e}")
        return False

def send_tunnel_notification(url, key, secret):
    """Send email with tunnel credentials"""
    global email_sent
    if email_sent:
        return True
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = "EAA Control V6 - Tunnel Started!"
    
    body = f"""
{'='*60}
   EAA CONTROL SYSTEM V6 - TUNNEL ACTIVE
{'='*60}

TUNNEL URL: {url}

API KEY: {key}

SECRET PHRASE: {secret}

{'='*60}
   COPY THIS FOR SUPER Z:
{'='*60}

URL: {url}
Key: {key}
Secret: {secret}

Timestamp: {timestamp}
{'='*60}
"""
    
    result = send_email(subject, body)
    if result:
        email_sent = True
    return result

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
# HELPER FUNCTIONS (ORIGINAL)
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
            "ram_used_gb": round(psutil.virtual_memory().used / (1024**3), 2),
            "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "disk_percent": psutil.disk_usage('C:\\').percent,
            "disk_free_gb": round(psutil.disk_usage('C:\\').free / (1024**3), 2),
            "uptime": int(time.time() - psutil.boot_time()),
        })
        net = psutil.net_io_counters()
        info["network"] = {
            "bytes_sent_mb": round(net.bytes_sent / (1024**2), 2),
            "bytes_recv_mb": round(net.bytes_recv / (1024**2), 2),
        }
    if GPU_AVAILABLE:
        try:
            gpus = GPUtil.getGPUs()
            if gpus:
                info["gpu"] = [{"name": g.name, "load": round(g.load * 100, 1), "memory_used": round(g.memoryUsed, 1), "memory_total": round(g.memoryTotal, 1), "temperature": g.temperature} for g in gpus]
        except:
            pass
    return info

def get_process_list():
    if not PSUTIL_AVAILABLE:
        return []
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            procs.append({"pid": p.info['pid'], "name": p.info['name'], "cpu": round(p.info['cpu_percent'] or 0, 1), "memory": round(p.info['memory_percent'] or 0, 1)})
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
                windows.append({"hwnd": hwnd, "title": title, "active": hwnd == win32gui.GetForegroundWindow()})
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
        global clipboard_history
        clipboard_history.insert(0, {"content": content, "time": datetime.now().isoformat()})
        clipboard_history = clipboard_history[:MAX_CLIPBOARD_HISTORY]
        return True, None
    except Exception as e:
        return False, str(e)

def send_notification(title, message):
    try:
        ps_cmd = f'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show("{message}", "{title}")'
        subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=5)
        return True, None
    except Exception as e:
        return False, str(e)

def run_shell(cmd, timeout=30):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=ALLOWED_PATH)
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Timeout", "returncode": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1}

def start_tunnel(port):
    global tunnel_process, tunnel_url
    if not os.path.exists(CLOUDFLARED_PATH):
        print(f"[TUNNEL] cloudflared not found at {CLOUDFLARED_PATH}")
        return None
    try:
        tunnel_process = subprocess.Popen([CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{port}"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
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
    global eaa_process
    if not os.path.exists(EAA_SCRIPT):
        print(f"[EAA] Script not found: {EAA_SCRIPT}")
        return None
    try:
        eaa_process = subprocess.Popen([sys.executable, EAA_SCRIPT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=SCRIPT_DIR)
        print(f"[EAA] Started (PID: {eaa_process.pid})")
        return eaa_process.pid
    except Exception as e:
        print(f"[EAA] Error: {e}")
        return None

# ============================================
# NEW HELPER FUNCTIONS - AUDIO
# ============================================

def set_volume(level):
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
        return False, "pycaw not installed"

def get_volume():
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
    if not TTS_AVAILABLE:
        return False, "pyttsx3 not installed"
    try:
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        return True, None
    except Exception as e:
        return False, str(e)

# ============================================
# NEW HELPER FUNCTIONS - WEBCAM
# ============================================

def capture_webcam():
    if not CV2_AVAILABLE:
        return None, "opencv-python not installed"
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return None, "Cannot open webcam"
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None, "Failed to capture"
        _, buffer = cv2.imencode('.png', frame)
        return base64.b64encode(buffer).decode(), None
    except Exception as e:
        return None, str(e)

def list_webcams():
    if not CV2_AVAILABLE:
        return [], "opencv-python not installed"
    cams = []
    for i in range(3):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            cams.append({"index": i, "available": True})
            cap.release()
    return cams, None

# ============================================
# NEW HELPER FUNCTIONS - RECORDING
# ============================================

def start_recording(region=None, fps=10):
    global recording_state
    if recording_state["active"]:
        return False, "Already recording"
    recording_state = {"active": True, "frames": [], "start_time": time.time(), "region": region, "fps": fps}
    def record_loop():
        global recording_state
        while recording_state["active"]:
            try:
                if recording_state["region"]:
                    x, y, w, h = recording_state["region"]
                    img = pyautogui.screenshot(region=(x, y, w, h))
                else:
                    img = pyautogui.screenshot()
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                recording_state["frames"].append(buf.getvalue())
                time.sleep(1.0 / recording_state["fps"])
            except:
                break
    threading.Thread(target=record_loop, daemon=True).start()
    return True, None

def stop_recording(save_path=None):
    global recording_state
    if not recording_state["active"]:
        return None, "Not recording"
    recording_state["active"] = False
    frames = recording_state["frames"]
    duration = time.time() - recording_state["start_time"]
    if not frames:
        return None, "No frames recorded"
    if save_path and CV2_AVAILABLE and NUMPY_AVAILABLE:
        try:
            first_img = Image.open(io.BytesIO(frames[0]))
            width, height = first_img.size
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(save_path, fourcc, recording_state["fps"], (width, height))
            for frame_data in frames:
                img = Image.open(io.BytesIO(frame_data))
                img_array = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                out.write(img_array)
            out.release()
            return {"frames": len(frames), "duration": round(duration, 2), "saved_to": save_path}, None
        except Exception as e:
            return {"frames": len(frames), "duration": round(duration, 2)}, str(e)
    frames_b64 = [base64.b64encode(f).decode() for f in frames[:30]]
    return {"frames": len(frames), "duration": round(duration, 2), "sample_frames": frames_b64}, None

# ============================================
# NEW HELPER FUNCTIONS - OCR
# ============================================

def ocr_screenshot(region=None):
    if not PYTESSERACT_AVAILABLE:
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
    if not PYTESSERACT_AVAILABLE:
        return None, "pytesseract not installed"
    try:
        img_data = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(img_data))
        text = pytesseract.image_to_string(img)
        return text.strip(), None
    except Exception as e:
        return None, str(e)

# ============================================
# NEW HELPER FUNCTIONS - FILE SEARCH
# ============================================

def search_files(query, path=None, max_results=50):
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
                        results.append({"path": full_path, "name": name, "is_dir": os.path.isdir(full_path), "size": os.path.getsize(full_path) if os.path.isfile(full_path) else 0, "modified": datetime.fromtimestamp(os.path.getmtime(full_path)).isoformat()})
                    except:
                        pass
                    if len(results) >= max_results:
                        return results, None
        return results, None
    except Exception as e:
        return results, str(e)

def search_in_files(query, path=None, extensions=None, max_results=30):
    if path is None:
        path = ALLOWED_PATH
    if not validate_path(path):
        return [], "Access denied"
    if extensions is None:
        extensions = ['.txt', '.py', '.js', '.json', '.md', '.html', '.css', '.xml', '.log', '.csv']
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
                                    results.append({"path": full_path, "line": i, "content": line.strip()[:200]})
                                    if len(results) >= max_results:
                                        return results, None
                    except:
                        pass
        return results, None
    except Exception as e:
        return results, str(e)

# ============================================
# NEW HELPER FUNCTIONS - NETWORK
# ============================================

def download_file(url, save_path, timeout=60):
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
    try:
        result = subprocess.run(f"ping -n {count} {host}", shell=True, capture_output=True, text=True, timeout=30)
        return {"output": result.stdout, "success": result.returncode == 0}, None
    except Exception as e:
        return None, str(e)

def check_port(host, port, timeout=5):
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return {"open": result == 0, "port": port, "host": host}, None
    except Exception as e:
        return {"open": False, "port": port, "host": host, "error": str(e)}, None

def get_public_ip():
    try:
        req = urllib.request.urlopen("https://api.ipify.org?format=json", timeout=5)
        data = json.loads(req.read().decode())
        return data.get("ip"), None
    except Exception as e:
        return None, str(e)

# ============================================
# NEW HELPER FUNCTIONS - MEDIA CONTROL
# ============================================

def media_control(action):
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
# NEW HELPER FUNCTIONS - IMAGE
# ============================================

def resize_image(image_base64, width, height):
    if not PIL_AVAILABLE:
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
    if not PIL_AVAILABLE:
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
    if not PIL_AVAILABLE:
        return None, "Pillow not installed"
    try:
        img_data = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(img_data))
        return {"width": img.width, "height": img.height, "format": img.format, "mode": img.mode, "size_bytes": len(img_data)}, None
    except Exception as e:
        return None, str(e)

# ============================================
# NEW HELPER FUNCTIONS - QUICK ACTIONS
# ============================================

def quick_action(action, **kwargs):
    actions = {
        "lock_screen": lambda: os.system("rundll32.exe user32.dll,LockWorkStation"),
        "task_manager": lambda: subprocess.run("taskmgr", shell=True),
        "file_explorer": lambda: subprocess.run("explorer", shell=True),
        "settings": lambda: subprocess.run("start ms-settings:", shell=True),
        "calculator": lambda: subprocess.run("calc", shell=True),
        "notepad": lambda: subprocess.run("notepad", shell=True),
        "empty_trash": lambda: subprocess.run('powershell -command "Clear-RecycleBin -Force"', shell=True),
        "show_desktop": lambda: pyautogui.hotkey('win', 'd'),
        "open_run": lambda: pyautogui.hotkey('win', 'r'),
        "open_search": lambda: pyautogui.hotkey('win', 's'),
        "emoji_picker": lambda: pyautogui.hotkey('win', '.'),
        "clipboard_history": lambda: pyautogui.hotkey('win', 'v'),
        "screenshot_tool": lambda: pyautogui.hotkey('win', 'shift', 's'),
        "game_bar": lambda: pyautogui.hotkey('win', 'g'),
    }
    if action not in actions:
        return False, f"Unknown action: {action}"
    try:
        actions[action]()
        return True, None
    except Exception as e:
        return False, str(e)

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
        key = self.headers.get("X-Control-Key", "")
        secret = self.headers.get("X-Secret", "")
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
        
        if path == "/health":
            self.send_json({"status": "online", "version": "v6", "session_active": session_manager.session_token is not None, "remote_control": PYAUTOGUI_AVAILABLE, "screenshot": PIL_AVAILABLE, "webcam": CV2_AVAILABLE, "ocr": PYTESSERACT_AVAILABLE, "tts": TTS_AVAILABLE, "gpu": GPU_AVAILABLE, "tunnel": tunnel_url, "eaa_tunnel": eaa_tunnel_url})
            return
        
        auth_ok, auth_err = self.check_auth()
        if not auth_ok:
            self.send_json({"suc": False, "err": auth_err}, 401)
            return
        
        if path == "/screenshot":
            img, err = take_screenshot()
            if err:
                self.send_json({"suc": False, "err": err})
            else:
                self.send_json({"suc": True, "image": img})
            return
        
        if path == "/system/info":
            self.send_json({"suc": True, "system": get_system_info()})
            return
        
        if path == "/process/list":
            self.send_json({"suc": True, "processes": get_process_list()})
            return
        
        if path == "/windows/list":
            self.send_json({"suc": True, "windows": get_windows_list()})
            return
        
        if path == "/mouse/position":
            if PYAUTOGUI_AVAILABLE:
                x, y = pyautogui.position()
                self.send_json({"suc": True, "x": x, "y": y})
            else:
                self.send_json({"suc": False, "err": "pyautogui not available"})
            return
        
        if path == "/clipboard/get":
            content, err = get_clipboard()
            if err:
                self.send_json({"suc": False, "err": err})
            else:
                self.send_json({"suc": True, "content": content})
            return
        
        if path == "/clipboard/history":
            self.send_json({"suc": True, "history": clipboard_history})
            return
        
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
        
        if path == "/network/public_ip":
            ip, err = get_public_ip()
            if err:
                self.send_json({"suc": False, "err": err})
            else:
                self.send_json({"suc": True, "ip": ip})
            return
        
        if path == "/audio/volume":
            level, err = get_volume()
            if err:
                self.send_json({"suc": False, "err": err})
            else:
                self.send_json({"suc": True, "volume": level})
            return
        
        if path == "/webcam/list":
            cams, err = list_webcams()
            self.send_json({"suc": True, "webcams": cams})
            return
        
        if path == "/recording/status":
            self.send_json({"suc": True, "active": recording_state["active"], "frames": len(recording_state.get("frames", [])), "duration": time.time() - recording_state["start_time"] if recording_state["active"] else 0})
            return
        
        if path == "/eaa/status":
            self.send_json({"suc": True, "running": eaa_process is not None and eaa_process.poll() is None, "tunnel": eaa_tunnel_url})
            return
        
        if path == "/terminal/status":
            self.send_json({"suc": True, "eaa_running": eaa_process is not None and eaa_process.poll() is None, "tunnel_running": tunnel_process is not None and tunnel_process.poll() is None, "recording": recording_state["active"]})
            return
        
        self.send_json({"suc": False, "err": "Unknown endpoint"})
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if not rate_limiter.check(self.get_client_ip()):
            self.send_json({"suc": False, "err": "Rate limit"}, 429)
            return
        
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length > 0 else "{}"
        
        try:
            data = json.loads(body)
        except:
            data = {}
        
        auth_ok, auth_err = self.check_auth()
        if not auth_ok:
            self.send_json({"suc": False, "err": auth_err}, 401)
            return
        
        # ORIGINAL ENDPOINTS
        if path == "/mouse/move":
            if not PYAUTOGUI_AVAILABLE:
                self.send_json({"suc": False, "err": "pyautogui not available"})
                return
            pyautogui.moveTo(data.get("x", 0), data.get("y", 0))
            self.send_json({"suc": True})
            return
        
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
        
        if path == "/keyboard/type":
            if not PYAUTOGUI_AVAILABLE:
                self.send_json({"suc": False, "err": "pyautogui not available"})
                return
            pyautogui.typewrite(data.get("text", ""), interval=data.get("interval", 0.02))
            self.send_json({"suc": True})
            return
        
        if path == "/keyboard/press" or path == "/keyboard/key":
            if not PYAUTOGUI_AVAILABLE:
                self.send_json({"suc": False, "err": "pyautogui not available"})
                return
            pyautogui.press(data.get("key", "enter"))
            self.send_json({"suc": True})
            return
        
        if path == "/keyboard/hotkey":
            if not PYAUTOGUI_AVAILABLE:
                self.send_json({"suc": False, "err": "pyautogui not available"})
                return
            keys = data.get("keys", [])
            if keys:
                pyautogui.hotkey(*keys)
            self.send_json({"suc": True})
            return
        
        if path == "/notify":
            ok, err = send_notification(data.get("title", "EAA"), data.get("message", ""))
            if ok:
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": err})
            return
        
        if path == "/app/launch":
            app = data.get("app", "")
            path_arg = data.get("path", "")
            apps = {"chrome": "start chrome", "firefox": "start firefox", "edge": "start msedge", "vscode": "code", "notepad": "notepad", "explorer": "explorer", "spotify": "start spotify", "discord": "start discord"}
            if path_arg:
                subprocess.run(f'"{path_arg}"', shell=True)
            elif app in apps:
                subprocess.run(apps[app], shell=True)
            else:
                self.send_json({"suc": False, "err": f"Unknown app: {app}"})
                return
            self.send_json({"suc": True})
            return
        
        if path == "/browser/open":
            subprocess.run(f'start "" "{data.get("url", "https://google.com")}"', shell=True)
            self.send_json({"suc": True})
            return
        
        if path == "/browser/search":
            subprocess.run(f'start "" "https://www.google.com/search?q={data.get("query", "")}"', shell=True)
            self.send_json({"suc": True})
            return
        
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
        
        if path == "/file/list":
            dir_path = data.get("path", ALLOWED_PATH)
            if not validate_path(dir_path):
                self.send_json({"suc": False, "err": "Access denied"})
                return
            try:
                items = []
                for item in os.listdir(dir_path):
                    full = os.path.join(dir_path, item)
                    items.append({"name": item, "is_dir": os.path.isdir(full), "size": os.path.getsize(full) if os.path.isfile(full) else 0})
                self.send_json({"suc": True, "items": items})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
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
        
        if path == "/shell":
            cmd = data.get("command", "")
            timeout = data.get("timeout", 30)
            result = run_shell(cmd, timeout)
            self.send_json({"suc": True, "result": result})
            return
        
        if path == "/clipboard/set":
            ok, err = set_clipboard(data.get("content", ""))
            if ok:
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": err})
            return
        
        if path == "/window/focus":
            ok, err = focus_window(data.get("title", ""))
            if ok:
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": err})
            return
        
        if path == "/window/close":
            ok, err = close_window(data.get("title", ""))
            if ok:
                self.send_json({"suc": True})
            else:
                self.send_json({"suc": False, "err": err})
            return
        
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
        
        # NEW ENDPOINTS - AUDIO
        if path == "/audio/volume/set":
            ok, err = set_volume(data.get("level", 50))
            self.send_json({"suc": ok, "err": err} if err else {"suc": True, "volume": data.get("level", 50)})
            return
        
        if path == "/audio/mute":
            ok, err = set_mute(True)
            self.send_json({"suc": ok, "err": err} if err else {"suc": True, "muted": True})
            return
        
        if path == "/audio/unmute":
            ok, err = set_mute(False)
            self.send_json({"suc": ok, "err": err} if err else {"suc": True, "muted": False})
            return
        
        if path == "/audio/tts" or path == "/speak":
            ok, err = text_to_speech(data.get("text", ""))
            self.send_json({"suc": ok, "err": err} if err else {"suc": True})
            return
        
        # NEW ENDPOINTS - WEBCAM
        if path == "/webcam/capture":
            img, err = capture_webcam()
            self.send_json({"suc": False, "err": err} if err else {"suc": True, "image": img})
            return
        
        # NEW ENDPOINTS - RECORDING
        if path == "/recording/start":
            ok, err = start_recording(data.get("region"), data.get("fps", 10))
            self.send_json({"suc": ok, "err": err} if err else {"suc": True, "message": "Recording started"})
            return
        
        if path == "/recording/stop":
            result, err = stop_recording(data.get("path"))
            if err and not result:
                self.send_json({"suc": False, "err": err})
            else:
                self.send_json({"suc": True, "result": result, "warning": err})
            return
        
        # NEW ENDPOINTS - OCR
        if path == "/ocr/screenshot":
            text, err = ocr_screenshot(data.get("region"))
            self.send_json({"suc": False, "err": err} if err else {"suc": True, "text": text})
            return
        
        if path == "/ocr/image":
            text, err = ocr_image(data.get("image", ""))
            self.send_json({"suc": False, "err": err} if err else {"suc": True, "text": text})
            return
        
        # NEW ENDPOINTS - FILE SEARCH
        if path == "/file/search":
            results, err = search_files(data.get("query", ""), data.get("path", ALLOWED_PATH), data.get("max_results", 50))
            self.send_json({"suc": True, "results": results, "error": err})
            return
        
        if path == "/file/search_content":
            results, err = search_in_files(data.get("query", ""), data.get("path", ALLOWED_PATH), data.get("extensions"))
            self.send_json({"suc": True, "results": results, "error": err})
            return
        
        # NEW ENDPOINTS - NETWORK
        if path == "/network/download":
            url = data.get("url", "")
            save_path = data.get("path", "")
            if not url or not save_path:
                self.send_json({"suc": False, "err": "url and path required"})
                return
            ok, err = download_file(url, save_path)
            self.send_json({"suc": ok, "err": err} if err else {"suc": True, "saved_to": save_path})
            return
        
        if path == "/network/ping":
            result, err = ping_host(data.get("host", "google.com"), data.get("count", 4))
            self.send_json({"suc": False, "err": err} if err else {"suc": True, "result": result})
            return
        
        if path == "/network/check_port":
            result, _ = check_port(data.get("host", "localhost"), data.get("port", 80))
            self.send_json({"suc": True, "result": result})
            return
        
        # NEW ENDPOINTS - MEDIA
        if path == "/media/control":
            ok, err = media_control(data.get("action", "play_pause"))
            self.send_json({"suc": ok, "err": err} if err else {"suc": True, "action": data.get("action")})
            return
        
        # NEW ENDPOINTS - IMAGE
        if path == "/image/resize":
            result, err = resize_image(data.get("image", ""), data.get("width", 800), data.get("height", 600))
            self.send_json({"suc": False, "err": err} if err else {"suc": True, "image": result})
            return
        
        if path == "/image/convert":
            result, err = convert_image(data.get("image", ""), data.get("format", "JPEG"))
            self.send_json({"suc": False, "err": err} if err else {"suc": True, "image": result, "format": data.get("format", "JPEG")})
            return
        
        if path == "/image/info":
            result, err = get_image_info(data.get("image", ""))
            self.send_json({"suc": False, "err": err} if err else {"suc": True, "info": result})
            return
        
        # NEW ENDPOINTS - QUICK ACTIONS
        if path == "/quick":
            ok, err = quick_action(data.get("action", ""))
            self.send_json({"suc": ok, "err": err} if err else {"suc": True, "action": data.get("action")})
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
    if recording_state["active"]:
        recording_state["active"] = False
    print("[BYE] All stopped!")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))
    
    print("=" * 60)
    print("  EAA CONTROL SYSTEM V6 - FULL REMOTE CONTROL")
    print("  Screenshot | Click | Type | Keys | Files | Shell")
    print("  Audio | Webcam | OCR | Recording | Media | Network")
    print("=" * 60)
    
    print(f"\n[KEY] Generated API Key: {API_KEY}")
    print(f"[SECRET] Generated Secret Phrase: {SECRET_PHRASE}")
    
    print("\n" + "=" * 60)
    print("  FEATURES STATUS")
    print("=" * 60)
    print(f"  Screenshot: {'YES' if PIL_AVAILABLE else 'NO'}")
    print(f"  Mouse Control: {'YES' if PYAUTOGUI_AVAILABLE else 'NO'}")
    print(f"  Keyboard Control: {'YES' if PYAUTOGUI_AVAILABLE else 'NO'}")
    print(f"  Webcam: {'YES' if CV2_AVAILABLE else 'NO'}")
    print(f"  OCR: {'YES' if PYTESSERACT_AVAILABLE else 'NO'}")
    print(f"  TTS: {'YES' if TTS_AVAILABLE else 'NO'}")
    print(f"  GPU Monitor: {'YES' if GPU_AVAILABLE else 'NO'}")
    print("=" * 60)
    
    print("\n[START] Starting EAA AI Server...")
    start_eaa()
    
    print("\n[START] Starting Cloudflare Tunnel...")
    url = start_tunnel(PORT)
    
    if url:
        print(f"\n[TUNNEL] YES - {url}")
        print("\n[EMAIL] Sending credentials...")
        send_tunnel_notification(url, API_KEY, SECRET_PHRASE)
    else:
        print("[TUNNEL] Failed to start")
    
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
    
    run_server()