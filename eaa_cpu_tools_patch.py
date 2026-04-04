# CPU-Only Tools Patch for EAA 
import os, subprocess, json 
os.environ["CUDA_VISIBLE_DEVICES"] = "" 
 
def web_search_cpu(query): 
    results = [] 
    try: 
        cmd = "powershell -Command (Invoke-WebRequest -Uri https://blockchain.info/q/24hrprice -UseBasicParsing).Content" 
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15) 
        if r.returncode == 0 and r.stdout.strip(): 
            price = float(r.stdout.strip()) 
            results.append({"title": f"Bitcoin: ${price:,.2f}", "snippet": f"Current price is ${price:,.2f} USD"}) 
    except: pass 
    return {"success": len(results), "results": results, "cpu_only": True} 
