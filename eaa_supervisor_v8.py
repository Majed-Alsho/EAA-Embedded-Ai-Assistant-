# -*- coding: utf-8 -*-
import os
import json
from datetime import datetime

try:
    from eaa_tools_cpu_v2 import CPUTools
    from eaa_smart_router import SmartRouter
    MODULES_OK = True
except:
    MODULES_OK = False
    print("Warning: Modules not loaded")

class EAASupervisorV8:
    def __init__(self):
        self.cpu_tools = CPUTools() if MODULES_OK else None
        self.router = SmartRouter() if MODULES_OK else None
        self.history = []
        print("[EAA V8] Initialized")
    
    def process_query(self, query):
        print("[Query] " + query)
        if not MODULES_OK:
            return "Error: Modules not loaded"
        decision = self.router.analyze(query)
        print("[Router] -> " + decision.tool_name)
        if decision.tool_name in ["crypto_price", "btc"]:
            result = self.cpu_tools.btc()
            return "Bitcoin: $" + str(result)
        elif decision.tool_name == "weather":
            result = self.cpu_tools.weather()
            return "Temperature: " + str(result) + "C"
        return "Tool: " + decision.tool_name

if __name__ == "__main__":
    eaa = EAASupervisorV8()
    print("\n--- TEST 1 ---")
    r1 = eaa.process_query("What is BTC price?")
    print("\n--- TEST 2 ---")
    r2 = eaa.process_query("Weather in Riyadh?")
