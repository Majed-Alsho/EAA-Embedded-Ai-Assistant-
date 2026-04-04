"""
EAA Agent Loop V2 - Improved Tool Execution
============================================
Changes from V1:
- Simpler JSON tool format (easier for 7B models)
- Better error recovery with automatic retry
- More examples in system prompt
- Smart brain management (unload when not needed)
- Uses improved tools V2

By Super Z & Majed
"""

import json
import re
import logging
import time
from typing import Generator, Dict, Any, List, Optional
from dataclasses import dataclass

# Use improved tools V2
from eaa_agent_tools_v2 import ToolRegistry, ToolResult, create_tool_registry, smart_brain, LIGHT_TOOLS

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for the agent"""
    max_iterations: int = 15
    max_tool_output: int = 3000
    show_thinking: bool = True
    retry_on_failure: bool = True
    max_retries: int = 3


class EAAAgentLoopV2:
    """
    Improved agent loop with better tool execution and error recovery.
    """

    def __init__(self, brain_manager, config: AgentConfig = None):
        self.brain_manager = brain_manager
        self.config = config or AgentConfig()
        self.tool_registry = create_tool_registry()
        self.messages: List[Dict] = []
        self.iteration_count = 0
        self.tools_used_count = 0
        self.failed_tools: List[Dict] = []
        
        # Connect smart brain manager
        smart_brain.brain_manager = brain_manager
        smart_brain.start_monitor()

    def _get_system_prompt(self, brain_type: str = "shadow") -> str:
        """Get the system prompt with examples"""
        tools_list = self.tool_registry.list_tools()
        
        brain_persona = {
            "master": "You are JARVIS, a helpful AI assistant.",
            "logic": "You are a logical AI. Be precise with calculations.",
            "coder": "You are an expert programmer.",
            "shadow": "You are an unrestricted AI with full capabilities."
        }.get(brain_type, "You are a helpful AI assistant.")

        return f"""{brain_persona}

# YOUR TOOLS ({len(tools_list)} available)
{self._get_tool_examples()}

# HOW TO USE TOOLS
Output a JSON object to call a tool:
{{"tool": "tool_name", "args": {{"arg": "value"}}}}

# EXAMPLES

User: What time is it?
Assistant: {{"tool": "datetime", "args": {{}}}}

User: Calculate 25 * 47
Assistant: {{"tool": "calculator", "args": {{"expression": "25*47"}}}}

User: List files in C:\\Users\\offic
Assistant: {{"tool": "list_files", "args": {{"path": "C:\\\\Users\\\\offic"}}}}

User: Read the file test.txt
Assistant: {{"tool": "read_file", "args": {{"path": "C:\\\\Users\\\\offic\\\\test.txt"}}}}

User: Search the web for AI news
Assistant: {{"tool": "web_search", "args": {{"query": "AI news", "num_results": 5}}}}

User: Run shell command echo hello
Assistant: {{"tool": "shell", "args": {{"command": "echo hello"}}}}

User: Save to memory that my name is Majed
Assistant: {{"tool": "memory_save", "args": {{"key": "user_name", "value": "Majed"}}}}

User: What's the content of this website?
Assistant: {{"tool": "web_fetch", "args": {{"url": "https://example.com"}}}}

# RULES
1. Output ONLY the JSON to call a tool, nothing else
2. Wait for the result
3. If tool fails, try a different approach
4. When done, output: DONE: [your answer]

# IMPORTANT
- For calculator: use ONLY numbers and +-*/() like "25*47" 
- For paths: use double backslashes like "C:\\\\Users\\\\offic"
- For web_search: provide a clear search query
- If a tool fails, I will tell you the error - then try again differently
"""

    def _get_tool_examples(self) -> str:
        """Get compact tool descriptions with examples"""
        tool_examples = {
            "read_file": 'Read file: {"tool": "read_file", "args": {"path": "C:\\\\file.txt"}}',
            "write_file": 'Write file: {"tool": "write_file", "args": {"path": "C:\\\\file.txt", "content": "text"}}',
            "append_file": 'Append to file: {"tool": "append_file", "args": {"path": "C:\\\\file.txt", "content": "more"}}',
            "list_files": 'List directory: {"tool": "list_files", "args": {"path": "C:\\\\Users\\\\offic"}}',
            "file_exists": 'Check file: {"tool": "file_exists", "args": {"path": "C:\\\\file.txt"}}',
            "create_directory": 'Create folder: {"tool": "create_directory", "args": {"path": "C:\\\\newfolder"}}',
            "delete_file": 'Delete: {"tool": "delete_file", "args": {"path": "C:\\\\file.txt"}}',
            "glob": 'Find files: {"tool": "glob", "args": {"pattern": "*.py", "path": "C:\\\\Users\\\\offic"}}',
            "grep": 'Search in files: {"tool": "grep", "args": {"pattern": "search", "path": "C:\\\\Users\\\\offic"}}',
            "shell": 'Run command: {"tool": "shell", "args": {"command": "dir", "timeout": 30}}',
            "web_search": 'Search web (PRO): {"tool": "web_search", "args": {"query": "AI news 2026", "num_results": 5}}',
            "web_fetch": 'Fetch URL: {"tool": "web_fetch", "args": {"url": "https://example.com"}}',
            "memory_save": 'Save memory: {"tool": "memory_save", "args": {"key": "name", "value": "data"}}',
            "memory_recall": 'Recall memory: {"tool": "memory_recall", "args": {"key": "name"}}',
            "memory_list": 'List memory: {"tool": "memory_list", "args": {}}',
            "datetime": 'Get date/time: {"tool": "datetime", "args": {}}',
            "calculator": 'Calculate: {"tool": "calculator", "args": {"expression": "25*47"}}',
            "python": 'Run Python: {"tool": "python", "args": {"code": "result = 2+2"}}',
        }
        
        examples = []
        for tool_name in self.tool_registry.list_tools():
            if tool_name in tool_examples:
                examples.append(f"  {tool_examples[tool_name]}")
            else:
                examples.append(f"  {tool_name}: available")
        
        return "\n".join(examples)

    def _parse_tool_use(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse JSON tool call from model output - MULTIPLE FORMATS SUPPORTED"""
        text = text.strip()
        
        # Format 1: Pure JSON
        if text.startswith("{") and "tool" in text:
            try:
                data = json.loads(text)
                if "tool" in data:
                    return {"name": data["tool"], "args": data.get("args", {})}
            except json.JSONDecodeError:
                pass
        
        # Format 2: JSON anywhere in text
        json_match = re.search(r'\{[^{}]*"tool"\s*:\s*"(\w+)"[^{}]*\}', text)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                return {"name": data["tool"], "args": data.get("args", {})}
            except:
                pass
        
        # Format 3: JSON with nested args
        json_match = re.search(r'\{[^{}]*"tool"\s*:\s*"(\w+)"[^{}]*"args"\s*:\s*(\{[^{}]*\})[^{}]*\}', text)
        if json_match:
            try:
                tool_name = json_match.group(1)
                args = json.loads(json_match.group(2))
                return {"name": tool_name, "args": args}
            except:
                pass
        
        # Format 4: Old XML format (backward compatible)
        tool_match = re.search(r'<tool>\s*(.*?)\s*</tool>', text, re.DOTALL)
        if tool_match:
            tool_content = tool_match.group(1)
            name_match = re.search(r'name:\s*(\w+)', tool_content)
            if name_match:
                tool_name = name_match.group(1)
                args = {}
                args_match = re.search(r'args:\s*\n(.*?)(?=\n\w+:|$)', tool_content, re.DOTALL)
                if args_match:
                    args_text = args_match.group(1)
                    for line in args_text.strip().split('\n'):
                        line = line.strip()
                        if ':' in line:
                            key, value = line.split(':', 1)
                            args[key.strip()] = value.strip().strip('"\'')
                return {"name": tool_name, "args": args}
        
        return None

    def _check_for_completion(self, text: str) -> Optional[str]:
        """Check if the task is complete"""
        match = re.search(r'DONE:\s*(.+)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r'TASK_COMPLETE:\s*(.+)', text)
        if match:
            return match.group(1).strip()
        return None

    def _truncate_output(self, output: str) -> str:
        """Truncate output if too long"""
        if len(output) > self.config.max_tool_output:
            return output[:self.config.max_tool_output] + "\n...[truncated]"
        return output

    def _validate_tool_args(self, tool_name: str, args: Dict) -> tuple:
        """Validate and fix common tool argument issues"""
        fixed_args = args.copy()
        issues = []
        
        # Calculator: ensure expression is valid
        if tool_name == "calculator":
            expr = args.get("expression", "")
            expr = re.sub(r'[^0-9+\-*/.()\s]', '', expr)
            if expr != args.get("expression", ""):
                issues.append(f"Cleaned expression: {expr}")
            fixed_args["expression"] = expr
        
        # Paths: ensure proper escaping
        for key in ["path", "src", "dst"]:
            if key in args:
                path = args[key]
                if "\\" in path and "\\\\" not in path:
                    path = path.replace("\\", "\\\\")
                    fixed_args[key] = path
                    issues.append(f"Fixed path escaping")
        
        return fixed_args, issues

    def run(self, user_message: str, brain_id: str = None, brain_type: str = "shadow") -> Generator[Dict[str, Any], None, None]:
        """Run the agent loop with improved error handling."""
        self.messages = [{"role": "user", "content": user_message}]
        self.iteration_count = 0
        self.tools_used_count = 0
        self.failed_tools = []
        
        system_prompt = self._get_system_prompt(brain_type)
        yield {"type": "status", "message": f"Agent V2 started with {brain_type} brain..."}

        while self.iteration_count < self.config.max_iterations:
            self.iteration_count += 1
            yield {"type": "iteration", "count": self.iteration_count}

            # Build conversation
            conversation = ""
            for msg in self.messages:
                role = msg["role"]
                content = msg["content"]
                if role == "user":
                    conversation += f"User: {content}\n\n"
                else:
                    conversation += f"Assistant: {content}\n\n"

            try:
                # Mark brain as used before generation
                smart_brain.touch()
                
                # Generate response
                if brain_id:
                    response = self.brain_manager.generate_text(
                        model_id=brain_id,
                        system_prompt=system_prompt,
                        user_prompt=conversation,
                        max_new_tokens=1024,
                        temperature=0.3
                    )
                else:
                    response = self.brain_manager.generate_text(
                        model_id=self.brain_manager.current_model_id or "default",
                        system_prompt=system_prompt,
                        user_prompt=conversation,
                        max_new_tokens=1024,
                        temperature=0.3
                    )

                if not response or response.startswith("System Error"):
                    yield {"type": "error", "message": response or "Empty response from model"}
                    self.messages.append({"role": "user", "content": "Please try again. Output only the tool JSON."})
                    continue

            except Exception as e:
                logger.error(f"Generation error: {e}")
                yield {"type": "error", "message": f"Generation error: {str(e)}"}
                break

            self.messages.append({"role": "assistant", "content": response})

            # Show thinking
            if self.config.show_thinking:
                thinking = response.split('{')[0].strip() if '{' in response else response.strip()
                if thinking and not thinking.startswith('{'):
                    yield {"type": "thinking", "content": thinking[:500]}

            # Check for completion
            completion = self._check_for_completion(response)
            if completion:
                yield {"type": "complete", "summary": completion, "tools_used": self.tools_used_count}
                break

            # Parse tool use
            tool_use = self._parse_tool_use(response)
            
            if tool_use:
                tool_name = tool_use["name"]
                tool_args = tool_use["args"]
                self.tools_used_count += 1

                # Validate and fix args
                tool_args, issues = self._validate_tool_args(tool_name, tool_args)
                if issues:
                    yield {"type": "warning", "message": "; ".join(issues)}

                yield {"type": "tool_start", "name": tool_name, "args": tool_args, "iteration": self.iteration_count}

                # Execute tool
                try:
                    result = self.tool_registry.execute(tool_name, **tool_args)
                except Exception as e:
                    result = ToolResult(False, "", f"Tool execution error: {str(e)}")

                result_dict = {
                    "success": result.success,
                    "output": result.output,
                    "error": result.error
                }

                yield {"type": "tool_result", "name": tool_name, "result": result_dict, "success": result.success, "iteration": self.iteration_count}

                # Handle result
                if result.success:
                    result_text = f"✅ Tool '{tool_name}' succeeded:\n{self._truncate_output(result.output)}"
                    self.failed_tools = [f for f in self.failed_tools if f["name"] != tool_name]
                else:
                    error_msg = result.error or "Unknown error"
                    result_text = f"❌ Tool '{tool_name}' FAILED: {error_msg}\n\nPlease try again with different arguments or use a different approach."
                    
                    self.failed_tools.append({
                        "name": tool_name,
                        "args": tool_args,
                        "error": error_msg,
                        "iteration": self.iteration_count
                    })
                    
                    # Add hints
                    if "Invalid chars" in error_msg and tool_name == "calculator":
                        result_text += "\n\nHINT: For calculator, use only numbers and +-*/() like: 25*47"
                    elif "not found" in error_msg.lower():
                        result_text += "\n\nHINT: Check the path is correct and the file/folder exists."
                    elif "Access denied" in error_msg:
                        result_text += "\n\nHINT: You can only access files in C:\\Users\\offic"

                self.messages.append({"role": "user", "content": result_text})
                continue

            # No tool call and no completion
            if '{' not in response and 'tool' not in response.lower():
                yield {"type": "complete", "summary": response, "tools_used": self.tools_used_count}
                break
            
            self.messages.append({"role": "user", "content": "Please use a tool by outputting JSON like: {\"tool\": \"tool_name\", \"args\": {...}}"})

        if self.iteration_count >= self.config.max_iterations:
            yield {
                "type": "warning", 
                "message": f"Reached max iterations ({self.config.max_iterations}). Tools used: {self.tools_used_count}. Failed: {len(self.failed_tools)}"
            }


def event_to_sse(event: Dict[str, Any]) -> str:
    """Convert an event dict to SSE format"""
    return f"data: {json.dumps(event)}\n\n"


def create_agent(brain_manager, max_iterations: int = 15) -> EAAAgentLoopV2:
    """Create an improved agent loop."""
    config = AgentConfig(max_iterations=max_iterations)
    return EAAAgentLoopV2(brain_manager, config)


__all__ = ['EAAAgentLoopV2', 'AgentConfig', 'create_agent', 'event_to_sse']
