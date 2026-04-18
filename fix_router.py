"""
Fix script: Repair eaa_smart_tool_router.py
============================================
Run this after the bad patch corrupted the file.
"""
import os, re

ROUTER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eaa_smart_tool_router.py")

with open(ROUTER_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# ── Fix 1: Rebuild TOOL_CATEGORIES with correct data ──
GOOD_TOOL_CATEGORIES = '''TOOL_CATEGORIES = {
    "file": ["read_file", "write_file", "append_file", "list_files", "file_exists", "create_directory", "delete_file", "glob", "grep"],
    "web": ["web_search", "web_fetch"],
    "memory": ["memory_save", "memory_recall", "memory_list", "memory_search", "memory_clear", "memory_export", "memory_import", "memory_stats"],
    "code": ["code_run", "code_lint", "code_format", "code_test", "python", "git_status", "git_commit", "git_diff", "git_log", "git_branch"],
    "document": ["pdf_read", "pdf_info", "pdf_create", "docx_read", "docx_create", "xlsx_read", "xlsx_create", "pptx_read", "pptx_create"],
    "system": ["shell", "screenshot", "clipboard_read", "clipboard_write", "process_list", "process_kill", "system_info", "app_launch", "env_get", "env_set", "datetime", "calculator"],
    "multimodal": ["image_analyze", "image_describe", "ocr_extract", "image_generate", "image_info", "image_convert", "image_resize"],
    "browser": ["browser_open", "browser_click", "browser_type", "browser_screenshot", "browser_scroll", "browser_get_text", "browser_close"],
    "communication": ["email_send", "notify_send", "sms_send"],
    "data": ["json_parse", "csv_read", "csv_write", "database_query", "api_call", "hash_text", "hash_file"],
    "audio_video": ["audio_transcribe", "audio_generate", "audio_info", "audio_convert", "video_analyze", "video_info"],
    "scheduler": ["schedule_task", "schedule_list", "schedule_cancel", "schedule_info"],
    "context": ["context_save", "context_load", "context_list", "context_delete"],
    # ── Advanced Categories (24 new tools) ──
    "infra": ["docker_list", "docker_build", "docker_start", "docker_stop", "docker_logs", "github_issue"],
    "networking": ["whois_lookup", "dns_resolve", "subdomain_enum", "ping_host", "traceroute", "port_scan"],
    "research": ["rss_read", "html_extract", "wayback_fetch"],
    "iot": ["mqtt_publish", "mqtt_subscribe"],
    "media_advanced": ["video_trim", "video_extract_audio", "video_compress", "pdf_split", "pdf_merge", "pdf_watermark"],
}'''

# Find the old TOOL_CATEGORIES block and replace everything up to its closing }
# Match from "TOOL_CATEGORIES = {" to the first "}" that ends the dict (before CORE_TOOLS)
pattern = r'TOOL_CATEGORIES\s*=\s*\{.*?\n\}\s*\n'
match = re.search(pattern, content, re.DOTALL)
if match:
    # Also remove the floating categories that ended up outside
    end_pos = match.end()
    # Check if there are floating category lines after the closing brace
    rest = content[end_pos:]
    floating_pattern = r'\s*#\s*── Advanced Categories.*?(?=\n# Always-loaded|\nCORE_TOOLS|\n# ═)'
    floating_match = re.match(floating_pattern, rest, re.DOTALL)
    if floating_match:
        end_pos += floating_match.end()
    content = content[:match.start()] + GOOD_TOOL_CATEGORIES + "\n\n" + content[end_pos:]
    print("OK: Rebuilt TOOL_CATEGORIES")
else:
    print("WARN: Could not find TOOL_CATEGORIES block")

# ── Fix 2: Add new keywords to CATEGORY_KEYWORDS ──
NEW_KEYWORDS = '''    "context": [
        "context", "session", "state", "save context", "load context",
        "switch context", "workspace",
    ],
    # ── Advanced Category Keywords ──
    "infra": [
        "docker", "container", "image build", "github", "pull request",
        "issue", "repository", "deploy", "ci/cd", "pipeline",
    ],
    "networking": [
        "whois", "dns", "domain", "subdomain", "ping", "traceroute",
        "port scan", "network", "ip address", "dns lookup", "nslookup",
        "recon", "enum", "enumerate",
    ],
    "research": [
        "rss", "feed", "atom", "blog", "news feed", "subscribe",
        "xpath", "css selector", "scrape", "extract html", "parse html",
        "wayback", "archive", "historical", "snapshot",
    ],
    "iot": [
        "mqtt", "broker", "publish", "subscribe topic", "iot",
        "smart home", "sensor", "home assistant", "message queue",
    ],
    "media_advanced": [
        "trim video", "cut video", "extract audio", "video to audio",
        "compress video", "reduce video size", "split pdf", "merge pdf",
        "combine pdf", "watermark", "stamp", "ffmpeg",
    ],
}'''

# Find the closing of CATEGORY_KEYWORDS (the "context" block followed by })
ctx_pattern = r'("context":\s*\[[^\]]*\][^\n]*\n)\}'
ctx_match = re.search(ctx_pattern, content)
if ctx_match:
    content = content[:ctx_match.start()] + NEW_KEYWORDS + "\n\n" + content[ctx_match.end():]
    print("OK: Added new keyword mappings")
else:
    print("WARN: Could not find CATEGORY_KEYWORDS closing")

with open(ROUTER_FILE, "w", encoding="utf-8") as f:
    f.write(content)

# Verify
try:
    compile(content, ROUTER_FILE, "exec")
    print("\nOK: File compiles successfully!")
except SyntaxError as e:
    print(f"\nERROR: Syntax error at line {e.lineno}: {e.msg}")
    print("Restoring backup...")
    os.replace(ROUTER_FILE + ".bak", ROUTER_FILE)
    print("Restored from backup.")
    exit(1)
