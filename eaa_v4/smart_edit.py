"""
EAA V4 - Smart Edit Engine
==========================
Aider-style SEARCH/REPLACE fuzzy matching editor with atomic writes.

From the blueprint (Section 5.2):
  "Instead of requiring the model to reproduce the exact text it wants to
   change, the system accepts approximate matches and uses fuzzy matching
   algorithms to locate the target block."

This replaces Claude Code's exact string matching (Section 5.1.2) with
a fuzzy approach that's more reliable for local 7B models that struggle
with exact whitespace/indentation reproduction.

Architecture:
  - Three-layer normalization (exact → quote → XML) with fuzzy fallback
  - Atomic 7-step write pattern from Claude Code (Section 5.1.1)
  - 11 validation error codes from Claude Code (Section 5.1.3)
  - Configurable similarity threshold (default 0.8)

Integration:
  FileStateManager → SmartEditEngine (read-before-write + staleness check)
  SmartEditEngine → RollbackManager (automatic backup before every write)
"""

import os
import re
import hashlib
import logging
import tempfile
import shutil
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

from file_state import FileStateManager, FileStateStatus

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# EDIT ERROR CODES (Blueprint Section 5.1.3)
# ═══════════════════════════════════════════════════════════════════════════════

class EditErrorCode(Enum):
    """Validation error codes that provide specific, actionable feedback."""
    NO_ERROR = -1                          # Success
    SECRETS_DETECTED = 0                   # Team memory secrets being introduced
    NOOP_EDIT = 1                          # old_string equals new_string
    PATH_DENIED = 2                        # Path denied by permission rules
    OVERWRITE_EXISTING = 3                 # Overwriting non-empty with create
    FILE_NOT_FOUND = 4                     # File not found (with fuzzy suggestions)
    REDIRECT_NOTEBOOK = 5                  # .ipynb files redirected
    READ_BEFORE_WRITE = 6                  # File not read before editing
    STALE_READ = 7                         # File modified since last read
    STRING_NOT_FOUND = 8                   # Search string not found in file
    MULTIPLE_MATCHES = 9                   # Multiple matches without replace_all
    FILE_TOO_LARGE = 10                    # File exceeds 1 GiB


@dataclass
class EditResult:
    """
    Result of a smart edit operation.
    Contains success/failure status, error code, and metadata.
    """
    success: bool
    file_path: str
    error_code: EditErrorCode = EditErrorCode.NO_ERROR
    error_message: str = ""
    search_string: str = ""
    replace_string: str = ""
    matches_found: int = 0
    similarity_score: float = 0.0
    best_match_line: int = -1
    lines_changed: int = 0
    original_content: str = ""
    new_content: str = ""
    backup_path: str = ""

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "file_path": self.file_path,
            "error_code": self.error_code.value if isinstance(self.error_code, EditErrorCode) else self.error_code,
            "error_message": self.error_message,
            "matches_found": self.matches_found,
            "similarity_score": self.similarity_score,
            "best_match_line": self.best_match_line,
            "lines_changed": self.lines_changed,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# THREE-LAYER STRING NORMALIZATION (Blueprint Section 5.1.2)
# ═══════════════════════════════════════════════════════════════════════════════

# Curly quote mappings
_CURLY_TO_STRAIGHT = {
    "\u201c": '"',  # "
    "\u201d": '"',  # "
    "\u2018": "'",  # '
    "\u2019": "'",  # '
}

# XML entity mappings
_XML_ENTITIES = {
    "&lt;": "<",
    "&gt;": ">",
    "&amp;": "&",
    "&quot;": '"',
    "&apos;": "'",
}

# Reverse XML entities
_XML_ENTITIES_REVERSE = {v: k for k, v in _XML_ENTITIES.items()}


def normalize_quotes(text: str) -> str:
    """Layer 2: Normalize curly quotes to straight quotes (and vice versa)."""
    result = text
    for curly, straight in _CURLY_TO_STRAIGHT.items():
        result = result.replace(curly, straight)
    return result


def normalize_xml(text: str) -> str:
    """Layer 3: Normalize XML entities (collapse expanded entities)."""
    result = text
    for entity, char in _XML_ENTITIES.items():
        result = result.replace(entity, char)
    return result


def strip_whitespace_blocks(text: str) -> str:
    """Strip leading/trailing blank lines and common indentation for matching."""
    lines = text.split("\n")
    # Strip leading blank lines
    while lines and not lines[0].strip():
        lines.pop(0)
    # Strip trailing blank lines
    while lines and not lines[-1].strip():
        lines.pop()
    # Dedent (remove common leading whitespace)
    if lines:
        min_indent = min(
            len(line) - len(line.lstrip())
            for line in lines
            if line.strip()
        )
        lines = [line[min_indent:] if len(line) >= min_indent else line for line in lines]
    return "\n".join(lines)


def compute_similarity(a: str, b: str) -> float:
    """Compute similarity ratio between two strings using SequenceMatcher."""
    return SequenceMatcher(None, a, b).ratio()


# ═══════════════════════════════════════════════════════════════════════════════
# FUZZY MATCHER
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FuzzyMatchResult:
    """Result of a fuzzy search for a string in file content."""
    found: bool
    start_line: int = -1           # 0-based line number
    end_line: int = -1             # 0-based, exclusive
    matched_text: str = ""
    similarity: float = 0.0
    total_matches: int = 0         # Total matches above threshold


class FuzzyMatcher:
    """
    Searches file content for approximate matches using a three-layer
    approach with fuzzy fallback.

    Layer 1: Exact string match
    Layer 2: Quote-normalized match
    Layer 3: XML-de-sanitized match
    Fallback: SequenceMatcher-based fuzzy search

    Blueprint (Section 5.2):
      "A fuzzy matching algorithm (based on difflib.SequenceMatcher) scans
       the file for the best match above a configurable threshold (default 0.8)."
    """

    def __init__(self, similarity_threshold: float = 0.8):
        self.similarity_threshold = similarity_threshold

    def find_match(
        self,
        file_content: str,
        search_string: str,
        replace_all: bool = False,
    ) -> FuzzyMatchResult:
        """
        Find the best match for search_string in file_content.

        Returns FuzzyMatchResult with location, matched text, and similarity.
        """
        if not search_string:
            return FuzzyMatchResult(found=False)

        file_lines = file_content.split("\n")
        search_lines = search_string.split("\n")
        search_len = len(search_lines)

        # Try exact match first (Layer 1)
        exact_result = self._try_exact(file_lines, search_lines)
        if exact_result.found:
            if replace_all:
                count = self._count_all_exact(file_lines, search_lines)
                return FuzzyMatchResult(
                    found=True,
                    start_line=exact_result.start_line,
                    end_line=exact_result.end_line,
                    matched_text=exact_result.matched_text,
                    similarity=1.0,
                    total_matches=count,
                )
            return FuzzyMatchResult(
                found=True,
                start_line=exact_result.start_line,
                end_line=exact_result.end_line,
                matched_text=exact_result.matched_text,
                similarity=1.0,
                total_matches=1,
            )
        # Multiple exact matches without replace_all → error
        if exact_result.total_matches > 1 and not replace_all:
            return exact_result
        elif exact_result.total_matches > 1 and replace_all:
            return FuzzyMatchResult(
                found=True,
                start_line=exact_result.start_line,
                end_line=exact_result.end_line,
                matched_text=exact_result.matched_text,
                similarity=1.0,
                total_matches=exact_result.total_matches,
            )

        # Try quote-normalized match (Layer 2)
        quote_result = self._try_normalized(
            file_lines, search_lines, normalize_quotes
        )
        if quote_result.found:
            return quote_result

        # Try XML-de-sanitized match (Layer 3)
        xml_result = self._try_normalized(
            file_lines, search_lines, normalize_xml
        )
        if xml_result.found:
            return xml_result

        # Fallback: fuzzy search using sliding window
        return self._fuzzy_search(file_lines, search_lines, replace_all)

    def _try_exact(
        self, file_lines: List[str], search_lines: List[str]
    ) -> FuzzyMatchResult:
        """Layer 1: Exact string matching."""
        search_len = len(search_lines)
        all_matches = []
        for i in range(len(file_lines) - search_len + 1):
            candidate = file_lines[i:i + search_len]
            if candidate == search_lines:
                all_matches.append(i)

        if len(all_matches) == 1:
            i = all_matches[0]
            return FuzzyMatchResult(
                found=True,
                start_line=i,
                end_line=i + search_len,
                matched_text="\n".join(file_lines[i:i + search_len]),
                similarity=1.0,
                total_matches=1,
            )
        elif len(all_matches) > 1:
            # Multiple exact matches — return as error (Blueprint Section 5.1.2)
            i = all_matches[0]
            return FuzzyMatchResult(
                found=False,
                start_line=i,
                end_line=i + search_len,
                matched_text="\n".join(file_lines[i:i + search_len]),
                similarity=1.0,
                total_matches=len(all_matches),
            )
        return FuzzyMatchResult(found=False)

    def _count_all_exact(
        self, file_lines: List[str], search_lines: List[str]
    ) -> int:
        """Count all exact occurrences."""
        count = 0
        search_len = len(search_lines)
        for i in range(len(file_lines) - search_len + 1):
            if file_lines[i:i + search_len] == search_lines:
                count += 1
        return count

    def _try_normalized(
        self,
        file_lines: List[str],
        search_lines: List[str],
        normalizer,
    ) -> FuzzyMatchResult:
        """Layer 2/3: Normalized matching with quote or XML normalization."""
        search_len = len(search_lines)
        norm_search = [normalizer(line) for line in search_lines]

        for i in range(len(file_lines) - search_len + 1):
            candidate = file_lines[i:i + search_len]
            norm_candidate = [normalizer(line) for line in candidate]
            if norm_candidate == norm_search:
                return FuzzyMatchResult(
                    found=True,
                    start_line=i,
                    end_line=i + search_len,
                    matched_text="\n".join(candidate),
                    similarity=0.95,  # High confidence but not exact
                    total_matches=1,
                )
        return FuzzyMatchResult(found=False)

    def _fuzzy_search(
        self,
        file_lines: List[str],
        search_lines: List[str],
        replace_all: bool = False,
    ) -> FuzzyMatchResult:
        """
        Fallback: Sliding window fuzzy search.
        Uses SequenceMatcher to find the best match above threshold.
        """
        search_len = len(search_lines)
        if search_len == 0 or len(file_lines) == 0:
            return FuzzyMatchResult(found=False)

        search_text = "\n".join(search_lines)
        matches = []

        for i in range(len(file_lines) - search_len + 1):
            candidate = file_lines[i:i + search_len]
            candidate_text = "\n".join(candidate)

            # Strip whitespace for comparison (fuzzy tolerance)
            stripped_search = strip_whitespace_blocks(search_text)
            stripped_candidate = strip_whitespace_blocks(candidate_text)

            similarity = compute_similarity(stripped_search, stripped_candidate)

            if similarity >= self.similarity_threshold:
                matches.append((i, i + search_len, similarity, candidate_text))

        if not matches:
            # Report the best match even if below threshold
            best_sim = 0.0
            best_idx = 0
            best_text = ""
            for i in range(len(file_lines) - search_len + 1):
                candidate = file_lines[i:i + search_len]
                candidate_text = "\n".join(candidate)
                stripped_search = strip_whitespace_blocks(search_text)
                stripped_candidate = strip_whitespace_blocks(candidate_text)
                sim = compute_similarity(stripped_search, stripped_candidate)
                if sim > best_sim:
                    best_sim = sim
                    best_idx = i
                    best_text = candidate_text

            return FuzzyMatchResult(
                found=False,
                start_line=best_idx,
                end_line=best_idx + search_len,
                matched_text=best_text,
                similarity=best_sim,
                total_matches=0,
            )

        # Sort by similarity (highest first)
        matches.sort(key=lambda x: x[2], reverse=True)

        total = len(matches)

        if replace_all:
            # Return info about all matches
            return FuzzyMatchResult(
                found=True,
                start_line=matches[0][0],
                end_line=matches[0][1],
                matched_text=matches[0][3],
                similarity=matches[0][2],
                total_matches=total,
            )

        if len(matches) == 1:
            return FuzzyMatchResult(
                found=True,
                start_line=matches[0][0],
                end_line=matches[0][1],
                matched_text=matches[0][3],
                similarity=matches[0][2],
                total_matches=1,
            )

        # Multiple matches without replace_all → error
        return FuzzyMatchResult(
            found=False,
            start_line=matches[0][0],
            end_line=matches[0][1],
            matched_text=matches[0][3],
            similarity=matches[0][2],
            total_matches=total,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SMART EDIT ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class SmartEditEngine:
    """
    Main smart edit engine with Aider-style SEARCH/REPLACE and atomic writes.

    Blueprint (Section 5.2):
      "The Worker outputs a SEARCH block and a REPLACE block. The Python backend
       strips leading/trailing whitespace from both. A fuzzy matching algorithm
       scans the file for the best match above a configurable threshold."

    Atomic write pattern (Section 5.1.1):
      Step 1: Create parent directory
      Step 2: Create idempotent backup keyed on content hash
      Step 3: Read file with metadata preservation
      Step 4: Staleness check via mtime
      Step 5: Find matching string (3-layer normalization)
      Step 6: Write to temp file
      Step 7: Atomic rename

    Usage:
        engine = SmartEditEngine(file_state_manager=fsm)
        result = engine.edit(
            file_path="/project/main.py",
            search_string="old code",
            replace_string="new code",
        )
    """

    def __init__(
        self,
        file_state_manager: Optional[FileStateManager] = None,
        similarity_threshold: float = 0.8,
        protected_paths: Optional[List[str]] = None,
    ):
        self.file_state = file_state_manager or FileStateManager()
        self.matcher = FuzzyMatcher(similarity_threshold=similarity_threshold)
        self.protected_paths = protected_paths or [
            "/etc/", "/var/", "/boot/", "/usr/", "/bin/", "/sbin/",
            "~/.ssh/", "~/.gnupg/", "~/.aws/",
        ]

        # Stats
        self._total_edits = 0
        self._successful_edits = 0
        self._failed_edits = 0
        self._total_lines_changed = 0

        logger.info(
            f"[SmartEdit] Initialized: threshold={similarity_threshold}"
        )

    def edit(
        self,
        file_path: str,
        search_string: str,
        replace_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """
        Perform a smart edit on a file.

        Args:
            file_path: Absolute path to the file to edit
            search_string: The text to find (SEARCH block)
            replace_string: The replacement text (REPLACE block)
            replace_all: If True, replace all occurrences

        Returns:
            EditResult with success/failure, error code, and metadata
        """
        self._total_edits += 1
        norm_path = os.path.normpath(os.path.abspath(file_path))

        # ── Pre-edit validation ──

        # Code 2: Path denied by permission rules
        for protected in self.protected_paths:
            prot_norm = os.path.normpath(os.path.abspath(os.path.expanduser(protected)))
            if norm_path.startswith(prot_norm):
                return EditResult(
                    success=False,
                    file_path=norm_path,
                    error_code=EditErrorCode.PATH_DENIED,
                    error_message=f"Cannot edit file in protected path: {protected}",
                )

        # Code 5: Redirect .ipynb files
        if norm_path.endswith(".ipynb"):
            return EditResult(
                success=False,
                file_path=norm_path,
                error_code=EditErrorCode.REDIRECT_NOTEBOOK,
                error_message="Use NotebookEditTool for .ipynb files",
            )

        # Code 1: No-op check
        if search_string == replace_string:
            return EditResult(
                success=False,
                file_path=norm_path,
                error_code=EditErrorCode.NOOP_EDIT,
                error_message="Search string is identical to replace string (no-op edit)",
                search_string=search_string,
            )

        # Code 4: File not found
        if not os.path.exists(norm_path):
            # Try fuzzy path suggestion
            suggestion = self._suggest_path(norm_path)
            msg = f"File not found: {norm_path}"
            if suggestion:
                msg += f". Did you mean: {suggestion}?"
            return EditResult(
                success=False,
                file_path=norm_path,
                error_code=EditErrorCode.FILE_NOT_FOUND,
                error_message=msg,
                search_string=search_string,
            )

        # Code 10: File too large
        file_size = os.path.getsize(norm_path)
        if file_size > self.file_state._max_size_bytes:
            return EditResult(
                success=False,
                file_path=norm_path,
                error_code=EditErrorCode.FILE_TOO_LARGE,
                error_message=(
                    f"File too large ({file_size} bytes > "
                    f"{self.file_state._max_size_bytes} bytes limit)"
                ),
            )

        # Code 6 & 7: Read-before-write / staleness check
        status, reason = self.file_state.check_editable(norm_path)
        if status == FileStateStatus.NOT_READ:
            return EditResult(
                success=False,
                file_path=norm_path,
                error_code=EditErrorCode.READ_BEFORE_WRITE,
                error_message=reason,
                search_string=search_string,
            )
        if status == FileStateStatus.STALE:
            return EditResult(
                success=False,
                file_path=norm_path,
                error_code=EditErrorCode.STALE_READ,
                error_message=reason,
                search_string=search_string,
            )
        if status == FileStateStatus.TOO_LARGE:
            return EditResult(
                success=False,
                file_path=norm_path,
                error_code=EditErrorCode.FILE_TOO_LARGE,
                error_message=reason,
                search_string=search_string,
            )

        # ── Atomic Write Pattern (Blueprint Section 5.1.1) ──

        # Step 1: Ensure parent directory exists
        parent_dir = os.path.dirname(norm_path)
        os.makedirs(parent_dir, exist_ok=True)

        # Step 2: Create idempotent backup (done by rollback manager externally)
        # Step 3: Read file synchronously with metadata preservation
        try:
            with open(norm_path, "r", encoding="utf-8", errors="replace") as f:
                original_content = f.read()
        except Exception as e:
            return EditResult(
                success=False,
                file_path=norm_path,
                error_code=EditErrorCode.FILE_NOT_FOUND,
                error_message=f"Failed to read file: {e}",
                search_string=search_string,
            )

        # Step 4: Final staleness check (double-check mtime)
        current_mtime = os.stat(norm_path).st_mtime
        record = self.file_state.get_record(norm_path)
        if record and abs(current_mtime - record.file_mtime) > 0.001:
            return EditResult(
                success=False,
                file_path=norm_path,
                error_code=EditErrorCode.STALE_READ,
                error_message="File was modified between staleness check and read",
                search_string=search_string,
            )

        # Step 5: Find matching string using 3-layer normalization + fuzzy
        match_result = self.matcher.find_match(
            original_content, search_string, replace_all
        )

        if not match_result.found:
            if match_result.total_matches > 1 and not replace_all:
                return EditResult(
                    success=False,
                    file_path=norm_path,
                    error_code=EditErrorCode.MULTIPLE_MATCHES,
                    error_message=(
                        f"Found {match_result.total_matches} matches but "
                        f"replace_all is False. Make the search string more "
                        f"specific, or set replace_all=True."
                    ),
                    search_string=search_string,
                    matches_found=match_result.total_matches,
                    similarity_score=match_result.similarity,
                    best_match_line=match_result.start_line,
                )
            else:
                # Code 8: String not found
                msg = (
                    f"Search string not found in {norm_path}. "
                    f"Best match similarity: {match_result.similarity:.2f} "
                    f"(threshold: {self.matcher.similarity_threshold})."
                )
                if match_result.start_line >= 0:
                    msg += (
                        f" Best match at line {match_result.start_line + 1}. "
                        f"Try making your search string more similar to the "
                        f"actual file content."
                    )
                return EditResult(
                    success=False,
                    file_path=norm_path,
                    error_code=EditErrorCode.STRING_NOT_FOUND,
                    error_message=msg,
                    search_string=search_string,
                    similarity_score=match_result.similarity,
                    best_match_line=match_result.start_line,
                )

        # ── Apply the edit ──

        file_lines = original_content.split("\n")

        if replace_all:
            # Replace all matches
            replace_lines = replace_string.split("\n")
            new_lines = []
            search_len = len(search_string.split("\n"))
            i = 0
            replacements = 0
            while i < len(file_lines):
                candidate = file_lines[i:i + search_len]
                candidate_text = "\n".join(candidate)
                stripped_search = strip_whitespace_blocks(search_string)
                stripped_candidate = strip_whitespace_blocks(candidate_text)
                sim = compute_similarity(stripped_search, stripped_candidate)
                if sim >= self.matcher.similarity_threshold:
                    new_lines.extend(replace_lines)
                    i += search_len
                    replacements += 1
                else:
                    new_lines.append(file_lines[i])
                    i += 1
            new_content = "\n".join(new_lines)
            lines_changed = replacements * max(1, abs(
                len(replace_string.split("\n")) - search_len
            ))
        else:
            # Single replacement
            replace_lines = replace_string.split("\n")
            new_lines = (
                file_lines[:match_result.start_line] +
                replace_lines +
                file_lines[match_result.end_line:]
            )
            new_content = "\n".join(new_lines)
            lines_changed = abs(len(replace_lines) - (match_result.end_line - match_result.start_line))

        # Step 6: Write to temp file in same directory (atomic rename requirement)
        try:
            fd, temp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix=".eaa_edit_",
                dir=parent_dir,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception as e:
            return EditResult(
                success=False,
                file_path=norm_path,
                error_code=EditErrorCode.FILE_NOT_FOUND,
                error_message=f"Failed to write temp file: {e}",
                search_string=search_string,
            )

        # Step 7: Atomic rename
        try:
            os.replace(temp_path, norm_path)
        except Exception as e:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            return EditResult(
                success=False,
                file_path=norm_path,
                error_code=EditErrorCode.FILE_NOT_FOUND,
                error_message=f"Failed to rename temp file: {e}",
                search_string=search_string,
            )

        # Update file state after write
        try:
            self.file_state.mark_written(norm_path, new_content)
        except Exception:
            pass  # Non-critical: state update failed but edit succeeded

        # Update stats
        self._successful_edits += 1
        self._total_lines_changed += lines_changed

        logger.info(
            f"[SmartEdit] Edit applied: {norm_path} "
            f"(matches={match_result.total_matches}, "
            f"similarity={match_result.similarity:.2f}, "
            f"lines_changed={lines_changed})"
        )

        return EditResult(
            success=True,
            file_path=norm_path,
            search_string=search_string,
            replace_string=replace_string,
            matches_found=match_result.total_matches,
            similarity_score=match_result.similarity,
            best_match_line=match_result.start_line,
            lines_changed=lines_changed,
            original_content=original_content,
            new_content=new_content,
        )

    def create_file(
        self,
        file_path: str,
        content: str,
        allow_overwrite: bool = False,
    ) -> EditResult:
        """
        Create a new file with atomic write.

        Code 3 from blueprint: prevents overwriting existing non-empty files
        with a create operation unless allow_overwrite=True.
        """
        norm_path = os.path.normpath(os.path.abspath(file_path))

        # Code 3: Overwriting existing non-empty file
        if os.path.exists(norm_path) and not allow_overwrite:
            if os.path.getsize(norm_path) > 0:
                return EditResult(
                    success=False,
                    file_path=norm_path,
                    error_code=EditErrorCode.OVERWRITE_EXISTING,
                    error_message=(
                        f"File already exists and is non-empty: {norm_path}. "
                        f"Use allow_overwrite=True or edit_file instead."
                    ),
                )

        # Ensure parent directory
        parent_dir = os.path.dirname(norm_path)
        os.makedirs(parent_dir, exist_ok=True)

        # Atomic write via temp file
        try:
            fd, temp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix=".eaa_edit_",
                dir=parent_dir,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(temp_path, norm_path)
        except Exception as e:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            return EditResult(
                success=False,
                file_path=norm_path,
                error_code=EditErrorCode.FILE_NOT_FOUND,
                error_message=f"Failed to create file: {e}",
            )

        # Mark as written in file state
        try:
            self.file_state.mark_written(norm_path, content)
        except Exception:
            pass

        self._successful_edits += 1
        logger.info(f"[SmartEdit] File created: {norm_path}")

        return EditResult(
            success=True,
            file_path=norm_path,
            new_content=content,
            lines_changed=content.count("\n"),
        )

    def _suggest_path(self, file_path: str) -> str:
        """Suggest a similar file path when the target doesn't exist."""
        norm_path = os.path.normpath(os.path.abspath(file_path))
        parent_dir = os.path.dirname(norm_path)
        target_name = os.path.basename(norm_path)

        if not os.path.exists(parent_dir):
            return ""

        try:
            existing = os.listdir(parent_dir)
            # Find similar filenames
            for name in existing:
                sim = SequenceMatcher(None, target_name, name).ratio()
                if sim > 0.7:
                    return os.path.join(parent_dir, name)
        except OSError:
            pass

        return ""

    def get_stats(self) -> Dict:
        """Get smart edit statistics."""
        return {
            "total_edits": self._total_edits,
            "successful_edits": self._successful_edits,
            "failed_edits": self._failed_edits,
            "total_lines_changed": self._total_lines_changed,
            "similarity_threshold": self.matcher.similarity_threshold,
            "file_state": self.file_state.get_stats(),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_smart_edit(
    file_state_manager: Optional[FileStateManager] = None,
    similarity_threshold: float = 0.8,
) -> SmartEditEngine:
    """Create a SmartEditEngine with sensible defaults."""
    fsm = file_state_manager or FileStateManager()
    return SmartEditEngine(
        file_state_manager=fsm,
        similarity_threshold=similarity_threshold,
    )


__all__ = [
    "EditErrorCode",
    "EditResult",
    "FuzzyMatchResult",
    "FuzzyMatcher",
    "SmartEditEngine",
    "normalize_quotes",
    "normalize_xml",
    "strip_whitespace_blocks",
    "compute_similarity",
    "create_smart_edit",
]
