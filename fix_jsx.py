p = r"C:\Users\offic\EAA\src\components\HtmlCanvas\HtmlCanvasProvider.tsx"
with open(p, "r", encoding="utf-8") as f:
    c = f.read()
# Fix the > character in JSX
c = c.replace('Type ">" in palette', 'Type {">"} in palette')
with open(p, "w", encoding="utf-8") as f:
    f.write(c)
print("FIXED")
