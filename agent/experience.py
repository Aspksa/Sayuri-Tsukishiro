from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import sqlite3
import uuid


class ExperienceError(ValueError):
    pass


class ExperienceStore:
    """Локальная память опыта Sayuri: исходы стратегий без сохранения полного диалога."""

    POSITIVE_OUTCOMES = {"success", "accepted", "useful", "corrected_success"}
    NEGATIVE_OUTCOMES = {"failure", "rejected", "not_useful", "corrected_failure"}
    NEUTRAL_OUTCOMES = {"produced", "cancelled", "expired"}

    def __init__(self, path: Path):
        self.path = path
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
                CREATE TABLE IF NOT EXISTS experience_events (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    reward REAL NOT NULL,
                    source TEXT NOT NULL,
                    subject_id TEXT,
                    context_json TEXT,
                    details_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_experience_strategy ON experience_events(strategy, updated_at)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_experience_category ON experience_events(category, updated_at)"
            )

    @staticmethod
    def _clean_key(value: str, *, label: str, max_length: int = 120) -> str:
        text = (value or "").strip()
        if not text:
            raise ExperienceError(f"{label} не может быть пустым.")
        return text[:max_length]

    @classmethod
    def _reward_for(cls, outcome: str) -> float:
        if outcome in cls.POSITIVE_OUTCOMES:
            return 1.0
        if outcome in cls.NEGATIVE_OUTCOMES:
            return -1.0
        if outcome in cls.NEUTRAL_OUTCOMES:
            return 0.0
        raise ExperienceError("Неизвестный исход опыта.")

    @staticmethod
    def _json(value: Any, max_length: int = 16000) -> str | None:
        if value is None:
            return None
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ExperienceError("Контекст опыта должен быть JSON-совместимым.") from exc
        return encoded[:max_length]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        def decode(value: str | None) -> Any:
            if not value:
                return None
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None

        return {
            "id": row["id"],
            "category": row["category"],
            "strategy": row["strategy"],
            "outcome": row["outcome"],
            "reward": row["reward"],
            "source": row["source"],
            "subject_id": row["subject_id"],
            "context": decode(row["context_json"]),
            "details": decode(row["details_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def fingerprint(*parts: str) -> str:
        raw = "\x1f".join(str(part or "") for part in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def record(
        self,
        *,
        category: str,
        strategy: str,
        outcome: str,
        source: str,
        subject_id: str | None = None,
        context: Any = None,
        details: Any = None,
        fingerprint: str | None = None,
    ) -> dict[str, Any]:
        category = self._clean_key(category, label="Категория")
        strategy = self._clean_key(strategy, label="Стратегия")
        source = self._clean_key(source, label="Источник")
        outcome = (outcome or "").strip().lower()
        reward = self._reward_for(outcome)
        subject = (subject_id or "").strip()[:160] or None
        fp = fingerprint or self.fingerprint(category, strategy, source, subject or "", outcome)
        now = self._now()
        event_id = uuid.uuid4().hex
        context_json = self._json(context)
        details_json = self._json(details)

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO experience_events(
                    id, fingerprint, category, strategy, outcome, reward, source,
                    subject_id, context_json, details_json, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    category=excluded.category,
                    strategy=excluded.strategy,
                    outcome=excluded.outcome,
                    reward=excluded.reward,
                    source=excluded.source,
                    subject_id=excluded.subject_id,
                    context_json=excluded.context_json,
                    details_json=excluded.details_json,
                    updated_at=excluded.updated_at
                """,
                (
                    event_id,
                    fp,
                    category,
                    strategy,
                    outcome,
                    reward,
                    source,
                    subject,
                    context_json,
                    details_json,
                    now,
                    now,
                ),
            )
            row = db.execute(
                "SELECT * FROM experience_events WHERE fingerprint = ?",
                (fp,),
            ).fetchone()
        return self._row(row)

    def record_chat_response(self, response_id: str, context: Any = None) -> dict[str, Any]:
        return self.record(
            category="chat",
            strategy="chat.deepseek_v4_flash",
            outcome="produced",
            source="chat_runtime",
            subject_id=response_id,
            context=context,
            fingerprint=self.fingerprint("chat_response", response_id),
        )

    def record_chat_feedback(self, response_id: str, rating: str, context: Any = None) -> dict[str, Any]:
        normalized = (rating or "").strip().lower()
        if normalized not in {"useful", "not_useful"}:
            raise ExperienceError("Оценка ответа должна быть useful или not_useful.")
        return self.record(
            category="chat_feedback",
            strategy="chat.deepseek_v4_flash",
            outcome=normalized,
            source="user_feedback",
            subject_id=response_id,
            context=context,
            fingerprint=self.fingerprint("chat_feedback", response_id),
        )

    def record_action(self, action_id: str, tool: str, status: str, details: Any = None) -> dict[str, Any]:
        outcome_map = {
            "completed": "success",
            "failed": "failure",
            "cancelled": "cancelled",
            "expired": "expired",
        }
        outcome = outcome_map.get(status)
        if not outcome:
            raise ExperienceError("Нельзя записать незавершённое действие как опыт.")
        return self.record(
            category="action",
            strategy=f"tool.{tool}",
            outcome=outcome,
            source="action_broker",
            subject_id=action_id,
            details=details,
            fingerprint=self.fingerprint("action", action_id),
        )

    def record_memory_review(
        self,
        candidate_id: str,
        *,
        scope: str,
        kind: str,
        decision: str,
        relation: str,
    ) -> dict[str, Any]:
        outcome = "accepted" if decision == "accept" else "rejected"
        return self.record(
            category="memory_review",
            strategy=f"memory.{scope}.{kind}",
            outcome=outcome,
            source="memory_guardian",
            subject_id=candidate_id,
            details={"relation": relation},
            fingerprint=self.fingerprint("memory_candidate", candidate_id),
        )

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 200)
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM experience_events ORDER BY updated_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def strategy_stats(self, strategy: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        clause = ""
        if strategy:
            clause = "WHERE strategy = ?"
            params.append(strategy)
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT
                    strategy,
                    COUNT(*) AS total,
                    SUM(CASE WHEN reward > 0 THEN 1 ELSE 0 END) AS positive,
                    SUM(CASE WHEN reward < 0 THEN 1 ELSE 0 END) AS negative,
                    SUM(CASE WHEN reward = 0 THEN 1 ELSE 0 END) AS neutral,
                    COALESCE(SUM(reward), 0) AS reward_sum,
                    MAX(updated_at) AS last_seen_at
                FROM experience_events
                {clause}
                GROUP BY strategy
                ORDER BY (SUM(CASE WHEN reward != 0 THEN 1 ELSE 0 END)) DESC, last_seen_at DESC
                """,
                params,
            ).fetchall()

        result = []
        for row in rows:
            meaningful = int(row["positive"] or 0) + int(row["negative"] or 0)
            # Beta(1,1) сглаживание: маленькая выборка не даёт экстремальной уверенности.
            success_rate = (int(row["positive"] or 0) + 1) / (meaningful + 2)
            result.append({
                "strategy": row["strategy"],
                "total": row["total"],
                "positive": row["positive"] or 0,
                "negative": row["negative"] or 0,
                "neutral": row["neutral"] or 0,
                "reward_sum": row["reward_sum"] or 0,
                "meaningful": meaningful,
                "success_rate": round(success_rate, 4),
                "evidence_strength": round(min(1.0, meaningful / 12.0), 4),
                "last_seen_at": row["last_seen_at"],
            })
        return result

    def confidence_adjustment(self, strategy: str) -> float:
        rows = self.strategy_stats(strategy)
        if not rows:
            return 0.0
        stats = rows[0]
        if stats["meaningful"] < 3:
            return 0.0
        centered = stats["success_rate"] - 0.5
        strength = stats["evidence_strength"]
        return round(max(-0.08, min(0.08, centered * 0.16 * strength)), 4)

    def stats(self) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN reward > 0 THEN 1 ELSE 0 END) AS positive,
                    SUM(CASE WHEN reward < 0 THEN 1 ELSE 0 END) AS negative,
                    SUM(CASE WHEN reward = 0 THEN 1 ELSE 0 END) AS neutral
                FROM experience_events
                """
            ).fetchone()
        strategies = self.strategy_stats()
        return {
            "status": "готово",
            "total": row["total"] or 0,
            "positive": row["positive"] or 0,
            "negative": row["negative"] or 0,
            "neutral": row["neutral"] or 0,
            "learned_strategies": sum(1 for item in strategies if item["meaningful"] >= 3),
            "strategies": strategies[:20],
            "database": str(self.path),
        }
