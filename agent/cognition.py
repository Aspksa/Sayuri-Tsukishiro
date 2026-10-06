from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import re
import sqlite3
import uuid


class CognitiveBrainError(ValueError):
    pass


class CognitiveProjectBrain:
    """Deterministic portfolio/task orchestration above Goal/Task Memory.

    This layer never executes mutations on behalf of the LLM and never marks
    tasks done automatically. It provides project/module scoping, dependency
    readiness, completion assessment, scheduling, uncertainty, strategy
    statistics, replan proposals and metacognitive summaries.
    """

    VERSION = "1.1"
    PROJECT_KEY = "sayuri-tsukishiro"
    DEPENDENCY_RELATIONS = {"requires", "blocks", "unlocks", "follows"}
    OPEN_TASK_STATUSES = {"planned", "in_progress", "blocked"}
    MAX_PROJECTS = 100
    MAX_MODULES = 500
    MAX_TASKS = 1000

    def __init__(self, root: Path, memory_v4: Any):
        self.root = root
        self.path = root / "data" / "sayuri-memory.db"
        self.memory_v4 = memory_v4
        self.initialize()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode(value: str | None, fallback: Any) -> Any:
        if not value:
            return fallback
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return fallback
        return decoded

    @staticmethod
    def _key(value: str, *, fallback: str = "") -> str:
        normalized = re.sub(r"[^a-z0-9._-]+", "-", (value or "").strip().casefold())
        normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
        return (normalized or fallback)[:120]

    @staticmethod
    def _tokens(*parts: Any) -> set[str]:
        text = " ".join(str(part or "") for part in parts).casefold().replace("ё", "е")
        return set(re.findall(r"[a-zа-я0-9_-]{3,}", text))

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
                CREATE TABLE IF NOT EXISTS cognitive_projects (
                    id TEXT PRIMARY KEY,
                    project_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognitive_modules (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    module_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    path TEXT,
                    status TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, module_key)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognitive_task_scope (
                    task_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    module_id TEXT,
                    completion_criteria_json TEXT NOT NULL,
                    attention_state TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    plan_revision INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognitive_task_edges (
                    id TEXT PRIMARY KEY,
                    source_task_id TEXT NOT NULL,
                    target_task_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    evidence_ref TEXT,
                    confirmed INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_task_id, target_task_id, relation)
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_cognitive_edges_source ON cognitive_task_edges(source_task_id, relation)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_cognitive_edges_target ON cognitive_task_edges(target_task_id, relation)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognitive_uncertainties (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    module_id TEXT,
                    task_id TEXT,
                    question TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    evidence_needed TEXT,
                    source_ref TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolution TEXT
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_cognitive_uncertainty_status ON cognitive_uncertainties(status, severity, created_at DESC)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognitive_strategies (
                    id TEXT PRIMARY KEY,
                    strategy_key TEXT NOT NULL UNIQUE,
                    project_id TEXT,
                    module_id TEXT,
                    pattern TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL,
                    last_outcome TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognitive_plan_revisions (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    previous_next_action TEXT,
                    proposed_next_action TEXT NOT NULL,
                    evidence_ref TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, revision)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognitive_evaluations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    module_id TEXT,
                    task_id TEXT,
                    status TEXT NOT NULL,
                    score REAL NOT NULL,
                    checks_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognitive_causal_links (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    effect_type TEXT NOT NULL,
                    effect_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    evidence_ref TEXT,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_type, source_id, effect_type, effect_id, relation)
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_cognitive_causal_task ON cognitive_causal_links(task_id, created_at DESC)"
            )

    def register_project(
        self,
        project_key: str,
        *,
        title: str | None = None,
        description: str = "",
        priority: int | None = None,
    ) -> dict[str, Any]:
        key = self._key(project_key, fallback=self.PROJECT_KEY)
        display = " ".join((title or project_key or key).strip().split())[:300]
        if not display:
            raise CognitiveBrainError("Название проекта не может быть пустым.")
        now = self._now()
        normalized_priority = 3 if priority is None else min(max(int(priority), 1), 5)
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM cognitive_projects WHERE project_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                project_id = uuid.uuid4().hex
                db.execute(
                    """
                    INSERT INTO cognitive_projects(
                        id, project_key, title, description, status, priority,
                        created_at, updated_at
                    ) VALUES(?, ?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (project_id, key, display, description[:2000] or None, normalized_priority, now, now),
                )
                row = db.execute(
                    "SELECT * FROM cognitive_projects WHERE id = ?",
                    (project_id,),
                ).fetchone()
            else:
                next_title = display if title is not None else row["title"]
                next_priority = normalized_priority if priority is not None else int(row["priority"])
                db.execute(
                    """
                    UPDATE cognitive_projects
                    SET title = ?, description = COALESCE(NULLIF(?, ''), description),
                        priority = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (next_title, description[:2000], next_priority, now, row["id"]),
                )
                row = db.execute(
                    "SELECT * FROM cognitive_projects WHERE id = ?",
                    (row["id"],),
                ).fetchone()
        return self._project_row(row)

    @staticmethod
    def _project_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "key": row["project_key"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "priority": row["priority"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _module_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "key": row["module_key"],
            "title": row["title"],
            "path": row["path"],
            "status": row["status"],
            "metadata": CognitiveProjectBrain._decode(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def projects(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM cognitive_projects ORDER BY priority DESC, updated_at DESC LIMIT ?",
                (self.MAX_PROJECTS,),
            ).fetchall()
        return [self._project_row(row) for row in rows]

    def project_by_key(self, project_key: str) -> dict[str, Any] | None:
        key = self._key(project_key)
        if not key:
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM cognitive_projects WHERE project_key = ?",
                (key,),
            ).fetchone()
        return self._project_row(row) if row else None

    def register_module(
        self,
        project_key: str,
        module_key: str,
        *,
        title: str | None = None,
        path: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self.register_project(project_key)
        key = self._key(module_key)
        if not key:
            raise CognitiveBrainError("Ключ модуля не может быть пустым.")
        display = " ".join((title or module_key).strip().split())[:300]
        now = self._now()
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM cognitive_modules
                WHERE project_id = ? AND module_key = ?
                """,
                (project["id"], key),
            ).fetchone()
            if row is None:
                module_id = uuid.uuid4().hex
                db.execute(
                    """
                    INSERT INTO cognitive_modules(
                        id, project_id, module_key, title, path, status,
                        metadata_json, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (
                        module_id,
                        project["id"],
                        key,
                        display,
                        path[:500] or None,
                        self._json(metadata or {}),
                        now,
                        now,
                    ),
                )
                row = db.execute(
                    "SELECT * FROM cognitive_modules WHERE id = ?",
                    (module_id,),
                ).fetchone()
            else:
                db.execute(
                    """
                    UPDATE cognitive_modules
                    SET title = ?, path = COALESCE(NULLIF(?, ''), path),
                        metadata_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        display,
                        path[:500],
                        self._json(metadata or self._decode(row["metadata_json"], {})),
                        now,
                        row["id"],
                    ),
                )
                row = db.execute(
                    "SELECT * FROM cognitive_modules WHERE id = ?",
                    (row["id"],),
                ).fetchone()
        return self._module_row(row)

    def modules(self, project_key: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            if project_key:
                project = self.project_by_key(project_key)
                if not project:
                    return []
                rows = db.execute(
                    """
                    SELECT * FROM cognitive_modules
                    WHERE project_id = ?
                    ORDER BY module_key
                    LIMIT ?
                    """,
                    (project["id"], self.MAX_MODULES),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM cognitive_modules ORDER BY module_key LIMIT ?",
                    (self.MAX_MODULES,),
                ).fetchall()
        return [self._module_row(row) for row in rows]

    def module_by_key(self, project_key: str, module_key: str) -> dict[str, Any] | None:
        project = self.project_by_key(project_key)
        if not project:
            return None
        key = self._key(module_key)
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM cognitive_modules
                WHERE project_id = ? AND module_key = ?
                """,
                (project["id"], key),
            ).fetchone()
        return self._module_row(row) if row else None

    def bootstrap_manifest(self) -> dict[str, Any]:
        project = self.register_project(
            self.PROJECT_KEY,
            title="Sayuri-Tsukishiro",
            description="Основной проект Sayuri и контейнер для модулей.",
            priority=5,
        )
        loaded = 0
        manifest_path = self.root / "MODULES.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        modules = manifest.get("modules") if isinstance(manifest, dict) else []
        if isinstance(modules, list):
            for raw in modules[: self.MAX_MODULES]:
                if not isinstance(raw, dict):
                    continue
                key = str(raw.get("id") or "").strip()
                if not key:
                    continue
                module_project_key = self._key(
                    str(raw.get("project_key") or project["key"]),
                    fallback=project["key"],
                )
                if self.project_by_key(module_project_key) is None:
                    self.register_project(
                        module_project_key,
                        title=str(raw.get("project_title") or module_project_key),
                    )
                self.register_module(
                    module_project_key,
                    key,
                    title=str(raw.get("display_name") or key),
                    path=str(raw.get("path") or ""),
                    metadata={
                        "description": str(raw.get("description") or "")[:2000],
                        "source": "MODULES.json",
                        "capabilities": raw.get("capabilities") if isinstance(raw.get("capabilities"), list) else [],
                        "depends_on": raw.get("depends_on") if isinstance(raw.get("depends_on"), list) else [],
                    },
                )
                loaded += 1
        scoped = self.sync_tasks()
        return {
            "project": project,
            "manifest_modules": loaded,
            "scoped_tasks": scoped,
        }

    @staticmethod
    def _context_key(context: Any, name: str) -> str:
        if not isinstance(context, dict):
            return ""
        direct = context.get(name + "_key")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        nested = context.get(name)
        if isinstance(nested, dict):
            for key in ("key", "id"):
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def module_key_from_context(self, context: Any) -> str:
        explicit = self._key(self._context_key(context, "module"))
        if explicit:
            return explicit
        if not isinstance(context, dict):
            return ""
        view = self._key(str(context.get("view") or ""))
        section = self._key(str(context.get("section") or ""))
        aliases = {
            "disk": "sayuri-disk",
            "drive": "sayuri-disk",
            "dna": "sayuri-disk",
            "sayuri": "agent-core",
            "chat": "agent-core",
            "home": "sayuri-core",
            "settings": "sayuri-core",
            "system": "sayuri-core",
        }
        return aliases.get(view) or aliases.get(section) or ""

    def normalize_task_context(self, context: Any) -> dict[str, Any]:
        raw = context if isinstance(context, dict) else {}
        project_key = self._key(
            self._context_key(raw, "project"),
            fallback=self.PROJECT_KEY,
        )
        module_key = self.module_key_from_context(raw)
        normalized: dict[str, Any] = {
            "project_key": project_key,
            "module_key": module_key or None,
            "completion_criteria": self._normalize_criteria(raw.get("completion_criteria")),
        }
        milestone = raw.get("milestone")
        if isinstance(milestone, str) and milestone.strip():
            normalized["milestone"] = " ".join(milestone.strip().split())[:300]
        labels = raw.get("labels")
        if isinstance(labels, list):
            normalized["labels"] = [
                " ".join(str(item).strip().split())[:80]
                for item in labels[:20]
                if str(item).strip()
            ]
        return normalized

    @staticmethod
    def _normalize_criteria(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        result: list[dict[str, Any]] = []
        for item in raw[:12]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "").strip().lower()
            if kind not in {
                "checkpoint_count",
                "tool_completed",
                "dependency_done",
                "manual_confirmation",
            }:
                continue
            normalized: dict[str, Any] = {"type": kind}
            if kind == "checkpoint_count":
                try:
                    normalized["min"] = min(max(int(item.get("min", 1)), 1), 100)
                except (TypeError, ValueError):
                    normalized["min"] = 1
            elif kind == "tool_completed":
                normalized["tool"] = str(item.get("tool") or "")[:160]
                try:
                    normalized["min"] = min(max(int(item.get("min", 1)), 1), 100)
                except (TypeError, ValueError):
                    normalized["min"] = 1
            elif kind == "dependency_done":
                normalized["task_id"] = str(item.get("task_id") or "")[:160]
            elif kind == "manual_confirmation":
                normalized["confirmed"] = bool(item.get("confirmed"))
            result.append(normalized)
        return result

    def _scope_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "project_id": row["project_id"],
            "module_id": row["module_id"],
            "completion_criteria": self._decode(row["completion_criteria_json"], []),
            "attention_state": row["attention_state"],
            "confidence": row["confidence"],
            "plan_revision": row["plan_revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def task_scope(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM cognitive_task_scope WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return self._scope_row(row) if row else None

    def bind_task(
        self,
        task_id: str,
        *,
        project_key: str | None = None,
        module_key: str | None = None,
        completion_criteria: Any = None,
        attention_state: str = "active",
        confidence: float = 0.5,
    ) -> dict[str, Any]:
        project_key = project_key or self.PROJECT_KEY
        project = self.project_by_key(project_key) or self.register_project(project_key)
        module = None
        if module_key:
            module = self.module_by_key(project["key"], module_key)
            if module is None:
                module = self.register_module(project["key"], module_key, title=module_key)
        criteria = self._normalize_criteria(completion_criteria)
        state = attention_state if attention_state in {"active", "waiting", "blocked", "later"} else "active"
        confidence = max(0.0, min(float(confidence), 1.0))
        now = self._now()
        with self._connect() as db:
            existing = db.execute(
                "SELECT * FROM cognitive_task_scope WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if existing is None:
                db.execute(
                    """
                    INSERT INTO cognitive_task_scope(
                        task_id, project_id, module_id, completion_criteria_json,
                        attention_state, confidence, plan_revision, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        task_id,
                        project["id"],
                        module["id"] if module else None,
                        self._json(criteria),
                        state,
                        confidence,
                        now,
                        now,
                    ),
                )
            else:
                next_criteria = (
                    criteria
                    if completion_criteria is not None
                    else self._decode(existing["completion_criteria_json"], [])
                )
                db.execute(
                    """
                    UPDATE cognitive_task_scope
                    SET project_id = ?, module_id = COALESCE(?, module_id),
                        completion_criteria_json = ?, attention_state = ?,
                        confidence = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (
                        project["id"],
                        module["id"] if module else None,
                        self._json(next_criteria),
                        state,
                        confidence,
                        now,
                        task_id,
                    ),
                )
            row = db.execute(
                "SELECT * FROM cognitive_task_scope WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return self._scope_row(row)

    def sync_tasks(self) -> int:
        tasks = self.memory_v4.tasks(limit=self.MAX_TASKS)
        count = 0
        for task in tasks:
            task_id = str(task["id"])
            if self.task_scope(task_id) is not None:
                count += 1
                continue
            context = self.normalize_task_context(task.get("context"))
            project_key = str(context.get("project_key") or self.PROJECT_KEY)
            module_key = str(context.get("module_key") or "") or None
            self.bind_task(
                task_id,
                project_key=project_key,
                module_key=module_key,
                completion_criteria=context.get("completion_criteria"),
                attention_state="blocked" if task.get("status") == "blocked" else "active",
                confidence=0.65 if task.get("source") in {"manual", "memory_intelligence_confirmed"} else 0.5,
            )
            count += 1
        return count

    @staticmethod
    def _edge_dependency_pair(edge: dict[str, Any]) -> tuple[str, str] | None:
        source = str(edge.get("source_task_id") or "")
        target = str(edge.get("target_task_id") or "")
        relation = str(edge.get("relation") or "")
        if relation in {"requires", "follows"} and source and target:
            return source, target
        if relation in {"blocks", "unlocks"} and source and target:
            return target, source
        return None

    def _dependency_adjacency(self) -> dict[str, set[str]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT source_task_id, target_task_id, relation, confirmed
                FROM cognitive_task_edges
                WHERE confirmed = 1
                """
            ).fetchall()
        adjacency: dict[str, set[str]] = {}
        for row in rows:
            pair = self._edge_dependency_pair(dict(row))
            if pair:
                dependent, prerequisite = pair
                adjacency.setdefault(dependent, set()).add(prerequisite)
        return adjacency

    def _would_create_cycle(
        self,
        task_id: str,
        dependency_task_id: str,
        relation: str,
    ) -> bool:
        pair = self._edge_dependency_pair(
            {
                "source_task_id": task_id,
                "target_task_id": dependency_task_id,
                "relation": relation,
            }
        )
        if not pair:
            return False
        dependent, prerequisite = pair
        adjacency = self._dependency_adjacency()
        stack = [prerequisite]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current == dependent:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(adjacency.get(current, set()) - seen)
        return False

    def add_dependency(
        self,
        task_id: str,
        dependency_task_id: str,
        *,
        relation: str = "requires",
        evidence_ref: str = "local_explicit",
        confirmed: bool = True,
    ) -> dict[str, Any]:
        if relation not in self.DEPENDENCY_RELATIONS:
            raise CognitiveBrainError("Неизвестный тип зависимости.")
        if task_id == dependency_task_id:
            raise CognitiveBrainError("Задача не может зависеть от самой себя.")
        known = {item["id"]: item for item in self.memory_v4.tasks(limit=self.MAX_TASKS)}
        if task_id not in known or dependency_task_id not in known:
            raise CognitiveBrainError("Одна из задач зависимости не найдена.")
        source_scope = self.task_scope(task_id) or self.bind_task(task_id)
        target_scope = self.task_scope(dependency_task_id) or self.bind_task(dependency_task_id)
        if source_scope["project_id"] != target_scope["project_id"]:
            raise CognitiveBrainError(
                "Прямые зависимости между разными проектами запрещены; используйте milestone/external blocker."
            )
        if confirmed and self._would_create_cycle(task_id, dependency_task_id, relation):
            raise CognitiveBrainError("Зависимость создаёт цикл в task graph.")
        now = self._now()
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM cognitive_task_edges
                WHERE source_task_id = ? AND target_task_id = ? AND relation = ?
                """,
                (task_id, dependency_task_id, relation),
            ).fetchone()
            if row is None:
                edge_id = uuid.uuid4().hex
                db.execute(
                    """
                    INSERT INTO cognitive_task_edges(
                        id, source_task_id, target_task_id, relation,
                        evidence_ref, confirmed, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge_id,
                        task_id,
                        dependency_task_id,
                        relation,
                        evidence_ref[:500] or None,
                        1 if confirmed else 0,
                        now,
                    ),
                )
                row = db.execute(
                    "SELECT * FROM cognitive_task_edges WHERE id = ?",
                    (edge_id,),
                ).fetchone()
        return {
            "id": row["id"],
            "source_task_id": row["source_task_id"],
            "target_task_id": row["target_task_id"],
            "relation": row["relation"],
            "evidence_ref": row["evidence_ref"],
            "confirmed": bool(row["confirmed"]),
            "created_at": row["created_at"],
        }

    def dependencies(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM cognitive_task_edges
                WHERE source_task_id = ? OR target_task_id = ?
                ORDER BY created_at
                """,
                (task_id, task_id),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "source_task_id": row["source_task_id"],
                "target_task_id": row["target_task_id"],
                "relation": row["relation"],
                "evidence_ref": row["evidence_ref"],
                "confirmed": bool(row["confirmed"]),
            }
            for row in rows
        ]

    def blockers(self, task_id: str) -> list[dict[str, Any]]:
        tasks = {item["id"]: item for item in self.memory_v4.tasks(limit=self.MAX_TASKS)}
        blockers: list[dict[str, Any]] = []
        for edge in self.dependencies(task_id):
            blocking_id = None
            if (
                edge["source_task_id"] == task_id
                and edge["relation"] in {"requires", "follows"}
            ):
                blocking_id = edge["target_task_id"]
            elif (
                edge["target_task_id"] == task_id
                and edge["relation"] in {"blocks", "unlocks"}
            ):
                blocking_id = edge["source_task_id"]
            if not blocking_id or not edge.get("confirmed"):
                continue
            blocking_task = tasks.get(blocking_id)
            if blocking_task and blocking_task.get("status") != "done":
                blockers.append(
                    {
                        "task_id": blocking_id,
                        "title": blocking_task.get("title"),
                        "status": blocking_task.get("status"),
                        "relation": edge["relation"],
                    }
                )
        return blockers

    def set_completion_criteria(self, task_id: str, criteria: Any) -> dict[str, Any]:
        if self.task_scope(task_id) is None:
            self.bind_task(task_id)
        normalized = self._normalize_criteria(criteria)
        with self._connect() as db:
            db.execute(
                """
                UPDATE cognitive_task_scope
                SET completion_criteria_json = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (self._json(normalized), self._now(), task_id),
            )
            row = db.execute(
                "SELECT * FROM cognitive_task_scope WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise CognitiveBrainError("Задача не найдена.")
        return self._scope_row(row)

    def completion_assessment(self, task_id: str) -> dict[str, Any]:
        scope = self.task_scope(task_id)
        criteria = list(scope.get("completion_criteria", [])) if scope else []
        checkpoints = [
            item
            for item in self.memory_v4.task_checkpoints(task_id=task_id, limit=200)
            if item.get("applied")
        ]
        tasks = {item["id"]: item for item in self.memory_v4.tasks(limit=self.MAX_TASKS)}
        checks: list[dict[str, Any]] = []
        for criterion in criteria:
            kind = criterion.get("type")
            satisfied = False
            detail = ""
            if kind == "checkpoint_count":
                required = int(criterion.get("min") or 1)
                satisfied = len(checkpoints) >= required
                detail = f"{len(checkpoints)}/{required} checkpoints"
            elif kind == "tool_completed":
                tool = str(criterion.get("tool") or "")
                required = int(criterion.get("min") or 1)
                found = sum(1 for item in checkpoints if item.get("tool") == tool and item.get("applied"))
                satisfied = bool(tool) and found >= required
                detail = f"{found}/{required} confirmed {tool}"
            elif kind == "dependency_done":
                dependency = tasks.get(str(criterion.get("task_id") or ""))
                satisfied = bool(dependency and dependency.get("status") == "done")
                detail = str(dependency.get("status") if dependency else "missing")
            elif kind == "manual_confirmation":
                satisfied = bool(criterion.get("confirmed"))
                detail = "confirmed" if satisfied else "requires explicit confirmation"
            checks.append({"criterion": criterion, "satisfied": satisfied, "detail": detail})
        satisfied_count = sum(1 for item in checks if item["satisfied"])
        total = len(checks)
        blockers = self.blockers(task_id)
        if blockers:
            status = "blocked_by_dependencies"
            score = 0.0
        elif not total:
            status = "criteria_missing"
            score = 0.0
        elif satisfied_count == total:
            status = "ready_for_confirmation"
            score = 1.0
        else:
            status = "incomplete"
            score = satisfied_count / total
        return {
            "task_id": task_id,
            "status": status,
            "score": round(score, 4),
            "satisfied": satisfied_count,
            "total": total,
            "checks": checks,
            "blockers": blockers,
            "automatic_completion": False,
        }

    def uncertainties(
        self,
        *,
        task_id: str | None = None,
        project_id: str | None = None,
        module_id: str | None = None,
        status: str = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses = ["status = ?"]
        params: list[Any] = [status]
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if module_id:
            clauses.append("module_id = ?")
            params.append(module_id)
        params.append(min(max(int(limit), 1), 200))
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM cognitive_uncertainties
                WHERE {' AND '.join(clauses)}
                ORDER BY CASE severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC,
                         created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "module_id": row["module_id"],
                "task_id": row["task_id"],
                "question": row["question"],
                "severity": row["severity"],
                "status": row["status"],
                "evidence_needed": row["evidence_needed"],
                "source_ref": row["source_ref"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def record_uncertainty(
        self,
        question: str,
        *,
        task_id: str | None = None,
        project_id: str | None = None,
        module_id: str | None = None,
        severity: str = "medium",
        evidence_needed: str = "",
        source_ref: str = "",
    ) -> dict[str, Any]:
        text = " ".join((question or "").strip().split())[:1500]
        if not text:
            raise CognitiveBrainError("Вопрос неопределённости не может быть пустым.")
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        fingerprint = hashlib.sha256(
            self._json([project_id, module_id, task_id, text.casefold(), source_ref]).encode("utf-8")
        ).hexdigest()
        uncertainty_id = fingerprint[:32]
        with self._connect() as db:
            existing = db.execute(
                "SELECT * FROM cognitive_uncertainties WHERE id = ?",
                (uncertainty_id,),
            ).fetchone()
            if existing is None:
                db.execute(
                    """
                    INSERT INTO cognitive_uncertainties(
                        id, project_id, module_id, task_id, question, severity,
                        status, evidence_needed, source_ref, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
                    """,
                    (
                        uncertainty_id,
                        project_id,
                        module_id,
                        task_id,
                        text,
                        severity,
                        evidence_needed[:1500] or None,
                        source_ref[:500] or None,
                        self._now(),
                    ),
                )
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM cognitive_uncertainties WHERE id = ?",
                (uncertainty_id,),
            ).fetchone()
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "module_id": row["module_id"],
            "task_id": row["task_id"],
            "question": row["question"],
            "severity": row["severity"],
            "status": row["status"],
            "evidence_needed": row["evidence_needed"],
            "source_ref": row["source_ref"],
            "created_at": row["created_at"],
        }

    def resolve_uncertainty(self, uncertainty_id: str, resolution: str) -> dict[str, Any]:
        text = " ".join((resolution or "").strip().split())[:2000]
        if not text:
            raise CognitiveBrainError("Нужно указать результат разрешения неопределённости.")
        now = self._now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM cognitive_uncertainties WHERE id = ?",
                (uncertainty_id,),
            ).fetchone()
            if row is None:
                raise CognitiveBrainError("Неопределённость не найдена.")
            if row["status"] == "open":
                db.execute(
                    """
                    UPDATE cognitive_uncertainties
                    SET status='resolved', resolved_at=?, resolution=?
                    WHERE id=?
                    """,
                    (now, text, uncertainty_id),
                )
            row = db.execute(
                "SELECT * FROM cognitive_uncertainties WHERE id = ?",
                (uncertainty_id,),
            ).fetchone()
        return {
            "id": row["id"],
            "task_id": row["task_id"],
            "status": row["status"],
            "resolution": row["resolution"],
            "resolved_at": row["resolved_at"],
        }

    def _record_replan_proposal(
        self,
        task_id: str,
        *,
        reason: str,
        proposed_next_action: str,
        evidence_ref: str,
    ) -> dict[str, Any]:
        task = next(
            (item for item in self.memory_v4.tasks(limit=self.MAX_TASKS) if item["id"] == task_id),
            None,
        )
        if not task:
            raise CognitiveBrainError("Задача для replanning не найдена.")
        with self._connect() as db:
            revision = int(
                db.execute(
                    "SELECT COALESCE(MAX(revision), 0) + 1 FROM cognitive_plan_revisions WHERE task_id = ?",
                    (task_id,),
                ).fetchone()[0]
            )
            revision_id = uuid.uuid4().hex
            db.execute(
                """
                INSERT INTO cognitive_plan_revisions(
                    id, task_id, revision, reason, previous_next_action,
                    proposed_next_action, evidence_ref, status, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 'proposed', ?)
                """,
                (
                    revision_id,
                    task_id,
                    revision,
                    reason[:1500],
                    str(task.get("next_action") or "")[:2000] or None,
                    proposed_next_action[:2000],
                    evidence_ref[:500] or None,
                    self._now(),
                ),
            )
            db.execute(
                """
                UPDATE cognitive_task_scope
                SET plan_revision = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (revision, self._now(), task_id),
            )
        return {
            "id": revision_id,
            "task_id": task_id,
            "revision": revision,
            "status": "proposed",
            "reason": reason[:1500],
            "previous_next_action": task.get("next_action"),
            "proposed_next_action": proposed_next_action[:2000],
            "evidence_ref": evidence_ref[:500] or None,
            "automatic_apply": False,
        }

    def apply_replan(self, revision_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM cognitive_plan_revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
        if row is None:
            raise CognitiveBrainError("Предложение replanning не найдено.")
        if row["status"] != "proposed":
            return {
                "id": row["id"],
                "task_id": row["task_id"],
                "status": row["status"],
                "applied": row["status"] == "accepted",
            }
        task = next(
            (
                item
                for item in self.memory_v4.tasks(limit=self.MAX_TASKS)
                if item["id"] == row["task_id"]
            ),
            None,
        )
        if task is None:
            raise CognitiveBrainError("Связанная задача не найдена.")
        if str(task.get("next_action") or "") != str(row["previous_next_action"] or ""):
            raise CognitiveBrainError(
                "Replan устарел: next_action задачи изменился после создания предложения."
            )
        updated = self.memory_v4.update_task(
            task["id"],
            next_action=str(row["proposed_next_action"] or ""),
        )
        with self._connect() as db:
            db.execute(
                "UPDATE cognitive_plan_revisions SET status='accepted' WHERE id=?",
                (revision_id,),
            )
        return {
            "id": revision_id,
            "task_id": task["id"],
            "status": "accepted",
            "applied": True,
            "next_action": updated.get("next_action"),
        }

    def replan_proposals(self, task_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM cognitive_plan_revisions
                WHERE task_id = ?
                ORDER BY revision DESC
                LIMIT ?
                """,
                (task_id, min(max(int(limit), 1), 100)),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "revision": row["revision"],
                "reason": row["reason"],
                "previous_next_action": row["previous_next_action"],
                "proposed_next_action": row["proposed_next_action"],
                "evidence_ref": row["evidence_ref"],
                "status": row["status"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _strategy_scope(self, task_id: str | None) -> tuple[str | None, str | None]:
        if not task_id:
            return None, None
        scope = self.task_scope(task_id)
        if not scope:
            return None, None
        return scope.get("project_id"), scope.get("module_id")

    def _record_causal_link(
        self,
        *,
        task_id: str | None,
        source_type: str,
        source_id: str,
        effect_type: str,
        effect_id: str,
        relation: str,
        evidence_ref: str,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        fingerprint = hashlib.sha256(
            self._json([source_type, source_id, effect_type, effect_id, relation]).encode("utf-8")
        ).hexdigest()
        link_id = fingerprint[:32]
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO cognitive_causal_links(
                    id, task_id, source_type, source_id, effect_type, effect_id,
                    relation, evidence_ref, confidence, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_type, source_id, effect_type, effect_id, relation)
                DO UPDATE SET
                    evidence_ref=excluded.evidence_ref,
                    confidence=excluded.confidence
                """,
                (
                    link_id,
                    task_id or None,
                    source_type[:80],
                    source_id[:200],
                    effect_type[:80],
                    effect_id[:200],
                    relation[:120],
                    evidence_ref[:500] or None,
                    max(0.0, min(float(confidence), 1.0)),
                    self._now(),
                ),
            )
            row = db.execute(
                "SELECT * FROM cognitive_causal_links WHERE id = ?",
                (link_id,),
            ).fetchone()
        return {
            "id": row["id"],
            "task_id": row["task_id"],
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "effect_type": row["effect_type"],
            "effect_id": row["effect_id"],
            "relation": row["relation"],
            "evidence_ref": row["evidence_ref"],
            "confidence": row["confidence"],
            "created_at": row["created_at"],
        }

    def causal_links(
        self,
        *,
        task_id: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 100)
        with self._connect() as db:
            if task_id:
                rows = db.execute(
                    """
                    SELECT * FROM cognitive_causal_links
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (task_id, safe_limit),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM cognitive_causal_links
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (safe_limit,),
                ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "source_type": row["source_type"],
                "source_id": row["source_id"],
                "effect_type": row["effect_type"],
                "effect_id": row["effect_id"],
                "relation": row["relation"],
                "evidence_ref": row["evidence_ref"],
                "confidence": row["confidence"],
            }
            for row in rows
        ]

    def observe_action(
        self,
        action: dict[str, Any],
        *,
        context: Any,
        checkpoint: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        status = str(action.get("status") or "")
        if status not in {"completed", "failed", "cancelled", "expired"}:
            return None
        safe_context = context if isinstance(context, dict) else {}
        lifecycle = safe_context.get("_task_lifecycle")
        task_id = str(lifecycle.get("task_id") or "") if isinstance(lifecycle, dict) else ""
        project_id, module_id = self._strategy_scope(task_id or None)
        tool = str(action.get("tool") or "unknown")[:160]
        strategy_key = hashlib.sha256(
            self._json([project_id, module_id, "tool", tool]).encode("utf-8")
        ).hexdigest()
        now = self._now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM cognitive_strategies WHERE strategy_key = ?",
                (strategy_key,),
            ).fetchone()
            success = int(row["success_count"]) if row else 0
            failure = int(row["failure_count"]) if row else 0
            if status == "completed":
                success += 1
            elif status == "failed":
                failure += 1
            confidence = (success + 1.0) / (success + failure + 2.0)
            if row is None:
                strategy_id = uuid.uuid4().hex
                db.execute(
                    """
                    INSERT INTO cognitive_strategies(
                        id, strategy_key, project_id, module_id, pattern, strategy,
                        success_count, failure_count, confidence, last_outcome, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        strategy_id,
                        strategy_key,
                        project_id,
                        module_id,
                        "tool:" + tool,
                        "Использовать " + tool + " только через подтверждённый Action Broker и проверять результат.",
                        success,
                        failure,
                        confidence,
                        status,
                        now,
                    ),
                )
            else:
                db.execute(
                    """
                    UPDATE cognitive_strategies
                    SET success_count = ?, failure_count = ?, confidence = ?,
                        last_outcome = ?, updated_at = ?
                    WHERE strategy_key = ?
                    """,
                    (success, failure, confidence, status, now, strategy_key),
                )

        replan = None
        uncertainty = None
        causal_links: list[dict[str, Any]] = []
        action_id = str(action.get("id") or "")
        if status == "completed" and task_id and isinstance(checkpoint, dict) and checkpoint.get("id"):
            causal_links.append(
                self._record_causal_link(
                    task_id=task_id,
                    source_type="confirmed_action",
                    source_id=action_id,
                    effect_type="task_checkpoint",
                    effect_id=str(checkpoint["id"]),
                    relation="confirmed_result_recorded_as",
                    evidence_ref="action:" + action_id[:160],
                    confidence=1.0,
                )
            )
        if status == "failed" and task_id:
            error = " ".join(str(action.get("error") or "неизвестная ошибка").split())[:700]
            replan = self._record_replan_proposal(
                task_id,
                reason="Подтверждённое действие завершилось ошибкой: " + error,
                proposed_next_action="Проверить причину ошибки и необходимые доказательства перед повтором действия.",
                evidence_ref="action:" + str(action.get("id") or "")[:160],
            )
            uncertainty = self.record_uncertainty(
                "Что необходимо проверить перед повтором неуспешного действия " + tool + "?",
                task_id=task_id,
                project_id=project_id,
                module_id=module_id,
                severity="high",
                evidence_needed=error,
                source_ref="action:" + action_id[:160],
            )
            causal_links.extend([
                self._record_causal_link(
                    task_id=task_id,
                    source_type="confirmed_action_failure",
                    source_id=action_id,
                    effect_type="replan_proposal",
                    effect_id=str(replan["id"]),
                    relation="triggered_replan",
                    evidence_ref="action:" + action_id[:160],
                    confidence=1.0,
                ),
                self._record_causal_link(
                    task_id=task_id,
                    source_type="confirmed_action_failure",
                    source_id=action_id,
                    effect_type="uncertainty",
                    effect_id=str(uncertainty["id"]),
                    relation="raised_uncertainty",
                    evidence_ref="action:" + action_id[:160],
                    confidence=1.0,
                ),
            ])
        return {
            "strategy": {
                "pattern": "tool:" + tool,
                "success_count": success,
                "failure_count": failure,
                "confidence": round(confidence, 4),
                "last_outcome": status,
            },
            "checkpoint_id": checkpoint.get("id") if isinstance(checkpoint, dict) else None,
            "replan": replan,
            "uncertainty": uncertainty,
            "causal_links": causal_links,
        }

    def strategies(
        self,
        *,
        project_id: str | None = None,
        module_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if module_id:
            clauses.append("module_id = ?")
            params.append(module_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(min(max(int(limit), 1), 100))
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM cognitive_strategies
                {where}
                ORDER BY confidence DESC, updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "module_id": row["module_id"],
                "pattern": row["pattern"],
                "strategy": row["strategy"],
                "success_count": row["success_count"],
                "failure_count": row["failure_count"],
                "confidence": row["confidence"],
                "last_outcome": row["last_outcome"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def _task_project_module(self, task_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        scope = self.task_scope(task_id)
        if not scope:
            return None, None
        with self._connect() as db:
            project_row = db.execute(
                "SELECT * FROM cognitive_projects WHERE id = ?",
                (scope["project_id"],),
            ).fetchone()
            module_row = (
                db.execute(
                    "SELECT * FROM cognitive_modules WHERE id = ?",
                    (scope["module_id"],),
                ).fetchone()
                if scope.get("module_id")
                else None
            )
        return (
            self._project_row(project_row) if project_row else None,
            self._module_row(module_row) if module_row else None,
        )

    def scheduler(
        self,
        query: str = "",
        *,
        context: Any = None,
        for_cloud: bool = False,
    ) -> dict[str, Any]:
        raw_tasks = [
            item
            for item in self.memory_v4.tasks(limit=self.MAX_TASKS)
            if item.get("status") in self.OPEN_TASK_STATUSES
        ]
        query_tokens = self._tokens(query)
        context_project = self._key(self._context_key(context, "project"))
        context_module = self.module_key_from_context(context)
        candidates: list[tuple[int, str, dict[str, Any]]] = []
        for task in raw_tasks:
            if for_cloud and not self.memory_v4._cloud_text_allowed(
                task.get("title"), task.get("next_action"), task.get("blocked_reason")
            ):
                continue
            scope = self.task_scope(task["id"])
            if not scope:
                continue
            project, module = self._task_project_module(task["id"])
            if for_cloud:
                project_view = None
                if project:
                    project_view = {
                        "id": project.get("id"),
                        "key": project.get("key"),
                        "title": (
                            project.get("title")
                            if self.memory_v4._cloud_text_allowed(project.get("title"))
                            else None
                        ),
                    }
                module_view = None
                if module:
                    module_view = {
                        "id": module.get("id"),
                        "key": module.get("key"),
                        "title": (
                            module.get("title")
                            if self.memory_v4._cloud_text_allowed(module.get("title"))
                            else None
                        ),
                    }
            else:
                project_view = project
                module_view = module
            blockers = self.blockers(task["id"])
            open_uncertainty = self.uncertainties(task_id=task["id"], limit=20)
            assessment = self.completion_assessment(task["id"])
            overlap = len(query_tokens & self._tokens(task.get("title"), task.get("next_action")))
            score = int(task.get("priority") or 1) * 10
            score += {"in_progress": 8, "planned": 5, "blocked": -20}.get(str(task.get("status")), 0)
            score += overlap * 12
            if context_project and project and project["key"] == context_project:
                score += 12
            if context_module and module and module["key"] == context_module:
                score += 18
            score -= len(blockers) * 100
            score -= sum(15 if item["severity"] == "high" else 5 for item in open_uncertainty)
            if scope.get("attention_state") == "later":
                score -= 20
            if assessment["status"] == "ready_for_confirmation":
                score += 4
            candidate = {
                "id": task["id"],
                "title": task.get("title"),
                "status": task.get("status"),
                "priority": task.get("priority"),
                "next_action": task.get("next_action"),
                "blocked_reason": task.get("blocked_reason"),
                "project": project_view,
                "module": module_view,
                "blockers": blockers,
                "uncertainty_count": len(open_uncertainty),
                "completion": {
                    "status": assessment["status"],
                    "score": assessment["score"],
                    "satisfied": assessment["satisfied"],
                    "total": assessment["total"],
                },
                "plan_revision": scope.get("plan_revision"),
                "attention_state": scope.get("attention_state"),
                "confidence": scope.get("confidence"),
                "query_overlap": overlap,
            }
            candidates.append((score, str(task.get("updated_at") or ""), candidate))
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        actionable = [item for item in candidates if not item[2]["blockers"] and item[2]["status"] != "blocked"]
        selected = actionable[0][2] if actionable else None
        if selected:
            if selected["completion"]["status"] == "ready_for_confirmation":
                recommendation = "Проверить критерии готовности и запросить явное подтверждение завершения задачи."
            elif selected.get("next_action"):
                recommendation = str(selected["next_action"])
            else:
                recommendation = "Определить ближайший проверяемый шаг задачи."
        else:
            recommendation = "Нет разблокированной задачи; проверить blockers и uncertainties."
        return {
            "engine": "cognitive-scheduler-v1",
            "selected": selected,
            "recommendation": recommendation,
            "open_tasks": len(raw_tasks),
            "actionable_tasks": len(actionable),
            "blocked_by_dependencies": sum(1 for _, _, item in candidates if item["blockers"]),
            "candidates": [item[2] for item in candidates[:8]],
        }

    def metacognition(self, task_id: str | None = None) -> dict[str, Any]:
        if not task_id:
            scheduled = self.scheduler()
            task_id = scheduled.get("selected", {}).get("id") if isinstance(scheduled.get("selected"), dict) else None
        if not task_id:
            return {
                "state": "idle",
                "known": [],
                "uncertain": [],
                "blocked": [],
                "replan_required": False,
            }
        task = next(
            (item for item in self.memory_v4.tasks(limit=self.MAX_TASKS) if item["id"] == task_id),
            None,
        )
        if not task:
            return {"state": "missing_task", "task_id": task_id}
        blockers = self.blockers(task_id)
        uncertainties = self.uncertainties(task_id=task_id, limit=20)
        assessment = self.completion_assessment(task_id)
        replans = self.replan_proposals(task_id, limit=1)
        if task.get("status") == "blocked" or blockers:
            state = "blocked"
        elif any(item["severity"] == "high" for item in uncertainties):
            state = "uncertain"
        elif replans and replans[0]["status"] == "proposed":
            state = "replan_required"
        elif assessment["status"] == "ready_for_confirmation":
            state = "ready_for_completion_confirmation"
        elif assessment["status"] == "criteria_missing":
            state = "criteria_missing"
        else:
            state = "actionable"
        return {
            "state": state,
            "task_id": task_id,
            "known": [
                "task_status:" + str(task.get("status")),
                "next_action:" + str(task.get("next_action") or ""),
            ],
            "uncertain": [
                {
                    "question": item["question"],
                    "severity": item["severity"],
                    "evidence_needed": item["evidence_needed"],
                }
                for item in uncertainties[:5]
            ],
            "blocked": blockers[:5],
            "replan_required": state == "replan_required",
            "completion": assessment,
            "latest_replan": replans[0] if replans else None,
            "causal_trace": self.causal_links(task_id=task_id, limit=5),
        }

    def self_evaluation(
        self,
        *,
        project_key: str | None = None,
        module_key: str | None = None,
        persist: bool = False,
    ) -> dict[str, Any]:
        project = self.project_by_key(project_key or self.PROJECT_KEY)
        if not project:
            raise CognitiveBrainError("Проект не найден.")
        module = self.module_by_key(project["key"], module_key) if module_key else None
        tasks = []
        for task in self.memory_v4.tasks(limit=self.MAX_TASKS):
            scope = self.task_scope(task["id"])
            if not scope or scope["project_id"] != project["id"]:
                continue
            if module and scope.get("module_id") != module["id"]:
                continue
            tasks.append(task)
        open_tasks = [item for item in tasks if item["status"] in self.OPEN_TASK_STATUSES]
        done = [item for item in tasks if item["status"] == "done"]
        dependency_blocked = sum(1 for item in open_tasks if self.blockers(item["id"]))
        completion_ready = sum(
            1
            for item in open_tasks
            if self.completion_assessment(item["id"])["status"] == "ready_for_confirmation"
        )
        uncertainties = self.uncertainties(
            project_id=project["id"],
            module_id=module["id"] if module else None,
            limit=200,
        )
        checks = {
            "tasks_total": len(tasks),
            "tasks_open": len(open_tasks),
            "tasks_done": len(done),
            "dependency_blocked": dependency_blocked,
            "completion_ready": completion_ready,
            "open_uncertainties": len(uncertainties),
            "high_uncertainties": sum(1 for item in uncertainties if item["severity"] == "high"),
        }
        denominator = max(len(tasks), 1)
        score = max(
            0.0,
            min(
                1.0,
                (len(done) / denominator)
                + (completion_ready * 0.08)
                - (dependency_blocked * 0.06)
                - (checks["high_uncertainties"] * 0.08),
            ),
        )
        if checks["high_uncertainties"] or dependency_blocked:
            status = "attention"
        elif open_tasks:
            status = "in_progress"
        else:
            status = "stable"
        result = {
            "engine": "cognitive-self-eval-v1",
            "project": project,
            "module": module,
            "status": status,
            "score": round(score, 4),
            "checks": checks,
            "automatic_mutations": False,
        }
        if persist:
            with self._connect() as db:
                db.execute(
                    """
                    INSERT INTO cognitive_evaluations(
                        id, project_id, module_id, task_id, status, score, checks_json, created_at
                    ) VALUES(?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        project["id"],
                        module["id"] if module else None,
                        status,
                        score,
                        self._json(checks),
                        self._now(),
                    ),
                )
        return result

    def context(
        self,
        query: str,
        *,
        ui_context: Any = None,
        for_cloud: bool = True,
    ) -> dict[str, Any]:
        scheduler = self.scheduler(query, context=ui_context, for_cloud=for_cloud)
        selected = scheduler.get("selected") if isinstance(scheduler.get("selected"), dict) else None
        task_id = str(selected.get("id") or "") if selected else ""
        meta = self.metacognition(task_id or None)
        project = selected.get("project") if selected else self.project_by_key(self.PROJECT_KEY)
        module = selected.get("module") if selected else None
        if for_cloud and not selected and isinstance(project, dict):
            project = {
                "id": project.get("id"),
                "key": project.get("key"),
                "title": (
                    project.get("title")
                    if self.memory_v4._cloud_text_allowed(project.get("title"))
                    else None
                ),
            }
        project_id = project.get("id") if isinstance(project, dict) else None
        module_id = module.get("id") if isinstance(module, dict) else None
        strategies = (
            self.strategies(project_id=project_id, module_id=module_id, limit=5)
            if project_id
            else []
        )
        if for_cloud:
            strategies = [
                item
                for item in strategies
                if self.memory_v4._cloud_text_allowed(item.get("pattern"), item.get("strategy"))
            ]
            if isinstance(meta.get("uncertain"), list):
                meta["uncertain"] = [
                    item
                    for item in meta["uncertain"]
                    if self.memory_v4._cloud_text_allowed(
                        item.get("question"), item.get("evidence_needed")
                    )
                ][:5]
        return {
            "engine": "cognitive-project-brain-v1",
            "version": self.VERSION,
            "scheduler": scheduler,
            "metacognition": meta,
            "strategies": strategies[:5],
            "portfolio": {
                "projects": len(self.projects()),
                "modules": len(self.modules()),
                "project": project,
                "module": module,
            },
            "mutation_policy": "read_only_for_llm",
        }

    def status(self) -> dict[str, Any]:
        with self._connect() as db:
            counts = {
                "projects": db.execute("SELECT COUNT(*) FROM cognitive_projects").fetchone()[0],
                "modules": db.execute("SELECT COUNT(*) FROM cognitive_modules").fetchone()[0],
                "task_scopes": db.execute("SELECT COUNT(*) FROM cognitive_task_scope").fetchone()[0],
                "dependencies": db.execute("SELECT COUNT(*) FROM cognitive_task_edges").fetchone()[0],
                "uncertainties": db.execute(
                    "SELECT COUNT(*) FROM cognitive_uncertainties WHERE status='open'"
                ).fetchone()[0],
                "strategies": db.execute("SELECT COUNT(*) FROM cognitive_strategies").fetchone()[0],
                "replan_proposals": db.execute(
                    "SELECT COUNT(*) FROM cognitive_plan_revisions WHERE status='proposed'"
                ).fetchone()[0],
                "evaluations": db.execute("SELECT COUNT(*) FROM cognitive_evaluations").fetchone()[0],
                "causal_links": db.execute("SELECT COUNT(*) FROM cognitive_causal_links").fetchone()[0],
            }
        return {
            "version": self.VERSION,
            "engine": "cognitive-project-brain-v1",
            "capabilities": {
                "multi_project": True,
                "multi_module": True,
                "task_graph": True,
                "completion_criteria": True,
                "cognitive_scheduler": True,
                "uncertainty": True,
                "strategy_memory": True,
                "causal_reasoning": "conservative_evidence_links",
                "replanning": True,
                "self_evaluation": True,
                "metacognition": True,
                "long_horizon_restore": True,
            },
            "counts": counts,
            "mutation_policy": "action_broker_or_explicit_local_only",
        }
