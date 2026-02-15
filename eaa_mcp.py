from fastmcp import FastMCP
import os
import subprocess

mcp = FastMCP("EAA_Training_Assistant")
BASE_DIR = r"C:\Users\offic\EAA"

@mcp.tool()
def read_script(filename: str) -> str:
    """Read any script from the EAA folder for surgery."""
    with open(os.path.join(BASE_DIR, filename), "r") as f:
        return f.read()

@mcp.tool()
def update_script(filename: str, new_content: str) -> str:
    """Update a script. Rule: Add new features on top; don't remove working code."""
    path = os.path.join(BASE_DIR, filename)
    # Automatic backup before surgery
    with open(path + ".bak", "w") as b:
        with open(path, "r") as f: b.write(f.read())
    
    with open(path, "w") as f:
        f.write(new_content)
    return f"Updated {filename}. Backup created at {filename}.bak"

@mcp.tool()
def run_eaa_training() -> str:
    """Executes the full training pipeline in order."""
    scripts = ["make_eaa_train_jsonl.py", "train_qwen_lora.py", "compare_lora.py"]
    outputs = []
    for script in scripts:
        res = subprocess.run([r".\.venv-hf\Scripts\python.exe", script], 
                             cwd=BASE_DIR, capture_output=True, text=True)
        outputs.append(f"--- {script} ---\n{res.stdout or res.stderr}")
    return "\n".join(outputs)

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)