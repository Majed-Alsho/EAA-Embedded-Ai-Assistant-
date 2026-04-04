import os 
os.environ["CUDA_VISIBLE_DEVICES"] = "" 
 
# Auto-unload brain after task 
import urllib.request, json 
 
def unload_brain(): 
    try: 
        req = urllib.request.Request("http://127.0.0.1:8000/v1/agent/brain/unload", data=b"{}", method="POST") 
        urllib.request.urlopen(req, timeout=30) 
        print("[Auto] Brain unloaded") 
    except: pass 
