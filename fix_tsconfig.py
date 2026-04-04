p = r"C:\Users\offic\EAA\tsconfig.json"
with open(p, "r", encoding="utf-8") as f:
    c = f.read()

# Disable strict checking for unused variables
c = c.replace('"noUnusedLocals": true', '"noUnusedLocals": false')
c = c.replace('"noUnusedParameters": true', '"noUnusedParameters": false')

with open(p, "w", encoding="utf-8") as f:
    f.write(c)
print("UPDATED")
