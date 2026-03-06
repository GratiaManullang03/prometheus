"""File editor tool — safe read/write operations on workspace files only.

The agent is NOT allowed to write outside the workspace directory.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = Path(os.environ.get("AGENT_WORKSPACE", "./workspace/source_code")).resolve()


class FileEditorError(Exception):
    """Raised on unsafe or failed file operations."""


class FileEditor:
    """Read, write, patch, and list files within the workspace sandbox.

    All paths are validated against the workspace root before any I/O.
    """

    def __init__(self, workspace_root: Optional[Path] = None) -> None:
        self._root = (workspace_root or _WORKSPACE_ROOT).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        logger.info("FileEditor: workspace root = %s", self._root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self, relative_path: str) -> str:
        """Read and return file contents.

        Args:
            relative_path: Path relative to workspace root.

        Returns:
            File contents as a string.
        """
        safe = self._safe_path(relative_path)
        logger.debug("FileEditor.read: %s", safe)
        return safe.read_text(encoding="utf-8")

    def write(self, relative_path: str, content: str) -> None:
        """Write (overwrite) a file atomically.

        Args:
            relative_path: Path relative to workspace root.
            content: New file contents.
        """
        safe = self._safe_path(relative_path)
        safe.parent.mkdir(parents=True, exist_ok=True)
        tmp = safe.with_suffix(safe.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(safe)
        logger.info("FileEditor.write: %s (%d bytes)", safe, len(content))

    def patch(self, relative_path: str, old: str, new: str) -> None:
        """Replace the first occurrence of `old` with `new` in a file.

        Args:
            relative_path: Path relative to workspace root.
            old: Exact string to replace.
            new: Replacement string.
        """
        content = self.read(relative_path)
        if old not in content:
            raise FileEditorError(f"patch: '{old[:60]}...' not found in {relative_path}")
        self.write(relative_path, content.replace(old, new, 1))
        logger.info("FileEditor.patch: applied patch to %s", relative_path)

    def delete(self, relative_path: str) -> None:
        """Delete a file from the workspace.

        Args:
            relative_path: Path relative to workspace root.
        """
        safe = self._safe_path(relative_path)
        safe.unlink()
        logger.info("FileEditor.delete: %s", safe)

    def list_files(self, subdirectory: str = "") -> list[str]:
        """List all files under a subdirectory of the workspace.

        Args:
            subdirectory: Optional sub-path. Defaults to workspace root.

        Returns:
            Sorted list of relative paths.
        """
        base = self._safe_path(subdirectory) if subdirectory else self._root
        paths = [str(p.relative_to(self._root)) for p in base.rglob("*") if p.is_file()]
        return sorted(paths)

    def backup(self, relative_path: str) -> str:
        """Create a .bak backup of a file; returns backup path."""
        safe = self._safe_path(relative_path)
        backup_path = safe.with_suffix(safe.suffix + ".bak")
        shutil.copy2(safe, backup_path)
        logger.info("FileEditor.backup: %s -> %s", safe, backup_path)
        return str(backup_path.relative_to(self._root))

    # ------------------------------------------------------------------

    def _safe_path(self, relative_path: str) -> Path:
        """Resolve and validate path is within workspace root."""
        target = (self._root / relative_path).resolve()
        try:
            target.relative_to(self._root)
        except ValueError:
            raise FileEditorError(
                f"Path traversal attempt blocked: {relative_path!r} -> {target}"
            )
        return target
