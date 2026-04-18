import ast 
fp = r"C:\Users\offic\EAA\eaa_agent_loop_v3.py" 
with open(fp,"r",encoding="utf-8") as f: c = f.read() 
old = "                # VRAM GUARD: Free cached VRAM before generation\n                try:\n                    import torch\n                    if torch.cuda.is_available():\n                        gc.collect()\n                        torch.cuda.empty_cache()\n                        torch.cuda.synchronize()\n                except Exception:\n                    pass" 
new = "                # VRAM GUARD: Aggressive cleanup before generation\n                # Uses full _free_vram() to also clear brain_manager cached tensor refs\n                self._free_vram()" 
assert old in c, "old guard not found" 
c2 = c.replace(old, new, 1) 
assert c2 != c, "no change" 
ast.parse(c2) 
print("SYNTAX OK") 
with open(fp,"w",encoding="utf-8") as f: f.write(c2) 
print(f"PATCH APPLIED. _free_vram calls: {c2.count(chr(95)+chr(102)+chr(114)+chr(101)+chr(101)+chr(95)+chr(118)+chr(114)+chr(97)+chr(109)+chr(40)+chr(41))}") 
