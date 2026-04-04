"""
EAA CONTROL STATION V3 - SECRET PASSPHRASE EDITION
====================================================
- Same session token security
- PLUS: Secret passphrase to prevent bot hijacking
- Only Super Z (with the secret) can claim the session
"""

import http.server
import socketserver
import json
import threading
import time
import secrets
import hashlib
from urllib.parse import urlparse, parse_qs
from typing import Optional, Dict, Any

# ============================
# CONFIG
# ============================
CONTROL_PORT = 8001
INACTIVITY_TIMEOUT = 300  # 5 minutes

# ============================
# GLOBAL STATE
# ============================
class ControlState:
    def __init__(self):
        self.api_key: Optional[str] = None
        self.session_token: Optional[str] = None
        self.session_secret: Optional[str] = None  # NEW: The secret passphrase
        self.last_activity: float = time.time()
        self.lock = threading.Lock()
        self.terminal_controller = None
        
    def set_credentials(self, api_key: str, secret: str):
        with self.lock:
            self.api_key = api_key
            self.session_secret = secret
            self.session_token = None  # Reset session on new credentials
            self.last_activity = time.time()
            print(f"[AUTH] Credentials set. Secret: '{secret[:3]}...{secret[-3:]}'")

state = ControlState()

# ============================
# REQUEST HANDLER
# ============================
class ControlHandler(http.server.BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        # Suppress default logging
        pass
    
    def _send_json(self, data: dict, status: int = 200):
        response = json.dumps(data, indent=2)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', '*')
        self.end_headers()
        self.wfile.write(response.encode())
    
    def _get_api_key(self) -> Optional[str]:
        """Extract API key from headers."""
        return self.headers.get('X-Control-Key')
    
    def _get_session_token(self) -> Optional[str]:
        """Extract session token from headers."""
        return self.headers.get('X-Session-Token')
    
    def _get_secret(self) -> Optional[str]:
        """Extract secret passphrase from headers or body."""
        secret = self.headers.get('X-Secret-Phrase')
        if not secret:
            # Try to get from body for POST requests
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length > 0:
                    body = self.rfile.read(content_length).decode()
                    data = json.loads(body)
                    secret = data.get('secret')
            except:
                pass
        return secret
    
    def _check_api_key(self) -> tuple:
        """Check if API key is valid. Returns (valid, error_response)."""
        key = self._get_api_key()
        if not key:
            return False, {"suc": False, "err": "Missing API key"}
        if key != state.api_key:
            return False, {"suc": False, "err": "Invalid API key"}
        return True, None
    
    def _check_session(self) -> tuple:
        """Check if session is valid. Returns (valid, error_response)."""
        # First check API key
        valid, error = self._check_api_key()
        if not valid:
            return False, error
        
        # Check if session is locked
        with state.lock:
            if state.session_token:
                # Session is locked - require token
                provided_token = self._get_session_token()
                if not provided_token:
                    return False, {
                        "suc": False, 
                        "err": "Session locked by another user. Your session token is required.",
                        "hint": "First connection gets the session token. Use X-Session-Token header."
                    }
                if provided_token != state.session_token:
                    return False, {"suc": False, "err": "Invalid session token"}
        
        return True, None
    
    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self._send_json({"status": "ok"})
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        # Health check - no auth required
        if path == '/health':
            self._send_json({"status": "healthy", "version": "v3"})
            return
        
        # Status endpoint - requires auth
        if path == '/status':
            valid, error = self._check_session()
            if not valid:
                self._send_json(error)
                return
            
            with state.lock:
                state.last_activity = time.time()
                status_data = {
                    "suc": True,
                    "eaa_running": state.terminal_controller.is_running if state.terminal_controller else False,
                    "session_active": state.session_token is not None,
                    "uptime": time.time() - state.last_activity
                }
            self._send_json(status_data)
            return
        
        # Unknown path
        self._send_json({"suc": False, "err": "Not found"}, 404)
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        # Connect endpoint - claim session with SECRET
        if path == '/connect':
            valid, error = self._check_api_key()
            if not valid:
                self._send_json(error)
                return
            
            # Get the secret passphrase
            provided_secret = self._get_secret()
            
            with state.lock:
                # Check if session is already claimed
                if state.session_token:
                    provided_token = self._get_session_token()
                    if provided_token != state.session_token:
                        self._send_json({
                            "suc": False,
                            "err": "Session already locked. Provide session token.",
                            "hint": "Use X-Session-Token header."
                        })
                        return
                    # Valid session token - refresh activity
                    state.last_activity = time.time()
                    self._send_json({
                        "suc": True,
                        "msg": "Session renewed",
                        "session_token": state.session_token
                    })
                    return
                
                # NEW: Check the secret passphrase
                if not provided_secret:
                    self._send_json({
                        "suc": False,
                        "err": "Secret passphrase required",
                        "hint": "Include X-Secret-Phrase header or 'secret' in body"
                    })
                    return
                
                if provided_secret != state.session_secret:
                    print(f"[BLOCKED] Wrong secret: '{provided_secret}'")
                    self._send_json({
                        "suc": False,
                        "err": "Invalid secret passphrase"
                    })
                    return
                
                # Generate session token for THIS client
                state.session_token = f"SESS_{secrets.token_urlsafe(32)}"
                state.last_activity = time.time()
                print(f"[SESSION] ✅ Granted to Super Z! Token: {state.session_token[:15]}...")
                
                self._send_json({
                    "suc": True,
                    "msg": "Session claimed! Welcome Super Z!",
                    "session_token": state.session_token
                })
            return
        
        # All other POST endpoints require session
        valid, error = self._check_session()
        if not valid:
            self._send_json(error)
            return
        
        # Execute command
        if path == '/exec':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode()
                data = json.loads(body)
                command = data.get('cmd')
                
                if not command:
                    self._send_json({"suc": False, "err": "No command provided"})
                    return
                
                # Execute via terminal controller
                if state.terminal_controller:
                    result = state.terminal_controller.execute_command(command)
                    with state.lock:
                        state.last_activity = time.time()
                    self._send_json({"suc": True, "result": result})
                else:
                    self._send_json({"suc": False, "err": "Terminal controller not available"})
                    
            except Exception as e:
                self._send_json({"suc": False, "err": str(e)})
            return
        
        # Read file
        if path == '/read':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode()
                data = json.loads(body)
                filepath = data.get('path')
                
                if not filepath:
                    self._send_json({"suc": False, "err": "No path provided"})
                    return
                
                # Security: only allow C:\Users\offic paths
                if not filepath.startswith('C:\\Users\\offic'):
                    self._send_json({"suc": False, "err": "Access denied - path not allowed"})
                    return
                
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                with state.lock:
                    state.last_activity = time.time()
                
                self._send_json({"suc": True, "content": content})
                
            except Exception as e:
                self._send_json({"suc": False, "err": str(e)})
            return
        
        # Write file
        if path == '/write':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode()
                data = json.loads(body)
                filepath = data.get('path')
                content = data.get('content')
                
                if not filepath or content is None:
                    self._send_json({"suc": False, "err": "Path and content required"})
                    return
                
                # Security: only allow C:\Users\offic paths
                if not filepath.startswith('C:\\Users\\offic'):
                    self._send_json({"suc": False, "err": "Access denied - path not allowed"})
                    return
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                with state.lock:
                    state.last_activity = time.time()
                
                self._send_json({"suc": True, "msg": f"Written to {filepath}"})
                
            except Exception as e:
                self._send_json({"suc": False, "err": str(e)})
            return
        
        # Unknown path
        self._send_json({"suc": False, "err": "Not found"}, 404)

# ============================
# INACTIVITY MONITOR
# ============================
def inactivity_monitor():
    """Clear session after inactivity timeout."""
    while True:
        time.sleep(30)
        with state.lock:
            if state.session_token and (time.time() - state.last_activity > INACTIVITY_TIMEOUT):
                print("[SESSION] ⏰ Session expired due to inactivity")
                state.session_token = None

# ============================
# MAIN
# ============================
def run_server(api_key: str, secret: str, terminal_controller=None):
    """Run the control station with given credentials."""
    state.set_credentials(api_key, secret)
    state.terminal_controller = terminal_controller
    
    # Start inactivity monitor
    threading.Thread(target=inactivity_monitor, daemon=True).start()
    
    with socketserver.ThreadingTCPServer(("", CONTROL_PORT), ControlHandler) as httpd:
        print(f"[CONTROL] 🚀 Control Station V3 listening on port {CONTROL_PORT}")
        print(f"[CONTROL] 🔐 Secret phrase: '{secret}'")
        httpd.serve_forever()

if __name__ == "__main__":
    # Test mode
    run_server("test-key-12345", "blueberry-pancake")
