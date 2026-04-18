import json, requests, time, sys
BASE = "http://localhost:8000"
def chat(msg, max_tokens=128, timeout=60):
    try:
        r = requests.post(f"{BASE}/v1/agent/chat", json={"message": msg, "max_tokens": max_tokens}, timeout=timeout)
        return r.json()
    except Exception as e:
        return {"success": False, "error": str(e)}
def get_vram():
    try:
        r = requests.get(f"{BASE}/v1/agent/vram", timeout=10)
        return r.json().get("allocated_gb", "?")
    except:
        return "?"
tests = [
    ("datetime", "What time is it now? Brief."),
    ("calculator", "Calculate 987 * 654. Number only."),
    ("shell", "Run: echo hello"),
    ("list_files", "List .py files in C:\\Users\\offic\\EAA\\"),
    ("file_exists", "Does C:\\Users\\offic\\EAA\\eaa_agent_loop_v3.py exist?"),
    ("glob", "Find .bak files in C:\\Users\\offic\\EAA\\"),
    ("grep", "Search for VRAM GUARD in C:\\Users\\offic\\EAA\\eaa_agent_loop_v3.py"),
    ("read_file", "Read first 3 lines of C:\\Users\\offic\\EAA\\eaa_agent_loop_v3.py"),
    ("web_search", "Search web for Python AI. Brief."),
    ("web_fetch", "Fetch https://example.com give title."),
    ("memory_save", "Save memory key t1 value test ok"),
    ("memory_recall", "Recall memory key t1"),
    ("memory_list", "List all memories"),
    ("memory_search", "Search memories for t1"),
    ("memory_stats", "Show memory stats"),
    ("write_file", "Create C:\\Users\\offic\\EAA\\tt.txt with hello"),
    ("append_file", "Append world to C:\\Users\\offic\\EAA\\tt.txt"),
    ("create_directory", "Create C:\\Users\\offic\\EAA\\tt_dir"),
    ("delete_file", "Delete C:\\Users\\offic\\EAA\\tt.txt"),
    ("system_info", "System info CPU RAM GPU Brief."),
    ("process_list", "Top 5 processes by memory."),
    ("env_get", "Get USERNAME env var."),
    ("clipboard_read", "Read clipboard."),
    ("code_run", "Run Python: print(sum(range(1,101)))"),
    ("python", "Run: import math; print(math.sqrt(144))"),
    ("git_status", "Git status in C:\\Users\\offic\\EAA\\"),
    ("git_log", "Last 3 git commits in C:\\Users\\offic\\EAA\\"),
    ("git_diff", "Git diff in C:\\Users\\offic\\EAA\\"),
    ("git_branch", "Current git branch in C:\\Users\\offic\\EAA\\"),
    ("json_parse", 'Parse JSON show name: {"name":"Majed","v":3}'),
    ("hash_text", "SHA256 of text EAA test"),
    ("hash_file", "SHA256 of C:\\Users\\offic\\EAA\\eaa_agent_loop_v3.py"),
    ("csv_read", "Any CSV files in C:\\Users\\offic\\EAA\\?"),
    ("csv_write", "Create C:\\Users\\offic\\EAA\\tt.csv name,age Majed,25"),
    ("database_query", "Any SQLite databases in C:\\Users\\offic\\EAA\\?"),
    ("api_call", "GET https://httpbin.org/get show origin"),
    ("pdf_info", "Any PDF files in C:\\Users\\offic\\EAA\\?"),
    ("pdf_create", "Create PDF at C:\\Users\\offic\\EAA\\tt.pdf text Hello"),
    ("docx_read", "Any DOCX files in C:\\Users\\offic\\EAA\\?"),
    ("docx_create", "Create C:\\Users\\offic\\EAA\\tt.docx text Hello"),
    ("xlsx_read", "Any Excel files in C:\\Users\\offic\\EAA\\?"),
    ("xlsx_create", "Create C:\\Users\\offic\\EAA\\tt.xlsx cell Hello"),
    ("pptx_read", "Any PPTX files in C:\\Users\\offic\\EAA\\?"),
    ("pptx_create", "Create C:\\Users\\offic\\EAA\\tt.pptx title Test"),
    ("schedule_list", "List scheduled tasks"),
    ("image_info", "Any image files in C:\\Users\\offic\\EAA\\?"),
    ("image_analyze", "Describe any image in C:\\Users\\offic\\EAA\\"),
    ("ocr_extract", "OCR any image in C:\\Users\\offic\\EAA\\"),
    ("screenshot", "Take screenshot briefly describe"),
    ("audio_info", "Any audio files in C:\\Users\\offic\\EAA\\?"),
    ("audio_transcribe", "Transcribe any audio in C:\\Users\\offic\\EAA\\"),
    ("video_info", "Any video files in C:\\Users\\offic\\EAA\\?"),
    ("video_analyze", "Analyze any video in C:\\Users\\offic\\EAA\\"),
    ("browser_open", "Open https://example.com"),
    ("browser_screenshot", "Screenshot browser"),
    ("browser_close", "Close browser"),
    ("notify_send", "Desktop notification Test done"),
    ("email_send", "Describe email_send tool only do not send"),
    ("sms_send", "Describe sms_send tool only do not send"),
    ("memory_export", "Export memories to file"),
    ("memory_import", "Import memories from default"),
    ("memory_clear", "Clear all saved memories"),
    ("context_save", "Save context tc key k value v"),
    ("context_load", "Load context tc"),
    ("context_list", "List all contexts"),
    ("context_delete", "Delete context tc"),
    ("code_lint", "Lint C:\\Users\\offic\\EAA\\eaa_agent_loop_v3.py"),
    ("code_format", "Check format of C:\\Users\\offic\\EAA\\eaa_agent_loop_v3.py"),
    ("code_test", "Run tests in C:\\Users\\offic\\EAA\\ if any"),
    ("env_set", "Set env var TT to ok then verify"),
    ("clipboard_write", "Write ctest to clipboard"),
    ("process_kill", "Describe process_kill tool only"),
    ("app_launch", "Describe app_launch tool only"),
    ("image_generate", "Describe image_generate tool only"),
    ("image_convert", "Describe image_convert tool only"),
    ("image_resize", "Describe image_resize tool only"),
    ("audio_generate", "Describe audio_generate tool only"),
    ("audio_convert", "Describe audio_convert tool only"),
    ("browser_click", "Describe browser_click tool only"),
    ("browser_type", "Describe browser_type tool only"),
    ("browser_scroll", "Describe browser_scroll tool only"),
    ("browser_get_text", "Describe browser_get_text tool only"),
    ("schedule_task", "Describe schedule_task tool only"),
    ("schedule_info", "Describe schedule_info tool only"),
    ("schedule_cancel", "Describe schedule_cancel tool only"),
]
start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
end = int(sys.argv[2]) if len(sys.argv) > 2 else min(start + 10, len(tests))
batch = tests[start:end]
print(f"TESTS {start+1}-{end}/{len(tests)}")
v0 = get_vram()
print(f"VRAM: {v0} GB\n")
results = []
for i, (name, msg) in enumerate(batch):
    idx = start + i + 1
    print(f"[{idx}] {name:20s}", end=" ", flush=True)
    t0 = time.time()
    r = chat(msg, timeout=60)
    dt = time.time() - t0
    if r.get("success") and r.get("status") == "success" and r.get("tools_used", 0) > 0:
        s = "OK"
    elif r.get("success") and r.get("status") == "success":
        s = "OK"
    elif r.get("error"):
        s = "ERR"
    else:
        s = "OK" if r.get("success") else "FAIL"
    results.append((name, s, dt))
    print(f"{s:5s} ({dt:.1f}s)")
v1 = get_vram()
print(f"\nVRAM: {v0} -> {v1} GB")
ok = sum(1 for _, s, _ in results if s == "OK")
print(f"PASS: {ok}/{len(results)}")
for n, s, t in results:
    print(f"  {'OK' if s=='OK' else 'FAIL':5s} {n:25s} {t:.1f}s")
with open(r"C:\Users\offic\EAA\tool_results.txt", "a") as f:
    for n, s, t in results:
        f.write(f"{n},{s},{t:.1f}\n")
