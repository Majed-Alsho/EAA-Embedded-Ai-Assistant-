import subprocess
import os
import re
import threading
import sys
import time

# ===========================
# CONFIG
# ===========================
TOOLS_DIR = os.path.join(os.getcwd(), "tools")
CLOUDFLARED_PATH = os.path.join(TOOLS_DIR, "cloudflared.exe")
LOCAL_PORT = 8000
MEDIA_PORT = 8188  # ComfyUI default

class TunnelManager:
    def __init__(self):
        # ---- Brain tunnel fields ----
        self.process = None
        self.brain_url = None  # <--- FIXED: Renamed from public_url to brain_url
        self.is_running = False

        # ---- Studio tunnel fields ----
        self.media_process = None
        self.media_url = None

    # ===========================
    # Backward compatible brain start
    # ===========================
    def start(self):
        """Launches the invisible drill (Brain tunnel on LOCAL_PORT)."""
        return self.start_brain(port=LOCAL_PORT)

    # ===========================
    # New API expected by run_eaa_agent.py
    # ===========================
    def start_brain(self, port=LOCAL_PORT):
        """Launches the Main Brain Tunnel."""
        # already running?
        if self.process and self.process.poll() is None and self.brain_url:
            return self.brain_url

        if not os.path.exists(CLOUDFLARED_PATH):
            print(f"[TUNNEL] ❌ Error: Could not find cloudflared.exe at {CLOUDFLARED_PATH}")
            print("[TUNNEL] Please download it and place it in the 'tools' folder.")
            return None

        print(f"[TUNNEL] 🚇 Starting Cloudflare Tunnel on port {port}...")

        cmd = [CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{port}"]

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

        self.is_running = True
        threading.Thread(target=self._watch_output, daemon=True).start()
        return self.brain_url

    def start_media(self, port=MEDIA_PORT):
        """Launches the ComfyUI Studio Tunnel. Returns the public URL."""
        # already running?
        if self.media_process and self.media_process.poll() is None and self.media_url:
            return self.media_url

        if not os.path.exists(CLOUDFLARED_PATH):
            print(f"[TUNNEL] ❌ Error: Could not find cloudflared.exe at {CLOUDFLARED_PATH}")
            print("[TUNNEL] Please download it and place it in the 'tools' folder.")
            return None

        print(f"[TUNNEL] 🚇 Starting Cloudflare Studio Tunnel on port {port}...")

        cmd = [CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{port}"]

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        self.media_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            startupinfo=startupinfo,
            encoding='utf-8'
        )

        self.is_running = True
        threading.Thread(target=self._watch_media_output, daemon=True).start()

        # small wait to catch URL quickly (non-blocking enough)
        start_time = time.time()
        while time.time() - start_time < 15:
            if self.media_url:
                return self.media_url
            if self.media_process.poll() is not None:
                break
            time.sleep(0.1)

        return self.media_url

    def _watch_output(self):
        """Reads the tunnel's messy logs to find the diamond (Brain URL)."""
        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

        if not self.process:
            return

        while self.is_running and self.process.poll() is None:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break

                if "error" in line.lower():
                    print(f"[TUNNEL LOG] {line.strip()}")

                match = url_pattern.search(line)
                if match:
                    self.brain_url = match.group(0) # <--- FIXED: Assigns to brain_url
                    print("\n" + "=" * 50)
                    print(f"🌍 PUBLIC BRAIN URL: {self.brain_url}")
                    print("=" * 50 + "\n")
            except Exception:
                break

    def _watch_media_output(self):
        """Reads the tunnel's messy logs to find the diamond (Studio URL)."""
        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

        if not self.media_process:
            return

        while self.is_running and self.media_process.poll() is None:
            try:
                line = self.media_process.stdout.readline()
                if not line:
                    break

                if "error" in line.lower():
                    print(f"[STUDIO TUNNEL LOG] {line.strip()}")

                match = url_pattern.search(line)
                if match:
                    self.media_url = match.group(0)
                    print("\n" + "=" * 50)
                    print(f"🌍 PUBLIC STUDIO URL: {self.media_url}")
                    print("=" * 50 + "\n")
            except Exception:
                break

    def stop(self):
        """Kills the tunnel(s) when EAA shuts down."""
        if self.process or self.media_process:
            print("[TUNNEL] 🛑 Collapsing tunnel(s)...")

        self.is_running = False

        if self.process:
            try:
                self.process.terminate()
            except:
                pass
            self.process = None

        if self.media_process:
            try:
                self.media_process.terminate()
            except:
                pass
            self.media_process = None

# Global instance
tunnel = TunnelManager()

if __name__ == "__main__":
    # Test mode
    tunnel.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        tunnel.stop()