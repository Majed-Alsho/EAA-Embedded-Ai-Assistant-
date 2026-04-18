import requests, time

print("Waiting for brain to load...")
for i in range(20):
    try:
        r = requests.post("http://localhost:8000/v1/agent/chat", json={"message": "Say hi"}, timeout=120)
        d = r.json()
        if d.get("success"):
            print(f"Brain loaded! ({i*15}s)")
            break
        else:
            err = d.get("error", "")[:80]
            print(f"[{i+1}] Still loading... {err}")
    except Exception as e:
        print(f"[{i+1}] Waiting... {str(e)[:60]}")
    time.sleep(15)

time.sleep(5)
print("\n=== TESTING 10 TOOLS (no VRAM clear between!) ===")
tools = [
    ("app_launch", "Use the app_launch tool to launch notepad.exe"),
    ("process_kill", "Use the process_list tool to list all running processes"),
    ("image_generate", "Use the image_generate tool to generate an image of a blue circle"),
    ("image_convert", "Use the image_convert tool to convert an image"),
    ("image_resize", "Use the image_resize tool to resize an image"),
    ("audio_generate", "Use the audio_generate tool to generate a beep sound"),
    ("audio_convert", "Use the audio_convert tool to convert audio"),
    ("schedule_list", "Use the schedule_list tool to list scheduled tasks"),
    ("schedule_info", "Use the schedule_info tool to get info about scheduled tasks"),
    ("schedule_cancel", "Use the schedule_list tool to list all scheduled tasks"),
]
ok = 0
for name, msg in tools:
    print(f"[{name}]", end=" ", flush=True)
    t0 = time.time()
    try:
        r = requests.post("http://localhost:8000/v1/agent/chat", json={"message": msg}, timeout=180)
        d = r.json()
        if d.get("success"):
            ok += 1
            resp = d.get("response", "")[:100]
            print(f"OK ({time.time()-t0:.0f}s) {resp}")
        else:
            err = d.get("error", "")[:100]
            print(f"ERR ({time.time()-t0:.0f}s) {err}")
    except Exception as e:
        print(f"FAIL ({time.time()-t0:.0f}s) {e}")
    time.sleep(2)
print(f"\nDONE: {ok}/{len(tools)} passed")
