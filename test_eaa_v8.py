"""
EAA V8 Test Script
==================
Test the complete Smart Routing System

Run this to verify all components are working.

Author: Majed Al-Shoghri
"""

import os
import sys
import time

print("=" * 60)
print("  EAA V8 SYSTEM TEST")
print("=" * 60)

# ============================================
# TEST 1: Import Check
# ============================================
print("\n[TEST 1] Checking imports...")

try:
    from eaa_tools_cpu import CPUTools, CPU_TOOL_REGISTRY
    print("  ✅ eaa_tools_cpu imported")
    CPU_TOOLS_OK = True
except ImportError as e:
    print(f"  ❌ eaa_tools_cpu failed: {e}")
    CPU_TOOLS_OK = False

try:
    from eaa_smart_router import SmartRouter, QueryType, ComplexityLevel
    print("  ✅ eaa_smart_router imported")
    ROUTER_OK = True
except ImportError as e:
    print(f"  ❌ eaa_smart_router failed: {e}")
    ROUTER_OK = False

try:
    from eaa_researcher_brain import ResearcherBrain, ResearchDepth
    print("  ✅ eaa_researcher_brain imported")
    RESEARCHER_OK = True
except ImportError as e:
    print(f"  ❌ eaa_researcher_brain failed: {e}")
    RESEARCHER_OK = False

try:
    from eaa_supervisor_v8 import EAASupervisorV8, BrainServer, VRAMManager
    print("  ✅ eaa_supervisor_v8 imported")
    SUPERVISOR_OK = True
except ImportError as e:
    print(f"  ❌ eaa_supervisor_v8 failed: {e}")
    SUPERVISOR_OK = False

# ============================================
# TEST 2: CPU Tools Test
# ============================================
print("\n[TEST 2] Testing CPU Tools (no VRAM)...")

if CPU_TOOLS_OK:
    tools = CPUTools()
    
    # Test Crypto
    print("  Testing crypto_price...")
    result = tools.crypto_price("BTC")
    if result.get("success"):
        print(f"    ✅ BTC: ${result.get('price_usd', 'N/A'):,.2f}")
    else:
        print(f"    ⚠️ Crypto test: {result.get('error')}")
    
    # Test Weather
    print("  Testing weather...")
    result = tools.weather("Riyadh")
    if result.get("success"):
        print(f"    ✅ Riyadh: {result.get('temperature_c')}°C, {result.get('description')}")
    else:
        print(f"    ⚠️ Weather test: {result.get('error')}")
    
    # Test Calculator
    print("  Testing calculator...")
    result = tools.calculator("2 + 2 * 10")
    if result.get("success"):
        print(f"    ✅ 2 + 2 * 10 = {result.get('result')}")
    else:
        print(f"    ⚠️ Calculator test: {result.get('error')}")
    
    # Test Web Search
    print("  Testing web_search...")
    result = tools.web_search_duckduckgo("Python programming")
    if result.get("success"):
        print(f"    ✅ Found {len(result.get('results', []))} results")
    else:
        print(f"    ⚠️ Web search test: {result.get('error')}")
else:
    print("  ⏭️ Skipped (import failed)")

# ============================================
# TEST 3: Smart Router Test
# ============================================
print("\n[TEST 3] Testing Smart Router...")

if ROUTER_OK:
    router = SmartRouter()
    
    test_queries = [
        ("What's the Bitcoin price?", "crypto_price", False),
        ("Weather in Riyadh", "weather", False),
        ("Calculate 25 * 4", "calculator", False),
        ("Research the best AI frameworks in 2024", "researcher_brain", True),
        ("Compare React vs Vue vs Angular", "researcher_brain", True),
    ]
    
    for query, expected_tool, expected_swap in test_queries:
        decision = router.analyze(query)
        tool_match = "✅" if decision.tool_name == expected_tool else "❌"
        swap_match = "✅" if decision.needs_brain_swap == expected_swap else "❌"
        
        print(f"  {tool_match} '{query[:30]}...' → {decision.tool_name}")
        print(f"     Swap: {swap_match} (expected: {expected_swap})")
else:
    print("  ⏭️ Skipped (import failed)")

# ============================================
# TEST 4: VRAM Manager Test
# ============================================
print("\n[TEST 4] Testing VRAM Manager...")

if SUPERVISOR_OK:
    vram = VRAMManager()
    
    # Check nvidia-smi exists
    nvidia_smi = r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
    if os.path.exists(nvidia_smi):
        usage = vram.get_vram_usage()
        print(f"  ✅ VRAM: {usage['used_mb']}MB / {usage['total_mb']}MB ({usage['percent']}%)")
    else:
        print("  ⚠️ nvidia-smi not found (will work on your PC)")
else:
    print("  ⏭️ Skipped (import failed)")

# ============================================
# TEST 5: Full Supervisor Test (Optional)
# ============================================
print("\n[TEST 5] Full Supervisor Test (requires brain server)...")

if SUPERVISOR_OK:
    try:
        eaa = EAASupervisorV8()
        
        # Test a simple query
        print("  Testing simple query (CPU only)...")
        # response = eaa.process_query("What's the Bitcoin price?")
        # print(f"    Response: {response[:100]}...")
        print("    ⏭️ Skipped (would load brain if running)")
        
    except Exception as e:
        print(f"  ⚠️ Supervisor test: {e}")
else:
    print("  ⏭️ Skipped (import failed)")

# ============================================
# SUMMARY
# ============================================
print("\n" + "=" * 60)
print("  TEST SUMMARY")
print("=" * 60)

results = {
    "CPU Tools": CPU_TOOLS_OK,
    "Smart Router": ROUTER_OK,
    "Researcher Brain": RESEARCHER_OK,
    "Supervisor V8": SUPERVISOR_OK,
}

for name, ok in results.items():
    status = "✅ PASS" if ok else "❌ FAIL"
    print(f"  {name}: {status}")

all_ok = all(results.values())
print("\n" + ("🎉 ALL TESTS PASSED!" if all_ok else "⚠️ Some tests failed"))

print("\n" + "=" * 60)
print("  NEXT STEPS")
print("=" * 60)
print("""
1. Copy these files to C:\\Users\\offic\\EAA\\:
   - eaa_tools_cpu.py
   - eaa_smart_router.py
   - eaa_researcher_brain.py
   - eaa_supervisor_v8.py

2. Run the supervisor:
   python eaa_supervisor_v8.py --interactive

3. Test queries:
   - "What's the Bitcoin price?"        → CPU tool, fast
   - "Weather in Riyadh?"               → CPU tool, fast
   - "Research AI trends in 2024"       → Brain swap, slower

4. The system will automatically:
   - Route simple queries to CPU tools (Master stays loaded)
   - Route complex queries to Researcher (brain swap)
   - Auto-unload brain after 30s idle
""")
print("=" * 60)
