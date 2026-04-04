"""
EAA WEB MANAGER
===============
Smart web search with multiple backends and caching.
No model loading needed, but follows same manager pattern.

Features:
- Multiple search backends (DuckDuckGo, Brave, Bing)
- Auto-retry on rate limits
- Smart caching to avoid repeated searches
- Web page reading with content extraction
"""

import os
import json
import time
import hashlib
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from pathlib import Path

class WebManager:
    """
    Smart web search manager - same pattern as BrainManager.
    Handles rate limits, caching, and multiple backends.
    """

    def __init__(self, cache_dir: str = None, cache_ttl_hours: int = 24):
        self.cache_dir = cache_dir or os.path.join(os.getcwd(), "web_cache")
        self.cache_ttl = timedelta(hours=cache_ttl_hours)

        # Create cache directory
        os.makedirs(self.cache_dir, exist_ok=True)

        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = 1.0  # seconds between requests

        # Available backends
        self.backends = {
            "duckduckgo": self._search_duckduckgo,
            "brave": self._search_brave,
        }

        self.default_backend = "duckduckgo"

        print(f"[WEB] Manager initialized. Cache: {self.cache_dir}")

    # ==================== CACHING ====================

    def _cache_key(self, query: str) -> str:
        """Generate cache key from query"""
        return hashlib.md5(query.lower().encode()).hexdigest()

    def _cache_path(self, query: str) -> str:
        """Get cache file path"""
        return os.path.join(self.cache_dir, f"{self._cache_key(query)}.json")

    def _get_cached(self, query: str) -> Optional[dict]:
        """Get cached results if still valid"""
        cache_file = self._cache_path(query)

        if not os.path.exists(cache_file):
            return None

        try:
            with open(cache_file, 'r') as f:
                cached = json.load(f)

            # Check TTL
            cached_time = datetime.fromisoformat(cached.get("timestamp", "2000-01-01"))
            if datetime.now() - cached_time > self.cache_ttl:
                return None

            print(f"[WEB] 📦 Cache hit: {query[:50]}")
            return cached
        except:
            return None

    def _save_cache(self, query: str, results: dict):
        """Save results to cache"""
        cache_file = self._cache_path(query)

        cached = {
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "results": results
        }

        with open(cache_file, 'w') as f:
            json.dump(cached, f, indent=2)

        print(f"[WEB] 💾 Cached: {query[:50]}")

    # ==================== RATE LIMITING ====================

    def _wait_for_rate_limit(self):
        """Wait to respect rate limits"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    # ==================== SEARCH BACKENDS ====================

    def _search_duckduckgo(self, query: str, num_results: int = 5) -> dict:
        """Search using DuckDuckGo (free, no API key)"""
        try:
            from duckduckgo_search import DDGS

            self._wait_for_rate_limit()

            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=num_results * 2))  # Get extra in case of filtering

            # Format results
            formatted = []
            for r in results[:num_results]:
                formatted.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")[:300],
                    "source": "duckduckgo"
                })

            return {
                "success": True,
                "results": formatted,
                "backend": "duckduckgo"
            }

        except Exception as e:
            return {
                "success": False,
                "results": [],
                "error": str(e),
                "backend": "duckduckgo"
            }

    def _search_brave(self, query: str, num_results: int = 5) -> dict:
        """Search using Brave Search API (requires free API key)"""
        # Check for API key
        api_key = os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            return {
                "success": False,
                "results": [],
                "error": "BRAVE_API_KEY not set. Get free key at https://brave.com/search/api/",
                "backend": "brave"
            }

        try:
            import urllib.request
            import urllib.parse

            self._wait_for_rate_limit()

            url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(query)}&count={num_results}"

            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key
            })

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            # Parse results
            formatted = []
            web_results = data.get("web", {}).get("results", [])
            for r in web_results[:num_results]:
                formatted.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("description", "")[:300],
                    "source": "brave"
                })

            return {
                "success": True,
                "results": formatted,
                "backend": "brave"
            }

        except Exception as e:
            return {
                "success": False,
                "results": [],
                "error": str(e),
                "backend": "brave"
            }

    # ==================== MAIN SEARCH ====================

    def search(self, query: str, num_results: int = 5, use_cache: bool = True, backend: str = None) -> dict:
        """
        Search the web with caching and fallback.

        Args:
            query: Search query
            num_results: Number of results to return
            use_cache: Whether to use cached results
            backend: Specific backend to use (None = auto)

        Returns:
            dict with success, results, backend used
        """
        print(f"[WEB] 🔍 Searching: {query}")

        # Check cache first
        if use_cache:
            cached = self._get_cached(query)
            if cached:
                return cached["results"]

        # Try backends
        backends_to_try = [backend] if backend else [self.default_backend, "duckduckgo", "brave"]
        backends_to_try = [b for b in backends_to_try if b in self.backends]

        for backend_name in backends_to_try:
            print(f"[WEB] 🌐 Trying backend: {backend_name}")
            result = self.backends[backend_name](query, num_results)

            if result["success"]:
                # Cache successful results
                self._save_cache(query, result)
                return result

            print(f"[WEB] ⚠️ {backend_name} failed: {result.get('error', 'Unknown error')}")

        # All backends failed
        return {
            "success": False,
            "results": [],
            "error": "All search backends failed",
            "backend": "none"
        }

    # ==================== WEB PAGE READING ====================

    def read_page(self, url: str) -> dict:
        """
        Read and extract text from a web page.

        Returns:
            dict with title, content, url
        """
        print(f"[WEB] 📖 Reading: {url}")

        # Check cache
        cache_key = f"page_{hashlib.md5(url.encode()).hexdigest()}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached["results"]

        try:
            import urllib.request
            import re

            self._wait_for_rate_limit()

            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })

            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            # Extract title
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else "Unknown"

            # Remove script, style, nav, footer
            html = re.sub(r'<(script|style|nav|footer|header)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)

            # Remove all tags
            text = re.sub(r'<[^>]+>', ' ', html)

            # Clean whitespace
            text = re.sub(r'\s+', ' ', text).strip()

            # Limit size
            if len(text) > 10000:
                text = text[:10000] + "..."

            result = {
                "success": True,
                "title": title,
                "content": text,
                "url": url
            }

            # Cache
            self._save_cache(cache_key, result)

            return result

        except Exception as e:
            return {
                "success": False,
                "title": "",
                "content": "",
                "url": url,
                "error": str(e)
            }

    # ==================== RESEARCH HELPER ====================

    def research(self, query: str, depth: int = 2) -> dict:
        """
        Do deep research on a topic.

        Args:
            query: Research query
            depth: How many result pages to read (1-3)

        Returns:
            Combined research results
        """
        print(f"[WEB] 🔬 Researching: {query} (depth: {depth})")

        # First search
        search_result = self.search(query, num_results=5)
        if not search_result["success"]:
            return search_result

        findings = []
        sources = []

        # Read top results
        for i, result in enumerate(search_result["results"][:depth]):
            page = self.read_page(result["url"])
            if page["success"]:
                findings.append(f"Source {i+1}: {result['title']}\n{page['content'][:2000]}")
                sources.append(result["url"])

        return {
            "success": True,
            "query": query,
            "findings": "\n\n---\n\n".join(findings),
            "sources": sources,
            "search_results": search_result["results"]
        }

    # ==================== STATUS ====================

    def get_status(self) -> dict:
        """Get manager status"""
        cache_files = [f for f in os.listdir(self.cache_dir) if f.endswith('.json')]

        return {
            "cache_dir": self.cache_dir,
            "cache_files": len(cache_files),
            "backends": list(self.backends.keys()),
            "default_backend": self.default_backend
        }


# ============== CONVENIENCE FUNCTIONS ==============

_web_manager = None

def get_web_manager() -> WebManager:
    """Get or create the global WebManager instance"""
    global _web_manager
    if _web_manager is None:
        _web_manager = WebManager()
    return _web_manager

def web_search(query: str, num_results: int = 5) -> dict:
    """Quick search function"""
    return get_web_manager().search(query, num_results)

def web_read(url: str) -> dict:
    """Quick page read function"""
    return get_web_manager().read_page(url)

def web_research(query: str, depth: int = 2) -> dict:
    """Quick research function"""
    return get_web_manager().research(query, depth)


# ============== INTEGRATION WITH EAA TOOLS ==============

def create_web_tools():
    """
    Create web tools that integrate with EAA's tool registry.
    These replace the placeholder tools in eaa_agent_tools.py
    """

    def tool_web_search_v2(query: str, num_results: int = 5) -> dict:
        """Enhanced web search with caching and fallbacks"""
        result = web_search(query, num_results)
        if result["success"]:
            output = f"Found {len(result['results'])} results for: {query}\n\n"
            for i, r in enumerate(result["results"], 1):
                output += f"{i}. {r['title']}\n   URL: {r['url']}\n   {r['snippet']}\n\n"
            return {"success": True, "output": output, "error": None}
        return {"success": False, "output": "", "error": result.get("error", "Search failed")}

    def tool_web_read_v2(url: str) -> dict:
        """Enhanced web page reader"""
        result = web_read(url)
        if result["success"]:
            output = f"Title: {result['title']}\nURL: {url}\n\n{result['content']}"
            return {"success": True, "output": output, "error": None}
        return {"success": False, "output": "", "error": result.get("error", "Failed to read page")}

    return tool_web_search_v2, tool_web_read_v2


# ============== TEST ==============

if __name__ == "__main__":
    print("=" * 50)
    print("  EAA WEB MANAGER TEST")
    print("=" * 50)

    wm = get_web_manager()
    print(f"\nStatus: {wm.get_status()}")

    # Test search
    print("\n--- Testing Search ---")
    result = wm.search("RTX 5090 specs", num_results=3)
    print(f"Success: {result['success']}")
    if result['success']:
        for r in result['results']:
            print(f"  - {r['title']}: {r['url'][:50]}...")
