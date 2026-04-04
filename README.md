# EAA - Embedded AI Assistant

## What is EAA?

EAA (Embedded AI Assistant) is a fully local AI assistant that runs entirely on your computer. Unlike cloud-based AI assistants like ChatGPT or Claude, EAA runs 100% locally - your data never leaves your machine. Built with Tauri 2, React 19, TypeScript, and Python, EAA combines a modern desktop application with powerful AI capabilities.

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

EAA consists of three main layers:

```
+-------------------------------------------------------------+
|                     DESKTOP APP (Tauri 2)                   |
|  +-----------------------------------------------------+   |
|  |           Frontend (React 19 + TypeScript)          |   |
|  |  +-----------+ +-----------+ +-------------------+  |   |
|  |  |   Chat    | |  Canvas   | |   Tool Panels     |  |   |
|  |  | Interface | |  Editor   | | (Read/Write/etc)  |  |   |
|  |  +-----------+ +-----------+ +-------------------+  |   |
|  +-----------------------------------------------------+   |
|                           |                                 |
|                    Tauri IPC Bridge                        |
|                           |                                 |
|  +-----------------------------------------------------+   |
|  |           Rust Backend (lib.rs)                      |   |
|  |  - Process Management (Python Agent)                 |   |
|  |  - File System Access                                |   |
|  |  - Brain Health Checks                               |   |
|  |  - ComfyUI Integration                               |   |
|  +-----------------------------------------------------+   |
+-------------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------------+
|              PYTHON BACKEND (FastAPI Server)                |
|  +-----------------------------------------------------+   |
|  |  eaa_agent_server.py (Port 8000)                     |   |
|  |  - /v1/health - Health check                        |   |
|  |  - /v1/tools - List available tools                 |   |
|  |  - /v1/chat/completions - Chat with AI              |   |
|  |  - /ai/chat - Chat with tool execution              |   |
|  +-----------------------------------------------------+   |
|                           |                                 |
|  +-----------------------------------------------------+   |
|  |  AI Brain (llama-cpp-python)                         |   |
|  |  - Loads GGUF models from brains/ folder            |   |
|  |  - Generates AI responses                           |   |
|  |  - Decides when to use tools                        |   |
|  +-----------------------------------------------------+   |
|                           |                                 |
|  +-----------------------------------------------------+   |
|  |  Tool Registry (eaa_agent_tools.py)                  |   |
|  |  - 19+ tools for file, web, memory, code            |   |
|  |  - Executes tool calls from AI                      |   |
|  +-----------------------------------------------------+   |
+-------------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------------+
|                 CLOUDFLARE TUNNEL (Optional)                |
|  - Secure tunnel from internet to local PC                 |
|  - Allows Z.ai to connect to your EAA                      |
|  - URL: https://xxx-xxx-xxx.trycloudflare.com              |
+-------------------------------------------------------------+
```

See the full README at: https://github.com/Majed-Alsho/EAA-Embedded-Ai-Assistant-

---

## Brains (AI Models)

EAA uses multiple AI brains for different tasks:

| Brain | Location | Size | Purpose |
|-------|----------|------|---------|
| **Shadow Brain** | `brains/shadow_brain.gguf` | 1.4 GB | Main conversational AI |
| **Shadow Brain (Full)** | `brains/shadow_brain/shadow_brain.gguf` | 5.4 GB | Full precision (local only) |
| **Master Baked** | `brains/master_baked/` | 5.5 GB | Fine-tuned Qwen model (local only) |
| **Vision Qwen2VL** | `brains/vision_qwen2vl/` | 4.1 GB | Vision model (local only) |

### Why Some Brains Are Not on GitHub

GitHub has a **2GB file size limit** even with Git LFS:

- `brains/shadow_brain/shadow_brain.gguf` (5.4 GB) - Exceeds limit
- `brains/master_baked/model-00001-of-00002.safetensors` (4.1 GB) - Exceeds limit
- `brains/master_baked/model-00002-of-00002.safetensors` (1.0 GB)
- `brains/vision_qwen2vl/model.safetensors` (4.1 GB) - Exceeds limit

---

## Remote Control & Z.ai Connection

EAA can be controlled remotely via a Cloudflare tunnel:

```
+-------------+         +------------------+         +-------------+
|   Z.ai      | ------> | Cloudflare       | ------> |  Your PC    |
|  (Internet) |         | Tunnel Server    |         |  (EAA)      |
+-------------+         +------------------+         +-------------+
```

### What Z.ai Can Do Through the Tunnel

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

### API Endpoints for Remote Access

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/health` | GET | Check if EAA is online |
| `/v1/tools` | GET | List available tools |
| `/v1/chat/completions` | POST | Chat with AI |
| `/auth` | POST | Authenticate with API key |
| `/file/list` | POST | List files in directory |
| `/file/read` | POST | Read file contents |
| `/file/write` | POST | Write to file |
| `/shell` | POST | Execute shell commands |

---

## Current Tools (19)

| Category | Tool | Description |
|----------|------|-------------|
| **File** | `read_file` | Read file contents |
| **File** | `write_file` | Write content to file |
| **File** | `list_files` | List directory contents |
| **File** | `glob` | Find files by pattern |
| **File** | `grep` | Search text in files |
| **System** | `shell` | Execute shell commands |
| **Web** | `web_search` | Search the web (DuckDuckGo) |
| **Web** | `web_fetch` | Fetch URL content |
| **Memory** | `memory_save` | Save to persistent memory |
| **Memory** | `memory_recall` | Retrieve saved information |
| **Utility** | `datetime` | Get current date/time |
| **Utility** | `calculator` | Evaluate math expressions |
| **Code** | `python` | Execute Python code |

---

## Upgrades To Do (50+ Tools Planned)

### Phase 1: Multi-Modal Tools (HIGH PRIORITY)
- `image_analyze` - Analyze images with AI vision
- `image_generate` - Generate images from text
- `ocr_extract` - Extract text from images

### Phase 2: Document Processing
- `pdf_read` / `pdf_create` - PDF handling
- `docx_read` / `docx_create` - Word documents
- `xlsx_read` / `xlsx_create` - Excel files

### Phase 3: Code Execution
- `code_run` - Execute code in sandbox
- `git_status` / `git_commit` - Git operations

### Phase 4: System Tools
- `screenshot` - Capture screen
- `clipboard_read` / `clipboard_write` - Clipboard access
- `process_list` / `process_kill` - Process management

### Phase 5: Browser Automation
- `browser_open` / `browser_click` / `browser_type`

---

## Getting Started

1. Install: `npm install`
2. Python setup: `pip install -r requirements.txt`
3. Place brain in `brains/shadow_brain.gguf`
4. Run: `npm run tauri dev`

---

## Author

**Majed Al-Shoghri**

## License

MIT