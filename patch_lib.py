p = r"C:\Users\offic\EAA\src-tauri\src\lib.rs" 
with open(p, "r", encoding="utf-8") as f: c = f.read() 
print(f"Original: {len(c)} chars") 
if "use reqwest" not in c: c = c.replace("use serde_json::Value;", "use serde_json::Value;\nuse reqwest::blocking::Client;"); print("Added reqwest") 
