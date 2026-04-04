"""
EAA Smart Router - Query Complexity Analyzer & Router
======================================================
Analyzes user queries and routes to appropriate tools:
- Simple queries → CPU Tools (Master stays loaded)
- Complex queries → Researcher Brain (brain swap)

Author: Majed Al-Shoghri
Version: 1.1 - Improved complex query detection
"""

import re
import os
import json
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
from datetime import datetime


class QueryType(Enum):
    """Types of queries the router can handle"""
    CRYPTO_PRICE = "crypto_price"
    STOCK_PRICE = "stock_price"
    WEATHER = "weather"
    EXCHANGE_RATE = "exchange_rate"
    WIKIPEDIA = "wikipedia"
    WEB_SEARCH_SIMPLE = "web_search_simple"
    NEWS = "news"
    TIME = "time"
    CALCULATOR = "calculator"
    RESEARCH_COMPLEX = "research_complex"
    UNKNOWN = "unknown"


class ComplexityLevel(Enum):
    """Query complexity levels"""
    SIMPLE = "simple"      # CPU tool, no brain swap
    MODERATE = "moderate"  # CPU tool + maybe extra processing
    COMPLEX = "complex"    # Requires Researcher Brain (brain swap)


@dataclass
class RoutingDecision:
    """Result of routing analysis"""
    query_type: QueryType
    complexity: ComplexityLevel
    tool_name: str
    tool_params: Dict[str, Any]
    needs_brain_swap: bool
    reason: str
    confidence: float


class SmartRouter:
    """
    Intelligent query router that analyzes user queries
    and determines the best tool/brain to use.
    """
    
    def __init__(self):
        # Patterns for simple queries
        self.patterns = {
            QueryType.CRYPTO_PRICE: [
                r"(?i)(bitcoin|btc|ethereum|eth|solana|sol|doge|dogecoin|xrp|ada|cardano)\s*(price|worth|value|cost)",
                r"(?i)what'?s?\s+(the\s+)?(bitcoin|btc|ethereum|eth|crypto)",
                r"(?i)(price|value|worth)\s+(of\s+)?(bitcoin|btc|eth|ethereum)",
                r"(?i)how much (is|does)\s+(a\s+)?(bitcoin|btc|eth|ethereum)\s+(cost|worth)",
            ],
            QueryType.STOCK_PRICE: [
                r"(?i)(stock|share|shares)\s+(price|value|worth)",
                r"(?i)(aapl|tsla|googl|goog|msft|nvda|meta|amzn|nflx)\s*(price|stock)",
                r"(?i)(apple|tesla|google|microsoft|nvidia|amazon|netflix)\s*(stock|price|shares)",
                r"(?i)price\s+(of\s+)?(aapl|tsla|googl|msft|nvda)",
            ],
            QueryType.WEATHER: [
                r"(?i)weather\s+(in|at|for|today)",
                r"(?i)(what'?s?\s+the\s+)?weather",
                r"(?i)(temperature|temp|how\s+(hot|cold|warm))",
                r"(?i)(is\s+it\s+(raining|sunny|cloudy|cold|hot))",
                r"(?i)(forecast|humidity|wind)",
            ],
            QueryType.EXCHANGE_RATE: [
                r"(?i)(exchange\s+rate|currency\s+rate)",
                r"(?i)(usd|eur|gbp|sar|jpy|cny)\s*(to|in|vs)\s*(usd|eur|gbp|sar|jpy|cny)",
                r"(?i)(dollar|euro|pound|riyal|yen|yuan)\s*(to|in|vs)",
                r"(?i)how\s+much\s+(is\s+)?(\d+)?\s*(usd|eur|gbp|sar)\s*(in|to)",
            ],
            QueryType.WIKIPEDIA: [
                r"(?i)(who\s+is|what\s+is|tell\s+me\s+about)\s+\w+\s*(\w+)?(\?)?$",
                r"(?i)(wikipedia|wiki)\s+",
                r"(?i)( biography|history|definition|explain)",
            ],
            QueryType.WEB_SEARCH_SIMPLE: [
                r"(?i)(search|google|look\s+up|find)\s+(for\s+)?",
                r"(?i)what\s+is\s+\w+",
                r"(?i)who\s+(is|was|are|were)\s+",
                r"(?i)when\s+(is|was|did)\s+",
                r"(?i)where\s+(is|was|are)\s+",
            ],
            QueryType.NEWS: [
                r"(?i)(news|headlines|latest|breaking|today'?s?\s+news)",
                r"(?i)what'?s?\s+(the\s+)?(latest|current)\s+news",
                r"(?i)(tech|technology|business|sports)\s+news",
            ],
            QueryType.TIME: [
                r"(?i)what\s+time\s+(is\s+it|is\s+it\s+in)",
                r"(?i)current\s+time",
                r"(?i)time\s+(in|at)\s+",
                r"(?i)(date|day)\s+(today|is\s+it)",
            ],
            QueryType.CALCULATOR: [
                r"(?i)(calculate|compute|what\s+is)\s+[\d\+\-\*\/\.\(\)\s]+",
                r"(?i)[\d]+\s*[\+\-\*\/\^]\s*[\d]+",
                r"(?i)what\s+(is\s+)?[\d]+\s*(plus|minus|times|divided|multiplied)",
            ],
        }
        
        # Complex research indicators - MUST CHECK FIRST
        self.complex_indicators = [
            r"(?i)\bresearch\b",
            r"(?i)\banalyze\b",
            r"(?i)\binvestigate\b",
            r"(?i)\bdeep\s+dive\b",
            r"(?i)\bcomprehensive\b",
            r"(?i)\bdetailed\b",
            r"(?i)\bcompare\b.*\bvs\b",
            r"(?i)\bcompare\b.*\band\b",
            r"(?i)\bcomparison\b",
            r"(?i)\bpros\s+and\s+cons\b",
            r"(?i)\badvantages\s+and\s+disadvantages\b",
            r"(?i)\bmultiple\s+(sources|websites|pages)\b",
            r"(?i)\bexplain\s+in\s+detail\b",
            r"(?i)\btell\s+me\s+everything\b",
            r"(?i)\bwrite\s+a\s+(report|article|summary|essay)\b",
            r"(?i)\bgather\s+information\b",
            r"(?i)\bcollect\s+data\b",
            r"(?i)\bfind\s+out\s+more\b",
            r"(?i)\bmarket\s+analysis\b",
            r"(?i)\bindustry\s+research\b",
            r"(?i)\bcompetitive\b.*\banalysis\b",
            r"(?i)\bstep\s+by\s+step\s+guide\b",
            r"(?i)\bhow\s+do\s+i\b.*\bstep\b",
            r"(?i)\btop\s+\d+\b",
            r"(?i)\bbest\s+\d+\b",
            r"(?i)\bworst\s+\d+\b",
            r"(?i)\breview\b.*\b\d+\b",
        ]
        
        # Simple queries that NEVER need brain swap
        self.simple_queries = [
            "price", "weather", "time", "date", "temperature",
            "how much", "how many", "what is the", "current"
        ]
    
    def analyze(self, query: str) -> RoutingDecision:
        """
        Analyze a query and determine routing
        
        Args:
            query: User's query text
            
        Returns:
            RoutingDecision with tool and parameters
        """
        query = query.strip()
        query_lower = query.lower()
        
        # Step 1: Check for complex research indicators FIRST
        for pattern in self.complex_indicators:
            if re.search(pattern, query):
                # Determine depth based on query
                depth = "standard"
                if any(word in query_lower for word in ["comprehensive", "deep", "detailed", "everything"]):
                    depth = "deep"
                elif any(word in query_lower for word in ["quick", "brief", "simple"]):
                    depth = "quick"
                
                return RoutingDecision(
                    query_type=QueryType.RESEARCH_COMPLEX,
                    complexity=ComplexityLevel.COMPLEX,
                    tool_name="researcher_brain",
                    tool_params={"query": query, "depth": depth},
                    needs_brain_swap=True,
                    reason=f"Complex research query detected (pattern: {pattern[:30]}...)",
                    confidence=0.9
                )
        
        # Step 2: Check for comparison patterns (X vs Y)
        if re.search(r"(?i)\b\w+\s+vs\s+\w+", query) or re.search(r"(?i)\bcompare\b", query):
            return RoutingDecision(
                query_type=QueryType.RESEARCH_COMPLEX,
                complexity=ComplexityLevel.COMPLEX,
                tool_name="researcher_brain",
                tool_params={"query": query, "depth": "standard"},
                needs_brain_swap=True,
                reason="Comparison query requires research",
                confidence=0.85
            )
        
        # Step 3: Check for "top N" or "best N" patterns
        if re.search(r"(?i)(top|best|worst)\s+\d+", query):
            return RoutingDecision(
                query_type=QueryType.RESEARCH_COMPLEX,
                complexity=ComplexityLevel.COMPLEX,
                tool_name="researcher_brain",
                tool_params={"query": query, "depth": "standard"},
                needs_brain_swap=True,
                reason="Ranked list query requires research",
                confidence=0.85
            )
        
        # Step 4: Match against simple patterns
        for query_type, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, query):
                    return self._create_decision(query_type, query)
        
        # Step 5: Keyword-based detection
        keyword_decision = self._keyword_detection(query)
        if keyword_decision:
            return keyword_decision
        
        # Step 6: Default to simple web search
        return RoutingDecision(
            query_type=QueryType.WEB_SEARCH_SIMPLE,
            complexity=ComplexityLevel.SIMPLE,
            tool_name="web_search",
            tool_params={"query": query, "max_results": 5},
            needs_brain_swap=False,
            reason="Default: treat as simple web search",
            confidence=0.6
        )
    
    def _check_complexity(self, query: str) -> Tuple[ComplexityLevel, str]:
        """Check if query needs complex research"""
        query_lower = query.lower()
        
        # Count complex indicators
        complex_count = 0
        matched_indicators = []
        
        for pattern in self.complex_indicators:
            if re.search(pattern, query):
                complex_count += 1
                matched_indicators.append(re.search(pattern, query).group())
        
        # Check for multiple questions/topics
        if query.count('?') > 1:
            complex_count += 1
            matched_indicators.append("multiple questions")
        
        # Check query length (longer = more complex)
        if len(query.split()) > 15:
            complex_count += 1
            matched_indicators.append("long query")
        
        # Check for "and" connecting multiple topics
        topic_count = len(re.findall(r'\b(and|also|plus|additionally)\b', query_lower))
        if topic_count >= 2:
            complex_count += 1
            matched_indicators.append("multiple topics")
        
        if complex_count >= 2:
            return (
                ComplexityLevel.COMPLEX,
                f"Complex query detected: {', '.join(matched_indicators[:3])}"
            )
        elif complex_count == 1:
            return (
                ComplexityLevel.MODERATE,
                f"Moderate complexity: {matched_indicators[0]}"
            )
        
        return (
            ComplexityLevel.SIMPLE,
            "Simple query - CPU tools sufficient"
        )
    
    def _create_decision(self, query_type: QueryType, query: str) -> RoutingDecision:
        """Create routing decision for known query types"""
        
        decisions = {
            QueryType.CRYPTO_PRICE: lambda q: RoutingDecision(
                query_type=query_type,
                complexity=ComplexityLevel.SIMPLE,
                tool_name="crypto_price",
                tool_params=self._extract_crypto_params(q),
                needs_brain_swap=False,
                reason="Crypto price lookup - CPU tool",
                confidence=0.9
            ),
            QueryType.STOCK_PRICE: lambda q: RoutingDecision(
                query_type=query_type,
                complexity=ComplexityLevel.SIMPLE,
                tool_name="stock_price",
                tool_params=self._extract_stock_params(q),
                needs_brain_swap=False,
                reason="Stock price lookup - CPU tool",
                confidence=0.9
            ),
            QueryType.WEATHER: lambda q: RoutingDecision(
                query_type=query_type,
                complexity=ComplexityLevel.SIMPLE,
                tool_name="weather",
                tool_params=self._extract_weather_params(q),
                needs_brain_swap=False,
                reason="Weather lookup - CPU tool",
                confidence=0.9
            ),
            QueryType.EXCHANGE_RATE: lambda q: RoutingDecision(
                query_type=query_type,
                complexity=ComplexityLevel.SIMPLE,
                tool_name="exchange_rate",
                tool_params=self._extract_exchange_params(q),
                needs_brain_swap=False,
                reason="Exchange rate lookup - CPU tool",
                confidence=0.9
            ),
            QueryType.WIKIPEDIA: lambda q: RoutingDecision(
                query_type=query_type,
                complexity=ComplexityLevel.MODERATE,
                tool_name="wikipedia",
                tool_params={"topic": self._extract_topic(q)},
                needs_brain_swap=False,
                reason="Wikipedia lookup - CPU tool",
                confidence=0.85
            ),
            QueryType.WEB_SEARCH_SIMPLE: lambda q: RoutingDecision(
                query_type=query_type,
                complexity=ComplexityLevel.SIMPLE,
                tool_name="web_search",
                tool_params={"query": q, "max_results": 5},
                needs_brain_swap=False,
                reason="Simple web search - CPU tool",
                confidence=0.8
            ),
            QueryType.NEWS: lambda q: RoutingDecision(
                query_type=query_type,
                complexity=ComplexityLevel.SIMPLE,
                tool_name="news",
                tool_params={"category": self._extract_news_category(q)},
                needs_brain_swap=False,
                reason="News lookup - CPU tool",
                confidence=0.9
            ),
            QueryType.TIME: lambda q: RoutingDecision(
                query_type=query_type,
                complexity=ComplexityLevel.SIMPLE,
                tool_name="time",
                tool_params={"timezone": self._extract_timezone(q)},
                needs_brain_swap=False,
                reason="Time lookup - CPU tool",
                confidence=0.9
            ),
            QueryType.CALCULATOR: lambda q: RoutingDecision(
                query_type=query_type,
                complexity=ComplexityLevel.SIMPLE,
                tool_name="calculator",
                tool_params={"expression": self._extract_math(q)},
                needs_brain_swap=False,
                reason="Calculator - CPU tool",
                confidence=0.95
            ),
        }
        
        if query_type in decisions:
            return decisions[query_type](query)
        
        return RoutingDecision(
            query_type=QueryType.UNKNOWN,
            complexity=ComplexityLevel.SIMPLE,
            tool_name="web_search",
            tool_params={"query": query},
            needs_brain_swap=False,
            reason="Unknown type - defaulting to web search",
            confidence=0.5
        )
    
    def _keyword_detection(self, query: str) -> Optional[RoutingDecision]:
        """Fallback keyword-based detection"""
        query_lower = query.lower()
        
        # Crypto keywords
        crypto_keywords = ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "doge"]
        if any(kw in query_lower for kw in crypto_keywords):
            if any(kw in query_lower for kw in ["price", "worth", "value", "cost", "how much"]):
                return self._create_decision(QueryType.CRYPTO_PRICE, query)
        
        # Weather keywords
        weather_keywords = ["weather", "temperature", "rain", "sunny", "forecast", "hot", "cold"]
        if any(kw in query_lower for kw in weather_keywords):
            return self._create_decision(QueryType.WEATHER, query)
        
        # Time keywords
        if "time" in query_lower or "date" in query_lower:
            return self._create_decision(QueryType.TIME, query)
        
        # News keywords
        if "news" in query_lower or "headline" in query_lower:
            return self._create_decision(QueryType.NEWS, query)
        
        return None
    
    # ============================================
    # PARAMETER EXTRACTION HELPERS
    # ============================================
    
    def _extract_crypto_params(self, query: str) -> Dict[str, str]:
        """Extract cryptocurrency symbol from query"""
        query_lower = query.lower()
        
        symbols = {
            "bitcoin": "BTC", "btc": "BTC",
            "ethereum": "ETH", "eth": "ETH",
            "solana": "SOL", "sol": "SOL",
            "doge": "DOGE", "dogecoin": "DOGE",
            "xrp": "XRP", "ripple": "XRP",
            "ada": "ADA", "cardano": "ADA",
            "dot": "DOT", "polkadot": "DOT",
            "bnb": "BNB", "binance": "BNB"
        }
        
        for name, symbol in symbols.items():
            if name in query_lower:
                return {"symbol": symbol}
        
        return {"symbol": "BTC"}  # Default
    
    def _extract_stock_params(self, query: str) -> Dict[str, str]:
        """Extract stock symbol from query"""
        query_upper = query.upper()
        
        # Common stock symbols
        symbols = ["AAPL", "TSLA", "GOOGL", "GOOG", "MSFT", "NVDA", "META", 
                   "AMZN", "NFLX", "DIS", "BABA", "TSM", "V", "JPM", "WMT"]
        
        for symbol in symbols:
            if symbol in query_upper:
                return {"symbol": symbol}
        
        # Company names
        companies = {
            "apple": "AAPL", "tesla": "TSLA", "google": "GOOGL",
            "microsoft": "MSFT", "nvidia": "NVDA", "meta": "META",
            "facebook": "META", "amazon": "AMZN", "netflix": "NFLX"
        }
        
        query_lower = query.lower()
        for name, symbol in companies.items():
            if name in query_lower:
                return {"symbol": symbol}
        
        return {"symbol": "AAPL"}  # Default
    
    def _extract_weather_params(self, query: str) -> Dict[str, str]:
        """Extract city from weather query"""
        # Common cities
        cities = [
            "riyadh", "jeddah", "mecca", "medina", "dammam",
            "dubai", "abu dhabi", "cairo", "london", "new york",
            "paris", "tokyo", "singapore", "sydney", "toronto",
            "berlin", "moscow", "beijing", "mumbai", "istanbul"
        ]
        
        query_lower = query.lower()
        for city in cities:
            if city in query_lower:
                return {"city": city.title()}
        
        # Try to extract city after "in" or "for"
        match = re.search(r'(?:in|at|for)\s+([A-Za-z]+)', query_lower)
        if match:
            return {"city": match.group(1).title()}
        
        return {"city": "Riyadh"}  # Default
    
    def _extract_exchange_params(self, query: str) -> Dict[str, str]:
        """Extract currencies from exchange query"""
        query_upper = query.upper()
        
        currencies = ["USD", "EUR", "GBP", "SAR", "JPY", "CNY", "INR", "AUD", "CAD", "CHF"]
        
        found = []
        for curr in currencies:
            if curr in query_upper:
                found.append(curr)
        
        if len(found) >= 2:
            return {"from_currency": found[0], "to_currency": found[1]}
        elif len(found) == 1:
            if found[0] != "SAR":
                return {"from_currency": found[0], "to_currency": "SAR"}
            return {"from_currency": "USD", "to_currency": "SAR"}
        
        return {"from_currency": "USD", "to_currency": "SAR"}  # Default
    
    def _extract_topic(self, query: str) -> str:
        """Extract topic for Wikipedia/search"""
        # Remove common prefixes
        prefixes = [
            r"(?i)^who\s+is\s+",
            r"(?i)^what\s+is\s+",
            r"(?i)^tell\s+me\s+about\s+",
            r"(?i)^wikipedia\s+",
            r"(?i)^wiki\s+",
            r"(?i)^search\s+(for\s+)?",
            r"(?i)^look\s+up\s+",
            r"(?i)^find\s+",
        ]
        
        topic = query
        for prefix in prefixes:
            topic = re.sub(prefix, "", topic)
        
        # Remove question mark
        topic = topic.replace("?", "").strip()
        
        return topic
    
    def _extract_news_category(self, query: str) -> str:
        """Extract news category"""
        query_lower = query.lower()
        
        categories = {
            "tech": "technology", "technology": "technology",
            "business": "business", "finance": "business",
            "sports": "sports", "sport": "sports",
            "science": "science", "health": "health",
            "entertainment": "entertainment"
        }
        
        for keyword, category in categories.items():
            if keyword in query_lower:
                return category
        
        return "technology"  # Default
    
    def _extract_timezone(self, query: str) -> str:
        """Extract timezone from query"""
        query_lower = query.lower()
        
        timezones = {
            "riyadh": "Asia/Riyadh",
            "saudi": "Asia/Riyadh",
            "dubai": "Asia/Dubai",
            "london": "Europe/London",
            "new york": "America/New_York",
            "tokyo": "Asia/Tokyo",
            "paris": "Europe/Paris",
            "sydney": "Australia/Sydney",
            "singapore": "Asia/Singapore",
            "india": "Asia/Kolkata",
            "mumbai": "Asia/Kolkata",
            "beijing": "Asia/Shanghai",
            "shanghai": "Asia/Shanghai",
            "moscow": "Europe/Moscow",
            "berlin": "Europe/Berlin",
            "los angeles": "America/Los_Angeles",
            "california": "America/Los_Angeles",
            "chicago": "America/Chicago",
            "utc": "UTC",
            "gmt": "GMT"
        }
        
        for city, tz in timezones.items():
            if city in query_lower:
                return tz
        
        return "Asia/Riyadh"  # Default
    
    def _extract_math(self, query: str) -> str:
        """Extract math expression from query"""
        # Remove words, keep math
        math_pattern = r'[\d\.\+\-\*\/\^\(\)\s]+'
        matches = re.findall(math_pattern, query)
        
        if matches:
            # Find longest match
            expr = max(matches, key=len).strip()
            return expr
        
        return query


# ============================================
# CONVENIENCE FUNCTIONS
# ============================================

def route_query(query: str) -> RoutingDecision:
    """Convenience function to route a query"""
    router = SmartRouter()
    return router.analyze(query)


def get_routing_info(decision: RoutingDecision) -> str:
    """Get human-readable routing info"""
    info = f"""
┌─────────────────────────────────────────┐
│ ROUTING DECISION                        │
├─────────────────────────────────────────┤
│ Type:       {decision.query_type.value:<24} │
│ Complexity: {decision.complexity.value:<24} │
│ Tool:       {decision.tool_name:<24} │
│ Brain Swap: {str(decision.needs_brain_swap):<24} │
│ Confidence: {f"{decision.confidence:.0%}":<24} │
│ Reason:     {decision.reason[:24]:<24} │
└─────────────────────────────────────────┘
"""
    return info


# ============================================
# TEST FUNCTION
# ============================================

def test_router():
    """Test the smart router with various queries"""
    router = SmartRouter()
    
    test_queries = [
        # Simple queries
        "What's the Bitcoin price?",
        "How's the weather in Riyadh?",
        "What time is it?",
        "Calculate 25 * 4 + 10",
        "USD to SAR exchange rate",
        "What's the latest tech news?",
        
        # Moderate queries
        "Who is Elon Musk?",
        "What is quantum computing?",
        "Search for Python tutorials",
        
        # Complex queries
        "Research the best electric cars in 2024 and compare their features",
        "Do a comprehensive analysis of the AI market",
        "Compare the pros and cons of React vs Vue vs Angular",
        "What are the top 10 programming languages to learn in 2024?",
    ]
    
    print("=" * 70)
    print("SMART ROUTER TEST")
    print("=" * 70)
    
    for query in test_queries:
        decision = router.analyze(query)
        swap_indicator = "🔄 SWAP" if decision.needs_brain_swap else "✅ CPU"
        
        print(f"\nQuery: \"{query[:50]}{'...' if len(query) > 50 else ''}\"")
        print(f"→ {swap_indicator} | Tool: {decision.tool_name} | Complexity: {decision.complexity.value}")
        print(f"   Reason: {decision.reason}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_router()
