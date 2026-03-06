"""Persistent memory system for the autonomous agent.

Tracks architecture decisions, tool docs, failures,
successful improvements, and the ideas backlog.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MemoryCategory(str, Enum):
    ARCHITECTURE_DECISIONS = "architecture_decisions"
    TOOL_DOCUMENTATION = "tool_documentation"
    PAST_FAILURES = "past_failures"
    SUCCESSFUL_IMPROVEMENTS = "successful_improvements"
    IDEAS_BACKLOG = "ideas_backlog"
    EXPERIMENT_RESULTS = "experiment_results"


class MemoryEntry:
    """A single memory record."""

    def __init__(self, category: MemoryCategory, content: dict[str, Any]) -> None:
        self.id = str(uuid.uuid4())
        self.category = category
        self.content = content
        self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category.value,
            "content": self.content,
            "created_at": self.created_at,
        }


class MemoryManager:
    """Thread-safe persistent JSON-backed memory store.

    Memory is NEVER deleted — only appended to or pruned
    when exceeding the configured threshold (oldest entries
    are archived, not removed).
    """

    def __init__(self, db_path: str, max_entries: int = 1000) -> None:
        self._path = Path(db_path)
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, category: MemoryCategory, content: dict[str, Any]) -> str:
        """Persist a new memory entry; returns its ID."""
        entry = MemoryEntry(category, content)
        with self._lock:
            bucket: list = self._data.setdefault(category.value, [])
            bucket.append(entry.to_dict())
            self._maybe_prune(category.value)
            self._save()
        logger.info("Memory stored: category=%s id=%s", category.value, entry.id)
        return entry.id

    def retrieve(
        self,
        category: MemoryCategory,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return the most recent `limit` entries from a category."""
        with self._lock:
            bucket: list = self._data.get(category.value, [])
            return list(reversed(bucket))[offset : offset + limit]

    def search(self, keyword: str) -> list[dict[str, Any]]:
        """Full-text search across all categories."""
        results: list[dict[str, Any]] = []
        keyword_lower = keyword.lower()
        with self._lock:
            for bucket in self._data.values():
                for entry in bucket:
                    if keyword_lower in json.dumps(entry).lower():
                        results.append(entry)
        return results

    def stats(self) -> dict[str, int]:
        """Return entry counts per category."""
        with self._lock:
            return {k: len(v) for k, v in self._data.items() if isinstance(v, list)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load data from disk; initialise if file does not exist."""
        if not self._path.exists():
            self._data = {
                "version": "1.0",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            for cat in MemoryCategory:
                self._data[cat.value] = []
            self._save()
            return
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                self._data = json.load(fh)
            logger.info("Memory loaded from %s", self._path)
        except Exception as exc:
            logger.error("Failed to load memory: %s — starting fresh", exc)
            self._data = {}
            for cat in MemoryCategory:
                self._data[cat.value] = []

    def _save(self) -> None:
        """Atomically write data to disk."""
        tmp = self._path.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
            tmp.replace(self._path)
        except Exception as exc:
            logger.error("Failed to save memory: %s", exc)
            tmp.unlink(missing_ok=True)

    def _maybe_prune(self, category_key: str) -> None:
        """Keep only the newest entries when over threshold."""
        bucket: list = self._data.get(category_key, [])
        if len(bucket) <= self._max_entries:
            return
        cutoff = len(bucket) - self._max_entries
        archive_path = self._path.parent / f"archive_{category_key}.json"
        archived = bucket[:cutoff]
        self._data[category_key] = bucket[cutoff:]
        try:
            existing: list = []
            if archive_path.exists():
                with archive_path.open("r", encoding="utf-8") as fh:
                    existing = json.load(fh)
            with archive_path.open("w", encoding="utf-8") as fh:
                json.dump(existing + archived, fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Could not archive pruned entries: %s", exc)
        logger.info(
            "Pruned %d entries from %s — archived to %s",
            cutoff,
            category_key,
            archive_path,
        )
