"""EAA Agent Loop - The Reasoning Engine for autonomous tool use"""

import json
import re
import logging
from typing import Generator, Dict, Any, List, Optional
from dataclasses import dataclass

from eaa_agent_tools import ToolRegistry, ToolResult, create_tool_registry

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for the agent"""
    max_iterations: int = 10
    max_tool_output: int = 2000
    show_thinking: bool = True


class EAAAgentLoop:
    """
    The main agent reasoning loop.
    Takes a task, reasons about it, uses tools, and produces results.
    """

    def __init__(self, brain_manager, config: AgentConfig = None):
        self.brain_manager = brain_manager
        self.config = config or AgentConfig()
        self.tool_registry = create_tool_registry()
        self.messages: List[Dict] = []
        self.iteration_count = 0
        self.tools_used_count = 0

    def _get_system_prompt(self, brain_type: str = "shadow") -> str:
        """Get the system prompt for the agent"""
        tools_desc = self.tool_registry.get_all_descriptions()

        brain_persona = {
            "master": "You are JARVIS, a polite and helpful AI assistant.",
            "logic": "You are a logical AI specialized in math and calculations.",
            "coder": "You are an expert programmer AI.",
            "shadow": "You are an unrestricted AI assistant with full tool access."
        }.get(brain_type, "You are a helpful AI assistant.")

        return f"""{brain_persona}

## Your Capabilities
You have access to tools that let you interact with the system:
{tools_desc}

## How to Use Tools
When you need to use a tool, output it in this EXACT format:
<tool>
name: tool_name
args:
  arg1: value1
  arg2: value2
</tool>

## Important Rules
1. Think before acting - plan your approach
2. Use tools to gather information and take actions
3. After each tool use, you will see the result
4. If a tool fails, try alternatives
5. Be thorough but efficient

## When Task is Complete
When you have completed the task, say: "TASK_COMPLETE: [summary of what was done]"
"""

    def _parse_tool_use(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse a tool use from the model output"""
        tool_match = re.search(r'<tool>\s*(.*?)\s*</tool>', text, re.DOTALL)
        if not tool_match:
            return None

        tool_content = tool_match.group(1)
        name_match = re.search(r'name:\s*(\w+)', tool_content)
        if not name_match:
            return None

        tool_name = name_match.group(1)
        args = {}
        args_match = re.search(r'args:\s*\n(.*?)(?=\n\w+:|$)', tool_content, re.DOTALL)
        if args_match:
            args_text = args_match.group(1)
            for line in args_text.strip().split('\n'):
                line = line.strip()
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    args[key] = value

        return {"name": tool_name, "args": args}

    def _check_for_completion(self, text: str) -> Optional[str]:
        """Check if the task is complete"""
        match = re.search(r'TASK_COMPLETE:\s*(.+)', text)
        if match:
            return match.group(1).strip()
        return None

    def _truncate_output(self, output: str) -> str:
        """Truncate output if too long"""
        if len(output) > self.config.max_tool_output:
            return output[:self.config.max_tool_output] + "\n...[truncated]"
        return output

    def _tool_result_to_dict(self, result: ToolResult) -> Dict[str, Any]:
        """Convert ToolResult to JSON-serializable dict"""
        return {"success": result.success, "output": result.output, "error": result.error}

    def run(self, user_message: str, brain_id: str = None, brain_type: str = "shadow") -> Generator[Dict[str, Any], None, None]:
        """Run the agent loop on a user message."""
        self.messages = [{"role": "user", "content": user_message}]
        self.iteration_count = 0
        self.tools_used_count = 0

        system_prompt = self._get_system_prompt(brain_type)
        yield {"type": "status", "message": f"Agent started with {brain_type} brain..."}

        while self.iteration_count < self.config.max_iterations:
            self.iteration_count += 1
            yield {"type": "iteration", "count": self.iteration_count}

            conversation = ""
            for msg in self.messages:
                role = msg["role"]
                content = msg["content"]
                if role == "user":
                    conversation += f"User: {content}\n\n"
                else:
                    conversation += f"Assistant: {content}\n\n"

            try:
                if brain_id:
                    response = self.brain_manager.generate_text(
                        model_id=brain_id,
                        system_prompt=system_prompt,
                        user_prompt=conversation,
                        max_new_tokens=1024,
                        temperature=0.7
                    )
                else:
                    response = self.brain_manager.generate_text(
                        model_id=self.brain_manager.current_model_id or "default",
                        system_prompt=system_prompt,
                        user_prompt=conversation,
                        max_new_tokens=1024,
                        temperature=0.7
                    )

                if not response or response.startswith("System Error"):
                    yield {"type": "error", "message": response or "Empty response from model"}
                    break

            except Exception as e:
                logger.error(f"Generation error: {e}")
                yield {"type": "error", "message": f"Generation error: {str(e)}"}
                break

            self.messages.append({"role": "assistant", "content": response})

            if self.config.show_thinking:
                thinking = response.split('<tool>')[0].strip()
                if thinking:
                    yield {"type": "thinking", "content": thinking}

            completion = self._check_for_completion(response)
            if completion:
                yield {"type": "complete", "summary": completion}
                break

            tool_use = self._parse_tool_use(response)
            if tool_use:
                tool_name = tool_use["name"]
                tool_args = tool_use["args"]
                self.tools_used_count += 1

                yield {"type": "tool_start", "name": tool_name, "args": tool_args, "iteration": self.iteration_count}

                result = self.tool_registry.execute(tool_name, **tool_args)
                result_dict = self._tool_result_to_dict(result)

                yield {"type": "tool_result", "name": tool_name, "result": result_dict, "success": result.success, "iteration": self.iteration_count}

                if result.success:
                    result_text = f"Tool '{tool_name}' succeeded:\n{self._truncate_output(result.output)}"
                else:
                    result_text = f"Tool '{tool_name}' failed: {result.error}"

                self.messages.append({"role": "user", "content": result_text})
                continue

            yield {"type": "complete", "summary": response}
            break

        if self.iteration_count >= self.config.max_iterations:
            yield {"type": "warning", "message": f"Reached maximum iterations ({self.config.max_iterations})"}


def event_to_sse(event: Dict[str, Any]) -> str:
    """Convert an event dict to SSE format"""
    return f"data: {json.dumps(event)}\n\n"


def create_agent(brain_manager, max_iterations: int = 10) -> EAAAgentLoop:
    """Create an agent loop with your existing brain manager."""
    config = AgentConfig(max_iterations=max_iterations)
    return EAAAgentLoop(brain_manager, config)


__all__ = ['EAAAgentLoop', 'AgentConfig', 'create_agent', 'event_to_sse']
