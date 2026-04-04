"""
EAA CONTROL STATION V4 - NO SESSION TIMEOUT
Fixed version - session never expires!
"""

import http.server
import socketserver
import json
import threading
import time
import secrets
import hashlib
import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any

# Configuration
PORT = 8001
MAX_REQUESTS_PER_MINUTE = 150
ALLOWED_BASE_PATH = r"C:\Users\offic"
EAA_BACKEND_URL = "http://localhost:8000"  # EAA AI backend

class SecureControlHandler(http.server.BaseHTTPRequestHandler):
    """Secure control handler with NO timeout"""
    
    # Class-level session storage (persists across requests)
    session_token: Optional[str] = None
    api_key: Optional[str] = None
    secret_phrase: Optional[str] = None
    request_times: list = []
    
    def log_message(self, format, *args):
        """Custom logging with [CONTROL] prefix"""
        print(f"[CONTROL] {args[0]}")
    
    def send_json(self, data: dict, status: int = 200):
        """Send JSON response"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def check_rate_limit(self) -> bool:
        """Check if request is within rate limits"""
        now = time.time()
        # Keep only requests from last 60 seconds
        SecureControlHandler.request_times = [
            t for t in SecureControlHandler.request_times 
            if now - t < 60
        ]
        
        if len(SecureControlHandler.request_times) >= MAX_REQUESTS_PER_MINUTE:
            return False
        
        SecureControlHandler.request_times.append(now)
        return True
    
    def validate_path(self, path: str) -> bool:
        """Ensure path is within allowed directory"""
        try:
            abs_path = os.path.abspath(path)
            return abs_path.startswith(ALLOWED_BASE_PATH)
        except:
            return False
    
    def authenticate(self, data: dict) -> tuple:
        """Authenticate request - NO TIMEOUT CHECK"""
        # Check API key
        api_key = data.get('api_key', '')
        if api_key != SecureControlHandler.api_key:
            return False, "Invalid API key"
        
        # Check secret phrase
        secret = data.get('secret', '')
        if secret != SecureControlHandler.secret_phrase:
            return False, "Invalid secret phrase"
        
        # NO TIMEOUT CHECK - Session never expires!
        # The old code checked session_token here, but we removed it
        
        # Set session token on first successful auth
        if SecureControlHandler.session_token is None:
            SecureControlHandler.session_token = f"SESS_{secrets.token_urlsafe(16)}"
            print(f"[AUTH] 🎫 Session token issued: {SecureControlHandler.session_token[:10]}...")
        
        return True, SecureControlHandler.session_token
    
    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-API-Key, X-Secret')
        self.end_headers()
    
    def do_GET(self):
        """Handle GET requests"""
        if not self.check_rate_limit():
            self.send_json({"suc": False, "err": "Rate limit exceeded"}, 429)
            return
        
        # Health check endpoint (no auth required)
        if self.path == '/health':
            self.send_json({
                "status": "online",
                "session_active": SecureControlHandler.session_token is not None
            })
            return
        
        # Status endpoint
        if self.path == '/status':
            self.send_json({
                "status": "online",
                "session_active": SecureControlHandler.session_token is not None,
                "api_key_set": SecureControlHandler.api_key is not None,
                "secret_set": SecureControlHandler.secret_phrase is not None
            })
            return
        
        # AI Health endpoint (no auth required)
        if self.path == '/ai/health':
            try:
                req = urllib.request.urlopen(f"{EAA_BACKEND_URL}/ai/health", timeout=5)
                response = json.loads(req.read().decode())
                self.send_json({"suc": True, **response})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        self.send_json({"suc": False, "err": "Unknown endpoint"}, 404)
    
    def do_POST(self):
        """Handle POST requests"""
        if not self.check_rate_limit():
            self.send_json({"suc": False, "err": "Rate limit exceeded"}, 429)
            return
        
        # Read request body
        content_length = int(self.headers.get('Content-Length', 0))
        try:
            body = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(body) if body else {}
        except Exception as e:
            self.send_json({"suc": False, "err": f"Invalid JSON: {str(e)}"}, 400)
            return
        
        # Parse path
        path = self.path.split('?')[0].rstrip('/')
        
        # === PUBLIC ENDPOINTS (no auth) ===
        
        if path == '/auth' or path == '/authenticate':
            """Authenticate and get session token"""
            valid, result = self.authenticate(data)
            if valid:
                self.send_json({
                    "suc": True,
                    "session_token": result,
                    "message": "Authentication successful - session active (no expiration)"
                })
            else:
                self.send_json({"suc": False, "err": result}, 401)
            return
        
        # === PROTECTED ENDPOINTS (require auth) ===
        
        valid, session_or_err = self.authenticate(data)
        if not valid:
            self.send_json({"suc": False, "err": session_or_err}, 401)
            return
        
        # READ FILE
        if path == '/read' or path == '/v1/remote/read':
            file_path = data.get('path', '')
            if not self.validate_path(file_path):
                self.send_json({"suc": False, "err": "Path not allowed"}, 403)
                return
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.send_json({"suc": True, "content": content})
            except FileNotFoundError:
                self.send_json({"suc": False, "err": "File not found"}, 404)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)}, 500)
            return
        
        # WRITE FILE
        if path == '/write' or path == '/v1/remote/write':
            file_path = data.get('path', '')
            content = data.get('content', '')
            
            if not self.validate_path(file_path):
                self.send_json({"suc": False, "err": "Path not allowed"}, 403)
                return
            
            try:
                # Create directory if needed
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.send_json({"suc": True, "message": f"Written to {file_path}"})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)}, 500)
            return
        
        # DELETE FILE
        if path == '/delete' or path == '/v1/remote/delete':
            file_path = data.get('path', '')
            
            if not self.validate_path(file_path):
                self.send_json({"suc": False, "err": "Path not allowed"}, 403)
                return
            
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    self.send_json({"suc": True, "message": f"Deleted {file_path}"})
                else:
                    self.send_json({"suc": False, "err": "File not found"}, 404)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)}, 500)
            return
        
        # LIST DIRECTORY
        if path == '/list' or path == '/v1/remote/list':
            dir_path = data.get('path', '')
            
            if not self.validate_path(dir_path):
                self.send_json({"suc": False, "err": "Path not allowed"}, 403)
                return
            
            try:
                items = []
                for item in os.listdir(dir_path):
                    full_path = os.path.join(dir_path, item)
                    items.append({
                        "name": item,
                        "type": "directory" if os.path.isdir(full_path) else "file",
                        "size": os.path.getsize(full_path) if os.path.isfile(full_path) else None
                    })
                self.send_json({"suc": True, "items": items})
            except FileNotFoundError:
                self.send_json({"suc": False, "err": "Directory not found"}, 404)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)}, 500)
            return
        
        # EXECUTE COMMAND
        if path == '/exec' or path == '/v1/remote/exec':
            cmd = data.get('command', '')
            cwd = data.get('cwd', r'C:\Users\offic\EAA')
            
            if not self.validate_path(cwd):
                self.send_json({"suc": False, "err": "Working directory not allowed"}, 403)
                return
            
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    timeout=60
                )
                self.send_json({
                    "suc": True,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode
                })
            except subprocess.TimeoutExpired:
                self.send_json({"suc": False, "err": "Command timed out (60s)"}, 500)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)}, 500)
            return
        
        # GET EAA LOGS
        if path == '/logs' or path == '/v1/remote/logs':
            log_file = r"C:\Users\offic\EAA\eaa_terminal.log"
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    # Get last 100 lines
                    lines = f.readlines()[-100:]
                self.send_json({"suc": True, "logs": "".join(lines)})
            except FileNotFoundError:
                self.send_json({"suc": False, "err": "Log file not found"}, 404)
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)}, 500)
            return
        
        # AI CHAT - Forward to EAA backend
        if path == '/ai/chat':
            try:
                # Forward request to EAA backend
                req_data = json.dumps({
                    "message": data.get('message', ''),
                    "brain_type": data.get('brain_type', 'shadow'),
                    "max_tokens": data.get('max_tokens', 512)
                }).encode('utf-8')
                
                req = urllib.request.Request(
                    f"{EAA_BACKEND_URL}/ai/chat",
                    data=req_data,
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                
                response = urllib.request.urlopen(req, timeout=120)
                result = json.loads(response.read().decode())
                self.send_json(result)
            except urllib.error.URLError:
                self.send_json({"suc": False, "err": "EAA backend not running"})
            except Exception as e:
                self.send_json({"suc": False, "err": str(e)})
            return
        
        # UNKNOWN ENDPOINT
        self.send_json({"suc": False, "err": f"Unknown endpoint: {path}"}, 404)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Handle requests in separate threads"""
    allow_reuse_address = True
    daemon_threads = True


def set_credentials(api_key: str, secret_phrase: str):
    """Set authentication credentials"""
    SecureControlHandler.api_key = api_key
    SecureControlHandler.secret_phrase = secret_phrase
    SecureControlHandler.session_token = None  # Reset session
    print(f"[AUTH] Credentials set. Secret: '{secret_phrase[:3]}...{secret_phrase[-3:]}'")


def start_server():
    """Start the control station"""
    with ThreadedHTTPServer(("0.0.0.0", PORT), SecureControlHandler) as httpd:
        print(f"[CONTROL] 🚀 Control Station V4 (No Timeout) listening on port {PORT}")
        if SecureControlHandler.secret_phrase:
            print(f"[CONTROL] 🔐 Secret phrase: '{SecureControlHandler.secret_phrase}'")
        print(f"[CONTROL] ⏰ Session timeout: DISABLED (never expires)")
        httpd.serve_forever()


if __name__ == "__main__":
    # For standalone testing
    test_key = secrets.token_urlsafe(32)
    test_secret = "test-secret-phrase"
    set_credentials(test_key, test_secret)
    print(f"\n[TEST] API Key: {test_key}")
    print(f"[TEST] Secret: {test_secret}\n")
    start_server()
