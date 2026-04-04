"""
EAA Researcher Brain - Complex Research Module
===============================================
Browser-based deep research with Playwright + AI
This brain SWAPS IN/OUT of VRAM (requires ~6GB)

Author: Majed Al-Shoghri
Version: 1.0
"""

import os
import sys
import json
import time
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

# ============================================
# BROWSER RESEARCH CONFIG
# ============================================

BROWSER_CONFIG = {
    "headless": True,
    "disable_gpu": True,
    "disable_webgl": True,
    "disable_software_rasterizer": True,
    "no_sandbox": True,
    "disable_dev_shm_usage": True,
    "disable_extensions": True,
    "disable_plugins": True,
    "disable_images": False,  # Keep images for some sites
    "timeout": 60000,  # 60 seconds per page
}

# GPU_DISABLE for browser subprocess
BROWSER_ENV = {
    **os.environ,
    "CUDA_VISIBLE_DEVICES": "",
    "WGPU_BACKEND_TYPE": "WebGPU",
    "CHROMIUM_FLAGS": "--disable-gpu --disable-software-rasterizer",
}


class ResearchDepth(Enum):
    QUICK = 1      # 2-3 sources, ~30 seconds
    STANDARD = 2   # 5-7 sources, ~2 minutes
    DEEP = 3       # 10+ sources, ~5 minutes


@dataclass
class ResearchResult:
    """Structured research result"""
    query: str
    depth: ResearchDepth
    summary: str
    key_findings: List[str]
    sources: List[Dict[str, str]]
    confidence: float
    duration_seconds: float
    timestamp: str


class ResearcherBrain:
    """
    Complex research brain using browser automation.
    This module loads into VRAM, does research, then unloads.
    """
    
    def __init__(self, llm_endpoint: str = "http://localhost:8000/v1"):
        self.llm_endpoint = llm_endpoint
        self.browser = None
        self.context = None
        self.page = None
        
    async def _init_browser(self):
        """Initialize headless browser with GPU disabled"""
        try:
            from playwright.async_api import async_playwright
            
            self.playwright = await async_playwright().start()
            
            # Launch with GPU completely disabled
            self.browser = await self.playwright.chromium.launch(
                headless=BROWSER_CONFIG["headless"],
                args=[
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-webgl",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                    f"--timeout={BROWSER_CONFIG['timeout']}"
                ],
                env=BROWSER_ENV
            )
            
            self.context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                java_script_enabled=True,
            )
            
            self.page = await self.context.new_page()
            return True
            
        except Exception as e:
            print(f"[Researcher] Browser init failed: {e}")
            return False
    
    async def _close_browser(self):
        """Close browser to free resources"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if hasattr(self, 'playwright'):
                await self.playwright.stop()
        except:
            pass
        finally:
            self.page = None
            self.context = None
            self.browser = None
    
    async def _search_google(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        """Search Google and get results"""
        results = []
        
        try:
            search_url = f"https://www.google.com/search?q={query}&num={num_results + 2}"
            
            await self.page.goto(search_url, timeout=30000)
            await self.page.wait_for_selector('div#search', timeout=10000)
            
            # Extract search results
            search_items = await self.page.query_selector_all('div.g')
            
            for i, item in enumerate(search_items[:num_results]):
                try:
                    title_el = await item.query_selector('h3')
                    link_el = await item.query_selector('a')
                    snippet_el = await item.query_selector('div[data-sncf], span.aCOpRe')
                    
                    title = await title_el.inner_text() if title_el else ""
                    link = await link_el.get_attribute('href') if link_el else ""
                    snippet = await snippet_el.inner_text() if snippet_el else ""
                    
                    if title and link:
                        results.append({
                            "rank": i + 1,
                            "title": title,
                            "url": link,
                            "snippet": snippet
                        })
                except:
                    continue
                    
        except Exception as e:
            print(f"[Researcher] Google search error: {e}")
        
        return results
    
    async def _scrape_page(self, url: str, max_chars: int = 3000) -> Dict[str, Any]:
        """Scrape content from a single page"""
        try:
            await self.page.goto(url, timeout=20000)
            await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            
            # Get main content
            content = await self.page.evaluate("""
                () => {
                    // Try to find main content
                    const main = document.querySelector('main, article, .content, #content, .post, .article');
                    if (main) return main.innerText.substring(0, 5000);
                    
                    // Fallback to body
                    return document.body.innerText.substring(0, 5000);
                }
            """)
            
            # Get title
            title = await self.page.title()
            
            # Clean content
            content = ' '.join(content.split())[:max_chars]
            
            return {
                "success": True,
                "url": url,
                "title": title,
                "content": content,
                "scraped_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                "success": False,
                "url": url,
                "error": str(e)
            }
    
    async def _call_llm(self, prompt: str, max_tokens: int = 1000) -> str:
        """Call local LLM for analysis"""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.llm_endpoint}/chat/completions",
                    json={
                        "model": "local",
                        "messages": [
                            {"role": "system", "content": "You are a research analyst. Provide concise, factual summaries."},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": max_tokens,
                        "temperature": 0.3
                    },
                    timeout=30
                ) as response:
                    data = await response.json()
                    return data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
        except Exception as e:
            print(f"[Researcher] LLM call failed: {e}")
            return ""
    
    async def research(self, query: str, depth: ResearchDepth = ResearchDepth.STANDARD) -> ResearchResult:
        """
        Main research function - performs deep web research
        
        Args:
            query: Research query
            depth: How deep to research
            
        Returns:
            ResearchResult with findings
        """
        start_time = time.time()
        
        # Determine number of sources based on depth
        source_counts = {
            ResearchDepth.QUICK: 3,
            ResearchDepth.STANDARD: 5,
            ResearchDepth.DEEP: 10
        }
        num_sources = source_counts[depth]
        
        print(f"[Researcher] Starting {depth.name} research: '{query}'")
        print(f"[Researcher] Will scrape {num_sources} sources...")
        
        # Initialize browser
        browser_ready = await self._init_browser()
        if not browser_ready:
            return ResearchResult(
                query=query,
                depth=depth,
                summary="Failed to initialize browser for research.",
                key_findings=[],
                sources=[],
                confidence=0.0,
                duration_seconds=time.time() - start_time,
                timestamp=datetime.now().isoformat()
            )
        
        try:
            # Step 1: Search Google
            print(f"[Researcher] Searching Google...")
            search_results = await self._search_google(query, num_results=num_sources)
            
            if not search_results:
                return ResearchResult(
                    query=query,
                    depth=depth,
                    summary="No search results found.",
                    key_findings=[],
                    sources=[],
                    confidence=0.0,
                    duration_seconds=time.time() - start_time,
                    timestamp=datetime.now().isoformat()
                )
            
            print(f"[Researcher] Found {len(search_results)} results")
            
            # Step 2: Scrape each result
            all_content = []
            sources = []
            
            for i, result in enumerate(search_results):
                print(f"[Researcher] Scraping source {i+1}/{len(search_results)}: {result['title'][:50]}...")
                
                page_data = await self._scrape_page(result['url'])
                
                if page_data.get("success"):
                    all_content.append({
                        "title": result['title'],
                        "url": result['url'],
                        "snippet": result['snippet'],
                        "content": page_data['content']
                    })
                    sources.append({
                        "title": result['title'],
                        "url": result['url']
                    })
                
                # Small delay between requests
                await asyncio.sleep(0.5)
            
            # Step 3: Synthesize findings with LLM
            print(f"[Researcher] Synthesizing {len(all_content)} sources...")
            
            # Combine content for analysis
            combined_content = "\n\n---\n\n".join([
                f"SOURCE: {c['title']}\nURL: {c['url']}\n\n{c['content']}"
                for c in all_content[:5]  # Limit for token count
            ])
            
            synthesis_prompt = f"""Analyze the following research on "{query}" and provide:

1. A concise summary (2-3 paragraphs)
2. 3-5 key findings (bullet points)
3. A confidence score (0.0-1.0)

CONTENT:
{combined_content[:6000]}

Format your response as JSON:
{{
    "summary": "...",
    "key_findings": ["...", "...", "..."],
    "confidence": 0.X
}}"""

            llm_response = await self._call_llm(synthesis_prompt, max_tokens=800)
            
            # Parse LLM response
            try:
                # Try to extract JSON
                import re
                json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
                if json_match:
                    analysis = json.loads(json_match.group())
                    summary = analysis.get("summary", llm_response)
                    key_findings = analysis.get("key_findings", [])
                    confidence = float(analysis.get("confidence", 0.7))
                else:
                    summary = llm_response
                    key_findings = []
                    confidence = 0.5
            except:
                summary = llm_response
                key_findings = []
                confidence = 0.5
            
            duration = time.time() - start_time
            
            print(f"[Researcher] Research complete in {duration:.1f}s")
            
            return ResearchResult(
                query=query,
                depth=depth,
                summary=summary,
                key_findings=key_findings,
                sources=sources,
                confidence=confidence,
                duration_seconds=duration,
                timestamp=datetime.now().isoformat()
            )
            
        finally:
            # Always close browser
            await self._close_browser()


# ============================================
# SYNC WRAPPER FOR EASY USE
# ============================================

def run_research(query: str, depth: str = "standard") -> Dict[str, Any]:
    """
    Synchronous wrapper for research function
    
    Args:
        query: Research query
        depth: "quick", "standard", or "deep"
        
    Returns:
        Dictionary with research results
    """
    depth_map = {
        "quick": ResearchDepth.QUICK,
        "standard": ResearchDepth.STANDARD,
        "deep": ResearchDepth.DEEP
    }
    
    research_depth = depth_map.get(depth.lower(), ResearchDepth.STANDARD)
    
    async def _run():
        brain = ResearcherBrain()
        result = await brain.research(query, research_depth)
        return {
            "success": True,
            "query": result.query,
            "depth": result.depth.name,
            "summary": result.summary,
            "key_findings": result.key_findings,
            "sources": result.sources,
            "confidence": result.confidence,
            "duration_seconds": result.duration_seconds,
            "timestamp": result.timestamp
        }
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(_run())


# ============================================
# TEST FUNCTION
# ============================================

async def test_researcher():
    """Test the researcher brain"""
    print("=" * 60)
    print("TESTING RESEARCHER BRAIN")
    print("=" * 60)
    
    brain = ResearcherBrain()
    
    # Quick test
    result = await brain.research(
        "What is quantum computing and how does it work?",
        ResearchDepth.QUICK
    )
    
    print(f"\nQuery: {result.query}")
    print(f"Depth: {result.depth.name}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"Confidence: {result.confidence}")
    print(f"\nSummary:\n{result.summary}")
    print(f"\nKey Findings:")
    for i, finding in enumerate(result.key_findings, 1):
        print(f"  {i}. {finding}")
    print(f"\nSources: {len(result.sources)}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(test_researcher())
