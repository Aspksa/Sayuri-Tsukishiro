from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from typing import Any, Iterator

from .errors import DatabaseError


SCHEMA_VERSION = 2


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        try:
            with self.session() as db:
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS system_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        level TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        message TEXT NOT NULL,
                        details_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS error_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        code TEXT NOT NULL,
                        message TEXT NOT NULL,
                        context_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS system_settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (str(SCHEMA_VERSION),),
                )
                self._translate_legacy_events(db)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Не удалось инициализировать SQLite: {exc}") from exc

    @staticmethod
    def _translate_legacy_events(db: sqlite3.Connection) -> None:
        translations = (
            ("Запуск", "Ядро готово", "core.start", "Sayuri Core initialized"),
            ("Сайт", "Сервер готов", "web.ready", "Local web server ready"),
            ("Остановка", "Ядро остановлено", "core.stop", "Sayuri Core stopped"),
        )
        for new_type, new_message, old_type, old_message in translations:
            db.execute(
                """
                UPDATE system_events
                SET event_type = ?, message = ?
                WHERE event_type = ? AND message = ?
                """,
                (new_type, new_message, old_type, old_message),
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def ensure_settings(self, defaults: dict[str, Any]) -> None:
        now = self._now()
        with self.session() as db:
            for key, value in defaults.items():
                db.execute(
                    """
                    INSERT INTO system_settings(key, value_json, updated_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(key) DO NOTHING
                    """,
                    (key, json.dumps(value, ensure_ascii=False), now),
                )

    def read_settings(self) -> dict[str, Any]:
        with self.session() as db:
            rows = db.execute(
                "SELECT key, value_json FROM system_settings ORDER BY key"
            ).fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def write_settings(self, changes: dict[str, Any]) -> None:
        now = self._now()
        with self.session() as db:
            for key, value in changes.items():
                db.execute(
                    """
                    INSERT INTO system_settings(key, value_json, updated_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(value, ensure_ascii=False), now),
                )

    def record_event(
        self,
        event_type: str,
        message: str,
        *,
        level: str = "INFO",
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.session() as db:
            db.execute(
                "INSERT INTO system_events(created_at, level, event_type, message, details_json) VALUES(?, ?, ?, ?, ?)",
                (self._now(), level, event_type, message, json.dumps(details or {}, ensure_ascii=False)),
            )

    def record_error(self, code: str, message: str, context: dict[str, Any] | None = None) -> None:
        with self.session() as db:
            db.execute(
                "INSERT INTO error_events(created_at, code, message, context_json) VALUES(?, ?, ?, ?)",
                (self._now(), code, message, json.dumps(context or {}, ensure_ascii=False)),
            )

    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 100)
        with self.session() as db:
            rows = db.execute(
                "SELECT id, created_at, level, event_type, message, details_json FROM system_events ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            result.append(item)
        return result

    def health(self) -> dict[str, Any]:
        with self.session() as db:
            db.execute("SELECT 1").fetchone()
            schema = db.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            events = db.execute("SELECT COUNT(*) AS count FROM system_events").fetchone()["count"]
            errors = db.execute("SELECT COUNT(*) AS count FROM error_events").fetchone()["count"]
            settings = db.execute("SELECT COUNT(*) AS count FROM system_settings").fetchone()["count"]
        return {
            "status": "готово",
            "status_code": "ready",
            "engine": "SQLite",
            "schema_version": int(schema["value"]) if schema else 0,
            "events": events,
            "errors": errors,
            "settings": settings,
            "size_bytes": self.path.stat().st_size if self.path.exists() else 0,
            "path": str(self.path),
        }
