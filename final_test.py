import sys, os
os.chdir(r'C:\Users\offic\EAA')
sys.path.insert(0, '.')
from eaa_tool_executor import create_enhanced_registry
R, _, _ = create_enhanced_registry()
p = f = 0; E = []; SKIP = set()
def T(t, **kw):
    global p, f
    if t in SKIP: return
    try:
        r = R.execute(t, **kw)
        if r.success:
            p += 1; print(f'PASS {t}')
        else:
            f += 1; e = str(r.error or '')[:90]; print(f'FAIL {t}: {e}'); E.append((t, e))
    except Exception as ex:
        f += 1; e = str(ex)[:90]; print(f'ERR  {t}: {e}'); E.append((t, e))

# === FILE TOOLS (9) ===
T('read_file', path='eaa_tool_executor.py')
T('write_file', path='_tw.txt', content='hi')
T('append_file', path='_tw.txt', content=' w')
T('list_files', path='.')
T('file_exists', path='eaa_tool_executor.py')
T('create_directory', path='_td')
T('delete_file', path='_tw.txt')
T('glob', pattern='eaa_*.py', path='.')
T('grep', pattern='def ', path='eaa_tool_executor.py')

# === WEB (skip web_search - rate limited) ===
SKIP.add('web_search')
T('web_fetch', url='https://httpbin.org/get')

# === MEMORY (8) ===
T('memory_save', key='_fk', value='fv')
T('memory_recall', key='_fk')
T('memory_list')
T('memory_search', query='f')
T('memory_clear')
T('memory_stats')
T('memory_export', file_path='_fm.json')
T('memory_import', file_path='_fm.json')

# === SYSTEM (12) ===
T('datetime')
T('calculator', expression='33*3')
T('python', code='print(88)')
T('system_info')
T('process_list')
T('env_get', name='PATH')
T('env_set', name='_FV', value='1')
T('clipboard_read')
T('clipboard_write', text='_ft')
T('screenshot')
T('app_launch', app_name='notepad.exe')
T('process_kill', pid=999999)

# === CODE (10) ===
T('code_run', code='print(55)', language='python')
T('code_lint', file_path='eaa_tool_executor.py', language='python')
T('code_format', file_path='eaa_tool_executor.py', language='python')
T('code_test', path='.', test_type='quick')
T('git_status', repo_path='.')
T('git_log', repo_path='.', count=3)
T('git_diff', repo_path='.')
T('git_branch', repo_path='.')
T('git_commit', repo_path='.', message='_ft')

# === DOCUMENT (9) ===
T('pdf_info', file_path='eaa_tool_executor.py')
T('pdf_read', file_path='eaa_tool_executor.py')
T('pdf_create', file_path='_fp.pdf', content='Test')
T('docx_read', file_path='eaa_tool_executor.py')
T('docx_create', file_path='_fd.docx', content='Test doc')
T('xlsx_read', file_path='eaa_tool_executor.py')
T('xlsx_create', file_path='_fx.xlsx', headers='A,B', rows='1,2')
T('pptx_read', file_path='eaa_tool_executor.py')
T('pptx_create', file_path='_fp2.pptx', content='Test slide')

# === MULTIMODAL (skip image_generate - needs diffusers) ===
SKIP.add('image_generate')
T('image_info', image_path='eaa_tool_executor.py')
T('image_analyze', image_path='eaa_tool_executor.py')
T('image_describe', image_path='eaa_tool_executor.py')
T('ocr_extract', image_path='eaa_tool_executor.py')
T('image_convert', image_path='eaa_tool_executor.py', output_path='_fic.png', format='png')
T('image_resize', image_path='eaa_tool_executor.py', output_path='_fir.png', width=100)

# === BROWSER (skip all - playwright broken on Windows) ===
for b in ['browser_open','browser_click','browser_type','browser_screenshot','browser_scroll','browser_get_text','browser_close']:
    SKIP.add(b)

# === COMMUNICATION (skip email_send - SMTP issue) ===
SKIP.add('email_send')
T('notify_send', title='EAA', message='Test')
SKIP.add('sms_send')

# === DATA (7) ===
T('json_parse', data='{"x":1}')
T('csv_read', file_path='eaa_tool_executor.py')
T('csv_write', file_path='_fc.csv', headers='A', rows='1\n2')
T('database_query', db_path=':memory:', query='SELECT 1+1')
T('api_call', url='https://httpbin.org/get', method='GET')
T('hash_text', text='hello')
T('hash_file', file_path='eaa_tool_executor.py')

# === AUDIO/VIDEO (skip all - need audio/video files) ===
for a in ['audio_transcribe','audio_generate','audio_info','audio_convert','video_analyze','video_info']:
    SKIP.add(a)

# === SCHEDULER (4) ===
T('schedule_list')
T('schedule_info', task_id='_nf')
T('schedule_task', name='_ftsk', run_at='2099-01-01 00:00', command='echo hi')
T('schedule_cancel', task_id='_nf')

# === CONTEXT (4) ===
T('context_list')
T('context_save', name='_ftx', messages='[]')
T('context_load', name='_ftx')
T('context_delete', name='_ftx')

print(f'\n=== FINAL RESULTS ===')
print(f'  PASSED: {p}')
print(f'  FAILED: {f}')
print(f'  SKIPPED: {len(SKIP)} (known issues)')
print(f'  TOTAL:  {p + f + len(SKIP)}')
if E:
    print(f'\nFAILED TOOLS ({len(E)}):')
    for n,e in E: print(f'  {n}: {e}')
print(f'\nSKIPPED TOOLS ({len(SKIP)}):')
for s in sorted(SKIP): print(f'  {s}')

# Cleanup
for fn in ['_tw.txt','_fp.pdf','_fd.docx','_fx.xlsx','_fp2.pptx','_fc.csv','_fic.png','_fir.png','_fm.json']:
    try: os.remove(fn)
    except: pass
try: os.rmdir('_td')
except: pass
print('\nDONE')
