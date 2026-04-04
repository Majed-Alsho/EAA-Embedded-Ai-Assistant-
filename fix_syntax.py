"""Quick fix for syntax errors caused by previous script"""
import os

EAA_DIR = r"C:\Users\offic\EAA"

def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def write_file(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  ✓ Fixed: {os.path.basename(path)}")

def fix_read_panel():
    """Fix ReadPanel.tsx - properly remove the unused function"""
    path = os.path.join(EAA_DIR, "src/components/tools/Read/ReadPanel.tsx")
    content = read_file(path)

    # Remove the entire _looksAbsolute function properly
    import re

    # Remove _looksAbsolute function (multiline)
    content = re.sub(
        r"// function _looksAbsolute\(p: string\) \{[^}]*\n\}",
        "// _looksAbsolute removed - unused",
        content
    )

    # Remove _hadStored useMemo (multiline)
    content = re.sub(
        r"// const _hadStored = useMemo\(\(\) => \{[^}]*\}, \[\]\);",
        "// _hadStored removed - unused",
        content,
        flags=re.DOTALL
    )

    # Simpler approach: just remove lines with these patterns entirely
    lines = content.split('\n')
    new_lines = []
    skip_until_close = 0

    for line in lines:
        # Skip _looksAbsolute function entirely
        if 'function _looksAbsolute' in line or '// function _looksAbsolute' in line:
            skip_until_close = 1
            continue
        if skip_until_close > 0:
            if '{' in line:
                skip_until_close += 1
            if '}' in line:
                skip_until_close -= 1
            continue

        # Skip _hadStored
        if '_hadStored' in line:
            continue

        new_lines.append(line)

    write_file(path, '\n'.join(new_lines))

def fix_workspace_panel():
    """Fix WorkspacePanel.tsx - properly remove unused functions"""
    path = os.path.join(EAA_DIR, "src/components/tools/Workspace/WorkspacePanel.tsx")
    content = read_file(path)

    lines = content.split('\n')
    new_lines = []
    skip_until_close = 0

    for line in lines:
        # Skip _navigate and _goBack functions entirely
        if 'function _navigate' in line or '// function _navigate' in line:
            skip_until_close = 1
            continue
        if 'function _goBack' in line or '// function _goBack' in line:
            skip_until_close = 1
            continue
        if skip_until_close > 0:
            if '{' in line:
                skip_until_close += 1
            if '}' in line:
                skip_until_close -= 1
            continue

        new_lines.append(line)

    write_file(path, '\n'.join(new_lines))

def fix_write_panel():
    """Fix WritePanel.tsx - properly remove unused function"""
    path = os.path.join(EAA_DIR, "src/components/tools/Write/WritePanel.tsx")
    content = read_file(path)

    lines = content.split('\n')
    new_lines = []
    skip_until_close = 0

    for line in lines:
        # Skip _looksAbsolute function entirely
        if 'function _looksAbsolute' in line or '// function _looksAbsolute' in line:
            skip_until_close = 1
            continue
        if skip_until_close > 0:
            if '{' in line:
                skip_until_close += 1
            if '}' in line:
                skip_until_close -= 1
            continue

        new_lines.append(line)

    write_file(path, '\n'.join(new_lines))

def main():
    print("Fixing syntax errors...")

    print("\n[ReadPanel.tsx]")
    try: fix_read_panel()
    except Exception as e: print(f"  ✗ Error: {e}")

    print("\n[WorkspacePanel.tsx]")
    try: fix_workspace_panel()
    except Exception as e: print(f"  ✗ Error: {e}")

    print("\n[WritePanel.tsx]")
    try: fix_write_panel()
    except Exception as e: print(f"  ✗ Error: {e}")

    print("\n✓ Done! Run: npm run build")

if __name__ == "__main__":
    main()
