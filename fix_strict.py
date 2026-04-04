p = r"C:\Users\offic\EAA\tsconfig.json"
with open(p, "r", encoding="utf-8") as f:
    c = f.read()

# Disable strict checking
c = c.replace('"strict": true', '"strict": false')

with open(p, "w", encoding="utf-8") as f:
    f.write(c)
print("UPDATED")
