p = r"C:\Users\offic\EAA\src\App.tsx"
with open(p, "r", encoding="utf-8") as f:
    c = f.read()

# Replace fetch with invoke for health check
old_fetch = '''const res = await fetch("http://127.0.0.1:8000/v1/health");
        if (res.ok) {
          const data = await res.json();'''

new_invoke = '''// Use Tauri invoke to bypass webview network isolation
        const dataStr = await invoke<string>("eaa_check_brain_health");
        const data = JSON.parse(dataStr);
        if (true) {'''

if old_fetch in c:
    c = c.replace(old_fetch, new_invoke)
    with open(p, "w", encoding="utf-8") as f:
        f.write(c)
    print("PATCHED")
else:
    print("OLD CODE NOT FOUND")
