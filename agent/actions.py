from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import re
import sqlite3
import uuid


ACTION_TTL_MINUTES = 10

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "disk.create_folder": {
        "label": "Создать папку",
        "risk": "low",
        "confirmation_required": True,
    },
    "disk.set_favorite": {
        "label": "Изменить избранное",
        "risk": "low",
        "confirmation_required": True,
    },
    "disk.trash_current": {
        "label": "Переместить в корзину",
        "risk": "medium",
        "confirmation_required": True,
    },
    "disk.move_current": {
        "label": "Переместить объект",
        "risk": "medium",
        "confirmation_required": True,
    },
    "memory.remember": {
        "label": "Сохранить решение в память",
        "risk": "low",
        "confirmation_required": True,
    },
}


class ActionError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


class SayuriActionBroker:
    """Локальный брокер действий: планирование -> подтверждение -> однократное выполнение."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

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
                CREATE TABLE IF NOT EXISTS sayuri_actions (
                    id TEXT PRIMARY KEY,
                    tool TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    result_json TEXT,
                    error_message TEXT
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_sayuri_actions_status ON sayuri_actions(status, created_at)"
            )

    @staticmethod
    def tools() -> list[dict[str, Any]]:
        return [
            {"id": tool_id, **definition}
            for tool_id, definition in TOOL_DEFINITIONS.items()
        ]

    @staticmethod
    def _payload_json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        result = None
        if row["result_json"]:
            try:
                result = json.loads(row["result_json"])
            except json.JSONDecodeError:
                result = None
        return {
            "id": row["id"],
            "tool": row["tool"],
            "title": row["title"],
            "description": row["description"],
            "payload": json.loads(row["payload_json"]),
            "risk": row["risk"],
            "status": row["status"],
            "confirmation_required": True,
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "result": result,
            "error": row["error_message"],
        }

    def _create(
        self,
        *,
        tool: str,
        title: str,
        description: str,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if tool not in TOOL_DEFINITIONS:
            raise ActionError("Инструмент не разрешён.")
        payload_json = self._payload_json(payload)
        digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        now = _utcnow()
        action_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO sayuri_actions(
                    id, tool, title, description, payload_json, payload_sha256,
                    context_json, risk, status, created_at, expires_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    action_id,
                    tool,
                    title[:160],
                    description[:1000],
                    payload_json,
                    digest,
                    json.dumps(context, ensure_ascii=False, separators=(",", ":"))[:16000],
                    TOOL_DEFINITIONS[tool]["risk"],
                    _iso(now),
                    _iso(now + timedelta(minutes=ACTION_TTL_MINUTES)),
                ),
            )
            row = db.execute("SELECT * FROM sayuri_actions WHERE id = ?", (action_id,)).fetchone()
        return self._public(row)

    @staticmethod
    def _current_item(context: dict[str, Any]) -> dict[str, str] | None:
        current = context.get("current_document")
        if not isinstance(current, dict):
            return None
        object_id = current.get("id")
        kind = current.get("kind")
        name = current.get("name")
        if not isinstance(object_id, str) or not object_id:
            return None
        if kind not in {"file", "folder"}:
            return None
        return {
            "id": object_id,
            "kind": kind,
            "name": name if isinstance(name, str) and name else "текущий объект",
        }

    @staticmethod
    def _clean_name(value: str) -> str:
        text = value.strip().strip('"').strip("'").strip("«»").strip()
        text = re.sub(r"\s+", " ", text)
        return text

    def plan(self, text: str, context: Any = None) -> dict[str, Any] | None:
        message = " ".join((text or "").strip().split())
        if not message:
            return None
        safe_context = context if isinstance(context, dict) else {}
        current = self._current_item(safe_context)

        match = re.match(
            r"^(?:sayuri[,\s]*)?(?:создай|создать)\s+папк(?:у|а)\s+(.+)$",
            message,
            flags=re.IGNORECASE,
        )
        if match:
            name = self._clean_name(match.group(1))
            if not name or len(name) > 255:
                raise ActionError("Некорректное имя папки.")
            disk_context = safe_context.get("disk") if isinstance(safe_context.get("disk"), dict) else {}
            parent_id = disk_context.get("folder_id") if safe_context.get("view") == "disk" else None
            location = "в текущей папке Диска" if parent_id else "в корне Диска Sayuri"
            return self._create(
                tool="disk.create_folder",
                title=f"Создать папку «{name}»",
                description=f"Sayuri создаст папку «{name}» {location}.",
                payload={"name": name, "parent_id": parent_id},
                context=safe_context,
            )

        if current:
            match = re.match(
                r"^(?:sayuri[,\s]*)?(?:добавь|добавить)\s+(?:этот|текущий)?\s*(?:документ|файл|объект)?\s*в\s+избранное$",
                message,
                flags=re.IGNORECASE,
            )
            if match:
                return self._create(
                    tool="disk.set_favorite",
                    title=f"Добавить «{current['name']}» в избранное",
                    description="Изменится только флаг избранного у текущего объекта.",
                    payload={"item": {"id": current["id"], "kind": current["kind"]}, "favorite": True},
                    context=safe_context,
                )

            match = re.match(
                r"^(?:sayuri[,\s]*)?(?:убери|убрать)\s+(?:этот|текущий)?\s*(?:документ|файл|объект)?\s*из\s+избранного$",
                message,
                flags=re.IGNORECASE,
            )
            if match:
                return self._create(
                    tool="disk.set_favorite",
                    title=f"Убрать «{current['name']}» из избранного",
                    description="Изменится только флаг избранного у текущего объекта.",
                    payload={"item": {"id": current["id"], "kind": current["kind"]}, "favorite": False},
                    context=safe_context,
                )

            match = re.match(
                r"^(?:sayuri[,\s]*)?(?:удали|удалить|перемести|переместить)\s+(?:этот|текущий)?\s*(?:документ|файл|объект)?\s*(?:в\s+корзину)?$",
                message,
                flags=re.IGNORECASE,
            )
            if match and ("удал" in message.casefold() or "корзин" in message.casefold()):
                return self._create(
                    tool="disk.trash_current",
                    title=f"Переместить «{current['name']}» в корзину",
                    description="Объект будет перемещён в корзину. Это можно восстановить обычными средствами Диска Sayuri.",
                    payload={"item": {"id": current["id"], "kind": current["kind"]}},
                    context=safe_context,
                )

            match = re.match(
                r"^(?:sayuri[,\s]*)?(?:перемести|переместить)\s+(?:этот|текущий)?\s*(?:документ|файл|объект)?\s+в\s+папк(?:у|а)\s+(.+)$",
                message,
                flags=re.IGNORECASE,
            )
            if match:
                destination = self._clean_name(match.group(1))
                if not destination:
                    raise ActionError("Не указана папка назначения.")
                return self._create(
                    tool="disk.move_current",
                    title=f"Переместить «{current['name']}»",
                    description=f"Текущий объект будет перемещён в папку «{destination}».",
                    payload={
                        "item": {"id": current["id"], "kind": current["kind"]},
                        "destination": destination,
                    },
                    context=safe_context,
                )

        match = re.match(
            r"^(?:sayuri[,\s]*)?запомни\s+(?:это\s+)?как\s+решение\s+проекта\s*[:—-]\s*(.+)$",
            message,
            flags=re.IGNORECASE,
        )
        if match:
            memory_text = match.group(1).strip()
            if not memory_text:
                raise ActionError("Не указано решение проекта.")
            return self._create(
                tool="memory.remember",
                title="Сохранить решение проекта",
                description=f"В проектную память будет добавлено решение: «{memory_text[:220]}»",
                payload={
                    "scope": "project",
                    "kind": "decision",
                    "content": memory_text,
                    "importance": 5,
                },
                context=safe_context,
            )

        return None

    def get(self, action_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM sayuri_actions WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            raise ActionError("Действие не найдено.")
        return self._public(row)

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 100)
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM sayuri_actions ORDER BY created_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self._public(row) for row in rows]

    def begin(self, action_id: str) -> dict[str, Any]:
        now = _utcnow()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sayuri_actions WHERE id = ?", (action_id,)).fetchone()
            if row is None:
                raise ActionError("Действие не найдено.")
            if row["status"] != "pending":
                return self._public(row)
            expires = datetime.fromisoformat(row["expires_at"])
            if expires <= now:
                db.execute(
                    "UPDATE sayuri_actions SET status = 'expired', finished_at = ? WHERE id = ?",
                    (_iso(now), action_id),
                )
                row = db.execute("SELECT * FROM sayuri_actions WHERE id = ?", (action_id,)).fetchone()
                return self._public(row)
            payload_json = row["payload_json"]
            digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            if digest != row["payload_sha256"]:
                db.execute(
                    """
                    UPDATE sayuri_actions
                    SET status = 'failed', finished_at = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (_iso(now), "Контрольная сумма действия не совпала.", action_id),
                )
                row = db.execute("SELECT * FROM sayuri_actions WHERE id = ?", (action_id,)).fetchone()
                return self._public(row)
            db.execute(
                "UPDATE sayuri_actions SET status = 'executing', started_at = ? WHERE id = ?",
                (_iso(now), action_id),
            )
            row = db.execute("SELECT * FROM sayuri_actions WHERE id = ?", (action_id,)).fetchone()
        return self._public(row)

    def complete(self, action_id: str, result: dict[str, Any]) -> dict[str, Any]:
        now = _iso(_utcnow())
        with self._connect() as db:
            db.execute(
                """
                UPDATE sayuri_actions
                SET status = 'completed', finished_at = ?, result_json = ?, error_message = NULL
                WHERE id = ? AND status = 'executing'
                """,
                (now, json.dumps(result, ensure_ascii=False, separators=(",", ":")), action_id),
            )
            row = db.execute("SELECT * FROM sayuri_actions WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            raise ActionError("Действие не найдено.")
        return self._public(row)

    def fail(self, action_id: str, message: str) -> dict[str, Any]:
        now = _iso(_utcnow())
        with self._connect() as db:
            db.execute(
                """
                UPDATE sayuri_actions
                SET status = 'failed', finished_at = ?, error_message = ?
                WHERE id = ? AND status = 'executing'
                """,
                (message[:1000], now, action_id),
            )
            row = db.execute("SELECT * FROM sayuri_actions WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            raise ActionError("Действие не найдено.")
        return self._public(row)

    def cancel(self, action_id: str) -> dict[str, Any]:
        now = _iso(_utcnow())
        with self._connect() as db:
            db.execute(
                """
                UPDATE sayuri_actions
                SET status = 'cancelled', finished_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, action_id),
            )
            row = db.execute("SELECT * FROM sayuri_actions WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            raise ActionError("Действие не найдено.")
        return self._public(row)
