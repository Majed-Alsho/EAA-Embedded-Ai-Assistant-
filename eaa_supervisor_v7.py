"""
EAA CONTROL - SUPERVISOR V7 (IMMORTAL VERSION)
==============================================
This script CANNOT be stopped with Ctrl+C!

ONLY stops when you CLOSE the PowerShell window
If server crashes → auto restart + email
If you try Ctrl+C → IGNORED, keeps running
RUN THIS instead of the main server!
To stop: Close the PowerShell window

V7: Monitors eaa_control_email_v7.py (All V5 + V6 features)
"""

import os
import sys
import time
import subprocess
import smtplib
import signal
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# CONFIGURATION

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_SERVER = os.path.join(SCRIPT_DIR, "eaa_control_email_v7.py")
CHECK_INTERVAL = 5 # Check every 5 seconds

# Email settings
EMAIL_ENABLED = True
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_FROM = "majed1.alshoghri@gmail.com"
EMAIL_TO = "majed1.alshoghri@gmail.com"
EMAIL_PASSWORD = "vqgeblnuxfqsxbxn"

# ============================================
# EMAIL FUNCTION
# ============================================
def send_email(subject, body):
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
        
        print(f"[EMAIL] ✅ Sent: {subject}")
        return True
    except Exception as e:
        print(f"[EMAIL] ❌ Failed: {e}")
        return False

def send_crash_notification(reason="Server Crashed"):
    """Send email when server crashes and restarts"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"🚨 EAA Control V7 - {reason}"
    
    body = f"""
{'='*50}
EAA CONTROL V7 - SUPERVISOR NOTIFICATION
{'='*50}

{reason.upper()}

The server has been automatically restarted!
New credentials will be in the next email.

{'='*50}
WHAT HAPPENED:
{'='*50}

Server crashed or was stopped
Supervisor detected it
Server was automatically restarted
New tunnel was created
You'll receive new credentials shortly
Timestamp: {timestamp}

{'='*50}
CHECK YOUR NEXT EMAIL FOR NEW CREDENTIALS!
{'='*50}
"""
    return send_email(subject, body)

# ============================================
# SUPERVISOR - IMMORTAL VERSION
# ============================================
process = None
restart_count = 0

def ignore_signal(sig, frame):
    """IGNORE Ctrl+C and other signals!"""
    print("\n[SUPERVISOR] ⚠️ Ctrl+C ignored! Close this window to stop.")
    print("[SUPERVISOR] Server keeps running...")

def start_server():
    """Start the main server"""
    global process
    try:
        print(f"[SUPERVISOR] Starting main server...")
        process = subprocess.Popen(
            [sys.executable, MAIN_SERVER],
            cwd=SCRIPT_DIR
        )
        return process.pid
    except Exception as e:
        print(f"[SUPERVISOR] ❌ Failed to start: {e}")
        return None

def check_server():
    """Check if server is running"""
    global process
    if process is None:
        return False
    try:
        return process.poll() is None
    except:
        return False

def stop_server():
    """Stop the server"""
    global process
    if process:
        try:
            process.terminate()
            process.wait(timeout=10)
        except:
            try:
                process.kill()
            except:
                pass
        process = None

def restart_server(reason="Restart"):
    """Restart the server and send notification"""
    global restart_count, process
    restart_count += 1
    
    print(f"\n{'='*60}")
    print(f"[SUPERVISOR] 🔄 {reason} (restart #{restart_count})")
    print('='*60)
    
    # Send crash notification FIRST
    send_crash_notification(reason)
    
    # Stop old server
    stop_server()
    time.sleep(3)
    
    # Start new server (it will send email with new credentials)
    pid = start_server()
    
    if pid:
        print(f"[SUPERVISOR] ✅ Server restarted (PID: {pid})")
        print("[SUPERVISOR] 📧 Check your email for new credentials!")
    else:
        print("[SUPERVISOR] ❌ Failed to restart - will retry...")
        
    return pid

# ============================================
# MAIN LOOP - NEVER STOPS
# ============================================
if __name__ == "__main__":
    
    # IGNORE all signals (Ctrl+C wont work!)
    signal.signal(signal.SIGINT, ignore_signal)   # Ctrl+C
    signal.signal(signal.SIGTERM, ignore_signal)  # kill command
    
    print("=" * 60)
    print("  EAA CONTROL V7 - SUPERVISOR (IMMORTAL)")
    print("  Ctrl+C is IGNORED - Only stops when window closes!")
    print("=" * 60)
    print(f"[CONFIG] Main server: {MAIN_SERVER}")
    print(f"[CONFIG] Check interval: {CHECK_INTERVAL}s")
    print(f"[CONFIG] Email: {EMAIL_TO}")
    print("=" * 60)
    print("[INFO] 🔒 Press Ctrl+C all you want - I won't stop!")
    print("[INFO] ❌ To stop: Close this PowerShell window")
    print("=" * 60)
    
    # Check if main server exists
    if not os.path.exists(MAIN_SERVER):
        print(f"\n[SUPERVISOR] ❌ Main server not found: {MAIN_SERVER}")
        print("[SUPERVISOR] Please make sure eaa_control_email_v7.py exists!")
        sys.exit(1)
        
    # Initial start
    print("\n[SUPERVISOR] Starting main server...")
    pid = start_server()
    if pid:
        print(f"[SUPERVISOR] ✅ Main server started (PID: {pid})")
    else:
        print("[SUPERVISOR] ❌ Failed to start main server!")
        sys.exit(1)
        
    print("\n[SUPERVISOR] 🛡️ Monitoring... (Ctrl+C is disabled)")
    print("-" * 60)
    
    last_heartbeat = time.time()
    
    # INFINITE LOOP - only stops when window closes
    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            
            if not check_server():
                # Server died! Restart it!
                restart_server("Server Crashed/Stopped")
            else:
                # Heartbeat every 30 seconds
                now = time.time()
                if now - last_heartbeat > 30:
                    try:
                        print(f"[SUPERVISOR] 💓 Server OK (PID: {process.pid}, Restarts: {restart_count})")
                    except:
                        print(f"[SUPERVISOR] 💓 Server OK (Restarts: {restart_count})")
                    last_heartbeat = now
                    
        except Exception as e:
            print(f"[SUPERVISOR] ⚠️ Error (ignored): {e}")
            time.sleep(5)
            # Don't break! Keep going!