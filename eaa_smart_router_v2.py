import re
from enum import Enum
from dataclasses import dataclass

class Complexity(Enum):
    SIMPLE = "simple"
    COMPLEX = "complex"

@dataclass
class Route:
    tool: str
    swap: bool
    reason: str

def route_query(q):
    q = q.lower()
    complex_patterns = ["research", "analyze", "compare", "vs", "top 10", "best 5", "comprehensive", "deep dive"]
    if any(p in q for p in complex_patterns):
        return Route("researcher", True, "Complex query detected")
    if "btc" in q or "bitcoin" in q or "crypto" in q:
        return Route("crypto_price", False, "Crypto query")
    if "weather" in q:
        return Route("weather", False, "Weather query")
    if "price" in q and ("stock" in q or "apple" in q or "tesla" in q):
        return Route("stock_price", False, "Stock query")
    return Route("web_search", False, "Default web search")

if __name__ == "__main__":
    tests = [
        "What is BTC price?",
        "Research AI trends 2024",
        "Weather in Riyadh",
        "Compare React vs Vue",
        "Top 10 programming languages"
    ]
    for t in tests:
        r = route_query(t)
        swap = "SWAP" if r.swap else "CPU"
        print(f"{t[:30]:30} -> {r.tool:15} [{swap}] {r.reason}")
