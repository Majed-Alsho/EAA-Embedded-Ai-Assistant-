import json,os,datetime 
MEM_FILE="eaa_memory.json" 
def save(q,a): 
    m=[] 
    if os.path.exists(MEM_FILE): m=json.load(open(MEM_FILE)) 
    m.append({"q":q,"a":a,"t":str(datetime.datetime.now())[:19]}) 
    json.dump(m[-100:],open(MEM_FILE,"w")) 
def load(): return json.load(open(MEM_FILE)) if os.path.exists(MEM_FILE) else [] 
print("Memory:",len(load()),"items") 
