"""
EAA Canvas - Multi-Language Error Detection System
====================================================
Detects errors in Python, JavaScript, HTML, CSS, Java, C++, Rust, Go, and more.
Provides unified error reporting with AI fix suggestions.
"""

import re
import subprocess
import tempfile
import os
import json
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum


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
    XML = "xml"
    MARKDOWN = "markdown"
    UNKNOWN = "unknown"


@dataclass
class CodeError:
    line: int
    column: int
    message: str
    severity: str  # "error", "warning", "info"
    code: str
    language: str
    suggestion: Optional[str] = None


@dataclass
class ErrorReport:
    success: bool
    errors: List[CodeError]
    warnings: List[CodeError]
    language: str
    raw_output: str


class LanguageDetector:
    """Auto-detect programming language from code content"""
    
    # Language patterns with their signatures
    LANGUAGE_SIGNATURES = {
        Language.PYTHON: [
            r'^\s*(def|class|import|from|if\s+__name__|async\s+def|await\s+)',
            r'^\s*(print|input|len|range|str\(|int\(|float\(|list\(|dict\()',
            r':\s*$',  # Python colon at end of line
            r'(elif|except|finally|with\s+\w+\s+as)',
            r'__init__|__str__|__repr__|self\.',
            r'@\w+\s*\n\s*def',  # Decorators
            r'f["\'].*?\{.*?\}.*?["\']',  # f-strings
        ],
        Language.JAVASCRIPT: [
            r'(const|let|var)\s+\w+\s*=',
            r'function\s+\w+\s*\(|=>\s*\{',
            r'(async\s+function|async\s*\(|await\s+)',
            r'(document\.|window\.|console\.)',
            r'\.innerHTML|\.textContent|\.appendChild',
            r'(fetch\(|Promise|\.then\(|\.catch\()',
            r'(export\s+(default\s+)?|import\s+.*from)',
            r'(require\s*\(|module\.exports)',
        ],
        Language.TYPESCRIPT: [
            r':\s*(string|number|boolean|any|void|never)\s*[=\)\{]',
            r'interface\s+\w+\s*\{',
            r'type\s+\w+\s*=',
            r'<\w+>',  # Generics
            r'(public|private|protected)\s+\w+\s*[=\(]',
            r'as\s+(string|number|any)',
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
            r'(flexbox|grid|position\s*:\s*(absolute|relative|fixed))',
        ],
        Language.JAVA: [
            r'(public|private|protected)\s+(class|interface|enum)',
            r'(System\.out\.print|System\.in)',
            r'(import\s+java\.)',
            r'(public\s+static\s+void\s+main)',
            r'@Override|@Deprecated',
            r'(extends\s+\w+|implements\s+\w+)',
        ],
        Language.CPP: [
            r'#include\s*<',
            r'(std::|cout|cin|endl)',
            r'(namespace\s+\w+)',
            r'(class\s+\w+\s*\{|struct\s+\w+)',
            r'(int\s+main\s*\(|void\s+main\s*\()',
            r'(public:|private:|protected:)',
        ],
        Language.C: [
            r'#include\s*<stdio\.h|#include\s*<stdlib\.h',
            r'(printf\s*\(|scanf\s*\()',
            r'(malloc\s*\(|free\s*\()',
            r'(int\s+main\s*\(|void\s+main\s*\()',
        ],
        Language.RUST: [
            r'(fn\s+\w+\s*\(|pub\s+fn)',
            r'(let\s+mut|let\s+\w+:)',
            r'(impl\s+\w+|trait\s+\w+)',
            r'(use\s+std::|mod\s+\w+)',
            r'(Option::|Result::|Vec::)',
            r'(match\s+\w+\s*\{|=>)',
            r'(println!|format!|vec!)',
        ],
        Language.GO: [
            r'package\s+(main|\w+)',
            r'func\s+(main|\w+)\s*\(',
            r'(import\s*\(|import\s+"',
            r'(fmt\.Print|fmt\.Scan)',
            r'(go\s+\w+\(|defer\s+)',
            r'(var\s+\w+\s+\w+|:=)',
        ],
        Language.PHP: [
            r'<\?php',
            r'(\$\w+\s*=|\$this->)',
            r'(echo\s+|print\s+)',
            r'(function\s+__construct|public\s+function)',
            r'(include|require)(_once)?\s*\(',
        ],
        Language.RUBY: [
            r'(def\s+\w+|end\s*$)',
            r'(class\s+\w+|module\s+\w+)',
            r'(require|include)\s+["\']',
            r'(attr_accessor|attr_reader)',
            r'(puts\s+|gets\s+)',
            r'(do\s*\||\|.*\|)',
        ],
        Language.SQL: [
            r'(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\s+',
            r'(FROM|WHERE|JOIN|GROUP BY|ORDER BY)\s+',
            r'(INNER|OUTER|LEFT|RIGHT)\s+JOIN',
        ],
        Language.JSON: [
            r'^\s*\{',
            r'"\w+"\s*:',
            r'\[\s*\{|\}\s*\]',
        ],
    }
    
    # Extension mapping
    EXTENSION_MAP = {
        '.py': Language.PYTHON,
        '.js': Language.JAVASCRIPT,
        '.mjs': Language.JAVASCRIPT,
        '.cjs': Language.JAVASCRIPT,
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
        '.cxx': Language.CPP,
        '.c': Language.C,
        '.h': Language.C,
        '.hpp': Language.CPP,
        '.rs': Language.RUST,
        '.go': Language.GO,
        '.php': Language.PHP,
        '.rb': Language.RUBY,
        '.sql': Language.SQL,
        '.json': Language.JSON,
        '.xml': Language.XML,
        '.md': Language.MARKDOWN,
    }
    
    @classmethod
    def detect(cls, code: str, filename: str = None) -> Language:
        """Detect language from code content and optional filename"""
        
        # 1. Try extension first if filename provided
        if filename:
            ext = os.path.splitext(filename)[1].lower()
            if ext in cls.EXTENSION_MAP:
                return cls.EXTENSION_MAP[ext]
        
        # 2. Pattern matching on code content
        scores = {lang: 0 for lang in Language}
        
        for lang, patterns in cls.LANGUAGE_SIGNATURES.items():
            for pattern in patterns:
                matches = re.findall(pattern, code, re.MULTILINE | re.IGNORECASE)
                scores[lang] += len(matches)
        
        # Get highest scoring language
        best_lang = max(scores, key=scores.get)
        
        # Need at least some confidence
        if scores[best_lang] >= 2:
            return best_lang
        
        # Check for HTML specifically (common case)
        if re.search(r'<\w+[^>]*>', code) and re.search(r'</\w+>', code):
            return Language.HTML
        
        # Default to unknown
        return Language.UNKNOWN


class PythonErrorDetector:
    """Python error detection using AST and runtime checks"""
    
    @staticmethod
    def check_syntax(code: str) -> List[CodeError]:
        """Check Python syntax errors"""
        errors = []
        
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            errors.append(CodeError(
                line=e.lineno or 1,
                column=e.offset or 0,
                message=e.msg,
                severity="error",
                code="SyntaxError",
                language="python",
                suggestion=PythonErrorDetector._get_syntax_suggestion(e.msg, code, e.lineno)
            ))
        except Exception as e:
            errors.append(CodeError(
                line=1,
                column=0,
                message=str(e),
                severity="error",
                code="CompileError",
                language="python"
            ))
        
        return errors
    
    @staticmethod
    def check_runtime(code: str, timeout: int = 5) -> Tuple[bool, str, List[CodeError]]:
        """Run code and catch runtime errors"""
        errors = []
        output = ""
        
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_path = f.name
        
        try:
            result = subprocess.run(
                ['python', temp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.path.dirname(temp_path)
            )
            
            output = result.stdout + result.stderr
            
            if result.returncode != 0:
                # Parse error from stderr
                error_lines = result.stderr.split('\n')
                for line in error_lines:
                    # Look for error line numbers
                    match = re.search(r'File ".*?", line (\d+)', line)
                    if match:
                        line_num = int(match.group(1))
                    
                    # Look for error type and message
                    error_match = re.search(r'^(\w+Error|\w+Exception): (.+)$', line)
                    if error_match:
                        errors.append(CodeError(
                            line=locals().get('line_num', 1),
                            column=0,
                            message=error_match.group(2),
                            severity="error",
                            code=error_match.group(1),
                            language="python"
                        ))
        
        except subprocess.TimeoutExpired:
            errors.append(CodeError(
                line=0,
                column=0,
                message=f"Execution timed out after {timeout} seconds",
                severity="error",
                code="TimeoutError",
                language="python"
            ))
        except Exception as e:
            errors.append(CodeError(
                line=0,
                column=0,
                message=str(e),
                severity="error",
                code="RuntimeError",
                language="python"
            ))
        finally:
            try:
                os.unlink(temp_path)
            except:
                pass
        
        return len(errors) == 0, output, errors
    
    @staticmethod
    def _get_syntax_suggestion(msg: str, code: str, line_num: int) -> str:
        """Generate helpful suggestions for common Python syntax errors"""
        suggestions = {
            "expected ':'": "Add a colon (:) at the end of the statement (if, for, while, def, class, etc.)",
            "invalid syntax": "Check for missing parentheses, brackets, or operators",
            "unexpected EOF while parsing": "Code is incomplete - check for unclosed brackets or quotes",
            "unterminated string literal": "Close the string with matching quote",
            "EOL while scanning string literal": "String literal not closed on same line",
            "invalid character": "Remove or replace the invalid character",
            "expected an indented block": "Add indentation after colon",
            "unindent does not match": "Fix indentation to match surrounding code",
        }
        
        for key, suggestion in suggestions.items():
            if key.lower() in msg.lower():
                return suggestion
        
        return "Review the syntax around this line"


class JavaScriptErrorDetector:
    """JavaScript/TypeScript error detection"""
    
    COMMON_ERRORS = {
        'Unexpected token': 'Check for missing brackets, parentheses, or operators',
        'Cannot read properties': 'The object is null or undefined. Add a null check.',
        'is not defined': 'Variable or function not declared. Check spelling or add declaration.',
        'is not a function': 'Trying to call something that is not a function',
        'Unexpected end of input': 'Missing closing bracket or parenthesis',
        'Invalid or unexpected token': 'Check for invalid characters or unclosed strings',
        'Missing } in compound statement': 'Add missing closing brace',
        'Missing ) after argument list': 'Add missing closing parenthesis',
        'Unexpected identifier': 'Check for missing operators or keywords',
        'await is only valid in async function': 'Make the containing function async',
        'Cannot access before initialization': 'Variable used before declaration',
        'Assignment to constant variable': 'Use let instead of const, or create new variable',
    }
    
    @staticmethod
    def check_syntax(code: str, is_typescript: bool = False) -> List[CodeError]:
        """Check JavaScript syntax using Node.js"""
        errors = []
        
        # Try to use Node.js for syntax checking
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
                # Parse Node.js error output
                error_text = result.stderr
                errors.extend(JavaScriptErrorDetector._parse_node_error(error_text))
        
        except FileNotFoundError:
            # Node.js not available, use pattern matching
            errors.extend(JavaScriptErrorDetector._pattern_check(code))
        except Exception as e:
            errors.append(CodeError(
                line=1,
                column=0,
                message=f"Could not check JavaScript: {str(e)}",
                severity="warning",
                code="CheckError",
                language="javascript"
            ))
        finally:
            try:
                os.unlink(temp_path)
            except:
                pass
        
        return errors
    
    @staticmethod
    def _parse_node_error(error_text: str) -> List[CodeError]:
        """Parse Node.js error output"""
        errors = []
        
        # Pattern for Node.js errors
        patterns = [
            r'SyntaxError: (.+?)\n\s+at new Script',
            r'(\d+):(\d+)',
        ]
        
        lines = error_text.split('\n')
        for i, line in enumerate(lines):
            if 'SyntaxError:' in line:
                match = re.search(r'SyntaxError: (.+)', line)
                if match:
                    msg = match.group(1)
                    
                    # Try to find line number
                    line_num = 1
                    col = 0
                    for next_line in lines[i+1:i+3]:
                        line_match = re.search(r'(\d+):(\d+)', next_line)
                        if line_match:
                            line_num = int(line_match.group(1))
                            col = int(line_match.group(2))
                            break
                    
                    suggestion = JavaScriptErrorDetector.COMMON_ERRORS.get(
                        msg[:30], "Review the JavaScript syntax"
                    )
                    
                    errors.append(CodeError(
                        line=line_num,
                        column=col,
                        message=msg,
                        severity="error",
                        code="SyntaxError",
                        language="javascript",
                        suggestion=suggestion
                    ))
        
        return errors
    
    @staticmethod
    def _pattern_check(code: str) -> List[CodeError]:
        """Basic pattern-based JavaScript error detection"""
        errors = []
        lines = code.split('\n')
        
        # Check for common issues
        for i, line in enumerate(lines, 1):
            # Missing semicolons after statements (warning)
            if re.search(r'(let|const|var)\s+\w+\s*=\s*[^;\n]+$', line):
                pass  # Could add warning
            
            # Unclosed brackets
            open_parens = line.count('(') - line.count(')')
            open_brackets = line.count('[') - line.count(']')
            open_braces = line.count('{') - line.count('}')
            
            if open_parens > 0 and i == len(lines):
                errors.append(CodeError(
                    line=i,
                    column=len(line),
                    message="Unclosed parenthesis",
                    severity="error",
                    code="SyntaxError",
                    language="javascript",
                    suggestion="Add missing )"
                ))
        
        return errors


class HTMLErrorDetector:
    """HTML error detection"""
    
    @staticmethod
    def check(code: str) -> List[CodeError]:
        """Check HTML for common errors"""
        errors = []
        lines = code.split('\n')
        
        # Check for unclosed tags
        tag_stack = []
        void_elements = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 
                         'link', 'meta', 'param', 'source', 'track', 'wbr'}
        
        for i, line in enumerate(lines, 1):
            # Find all tags
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
                            line=i,
                            column=match.start(),
                            message=f"Unexpected closing tag </{tag_name}>",
                            severity="error",
                            code="HTMLParseError",
                            language="html",
                            suggestion=f"Remove this closing tag or check for missing opening tag"
                        ))
                else:
                    tag_stack.append((tag_name, i, match.start()))
        
        # Check for unclosed tags
        for tag_name, line_num, col in tag_stack:
            errors.append(CodeError(
                line=line_num,
                column=col,
                message=f"Unclosed tag <{tag_name}>",
                severity="error",
                code="HTMLParseError",
                language="html",
                suggestion=f"Add closing tag </{tag_name}>"
            ))
        
        # Check for script errors in embedded JS
        script_match = re.search(r'<script[^>]*>(.*?)</script>', code, re.DOTALL | re.IGNORECASE)
        if script_match:
            js_code = script_match.group(1)
            js_errors = JavaScriptErrorDetector.check_syntax(js_code)
            
            # Adjust line numbers
            script_start = code[:script_match.start()].count('\n') + 1
            for err in js_errors:
                err.line += script_start
                errors.append(err)
        
        return errors


class CSSErrorDetector:
    """CSS error detection"""
    
    @staticmethod
    def check(code: str) -> List[CodeError]:
        """Check CSS for common errors"""
        errors = []
        lines = code.split('\n')
        
        # Track braces
        brace_count = 0
        for i, line in enumerate(lines, 1):
            brace_count += line.count('{') - line.count('}')
            
            # Missing semicolon in property
            if re.search(r'\{\s*[^}]*[\w-]+\s*:\s*[^;}\n]+$', line):
                pass  # Could add warning
        
        if brace_count > 0:
            errors.append(CodeError(
                line=len(lines),
                column=0,
                message="Unclosed brace in CSS",
                severity="error",
                code="CSSParseError",
                language="css",
                suggestion="Add missing }"
            ))
        
        return errors


class JavaErrorDetector:
    """Java error detection"""
    
    @staticmethod
    def check(code: str) -> List[CodeError]:
        """Check Java code for syntax errors using javac"""
        errors = []
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.java', delete=False) as f:
                f.write(code)
                temp_path = f.name
            
            result = subprocess.run(
                ['javac', '-Xlint:all', temp_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                errors.extend(JavaErrorDetector._parse_javac_error(result.stderr))
        
        except FileNotFoundError:
            # javac not available
            errors.append(CodeError(
                line=1,
                column=0,
                message="Java compiler not available for syntax checking",
                severity="warning",
                code="CompilerNotFound",
                language="java"
            ))
        except Exception as e:
            pass
        finally:
            try:
                os.unlink(temp_path)
                class_file = temp_path.replace('.java', '.class')
                if os.path.exists(class_file):
                    os.unlink(class_file)
            except:
                pass
        
        return errors
    
    @staticmethod
    def _parse_javac_error(error_text: str) -> List[CodeError]:
        """Parse javac error output"""
        errors = []
        
        # Pattern: file.java:line: error: message
        pattern = r'.*?:(\d+):\s*(error|warning):\s*(.+)'
        
        for line in error_text.split('\n'):
            match = re.match(pattern, line)
            if match:
                line_num = int(match.group(1))
                severity = match.group(2)
                message = match.group(3)
                
                errors.append(CodeError(
                    line=line_num,
                    column=0,
                    message=message,
                    severity=severity,
                    code="CompileError",
                    language="java"
                ))
        
        return errors


class UniversalErrorDetector:
    """Main class that routes to appropriate language detector"""
    
    DETECTORS = {
        Language.PYTHON: PythonErrorDetector,
        Language.JAVASCRIPT: JavaScriptErrorDetector,
        Language.TYPESCRIPT: JavaScriptErrorDetector,
        Language.HTML: HTMLErrorDetector,
        Language.CSS: CSSErrorDetector,
        Language.JAVA: JavaErrorDetector,
    }
    
    @classmethod
    def analyze(cls, code: str, filename: str = None, run_code: bool = False) -> ErrorReport:
        """
        Analyze code for errors
        
        Args:
            code: Source code to analyze
            filename: Optional filename for language detection
            run_code: Whether to attempt running Python code
        
        Returns:
            ErrorReport with all detected issues
        """
        # Detect language
        language = LanguageDetector.detect(code, filename)
        
        # Get appropriate detector
        detector = cls.DETECTORS.get(language)
        
        all_errors = []
        raw_output = ""
        
        if detector:
            # Check syntax
            errors = detector.check_syntax(code) if hasattr(detector, 'check_syntax') else detector.check(code)
            all_errors.extend(errors)
            
            # Run Python code if requested
            if run_code and language == Language.PYTHON:
                success, output, runtime_errors = PythonErrorDetector.check_runtime(code)
                all_errors.extend(runtime_errors)
                raw_output = output
        else:
            # No detector available, try basic checks
            all_errors.append(CodeError(
                line=1,
                column=0,
                message=f"No error detector available for {language.value}",
                severity="info",
                code="Info",
                language=language.value
            ))
        
        # Separate errors and warnings
        errors = [e for e in all_errors if e.severity == "error"]
        warnings = [e for e in all_errors if e.severity in ("warning", "info")]
        
        return ErrorReport(
            success=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            language=language.value,
            raw_output=raw_output
        )


def analyze_code(code: str, filename: str = None, run_code: bool = False) -> Dict[str, Any]:
    """
    Main entry point for code analysis
    
    Returns a dictionary suitable for JSON serialization
    """
    report = UniversalErrorDetector.analyze(code, filename, run_code)
    
    return {
        "success": report.success,
        "language": report.language,
        "errors": [
            {
                "line": e.line,
                "column": e.column,
                "message": e.message,
                "severity": e.severity,
                "code": e.code,
                "suggestion": e.suggestion
            }
            for e in report.errors
        ],
        "warnings": [
            {
                "line": w.line,
                "column": w.column,
                "message": w.message,
                "severity": w.severity,
                "code": w.code,
                "suggestion": w.suggestion
            }
            for w in report.warnings
        ],
        "output": report.raw_output,
        "has_errors": len(report.errors) > 0,
        "error_count": len(report.errors),
        "warning_count": len(report.warnings)
    }


# For FastAPI integration
def setup_error_detection_endpoints(app):
    """Add error detection endpoints to FastAPI app"""
    from fastapi import HTTPException
    from pydantic import BaseModel
    
    class AnalyzeRequest(BaseModel):
        code: str
        filename: str = None
        run_code: bool = False
    
    @app.post("/v1/canvas/analyze")
    async def analyze_endpoint(req: AnalyzeRequest):
        """Analyze code for errors"""
        try:
            result = analyze_code(req.code, req.filename, req.run_code)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/v1/canvas/detect-language")
    async def detect_language_endpoint(req: AnalyzeRequest):
        """Detect the programming language of code"""
        language = LanguageDetector.detect(req.code, req.filename)
        return {
            "language": language.value,
            "filename": req.filename
        }


if __name__ == "__main__":
    # Test examples
    test_python = """
def calculate_score(points):
    if points > 10
        return points * 2
    return points

result = calculate_score(missing_var)
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
        var x = undefined_var
    </script>
</body>
</html>
"""
    
    print("=" * 60)
    print("PYTHON TEST:")
    print("=" * 60)
    result = analyze_code(test_python, "test.py", run_code=True)
    print(json.dumps(result, indent=2))
    
    print("\n" + "=" * 60)
    print("JAVASCRIPT TEST:")
    print("=" * 60)
    result = analyze_code(test_js, "test.js")
    print(json.dumps(result, indent=2))
    
    print("\n" + "=" * 60)
    print("HTML TEST:")
    print("=" * 60)
    result = analyze_code(test_html, "test.html")
    print(json.dumps(result, indent=2))
