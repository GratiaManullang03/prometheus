"""Persistent memory system backed by SQLite with FTS5 full-text search.

Replaces JSON flat-file backend (v1) with a proper database.
Auto-migrates from legacy knowledge_base.json on first run.
WAL mode enables concurrent reads across multiple agent instances (Phase 3+).
Memory is NEVER deleted — only archived when over threshold.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)


class MemoryCategory(str, Enum):
    ARCHITECTURE_DECISIONS = "architecture_decisions"
    TOOL_DOCUMENTATION = "tool_documentation"
    PAST_FAILURES = "past_failures"
    SUCCESSFUL_IMPROVEMENTS = "successful_improvements"
    IDEAS_BACKLOG = "ideas_backlog"
    EXPERIMENT_RESULTS = "experiment_results"


class MemoryManager:
    """Thread-safe SQLite-backed memory store with FTS5 full-text search.

    Schema v2. Auto-migrates from legacy knowledge_base.json on first run.
    WAL journal mode supports concurrent reads from multiple instances.
    """

    def __init__(self, db_path: str, max_entries: int = 1000) -> None:
        path = Path(db_path)
        self._db_path = path.with_suffix(".db") if path.suffix == ".json" else path
        self._legacy_json = self._db_path.with_suffix(".json")
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._init_db()
        self._maybe_migrate()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, category: MemoryCategory, content: dict[str, Any]) -> str:
        """Persist a new memory entry; returns its ID."""
        entry_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._db() as conn:
                conn.execute(
                    "INSERT INTO memories (id, category, content, created_at) VALUES (?,?,?,?)",
                    (entry_id, category.value, json.dumps(content, ensure_ascii=False), created_at),
                )
            self._maybe_prune(category)
        logger.info("Memory stored: category=%s id=%s", category.value, entry_id[:8])
        return entry_id

    def retrieve(
        self, category: MemoryCategory, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Return the most recent `limit` entries from a category."""
        with self._lock:
            with self._db() as conn:
                rows = conn.execute(
                    "SELECT id, category, content, created_at FROM memories "
                    "WHERE category=? ORDER BY rowid DESC LIMIT ? OFFSET ?",
                    (category.value, limit, offset),
                ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search(self, keyword: str) -> list[dict[str, Any]]:
        """Full-text search across all categories using FTS5."""
        with self._lock:
            with self._db() as conn:
                try:
                    rows = conn.execute(
                        "SELECT m.id, m.category, m.content, m.created_at "
                        "FROM memories m JOIN memories_fts f ON f.id = m.id "
                        "WHERE memories_fts MATCH ? ORDER BY rank LIMIT 50",
                        (keyword,),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = conn.execute(
                        "SELECT id, category, content, created_at FROM memories "
                        "WHERE content LIKE ? LIMIT 50",
                        (f"%{keyword}%",),
                    ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def stats(self) -> dict[str, int]:
        """Return entry counts per category."""
        with self._lock:
            with self._db() as conn:
                rows = conn.execute(
                    "SELECT category, COUNT(*) FROM memories GROUP BY category"
                ).fetchall()
        result = {cat.value: 0 for cat in MemoryCategory}
        result.update({row[0]: row[1] for row in rows})
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @contextmanager
    def _db(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self._db_path), timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id         TEXT PRIMARY KEY,
                    category   TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cat ON memories(category);
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    id UNINDEXED, category, content,
                    content='memories', content_rowid='rowid'
                );
                CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, id, category, content)
                    VALUES (new.rowid, new.id, new.category, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, id, category, content)
                    VALUES ('delete', old.rowid, old.id, old.category, old.content);
                END;
            """)
        logger.info("MemoryManager: SQLite DB ready at %s", self._db_path)

    def _maybe_migrate(self) -> None:
        if not self._legacy_json.exists():
            return
        try:
            data = json.loads(self._legacy_json.read_text("utf-8"))
            count = 0
            with self._lock, self._db() as conn:
                for cat in MemoryCategory:
                    for entry in data.get(cat.value, []):
                        conn.execute(
                            "INSERT OR IGNORE INTO memories (id,category,content,created_at) VALUES (?,?,?,?)",
                            (
                                entry.get("id", str(uuid.uuid4())),
                                cat.value,
                                json.dumps(entry.get("content", {}), ensure_ascii=False),
                                entry.get("created_at") or datetime.now(timezone.utc).isoformat(),
                            ),
                        )
                        count += 1
            archive = self._legacy_json.with_suffix(".json.migrated")
            self._legacy_json.rename(archive)
            logger.info(
                "MemoryManager: migrated %d entries JSON→SQLite, archived to %s", count, archive
            )
        except Exception as exc:
            logger.error("MemoryManager: migration failed: %s", exc)

    def _maybe_prune(self, category: MemoryCategory) -> None:
        with self._db() as conn:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE category=?", (category.value,)
            ).fetchone()
            if count <= self._max_entries:
                return
            to_del = count - self._max_entries
            old = conn.execute(
                "SELECT id, category, content, created_at FROM memories "
                "WHERE category=? ORDER BY rowid ASC LIMIT ?",
                (category.value, to_del),
            ).fetchall()
            self._append_archive(category.value, [self._row_to_dict(r) for r in old])
            ids = [r[0] for r in old]
            conn.execute(
                f"DELETE FROM memories WHERE id IN ({','.join('?'*len(ids))})", ids
            )
        logger.info("MemoryManager: pruned %d from %s", to_del, category.value)

    def _append_archive(self, category_key: str, entries: list) -> None:
        path = self._db_path.parent / f"archive_{category_key}.json"
        existing: list = []
        if path.exists():
            try:
                existing = json.loads(path.read_text("utf-8"))
            except Exception:
                pass
        path.write_text(
            json.dumps(existing + entries, indent=2, ensure_ascii=False), "utf-8"
        )

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        return {
            "id": row[0],
            "category": row[1],
            "content": json.loads(row[2]),
            "created_at": row[3],
        }
