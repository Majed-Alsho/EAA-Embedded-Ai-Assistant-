import re

# Fix App.tsx - remove onOpenFile prop that doesn't exist
p = r"C:\Users\offic\EAA\src\App.tsx"
with open(p, "r", encoding="utf-8") as f:
    c = f.read()

# Remove the onOpenFile prop from WorkspacePanel
old = '''onOpenFile={(p) => {
                    setDefaultToolPath(p);
                    setRightTab("read");
                  }}'''
new = ''
if old in c:
    c = c.replace(old, new)
    with open(p, "w", encoding="utf-8") as f:
        f.write(c)
    print("FIXED App.tsx")
else:
    print("App.tsx - onOpenFile not found")

# Fix CanvasEditor.tsx - regex test issue
p2 = r"C:\Users\offic\EAA\src\components\canvas\CanvasEditor.tsx"
with open(p2, "r", encoding="utf-8") as f:
    c = f.read()

# Fix the regex.test issue - cast to RegExp
old2 = 'if (langPattern.test(code))'
new2 = 'if (langPattern instanceof RegExp && langPattern.test(code))'
if old2 in c:
    c = c.replace(old2, new2)

# Fix the score comparison
old3 = 'if (score > bestScore)'
new3 = 'if (typeof score === "number" && score > bestScore)'
if old3 in c:
    c = c.replace(old3, new3)

old4 = 'bestScore = score'
new4 = 'bestScore = typeof score === "number" ? score : 0'
if old4 in c:
    c = c.replace(old4, new4)

with open(p2, "w", encoding="utf-8") as f:
    f.write(c)
print("FIXED CanvasEditor.tsx")

# Fix ToolStyleBag - add missing properties
p3 = r"C:\Users\offic\EAA\src\styles\toolStyles.ts"
with open(p3, "r", encoding="utf-8") as f:
    c = f.read()

# Add missing properties to ToolStyleBag
old5 = 'export type ToolStyleBag = Record<string, any>;'
new5 = '''export type ToolStyleBag = Record<string, any> & {
  btn?: any;
  output?: any;
  editorWrap?: any;
};'''
if old5 in c:
    c = c.replace(old5, new5)
    with open(p3, "w", encoding="utf-8") as f:
        f.write(c)
    print("FIXED toolStyles.ts")
else:
    print("toolStyles.ts - pattern not found")
