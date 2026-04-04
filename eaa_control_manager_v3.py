"""
EAA CONTROL MANAGER V3 - SECRET PASSPHRASE EDITION
====================================================
- Generates API key AND secret passphrase
- Shows both to user
- User tells Super Z the secret
- Only Super Z can claim the session
"""

import subprocess
import sys
import time
import secrets
import os
import threading

# ============================
# CONFIG
# ============================
CONTROL_PORT = 8001
TUNNEL_PORT = 8001

# ============================
# IMPORTS
# ============================
try:
    from eaa_control_station_v3 import run_server as run_control_station
except ImportError:
    print("[ERROR] Could not import eaa_control_station_v3.py")
    print("[ERROR] Make sure it's in the same directory")
    sys.exit(1)

try:
    from eaa_terminal_controller import TerminalController
except ImportError:
    print("[ERROR] Could not import eaa_terminal_controller.py")
    print("[ERROR] Make sure it's in the same directory")
    sys.exit(1)

# ============================
# TUNNEL MANAGER
# ============================
class TunnelManager:
    def __init__(self):
        self.process = None
        self.url = None
        
    def start(self, port):
        tools_dir = os.path.join(os.getcwd(), "tools")
        cloudflared_path = os.path.join(tools_dir, "cloudflared.exe")
        
        if not os.path.exists(cloudflared_path):
            print(f"[ERROR] cloudflared.exe not found at {cloudflared_path}")
            return None
        
        print(f"[START] Starting Cloudflare Tunnel...")
        print(f"[WAIT] Waiting for tunnel URL...")
        
        cmd = [cloudflared_path, "tunnel", "--url", f"http://localhost:{port}"]
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            startupinfo=startupinfo,
            encoding='utf-8'
        )
        
        # Read output to find URL
        import re
        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        
        start_time = time.time()
        while time.time() - start_time < 20:
            line = self.process.stdout.readline()
            if line:
                print(f"[TUNNEL] {line.strip()}")
                match = url_pattern.search(line)
                if match:
                    self.url = match.group(0)
                    return self.url
        
        return None
    
    def stop(self):
        if self.process:
            try:
                self.process.terminate()
            except:
                pass

# ============================
# MAIN
# ============================
def main():
    print("\n" + "=" * 60)
    print("  EAA CONTROL SYSTEM V3 - SECRET PASSPHRASE")
    print("=" * 60)
    
    # Generate API key (43 chars)
    api_key = secrets.token_urlsafe(32)
    print(f"\n[KEY] Generated API Key: {api_key}")
    
    # Generate secret passphrase (human-readable)
    # Using word combinations for easier communication
    words = [
        "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", 
        "golf", "hotel", "india", "juliet", "kilo", "lima",
        "mike", "november", "oscar", "papa", "quebec", "romeo",
        "sierra", "tango", "uniform", "victor", "whiskey", "xray",
        "yankee", "zulu", "ace", "bolt", "cloud", "dawn",
        "ember", "frost", "glow", "haze", "iron", "jade",
        "king", "lunar", "mist", "nova", "ocean", "pulse",
        "quartz", "river", "storm", "thunder", "ultra", "vivid",
        "wolf", "zenith"
    ]
    secret = f"{secrets.choice(words)}-{secrets.choice(words)}-{secrets.choice(words)}"
    print(f"[SECRET] Generated Secret Phrase: {secret}")
    
    print("\n" + "=" * 60)
    
    # Start control station in thread
    print(f"[START] Starting Control Station V3...")
    
    terminal_controller = TerminalController()
    
    control_thread = threading.Thread(
        target=run_control_station,
        args=(api_key, secret, terminal_controller),
        daemon=True
    )
    control_thread.start()
    
    time.sleep(2)
    
    # Start terminal controller (EAA)
    print("[START] Starting Terminal Controller...")
    terminal_controller.start()
    
    # Start tunnel
    tunnel = TunnelManager()
    tunnel_url = tunnel.start(TUNNEL_PORT)
    
    if tunnel_url:
        print("\n" + "=" * 60)
        print("  ALL SYSTEMS ONLINE!")
        print("=" * 60)
        print(f"\n  Control URL: {tunnel_url}")
        print(f"  API Key: {api_key}")
        print(f"  Secret: {secret}")
        print("\n  >>> TELL SUPER Z <<<")
        print(f"    URL: {tunnel_url}")
        print(f"    Key: {api_key}")
        print(f"    Secret: {secret}")
        print("=" * 60)
    else:
        print("\n[ERROR] Failed to start tunnel")
        print("[INFO] Control system running locally only")
    
    print("\n[READY] Press Ctrl+C to stop")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[STOP] Stopping all processes...")
        terminal_controller.stop()
        tunnel.stop()
        print("\n[BYE] All stopped!")

if __name__ == "__main__":
    main()
