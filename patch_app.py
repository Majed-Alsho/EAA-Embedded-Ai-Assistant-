import re

p = r"C:\Users\offic\EAA\src\App.tsx"
with open(p, "r", encoding="utf-8") as f:
    c = f.read()

# Find and replace the fetch call in useEffect for checkBrain
old_code = '''useEffect(() => {
    let attempts = 0;
    const checkBrain = async () => {
      try {
        const res = await fetch("http://127.0.0.1:8000/v1/health");
        if (res.ok) {
          const data = await res.json();
          if (data.status === "online") {
            logLine("[system] Brain connected!");
            setIsBusy(false);
            setShowHub(true);
            return;
          }
        }
      } catch (e) {
        logLine("[system] Connecting to brain... (" + (attempts + 1) + ")");
      }
      attempts++;
      if (attempts < 30) setTimeout(checkBrain, 1000);
      else {
        logLine("[system] Proceeding without brain connection");
        setIsBusy(false);
        setShowHub(true);
      }
    };
    checkBrain();
  }, []);'''

new_code = '''useEffect(() => {
    let attempts = 0;
    const checkBrain = async () => {
      try {
        // Use Tauri invoke instead of fetch (bypasses webview network isolation)
        const dataStr = await invoke<string>("eaa_check_brain_health");
        const data = JSON.parse(dataStr);
        if (data.status === "online") {
          logLine("[system] Brain connected!");
          setIsBusy(false);
          setShowHub(true);
          return;
        }
      } catch (e) {
        logLine("[system] Connecting to brain... (" + (attempts + 1) + ")");
      }
      attempts++;
      if (attempts < 30) setTimeout(checkBrain, 1000);
      else {
        logLine("[system] Proceeding without brain connection");
        setIsBusy(false);
        setShowHub(true);
      }
    };
    checkBrain();
  }, []);'''

if old_code in c:
    c = c.replace(old_code, new_code)
    with open(p, "w", encoding="utf-8") as f:
        f.write(c)
    print("PATCHED App.tsx")
else:
    print("OLD CODE NOT FOUND - checking current state...")
    # Show the current useEffect
    match = re.search(r'useEffect\(\(\) => \{[^}]+checkBrain[^}]+\}, \[\]\);', c, re.DOTALL)
    if match:
        print("Current checkBrain code:")
        print(match.group(0)[:500])
