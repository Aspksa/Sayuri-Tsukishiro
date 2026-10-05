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
    QUALITY_GATE_ID = "memory-v4.1-quality"
    MAX_SCAN = 5000
    CLOUD_RECALL_CHAR_BUDGET = 9000
    CLOUD_AUX_CHAR_BUDGET = 7000
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
    _INSTRUCTION_RISK_HIGH = (
        re.compile(r"\bignore\s+(?:all\s+|previous\s+|prior\s+)?(?:instructions?|rules?|system)\b", re.IGNORECASE),
        re.compile(r"\bdo\s+not\s+follow\s+(?:the\s+)?(?:instructions?|rules?)\b", re.IGNORECASE),
        re.compile(r"\b(?:reveal|show|print|leak)\s+(?:the\s+)?(?:system\s+prompt|developer\s+message)\b", re.IGNORECASE),
        re.compile(r"\bигнорируй\s+(?:все\s+|предыдущие\s+|системные\s+)?(?:инструкц|правил)", re.IGNORECASE),
        re.compile(r"\bне\s+следуй\s+(?:предыдущим\s+|системным\s+)?(?:инструкц|правил)", re.IGNORECASE),
        re.compile(r"\b(?:покажи|раскрой|выведи|сообщи)\s+(?:системн(?:ый|ую)\s+)?(?:промпт|инструкц|developer)", re.IGNORECASE),
        re.compile(r"\b(?:system|developer)\s*:\s*(?:ignore|override|forget)\b", re.IGNORECASE),
    )
    _INSTRUCTION_RISK_MEDIUM = (
        re.compile(r"\bprompt\s*injection\b", re.IGNORECASE),
        re.compile(r"\bjailbreak\b", re.IGNORECASE),
        re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE),
        re.compile(r"\bdeveloper\s+message\b", re.IGNORECASE),
        re.compile(r"\bпромпт[- ]?инъекц", re.IGNORECASE),
        re.compile(r"\bсистемн(?:ый|ого|ому|ым|ом)\s+промпт", re.IGNORECASE),
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
                    instruction_risk TEXT NOT NULL DEFAULT 'none',
                    instruction_risk_score REAL NOT NULL DEFAULT 0.0,
                    recall_count INTEGER NOT NULL DEFAULT 0,
                    helpful_count INTEGER NOT NULL DEFAULT 0,
                    unhelpful_count INTEGER NOT NULL DEFAULT 0,
                    last_recalled_at TEXT,
                    evaluated_at TEXT NOT NULL
                )
                """
            )
            state_columns = {
                row["name"]
                for row in db.execute("PRAGMA table_info(memory_v4_state)").fetchall()
            }
            if "instruction_risk" not in state_columns:
                db.execute(
                    "ALTER TABLE memory_v4_state ADD COLUMN instruction_risk TEXT NOT NULL DEFAULT 'none'"
                )
            if "instruction_risk_score" not in state_columns:
                db.execute(
                    "ALTER TABLE memory_v4_state ADD COLUMN instruction_risk_score REAL NOT NULL DEFAULT 0.0"
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
    def classify_instruction_risk(cls, text: str) -> tuple[str, float]:
        value = text or ""
        if any(pattern.search(value) for pattern in cls._INSTRUCTION_RISK_HIGH):
            return "high", 0.95
        if any(pattern.search(value) for pattern in cls._INSTRUCTION_RISK_MEDIUM):
            return "medium", 0.55
        return "none", 0.0

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
        content_text = str(entry.get("content") or "")
        sensitivity, cloud_allowed = self.classify_sensitivity(content_text)
        instruction_risk, instruction_risk_score = self.classify_instruction_risk(content_text)
        cloud_allowed = cloud_allowed and instruction_risk != "high"

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
                    cloud_allowed, instruction_risk, instruction_risk_score,
                    recall_count, helpful_count, unhelpful_count,
                    last_recalled_at, evaluated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    source_key=excluded.source_key,
                    source_trust=excluded.source_trust,
                    freshness_class=excluded.freshness_class,
                    freshness_score=excluded.freshness_score,
                    utility_score=excluded.utility_score,
                    tier=excluded.tier,
                    sensitivity=excluded.sensitivity,
                    cloud_allowed=excluded.cloud_allowed,
                    instruction_risk=excluded.instruction_risk,
                    instruction_risk_score=excluded.instruction_risk_score,
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
                    instruction_risk,
                    instruction_risk_score,
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
            "instruction_risk": instruction_risk,
            "instruction_risk_score": round(instruction_risk_score, 4),
            "cloud_allowed": cloud_allowed,
            "recall_count": recalls,
            "helpful_count": helpful,
            "unhelpful_count": unhelpful,
            "last_recalled_at": last_recalled_at,
            "evaluated_at": now,
        }

    def refresh_memory_states(self) -> dict[str, Any]:
        entries = self.memory.scan_active(limit=self.MAX_SCAN)
        counts = {"hot": 0, "warm": 0, "cold": 0, "protected": 0, "quarantined": 0}
        for entry in entries:
            state = self.evaluate_entry(entry)
            counts[state["tier"]] += 1
            if not state["cloud_allowed"]:
                counts["protected"] += 1
            if state["instruction_risk"] == "high":
                counts["quarantined"] += 1
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
        if state["instruction_risk"] == "high":
            reasons.append("instruction-risk: только локально")
        elif state["instruction_risk"] == "medium":
            reasons.append("instruction-risk: требует осторожности")
        return {
            "memory_id": entry["id"],
            "final_score": round(final_score, 4),
            "semantic_score": round(float((semantic_match or {}).get("score") or 0), 4),
            "source_trust": state["source_trust"],
            "freshness": state["freshness_score"],
            "utility": state["utility_score"],
            "tier": state["tier"],
            "sensitivity": state["sensitivity"],
            "instruction_risk": state["instruction_risk"],
            "instruction_risk_score": state["instruction_risk_score"],
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
        record_usage: bool = True,
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
            mark_used=False,
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
        selected = self._select_diverse_recall(
            ranked,
            min(max(int(limit), 1), 30),
        )
        selected_ids = [entry["id"] for _, entry, _ in selected]
        explanations = [explanation for _, _, explanation in selected]
        prepared_recall = {
            "selected_ids": selected_ids,
            "explanations": explanations,
            "scopes": list(valid_scopes),
            "for_cloud": bool(for_cloud),
        }
        recall_id: str | None = None
        if record_usage:
            recall_id = self.commit_prepared_recall(text, prepared_recall)

        result = {scope: [] for scope in valid_scopes}
        for _, entry, _ in selected:
            result[entry["scope"]].append(entry)
        result.update({
            "recall_id": recall_id,
            "retrieval": self.ENGINE_ID,
            "explanations": explanations,
            "prepared_recall": prepared_recall,
        })
        return result

    def _select_diverse_recall(
        self,
        ranked: list[tuple[float, dict[str, Any], dict[str, Any]]],
        limit: int,
    ) -> list[tuple[float, dict[str, Any], dict[str, Any]]]:
        if not ranked or limit <= 0:
            return []
        pool = list(ranked)
        selected: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        while pool and len(selected) < limit:
            best_index = 0
            best_selection = float("-inf")
            best_redundancy = 0.0
            for index, item in enumerate(pool):
                score, entry, _ = item
                redundancy = 0.0
                same_source = 0
                for _, chosen, _ in selected:
                    similarity = float(
                        self.semantic.score(
                            str(entry.get("content") or ""),
                            str(chosen.get("content") or ""),
                            importance=3,
                            confidence=0.8,
                        )["score"]
                    )
                    redundancy = max(redundancy, similarity)
                    if entry.get("v4", {}).get("source_key") == chosen.get("v4", {}).get("source_key"):
                        same_source += 1
                source_penalty = min(same_source * 0.025, 0.075)
                selection_score = score * 0.82 - redundancy * 0.18 - source_penalty
                if selection_score > best_selection:
                    best_index = index
                    best_selection = selection_score
                    best_redundancy = redundancy

            chosen = pool.pop(best_index)
            explanation = chosen[2]
            explanation["selection_score"] = round(best_selection, 4)
            explanation["redundancy_penalty"] = round(best_redundancy, 4)
            if best_redundancy >= 0.45:
                explanation["why"].append(
                    f"diversity: похожесть с уже выбранной памятью {round(best_redundancy * 100)}%"
                )
            selected.append(chosen)
        return selected

    def commit_prepared_recall(self, query: str, prepared: Any) -> str | None:
        if not isinstance(prepared, dict):
            return None
        selected_ids = [
            str(memory_id)
            for memory_id in prepared.get("selected_ids", [])
            if isinstance(memory_id, str) and memory_id
        ][:30]
        explanations = prepared.get("explanations")
        if not isinstance(explanations, list):
            explanations = []
        scopes = [
            str(scope)
            for scope in prepared.get("scopes", [])
            if scope in {"personal", "project"}
        ]
        if not scopes:
            scopes = ["personal", "project"]

        recall_id = uuid.uuid4().hex
        now = self._now()
        text = (query or "").strip()
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
                    self._json(scopes),
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
        if selected_ids:
            self.memory.mark_used(selected_ids)
        self._audit(
            "memory_recalled",
            "recall",
            recall_id,
            {
                "count": len(selected_ids),
                "scopes": scopes,
                "for_cloud": bool(prepared.get("for_cloud")),
            },
        )
        return recall_id

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
        # Response usefulness measures retrieval utility, not factual truth of the
        # underlying source. Source Trust changes only through explicit validation
        # or a manual override, never from a generic thumbs-up/down.
        for memory_id in memory_ids:
            entry = self.memory.get(memory_id)
            if entry:
                self.evaluate_entry(entry)
        self._audit(
            "recall_feedback",
            "response",
            response_id,
            {
                "rating": normalized,
                "memory_count": len(memory_ids),
                "source_trust_changed": False,
            },
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
            reopened = False
            with self._connect() as db:
                row = db.execute(
                    "SELECT * FROM memory_failures WHERE fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
                if row:
                    reopened = row["status"] == "resolved"
                    db.execute(
                        """
                        UPDATE memory_failures
                        SET occurrences = occurrences + 1,
                            status = 'open',
                            updated_at = ?,
                            source_ref = ?
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
            if reopened:
                self._audit(
                    "failure_reopened",
                    "failure",
                    failure_id,
                    {"tool": tool, "action_id": action_id},
                )
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
                now = self._now()
                effect_id = action_id or uuid.uuid4().hex
                causal_id = self._fingerprint(
                    "failure_observation",
                    row["id"],
                    effect_id,
                    "followed_by_success",
                )
                db.execute(
                    """
                    INSERT OR IGNORE INTO memory_causal_links(
                        id, cause_type, cause_id, effect_type, effect_id,
                        relation, confidence, evidence_json, created_at, updated_at
                    ) VALUES(?, 'failure', ?, 'action', ?, 'followed_by_success', 0.45, ?, ?, ?)
                    """,
                    (
                        causal_id,
                        row["id"],
                        effect_id,
                        self._json({
                            "tool": tool,
                            "result": action.get("result"),
                            "interpretation": "correlation_only",
                        }),
                        now,
                        now,
                    ),
                )
                updated = db.execute(
                    "SELECT * FROM memory_failures WHERE id = ?",
                    (row["id"],),
                ).fetchone()
            self._audit(
                "failure_success_observed",
                "failure",
                row["id"],
                {"action_id": action_id, "causal_claim": False},
            )
            return self._failure_row(updated)
        return None

    def causal_links(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM memory_causal_links
                ORDER BY updated_at DESC LIMIT ?
                """,
                (min(max(int(limit), 1), 300),),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "cause_type": row["cause_type"],
                "cause_id": row["cause_id"],
                "effect_type": row["effect_type"],
                "effect_id": row["effect_id"],
                "relation": row["relation"],
                "confidence": row["confidence"],
                "evidence": self._decode(row["evidence_json"], {}),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def entity_profiles(self, limit: int = 40) -> list[dict[str, Any]]:
        graph = self.memory_v3.graph(limit_nodes=500, limit_edges=1000)
        allowed_types = {"person", "project", "document", "vehicle", "company"}
        nodes = {
            node["id"]: node
            for node in graph.get("nodes", [])
            if node.get("type") in allowed_types
        }
        relations: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in nodes}
        for edge in graph.get("edges", []):
            source = edge.get("source")
            target = edge.get("target")
            if source in nodes:
                other = next(
                    (item for item in graph.get("nodes", []) if item.get("id") == target),
                    None,
                )
                relations[source].append({
                    "direction": "out",
                    "relation": edge.get("relation"),
                    "other": other.get("label") if other else target,
                    "other_type": other.get("type") if other else None,
                })
            if target in nodes:
                other = next(
                    (item for item in graph.get("nodes", []) if item.get("id") == source),
                    None,
                )
                relations[target].append({
                    "direction": "in",
                    "relation": edge.get("relation"),
                    "other": other.get("label") if other else source,
                    "other_type": other.get("type") if other else None,
                })
        profiles = [
            {
                "id": node_id,
                "type": node["type"],
                "label": node["label"],
                "metadata": node.get("metadata") or {},
                "relation_count": len(relations[node_id]),
                "relations": relations[node_id][:12],
            }
            for node_id, node in nodes.items()
        ]
        profiles.sort(
            key=lambda item: (item["relation_count"], item["label"]),
            reverse=True,
        )
        return profiles[: min(max(int(limit), 1), 100)]

    def preference_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, content, importance, source, created_at, updated_at,
                       active, confidence, supersedes_id
                FROM memory_entries
                WHERE scope='personal' AND kind='preference'
                ORDER BY created_at DESC LIMIT ?
                """,
                (min(max(int(limit), 1), 200),),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "content": row["content"],
                "importance": row["importance"],
                "source": row["source"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "active": bool(row["active"]),
                "confidence": row["confidence"],
                "supersedes_id": row["supersedes_id"],
            }
            for row in rows
        ]

    def resolve_failure(
        self,
        failure_id: str,
        *,
        resolution: str,
        cause: str = "",
        prevention: str = "",
    ) -> dict[str, Any]:
        clean_resolution = " ".join((resolution or "").strip().split())
        if not clean_resolution:
            raise MemorySystemV4Error("Нужно указать, как была исправлена ошибка.")
        clean_cause = " ".join((cause or "").strip().split())
        clean_prevention = " ".join((prevention or "").strip().split())
        now = self._now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM memory_failures WHERE id = ?",
                (failure_id,),
            ).fetchone()
            if row is None:
                raise MemorySystemV4Error("Ошибка в Failure Memory не найдена.")

            next_cause = clean_cause[:3000] or row["cause"]
            next_resolution = clean_resolution[:3000]
            next_prevention = clean_prevention[:3000] or row["prevention"]
            same_resolution = (
                row["status"] == "resolved"
                and (row["cause"] or None) == (next_cause or None)
                and (row["resolution"] or "") == next_resolution
                and (row["prevention"] or None) == (next_prevention or None)
            )
            if same_resolution:
                return self._failure_row(row)

            increment = 1 if row["status"] != "resolved" else 0
            db.execute(
                """
                UPDATE memory_failures
                SET cause = ?, resolution = ?, prevention = ?, status = 'resolved',
                    resolved_count = resolved_count + ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    next_cause,
                    next_resolution,
                    next_prevention,
                    increment,
                    now,
                    failure_id,
                ),
            )
            updated = db.execute(
                "SELECT * FROM memory_failures WHERE id = ?",
                (failure_id,),
            ).fetchone()
        self._audit(
            "failure_resolved_by_user",
            "failure",
            failure_id,
            {
                "has_cause": bool(clean_cause),
                "has_prevention": bool(clean_prevention),
                "new_resolution_event": bool(increment),
            },
        )
        return self._failure_row(updated)

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
            # The restored DB can predate both snapshot manifest rows.
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
                            snapshot_id,
                            row["filename"],
                            row["sha256"],
                            row["size_bytes"],
                            row["reason"],
                            row["created_at"],
                        ),
                    )
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

    def integrity_check(self, *, audit: bool = False) -> dict[str, Any]:
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
        if audit:
            self._audit("integrity_checked", "system", None, {"status": result["status"], "issues": len(issues)})
        return result

    def bootstrap(self) -> dict[str, Any]:
        entries = self.memory.scan_active(limit=self.MAX_SCAN)
        with self._connect() as db:
            meta = db.execute(
                "SELECT value FROM memory_v4_meta WHERE key='bootstrap_version'"
            ).fetchone()
        if meta and meta["value"] == "4.1":
            return {
                "entries": len(entries),
                "ingested": 0,
                "states": self.refresh_memory_states(),
                "already_bootstrapped": True,
            }

        ingested = 0
        for entry in entries:
            self.ingest_memory(entry)
            ingested += 1
        now = self._now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO memory_v4_meta(key, value, updated_at)
                VALUES('bootstrap_version', '4.1', ?)
                ON CONFLICT(key) DO UPDATE SET value='4.1', updated_at=excluded.updated_at
                """,
                (now,),
            )
        self._audit(
            "memory_v4_bootstrap",
            "system",
            None,
            {"entries": len(entries), "ingested": ingested},
        )
        states = self.refresh_memory_states()
        verification = self.refresh_verification_questions()
        completed = self._now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO memory_v4_meta(key, value, updated_at)
                VALUES('last_quality_maintenance', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (completed, completed),
            )
        return {
            "entries": len(entries),
            "ingested": ingested,
            "states": states,
            "verification": verification,
            "already_bootstrapped": False,
        }

    def refresh_verification_questions(self) -> dict[str, Any]:
        opened = 0
        checked = 0
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT m.id, m.scope, m.content, m.importance,
                       s.freshness_class, s.freshness_score, s.source_trust
                FROM memory_entries AS m
                JOIN memory_v4_state AS s ON s.memory_id = m.id
                WHERE m.active = 1
                ORDER BY m.importance DESC, m.updated_at DESC
                LIMIT ?
                """,
                (self.MAX_SCAN,),
            ).fetchall()

        for row in rows:
            checked += 1
            importance = int(row["importance"] or 1)
            reason = None
            if (
                importance >= 4
                and row["freshness_class"] == "volatile"
                and float(row["freshness_score"]) < 0.45
            ):
                reason = "freshness_review"
            elif importance >= 4 and float(row["source_trust"]) < 0.45:
                reason = "source_trust_review"
            if reason is None:
                continue

            question_text = (
                f"Проверить актуальность важной памяти: "
                f"«{str(row['content'] or '')[:500]}»"
            )
            fingerprint = self._fingerprint(str(row["scope"] or "project"), question_text)
            with self._connect() as db:
                existed = db.execute(
                    "SELECT 1 FROM memory_questions WHERE fingerprint = ?",
                    (fingerprint,),
                ).fetchone() is not None
            self.open_question(
                question_text,
                scope=str(row["scope"] or "project"),
                reason=reason,
                related_ids=[str(row["id"])],
                source="memory_quality_gate",
            )
            if not existed:
                opened += 1
        return {"checked": checked, "opened": opened}


    def maybe_maintain(self, *, interval_hours: int = 24) -> dict[str, Any]:
        interval_hours = min(max(int(interval_hours), 1), 168)
        with self._connect() as db:
            row = db.execute(
                "SELECT value FROM memory_v4_meta WHERE key='last_quality_maintenance'"
            ).fetchone()
        last = self._parse_time(row["value"]) if row else None
        now = self._now_dt()
        if last and now - last < timedelta(hours=interval_hours):
            return {
                "ran": False,
                "last_maintenance": last.isoformat(),
                "next_after": (last + timedelta(hours=interval_hours)).isoformat(),
            }

        states = self.refresh_memory_states()
        verification = self.refresh_verification_questions()
        integrity = self.integrity_check(audit=False)
        completed = self._now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO memory_v4_meta(key, value, updated_at)
                VALUES('last_quality_maintenance', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (completed, completed),
            )
        self._audit(
            "memory_quality_maintenance",
            "system",
            None,
            {
                "states": states,
                "verification": verification,
                "integrity": integrity["status"],
            },
        )
        return {
            "ran": True,
            "last_maintenance": completed,
            "states": states,
            "verification": verification,
            "integrity": integrity,
        }

    def maintenance(self, *, create_snapshot: bool = False) -> dict[str, Any]:
        snapshot = self.create_snapshot("memory_v4_maintenance") if create_snapshot else None
        states = self.refresh_memory_states()
        verification = self.refresh_verification_questions()
        integrity = self.integrity_check(audit=True)
        return {
            "status": "готово",
            "states": states,
            "verification": verification,
            "integrity": integrity,
            "snapshot": snapshot,
            "stats": self.stats(),
        }

    def stats(self) -> dict[str, Any]:
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
            quarantined = db.execute(
                "SELECT COUNT(*) FROM memory_v4_state WHERE instruction_risk='high'"
            ).fetchone()[0]
            verification_due = db.execute(
                """
                SELECT COUNT(*) FROM memory_questions
                WHERE status='open'
                  AND reason IN ('freshness_review','source_trust_review')
                """
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
            causal = db.execute(
                "SELECT COUNT(*) FROM memory_causal_links"
            ).fetchone()[0]
            audits = db.execute(
                "SELECT COUNT(*) FROM memory_audit_log"
            ).fetchone()[0]
        return {
            "version": "4.1",
            "engine": self.ENGINE_ID,
            "quality_gate": self.QUALITY_GATE_ID,
            "hot": tiers.get("hot", 0),
            "warm": tiers.get("warm", 0),
            "cold": tiers.get("cold", 0),
            "protected": protected,
            "quarantined": quarantined,
            "verification_due": verification_due,
            "active_goals": goals,
            "open_tasks": tasks,
            "blocked_tasks": blocked,
            "active_decisions": decisions,
            "open_failures": failures,
            "open_questions": questions,
            "recalls": recalls,
            "snapshots": snapshots,
            "causal_links": causal,
            "audit_events": audits,
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
            "causal_links": self.causal_links(30),
            "questions": self.questions(status="open", limit=30),
            "preferences": self.preference_history(30),
            "entities": self.entity_profiles(30),
            "sources": self._source_profiles(30),
            "recalls": self.recall_audit(20),
            "audit": self.audit_log(30),
            "integrity": integrity,
            "snapshots": self.snapshots(20),
        }

    @classmethod
    def _cloud_text_allowed(cls, *parts: Any) -> bool:
        text = " ".join(
            str(part)
            for part in parts
            if part is not None and str(part).strip()
        )
        if not text:
            return True
        sensitive_allowed = cls.classify_sensitivity(text)[1]
        instruction_risk, _ = cls.classify_instruction_risk(text)
        return sensitive_allowed and instruction_risk != "high"

    def _memory_cloud_allowed(self, memory_id: str | None) -> bool:
        if not memory_id:
            return True
        with self._connect() as db:
            row = db.execute(
                "SELECT cloud_allowed FROM memory_v4_state WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        if row is not None:
            return bool(row["cloud_allowed"])
        entry = self.memory.get(memory_id, include_inactive=True)
        if entry is None:
            return False
        return bool(self.evaluate_entry(entry)["cloud_allowed"])

    def _all_memory_sources_cloud_allowed(self, source_ids: Iterable[str]) -> bool:
        return all(self._memory_cloud_allowed(str(memory_id)) for memory_id in source_ids)

    def sanitize_memory_v3_context(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {
                "working": [],
                "knowledge": [],
                "episodes": [],
                "conflicts": [],
                "open_conflicts": 0,
                "engine": "memory-v3",
            }

        working = []
        for item in payload.get("working", []):
            if not isinstance(item, dict):
                continue
            if self._cloud_text_allowed(self._json(item.get("value"), 6000)):
                working.append(item)

        knowledge = []
        for item in payload.get("knowledge", []):
            if not isinstance(item, dict):
                continue
            source_ids = item.get("source_memory_ids") if isinstance(item.get("source_memory_ids"), list) else []
            if not self._cloud_text_allowed(item.get("statement")):
                continue
            if source_ids and not self._all_memory_sources_cloud_allowed(source_ids):
                continue
            knowledge.append(item)

        episodes = []
        for item in payload.get("episodes", []):
            if not isinstance(item, dict):
                continue
            if self._cloud_text_allowed(
                item.get("summary"),
                self._json(item.get("details"), 6000),
            ):
                episodes.append(item)

        conflicts = []
        for item in payload.get("conflicts", []):
            if not isinstance(item, dict):
                continue
            if not self._memory_cloud_allowed(item.get("old_memory_id")):
                continue
            if not self._memory_cloud_allowed(item.get("new_memory_id")):
                continue
            if not self._cloud_text_allowed(item.get("old_content"), item.get("new_content")):
                continue
            conflicts.append(item)

        return {
            "working": working[:2],
            "knowledge": knowledge[:6],
            "episodes": episodes[:4],
            "conflicts": conflicts[:6],
            "open_conflicts": len(conflicts),
            "engine": str(payload.get("engine") or "memory-v3"),
        }

    def sanitize_experience_context(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"retrieval": "hybrid_semantic_v1", "helpful": [], "avoid": []}

        def safe_items(name: str) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for item in payload.get(name, []):
                if not isinstance(item, dict):
                    continue
                if not self._cloud_text_allowed(
                    item.get("strategy"),
                    item.get("category"),
                    self._json(item.get("details"), 6000),
                ):
                    continue
                result.append(item)
            return result[:4]

        return {
            "retrieval": str(payload.get("retrieval") or "hybrid_semantic_v1"),
            "helpful": safe_items("helpful"),
            "avoid": safe_items("avoid"),
        }

    @staticmethod
    def _compact_text(value: Any, limit: int) -> tuple[str | None, bool]:
        if value is None:
            return None, False
        text = str(value)
        if len(text) <= limit:
            return text, False
        return text[: max(limit - 1, 1)].rstrip() + "…", True

    def _budget_recalled_memories(
        self,
        recalled: dict[str, Any],
        *,
        char_budget: int | None = None,
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
        budget = max(int(char_budget or self.CLOUD_RECALL_CHAR_BUDGET), 1000)
        candidates: list[tuple[float, str, dict[str, Any], dict[str, Any]]] = []
        for scope in ("personal", "project"):
            for item in recalled.get(scope, []):
                if not isinstance(item, dict):
                    continue
                compact_content, truncated = self._compact_text(item.get("content"), 2400)
                compact = {
                    "memory_id": item.get("id"),
                    "kind": item.get("kind"),
                    "content": compact_content or "",
                    "importance": item.get("importance"),
                    "relevance": item.get("relevance"),
                    "why": list(item.get("recall_explanation", {}).get("why") or [])[:6],
                    "tier": item.get("v4", {}).get("tier"),
                    "content_truncated": truncated,
                }
                candidates.append(
                    (
                        float(item.get("relevance") or 0.0),
                        scope,
                        compact,
                        item,
                    )
                )
        candidates.sort(key=lambda row: row[0], reverse=True)

        selected: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        used = 2
        for _, scope, compact, original in candidates:
            encoded = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
            cost = len(encoded) + 1
            if selected and used + cost > budget:
                continue
            if not selected and cost > budget:
                compact = dict(compact)
                compact_content, _ = self._compact_text(compact.get("content"), 700)
                compact["content"] = compact_content or ""
                compact["content_truncated"] = True
                compact["why"] = compact["why"][:3]
                encoded = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
                cost = len(encoded) + 1
            if used + cost > budget:
                continue
            selected.append((scope, compact, original))
            used += cost

        result = {"personal": [], "project": []}
        selected_ids: list[str] = []
        explanations: list[dict[str, Any]] = []
        for scope, compact, original in selected:
            result[scope].append(compact)
            memory_id = original.get("id")
            if isinstance(memory_id, str) and memory_id:
                selected_ids.append(memory_id)
            explanation = original.get("recall_explanation")
            if isinstance(explanation, dict):
                explanations.append(explanation)

        original_prepared = recalled.get("prepared_recall")
        prepared = {
            "selected_ids": selected_ids,
            "explanations": explanations,
            "scopes": (
                list(original_prepared.get("scopes", []))
                if isinstance(original_prepared, dict)
                else ["personal", "project"]
            ),
            "for_cloud": True,
        }
        meta = {
            "char_budget": budget,
            "used_chars": used,
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "dropped_count": max(0, len(candidates) - len(selected)),
        }
        return result, prepared, meta

    def _budget_aux_context(
        self,
        *,
        goals: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        failures: list[dict[str, Any]],
        questions: list[dict[str, Any]],
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
        sections = {
            "tasks": tasks,
            "goals": goals,
            "failures_to_avoid": failures,
            "questions": questions,
        }
        limits = {
            "tasks": {"title": 700, "next_action": 900, "blocked_reason": 700},
            "goals": {"title": 700},
            "failures_to_avoid": {"strategy": 300, "symptom": 900, "prevention": 900},
            "questions": {"question": 900, "reason": 300},
        }
        output = {name: [] for name in sections}
        budget = self.CLOUD_AUX_CHAR_BUDGET
        used = 2
        positions = {name: 0 for name in sections}
        order = ("tasks", "goals", "failures_to_avoid", "questions")

        while True:
            progressed = False
            for name in order:
                items = sections[name]
                index = positions[name]
                if index >= len(items):
                    continue
                positions[name] += 1
                item = dict(items[index])
                for field, max_chars in limits[name].items():
                    if field in item:
                        compact, truncated = self._compact_text(item.get(field), max_chars)
                        item[field] = compact
                        if truncated:
                            item[f"{field}_truncated"] = True
                encoded = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                cost = len(encoded) + 1
                if used + cost > budget:
                    continue
                output[name].append(item)
                used += cost
                progressed = True
            if not progressed:
                break

        total_candidates = sum(len(items) for items in sections.values())
        total_selected = sum(len(items) for items in output.values())
        return output, {
            "char_budget": budget,
            "used_chars": used,
            "candidate_count": total_candidates,
            "selected_count": total_selected,
            "dropped_count": max(0, total_candidates - total_selected),
        }

    def context(self, query: str, *, record_usage: bool = True) -> dict[str, Any]:
        recalled = self.recall(
            query,
            limit=10,
            for_cloud=True,
            record_usage=False,
        )
        budgeted_memory, prepared_recall, recall_budget = self._budget_recalled_memories(recalled)

        active_goals = [
            item
            for item in self.goals(status="active", limit=30)
            if self._memory_cloud_allowed(item.get("source_memory_id"))
            and self._cloud_text_allowed(item.get("title"), item.get("description"))
        ][:8]

        open_tasks = [
            item
            for item in self.tasks(limit=80)
            if item["status"] in {"planned", "in_progress", "blocked"}
            and self._memory_cloud_allowed(item.get("source_memory_id"))
            and self._cloud_text_allowed(
                item.get("title"),
                item.get("next_action"),
                item.get("blocked_reason"),
            )
        ][:8]

        failures = [
            item
            for item in self.failures(80)
            if item["status"] == "open"
            and self._cloud_text_allowed(
                item.get("strategy"),
                item.get("symptom"),
                item.get("cause"),
                item.get("prevention"),
            )
        ][:5]

        questions = [
            item
            for item in self.questions(status="open", limit=30)
            if self._cloud_text_allowed(item.get("question"), item.get("reason"))
        ][:5]
        compact_goals = [
            {
                "id": item["id"],
                "title": item["title"],
                "priority": item["priority"],
            }
            for item in active_goals
        ]
        compact_tasks = [
            {
                "id": item["id"],
                "title": item["title"],
                "status": item["status"],
                "priority": item["priority"],
                "next_action": item["next_action"],
                "blocked_reason": item["blocked_reason"],
            }
            for item in open_tasks
        ]
        compact_failures = [
            {
                "strategy": item["strategy"],
                "symptom": item["symptom"],
                "prevention": item["prevention"],
                "occurrences": item["occurrences"],
            }
            for item in failures
        ]
        compact_questions = [
            {
                "question": item["question"],
                "reason": item["reason"],
            }
            for item in questions
        ]
        aux_context, aux_budget = self._budget_aux_context(
            goals=compact_goals,
            tasks=compact_tasks,
            failures=compact_failures,
            questions=compact_questions,
        )
        recall_id = (
            self.commit_prepared_recall(query, prepared_recall)
            if record_usage
            else None
        )
        return {
            "engine": self.ENGINE_ID,
            "recall_id": recall_id,
            "_prepared_recall": prepared_recall,
            "context_budget": {
                "recall": recall_budget,
                "aux": aux_budget,
            },
            "personal": budgeted_memory["personal"],
            "project": budgeted_memory["project"],
            "goals": aux_context["goals"],
            "tasks": aux_context["tasks"],
            "failures_to_avoid": aux_context["failures_to_avoid"],
            "questions": aux_context["questions"],
        }
