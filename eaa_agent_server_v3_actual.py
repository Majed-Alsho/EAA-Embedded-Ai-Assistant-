"""
EAA Agent Server V3 - PROFESSIONAL GRADE
========================================
Features:
- Stop functionality with proper cleanup
- VRAM management and monitoring
- Streaming responses with SSE
- Smart brain loading/unloading
- Health checks and status endpoints
"""

import json
import asyncio
import logging
import gc
import time
from typing import Optional
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Import V3 components
from eaa_agent_loop_v3 import (
    EAAAgentLoop, AgentConfig, EventType, 
    event_to_sse, LIGHT_TOOLS
)

# Enhanced tools (88 tools from 10 modules) - loads if available, no error if missing
HAS_ENHANCED_TOOLS = False
_enhanced_registry = None
_enhanced_history = None
_enhanced_chain = None
try:
    from eaa_tool_executor import create_enhanced_registry, get_tools_prompt
    _enhanced_registry, _enhanced_history, _enhanced_chain = create_enhanced_registry()
    HAS_ENHANCED_TOOLS = True
    print("[ENHANCED] 88 Enhanced Tools loaded successfully!")
except Exception as e:
    print(f"[ENHANCED] Enhanced tools not available: {e}")
    print("[ENHANCED] Falling back to V3 tools (18 tools)")

logger = logging.getLogger(__name__)

# ============================================
# GLOBAL STATE
# ============================================

_current_agent_task: Optional[asyncio.Task] = None
_agent_running: bool = False
_agent_cancelled: bool = False
_last_activity: float = 0

# Brain management
_brain_loaded_at: float = 0
_auto_unload_delay: int = 60  # Unload brain after 60s of light-tool-only usage

# ============================================
# REQUEST MODELS
# ============================================

class AgentRunRequest(BaseModel):
    message: str
    brain_id: str = None
    brain_type: str = "shadow"
    max_iterations: int = 15
    show_thinking: bool = True
    auto_retry: bool = True

class AgentChatRequest(BaseModel):
    message: str
    brain_id: str = None
    brain_type: str = "shadow"
    max_iterations: int = 10

class BrainLoadRequest(BaseModel):
    brain_id: str
    adapter_path: str = None

# ============================================
# VRAM MANAGEMENT
# ============================================

def clear_vram() -> bool:
    """Clear VRAM manually"""
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
    except Exception as e:
        logger.error(f"Failed to clear VRAM: {e}")
        return False


def get_vram_info() -> dict:
    """Get current VRAM usage"""
    try:
        import torch
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated(0) / (1024**3)
            reserved = torch.cuda.memory_reserved(0) / (1024**3)
            total = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            free = total - allocated
            percent = (allocated / total) * 100
            
            return {
                "allocated_gb": round(allocated, 2),
                "reserved_gb": round(reserved, 2),
                "total_gb": round(total, 2),
                "free_gb": round(free, 2),
                "percent_used": round(percent, 1),
                "available": True
            }
    except ImportError:
        pass
    except Exception as e:
        logger.error(f"VRAM check failed: {e}")
    
    return {"available": False, "error": "CUDA not available"}


# ============================================
# SMART BRAIN MANAGER
# ============================================

class SmartBrainManager:
    """
    Manages brain loading/unloading for efficiency.
    Light tools don't need the brain loaded.
    """
    
    def __init__(self, brain_manager, auto_unload_delay: int = 60):
        self.brain_manager = brain_manager
        self.auto_unload_delay = auto_unload_delay
        self._last_heavy_use = time.time()
        self._check_task = None
    
    def is_light_tool(self, tool_name: str) -> bool:
        """Check if tool can run without brain"""
        return tool_name in LIGHT_TOOLS
    
    def on_tool_use(self, tool_name: str):
        """Called when a tool is used"""
        if not self.is_light_tool(tool_name):
            self._last_heavy_use = time.time()
    
    def should_unload_brain(self) -> bool:
        """Check if brain should be unloaded to save VRAM"""
        if not self.brain_manager.current_model_id:
            return False
        
        elapsed = time.time() - self._last_heavy_use
        return elapsed > self.auto_unload_delay
    
    async def start_monitor(self):
        """Start background monitor for auto-unload"""
        while True:
            await asyncio.sleep(30)  # Check every 30 seconds
            if self.should_unload_brain():
                logger.info("Auto-unloading brain due to inactivity")
                self.brain_manager.unload()
                clear_vram()


# ============================================
# ENDPOINT SETUP
# ============================================

def setup_agent_endpoints(app: FastAPI, brain_manager):
    """Set up agent endpoints with full management"""
    
    global _current_agent_task, _agent_running
    smart_manager = SmartBrainManager(brain_manager)
    
    # ========================================
    # TOOLS ENDPOINT
    # ========================================
    
    @app.get("/v1/agent/tools")
    async def list_agent_tools():
        """List all available tools - Enhanced (88) if available, else V3 (18)"""
        # Use enhanced registry (88 tools) if available
        if HAS_ENHANCED_TOOLS and _enhanced_registry is not None:
            registry = _enhanced_registry
            enhanced = True
        else:
            from eaa_agent_tools_v3 import create_tool_registry
            registry = create_tool_registry()
            enhanced = False
        
        tools = []
        for name in registry.list_tools():
            desc = registry._descriptions.get(name, "")
            schema = registry._schemas.get(name, {})
            is_light = name in LIGHT_TOOLS
            category = "unknown"
            
            tools.append({
                "name": name,
                "description": desc,
                "schema": schema,
                "lightweight": is_light
            })
        
        result = {
            "tools": tools,
            "count": len(tools),
            "light_tools": list(LIGHT_TOOLS)
        }
        if enhanced:
            result["enhanced"] = True
            result["mode"] = "88 tools (10 modules)"
        
        return result
    
    # ========================================
    # STOP ENDPOINT
    # ========================================
    
    @app.post("/v1/agent/stop")
    async def stop_agent():
        """Stop the running agent and free resources"""
        global _agent_running, _agent_cancelled, _current_agent_task
        
        _agent_running = False
        _agent_cancelled = True
        
        # Cancel current task
        if _current_agent_task and not _current_agent_task.done():
            _current_agent_task.cancel()
            try:
                await _current_agent_task
            except asyncio.CancelledError:
                pass
        
        # Clear VRAM
        freed = clear_vram()
        
        # Unload brain if not needed
        if brain_manager.current_model_id:
            brain_manager.unload()
            freed = True
        
        return {
            "status": "stopped",
            "vram_cleared": freed,
            "message": "Agent stopped and resources freed"
        }
    
    # ========================================
    # VRAM ENDPOINTS
    # ========================================
    
    @app.get("/v1/agent/vram")
    async def get_vram_status():
        """Get current VRAM usage"""
        info = get_vram_info()
        info["loaded_model"] = brain_manager.current_model_id
        info["is_gguf"] = getattr(brain_manager, "is_gguf", False)
        return info
    
    @app.post("/v1/agent/clear-vram")
    async def clear_vram_endpoint():
        """Force clear VRAM"""
        # Unload brain first
        if brain_manager.current_model_id:
            brain_manager.unload()
        
        cleared = clear_vram()
        return {"status": "cleared", "success": cleared}
    
    # ========================================
    # RUN ENDPOINT (STREAMING)
    # ========================================
    
    @app.post("/v1/agent/run")
    async def run_agent(request: AgentRunRequest):
        """Run agent with streaming output"""
        global _agent_running, _agent_cancelled, _current_agent_task
        
        _agent_running = True
        _agent_cancelled = False
        
        async def generate_stream():
            global _agent_running
            
            try:
                yield event_to_sse({
                    "type": EventType.STATUS.value,
                    "message": f"Starting agent with {request.brain_type} brain..."
                })
                
                # Create config
                config = AgentConfig(
                    max_iterations=request.max_iterations,
                    show_thinking=request.show_thinking,
                    auto_retry=request.auto_retry
                )
                
                # Pass enhanced registry if available (88 tools with smart routing)
                registry = _enhanced_registry if HAS_ENHANCED_TOOLS else None
                agent = EAAAgentLoop(brain_manager, config, tool_registry=registry)
                
                # Run agent loop
                for event in agent.run(
                    request.message,
                    brain_id=request.brain_id,
                    brain_type=request.brain_type
                ):
                    # Check if cancelled
                    if not _agent_running or _agent_cancelled:
                        yield event_to_sse({
                            "type": EventType.STATUS.value,
                            "message": "Agent stopped by user"
                        })
                        break
                    
                    # Track tool usage for smart brain management
                    if event.get("type") == EventType.TOOL_START.value:
                        smart_manager.on_tool_use(event.get("tool", ""))
                    
                    yield event_to_sse(event)
                    await asyncio.sleep(0)  # Yield control
                
            except asyncio.CancelledError:
                yield event_to_sse({
                    "type": EventType.STATUS.value,
                    "message": "Agent cancelled"
                })
            
            except Exception as e:
                logger.error(f"Agent error: {e}")
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
    
    # ========================================
    # CHAT ENDPOINT (NON-STREAMING)
    # ========================================
    
    @app.post("/v1/agent/chat")
    async def agent_chat(request: AgentChatRequest):
        """Simple chat - returns final result only"""
        config = AgentConfig(
            max_iterations=request.max_iterations,
            show_thinking=False
        )
        
        # Pass enhanced registry if available (88 tools with smart routing)
        registry = _enhanced_registry if HAS_ENHANCED_TOOLS else None
        agent = EAAAgentLoop(brain_manager, config, tool_registry=registry)
        final_response = None
        tools_used = 0
        
        try:
            for event in agent.run(
                request.message,
                brain_id=request.brain_id,
                brain_type=request.brain_type
            ):
                if event["type"] == EventType.COMPLETE.value:
                    final_response = event
                elif event["type"] == EventType.TOOL_START.value:
                    tools_used += 1
                elif event["type"] == EventType.ERROR.value:
                    return {
                        "success": False,
                        "error": event.get("message", "Unknown error"),
                        "tools_used": tools_used
                    }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "tools_used": tools_used
            }
        
        return {
            "success": True,
            "response": final_response.get("summary", "") if final_response else "",
            "tools_used": tools_used,
            "iterations": agent.state.iterations,
            "status": final_response.get("status", "unknown") if final_response else "unknown"
        }
    
    # ========================================
    # STATUS ENDPOINT
    # ========================================
    
    @app.get("/v1/agent/status")
    async def agent_status():
        """Get current agent and system status"""
        vram = get_vram_info()
        
        return {
            "running": _agent_running,
            "brain_loaded": brain_manager.current_model_id is not None,
            "brain_id": brain_manager.current_model_id,
            "is_gguf": getattr(brain_manager, "is_gguf", False),
            "current_adapter": getattr(brain_manager, "current_adapter", None),
            "vram": vram,
            "light_tools": list(LIGHT_TOOLS)
        }
    
    # ========================================
    # BRAIN MANAGEMENT ENDPOINTS
    # ========================================
    
    @app.post("/v1/agent/brain/load")
    async def load_brain(request: BrainLoadRequest):
        """Load a specific brain"""
        try:
            brain_manager.load(request.brain_id, adapter_path=request.adapter_path)
            return {
                "success": True,
                "brain_id": request.brain_id
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    @app.post("/v1/agent/brain/unload")
    async def unload_brain():
        """Unload current brain"""
        if brain_manager.current_model_id:
            brain_manager.unload()
            clear_vram()
            return {"success": True, "message": "Brain unloaded"}
        return {"success": True, "message": "No brain was loaded"}
    
    # ========================================
    # HEALTH CHECK
    # ========================================
    
    @app.get("/v1/agent/health")
    async def agent_health():
        """Quick health check"""
        return {
            "status": "healthy",
            "running": _agent_running,
            "brain_loaded": brain_manager.current_model_id is not None
        }
    
    # Print endpoint summary
    print("\n" + "=" * 60)
    print("  EAA AGENT V3 - ENDPOINTS REGISTERED")
    print("=" * 60)
    print("  GET  /v1/agent/tools         - List all tools")
    print("  POST /v1/agent/run           - Run agent (streaming)")
    print("  POST /v1/agent/chat          - Simple chat (non-streaming)")
    print("  POST /v1/agent/stop          - Stop agent & free VRAM")
    print("  GET  /v1/agent/status        - Full status")
    print("  GET  /v1/agent/health        - Quick health check")
    print("  GET  /v1/agent/vram          - VRAM usage info")
    print("  POST /v1/agent/clear-vram    - Force clear VRAM")
    print("  POST /v1/agent/brain/load    - Load specific brain")
    print("  POST /v1/agent/brain/unload  - Unload brain")
    print("=" * 60)
    print(f"  Light tools (no brain needed): {len(LIGHT_TOOLS)}")
    print("=" * 60 + "\n")


# ============================================
# LEGACY COMPATIBILITY
# ============================================

# Keep old function name for compatibility
def event_to_sse(event) -> str:
    return f"data: {json.dumps(event)}\n\n"


__all__ = [
    "setup_agent_endpoints",
    "AgentRunRequest",
    "AgentChatRequest", 
    "BrainLoadRequest",
    "clear_vram",
    "get_vram_info",
    "SmartBrainManager"
]
