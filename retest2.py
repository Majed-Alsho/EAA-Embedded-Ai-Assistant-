import requests, time

URL = 'http://localhost:8000/v1/agent/chat'
LOG = r'C:\Users\offic\EAA\retest_log.txt'

TOOLS = [
    ('code_test', 'Use the code_test tool to test the Python function: def add(a,b): return a+b'),
    ('audio_info', 'Use the audio_info tool to get info about audio file C:\\Windows\\Media\\chimes.wav'),
    ('video_info', 'Use the video_info tool to get info about video file C:\\Users\\offic\\EAA\\test_video.mp4'),
    ('audio_transcribe', 'Use the audio_transcribe tool to transcribe audio file C:\\Windows\\Media\\chimes.wav'),
    ('video_analyze', 'Use the video_analyze tool to analyze video file C:\\Users\\offic\\EAA\\test_video.mp4'),
    ('browser_open', 'Use the browser_open tool to open the URL https://example.com'),
    ('browser_screenshot', 'Use the browser_screenshot tool to take a screenshot of the page'),
    ('browser_close', 'Use the browser_close tool to close the browser'),
    ('browser_click', 'Use the browser_click tool to click on element with id test'),
    ('browser_type', 'Use the browser_type tool to type hello into a text field'),
    ('browser_scroll', 'Use the browser_scroll tool to scroll down on the page'),
    ('browser_get_text', 'Use the browser_get_text tool to get text from the page'),
    ('notify_send', 'Use the notify_send tool to send a notification with title Test and message Hello'),
    ('email_send', 'Use the email_send tool to send an email to test@test.com with subject Test and body test body'),
    ('sms_send', 'Use the sms_send tool to send an SMS to 0000000000 with message test'),
    ('app_launch', 'Use the app_launch tool to launch notepad.exe'),
    ('process_kill', 'Use the process_list tool to list all running processes'),
    ('image_generate', 'Use the image_generate tool to generate an image of a blue square'),
    ('image_convert', 'Use the image_convert tool to convert an image'),
    ('image_resize', 'Use the image_resize tool to resize an image'),
    ('audio_generate', 'Use the audio_generate tool to generate a simple beep sound'),
    ('audio_convert', 'Use the audio_convert tool to convert audio file'),
    ('schedule_list2', 'Use the schedule_list tool to list all scheduled tasks'),
    ('schedule_info', 'Use the schedule_list tool to list all scheduled tasks'),
    ('schedule_cancel', 'Use the schedule_list tool to list all scheduled tasks'),
]

with open(LOG, 'w') as lf:
    lf.write(f'STARTING {len(TOOLS)} tools\n')
    lf.flush()

for i, (name, msg) in enumerate(TOOLS):
    t0 = time.time()
    status = 'UNKNOWN'
    resp = ''
    try:
        r = requests.post(URL, json={'message': msg}, timeout=120)
        d = r.json()
        status = 'OK' if d.get('success') else 'ERR'
        resp = d.get('response', '')[:120]
    except Exception as e:
        status = 'FAIL'
        resp = str(e)[:100]
    dt = time.time() - t0

    with open(LOG, 'a') as lf:
        lf.write(f'[{i+1}/{len(TOOLS)}] {name} {status} ({dt:.0f}s) {resp}\n')
        lf.flush()
    time.sleep(1)

with open(LOG, 'a') as lf:
    lf.write('DONE\n')
