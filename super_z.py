"""
SUPER Z INTEGRATION MODULE
==========================
Integration layer between EAA Control System and Super Z AI assistant.
Provides unified API for remote control operations.
"""

import json
import time
import base64
import requests
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

class ControlLevel(Enum):
    """Access control levels"""
    READ_ONLY = 1      # Screenshot, system info, file read
    ACTIVE = 2         # Notifications, clipboard, browser
    FULL = 3           # Mouse, keyboard, shell, power

@dataclass
class SuperZConfig:
    """Configuration for Super Z connection"""
    tunnel_url: str
    api_key: str
    secret: str
    session_token: Optional[str] = None
    timeout: int = 30

class SuperZIntegration:
    """
    Super Z Integration Class
    
    Provides high-level API for controlling EAA remotely.
    Handles authentication, session management, and all control operations.
    """
    
    def __init__(self, config: SuperZConfig):
        self.config = config
        self.session_token = config.session_token
        self.last_screenshot = None
        self.last_activity = time.time()
    
    def _headers(self) -> Dict[str, str]:
        """Build request headers with auth"""
        headers = {
            "X-Control-Key": self.config.api_key,
            "X-Secret": self.config.secret,
            "Content-Type": "application/json"
        }
        if self.session_token:
            headers["X-Session-Token"] = self.session_token
        return headers
    
    def _request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make HTTP request to control server"""
        url = f"{self.config.tunnel_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=self._headers(), 
                                       timeout=self.config.timeout)
            else:
                response = requests.post(url, headers=self._headers(),
                                        json=data or {}, 
                                        timeout=self.config.timeout)
            
            result = response.json()
            
            # Capture session token if provided
            if "session_token" in result:
                self.session_token = result["session_token"]
            
            self.last_activity = time.time()
            return result
            
        except requests.exceptions.Timeout:
            return {"suc": False, "err": "Request timed out"}
        except requests.exceptions.ConnectionError:
            return {"suc": False, "err": "Connection failed"}
        except Exception as e:
            return {"suc": False, "err": str(e)}
    
    # ==========================================
    # SYSTEM OPERATIONS
    # ==========================================
    
    def health_check(self) -> Dict:
        """Check if control server is online"""
        return self._request("GET", "/health")
    
    def get_system_info(self) -> Dict:
        """Get system information (CPU, RAM, etc.)"""
        return self._request("GET", "/system/info")
    
    def get_process_list(self) -> List[Dict]:
        """Get list of running processes"""
        result = self._request("GET", "/process/list")
        return result.get("processes", [])
    
    def kill_process(self, pid: int) -> bool:
        """Kill a process by PID"""
        result = self._request("POST", "/process/kill", {"pid": pid})
        return result.get("suc", False)
    
    def start_program(self, path: str) -> bool:
        """Start a program"""
        result = self._request("POST", "/process/start", {"path": path})
        return result.get("suc", False)
    
    # ==========================================
    # SCREENSHOT OPERATIONS
    # ==========================================
    
    def take_screenshot(self) -> Optional[bytes]:
        """Take screenshot and return image bytes"""
        result = self._request("GET", "/screenshot")
        if result.get("suc") and "image" in result:
            self.last_screenshot = result["image"]
            return base64.b64decode(result["image"])
        return None
    
    def get_screenshot_base64(self) -> Optional[str]:
        """Take screenshot and return base64 string"""
        result = self._request("GET", "/screenshot")
        if result.get("suc") and "image" in result:
            self.last_screenshot = result["image"]
            return result["image"]
        return None
    
    # ==========================================
    # MOUSE OPERATIONS
    # ==========================================
    
    def get_mouse_position(self) -> tuple:
        """Get current mouse position"""
        result = self._request("GET", "/mouse/position")
        if result.get("suc"):
            return (result.get("x", 0), result.get("y", 0))
        return (0, 0)
    
    def move_mouse(self, x: int, y: int) -> bool:
        """Move mouse to coordinates"""
        result = self._request("POST", "/mouse/move", {"x": x, "y": y})
        return result.get("suc", False)
    
    def click(self, x: int = None, y: int = None, 
              button: str = "left", clicks: int = 1) -> bool:
        """Click at position or current location"""
        data = {"button": button, "clicks": clicks}
        if x is not None and y is not None:
            data["x"] = x
            data["y"] = y
        result = self._request("POST", "/mouse/click", data)
        return result.get("suc", False)
    
    def double_click(self, x: int = None, y: int = None) -> bool:
        """Double click at position"""
        return self.click(x, y, clicks=2)
    
    def right_click(self, x: int = None, y: int = None) -> bool:
        """Right click at position"""
        return self.click(x, y, button="right")
    
    def scroll(self, amount: int = 3, direction: str = "down") -> bool:
        """Scroll mouse wheel"""
        result = self._request("POST", "/mouse/scroll", 
                              {"amount": amount, "direction": direction})
        return result.get("suc", False)
    
    # ==========================================
    # KEYBOARD OPERATIONS
    # ==========================================
    
    def type_text(self, text: str, interval: float = 0.02) -> bool:
        """Type text on keyboard"""
        result = self._request("POST", "/keyboard/type", 
                              {"text": text, "interval": interval})
        return result.get("suc", False)
    
    def press_key(self, key: str) -> bool:
        """Press a single key"""
        result = self._request("POST", "/keyboard/press", {"key": key})
        return result.get("suc", False)
    
    def hotkey(self, *keys) -> bool:
        """Press keyboard combination"""
        result = self._request("POST", "/keyboard/hotkey", {"keys": list(keys)})
        return result.get("suc", False)
    
    def copy(self) -> bool:
        """Press Ctrl+C"""
        return self.hotkey("ctrl", "c")
    
    def paste(self) -> bool:
        """Press Ctrl+V"""
        return self.hotkey("ctrl", "v")
    
    def select_all(self) -> bool:
        """Press Ctrl+A"""
        return self.hotkey("ctrl", "a")
    
    def undo(self) -> bool:
        """Press Ctrl+Z"""
        return self.hotkey("ctrl", "z")
    
    def enter(self) -> bool:
        """Press Enter"""
        return self.press_key("enter")
    
    def tab(self) -> bool:
        """Press Tab"""
        return self.press_key("tab")
    
    def escape(self) -> bool:
        """Press Escape"""
        return self.press_key("escape")
    
    # ==========================================
    # FILE OPERATIONS
    # ==========================================
    
    def read_file(self, path: str) -> Optional[str]:
        """Read file content"""
        result = self._request("POST", "/file/read", {"path": path})
        return result.get("content") if result.get("suc") else None
    
    def write_file(self, path: str, content: str) -> bool:
        """Write content to file"""
        result = self._request("POST", "/file/write", 
                              {"path": path, "content": content})
        return result.get("suc", False)
    
    def list_directory(self, path: str) -> List[Dict]:
        """List directory contents"""
        result = self._request("POST", "/file/list", {"path": path})
        return result.get("items", [])
    
    def delete_file(self, path: str) -> bool:
        """Delete file or folder"""
        result = self._request("POST", "/file/delete", {"path": path})
        return result.get("suc", False)
    
    def move_file(self, src: str, dst: str) -> bool:
        """Move file or folder"""
        result = self._request("POST", "/file/move", {"src": src, "dst": dst})
        return result.get("suc", False)
    
    def copy_file(self, src: str, dst: str) -> bool:
        """Copy file or folder"""
        result = self._request("POST", "/file/copy", {"src": src, "dst": dst})
        return result.get("suc", False)
    
    # ==========================================
    # SHELL OPERATIONS
    # ==========================================
    
    def run_command(self, command: str, timeout: int = 30) -> Dict:
        """Run shell command"""
        return self._request("POST", "/shell", 
                            {"command": command, "timeout": timeout})
    
    # ==========================================
    # WINDOW OPERATIONS
    # ==========================================
    
    def list_windows(self) -> List[Dict]:
        """List all open windows"""
        result = self._request("GET", "/windows/list")
        return result.get("windows", [])
    
    def focus_window(self, title: str) -> bool:
        """Focus window by title"""
        result = self._request("POST", "/window/focus", {"title": title})
        return result.get("suc", False)
    
    def close_window(self, title: str) -> bool:
        """Close window by title"""
        result = self._request("POST", "/window/close", {"title": title})
        return result.get("suc", False)
    
    # ==========================================
    # CLIPBOARD OPERATIONS
    # ==========================================
    
    def get_clipboard(self) -> Optional[str]:
        """Get clipboard content"""
        result = self._request("GET", "/clipboard/get")
        return result.get("content") if result.get("suc") else None
    
    def set_clipboard(self, content: str) -> bool:
        """Set clipboard content"""
        result = self._request("POST", "/clipboard/set", {"content": content})
        return result.get("suc", False)
    
    # ==========================================
    # NOTIFICATION & BROWSER
    # ==========================================
    
    def send_notification(self, title: str, message: str) -> bool:
        """Send Windows notification"""
        result = self._request("POST", "/notify", 
                              {"title": title, "message": message})
        return result.get("suc", False)
    
    def open_browser(self, url: str) -> bool:
        """Open URL in browser"""
        result = self._request("POST", "/browser/open", {"url": url})
        return result.get("suc", False)
    
    def search_web(self, query: str) -> bool:
        """Open Google search"""
        result = self._request("POST", "/browser/search", {"query": query})
        return result.get("suc", False)
    
    def launch_app(self, app: str) -> bool:
        """Launch an application"""
        result = self._request("POST", "/app/launch", {"app": app})
        return result.get("suc", False)
    
    # ==========================================
    # POWER OPERATIONS
    # ==========================================
    
    def sleep(self) -> bool:
        """Put computer to sleep"""
        result = self._request("POST", "/power/sleep", {})
        return result.get("suc", False)
    
    def restart(self) -> bool:
        """Restart computer"""
        result = self._request("POST", "/power/restart", {})
        return result.get("suc", False)
    
    def shutdown(self) -> bool:
        """Shutdown computer"""
        result = self._request("POST", "/power/shutdown", {})
        return result.get("suc", False)
    
    def cancel_power(self) -> bool:
        """Cancel pending power action"""
        result = self._request("POST", "/power/cancel", {})
        return result.get("suc", False)
    
    # ==========================================
    # HIGH-LEVEL OPERATIONS
    # ==========================================
    
    def see_screen(self) -> str:
        """Take screenshot and describe what's visible"""
        img = self.get_screenshot_base64()
        if img:
            return f"Screenshot captured ({len(img)} bytes base64)"
        return "Failed to capture screenshot"
    
    def click_at_text(self, text: str) -> bool:
        """Click where specific text appears (requires vision)"""
        # This would integrate with vision AI to find text on screen
        # Placeholder for now
        return False
    
    def type_and_enter(self, text: str) -> bool:
        """Type text and press Enter"""
        if self.type_text(text):
            return self.enter()
        return False
    
    def multi_action(self, actions: List[Dict]) -> List[bool]:
        """Execute multiple actions in sequence"""
        results = []
        for action in actions:
            action_type = action.get("type")
            params = action.get("params", {})
            
            if action_type == "click":
                results.append(self.click(**params))
            elif action_type == "type":
                results.append(self.type_text(**params))
            elif action_type == "hotkey":
                results.append(self.hotkey(*params.get("keys", [])))
            elif action_type == "screenshot":
                results.append(self.take_screenshot() is not None)
            elif action_type == "wait":
                time.sleep(params.get("seconds", 1))
                results.append(True)
            else:
                results.append(False)
        
        return results


# ==========================================
# CONVENIENCE FUNCTIONS
# ==========================================

def create_super_z(tunnel_url: str, api_key: str, secret: str) -> SuperZIntegration:
    """Create Super Z integration instance"""
    config = SuperZConfig(
        tunnel_url=tunnel_url,
        api_key=api_key,
        secret=secret
    )
    return SuperZIntegration(config)


# ==========================================
# EXAMPLE USAGE
# ==========================================

if __name__ == "__main__":
    # Example usage
    print("Super Z Integration Module")
    print("=" * 40)
    print("\nUsage:")
    print("""
    from super_z import create_super_z
    
    # Connect to control server
    sz = create_super_z(
        tunnel_url="https://your-tunnel.trycloudflare.com",
        api_key="your-api-key",
        secret="your-secret"
    )
    
    # Take screenshot
    img = sz.take_screenshot()
    
    # Get system info
    info = sz.get_system_info()
    
    # Click at position
    sz.click(500, 300)
    
    # Type text
    sz.type_text("Hello World!")
    
    # Press Enter
    sz.enter()
    
    # Run shell command
    result = sz.run_command("dir")
    print(result)
    """)
