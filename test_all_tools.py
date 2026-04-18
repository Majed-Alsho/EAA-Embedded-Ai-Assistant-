import sys, os, traceback, json, time
os.chdir(r'C:\Users\offic\EAA')
sys.path.insert(0, r'C:\Users\offic\EAA')

from eaa_tool_executor import create_enhanced_registry

registry, history, chain_executor = create_enhanced_registry()
all_tools = sorted(registry.list_tools())
print(f'Total tools registered: {len(all_tools)}')
print()

TESTS = {
    'read_file': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'write_file': {'path': r'C:\Users\offic\EAA\_test_write.txt', 'content': 'hello world'},
    'append_file': {'path': r'C:\Users\offic\EAA\_test_write.txt', 'content': ' appended'},
    'list_files': {'path': r'C:\Users\offic\EAA'},
    'file_exists': {'path': r'C:\Users\offic\EAA\eaa_tool_executor.py'},
    'create_directory': {'path': r'C:\Users\offic\EAA\_test_dir'},
    'delete_file': {'path': r'C:\Users\offic\EAA\_test_write.txt'},
    'glob': {'pattern': '*.py', 'path': r'C:\Users\offic\EAA'},
    'grep': {'pattern': 'import', 'path': r'C:\Users\offic\EAA\eaa_tool_executor.py'},
    'shell': {'command': 'echo test123'},
    'memory_save': {'key': '_test_key', 'value': 'test_value'},
    'memory_recall': {'key': '_test_key'},
    'memory_list': {},
    'memory_search': {'query': 'test'},
    'memory_clear': {},
    'memory_stats': {},
    'datetime': {},
    'calculator': {'expression': '2+2'},
    'python': {'code': 'print(42)'},
    'system_info': {},
    'process_list': {},
    'env_get': {'name': 'PATH'},
    'env_set': {'name': '_TEST_VAR', 'value': 'test123'},
    'clipboard_read': {},
    'clipboard_write': {'text': '_clipboard_test'},
    'screenshot': {},
    'image_info': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'image_analyze': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'ocr_extract': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'pdf_info': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'pdf_read': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'pdf_create': {'pages': [{'text': 'test page'}], 'output_path': r'C:\Users\offic\EAA\_test.pdf'},
    'docx_read': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'docx_create': {'content': 'test', 'output_path': r'C:\Users\offic\EAA\_test.docx'},
    'xlsx_read': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'xlsx_create': {'data': [[1,2],[3,4]], 'output_path': r'C:\Users\offic\EAA\_test.xlsx'},
    'pptx_read': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'pptx_create': {'slides': [{'text': 'test'}], 'output_path': r'C:\Users\offic\EAA\_test.pptx'},
    'code_run': {'code': 'print(42)', 'language': 'python'},
    'code_lint': {'code': 'print(42)', 'language': 'python'},
    'code_format': {'code': 'x=1+2', 'language': 'python'},
    'code_test': {'code': 'def test_add(): assert 1+1==2', 'language': 'python'},
    'git_status': {'path': r'C:\Users\offic\EAA'},
    'git_log': {'path': r'C:\Users\offic\EAA'},
    'git_diff': {'path': r'C:\Users\offic\EAA'},
    'git_branch': {'path': r'C:\Users\offic\EAA'},
    'git_commit': {'path': r'C:\Users\offic\EAA', 'message': 'test'},
    'browser_open': {'url': 'about:blank'},
    'browser_screenshot': {},
    'browser_get_text': {},
    'browser_click': {'selector': 'body'},
    'browser_type': {'selector': 'body', 'text': 'test'},
    'browser_scroll': {'direction': 'down'},
    'browser_close': {},
    'notify_send': {'title': 'EAA Test', 'message': 'Tool test running'},
    'email_send': {'to': 'test@test.com', 'subject': 'test', 'body': 'test'},
    'json_parse': {'json_string': '{"a":1}'},
    'csv_read': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'csv_write': {'data': [[1,2],[3,4]], 'output_path': r'C:\Users\offic\EAA\_test.csv'},
    'api_call': {'url': 'https://httpbin.org/get', 'method': 'GET'},
    'hash_text': {'text': 'hello'},
    'hash_file': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'database_query': {'query': 'SELECT 1+1'},
    'audio_info': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'audio_transcribe': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'audio_generate': {'text': 'hello', 'output_path': r'C:\Users\offic\EAA\_test_audio.wav'},
    'audio_convert': {'input_path': r'C:\Users\offic\EAA\test_all_tools.py', 'output_path': r'C:\Users\offic\EAA\_test_conv.wav'},
    'video_analyze': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'video_info': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'schedule_list': {},
    'schedule_info': {'task_id': '_test'},
    'schedule_task': {'task_id': '_test', 'command': 'echo hi', 'schedule': 'daily'},
    'schedule_cancel': {'task_id': '_test'},
    'context_save': {'name': '_test_ctx', 'data': {'key': 'val'}},
    'context_load': {'name': '_test_ctx'},
    'context_list': {},
    'context_delete': {'name': '_test_ctx'},
    'memory_export': {'path': r'C:\Users\offic\EAA\_test_mem.json'},
    'memory_import': {'path': r'C:\Users\offic\EAA\_test_mem.json'},
    'image_convert': {'path': r'C:\Users\offic\EAA\test_all_tools.py', 'format': 'png'},
    'image_resize': {'path': r'C:\Users\offic\EAA\test_all_tools.py', 'width': 100},
    'image_generate': {'prompt': 'test', 'output_path': r'C:\Users\offic\EAA\_test_img.png'},
    'image_describe': {'path': r'C:\Users\offic\EAA\test_all_tools.py'},
    'process_kill': {'pid': 999999},
    'app_launch': {'app': 'notepad.exe'},
    'web_search': {'query': 'test'},
    'web_fetch': {'url': 'https://httpbin.org/get'},
}

passed = 0
failed = 0
errors = []
skipped = []

for tool_name in all_tools:
    if tool_name not in TESTS:
        skipped.append(tool_name)
        continue
    args = TESTS[tool_name]
    try:
        result = registry.execute(tool_name, **args)
        if result.success:
            out = (result.output or '')[:100].replace('\n', ' ')
            print(f'PASS: {tool_name} -> {out}')
            passed += 1
        else:
            err = (result.error or 'unknown error')[:150]
            print(f'FAIL: {tool_name} -> {err}')
            errors.append((tool_name, err))
            failed += 1
    except Exception as e:
        err = str(e)[:150]
        print(f'ERR:  {tool_name} -> {err}')
        errors.append((tool_name, err))
        failed += 1

print()
print(f'=== RESULTS: {passed} PASSED, {failed} FAILED, {len(skipped)} SKIPPED ===')
if errors:
    print('=== FAILED TOOLS ===')
    for name, err in errors:
        print(f'  {name}: {err}')
if skipped:
    print(f'=== SKIPPED (no test case) ===')
    for name in skipped:
        print(f'  {name}')

# Cleanup
for f in ['_test_write.txt','_test.pdf','_test.docx','_test.xlsx','_test.csv','_test.pptx','_test_audio.wav','_test_conv.wav','_test_img.png','_test_mem.json']:
    try: os.remove(os.path.join(r'C:\Users\offic\EAA', f))
    except: pass
try: os.rmdir(r'C:\Users\offic\EAA\_test_dir')
except: pass
print('DONE')
