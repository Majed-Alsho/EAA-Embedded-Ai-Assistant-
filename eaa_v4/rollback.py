"""
EAA V4 - Absolute Rollback System
==================================
Instant, unlimited undo for all file edits via .eaa_history/ directory.

From the blueprint (Section 12.3.1):
  "The user can type /undo in the terminal at any time to instantly restore
   the most recent edit, or /undo 3 to revert the last 3 edits in sequence.
   The rollback system replaces the broken file with the exact snapshot from
   the specified point in history."

Key features:
  - Automatic backup before every smart_edit write
  - Idempotent backups keyed on content hash (no duplicates)
  - /undo → revert most recent edit
  - /undo N → revert last N edits in sequence
  - Project-scoped, survives across sessions
  - Garbage collection (default: prune after 7 days)
  - Atomic restore (temp file + rename, same as writes)

Integration:
  SmartEditEngine.edit() → RollbackManager.backup_before_edit()
  /undo command → RollbackManager.undo()

The RollbackManager sits between SmartEditEngine and HistoryIndex:
  SmartEditEngine → RollbackManager → HistoryIndex
"""

import os
import time
import shutil
import logging
import tempfile
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

from history_index import HistoryIndex, SnapshotEntry, create_history_index
from file_state import FileStateManager

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# ROLLBACK RESULT
# ═══════════════════════════════════════════════════════════════════════════════

class RollbackResultStatus(Enum):
    """Status of a rollback operation."""
    SUCCESS = "success"
    NO_HISTORY = "no_history"       # No snapshots found for this file
    SNAPSHOT_MISSING = "snapshot_missing"  # Backup file doesn't exist
    RESTORE_FAILED = "restore_failed"      # OS error during restore
    WRONG_FILE = "wrong_file"              # Snapshot is for a different file


@dataclass
class RollbackResult:
    """Result of an undo/rollback operation."""
    status: RollbackResultStatus
    file_path: str = ""
    snapshot_id: str = ""
    restored_from: str = ""          # Backup file path used
    message: str = ""
    edits_reverted: int = 0          # Number of edits that were reverted

    def to_dict(self) -> Dict:
        return {
            "status": self.status.value,
            "file_path": self.file_path,
            "snapshot_id": self.snapshot_id,
            "restored_from": self.restored_from,
            "message": self.message,
            "edits_reverted": self.edits_reverted,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ROLLBACK MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class RollbackManager:
    """
    Manages absolute rollback for file edits.

    Blueprint (Section 12.3.1):
      "This provides complete peace of mind when delegating file modifications
       to the agent, because any mistake can be reversed instantly and completely.
       The history is project-scoped, survives across sessions, and includes a
       garbage collection mechanism."

    Usage:
        rm = RollbackManager(project_root="/path/to/project")

        # Before edit (called automatically by SmartEditEngine):
        rm.backup_before_edit("/path/to/project/main.py", content, worker_id="coder")

        # After edit, to undo:
        result = rm.undo("/path/to/project/main.py")
        # Or undo last 3 edits:
        result = rm.undo("/path/to/project/main.py", steps=3)
    """

    def __init__(
        self,
        project_root: str,
        file_state_manager: Optional[FileStateManager] = None,
        history_index: Optional[HistoryIndex] = None,
        retention_days: int = 7,
    ):
        self.project_root = os.path.normpath(os.path.abspath(project_root))
        self.file_state = file_state_manager or FileStateManager()
        self.index = history_index or create_history_index(
            project_root=self.project_root,
            retention_days=retention_days,
        )
        self.retention_days = retention_days

        # Stats
        self._total_backups = 0
        self._total_undos = 0
        self._successful_undos = 0
        self._failed_undos = 0

        logger.info(
            f"[Rollback] Initialized: project={self.project_root}, "
            f"retention={retention_days}d"
        )

    def backup_before_edit(
        self,
        file_path: str,
        content: str,
        worker_id: str = "",
        tool_name: str = "smart_edit",
        reason: str = "",
    ) -> Optional[SnapshotEntry]:
        """
        Create a backup snapshot before an edit operation.

        This is the Step 2 from the atomic write pattern (Section 5.1.1):
        "Create an idempotent file history backup keyed on content hash."

        Idempotent: if a backup with the same content hash already exists,
        the backup file is skipped (no duplicate storage).

        Args:
            file_path: Absolute path to the file about to be edited
            content: Current file content (before the edit)
            worker_id: Worker making the edit
            tool_name: Tool being used
            reason: Why the edit is being made

        Returns:
            SnapshotEntry if backup was created, None on failure
        """
        self._total_backups += 1

        try:
            entry = self.index.record_snapshot(
                file_path=file_path,
                content=content,
                worker_id=worker_id,
                tool_name=tool_name,
                reason=reason,
            )
            logger.debug(
                f"[Rollback] Backup created: {entry.snapshot_id} "
                f"for {file_path}"
            )
            return entry
        except Exception as e:
            logger.error(f"[Rollback] Backup failed for {file_path}: {e}")
            return None

    def undo(
        self,
        file_path: str,
        steps: int = 1,
    ) -> RollbackResult:
        """
        Revert a file to a previous state by restoring from backup.

        Blueprint: /undo → revert most recent, /undo N → revert last N.

        When steps > 1, the system restores the Nth-to-last snapshot directly.
        Intermediate edits are NOT replayed — the file jumps back to the
        state at that snapshot.

        Args:
            file_path: Absolute path to the file to revert
            steps: Number of edits to revert (1 = most recent)

        Returns:
            RollbackResult with success/failure and metadata
        """
        self._total_undos += 1
        norm_path = os.path.normpath(os.path.abspath(file_path))

        # Get the Nth-to-last snapshot
        snapshot = self.index.get_n_latest_snapshot(norm_path, n=steps)

        if not snapshot:
            self._failed_undos += 1
            return RollbackResult(
                status=RollbackResultStatus.NO_HISTORY,
                file_path=norm_path,
                message=f"No edit history found for: {norm_path}",
                edits_reverted=0,
            )

        # Verify backup file exists
        if not snapshot.backup_path or not os.path.exists(snapshot.backup_path):
            self._failed_undos += 1
            return RollbackResult(
                status=RollbackResultStatus.SNAPSHOT_MISSING,
                file_path=norm_path,
                snapshot_id=snapshot.snapshot_id,
                message=(
                    f"Backup file missing for snapshot {snapshot.snapshot_id}: "
                    f"{snapshot.backup_path}"
                ),
                edits_reverted=0,
            )

        # Verify the snapshot is for the correct file
        if os.path.normpath(snapshot.file_path) != norm_path:
            self._failed_undos += 1
            return RollbackResult(
                status=RollbackResultStatus.WRONG_FILE,
                file_path=norm_path,
                snapshot_id=snapshot.snapshot_id,
                message=f"Snapshot is for different file: {snapshot.file_path}",
                edits_reverted=0,
            )

        # Perform atomic restore
        restore_ok = self._restore_from_backup(norm_path, snapshot.backup_path)

        if not restore_ok:
            self._failed_undos += 1
            return RollbackResult(
                status=RollbackResultStatus.RESTORE_FAILED,
                file_path=norm_path,
                snapshot_id=snapshot.snapshot_id,
                message=f"Failed to restore from {snapshot.backup_path}",
                edits_reverted=0,
            )

        # Update file state after restore
        try:
            with open(norm_path, "r", encoding="utf-8") as f:
                restored_content = f.read()
            self.file_state.mark_written(norm_path, restored_content)
        except Exception:
            pass

        # Remove reverted snapshots from index (they're no longer valid)
        self._remove_reverted_snapshots(norm_path, steps)

        self._successful_undos += 1

        logger.info(
            f"[Rollback] Undo successful: {norm_path} "
            f"restored to snapshot {snapshot.snapshot_id} "
            f"({steps} edit(s) reverted)"
        )

        return RollbackResult(
            status=RollbackResultStatus.SUCCESS,
            file_path=norm_path,
            snapshot_id=snapshot.snapshot_id,
            restored_from=snapshot.backup_path,
            message=(
                f"Restored {norm_path} to state from "
                f"{snapshot.datetime_str} (reverted {steps} edit(s))"
            ),
            edits_reverted=steps,
        )

    def list_history(
        self,
        file_path: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """
        List edit history for a file or all files.

        Returns human-readable list of snapshot entries.
        """
        snapshots = self.index.get_snapshots(file_path=file_path, limit=limit)
        return [
            {
                "snapshot_id": s.snapshot_id,
                "file": os.path.basename(s.file_path),
                "full_path": s.file_path,
                "datetime": s.datetime_str,
                "worker": s.worker_id,
                "lines": s.line_count,
                "size_bytes": s.file_size,
                "has_backup": bool(s.backup_path and os.path.exists(s.backup_path)),
            }
            for s in snapshots
        ]

    def get_history_count(self, file_path: Optional[str] = None) -> int:
        """Get number of snapshots for a file or all files."""
        if file_path:
            norm_path = os.path.normpath(os.path.abspath(file_path))
            return len(self.index._index.get(norm_path, []))
        return sum(len(v) for v in self.index._index.values())

    def clear_history(self, file_path: Optional[str] = None):
        """Clear all history for a file or all files."""
        if file_path:
            norm_path = os.path.normpath(os.path.abspath(file_path))
            if norm_path in self.index._index:
                # Delete backup files
                for entry in self.index._index[norm_path]:
                    if entry.backup_path and os.path.exists(entry.backup_path):
                        try:
                            os.unlink(entry.backup_path)
                        except OSError:
                            pass
                del self.index._index[norm_path]
        else:
            # Clear everything
            for entries in self.index._index.values():
                for entry in entries:
                    if entry.backup_path and os.path.exists(entry.backup_path):
                        try:
                            os.unlink(entry.backup_path)
                        except OSError:
                            pass
            self.index._index.clear()

        self.index._save_index()
        logger.info(f"[Rollback] History cleared: {file_path or 'all files'}")

    def garbage_collect(self) -> int:
        """
        Prune snapshots older than retention period.
        Returns number of snapshots removed.
        """
        return self.index.garbage_collect()

    def get_stats(self) -> Dict:
        """Get rollback system statistics."""
        return {
            "project_root": self.project_root,
            "total_backups": self._total_backups,
            "total_undos": self._total_undos,
            "successful_undos": self._successful_undos,
            "failed_undos": self._failed_undos,
            "retention_days": self.retention_days,
            "history_index": self.index.get_stats(),
            "file_state": self.file_state.get_stats(),
        }

    def _restore_from_backup(
        self, file_path: str, backup_path: str
    ) -> bool:
        """
        Atomically restore a file from a backup.

        Uses the same atomic rename pattern as smart_edit:
        Write to temp file in same directory → rename over original.

        Blueprint (Section 5.1.1, Steps 6-7):
          "Write to a temporary file in the same directory (same filesystem
           for atomic rename). Atomically rename the temp file over the original."
        """
        try:
            # Ensure parent directory exists
            parent_dir = os.path.dirname(file_path)
            os.makedirs(parent_dir, exist_ok=True)

            # Read backup content
            with open(backup_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Write to temp file in same directory
            fd, temp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix=".eaa_undo_",
                dir=parent_dir,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)

            # Atomic rename
            os.replace(temp_path, file_path)
            return True

        except Exception as e:
            logger.error(
                f"[Rollback] Atomic restore failed for {file_path}: {e}"
            )
            # Clean up temp file
            try:
                if 'temp_path' in locals():
                    os.unlink(temp_path)
            except OSError:
                pass
            return False

    def _remove_reverted_snapshots(
        self, file_path: str, steps: int
    ):
        """
        Remove the N most recent snapshots after a successful undo.
        These snapshots are no longer valid since we've reverted past them.
        """
        norm_path = os.path.normpath(os.path.abspath(file_path))
        entries = self.index._index.get(norm_path, [])

        if not entries:
            return

        # Remove the last N entries (most recent)
        to_remove = entries[-steps:] if steps <= len(entries) else entries[:]

        for entry in to_remove:
            # Delete backup files
            if entry.backup_path and os.path.exists(entry.backup_path):
                try:
                    os.unlink(entry.backup_path)
                except OSError:
                    pass

        # Trim the list
        remaining = len(entries) - steps
        if remaining <= 0:
            del self.index._index[norm_path]
        else:
            self.index._index[norm_path] = entries[:-steps]

        self.index._save_index()


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_rollback_manager(
    project_root: str,
    file_state_manager: Optional[FileStateManager] = None,
    retention_days: int = 7,
) -> RollbackManager:
    """Create a RollbackManager for a project."""
    return RollbackManager(
        project_root=project_root,
        file_state_manager=file_state_manager,
        retention_days=retention_days,
    )


__all__ = [
    "RollbackResultStatus",
    "RollbackResult",
    "RollbackManager",
    "create_rollback_manager",
]
