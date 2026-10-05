from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import json
import re
import sqlite3
import uuid


MEMORY_SCOPES = ("personal", "project")
MEMORY_KINDS = ("fact", "preference", "decision", "task", "note")
_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё_-]{3,}", re.UNICODE)


class MemoryError(ValueError):
    pass


class SayuriMemory:
    """Локальная долговременная память Sayuri с жёстким разделением областей."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA synchronous = NORMAL")
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL CHECK(scope IN ('personal', 'project')),
                    kind TEXT NOT NULL CHECK(kind IN ('fact', 'preference', 'decision', 'task', 'note')),
                    content TEXT NOT NULL,
                    normalized TEXT NOT NULL,
                    importance INTEGER NOT NULL CHECK(importance BETWEEN 1 AND 5),
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(scope, kind, normalized)
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_scope_active ON memory_entries(scope, active, updated_at)"
            )

    @staticmethod
    def _validate_scope(scope: str) -> str:
        value = (scope or "").strip().lower()
        if value not in MEMORY_SCOPES:
            raise MemoryError("Область памяти должна быть personal или project.")
        return value

    @staticmethod
    def _validate_kind(kind: str) -> str:
        value = (kind or "").strip().lower()
        if value not in MEMORY_KINDS:
            raise MemoryError("Неизвестный тип памяти.")
        return value

    @staticmethod
    def _normalize(content: str) -> tuple[str, str]:
        text = " ".join((content or "").strip().split())
        if not text:
            raise MemoryError("Память не может быть пустой.")
        if len(text) > 8000:
            raise MemoryError("Одна запись памяти не должна превышать 8000 символов.")
        normalized = text.casefold()
        return text, normalized

    @staticmethod
    def _importance(value: Any) -> int:
        try:
            importance = int(value)
        except (TypeError, ValueError) as exc:
            raise MemoryError("Важность памяти должна быть числом от 1 до 5.") from exc
        if not 1 <= importance <= 5:
            raise MemoryError("Важность памяти должна быть от 1 до 5.")
        return importance

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "scope": row["scope"],
            "kind": row["kind"],
            "content": row["content"],
            "importance": row["importance"],
            "source": row["source"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_used_at": row["last_used_at"],
            "use_count": row["use_count"],
        }

    def add(
        self,
        *,
        scope: str,
        kind: str,
        content: str,
        importance: int = 3,
        source: str = "manual",
    ) -> dict[str, Any]:
        scope = self._validate_scope(scope)
        kind = self._validate_kind(kind)
        text, normalized = self._normalize(content)
        importance = self._importance(importance)
        source = (source or "manual").strip()[:80] or "manual"
        now = self._now()
        entry_id = uuid.uuid4().hex

        with self._connect() as db:
            existing = db.execute(
                """
                SELECT * FROM memory_entries
                WHERE scope = ? AND kind = ? AND normalized = ?
                """,
                (scope, kind, normalized),
            ).fetchone()
            if existing:
                db.execute(
                    """
                    UPDATE memory_entries
                    SET content = ?, importance = MAX(importance, ?), source = ?,
                        updated_at = ?, active = 1
                    WHERE id = ?
                    """,
                    (text, importance, source, now, existing["id"]),
                )
                row = db.execute("SELECT * FROM memory_entries WHERE id = ?", (existing["id"],)).fetchone()
                return self._row(row)

            db.execute(
                """
                INSERT INTO memory_entries(
                    id, scope, kind, content, normalized, importance, source,
                    created_at, updated_at, active
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (entry_id, scope, kind, text, normalized, importance, source, now, now),
            )
            row = db.execute("SELECT * FROM memory_entries WHERE id = ?", (entry_id,)).fetchone()
            return self._row(row)

    def delete(self, entry_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE memory_entries SET active = 0, updated_at = ? WHERE id = ? AND active = 1",
                (self._now(), entry_id),
            )
            return cursor.rowcount > 0

    def list(
        self,
        *,
        scope: str | None = None,
        query: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 300)
        params: list[Any] = []
        clauses = ["active = 1"]
        if scope:
            clauses.append("scope = ?")
            params.append(self._validate_scope(scope))
        if query.strip():
            clauses.append("normalized LIKE ?")
            params.append(f"%{query.strip().casefold()}%")
        params.append(safe_limit)
        sql = f"""
            SELECT * FROM memory_entries
            WHERE {' AND '.join(clauses)}
            ORDER BY importance DESC, updated_at DESC
            LIMIT ?
        """
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._row(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT scope, COUNT(*) AS count, COALESCE(SUM(use_count), 0) AS uses
                FROM memory_entries
                WHERE active = 1
                GROUP BY scope
                """
            ).fetchall()
        counts = {scope: {"count": 0, "uses": 0} for scope in MEMORY_SCOPES}
        for row in rows:
            counts[row["scope"]] = {"count": row["count"], "uses": row["uses"]}
        return {
            "status": "готово",
            "database": str(self.path),
            "total": sum(item["count"] for item in counts.values()),
            "personal": counts["personal"],
            "project": counts["project"],
        }

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {match.group(0).casefold() for match in _TOKEN_RE.finditer(text or "")}

    def search(
        self,
        query: str,
        *,
        scopes: Iterable[str] = MEMORY_SCOPES,
        limit: int = 10,
    ) -> dict[str, list[dict[str, Any]]]:
        valid_scopes = tuple(dict.fromkeys(self._validate_scope(scope) for scope in scopes))
        tokens = self._tokens(query)
        if not tokens:
            return {scope: [] for scope in valid_scopes}

        placeholders = ",".join("?" for _ in valid_scopes)
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM memory_entries
                WHERE active = 1 AND scope IN ({placeholders})
                ORDER BY updated_at DESC
                LIMIT 1000
                """,
                valid_scopes,
            ).fetchall()

            scored: list[tuple[float, sqlite3.Row]] = []
            for row in rows:
                haystack = row["normalized"]
                matched = sum(1 for token in tokens if token in haystack)
                if matched <= 0:
                    continue
                score = matched * 3.0 + float(row["importance"]) * 0.35
                scored.append((score, row))
            scored.sort(key=lambda item: (item[0], item[1]["updated_at"]), reverse=True)
            selected = scored[: min(max(int(limit), 1), 30)]
            now = self._now()
            if selected:
                db.executemany(
                    """
                    UPDATE memory_entries
                    SET last_used_at = ?, use_count = use_count + 1
                    WHERE id = ?
                    """,
                    [(now, row["id"]) for _, row in selected],
                )

        result = {scope: [] for scope in valid_scopes}
        for score, row in selected:
            item = self._row(row)
            item["relevance"] = round(score, 3)
            result[row["scope"]].append(item)
        return result

    def capture_explicit(self, message: str) -> dict[str, Any] | None:
        text = (message or "").strip()
        patterns = (
            (r"^запомни\s+(?:это\s+)?лично\s*[:—-]\s*(.+)$", "personal"),
            (r"^запомни\s+(?:это\s+)?(?:в|для)\s+проект(?:е|а)?\s*[:—-]\s*(.+)$", "project"),
            (r"^запомни\s*[:—-]\s*(.+)$", "personal"),
            (r"^remember\s+personal\s*[:—-]\s*(.+)$", "personal"),
            (r"^remember\s+project\s*[:—-]\s*(.+)$", "project"),
        )
        for pattern, scope in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            content = match.group(1).strip()
            if not content:
                return None
            return self.add(
                scope=scope,
                kind="note",
                content=content,
                importance=4,
                source="explicit_chat",
            )
        return None

    def export_context(self, query: str, limit: int = 10) -> dict[str, Any]:
        found = self.search(query, limit=limit)
        return {
            "personal": [
                {
                    "kind": item["kind"],
                    "content": item["content"],
                    "importance": item["importance"],
                }
                for item in found.get("personal", [])
            ],
            "project": [
                {
                    "kind": item["kind"],
                    "content": item["content"],
                    "importance": item["importance"],
                }
                for item in found.get("project", [])
            ],
        }
