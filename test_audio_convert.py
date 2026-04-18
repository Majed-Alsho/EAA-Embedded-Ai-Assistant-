import requests, time, json

print("Testing audio_convert with real file...")
r = requests.post("http://localhost:8000/v1/agent/chat", json={"message": "Use the audio_convert tool to convert C:\\Users\\offic\\EAA\\beep_sound.wav to mp3 format, save it as C:\\Users\\offic\\EAA\\beep_sound.mp3"}, timeout=180)
print(f"Status: {r.status_code}")
d = r.json()
print(json.dumps(d, indent=2)[:2000])
print(f"\nTime: {d.get('execution_time', 'N/A')}")
print(f"Success: {d.get('success')}")
