"""
EAA Communication Tools - Phase 6
Email, desktop notifications, and SMS.
All tools use the existing ToolResult pattern from eaa_agent_tools.py.
"""

import os
import json
import smtplib
import traceback
from typing import Optional
from dataclasses import dataclass
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

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


# ─── EMAIL SEND ───────────────────────────────────────────────────────────────
def tool_email_send(
    to: str,
    subject: str,
    body: str,
    from_addr: str = None,
    smtp_server: str = "smtp.gmail.com",
    smtp_port: int = 587,
    smtp_user: str = None,
    smtp_password: str = None,
    html: bool = False
) -> ToolResult:
    """
    Send an email via SMTP.
    Requires SMTP credentials (Gmail, Outlook, etc).
    For Gmail: enable App Passwords at https://myaccount.google.com/apppasswords
    """
    try:
        msg = MIMEMultipart()
        msg["To"] = to
        msg["Subject"] = subject
        msg["From"] = from_addr or smtp_user or "eaa@local"
        msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

        if html:
            msg.attach(MIMEText(body, "html"))
        else:
            msg.attach(MIMEText(body, "plain"))

        # Connect and send
        if smtp_user and smtp_password:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
            server.quit()
        else:
            # Try local SMTP (no auth)
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            server.send_message(msg)
            server.quit()

        return ToolResult(True, f"Email sent to {to}\nSubject: {subject}\nVia: {smtp_server}:{smtp_port}")

    except smtplib.SMTPAuthenticationError:
        return ToolResult(False, "", "SMTP authentication failed. Check username/password.\nFor Gmail: use App Password, not regular password.")
    except smtplib.SMTPException as e:
        return ToolResult(False, "", f"SMTP error: {str(e)}")
    except Exception as e:
        return ToolResult(False, "", f"Email send failed: {str(e)}")


# ─── NOTIFY SEND (Desktop Notification) ──────────────────────────────────────
def tool_notify_send(title: str, message: str, duration: int = 5) -> ToolResult:
    """Show a desktop notification (Windows toast)."""
    try:
        # Windows toast notification
        if os.name == "nt":
            try:
                from win10toast import ToastNotifier
                toaster = ToastNotifier()
                toaster.show_toast(title, message, duration=duration, threaded=True)
                return ToolResult(True, f"Desktop notification shown: {title}")
            except ImportError:
                # Fallback: PowerShell notification
                import subprocess
                ps_script = f'''
                [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
                [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] > $null
                $template = @"<toast><visual><binding template="ToastGeneric"><text>{title}</text><text>{message}</text></binding></visual></toast>"@
                $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
                $xml.LoadXml($template)
                $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
                [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("EAA").Show($toast)
                '''
                result = subprocess.run(
                    ["powershell", "-Command", ps_script],
                    capture_output=True, text=True, timeout=10
                )
                return ToolResult(True, f"Notification sent: {title}")
        elif os.name == "posix":
            # Linux desktop notification
            subprocess.run(["notify-send", title, message], timeout=5)
            return ToolResult(True, f"Notification sent: {title}")
        else:
            return ToolResult(False, "", f"Desktop notifications not supported on: {os.name}")

    except Exception as e:
        return ToolResult(False, "", f"Notification failed: {str(e)}")


# ─── SMS SEND ─────────────────────────────────────────────────────────────────
def tool_sms_send(phone: str, message: str, provider: str = None) -> ToolResult:
    """
    Send SMS via email-to-SMS gateway (free, no API key needed).
    Uses carrier email-to-SMS gateways.
    Provider: att, tmobile, verizon, sprint, or custom email gateway
    For production use, integrate with Twilio or similar service.
    """
    gateway_map = {
        "att": f"{phone.replace('-', '')}@mms.att.net",
        "tmobile": f"{phone.replace('-', '')}@tmomail.net",
        "verizon": f"{phone.replace('-', '')}@vzwpix.com",
        "sprint": f"{phone.replace('-', '')}@messaging.sprintpcs.com",
        "google_fi": f"{phone.replace('-', '')}@msg.fi.google.com",
    }

    if provider and provider in gateway_map:
        to_email = gateway_map[provider]
    elif "@" in phone:
        to_email = phone
    elif provider:
        to_email = f"{phone.replace('-', '')}@{provider}"
    else:
        return ToolResult(False, "",
            "Specify a provider: att, tmobile, verizon, sprint, google_fi\n"
            "Or provide full email gateway address (e.g., 1234567890@tmomail.net)\n"
            "Note: This uses free email-to-SMS gateways and may not be reliable."
        )

    try:
        # Send via SMTP (requires configured SMTP)
        msg = MIMEText(message)
        msg["To"] = to_email
        msg["From"] = "eaa@local"
        msg["Subject"] = ""  # SMS gateways often ignore subject

        # Try local SMTP
        try:
            server = smtplib.SMTP("localhost", 25, timeout=10)
            server.send_message(msg)
            server.quit()
            return ToolResult(True, f"SMS sent to {to_email} via local SMTP")
        except Exception:
            return ToolResult(False, "",
                f"SMS gateway address: {to_email}\n"
                "Local SMTP not available. Configure SMTP credentials or use an external SMS API (Twilio, etc)."
            )

    except Exception as e:
        return ToolResult(False, "", f"SMS send failed: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

def register_communication_tools(registry) -> None:
    """Register all communication tools with the existing ToolRegistry."""
    registry.register("email_send", tool_email_send, "Send email via SMTP. Args: to, subject, body, smtp_user, smtp_password, smtp_server")
    registry.register("notify_send", tool_notify_send, "Desktop notification. Args: title, message, duration")
    registry.register("sms_send", tool_sms_send, "Send SMS (free gateway). Args: phone, message, provider (att/tmobile/verizon/sprint)")

__all__ = [
    "register_communication_tools",
    "tool_email_send", "tool_notify_send", "tool_sms_send",
]
