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
            columns = {row["name"] for row in db.execute("PRAGMA table_info(memory_entries)").fetchall()}
            if "source_context_json" not in columns:
                db.execute("ALTER TABLE memory_entries ADD COLUMN source_context_json TEXT")
            if "confidence" not in columns:
                db.execute("ALTER TABLE memory_entries ADD COLUMN confidence REAL")
            if "supersedes_id" not in columns:
                db.execute("ALTER TABLE memory_entries ADD COLUMN supersedes_id TEXT")
            if "retention_score" not in columns:
                db.execute("ALTER TABLE memory_entries ADD COLUMN retention_score REAL NOT NULL DEFAULT 1.0")
            if "retention_evaluated_at" not in columns:
                db.execute("ALTER TABLE memory_entries ADD COLUMN retention_evaluated_at TEXT")
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
            "source_context": (
                json.loads(row["source_context_json"])
                if "source_context_json" in row.keys() and row["source_context_json"]
                else None
            ),
            "confidence": row["confidence"] if "confidence" in row.keys() else None,
            "supersedes_id": row["supersedes_id"] if "supersedes_id" in row.keys() else None,
            "retention_score": (
                float(row["retention_score"])
                if "retention_score" in row.keys() and row["retention_score"] is not None
                else 1.0
            ),
            "retention_evaluated_at": (
                row["retention_evaluated_at"]
                if "retention_evaluated_at" in row.keys()
                else None
            ),
        }

    def add(
        self,
        *,
        scope: str,
        kind: str,
        content: str,
        importance: int = 3,
        source: str = "manual",
        source_context: dict[str, Any] | None = None,
        confidence: float | None = None,
        supersedes_id: str | None = None,
    ) -> dict[str, Any]:
        scope = self._validate_scope(scope)
        kind = self._validate_kind(kind)
        text, normalized = self._normalize(content)
        importance = self._importance(importance)
        source = (source or "manual").strip()[:80] or "manual"
        now = self._now()
        entry_id = uuid.uuid4().hex
        context_json = (
            json.dumps(source_context, ensure_ascii=False, separators=(",", ":"))[:16000]
            if isinstance(source_context, dict)
            else None
        )
        safe_confidence = None if confidence is None else max(0.0, min(float(confidence), 1.0))
        safe_supersedes = supersedes_id.strip() if isinstance(supersedes_id, str) and supersedes_id.strip() else None

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
                        source_context_json = COALESCE(?, source_context_json),
                        confidence = COALESCE(?, confidence),
                        supersedes_id = COALESCE(?, supersedes_id),
                        updated_at = ?, active = 1
                    WHERE id = ?
                    """,
                    (
                        text,
                        importance,
                        source,
                        context_json,
                        safe_confidence,
                        safe_supersedes,
                        now,
                        existing["id"],
                    ),
                )
                row = db.execute("SELECT * FROM memory_entries WHERE id = ?", (existing["id"],)).fetchone()
                return self._row(row)

            db.execute(
                """
                INSERT INTO memory_entries(
                    id, scope, kind, content, normalized, importance, source,
                    created_at, updated_at, active, source_context_json, confidence, supersedes_id
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    entry_id,
                    scope,
                    kind,
                    text,
                    normalized,
                    importance,
                    source,
                    now,
                    now,
                    context_json,
                    safe_confidence,
                    safe_supersedes,
                ),
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

    def get(self, entry_id: str, *, include_inactive: bool = False) -> dict[str, Any] | None:
        sql = "SELECT * FROM memory_entries WHERE id = ?"
        params: tuple[Any, ...] = (entry_id,)
        if not include_inactive:
            sql += " AND active = 1"
        with self._connect() as db:
            row = db.execute(sql, params).fetchone()
        return self._row(row) if row is not None else None

    def set_retention(self, entry_id: str, score: float) -> dict[str, Any] | None:
        safe_score = max(0.0, min(float(score), 1.0))
        now = self._now()
        with self._connect() as db:
            db.execute(
                """
                UPDATE memory_entries
                SET retention_score = ?, retention_evaluated_at = ?
                WHERE id = ? AND active = 1
                """,
                (safe_score, now, entry_id),
            )
            row = db.execute(
                "SELECT * FROM memory_entries WHERE id = ? AND active = 1",
                (entry_id,),
            ).fetchone()
        return self._row(row) if row is not None else None

    def restore(self, entry_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE memory_entries SET active = 1, updated_at = ? WHERE id = ? AND active = 0",
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

    def scan_active(self, *, limit: int = 5000) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 5000)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM memory_entries
                WHERE active = 1
                ORDER BY importance DESC, updated_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
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
        with self._connect() as db:
            stale = db.execute(
                """
                SELECT COUNT(*) AS count
                FROM memory_entries
                WHERE active = 1 AND retention_score < 0.30
                """
            ).fetchone()["count"]
        return {
            "status": "готово",
            "database": str(self.path),
            "total": sum(item["count"] for item in counts.values()),
            "personal": counts["personal"],
            "project": counts["project"],
            "stale_candidates": stale,
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

    def mark_used(self, entry_ids: Iterable[str]) -> None:
        ids = [entry_id for entry_id in dict.fromkeys(entry_ids) if isinstance(entry_id, str) and entry_id]
        if not ids:
            return
        now = self._now()
        with self._connect() as db:
            db.executemany(
                """
                UPDATE memory_entries
                SET last_used_at = ?, use_count = use_count + 1
                WHERE id = ? AND active = 1
                """,
                [(now, entry_id) for entry_id in ids],
            )

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
