# EAA CPU-Only Web Researcher - NO GPU USAGE
# Forces CUDA_VISIBLE_DEVICES="" to ensure CPU only

import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""  # HIDE GPU!

import subprocess
import json
import re
from typing import Dict, Any, List

def web_search_cpu(query: str) -> Dict[str, Any]:
    """
    Search the web using CPU only.
    Uses PowerShell Invoke-WebRequest (runs on CPU).
    """
    results = []
    
    # 1. Crypto prices (blockchain.info - works!)
    crypto_keywords = ["bitcoin", "btc", "ethereum", "eth", "crypto", "price"]
    if any(kw in query.lower() for kw in crypto_keywords):
        try:
            cmd = 'powershell -Command "(Invoke-WebRequest -Uri https://blockchain.info/q/24hrprice -UseBasicParsing).Content"'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                price = result.stdout.strip()
                results.append({
                    "title": f"Bitcoin Price: ${float(price):,.2f} USD",
                    "snippet": f"Current Bitcoin price is ${float(price):,.2f} USD",
                    "source": "blockchain.info"
                })
        except: pass
    
    # 2. Weather (wttr.in - works!)
    weather_keywords = ["weather", "temperature", "forecast"]
    if any(kw in query.lower() for kw in weather_keywords):
        # Extract location
        location = "New_York"
        for word in query.split():
            if word[0].isupper() and len(word) > 2:
                location = word
                break
        try:
            cmd = f'powershell -Command "$r = Invoke-WebRequest -Uri https://wttr.in/{location}?format=j1 -UseBasicParsing; $r.Content"'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                current = data.get("current_condition", [{}])[0]
                results.append({
                    "title": f"Weather in {location}",
                    "snippet": f"{current.get('temp_F', '?')}F, {current.get('weatherDesc', [{}])[0].get('value', 'Unknown')}",
                    "source": "wttr.in"
                })
        except: pass
    
    # 3. Wikipedia (works!)
    try:
        search_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ', '_')}"
        cmd = f'powershell -Command "(Invoke-WebRequest -Uri {search_url} -UseBasicParsing).Content"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get("extract"):
                results.append({
                    "title": data.get("title", query),
                    "snippet": data.get("extract", "")[:300],
                    "link": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                    "source": "wikipedia"
                })
    except: pass
    
    # Build response
    response_text = f"Found {len(results)} results for: {query}\n\n"
    for i, r in enumerate(results, 1):
        response_text += f"{i}. {r['title']}\n   {r['snippet']}\n   Source: {r['source']}\n\n"
    
    return {
        "success": len(results) > 0,
        "query": query,
        "results": results,
        "response_text": response_text
    }

def web_browse_cpu(url: str) -> Dict[str, Any]:
    """
    Browse a URL and extract content - CPU only.
    """
    try:
        cmd = f'powershell -Command "$r = Invoke-WebRequest -Uri {url} -UseBasicParsing; $r.Content"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            html = result.stdout
            
            # Extract title
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.DOTALL)
            title = title_match.group(1).strip() if title_match else "No title"
            
            # Extract text
            html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL|re.I)
            html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL|re.I)
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()[:10000]
            
            return {
                "success": True,
                "url": url,
                "title": title,
                "content": text
            }
    except Exception as e:
        return {"success": False, "error": str(e)}
    
    return {"success": False, "error": "Unknown error"}

def web_research_cpu(query: str, depth: int = 3) -> Dict[str, Any]:
    """
    Full research workflow - CPU only:
    1. Search for results
    2. Browse top sites
    3. Return comprehensive answer
    """
    # Step 1: Search
    search_result = web_search_cpu(query)
    
    # Step 2: Browse found links
    all_content = []
    for r in search_result.get("results", [])[:depth]:
        if r.get("link"):
            browse_result = web_browse_cpu(r["link"])
            if browse_result.get("success"):
                all_content.append({
                    "source": r.get("title"),
                    "content": browse_result.get("content", "")[:2000]
                })
    
    # Step 3: Build comprehensive response
    response = search_result.get("response_text", "")
    if all_content:
        response += "\n\n--- Detailed Content ---\n\n"
        for c in all_content:
            response += f"Source: {c['source']}\n{c['content'][:500]}...\n\n"
    
    return {
        "success": True,
        "query": query,
        "response_text": response,
        "sources": search_result.get("results", []),
        "content": all_content
    }

# Test
if __name__ == "__main__":
    print("Testing CPU-only web researcher...")
    print(web_search_cpu("bitcoin price"))

