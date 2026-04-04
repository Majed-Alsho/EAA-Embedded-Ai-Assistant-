"""
EAA CONTROL MANAGER V2
One command to start everything!
Generates NEW API key on every start.
Single-Session Lock - only 1 user per key.
"""
import os,sys,json,time,secrets,subprocess,threading,re
from pathlib import Path
from datetime import datetime

EAA_DIR=Path(r"C:\Users\offic\EAA")
PYTHON_EXE=EAA_DIR/".venv-hf"/"Scripts"/"python.exe"
CLOUDFLARED=EAA_DIR/"tools"/"cloudflared.exe"
KEY_FILE=EAA_DIR/".control_key"
TUNNEL_FILE=EAA_DIR/"control_tunnel_url.txt"

procs=[]

def log(tag,msg):
    ts=datetime.now().strftime("[%H:%M:%S]")
    print(ts+" ["+tag+"] "+msg)

def gen_key():
    return secrets.token_urlsafe(32)

def start_control_station(key):
    log("START","Starting Control Station V2...")
    cmd=[str(PYTHON_EXE),str(EAA_DIR/"eaa_control_station_v2.py"),"--key",key]
    p=subprocess.Popen(cmd,cwd=str(EAA_DIR))
    procs.append(p)
    time.sleep(2)
    return p

def start_terminal_controller():
    log("START","Starting Terminal Controller...")
    cmd=[str(PYTHON_EXE),str(EAA_DIR/"eaa_terminal_controller.py")]
    p=subprocess.Popen(cmd,cwd=str(EAA_DIR))
    procs.append(p)
    time.sleep(2)
    return p

def start_tunnel():
    log("START","Starting Cloudflare Tunnel...")
    cmd=[str(CLOUDFLARED),"tunnel","--url","http://127.0.0.1:8001"]
    p=subprocess.Popen(cmd,cwd=str(EAA_DIR),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    procs.append(p)
    return p

def get_tunnel_url(p,timeout=30):
    log("WAIT","Waiting for tunnel URL...")
    start=time.time()
    while time.time()-start<timeout:
        try:
            line=p.stdout.readline()
        except:
            time.sleep(0.5)
            continue
        
        if not line:
            time.sleep(0.5)
            continue
        
        line=line.strip()
        if line:
            print("[TUNNEL] "+line)
        
        m=re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com",line)
        if m:
            url=m.group(0)
            TUNNEL_FILE.write_text(url)
            return url
    return None

def cleanup():
    log("STOP","Stopping all processes...")
    for p in procs:
        try:
            p.terminate()
        except:
            pass

def main():
    print("\n"+"="*60)
    print("  EAA CONTROL SYSTEM V2 - SECURE")
    print("="*60+"\n")
    
    key=gen_key()
    KEY_FILE.write_text(key)
    log("KEY","Generated NEW key: "+key)
    print("\n  API Key: "+key+"\n")
    print("="*60+"\n")
    
    start_control_station(key)
    start_terminal_controller()
    tunnel_proc=start_tunnel()
    
    url=get_tunnel_url(tunnel_proc)
    
    if url:
        print("\n"+"="*60)
        print("  ALL SYSTEMS ONLINE!")
        print("="*60)
        print("\n  Control URL: "+url)
        print("  API Key: "+key)
        print("\n  >>> TELL SUPER Z <<<")
        print("    URL: "+url)
        print("    Key: "+key)
        print("="*60+"\n")
    else:
        print("\n[ERROR] Could not get tunnel URL\n")
    
    log("READY","Press Ctrl+C to stop")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()
        print("\n[BYE] All stopped!\n")

if __name__=="__main__":
    main()
