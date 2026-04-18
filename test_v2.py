import sys, os, json
os.chdir(r'C:\Users\offic\EAA')
sys.path.insert(0, '.')
from eaa_tool_executor import create_enhanced_registry
R, _, _ = create_enhanced_registry()
passed = failed = 0
errors = []
def test(name, **kw):
    global passed, failed
    try:
        r = R.execute(name, **kw)
        if r.success:
            passed += 1
            out = str(r.output or '')[:80].replace('\n',' ')
            print(f'PASS {name}: {out}')
        else:
            failed += 1
            e = str(r.error or '')[:120].replace('\n',' ')
            print(f'FAIL {name}: {e}')
            errors.append((name, e))
    except Exception as ex:
        failed += 1
        e = str(ex)[:120].replace('\n',' ')
        print(f'ERR  {name}: {e}')
        errors.append((name, e))

# FILE TOOLS
test('read_file', path='eaa_tool_executor.py')
test('write_file', path='_tw.txt', content='hello')
test('append_file', path='_tw.txt', content=' world')
test('list_files', path='.')
test('file_exists', path='eaa_tool_executor.py')
test('create_directory', path='_td')
test('delete_file', path='_tw.txt')
test('glob', pattern='eaa_*.py', path='.')
test('grep', pattern='def ', path='eaa_tool_executor.py')

# WEB TOOLS
test('web_search', query='hello')
test('web_fetch', url='https://httpbin.org/get')

# MEMORY TOOLS
test('memory_save', key='_tk', value='testval')
test('memory_recall', key='_tk')
test('memory_list')
test('memory_search', query='test')
test('memory_clear')
test('memory_stats')
test('memory_export', file_path='_tm.json')
test('memory_import', file_path='_tm.json')

# SYSTEM TOOLS
test('datetime')
test('calculator', expression='22*33')
test('python', code='print(77)')
test('system_info')
test('process_list')
test('env_get', name='PATH')
test('env_set', name='_TV', value='test123')
test('clipboard_read')
test('clipboard_write', text='_ctest')
test('screenshot')
test('app_launch', app_name='notepad.exe')
test('process_kill', pid=999999)

# CODE TOOLS (correct param names!)
test('code_run', code='print(55)', language='python')
test('code_lint', file_path='eaa_tool_executor.py', language='python')
test('code_format', file_path='eaa_tool_executor.py', language='python')
test('code_test', path='.', test_type='quick')
test('git_status', repo_path='.')
test('git_log', repo_path='.', count=3)
test('git_diff', repo_path='.')
test('git_branch', repo_path='.')
test('git_commit', repo_path='.', message='_test_commit')

# DOCUMENT TOOLS (correct param names!)
test('pdf_info', file_path='eaa_tool_executor.py')
test('pdf_read', file_path='eaa_tool_executor.py')
test('pdf_create', file_path='_tp.pdf', content='Test page content')
test('docx_read', file_path='eaa_tool_executor.py')
test('docx_create', file_path='_td.docx', content='Test doc content')
test('xlsx_read', file_path='eaa_tool_executor.py')
test('xlsx_create', file_path='_tx.xlsx', headers='A,B', rows='1,2\n3,4')
test('pptx_read', file_path='eaa_tool_executor.py')
test('pptx_create', file_path='_tpp.pptx', content='Test slide')

# MULTIMODAL TOOLS (correct param names!)
test('image_info', image_path='eaa_tool_executor.py')
test('image_analyze', image_path='eaa_tool_executor.py')
test('image_describe', image_path='eaa_tool_executor.py')
test('ocr_extract', image_path='eaa_tool_executor.py')
test('image_convert', image_path='eaa_tool_executor.py', output_path='_tic.png', format='png')
test('image_resize', image_path='eaa_tool_executor.py', output_path='_tir.png', width=100)

# BROWSER TOOLS
test('browser_open', url='about:blank')
test('browser_get_text')
test('browser_screenshot')
test('browser_click', selector='body')
test('browser_type', selector='body', text='test')
test('browser_scroll', direction='down')
test('browser_close')

# COMMUNICATION TOOLS
test('notify_send', title='EAA Test', message='Testing tools')
test('email_send', to='test@test.com', subject='EAA Test', body='Test body')

# DATA TOOLS (correct param names!)
test('json_parse', data='{"a":1,"b":2}')
test('csv_read', file_path='eaa_tool_executor.py')
test('csv_write', file_path='_tc.csv', headers='X,Y', rows='1,2\n3,4')
test('database_query', db_path=':memory:', query='SELECT 1+1 AS result')
test('api_call', url='https://httpbin.org/get', method='GET')
test('hash_text', text='hello world')
test('hash_file', file_path='eaa_tool_executor.py')

# AUDIO/VIDEO TOOLS (correct param names!)
test('audio_info', audio_path='eaa_tool_executor.py')
test('audio_transcribe', audio_path='eaa_tool_executor.py')
test('audio_generate', text='hello test', output_path='_ta.wav')
test('audio_convert', input_path='eaa_tool_executor.py', output_path='_tac.wav')
test('video_analyze', video_path='eaa_tool_executor.py')
test('video_info', video_path='eaa_tool_executor.py')

# SCHEDULER TOOLS (correct param names!)
test('schedule_list')
test('schedule_info', task_id='_nonexistent')
test('schedule_task', name='_test_task', run_at='2099-01-01 00:00', command='echo hi')
test('schedule_cancel', task_id='_nonexistent')

# CONTEXT TOOLS (correct param names - these have 'name' param!)
test('context_save', name='_tctx', messages='test context')
test('context_load', name='_tctx')
test('context_list')
test('context_delete', name='_tctx')

print(f'\n=== RESULTS: {passed} PASSED, {failed} FAILED ===')
if errors:
    print('FAILED TOOLS:')
    for n,e in errors:
        print(f'  {n}: {e}')

# Cleanup
for f in ['_tw.txt','_tp.pdf','_td.docx','_tx.xlsx','_tpp.pptx','_tc.csv','_ta.wav','_tac.wav','_tic.png','_tir.png','_tm.json']:
    try: os.remove(f)
    except: pass
try: os.rmdir('_td')
except: pass
print('DONE')
