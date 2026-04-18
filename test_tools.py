"""Test all 88 EAA tools"""
import os, sys
os.chdir("C:/Users/offic/EAA")
sys.path.insert(0, "C:/Users/offic/EAA")

from eaa_tool_executor import create_enhanced_registry
r, h, c = create_enhanced_registry()

# Test safe tools that don't need external resources
tests = [
    ("datetime", {}),
    ("calculator", {"expression": "2+2"}),
    ("system_info", {}),
    ("process_list", {}),
    ("json_parse", {"json_string": '{"a": 1, "b": 2}'}),
    ("hash_text", {"text": "hello", "algorithm": "md5"}),
    ("memory_save", {"key": "test_key", "value": "test_value"}),
    ("memory_recall", {"key": "test_key"}),
    ("memory_search", {"query": "test"}),
    ("memory_stats", {}),
    ("memory_list", {}),
    ("memory_clear", {}),
    ("file_exists", {"path": "C:/Users/offic/EAA/eaa_tool_executor.py"}),
    ("list_files", {"path": "C:/Users/offic/EAA", "show_hidden": False}),
    ("env_get", {"name": "COMPUTERNAME"}),
    ("env_set", {"name": "EAA_TEST", "value": "hello"}),
    ("env_get", {"name": "EAA_TEST"}),
    ("clipboard_read", {}),
    ("app_launch", {"app": "notepad"}),
    ("read_file", {"path": "C:/Users/offic/EAA/eaa_tool_executor.py", "limit": 5}),
    ("glob", {"pattern": "eaa_*.py", "path": "C:/Users/offic/EAA"}),
    ("grep", {"pattern": "create_enhanced_registry", "path": "C:/Users/offic/EAA"}),
    ("shell", {"command": "echo hello from shell"}),
    ("python", {"code": "result = [x**2 for x in range(5)]"}),
    ("schedule_list", {}),
    ("schedule_info", {}),
    ("notify_send", {"title": "EAA Test", "message": "Tools are working!"}),
    ("csv_write", {"path": "C:/Users/offic/EAA/test_output.csv", "data": "name,age\nJohn,25\nJane,30"}),
    ("csv_read", {"path": "C:/Users/offic/EAA/test_output.csv"}),
    ("hash_file", {"path": "C:/Users/offic/EAA/eaa_tool_executor.py", "algorithm": "md5"}),
    ("screenshot", {}),
    ("pdf_info", {"path": "C:/Users/offic/EAA/nonexistent.pdf"}),
]

passed = 0
failed = 0
for name, args in tests:
    try:
        result = r.execute(name, **args)
        if result.success:
            passed += 1
            out = str(result.output)[:60].replace("\n", " ")
            print(f"  OK  | {name}: {out}")
        else:
            failed += 1
            err = str(result.error)[:60]
            print(f"  FAIL| {name}: {err}")
    except Exception as e:
        failed += 1
        print(f"  ERR | {name}: {str(e)[:60]}")

# Tool chain test
print("\n--- TOOL CHAIN TEST ---")
chain_results = c.execute_chain([
    {"tool": "calculator", "args": {"expression": "10*10"}},
    {"tool": "datetime", "args": {}},
])
for cr in chain_results:
    status = "OK" if cr["success"] else "FAIL"
    print(f"  Chain step {cr['step']} {status}: {cr.get('output','')[:50]}")

# Stats
stats = h.stats()
print(f"\n--- RESULTS: {passed} passed, {failed} failed ---")
print(f"--- History: {stats['total_executions']} executions ---")
