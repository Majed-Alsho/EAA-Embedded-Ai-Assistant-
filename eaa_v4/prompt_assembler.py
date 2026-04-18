"""
prompt_assembler.py — Multi-Layer Prompt Assembly Pipeline (Phase 4)

Assembles the complete system prompt from 6 distinct layers, each with
different content sources and caching strategies. This mirrors Claude Code's
prompt assembly pipeline from Section 10.1.

Layers:
    0: Attribution Header — Identifies the agent (never cached)
    1: Static Sections — 7 global instruction sections (globally cached)
    2: Boundary Marker — Separates cacheable from dynamic content
    3: Dynamic Sections — Session-specific context (session-scoped)
    4: Context Injections — Git status, memory files, current date (session-scoped)
    5: Agent/Custom Prompts — Priority-based override selection (session-scoped)

Reference: Blueprint Section 10.1 — Prompt Assembly Pipeline
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from prompt_cache import (
    CacheScope,
    PromptBlock,
    PromptCacheStore,
    split_prompt_blocks,
    create_cache_key,
    CACHE_BOUNDARY_MARKER,
)
from tool_instructions import ToolInstructionRegistry
from memory_loader import MemoryLoadResult, load_all_memory


# The 8 key behavioral instructions from Claude Code
DEFAULT_BEHAVIORAL_INSTRUCTIONS = [
    "Consider instructions in the context of software engineering tasks rather than answering generically.",
    "Allow ambitious tasks and defer to user judgment on scope.",
    "Never propose changes to code that hasn't been read first.",
    "Minimize file creation by preferring edits to existing files.",
    "Avoid giving time estimates.",
    "When approaches fail, investigate the root cause before switching tactics.",
    "Be careful not to introduce security vulnerabilities (OWASP top 10).",
    "Practice code minimalism: no extra features, comments, abstractions, or error handling beyond what was asked.",
]


@dataclass
class PromptConfig:
    """Configuration for prompt assembly."""
    agent_name: str = "EAA"
    agent_version: str = "4.0"
    model_name: str = "Qwen2.5-7B-Instruct"
    project_root: str = "."
    working_dir: str = "."
    session_id: str = ""
    language: str = "en"
    # Layer 5: Priority levels for custom prompts
    # (higher value = higher priority)
    override_prompt: str = ""
    coordinator_prompt: str = ""
    agent_prompt: str = ""
    custom_prompt: str = ""
    default_prompt: str = ""
    append_prompt: str = ""


@dataclass
class AssembledPrompt:
    """Result of prompt assembly."""
    full_prompt: str = ""
    layers: Dict[str, str] = field(default_factory=dict)
    total_chars: int = 0
    token_estimate: int = 0
    cache_blocks: List[PromptBlock] = field(default_factory=list)

    def __post_init__(self):
        self.total_chars = len(self.full_prompt)
        self.token_estimate = self.total_chars // 4


class PromptAssembler:
    """
    Multi-layer system prompt assembler.

    Assembles the system prompt from 6 layers following Claude Code's
    architecture, with support for caching and dynamic content injection.
    """

    def __init__(
        self,
        config: PromptConfig,
        tool_registry: Optional[ToolInstructionRegistry] = None,
        cache_store: Optional[PromptCacheStore] = None,
    ):
        self.config = config
        self.tool_registry = tool_registry or ToolInstructionRegistry()
        self.cache_store = cache_store or PromptCacheStore()

        # Section registry for Layer 3 dynamic sections
        self._dynamic_sections: Dict[str, Callable[[], str]] = {}
        self._section_cache: Dict[str, str] = {}

    def register_dynamic_section(self, name: str, factory: Callable[[], str]) -> None:
        """
        Register a dynamic section factory for Layer 3.

        The factory is called each time the prompt is assembled to get
        fresh content. Use for session-specific data like git status,
        environment info, etc.
        """
        self._dynamic_sections[name] = factory

    def _build_layer0_attribution(self) -> str:
        """Layer 0: Attribution header (never cached)."""
        return (
            f"<agent_info>\n"
            f"name={self.config.agent_name}\n"
            f"version={self.config.agent_version}\n"
            f"model={self.config.model_name}\n"
            f"</agent_info>\n"
        )

    def _build_layer1_static(self) -> str:
        """Layer 1: Static system prompt sections (globally cached).

        Contains the 7 core instruction sections from Claude Code:
        Intro, System, Doing Tasks, Actions, Using Your Tools,
        Tone & Style, Output Efficiency.
        """
        sections = []

        # Section 1: Intro
        sections.append(
            "## Introduction\n"
            "You are an AI coding assistant that helps users with software engineering tasks. "
            "You have access to a set of tools that let you read, edit, and create files, "
            "execute shell commands, search code, and more. Use these tools to accomplish "
            "the user's requests effectively and safely.\n"
        )

        # Section 2: System
        sections.append(
            "## System Behavior\n"
            + "\n".join(f"- {instr}" for instr in DEFAULT_BEHAVIORAL_INSTRUCTIONS)
            + "\n"
        )

        # Section 3: Doing Tasks
        sections.append(
            "## Doing Tasks\n"
            "- Analyze the task before starting. Understand what's being asked.\n"
            "- Plan your approach. For complex tasks, use TodoWrite to track progress.\n"
            "- Execute step by step. Verify each step before proceeding.\n"
            "- Use parallel tool calls when operations are independent.\n"
            "- Read files before editing them. Never edit a file you haven't read.\n"
            "- When a tool call fails, analyze the error and try to fix it.\n"
            "- Write down important information (URLs, paths, error messages) since "
            "context may be compressed later.\n"
        )

        # Section 4: Actions
        sections.append(
            "## Actions\n"
            "- Prefer Edit over Write when modifying existing files.\n"
            "- Prefer dedicated tools over Bash for file operations.\n"
            "- Use TodoWrite to plan and track multi-step tasks.\n"
            "- Always provide the full corrected code when fixing errors.\n"
            "- Check your work after making changes (run tests, verify output).\n"
        )

        # Section 5: Using Your Tools
        sections.append(
            "## Using Your Tools\n"
            "Each tool has a specific purpose. Use the right tool for the job:\n"
            "- Read: View file contents\n"
            "- Edit: Modify specific parts of files\n"
            "- Write: Create new files or completely overwrite existing ones\n"
            "- Glob: Find files by pattern\n"
            "- Grep: Search file contents\n"
            "- Bash: Execute shell commands (last resort)\n"
        )

        # Section 6: Tone & Style
        sections.append(
            "## Tone & Style\n"
            "- Be concise and direct. Avoid unnecessary elaboration.\n"
            "- Use the same language as the user's request.\n"
            "- Focus on the technical task, not on pleasantries.\n"
            "- When presenting code, ensure it's complete and runnable.\n"
            "- Admit uncertainty when unsure rather than guessing.\n"
        )

        # Section 7: Output Efficiency
        sections.append(
            "## Output Efficiency\n"
            "- Minimize the amount of text you output.\n"
            "- Do not repeat information already provided in the conversation.\n"
            "- Use code blocks for code, not inline code for large snippets.\n"
            "- When listing items, be concise.\n"
            "- Do not output file contents unless explicitly asked.\n"
        )

        return "\n".join(sections)

    def _build_layer3_dynamic(self) -> str:
        """Layer 3: Dynamic sections (session-scoped)."""
        parts = []

        # Built-in dynamic: session guidance
        parts.append(f"<session_id>{self.config.session_id}</session_id>\n")

        # Built-in dynamic: environment info
        parts.append(
            f"<environment>\n"
            f"working_dir={os.path.abspath(self.config.working_dir)}\n"
            f"platform={os.name}\n"
            f"</environment>\n"
        )

        # Built-in dynamic: language preference
        if self.config.language != "en":
            parts.append(f"<language_preference>{self.config.language}</language_preference>\n")

        # Registered dynamic sections
        for name, factory in self._dynamic_sections.items():
            try:
                content = factory()
                if content and content.strip():
                    parts.append(f"<dynamic_section name=\"{name}\">\n{content}\n</dynamic_section>\n")
            except Exception:
                pass  # Don't let a broken section crash assembly

        return "\n".join(parts)

    def _build_layer4_context(self, memory_result: MemoryLoadResult) -> str:
        """Layer 4: Context injections (git status, memory files, date)."""
        parts = []

        # Current date
        parts.append(
            f"<current_date>{datetime.now().strftime('%Y-%m-%d')}</current_date>\n"
        )

        # Memory files (from memory_loader)
        if memory_result.combined_content:
            parts.append(
                f"<system-reminder>\n"
                f"The following instructions from project memory files take priority "
                f"over default behavior. Follow them carefully.\n\n"
                f"{memory_result.combined_content}\n"
                f"</system-reminder>\n"
            )

        return "\n".join(parts)

    def _build_layer5_custom(self) -> str:
        """Layer 5: Agent/Custom prompts with priority-based selection.

        Priority order (highest first):
        override > coordinator > agent > custom > default > append
        """
        prompts = [
            ("override", self.config.override_prompt),
            ("coordinator", self.config.coordinator_prompt),
            ("agent", self.config.agent_prompt),
            ("custom", self.config.custom_prompt),
            ("default", self.config.default_prompt),
        ]

        selected = ""
        for name, content in prompts:
            if content and content.strip():
                selected = content
                break

        parts = []
        if selected:
            parts.append(f"<custom_instructions>\n{selected}\n</custom_instructions>\n")

        # Append always gets added (lowest priority, additive)
        if self.config.append_prompt and self.config.append_prompt.strip():
            parts.append(f"<append_instructions>\n{self.config.append_prompt}\n</append_instructions>\n")

        return "\n".join(parts)

    def assemble(
        self,
        memory_result: Optional[MemoryLoadResult] = None,
        tool_names: Optional[List[str]] = None,
    ) -> AssembledPrompt:
        """
        Assemble the complete system prompt from all 6 layers.

        Args:
            memory_result: Pre-loaded memory files (or will be loaded).
            tool_names: Specific tools to include instructions for.

        Returns:
            AssembledPrompt with the full prompt and metadata.
        """
        layers: Dict[str, str] = {}

        # Load memory if not provided
        if memory_result is None:
            memory_result = load_all_memory(self.config.project_root)

        # Layer 0: Attribution
        layer0 = self._build_layer0_attribution()
        layers["layer0_attribution"] = layer0

        # Layer 1: Static instructions
        layer1 = self._build_layer1_static()
        layers["layer1_static"] = layer1

        # Tool instructions section (part of static content)
        tool_section = self.tool_registry.generate_tool_section(tool_names)
        preference_section = self.tool_registry.generate_preference_section()
        layer1_with_tools = layer1
        if tool_section:
            layer1_with_tools += "\n" + tool_section
        if preference_section:
            layer1_with_tools += "\n" + preference_section
        layers["layer1_static_with_tools"] = layer1_with_tools

        # Layer 3: Dynamic sections
        layer3 = self._build_layer3_dynamic()
        layers["layer3_dynamic"] = layer3

        # Layer 4: Context injections
        layer4 = self._build_layer4_context(memory_result)
        layers["layer4_context"] = layer4

        # Layer 5: Custom prompts
        layer5 = self._build_layer5_custom()
        layers["layer5_custom"] = layer5

        # Combine with boundary marker (Layer 2)
        # Everything before the boundary is cacheable
        cacheable_content = layer1_with_tools
        dynamic_content = layer3 + layer4 + layer5

        full_prompt = (
            f"{layer0}\n"
            f"{cacheable_content}\n"
            f"{CACHE_BOUNDARY_MARKER}\n"
            f"{dynamic_content}\n"
        ).strip()

        # Split into cache blocks
        cache_result = split_prompt_blocks(
            full_prompt,
            attribution_header=layer0,
        )

        return AssembledPrompt(
            full_prompt=full_prompt,
            layers=layers,
            cache_blocks=cache_result.blocks,
        )
