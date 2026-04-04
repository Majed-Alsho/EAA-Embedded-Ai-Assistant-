# EAA - Embedded AI Assistant

<div align="center">

**A fully local AI assistant that runs 100% on your computer**

*Your data never leaves your machine*

Built with **Tauri 2** • **React 19** • **TypeScript** • **Python** • **llama-cpp**

[Features](#features) • [Architecture](#architecture-overview) • [How It Works](#how-eaa-works) • [Installation](#getting-started)

</div>

---

## What is EAA?

EAA (Embedded AI Assistant) is a fully local AI assistant that runs entirely on your computer. Unlike cloud-based AI assistants like ChatGPT or Claude, EAA runs 100% locally - your data never leaves your machine.

**Key Features:**
- 🔒 **100% Private** - All processing happens locally
- 🧠 **Multiple AI Brains** - Different models for different tasks
- 🛠️ **19+ Built-in Tools** - File operations, web search, code execution
- 🌐 **Remote Access** - Connect from anywhere via Cloudflare tunnel
- 💻 **Modern UI** - Built with React 19 and Tauri 2
- 📝 **Canvas Editor** - Full-featured code editor with AI assistance

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [How EAA Works](#how-eaa-works)
3. [Brains (AI Models)](#brains-ai-models)
4. [Frontend (React/Tauri)](#frontend-reacttauri)
5. [Backend (Python)](#backend-python)
6. [Tool System](#tool-system)
7. [Remote Control & Z.ai Connection](#remote-control--zai-connection)
8. [File Structure](#file-structure)
9. [Upgrades To Do](#upgrades-to-do)
10. [Getting Started](#getting-started)

---

## Architecture Overview

EAA consists of three main layers working together:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DESKTOP APP (Tauri 2)                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │              Frontend (React 19 + TypeScript)                     │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────────┐  │  │
│  │  │    Chat     │ │   Canvas    │ │       Tool Panels           │  │  │
│  │  │  Interface  │ │   Editor    │ │   (Read/Write/Logs/etc)     │  │  │
│  │  └─────────────┘ └─────────────┘ └─────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                       Tauri IPC Bridge                                  │
│                              │                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                Rust Backend (lib.rs)                              │  │
│  │  • Process Management (Python Agent)                              │  │
│  │  • File System Access                                             │  │
│  │  • Brain Health Checks                                            │  │
│  │  • ComfyUI Integration                                            │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  PYTHON BACKEND (FastAPI Server)                        │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │            eaa_agent_server.py (Port 8000)                        │  │
│  │  • /v1/health      - Health check                                 │  │
│  │  • /v1/tools       - List available tools                         │  │
│  │  • /v1/chat/completions - Chat with AI (OpenAI format)           │  │
│  │  • /ai/chat        - Chat with tool execution                     │  │
│  │  • /canvas/analyze - Code analysis                                │  │
│  │  • /canvas/fix     - AI code fixing                               │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │            AI Brain (llama-cpp-python)                            │  │
│  │  • Loads GGUF models from brains/ folder                          │  │
│  │  • GPU acceleration via CUDA                                      │  │
│  │  • 8192 token context window                                      │  │
│  │  • Generates AI responses                                         │  │
│  │  • Decides when to use tools                                      │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │            Tool Registry (eaa_agent_tools.py)                     │  │
│  │  • 19+ tools for file, web, memory, code operations              │  │
│  │  • Executes tool calls from AI                                    │  │
│  │  • Returns results to AI for processing                           │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   CLOUDFLARE TUNNEL (Optional)                          │
│  • Secure tunnel from internet to local PC                             │
│  • Allows Z.ai to connect to your EAA remotely                         │
│  • URL: https://your-tunnel.trycloudflare.com                          │
│  • Authentication via API key                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## How EAA Works

### 1. Application Startup Sequence

When you launch EAA, the following sequence occurs:

```
1. Tauri App Starts (Rust process)
          │
          ▼
2. Rust Auto-Launches Python Agent
   Command: C:\Users\offic\EAA\.venv-hf\Scripts\python.exe run_eaa_agent.py
          │
          ▼
3. Python Loads AI Brain
   - Reads brains/shadow_brain.gguf (1.4 GB)
   - Initializes llama-cpp-python with GPU support
   - Sets up 8192 token context window
          │
          ▼
4. Python Starts FastAPI Server
   - Binds to http://127.0.0.1:8000
   - Registers all endpoints
   - Loads tool registry
          │
          ▼
5. React Frontend Checks Brain Health
   - Calls eaa_check_brain_health() via Tauri IPC
   - Rust bypasses webview isolation to reach localhost
          │
          ▼
6. Brain Online - Connection Hub Appears
   - User can configure connection
   - Enter API keys or server URLs
          │
          ▼
7. User Connects - Ready to Chat!
   - Full AI assistant functionality available
```

### 2. Chat Message Flow

When you send a message to EAA:

```
User Types: "Read my config file and tell me what settings I have"
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ Frontend sends POST to /ai/chat                             │
│ { "messages": [{ "role": "user", "content": "..." }] }     │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ Python Backend Receives Request                             │
│ - Adds system prompt                                        │
│ - Adds conversation history                                 │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ AI Brain Processes Message                                  │
│ - Analyzes user intent                                      │
│ - Decides tool is needed: tool_read_file                    │
│ - Outputs: .tool{"name": "read_file", "args": {...}}       │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ Tool Executor Parses Tool Call                              │
│ - Detects .tool{} pattern                                   │
│ - Extracts tool name and arguments                          │
│ - Validates against registry                                │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ Tool Execution: tool_read_file                              │
│ - Reads C:\Users\offic\EAA\config.json                      │
│ - Returns file contents                                     │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ Tool Result Fed Back to AI                                  │
│ - AI now has file contents                                  │
│ - AI analyzes the configuration                             │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ AI Generates Final Response                                 │
│ "I found your configuration. Here are your settings:        │
│  - Theme: Dark                                              │
│  - Language: English                                        │
│  - ..."                                                     │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ Response Streamed to Frontend                               │
│ - Displayed in chat interface                               │
│ - Saved to conversation history                             │
└─────────────────────────────────────────────────────────────┘
```

### 3. Tool Call Format

The AI uses a special format to call tools:

```
.tool{"name": "read_file", "args": {"path": "C:\\Users\\offic\\EAA\\README.md"}}
```

The agent loop (in `eaa_agent_loop.py`) detects this pattern using regex, parses the JSON, executes the tool, and returns the result to the AI.

---

## Brains (AI Models)

EAA uses multiple AI "brains" for different tasks. These are stored locally in the `brains/` folder.

### Brain Files Overview

| Brain | Location | Size | Purpose |
|-------|----------|------|---------|
| **Shadow Brain** | `brains/shadow_brain.gguf` | 1.4 GB | Main conversational AI. Handles chat, reasoning, and tool selection. Optimized GGUF format for fast inference with GPU acceleration. |
| **Shadow Brain (Full)** | `brains/shadow_brain/shadow_brain.gguf` | 5.4 GB | Full precision version of shadow brain. Higher quality responses but slower inference. Local only. |
| **Master Baked** | `brains/master_baked/` | 5.5 GB | Fine-tuned Qwen model. Custom trained for specific tasks. Safetensors format. Local only. |
| **Vision Qwen2VL** | `brains/vision_qwen2vl/` | 4.1 GB | Vision-capable model. Can understand and describe images. Safetensors format. Local only. |

### Why Some Brains Are Not on GitHub

GitHub has a **2GB file size limit** even with Git LFS. The following files exceed this limit and exist **only on your local PC**:

| File | Size | Reason |
|------|------|--------|
| `brains/shadow_brain/shadow_brain.gguf` | 5.4 GB | ❌ Exceeds 2GB limit |
| `brains/master_baked/model-00001-of-00002.safetensors` | 4.1 GB | ❌ Exceeds 2GB limit |
| `brains/master_baked/model-00002-of-00002.safetensors` | 1.0 GB | ⚠️ Would need LFS |
| `brains/vision_qwen2vl/model.safetensors` | 4.1 GB | ❌ Exceeds 2GB limit |

**The main brain** (`shadow_brain.gguf` at 1.4GB) **is on GitHub** and can be downloaded.

### How the Brain Works

EAA uses `llama-cpp-python` to run GGUF models locally with GPU acceleration:

```python
from llama_cpp import Llama

# Load the brain
llm = Llama(
    model_path="brains/shadow_brain.gguf",
    n_ctx=8192,        # Context window: 8192 tokens
    n_gpu_layers=35,   # GPU layers for acceleration
    verbose=False      # Quiet mode
)

# Generate response
response = llm.create_chat_completion(
    messages=[
        {"role": "system", "content": "You are EAA, a helpful AI assistant..."},
        {"role": "user", "content": "Hello! What can you do?"}
    ],
    temperature=0.7,
    max_tokens=2048
)
```

### Brain Training

The `train_data/` folder contains training datasets for fine-tuning:

| File | Purpose |
|------|---------|
| `eaa_train.jsonl` | Main training data |
| `shadow_train.jsonl` | Shadow personality training |
| `master_train.jsonl` | Master model training |
| `shadow_personality.jsonl` | Personality fine-tuning |

Use `bake_brains.py` to train/fine-tune models on your custom data.

---

## Frontend (React/Tauri)

### Technology Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| React | 19.1.0 | UI framework |
| TypeScript | 5.8.3 | Type safety |
| Tauri | 2.x | Native desktop wrapper |
| Vite | 7.0.4 | Build tool |
| Monaco Editor | 4.7.0 | Code editing (VS Code engine) |
| PrismJS | 1.30.0 | Syntax highlighting |

### Main Components

#### App.tsx - Main Application

The main React component handles:
- **State management** for chat, tools, and UI
- **Brain health check** during startup
- **Voice activation detection (VAD)** for voice input
- **Multiple chat sessions** with project management
- **Tool panel switching** between different tools
- **Canvas editor integration**

```tsx
// Brain health check on startup
useEffect(() => {
  const checkBrainHealth = async () => {
    const dataStr = await invoke<string>("eaa_check_brain_health");
    const data = JSON.parse(dataStr);
    if (data.status === "online") {
      setIsBusy(false);
      setShowHub(true);
    }
  };
  checkBrainHealth();
}, []);
```

#### ConnectionHub.tsx

The connection screen where users:
- Enter server URL (for remote connections)
- Configure API keys
- Connect to local or remote EAA instances

#### Canvas Editor (src/components/canvas/)

A full-featured code editor with AI integration:

| File | Purpose |
|------|---------|
| `CanvasEditor.tsx` | Main editor component |
| `CanvasContext.tsx` | State management for canvas |
| `CanvasPreview.tsx` | Live preview panel |
| `ProCanvasEditor.tsx` | Advanced features |
| `AIAssistantPanel.tsx` | AI chat within editor |
| `VisualCanvas.tsx` | Visual editing mode |
| `ViewportFrame.tsx` | Responsive design preview |

**Features:**
- Monaco Editor (VS Code engine)
- File tabs for multiple open files
- AI integration for code assistance
- Preview panel for HTML/React
- Viewport switching for responsive design
- Error detection and AI fixing

#### Tool Panels (src/components/tools/)

Each tool has its own dedicated panel:

| Panel | Purpose |
|-------|---------|
| **Logs** | View system logs and debug output |
| **Workspace** | Browse and manage files |
| **Read** | Read file contents |
| **Write** | Create and edit files |
| **Patch** | Apply code patches |
| **Media** | Handle images, audio, video |
| **Sandbox** | Execute code safely |

### Rust Backend (src-tauri/src/lib.rs)

The Rust layer handles native functionality that JavaScript cannot access:

#### Process Management

```rust
// Auto-start Python agent when app launches
fn start_agent() {
    let python_exe = r"C:\Users\offic\EAA\.venv-hf\Scripts\python.exe";
    let script_path = r"C:\Users\offic\EAA\run_eaa_agent.py";
    Command::new(python_exe)
        .arg(script_path)
        .spawn()
        .expect("Failed to start agent");
}
```

#### Brain Health Check (Critical)

This function is critical - Tauri 2's webview cannot access localhost directly due to security restrictions, so Rust makes the HTTP request instead:

```rust
#[tauri::command]
fn eaa_check_brain_health() -> Result<String, String> {
    let client = reqwest::blocking::Client::new();
    let resp = client
        .get("http://127.0.0.1:8000/v1/health")
        .timeout(Duration::from_secs(5))
        .send();
    
    match resp {
        Ok(r) if r.status().is_success() => Ok(r.text().unwrap()),
        _ => Err("Brain not reachable".to_string())
    }
}
```

#### File Operations

Rust handles secure file operations:
- `read_file` - Read file contents
- `write_file` - Write to files
- `list_dir` - List directory contents
- Path validation to prevent directory traversal attacks

---

## Backend (Python)

### Server (eaa_agent_server.py)

FastAPI server providing the AI API:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="EAA Agent Server")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/v1/health")
async def health_check():
    return {
        "status": "online",
        "version": "v3",
        "model_loaded": True,
        "tools_available": len(registry.list_tools())
    }

@app.get("/v1/tools")
async def list_tools():
    return {"tools": registry.list_tools()}

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    """OpenAI-compatible chat endpoint"""
    response = llm.create_chat_completion(
        messages=request.messages,
        temperature=request.temperature,
        max_tokens=request.max_tokens
    )
    return response

@app.post("/ai/chat")
async def ai_chat(request: ChatRequest):
    """Chat with automatic tool execution"""
    response = process_with_tools(request.messages)
    return response
```

### Agent Loop (eaa_agent_loop.py)

The main agent logic that orchestrates AI-tool interaction:

```python
import re

TOOL_PATTERN = r'\.tool\{[^}]+\}'

async def agent_loop(messages: list) -> str:
    """Main agent loop with tool execution"""
    while True:
        # Get AI response
        response = await llm.chat(messages)
        
        # Check for tool calls
        tool_matches = re.findall(TOOL_PATTERN, response)
        
        if tool_matches:
            for match in tool_matches:
                # Parse tool call
                tool_call = json.loads(match[6:])  # Remove .tool prefix
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                
                # Execute tool
                result = registry.execute(tool_name, **tool_args)
                
                # Add result to messages
                messages.append({
                    "role": "tool",
                    "content": result.output
                })
        else:
            # No tools needed, return response
            return response
```

### Tool Registry (eaa_agent_tools.py)

Manages all available tools:

```python
from dataclasses import dataclass
from typing import Optional, Callable, Any

@dataclass
class ToolResult:
    success: bool
    output: str
    error: Optional[str] = None

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Callable] = {}
        self._descriptions: dict[str, str] = {}
    
    def register(self, name: str, func: Callable, description: str):
        """Register a new tool"""
        self._tools[name] = func
        self._descriptions[name] = description
    
    def execute(self, name: str, **kwargs) -> ToolResult:
        """Execute a tool by name"""
        if name not in self._tools:
            return ToolResult(False, "", f"Tool '{name}' not found")
        
        try:
            result = self._tools[name](**kwargs)
            return ToolResult(True, str(result))
        except Exception as e:
            return ToolResult(False, "", str(e))
    
    def list_tools(self) -> list[str]:
        """List all registered tools"""
        return list(self._tools.keys())

# Create and populate registry
registry = ToolRegistry()

# Register file tools
registry.register("read_file", tool_read_file, "Read file contents")
registry.register("write_file", tool_write_file, "Write content to file")
# ... more tools
```

---

## Tool System

EAA has **19+ built-in tools** that allow the AI to interact with your computer.

### Current Tools

| Category | Tool | Description |
|----------|------|-------------|
| **File** | `read_file` | Read file contents with line numbers |
| **File** | `write_file` | Create or overwrite files |
| **File** | `append_file` | Append content to existing files |
| **File** | `list_files` | List directory contents with sizes |
| **File** | `file_exists` | Check if file exists |
| **File** | `create_directory` | Create new directories |
| **File** | `delete_file` | Delete files or directories |
| **File** | `glob` | Find files matching pattern |
| **File** | `grep` | Search for text in files |
| **System** | `shell` | Execute shell commands |
| **Web** | `web_search` | Search the web via DuckDuckGo |
| **Web** | `web_fetch` | Fetch and read web page content |
| **Memory** | `memory_save` | Save information to persistent memory |
| **Memory** | `memory_recall` | Retrieve saved information |
| **Memory** | `memory_list` | List all saved memory keys |
| **Utility** | `datetime` | Get current date and time |
| **Utility** | `calculator` | Evaluate math expressions |
| **Code** | `python` | Execute Python code safely |

### Tool Call Example

When you ask EAA to do something that requires a tool:

```
User: "Read my config.json file and tell me what's in it"

AI Response:
.tool{"name": "read_file", "args": {"path": "C:\\Users\\offic\\EAA\\config.json"}}

Tool Result:
{
  "success": true,
  "output": "1: {\n2:   \"theme\": \"dark\",\n3:   \"language\": \"en\",\n..."
}

AI Final Response:
I read your config.json file. Here's what I found:
- Theme: dark
- Language: en
- ...
```

### Safety Features

- **Dangerous command blocking** - Shell commands like `rm -rf`, `format`, etc. are blocked
- **Path validation** - Prevents directory traversal attacks
- **Timeout handling** - Tools timeout after configurable duration
- **Error recovery** - Graceful error handling and reporting

---

## Remote Control & Z.ai Connection

EAA can be controlled remotely via a Cloudflare tunnel. This is how Z.ai (or any external service) can connect to your PC.

### How the Tunnel Works

```
┌─────────────┐         ┌──────────────────┐         ┌─────────────┐
│    Z.ai     │ ──────► │   Cloudflare     │ ──────► │   Your PC   │
│  (Internet) │         │  Tunnel Server   │         │    (EAA)    │
└─────────────┘         └──────────────────┘         └─────────────┘
   Public URL                  Relay                   Localhost
   (External)               (Secure Bridge)           127.0.0.1:8000
```

### Setting Up the Tunnel

1. **Cloudflared installed** at `tools/cloudflared.exe`
2. **Tunnel starts** when EAA launches (or manually)
3. **Tunnel URL** is generated (e.g., `https://xxx-xxx.trycloudflare.com`)
4. **API Key** is set for authentication

```python
# eaa_tunnel.py
import subprocess

def start_tunnel():
    cloudflared = "tools/cloudflared.exe"
    command = [
        cloudflared, "tunnel",
        "--url", "http://127.0.0.1:8000",
        "--protocol", "http2"
    ]
    process = subprocess.Popen(command)
    return process
```

### What Z.ai Can Do Through the Tunnel

When connected remotely, Z.ai can:

| Capability | Description |
|------------|-------------|
| **Chat** | Send messages and receive AI responses |
| **Execute Tools** | Run any of the 19+ tools on your PC |
| **Read Files** | Access any file on your computer |
| **Write Files** | Create and modify files |
| **Run Commands** | Execute shell commands |
| **Web Search** | Search the web from your PC |
| **Screenshots** | Capture your screen |
| **Webcam** | Access webcam for images |
| **System Info** | Get system information |

### API Endpoints for Remote Access

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/health` | GET | Check if EAA is online |
| `/v1/tools` | GET | List available tools |
| `/v1/chat/completions` | POST | Chat with AI (OpenAI format) |
| `/ai/chat` | POST | Chat with tool execution |
| `/auth` | POST | Authenticate with API key |
| `/file/list` | POST | List files in directory |
| `/file/read` | POST | Read file contents |
| `/file/write` | POST | Write to file |
| `/shell` | POST | Execute shell commands |
| `/screenshot` | GET | Capture screenshot |
| `/webcam` | GET | Capture webcam image |

### Authentication

All remote requests require authentication:

```json
{
    "api_key": "your-api-key-here",
    "session_token": "session-token-from-auth",
    "command": "dir C:\\Users\\offic\\EAA"
}
```

### Security

- **API Key required** for all operations
- **Session tokens** for authenticated sessions
- **Path validation** prevents directory traversal
- **Dangerous commands blocked** in shell tool
- **Rate limiting** to prevent abuse

---

## File Structure

```
EAA/
│
├── src/                          # React Frontend
│   ├── App.tsx                   # Main application component
│   ├── App.css                   # Application styles
│   ├── main.tsx                  # React entry point
│   │
│   ├── components/               # UI Components
│   │   ├── ConnectionHub.tsx     # Connection screen
│   │   │
│   │   ├── canvas/               # Canvas Editor
│   │   │   ├── CanvasEditor.tsx      # Main editor
│   │   │   ├── CanvasContext.tsx     # State management
│   │   │   ├── CanvasPreview.tsx     # Live preview
│   │   │   ├── ProCanvasEditor.tsx   # Advanced editor
│   │   │   ├── AIAssistantPanel.tsx  # AI in editor
│   │   │   ├── VisualCanvas.tsx      # Visual editing
│   │   │   ├── ViewportFrame.tsx     # Responsive view
│   │   │   ├── docProject.ts         # Document projects
│   │   │   ├── htmlProject.ts        # HTML projects
│   │   │   └── pythonProject.ts      # Python projects
│   │   │
│   │   ├── tools/                # Tool Panels
│   │   │   ├── Logs/LogsPanel.tsx
│   │   │   ├── Read/ReadPanel.tsx
│   │   │   ├── Write/WritePanel.tsx
│   │   │   ├── Patch/PatchPanel.tsx
│   │   │   ├── Media/MediaPanel.tsx
│   │   │   ├── Workspace/WorkspacePanel.tsx
│   │   │   └── Sandbox/SandboxPanel.tsx
│   │   │
│   │   ├── HtmlCanvas/           # HTML Canvas
│   │   │   ├── HtmlCanvasProvider.tsx
│   │   │   └── defaultProject.ts
│   │   │
│   │   ├── ComfyPanel.tsx        # ComfyUI panel
│   │   └── PictureVideoTab.tsx   # Media tab
│   │
│   ├── hooks/                    # React Hooks
│   │   ├── useAI.ts              # AI generation hook
│   │   └── useComfyBridge.ts     # ComfyUI integration
│   │
│   └── assets/                   # Static assets
│       └── logo.png              # EAA logo
│
├── src-tauri/                    # Tauri/Rust Backend
│   ├── src/
│   │   ├── lib.rs                # Main Rust code
│   │   ├── main.rs               # Entry point
│   │   ├── comfyui_cmds.rs       # ComfyUI commands
│   │   └── health.rs             # Health check
│   │
│   ├── Cargo.toml                # Rust dependencies
│   ├── tauri.conf.json           # Tauri configuration
│   ├── capabilities/             # Tauri permissions
│   └── icons/                    # App icons
│
├── brains/                       # AI Models
│   ├── shadow_brain.gguf         # Main brain (1.4 GB) ✅ On GitHub
│   ├── shadow_brain/             # Full brain (local only) ❌ Too large
│   ├── master_baked/             # Fine-tuned model (local only) ❌ Too large
│   └── vision_qwen2vl/           # Vision model (local only) ❌ Too large
│
├── datasets/                     # Training Data
│   └── eaa_train.jsonl
│
├── train_data/                   # Training Datasets
│   ├── eaa_train.jsonl
│   ├── eaa_sft.jsonl
│   ├── master_train.jsonl
│   ├── shadow_train.jsonl
│   └── shadow_personality.jsonl
│
├── lora/                         # LoRA Adapters
│   └── master_qwen/
│
├── outputs/                      # Model Outputs
│   ├── master_qwen/
│   ├── qwen25_7b_lora/
│   └── shadow_temp/
│
├── outputs_master/               # Master Training Outputs
│   └── checkpoint-*/
│
├── outputs_shadow/               # Shadow Training Outputs
│   └── checkpoint-*/
│
├── presets/                      # Workflow Presets
│   ├── ltx_picture_no_picture_workflow.json
│   └── ltx_picture_with_picture_workflow.json
│
├── tools/                        # External Tools
│   └── cloudflared.exe           # Cloudflare tunnel
│
├── public/                       # Static Files
│   ├── logo.svg
│   └── icons/
│
├── Video/                        # ComfyUI Integration
│   └── ComfyUI/
│
├── .venv-hf/                     # Python Virtual Environment
│
├── # Python Agent Files
│   ├── run_eaa_agent.py          # Main agent runner
│   ├── run_eaa_agent_v2.py       # Agent v2
│   ├── run_eaa_agent_v3.py       # Agent v3
│   ├── eaa_agent_server.py       # FastAPI server
│   ├── eaa_agent_server_v2.py
│   ├── eaa_agent_server_v3.py
│   ├── eaa_agent_loop.py         # Agent loop
│   ├── eaa_agent_loop_v2.py
│   ├── eaa_agent_loop_v3.py
│   ├── eaa_agent_tools.py        # Tool registry
│   ├── eaa_agent_tools_v2.py
│   ├── eaa_agent_tools_v3.py
│   ├── eaa_agent_tools_v4.py
│   ├── eaa_agent_tools_v5_cpu.py
│   ├── eaa_agent_v6.py
│   └── eaa_agent_v8.py
│
├── # Control Station Files
│   ├── eaa_control_station_v2.py
│   ├── eaa_control_station_v3.py
│   ├── eaa_control_station_v4_no_timeout.py
│   ├── eaa_control_station_v5_remote.py
│   ├── eaa_control_manager.py
│   ├── eaa_control_manager_v2.py
│   ├── eaa_control_manager_v3.py
│   ├── eaa_control_manager_v4_no_timeout.py
│   ├── eaa_control_manager_v5.py
│   ├── eaa_control_manager_v5_complete.py
│   ├── eaa_control_v5_ALL_ENDPOINTS.py
│   ├── eaa_control_v6.py
│   ├── eaa_control_v6_complete.py
│   └── eaa_control_v6_final.py
│
├── # Other Python Files
│   ├── brain_manager.py          # Brain management
│   ├── eaa_tunnel.py             # Tunnel setup
│   ├── eaa_supervisor.py         # Supervision
│   ├── eaa_supervisor_v6.py
│   ├── eaa_supervisor_v6_final.py
│   ├── eaa_supervisor_v7.py
│   ├── eaa_supervisor_v8.py
│   ├── eaa_memory.py             # Memory system
│   ├── eaa_vision_manager.py     # Vision handling
│   ├── eaa_web_manager.py        # Web interface
│   ├── eaa_voice.py              # Voice processing
│   ├── eaa_ears.py               # Audio input
│   ├── eaa_clipboard.py          # Clipboard access
│   ├── eaa_files.py              # File operations
│   ├── eaa_image.py              # Image processing
│   ├── eaa_video_tool.py         # Video tools
│   ├── eaa_url.py                # URL handling
│   ├── eaa_wiki.py               # Wikipedia search
│   ├── eaa_stock.py              # Stock information
│   ├── eaa_timer.py              # Timer functionality
│   ├── eaa_cmd.py                # Command execution
│   ├── eaa_browser.py            # Browser control
│   ├── eaa_browser_use_cpu.py
│   ├── eaa_web_search_cpu.py
│   ├── eaa_web_researcher_cpu.py
│   ├── eaa_researcher.py
│   ├── eaa_researcher_brain.py
│   ├── eaa_smart_router.py       # Smart routing
│   ├── eaa_smart_router_v2.py
│   ├── eaa_auto_patch.py         # Auto patching
│   ├── eaa_unified.py            # Unified interface
│   ├── eaa_v8_unified.py
│   ├── eaa_mcp.py                # MCP integration
│   ├── eaa_monitor.py            # Monitoring
│   ├── eaa_terminal_controller.py
│   ├── eaa_tools_cpu.py
│   ├── eaa_tools_cpu_v2.py
│   ├── eaa_cpu_tools_patch.py
│   ├── bake_brains.py            # Brain training
│   ├── shadow_agent.py           # Shadow agent
│   ├── super_z.py                # Super Z integration
│   └── emergency_recover.py      # Emergency recovery
│
├── # Configuration Files
│   ├── package.json              # NPM dependencies
│   ├── vite.config.ts            # Vite configuration
│   ├── tsconfig.json             # TypeScript config
│   ├── eslint.config.js          # ESLint config
│   ├── index.html                # Entry HTML
│   ├── Modelfile                 # Ollama model file
│   ├── .gitignore                # Git ignore rules
│   └── .gitattributes            # Git LFS config
│
├── README.md                     # This file
└── UPGRADES_TO_DO.md             # Planned upgrades (see below)
```

---

## Upgrades To Do

> 📋 **See [UPGRADES_TO_DO.md](./UPGRADES_TO_DO.md) for the complete list of planned upgrades!**

EAA is continuously evolving. Here's a summary of planned upgrades to make EAA as capable as Z.ai, Claude, and GLM-5:

### Current Tools: 19 ✅

### Planned: 50+ New Tools

| Phase | Category | Tools | Priority |
|-------|----------|-------|----------|
| **1** | Multi-Modal | `image_analyze`, `image_generate`, `ocr_extract` | HIGH |
| **2** | Documents | `pdf_read`, `docx_create`, `xlsx_read` | HIGH |
| **3** | Code Execution | `code_run`, `git_status`, `git_commit` | HIGH |
| **4** | System | `screenshot`, `clipboard_read`, `process_list` | MEDIUM |
| **5** | Browser | `browser_open`, `browser_click`, `browser_type` | MEDIUM |
| **6** | Communication | `email_send`, `notify_send` | MEDIUM |
| **7** | Advanced Memory | `memory_search`, `context_save` | MEDIUM |
| **8** | Data | `csv_read`, `database_query`, `api_call` | LOW |
| **9** | Audio/Video | `audio_transcribe`, `audio_generate` | LOW |
| **10** | Scheduling | `schedule_task`, `schedule_list` | LOW |

### Required Packages

```bash
pip install Pillow pytesseract PyPDF2 python-docx openpyxl python-pptx psutil pyperclip pyautogui
```

---

## Getting Started

### Prerequisites

- **Node.js** 18+ and npm
- **Python** 3.10+
- **Rust** (for Tauri)
- **CUDA-capable GPU** (recommended for AI inference)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Majed-Alsho/EAA-Embedded-Ai-Assistant-.git
   cd EAA-Embedded-Ai-Assistant-
   ```

2. **Install Node.js dependencies:**
   ```bash
   npm install
   ```

3. **Set up Python environment:**
   ```bash
   python -m venv .venv-hf
   .venv-hf\Scripts\activate  # Windows
   pip install -r requirements.txt
   ```

4. **Download AI brain:**
   Place your GGUF model file in `brains/shadow_brain.gguf`
   
   Or download from HuggingFace (recommended models):
   - Qwen2.5-7B-Instruct-GGUF
   - Llama-3.2-3B-Instruct-GGUF

5. **Build Tauri:**
   ```bash
   cd src-tauri
   cargo build
   cd ..
   ```

### Running

**Development mode:**
```bash
npm run tauri dev
```

**Production build:**
```bash
npm run tauri build
```

### Configuration

- Edit `src-tauri/tauri.conf.json` for Tauri settings
- Edit `eaa_agent_server.py` for AI server settings
- Edit `src/App.tsx` for frontend configuration

---

## Author

**Majed Al-Shoghri**

---

## License

MIT License - Feel free to use, modify, and distribute.

---

<div align="center">

**Made with ❤️ for privacy-focused AI assistance**

</div>
