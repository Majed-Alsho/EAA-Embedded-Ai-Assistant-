"""
EAA V4 - History Index
======================
Timestamp-based diff index for the .eaa_history/ rollback system.

From the blueprint (Section 12.3.1):
  "Every time any Worker touches a file via smart_edit, a background function
   automatically copies the original file state into a hidden .eaa_history/
   directory, indexed by timestamp and a short hash of the diff."

This module provides the indexing layer that maps file paths to their
backup history, enabling fast lookups for undo operations.

Structure:
  .eaa_history/
    <project_root_hash>/
      index.json              ← HistoryIndex (this module manages this)
      snapshots/
        20260418_143022_a1b2c3.py   ← Backup files
        20260418_143025_d4e5f6.py
        ...

Integration:
  RollbackManager → HistoryIndex (record + lookup backups)
  /undo command → HistoryIndex (find the right snapshot to restore)
"""

import os
import json
import time
import logging
import hashlib
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# SNAPSHOT ENTRY
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SnapshotEntry:
    """
    A single snapshot record in the history index.
    Represents one file backup at one point in time.
    """
    snapshot_id: str                   # Unique ID: timestamp_short_hash
    file_path: str                     # Original file path (absolute)
    backup_path: str                   # Path to backup file in .eaa_history/
    timestamp: float                   # Unix timestamp of the edit
    original_hash: str                 # SHA-256 hash of original content
    diff_hash: str                     # Short hash of the diff (6 chars)
    file_size: int                     # Original file size in bytes
    line_count: int                    # Original line count
    worker_id: str = ""                # Which worker made the edit
    tool_name: str = ""                # Which tool was used
    reason: str = ""                   # Why the edit was made

    @property
    def datetime_str(self) -> str:
        """Human-readable timestamp."""
        return datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def age_seconds(self) -> float:
        """Age of this snapshot in seconds."""
        return time.time() - self.timestamp

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "SnapshotEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ═══════════════════════════════════════════════════════════════════════════════
# HISTORY INDEX
# ═══════════════════════════════════════════════════════════════════════════════

class HistoryIndex:
    """
    Manages the timestamp-based diff index for file edit history.

    Blueprint (Section 12.3.1):
      "The user can type /undo in the terminal at any time to instantly
       restore the most recent edit, or /undo 3 to revert the last 3 edits."

    The index is a JSON file (index.json) inside .eaa_history/<project_hash>/
    that maps file paths to ordered lists of SnapshotEntry objects.

    Usage:
        index = HistoryIndex(project_root="/path/to/project")
        entry = index.record_snapshot(
            file_path="/path/to/project/main.py",
            content="original content",
            worker_id="coder",
        )
        # Later, to undo:
        latest = index.get_latest_snapshot("/path/to/project/main.py")
        if latest:
            # Restore from latest.backup_path
            pass
    """

    def __init__(
        self,
        project_root: str,
        history_dir_name: str = ".eaa_history",
        retention_days: int = 7,
    ):
        self.project_root = os.path.normpath(os.path.abspath(project_root))
        self.retention_days = retention_days
        self.history_dir_name = history_dir_name

        # Compute project-specific history directory
        project_hash = hashlib.sha256(
            self.project_root.encode()
        ).hexdigest()[:8]
        self.history_root = os.path.join(
            self.project_root,
            history_dir_name,
            project_hash,
        )
        self.snapshots_dir = os.path.join(self.history_root, "snapshots")
        self.index_file = os.path.join(self.history_root, "index.json")

        # In-memory index: file_path → [SnapshotEntry, ...]
        self._index: Dict[str, List[SnapshotEntry]] = {}

        # Stats
        self._total_snapshots = 0

        # Load existing index
        self._load_index()

        logger.info(
            f"[HistoryIndex] Initialized: project={self.project_root}, "
            f"history_dir={self.history_root}, "
            f"existing_snapshots={sum(len(v) for v in self._index.values())}"
        )

    def record_snapshot(
        self,
        file_path: str,
        content: str,
        worker_id: str = "",
        tool_name: str = "smart_edit",
        reason: str = "",
    ) -> SnapshotEntry:
        """
        Record a file snapshot before an edit.

        Creates a backup file and adds an entry to the index.

        Args:
            file_path: Absolute path to the file being edited
            content: Current file content (before edit)
            worker_id: Worker making the edit
            tool_name: Tool being used
            reason: Why the edit is being made

        Returns:
            SnapshotEntry with backup metadata
        """
        norm_path = os.path.normpath(os.path.abspath(file_path))
        timestamp = time.time()

        # Generate snapshot ID: timestamp_short_hash
        time_str = datetime.fromtimestamp(timestamp).strftime("%Y%m%d_%H%M%S")
        content_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        diff_hash = content_hash[:6]
        snapshot_id = f"{time_str}_{diff_hash}"

        # Determine backup file name (preserve original extension)
        ext = os.path.splitext(norm_path)[1] or ".txt"
        backup_filename = f"{snapshot_id}{ext}"
        backup_path = os.path.join(self.snapshots_dir, backup_filename)

        # Create directories
        os.makedirs(self.snapshots_dir, exist_ok=True)

        # Write backup file (idempotent: if same content hash exists, skip)
        if not os.path.exists(backup_path):
            try:
                with open(backup_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                logger.error(f"[HistoryIndex] Failed to write backup: {e}")
                # Still record the entry but mark backup as failed
                backup_path = ""

        # Create snapshot entry
        entry = SnapshotEntry(
            snapshot_id=snapshot_id,
            file_path=norm_path,
            backup_path=backup_path,
            timestamp=timestamp,
            original_hash=content_hash,
            diff_hash=diff_hash,
            file_size=len(content.encode("utf-8")),
            line_count=content.count("\n") + (1 if content and not content.endswith("\n") else 0),
            worker_id=worker_id,
            tool_name=tool_name,
            reason=reason,
        )

        # Add to index
        if norm_path not in self._index:
            self._index[norm_path] = []
        self._index[norm_path].append(entry)
        self._total_snapshots += 1

        # Persist index to disk
        self._save_index()

        logger.debug(
            f"[HistoryIndex] Snapshot recorded: {snapshot_id} "
            f"for {norm_path} (worker={worker_id})"
        )
        return entry

    def get_latest_snapshot(
        self, file_path: str
    ) -> Optional[SnapshotEntry]:
        """Get the most recent snapshot for a file."""
        norm_path = os.path.normpath(os.path.abspath(file_path))
        entries = self._index.get(norm_path, [])
        return entries[-1] if entries else None

    def get_n_latest_snapshot(
        self, file_path: str, n: int = 1
    ) -> Optional[SnapshotEntry]:
        """
        Get the Nth most recent snapshot (1 = latest, 2 = second latest, etc.)
        Used for /undo N command.
        """
        norm_path = os.path.normpath(os.path.abspath(file_path))
        entries = self._index.get(norm_path, [])
        idx = len(entries) - n
        if 0 <= idx < len(entries):
            return entries[idx]
        return None

    def get_snapshots(
        self,
        file_path: Optional[str] = None,
        since: Optional[float] = None,
        limit: int = 50,
    ) -> List[SnapshotEntry]:
        """
        Get snapshot entries, optionally filtered by file path and time.

        Args:
            file_path: Filter to specific file (None = all files)
            since: Only entries after this timestamp
            limit: Maximum entries to return
        """
        if file_path:
            norm_path = os.path.normpath(os.path.abspath(file_path))
            entries = self._index.get(norm_path, [])
        else:
            # All files, sorted by timestamp
            entries = []
            for file_entries in self._index.values():
                entries.extend(file_entries)

        # Filter by time
        if since:
            entries = [e for e in entries if e.timestamp >= since]

        # Sort by timestamp (newest first)
        entries.sort(key=lambda e: e.timestamp, reverse=True)

        return entries[:limit]

    def get_all_edited_files(self) -> List[str]:
        """Get list of all files that have snapshot history."""
        return list(self._index.keys())

    def remove_snapshot(self, snapshot_id: str) -> bool:
        """Remove a specific snapshot from the index and delete its backup."""
        for file_path, entries in self._index.items():
            for i, entry in enumerate(entries):
                if entry.snapshot_id == snapshot_id:
                    # Remove from index
                    entries.pop(i)
                    if not entries:
                        del self._index[file_path]

                    # Delete backup file
                    if entry.backup_path and os.path.exists(entry.backup_path):
                        try:
                            os.unlink(entry.backup_path)
                        except OSError:
                            pass

                    self._save_index()
                    logger.debug(f"[HistoryIndex] Snapshot removed: {snapshot_id}")
                    return True
        return False

    def garbage_collect(self) -> int:
        """
        Prune snapshots older than the retention period.

        Returns:
            Number of snapshots removed
        """
        cutoff = time.time() - (self.retention_days * 86400)
        removed = 0

        files_to_remove = []
        for file_path in list(self._index.keys()):
            entries = self._index[file_path]
            kept = []
            for entry in entries:
                if entry.timestamp < cutoff:
                    # Delete backup file
                    if entry.backup_path and os.path.exists(entry.backup_path):
                        try:
                            os.unlink(entry.backup_path)
                        except OSError:
                            pass
                    removed += 1
                else:
                    kept.append(entry)

            if kept:
                self._index[file_path] = kept
            else:
                files_to_remove.append(file_path)

        # Remove empty file entries
        for fp in files_to_remove:
            del self._index[fp]

        if removed > 0:
            self._save_index()
            logger.info(f"[HistoryIndex] GC: removed {removed} old snapshots")

        return removed

    def get_stats(self) -> Dict:
        """Get history index statistics."""
        total_entries = sum(len(v) for v in self._index.values())
        total_backup_size = 0
        backup_count = 0

        for entries in self._index.values():
            for entry in entries:
                if entry.backup_path and os.path.exists(entry.backup_path):
                    total_backup_size += os.path.getsize(entry.backup_path)
                    backup_count += 1

        return {
            "project_root": self.project_root,
            "history_dir": self.history_root,
            "total_snapshots": total_entries,
            "files_tracked": len(self._index),
            "backup_files_on_disk": backup_count,
            "total_backup_size_bytes": total_backup_size,
            "retention_days": self.retention_days,
            "index_file": self.index_file,
        }

    def _load_index(self):
        """Load index from disk if it exists."""
        if not os.path.exists(self.index_file):
            return

        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for file_path, entries_data in data.items():
                self._index[file_path] = [
                    SnapshotEntry.from_dict(e) for e in entries_data
                ]
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[HistoryIndex] Failed to load index: {e}")
            self._index = {}

    def _save_index(self):
        """Persist index to disk."""
        os.makedirs(os.path.dirname(self.index_file), exist_ok=True)

        try:
            data = {}
            for file_path, entries in self._index.items():
                data[file_path] = [e.to_dict() for e in entries]

            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"[HistoryIndex] Failed to save index: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_history_index(
    project_root: str,
    retention_days: int = 7,
) -> HistoryIndex:
    """Create a HistoryIndex for a project."""
    return HistoryIndex(
        project_root=project_root,
        retention_days=retention_days,
    )


__all__ = [
    "SnapshotEntry",
    "HistoryIndex",
    "create_history_index",
]
