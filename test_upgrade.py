import sys, os
sys.path.insert(0, os.getcwd())
from eaa_agent_tools import create_tool_registry
r = create_tool_registry()
print(f"Base tools: {len(r.list_tools())}")
modules = [
    ("eaa_multimodal_tools", "register_multimodal_tools", "Multimodal"),
    ("eaa_document_tools", "register_document_tools", "Documents"),
    ("eaa_system_tools", "register_system_tools", "System"),
    ("eaa_code_tools", "register_code_tools", "Code"),
    ("eaa_browser_tools", "register_browser_tools", "Browser"),
    ("eaa_communication_tools", "register_communication_tools", "Comms"),
    ("eaa_memory_enhanced", "register_memory_tools", "Memory"),
    ("eaa_data_tools", "register_data_tools", "Data"),
    ("eaa_audio_video_tools", "register_audio_video_tools", "AudioVideo"),
    ("eaa_scheduler_tools", "register_scheduler_tools", "Scheduler"),
]
failed = []
for mod_name, func_name, label in modules:
    try:
        mod = __import__(mod_name, fromlist=[func_name])
        func = getattr(mod, func_name)
        func(r)
        print(f"+ {label}: {len(r.list_tools())} total")
    except Exception as e:
        print(f"x {label}: FAILED - {e}")
        failed.append(label)
print(f"\nTOTAL TOOLS: {len(r.list_tools())}")
if failed:
    print(f"FAILED: {failed}")
else:
    print("ALL MODULES LOADED OK!")
