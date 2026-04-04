"""
EAA Canvas Integration Module
=============================
Complete canvas functionality with:
- Auto language detection
- Multi-language error detection
- AI-powered code fixing

Add this to your run_eaa_agent.py by importing and calling setup_canvas_endpoints()
"""

import os
import json
import tempfile
import subprocess
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
from fastapi import HTTPException
from pydantic import BaseModel


# ============================================
# LANGUAGE DETECTION
# ============================================

class Language(Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    HTML = "html"
    CSS = "css"
    JAVA = "java"
    CPP = "cpp"
    C = "c"
    RUST = "rust"
    GO = "go"
    PHP = "php"
    RUBY = "ruby"
    SQL = "sql"
    JSON = "json"
    UNKNOWN = "unknown"


LANGUAGE_SIGNATURES = {
    Language.PYTHON: [
        r'^\s*(def|class|import|from|if\s+__name__|async\s+def|await\s+)',
        r'^\s*(print|input|len|range|str\(|int\(|float\()',
        r':\s*$',
        r'(elif|except|finally|with\s+\w+\s+as)',
        r'__init__|__str__|__repr__|self\.',
        r'@\w+\s*\n\s*def',
        r'f["\'].*?\{.*?\}.*?["\']',
    ],
    Language.JAVASCRIPT: [
        r'(const|let|var)\s+\w+\s*=',
        r'function\s+\w+\s*\(|=>\s*\{',
        r'(async\s+function|async\s*\(|await\s+)',
        r'(document\.|window\.|console\.)',
        r'\.innerHTML|\.textContent|\.appendChild',
        r'(fetch\(|Promise|\.then\(|\.catch\()',
        r'(export\s+(default\s+)?|import\s+.*from)',
    ],
    Language.TYPESCRIPT: [
        r':\s*(string|number|boolean|any|void|never)\s*[=\)\{]',
        r'interface\s+\w+\s*\{',
        r'type\s+\w+\s*=',
        r'<\w+>',
        r'(public|private|protected)\s+\w+\s*[=\(]',
    ],
    Language.HTML: [
        r'<!DOCTYPE\s+html',
        r'<html',
        r'<head|<body|<div|<span|<p>',
        r'<script|<style',
        r'<\/[a-z]+>',
    ],
    Language.CSS: [
        r'^\s*\*?\s*[.#]?\w+\s*\{',
        r'(@media|@keyframes|@import)',
        r'(margin|padding|border|color|background|font|display)\s*:',
    ],
    Language.JAVA: [
        r'(public|private|protected)\s+(class|interface|enum)',
        r'(System\.out\.print|System\.in)',
        r'(import\s+java\.)',
        r'(public\s+static\s+void\s+main)',
    ],
    Language.CPP: [
        r'#include\s*<',
        r'(std::|cout|cin|endl)',
        r'(namespace\s+\w+)',
        r'(class\s+\w+\s*\{|struct\s+\w+)',
    ],
    Language.RUST: [
        r'(fn\s+\w+\s*\(|pub\s+fn)',
        r'(let\s+mut|let\s+\w+:)',
        r'(impl\s+\w+|trait\s+\w+)',
        r'(println!|format!|vec!)',
    ],
    Language.GO: [
        r'package\s+(main|\w+)',
        r'func\s+(main|\w+)\s*\(',
        r'(import\s*\(|import\s+"',
        r'(fmt\.Print|fmt\.Scan)',
    ],
    Language.PHP: [
        r'<\?php',
        r'(\$\w+\s*=|\$this->)',
        r'(echo\s+|print\s+)',
    ],
    Language.RUBY: [
        r'(def\s+\w+|end\s*$)',
        r'(class\s+\w+|module\s+\w+)',
        r'(require|include)\s+["\']',
    ],
    Language.SQL: [
        r'(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\s+',
        r'(FROM|WHERE|JOIN|GROUP BY|ORDER BY)\s+',
    ],
}

EXTENSION_MAP = {
    '.py': Language.PYTHON,
    '.js': Language.JAVASCRIPT,
    '.mjs': Language.JAVASCRIPT,
    '.ts': Language.TYPESCRIPT,
    '.tsx': Language.TYPESCRIPT,
    '.jsx': Language.JAVASCRIPT,
    '.html': Language.HTML,
    '.htm': Language.HTML,
    '.css': Language.CSS,
    '.scss': Language.CSS,
    '.less': Language.CSS,
    '.java': Language.JAVA,
    '.cpp': Language.CPP,
    '.cc': Language.CPP,
    '.c': Language.C,
    '.h': Language.C,
    '.hpp': Language.CPP,
    '.rs': Language.RUST,
    '.go': Language.GO,
    '.php': Language.PHP,
    '.rb': Language.RUBY,
    '.sql': Language.SQL,
    '.json': Language.JSON,
}


def detect_language(code: str, filename: str = None) -> str:
    """Detect programming language from code content"""
    
    # Try extension first
    if filename:
        ext = os.path.splitext(filename)[1].lower()
        if ext in EXTENSION_MAP:
            return EXTENSION_MAP[ext].value
    
    # Pattern matching
    scores = {lang: 0 for lang in Language}
    
    for lang, patterns in LANGUAGE_SIGNATURES.items():
        for pattern in patterns:
            matches = re.findall(pattern, code, re.MULTILINE | re.IGNORECASE)
            scores[lang] += len(matches)
    
    best_lang = max(scores, key=scores.get)
    
    if scores[best_lang] >= 2:
        return best_lang.value
    
    # Check for HTML
    if re.search(r'<\w+[^>]*>', code) and re.search(r'</\w+>', code):
        return "html"
    
    return "unknown"


# ============================================
# ERROR DETECTION
# ============================================

@dataclass
class CodeError:
    line: int
    column: int
    message: str
    severity: str
    code: str
    suggestion: Optional[str] = None
    
    def to_dict(self):
        return asdict(self)


def check_python_errors(code: str, run_code: bool = False) -> List[CodeError]:
    """Check Python code for errors"""
    errors = []
    
    # Syntax check
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        suggestion = None
        if "expected ':'" in str(e.msg):
            suggestion = "Add a colon (:) at the end of the statement"
        elif "invalid syntax" in str(e.msg):
            suggestion = "Check for missing parentheses, brackets, or operators"
        elif "unexpected EOF" in str(e.msg):
            suggestion = "Code is incomplete - check for unclosed brackets or quotes"
        
        errors.append(CodeError(
            line=e.lineno or 1,
            column=e.offset or 0,
            message=e.msg,
            severity="error",
            code="SyntaxError",
            suggestion=suggestion
        ))
    
    # Runtime check
    if run_code and len(errors) == 0:
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_path = f.name
            
            result = subprocess.run(
                ['python', temp_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                stderr = result.stderr
                # Parse error
                for line in stderr.split('\n'):
                    if 'Error:' in line or 'Exception:' in line:
                        match = re.search(r'(\w+Error|\w+Exception): (.+)', line)
                        if match:
                            # Find line number
                            line_match = re.search(r'line (\d+)', stderr)
                            line_num = int(line_match.group(1)) if line_match else 1
                            
                            errors.append(CodeError(
                                line=line_num,
                                column=0,
                                message=match.group(2),
                                severity="error",
                                code=match.group(1)
                            ))
                            break
        except subprocess.TimeoutExpired:
            errors.append(CodeError(
                line=0, column=0,
                message="Execution timed out",
                severity="error",
                code="TimeoutError"
            ))
        except Exception as e:
            pass
        finally:
            try:
                os.unlink(temp_path)
            except:
                pass
    
    return errors


def check_javascript_errors(code: str) -> List[CodeError]:
    """Check JavaScript code for errors using Node.js"""
    errors = []
    
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
            f.write(code)
            temp_path = f.name
        
        result = subprocess.run(
            ['node', '--check', temp_path],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            stderr = result.stderr
            
            # Parse Node.js error
            for line in stderr.split('\n'):
                if 'SyntaxError:' in line:
                    match = re.search(r'SyntaxError: (.+)', line)
                    if match:
                        # Find line number
                        line_match = re.search(r':(\d+):\d+', stderr)
                        line_num = int(line_match.group(1)) if line_match else 1
                        
                        msg = match.group(1)
                        suggestion = {
                            'Unexpected token': 'Check for missing brackets or operators',
                            'Unexpected end of input': 'Missing closing bracket or parenthesis',
                            'is not defined': 'Variable not declared',
                        }.get(msg[:30], 'Review the syntax')
                        
                        errors.append(CodeError(
                            line=line_num,
                            column=0,
                            message=msg,
                            severity="error",
                            code="SyntaxError",
                            suggestion=suggestion
                        ))
                        break
    except FileNotFoundError:
        # Node.js not available - use pattern matching
        errors.extend(check_js_patterns(code))
    except Exception as e:
        pass
    finally:
        try:
            os.unlink(temp_path)
        except:
            pass
    
    return errors


def check_js_patterns(code: str) -> List[CodeError]:
    """Pattern-based JavaScript error detection (fallback)"""
    errors = []
    lines = code.split('\n')
    
    # Track brackets
    open_parens = 0
    open_braces = 0
    open_brackets = 0
    
    for i, line in enumerate(lines, 1):
        open_parens += line.count('(') - line.count(')')
        open_braces += line.count('{') - line.count('}')
        open_brackets += line.count('[') - line.count(']')
        
        # Check for common issues
        if re.search(r'\.innerHTML\s*=\s*\w+\(', line):
            pass  # Common pattern, might be okay
    
    if open_parens > 0:
        errors.append(CodeError(
            line=len(lines), column=0,
            message=f"Unclosed parenthesis (missing {abs(open_parens)} ')')",
            severity="error",
            code="SyntaxError",
            suggestion="Add missing closing parenthesis"
        ))
    
    if open_braces > 0:
        errors.append(CodeError(
            line=len(lines), column=0,
            message=f"Unclosed brace (missing {abs(open_braces)} '}}')",
            severity="error",
            code="SyntaxError",
            suggestion="Add missing closing brace"
        ))
    
    return errors


def check_html_errors(code: str) -> List[CodeError]:
    """Check HTML for errors"""
    errors = []
    lines = code.split('\n')
    
    # Check for unclosed tags
    tag_stack = []
    void_elements = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                     'link', 'meta', 'param', 'source', 'track', 'wbr'}
    
    for i, line in enumerate(lines, 1):
        for match in re.finditer(r'<(/?)(\w+)[^>]*>', line):
            is_closing, tag_name = match.groups()
            tag_name = tag_name.lower()
            
            if tag_name in void_elements:
                continue
            
            if is_closing:
                if tag_stack and tag_stack[-1][0] == tag_name:
                    tag_stack.pop()
                else:
                    errors.append(CodeError(
                        line=i, column=match.start(),
                        message=f"Unexpected closing tag </{tag_name}>",
                        severity="error",
                        code="HTMLParseError",
                        suggestion=f"Remove this closing tag or check for missing opening tag"
                    ))
            else:
                tag_stack.append((tag_name, i, match.start()))
    
    # Unclosed tags
    for tag_name, line_num, col in tag_stack:
        errors.append(CodeError(
            line=line_num, column=col,
            message=f"Unclosed tag <{tag_name}>",
            severity="error",
            code="HTMLParseError",
            suggestion=f"Add closing tag </{tag_name}>"
        ))
    
    # Check embedded JavaScript
    script_match = re.search(r'<script[^>]*>(.*?)</script>', code, re.DOTALL | re.IGNORECASE)
    if script_match:
        js_code = script_match.group(1)
        js_errors = check_javascript_errors(js_code)
        
        script_start = code[:script_match.start()].count('\n') + 1
        for err in js_errors:
            err.line += script_start
            errors.append(err)
    
    return errors


def check_code(code: str, language: str, run_code: bool = False) -> List[CodeError]:
    """Route to appropriate checker based on language"""
    
    if language == "python":
        return check_python_errors(code, run_code)
    elif language in ("javascript", "typescript"):
        return check_javascript_errors(code)
    elif language == "html":
        return check_html_errors(code)
    else:
        # Generic bracket check
        return check_js_patterns(code)  # Works as generic checker


# ============================================
# AI FIX
# ============================================

FIX_PROMPTS = {
    "python": """Fix this Python code. Return ONLY the corrected code in a ```python block, then briefly explain the fixes.

CODE:
```python
{code}
```

ERRORS:
{errors}""",

    "javascript": """Fix this JavaScript code. Return ONLY the corrected code in a ```javascript block, then briefly explain the fixes.

CODE:
```javascript
{code}
```

ERRORS:
{errors}""",

    "html": """Fix this HTML code. Return ONLY the corrected code in a ```html block, then briefly explain the fixes.

CODE:
```html
{code}
```

ERRORS:
{errors}""",

    "default": """Fix this {language} code. Return ONLY the corrected code in a code block, then briefly explain the fixes.

CODE:
```
{code}
```

ERRORS:
{errors}"""
}


def get_fix_prompt(language: str, code: str, errors: List[CodeError]) -> str:
    """Generate fix prompt for the language"""
    error_text = "\n".join([f"- Line {e.line}: {e.message}" for e in errors])
    
    template = FIX_PROMPTS.get(language, FIX_PROMPTS["default"])
    return template.format(language=language, code=code, errors=error_text)


def extract_code(response: str, language: str) -> str:
    """Extract fixed code from AI response"""
    pattern = rf'```{language}\s*\n(.*?)```'
    match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
    
    if match:
        return match.group(1).strip()
    
    # Try generic block
    match = re.search(r'```\s*\n(.*?)```', response, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    return response.strip()


# ============================================
# API MODELS
# ============================================

class AnalyzeRequest(BaseModel):
    code: str
    filename: Optional[str] = None
    run_code: bool = False


class FixRequest(BaseModel):
    code: str
    errors: List[Dict]
    language: str


# ============================================
# ENDPOINT SETUP
# ============================================

def setup_canvas_endpoints(app, brain_manager):
    """Add canvas endpoints to FastAPI app"""
    
    ID_CODER = "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit"
    CODER_SYS = "You are an expert code fixer. Fix the errors and return only the corrected code."
    
    @app.post("/v1/canvas/analyze")
    async def analyze_code(req: AnalyzeRequest):
        """Analyze code for errors with auto language detection"""
        try:
            # Detect language
            language = detect_language(req.code, req.filename)
            
            # Check for errors
            errors = check_code(req.code, language, req.run_code)
            
            return {
                "success": len([e for e in errors if e.severity == "error"]) == 0,
                "language": language,
                "errors": [e.to_dict() for e in errors if e.severity == "error"],
                "warnings": [e.to_dict() for e in errors if e.severity != "error"],
                "error_count": len([e for e in errors if e.severity == "error"]),
                "warning_count": len([e for e in errors if e.severity != "error"])
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/v1/canvas/detect-language")
    async def detect_lang(req: AnalyzeRequest):
        """Detect programming language"""
        language = detect_language(req.code, req.filename)
        return {"language": language, "filename": req.filename}
    
    @app.post("/v1/canvas/fix")
    async def fix_code(req: FixRequest):
        """Fix code using AI"""
        try:
            # Build prompt
            code_errors = [CodeError(**e) for e in req.errors]
            prompt = get_fix_prompt(req.language, req.code, code_errors)
            
            # Get AI fix
            response = brain_manager.generate_text(
                ID_CODER,
                CODER_SYS,
                prompt,
                max_new_tokens=2048,
                temperature=0.1
            )
            
            # Extract fixed code
            fixed_code = extract_code(response, req.language)
            
            return {
                "success": True,
                "fixed_code": fixed_code,
                "original_code": req.code,
                "language": req.language,
                "raw_response": response
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "fixed_code": req.code,
                "language": req.language
            }
    
    @app.post("/v1/canvas/analyze-and-fix")
    async def analyze_and_fix(req: AnalyzeRequest):
        """Analyze and fix in one call"""
        try:
            # Detect language
            language = detect_language(req.code, req.filename)
            
            # Check errors
            errors = check_code(req.code, language, req.run_code)
            error_dicts = [e.to_dict() for e in errors if e.severity == "error"]
            
            result = {
                "language": language,
                "errors": error_dicts,
                "warnings": [e.to_dict() for e in errors if e.severity != "error"],
                "has_errors": len(error_dicts) > 0
            }
            
            # If errors, try to fix
            if error_dicts:
                code_errors = [CodeError(**e) for e in error_dicts]
                prompt = get_fix_prompt(language, req.code, code_errors)
                
                response = brain_manager.generate_text(
                    ID_CODER,
                    CODER_SYS,
                    prompt,
                    max_new_tokens=2048,
                    temperature=0.1
                )
                
                fixed_code = extract_code(response, language)
                
                result["fixed_code"] = fixed_code
                result["fix_success"] = True
            else:
                result["fixed_code"] = req.code
                result["fix_success"] = None
            
            return result
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    print("[CANVAS] ✅ Canvas endpoints added: /v1/canvas/analyze, /v1/canvas/fix, /v1/canvas/detect-language")


# ============================================
# TESTING
# ============================================

if __name__ == "__main__":
    # Test code samples
    test_python = """
def calculate_score(points):
    if points > 10
        return points * 2
    return points

result = calculate_score(15)
"""
    
    test_js = """
function gameLoop() {
    ctx.fillRect(0, 0, canvas.width, canvas.height
    scoreBoard("Score: " + score)
}
"""
    
    test_html = """
<!DOCTYPE html>
<html>
<head>
    <title>Test
</head>
<body>
    <div id="game">
    <script>
        var x = undefined_var;
    </script>
</body>
</html>
"""
    
    print("=" * 60)
    print("PYTHON TEST:")
    print("=" * 60)
    lang = detect_language(test_python)
    print(f"Detected: {lang}")
    errors = check_code(test_python, lang)
    for e in errors:
        print(f"  Line {e.line}: {e.message}")
        if e.suggestion:
            print(f"    → {e.suggestion}")
    
    print("\n" + "=" * 60)
    print("JAVASCRIPT TEST:")
    print("=" * 60)
    lang = detect_language(test_js)
    print(f"Detected: {lang}")
    errors = check_code(test_js, lang)
    for e in errors:
        print(f"  Line {e.line}: {e.message}")
        if e.suggestion:
            print(f"    → {e.suggestion}")
    
    print("\n" + "=" * 60)
    print("HTML TEST:")
    print("=" * 60)
    lang = detect_language(test_html)
    print(f"Detected: {lang}")
    errors = check_code(test_html, lang)
    for e in errors:
        print(f"  Line {e.line}: {e.message}")
        if e.suggestion:
            print(f"    → {e.suggestion}")
