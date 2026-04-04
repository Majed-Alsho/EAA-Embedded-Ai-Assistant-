"""
EAA CPU-Only Quick Search Tools
================================
These tools run on CPU ONLY - NO VRAM usage!
Master Brain can stay loaded while these run.

Author: Majed Al-Shoghri
Version: 1.1 - Fixed TLS 1.2 for PowerShell
"""

import os
import subprocess
import json
import re
from datetime import datetime
from typing import Optional, Dict, Any
import urllib.parse

# CRITICAL: Hide GPU from this process
os.environ["CUDA_VISIBLE_DEVICES"] = ""

class CPUTools:
    """CPU-only tools that don't require VRAM"""
    
    def __init__(self):
        self.timeout = 30  # seconds
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
    
    def _run_powershell(self, url: str, extra_headers: dict = None) -> tuple:
        """Execute PowerShell web request - CPU only!"""
        headers = self.headers.copy()
        if extra_headers:
            headers.update(extra_headers)
        
        # Build headers string
        headers_str = ""
        for k, v in headers.items():
            headers_str += f"-Headers @{{'{k}'='{v}'}} "
        
        # PowerShell command with TLS 1.2 enabled - CRITICAL for HTTPS!
        cmd = f'''powershell -Command "try {{
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;
            $response = Invoke-WebRequest -Uri '{url}' -UseBasicParsing -TimeoutSec {self.timeout} {headers_str};
            $response.Content
        }} catch {{
            Write-Error $_.Exception.Message
        }}"'''
        
        # Run with GPU hidden
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = ""
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=self.timeout + 10,
            env=env
        )
        
        return result.stdout.strip(), result.stderr.strip()
    
    # ============================================
    # QUICK SEARCH TOOLS - Real Data, CPU Only
    # ============================================
    
    def crypto_price(self, symbol: str = "BTC") -> Dict[str, Any]:
        """Get cryptocurrency price from API"""
        symbol = symbol.upper()
        
        # Map common symbols to IDs
        crypto_ids = {
            "BTC": "bitcoin",
            "ETH": "ethereum", 
            "SOL": "solana",
            "XRP": "ripple",
            "DOGE": "dogecoin",
            "ADA": "cardano",
            "DOT": "polkadot",
            "BNB": "binancecoin"
        }
        
        try:
            # Use CoinGecko API (free, reliable)
            coin_id = crypto_ids.get(symbol, symbol.lower())
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
            
            content, error = self._run_powershell(url)
            
            if content and not error:
                data = json.loads(content)
                if coin_id in data:
                    return {
                        "success": True,
                        "symbol": symbol,
                        "name": coin_id,
                        "price_usd": data[coin_id].get("usd", 0),
                        "change_24h": data[coin_id].get("usd_24h_change", 0),
                        "source": "coingecko",
                        "timestamp": datetime.now().isoformat()
                    }
            
            # Fallback: blockchain.info for BTC
            if symbol == "BTC":
                url = "https://blockchain.info/q/24hrprice"
                content, error = self._run_powershell(url)
                
                if content and not error:
                    try:
                        price = float(content)
                        return {
                            "success": True,
                            "symbol": "BTC",
                            "name": "Bitcoin",
                            "price_usd": price,
                            "source": "blockchain.info",
                            "timestamp": datetime.now().isoformat()
                        }
                    except:
                        pass
            
            return {"success": False, "error": f"Could not fetch price for {symbol}"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def weather(self, city: str = "Riyadh") -> Dict[str, Any]:
        """Get weather using wttr.in API (free, no key needed)"""
        try:
            city_encoded = urllib.parse.quote(city)
            url = f"https://wttr.in/{city_encoded}?format=j1"
            
            content, error = self._run_powershell(url)
            
            if content and not error:
                data = json.loads(content)
                current = data.get("current_condition", [{}])[0]
                location = data.get("nearest_area", [{}])[0]
                
                return {
                    "success": True,
                    "city": location.get("areaName", [{}])[0].get("value", city),
                    "country": location.get("country", [{}])[0].get("value", ""),
                    "temperature_c": current.get("temp_C", "N/A"),
                    "temperature_f": current.get("temp_F", "N/A"),
                    "description": current.get("weatherDesc", [{}])[0].get("value", "N/A"),
                    "humidity": current.get("humidity", "N/A"),
                    "wind_speed": current.get("windspeedKmph", "N/A"),
                    "feels_like": current.get("FeelsLikeC", "N/A"),
                    "source": "wttr.in",
                    "timestamp": datetime.now().isoformat()
                }
            
            return {"success": False, "error": f"Could not fetch weather for {city}"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def exchange_rate(self, from_currency: str = "USD", to_currency: str = "SAR") -> Dict[str, Any]:
        """Get exchange rate from API (free)"""
        try:
            from_curr = from_currency.upper()
            to_curr = to_currency.upper()
            
            # Use frankfurter API (free, reliable)
            url = f"https://api.frankfurter.app/latest?from={from_curr}&to={to_curr}"
            
            content, error = self._run_powershell(url)
            
            if content and not error:
                data = json.loads(content)
                if "rates" in data and to_curr in data["rates"]:
                    return {
                        "success": True,
                        "from": from_curr,
                        "to": to_curr,
                        "rate": data["rates"][to_curr],
                        "source": "frankfurter.app",
                        "timestamp": datetime.now().isoformat()
                    }
            
            # Fallback: exchangerate.host
            url = f"https://api.exchangerate.host/latest?base={from_curr}&symbols={to_curr}"
            content, error = self._run_powershell(url)
            
            if content and not error:
                data = json.loads(content)
                if "rates" in data and to_curr in data["rates"]:
                    return {
                        "success": True,
                        "from": from_curr,
                        "to": to_curr,
                        "rate": data["rates"][to_curr],
                        "source": "exchangerate.host",
                        "timestamp": datetime.now().isoformat()
                    }
            
            return {"success": False, "error": f"Could not fetch rate for {from_curr}/{to_curr}"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def stock_price(self, symbol: str) -> Dict[str, Any]:
        """Get stock price (using Yahoo Finance API)"""
        try:
            symbol = symbol.upper()
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
            
            content, error = self._run_powershell(url)
            
            if content and not error:
                data = json.loads(content)
                chart = data.get("chart", {}).get("result", [{}])[0]
                meta = chart.get("meta", {})
                
                if meta:
                    return {
                        "success": True,
                        "symbol": symbol,
                        "name": meta.get("shortName", symbol),
                        "price": meta.get("regularMarketPrice", 0),
                        "currency": meta.get("currency", "USD"),
                        "exchange": meta.get("exchangeName", ""),
                        "previous_close": meta.get("previousClose", 0),
                        "source": "yahoo_finance",
                        "timestamp": datetime.now().isoformat()
                    }
            
            return {"success": False, "error": f"Could not fetch stock price for {symbol}"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def web_search_duckduckgo(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Quick search using DuckDuckGo Instant Answer API"""
        try:
            query_encoded = urllib.parse.quote(query)
            url = f"https://api.duckduckgo.com/?q={query_encoded}&format=json&no_html=1"
            
            content, error = self._run_powershell(url)
            
            results = []
            
            if content and not error:
                data = json.loads(content)
                
                # Get instant answer
                if data.get("AbstractText"):
                    results.append({
                        "type": "instant_answer",
                        "title": data.get("Heading", ""),
                        "text": data.get("AbstractText", ""),
                        "source": data.get("AbstractURL", ""),
                        "source_name": data.get("AbstractSource", "")
                    })
                
                # Get related topics
                for topic in data.get("RelatedTopics", [])[:max_results]:
                    if "Text" in topic and "FirstURL" in topic:
                        results.append({
                            "type": "related",
                            "title": topic.get("Text", "")[:100],
                            "url": topic.get("FirstURL", "")
                        })
                
                # Get infobox if available
                infobox = data.get("Infobox", {})
                if infobox.get("content"):
                    for item in infobox["content"][:3]:
                        results.append({
                            "type": "fact",
                            "label": item.get("label", ""),
                            "value": item.get("value", "")
                        })
            
            if results:
                return {
                    "success": True,
                    "query": query,
                    "results": results,
                    "source": "duckduckgo",
                    "timestamp": datetime.now().isoformat()
                }
            
            return {"success": False, "error": "No results found", "query": query}
            
        except Exception as e:
            return {"success": False, "error": str(e), "query": query}
    
    def wikipedia_summary(self, topic: str) -> Dict[str, Any]:
        """Get Wikipedia summary for a topic"""
        try:
            topic_encoded = urllib.parse.quote(topic)
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{topic_encoded}"
            
            content, error = self._run_powershell(url)
            
            if content and not error:
                data = json.loads(content)
                
                return {
                    "success": True,
                    "topic": topic,
                    "title": data.get("title", ""),
                    "extract": data.get("extract", ""),
                    "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                    "thumbnail": data.get("thumbnail", {}).get("source", ""),
                    "source": "wikipedia",
                    "timestamp": datetime.now().isoformat()
                }
            
            return {"success": False, "error": f"Could not find Wikipedia article for {topic}"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def news_headlines(self, category: str = "technology") -> Dict[str, Any]:
        """Get news headlines using RSS (free)"""
        try:
            # Use hnrss.org for tech news (free, no key)
            if category.lower() in ["tech", "technology"]:
                url = "https://hnrss.org/frontpage"
            else:
                url = f"https://hnrss.org/{category}"
            
            content, error = self._run_powershell(url)
            
            if content and not error:
                # Parse RSS XML simply
                items = re.findall(r'<item>(.*?)</item>', content, re.DOTALL)[:5]
                headlines = []
                
                for item in items:
                    title_match = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', item)
                    link_match = re.search(r'<link>(.*?)</link>', item)
                    
                    if title_match:
                        headlines.append({
                            "title": title_match.group(1),
                            "link": link_match.group(1) if link_match else ""
                        })
                
                if headlines:
                    return {
                        "success": True,
                        "category": category,
                        "headlines": headlines,
                        "source": "hnrss",
                        "timestamp": datetime.now().isoformat()
                    }
            
            return {"success": False, "error": "Could not fetch news headlines"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def time_zone(self, timezone: str = "Asia/Riyadh") -> Dict[str, Any]:
        """Get current time in a timezone"""
        try:
            # Use worldtimeapi
            url = f"http://worldtimeapi.org/api/timezone/{timezone}"
            
            content, error = self._run_powershell(url)
            
            if content and not error:
                data = json.loads(content)
                
                return {
                    "success": True,
                    "timezone": timezone,
                    "datetime": data.get("datetime", ""),
                    "day_of_week": data.get("day_of_week", ""),
                    "week_number": data.get("week_number", ""),
                    "source": "worldtimeapi",
                    "timestamp": datetime.now().isoformat()
                }
            
            return {"success": False, "error": f"Could not get time for {timezone}"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def calculator(self, expression: str) -> Dict[str, Any]:
        """Safe calculator - evaluates math expressions"""
        try:
            # Only allow safe characters
            allowed = set("0123456789+-*/.() %^")
            if not all(c in allowed or c.isspace() for c in expression):
                return {"success": False, "error": "Invalid characters in expression"}
            
            # Replace ^ with ** for power
            expression = expression.replace("^", "**")
            
            result = eval(expression)
            
            return {
                "success": True,
                "expression": expression,
                "result": result,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {"success": False, "error": str(e), "expression": expression}


# ============================================
# TOOL REGISTRY FOR EAA INTEGRATION
# ============================================

CPU_TOOL_REGISTRY = {
    "crypto_price": {
        "function": "crypto_price",
        "description": "Get cryptocurrency price (BTC, ETH, SOL, etc.)",
        "params": {"symbol": "Cryptocurrency symbol (default: BTC)"},
        "category": "quick_search",
        "vram_required": False
    },
    "weather": {
        "function": "weather", 
        "description": "Get current weather for any city",
        "params": {"city": "City name (default: Riyadh)"},
        "category": "quick_search",
        "vram_required": False
    },
    "exchange_rate": {
        "function": "exchange_rate",
        "description": "Get currency exchange rate",
        "params": {
            "from_currency": "Source currency (default: USD)",
            "to_currency": "Target currency (default: SAR)"
        },
        "category": "quick_search",
        "vram_required": False
    },
    "stock_price": {
        "function": "stock_price",
        "description": "Get stock price from Yahoo Finance",
        "params": {"symbol": "Stock symbol (e.g., AAPL, TSLA)"},
        "category": "quick_search",
        "vram_required": False
    },
    "web_search": {
        "function": "web_search_duckduckgo",
        "description": "Quick web search using DuckDuckGo",
        "params": {
            "query": "Search query",
            "max_results": "Maximum results (default: 5)"
        },
        "category": "quick_search",
        "vram_required": False
    },
    "wikipedia": {
        "function": "wikipedia_summary",
        "description": "Get Wikipedia summary for a topic",
        "params": {"topic": "Topic to search on Wikipedia"},
        "category": "quick_search",
        "vram_required": False
    },
    "news": {
        "function": "news_headlines",
        "description": "Get current news headlines",
        "params": {"category": "News category (default: technology)"},
        "category": "quick_search",
        "vram_required": False
    },
    "time": {
        "function": "time_zone",
        "description": "Get current time in any timezone",
        "params": {"timezone": "Timezone (default: Asia/Riyadh)"},
        "category": "quick_search",
        "vram_required": False
    },
    "calculator": {
        "function": "calculator",
        "description": "Evaluate mathematical expressions",
        "params": {"expression": "Math expression to evaluate"},
        "category": "utility",
        "vram_required": False
    }
}


def get_cpu_tool(tool_name: str):
    """Get a CPU tool by name"""
    tools = CPUTools()
    
    if tool_name in CPU_TOOL_REGISTRY:
        func_name = CPU_TOOL_REGISTRY[tool_name]["function"]
        return getattr(tools, func_name)
    
    return None


def list_cpu_tools():
    """List all available CPU tools"""
    return [
        {
            "name": name,
            "description": info["description"],
            "category": info["category"],
            "vram_required": info["vram_required"]
        }
        for name, info in CPU_TOOL_REGISTRY.items()
    ]


# ============================================
# TEST FUNCTIONS
# ============================================

def test_all_tools():
    """Test all CPU tools"""
    tools = CPUTools()
    
    print("=" * 60)
    print("TESTING CPU TOOLS (NO VRAM USAGE)")
    print("=" * 60)
    
    # Test 1: Crypto
    print("\n[1] Crypto Price Test:")
    result = tools.crypto_price("BTC")
    print(f"    BTC Price: ${result.get('price_usd', 'N/A')}")
    
    # Test 2: Weather
    print("\n[2] Weather Test:")
    result = tools.weather("Riyadh")
    print(f"    Riyadh: {result.get('temperature_c', 'N/A')}°C, {result.get('description', 'N/A')}")
    
    # Test 3: Exchange Rate
    print("\n[3] Exchange Rate Test:")
    result = tools.exchange_rate("USD", "SAR")
    print(f"    USD/SAR: {result.get('rate', 'N/A')}")
    
    # Test 4: Web Search
    print("\n[4] Web Search Test:")
    result = tools.web_search_duckduckgo("Python programming")
    if result.get("success"):
        print(f"    Found {len(result.get('results', []))} results")
    
    # Test 5: Calculator
    print("\n[5] Calculator Test:")
    result = tools.calculator("2 + 2 * 10")
    print(f"    2 + 2 * 10 = {result.get('result', 'N/A')}")
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETE - NO VRAM USED!")
    print("=" * 60)


if __name__ == "__main__":
    test_all_tools()
