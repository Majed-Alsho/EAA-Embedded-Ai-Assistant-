"""
EMERGENCY FILE RECOVERY
If your control server is running, this will read ALL important files
and save them before anything else gets lost!
"""
import os
import subprocess
import time

EAA_DIR = r"C:\Users\offic\EAA"

# List of critical files to try to recover
CRITICAL_FILES = [
    "eaa_control_manager_v5_remote.py",
    "eaa_control_manager_v4.py",
    "eaa_control_manager_v3.py",
    "eaa_control_manager_v2.py",
    "eaa_control_manager.py",
    "run_eaa_agent.py",
    "eaa_agent_server.py",
    "eaa_agent_tools.py",
    "eaa_agent_loop.py",
    "eaa_tunnel.py",
]

# Create recovery folder
RECOVERY_DIR = os.path.join(EAA_DIR, "RECOVERED_FILES")
os.makedirs(RECOVERY_DIR, exist_ok=True)

print("="*60)
print("EMERGENCY FILE RECOVERY")
print("="*60)
print(f"\nSaving to: {RECOVERY_DIR}")
print("\n[Step 1] Checking what files exist and their sizes...")

for filename in CRITICAL_FILES:
    filepath = os.path.join(EAA_DIR, filename)
    if os.path.exists(filepath):
        size = os.path.getsize(filepath)
        print(f"  ✓ {filename} - {size} bytes")

        # Copy to recovery folder
        recovery_path = os.path.join(RECOVERY_DIR, filename)
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        with open(recovery_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"    → Saved to RECOVERED_FILES/")
    else:
        print(f"  ✗ {filename} - NOT FOUND")

# Also check for ANY .py files that might be important
print("\n[Step 2] Finding all Python files in EAA folder...")
all_py_files = []
for f in os.listdir(EAA_DIR):
    if f.endswith('.py'):
        filepath = os.path.join(EAA_DIR, f)
        size = os.path.getsize(filepath)
        all_py_files.append((f, size))
        print(f"  {f} - {size} bytes")

print(f"\n  Total Python files found: {len(all_py_files)}")

# Check TypeScript files
print("\n[Step 3] Checking src/components for TypeScript files...")
ts_count = 0
for root, dirs, files in os.walk(os.path.join(EAA_DIR, "src")):
    dirs[:] = [d for d in dirs if d not in ["node_modules", "dist", ".git"]]
    for f in files:
        if f.endswith(('.ts', '.tsx')):
            ts_count += 1

print(f"  Total TypeScript files: {ts_count}")

# Check git status
print("\n[Step 4] Git status...")
result = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=EAA_DIR)
if result.stdout:
    print(result.stdout[:500])
else:
    print("  No changes detected by git")

# Check if there are unstaged changes that might be recoverable
print("\n[Step 5] Checking for ANY stashed changes...")
result = subprocess.run(["git", "stash", "list"], capture_output=True, text=True, cwd=EAA_DIR)
if result.stdout.strip():
    print(result.stdout)
else:
    print("  No stashed changes")

print("\n" + "="*60)
print("Check the RECOVERED_FILES folder!")
print("="*60)
