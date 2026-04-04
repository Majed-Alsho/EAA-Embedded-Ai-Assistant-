# EAA Agent V6 - Auto Brain Management 
import os, subprocess, json, time, gc 
os.environ["CUDA_VISIBLE_DEVICES"] = "" 
 
# CPU-only web search 
def web_search_cpu(query): 
    results = [] 
    try: 
        cmd = "powershell -Command (Invoke-WebRequest -Uri https://blockchain.info/q/24hrprice -UseBasicParsing).Content" 
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15) 
        if r.returncode == 0: 
            price = float(r.stdout.strip()) 
            results.append({"title": "Bitcoin: $" + str(round(price,2)), "price": price}) 
            print(f"Found Bitcoin: ${price:,.2f}") 
    except Exception as e: print(f"Error: {e}") 
    return {"success": len(results), "results": results, "cpu_only": True} 
