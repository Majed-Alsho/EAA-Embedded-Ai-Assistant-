# EAA - Embedded AI Assistant

A powerful local AI assistant built with Tauri 2, React, TypeScript, and Python.

## Features
- Local LLM Integration
- Multi-Brain Support
- Tool System (19+ tools)
- Modern UI with Tauri 2
- Remote Control via Cloudflare tunnel
- Canvas Editor with Monaco
- Voice interaction (VAD, TTS, STT)

## Brains (AI Models)

EAA uses multiple AI brains for different tasks. These are stored locally in the `brains/` folder:

| Brain | Location | Size | Description |
|-------|----------|------|-------------|
| **Shadow Brain** | `brains/shadow_brain.gguf` | 1.4 GB | Main conversational brain (GGUF format) |
| **Shadow Brain (Full)** | `brains/shadow_brain/shadow_brain.gguf` | 5.4 GB | Full precision shadow brain |
| **Master Baked** | `brains/master_baked/` | 5.5 GB | Fine-tuned Qwen model (safetensors) |
| **Vision Qwen2VL** | `brains/vision_qwen2vl/` | 4.1 GB | Vision-capable model for image understanding |

### Why are some brains not on GitHub?

GitHub has a **2GB file size limit** even with Git LFS. The following brain files exceed this limit and could not be pushed:

- `brains/shadow_brain/shadow_brain.gguf` (5.4 GB) 
- `brains/master_baked/model-00001-of-00002.safetensors` (4.1 GB)
- `brains/master_baked/model-00002-of-00002.safetensors` (1.0 GB)
- `brains/vision_qwen2vl/model.safetensors` (4.1 GB)

**Solution:** For sharing large model files, consider using:
- [Hugging Face](https://huggingface.co/) - No file size limits for models
- Google Drive / OneDrive
- Dedicated model hosting services

### Brains Folder Structure

```
brains/
├── shadow_brain.gguf          # Main brain (in GitHub)
├── shadow_brain/              # Full precision version (local only - too large)
│   └── shadow_brain.gguf
├── master_baked/              # Fine-tuned model (local only - too large)
│   ├── model-00001-of-00002.safetensors
│   └── model-00002-of-00002.safetensors
└── vision_qwen2vl/            # Vision model (local only - too large)
    └── model.safetensors
```

## Tech Stack

### Frontend
- **Tauri 2** - Native desktop app
- **React 19** - UI framework
- **TypeScript** - Type safety
- **Monaco Editor** - Code editing
- **Vite** - Build tool

### Backend (Python)
- **FastAPI** - API server
- **llama-cpp-python** - LLM inference
- **DuckDuckGo Search** - Web search
- **PyAudio** - Voice processing

## Tools (19+)

EAA has a powerful tool system including:
- `read_file` - Read file contents
- `write_file` - Write/create files
- `list_files` - Directory listing
- `web_search` - Search the web
- `execute_code` - Run Python code
- `memory_save` / `memory_recall` - Persistent memory
- And many more...

See `UPGRADES_TO_DO.md` for planned 50+ new tools.

## Project Structure

```
EAA/
├── src/                    # React frontend
│   ├── components/         # UI components
│   │   ├── canvas/         # Canvas editor
│   │   └── tools/          # Tool panels
│   └── hooks/              # React hooks
├── src-tauri/              # Tauri/Rust backend
│   └── src/
│       └── lib.rs          # Main Rust code
├── brains/                 # AI models (local)
├── datasets/               # Training data
├── train_data/             # Training datasets
├── lora/                   # LoRA adapters
├── outputs/                # Model outputs
├── presets/                # Workflow presets
├── tools/                  # External tools
├── public/                 # Static assets
├── Video/                  # ComfyUI integration
├── eaa_agent_*.py          # Agent system files
├── run_eaa_agent.py        # Main agent runner
└── brain_manager.py        # Brain management
```

## Getting Started

1. Install dependencies:
   ```bash
   npm install
   cd src-tauri && cargo build
   ```

2. Set up Python environment:
   ```bash
   python -m venv .venv-hf
   .venv-hf\Scripts\activate
   pip install -r requirements.txt
   ```

3. Run the app:
   ```bash
   npm run tauri dev
   ```

## Author

**Majed Al-Shoghri**

## License

MIT