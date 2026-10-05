from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import re
import sqlite3
import uuid

from .memory import MEMORY_KINDS, MEMORY_SCOPES, SayuriMemory


_CANDIDATE_STATUSES = {"pending", "accepted", "rejected", "duplicate", "conflict", "auto_saved"}
_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё_-]{3,}", re.UNICODE)
_NEGATION = {"не", "нет", "нельзя", "убрать", "отказаться", "без"}


class MemoryIntelligenceError(ValueError):
    pass


class MemoryIntelligence:
    """Детерминированный Memory Guardian: кандидаты, дубли, конфликты и настройки автоматизации."""

    DEFAULT_SETTINGS = {
        "candidate_generation": True,
        "conflict_detection": True,
        "context_linking": True,
        "auto_save_high_confidence": False,
        "auto_save_threshold": 0.96,
    }

    def __init__(self, path: Path, memory: SayuriMemory):
        self.path = path
        self.memory = memory
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

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
                CREATE TABLE IF NOT EXISTS memory_candidates (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    normalized TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    importance INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_context_json TEXT,
                    relation TEXT NOT NULL,
                    related_memory_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_candidates_status ON memory_candidates(status, created_at)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_intelligence_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            now = self._now()
            for key, value in self.DEFAULT_SETTINGS.items():
                db.execute(
                    """
                    INSERT OR IGNORE INTO memory_intelligence_settings(key, value_json, updated_at)
                    VALUES(?, ?, ?)
                    """,
                    (key, json.dumps(value), now),
                )

    def settings(self) -> dict[str, Any]:
        result = dict(self.DEFAULT_SETTINGS)
        with self._connect() as db:
            rows = db.execute(
                "SELECT key, value_json FROM memory_intelligence_settings"
            ).fetchall()
        for row in rows:
            if row["key"] not in result:
                continue
            try:
                result[row["key"]] = json.loads(row["value_json"])
            except json.JSONDecodeError:
                pass
        return result

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = set(self.DEFAULT_SETTINGS)
        unknown = sorted(set(changes) - allowed)
        if unknown:
            raise MemoryIntelligenceError("Неизвестные настройки памяти: " + ", ".join(unknown))

        current = self.settings()
        for key, value in changes.items():
            if key in {"candidate_generation", "conflict_detection", "context_linking", "auto_save_high_confidence"}:
                if type(value) is not bool:
                    raise MemoryIntelligenceError(f"Настройка {key} должна быть логической.")
            elif key == "auto_save_threshold":
                try:
                    value = float(value)
                except (TypeError, ValueError) as exc:
                    raise MemoryIntelligenceError("Порог автосохранения должен быть числом.") from exc
                if value < 0.90 or value > 1.0:
                    raise MemoryIntelligenceError("Порог автосохранения должен быть от 0.90 до 1.00.")
            current[key] = value

        now = self._now()
        with self._connect() as db:
            for key in changes:
                db.execute(
                    """
                    INSERT INTO memory_intelligence_settings(key, value_json, updated_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                    """,
                    (key, json.dumps(current[key]), now),
                )
        return current

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {m.group(0).casefold() for m in _TOKEN_RE.finditer(text or "")}

    @staticmethod
    def _polarity(tokens: set[str]) -> int:
        return -1 if tokens.intersection(_NEGATION) else 1

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join((text or "").strip().split()).casefold()

    @staticmethod
    def _safe_context(context: Any) -> dict[str, Any]:
        if not isinstance(context, dict):
            return {}
        safe: dict[str, Any] = {}
        for key in ("view", "title", "route"):
            value = context.get(key)
            if isinstance(value, str):
                safe[key] = value[:500]
        current = context.get("current_document")
        if isinstance(current, dict):
            safe["current_document"] = {
                key: current.get(key)
                for key in ("id", "name", "kind", "category")
                if isinstance(current.get(key), str)
            }
        disk = context.get("disk")
        if isinstance(disk, dict):
            safe["disk"] = {
                key: disk.get(key)
                for key in ("scope", "folder_id", "search", "selected_count")
                if isinstance(disk.get(key), (str, int)) or disk.get(key) is None
            }
        return safe

    @staticmethod
    def _classify(text: str) -> list[dict[str, Any]]:
        compact = " ".join(text.strip().split())
        lower = compact.casefold()
        if not compact or len(compact) < 8:
            return []
        if re.match(r"^(запомни|remember)\b", lower):
            return []

        candidates: list[dict[str, Any]] = []

        personal_patterns = (
            (r"\bя\s+(?:предпочитаю|люблю|хочу|не хочу)\s+(.+)", "preference", 0.86, 4, "явное личное предпочтение"),
            (r"\bмне\s+(?:нравится|не нравится|удобнее)\s+(.+)", "preference", 0.84, 4, "явное личное предпочтение"),
        )
        for pattern, kind, confidence, importance, reason in personal_patterns:
            match = re.search(pattern, compact, flags=re.IGNORECASE)
            if match:
                candidates.append({
                    "scope": "personal",
                    "kind": kind,
                    "content": compact,
                    "confidence": confidence,
                    "importance": importance,
                    "reason": reason,
                })
                break

        technical_fact_patterns = (
            (r"^версия проекта\s*[:—-]\s*.+$", 0.99, "явно оформленный технический факт"),
            (r"^репозиторий проекта\s*[:—-]\s*.+$", 0.99, "явно оформленный технический факт"),
            (r"^основная ветка\s*[:—-]\s*.+$", 0.98, "явно оформленный технический факт"),
            (r"^модель проекта\s*[:—-]\s*.+$", 0.97, "явно оформленный технический факт"),
        )
        for pattern, confidence, reason in technical_fact_patterns:
            if re.search(pattern, compact, flags=re.IGNORECASE):
                candidates.append({
                    "scope": "project",
                    "kind": "fact",
                    "content": compact,
                    "confidence": confidence,
                    "importance": 4,
                    "reason": reason,
                })
                break

        project_patterns = (
            (r"\b(?:решили|решаем|фиксируем|зафиксировали)\b", "decision", 0.91, 5, "похоже на проектное решение"),
            (r"\b(?:будем использовать|используем только|оставляем только|переходим на)\b", "decision", 0.90, 5, "похоже на архитектурное решение"),
            (r"\b(?:в проекте|для проекта)\b.*\b(?:должен|должна|должно|будет|нужно)\b", "decision", 0.84, 4, "правило или решение проекта"),
            (r"\b(?:надо|нужно|следующий этап|дальше нужно)\b", "task", 0.74, 3, "похоже на проектную задачу"),
        )
        for pattern, kind, confidence, importance, reason in project_patterns:
            if re.search(pattern, compact, flags=re.IGNORECASE):
                candidates.append({
                    "scope": "project",
                    "kind": kind,
                    "content": compact,
                    "confidence": confidence,
                    "importance": importance,
                    "reason": reason,
                })
                break

        if not candidates and (
            "sayuri" in lower
            and any(word in lower for word in ("версия", "модель", "память", "днк", "cloud.ru", "deepseek"))
        ):
            candidates.append({
                "scope": "project",
                "kind": "fact",
                "content": compact,
                "confidence": 0.68,
                "importance": 3,
                "reason": "возможный технический факт проекта",
            })

        return candidates[:2]

    def _relation(self, candidate: dict[str, Any]) -> tuple[str, str | None]:
        existing = self.memory.list(scope=candidate["scope"], limit=300)
        normalized = self._normalize(candidate["content"])
        tokens = self._tokens(candidate["content"])
        polarity = self._polarity(tokens)
        best_overlap = 0.0
        best_id = None
        best_polarity = polarity

        for item in existing:
            if item["kind"] != candidate["kind"]:
                continue
            item_normalized = self._normalize(item["content"])
            if item_normalized == normalized:
                return "duplicate", item["id"]
            item_tokens = self._tokens(item["content"])
            if not tokens or not item_tokens:
                continue
            union = tokens | item_tokens
            overlap = len(tokens & item_tokens) / max(len(union), 1)
            if overlap > best_overlap:
                best_overlap = overlap
                best_id = item["id"]
                best_polarity = self._polarity(item_tokens)

        if best_overlap >= 0.88:
            return "duplicate", best_id
        if self.settings().get("conflict_detection") and best_overlap >= 0.45 and best_polarity != polarity:
            return "conflict", best_id
        return "new", best_id if best_overlap >= 0.35 else None

    def _candidate_row(self, row: sqlite3.Row) -> dict[str, Any]:
        context = None
        if row["source_context_json"]:
            try:
                context = json.loads(row["source_context_json"])
            except json.JSONDecodeError:
                context = None
        return {
            "id": row["id"],
            "scope": row["scope"],
            "kind": row["kind"],
            "content": row["content"],
            "confidence": row["confidence"],
            "importance": row["importance"],
            "reason": row["reason"],
            "source": row["source"],
            "source_context": context,
            "relation": row["relation"],
            "related_memory_id": row["related_memory_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "reviewed_at": row["reviewed_at"],
        }

    def analyze_message(self, message: str, context: Any = None) -> list[dict[str, Any]]:
        settings = self.settings()
        if not settings.get("candidate_generation"):
            return []

        source_context = self._safe_context(context) if settings.get("context_linking") else {}
        proposals = self._classify(message)
        created: list[dict[str, Any]] = []
        now = self._now()

        with self._connect() as db:
            for proposal in proposals:
                if proposal["scope"] not in MEMORY_SCOPES or proposal["kind"] not in MEMORY_KINDS:
                    continue
                normalized = self._normalize(proposal["content"])
                existing_candidate = db.execute(
                    """
                    SELECT * FROM memory_candidates
                    WHERE normalized = ? AND scope = ? AND kind = ?
                      AND status IN ('pending', 'accepted', 'auto_saved', 'duplicate', 'conflict')
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (normalized, proposal["scope"], proposal["kind"]),
                ).fetchone()
                if existing_candidate:
                    created.append(self._candidate_row(existing_candidate))
                    continue

                relation, related_id = self._relation(proposal)
                status = "pending"
                if relation == "duplicate":
                    status = "duplicate"
                elif relation == "conflict":
                    status = "conflict"

                candidate_id = uuid.uuid4().hex
                db.execute(
                    """
                    INSERT INTO memory_candidates(
                        id, scope, kind, content, normalized, confidence, importance,
                        reason, source, source_context_json, relation, related_memory_id,
                        status, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        proposal["scope"],
                        proposal["kind"],
                        proposal["content"],
                        normalized,
                        proposal["confidence"],
                        proposal["importance"],
                        proposal["reason"],
                        "automatic_chat_analysis",
                        json.dumps(source_context, ensure_ascii=False, separators=(",", ":")) if source_context else None,
                        relation,
                        related_id,
                        status,
                        now,
                    ),
                )
                row = db.execute("SELECT * FROM memory_candidates WHERE id = ?", (candidate_id,)).fetchone()
                item = self._candidate_row(row)

                if (
                    status == "pending"
                    and settings.get("auto_save_high_confidence")
                    and proposal["scope"] == "project"
                    and proposal["kind"] == "fact"
                    and proposal["confidence"] >= float(settings.get("auto_save_threshold", 0.96))
                ):
                    memory = self.memory.add(
                        scope=proposal["scope"],
                        kind=proposal["kind"],
                        content=proposal["content"],
                        importance=proposal["importance"],
                        source="memory_intelligence_auto",
                        source_context=source_context,
                        confidence=proposal["confidence"],
                    )
                    db.execute(
                        """
                        UPDATE memory_candidates
                        SET status='auto_saved', reviewed_at=?, related_memory_id=?
                        WHERE id=?
                        """,
                        (now, memory["id"], candidate_id),
                    )
                    row = db.execute("SELECT * FROM memory_candidates WHERE id = ?", (candidate_id,)).fetchone()
                    item = self._candidate_row(row)

                created.append(item)

        return created

    def list_candidates(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 300)
        clauses = []
        params: list[Any] = []
        if status:
            if status not in _CANDIDATE_STATUSES:
                raise MemoryIntelligenceError("Неизвестный статус кандидата памяти.")
            clauses.append("status = ?")
            params.append(status)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(safe_limit)
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM memory_candidates {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._candidate_row(row) for row in rows]

    def review(self, candidate_id: str, decision: str) -> dict[str, Any]:
        decision = (decision or "").strip().lower()
        if decision not in {"accept", "reject"}:
            raise MemoryIntelligenceError("Решение должно быть accept или reject.")

        with self._connect() as db:
            row = db.execute("SELECT * FROM memory_candidates WHERE id = ?", (candidate_id,)).fetchone()
            if row is None:
                raise MemoryIntelligenceError("Кандидат памяти не найден.")
            item = self._candidate_row(row)
            if item["status"] not in {"pending", "conflict"}:
                return item

            now = self._now()
            if decision == "reject":
                db.execute(
                    "UPDATE memory_candidates SET status='rejected', reviewed_at=? WHERE id=?",
                    (now, candidate_id),
                )
            else:
                memory = self.memory.add(
                    scope=item["scope"],
                    kind=item["kind"],
                    content=item["content"],
                    importance=item["importance"],
                    source="memory_intelligence_confirmed",
                    source_context=item["source_context"],
                    confidence=item["confidence"],
                    supersedes_id=item["related_memory_id"] if item["relation"] == "conflict" else None,
                )
                db.execute(
                    """
                    UPDATE memory_candidates
                    SET status='accepted', reviewed_at=?, related_memory_id=?
                    WHERE id=?
                    """,
                    (now, memory["id"], candidate_id),
                )
            row = db.execute("SELECT * FROM memory_candidates WHERE id = ?", (candidate_id,)).fetchone()
        return self._candidate_row(row)

    def stats(self) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS count FROM memory_candidates GROUP BY status"
            ).fetchall()
        counts = {status: 0 for status in _CANDIDATE_STATUSES}
        for row in rows:
            counts[row["status"]] = row["count"]
        return {
            "candidates": counts,
            "pending_review": counts["pending"] + counts["conflict"],
            "settings": self.settings(),
        }
