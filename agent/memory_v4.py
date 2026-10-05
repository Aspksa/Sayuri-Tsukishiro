from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import exp, log1p
from pathlib import Path
from threading import RLock
from typing import Any, Iterable
import hashlib
import json
import re
import sqlite3
import uuid

from .memory import SayuriMemory
from .memory_v3 import MemorySystemV3
from .semantic_memory import SemanticMemoryIndex


class MemorySystemV4Error(ValueError):
    pass


class MemorySystemV4:
    """Memory 4.0: goals/tasks, source trust, utility, causal/failure memory and explainable recall."""

    ENGINE_ID = "memory-v4"
    MAX_SCAN = 5000
    TIERS = {"hot", "warm", "cold"}
    TASK_STATUSES = {"planned", "in_progress", "blocked", "done", "cancelled"}
    GOAL_STATUSES = {"active", "paused", "achieved", "cancelled"}
    QUESTION_STATUSES = {"open", "resolved", "dismissed"}
    SOURCE_BASE_TRUST = {
        "manual": 0.96,
        "explicit_chat": 0.98,
        "memory_intelligence_confirmed": 0.94,
        "memory_intelligence_auto": 0.82,
        "memory_intelligence": 0.86,
        "safe_action": 0.98,
        "user_feedback": 0.98,
        "document_dna": 0.90,
        "document": 0.88,
        "ocr": 0.72,
        "automatic_chat_analysis": 0.74,
        "system": 0.84,
        "unknown": 0.70,
    }

    _SECRET_PATTERNS = (
        re.compile(r"\b(?:api[-_ ]?key|token|парол[ья]|password|secret)\s*[:=]\s*\S{6,}", re.IGNORECASE),
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}\b", re.IGNORECASE),
    )
    _SENSITIVE_PATTERNS = (
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        re.compile(r"(?<!\d)(?:\+7|8)[\s()-]*\d{3}[\s()-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)"),
        re.compile(r"\b(?:паспорт|passport)\s*(?:№|номер|number)?\s*[:#-]?\s*[A-ZА-Я0-9 -]{6,}", re.IGNORECASE),
    )
    _VOLATILE_TERMS = (
        "версия", "version", "цена", "price", "курс", "rate", "api",
        "модель", "model", "доступен", "status", "статус", "текущий",
        "сегодня", "latest", "актуальн",
    )
    _GOAL_MARKERS = (
        "цель проекта", "главная цель", "наша цель", "хочу чтобы", "нужно добиться",
        "целевое состояние", "goal:",
    )

    def __init__(
        self,
        root: Path,
        memory: SayuriMemory,
        semantic: SemanticMemoryIndex,
        memory_v3: MemorySystemV3,
    ):
        self.root = root
        self.path = root / "data" / "sayuri-memory.db"
        self.snapshot_dir = root / "data" / "memory-snapshots"
        self.memory = memory
        self.semantic = semantic
        self.memory_v3 = memory_v3
        self._lock = RLock()
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @staticmethod
    def _now_dt() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _now(cls) -> str:
        return cls._now_dt().isoformat()

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _json(value: Any, limit: int = 32000) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:limit]

    @staticmethod
    def _decode(value: str | None, fallback: Any = None) -> Any:
        if not value:
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join((text or "").casefold().replace("ё", "е").split())

    @staticmethod
    def _fingerprint(*parts: str) -> str:
        joined = "\x1f".join((part or "").strip().casefold() for part in parts)
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA synchronous = NORMAL")
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_v4_state (
                    memory_id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL,
                    source_trust REAL NOT NULL,
                    freshness_class TEXT NOT NULL,
                    freshness_score REAL NOT NULL,
                    utility_score REAL NOT NULL,
                    tier TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    cloud_allowed INTEGER NOT NULL,
                    recall_count INTEGER NOT NULL DEFAULT 0,
                    helpful_count INTEGER NOT NULL DEFAULT 0,
                    unhelpful_count INTEGER NOT NULL DEFAULT 0,
                    last_recalled_at TEXT,
                    evaluated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_v4_tier ON memory_v4_state(tier, evaluated_at DESC)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_source_trust (
                    source_key TEXT PRIMARY KEY,
                    trust_score REAL NOT NULL,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    correction_count INTEGER NOT NULL DEFAULT 0,
                    manual_override REAL,
                    last_outcome TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_goals (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    source_memory_id TEXT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_goals_status ON memory_goals(status, priority DESC, updated_at DESC)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_tasks (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    goal_id TEXT,
                    parent_task_id TEXT,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    next_action TEXT,
                    blocked_reason TEXT,
                    source TEXT NOT NULL,
                    source_memory_id TEXT,
                    context_json TEXT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_tasks_status ON memory_tasks(status, priority DESC, updated_at DESC)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_decision_records (
                    id TEXT PRIMARY KEY,
                    source_memory_id TEXT NOT NULL UNIQUE,
                    scope TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    rationale TEXT,
                    alternatives_json TEXT NOT NULL,
                    project_version TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_failures (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    strategy TEXT NOT NULL,
                    symptom TEXT NOT NULL,
                    cause TEXT,
                    resolution TEXT,
                    prevention TEXT,
                    status TEXT NOT NULL,
                    occurrences INTEGER NOT NULL DEFAULT 1,
                    resolved_count INTEGER NOT NULL DEFAULT 0,
                    source_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_causal_links (
                    id TEXT PRIMARY KEY,
                    cause_type TEXT NOT NULL,
                    cause_id TEXT NOT NULL,
                    effect_type TEXT NOT NULL,
                    effect_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(cause_type, cause_id, effect_type, effect_id, relation)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_questions (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    question TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    related_ids_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolution TEXT
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_questions_status ON memory_questions(status, created_at DESC)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_recall_audit (
                    id TEXT PRIMARY KEY,
                    query_hash TEXT NOT NULL,
                    query_excerpt TEXT NOT NULL,
                    selected_ids_json TEXT NOT NULL,
                    explanations_json TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_recall_time ON memory_recall_audit(created_at DESC)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_response_recall (
                    response_id TEXT PRIMARY KEY,
                    recall_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    feedback TEXT,
                    feedback_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_audit_log (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT,
                    details_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_audit_time ON memory_audit_log(created_at DESC)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_snapshots (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL UNIQUE,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_v4_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _audit(
        self,
        action: str,
        subject_type: str,
        subject_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO memory_audit_log(
                    id, action, subject_type, subject_id, details_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    action[:80],
                    subject_type[:80],
                    subject_id,
                    self._json(details) if details else None,
                    self._now(),
                ),
            )

    def _project_version(self) -> str | None:
        try:
            return (self.root / "VERSION").read_text(encoding="utf-8").strip()[:40]
        except OSError:
            return None

    @classmethod
    def classify_sensitivity(cls, text: str) -> tuple[str, bool]:
        value = text or ""
        if any(pattern.search(value) for pattern in cls._SECRET_PATTERNS):
            return "secret", False
        if any(pattern.search(value) for pattern in cls._SENSITIVE_PATTERNS):
            return "sensitive", False
        return "normal", True

    @classmethod
    def freshness_policy(cls, entry: dict[str, Any]) -> tuple[str, float]:
        text = cls._normalize(str(entry.get("content") or ""))
        kind = str(entry.get("kind") or "note")
        if any(term in text for term in cls._VOLATILE_TERMS):
            return "volatile", 30.0
        if kind == "decision":
            return "durable", 3650.0
        if kind == "preference":
            return "stable", 730.0
        if kind == "task":
            return "medium", 120.0
        if kind == "fact":
            return "medium", 365.0
        return "medium", 180.0

    def _source_key(self, entry: dict[str, Any]) -> str:
        source = str(entry.get("source") or "unknown").strip().casefold()
        context = entry.get("source_context")
        if isinstance(context, dict):
            document = context.get("current_document")
            if isinstance(document, dict) and document.get("id"):
                return f"document:{document['id']}"
        return source or "unknown"

    def _source_base(self, entry: dict[str, Any]) -> float:
        source = str(entry.get("source") or "unknown").strip().casefold()
        if source in self.SOURCE_BASE_TRUST:
            base = self.SOURCE_BASE_TRUST[source]
        elif "ocr" in source:
            base = self.SOURCE_BASE_TRUST["ocr"]
        elif "document" in source or "dna" in source:
            base = self.SOURCE_BASE_TRUST["document"]
        elif "manual" in source:
            base = self.SOURCE_BASE_TRUST["manual"]
        else:
            base = self.SOURCE_BASE_TRUST["unknown"]
        confidence = entry.get("confidence")
        if confidence is not None:
            base = base * 0.72 + max(0.0, min(float(confidence), 1.0)) * 0.28
        return max(0.05, min(base, 1.0))

    def _source_profile(self, source_key: str, base: float) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM memory_source_trust WHERE source_key = ?",
                (source_key,),
            ).fetchone()
            if row is None:
                now = self._now()
                db.execute(
                    """
                    INSERT INTO memory_source_trust(
                        source_key, trust_score, evidence_count, correction_count,
                        manual_override, last_outcome, updated_at
                    ) VALUES(?, ?, 0, 0, NULL, NULL, ?)
                    """,
                    (source_key, base, now),
                )
                return {
                    "source_key": source_key,
                    "trust_score": base,
                    "evidence_count": 0,
                    "correction_count": 0,
                    "manual_override": None,
                    "last_outcome": None,
                    "updated_at": now,
                }
        score = row["manual_override"] if row["manual_override"] is not None else row["trust_score"]
        return {
            "source_key": row["source_key"],
            "trust_score": float(score),
            "evidence_count": row["evidence_count"],
            "correction_count": row["correction_count"],
            "manual_override": row["manual_override"],
            "last_outcome": row["last_outcome"],
            "updated_at": row["updated_at"],
        }

    def set_source_trust(self, source_key: str, score: float | None) -> dict[str, Any]:
        key = (source_key or "").strip()
        if not key:
            raise MemorySystemV4Error("Не указан источник.")
        override = None if score is None else max(0.05, min(float(score), 1.0))
        with self._connect() as db:
            row = db.execute(
                "SELECT trust_score FROM memory_source_trust WHERE source_key = ?",
                (key,),
            ).fetchone()
            base = float(row["trust_score"]) if row else self.SOURCE_BASE_TRUST["unknown"]
            now = self._now()
            db.execute(
                """
                INSERT INTO memory_source_trust(
                    source_key, trust_score, evidence_count, correction_count,
                    manual_override, last_outcome, updated_at
                ) VALUES(?, ?, 0, 0, ?, NULL, ?)
                ON CONFLICT(source_key) DO UPDATE SET
                    manual_override=excluded.manual_override,
                    updated_at=excluded.updated_at
                """,
                (key, base, override, now),
            )
        self.refresh_memory_states()
        self._audit("source_trust_changed", "source", key, {"manual_override": override})
        return self._source_profile(key, base)

    def _freshness_score(self, entry: dict[str, Any], half_life_days: float) -> float:
        anchor = (
            self._parse_time(entry.get("updated_at"))
            or self._parse_time(entry.get("created_at"))
            or self._now_dt()
        )
        age_days = max((self._now_dt() - anchor).total_seconds() / 86400.0, 0.0)
        if half_life_days <= 0:
            return 1.0
        return max(0.05, min(exp(-0.69314718056 * age_days / half_life_days), 1.0))

    def _utility_from_counts(self, helpful: int, unhelpful: int) -> float:
        return (helpful + 1.0) / (helpful + unhelpful + 2.0)

    def _tier(
        self,
        entry: dict[str, Any],
        *,
        freshness: float,
        utility: float,
    ) -> str:
        retention = max(0.0, min(float(entry.get("retention_score", 1.0)), 1.0))
        importance = min(max(int(entry.get("importance") or 1), 1), 5) / 5.0
        uses = min(log1p(max(int(entry.get("use_count") or 0), 0)) / log1p(16), 1.0)
        score = retention * 0.30 + importance * 0.25 + freshness * 0.20 + utility * 0.15 + uses * 0.10
        if str(entry.get("kind") or "") == "decision" and importance >= 0.8:
            score = max(score, 0.78)
        if score >= 0.72:
            return "hot"
        if score >= 0.43:
            return "warm"
        return "cold"

    def evaluate_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        memory_id = str(entry.get("id") or "")
        if not memory_id:
            raise MemorySystemV4Error("У памяти нет ID.")
        source_key = self._source_key(entry)
        source_profile = self._source_profile(source_key, self._source_base(entry))
        freshness_class, half_life = self.freshness_policy(entry)
        freshness = self._freshness_score(entry, half_life)
        sensitivity, cloud_allowed = self.classify_sensitivity(str(entry.get("content") or ""))

        with self._connect() as db:
            existing = db.execute(
                """
                SELECT recall_count, helpful_count, unhelpful_count, last_recalled_at
                FROM memory_v4_state WHERE memory_id = ?
                """,
                (memory_id,),
            ).fetchone()
        recalls = int(existing["recall_count"]) if existing else 0
        helpful = int(existing["helpful_count"]) if existing else 0
        unhelpful = int(existing["unhelpful_count"]) if existing else 0
        last_recalled_at = existing["last_recalled_at"] if existing else None
        utility = self._utility_from_counts(helpful, unhelpful)
        tier = self._tier(entry, freshness=freshness, utility=utility)
        now = self._now()

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO memory_v4_state(
                    memory_id, source_key, source_trust, freshness_class,
                    freshness_score, utility_score, tier, sensitivity,
                    cloud_allowed, recall_count, helpful_count, unhelpful_count,
                    last_recalled_at, evaluated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    source_key=excluded.source_key,
                    source_trust=excluded.source_trust,
                    freshness_class=excluded.freshness_class,
                    freshness_score=excluded.freshness_score,
                    utility_score=excluded.utility_score,
                    tier=excluded.tier,
                    sensitivity=excluded.sensitivity,
                    cloud_allowed=excluded.cloud_allowed,
                    evaluated_at=excluded.evaluated_at
                """,
                (
                    memory_id,
                    source_key,
                    source_profile["trust_score"],
                    freshness_class,
                    freshness,
                    utility,
                    tier,
                    sensitivity,
                    1 if cloud_allowed else 0,
                    recalls,
                    helpful,
                    unhelpful,
                    last_recalled_at,
                    now,
                ),
            )
        return {
            "memory_id": memory_id,
            "source_key": source_key,
            "source_trust": round(float(source_profile["trust_score"]), 4),
            "freshness_class": freshness_class,
            "freshness_score": round(freshness, 4),
            "utility_score": round(utility, 4),
            "tier": tier,
            "sensitivity": sensitivity,
            "cloud_allowed": cloud_allowed,
            "recall_count": recalls,
            "helpful_count": helpful,
            "unhelpful_count": unhelpful,
            "last_recalled_at": last_recalled_at,
            "evaluated_at": now,
        }

    def refresh_memory_states(self) -> dict[str, Any]:
        entries = self.memory.scan_active(limit=self.MAX_SCAN)
        counts = {"hot": 0, "warm": 0, "cold": 0, "protected": 0}
        for entry in entries:
            state = self.evaluate_entry(entry)
            counts[state["tier"]] += 1
            if not state["cloud_allowed"]:
                counts["protected"] += 1
        return {"evaluated": len(entries), **counts}

    def state_for(self, memory_id: str) -> dict[str, Any] | None:
        entry = self.memory.get(memory_id)
        if entry is None:
            return None
        return self.evaluate_entry(entry)

    def _recall_explanation(
        self,
        entry: dict[str, Any],
        state: dict[str, Any],
        semantic_match: dict[str, Any] | None,
        final_score: float,
    ) -> dict[str, Any]:
        reasons = list((semantic_match or {}).get("reasons") or [])
        reasons.append(f"источник {round(state['source_trust'] * 100)}%")
        reasons.append(f"свежесть {round(state['freshness_score'] * 100)}%")
        reasons.append(f"полезность {round(state['utility_score'] * 100)}%")
        reasons.append(f"слой {state['tier']}")
        if state["sensitivity"] != "normal":
            reasons.append("защищённая локальная память")
        return {
            "memory_id": entry["id"],
            "final_score": round(final_score, 4),
            "semantic_score": round(float((semantic_match or {}).get("score") or 0), 4),
            "source_trust": state["source_trust"],
            "freshness": state["freshness_score"],
            "utility": state["utility_score"],
            "tier": state["tier"],
            "sensitivity": state["sensitivity"],
            "cloud_allowed": state["cloud_allowed"],
            "why": reasons,
        }

    def recall(
        self,
        query: str,
        *,
        scopes: Iterable[str] = ("personal", "project"),
        limit: int = 10,
        for_cloud: bool = False,
    ) -> dict[str, Any]:
        text = (query or "").strip()
        valid_scopes = tuple(dict.fromkeys(scope for scope in scopes if scope in {"personal", "project"}))
        if not valid_scopes:
            raise MemorySystemV4Error("Нет допустимой области памяти.")
        semantic = self.semantic.search(
            text,
            scopes=valid_scopes,
            limit=min(max(int(limit) * 6, 40), 120),
            minimum_score=0.02,
        )
        ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        for scope in valid_scopes:
            for entry in semantic.get(scope, []):
                state = self.evaluate_entry(entry)
                if for_cloud and not state["cloud_allowed"]:
                    continue
                semantic_score = float(entry.get("relevance") or 0)
                tier_boost = {"hot": 1.08, "warm": 1.0, "cold": 0.88}[state["tier"]]
                final_score = semantic_score
                final_score *= 0.72 + state["source_trust"] * 0.28
                final_score *= 0.72 + state["freshness_score"] * 0.28
                final_score *= 0.78 + state["utility_score"] * 0.22
                final_score *= tier_boost
                explanation = self._recall_explanation(
                    entry,
                    state,
                    entry.get("semantic_match"),
                    final_score,
                )
                enriched = dict(entry)
                enriched["v4"] = state
                enriched["recall_explanation"] = explanation
                enriched["relevance"] = round(final_score, 4)
                ranked.append((final_score, enriched, explanation))

        ranked.sort(
            key=lambda item: (
                item[0],
                int(item[1].get("importance") or 0),
                item[1].get("updated_at") or "",
            ),
            reverse=True,
        )
        selected = ranked[: min(max(int(limit), 1), 30)]
        selected_ids = [entry["id"] for _, entry, _ in selected]
        explanations = [explanation for _, _, explanation in selected]
        recall_id = uuid.uuid4().hex
        now = self._now()

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO memory_recall_audit(
                    id, query_hash, query_excerpt, selected_ids_json,
                    explanations_json, scopes_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recall_id,
                    hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    text[:300],
                    self._json(selected_ids),
                    self._json(explanations),
                    self._json(valid_scopes),
                    now,
                ),
            )
            if selected_ids:
                db.executemany(
                    """
                    UPDATE memory_v4_state
                    SET recall_count = recall_count + 1, last_recalled_at = ?
                    WHERE memory_id = ?
                    """,
                    [(now, memory_id) for memory_id in selected_ids],
                )
        self._audit(
            "memory_recalled",
            "recall",
            recall_id,
            {"count": len(selected_ids), "scopes": list(valid_scopes), "for_cloud": for_cloud},
        )

        result = {scope: [] for scope in valid_scopes}
        for _, entry, _ in selected:
            result[entry["scope"]].append(entry)
        result.update({
            "recall_id": recall_id,
            "retrieval": self.ENGINE_ID,
            "explanations": explanations,
        })
        return result

    def bind_response(self, response_id: str, recall_id: str | None) -> None:
        if not response_id or not recall_id:
            return
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO memory_response_recall(response_id, recall_id, created_at, feedback, feedback_at)
                VALUES(?, ?, ?, NULL, NULL)
                ON CONFLICT(response_id) DO UPDATE SET
                    recall_id=excluded.recall_id
                """,
                (response_id, recall_id, self._now()),
            )

    def apply_response_feedback(self, response_id: str, rating: str) -> dict[str, Any]:
        normalized = (rating or "").strip().lower()
        if normalized not in {"useful", "not_useful"}:
            raise MemorySystemV4Error("Оценка должна быть useful или not_useful.")
        with self._connect() as db:
            link = db.execute(
                "SELECT * FROM memory_response_recall WHERE response_id = ?",
                (response_id,),
            ).fetchone()
            if link is None:
                return {"updated": 0, "rating": normalized}
            recall = db.execute(
                "SELECT * FROM memory_recall_audit WHERE id = ?",
                (link["recall_id"],),
            ).fetchone()
            if recall is None:
                return {"updated": 0, "rating": normalized}
            memory_ids = self._decode(recall["selected_ids_json"], [])
            previous = link["feedback"]
            if previous == normalized:
                return {"updated": 0, "rating": normalized}

            for memory_id in memory_ids:
                row = db.execute(
                    """
                    SELECT helpful_count, unhelpful_count
                    FROM memory_v4_state WHERE memory_id = ?
                    """,
                    (memory_id,),
                ).fetchone()
                if row is None:
                    continue
                helpful = int(row["helpful_count"])
                unhelpful = int(row["unhelpful_count"])
                if previous == "useful":
                    helpful = max(0, helpful - 1)
                elif previous == "not_useful":
                    unhelpful = max(0, unhelpful - 1)
                if normalized == "useful":
                    helpful += 1
                else:
                    unhelpful += 1
                utility = self._utility_from_counts(helpful, unhelpful)
                db.execute(
                    """
                    UPDATE memory_v4_state
                    SET helpful_count = ?, unhelpful_count = ?, utility_score = ?
                    WHERE memory_id = ?
                    """,
                    (helpful, unhelpful, utility, memory_id),
                )
            db.execute(
                """
                UPDATE memory_response_recall
                SET feedback = ?, feedback_at = ?
                WHERE response_id = ?
                """,
                (normalized, self._now(), response_id),
            )
        for memory_id in memory_ids:
            entry = self.memory.get(memory_id)
            if entry:
                self.evaluate_entry(entry)
        self._audit(
            "recall_feedback",
            "response",
            response_id,
            {"rating": normalized, "memory_count": len(memory_ids)},
        )
        return {"updated": len(memory_ids), "rating": normalized}

    def _goal_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "scope": row["scope"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "priority": row["priority"],
            "source": row["source"],
            "source_memory_id": row["source_memory_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
        }

    def create_goal(
        self,
        title: str,
        *,
        description: str = "",
        scope: str = "project",
        priority: int = 4,
        source: str = "manual",
        source_memory_id: str | None = None,
    ) -> dict[str, Any]:
        title = " ".join((title or "").strip().split())
        if not title:
            raise MemorySystemV4Error("Название цели не может быть пустым.")
        if scope not in {"personal", "project"}:
            raise MemorySystemV4Error("Область цели должна быть personal или project.")
        priority = min(max(int(priority), 1), 5)
        fingerprint = self._fingerprint(scope, title)
        now = self._now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM memory_goals WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if row:
                return self._goal_row(row)
            goal_id = uuid.uuid4().hex
            db.execute(
                """
                INSERT INTO memory_goals(
                    id, scope, title, description, status, priority,
                    source, source_memory_id, fingerprint,
                    created_at, updated_at, completed_at
                ) VALUES(?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    goal_id,
                    scope,
                    title[:500],
                    description[:4000],
                    priority,
                    source[:80],
                    source_memory_id,
                    fingerprint,
                    now,
                    now,
                ),
            )
            row = db.execute("SELECT * FROM memory_goals WHERE id = ?", (goal_id,)).fetchone()
        self._audit("goal_created", "goal", goal_id, {"title": title, "scope": scope})
        self._link_goal_graph(self._goal_row(row))
        return self._goal_row(row)

    def _link_goal_graph(self, goal: dict[str, Any]) -> None:
        with self.memory_v3._connect() as db:
            project_or_person = self.memory_v3._ensure_node(
                db,
                node_type="project" if goal["scope"] == "project" else "person",
                node_key="sayuri-tsukishiro" if goal["scope"] == "project" else "master",
                label="Sayuri Tsukishiro" if goal["scope"] == "project" else "Господин",
            )
            node = self.memory_v3._ensure_node(
                db,
                node_type="goal",
                node_key=goal["id"],
                label=goal["title"],
                metadata={"status": goal["status"], "priority": goal["priority"]},
            )
            self.memory_v3._ensure_edge(
                db,
                source_id=project_or_person,
                target_id=node,
                relation="pursues",
                source_ref=goal["id"],
            )

    def goals(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            if status not in self.GOAL_STATUSES:
                raise MemorySystemV4Error("Неизвестный статус цели.")
            where = "WHERE status = ?"
            params.append(status)
        params.append(min(max(int(limit), 1), 300))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM memory_goals {where} ORDER BY priority DESC, updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._goal_row(row) for row in rows]

    def update_goal(self, goal_id: str, *, status: str | None = None) -> dict[str, Any]:
        if status is not None and status not in self.GOAL_STATUSES:
            raise MemorySystemV4Error("Неизвестный статус цели.")
        now = self._now()
        with self._connect() as db:
            row = db.execute("SELECT * FROM memory_goals WHERE id = ?", (goal_id,)).fetchone()
            if row is None:
                raise MemorySystemV4Error("Цель не найдена.")
            next_status = status or row["status"]
            completed_at = now if next_status == "achieved" else None
            db.execute(
                """
                UPDATE memory_goals
                SET status = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_status, completed_at, now, goal_id),
            )
            row = db.execute("SELECT * FROM memory_goals WHERE id = ?", (goal_id,)).fetchone()
        goal = self._goal_row(row)
        self._link_goal_graph(goal)
        self._audit("goal_updated", "goal", goal_id, {"status": goal["status"]})
        return goal

    def _task_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "scope": row["scope"],
            "goal_id": row["goal_id"],
            "parent_task_id": row["parent_task_id"],
            "title": row["title"],
            "status": row["status"],
            "priority": row["priority"],
            "next_action": row["next_action"],
            "blocked_reason": row["blocked_reason"],
            "source": row["source"],
            "source_memory_id": row["source_memory_id"],
            "context": self._decode(row["context_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
        }

    def create_task(
        self,
        title: str,
        *,
        scope: str = "project",
        goal_id: str | None = None,
        priority: int = 3,
        next_action: str = "",
        source: str = "manual",
        source_memory_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        title = " ".join((title or "").strip().split())
        if not title:
            raise MemorySystemV4Error("Название задачи не может быть пустым.")
        if scope not in {"personal", "project"}:
            raise MemorySystemV4Error("Область задачи должна быть personal или project.")
        if goal_id:
            with self._connect() as db:
                if db.execute("SELECT 1 FROM memory_goals WHERE id = ?", (goal_id,)).fetchone() is None:
                    raise MemorySystemV4Error("Связанная цель не найдена.")
        priority = min(max(int(priority), 1), 5)
        fingerprint = self._fingerprint(scope, goal_id or "", title)
        now = self._now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM memory_tasks WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if row:
                return self._task_row(row)
            task_id = uuid.uuid4().hex
            db.execute(
                """
                INSERT INTO memory_tasks(
                    id, scope, goal_id, parent_task_id, title, status, priority,
                    next_action, blocked_reason, source, source_memory_id,
                    context_json, fingerprint, created_at, updated_at, completed_at
                ) VALUES(?, ?, ?, NULL, ?, 'planned', ?, ?, NULL, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    task_id,
                    scope,
                    goal_id,
                    title[:1000],
                    priority,
                    next_action[:2000] or None,
                    source[:80],
                    source_memory_id,
                    self._json(context) if context else None,
                    fingerprint,
                    now,
                    now,
                ),
            )
            row = db.execute("SELECT * FROM memory_tasks WHERE id = ?", (task_id,)).fetchone()
        task = self._task_row(row)
        self._link_task_graph(task)
        self._audit("task_created", "task", task_id, {"title": title, "goal_id": goal_id})
        return task

    def _link_task_graph(self, task: dict[str, Any]) -> None:
        with self.memory_v3._connect() as db:
            task_node = self.memory_v3._ensure_node(
                db,
                node_type="task",
                node_key=task["id"],
                label=task["title"],
                metadata={
                    "status": task["status"],
                    "priority": task["priority"],
                    "next_action": task["next_action"],
                },
            )
            if task.get("goal_id"):
                goal = next((item for item in self.goals(limit=300) if item["id"] == task["goal_id"]), None)
                if goal:
                    goal_node = self.memory_v3._ensure_node(
                        db,
                        node_type="goal",
                        node_key=goal["id"],
                        label=goal["title"],
                        metadata={"status": goal["status"], "priority": goal["priority"]},
                    )
                    self.memory_v3._ensure_edge(
                        db,
                        source_id=goal_node,
                        target_id=task_node,
                        relation="has_task",
                        source_ref=task["id"],
                    )

    def tasks(self, *, status: str | None = None, limit: int = 150) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            if status not in self.TASK_STATUSES:
                raise MemorySystemV4Error("Неизвестный статус задачи.")
            where = "WHERE status = ?"
            params.append(status)
        params.append(min(max(int(limit), 1), 500))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM memory_tasks {where} ORDER BY priority DESC, updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._task_row(row) for row in rows]

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        next_action: str | None = None,
        blocked_reason: str | None = None,
    ) -> dict[str, Any]:
        if status is not None and status not in self.TASK_STATUSES:
            raise MemorySystemV4Error("Неизвестный статус задачи.")
        now = self._now()
        with self._connect() as db:
            row = db.execute("SELECT * FROM memory_tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise MemorySystemV4Error("Задача не найдена.")
            next_status = status or row["status"]
            next_step = row["next_action"] if next_action is None else next_action[:2000]
            block = row["blocked_reason"] if blocked_reason is None else blocked_reason[:2000]
            completed_at = now if next_status == "done" else None
            db.execute(
                """
                UPDATE memory_tasks
                SET status = ?, next_action = ?, blocked_reason = ?,
                    completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_status, next_step, block, completed_at, now, task_id),
            )
            row = db.execute("SELECT * FROM memory_tasks WHERE id = ?", (task_id,)).fetchone()
        task = self._task_row(row)
        self._link_task_graph(task)
        self._audit(
            "task_updated",
            "task",
            task_id,
            {"status": task["status"], "next_action": task["next_action"]},
        )
        return task

    def _decision_rationale(self, content: str) -> tuple[str | None, list[str]]:
        text = " ".join((content or "").split())
        rationale = None
        alternatives: list[str] = []
        match = re.search(r"\b(?:потому что|так как|because)\b(.+)$", text, flags=re.IGNORECASE)
        if match:
            rationale = match.group(1).strip(" .,:;-")[:2000] or None
        alt = re.search(r"\b(?:вместо|rather than)\b(.+)$", text, flags=re.IGNORECASE)
        if alt:
            alternatives.append(alt.group(1).strip(" .,:;-")[:1000])
        return rationale, alternatives

    def record_decision(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        if str(entry.get("kind") or "") != "decision":
            return None
        memory_id = str(entry.get("id") or "")
        if not memory_id:
            return None
        statement = str(entry.get("content") or "").strip()
        rationale, alternatives = self._decision_rationale(statement)
        now = self._now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM memory_decision_records WHERE source_memory_id = ?",
                (memory_id,),
            ).fetchone()
            if row is None:
                decision_id = uuid.uuid4().hex
                db.execute(
                    """
                    INSERT INTO memory_decision_records(
                        id, source_memory_id, scope, statement, rationale,
                        alternatives_json, project_version, status,
                        created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        decision_id,
                        memory_id,
                        entry.get("scope") or "project",
                        statement[:8000],
                        rationale,
                        self._json(alternatives),
                        self._project_version(),
                        now,
                        now,
                    ),
                )
                row = db.execute(
                    "SELECT * FROM memory_decision_records WHERE id = ?",
                    (decision_id,),
                ).fetchone()
        self._audit("decision_recorded", "decision", row["id"], {"source_memory_id": memory_id})
        return self._decision_row(row)

    def _decision_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "source_memory_id": row["source_memory_id"],
            "scope": row["scope"],
            "statement": row["statement"],
            "rationale": row["rationale"],
            "alternatives": self._decode(row["alternatives_json"], []),
            "project_version": row["project_version"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def decisions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM memory_decision_records
                WHERE status = 'active'
                ORDER BY updated_at DESC LIMIT ?
                """,
                (min(max(int(limit), 1), 300),),
            ).fetchall()
        return [self._decision_row(row) for row in rows]

    def _looks_like_goal(self, content: str) -> bool:
        lowered = self._normalize(content)
        return any(marker in lowered for marker in self._GOAL_MARKERS)

    def ingest_memory(self, entry: dict[str, Any]) -> dict[str, Any]:
        state = self.evaluate_entry(entry)
        task = None
        goal = None
        decision = self.record_decision(entry)

        kind = str(entry.get("kind") or "")
        content = str(entry.get("content") or "")
        source = str(entry.get("source") or "memory")
        scope = str(entry.get("scope") or "project")
        if kind == "task":
            task = self.create_task(
                content,
                scope=scope,
                priority=int(entry.get("importance") or 3),
                source=source,
                source_memory_id=entry.get("id"),
                context=entry.get("source_context") if isinstance(entry.get("source_context"), dict) else None,
            )
        elif self._looks_like_goal(content):
            goal = self.create_goal(
                content,
                scope=scope,
                priority=int(entry.get("importance") or 4),
                source=source,
                source_memory_id=entry.get("id"),
            )

        self._audit(
            "memory_v4_ingested",
            "memory",
            str(entry.get("id") or ""),
            {
                "tier": state["tier"],
                "source_trust": state["source_trust"],
                "sensitivity": state["sensitivity"],
                "task_id": task["id"] if task else None,
                "goal_id": goal["id"] if goal else None,
                "decision_id": decision["id"] if decision else None,
            },
        )
        return {"state": state, "task": task, "goal": goal, "decision": decision}

    def _failure_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "strategy": row["strategy"],
            "symptom": row["symptom"],
            "cause": row["cause"],
            "resolution": row["resolution"],
            "prevention": row["prevention"],
            "status": row["status"],
            "occurrences": row["occurrences"],
            "resolved_count": row["resolved_count"],
            "source_ref": row["source_ref"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def record_action_outcome(self, action: dict[str, Any]) -> dict[str, Any] | None:
        status = str(action.get("status") or "")
        tool = str(action.get("tool") or "unknown")
        action_id = str(action.get("id") or "")
        if status == "failed":
            symptom = str(action.get("error") or action.get("title") or "Неизвестная ошибка")
            fingerprint = self._fingerprint(tool, symptom)
            now = self._now()
            with self._connect() as db:
                row = db.execute(
                    "SELECT * FROM memory_failures WHERE fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
                if row:
                    db.execute(
                        """
                        UPDATE memory_failures
                        SET occurrences = occurrences + 1, updated_at = ?, source_ref = ?
                        WHERE id = ?
                        """,
                        (now, action_id, row["id"]),
                    )
                    failure_id = row["id"]
                else:
                    failure_id = uuid.uuid4().hex
                    db.execute(
                        """
                        INSERT INTO memory_failures(
                            id, fingerprint, strategy, symptom, cause, resolution,
                            prevention, status, occurrences, resolved_count,
                            source_ref, created_at, updated_at
                        ) VALUES(?, ?, ?, ?, NULL, NULL, NULL, 'open', 1, 0, ?, ?, ?)
                        """,
                        (failure_id, fingerprint, tool, symptom[:3000], action_id, now, now),
                    )
                row = db.execute("SELECT * FROM memory_failures WHERE id = ?", (failure_id,)).fetchone()
            failure = self._failure_row(row)
            self._audit("failure_recorded", "failure", failure_id, {"tool": tool})
            return failure

        if status == "completed":
            with self._connect() as db:
                row = db.execute(
                    """
                    SELECT * FROM memory_failures
                    WHERE strategy = ? AND status = 'open'
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (tool,),
                ).fetchone()
                if row is None:
                    return None
                resolution = str(action.get("result") or "Повторное действие завершилось успешно")[:3000]
                now = self._now()
                db.execute(
                    """
                    UPDATE memory_failures
                    SET resolution = ?, status = 'resolved',
                        resolved_count = resolved_count + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (resolution, now, row["id"]),
                )
                effect_id = action_id or uuid.uuid4().hex
                causal_id = uuid.uuid4().hex
                db.execute(
                    """
                    INSERT OR IGNORE INTO memory_causal_links(
                        id, cause_type, cause_id, effect_type, effect_id,
                        relation, confidence, evidence_json, created_at, updated_at
                    ) VALUES(?, 'failure', ?, 'action', ?, 'resolved_by', 0.85, ?, ?, ?)
                    """,
                    (
                        causal_id,
                        row["id"],
                        effect_id,
                        self._json({"tool": tool, "result": action.get("result")}),
                        now,
                        now,
                    ),
                )
                updated = db.execute(
                    "SELECT * FROM memory_failures WHERE id = ?",
                    (row["id"],),
                ).fetchone()
            self._audit("failure_resolved", "failure", row["id"], {"action_id": action_id})
            return self._failure_row(updated)
        return None

    def failures(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM memory_failures
                ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END,
                         occurrences DESC, updated_at DESC
                LIMIT ?
                """,
                (min(max(int(limit), 1), 300),),
            ).fetchall()
        return [self._failure_row(row) for row in rows]

    def open_question(
        self,
        question: str,
        *,
        scope: str = "project",
        reason: str = "uncertainty",
        related_ids: list[str] | None = None,
        source: str = "system",
    ) -> dict[str, Any]:
        text = " ".join((question or "").strip().split())
        if not text:
            raise MemorySystemV4Error("Вопрос памяти не может быть пустым.")
        fingerprint = self._fingerprint(scope, text)
        now = self._now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM memory_questions WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if row:
                return self._question_row(row)
            question_id = uuid.uuid4().hex
            db.execute(
                """
                INSERT INTO memory_questions(
                    id, scope, question, reason, status, related_ids_json,
                    source, fingerprint, created_at, resolved_at, resolution
                ) VALUES(?, ?, ?, ?, 'open', ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    question_id,
                    scope,
                    text[:2000],
                    reason[:500],
                    self._json(related_ids or []),
                    source[:80],
                    fingerprint,
                    now,
                ),
            )
            row = db.execute("SELECT * FROM memory_questions WHERE id = ?", (question_id,)).fetchone()
        self._audit("question_opened", "question", question_id, {"reason": reason})
        return self._question_row(row)

    def _question_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "scope": row["scope"],
            "question": row["question"],
            "reason": row["reason"],
            "status": row["status"],
            "related_ids": self._decode(row["related_ids_json"], []),
            "source": row["source"],
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
            "resolution": row["resolution"],
        }

    def questions(self, *, status: str | None = "open", limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            if status not in self.QUESTION_STATUSES:
                raise MemorySystemV4Error("Неизвестный статус вопроса.")
            where = "WHERE status = ?"
            params.append(status)
        params.append(min(max(int(limit), 1), 300))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM memory_questions {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._question_row(row) for row in rows]

    def resolve_question(self, question_id: str, resolution: str) -> dict[str, Any]:
        text = " ".join((resolution or "").strip().split())
        if not text:
            raise MemorySystemV4Error("Нужно указать решение вопроса.")
        with self._connect() as db:
            row = db.execute("SELECT * FROM memory_questions WHERE id = ?", (question_id,)).fetchone()
            if row is None:
                raise MemorySystemV4Error("Вопрос памяти не найден.")
            now = self._now()
            db.execute(
                """
                UPDATE memory_questions
                SET status='resolved', resolution=?, resolved_at=?
                WHERE id=?
                """,
                (text[:4000], now, question_id),
            )
            row = db.execute("SELECT * FROM memory_questions WHERE id = ?", (question_id,)).fetchone()
        self._audit("question_resolved", "question", question_id)
        return self._question_row(row)

    def register_conflict_question(self, conflict: dict[str, Any]) -> dict[str, Any] | None:
        if not conflict:
            return None
        return self.open_question(
            f"Какое утверждение актуально: «{conflict.get('old_content', '')[:300]}» или «{conflict.get('new_content', '')[:300]}»?",
            scope=str(conflict.get("scope") or "project"),
            reason="memory_conflict",
            related_ids=[
                str(conflict.get("id") or ""),
                str(conflict.get("old_memory_id") or ""),
                str(conflict.get("new_memory_id") or ""),
            ],
            source="contradiction_resolver",
        )

    def resolve_conflict_question(self, conflict_id: str, resolution: str) -> None:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM memory_questions
                WHERE status = 'open' AND reason = 'memory_conflict'
                """
            ).fetchall()
        for row in rows:
            related = self._decode(row["related_ids_json"], [])
            if conflict_id in related:
                self.resolve_question(row["id"], f"Конфликт разрешён: {resolution}")

    def _source_profiles(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM memory_source_trust
                ORDER BY COALESCE(manual_override, trust_score) DESC, updated_at DESC
                LIMIT ?
                """,
                (min(max(int(limit), 1), 200),),
            ).fetchall()
        return [
            {
                "source_key": row["source_key"],
                "trust_score": row["manual_override"] if row["manual_override"] is not None else row["trust_score"],
                "base_trust": row["trust_score"],
                "manual_override": row["manual_override"],
                "evidence_count": row["evidence_count"],
                "correction_count": row["correction_count"],
                "last_outcome": row["last_outcome"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def note_source_outcome(self, memory_ids: list[str], rating: str) -> None:
        positive = rating == "useful"
        with self._connect() as db:
            for memory_id in memory_ids:
                state = db.execute(
                    "SELECT source_key FROM memory_v4_state WHERE memory_id = ?",
                    (memory_id,),
                ).fetchone()
                if state is None:
                    continue
                source = db.execute(
                    "SELECT * FROM memory_source_trust WHERE source_key = ?",
                    (state["source_key"],),
                ).fetchone()
                if source is None:
                    continue
                evidence = int(source["evidence_count"]) + 1
                corrections = int(source["correction_count"]) + (0 if positive else 1)
                empirical = (evidence - corrections + 1.0) / (evidence + 2.0)
                next_score = float(source["trust_score"]) * 0.85 + empirical * 0.15
                db.execute(
                    """
                    UPDATE memory_source_trust
                    SET trust_score=?, evidence_count=?, correction_count=?,
                        last_outcome=?, updated_at=?
                    WHERE source_key=?
                    """,
                    (
                        max(0.05, min(next_score, 1.0)),
                        evidence,
                        corrections,
                        "useful" if positive else "not_useful",
                        self._now(),
                        state["source_key"],
                    ),
                )

    def recall_audit(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM memory_recall_audit
                ORDER BY created_at DESC LIMIT ?
                """,
                (min(max(int(limit), 1), 100),),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "query_excerpt": row["query_excerpt"],
                "selected_ids": self._decode(row["selected_ids_json"], []),
                "explanations": self._decode(row["explanations_json"], []),
                "scopes": self._decode(row["scopes_json"], []),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM memory_audit_log ORDER BY created_at DESC LIMIT ?",
                (min(max(int(limit), 1), 200),),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "action": row["action"],
                "subject_type": row["subject_type"],
                "subject_id": row["subject_id"],
                "details": self._decode(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def create_snapshot(self, reason: str = "manual") -> dict[str, Any]:
        with self._lock:
            snapshot_id = uuid.uuid4().hex
            timestamp = self._now_dt().strftime("%Y%m%dT%H%M%SZ")
            filename = f"sayuri-memory-{timestamp}-{snapshot_id[:8]}.db"
            target = self.snapshot_dir / filename
            with sqlite3.connect(self.path, timeout=10.0) as source:
                with sqlite3.connect(target, timeout=10.0) as destination:
                    source.backup(destination)
            sha = self._file_sha256(target)
            size = target.stat().st_size
            now = self._now()
            with self._connect() as db:
                db.execute(
                    """
                    INSERT INTO memory_snapshots(
                        id, filename, sha256, size_bytes, reason, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (snapshot_id, filename, sha, size, reason[:500], now),
                )
            self._audit("snapshot_created", "snapshot", snapshot_id, {"filename": filename, "sha256": sha})
            return {
                "id": snapshot_id,
                "filename": filename,
                "sha256": sha,
                "size_bytes": size,
                "reason": reason,
                "created_at": now,
            }

    def snapshots(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM memory_snapshots ORDER BY created_at DESC LIMIT ?",
                (min(max(int(limit), 1), 100),),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            path = self.snapshot_dir / row["filename"]
            result.append({
                "id": row["id"],
                "filename": row["filename"],
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
                "reason": row["reason"],
                "created_at": row["created_at"],
                "present": path.is_file(),
                "hash_valid": path.is_file() and self._file_sha256(path) == row["sha256"],
            })
        return result

    def restore_snapshot(self, snapshot_id: str, confirmation: str) -> dict[str, Any]:
        if confirmation != "RESTORE MEMORY":
            raise MemorySystemV4Error("Для восстановления требуется точное подтверждение RESTORE MEMORY.")
        with self._lock:
            with self._connect() as db:
                row = db.execute("SELECT * FROM memory_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
            if row is None:
                raise MemorySystemV4Error("Снимок памяти не найден.")
            source_path = self.snapshot_dir / row["filename"]
            if not source_path.is_file():
                raise MemorySystemV4Error("Файл снимка отсутствует.")
            if self._file_sha256(source_path) != row["sha256"]:
                raise MemorySystemV4Error("Контрольная сумма снимка не совпадает.")

            safety = self.create_snapshot("automatic_pre_restore")
            with sqlite3.connect(source_path, timeout=10.0) as source:
                with sqlite3.connect(self.path, timeout=10.0) as destination:
                    source.backup(destination)
            self.memory.initialize()
            self.memory_v3.initialize()
            self.initialize()
            # The restored DB can predate the safety snapshot record; restore its manifest.
            safety_path = self.snapshot_dir / safety["filename"]
            if safety_path.is_file():
                with self._connect() as db:
                    db.execute(
                        """
                        INSERT OR IGNORE INTO memory_snapshots(
                            id, filename, sha256, size_bytes, reason, created_at
                        ) VALUES(?, ?, ?, ?, ?, ?)
                        """,
                        (
                            safety["id"],
                            safety["filename"],
                            safety["sha256"],
                            safety["size_bytes"],
                            safety["reason"],
                            safety["created_at"],
                        ),
                    )
            self._audit(
                "snapshot_restored",
                "snapshot",
                snapshot_id,
                {"pre_restore_snapshot": safety["id"]},
            )
            return {
                "status": "восстановлено",
                "snapshot_id": snapshot_id,
                "pre_restore_snapshot": safety,
                "integrity": self.integrity_check(),
            }

    def integrity_check(self) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        with self._connect() as db:
            integrity_rows = [row[0] for row in db.execute("PRAGMA integrity_check").fetchall()]
            if integrity_rows != ["ok"]:
                issues.append({"type": "sqlite_integrity", "details": integrity_rows})

            orphan_edges = db.execute(
                """
                SELECT COUNT(*) FROM memory_graph_edges e
                LEFT JOIN memory_graph_nodes s ON s.id=e.source_id
                LEFT JOIN memory_graph_nodes t ON t.id=e.target_id
                WHERE s.id IS NULL OR t.id IS NULL
                """
            ).fetchone()[0]
            if orphan_edges:
                issues.append({"type": "orphan_graph_edges", "count": orphan_edges})

            dangling_tasks = db.execute(
                """
                SELECT COUNT(*) FROM memory_tasks t
                LEFT JOIN memory_goals g ON g.id=t.goal_id
                WHERE t.goal_id IS NOT NULL AND g.id IS NULL
                """
            ).fetchone()[0]
            if dangling_tasks:
                issues.append({"type": "dangling_task_goals", "count": dangling_tasks})

            knowledge_rows = db.execute(
                "SELECT id, source_memory_ids_json FROM knowledge_items WHERE status='confirmed'"
            ).fetchall()
            missing_sources = 0
            for row in knowledge_rows:
                for memory_id in self._decode(row["source_memory_ids_json"], []):
                    if db.execute("SELECT 1 FROM memory_entries WHERE id=?", (memory_id,)).fetchone() is None:
                        missing_sources += 1
            if missing_sources:
                issues.append({"type": "missing_knowledge_sources", "count": missing_sources})

            response_orphans = db.execute(
                """
                SELECT COUNT(*) FROM memory_response_recall r
                LEFT JOIN memory_recall_audit a ON a.id=r.recall_id
                WHERE a.id IS NULL
                """
            ).fetchone()[0]
            if response_orphans:
                issues.append({"type": "orphan_response_recall", "count": response_orphans})

        result = {
            "status": "ok" if not issues else "issues",
            "issues": issues,
            "checked_at": self._now(),
        }
        self._audit("integrity_checked", "system", None, {"status": result["status"], "issues": len(issues)})
        return result

    def bootstrap(self) -> dict[str, Any]:
        entries = self.memory.scan_active(limit=self.MAX_SCAN)
        ingested = 0
        for entry in entries:
            self.ingest_memory(entry)
            ingested += 1
        return {
            "entries": ingested,
            "states": self.refresh_memory_states(),
        }

    def maintenance(self, *, create_snapshot: bool = False) -> dict[str, Any]:
        snapshot = self.create_snapshot("memory_v4_maintenance") if create_snapshot else None
        states = self.refresh_memory_states()
        integrity = self.integrity_check()
        return {
            "status": "готово",
            "states": states,
            "integrity": integrity,
            "snapshot": snapshot,
            "stats": self.stats(),
        }

    def stats(self) -> dict[str, Any]:
        self.refresh_memory_states()
        with self._connect() as db:
            tiers = {
                row["tier"]: row["count"]
                for row in db.execute(
                    "SELECT tier, COUNT(*) AS count FROM memory_v4_state GROUP BY tier"
                ).fetchall()
            }
            protected = db.execute(
                "SELECT COUNT(*) FROM memory_v4_state WHERE cloud_allowed=0"
            ).fetchone()[0]
            goals = db.execute(
                "SELECT COUNT(*) FROM memory_goals WHERE status='active'"
            ).fetchone()[0]
            tasks = db.execute(
                "SELECT COUNT(*) FROM memory_tasks WHERE status IN ('planned','in_progress','blocked')"
            ).fetchone()[0]
            blocked = db.execute(
                "SELECT COUNT(*) FROM memory_tasks WHERE status='blocked'"
            ).fetchone()[0]
            decisions = db.execute(
                "SELECT COUNT(*) FROM memory_decision_records WHERE status='active'"
            ).fetchone()[0]
            failures = db.execute(
                "SELECT COUNT(*) FROM memory_failures WHERE status='open'"
            ).fetchone()[0]
            questions = db.execute(
                "SELECT COUNT(*) FROM memory_questions WHERE status='open'"
            ).fetchone()[0]
            recalls = db.execute(
                "SELECT COUNT(*) FROM memory_recall_audit"
            ).fetchone()[0]
            snapshots = db.execute(
                "SELECT COUNT(*) FROM memory_snapshots"
            ).fetchone()[0]
        return {
            "version": "4.0",
            "engine": self.ENGINE_ID,
            "hot": tiers.get("hot", 0),
            "warm": tiers.get("warm", 0),
            "cold": tiers.get("cold", 0),
            "protected": protected,
            "active_goals": goals,
            "open_tasks": tasks,
            "blocked_tasks": blocked,
            "active_decisions": decisions,
            "open_failures": failures,
            "open_questions": questions,
            "recalls": recalls,
            "snapshots": snapshots,
        }

    def dashboard(self) -> dict[str, Any]:
        integrity = self.integrity_check()
        return {
            "stats": self.stats(),
            "goals": self.goals(status="active", limit=30),
            "tasks": [
                item
                for item in self.tasks(limit=100)
                if item["status"] in {"planned", "in_progress", "blocked"}
            ][:40],
            "decisions": self.decisions(30),
            "failures": self.failures(30),
            "questions": self.questions(status="open", limit=30),
            "sources": self._source_profiles(30),
            "recalls": self.recall_audit(20),
            "audit": self.audit_log(30),
            "integrity": integrity,
            "snapshots": self.snapshots(20),
        }

    def context(self, query: str) -> dict[str, Any]:
        recalled = self.recall(query, limit=10, for_cloud=True)
        active_goals = self.goals(status="active", limit=8)
        open_tasks = [
            item for item in self.tasks(limit=30)
            if item["status"] in {"planned", "in_progress", "blocked"}
        ][:8]
        failures = [
            item for item in self.failures(40)
            if item["status"] == "open"
        ][:5]
        questions = self.questions(status="open", limit=5)
        return {
            "engine": self.ENGINE_ID,
            "recall_id": recalled["recall_id"],
            "personal": [
                {
                    "kind": item["kind"],
                    "content": item["content"],
                    "importance": item["importance"],
                    "relevance": item["relevance"],
                    "why": item["recall_explanation"]["why"],
                    "tier": item["v4"]["tier"],
                }
                for item in recalled.get("personal", [])
            ],
            "project": [
                {
                    "kind": item["kind"],
                    "content": item["content"],
                    "importance": item["importance"],
                    "relevance": item["relevance"],
                    "why": item["recall_explanation"]["why"],
                    "tier": item["v4"]["tier"],
                }
                for item in recalled.get("project", [])
            ],
            "goals": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "priority": item["priority"],
                }
                for item in active_goals
            ],
            "tasks": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "status": item["status"],
                    "priority": item["priority"],
                    "next_action": item["next_action"],
                    "blocked_reason": item["blocked_reason"],
                }
                for item in open_tasks
            ],
            "failures_to_avoid": [
                {
                    "strategy": item["strategy"],
                    "symptom": item["symptom"],
                    "prevention": item["prevention"],
                    "occurrences": item["occurrences"],
                }
                for item in failures
            ],
            "questions": [
                {
                    "question": item["question"],
                    "reason": item["reason"],
                }
                for item in questions
            ],
        }
