import sys

# eaa_web_researcher_cpu.py content
RESEARCHER_CODE = '''
"""
EAA Web Research Worker - CPU ONLY
"""
import asyncio
import os
import gc
from typing import Dict, Any, Optional

os.environ["CUDA_VISIBLE_DEVICES"] = ""  # Hide GPU from this process

class WebResearchWorker:
    """CPU-only web research worker"""
    
    def __init__(self, llm_api_url="http://127.0.0.1:8000/v1"):
        self.llm_api_url = llm_api_url
        self._llm = None
        self._browser = None
        print("[WebResearch] CPU-only worker created")
    
    async def search(self, query: str) -> Dict[str, Any]:
        """Web search using requests - no browser needed for simple search"""
        import requests
        import time
        
        start = time.time()
        print(f"[WebResearch] Searching: {query}")
        
        try:
            # Use DuckDuckGo HTML (no API key needed)
            resp = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30
            )
            
            # Parse results
            import re
            results = []
            pattern = r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>'
            matches = re.findall(pattern, resp.text)
            
            for url, title in matches[:5]:
                # Clean URL
                if url.startswith("//"):
                    url = "https:" + url
                results.append({"title": title, "link": url})
            
            elapsed = time.time() - start
            print(f"[WebResearch] Found {len(results)} results in {elapsed:.1f}s")
            
            return {"success": True, "query": query, "results": results, "elapsed_seconds": elapsed}
            
        except Exception as e:
            return {"success": False, "error": str(e), "query": query}
    
    async def research(self, query: str, depth: int = 2) -> Dict[str, Any]:
        """Full research - search + LLM synthesis"""
        import requests
        import time
        
        start = time.time()
        
        # Search first
        search_result = await self.search(query)
        
        if not search_result.get("success"):
            return search_result
        
        # Synthesize with local LLM
        try:
            results_text = "\\n".join([
                f"- {r['title']}: {r['link']}" 
                for r in search_result.get("results", [])
            ])
            
            llm_resp = requests.post(
                f"{self.llm_api_url}/chat/completions",
                json={
                    "messages": [
                        {"role": "system", "content": "You are a research assistant. Synthesize findings."},
                        {"role": "user", "content": f"Query: {query}\\n\\nSources:\\n{results_text}\\n\\nProvide a summary:"}
                    ],
                    "max_tokens": 500
                },
                timeout=60
            )
            
            synthesis = llm_resp.json()["choices"][0]["message"]["content"]
            
        except Exception as e:
            synthesis = f"Could not synthesize: {e}"
        
        elapsed = time.time() - start
        return {
            "success": True,
            "query": query,
            "synthesis": synthesis,
            "sources": search_result.get("results", []),
            "elapsed_seconds": elapsed
        }
    
    def cleanup(self):
        self._llm = None
        self._browser = None
        gc.collect()

# Sync wrappers
_worker = None

def get_worker():
    global _worker
    if _worker is None:
        _worker = WebResearchWorker()
    return _worker

def web_search_sync(query: str) -> Dict[str, Any]:
    worker = get_worker()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as ex:
                return ex.submit(asyncio.run, worker.search(query)).result(timeout=120)
        return loop.run_until_complete(worker.search(query))
    except:
        return asyncio.run(worker.search(query))

def web_research_sync(query: str, depth: int = 2) -> Dict[str, Any]:
    worker = get_worker()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as ex:
                return ex.submit(asyncio.run, worker.research(query, depth)).result(timeout=180)
        return loop.run_until_complete(worker.research(query, depth))
    except:
        return asyncio.run(worker.research(query, depth))
'''

# Write the file
with open(r'C:\Users\offic\EAA\eaa_web_researcher_cpu.py', 'w') as f:
    f.write(RESEARCHER_CODE)
print("Written: eaa_web_researcher_cpu.py")
