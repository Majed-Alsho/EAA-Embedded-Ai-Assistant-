"""
EAA Canvas - AI Fix Integration
===============================
Provides AI-powered code fixing for all supported languages.
Integrates with EAA's brain_manager for local LLM fixes.
"""

import re
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class FixResult:
    success: bool
    fixed_code: str
    explanation: str
    changes: List[Dict[str, Any]]
    language: str


# Language-specific fix prompts
FIX_PROMPTS = {
    "python": """You are a Python code fixer. Fix the following Python code.

ORIGINAL CODE:
```python
{code}
```

ERRORS:
{errors}

INSTRUCTIONS:
1. Fix ALL the errors listed above
2. Keep the same logic and functionality
3. Return ONLY the corrected code in a ```python block
4. After the code, briefly explain what was fixed

Do NOT add any new features. Only fix the errors.""",

    "javascript": """You are a JavaScript code fixer. Fix the following JavaScript code.

ORIGINAL CODE:
```javascript
{code}
```

ERRORS:
{errors}

INSTRUCTIONS:
1. Fix ALL the errors listed above
2. Keep the same logic and functionality  
3. Return ONLY the corrected code in a ```javascript block
4. After the code, briefly explain what was fixed

Do NOT add any new features. Only fix the errors.""",

    "typescript": """You are a TypeScript code fixer. Fix the following TypeScript code.

ORIGINAL CODE:
```typescript
{code}
```

ERRORS:
{errors}

INSTRUCTIONS:
1. Fix ALL the errors listed above
2. Keep the same logic and functionality
3. Maintain proper TypeScript types
4. Return ONLY the corrected code in a ```typescript block
5. After the code, briefly explain what was fixed

Do NOT add any new features. Only fix the errors.""",

    "html": """You are an HTML code fixer. Fix the following HTML code.

ORIGINAL CODE:
```html
{code}
```

ERRORS:
{errors}

INSTRUCTIONS:
1. Fix ALL the errors listed above (unclosed tags, invalid attributes, etc.)
2. Keep the same content and structure
3. If there are embedded script errors, fix them too
4. Return ONLY the corrected code in a ```html block
5. After the code, briefly explain what was fixed

Do NOT add any new features. Only fix the errors.""",

    "css": """You are a CSS code fixer. Fix the following CSS code.

ORIGINAL CODE:
```css
{code}
```

ERRORS:
{errors}

INSTRUCTIONS:
1. Fix ALL the errors listed above
2. Keep the same styling intent
3. Return ONLY the corrected code in a ```css block
4. After the code, briefly explain what was fixed

Do NOT add any new features. Only fix the errors.""",

    "java": """You are a Java code fixer. Fix the following Java code.

ORIGINAL CODE:
```java
{code}
```

ERRORS:
{errors}

INSTRUCTIONS:
1. Fix ALL the errors listed above
2. Keep the same logic and functionality
3. Maintain proper Java conventions
4. Return ONLY the corrected code in a ```java block
5. After the code, briefly explain what was fixed

Do NOT add any new features. Only fix the errors.""",

    "default": """You are a code fixer. Fix the following {language} code.

ORIGINAL CODE:
```{language}
{code}
```

ERRORS:
{errors}

INSTRUCTIONS:
1. Fix ALL the errors listed above
2. Keep the same logic and functionality
3. Return ONLY the corrected code in a code block
4. After the code, briefly explain what was fixed

Do NOT add any new features. Only fix the errors."""
}


def get_fix_prompt(language: str, code: str, errors: List[Dict]) -> str:
    """Get the appropriate fix prompt for the language"""
    
    # Format errors as a readable list
    error_text = "\n".join([
        f"- Line {e.get('line', '?')}: {e.get('message', 'Unknown error')}"
        for e in errors
    ])
    
    # Get the prompt template
    prompt_template = FIX_PROMPTS.get(language, FIX_PROMPTS["default"])
    
    # Fill in the template
    return prompt_template.format(
        language=language,
        code=code,
        errors=error_text
    )


def extract_code_from_response(response: str, language: str) -> str:
    """Extract the fixed code from the LLM response"""
    
    # Try to find code block
    # Pattern: ```language\ncode\n```
    pattern = rf'```{language}\s*\n(.*?)```'
    match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
    
    if match:
        return match.group(1).strip()
    
    # Try generic code block
    pattern = r'```\s*\n(.*?)```'
    match = re.search(pattern, response, re.DOTALL)
    
    if match:
        return match.group(1).strip()
    
    # If no code block found, return the whole response
    return response.strip()


def extract_explanation(response: str, language: str) -> str:
    """Extract the explanation from the LLM response"""
    
    # Remove code blocks first
    text = re.sub(r'```.*?```', '', response, flags=re.DOTALL)
    
    # Clean up
    text = text.strip()
    
    # Look for explanation markers
    patterns = [
        r'(?:explanation|what was fixed|changes|summary):?\s*(.+)',
        r'(?:fixed|corrected):?\s*(.+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()[:500]  # Limit length
    
    # Return first non-empty paragraph
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    if paragraphs:
        return paragraphs[0][:500]
    
    return "Code has been fixed."


def find_changes(original: str, fixed: str) -> List[Dict[str, Any]]:
    """Find the differences between original and fixed code"""
    
    changes = []
    orig_lines = original.split('\n')
    fixed_lines = fixed.split('\n')
    
    max_lines = max(len(orig_lines), len(fixed_lines))
    
    for i in range(max_lines):
        orig_line = orig_lines[i] if i < len(orig_lines) else ""
        fixed_line = fixed_lines[i] if i < len(fixed_lines) else ""
        
        if orig_line != fixed_line:
            changes.append({
                "line": i + 1,
                "original": orig_line,
                "fixed": fixed_line,
                "type": "modified" if orig_line and fixed_line else ("added" if not orig_line else "removed")
            })
    
    return changes


def fix_code_with_ai(
    code: str,
    errors: List[Dict],
    language: str,
    brain_manager,
    brain_id: str = None
) -> FixResult:
    """
    Fix code using AI
    
    Args:
        code: The original code with errors
        errors: List of error dictionaries from error detector
        language: Programming language
        brain_manager: EAA's brain_manager module
        brain_id: Optional specific brain to use (defaults to coder brain)
    
    Returns:
        FixResult with fixed code and explanation
    """
    try:
        # Get the fix prompt
        prompt = get_fix_prompt(language, code, errors)
        
        # Use coder brain by default
        if brain_id is None:
            brain_id = "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit"
        
        # System prompt for fixing
        system_prompt = "You are an expert code fixer. Fix the errors and return only the corrected code."
        
        # Generate fix
        response = brain_manager.generate_text(
            brain_id,
            system_prompt,
            prompt,
            max_new_tokens=2048,
            temperature=0.1
        )
        
        # Extract fixed code
        fixed_code = extract_code_from_response(response, language)
        
        # Extract explanation
        explanation = extract_explanation(response, language)
        
        # Find changes
        changes = find_changes(code, fixed_code)
        
        return FixResult(
            success=True,
            fixed_code=fixed_code,
            explanation=explanation,
            changes=changes,
            language=language
        )
        
    except Exception as e:
        return FixResult(
            success=False,
            fixed_code=code,
            explanation=f"AI fix failed: {str(e)}",
            changes=[],
            language=language
        )


def fix_code_remote(
    code: str,
    errors: List[Dict],
    language: str,
    api_url: str,
    api_key: str = None
) -> FixResult:
    """
    Fix code using remote API (for tunnel access)
    
    Args:
        code: The original code with errors
        errors: List of error dictionaries
        language: Programming language
        api_url: Remote API URL
        api_key: Optional API key
    
    Returns:
        FixResult with fixed code and explanation
    """
    import requests
    
    try:
        prompt = get_fix_prompt(language, code, errors)
        
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        response = requests.post(
            f"{api_url}/ai/chat",
            json={
                "message": prompt,
                "brain_type": "coder",
                "max_tokens": 2048
            },
            headers=headers,
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            ai_response = data.get("response", "")
            
            fixed_code = extract_code_from_response(ai_response, language)
            explanation = extract_explanation(ai_response, language)
            changes = find_changes(code, fixed_code)
            
            return FixResult(
                success=True,
                fixed_code=fixed_code,
                explanation=explanation,
                changes=changes,
                language=language
            )
        else:
            return FixResult(
                success=False,
                fixed_code=code,
                explanation=f"API error: {response.status_code}",
                changes=[],
                language=language
            )
            
    except Exception as e:
        return FixResult(
            success=False,
            fixed_code=code,
            explanation=f"Remote fix failed: {str(e)}",
            changes=[],
            language=language
        )


# FastAPI endpoint integration
def setup_fix_endpoints(app, brain_manager):
    """Add AI fix endpoints to FastAPI app"""
    from fastapi import HTTPException
    from pydantic import BaseModel
    from typing import List, Optional
    
    class FixRequest(BaseModel):
        code: str
        errors: List[Dict]
        language: str
    
    class RemoteFixRequest(BaseModel):
        code: str
        errors: List[Dict]
        language: str
        api_url: str
        api_key: Optional[str] = None
    
    @app.post("/v1/canvas/fix")
    async def fix_code_endpoint(req: FixRequest):
        """Fix code using local AI"""
        try:
            result = fix_code_with_ai(
                req.code,
                req.errors,
                req.language,
                brain_manager
            )
            
            return {
                "success": result.success,
                "fixed_code": result.fixed_code,
                "explanation": result.explanation,
                "changes": result.changes,
                "language": result.language
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/v1/canvas/fix-remote")
    async def fix_code_remote_endpoint(req: RemoteFixRequest):
        """Fix code using remote API"""
        try:
            result = fix_code_remote(
                req.code,
                req.errors,
                req.language,
                req.api_url,
                req.api_key
            )
            
            return {
                "success": result.success,
                "fixed_code": result.fixed_code,
                "explanation": result.explanation,
                "changes": result.changes,
                "language": result.language
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    # Test the prompt generation
    test_code = """
def calculate_score(points):
    if points > 10
        return points * 2
    return points
"""
    
    test_errors = [
        {"line": 3, "message": "expected ':'"},
        {"line": 5, "message": "'multiplier' is not defined"}
    ]
    
    prompt = get_fix_prompt("python", test_code, test_errors)
    print("Generated Fix Prompt:")
    print("=" * 60)
    print(prompt)
    print("=" * 60)
