"""
tool_instructions.py — Tool Instruction Registry (Phase 4)

Manages per-tool usage guides and tool preference rules that are
injected into the system prompt.

Claude Code teaches the model how to use each tool through a prompt()
method on the Tool interface. This module replicates that pattern for
EAA, generating usage instructions and enforcing tool preferences.

Tool Preference Rules (from Claude Code):
    - Read  instead of cat/head/tail/sed
    - Edit  instead of sed/awk
    - Write instead of cat heredoc/echo
    - Glob  instead of find/ls
    - Grep  instead of grep/rg
    - Bash  reserved for shell execution only

Reference: Blueprint Section 10.4 — Tool Preference Instructions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ToolInstruction:
    """Usage guide for a single tool."""
    name: str
    description: str
    usage: str  # How to use it correctly
    examples: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    is_read_only: bool = False
    is_destructive: bool = False


@dataclass
class ToolPreference:
    """A preference rule: prefer `preferred` over `inferior`."""
    preferred: str
    inferior: List[str]
    reason: str = ""


# Default tool preferences (matching Claude Code)
DEFAULT_PREFERENCES: List[ToolPreference] = [
    ToolPreference(
        preferred="Read",
        inferior=["cat", "head", "tail", "sed -n"],
        reason="Read tool preserves file metadata and respects encoding"
    ),
    ToolPreference(
        preferred="Edit",
        inferior=["sed", "awk"],
        reason="Edit tool uses SEARCH/REPLACE blocks with fuzzy matching"
    ),
    ToolPreference(
        preferred="Write",
        inferior=["cat heredoc", "echo >", "tee"],
        reason="Write tool handles encoding and atomic writes safely"
    ),
    ToolPreference(
        preferred="Glob",
        inferior=["find", "ls -R"],
        reason="Glob tool is optimized for file pattern matching"
    ),
    ToolPreference(
        preferred="Grep",
        inferior=["grep", "rg"],
        reason="Grep tool supports regex with proper context handling"
    ),
    ToolPreference(
        preferred="Bash",
        inferior=[],
        reason="Bash is reserved for shell execution only when no dedicated tool exists"
    ),
]


class ToolInstructionRegistry:
    """
    Registry of tool usage instructions.

    Manages per-tool usage guides and generates the combined instruction
    section that gets injected into the system prompt.
    """

    def __init__(self):
        self._tools: Dict[str, ToolInstruction] = {}
        self._preferences: List[ToolPreference] = list(DEFAULT_PREFERENCES)

    def register(self, instruction: ToolInstruction) -> None:
        """Register a tool instruction."""
        self._tools[instruction.name] = instruction

    def unregister(self, name: str) -> None:
        """Remove a tool instruction."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[ToolInstruction]:
        """Get a tool instruction by name."""
        return self._tools.get(name)

    def add_preference(self, preference: ToolPreference) -> None:
        """Add a tool preference rule."""
        self._preferences.append(preference)

    def get_preference(self, inferior_cmd: str) -> Optional[ToolPreference]:
        """
        Find the preferred tool for an inferior command.

        Args:
            inferior_cmd: The command to look up (e.g., "cat", "sed").

        Returns:
            The matching ToolPreference or None.
        """
        for pref in self._preferences:
            for inferior in pref.inferior:
                if inferior_cmd.strip().startswith(inferior):
                    return pref
        return None

    @property
    def registered_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def generate_tool_section(self, tool_names: Optional[List[str]] = None) -> str:
        """
        Generate the tool usage instruction section for the system prompt.

        Args:
            tool_names: If specified, only include instructions for these tools.

        Returns:
            Formatted markdown string with tool instructions.
        """
        if tool_names is None:
            tools = list(self._tools.values())
        else:
            tools = [self._tools[n] for n in tool_names if n in self._tools]

        if not tools:
            return ""

        sections = ["## Tool Usage Guide\n"]

        for tool in tools:
            sections.append(f"### {tool.name}")
            sections.append(tool.description)
            sections.append("")
            sections.append(f"**Usage:** {tool.usage}")
            sections.append("")

            if tool.examples:
                sections.append("**Examples:**")
                for ex in tool.examples:
                    sections.append(f"- {ex}")
                sections.append("")

            if tool.warnings:
                sections.append("**Warnings:**")
                for w in tool.warnings:
                    sections.append(f"- {w}")
                sections.append("")

            if tool.is_read_only:
                sections.append("*This tool is read-only.*")
                sections.append("")
            if tool.is_destructive:
                sections.append("*This tool is destructive — requires confirmation.*")
                sections.append("")

        return "\n".join(sections)

    def generate_preference_section(self) -> str:
        """
        Generate the tool preference rules section for the system prompt.

        Returns:
            Formatted markdown string with preference rules.
        """
        lines = [
            "## Tool Preference Rules",
            "",
            "Always use the dedicated tool instead of shell commands when available:",
            ""
        ]

        for pref in self._preferences:
            if pref.inferior:
                inferiors = ", ".join(f"`{i}`" for i in pref.inferior)
                lines.append(f"- Use **{pref.preferred}** instead of {inferiors}")
                if pref.reason:
                    lines.append(f"  - {pref.reason}")
            else:
                lines.append(f"- **{pref.preferred}** is reserved for shell execution only")

        lines.append("")
        lines.append("When multiple independent tool calls are possible, execute them in parallel to maximize efficiency.")
        lines.append("")

        return "\n".join(lines)


def create_default_registry() -> ToolInstructionRegistry:
    """
    Create a ToolInstructionRegistry pre-loaded with standard EAA tools
    matching the Claude Code tool set.
    """
    registry = ToolInstructionRegistry()

    # Read tool
    registry.register(ToolInstruction(
        name="Read",
        description="Read the contents of a text file. Returns content with line numbers.",
        usage="Provide the absolute file path. Supports offset/limit for large files.",
        examples=[
            'Read a Python file: {"path": "/home/user/project/main.py"}',
            'Read specific lines: {"path": "/home/user/project/main.py", "offset": 10, "limit": 50}'
        ],
        warnings=["Cannot read binary files (images, executables)."],
        is_read_only=True
    ))

    # Edit tool
    registry.register(ToolInstruction(
        name="Edit",
        description="Apply SEARCH/REPLACE edits to files using fuzzy matching.",
        usage="Provide old_str (text to find) and new_str (replacement). Uses fuzzy matching (threshold 0.8).",
        examples=[
            'Replace a function: {"old_str": "def old_name():", "new_str": "def new_name():"}',
            'Fix a bug: {"old_str": "x = 1 + 2", "new_str": "x = 1 + 3"}'
        ],
        warnings=[
            "File must be read before editing (read-before-write policy).",
            "Edits will be rejected if the file has been modified since last read.",
            "Multiple matches without replace_all will be rejected."
        ],
        is_destructive=True
    ))

    # Write tool
    registry.register(ToolInstruction(
        name="Write",
        description="Create or overwrite a file with new content.",
        usage="Provide the absolute file path and the complete file content.",
        examples=[
            'Create a new file: {"path": "/home/user/project/new.py", "content": "# New file\\nprint(1)"}'
        ],
        warnings=[
            "Prefer Edit over Write when modifying existing files.",
            "Always read a file before overwriting it."
        ],
        is_destructive=True
    ))

    # Glob tool
    registry.register(ToolInstruction(
        name="Glob",
        description="Find files matching a glob pattern in a directory.",
        usage="Provide path and pattern. Supports **, *, ?, [].",
        examples=[
            'Find Python files: {"path": "/home/user/project", "pattern": "**/*.py"}',
            'Find test files: {"path": "/home/user/project", "pattern": "test_*.py"}'
        ],
        is_read_only=True
    ))

    # Grep tool
    registry.register(ToolInstruction(
        name="Grep",
        description="Search for patterns in file contents using regex.",
        usage="Provide pattern and optional path. Supports regex, glob filtering, and context lines.",
        examples=[
            'Find function: {"pattern": "def process_", "path": "/home/user/project/src"}',
            'Case-insensitive: {"pattern": "TODO", "path": ".", "ignore_case": true}'
        ],
        is_read_only=True
    ))

    # Bash tool
    registry.register(ToolInstruction(
        name="Bash",
        description="Execute shell commands. Subject to permission checks and safety validation.",
        usage="Provide the command string. 23 security validators will check for dangerous patterns.",
        examples=[
            'Install packages: {"command": "pip install requests"}',
            'Run tests: {"command": "pytest tests/ -v"}'
        ],
        warnings=[
            "ALWAYS use dedicated tools (Read, Edit, Write, Glob, Grep) instead of Bash when possible.",
            "Bash is only for shell execution that has no dedicated tool equivalent.",
            "Commands are validated by 23 independent security validators.",
            "Dangerous commands will require user confirmation."
        ],
        is_destructive=True
    ))

    return registry
