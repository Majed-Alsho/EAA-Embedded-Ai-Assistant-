"""
EAA Agent Server V2 - Uses Improved Agent Loop
===============================================
Endpoints for agent execution with V2 improvements:
- Better tool formatting
- Error recovery
- Retry logic
"""

import json
import asyncio
import logging
import gc
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from eaa_agent_loop_v2 import EAAAgentLoopV2, AgentConfig, event_to_sse

logger = logging.getLogger(__name__)

# Global state
_current_agent_task = None
_agent_running = False


class AgentRunRequest(BaseModel):
    message: str
    brain_id: str = None
    brain_type: str = "shadow"
    max_iterations: int = 15
    show_thinking: bool = True


class AgentChatRequest(BaseModel):
    message: str
    brain_id: str = None
    brain_type: str = "shadow"


def setup_agent_endpoints(app: FastAPI, brain_manager):
    """Set up agent V2 endpoints"""

    @app.get("/v1/agent/tools")
    async def list_agent_tools():
        from eaa_agent_tools_v2 import create_tool_registry
        registry = create_tool_registry()
        return {"tools": registry.list_tools(), "count": len(registry.list_tools())}

    @app.post("/v1/agent/stop")
    async def stop_agent():
        """Stop the running agent"""
        global _agent_running, _current_agent_task
        
        _agent_running = False
        
        if _current_agent_task and not _current_agent_task.done():
            _current_agent_task.cancel()
        
        # Clear VRAM
        freed = clear_vram()
        
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
        try:
            import torch
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
        except:
            pass
        return {"error": "CUDA not available"}

    @app.post("/v1/agent/clear-vram")
    async def clear_vram_endpoint():
        """Force clear VRAM"""
        if brain_manager.current_model_id:
            brain_manager.unload()
        
        cleared = clear_vram()
        return {"status": "cleared", "success": cleared}

    @app.post("/v1/agent/run")
    async def run_agent(request: AgentRunRequest):
        """Run agent with streaming output"""
        global _agent_running, _current_agent_task
        
        _agent_running = True

        async def generate_stream():
            global _agent_running
            
            try:
                yield event_to_sse({"type": "status", "message": "Starting agent V2..."})
                
                config = AgentConfig(
                    max_iterations=request.max_iterations, 
                    show_thinking=request.show_thinking
                )
                agent = EAAAgentLoopV2(brain_manager, config)

                for event in agent.run(
                    request.message, 
                    brain_id=request.brain_id, 
                    brain_type=request.brain_type
                ):
                    if not _agent_running:
                        yield event_to_sse({"type": "stopped", "message": "Agent stopped by user"})
                        break
                    
                    yield event_to_sse(event)
                    await asyncio.sleep(0)
                
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
        """Simple chat - non-streaming with V2 improvements"""
        config = AgentConfig(max_iterations=15, show_thinking=False)
        agent = EAAAgentLoopV2(brain_manager, config)
        final_response = None
        tools_used = 0
        tool_results = []
        
        try:
            for event in agent.run(
                request.message, 
                brain_id=request.brain_id, 
                brain_type=request.brain_type
            ):
                if event["type"] == "complete":
                    final_response = event.get("summary", "")
                    tools_used = event.get("tools_used", agent.tools_used_count)
                elif event["type"] == "tool_result":
                    tool_results.append({
                        "tool": event.get("name"),
                        "success": event.get("success"),
                        "output": event.get("result", {}).get("output", "")[:500]
                    })
                elif event["type"] == "error":
                    final_response = f"Error: {event.get('message')}"
                    
        except Exception as e:
            return {"response": f"Error: {str(e)}", "tools_used": 0, "iterations": 0}
        
        return {
            "response": final_response, 
            "tools_used": tools_used, 
            "iterations": agent.iteration_count,
            "tool_results": tool_results if tool_results else None
        }

    @app.get("/v1/agent/status")
    async def agent_status():
        """Get current agent status"""
        return {
            "running": _agent_running,
            "version": "v2",
            "brain_manager_loaded": brain_manager.current_model_id, 
            "is_gguf": brain_manager.is_gguf, 
            "current_adapter": brain_manager.current_adapter
        }

    print("[EAA Agent V2] Endpoints registered:")
    print("  GET  /v1/agent/tools")
    print("  POST /v1/agent/run      (streaming)")
    print("  POST /v1/agent/chat     (simple)")
    print("  POST /v1/agent/stop")
    print("  GET  /v1/agent/vram")
    print("  POST /v1/agent/clear-vram")
    print("  GET  /v1/agent/status")


def clear_vram() -> bool:
    """Clear VRAM manually"""
    try:
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except:
            pass
        return True
    except Exception as e:
        logger.error(f"Failed to clear VRAM: {e}")
        return False


__all__ = ["setup_agent_endpoints", "AgentRunRequest", "AgentChatRequest", "clear_vram"]
