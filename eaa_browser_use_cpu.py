# EAA Browser-Use CPU Worker - NO GPU USAGE
import os, sys, asyncio, gc, time, urllib.request, urllib.parse, re
from typing import Dict, Any

# HIDE GPU FROM THIS PROCESS
os.environ["CUDA_VISIBLE_DEVICES"] = ""
print("[Browser-Use CPU] GPU HIDDEN - CPU ONLY")

class BrowserUseWorker:
    def __init__(self, llm_api_url="http://127.0.0.1:8000/v1"):
        self.llm_api_url = llm_api_url
        self._llm = None
        print("[Browser-Use CPU] Worker ready")
    
    def _init_llm(self):
        if self._llm: return self._llm
        from langchain_openai import ChatOpenAI
        self._llm = ChatOpenAI(base_url=self.llm_api_url, api_key="local", model="local-model", temperature=0.3)
        return self._llm
    
    async def search(self, query: str) -> Dict[str, Any]:
        try:
            from browser_use import Agent
            llm = self._init_llm()
            agent = Agent(task=f"Search the web for: {query}", llm=llm)
            result = await agent.run()
            return {"success": True, "result": str(result)}
        except Exception as e:
            return {"success": False, "error": str(e)}

# Simple search fallback (no browser)
def simple_search(query: str) -> Dict[str, Any]:
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        results = []
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html):
            link, title = m.group(1), m.group(2).strip()
            if link.startswith("//"): link = "https:" + link
            results.append({"title": title, "link": link})
            if len(results) >= 5: break
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}

_worker = None
def get_worker():
    global _worker
    if _worker is None: _worker = BrowserUseWorker()
    return _worker

def web_search_browser_use(query: str, use_browser: bool = True) -> Dict[str, Any]:
    if use_browser:
        try:
            worker = get_worker()
            return asyncio.run(worker.search(query))
        except Exception as e:
            print(f"[Browser-Use] Failed: {e}, using simple search")
    return simple_search(query)
