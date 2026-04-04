"""
EAA CONTROL STATION - SECURE
Requires API key for all requests.
Key is passed via --key argument (from control manager).
"""
import os,sys,json,time,hashlib,subprocess,threading,secrets,argparse,hmac
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from http.server import HTTPServer,BaseHTTPRequestHandler

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
rate_data=defaultdict(list)
banned={}
logs=[]

def check_rate(ip):
    now=time.time()
    if ip in banned and now-banned[ip]<300:
        return False
    rate_data[ip]=[t for t in rate_data[ip] if now-t<60]
    if len(rate_data[ip])>=100:
        banned[ip]=now
        return False
    rate_data[ip].append(now)
    return True

def log_req(ip,ep,ok):
    logs.append({"t":datetime.now().isoformat(),"ip":ip,"ep":ep,"ok":ok})
    if len(logs)>1000:
        logs.pop(0)

class H(BaseHTTPRequestHandler):
    def log_message(s,*a):
        pass
    
    def get_ip(s):
        f=s.headers.get("X-Forwarded-For","")
        return f.split(",")[0].strip() if f else s.client_address[0]
    
    def send_json(s,d,st=200):
        s.send_response(st)
        s.send_header("Content-Type","application/json")
        s.end_headers()
        s.wfile.write(json.dumps(d,indent=2).encode())
    
    def send_err(s,m,st=400):
        s.send_json({"suc":False,"err":m},st)
    
    def auth(s):
        ip=s.get_ip()
        if not check_rate(ip):
            log_req(ip,s.path,0)
            s.send_err("Rate limit",429)
            return False
        k=s.headers.get("X-Control-Key")
        if not k:
            log_req(ip,s.path,0)
            s.send_err("Missing API key",401)
            return False
        if not hmac.compare_digest(k,API_KEY):
            log_req(ip,s.path,0)
            s.send_err("Invalid API key",403)
            return False
        return True
    
    def read_body(s):
        try:
            l=int(s.headers.get("Content-Length",0))
            if l>1e7:
                return None
            return s.rfile.read(l).decode("utf-8","replace") if l else ""
        except:
            return None
    
    def do_GET(s):
        if not s.auth():
            return
        ip=s.get_ip()
        p=s.path.split("?")[0]
        try:
            if p=="/health":
                log_req(ip,p,1)
                s.send_json({"status":"online","port":CONTROL_PORT,"uptime":int(time.time()-start_time),"secure":True})
            elif p=="/eaa/status":
                import socket
                sock=socket.socket()
                sock.settimeout(2)
                r=sock.connect_ex(("127.0.0.1",EAA_PORT))
                sock.close()
                log_req(ip,p,1)
                s.send_json({"suc":True,"listening":r==0})
            elif p=="/terminal/status":
                if STATUS_FILE.exists():
                    log_req(ip,p,1)
                    s.send_json({"suc":True,"status":json.loads(STATUS_FILE.read_text())})
                else:
                    s.send_json({"suc":True,"status":{"status":"unknown"}})
            elif p=="/terminal/output":
                if OUTPUT_FILE.exists():
                    log_req(ip,p,1)
                    lines=OUTPUT_FILE.read_text("utf-8","replace").splitlines()[-500:]
                    s.send_json({"suc":True,"output":"\n".join(lines)})
                else:
                    s.send_json({"suc":True,"output":""})
            elif p=="/info":
                url=TUNNEL_FILE.read_text().strip() if TUNNEL_FILE.exists() else ""
                log_req(ip,p,1)
                s.send_json({"url":url,"key":API_KEY[:5]+"..."+API_KEY[-5:] if API_KEY else ""})
            else:
                log_req(ip,p,0)
                s.send_err("Not found",404)
        except:
            log_req(ip,p,0)
            s.send_err("Error",500)
    
    def do_POST(s):
        if not s.auth():
            return
        ip=s.get_ip()
        p=s.path.split("?")[0]
        b=s.read_body()
        if b is None:
            s.send_err("Too large",413)
            return
        try:
            d=json.loads(b) if b.strip() else {}
        except:
            d={}
        try:
            if p=="/shell":
                c=d.get("command","").strip()
                if not c:
                    s.send_json({"suc":False,"err":"No command"})
                    return
                try:
                    r=subprocess.run(c,shell=True,capture_output=True,text=True,timeout=60,cwd=str(EAA_DIR))
                    log_req(ip,p,1)
                    s.send_json({"suc":True,"out":r.stdout,"err":r.stderr,"ret":r.returncode})
                except subprocess.TimeoutExpired:
                    s.send_json({"suc":False,"err":"Timeout"})
            elif p=="/terminal/command":
                c=d.get("command","").strip().lower()
                if c not in["start","stop","restart","status"]:
                    s.send_json({"suc":False,"err":"Invalid command"})
                    return
                COMMAND_FILE.write_text(c)
                log_req(ip,p,1)
                s.send_json({"suc":True,"cmd":c})
            elif p=="/file/read":
                fp=d.get("path","").strip()
                if not fp:
                    s.send_json({"suc":False,"err":"No path"})
                    return
                sp=os.path.abspath(fp)
                if not (sp.startswith("C:\\Users\\offic") or sp.startswith("C:/Users/offic")):
                    s.send_json({"suc":False,"err":"Access denied"})
                    return
                try:
                    log_req(ip,p,1)
                    s.send_json({"suc":True,"content":open(sp,"r",encoding="utf-8",errors="replace").read()})
                except:
                    s.send_json({"suc":False,"err":"Read error"})
            elif p=="/file/write":
                fp=d.get("path","").strip()
                ct=d.get("content","")
                if not fp:
                    s.send_json({"suc":False,"err":"No path"})
                    return
                sp=os.path.abspath(fp)
                if not (sp.startswith("C:\\Users\\offic") or sp.startswith("C:/Users/offic")):
                    s.send_json({"suc":False,"err":"Access denied"})
                    return
                try:
                    open(sp,"w",encoding="utf-8").write(ct)
                    log_req(ip,p,1)
                    s.send_json({"suc":True})
                except:
                    s.send_json({"suc":False,"err":"Write error"})
            else:
                log_req(ip,p,0)
                s.send_err("Not found",404)
        except:
            log_req(ip,p,0)
            s.send_err("Error",500)

def main():
    global API_KEY
    ap=argparse.ArgumentParser(description="Secure Control Station")
    ap.add_argument("--key",type=str,required=True,help="API key (required)")
    args=ap.parse_args()
    
    API_KEY=args.key
    
    print(f"\n{'='*50}")
    print("  SECURE CONTROL STATION")
    print(f"{'='*50}")
    print(f"  Port: {CONTROL_PORT}")
    print(f"  Key: {API_KEY[:5]}...{API_KEY[-5:]}")
    print(f"{'='*50}\n")
    
    HTTPServer(("0.0.0.0",CONTROL_PORT),H).serve_forever()

if __name__=="__main__":
    main()
