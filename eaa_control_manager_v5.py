"""
EAA Control Manager v5 - With AI Endpoints Support
Add this to your EAA folder and update your startup to use this version.

This control manager:
1. Validates API keys and secrets
2. Routes requests to the backend AI server (localhost:8000)
3. Adds /ai/chat and /ai/health endpoints for external access
"""

import asyncio
import json
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx

# =========================
# CONFIG
# =========================
API_KEY = "LcY6XITk_xGct_4NNhQKvxFCN0OBS_F_pIk2EgbX6ts"
SECRET = "victor-jack-victor"
BACKEND_URL = "http://localhost:8000"

# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EAA-Control")

# =========================
# APP
# =========================
app = FastAPI(title="EAA Control Manager v5")

# =========================
# MODELS
# =========================
class AIChatRequest(BaseModel):
    message: str
    brain_type: str = "shadow"
    max_tokens: int = 512

# =========================
# AUTH HELPERS
# =========================
def validate_auth(api_key: Optional[str] = None, secret: Optional[str] = None) -> bool:
    """Validate API key and/or secret"""
    if api_key and api_key == API_KEY:
        return True
    if secret and secret == SECRET:
        return True
    # Allow if both match
    if api_key == API_KEY and secret == SECRET:
        return True
    return False

def get_auth_headers(request: Request) -> tuple:
    """Extract auth from request"""
    api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
    secret = request.headers.get("X-Secret")
    return api_key, secret

# =========================
# AI ENDPOINTS (Public with auth)
# =========================
@app.get("/ai/health")
async def ai_health(request: Request):
    """Check AI backend health - requires valid API key"""
    api_key, secret = get_auth_headers(request)
    
    if not validate_auth(api_key, secret):
        return {"suc": False, "err": "Unauthorized"}
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{BACKEND_URL}/ai/health")
            if response.status_code == 200:
                data = response.json()
                return {"suc": True, **data}
            return {"suc": False, "err": f"Backend returned {response.status_code}"}
    except httpx.ConnectError:
        return {"suc": False, "err": "Backend not running"}
    except Exception as e:
        return {"suc": False, "err": str(e)}

@app.post("/ai/chat")
async def ai_chat(request: Request, req: AIChatRequest):
    """Send message to AI - requires valid API key"""
    api_key, secret = get_auth_headers(request)
    
    if not validate_auth(api_key, secret):
        return {"suc": False, "err": "Unauthorized"}
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{BACKEND_URL}/ai/chat",
                json={
                    "message": req.message,
                    "brain_type": req.brain_type,
                    "max_tokens": req.max_tokens
                }
            )
            if response.status_code == 200:
                data = response.json()
                return data
            return {"suc": False, "err": f"Backend returned {response.status_code}"}
    except httpx.ConnectError:
        return {"suc": False, "err": "Backend not running"}
    except Exception as e:
        return {"suc": False, "err": str(e)}

# =========================
# PROXY ENDPOINTS (Forward to backend)
# =========================
@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_v1(request: Request, path: str):
    """Proxy /v1/* requests to backend"""
    api_key, secret = get_auth_headers(request)
    
    if not validate_auth(api_key, secret):
        return {"suc": False, "err": "Unauthorized"}
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Forward the request
            url = f"{BACKEND_URL}/v1/{path}"
            headers = dict(request.headers)
            headers.pop("host", None)
            
            if request.method == "GET":
                response = await client.get(url, headers=headers)
            elif request.method == "POST":
                body = await request.body()
                response = await client.post(url, content=body, headers=headers)
            elif request.method == "PUT":
                body = await request.body()
                response = await client.put(url, content=body, headers=headers)
            elif request.method == "DELETE":
                response = await client.delete(url, headers=headers)
            else:
                return {"suc": False, "err": "Method not allowed"}
            
            return JSONResponse(
                content=response.json() if response.headers.get("content-type", "").startswith("application/json") else {"data": response.text},
                status_code=response.status_code
            )
    except httpx.ConnectError:
        return {"suc": False, "err": "Backend not running"}
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return {"suc": False, "err": str(e)}

# =========================
# ROOT & STATUS
# =========================
@app.get("/")
async def root():
    return {
        "name": "EAA Control Manager v5",
        "status": "online",
        "endpoints": ["/ai/health", "/ai/chat", "/v1/*"]
    }

@app.get("/health")
async def health():
    return {"status": "online"}

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print("   EAA CONTROL MANAGER v5 - ONLINE")
    print("=" * 50)
    print(f"   API Key: {API_KEY[:8]}...")
    print(f"   Secret: {SECRET}")
    print(f"   Backend: {BACKEND_URL}")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)
