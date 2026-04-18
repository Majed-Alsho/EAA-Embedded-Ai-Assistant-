"""
EAA System Tools - Phase 4
System operations: screenshot, clipboard, processes, system info, app launch, environment.
All tools use the existing ToolResult pattern from eaa_agent_tools.py.
"""

import os
import sys
import json
import platform
import subprocess
import traceback
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

try:
    from eaa_agent_tools import ToolResult
except ImportError:
    @dataclass
    class ToolResult:
        success: bool
        output: str
        error: Optional[str] = None
        def to_dict(self):
            return {"success": self.success, "output": self.output, "error": self.error}


# ─── SCREENSHOT ───────────────────────────────────────────────────────────────
def tool_screenshot(output_path: str = None, monitor: int = 0) -> ToolResult:
    """Capture a screenshot of the screen."""
    try:
        import pyautogui
        import pygetwindow as gw

        if output_path is None:
            output_dir = os.path.join(os.path.dirname(__file__), "..", "outputs", "screenshots")
            os.makedirs(output_dir, exist_ok=True)
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            output_path = os.path.join(output_dir, filename)
        else:
            output_path = os.path.expanduser(output_path)
            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

        # Get monitor info
        monitors = []
        try:
            import screeninfo
            monitors = screeninfo.get_monitors()
        except Exception:
            monitors = []

        if monitor > 0 and monitor < len(monitors):
            m = monitors[monitor]
            screenshot = pyautogui.screenshot(region=(m.x, m.y, m.width, m.height))
        else:
            screenshot = pyautogui.screenshot()

        screenshot.save(output_path)
        size = os.path.getsize(output_path)

        # Also get active window info
        try:
            active_window = gw.getActiveWindow()
            window_info = f"Active window: {active_window.title if active_window else 'N/A'}"
        except Exception:
            window_info = ""

        return ToolResult(True, f"Screenshot saved: {output_path}\nSize: {screenshot.width}x{screenshot.height} ({size:,} bytes)\n{window_info}")

    except Exception as e:
        return ToolResult(False, "", f"Screenshot failed: {str(e)}")


# ─── CLIPBOARD READ ───────────────────────────────────────────────────────────
def tool_clipboard_read() -> ToolResult:
    """Read the current clipboard content."""
    try:
        import pyperclip
        content = pyperclip.paste()
        if not content:
            return ToolResult(True, "[Clipboard is empty]")
        return ToolResult(True, f"Clipboard ({len(content)} chars):\n{content}")
    except Exception as e:
        return ToolResult(False, "", f"Clipboard read failed: {str(e)}")


# ─── CLIPBOARD WRITE ──────────────────────────────────────────────────────────
def tool_clipboard_write(text: str) -> ToolResult:
    """Write text to the clipboard."""
    try:
        import pyperclip
        pyperclip.copy(text)
        return ToolResult(True, f"Copied {len(text)} chars to clipboard")
    except Exception as e:
        return ToolResult(False, "", f"Clipboard write failed: {str(e)}")


# ─── PROCESS LIST ─────────────────────────────────────────────────────────────
def tool_process_list(filter_name: str = None, sort_by: str = "memory") -> ToolResult:
    """
    List running processes.
    filter_name: Filter by process name (partial match).
    sort_by: 'memory' (default), 'cpu', 'name', 'pid'
    """
    try:
        import psutil

        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status', 'username']):
            try:
                info = proc.info
                if filter_name and filter_name.lower() not in info['name'].lower():
                    continue
                processes.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort
        if sort_by == "memory":
            processes.sort(key=lambda p: p.get('memory_percent', 0) or 0, reverse=True)
        elif sort_by == "cpu":
            processes.sort(key=lambda p: p.get('cpu_percent', 0) or 0, reverse=True)
        elif sort_by == "name":
            processes.sort(key=lambda p: p.get('name', '').lower())
        elif sort_by == "pid":
            processes.sort(key=lambda p: p.get('pid', 0))

        # Limit output
        lines = [f"{'PID':>8} {'MEM%':>6} {'CPU%':>6} {'STATUS':>10} {'NAME'}"]
        lines.append("-" * 80)

        for p in processes[:50]:  # Top 50
            pid = p.get('pid', '?')
            mem = f"{p.get('memory_percent', 0) or 0:.1f}"
            cpu = f"{p.get('cpu_percent', 0) or 0:.1f}"
            status = str(p.get('status', '?'))[:10]
            name = p.get('name', '?')
            lines.append(f"{pid:>8} {mem:>6} {cpu:>6} {status:>10} {name}")

        if len(processes) > 50:
            lines.append(f"\n... showing 50 of {len(processes)} processes (use filter_name to narrow)")

        return ToolResult(True, f"Running Processes ({len(processes)} total):\n\n" + "\n".join(lines))

    except Exception as e:
        return ToolResult(False, "", f"Process list failed: {str(e)}")


# ─── PROCESS KILL ─────────────────────────────────────────────────────────────
def tool_process_kill(pid: int, force: bool = False) -> ToolResult:
    """Kill a process by PID. Use force=True for SIGKILL equivalent."""
    try:
        import psutil

        proc = psutil.Process(pid)
        name = proc.name()
        proc.kill() if force else proc.terminate()

        return ToolResult(True, f"{'Force killed' if force else 'Terminated'} process: {name} (PID {pid})")
    except psutil.NoSuchProcess:
        return ToolResult(False, "", f"Process {pid} not found")
    except psutil.AccessDenied:
        return ToolResult(False, "", f"Access denied to kill process {pid}")
    except Exception as e:
        return ToolResult(False, "", f"Process kill failed: {str(e)}")


# ─── SYSTEM INFO ──────────────────────────────────────────────────────────────
def tool_system_info() -> ToolResult:
    """Get detailed system information."""
    try:
        import psutil
        import platform

        info = {
            "os": f"{platform.system()} {platform.release()} {platform.version()}",
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "hostname": platform.node(),
            "python": platform.python_version(),
        }

        # CPU
        cpu_info = {
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "cpu_percent": f"{psutil.cpu_percent(interval=1):.1f}%",
            "cpu_freq": str(psutil.cpu_freq().current) if psutil.cpu_freq() else "N/A",
        }
        info["cpu"] = cpu_info

        # Memory
        mem = psutil.virtual_memory()
        info["memory"] = {
            "total": f"{mem.total / (1024**3):.1f} GB",
            "available": f"{mem.available / (1024**3):.1f} GB",
            "used": f"{mem.used / (1024**3):.1f} GB",
            "percent": f"{mem.percent}%",
        }

        # Disk
        disk = psutil.disk_usage('/')
        info["disk"] = {
            "total": f"{disk.total / (1024**3):.1f} GB",
            "used": f"{disk.used / (1024**3):.1f} GB",
            "free": f"{disk.free / (1024**3):.1f} GB",
            "percent": f"{disk.percent}%",
        }

        # GPU
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                gpu_mem = torch.cuda.get_device_properties(0).total_mem / (1024**3)
                gpu_allocated = torch.cuda.memory_allocated(0) / (1024**3)
                info["gpu"] = {
                    "name": gpu_name,
                    "total_vram": f"{gpu_mem:.1f} GB",
                    "allocated": f"{gpu_allocated:.2f} GB",
                    "free": f"{gpu_mem - gpu_allocated:.2f} GB",
                    "cuda_version": torch.version.cuda,
                }
        except Exception:
            info["gpu"] = "Not available"

        # Network
        try:
            addrs = psutil.net_if_addrs()
            interfaces = {}
            for iface, addr_list in addrs.items():
                for addr in addr_list:
                    if addr.family == 2:  # IPv4
                        interfaces[iface] = addr.address
            info["network"] = interfaces
        except Exception:
            pass

        # Uptime
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        hours = int(uptime.total_seconds() // 3600)
        minutes = int((uptime.total_seconds() % 3600) // 60)
        info["uptime"] = f"{hours}h {minutes}m (booted: {boot_time.strftime('%Y-%m-%d %H:%M')})"

        return ToolResult(True, json.dumps(info, indent=2))

    except Exception as e:
        return ToolResult(False, "", f"System info failed: {str(e)}")


# ─── APP LAUNCH ───────────────────────────────────────────────────────────────
def tool_app_launch(app_name: str, args: str = "", wait: bool = False) -> ToolResult:
    """
    Launch an application by name or path.
    app_name: Application name (e.g., 'notepad', 'chrome', 'C:\\path\\to\\app.exe')
    args: Command line arguments
    wait: Whether to wait for the app to close
    """
    try:
        # Try common app names
        app_map = {
            "notepad": "notepad.exe",
            "calc": "calc.exe",
            "calculator": "calc.exe",
            "explorer": "explorer.exe",
            "cmd": "cmd.exe",
            "powershell": "powershell.exe",
            "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
            "msedge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "vscode": r"C:\Users\offic\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        }

        target = app_map.get(app_name.lower(), app_name)

        command = f'"{target}"'
        if args:
            command += f" {args}"

        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)

        if result.returncode == 0 or result.returncode is None:
            return ToolResult(True, f"Launched: {target}")
        else:
            # Some apps return non-zero even on success
            return ToolResult(True, f"Launched: {target} (exit code: {result.returncode})")

    except subprocess.TimeoutExpired:
        if wait:
            return ToolResult(True, f"App {app_name} still running (timeout waiting)")
        return ToolResult(True, f"Launched: {app_name}")
    except FileNotFoundError:
        return ToolResult(False, "", f"Application not found: {app_name}")
    except Exception as e:
        return ToolResult(False, "", f"App launch failed: {str(e)}")


# ─── ENV GET ──────────────────────────────────────────────────────────────────
def tool_env_get(name: str = None) -> ToolResult:
    """Get environment variable(s). If name is None, lists all env vars."""
    try:
        if name:
            value = os.environ.get(name)
            if value is None:
                return ToolResult(True, f"Environment variable '{name}' not set")
            # Mask sensitive values
            sensitive_keys = ["key", "secret", "password", "token", "api_key"]
            if any(s in name.lower() for s in sensitive_keys):
                masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
                return ToolResult(True, f"{name} = {masked} (masked)")
            return ToolResult(True, f"{name} = {value}")
        else:
            # List all env vars (excluding sensitive ones)
            env_vars = {}
            sensitive = ["key", "secret", "password", "token"]
            for k, v in sorted(os.environ.items()):
                if any(s in k.lower() for s in sensitive):
                    env_vars[k] = "***"
                else:
                    env_vars[k] = v
            return ToolResult(True, json.dumps(env_vars, indent=2))
    except Exception as e:
        return ToolResult(False, "", f"Env get failed: {str(e)}")


# ─── ENV SET ──────────────────────────────────────────────────────────────────
def tool_env_set(name: str, value: str, persistent: bool = False) -> ToolResult:
    """
    Set environment variable.
    persistent: If True, sets it system-wide (requires admin on Windows)
    """
    try:
        os.environ[name] = value
        result = f"Set {name} = {value} (current session)"

        if persistent:
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, name, 0, winreg.REG_EXPAND_SZ, value)
                winreg.CloseKey(key)
                # Notify system of change
                subprocess.run("rundll32.exe sysdm.cpl,EditEnvironmentVariables", shell=True, timeout=5)
                result += " (persistent - system-wide)"
            except Exception as reg_err:
                result += f" (session only - persistent failed: {reg_err})"

        return ToolResult(True, result)
    except Exception as e:
        return ToolResult(False, "", f"Env set failed: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

def register_system_tools(registry) -> None:
    """Register all system tools with the existing ToolRegistry."""
    registry.register("screenshot", tool_screenshot, "Capture screen. Args: output_path (optional), monitor (default 0)")
    registry.register("clipboard_read", tool_clipboard_read, "Read clipboard content. Args: none")
    registry.register("clipboard_write", tool_clipboard_write, "Write to clipboard. Args: text")
    registry.register("process_list", tool_process_list, "List processes. Args: filter_name (optional), sort_by (memory/cpu/name/pid)")
    registry.register("process_kill", tool_process_kill, "Kill process. Args: pid, force (default False)")
    registry.register("system_info", tool_system_info, "Get system information. Args: none")
    registry.register("app_launch", tool_app_launch, "Launch application. Args: app_name, args (optional), wait (optional)")
    registry.register("env_get", tool_env_get, "Get env variable. Args: name (optional, lists all if omitted)")
    registry.register("env_set", tool_env_set, "Set env variable. Args: name, value, persistent (default False)")

__all__ = [
    "register_system_tools",
    "tool_screenshot", "tool_clipboard_read", "tool_clipboard_write",
    "tool_process_list", "tool_process_kill", "tool_system_info",
    "tool_app_launch", "tool_env_get", "tool_env_set",
]
