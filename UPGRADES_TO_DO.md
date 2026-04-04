# EAA Upgrades To Do

This file contains planned upgrades to make EAA as capable as Z.ai, Claude, and GLM-5.

---

## Current Tools (19)

EAA currently has these tools in `eaa_agent_tools.py`:

| Tool | Description |
|------|-------------|
| read_file | Read file contents |
| write_file | Write content to file |
| append_file | Append to file |
| list_files | List directory contents |
| file_exists | Check if file exists |
| create_directory | Create a directory |
| delete_file | Delete file or directory |
| glob | Find files by pattern |
| grep | Search text in files |
| shell | Execute shell commands |
| web_search | Search the web (DuckDuckGo) |
| web_fetch | Fetch URL content |
| memory_save | Save to memory |
| memory_recall | Recall from memory |
| memory_list | List memory keys |
| datetime | Get current date/time |
| calculator | Evaluate math expressions |
| python | Execute Python code |

---

## Planned Upgrades (50+ Tools)

### Phase 1: Multi-Modal Tools (HIGH PRIORITY)

| Tool | Description | Status |
|------|-------------|--------|
| image_analyze | Analyze images with AI vision | Planned |
| image_generate | Generate images from text prompts | Planned |
| image_describe | Describe image content in detail | Planned |
| ocr_extract | Extract text from images (OCR) | Planned |

**Required packages:** `pip install Pillow pytesseract`

---

### Phase 2: Document Processing Tools (HIGH PRIORITY)

| Tool | Description | Status |
|------|-------------|--------|
| pdf_rry SQLite database | Planned |
| api_call | Make HTTP API calls | Planned |
| hash_text | Hash text (MD5, SHA, etc.) | Planned |

---

### Phase 9: Audio/Video Tools (LOW PRIORITY)

| Tool | Description | Status |
|------|-------------|--------|
| audio_transcribe | Transcribe audio to text | Planned |
| audio_generate | Generate speech from text (TTS) | Planned |
| video_analyze | Analyze video content | Planned |

---

### Phase 10: Scheduling Tools (LOW PRIORITY)

| Tool | Description | Status |
|------|-------------|--------|
| schedule_task | Schedule a task for later | Planned |
| schedule_list | List scheduled tasks | Planned |
| schedule_cancel | Cancel scheduled task | Planned |

---

## Enhanced Tool Registry Features

The new `eaa_agent_tools_enhanced.py` will include:

### 1. Tool Categories
Tools organized by category for better selection:
- `file` - File operations
- `web` - Web tools
- `memory` - Memory tools
- `code` - Code execution
- `document` - Document processing
- `system` - System operations
- `multimodal` - Image/audio/video
- `data` - Data processing
- `utility` - General utilities

### 2. Tool Chaining
Execute multiple tools in sequence:
```python
from eaa_agent_tools_enhanced import ToolChainExecutor

executor = ToolChainExecutor(registry)
results = executor.execute_chain([
    {"tool": "web_search", "args": {"query": "AI news"}},
    {"tool": "web_fetch", "args": {"url": "$result_0.data.results.0.href"}}
])
```

### 3. OpenAI Function Calling Forma brain prompts to know about new tools

---

## Status Legend

- **Planned** - Not yet implemented
- **In Progress** - Currently being worked on
- **Testing** - Implemented, needs testing
- **Complete** - Fully working

---

*Last updated: 2026-04-04*
t environment variable | Planned |

**Required packages:** `pip install psutil pyperclip pyautogui`

---

### Phase 5: Browser Automation (MEDIUM PRIORITY)

| Tool | Description | Status |
|------|-------------|--------|
| browser_open | Open URL in browser | Planned |
| browser_click | Click element on page | Planned |
| browser_type | Type text into field | Planned |
| browser_screenshot | Capture page screenshot | Planned |
| browser_scroll | Scroll page | Planned |

**Required packages:** `pip install playwright` or use Selenium

---

### Phase 6: Communication Tools (MEDIUM PRIORITY)

| Tool | Description | Status |
|------|-------------|--------|
| email_send | Send emails via SMTP | Planned |
| notify_send | Desktop notifications | Planned |
| sms_send | Send SMS (via API) | Planned |

---

### Phase 7: Advanced Memory (MEDIUM PRIORITY)

| Tool | Description | Status |
|------|-------------|--------|
| memory_search | Search memory by content | Planned |
| memory_clear | Clear all memory | Planned |
| memory_export | Export memory to file | Planned |
| memory_import | Import memory from file | Planned |
| context_save | Save conversation context | Planned |
| context_load | Load conversation context | Planned |

---

### Phase 8: Data Tools (LOW PRIORITY)

| Tool | Description | Status |
|------|-------------|--------|
| json_parse | Parse and query JSON | Planned |
| csv_read | Read CSV files | Planned |
| csv_write | Write CSV files | Planned |
| database_query | Queead | Read PDF files and extract text | Planned |
| pdf_create | Create PDF documents | Planned |
| docx_read | Read Word documents | Planned |
| docx_create | Create Word documents | Planned |
| xlsx_read | Read Excel files | Planned |
| xlsx_create | Create Excel files | Planned |
| pptx_read | Read PowerPoint files | Planned |
| pptx_create | Create PowerPoint presentations | Planned |

**Required packages:** `pip install PyPDF2 python-docx openpyxl python-pptx`

---

### Phase 3: Code Execution Tools (HIGH PRIORITY)

| Tool | Description | Status |
|------|-------------|--------|
| code_run | Execute code safely in sandbox | Planned |
| code_lint | Check code quality | Planned |
| code_format | Format code (black, prettier) | Planned |
| code_test | Run unit tests | Planned |
| git_status | Check git repository status | Planned |
| git_commit | Commit changes | Planned |
| git_diff | Show differences | Planned |
| git_log | Show commit history | Planned |

---

### Phase 4: System Tools (MEDIUM PRIORITY)

| Tool | Description | Status |
|------|-------------|--------|
| screenshot | Capture screen | Planned |
| clipboard_read | Read clipboard content | Planned |
| clipboard_write | Write to clipboard | Planned |
| process_list | List running processes | Planned |
| process_kill | Kill a process by PID | Planned |
| system_info | Get system information | Planned |
| app_launch | Launch applications | Planned |
| env_get | Get environment variable | Planned |
| env_set | Set
Get tools in proper schema for LLM function calling:
```python
tools_schema = registry.get_tools_for_llm()
# Returns list of tool definitions compatible with OpenAI API
```

### 4. Safety Features
- Dangerous tools marked with `is_dangerous` flag
- Blocked dangerous shell commands
- Timeout handling for all operations
- Proper error recovery

### 5. Execution History
All tool executions logged with:
- Tool name
- Arguments
- Success/failure
- Duration
- Timestamp

---

## Implementation Files

When ready to implement, these files will be created/modified:

1. **`eaa_agent_tools_enhanced.py`** - New enhanced tools (50+ tools)
2. **`eaa_multimodal_tools.py`** - Image/video/audio tools
3. **`eaa_document_tools.py`** - Document processing tools
4. **`eaa_system_tools.py`** - System operations tools
5. **`eaa_browser_tools.py`** - Browser automation tools
6. **`eaa_tool_executor.py`** - Smart tool execution with chaining

---

## Required Packages

Install all required packages:
```bash
pip install duckduckgo-search requests Pillow pytesseract PyPDF2 pandas pyperclip psutil pyautogui python-docx openpyxl python-pptx
```

---

## Integration

To integrate enhanced tools into existing EAA:

1. Copy `eaa_agent_tools_enhanced.py` to EAA folder
2. Update `run_eaa_agent_v3.py` to import from new tools file:
```python
from eaa_agent_tools_enhanced import create_tool_registry, ToolChainExecutor

registry = create_tool_registry()
tools_schema = registry.get_tools_for_llm()
```

3. Update