"""
EAA CONTROL MANAGER
One command to start everything!
Generates NEW API key on every start.
"""
import os,sys,json,time,secrets,subprocess,threading,signal,re
from pathlib import Path
from datetime import datetime

EAA_DIR=Path(r"C:\Users\offic\EAA")
PYTHON_EXE=EAA_DIR/".venv-hf"/"Scripts"/"python.exe"
CLOUDFLARED=EAA_DIR/"tools"/"cloudflared.exe"
KEY_FILE=EAA_DIR/".control_key"
TUNNEL_URL_FILE=EAA_DIR/"control_tunnel_url.txt"

CONTROL_PORT=8001

class ProcessManager:
    def __init__(s):
        s.processes=[]
        s.running=True
        s.api_key=None
        s.tunnel_url=None
    
    def log(s,cat,msg):
        t=datetime.now().strftime("%H:%M:%S")
        print(f"[{t}] [{cat}] {msg}")
    
    def gen_key(s):
        # Generate NEW key every time - never reuse
        s.api_key=secrets.token_urlsafe(32)
        KEY_FILE.write_text(s.api_key)
        s.log("KEY",f"Generated NEW key: {s.api_key}")
        return s.api_key
    
    def start_proc(s,name,cmd,capture_tunnel=False):
        def run():
            try:
                proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,cwd=EAA_DIR)
                s.processes.append((name,proc))
                for line in iter(proc.stdout.readline,""):
                    if not s.running:
                        break
                    line=line.rstrip()
                    if line:
                        if capture_tunnel and "trycloudflare.com" in line:
                            m=re.search(r"https://[a-z0-9-]+\.trycloudflare\.com",line)
                            if m:
                                s.tunnel_url=m.group(0)
                                TUNNEL_URL_FILE.write_text(s.tunnel_url)
                                s.log("TUNNEL",f"URL: {s.tunnel_url}")
                        if "ICMP proxy" not in line and "Starting metrics" not in line:
                            print(f"[{name}] {line}")
                proc.wait()
            except Exception as e:
                if s.running:
                    s.log(name,f"Error: {e}")
        threading.Thread(target=run,daemon=True).start()
    
    def start_all(s):
        print("\n"+"="*60)
        print("  EAA CONTROL SYSTEM - SECURE")
        print("="*60+"\n")
        
        # Generate NEW key every startup
        s.gen_key()
        
        print(f"\n  API Key: {s.api_key}")
        print("\n"+"="*60+"\n")
        
        s.log("START","Starting Control Station...")
        s.start_proc("CONTROL",[str(PYTHON_EXE),"eaa_control_station_secure.py","--key",s.api_key])
        time.sleep(2)
        
        s.log("START","Starting Terminal Controller...")
        s.start_proc("TERMINAL",[str(PYTHON_EXE),"eaa_terminal_controller.py"])
        time.sleep(3)
        
        s.log("START","Starting Cloudflare Tunnel...")
        s.start_proc("TUNNEL",[str(CLOUDFLARED),"tunnel","--url",f"http://127.0.0.1:{CONTROL_PORT}"],capture_tunnel=True)
        
        s.log("WAIT","Waiting for tunnel URL...")
        for _ in range(30):
            if s.tunnel_url:
                break
            time.sleep(1)
        
        if s.tunnel_url:
            print("\n"+"="*60)
            print("  ALL SYSTEMS ONLINE!")
            print("="*60)
            print(f"\n  Control URL: {s.tunnel_url}")
            print(f"  API Key: {s.api_key}")
            print("\n  >>> TELL SUPER Z <<<")
            print(f"    URL: {s.tunnel_url}")
            print(f"    Key: {s.api_key}")
            print("="*60+"\n")
        else:
            s.log("WARN","Tunnel URL not captured yet, check output above")
        
        s.log("READY","Press Ctrl+C to stop\n")
    
    def stop_all(s):
        s.running=False
        print("\n"+"="*60)
        print("  STOPPING ALL SYSTEMS")
        print("="*60+"\n")
        for name,proc in s.processes:
            try:
                proc.terminate()
                proc.wait(timeout=3)
                s.log("STOP",f"{name} stopped")
            except:
                try:
                    proc.kill()
                    s.log("KILL",f"{name} killed")
                except:
                    pass
        try:
            subprocess.run(["taskkill","/F","/IM","cloudflared.exe"],capture_output=True)
        except:
            pass
        print("\n"+"="*60)
        print("  ALL SYSTEMS STOPPED")
        print("="*60+"\n")

def main():
    mgr=ProcessManager()
    def h(sig,frame):
        mgr.stop_all()
        sys.exit(0)
    signal.signal(signal.SIGINT,h)
    signal.signal(signal.SIGTERM,h)
    mgr.start_all()
    try:
        while mgr.running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        mgr.stop_all()

if __name__=="__main__":
    main()
