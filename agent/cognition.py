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

    VERSION = "1.3.1"
    PROJECT_KEY = "sayuri-tsukishiro"
    DEPENDENCY_RELATIONS = {"requires", "blocks", "unlocks", "follows"}
    OPEN_TASK_STATUSES = {"planned", "in_progress", "blocked"}
    MAX_PROJECTS = 100
    MAX_MODULES = 500
    MAX_TASKS = 1000
    MAX_MILESTONES = 1000
    MAX_EXTERNAL_BLOCKERS = 2000

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
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognitive_milestones (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    module_id TEXT,
                    milestone_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, milestone_key)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognitive_milestone_tasks (
                    milestone_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    required INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(milestone_id, task_id)
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_cognitive_milestone_tasks_task ON cognitive_milestone_tasks(task_id)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognitive_external_blockers (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    module_id TEXT,
                    task_id TEXT,
                    blocker_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_project_id TEXT,
                    source_milestone_id TEXT,
                    evidence_ref TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolution TEXT,
                    UNIQUE(project_id, task_id, blocker_key)
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_cognitive_external_blockers_scope ON cognitive_external_blockers(project_id, module_id, task_id, status)"
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
                current_count = int(
                    db.execute("SELECT COUNT(*) FROM cognitive_projects").fetchone()[0]
                )
                if current_count >= self.MAX_PROJECTS:
                    raise CognitiveBrainError("Достигнут лимит зарегистрированных проектов.")
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
        project = self.project_by_key(project_key) or self.register_project(project_key)
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
                current_count = int(
                    db.execute("SELECT COUNT(*) FROM cognitive_modules").fetchone()[0]
                )
                if current_count >= self.MAX_MODULES:
                    raise CognitiveBrainError("Достигнут лимит зарегистрированных модулей.")
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
                existing_metadata = self._decode(row["metadata_json"], {})
                merged_metadata = (
                    {**existing_metadata, **metadata}
                    if isinstance(metadata, dict)
                    else existing_metadata
                )
                next_title = display if title is not None else row["title"]
                db.execute(
                    """
                    UPDATE cognitive_modules
                    SET title = ?, path = COALESCE(NULLIF(?, ''), path),
                        metadata_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        next_title,
                        path[:500],
                        self._json(merged_metadata),
                        now,
                        row["id"],
                    ),
                )
                row = db.execute(
                    "SELECT * FROM cognitive_modules WHERE id = ?",
                    (row["id"],),
                ).fetchone()
        return self._module_row(row)

    @staticmethod
    def _milestone_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "module_id": row["module_id"],
            "key": row["milestone_key"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "priority": row["priority"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def register_milestone(
        self,
        project_key: str,
        milestone_key: str,
        *,
        title: str | None = None,
        module_key: str | None = None,
        description: str = "",
        priority: int = 3,
    ) -> dict[str, Any]:
        project = self.project_by_key(project_key) or self.register_project(project_key)
        module = None
        if module_key:
            module = self.module_by_key(project["key"], module_key)
            if module is None:
                module = self.register_module(project["key"], module_key, title=module_key)
        key = self._key(milestone_key)
        if not key:
            raise CognitiveBrainError("Ключ milestone не может быть пустым.")
        display = " ".join((title or milestone_key).strip().split())[:300]
        if not display:
            raise CognitiveBrainError("Название milestone не может быть пустым.")
        normalized_priority = min(max(int(priority), 1), 5)
        now = self._now()
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM cognitive_milestones
                WHERE project_id = ? AND milestone_key = ?
                """,
                (project["id"], key),
            ).fetchone()
            if row is None:
                current_count = int(
                    db.execute("SELECT COUNT(*) FROM cognitive_milestones").fetchone()[0]
                )
                if current_count >= self.MAX_MILESTONES:
                    raise CognitiveBrainError("Достигнут лимит portfolio milestones.")
                milestone_id = uuid.uuid4().hex
                db.execute(
                    """
                    INSERT INTO cognitive_milestones(
                        id, project_id, module_id, milestone_key, title,
                        description, status, priority, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?)
                    """,
                    (
                        milestone_id,
                        project["id"],
                        module["id"] if module else None,
                        key,
                        display,
                        description[:2000] or None,
                        normalized_priority,
                        now,
                        now,
                    ),
                )
                row = db.execute(
                    "SELECT * FROM cognitive_milestones WHERE id = ?",
                    (milestone_id,),
                ).fetchone()
            else:
                db.execute(
                    """
                    UPDATE cognitive_milestones
                    SET title=?, module_id=COALESCE(?, module_id),
                        description=COALESCE(NULLIF(?, ''), description),
                        priority=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        display,
                        module["id"] if module else None,
                        description[:2000],
                        normalized_priority,
                        now,
                        row["id"],
                    ),
                )
                row = db.execute(
                    "SELECT * FROM cognitive_milestones WHERE id = ?",
                    (row["id"],),
                ).fetchone()
        return self._milestone_row(row)

    def milestones(
        self,
        *,
        project_key: str | None = None,
        module_key: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        project = self.project_by_key(project_key) if project_key else None
        if project_key and not project:
            return []
        module = (
            self.module_by_key(project["key"], module_key)
            if project and module_key
            else None
        )
        if module_key and project and not module:
            return []
        if project:
            clauses.append("project_id = ?")
            params.append(project["id"])
        if module:
            clauses.append("module_id = ?")
            params.append(module["id"])
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(min(max(int(limit), 1), 300))
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM cognitive_milestones
                {where}
                ORDER BY priority DESC, updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._milestone_row(row) for row in rows]

    def link_milestone_task(
        self,
        milestone_id: str,
        task_id: str,
        *,
        required: bool = True,
    ) -> dict[str, Any]:
        with self._connect() as db:
            milestone = db.execute(
                "SELECT * FROM cognitive_milestones WHERE id = ?",
                (milestone_id,),
            ).fetchone()
        if milestone is None:
            raise CognitiveBrainError("Milestone не найден.")
        task = next(
            (
                item
                for item in self.memory_v4.tasks(limit=self.MAX_TASKS)
                if item["id"] == task_id
            ),
            None,
        )
        if task is None:
            raise CognitiveBrainError("Задача milestone не найдена.")
        scope = self.task_scope(task_id) or self.bind_task(task_id)
        if scope["project_id"] != milestone["project_id"]:
            raise CognitiveBrainError(
                "Milestone может включать только задачи своего проекта."
            )
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO cognitive_milestone_tasks(
                    milestone_id, task_id, required, created_at
                ) VALUES(?, ?, ?, ?)
                ON CONFLICT(milestone_id, task_id)
                DO UPDATE SET required=excluded.required
                """,
                (milestone_id, task_id, 1 if required else 0, self._now()),
            )
        return {
            "milestone_id": milestone_id,
            "task_id": task_id,
            "required": bool(required),
        }

    def milestone_assessment(self, milestone_id: str) -> dict[str, Any]:
        with self._connect() as db:
            milestone = db.execute(
                "SELECT * FROM cognitive_milestones WHERE id = ?",
                (milestone_id,),
            ).fetchone()
            links = db.execute(
                """
                SELECT task_id, required
                FROM cognitive_milestone_tasks
                WHERE milestone_id = ?
                """,
                (milestone_id,),
            ).fetchall()
        if milestone is None:
            raise CognitiveBrainError("Milestone не найден.")
        tasks = {
            item["id"]: item
            for item in self.memory_v4.tasks(limit=self.MAX_TASKS)
        }
        required_ids = [str(row["task_id"]) for row in links if row["required"]]
        optional_ids = [str(row["task_id"]) for row in links if not row["required"]]
        required_done = sum(
            1
            for task_id in required_ids
            if tasks.get(task_id, {}).get("status") == "done"
        )
        optional_done = sum(
            1
            for task_id in optional_ids
            if tasks.get(task_id, {}).get("status") == "done"
        )
        if not required_ids:
            status = "criteria_missing"
        elif required_done == len(required_ids):
            status = "ready_for_confirmation"
        else:
            status = "incomplete"
        return {
            "milestone": self._milestone_row(milestone),
            "status": status,
            "required_done": required_done,
            "required_total": len(required_ids),
            "optional_done": optional_done,
            "optional_total": len(optional_ids),
            "automatic_completion": False,
        }

    def complete_milestone(
        self,
        milestone_id: str,
        *,
        confirmation: str,
    ) -> dict[str, Any]:
        if confirmation != "COMPLETE_MILESTONE":
            raise CognitiveBrainError(
                "Требуется явное подтверждение COMPLETE_MILESTONE."
            )
        assessment = self.milestone_assessment(milestone_id)
        if assessment["status"] != "ready_for_confirmation":
            raise CognitiveBrainError(
                "Milestone нельзя завершить: обязательные задачи ещё не выполнены."
            )
        now = self._now()
        with self._connect() as db:
            db.execute(
                """
                UPDATE cognitive_milestones
                SET status='done', updated_at=?
                WHERE id=?
                """,
                (now, milestone_id),
            )
            row = db.execute(
                "SELECT * FROM cognitive_milestones WHERE id = ?",
                (milestone_id,),
            ).fetchone()
        return {
            "status": "done",
            "milestone": self._milestone_row(row),
            "automatic_completion": False,
        }

    @staticmethod
    def _external_blocker_row(
        row: sqlite3.Row,
        *,
        source_milestone_status: str | None = None,
    ) -> dict[str, Any]:
        derived_resolution = bool(
            row["source_milestone_id"]
            and source_milestone_status == "done"
        )
        effective_status = (
            "resolved"
            if row["status"] == "resolved" or derived_resolution
            else row["status"]
        )
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "module_id": row["module_id"],
            "task_id": row["task_id"],
            "key": row["blocker_key"],
            "title": row["title"],
            "status": row["status"],
            "effective_status": effective_status,
            "source_project_id": row["source_project_id"],
            "source_milestone_id": row["source_milestone_id"],
            "evidence_ref": row["evidence_ref"],
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
            "resolution": row["resolution"],
            "derived_resolution": derived_resolution,
        }

    def _portfolio_dependency_adjacency(self) -> dict[str, set[str]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT b.project_id, b.source_project_id
                FROM cognitive_external_blockers b
                LEFT JOIN cognitive_milestones m
                  ON m.id=b.source_milestone_id
                WHERE b.status='open'
                  AND b.source_project_id IS NOT NULL
                  AND (
                    b.source_milestone_id IS NULL
                    OR COALESCE(m.status, '') != 'done'
                  )
                """
            ).fetchall()
        adjacency: dict[str, set[str]] = {}
        for row in rows:
            target = str(row["project_id"] or "")
            source = str(row["source_project_id"] or "")
            if target and source:
                adjacency.setdefault(target, set()).add(source)
        return adjacency

    def _would_create_portfolio_cycle(
        self,
        target_project_id: str,
        source_project_id: str,
    ) -> bool:
        if target_project_id == source_project_id:
            return True
        adjacency = self._portfolio_dependency_adjacency()
        stack = [source_project_id]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current == target_project_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(adjacency.get(current, set()) - seen)
        return False

    def add_external_blocker(
        self,
        project_key: str,
        blocker_key: str,
        title: str,
        *,
        task_id: str | None = None,
        module_key: str | None = None,
        source_project_key: str | None = None,
        source_milestone_id: str | None = None,
        evidence_ref: str = "explicit_local_api",
    ) -> dict[str, Any]:
        project = self.project_by_key(project_key) or self.register_project(project_key)
        module = None
        if module_key:
            module = self.module_by_key(project["key"], module_key)
            if module is None:
                module = self.register_module(project["key"], module_key, title=module_key)
        if task_id:
            scope = self.task_scope(task_id) or self.bind_task(task_id)
            if scope["project_id"] != project["id"]:
                raise CognitiveBrainError(
                    "External blocker должен принадлежать проекту связанной задачи."
                )
        source_project = (
            self.project_by_key(source_project_key)
            if source_project_key
            else None
        )
        if source_project_key and source_project is None:
            raise CognitiveBrainError("Исходный project external blocker не найден.")
        source_milestone = None
        if source_milestone_id:
            with self._connect() as db:
                source_milestone = db.execute(
                    "SELECT * FROM cognitive_milestones WHERE id = ?",
                    (source_milestone_id,),
                ).fetchone()
            if source_milestone is None:
                raise CognitiveBrainError("Исходный milestone external blocker не найден.")
            if source_project and source_milestone["project_id"] != source_project["id"]:
                raise CognitiveBrainError(
                    "Исходный milestone не принадлежит source project."
                )
            if source_project is None:
                with self._connect() as db:
                    source_row = db.execute(
                        "SELECT * FROM cognitive_projects WHERE id = ?",
                        (source_milestone["project_id"],),
                    ).fetchone()
                source_project = self._project_row(source_row) if source_row else None
        if source_project and self._would_create_portfolio_cycle(
            project["id"],
            source_project["id"],
        ):
            raise CognitiveBrainError(
                "External blocker создаёт цикл между проектами portfolio."
            )
        key = self._key(blocker_key)
        label = " ".join((title or blocker_key).strip().split())[:500]
        if not key or not label:
            raise CognitiveBrainError("External blocker должен иметь key и title.")
        now = self._now()
        with self._connect() as db:
            existing = db.execute(
                """
                SELECT * FROM cognitive_external_blockers
                WHERE project_id=?
                  AND COALESCE(task_id, '')=COALESCE(?, '')
                  AND blocker_key=?
                """,
                (project["id"], task_id, key),
            ).fetchone()
            if existing is None:
                current_count = int(
                    db.execute(
                        "SELECT COUNT(*) FROM cognitive_external_blockers"
                    ).fetchone()[0]
                )
                if current_count >= self.MAX_EXTERNAL_BLOCKERS:
                    raise CognitiveBrainError("Достигнут лимит external blockers.")
                blocker_id = uuid.uuid4().hex
                db.execute(
                    """
                    INSERT INTO cognitive_external_blockers(
                        id, project_id, module_id, task_id, blocker_key,
                        title, status, source_project_id, source_milestone_id,
                        evidence_ref, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
                    """,
                    (
                        blocker_id,
                        project["id"],
                        module["id"] if module else None,
                        task_id or None,
                        key,
                        label,
                        source_project["id"] if source_project else None,
                        source_milestone_id or None,
                        evidence_ref[:500] or None,
                        now,
                    ),
                )
            else:
                blocker_id = existing["id"]
                db.execute(
                    """
                    UPDATE cognitive_external_blockers
                    SET title=?,
                        module_id=COALESCE(?, module_id),
                        source_project_id=COALESCE(?, source_project_id),
                        source_milestone_id=COALESCE(?, source_milestone_id),
                        evidence_ref=COALESCE(NULLIF(?, ''), evidence_ref)
                    WHERE id=?
                    """,
                    (
                        label,
                        module["id"] if module else None,
                        source_project["id"] if source_project else None,
                        source_milestone_id or None,
                        evidence_ref[:500],
                        blocker_id,
                    ),
                )
            row = db.execute(
                """
                SELECT b.*, m.status AS source_milestone_status
                FROM cognitive_external_blockers b
                LEFT JOIN cognitive_milestones m
                  ON m.id=b.source_milestone_id
                WHERE b.id=?
                """,
                (blocker_id,),
            ).fetchone()
        return self._external_blocker_row(
            row,
            source_milestone_status=row["source_milestone_status"],
        )

    def external_blockers(
        self,
        *,
        project_id: str | None = None,
        module_id: str | None = None,
        task_id: str | None = None,
        effective_open_only: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id:
            clauses.append("b.project_id = ?")
            params.append(project_id)
        if module_id:
            clauses.append("(b.module_id IS NULL OR b.module_id = ?)")
            params.append(module_id)
        if task_id:
            clauses.append("(b.task_id IS NULL OR b.task_id = ?)")
            params.append(task_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(min(max(int(limit), 1), 500))
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT b.*, m.status AS source_milestone_status
                FROM cognitive_external_blockers b
                LEFT JOIN cognitive_milestones m
                  ON m.id=b.source_milestone_id
                {where}
                ORDER BY b.created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        result = [
            self._external_blocker_row(
                row,
                source_milestone_status=row["source_milestone_status"],
            )
            for row in rows
        ]
        if effective_open_only:
            result = [
                item
                for item in result
                if item["effective_status"] == "open"
            ]
        return result

    def resolve_external_blocker(
        self,
        blocker_id: str,
        resolution: str,
    ) -> dict[str, Any]:
        text = " ".join((resolution or "").strip().split())[:2000]
        if not text:
            raise CognitiveBrainError("Нужно указать resolution external blocker.")
        now = self._now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM cognitive_external_blockers WHERE id=?",
                (blocker_id,),
            ).fetchone()
            if row is None:
                raise CognitiveBrainError("External blocker не найден.")
            db.execute(
                """
                UPDATE cognitive_external_blockers
                SET status='resolved', resolved_at=?, resolution=?
                WHERE id=?
                """,
                (now, text, blocker_id),
            )
            row = db.execute(
                """
                SELECT b.*, m.status AS source_milestone_status
                FROM cognitive_external_blockers b
                LEFT JOIN cognitive_milestones m
                  ON m.id=b.source_milestone_id
                WHERE b.id=?
                """,
                (blocker_id,),
            ).fetchone()
        return self._external_blocker_row(
            row,
            source_milestone_status=row["source_milestone_status"],
        )

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
        with self._connect() as db:
            known = {
                str(row["task_id"])
                for row in db.execute(
                    "SELECT task_id FROM cognitive_task_scope"
                ).fetchall()
            }
        count = 0
        for task in tasks:
            task_id = str(task["id"])
            if task_id in known:
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
                attention_state=(
                    "blocked" if task.get("status") == "blocked" else "active"
                ),
                confidence=(
                    0.65
                    if task.get("source")
                    in {"manual", "memory_intelligence_confirmed", "personal_cabinet"}
                    else 0.5
                ),
            )
            known.add(task_id)
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
            milestone_rows = db.execute(
                "SELECT * FROM cognitive_milestones"
            ).fetchall()
            milestone_links = db.execute(
                "SELECT * FROM cognitive_milestone_tasks"
            ).fetchall()
            portfolio_rows = db.execute(
                """
                SELECT b.project_id, b.source_project_id
                FROM cognitive_external_blockers b
                LEFT JOIN cognitive_milestones m
                  ON m.id=b.source_milestone_id
                WHERE b.status='open'
                  AND b.source_project_id IS NOT NULL
                  AND (
                    b.source_milestone_id IS NULL
                    OR COALESCE(m.status, '') != 'done'
                  )
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
        snapshot = self._scheduler_snapshot()
        return self._completion_from_snapshot(task_id, snapshot)

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

    def _scheduler_snapshot(self) -> dict[str, Any]:
        """Read portfolio state once for scheduler/evaluation scale."""
        task_items = self.memory_v4.tasks(limit=self.MAX_TASKS)
        tasks = {str(item["id"]): item for item in task_items}
        with self._connect() as db:
            scopes = {
                str(row["task_id"]): self._scope_row(row)
                for row in db.execute(
                    "SELECT * FROM cognitive_task_scope"
                ).fetchall()
            }
            projects = {
                str(row["id"]): self._project_row(row)
                for row in db.execute(
                    "SELECT * FROM cognitive_projects"
                ).fetchall()
            }
            modules = {
                str(row["id"]): self._module_row(row)
                for row in db.execute(
                    "SELECT * FROM cognitive_modules"
                ).fetchall()
            }
            edge_rows = db.execute(
                """
                SELECT * FROM cognitive_task_edges
                WHERE confirmed = 1
                """
            ).fetchall()
            uncertainty_rows = db.execute(
                """
                SELECT * FROM cognitive_uncertainties
                WHERE status = 'open'
                """
            ).fetchall()
            checkpoint_total_rows = db.execute(
                """
                SELECT task_id, COUNT(*) AS total
                FROM memory_task_checkpoints
                WHERE applied = 1
                GROUP BY task_id
                """
            ).fetchall()
            checkpoint_tool_rows = db.execute(
                """
                SELECT task_id, tool, COUNT(*) AS total
                FROM memory_task_checkpoints
                WHERE applied = 1
                GROUP BY task_id, tool
                """
            ).fetchall()
            milestone_rows = db.execute(
                "SELECT * FROM cognitive_milestones"
            ).fetchall()
            milestone_task_rows = db.execute(
                "SELECT * FROM cognitive_milestone_tasks"
            ).fetchall()
            external_rows = db.execute(
                """
                SELECT b.*, m.status AS source_milestone_status
                FROM cognitive_external_blockers b
                LEFT JOIN cognitive_milestones m
                  ON m.id=b.source_milestone_id
                WHERE b.status='open'
                """
            ).fetchall()

        blockers: dict[str, list[dict[str, Any]]] = {}
        for row in edge_rows:
            edge = {
                "source_task_id": row["source_task_id"],
                "target_task_id": row["target_task_id"],
                "relation": row["relation"],
                "confirmed": bool(row["confirmed"]),
            }
            pair = self._edge_dependency_pair(edge)
            if not pair:
                continue
            dependent, prerequisite = pair
            prerequisite_task = tasks.get(prerequisite)
            if prerequisite_task and prerequisite_task.get("status") != "done":
                blockers.setdefault(dependent, []).append(
                    {
                        "task_id": prerequisite,
                        "title": prerequisite_task.get("title"),
                        "status": prerequisite_task.get("status"),
                        "relation": edge["relation"],
                    }
                )

        uncertainties: dict[str, list[dict[str, Any]]] = {}
        for row in uncertainty_rows:
            task_id = str(row["task_id"] or "")
            if not task_id:
                continue
            uncertainties.setdefault(task_id, []).append(
                {
                    "id": row["id"],
                    "question": row["question"],
                    "severity": row["severity"],
                    "evidence_needed": row["evidence_needed"],
                    "source_ref": row["source_ref"],
                }
            )

        checkpoint_totals = {
            str(row["task_id"]): int(row["total"])
            for row in checkpoint_total_rows
        }
        checkpoint_tools = {
            (str(row["task_id"]), str(row["tool"])): int(row["total"])
            for row in checkpoint_tool_rows
        }
        milestones = {
            str(row["id"]): self._milestone_row(row)
            for row in milestone_rows
        }
        milestone_tasks: dict[str, list[dict[str, Any]]] = {}
        task_milestones: dict[str, list[dict[str, Any]]] = {}
        for row in milestone_task_rows:
            milestone_id = str(row["milestone_id"])
            task_id = str(row["task_id"])
            link = {
                "milestone_id": milestone_id,
                "task_id": task_id,
                "required": bool(row["required"]),
            }
            milestone_tasks.setdefault(milestone_id, []).append(link)
            milestone = milestones.get(milestone_id)
            if milestone:
                task_milestones.setdefault(task_id, []).append(
                    {**milestone, "required": bool(row["required"])}
                )
        external_by_project: dict[str, list[dict[str, Any]]] = {}
        external_by_module: dict[str, list[dict[str, Any]]] = {}
        external_by_task: dict[str, list[dict[str, Any]]] = {}
        for row in external_rows:
            item = self._external_blocker_row(
                row,
                source_milestone_status=row["source_milestone_status"],
            )
            if item["effective_status"] != "open":
                continue
            blocker = {
                "type": "external_blocker",
                "key": item["key"],
                "title": item["title"],
                "source_project_id": item["source_project_id"],
                "source_milestone_id": item["source_milestone_id"],
            }
            if item.get("task_id"):
                external_by_task.setdefault(str(item["task_id"]), []).append(blocker)
            elif item.get("module_id"):
                external_by_module.setdefault(str(item["module_id"]), []).append(blocker)
            else:
                external_by_project.setdefault(str(item["project_id"]), []).append(blocker)
        return {
            "tasks": tasks,
            "scopes": scopes,
            "projects": projects,
            "modules": modules,
            "blockers": blockers,
            "uncertainties": uncertainties,
            "checkpoint_totals": checkpoint_totals,
            "checkpoint_tools": checkpoint_tools,
            "milestones": milestones,
            "milestone_tasks": milestone_tasks,
            "task_milestones": task_milestones,
            "external_by_project": external_by_project,
            "external_by_module": external_by_module,
            "external_by_task": external_by_task,
        }

    def _blockers_from_snapshot(
        self,
        task_id: str,
        snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        result = [
            {"type": "task_dependency", **item}
            for item in snapshot["blockers"].get(task_id, [])
        ]
        scope = snapshot["scopes"].get(task_id)
        if not scope:
            return result
        result.extend(
            snapshot["external_by_project"].get(
                str(scope.get("project_id")),
                [],
            )
        )
        if scope.get("module_id"):
            result.extend(
                snapshot["external_by_module"].get(
                    str(scope.get("module_id")),
                    [],
                )
            )
        result.extend(snapshot["external_by_task"].get(task_id, []))
        return result

    def _completion_from_snapshot(
        self,
        task_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        scope = snapshot["scopes"].get(task_id)
        criteria = list(scope.get("completion_criteria", [])) if scope else []
        task_blockers = self._blockers_from_snapshot(task_id, snapshot)
        checks: list[dict[str, Any]] = []
        for criterion in criteria:
            kind = criterion.get("type")
            satisfied = False
            detail = ""
            if kind == "checkpoint_count":
                required = int(criterion.get("min") or 1)
                found = int(snapshot["checkpoint_totals"].get(task_id, 0))
                satisfied = found >= required
                detail = f"{found}/{required} applied checkpoints"
            elif kind == "tool_completed":
                tool = str(criterion.get("tool") or "")
                required = int(criterion.get("min") or 1)
                found = int(
                    snapshot["checkpoint_tools"].get((task_id, tool), 0)
                )
                satisfied = bool(tool) and found >= required
                detail = f"{found}/{required} confirmed {tool}"
            elif kind == "dependency_done":
                dependency = snapshot["tasks"].get(
                    str(criterion.get("task_id") or "")
                )
                satisfied = bool(
                    dependency and dependency.get("status") == "done"
                )
                detail = str(
                    dependency.get("status") if dependency else "missing"
                )
            elif kind == "manual_confirmation":
                satisfied = bool(criterion.get("confirmed"))
                detail = (
                    "confirmed"
                    if satisfied
                    else "requires explicit confirmation"
                )
            checks.append(
                {
                    "criterion": criterion,
                    "satisfied": satisfied,
                    "detail": detail,
                }
            )
        satisfied_count = sum(1 for item in checks if item["satisfied"])
        total = len(checks)
        if task_blockers:
            status = (
                "blocked_by_external"
                if any(item.get("type") == "external_blocker" for item in task_blockers)
                else "blocked_by_dependencies"
            )
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
            "blockers": task_blockers,
            "automatic_completion": False,
        }

    @staticmethod
    def _scope_view_for_cloud(
        item: dict[str, Any] | None,
        cloud_allowed: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        title = item.get("title")
        return {
            "key": item.get("key"),
            "title": title if cloud_allowed(title) else None,
        }

    def _scheduler_projection_for_cloud(
        self,
        scheduler: dict[str, Any],
    ) -> dict[str, Any]:
        def safe_candidate(raw: Any) -> dict[str, Any] | None:
            if not isinstance(raw, dict):
                return None
            if not self.memory_v4._cloud_text_allowed(
                raw.get("title"),
                raw.get("next_action"),
                raw.get("blocked_reason"),
            ):
                return None
            blockers = []
            for item in raw.get("blockers", [])[:5]:
                if not isinstance(item, dict):
                    continue
                if not self.memory_v4._cloud_text_allowed(item.get("title")):
                    continue
                blockers.append(
                    {
                        "type": item.get("type"),
                        "title": item.get("title"),
                        "status": item.get("status"),
                        "relation": item.get("relation"),
                        "key": item.get("key"),
                    }
                )
            milestones = []
            for item in raw.get("milestones", [])[:3]:
                if not isinstance(item, dict):
                    continue
                title = item.get("title")
                milestones.append(
                    {
                        "key": item.get("key"),
                        "title": (
                            title
                            if self.memory_v4._cloud_text_allowed(title)
                            else None
                        ),
                        "priority": item.get("priority"),
                        "required": item.get("required"),
                    }
                )
            completion = raw.get("completion")
            completion = completion if isinstance(completion, dict) else {}
            return {
                "title": raw.get("title"),
                "status": raw.get("status"),
                "priority": raw.get("priority"),
                "next_action": raw.get("next_action"),
                "blocked_reason": raw.get("blocked_reason"),
                "project": self._scope_view_for_cloud(
                    raw.get("project"),
                    self.memory_v4._cloud_text_allowed,
                ),
                "module": self._scope_view_for_cloud(
                    raw.get("module"),
                    self.memory_v4._cloud_text_allowed,
                ),
                "blockers": blockers,
                "uncertainty_count": raw.get("uncertainty_count"),
                "high_uncertainty_count": raw.get("high_uncertainty_count"),
                "milestones": milestones,
                "completion": {
                    "status": completion.get("status"),
                    "score": completion.get("score"),
                    "satisfied": completion.get("satisfied"),
                    "total": completion.get("total"),
                },
                "attention_state": raw.get("attention_state"),
                "confidence": raw.get("confidence"),
                "query_overlap": raw.get("query_overlap"),
            }

        candidates = []
        for item in scheduler.get("candidates", [])[:8]:
            projected = safe_candidate(item)
            if projected is not None:
                candidates.append(projected)
        selected = safe_candidate(scheduler.get("selected"))
        return {
            "engine": scheduler.get("engine"),
            "selected": selected,
            "recommendation": scheduler.get("recommendation"),
            "open_tasks": scheduler.get("open_tasks"),
            "actionable_tasks": scheduler.get("actionable_tasks"),
            "blocked_by_dependencies": scheduler.get("blocked_by_dependencies"),
            "blocked_by_external": scheduler.get("blocked_by_external"),
            "candidates": candidates,
        }

    def scheduler(
        self,
        query: str = "",
        *,
        context: Any = None,
        for_cloud: bool = False,
        _snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = _snapshot or self._scheduler_snapshot()
        raw_tasks = [
            item
            for item in snapshot["tasks"].values()
            if item.get("status") in self.OPEN_TASK_STATUSES
        ]
        query_tokens = self._tokens(query)
        context_project = self._key(self._context_key(context, "project"))
        context_module = self.module_key_from_context(context)
        candidates: list[tuple[int, str, dict[str, Any]]] = []

        for task in raw_tasks:
            if for_cloud and not self.memory_v4._cloud_text_allowed(
                task.get("title"),
                task.get("next_action"),
                task.get("blocked_reason"),
            ):
                continue
            task_id = str(task["id"])
            scope = snapshot["scopes"].get(task_id)
            if not scope:
                continue
            project = snapshot["projects"].get(str(scope.get("project_id")))
            if context_project and (
                not project or project.get("key") != context_project
            ):
                continue
            module = (
                snapshot["modules"].get(str(scope.get("module_id")))
                if scope.get("module_id")
                else None
            )
            project_view = (
                self._scope_view_for_cloud(
                    project, self.memory_v4._cloud_text_allowed
                )
                if for_cloud
                else project
            )
            module_view = (
                self._scope_view_for_cloud(
                    module, self.memory_v4._cloud_text_allowed
                )
                if for_cloud
                else module
            )
            task_blockers = self._blockers_from_snapshot(task_id, snapshot)
            open_uncertainty = list(
                snapshot["uncertainties"].get(task_id, [])
            )
            high_uncertainty = [
                item
                for item in open_uncertainty
                if item.get("severity") == "high"
            ]
            assessment = self._completion_from_snapshot(task_id, snapshot)
            active_milestones = [
                item
                for item in snapshot["task_milestones"].get(task_id, [])
                if item.get("status") not in {"done", "cancelled"}
            ]
            overlap = len(
                query_tokens
                & self._tokens(task.get("title"), task.get("next_action"))
            )
            score = int(task.get("priority") or 1) * 10
            score += {
                "in_progress": 8,
                "planned": 5,
                "blocked": -20,
            }.get(str(task.get("status")), 0)
            score += overlap * 12
            if (
                context_project
                and project
                and project["key"] == context_project
            ):
                score += 12
            if context_module and module and module["key"] == context_module:
                score += 18
            score += sum(
                int(item.get("priority") or 1)
                for item in active_milestones
            )
            score -= len(task_blockers) * 100
            score -= sum(
                15 if item["severity"] == "high" else 5
                for item in open_uncertainty
            )
            if scope.get("attention_state") == "later":
                score -= 20
            if assessment["status"] == "ready_for_confirmation":
                score += 4
            candidate = {
                "id": task_id,
                "title": task.get("title"),
                "status": task.get("status"),
                "priority": task.get("priority"),
                "next_action": task.get("next_action"),
                "blocked_reason": task.get("blocked_reason"),
                "project": project_view,
                "module": module_view,
                "blockers": task_blockers,
                "uncertainty_count": len(open_uncertainty),
                "high_uncertainty_count": len(high_uncertainty),
                "milestones": [
                    {
                        "key": item.get("key"),
                        "title": item.get("title"),
                        "priority": item.get("priority"),
                        "required": item.get("required"),
                    }
                    for item in active_milestones[:3]
                ],
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
            candidates.append(
                (score, str(task.get("updated_at") or ""), candidate)
            )

        candidates.sort(
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
        actionable = [
            item
            for item in candidates
            if not item[2]["blockers"] and item[2]["status"] != "blocked"
        ]
        selected = actionable[0][2] if actionable else None
        if selected:
            if int(selected.get("high_uncertainty_count") or 0) > 0:
                recommendation = (
                    "Сначала получить недостающее доказательство для "
                    "high-uncertainty, затем пересчитать план."
                )
            elif (
                selected["completion"]["status"]
                == "ready_for_confirmation"
            ):
                recommendation = (
                    "Проверить критерии готовности и запросить явное "
                    "подтверждение завершения задачи."
                )
            elif selected.get("next_action"):
                recommendation = str(selected["next_action"])
            else:
                recommendation = (
                    "Определить ближайший проверяемый шаг задачи."
                )
        else:
            recommendation = (
                "Нет разблокированной задачи; проверить task dependencies, "
                "external blockers и uncertainties."
            )
        return {
            "engine": "cognitive-scheduler-v1.3",
            "selected": selected,
            "recommendation": recommendation,
            "open_tasks": len(raw_tasks),
            "actionable_tasks": len(actionable),
            "blocked_by_dependencies": sum(
                1
                for _, _, item in candidates
                if any(
                    blocker.get("type") == "task_dependency"
                    for blocker in item["blockers"]
                )
            ),
            "blocked_by_external": sum(
                1
                for _, _, item in candidates
                if any(
                    blocker.get("type") == "external_blocker"
                    for blocker in item["blockers"]
                )
            ),
            "candidates": [item[2] for item in candidates[:8]],
        }

    def metacognition(
        self,
        task_id: str | None = None,
        *,
        _snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = _snapshot or self._scheduler_snapshot()
        if not task_id:
            scheduled = self.scheduler()
            task_id = (
                scheduled.get("selected", {}).get("id")
                if isinstance(scheduled.get("selected"), dict)
                else None
            )
        if not task_id:
            return {
                "state": "idle",
                "known": [],
                "uncertain": [],
                "blocked": [],
                "replan_required": False,
            }
        task = snapshot["tasks"].get(str(task_id))
        if not task:
            return {"state": "missing_task", "task_id": task_id}
        blockers = self._blockers_from_snapshot(str(task_id), snapshot)
        uncertainties = list(
            snapshot["uncertainties"].get(str(task_id), [])
        )
        assessment = self._completion_from_snapshot(str(task_id), snapshot)
        replans = self.replan_proposals(str(task_id), limit=1)
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
            "causal_trace": self.causal_links(task_id=str(task_id), limit=5),
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
        module = (
            self.module_by_key(project["key"], module_key)
            if module_key
            else None
        )
        snapshot = self._scheduler_snapshot()
        tasks: list[dict[str, Any]] = []
        for task_id, task in snapshot["tasks"].items():
            scope = snapshot["scopes"].get(task_id)
            if not scope or scope["project_id"] != project["id"]:
                continue
            if module and scope.get("module_id") != module["id"]:
                continue
            tasks.append(task)
        open_tasks = [
            item
            for item in tasks
            if item["status"] in self.OPEN_TASK_STATUSES
        ]
        done = [item for item in tasks if item["status"] == "done"]
        dependency_blocked = 0
        external_blocked = 0
        for item in open_tasks:
            task_blockers = self._blockers_from_snapshot(
                str(item["id"]),
                snapshot,
            )
            if any(
                blocker.get("type") == "task_dependency"
                for blocker in task_blockers
            ):
                dependency_blocked += 1
            if any(
                blocker.get("type") == "external_blocker"
                for blocker in task_blockers
            ):
                external_blocked += 1
        completion_ready = sum(
            1
            for item in open_tasks
            if self._completion_from_snapshot(
                str(item["id"]), snapshot
            )["status"]
            == "ready_for_confirmation"
        )
        uncertainties = self.uncertainties(
            project_id=project["id"],
            module_id=module["id"] if module else None,
            limit=200,
        )
        project_milestones = [
            item
            for item in snapshot["milestones"].values()
            if item.get("project_id") == project["id"]
            and (
                not module
                or item.get("module_id") in {None, module["id"]}
            )
        ]
        milestone_ready = 0
        for milestone in project_milestones:
            links = snapshot["milestone_tasks"].get(milestone["id"], [])
            required_links = [link for link in links if link["required"]]
            if (
                required_links
                and milestone.get("status") != "done"
                and all(
                    snapshot["tasks"].get(link["task_id"], {}).get("status")
                    == "done"
                    for link in required_links
                )
            ):
                milestone_ready += 1
        checks = {
            "tasks_total": len(tasks),
            "tasks_open": len(open_tasks),
            "tasks_done": len(done),
            "dependency_blocked": dependency_blocked,
            "external_blocked": external_blocked,
            "completion_ready": completion_ready,
            "milestones_total": len(project_milestones),
            "milestones_ready": milestone_ready,
            "milestones_done": sum(
                1
                for item in project_milestones
                if item.get("status") == "done"
            ),
            "open_uncertainties": len(uncertainties),
            "high_uncertainties": sum(
                1
                for item in uncertainties
                if item.get("severity") == "high"
            ),
        }
        denominator = max(len(tasks), 1)
        score = max(
            0.0,
            min(
                1.0,
                (len(done) / denominator)
                + (completion_ready * 0.08)
                + (milestone_ready * 0.04)
                - (dependency_blocked * 0.06)
                - (external_blocked * 0.08)
                - (checks["high_uncertainties"] * 0.08),
            ),
        )
        if checks["high_uncertainties"] or dependency_blocked or external_blocked:
            status = "attention"
        elif open_tasks:
            status = "in_progress"
        else:
            status = "stable"
        result = {
            "engine": "cognitive-self-eval-v1.3",
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
                        id, project_id, module_id, task_id,
                        status, score, checks_json, created_at
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
        snapshot = self._scheduler_snapshot()
        local_scheduler = self.scheduler(
            query,
            context=ui_context,
            for_cloud=False,
            _snapshot=snapshot,
        )
        scheduler = (
            self._scheduler_projection_for_cloud(local_scheduler)
            if for_cloud
            else local_scheduler
        )
        selected_local = (
            local_scheduler.get("selected")
            if isinstance(local_scheduler.get("selected"), dict)
            else None
        )
        selected = (
            scheduler.get("selected")
            if isinstance(scheduler.get("selected"), dict)
            else None
        )
        fallback_candidate = (
            local_scheduler.get("candidates", [None])[0]
            if isinstance(local_scheduler.get("candidates"), list)
            and local_scheduler.get("candidates")
            else None
        )
        meta_task = (
            selected_local
            if selected_local
            else fallback_candidate
            if isinstance(fallback_candidate, dict)
            else None
        )
        task_id = (
            str(meta_task.get("id") or "")
            if isinstance(meta_task, dict)
            else ""
        )
        meta = self.metacognition(
            task_id or None,
            _snapshot=snapshot,
        )
        requested_project_key = self._key(
            self._context_key(ui_context, "project")
        )
        local_project_view = (
            selected_local.get("project")
            if selected_local
            else self.project_by_key(
                requested_project_key or self.PROJECT_KEY
            )
        )
        local_module_view = (
            selected_local.get("module")
            if selected_local
            else None
        )
        project = (
            self._scope_view_for_cloud(
                local_project_view,
                self.memory_v4._cloud_text_allowed,
            )
            if for_cloud
            else local_project_view
        )
        module = (
            self._scope_view_for_cloud(
                local_module_view,
                self.memory_v4._cloud_text_allowed,
            )
            if for_cloud
            else local_module_view
        )

        project_key = (
            str(local_project_view.get("key") or "")
            if isinstance(local_project_view, dict)
            else ""
        )
        module_key = (
            str(local_module_view.get("key") or "")
            if isinstance(local_module_view, dict)
            else ""
        )
        local_project = (
            self.project_by_key(project_key)
            if project_key
            else self.project_by_key(self.PROJECT_KEY)
        )
        local_module = (
            self.module_by_key(project_key, module_key)
            if project_key and module_key
            else None
        )
        strategies = (
            self.strategies(
                project_id=local_project.get("id"),
                module_id=local_module.get("id") if local_module else None,
                limit=5,
            )
            if isinstance(local_project, dict)
            else []
        )

        if for_cloud:
            # scheduler/project/module were already projected from local state.
            strategies = [
                {
                    "pattern": item.get("pattern"),
                    "strategy": item.get("strategy"),
                    "success_count": item.get("success_count"),
                    "failure_count": item.get("failure_count"),
                    "confidence": item.get("confidence"),
                    "last_outcome": item.get("last_outcome"),
                }
                for item in strategies
                if self.memory_v4._cloud_text_allowed(
                    item.get("pattern"),
                    item.get("strategy"),
                )
            ]
            meta = dict(meta)
            if isinstance(meta.get("uncertain"), list):
                meta["uncertain"] = [
                    {
                        "question": item.get("question"),
                        "severity": item.get("severity"),
                        "evidence_needed": item.get("evidence_needed"),
                    }
                    for item in meta["uncertain"][:5]
                    if self.memory_v4._cloud_text_allowed(
                        item.get("question"),
                        item.get("evidence_needed"),
                    )
                ]
            if isinstance(meta.get("blocked"), list):
                meta["blocked"] = [
                    {
                        "type": item.get("type"),
                        "title": item.get("title"),
                        "status": item.get("status"),
                        "relation": item.get("relation"),
                        "key": item.get("key"),
                    }
                    for item in meta["blocked"][:5]
                    if self.memory_v4._cloud_text_allowed(item.get("title"))
                ]
            latest_replan = meta.get("latest_replan")
            if isinstance(latest_replan, dict):
                meta["latest_replan"] = {
                    "status": latest_replan.get("status"),
                    "reason": latest_replan.get("reason"),
                    "previous_next_action": latest_replan.get(
                        "previous_next_action"
                    ),
                    "proposed_next_action": latest_replan.get(
                        "proposed_next_action"
                    ),
                }
            completion = meta.get("completion")
            if isinstance(completion, dict):
                meta["completion"] = {
                    "status": completion.get("status"),
                    "score": completion.get("score"),
                    "satisfied": completion.get("satisfied"),
                    "total": completion.get("total"),
                }
            if isinstance(meta.get("causal_trace"), list):
                meta["causal_trace"] = [
                    {
                        "source_type": item.get("source_type"),
                        "effect_type": item.get("effect_type"),
                        "relation": item.get("relation"),
                        "confidence": item.get("confidence"),
                    }
                    for item in meta["causal_trace"][:5]
                ]
            meta.pop("task_id", None)

        active_milestones: list[dict[str, Any]] = []
        if isinstance(local_project, dict):
            for milestone in snapshot["milestones"].values():
                if milestone.get("project_id") != local_project.get("id"):
                    continue
                if milestone.get("status") in {"done", "cancelled"}:
                    continue
                title = milestone.get("title")
                if for_cloud and not self.memory_v4._cloud_text_allowed(title):
                    title = None
                active_milestones.append(
                    {
                        "key": milestone.get("key"),
                        "title": title,
                        "status": milestone.get("status"),
                        "priority": milestone.get("priority"),
                    }
                )
                if len(active_milestones) >= 5:
                    break

        return {
            "engine": "cognitive-project-brain-v1.3",
            "version": self.VERSION,
            "scheduler": scheduler,
            "metacognition": meta,
            "strategies": strategies[:5],
            "portfolio": {
                "projects": len(self.projects()),
                "modules": len(self.modules()),
                "project": project,
                "module": module,
                "active_milestones": active_milestones,
            },
            "mutation_policy": "read_only_for_llm",
        }

    def graph_integrity(self) -> dict[str, Any]:
        tasks = {
            str(item["id"]): item
            for item in self.memory_v4.tasks(limit=self.MAX_TASKS)
        }
        with self._connect() as db:
            scopes = {
                str(row["task_id"]): self._scope_row(row)
                for row in db.execute(
                    "SELECT * FROM cognitive_task_scope"
                ).fetchall()
            }
            rows = db.execute(
                """
                SELECT source_task_id, target_task_id, relation, confirmed
                FROM cognitive_task_edges
                WHERE confirmed = 1
                """
            ).fetchall()

        adjacency: dict[str, set[str]] = {}
        issues: list[dict[str, Any]] = []
        for row in rows:
            edge = dict(row)
            pair = self._edge_dependency_pair(edge)
            if not pair:
                issues.append({"type": "invalid_relation"})
                continue
            dependent, prerequisite = pair
            if dependent not in tasks or prerequisite not in tasks:
                issues.append(
                    {
                        "type": "missing_task",
                        "dependent": dependent,
                        "prerequisite": prerequisite,
                    }
                )
                continue
            source_scope = scopes.get(dependent)
            target_scope = scopes.get(prerequisite)
            if (
                source_scope
                and target_scope
                and source_scope.get("project_id")
                != target_scope.get("project_id")
            ):
                issues.append(
                    {
                        "type": "cross_project_dependency",
                        "dependent": dependent,
                        "prerequisite": prerequisite,
                    }
                )
            adjacency.setdefault(dependent, set()).add(prerequisite)

        state: dict[str, int] = {}
        cycle_nodes: set[str] = set()

        def visit(node: str, stack: list[str]) -> None:
            marker = state.get(node, 0)
            if marker == 2:
                return
            if marker == 1:
                if node in stack:
                    cycle_nodes.update(stack[stack.index(node):])
                else:
                    cycle_nodes.add(node)
                return
            state[node] = 1
            stack.append(node)
            for target in adjacency.get(node, set()):
                visit(target, stack)
            stack.pop()
            state[node] = 2

        for node in list(adjacency):
            visit(node, [])
        if cycle_nodes:
            issues.append(
                {
                    "type": "cycle",
                    "task_ids": sorted(cycle_nodes)[:40],
                }
            )

        milestones_by_id = {
            str(row["id"]): row
            for row in milestone_rows
        }
        for link in milestone_links:
            milestone = milestones_by_id.get(str(link["milestone_id"]))
            task_id = str(link["task_id"])
            if milestone is None:
                issues.append(
                    {
                        "type": "missing_milestone",
                        "milestone_id": str(link["milestone_id"]),
                    }
                )
                continue
            scope = scopes.get(task_id)
            if not scope:
                issues.append(
                    {
                        "type": "missing_milestone_task",
                        "milestone_id": str(link["milestone_id"]),
                        "task_id": task_id,
                    }
                )
            elif scope.get("project_id") != milestone["project_id"]:
                issues.append(
                    {
                        "type": "cross_project_milestone_task",
                        "milestone_id": str(link["milestone_id"]),
                        "task_id": task_id,
                    }
                )

        project_adjacency: dict[str, set[str]] = {}
        for row in portfolio_rows:
            target = str(row["project_id"] or "")
            source = str(row["source_project_id"] or "")
            if target and source:
                project_adjacency.setdefault(target, set()).add(source)
        project_state: dict[str, int] = {}
        portfolio_cycle_nodes: set[str] = set()

        def visit_project(node: str, stack: list[str]) -> None:
            marker = project_state.get(node, 0)
            if marker == 2:
                return
            if marker == 1:
                if node in stack:
                    portfolio_cycle_nodes.update(stack[stack.index(node):])
                else:
                    portfolio_cycle_nodes.add(node)
                return
            project_state[node] = 1
            stack.append(node)
            for target in project_adjacency.get(node, set()):
                visit_project(target, stack)
            stack.pop()
            project_state[node] = 2

        for node in list(project_adjacency):
            visit_project(node, [])
        if portfolio_cycle_nodes:
            issues.append(
                {
                    "type": "portfolio_cycle",
                    "project_ids": sorted(portfolio_cycle_nodes)[:40],
                }
            )
        return {
            "status": "healthy" if not issues else "issues",
            "confirmed_edges": len(rows),
            "milestones": len(milestone_rows),
            "portfolio_dependencies": len(portfolio_rows),
            "issues": issues[:40],
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
                "milestones": db.execute("SELECT COUNT(*) FROM cognitive_milestones").fetchone()[0],
                "external_blockers": db.execute(
                    """
                    SELECT COUNT(*)
                    FROM cognitive_external_blockers b
                    LEFT JOIN cognitive_milestones m
                      ON m.id=b.source_milestone_id
                    WHERE b.status='open'
                      AND (
                        b.source_milestone_id IS NULL
                        OR COALESCE(m.status, '') != 'done'
                      )
                    """
                ).fetchone()[0],
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
                "portfolio_snapshot": True,
                "graph_integrity": True,
                "evidence_first_uncertainty": True,
                "portfolio_milestones": True,
                "external_blockers": True,
                "cross_project_coordination": True,
                "portfolio_cycle_guard": True,
            },
            "counts": counts,
            "integrity_check": "available_on_explicit_cognition_diagnostics",
            "mutation_policy": "action_broker_or_explicit_local_only",
        }
