"""
EAA Canvas Enhancement - Integration Guide
==========================================

This guide shows how to integrate the multi-language error detection
and AI fix functionality into your EAA backend.

QUICK SETUP:
------------

1. Copy 'canvas_integration.py' to your EAA folder:
   C:\Users\offic\EAA\canvas_integration.py

2. Add ONE import and ONE function call to your run_eaa_agent.py:

   At the top of run_eaa_agent.py, add:
   ----------------------------------------
   from canvas_integration import setup_canvas_endpoints
   ----------------------------------------

   Then in your startup code, after the app is created, add:
   ----------------------------------------
   setup_canvas_endpoints(app, brain)
   ----------------------------------------

3. That's it! The canvas will now:
   - Auto-detect languages (Python, JS, HTML, etc.)
   - Show errors for ALL languages
   - Have a working "Fix with AI" button

FULL INTEGRATION EXAMPLE:
-------------------------

Here's how your run_eaa_agent.py should look after integration:

```python
# ... existing imports ...
from canvas_integration import setup_canvas_endpoints

# ... existing code ...

brain = brain_manager.BrainManager()
app = FastAPI()
app.add_middleware(CORSMiddleware, ...)

# 🤖 SETUP AGENT ENDPOINTS
if HAS_AGENT:
    setup_agent_endpoints(app, brain)

# 🎨 SETUP CANVAS ENDPOINTS (NEW!)
setup_canvas_endpoints(app, brain)
print("[SYSTEM] 🎨 Canvas Endpoints Active!")

# ... rest of your code ...
```

NEW ENDPOINTS ADDED:
--------------------

POST /v1/canvas/analyze
    Analyzes code for errors with auto language detection
    Request: { "code": "...", "filename": "test.py", "run_code": false }
    Response: {
        "success": true/false,
        "language": "python",
        "errors": [{ "line": 1, "message": "...", "suggestion": "..." }],
        "warnings": [...]
    }

POST /v1/canvas/detect-language
    Detects the programming language of code
    Request: { "code": "...", "filename": null }
    Response: { "language": "python" }

POST /v1/canvas/fix
    Fixes code using AI
    Request: { "code": "...", "errors": [...], "language": "python" }
    Response: {
        "success": true,
        "fixed_code": "...",
        "original_code": "..."
    }

POST /v1/canvas/analyze-and-fix
    One-click analyze and fix
    Request: { "code": "...", "filename": null, "run_code": false }
    Response: {
        "language": "python",
        "errors": [...],
        "fixed_code": "..."
    }

SUPPORTED LANGUAGES:
--------------------
- Python (.py)
- JavaScript (.js, .jsx)
- TypeScript (.ts, .tsx)
- HTML (.html, .htm)
- CSS (.css, .scss, .less)
- Java (.java)
- C++ (.cpp, .cc, .hpp)
- C (.c, .h)
- Rust (.rs)
- Go (.go)
- PHP (.php)
- Ruby (.rb)
- SQL (.sql)
- JSON (.json)

HOW IT WORKS:
-------------

1. AUTO LANGUAGE DETECTION:
   The system uses pattern matching to identify languages.
   - Checks file extension first (if filename provided)
   - Then uses code patterns (def, function, class, etc.)
   - Works with as little as 2 matching patterns

2. ERROR DETECTION:
   Python: Uses compile() + optional runtime execution
   JavaScript: Uses Node.js --check (if available)
   HTML: Parses tags, checks for unclosed elements
   CSS: Basic bracket matching
   Java: Uses javac (if available)

3. AI FIX:
   Uses your local Qwen2.5-Coder-7B model to generate fixes.
   Prompts are optimized for each language.
   Returns both fixed code and explanation.

TROUBLESHOOTING:
----------------

Q: Node.js errors not showing?
A: Make sure Node.js is installed and in PATH.
   Test with: node --version

Q: Python errors not showing?
A: Python syntax errors always show.
   Runtime errors need run_code=true.

Q: "Fix with AI" button not working?
A: Make sure the endpoint is reachable.
   Check browser console for errors.

Q: Language not detected correctly?
A: The system needs at least 2 pattern matches.
   Or provide a filename with extension.

"""

# ============================================================
# MINIMAL INTEGRATION - COPY THIS INTO YOUR run_eaa_agent.py
# ============================================================

INTEGRATION_CODE = '''
# Add after your imports:
from canvas_integration import setup_canvas_endpoints

# Add after app creation and before uvicorn.run():
setup_canvas_endpoints(app, brain)
print("[SYSTEM] 🎨 Canvas Endpoints Active!")
'''

# ============================================================
# ALTERNATIVE: Inline integration (no extra file needed)
# ============================================================

INLINE_INTEGRATION = '''
# Add this directly to run_eaa_agent.py if you don't want
# to create a separate canvas_integration.py file:

import re
import tempfile
import subprocess

# Language Detection
def detect_language(code: str, filename: str = None) -> str:
    ext_map = {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
        '.html': 'html', '.htm': 'html', '.css': 'css',
        '.java': 'java', '.cpp': 'cpp', '.c': 'c',
        '.rs': 'rust', '.go': 'go', '.php': 'php', '.rb': 'ruby',
    }
    
    if filename:
        import os
        ext = os.path.splitext(filename)[1].lower()
        if ext in ext_map:
            return ext_map[ext]
    
    patterns = {
        'python': [r'^\\s*(def|class|import|from)', r'self\\.', r':\\s*$'],
        'javascript': [r'(const|let|var)\\s+', r'function\\s+', r'=>\\s*\\{'],
        'html': [r'<html', r'<head', r'<body', r'<div'],
    }
    
    for lang, pats in patterns.items():
        score = sum(len(re.findall(p, code, re.M)) for p in pats)
        if score >= 2:
            return lang
    
    return 'unknown'

# Error Check
def check_code(code: str, language: str, run: bool = False):
    errors = []
    
    if language == 'python':
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            errors.append({
                'line': e.lineno or 1,
                'message': e.msg,
                'severity': 'error'
            })
    
    elif language in ('javascript', 'typescript'):
        # Try Node.js
        try:
            import tempfile, os
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
                f.write(code)
                temp = f.name
            result = subprocess.run(['node', '--check', temp], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                for line in result.stderr.split('\\n'):
                    if 'SyntaxError:' in line:
                        m = re.search(r'SyntaxError: (.+)', line)
                        if m:
                            errors.append({'line': 1, 'message': m.group(1), 'severity': 'error'})
            os.unlink(temp)
        except:
            pass
    
    elif language == 'html':
        # Check unclosed tags
        void_tags = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
        stack = []
        for match in re.finditer(r'<(/?)(\\w+)[^>]*>', code):
            is_close, tag = match.groups()
            if tag.lower() in void_tags:
                continue
            if is_close:
                if stack and stack[-1] == tag:
                    stack.pop()
                else:
                    errors.append({'line': 1, 'message': f'Unexpected </{tag}>', 'severity': 'error'})
            else:
                stack.append(tag)
        
        for tag in stack:
            errors.append({'line': 1, 'message': f'Unclosed <{tag}>', 'severity': 'error'})
    
    return errors

# Endpoints
from pydantic import BaseModel
from typing import List, Optional, Dict

class AnalyzeReq(BaseModel):
    code: str
    filename: Optional[str] = None
    run_code: bool = False

class FixReq(BaseModel):
    code: str
    errors: List[Dict]
    language: str

ID_CODER = "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit"

@app.post("/v1/canvas/analyze")
async def canvas_analyze(req: AnalyzeReq):
    lang = detect_language(req.code, req.filename)
    errors = check_code(req.code, lang, req.run_code)
    return {"success": len(errors)==0, "language": lang, "errors": errors, "warnings": []}

@app.post("/v1/canvas/fix")
async def canvas_fix(req: FixReq):
    error_text = "\\n".join([f"Line {e.get('line')}: {e.get('message')}" for e in req.errors])
    prompt = f"Fix this {req.language} code. Return ONLY corrected code in a code block.\\n\\nCode:\\n```{req.language}\\n{req.code}\\n```\\n\\nErrors:\\n{error_text}"
    
    response = brain.generate_text(ID_CODER, "You are a code fixer.", prompt, max_new_tokens=2048, temperature=0.1)
    
    # Extract code from response
    match = re.search(rf'```{req.language}\\s*\\n(.*?)```', response, re.DOTALL)
    fixed = match.group(1).strip() if match else response
    
    return {"success": True, "fixed_code": fixed, "original_code": req.code, "language": req.language}

@app.post("/v1/canvas/detect-language")
async def canvas_detect(req: AnalyzeReq):
    return {"language": detect_language(req.code, req.filename)}

print("[CANVAS] ✅ Canvas endpoints added!")
'''

if __name__ == "__main__":
    print(__doc__)
    print("\n" + "="*60)
    print("INLINE INTEGRATION CODE:")
    print("="*60)
    print(INLINE_INTEGRATION)
