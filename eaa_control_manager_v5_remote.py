"""
EAA CONTROL MANAGER V5 - FULL REMOTE CONTROL
Orchestrates Control Station V5, EAA, and Tunnel
Includes screenshot + mouse + keyboard control!
"""

import subprocess
import threading
import time
import secrets
import sys
import os
import re

# Configuration
EAA_PATH = r"C:\Users\offic\EAA"
EAA_ENTRY = r"run_eaa_agent.py"
CONTROL_PORT = 8001
EAA_PORT = 8000

# Global processes
processes = {
    "control": None,
    "eaa": None,
    "tunnel": None
}

def generate_api_key() -> str:
    """Generate secure API key"""
    return secrets.token_urlsafe(32)

def generate_secret_phrase() -> str:
    """Generate memorable secret phrase"""
    words = [
        "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
        "india", "juliet", "kilo", "lima", "mike", "november", "oscar", "papa",
        "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey", 
        "xray", "yankee", "zulu",
        "ace", "king", "queen", "jack", "joker", "wild", "fast", "slow", "high",
        "low", "deep", "dark", "light", "fire", "ice", "storm", "calm", "rock",
        "paper", "steel", "gold", "silver", "bronze", "iron", "copper", "crystal",
        "shadow", "ghost", "phantom", "ninja", "warrior", "sage", "wizard", "knight"
    ]
    import random
    return f"{random.choice(words)}-{random.choice(words)}-{random.choice(words)}"

def print_banner():
    """Print startup banner"""
    print("\n" + "=" * 60)
    print("  EAA CONTROL SYSTEM V5 - FULL REMOTE CONTROL")
    print("  📸 Screenshot | 🖱️ Click | ⌨️ Type | 🔑 Keys")
    print("=" * 60)

def check_dependencies():
    """Check and offer to install dependencies"""
    try:
        import pyautogui
        from PIL import Image
        print("[CHECK] ✅ pyautogui and Pillow installed")
        return True
    except ImportError as e:
        print(f"[CHECK] ⚠️ Missing dependency: {e}")
        print("[CHECK] Installing pyautogui and Pillow...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pyautogui", "Pillow"], 
                         check=True, capture_output=True)
            print("[CHECK] ✅ Dependencies installed!")
            return True
        except:
            print("[CHECK] ❌ Failed to auto-install. Run manually:")
            print("        pip install pyautogui Pillow")
            return False

def start_control_station(api_key: str, secret: str):
    """Start control station v5 with credentials"""
    print("[START] Starting Control Station V5 (Remote Control)...")
    
    # Import and configure control station
    from eaa_control_station_v5_remote import set_credentials, start_server
    
    # Set credentials
    set_credentials(api_key, secret)
    
    # Run in thread
    thread = threading.Thread(target=start_server, daemon=True)
    thread.start()
    time.sleep(1)

def start_eaa():
    """Start EAA process"""
    print("[START] Starting EAA AI Server...")
    
    venv_python = os.path.join(EAA_PATH, ".venv-hf", "Scripts", "python.exe")
    
    if not os.path.exists(venv_python):
        print(f"[ERR] Python not found: {venv_python}")
        return None
    
    process = subprocess.Popen(
        [venv_python, os.path.join(EAA_PATH, EAA_ENTRY)],
        cwd=EAA_PATH,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace'
    )
    
    processes["eaa"] = process
    print(f"[EAA] Started (PID: {process.pid})")
    
    # Output reader thread
    def read_output():
        try:
            for line in iter(process.stdout.readline, ''):
                if line:
                    print(f"[EAA] {line.rstrip()}")
        except:
            pass
    
    threading.Thread(target=read_output, daemon=True).start()
    return process

def start_tunnel():
    """Start Cloudflare tunnel"""
    print("[START] Starting Cloudflare Tunnel...")
    
    cloudflared_path = os.path.join(EAA_PATH, "tools", "cloudflared.exe")
    
    if not os.path.exists(cloudflared_path):
        print(f"[ERR] cloudflared not found: {cloudflared_path}")
        return None
    
    process = subprocess.Popen(
        [cloudflared_path, "tunnel", "--url", f"http://localhost:{CONTROL_PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    processes["tunnel"] = process
    print("[WAIT] Waiting for tunnel URL...")
    
    # Find tunnel URL
    tunnel_url = None
    start_time = time.time()
    
    def read_tunnel_output():
        nonlocal tunnel_url
        try:
            for line in iter(process.stdout.readline, ''):
                if line:
                    print(f"[TUNNEL] {line.rstrip()}")
                    match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
                    if match and not tunnel_url:
                        tunnel_url = match.group(0)
        except:
            pass
    
    threading.Thread(target=read_tunnel_output, daemon=True).start()
    
    # Wait for URL
    while not tunnel_url and time.time() - start_time < 30:
        time.sleep(0.5)
    
    return tunnel_url

def stop_all():
    """Stop all processes"""
    print("\n[STOP] Stopping all processes...")
    
    for name, proc in processes.items():
        if proc and proc.poll() is None:
            print(f"[{name.upper()}] Stopping...")
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except:
                proc.kill()
            print(f"[{name.upper()}] Stopped")
    
    print("[BYE] All stopped!")

def main():
    """Main entry point"""
    print_banner()
    
    # Check dependencies
    check_dependencies()
    
    # Generate credentials
    api_key = generate_api_key()
    secret = generate_secret_phrase()
    
    print(f"\n[KEY] Generated API Key: {api_key}")
    print(f"[SECRET] Generated Secret Phrase: {secret}")
    print()
    
    try:
        # Start control station
        start_control_station(api_key, secret)
        
        # Start EAA
        start_eaa()
        
        # Start tunnel
        tunnel_url = start_tunnel()
        
        if tunnel_url:
            print("\n" + "=" * 60)
            print("  🎮 FULL REMOTE CONTROL ENABLED!")
            print("=" * 60)
            print(f"\n  Control URL: {tunnel_url}")
            print(f"  API Key: {api_key}")
            print(f"  Secret: {secret}")
            print(f"\n  📸 GET  /screenshot - See the screen")
            print(f"  🖱️  POST /click     - Click at x,y")
            print(f"  ⌨️  POST /type      - Type text")
            print(f"  🔑 POST /key       - Press key")
            print(f"  🔗 POST /hotkey    - Ctrl+C, Alt+Tab, etc.")
            print(f"  📜 POST /scroll    - Scroll up/down")
            print(f"\n  Session Timeout: DISABLED (never expires!)")
            print("\n  >>> TELL SUPER Z <<<")
            print(f"    URL: {tunnel_url}")
            print(f"    Key: {api_key}")
            print(f"    Secret: {secret}")
            print("=" * 60)
            print("\n[READY] Press Ctrl+C to stop")
        else:
            print("[ERR] Failed to get tunnel URL")
        
        # Keep running
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        stop_all()
    except Exception as e:
        print(f"[ERR] {e}")
        stop_all()

if __name__ == "__main__":
    main()
