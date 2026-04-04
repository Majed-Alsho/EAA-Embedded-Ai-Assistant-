"""
EAA CONTROL STATION V2 - SESSION TOKEN EDITION
- API Key + Session Token (double security)
- Only first connection gets session token
- Subsequent connections need BOTH keys
- Thread-safe, crash-proof
"""
import os,sys,json,time,hashlib,subprocess,threading,secrets,argparse,hmac,socket,psutil,base64
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from http.server import HTTPServer,BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

CONTROL_PORT=8001
EAA_PORT=8000
EAA_DIR=Path(r"C:\Users\offic\EAA")
KEY_FILE=EAA_DIR/".control_key"
STATUS_FILE=EAA_DIR/"terminal_status.json"
OUTPUT_FILE=EAA_DIR/"terminal_output.txt"
COMMAND_FILE=EAA_DIR/"terminal_command.txt"
TUNNEL_FILE=EAA_DIR/"control_tunnel_url.txt"

start_time=time.time()
API_KEY=None
lock=threading.Lock()

# ===== SESSION TOKEN SYSTEM =====
class SessionManager:
    """
    Two-layer security:
    1. API Key - proves you know the initial key
    2. Session Token - proves you were the FIRST to connect
    
    Only the FIRST connection with valid API key gets a session token.
    All subsequent requests need BOTH API key + Session token.
    """
    def __init__(s):
        s.lock=threading.Lock()
        s.session_token=None  # The active session token
        s.last_activity=0
        s.timeout=300  # 5 minutes
        s.request_count=0
        s.created_at=0
    
    def generate_token(s):
        """Generate a new session token (only called once)"""
        return "SESS_" + secrets.token_urlsafe(32)
    
    def get_or_create_session(s,has_token):
        """
        Returns: (success, session_token_or_error_message)
        
        Cases:
        1. No session exists, no token provided → CREATE new session, return token
        2. No session exists, token provided → CREATE new session (ignore provided token)
        3. Session exists, correct token provided → ALLOW access
        4. Session exists, wrong/no token provided → REJECT
        """
        with s.lock:
            now=time.time()
            
            # Check if session timed out
            if s.session_token and (now-s.last_activity)>s.timeout:
                s.session_token=None
                s.request_count=0
            
            # Case 1 & 2: No active session - CREATE ONE
            if s.session_token is None:
                s.session_token=s.generate_token()
                s.last_activity=now
                s.created_at=now
                s.request_count=1
                return (True, s.session_token, "new_session")
            
            # Case 3 & 4: Session exists - check token
            if has_token==s.session_token:
                s.last_activity=now
                s.request_count+=1
                return (True, s.session_token, "session_active")
            else:
                return (False, None, "session_locked")
    
    def release(s,token):
        """Release session (logout)"""
        with s.lock:
            if s.session_token and s.session_token==token:
                s.session_token=None
                s.last_activity=0
                return True
            return False
    
    def status(s):
        with s.lock:
            return {
                "active": s.session_token is not None,
                "token_preview": s.session_token[:15]+"..." if s.session_token else None,
                "last_activity": s.last_activity,
                "created_at": s.created_at,
                "requests": s.request_count,
                "timeout": s.timeout
            }

session=SessionManager()

# ===== RATE LIMITING =====
request_times=defaultdict(list)

def check_rate(ip):
    now=time.time()
    with lock:
        request_times[ip]=[t for t in request_times[ip] if now-t<60]
        if len(request_times[ip])>=150:
            return False
        request_times[ip].append(now)
        return True

# ===== HELPER FUNCTIONS =====
def safe_run(cmd,timeout=30,cwd=None):
    try:
        r=subprocess.run(cmd,shell=True,capture_output=True,text=True,timeout=timeout,cwd=cwd or str(EAA_DIR))
        return {"suc":True,"out":r.stdout,"err":r.stderr,"ret":r.returncode}
    except subprocess.TimeoutExpired:
        return {"suc":False,"err":"Timeout ("+str(timeout)+"s)"}
    except Exception as e:
        return {"suc":False,"err":str(e)[:100]}

def get_system_info():
    try:
        cpu=psutil.cpu_percent(interval=0.5)
        ram=psutil.virtual_memory()
        disk=psutil.disk_usage("C:\\")
        return {
            "cpu_percent": cpu,
            "ram_total": ram.total,
            "ram_used": ram.used,
            "ram_percent": ram.percent,
            "disk_total": disk.total,
            "disk_used": disk.used,
            "disk_percent": disk.percent,
            "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat()
        }
    except:
        return {"error": "Could not get system info"}

def get_processes():
    try:
        procs=[]
        for p in psutil.process_iter(["pid","name","cpu_percent","memory_percent","status"]):
            try:
                procs.append({
                    "pid": p.info["pid"],
                    "name": p.info["name"],
                    "cpu": round(p.info["cpu_percent"] or 0, 1),
                    "mem": round(p.info["memory_percent"] or 0, 1),
                    "status": p.info["status"]
                })
            except:
                pass
        procs.sort(key=lambda x: x["cpu"], reverse=True)
        return procs[:50]
    except:
        return []

def kill_process(pid):
    try:
        p=psutil.Process(pid)
        p.terminate()
        return {"suc": True, "name": p.name()}
    except psutil.NoSuchProcess:
        return {"suc": False, "err": "Process not found"}
    except psutil.AccessDenied:
        return {"suc": False, "err": "Access denied"}
    except Exception as e:
        return {"suc": False, "err": str(e)[:100]}

def start_program(path):
    try:
        subprocess.Popen(path,shell=True)
        return {"suc": True}
    except Exception as e:
        return {"suc": False, "err": str(e)[:100]}

def send_notification(title,message):
    try:
        ps_script='''
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
        $template = @"
        <toast>
            <visual>
                <binding template="ToastText02">
                    <text id="1">__TITLE__</text>
                    <text id="2">__MESSAGE__</text>
                </binding>
            </visual>
        </toast>
"@
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($template)
        $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Super Z").Show($toast)
        '''.replace("__TITLE__",title).replace("__MESSAGE__",message)
        subprocess.run(["powershell","-Command",ps_script],capture_output=True,timeout=5)
        return {"suc": True}
    except:
        try:
            subprocess.run(["msg","*",title+": "+message],capture_output=True,timeout=5)
            return {"suc": True}
        except:
            return {"suc": False, "err": "Could not send notification"}

def take_screenshot():
    try:
        from PIL import ImageGrab
        import io
        img=ImageGrab.grab()
        buffer=io.BytesIO()
        img.save(buffer,format="PNG")
        img_base64=base64.b64encode(buffer.getvalue()).decode()
        return {"suc": True, "image": img_base64, "width": img.width, "height": img.height}
    except ImportError:
        try:
            tmp=os.path.join(os.environ["TEMP"],"screenshot_super_z.png")
            ps_script='''
            Add-Type -AssemblyName System.Windows.Forms
            $bitmap = New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width,[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height)
            $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
            $graphics.CopyFromScreen([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Location,[System.Drawing.Point]::Empty,[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Size)
            $bitmap.Save("__TMP__")
            '''.replace("__TMP__",tmp)
            subprocess.run(["powershell","-Command",ps_script],capture_output=True,timeout=10)
            if os.path.exists(tmp):
                with open(tmp,"rb") as f:
                    img_base64=base64.b64encode(f.read()).decode()
                os.remove(tmp)
                return {"suc": True, "image": img_base64}
            return {"suc": False, "err": "Screenshot failed"}
        except Exception as e:
            return {"suc": False, "err": str(e)[:100]}
    except Exception as e:
        return {"suc": False, "err": str(e)[:100]}

def get_windows():
    try:
        import pygetwindow as gw
        windows=[]
        for w in gw.getAllWindows():
            if w.title:
                windows.append({
                    "title": w.title,
                    "active": w.isActive,
                    "visible": w.visible,
                    "left": w.left,
                    "top": w.top,
                    "width": w.width,
                    "height": w.height
                })
        return {"suc": True, "windows": windows}
    except ImportError:
        try:
            ps_script='''
            Add-Type @"
            using System;
            using System.Runtime.InteropServices;
            using System.Text;
            public class Win32 {
                [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
                [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
                [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc enumProc, IntPtr lParam);
                [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
                public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
            }
"@
            $windows = @()
            [Win32]::EnumWindows({
                param($hwnd, $lParam)
                if ([Win32]::IsWindowVisible($hwnd)) {
                    $title = New-Object System.Text.StringBuilder 256
                    [Win32]::GetWindowText($hwnd, $title, 256) | Out-Null
                    if ($title.ToString()) {
                        $windows += $title.ToString()
                    }
                }
                return $true
            }, [IntPtr]::Zero) | Out-Null
            $windows | ConvertTo-Json
            '''
            r=subprocess.run(["powershell","-Command",ps_script],capture_output=True,text=True,timeout=10)
            return {"suc": True, "windows": r.stdout.strip().split("\n") if r.stdout.strip() else []}
        except Exception as e:
            return {"suc": False, "err": str(e)[:100]}
    except Exception as e:
        return {"suc": False, "err": str(e)[:100]}

def get_clipboard():
    try:
        r=subprocess.run(["powershell","-Command","Get-Clipboard"],capture_output=True,text=True,timeout=5)
        return {"suc": True, "content": r.stdout}
    except Exception as e:
        return {"suc": False, "err": str(e)[:100]}

def set_clipboard(content):
    try:
        escaped=content.replace('"','""')
        ps_script='Set-Clipboard -Value "'+escaped+'"'
        subprocess.run(["powershell","-Command",ps_script],capture_output=True,timeout=5)
        return {"suc": True}
    except Exception as e:
        return {"suc": False, "err": str(e)[:100]}

def focus_window(title):
    try:
        import pygetwindow as gw
        w=gw.getWindowsWithTitle(title)
        if w:
            w[0].activate()
            return {"suc": True}
        return {"suc": False, "err": "Window not found"}
    except:
        try:
            ps_script='''
            Add-Type @"
            using System;
            using System.Runtime.InteropServices;
            public class Win32 {
                [DllImport("user32.dll")] public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
                [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
            }
"@
            $hwnd = [Win32]::FindWindow($null, "__TITLE__")
            if ($hwnd) { [Win32]::SetForegroundWindow($hwnd) }
            '''.replace("__TITLE__",title)
            subprocess.run(["powershell","-Command",ps_script],capture_output=True,timeout=5)
            return {"suc": True}
        except Exception as e:
            return {"suc": False, "err": str(e)[:100]}

# ===== HTTP HANDLER =====
class H(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    
    def log_message(s,*a):
        pass
    
    def get_ip(s):
        headers=["X-Forwarded-For","X-Real-IP","CF-Connecting-IP"]
        for h in headers:
            v=s.headers.get(h,"")
            if v:
                return v.split(",")[0].strip()
        return s.client_address[0] if s.client_address else "unknown"
    
    def send_json(s,d,st=200):
        try:
            body=json.dumps(d,indent=2).encode("utf-8")
            s.send_response(st)
            s.send_header("Content-Type","application/json")
            s.send_header("Content-Length",len(body))
            s.send_header("Connection","close")
            s.end_headers()
            s.wfile.write(body)
        except:
            pass
    
    def send_err(s,m,st=400):
        s.send_json({"suc":False,"err":m},st)
    
    def auth(s,require_session=True):
        """
        Two-step auth:
        1. Check API key
        2. Check/Create session token
        
        Returns: (success, session_token or None)
        """
        # Step 1: API Key
        api_key=s.headers.get("X-Control-Key")
        if not api_key:
            s.send_err("Missing API key",401)
            return (False, None)
        if not hmac.compare_digest(api_key,API_KEY):
            s.send_err("Invalid API key",403)
            return (False, None)
        
        # Step 2: Session Token
        session_token=s.headers.get("X-Session-Token")
        
        # Get or create session
        success, token, status = session.get_or_create_session(session_token)
        
        if not success:
            s.send_json({
                "suc": False, 
                "err": "Session locked by another user. Your session token is required.",
                "hint": "First connection gets the session token. Use X-Session-Token header."
            }, 423)
            return (False, None)
        
        # Rate limiting
        ip=s.get_ip()
        if not check_rate(ip):
            s.send_err("Rate limit exceeded",429)
            return (False, None)
        
        # Return session token (important for first connection!)
        return (True, token)
    
    def read_body(s):
        try:
            l=int(s.headers.get("Content-Length",0))
            if l>1e7:
                return None
            return s.rfile.read(l).decode("utf-8","replace") if l else ""
        except:
            return None
    
    def do_GET(s):
        try:
            p=s.path.split("?")[0]
            
            # Public endpoint
            if p=="/health":
                s.send_json({"status":"online","port":CONTROL_PORT,"uptime":int(time.time()-start_time),"secure":True})
                return
            
            # Auth required for everything else
            success, sess_token = s.auth()
            if not success:
                return
            
            # Include session token in response (crucial for first connection!)
            def response(data):
                data["session_token"]=sess_token
                return s.send_json(data)
            
            if p=="/session/status":
                response({"suc":True,"session":session.status()})
            
            elif p=="/session/release":
                session.release(sess_token)
                response({"suc":True,"msg":"Session released"})
            
            elif p=="/eaa/status":
                try:
                    sock=socket.socket()
                    sock.settimeout(2)
                    r=sock.connect_ex(("127.0.0.1",EAA_PORT))
                    sock.close()
                    response({"suc":True,"listening":r==0})
                except:
                    response({"suc":True,"listening":False})
            
            elif p=="/terminal/status":
                if STATUS_FILE.exists():
                    try:
                        response({"suc":True,"status":json.loads(STATUS_FILE.read_text())})
                    except:
                        response({"suc":True,"status":{"status":"unknown"}})
                else:
                    response({"suc":True,"status":{"status":"unknown"}})
            
            elif p=="/terminal/output":
                if OUTPUT_FILE.exists():
                    try:
                        lines=OUTPUT_FILE.read_text("utf-8","replace").splitlines()[-500:]
                        response({"suc":True,"output":"\n".join(lines)})
                    except:
                        response({"suc":True,"output":""})
                else:
                    response({"suc":True,"output":""})
            
            elif p=="/system/info":
                response({"suc":True,"system":get_system_info()})
            
            elif p=="/process/list":
                response({"suc":True,"processes":get_processes()})
            
            elif p=="/screenshot":
                response(take_screenshot())
            
            elif p=="/clipboard/get":
                response(get_clipboard())
            
            elif p=="/windows/list":
                response(get_windows())
            
            elif p=="/network/info":
                try:
                    addrs=[]
                    for name,addrs_list in psutil.net_if_addrs().items():
                        for addr in addrs_list:
                            if addr.family==2:
                                addrs.append({"interface":name,"ip":addr.address})
                    response({"suc":True,"interfaces":addrs})
                except Exception as e:
                    response({"suc":False,"err":str(e)[:100]})
            
            else:
                s.send_err("Not found",404)
        except Exception as e:
            try:
                s.send_err("Error",500)
            except:
                pass
    
    def do_POST(s):
        try:
            success, sess_token = s.auth()
            if not success:
                return
            
            def response(data):
                data["session_token"]=sess_token
                return s.send_json(data)
            
            p=s.path.split("?")[0]
            b=s.read_body()
            if b is None:
                s.send_err("Request too large",413)
                return
            try:
                d=json.loads(b) if b.strip() else {}
            except:
                d={}
            
            if p=="/shell":
                c=d.get("command","").strip()
                if not c:
                    response({"suc":False,"err":"No command"})
                    return
                response(safe_run(c,timeout=60))
            
            elif p=="/terminal/command":
                c=d.get("command","").strip().lower()
                if c not in["start","stop","restart","status"]:
                    response({"suc":False,"err":"Invalid. Use: start, stop, restart, status"})
                    return
                try:
                    COMMAND_FILE.write_text(c)
                    response({"suc":True,"cmd":c})
                except:
                    response({"suc":False,"err":"Could not send command"})
            
            elif p=="/file/read":
                fp=d.get("path","").strip()
                if not fp:
                    response({"suc":False,"err":"No path"})
                    return
                sp=os.path.abspath(fp)
                if not (sp.startswith("C:\\Users\\offic") or sp.startswith("C:/Users/offic")):
                    response({"suc":False,"err":"Access denied"})
                    return
                try:
                    response({"suc":True,"content":open(sp,"r",encoding="utf-8",errors="replace").read()})
                except FileNotFoundError:
                    response({"suc":False,"err":"File not found"})
                except:
                    response({"suc":False,"err":"Could not read file"})
            
            elif p=="/file/write":
                fp=d.get("path","").strip()
                ct=d.get("content","")
                if not fp:
                    response({"suc":False,"err":"No path"})
                    return
                sp=os.path.abspath(fp)
                if not (sp.startswith("C:\\Users\\offic") or sp.startswith("C:/Users/offic")):
                    response({"suc":False,"err":"Access denied"})
                    return
                try:
                    open(sp,"w",encoding="utf-8").write(ct)
                    response({"suc":True})
                except:
                    response({"suc":False,"err":"Could not write file"})
            
            elif p=="/file/list":
                fp=d.get("path",str(EAA_DIR)).strip()
                sp=os.path.abspath(fp)
                if not (sp.startswith("C:\\Users\\offic") or sp.startswith("C:/Users/offic")):
                    response({"suc":False,"err":"Access denied"})
                    return
                try:
                    items=[]
                    for item in os.listdir(sp):
                        full=os.path.join(sp,item)
                        items.append({"name":item,"dir":os.path.isdir(full),"size":os.path.getsize(full) if os.path.isfile(full) else 0})
                    response({"suc":True,"path":sp,"items":items})
                except:
                    response({"suc":False,"err":"Could not list directory"})
            
            elif p=="/file/delete":
                fp=d.get("path","").strip()
                if not fp:
                    response({"suc":False,"err":"No path"})
                    return
                sp=os.path.abspath(fp)
                if not (sp.startswith("C:\\Users\\offic") or sp.startswith("C:/Users/offic")):
                    response({"suc":False,"err":"Access denied"})
                    return
                try:
                    if os.path.isfile(sp):
                        os.remove(sp)
                    elif os.path.isdir(sp):
                        import shutil
                        shutil.rmtree(sp)
                    response({"suc":True})
                except:
                    response({"suc":False,"err":"Could not delete"})
            
            elif p=="/file/move":
                src=d.get("src","").strip()
                dst=d.get("dst","").strip()
                if not src or not dst:
                    response({"suc":False,"err":"Need src and dst"})
                    return
                ssp=os.path.abspath(src)
                dsp=os.path.abspath(dst)
                if not (ssp.startswith("C:\\Users\\offic") or ssp.startswith("C:/Users/offic")):
                    response({"suc":False,"err":"Access denied"})
                    return
                if not (dsp.startswith("C:\\Users\\offic") or dsp.startswith("C:/Users/offic")):
                    response({"suc":False,"err":"Access denied"})
                    return
                try:
                    import shutil
                    shutil.move(ssp,dsp)
                    response({"suc":True})
                except:
                    response({"suc":False,"err":"Could not move"})
            
            elif p=="/file/copy":
                src=d.get("src","").strip()
                dst=d.get("dst","").strip()
                if not src or not dst:
                    response({"suc":False,"err":"Need src and dst"})
                    return
                ssp=os.path.abspath(src)
                dsp=os.path.abspath(dst)
                if not (ssp.startswith("C:\\Users\\offic") or ssp.startswith("C:/Users/offic")):
                    response({"suc":False,"err":"Access denied"})
                    return
                if not (dsp.startswith("C:\\Users\\offic") or dsp.startswith("C:/Users/offic")):
                    response({"suc":False,"err":"Access denied"})
                    return
                try:
                    import shutil
                    if os.path.isfile(ssp):
                        shutil.copy2(ssp,dsp)
                    else:
                        shutil.copytree(ssp,dsp)
                    response({"suc":True})
                except:
                    response({"suc":False,"err":"Could not copy"})
            
            elif p=="/process/kill":
                pid=d.get("pid")
                if not pid:
                    response({"suc":False,"err":"No PID"})
                    return
                response(kill_process(int(pid)))
            
            elif p=="/process/start":
                path=d.get("path","").strip()
                if not path:
                    response({"suc":False,"err":"No path"})
                    return
                response(start_program(path))
            
            elif p=="/notify":
                title=d.get("title","Super Z")
                msg=d.get("message","")
                if not msg:
                    response({"suc":False,"err":"No message"})
                    return
                response(send_notification(title,msg))
            
            elif p=="/app/launch":
                app=d.get("app","").lower()
                apps={
                    "vscode": "code",
                    "chrome": "start chrome",
                    "firefox": "start firefox",
                    "notepad": "notepad",
                    "explorer": "explorer",
                    "cmd": "cmd",
                    "powershell": "powershell",
                    "taskmgr": "taskmgr",
                    "calculator": "calc",
                    "paint": "mspaint",
                    "word": "winword",
                    "excel": "excel",
                    "spotify": "start spotify",
                    "discord": "start discord",
                    "steam": "start steam",
                }
                if app in apps:
                    response(safe_run(apps[app]))
                elif d.get("path"):
                    response(start_program(d.get("path")))
                else:
                    response({"suc":False,"err":"Unknown app. Use path parameter or one of: "+", ".join(apps.keys())})
            
            elif p=="/window/focus":
                title=d.get("title","").strip()
                if not title:
                    response({"suc":False,"err":"No title"})
                    return
                response(focus_window(title))
            
            elif p=="/window/close":
                title=d.get("title","").strip()
                if not title:
                    response({"suc":False,"err":"No title"})
                    return
                response(safe_run('taskkill /FI "WINDOWTITLE eq '+title+'*" /F'))
            
            elif p=="/clipboard/set":
                content=d.get("content","")
                response(set_clipboard(content))
            
            elif p=="/schedule/add":
                task_name=d.get("name","task_"+str(int(time.time())))
                task_time=d.get("time")
                task_cmd=d.get("command")
                if not task_time or not task_cmd:
                    response({"suc":False,"err":"Need time and command"})
                    return
                try:
                    tasks_file=EAA_DIR/"scheduled_tasks.json"
                    tasks=json.loads(tasks_file.read_text()) if tasks_file.exists() else []
                    tasks.append({"name":task_name,"time":task_time,"command":task_cmd,"done":False})
                    tasks_file.write_text(json.dumps(tasks,indent=2))
                    response({"suc":True,"task":task_name})
                except Exception as e:
                    response({"suc":False,"err":str(e)[:100]})
            
            elif p=="/schedule/list":
                try:
                    tasks_file=EAA_DIR/"scheduled_tasks.json"
                    tasks=json.loads(tasks_file.read_text()) if tasks_file.exists() else []
                    response({"suc":True,"tasks":tasks})
                except:
                    response({"suc":True,"tasks":[]})
            
            elif p=="/schedule/remove":
                task_name=d.get("name")
                if not task_name:
                    response({"suc":False,"err":"No task name"})
                    return
                try:
                    tasks_file=EAA_DIR/"scheduled_tasks.json"
                    tasks=json.loads(tasks_file.read_text()) if tasks_file.exists() else []
                    tasks=[t for t in tasks if t.get("name")!=task_name]
                    tasks_file.write_text(json.dumps(tasks,indent=2))
                    response({"suc":True})
                except:
                    response({"suc":False,"err":"Could not remove task"})
            
            elif p=="/power/sleep":
                response(safe_run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0"))
            
            elif p=="/power/restart":
                response(safe_run("shutdown /r /t 10"))
            
            elif p=="/power/shutdown":
                response(safe_run("shutdown /s /t 10"))
            
            elif p=="/power/cancel":
                response(safe_run("shutdown /a"))
            
            elif p=="/mouse/position":
                try:
                    import pyautogui
                    x,y=pyautogui.position()
                    response({"suc":True,"x":x,"y":y})
                except ImportError:
                    response({"suc":False,"err":"pyautogui not installed"})
                except Exception as e:
                    response({"suc":False,"err":str(e)[:100]})
            
            elif p=="/mouse/move":
                try:
                    import pyautogui
                    x=d.get("x")
                    y=d.get("y")
                    if x is None or y is None:
                        response({"suc":False,"err":"Need x and y"})
                        return
                    pyautogui.moveTo(int(x),int(y))
                    response({"suc":True})
                except ImportError:
                    response({"suc":False,"err":"pyautogui not installed"})
                except Exception as e:
                    response({"suc":False,"err":str(e)[:100]})
            
            elif p=="/mouse/click":
                try:
                    import pyautogui
                    button=d.get("button","left")
                    clicks=d.get("clicks",1)
                    pyautogui.click(button=button,clicks=int(clicks))
                    response({"suc":True})
                except ImportError:
                    response({"suc":False,"err":"pyautogui not installed"})
                except Exception as e:
                    response({"suc":False,"err":str(e)[:100]})
            
            elif p=="/keyboard/type":
                try:
                    import pyautogui
                    text=d.get("text","")
                    pyautogui.write(text)
                    response({"suc":True})
                except ImportError:
                    response({"suc":False,"err":"pyautogui not installed"})
                except Exception as e:
                    response({"suc":False,"err":str(e)[:100]})
            
            elif p=="/keyboard/hotkey":
                try:
                    import pyautogui
                    keys=d.get("keys",[])
                    if not keys:
                        response({"suc":False,"err":"Need keys array"})
                        return
                    pyautogui.hotkey(*keys)
                    response({"suc":True})
                except ImportError:
                    response({"suc":False,"err":"pyautogui not installed"})
                except Exception as e:
                    response({"suc":False,"err":str(e)[:100]})
            
            elif p=="/browser/open":
                url=d.get("url","")
                if not url:
                    response({"suc":False,"err":"No URL"})
                    return
                response(safe_run('start "" "'+url+'"'))
            
            elif p=="/browser/search":
                query=d.get("query","")
                if not query:
                    response({"suc":False,"err":"No query"})
                    return
                url="https://www.google.com/search?q="+query.replace(" ","+")
                response(safe_run('start "" "'+url+'"'))
            
            else:
                s.send_err("Not found",404)
        except Exception as e:
            try:
                s.send_err("Error",500)
            except:
                pass

class ThreadedHTTPServer(ThreadingMixIn,HTTPServer):
    daemon_threads=True
    allow_reuse_address=True

def main():
    global API_KEY
    ap=argparse.ArgumentParser(description="EAA Control Station V2 - Session Token Edition")
    ap.add_argument("--key",type=str,required=True)
    args=ap.parse_args()
    API_KEY=args.key
    
    print("\n"+"="*60)
    print("  EAA CONTROL STATION V2")
    print("  SESSION TOKEN EDITION")
    print("="*60)
    print("  Port:",CONTROL_PORT)
    print("  API Key:",API_KEY[:5]+"..."+API_KEY[-5:])
    print("="*60)
    print("  SECURITY:")
    print("  1. First connection gets SESSION TOKEN")
    print("  2. All future requests need SESSION TOKEN")
    print("  3. Other users are REJECTED (even with API key)")
    print("="*60+"\n")
    
    server=ThreadedHTTPServer(("0.0.0.0",CONTROL_PORT),H)
    server.serve_forever()

if __name__=="__main__":
    main()
