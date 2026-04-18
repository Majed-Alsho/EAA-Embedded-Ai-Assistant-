"""
EAA Browser Tools - Phase 5
Browser automation using Playwright.
All tools use the existing ToolResult pattern from eaa_agent_tools.py.
"""

import os
import json
import asyncio
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

# Global browser state
_browser_page = None
_browser_context = None
_browser_playwright = None


def _get_event_loop():
    """Get or create an event loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


# ─── BROWSER OPEN ─────────────────────────────────────────────────────────────
def tool_browser_open(url: str, headless: bool = True, wait_ms: int = 3000) -> ToolResult:
    """Open a URL in the browser."""
    global _browser_page, _browser_context, _browser_playwright

    try:
        loop = _get_event_loop()

        async def _open():
            global _browser_page, _browser_context, _browser_playwright
            from playwright.async_api import async_playwright

            # Close existing if any
            if _browser_page:
                try:
                    await _browser_page.close()
                except Exception:
                    pass

            _browser_playwright = await async_playwright().start()
            _browser_context = await _browser_playwright.chromium.launch(
                headless=headless
            )
            page = await _browser_context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(wait_ms)

            title = await page.title()
            current_url = page.url
            content = await page.content()
            text_len = len(await page.inner_text("body"))

            _browser_page = page

            return {
                "title": title,
                "url": current_url,
                "text_length": text_len,
                "status": "success"
            }

        result = loop.run_until_complete(_open())
        return ToolResult(True, f"Opened: {result['title']}\nURL: {result['url']}\nText length: {result['text_length']} chars")

    except Exception as e:
        return ToolResult(False, "", f"Browser open failed: {str(e)}")


# ─── BROWSER CLICK ────────────────────────────────────────────────────────────
def tool_browser_click(selector: str) -> ToolResult:
    """Click an element on the current page using CSS selector."""
    global _browser_page

    try:
        if not _browser_page:
            return ToolResult(False, "", "No browser page open. Use browser_open first.")

        loop = _get_event_loop()

        async def _click():
            element = await _browser_page.query_selector(selector)
            if not element:
                return f"Element not found: {selector}"
            await element.click()
            await _browser_page.wait_for_timeout(500)
            title = await _browser_page.title()
            return f"Clicked: {selector}\nCurrent page: {title}"

        result = loop.run_until_complete(_click())
        return ToolResult(True, result)

    except Exception as e:
        return ToolResult(False, "", f"Browser click failed: {str(e)}")


# ─── BROWSER TYPE ─────────────────────────────────────────────────────────────
def tool_browser_type(selector: str, text: str, press_enter: bool = False) -> ToolResult:
    """Type text into an input field."""
    global _browser_page

    try:
        if not _browser_page:
            return ToolResult(False, "", "No browser page open. Use browser_open first.")

        loop = _get_event_loop()

        async def _type():
            element = await _browser_page.query_selector(selector)
            if not element:
                return f"Element not found: {selector}"
            await element.fill(text)
            if press_enter:
                await element.press("Enter")
                await _browser_page.wait_for_timeout(500)
            return f"Typed into {selector}: '{text[:50]}{'...' if len(text) > 50 else ''}'"

        result = loop.run_until_complete(_type())
        return ToolResult(True, result)

    except Exception as e:
        return ToolResult(False, "", f"Browser type failed: {str(e)}")


# ─── BROWSER SCREENSHOT ───────────────────────────────────────────────────────
def tool_browser_screenshot(output_path: str = None, full_page: bool = False) -> ToolResult:
    """Take a screenshot of the current browser page."""
    global _browser_page

    try:
        if not _browser_page:
            return ToolResult(False, "", "No browser page open. Use browser_open first.")

        if output_path is None:
            output_dir = os.path.join(os.path.dirname(__file__), "..", "outputs", "browser")
            os.makedirs(output_dir, exist_ok=True)
            filename = f"browser_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            output_path = os.path.join(output_dir, filename)
        else:
            output_path = os.path.expanduser(output_path)
            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

        loop = _get_event_loop()

        async def _screenshot():
            await _browser_page.screenshot(path=output_path, full_page=full_page)

        loop.run_until_complete(_screenshot())
        size = os.path.getsize(output_path)
        return ToolResult(True, f"Browser screenshot: {output_path} ({size:,} bytes)")

    except Exception as e:
        return ToolResult(False, "", f"Browser screenshot failed: {str(e)}")


# ─── BROWSER SCROLL ───────────────────────────────────────────────────────────
def tool_browser_scroll(direction: str = "down", amount: int = 500) -> ToolResult:
    """Scroll the current browser page."""
    global _browser_page

    try:
        if not _browser_page:
            return ToolResult(False, "", "No browser page open. Use browser_open first.")

        loop = _get_event_loop()

        async def _scroll():
            if direction == "down":
                await _browser_page.evaluate(f"window.scrollBy(0, {amount})")
            elif direction == "up":
                await _browser_page.evaluate(f"window.scrollBy(0, -{amount})")
            elif direction == "top":
                await _browser_page.evaluate("window.scrollTo(0, 0)")
            elif direction == "bottom":
                await _browser_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await _browser_page.wait_for_timeout(300)
            scroll_pos = await _browser_page.evaluate("window.scrollY")
            return f"Scrolled {direction} by {amount}px. Current position: {scroll_pos}"

        result = loop.run_until_complete(_scroll())
        return ToolResult(True, result)

    except Exception as e:
        return ToolResult(False, "", f"Browser scroll failed: {str(e)}")


# ─── BROWSER GET TEXT ─────────────────────────────────────────────────────────
def tool_browser_get_text(selector: str = "body") -> ToolResult:
    """Get text content from the current page or a specific element."""
    global _browser_page

    try:
        if not _browser_page:
            return ToolResult(False, "", "No browser page open. Use browser_open first.")

        loop = _get_event_loop()

        async def _get_text():
            text = await _browser_page.inner_text(selector)
            return text[:10000]

        result = loop.run_until_complete(_get_text())
        return ToolResult(True, f"Page text ({len(result)} chars):\n{result}")

    except Exception as e:
        return ToolResult(False, "", f"Get text failed: {str(e)}")


# ─── BROWSER CLOSE ────────────────────────────────────────────────────────────
def tool_browser_close() -> ToolResult:
    """Close the browser."""
    global _browser_page, _browser_context, _browser_playwright

    try:
        loop = _get_event_loop()

        async def _close():
            global _browser_page, _browser_context, _browser_playwright
            if _browser_page:
                await _browser_page.close()
            if _browser_context:
                await _browser_context.close()
            if _browser_playwright:
                await _browser_playwright.stop()
            _browser_page = None
            _browser_context = None
            _browser_playwright = None

        loop.run_until_complete(_close())
        return ToolResult(True, "Browser closed")

    except Exception as e:
        return ToolResult(False, "", f"Browser close failed: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

def register_browser_tools(registry) -> None:
    """Register all browser tools with the existing ToolRegistry."""
    registry.register("browser_open", tool_browser_open, "Open URL in browser. Args: url, headless (default True)")
    registry.register("browser_click", tool_browser_click, "Click element. Args: selector (CSS selector)")
    registry.register("browser_type", tool_browser_type, "Type into field. Args: selector, text, press_enter")
    registry.register("browser_screenshot", tool_browser_screenshot, "Screenshot page. Args: output_path, full_page")
    registry.register("browser_scroll", tool_browser_scroll, "Scroll page. Args: direction (up/down/top/bottom), amount (pixels)")
    registry.register("browser_get_text", tool_browser_get_text, "Get page text. Args: selector (default 'body')")
    registry.register("browser_close", tool_browser_close, "Close browser. Args: none")

__all__ = [
    "register_browser_tools",
    "tool_browser_open", "tool_browser_click", "tool_browser_type",
    "tool_browser_screenshot", "tool_browser_scroll", "tool_browser_get_text",
    "tool_browser_close",
]
