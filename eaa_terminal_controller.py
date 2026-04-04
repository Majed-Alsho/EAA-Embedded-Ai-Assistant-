"""
EAA TERMINAL CONTROLLER
=======================
- Starts and manages the EAA process
- Captures output
- Provides command execution
"""

import subprocess
import threading
import time
import os
import sys

class TerminalController:
    def __init__(self):
        self.process = None
        self.is_running = False
        self.output_buffer = []
        self.lock = threading.Lock()
        
    def start(self):
        """Start the EAA process."""
        if self.is_running:
            print("[EAA] Already running")
            return
        
        print("=" * 50)
        print("  EAA TERMINAL CONTROLLER")
        print("=" * 50)
        
        # Find the main EAA entry point
        eaa_dir = os.getcwd()
        main_script = os.path.join(eaa_dir, "run_eaa_agent.py")
        
        if not os.path.exists(main_script):
            print(f"[ERROR] Could not find {main_script}")
            return
        
        print(f"[START] Starting EAA...")
        
        # Start the process
        try:
            # Use the same Python interpreter and venv
            python_exe = sys.executable
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            self.process = subprocess.Popen(
                [python_exe, main_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=eaa_dir,
                startupinfo=startupinfo,
                encoding='utf-8',
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}
            )
            
            self.is_running = True
            print(f"[EAA] Started (PID: {self.process.pid})")
            
            # Start output capture thread
            threading.Thread(target=self._capture_output, daemon=True).start()
            
        except Exception as e:
            print(f"[ERROR] Failed to start EAA: {e}")
    
    def stop(self):
        """Stop the EAA process."""
        if not self.is_running:
            return
        
        print("[EAA] Stopping...")
        self.is_running = False
        
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except:
                try:
                    self.process.kill()
                except:
                    pass
            self.process = None
        
        print("[EAA] Stopped")
    
    def _capture_output(self):
        """Capture EAA output in a background thread."""
        if not self.process:
            return
        
        while self.is_running and self.process.poll() is None:
            try:
                line = self.process.stdout.readline()
                if line:
                    with self.lock:
                        self.output_buffer.append(line.strip())
                        # Keep only last 1000 lines
                        if len(self.output_buffer) > 1000:
                            self.output_buffer = self.output_buffer[-1000:]
                    print(f"[EAA] {line.strip()}")
            except:
                break
        
        self.is_running = False
    
    def get_output(self, lines=50):
        """Get recent output."""
        with self.lock:
            return self.output_buffer[-lines:]
    
    def execute_command(self, command):
        """Execute a shell command and return output."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.getcwd()
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out"}
        except Exception as e:
            return {"error": str(e)}


# For testing
if __name__ == "__main__":
    controller = TerminalController()
    controller.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        controller.stop()
