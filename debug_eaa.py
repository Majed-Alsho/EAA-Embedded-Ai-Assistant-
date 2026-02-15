import os
import sys

print(f"Current Working Directory: {os.getcwd()}")
print("\n🔍 Scanning for 'eaa_researcher' files...")

files = os.listdir(".")
found = False

for f in files:
    if "eaa_researcher" in f:
        print(f" -> FOUND FILE: '{f}'")
        found = True

if not found:
    print("❌ Python sees NO file with that name.")
else:
    print("✅ File exists. Attempting to import it...")
    try:
        import eaa_researcher
        print("🎉 SUCCESS! The file is valid and importable.")
    except Exception as e:
        print(f"💀 CRITICAL ERROR: The file exists, but Python can't read it!")
        print(f"Error Message: {e}")