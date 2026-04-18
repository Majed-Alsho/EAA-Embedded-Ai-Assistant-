"""
EAA V4 - File State Tracker
============================
Tracks file read state and modification timestamps to enforce
Claude Code's read-before-write policy.

From the blueprint (Section 5.1):
  "The FileEditTool enforces a read-before-write policy through a readFileState
   cache that tracks which files have been recently read and their modification
   timestamps. When a file has not been read, or has been modified since it was
   last read, the tool rejects the edit with an appropriate error code."

This prevents editing files based on stale information — a critical safety
feature that Claude Code implements with staleness checks comparing file
modification times against a cached read timestamp.

Integration:
  smart_edit.py → file_state.py (checks before every edit)
  rollback.py → file_state.py (records after every edit)
"""

import os
import time
import logging
import hashlib
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# FILE STATE TYPES
# ═══════════════════════════════════════════════════════════════════════════════

class FileStateStatus(Enum):
    """Status of a file in the tracking cache."""
    NOT_READ = "not_read"           # File has never been read
    CURRENT = "current"             # File was read and is up-to-date
    STALE = "stale"                 # File was read but has been modified since
    DELETED = "deleted"             # File was read but no longer exists
    TOO_LARGE = "too_large"         # File exceeds size limit


@dataclass
class FileReadRecord:
    """
    Record of when a file was last read and its state at that time.
    Stored in the readFileState cache.
    """
    file_path: str                              # Absolute, normalized path
    read_timestamp: float                       # When the file was read (time.time())
    file_mtime: float                           # File modification time at read
    file_size: int                              # File size in bytes at read
    content_hash: str = ""                      # SHA-256 hash of file content
    encoding: str = "utf-8"                     # Detected encoding
    line_count: int = 0                         # Number of lines

    def to_dict(self) -> Dict:
        return {
            "file_path": self.file_path,
            "read_timestamp": self.read_timestamp,
            "file_mtime": self.file_mtime,
            "file_size": self.file_size,
            "content_hash": self.content_hash,
            "encoding": self.encoding,
            "line_count": self.line_count,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# FILE STATE MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class FileStateManager:
    """
    Tracks file read/write state to enforce read-before-write policy.

    Claude Code's approach (Section 5.1):
      "The tool enforces a read-before-write policy through a readFileState
       cache that tracks which files have been recently read and their
       modification timestamps."

    When a file has not been read, or has been modified since it was last
    read, the edit is rejected with error code 6 (read-before-write) or
    error code 7 (stale read).

    Usage:
        fsm = FileStateManager()
        fsm.mark_read("/path/to/file.py", content)
        status = fsm.check_editable("/path/to/file.py")
        if status == FileStateStatus.CURRENT:
            # Safe to edit
        fsm.mark_written("/path/to/file.py", new_content)
    """

    def __init__(
        self,
        max_size_bytes: int = 1_073_741_824,  # 1 GiB default (blueprint Section 5.1.3, Code 10)
        max_cache_entries: int = 1000,
    ):
        self._cache: Dict[str, FileReadRecord] = {}
        self._max_size_bytes = max_size_bytes
        self._max_cache_entries = max_cache_entries

        # Stats
        self._total_reads = 0
        self._total_writes = 0
        self._total_stale_rejects = 0
        self._total_unread_rejects = 0

        logger.info(
            f"[FileState] Initialized: max_file_size={max_size_bytes}, "
            f"max_cache={max_cache_entries}"
        )

    def mark_read(
        self,
        file_path: str,
        content: str = "",
        encoding: str = "utf-8",
    ) -> FileReadRecord:
        """
        Record that a file has been read. Stores file metadata and content hash.

        Args:
            file_path: Absolute path to the file
            content: File content (for hashing)
            encoding: Detected encoding of the file

        Returns:
            FileReadRecord with the read state

        Raises:
            FileNotFoundError: If the file doesn't exist on disk
        """
        norm_path = os.path.normpath(os.path.abspath(file_path))

        # Get actual file metadata from disk
        if not os.path.exists(norm_path):
            raise FileNotFoundError(f"File not found: {norm_path}")

        stat = os.stat(norm_path)
        file_size = stat.st_size

        # Check file size limit
        if file_size > self._max_size_bytes:
            record = FileReadRecord(
                file_path=norm_path,
                read_timestamp=time.time(),
                file_mtime=stat.st_mtime,
                file_size=file_size,
                content_hash="",
                encoding=encoding,
                line_count=0,
            )
            self._cache[norm_path] = record
            logger.warning(
                f"[FileState] File too large ({file_size} bytes > "
                f"{self._max_size_bytes}): {norm_path}"
            )
            return record

        # Compute content hash
        content_hash = hashlib.sha256(content.encode(encoding, errors="replace")).hexdigest()
        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

        record = FileReadRecord(
            file_path=norm_path,
            read_timestamp=time.time(),
            file_mtime=stat.st_mtime,
            file_size=file_size,
            content_hash=content_hash,
            encoding=encoding,
            line_count=line_count,
        )

        # Store in cache
        self._cache[norm_path] = record
        self._total_reads += 1

        # Evict old entries if over limit
        if len(self._cache) > self._max_cache_entries:
            self._evict_oldest()

        logger.debug(
            f"[FileState] Marked read: {norm_path} "
            f"(size={file_size}, lines={line_count}, hash={content_hash[:12]}...)"
        )
        return record

    def mark_written(
        self,
        file_path: str,
        content: str = "",
        encoding: str = "utf-8",
    ) -> FileReadRecord:
        """
        Update file state after a write operation.
        This resets the read state to the new content, so the file
        is immediately editable again (no staleness window).
        """
        norm_path = os.path.normpath(os.path.abspath(file_path))

        if not os.path.exists(norm_path):
            raise FileNotFoundError(f"File not found after write: {norm_path}")

        stat = os.stat(norm_path)
        content_hash = hashlib.sha256(content.encode(encoding, errors="replace")).hexdigest()
        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

        record = FileReadRecord(
            file_path=norm_path,
            read_timestamp=time.time(),
            file_mtime=stat.st_mtime,
            file_size=stat.st_size,
            content_hash=content_hash,
            encoding=encoding,
            line_count=line_count,
        )

        self._cache[norm_path] = record
        self._total_writes += 1

        logger.debug(
            f"[FileState] Marked written: {norm_path} "
            f"(size={stat.st_size}, hash={content_hash[:12]}...)"
        )
        return record

    def check_editable(self, file_path: str) -> Tuple[FileStateStatus, str]:
        """
        Check if a file is safe to edit based on read state.

        Returns:
            Tuple of (status, reason):
            - (CURRENT, "File is up-to-date") → Safe to edit
            - (STALE, "File modified since read") → Reject with error code 7
            - (NOT_READ, "File has not been read") → Reject with error code 6
            - (DELETED, "File no longer exists") → Reject with error code 4
            - (TOO_LARGE, "File exceeds size limit") → Reject with error code 10

        Blueprint reference (Section 5.1.3):
          Code 6: read-before-write policy
          Code 7: stale file reads
          Code 10: files larger than 1 GiB
        """
        norm_path = os.path.normpath(os.path.abspath(file_path))

        # Check if file exists
        if not os.path.exists(norm_path):
            if norm_path in self._cache:
                return FileStateStatus.DELETED, (
                    f"File was previously read but no longer exists: {norm_path}"
                )
            return FileStateStatus.NOT_READ, (
                f"File not found: {norm_path}"
            )

        # Check if file has been read
        if norm_path not in self._cache:
            self._total_unread_rejects += 1
            return FileStateStatus.NOT_READ, (
                f"File has not been read before editing: {norm_path}. "
                f"Read the file first using read_file tool."
            )

        record = self._cache[norm_path]

        # Check file size
        current_stat = os.stat(norm_path)
        if current_stat.st_size > self._max_size_bytes:
            return FileStateStatus.TOO_LARGE, (
                f"File too large ({current_stat.st_size} bytes > "
                f"{self._max_size_bytes} bytes limit)"
            )

        # Check staleness via modification time
        # Claude Code uses mtime comparison with content-based fallback on Windows
        if abs(current_stat.st_mtime - record.file_mtime) > 0.001:
            # Modification time changed — file may have been edited externally
            self._total_stale_rejects += 1
            return FileStateStatus.STALE, (
                f"File has been modified since it was last read: {norm_path}. "
                f"Last read at {time.ctime(record.read_timestamp)}, "
                f"current mtime {time.ctime(current_stat.st_mtime)} vs "
                f"cached mtime {time.ctime(record.file_mtime)}. "
                f"Re-read the file to get the latest version."
            )

        # File is current — safe to edit
        return FileStateStatus.CURRENT, "File is up-to-date and safe to edit"

    def get_record(self, file_path: str) -> Optional[FileReadRecord]:
        """Get the cached read record for a file."""
        norm_path = os.path.normpath(os.path.abspath(file_path))
        return self._cache.get(norm_path)

    def is_read(self, file_path: str) -> bool:
        """Check if a file has been read (regardless of staleness)."""
        norm_path = os.path.normpath(os.path.abspath(file_path))
        return norm_path in self._cache

    def invalidate(self, file_path: str):
        """Remove a file from the cache (force re-read)."""
        norm_path = os.path.normpath(os.path.abspath(file_path))
        if norm_path in self._cache:
            del self._cache[norm_path]
            logger.debug(f"[FileState] Invalidated: {norm_path}")

    def invalidate_all(self):
        """Clear the entire cache."""
        self._cache.clear()
        logger.debug("[FileState] All entries invalidated")

    def get_read_files(self) -> list:
        """Get list of all currently tracked file paths."""
        return list(self._cache.keys())

    def get_stats(self) -> Dict:
        """Get file state tracking statistics."""
        return {
            "cached_files": len(self._cache),
            "total_reads": self._total_reads,
            "total_writes": self._total_writes,
            "stale_rejects": self._total_stale_rejects,
            "unread_rejects": self._total_unread_rejects,
            "max_file_size_bytes": self._max_size_bytes,
            "max_cache_entries": self._max_cache_entries,
        }

    def _evict_oldest(self):
        """Evict the oldest cache entries to free space."""
        if not self._cache:
            return

        # Sort by read_timestamp, remove oldest 20%
        sorted_records = sorted(
            self._cache.items(),
            key=lambda x: x[1].read_timestamp,
        )
        to_remove = max(1, len(sorted_records) // 5)
        for path, _ in sorted_records[:to_remove]:
            del self._cache[path]

        logger.debug(f"[FileState] Evicted {to_remove} old entries")


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_file_state_manager(
    max_file_size_mb: int = 1024,
) -> FileStateManager:
    """Create a FileStateManager with human-readable size limit."""
    return FileStateManager(max_size_bytes=max_file_size_mb * 1024 * 1024)


__all__ = [
    "FileStateStatus",
    "FileReadRecord",
    "FileStateManager",
    "create_file_state_manager",
]
