from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import exp, log1p
from pathlib import Path
from typing import Any
import hashlib
import json
import re
import sqlite3
import uuid

from .memory import SayuriMemory
from .semantic_memory import SemanticMemoryIndex


class MemorySystemError(ValueError):
    pass


class MemorySystemV3:
    """Memory 3.0: working, episodic, knowledge, temporal and graph memory."""

    WORKING_TTL_HOURS = 24
    CONSOLIDATION_THRESHOLD = 0.72
    STALE_THRESHOLD = 0.30

    def __init__(self, path: Path, memory: SayuriMemory, semantic: SemanticMemoryIndex):
        self.path = path
        self.memory = memory
        self.semantic = semantic
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
    def _normalize(text: str) -> str:
        return " ".join((text or "").casefold().replace("ё", "е").split())

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
                CREATE TABLE IF NOT EXISTS working_memory (
                    key TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    importance INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details_json TEXT,
                    source TEXT NOT NULL,
                    importance INTEGER NOT NULL,
                    occurred_at TEXT NOT NULL,
                    fingerprint TEXT
                )
                """
            )
            episode_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(episodic_memory)").fetchall()
            }
            if "fingerprint" not in episode_columns:
                db.execute("ALTER TABLE episodic_memory ADD COLUMN fingerprint TEXT")
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodes_time ON episodic_memory(occurred_at DESC)"
            )
            db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_episodes_fingerprint
                ON episodic_memory(fingerprint)
                WHERE fingerprint IS NOT NULL
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_items (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    normalized TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    source_memory_ids_json TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT,
                    supersedes_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(scope, kind, normalized)
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_status ON knowledge_items(status, updated_at DESC)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_graph_nodes (
                    id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL,
                    node_key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(node_type, node_key)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_graph_edges (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    weight REAL NOT NULL,
                    source_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_id, target_id, relation)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_timeline (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT,
                    scope TEXT,
                    summary TEXT NOT NULL,
                    details_json TEXT,
                    occurred_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_timeline_time ON memory_timeline(occurred_at DESC)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_conflicts (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    candidate_id TEXT,
                    old_memory_id TEXT NOT NULL,
                    new_memory_id TEXT NOT NULL,
                    old_content TEXT NOT NULL,
                    new_content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resolution TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    UNIQUE(old_memory_id, new_memory_id)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_consolidations (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    knowledge_id TEXT NOT NULL,
                    source_memory_ids_json TEXT NOT NULL,
                    similarity REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(knowledge_id, source_memory_ids_json)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_v3_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

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
    def _json(value: Any, limit: int = 16000) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:limit]

    @staticmethod
    def _decode(value: str | None, fallback: Any = None) -> Any:
        if not value:
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback

    def _timeline(
        self,
        *,
        event_type: str,
        subject_type: str,
        subject_id: str | None,
        scope: str | None,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_id = uuid.uuid4().hex
        now = self._now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO memory_timeline(
                    id, event_type, subject_type, subject_id, scope,
                    summary, details_json, occurred_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type[:80],
                    subject_type[:80],
                    subject_id,
                    scope,
                    summary[:1200],
                    self._json(details) if details else None,
                    now,
                ),
            )
        return {
            "id": event_id,
            "event_type": event_type,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "scope": scope,
            "summary": summary,
            "details": details,
            "occurred_at": now,
        }

    def update_working(self, *, message: str, context: Any = None) -> dict[str, Any]:
        now = self._now_dt()
        expires = now + timedelta(hours=self.WORKING_TTL_HOURS)
        safe_context = self._safe_context(context)
        items = {
            "current_focus": {
                "scope": "session",
                "value": {"message": " ".join((message or "").strip().split())[:3000]},
                "importance": 5,
            },
            "current_context": {
                "scope": "session",
                "value": safe_context,
                "importance": 4,
            },
        }
        with self._connect() as db:
            for key, item in items.items():
                db.execute(
                    """
                    INSERT INTO working_memory(key, scope, value_json, importance, updated_at, expires_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        scope=excluded.scope,
                        value_json=excluded.value_json,
                        importance=excluded.importance,
                        updated_at=excluded.updated_at,
                        expires_at=excluded.expires_at
                    """,
                    (
                        key,
                        item["scope"],
                        self._json(item["value"]),
                        item["importance"],
                        now.isoformat(),
                        expires.isoformat(),
                    ),
                )
        return self.working()

    def working(self) -> dict[str, Any]:
        now = self._now()
        with self._connect() as db:
            db.execute(
                "DELETE FROM working_memory WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            )
            rows = db.execute(
                "SELECT * FROM working_memory ORDER BY importance DESC, updated_at DESC"
            ).fetchall()
        return {
            "ttl_hours": self.WORKING_TTL_HOURS,
            "items": [
                {
                    "key": row["key"],
                    "scope": row["scope"],
                    "value": self._decode(row["value_json"], {}),
                    "importance": row["importance"],
                    "updated_at": row["updated_at"],
                    "expires_at": row["expires_at"],
                }
                for row in rows
            ],
        }

    def record_episode(
        self,
        *,
        event_type: str,
        summary: str,
        scope: str = "project",
        details: dict[str, Any] | None = None,
        source: str = "system",
        importance: int = 3,
        fingerprint: str | None = None,
    ) -> dict[str, Any]:
        if scope not in {"personal", "project", "system"}:
            raise MemorySystemError("Недопустимая область эпизодической памяти.")
        text = " ".join((summary or "").strip().split())
        if not text:
            raise MemorySystemError("Событие памяти не может быть пустым.")
        event_id = uuid.uuid4().hex
        now = self._now()
        importance = min(max(int(importance), 1), 5)
        safe_fingerprint = (
            fingerprint.strip()[:300]
            if isinstance(fingerprint, str) and fingerprint.strip()
            else None
        )
        with self._connect() as db:
            existing = None
            if safe_fingerprint:
                existing = db.execute(
                    "SELECT id FROM episodic_memory WHERE fingerprint = ?",
                    (safe_fingerprint,),
                ).fetchone()
            if existing:
                event_id = existing["id"]
                db.execute(
                    """
                    UPDATE episodic_memory
                    SET scope = ?, event_type = ?, summary = ?, details_json = ?,
                        source = ?, importance = ?, occurred_at = ?
                    WHERE id = ?
                    """,
                    (
                        scope,
                        event_type[:80],
                        text[:2000],
                        self._json(details) if details else None,
                        (source or "system")[:80],
                        importance,
                        now,
                        event_id,
                    ),
                )
            else:
                db.execute(
                    """
                    INSERT INTO episodic_memory(
                        id, scope, event_type, summary, details_json,
                        source, importance, occurred_at, fingerprint
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        scope,
                        event_type[:80],
                        text[:2000],
                        self._json(details) if details else None,
                        (source or "system")[:80],
                        importance,
                        now,
                        safe_fingerprint,
                    ),
                )
        self._timeline(
            event_type=event_type,
            subject_type="episode",
            subject_id=event_id,
            scope=scope,
            summary=text,
            details=details,
        )
        with self._connect() as db:
            event_node = self._ensure_node(
                db,
                node_type="event",
                node_key=event_id,
                label=text[:220],
                metadata={"event_type": event_type, "scope": scope, "source": source},
            )
            owner_type = "person" if scope == "personal" else "project"
            owner_key = "master" if scope == "personal" else "sayuri-tsukishiro"
            owner_label = "Господин" if scope == "personal" else "Sayuri Tsukishiro"
            owner = self._ensure_node(
                db,
                node_type=owner_type,
                node_key=owner_key,
                label=owner_label,
            )
            self._ensure_edge(
                db,
                source_id=owner,
                target_id=event_node,
                relation="experienced",
                source_ref=event_id,
            )
        return {
            "id": event_id,
            "scope": scope,
            "event_type": event_type,
            "summary": text,
            "details": details,
            "source": source,
            "importance": importance,
            "occurred_at": now,
        }

    def episodes(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 200)
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM episodic_memory ORDER BY occurred_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "scope": row["scope"],
                "event_type": row["event_type"],
                "summary": row["summary"],
                "details": self._decode(row["details_json"]),
                "source": row["source"],
                "importance": row["importance"],
                "occurred_at": row["occurred_at"],
                "fingerprint": row["fingerprint"] if "fingerprint" in row.keys() else None,
            }
            for row in rows
        ]

    def _ensure_node(
        self,
        db: sqlite3.Connection,
        *,
        node_type: str,
        node_key: str,
        label: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        row = db.execute(
            "SELECT id FROM memory_graph_nodes WHERE node_type = ? AND node_key = ?",
            (node_type, node_key),
        ).fetchone()
        now = self._now()
        if row:
            db.execute(
                """
                UPDATE memory_graph_nodes
                SET label = ?, metadata_json = COALESCE(?, metadata_json), updated_at = ?
                WHERE id = ?
                """,
                (label[:500], self._json(metadata) if metadata else None, now, row["id"]),
            )
            return row["id"]
        node_id = uuid.uuid4().hex
        db.execute(
            """
            INSERT INTO memory_graph_nodes(
                id, node_type, node_key, label, metadata_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id,
                node_type[:80],
                node_key[:500],
                label[:500],
                self._json(metadata) if metadata else None,
                now,
                now,
            ),
        )
        return node_id

    def _ensure_edge(
        self,
        db: sqlite3.Connection,
        *,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
        source_ref: str | None = None,
    ) -> str:
        row = db.execute(
            """
            SELECT id FROM memory_graph_edges
            WHERE source_id = ? AND target_id = ? AND relation = ?
            """,
            (source_id, target_id, relation),
        ).fetchone()
        now = self._now()
        if row:
            db.execute(
                """
                UPDATE memory_graph_edges
                SET weight = MAX(weight, ?), source_ref = COALESCE(?, source_ref), updated_at = ?
                WHERE id = ?
                """,
                (max(0.0, min(float(weight), 1.0)), source_ref, now, row["id"]),
            )
            return row["id"]
        edge_id = uuid.uuid4().hex
        db.execute(
            """
            INSERT INTO memory_graph_edges(
                id, source_id, target_id, relation, weight, source_ref, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                source_id,
                target_id,
                relation[:80],
                max(0.0, min(float(weight), 1.0)),
                source_ref,
                now,
                now,
            ),
        )
        return edge_id

    @staticmethod
    def _extract_entity_keys(text: str) -> list[tuple[str, str, str]]:
        found: list[tuple[str, str, str]] = []
        for match in re.finditer(r"\b[A-HJ-NPR-Z0-9]{17}\b", text or "", flags=re.IGNORECASE):
            value = match.group(0).upper()
            found.append(("vehicle", "vin:" + value, "VIN " + value))
        plate_re = r"\b[АВЕКМНОРСТУХABEKMHOPCTYX]\d{3}[АВЕКМНОРСТУХABEKMHOPCTYX]{2}\d{2,3}\b"
        for match in re.finditer(plate_re, text or "", flags=re.IGNORECASE):
            value = match.group(0).upper()
            found.append(("vehicle", "plate:" + value, "Госномер " + value))

        company_re = r"\b(ООО|АО|ПАО|ИП)\s+[«\"']?([А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9 ._-]{2,70})"
        for match in re.finditer(company_re, text or ""):
            legal_form = match.group(1)
            name = " ".join(match.group(2).strip(" ._-«»\"'").split())
            if not name:
                continue
            label = f"{legal_form} {name}"
            found.append(("company", "company:" + label.casefold(), label))
        return list(dict.fromkeys(found))

    def ingest_memory(
        self,
        entry: dict[str, Any],
        *,
        timeline: bool = True,
        event_type: str = "memory_saved",
    ) -> dict[str, Any]:
        entry_id = str(entry.get("id") or "")
        if not entry_id:
            raise MemorySystemError("У записи памяти нет ID.")
        scope = str(entry.get("scope") or "project")
        kind = str(entry.get("kind") or "note")
        content = str(entry.get("content") or "")
        source_context = entry.get("source_context") if isinstance(entry.get("source_context"), dict) else {}
        with self._connect() as db:
            memory_node = self._ensure_node(
                db,
                node_type="memory",
                node_key=entry_id,
                label=content[:180] or entry_id,
                metadata={"scope": scope, "kind": kind, "importance": entry.get("importance")},
            )
            if scope == "personal":
                owner = self._ensure_node(
                    db,
                    node_type="person",
                    node_key="master",
                    label="Господин",
                )
                self._ensure_edge(
                    db,
                    source_id=owner,
                    target_id=memory_node,
                    relation="has_memory",
                    source_ref=entry_id,
                )
            else:
                project = self._ensure_node(
                    db,
                    node_type="project",
                    node_key="sayuri-tsukishiro",
                    label="Sayuri Tsukishiro",
                )
                self._ensure_edge(
                    db,
                    source_id=project,
                    target_id=memory_node,
                    relation="has_memory",
                    source_ref=entry_id,
                )

            if kind == "decision":
                decision = self._ensure_node(
                    db,
                    node_type="decision",
                    node_key=entry_id,
                    label=content[:220],
                    metadata={"scope": scope},
                )
                self._ensure_edge(
                    db,
                    source_id=decision,
                    target_id=memory_node,
                    relation="grounded_in",
                    source_ref=entry_id,
                )

            current = source_context.get("current_document")
            if isinstance(current, dict) and isinstance(current.get("id"), str):
                document = self._ensure_node(
                    db,
                    node_type="document",
                    node_key=current["id"],
                    label=str(current.get("name") or current["id"]),
                    metadata={
                        "kind": current.get("kind"),
                        "category": current.get("category"),
                    },
                )
                self._ensure_edge(
                    db,
                    source_id=document,
                    target_id=memory_node,
                    relation="source_for",
                    source_ref=entry_id,
                )

            for node_type, node_key, label in self._extract_entity_keys(content):
                entity = self._ensure_node(
                    db,
                    node_type=node_type,
                    node_key=node_key,
                    label=label,
                )
                self._ensure_edge(
                    db,
                    source_id=memory_node,
                    target_id=entity,
                    relation="mentions",
                    source_ref=entry_id,
                )

            supersedes = entry.get("supersedes_id")
            if isinstance(supersedes, str) and supersedes:
                old_node = self._ensure_node(
                    db,
                    node_type="memory",
                    node_key=supersedes,
                    label="Предыдущая версия памяти",
                )
                self._ensure_edge(
                    db,
                    source_id=memory_node,
                    target_id=old_node,
                    relation="supersedes",
                    source_ref=entry_id,
                )

        knowledge = self._promote_if_ready(entry)
        if timeline:
            self._timeline(
                event_type=event_type,
                subject_type="memory",
                subject_id=entry_id,
                scope=scope,
                summary=content[:800],
                details={"kind": kind, "source": entry.get("source")},
            )
        return {"memory_id": entry_id, "knowledge": knowledge}

    @staticmethod
    def _knowledge_ready(entry: dict[str, Any]) -> bool:
        kind = str(entry.get("kind") or "")
        importance = int(entry.get("importance") or 0)
        confidence = entry.get("confidence")
        confidence_value = 0.72 if confidence is None else float(confidence)
        uses = int(entry.get("use_count") or 0)
        if kind == "decision" and importance >= 4:
            return True
        if kind in {"fact", "preference"} and importance >= 4 and confidence_value >= 0.78:
            return True
        return importance >= 4 and uses >= 3 and confidence_value >= 0.70

    def _promote_if_ready(
        self,
        entry: dict[str, Any],
        *,
        source_ids: list[str] | None = None,
        confidence_override: float | None = None,
    ) -> dict[str, Any] | None:
        if not self._knowledge_ready(entry) and not source_ids:
            return None
        statement = " ".join(str(entry.get("content") or "").split())
        if not statement:
            return None
        scope = str(entry.get("scope") or "project")
        kind = str(entry.get("kind") or "fact")
        normalized = self._normalize(statement)
        ids = list(dict.fromkeys(source_ids or [str(entry.get("id") or "")]))
        ids = [item for item in ids if item]
        confidence = confidence_override
        if confidence is None:
            raw = entry.get("confidence")
            confidence = 0.82 if raw is None else float(raw)
        confidence = max(0.0, min(float(confidence), 1.0))
        now = self._now()

        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM knowledge_items
                WHERE scope = ? AND kind = ? AND normalized = ?
                """,
                (scope, kind, normalized),
            ).fetchone()
            if row:
                existing_ids = self._decode(row["source_memory_ids_json"], [])
                merged_ids = list(dict.fromkeys([*existing_ids, *ids]))
                db.execute(
                    """
                    UPDATE knowledge_items
                    SET confidence = MAX(confidence, ?),
                        source_memory_ids_json = ?,
                        status = 'confirmed',
                        valid_to = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (confidence, self._json(merged_ids), now, row["id"]),
                )
                knowledge_id = row["id"]
            else:
                knowledge_id = uuid.uuid4().hex
                db.execute(
                    """
                    INSERT INTO knowledge_items(
                        id, scope, kind, statement, normalized, confidence,
                        status, source_memory_ids_json, valid_from, valid_to,
                        supersedes_id, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        knowledge_id,
                        scope,
                        kind,
                        statement[:8000],
                        normalized,
                        confidence,
                        self._json(ids),
                        now,
                        entry.get("supersedes_id"),
                        now,
                        now,
                    ),
                )
            knowledge_node = self._ensure_node(
                db,
                node_type="knowledge",
                node_key=knowledge_id,
                label=statement[:220],
                metadata={"scope": scope, "kind": kind, "confidence": confidence},
            )
            for source_id in ids:
                memory_node = self._ensure_node(
                    db,
                    node_type="memory",
                    node_key=source_id,
                    label="Источник знания",
                )
                self._ensure_edge(
                    db,
                    source_id=memory_node,
                    target_id=knowledge_node,
                    relation="supports",
                    source_ref=source_id,
                )

        return self.get_knowledge(knowledge_id)

    def get_knowledge(self, knowledge_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM knowledge_items WHERE id = ?", (knowledge_id,)).fetchone()
        return self._knowledge_row(row) if row else None

    def _knowledge_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "scope": row["scope"],
            "kind": row["kind"],
            "statement": row["statement"],
            "confidence": row["confidence"],
            "status": row["status"],
            "source_memory_ids": self._decode(row["source_memory_ids_json"], []),
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "supersedes_id": row["supersedes_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def knowledge(self, limit: int = 100, *, status: str | None = "confirmed") -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 300)
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.append(safe_limit)
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM knowledge_items {where} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._knowledge_row(row) for row in rows]

    def bootstrap(self) -> dict[str, Any]:
        entries = self.memory.scan_active(limit=5000)
        promoted = 0
        for entry in entries:
            result = self.ingest_memory(entry, timeline=False)
            if result.get("knowledge"):
                promoted += 1
        retention = self.evaluate_retention()
        return {
            "entries": len(entries),
            "knowledge_promoted": promoted,
            "retention": retention,
        }

    def retention_snapshot(self) -> dict[str, Any]:
        entries = self.memory.scan_active(limit=5000)
        stale = [
            {
                "id": entry["id"],
                "scope": entry["scope"],
                "kind": entry["kind"],
                "content": entry["content"],
                "retention_score": round(float(entry.get("retention_score", 1.0)), 4),
            }
            for entry in entries
            if float(entry.get("retention_score", 1.0)) < self.STALE_THRESHOLD
        ]
        return {
            "updated": 0,
            "stale_count": len(stale),
            "threshold": self.STALE_THRESHOLD,
            "stale": sorted(stale, key=lambda item: item["retention_score"])[:50],
        }

    def evaluate_retention(self) -> dict[str, Any]:
        entries = self.memory.scan_active(limit=5000)
        now = self._now_dt()
        stale: list[dict[str, Any]] = []
        updated = 0
        for entry in entries:
            importance = min(max(int(entry.get("importance") or 1), 1), 5) / 5.0
            confidence = entry.get("confidence")
            confidence_score = 0.62 if confidence is None else max(0.0, min(float(confidence), 1.0))
            use_count = max(int(entry.get("use_count") or 0), 0)
            use_score = min(log1p(use_count) / log1p(12), 1.0)
            anchor = self._parse_time(entry.get("last_used_at")) or self._parse_time(entry.get("updated_at")) or now
            age_days = max((now - anchor).total_seconds() / 86400.0, 0.0)
            recency = exp(-age_days / 180.0)
            score = importance * 0.38 + confidence_score * 0.22 + use_score * 0.20 + recency * 0.20

            kind = str(entry.get("kind") or "")
            if kind == "decision" and int(entry.get("importance") or 0) >= 4:
                score = max(score, 0.82)
            elif kind == "preference" and int(entry.get("importance") or 0) >= 4:
                score = max(score, 0.72)

            score = max(0.0, min(score, 1.0))
            self.memory.set_retention(entry["id"], score)
            updated += 1
            if score < self.STALE_THRESHOLD:
                stale.append({
                    "id": entry["id"],
                    "scope": entry["scope"],
                    "kind": entry["kind"],
                    "content": entry["content"],
                    "retention_score": round(score, 4),
                    "age_days": round(age_days, 1),
                })

        return {
            "updated": updated,
            "stale_count": len(stale),
            "threshold": self.STALE_THRESHOLD,
            "stale": sorted(stale, key=lambda item: item["retention_score"])[:50],
        }

    def consolidate(self) -> dict[str, Any]:
        entries = self.memory.scan_active(limit=5000)
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for entry in entries:
            groups.setdefault((entry["scope"], entry["kind"]), []).append(entry)

        created = 0
        seen_pairs: set[tuple[str, str]] = set()
        for (scope, kind), items in groups.items():
            items = items[:120]
            for index, left in enumerate(items):
                cluster = [left]
                scores: list[float] = []
                for right in items[index + 1:]:
                    pair = tuple(sorted((left["id"], right["id"])))
                    if pair in seen_pairs:
                        continue
                    details = self.semantic.score(
                        left["content"],
                        right["content"],
                        importance=max(left["importance"], right["importance"]),
                        confidence=max(
                            float(left.get("confidence") or 0.5),
                            float(right.get("confidence") or 0.5),
                        ),
                    )
                    similarity = float(details["score"])
                    if similarity < self.CONSOLIDATION_THRESHOLD:
                        continue
                    seen_pairs.add(pair)
                    cluster.append(right)
                    scores.append(similarity)

                if len(cluster) < 2:
                    continue
                source_ids = sorted({item["id"] for item in cluster})
                fingerprint = hashlib.sha256("|".join(source_ids).encode("utf-8")).hexdigest()
                with self._connect() as db:
                    exists = db.execute(
                        "SELECT id FROM memory_consolidations WHERE id = ?",
                        (fingerprint,),
                    ).fetchone()
                if exists:
                    continue

                canonical = max(
                    cluster,
                    key=lambda item: (
                        int(item.get("importance") or 0),
                        float(item.get("confidence") or 0.5),
                        int(item.get("use_count") or 0),
                        item.get("updated_at") or "",
                    ),
                )
                confidence = min(
                    0.99,
                    max(float(item.get("confidence") or 0.6) for item in cluster)
                    + min(0.10, 0.02 * (len(cluster) - 1)),
                )
                knowledge = self._promote_if_ready(
                    canonical,
                    source_ids=source_ids,
                    confidence_override=confidence,
                )
                if not knowledge:
                    continue
                with self._connect() as db:
                    db.execute(
                        """
                        INSERT INTO memory_consolidations(
                            id, scope, kind, knowledge_id,
                            source_memory_ids_json, similarity, created_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            fingerprint,
                            scope,
                            kind,
                            knowledge["id"],
                            self._json(source_ids),
                            min(scores) if scores else 1.0,
                            self._now(),
                        ),
                    )
                created += 1

        if created:
            self._timeline(
                event_type="memory_consolidated",
                subject_type="knowledge",
                subject_id=None,
                scope="system",
                summary=f"Memory 3.0 создала устойчивые знания из похожих записей: {created}.",
                details={"created": created},
            )
        return {"created": created, "threshold": self.CONSOLIDATION_THRESHOLD}

    def register_conflict(
        self,
        *,
        candidate_id: str | None,
        old_memory_id: str,
        new_memory_id: str,
        scope: str,
    ) -> dict[str, Any] | None:
        old = self.memory.get(old_memory_id, include_inactive=True)
        new = self.memory.get(new_memory_id, include_inactive=True)
        if not old or not new:
            return None
        now = self._now()
        conflict_id = hashlib.sha256(f"{old_memory_id}|{new_memory_id}".encode("utf-8")).hexdigest()
        with self._connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO memory_conflicts(
                    id, scope, candidate_id, old_memory_id, new_memory_id,
                    old_content, new_content, status, resolution, created_at, resolved_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 'open', NULL, ?, NULL)
                """,
                (
                    conflict_id,
                    scope,
                    candidate_id,
                    old_memory_id,
                    new_memory_id,
                    old["content"],
                    new["content"],
                    now,
                ),
            )
            row = db.execute("SELECT * FROM memory_conflicts WHERE id = ?", (conflict_id,)).fetchone()
        self._timeline(
            event_type="memory_conflict_opened",
            subject_type="conflict",
            subject_id=conflict_id,
            scope=scope,
            summary="Обнаружено противоречие между старой и новой памятью.",
            details={"old_memory_id": old_memory_id, "new_memory_id": new_memory_id},
        )
        return self._conflict_row(row)

    @staticmethod
    def _conflict_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "scope": row["scope"],
            "candidate_id": row["candidate_id"],
            "old_memory_id": row["old_memory_id"],
            "new_memory_id": row["new_memory_id"],
            "old_content": row["old_content"],
            "new_content": row["new_content"],
            "status": row["status"],
            "resolution": row["resolution"],
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
        }

    def conflicts(self, *, status: str | None = "open", limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 200)
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.append(safe_limit)
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM memory_conflicts {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._conflict_row(row) for row in rows]

    def _close_knowledge_for_memory(self, memory_id: str, *, status: str = "superseded") -> int:
        now = self._now()
        changed = 0
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, source_memory_ids_json FROM knowledge_items WHERE status = 'confirmed'"
            ).fetchall()
            for row in rows:
                source_ids = self._decode(row["source_memory_ids_json"], [])
                if memory_id not in source_ids:
                    continue
                remaining = [
                    source_id
                    for source_id in source_ids
                    if source_id != memory_id and self.memory.get(source_id) is not None
                ]
                if remaining:
                    db.execute(
                        """
                        UPDATE knowledge_items
                        SET source_memory_ids_json = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (self._json(remaining), now, row["id"]),
                    )
                else:
                    db.execute(
                        """
                        UPDATE knowledge_items
                        SET status = ?, valid_to = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (status, now, now, row["id"]),
                    )
                changed += 1
        return changed

    def resolve_conflict(self, conflict_id: str, resolution: str) -> dict[str, Any]:
        resolution = (resolution or "").strip().lower()
        if resolution not in {"prefer_new", "prefer_old", "keep_both"}:
            raise MemorySystemError("Решение конфликта должно быть prefer_new, prefer_old или keep_both.")
        with self._connect() as db:
            row = db.execute("SELECT * FROM memory_conflicts WHERE id = ?", (conflict_id,)).fetchone()
        if row is None:
            raise MemorySystemError("Конфликт памяти не найден.")
        conflict = self._conflict_row(row)
        if conflict["status"] != "open":
            return conflict

        if resolution == "prefer_new":
            self.memory.delete(conflict["old_memory_id"])
            self._close_knowledge_for_memory(conflict["old_memory_id"])
            selected = self.memory.get(conflict["new_memory_id"], include_inactive=True)
        elif resolution == "prefer_old":
            self.memory.delete(conflict["new_memory_id"])
            self._close_knowledge_for_memory(conflict["new_memory_id"])
            selected = self.memory.get(conflict["old_memory_id"], include_inactive=True)
        else:
            selected = None

        if selected:
            self._promote_if_ready(selected, source_ids=[selected["id"]])

        now = self._now()
        with self._connect() as db:
            db.execute(
                """
                UPDATE memory_conflicts
                SET status = 'resolved', resolution = ?, resolved_at = ?
                WHERE id = ?
                """,
                (resolution, now, conflict_id),
            )
            row = db.execute("SELECT * FROM memory_conflicts WHERE id = ?", (conflict_id,)).fetchone()
        result = self._conflict_row(row)
        self._timeline(
            event_type="memory_conflict_resolved",
            subject_type="conflict",
            subject_id=conflict_id,
            scope=result["scope"],
            summary=f"Конфликт памяти разрешён: {resolution}.",
            details=result,
        )
        return result

    def graph(self, limit_nodes: int = 120, limit_edges: int = 240) -> dict[str, Any]:
        limit_nodes = min(max(int(limit_nodes), 1), 500)
        limit_edges = min(max(int(limit_edges), 1), 1000)
        with self._connect() as db:
            nodes = db.execute(
                """
                SELECT * FROM memory_graph_nodes
                ORDER BY updated_at DESC LIMIT ?
                """,
                (limit_nodes,),
            ).fetchall()
            node_ids = {row["id"] for row in nodes}
            edges = db.execute(
                """
                SELECT * FROM memory_graph_edges
                ORDER BY updated_at DESC LIMIT ?
                """,
                (limit_edges * 2,),
            ).fetchall()
        return {
            "nodes": [
                {
                    "id": row["id"],
                    "type": row["node_type"],
                    "key": row["node_key"],
                    "label": row["label"],
                    "metadata": self._decode(row["metadata_json"]),
                }
                for row in nodes
            ],
            "edges": [
                {
                    "id": row["id"],
                    "source": row["source_id"],
                    "target": row["target_id"],
                    "relation": row["relation"],
                    "weight": row["weight"],
                    "source_ref": row["source_ref"],
                }
                for row in edges
                if row["source_id"] in node_ids and row["target_id"] in node_ids
            ][:limit_edges],
        }

    def timeline(self, limit: int = 80) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 300)
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM memory_timeline ORDER BY occurred_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "subject_type": row["subject_type"],
                "subject_id": row["subject_id"],
                "scope": row["scope"],
                "summary": row["summary"],
                "details": self._decode(row["details_json"]),
                "occurred_at": row["occurred_at"],
            }
            for row in rows
        ]

    def maybe_maintain(self, *, interval_hours: int = 6) -> dict[str, Any]:
        interval_hours = min(max(int(interval_hours), 1), 168)
        with self._connect() as db:
            row = db.execute(
                "SELECT value FROM memory_v3_meta WHERE key = 'last_maintenance'"
            ).fetchone()
        last = self._parse_time(row["value"]) if row else None
        now = self._now_dt()
        if last and now - last < timedelta(hours=interval_hours):
            return {
                "ran": False,
                "last_maintenance": last.isoformat(),
                "next_after": (last + timedelta(hours=interval_hours)).isoformat(),
            }

        result = self.maintenance()
        completed = self._now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO memory_v3_meta(key, value, updated_at)
                VALUES('last_maintenance', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (completed, completed),
            )
        return {"ran": True, "last_maintenance": completed, "result": result}

    def maintenance(self) -> dict[str, Any]:
        retention = self.evaluate_retention()
        entries = self.memory.scan_active(limit=5000)
        promoted = 0
        for entry in entries:
            result = self.ingest_memory(entry, timeline=False)
            if result.get("knowledge"):
                promoted += 1
        consolidation = self.consolidate()
        self._timeline(
            event_type="memory_maintenance",
            subject_type="system",
            subject_id=None,
            scope="system",
            summary="Memory 3.0 выполнила обслуживание памяти.",
            details={
                "retention_updated": retention["updated"],
                "stale_count": retention["stale_count"],
                "knowledge_promoted": promoted,
                "consolidations": consolidation["created"],
            },
        )
        return {
            "status": "готово",
            "retention": retention,
            "knowledge_promoted": promoted,
            "consolidation": consolidation,
            "stats": self.stats(),
        }

    def stats(self) -> dict[str, Any]:
        now = self._now()
        with self._connect() as db:
            db.execute(
                "DELETE FROM working_memory WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            )
            working = db.execute("SELECT COUNT(*) AS count FROM working_memory").fetchone()["count"]
            episodes = db.execute("SELECT COUNT(*) AS count FROM episodic_memory").fetchone()["count"]
            knowledge = db.execute(
                "SELECT COUNT(*) AS count FROM knowledge_items WHERE status = 'confirmed'"
            ).fetchone()["count"]
            nodes = db.execute("SELECT COUNT(*) AS count FROM memory_graph_nodes").fetchone()["count"]
            edges = db.execute("SELECT COUNT(*) AS count FROM memory_graph_edges").fetchone()["count"]
            conflicts = db.execute(
                "SELECT COUNT(*) AS count FROM memory_conflicts WHERE status = 'open'"
            ).fetchone()["count"]
            consolidations = db.execute(
                "SELECT COUNT(*) AS count FROM memory_consolidations"
            ).fetchone()["count"]
        memory_stats = self.memory.stats()
        return {
            "version": "3.0",
            "working": working,
            "episodes": episodes,
            "knowledge": knowledge,
            "graph_nodes": nodes,
            "graph_edges": edges,
            "open_conflicts": conflicts,
            "consolidations": consolidations,
            "stale_candidates": memory_stats.get("stale_candidates", 0),
        }

    def dashboard(self) -> dict[str, Any]:
        retention = self.retention_snapshot()
        return {
            "stats": self.stats(),
            "working": self.working(),
            "knowledge": self.knowledge(30),
            "episodes": self.episodes(30),
            "timeline": self.timeline(40),
            "conflicts": self.conflicts(status="open", limit=30),
            "graph": self.graph(80, 160),
            "retention": retention,
        }

    def context(self, query: str) -> dict[str, Any]:
        text = (query or "").strip()
        knowledge_ranked: list[tuple[float, dict[str, Any]]] = []
        for item in self.knowledge(120):
            score = self.semantic.score(
                text,
                item["statement"],
                importance=5 if item["kind"] == "decision" else 4,
                confidence=item["confidence"],
            )["score"]
            if score >= 0.12:
                enriched = dict(item)
                enriched["relevance"] = score
                knowledge_ranked.append((score, enriched))
        knowledge_ranked.sort(key=lambda pair: pair[0], reverse=True)

        episode_ranked: list[tuple[float, dict[str, Any]]] = []
        for item in self.episodes(120):
            score = self.semantic.score(
                text,
                item["summary"],
                importance=item["importance"],
                confidence=0.8,
            )["score"]
            if score >= 0.12:
                enriched = dict(item)
                enriched["relevance"] = score
                episode_ranked.append((score, enriched))
        episode_ranked.sort(key=lambda pair: pair[0], reverse=True)

        open_conflicts = self.conflicts(status="open", limit=6)
        return {
            "working": self.working()["items"],
            "knowledge": [item for _, item in knowledge_ranked[:6]],
            "episodes": [item for _, item in episode_ranked[:4]],
            "conflicts": [
                {
                    "scope": item["scope"],
                    "old_memory_id": item["old_memory_id"],
                    "new_memory_id": item["new_memory_id"],
                    "old_content": item["old_content"][:700],
                    "new_content": item["new_content"][:700],
                    "status": item["status"],
                }
                for item in open_conflicts
            ],
            "open_conflicts": len(open_conflicts),
            "engine": "memory-v3",
        }

    def archive_memory(self, entry: dict[str, Any]) -> dict[str, Any]:
        memory_id = str(entry.get("id") or "")
        if not memory_id:
            raise MemorySystemError("У архивируемой памяти нет ID.")
        knowledge_updated = self._close_knowledge_for_memory(memory_id, status="archived")
        self.record_memory_removed(entry)
        return {
            "memory_id": memory_id,
            "knowledge_updated": knowledge_updated,
        }

    def record_memory_removed(self, entry: dict[str, Any]) -> None:
        self._timeline(
            event_type="memory_archived",
            subject_type="memory",
            subject_id=str(entry.get("id") or ""),
            scope=str(entry.get("scope") or "project"),
            summary=str(entry.get("content") or "")[:800],
            details={"kind": entry.get("kind")},
        )
