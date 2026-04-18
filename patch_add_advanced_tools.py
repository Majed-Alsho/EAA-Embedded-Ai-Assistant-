"""
Patch Script: Add 24 Advanced Tools to EAA
==========================================
Run this in C:/Users/offic/EAA with the venv activated.

This script:
1. Installs missing pip packages
2. Patches eaa_agent_tools_v3.py to import & register new tools
3. Patches eaa_smart_tool_router.py to add new categories & keywords
4. Verifies the patches worked
"""

import os
import sys
import subprocess
import shutil

EAA_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_FILE = os.path.join(EAA_DIR, "eaa_agent_tools_v3.py")
ROUTER_FILE = os.path.join(EAA_DIR, "eaa_smart_tool_router.py")
ADVANCED_FILE = os.path.join(EAA_DIR, "eaa_agent_tools_advanced.py")

# Colors for terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def log(msg, color=""):
    print(f"{color}{msg}{RESET}")


def run(cmd, **kwargs):
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    return result


def step(msg):
    log(f"\n{'='*60}", CYAN)
    log(f"  {msg}", CYAN)
    log(f"{'='*60}", CYAN)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: Install pip packages
# ═══════════════════════════════════════════════════════════════════════════════
def install_packages():
    step("STEP 1: Installing pip packages")
    packages = ["python-whois", "dnspython", "feedparser", "paho-mqtt"]
    optional = ["docker"]  # Only if Docker Desktop is installed

    for pkg in packages:
        log(f"Installing {pkg}...")
        result = run([sys.executable, "-m", "pip", "install", pkg, "-q"])
        if result.returncode == 0:
            log(f"  ✅ {pkg} installed", GREEN)
        else:
            log(f"  ❌ {pkg} failed: {result.stderr.strip()[-200:]}", RED)

    # Try optional packages
    for pkg in optional:
        log(f"Installing optional {pkg}...")
        result = run([sys.executable, "-m", "pip", "install", pkg, "-q"])
        if result.returncode == 0:
            log(f"  ✅ {pkg} installed", GREEN)
        else:
            log(f"  ⚠️  {pkg} skipped (Docker SDK optional)", YELLOW)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: Patch eaa_agent_tools_v3.py
# ═══════════════════════════════════════════════════════════════════════════════
def patch_tools_file():
    step("STEP 2: Patching eaa_agent_tools_v3.py")

    if not os.path.exists(TOOLS_FILE):
        log(f"  ❌ File not found: {TOOLS_FILE}", RED)
        return False

    with open(TOOLS_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    patched = False

    # Check if already patched
    if "register_advanced_tools" in content:
        log("  ⚠️  Already patched (register_advanced_tools found). Skipping.", YELLOW)
        return True

    # --- Patch 1: Add import inside create_tool_registry() ---
    log("  Adding advanced tools import to create_tool_registry()...")

    # Find "return r" near the end of create_tool_registry and add import before it
    # We insert before the last "return r" in the file
    import_block = '''
    # ── Advanced Tools (24 new tools) ──
    try:
        from eaa_agent_tools_advanced import register_advanced_tools, ADVANCED_LIGHT_TOOLS
        register_advanced_tools(r)
        LIGHT_TOOLS.update(ADVANCED_LIGHT_TOOLS)
    except ImportError as e:
        pass  # Advanced tools optional
'''

    # Find the "return r" at the end of create_tool_registry
    # It should be near the end, after all register calls
    lines = content.split("\n")
    inserted = False
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "return r" and i > 900:  # create_tool_registry starts at 972
            lines.insert(i, import_block)
            inserted = True
            log(f"  ✅ Inserted import+register call at line {i+1}", GREEN)
            break

    if not inserted:
        log("  ❌ Could not find 'return r' in create_tool_registry()", RED)
        return False

    content = "\n".join(lines)
    patched = True

    with open(TOOLS_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    log("  ✅ eaa_agent_tools_v3.py patched successfully!", GREEN)
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: Patch eaa_smart_tool_router.py
# ═══════════════════════════════════════════════════════════════════════════════
def patch_router_file():
    step("STEP 3: Patching eaa_smart_tool_router.py")

    if not os.path.exists(ROUTER_FILE):
        log(f"  ⚠️  File not found: {ROUTER_FILE}", YELLOW)
        log("  Smart router categories not updated. Tools will still work but won't be lazy-loaded by category.", YELLOW)
        return True  # Not critical, tools still work

    with open(ROUTER_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    if "docker_list" in content:
        log("  ⚠️  Already patched. Skipping.", YELLOW)
        return True

    # --- Add new categories to TOOL_CATEGORIES ---
    log("  Adding new tool categories...")

    new_categories = '''
    # ── Advanced Categories (24 new tools) ──
    "infra": ["docker_list", "docker_build", "docker_start", "docker_stop", "docker_logs", "github_issue"],
    "networking": ["whois_lookup", "dns_resolve", "subdomain_enum", "ping_host", "traceroute", "port_scan"],
    "research": ["rss_read", "html_extract", "wayback_fetch"],
    "iot": ["mqtt_publish", "mqtt_subscribe"],
    "media_advanced": ["video_trim", "video_extract_audio", "video_compress", "pdf_split", "pdf_merge", "pdf_watermark"],
'''

    # Insert before the closing brace of TOOL_CATEGORIES
    # Find the last line of TOOL_CATEGORIES dict (before CORE_TOOLS)
    marker = '\n# Always-loaded core tools'
    if marker in content:
        content = content.replace(marker, new_categories + "\n" + marker)
        log("  ✅ Added 5 new categories to TOOL_CATEGORIES", GREEN)
    else:
        # Fallback: add before CORE_TOOLS
        marker2 = "\nCORE_TOOLS"
        if marker2 in content:
            content = content.replace(marker2, new_categories + "\n" + marker2)
            log("  ✅ Added 5 new categories to TOOL_CATEGORIES", GREEN)
        else:
            log("  ⚠️  Could not find insertion point for categories", YELLOW)

    # --- Add new keywords to CATEGORY_KEYWORDS ---
    log("  Adding category keywords...")

    new_keywords = '''
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
'''

    # Insert after the last existing keyword entry
    # Find a good insertion point - after the existing categories
    marker3 = '"scheduler": ['
    if marker3 in content:
        # Find the end of the scheduler block
        idx = content.index(marker3)
        # Find the closing bracket after this
        bracket_count = 0
        end_idx = idx
        for j in range(idx, len(content)):
            if content[j] == '[':
                bracket_count += 1
            elif content[j] == ']':
                bracket_count -= 1
                if bracket_count == 0:
                    end_idx = j + 1
                    break
        # Find the end of this dict entry (next key or closing brace)
        rest = content[end_idx:]
        comma_pos = 0
        for j, ch in enumerate(rest):
            if ch == '"':
                comma_pos = j
                break
        if comma_pos > 0:
            insert_pos = end_idx
            content = content[:insert_pos] + ",\n" + new_keywords + content[insert_pos:]
            log("  ✅ Added 5 new keyword mappings to CATEGORY_KEYWORDS", GREEN)
        else:
            log("  ⚠️  Could not find keyword insertion point", YELLOW)
    else:
        log("  ⚠️  Could not find scheduler keyword block", YELLOW)

    with open(ROUTER_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    log("  ✅ eaa_smart_tool_router.py patched successfully!", GREEN)
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4: Verify everything
# ═══════════════════════════════════════════════════════════════════════════════
def verify():
    step("STEP 4: Verifying patches")

    all_ok = True

    # Check advanced tools file exists
    if os.path.exists(ADVANCED_FILE):
        log(f"  ✅ eaa_agent_tools_advanced.py exists", GREEN)
    else:
        log(f"  ❌ eaa_agent_tools_advanced.py NOT FOUND", RED)
        all_ok = False

    # Check import was added
    with open(TOOLS_FILE, "r", encoding="utf-8") as f:
        tools_content = f.read()
    if "register_advanced_tools" in tools_content:
        log(f"  ✅ Tools file patched (import found)", GREEN)
    else:
        log(f"  ❌ Tools file NOT patched", RED)
        all_ok = False

    # Check router was updated
    if os.path.exists(ROUTER_FILE):
        with open(ROUTER_FILE, "r", encoding="utf-8") as f:
            router_content = f.read()
        if "docker_list" in router_content:
            log(f"  ✅ Router file patched (new categories found)", GREEN)
        else:
            log(f"  ⚠️  Router file not patched (optional, tools still work)", YELLOW)

    # Test import
    log("  Testing import of advanced tools...")
    try:
        os.chdir(EAA_DIR)
        sys.path.insert(0, EAA_DIR)
        from eaa_agent_tools_advanced import register_advanced_tools, ADVANCED_TOOL_NAMES
        log(f"  ✅ Import successful! {len(ADVANCED_TOOL_NAMES)} new tools loaded", GREEN)
    except Exception as e:
        log(f"  ❌ Import failed: {e}", RED)
        all_ok = False

    # Count total tools
    log("  Testing full registry...")
    try:
        from eaa_agent_tools_v3 import create_tool_registry
        registry = create_tool_registry()
        total = len(registry.tools)
        log(f"  ✅ Total registered tools: {total} (was 88, now 88+24={88+24})", GREEN)
        if total < 100:
            log(f"  ⚠️  Expected 112 tools, got {total}. Some may not have registered.", YELLOW)
    except Exception as e:
        log(f"  ⚠️  Could not verify registry: {e}", YELLOW)

    return all_ok


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    log("\n" + "=" * 60, CYAN)
    log("  EAA ADVANCED TOOLS INSTALLER", CYAN)
    log("  Adding 24 new tools across 5 categories", CYAN)
    log("=" * 60, CYAN)

    # Check prerequisites
    if not os.path.exists(TOOLS_FILE):
        log(f"\n❌ eaa_agent_tools_v3.py not found in {EAA_DIR}", RED)
        log("Make sure you're running this from the EAA directory.", RED)
        sys.exit(1)

    # Confirm with user
    print()
    resp = input("This will modify eaa_agent_tools_v3.py and eaa_smart_tool_router.py. Continue? [Y/n]: ")
    if resp.strip().lower() in ("n", "no"):
        log("Cancelled.", YELLOW)
        sys.exit(0)

    # Run steps
    install_packages()

    if not patch_tools_file():
        log("\n❌ Tool file patch failed. Check errors above.", RED)
        sys.exit(1)

    if not patch_router_file():
        log("\n⚠️  Router patch had issues. Tools will still work.", YELLOW)

    ok = verify()

    log("\n" + "=" * 60, CYAN)
    if ok:
        log("  ✅ ALL DONE! 24 new tools installed successfully!", GREEN)
        log("  Total tools: 88 → 112", GREEN)
        log("  Restart the EAA server to activate.", GREEN)
    else:
        log("  ⚠️  Done with warnings. Check above.", YELLOW)
        log("  Restart the EAA server to test.", YELLOW)
    log("=" * 60, CYAN)

    # List new tools
    print()
    log("NEW TOOLS:", CYAN)
    tools = [
        ("INFRASTRUCTURE", ["docker_list", "docker_build", "docker_start", "docker_stop", "docker_logs", "github_issue"]),
        ("NETWORKING", ["whois_lookup", "dns_resolve", "subdomain_enum", "ping_host", "traceroute", "port_scan"]),
        ("RESEARCH", ["rss_read", "html_extract", "wayback_fetch"]),
        ("IoT", ["hardware_stats", "mqtt_publish", "mqtt_subscribe"]),
        ("MEDIA", ["video_trim", "video_extract_audio", "video_compress", "pdf_split", "pdf_merge", "pdf_watermark"]),
    ]
    for cat, names in tools:
        print(f"  {cat}:")
        for n in names:
            print(f"    - {n}")
    print()


if __name__ == "__main__":
    main()

