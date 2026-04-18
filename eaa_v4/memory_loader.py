"""
memory_loader.py — Memory Loading System (Phase 4)

Loads instruction/memory files from multiple scope levels,
inspired by Claude Code's CLAUDE.md loading system.

Loading priority (later = higher priority):
    1. managed  — /etc/eaa/  (system-wide defaults)
    2. user     — ~/.eaa/    (user preferences)
    3. project  — walked from project root to CWD
    4. local    — EAA.local.md in CWD
    5. auto_mem — ~/.eaa/memory/auto.md (agent-generated memory)
    6. team_mem — ~/.eaa/memory/team.md (shared team memory)

Features:
    - @include directives (up to 5 levels deep)
    - HTML comment stripping
    - YAML frontmatter with paths: glob patterns for conditional application
    - Maximum file size: 40,000 characters

Reference: Blueprint Section 10.3 — CLAUDE.md Loading System
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Maximum file size to load (40K chars, matching Claude Code)
MAX_MEMORY_FILE_SIZE = 40000

# Maximum @include nesting depth
MAX_INCLUDE_DEPTH = 5

# Default memory file names
MANAGED_DIR = "/etc/eaa"
USER_DIR = "~/.eaa"
PROJECT_FILE = "EAA.md"
LOCAL_FILE = "EAA.local.md"
AUTO_MEM_FILE = "memory/auto.md"
TEAM_MEM_FILE = "memory/team.md"


@dataclass
class MemoryFile:
    """A loaded memory file with metadata."""
    path: str
    content: str
    scope: str  # managed, user, project, local, auto, team
    priority: int  # Higher = overrides lower
    size: int = 0
    includes: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.size = len(self.content)


@dataclass
class MemoryLoadResult:
    """Result of loading all memory files."""
    files: List[MemoryFile] = field(default_factory=list)
    combined_content: str = ""
    total_size: int = 0
    errors: List[str] = field(default_factory=list)

    def get_scoped_content(self, scope: str) -> str:
        """Get content from a specific scope."""
        for f in reversed(self.files):
            if f.scope == scope:
                return f.content
        return ""


def _strip_html_comments(text: str) -> str:
    """Remove HTML comments from text."""
    return re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)


def _parse_yaml_frontmatter(text: str) -> Tuple[dict, str]:
    """
    Parse YAML frontmatter from text.

    Returns:
        (metadata_dict, body_without_frontmatter)
    """
    if not text.startswith('---'):
        return {}, text

    end_match = re.search(r'^---\s*$', text[3:], re.MULTILINE)
    if not end_match:
        return {}, text

    frontmatter = text[3:3 + end_match.start()].strip()
    body = text[3 + end_match.end():].strip()

    # Simple YAML parsing (key: value pairs)
    metadata = {}
    for line in frontmatter.split('\n'):
        line = line.strip()
        if ':' in line and not line.startswith('#'):
            key, _, value = line.partition(':')
            metadata[key.strip()] = value.strip().strip('"').strip("'")

    return metadata, body


def _process_includes(
    content: str,
    base_path: str,
    depth: int = 0,
    visited: Optional[set] = None,
) -> Tuple[str, List[str]]:
    """
    Process @include directives in content.

    Supports: @include path/to/file.md

    Args:
        content: The content to process.
        base_path: Directory to resolve relative paths from.
        depth: Current include depth.
        visited: Set of already-visited absolute paths (cycle detection).

    Returns:
        (processed_content, list_of_included_paths)
    """
    if visited is None:
        visited = set()

    included_paths = []
    include_pattern = re.compile(r'^@include\s+(.+)$', re.MULTILINE)

    def replace_include(match: re.Match) -> str:
        nonlocal depth
        rel_path = match.group(1).strip()

        # Resolve the path
        if os.path.isabs(rel_path):
            inc_path = rel_path
        else:
            inc_path = os.path.normpath(os.path.join(base_path, rel_path))

        # Cycle detection
        if inc_path in visited:
            return f"<!-- [skipped circular include: {rel_path}] -->"

        # Depth check
        if depth >= MAX_INCLUDE_DEPTH:
            return f"<!-- [skipped: max include depth ({MAX_INCLUDE_DEPTH}) exceeded] -->"

        # File existence check
        if not os.path.isfile(inc_path):
            return f"<!-- [include not found: {rel_path}] -->"

        # Size check
        try:
            with open(inc_path, 'r', encoding='utf-8') as f:
                inc_content = f.read()
        except (IOError, OSError):
            return f"<!-- [include read error: {rel_path}] -->"

        if len(inc_content) > MAX_MEMORY_FILE_SIZE:
            return f"<!-- [include too large: {rel_path}] -->"

        visited.add(inc_path)
        included_paths.append(inc_path)

        # Recursively process includes
        processed, sub_includes = _process_includes(
            inc_content, os.path.dirname(inc_path), depth + 1, visited
        )
        included_paths.extend(sub_includes)

        return processed

    processed = include_pattern.sub(replace_include, content)
    return processed, included_paths


def _check_path_conditions(metadata: dict, cwd: str) -> bool:
    """
    Check if YAML frontmatter path conditions match current working directory.

    Supports:
        paths: "src/**"         — matches any file under src/
        paths: ["src/**", "lib"] — matches any of the patterns

    Args:
        metadata: Parsed YAML frontmatter.
        cwd: Current working directory.

    Returns:
        True if no path conditions or conditions match.
    """
    if 'paths' not in metadata:
        return True

    paths_value = metadata['paths']

    # Normalize to list
    if isinstance(paths_value, str):
        patterns = [p.strip() for p in paths_value.split(',')]
    else:
        patterns = [str(p).strip() for p in paths_value]

    for pattern in patterns:
        # Convert glob-like patterns to simple matching
        if pattern.endswith('/**') or pattern.endswith('\\**'):
            prefix = pattern[:-3]
            if os.path.normpath(cwd).startswith(os.path.normpath(prefix)):
                return True
        elif pattern.startswith('*.'):
            # Extension match
            ext = pattern[1:]  # e.g., ".py"
            if any(f.endswith(ext) for f in os.listdir(cwd) if os.path.isfile(os.path.join(cwd, f))):
                return True
        else:
            # Exact or prefix match
            if os.path.normpath(cwd) == os.path.normpath(pattern):
                return True
            if os.path.normpath(cwd).startswith(os.path.normpath(pattern)):
                return True

    return False


def _load_single_file(path: str, scope: str, priority: int) -> Optional[MemoryFile]:
    """
    Load a single memory file with processing.

    Returns None if file doesn't exist or is too large.
    """
    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        return None

    try:
        with open(expanded, 'r', encoding='utf-8') as f:
            raw = f.read()
    except (IOError, OSError):
        return None

    if len(raw) > MAX_MEMORY_FILE_SIZE:
        return None

    # Strip HTML comments
    content = _strip_html_comments(raw)

    # Parse frontmatter
    metadata, body = _parse_yaml_frontmatter(content)
    content = body

    # Check path conditions
    cwd = os.getcwd()
    if not _check_path_conditions(metadata, cwd):
        return None

    # Process includes
    base_dir = os.path.dirname(os.path.abspath(expanded))
    processed, includes = _process_includes(content, base_dir)
    content = processed

    return MemoryFile(
        path=expanded,
        content=content,
        scope=scope,
        priority=priority,
        includes=includes
    )


def load_all_memory(project_root: str = ".") -> MemoryLoadResult:
    """
    Load all memory files from all scope levels.

    Args:
        project_root: The project root directory.

    Returns:
        MemoryLoadResult with all loaded files combined by priority.
    """
    result = MemoryLoadResult()
    cwd = os.path.abspath(project_root or ".")
    home = os.path.expanduser("~")
    priority = 0
    errors = []

    # 1. Managed scope (/etc/eaa/)
    managed_path = os.path.join(MANAGED_DIR, PROJECT_FILE)
    f = _load_single_file(managed_path, "managed", priority)
    if f:
        result.files.append(f)
    priority += 1

    # 2. User scope (~/.eaa/)
    user_path = os.path.join(USER_DIR, PROJECT_FILE)
    f = _load_single_file(user_path, "user", priority)
    if f:
        result.files.append(f)
    priority += 1

    # 3. Project scope (walk from root to CWD)
    root = os.path.abspath(project_root)
    current = root
    project_files = []
    while current and current != os.path.dirname(current):
        md_path = os.path.join(current, PROJECT_FILE)
        if os.path.isfile(md_path):
            f = _load_single_file(md_path, "project", priority)
            if f:
                project_files.append(f)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    # Add project files in root-to-CWD order (CWD has higher priority)
    result.files.extend(project_files)
    priority += 1

    # 4. Local scope (EAA.local.md in CWD)
    local_path = os.path.join(cwd, LOCAL_FILE)
    f = _load_single_file(local_path, "local", priority)
    if f:
        result.files.append(f)
    priority += 1

    # 5. Auto memory (~/.eaa/memory/auto.md)
    auto_path = os.path.join(USER_DIR, AUTO_MEM_FILE)
    f = _load_single_file(auto_path, "auto", priority)
    if f:
        result.files.append(f)
    priority += 1

    # 6. Team memory (~/.eaa/memory/team.md)
    team_path = os.path.join(USER_DIR, TEAM_MEM_FILE)
    f = _load_single_file(team_path, "team", priority)
    if f:
        result.files.append(f)

    # Sort by priority and combine
    result.files.sort(key=lambda mf: mf.priority)
    sections = []
    for mf in result.files:
        if mf.content.strip():
            sections.append(f"<!-- memory: {mf.scope} [{mf.path}] -->\n{mf.content}")
    result.combined_content = "\n\n".join(sections)
    result.total_size = len(result.combined_content)

    return result
