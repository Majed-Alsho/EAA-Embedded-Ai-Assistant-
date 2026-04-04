"""EAA Agent Server Endpoints - Fixed with Stop and VRAM cleanup"""

import json
import asyncio
import logging
import gc
import torch
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from eaa_agent_loop import EAAAgentLoop, AgentConfig, event_to_sse

logger = logging.getLogger(__name__)

# Global state for agent control
_current_agent_task = None
_agent_running = False

class AgentRunRequest(BaseModel):
    message: str
    brain_id: str = None
    brain_type: str = "shadow"
    max_iterations: int = 10
    show_thinking: bool = True

class AgentChatRequest(BaseModel):
    message: str
    brain_id: str = None
    brain_type: str = "shadow"

def setup_agent_endpoints(app: FastAPI, brain_manager):
    """Set up agent endpoints with Stop and VRAM management"""

    @app.get("/v1/agent/tools")
    async def list_agent_tools():
        from eaa_agent_tools import create_tool_registry
        registry = create_tool_registry()
        return {"tools": registry.list_tools(), "count": len(registry.list_tools())}

    @app.post("/v1/agent/stop")
    async def stop_agent():
        """Stop the running agent and free VRAM"""
        global _agent_running, _current_agent_task
        
        _agent_running = False
        
        # Cancel current task if exists
        if _current_agent_task and not _current_agent_task.done():
            _current_agent_task.cancel()
        
        # Clear VRAM
        freed = clear_vram()
        
        # Unload brain to free more memory
        if brain_manager.current_model_id:
            brain_manager.unload()
            freed = True
        
        return {
            "status": "stopped",
            "vram_cleared": freed,
            "message": "Agent stopped and VRAM cleared"
        }

    @app.get("/v1/agent/vram")
    async def get_vram_status():
        """Get current VRAM usage"""
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated(0) / (1024**3)
            total = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            percent = (allocated / total) * 100
            return {
                "allocated_gb": round(allocated, 2),
                "total_gb": round(total, 2),
                "percent": round(percent, 1),
                "loaded_model": brain_manager.current_model_id
            }
        return {"error": "CUDA not available"}

    @app.post("/v1/agent/clear-vram")
    async def clear_vram_endpoint():
        """Force clear VRAM"""
        # Unload current brain
        if brain_manager.current_model_id:
            brain_manager.unload()
        
        cleared = clear_vram()
        return {"status": "cleared", "success": cleared}

    @app.post("/v1/agent/run")
    async def run_agent(request: AgentRunRequest):
        """Run agent with streaming and ability to stop"""
        global _agent_running, _current_agent_task
        
        _agent_running = True

        async def generate_stream():
            global _agent_running
            
            try:
                yield event_to_sse({"type": "status", "message": "Starting agent..."})
                
                config = AgentConfig(
                    max_iterations=request.max_iterations, 
                    show_thinking=request.show_thinking
                )
                agent = EAAAgentLoop(brain_manager, config)

                for event in agent.run(
                    request.message, 
                    brain_id=request.brain_id, 
                    brain_type=request.brain_type
                ):
                    # Check if stopped
                    if not _agent_running:
                        yield event_to_sse({"type": "stopped", "message": "Agent stopped by user"})
                        break
                    
                    yield event_to_sse(event)
                    await asyncio.sleep(0)
                
                # After completion, clear VRAM if we loaded a brain just for this
                if request.brain_id and brain_manager.current_model_id:
                    # Small delay then cleanup
                    await asyncio.sleep(0.5)
                    
            except asyncio.CancelledError:
                yield event_to_sse({"type": "stopped", "message": "Agent cancelled"})
            except Exception as e:
                logger.error(f"Agent error: {e}")
                yield event_to_sse({"type": "error", "message": str(e)})
            finally:
                _agent_running = False

        return StreamingResponse(
            generate_stream(), 
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )

    @app.post("/v1/agent/chat")
    async def agent_chat(request: AgentChatRequest):
        """Simple chat - non-streaming"""
        config = AgentConfig(max_iterations=10, show_thinking=False)
        agent = EAAAgentLoop(brain_manager, config)
        final_response = None
        tools_used = 0
        
        try:
            for event in agent.run(
                request.message, 
                brain_id=request.brain_id, 
                brain_type=request.brain_type
            ):
                if event["type"] == "complete":
                    final_response = event.get("summary", "")
                elif event["type"] == "tool_start":
                    tools_used += 1
        except Exception as e:
            return {"response": f"Error: {str(e)}", "tools_used": 0, "iterations": 0}
        
        return {
            "response": final_response, 
            "tools_used": tools_used, 
            "iterations": agent.iteration_count
        }

    @app.get("/v1/agent/status")
    async def agent_status():
        """Get current agent status"""
        return {
            "running": _agent_running,
            "brain_manager_loaded": brain_manager.current_model_id, 
            "is_gguf": brain_manager.is_gguf, 
            "current_adapter": brain_manager.current_adapter
        }

    print("[EAA Agent] Endpoints registered:")
    print("  GET  /v1/agent/tools")
    print("  POST /v1/agent/run")
    print("  POST /v1/agent/chat")
    print("  POST /v1/agent/stop      <- NEW: Stop agent & free VRAM")
    print("  GET  /v1/agent/vram      <- NEW: Check VRAM usage")
    print("  POST /v1/agent/clear-vram <- NEW: Force clear VRAM")
    print("  GET  /v1/agent/status")


def clear_vram() -> bool:
    """Clear VRAM manually"""
    try:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        return True
    except Exception as e:
        logger.error(f"Failed to clear VRAM: {e}")
        return False


def event_to_sse(event) -> str:
    return f"data: {json.dumps(event)}\n\n"


__all__ = ["setup_agent_endpoints", "AgentRunRequest", "AgentChatRequest", "clear_vram"]
