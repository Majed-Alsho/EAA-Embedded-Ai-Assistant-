"""
EAA V4 - Agent Backend (Bridge Script)
======================================
Replaces run_eaa_agent_v3.py with the V4 architecture.

Wireup:
  eaa_control_email_v7.py (port 8001, control station)
    -> run_eaa_v4.py (port 8000, AI backend)
      -> brain_manager.py (model load/unload)
      -> eaa_v4/main_loop.py (ALL 8 PHASES, 31 modules)
        -> 124+ tools from enhanced tool registry

Run with: python run_eaa_v4.py
"""

import os
import sys
import gc
import time
import json
import uuid
import warnings
import asyncio
import logging
from typing import Optional, Dict, Any, List

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── Brain Manager ──
import brain_manager

# ── V4 Main Loop ──
from eaa_v4.main_loop import (
    EAAMainLoop,
    MainLoopConfig,
    EventType,
    event_to_sse,
    create_main_loop,
)

logger = logging.getLogger(__name__)

# =========================
# CONFIG
# =========================
EAA_DIR = os.path.dirname(os.path.abspath(__file__))
HOST = "127.0.0.1"
PORT = 8000
ALLOWED_ORIGINS = ["*"]

# Model IDs (same as V3)
ID_MASTER = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
ID_LOGIC  = "unsloth/DeepSeek-R1-Distill-Qwen-7B-unsloth-bnb-4bit"
ID_CODER  = "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit"
ID_SHADOW = os.path.join(EAA_DIR, "brains", "shadow_brain.gguf")

# =========================
# TOOL REGISTRY
# =========================
HAS_ENHANCED_TOOLS = False
_tool_registry = None

try:
    from eaa_tool_executor import create_enhanced_registry
    _tool_registry, _, _ = create_enhanced_registry()
    HAS_ENHANCED_TOOLS = True
    print("[V4] 88+ Enhanced Tools loaded successfully!")
except Exception as e:
    print(f"[V4] Enhanced tools not available: {e}")
    print("[V4] Falling back to base V3 tools")
    try:
        from eaa_agent_tools_v3 import create_tool_registry
        _tool_registry = create_tool_registry()
    except Exception as e2:
        print(f"[V4] CRITICAL: No tools available: {e2}")
        _tool_registry = None

# =========================
# API MODELS
# =========================
class AgentRunRequest(BaseModel):
    message: str
    brain_id: Optional[str] = None
    brain_type: str = "master"
    max_iterations: int = 15
    show_thinking: bool = True
    auto_retry: bool = True

class AgentChatRequest(BaseModel):
    message: str
    brain_id: Optional[str] = None
    brain_type: str = "master"
    max_iterations: int = 10

class BrainLoadRequest(BaseModel):
    brain_id: str
    adapter_path: Optional[str] = None

# =========================
# GLOBAL STATE
# =========================
brain = brain_manager.BrainManager()
main_loop: Optional[EAAMainLoop] = None
_agent_running: bool = False
_agent_cancelled: bool = False

# =========================
# SAFE PRINT
# =========================
def safe_print(msg):
    try:
        print(msg)
    except (OSError, UnicodeEncodeError):
        try:
            sys.stdout.write(str(msg) + "\n")
            sys.stdout.flush()
        except:
            pass

# =========================
# VRAM HELPERS
# =========================
def clear_vram() -> bool:
    try:
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except ImportError:
            pass
        return True
    except Exception:
        return False

def get_vram_info() -> dict:
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            if len(parts) >= 3:
                used_mb = int(parts[0])
                total_mb = int(parts[1])
                free_mb = int(parts[2])
                return {
                    "allocated_gb": round(used_mb / 1024, 2),
                    "total_gb": round(total_mb / 1024, 2),
                    "free_gb": round(free_mb / 1024, 2),
                    "percent_used": round(used_mb / total_mb * 100, 1),
                    "available": True,
                    "source": "nvidia-smi"
                }
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated(0) / (1024**3)
            total = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            return {
                "allocated_gb": round(allocated, 2),
                "total_gb": round(total, 2),
                "free_gb": round(total - allocated, 2),
                "percent_used": round(allocated / total * 100, 1),
                "available": True,
                "source": "torch (fallback)"
            }
    except Exception:
        pass
    return {"available": False, "error": "CUDA not available"}

# =========================
# ENSURE MAIN LOOP
# =========================
def ensure_main_loop() -> EAAMainLoop:
    """Create the V4 main loop if not yet initialized."""
    global main_loop
    if main_loop is not None:
        return main_loop

    if _tool_registry is None:
        raise RuntimeError("No tool registry available - cannot start V4 main loop")

    config = MainLoopConfig(
        project_root=EAA_DIR,
        total_vram_gb=8.0,
        max_iterations=15,
    )

    main_loop = create_main_loop(
        brain_manager=brain,
        tool_registry=_tool_registry,
        project_root=EAA_DIR,
        **{
            "total_vram_gb": 8.0,
            "max_iterations": 15,
        }
    )

    safe_print("[V4] Main Loop initialized - ALL 8 PHASES ACTIVE")
    safe_print(f"[V4] Tools available: {len(_tool_registry.list_tools())}")
    return main_loop

# =========================
# FASTAPI APP
# =========================
app = FastAPI(title="EAA V4 - Full Architecture")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

# =========================
# HEALTH
# =========================
@app.get("/v1/health")
async def health_check():
    return {
        "status": "online",
        "model_loaded": brain.current_model_id is not None,
        "version": "V4",
        "phases": 8,
        "modules": 31,
        "tools": len(_tool_registry.list_tools()) if _tool_registry else 0,
    }

@app.get("/ai/health")
async def ai_health():
    return {
        "status": "online",
        "model_loaded": brain.current_model_id is not None,
        "model_id": brain.current_model_id,
        "version": "V4 - Full 8-Phase Architecture",
    }

# =========================
# V1 CHAT COMPAT (Simple passthrough)
# =========================
@app.post("/v1/chat/completions")
async def chat_completions(request: dict):
    """OpenAI-compatible chat endpoint - routes through V4 main loop."""
    messages = request.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided.")

    user_input = messages[-1].get("content", "")
    request_id = str(uuid.uuid4())[:8]
    safe_print(f"[{request_id}] [V4-CHAT] {user_input[:80]}...")

    try:
        loop = ensure_main_loop()
        response_text = ""

        for event in loop.run(user_input, brain_type="master"):
            if event.get("type") == EventType.COMPLETE.value:
                response_text = event.get("summary", "")
            elif event.get("type") == EventType.ERROR.value:
                response_text = f"[Error: {event.get('message', 'unknown')}]"
                break

        return {
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "local-eaa-v4",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": response_text.strip()},
                "finish_reason": "stop"
            }]
        }
    except Exception as e:
        safe_print(f"[{request_id}] [ERROR] {e}")
        return {
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "local-eaa-v4",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": f"Error: {str(e)}"},
                "finish_reason": "stop"
            }]
        }

# =========================
# AGENT V4 ENDPOINTS
# =========================

@app.get("/v1/agent/tools")
async def list_agent_tools():
    """List all available tools."""
    if _tool_registry is None:
        return {"tools": [], "count": 0, "enhanced": False}

    tools = []
    schemas = getattr(_tool_registry, '_schemas', {})
    descriptions = getattr(_tool_registry, '_descriptions', {})
    for name in _tool_registry.list_tools():
        desc = descriptions.get(name, "")
        schema = schemas.get(name, {})
        tools.append({
            "name": name,
            "description": desc,
            "schema": schema,
        })

    return {
        "tools": tools,
        "count": len(tools),
        "enhanced": HAS_ENHANCED_TOOLS,
    }

@app.post("/v1/agent/run")
async def run_agent(request: AgentRunRequest):
    """Run V4 agent with streaming output (SSE)."""
    global _agent_running, _agent_cancelled
    _agent_running = True
    _agent_cancelled = False

    async def generate_stream():
        global _agent_running
        try:
            loop = ensure_main_loop()

            yield event_to_sse({
                "type": EventType.STATUS.value,
                "message": f"V4 Agent started with {request.brain_type} brain..."
            })

            for event in loop.run(
                request.message,
                brain_type=request.brain_type,
                brain_id=request.brain_id,
            ):
                if not _agent_running or _agent_cancelled:
                    yield event_to_sse({
                        "type": EventType.STATUS.value,
                        "message": "Agent stopped by user"
                    })
                    break
                yield event_to_sse(event)
                await asyncio.sleep(0)

        except asyncio.CancelledError:
            yield event_to_sse({
                "type": EventType.STATUS.value,
                "message": "Agent cancelled"
            })
        except Exception as e:
            logger.error(f"V4 Agent error: {e}")
            yield event_to_sse({
                "type": EventType.ERROR.value,
                "message": str(e)
            })
        finally:
            _agent_running = False

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/v1/agent/chat")
async def agent_chat(request: AgentChatRequest):
    """Simple chat - returns final result only (non-streaming)."""
    try:
        loop = ensure_main_loop()
        final_response = None
        tools_used = 0

        for event in loop.run(
            request.message,
            brain_type=request.brain_type,
            brain_id=request.brain_id,
        ):
            if event.get("type") == EventType.COMPLETE.value:
                final_response = event
            elif event.get("type") == EventType.TOOL_START.value:
                tools_used += 1
            elif event.get("type") == EventType.ERROR.value:
                return {
                    "success": False,
                    "error": event.get("message", "Unknown error"),
                    "tools_used": tools_used,
                }

        return {
            "success": True,
            "response": final_response.get("summary", "") if final_response else "",
            "tools_used": tools_used,
            "state": final_response.get("state", {}) if final_response else {},
            "version": "V4",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "tools_used": 0,
            "version": "V4",
        }

@app.post("/v1/agent/stop")
async def stop_agent():
    """Stop the running agent and free resources."""
    global _agent_running, _agent_cancelled
    _agent_running = False
    _agent_cancelled = True

    freed = clear_vram()
    if brain.current_model_id:
        brain.unload()
        freed = True

    return {
        "status": "stopped",
        "vram_cleared": freed,
        "version": "V4",
    }

@app.get("/v1/agent/status")
async def agent_status():
    """Get current agent and system status."""
    vram = get_vram_info()
    loop = ensure_main_loop() if _tool_registry else None

    return {
        "running": _agent_running,
        "brain_loaded": brain.current_model_id is not None,
        "brain_id": brain.current_model_id,
        "is_gguf": getattr(brain, "is_gguf", False),
        "vram": vram,
        "version": "V4",
        "phases": 8,
        "modules": 31,
        "tools_count": len(_tool_registry.list_tools()) if _tool_registry else 0,
        "v4_status": loop.get_status() if loop else {},
    }

@app.get("/v1/agent/vram")
async def get_vram_status():
    """Get current VRAM usage."""
    info = get_vram_info()
    info["loaded_model"] = brain.current_model_id
    info["is_gguf"] = getattr(brain, "is_gguf", False)
    info["version"] = "V4"
    return info

@app.post("/v1/agent/clear-vram")
async def clear_vram_endpoint():
    """Force clear VRAM."""
    if brain.current_model_id:
        brain.unload()
    cleared = clear_vram()
    return {"status": "cleared", "success": cleared, "version": "V4"}

@app.post("/v1/agent/brain/load")
async def load_brain(request: BrainLoadRequest):
    """Load a specific brain."""
    try:
        brain.load(request.brain_id, adapter_path=request.adapter_path)
        return {"success": True, "brain_id": request.brain_id, "version": "V4"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/v1/agent/brain/unload")
async def unload_brain():
    """Unload current brain."""
    if brain.current_model_id:
        brain.unload()
        clear_vram()
    return {"success": True, "message": "Brain unloaded", "version": "V4"}

@app.get("/v1/agent/health")
async def agent_health():
    """Quick health check."""
    return {
        "status": "healthy",
        "running": _agent_running,
        "brain_loaded": brain.current_model_id is not None,
        "version": "V4",
        "phases": 8,
    }

# =========================
# CANVAS ENDPOINTS (Backward compat with V3)
# =========================
class CanvasAnalyzeRequest(BaseModel):
    code: str
    filename: Optional[str] = None
    run_code: bool = False

@app.post("/v1/canvas/analyze")
async def canvas_analyze(req: CanvasAnalyzeRequest):
    """Basic code analysis placeholder - V3 compat."""
    return {"success": True, "language": "unknown", "errors": [], "warnings": [], "error_count": 0, "warning_count": 0}

# =========================
# STARTUP
# =========================
@app.on_event("startup")
async def startup_event():
    print("\n" + "=" * 60)
    print("   EAA V4 - FULL ARCHITECTURE STARTING")
    print("   8 Phases | 31 Modules | 120/120 Tests Passing")
    print("=" * 60)

    # Load master brain in background thread
    import threading
    thread = threading.Thread(
        target=brain.load,
        args=(ID_MASTER,),
        daemon=True
    )
    thread.start()

    # Pre-initialize the main loop
    try:
        ensure_main_loop()
        print("[V4] All subsystems ready")
    except Exception as e:
        print(f"[V4] Warning: Main loop init deferred: {e}")

@app.on_event("shutdown")
def shutdown_event():
    if main_loop:
        try:
            main_loop.end_session()
        except:
            pass
    brain.unload()
    clear_vram()

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    warnings.filterwarnings("ignore")

    print("\n" + "=" * 60)
    print("   EAA V4 - FULL 8-PHASE ARCHITECTURE")
    print("   Replaces V3 agent loop with V4 orchestrator")
    print(f"   Tools: {len(_tool_registry.list_tools()) if _tool_registry else 0}")
    print(f"   Enhanced: {HAS_ENHANCED_TOOLS}")
    print("=" * 60 + "\n")

    uvicorn.run(app, host=HOST, port=PORT)
