from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import hashlib
import json
import sqlite3
import time
import uuid

from .actions import TOOL_DEFINITIONS


READ_ONLY_TOOLS: dict[str, dict[str, Any]] = {
    "system.status": {
        "label": "Состояние системы",
        "mode": "read_only",
        "args": {},
    },
    "memory.stats": {
        "label": "Статистика памяти",
        "mode": "read_only",
        "args": {},
    },
    "memory.search": {
        "label": "Поиск в памяти",
        "mode": "read_only",
        "args": {
            "query": "string",
            "scope": "personal|project|all",
            "limit": "1..6",
        },
    },
    "memory.continuity": {
        "label": "Незавершённые цели и задачи",
        "mode": "read_only",
        "args": {
            "query": "string",
            "limit": "1..6",
        },
    },
    "memory.integrity": {
        "label": "Проверка целостности памяти",
        "mode": "read_only",
        "args": {},
    },
    "experience.stats": {
        "label": "Статистика опыта",
        "mode": "read_only",
        "args": {},
    },
    "context.current_document": {
        "label": "Текущий документ",
        "mode": "read_only",
        "args": {},
    },
    "document.evidence_search": {
        "label": "Доказательства текущего документа",
        "mode": "read_only",
        "args": {
            "query": "string",
            "limit": "1..6",
        },
    },
}

MAX_TOOL_INTENTS = 8
MAX_READ_ONLY_CALLS = 4
MAX_CLOUD_EVIDENCE_CHARS = 9000
MAX_RECEIPT_PREVIEW_CHARS = 5000


class ToolPlannerError(ValueError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidenceToolPlanner:
    """Deterministic tool policy + execution receipts for structured plans."""

    VERSION = "0.3"

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
                CREATE TABLE IF NOT EXISTS tool_execution_receipts (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    tool TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    evidence_json TEXT NOT NULL,
                    output_sha256 TEXT,
                    output_preview_json TEXT,
                    error_class TEXT,
                    error_message TEXT
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tool_receipts_request
                ON tool_execution_receipts(request_id, started_at)
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tool_receipts_recent
                ON tool_execution_receipts(started_at DESC)
                """
            )

    def public_status(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "evidence_aware": True,
            "receipt_ledger": True,
            "max_read_only_calls": MAX_READ_ONLY_CALLS,
            "read_only_tools": len(READ_ONLY_TOOLS),
            "confirmation_gated_tools": len(TOOL_DEFINITIONS),
            "llm_direct_execution": False,
        }

    @staticmethod
    def catalog() -> list[dict[str, Any]]:
        catalog = [
            {
                "id": tool_id,
                "label": definition["label"],
                "mode": "read_only",
                "confirmation_required": False,
                "args": definition.get("args", {}),
            }
            for tool_id, definition in READ_ONLY_TOOLS.items()
        ]
        catalog.extend(
            {
                "id": tool_id,
                "label": definition["label"],
                "mode": "confirmation_gated",
                "confirmation_required": True,
                "risk": definition["risk"],
                "args": "Action Broker owns and validates mutation payloads",
            }
            for tool_id, definition in TOOL_DEFINITIONS.items()
        )
        return catalog

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _sanitize(cls, value: Any, *, depth: int = 0) -> Any:
        if depth > 6:
            return "[truncated]"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value[:2400]
        if isinstance(value, list):
            return [cls._sanitize(item, depth=depth + 1) for item in value[:30]]
        if isinstance(value, tuple):
            return [cls._sanitize(item, depth=depth + 1) for item in value[:30]]
        if isinstance(value, dict):
            safe: dict[str, Any] = {}
            for raw_key, item in list(value.items())[:50]:
                key = str(raw_key)[:120]
                folded = key.casefold()
                if (
                    folded in {"api_key", "authorization", "password", "secret", "cookie", "access_token", "refresh_token"}
                    or "secret" in folded
                    or folded.endswith("_api_key")
                ):
                    continue
                safe[key] = cls._sanitize(item, depth=depth + 1)
            return safe
        return str(value)[:1000]

    @staticmethod
    def _bounded_text(value: Any, limit: int) -> str:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) <= limit:
            return encoded
        return encoded[: max(200, limit - 40)] + "…"

    @staticmethod
    def _normalize_args(tool: str, args: Any) -> dict[str, Any]:
        raw = args if isinstance(args, dict) else {}
        if tool in {"system.status", "memory.stats", "memory.integrity", "experience.stats", "context.current_document"}:
            return {}
        if tool == "memory.search":
            query = " ".join(str(raw.get("query") or "").strip().split())[:1200]
            if not query:
                raise ToolPlannerError("memory.search требует непустой query.")
            scope = str(raw.get("scope") or "all").strip().lower()
            if scope not in {"personal", "project", "all"}:
                scope = "all"
            try:
                limit = int(raw.get("limit", 4))
            except (TypeError, ValueError):
                limit = 4
            return {
                "query": query,
                "scope": scope,
                "limit": min(max(limit, 1), 6),
            }
        if tool == "memory.continuity":
            query = " ".join(str(raw.get("query") or "").strip().split())[:1200]
            if not query:
                query = "продолжить текущую задачу"
            try:
                limit = int(raw.get("limit", 6))
            except (TypeError, ValueError):
                limit = 6
            return {
                "query": query,
                "limit": min(max(limit, 1), 6),
            }
        if tool == "document.evidence_search":
            query = " ".join(str(raw.get("query") or "").strip().split())[:1600]
            if not query:
                raise ToolPlannerError("document.evidence_search требует непустой query.")
            try:
                limit = int(raw.get("limit", 6))
            except (TypeError, ValueError):
                limit = 6
            return {
                "query": query,
                "limit": min(max(limit, 1), 6),
            }
        if tool in TOOL_DEFINITIONS:
            # Mutation payloads are intentionally not accepted from the LLM.
            return {}
        raise ToolPlannerError("Инструмент не входит в allowlist.")

    @staticmethod
    def _normalize_intent(intent: Any, step_count: int) -> dict[str, Any] | None:
        if not isinstance(intent, dict):
            return None
        tool = str(intent.get("tool") or "").strip()
        if not tool:
            return None
        try:
            step_index = int(intent.get("step", intent.get("step_index", 1)))
        except (TypeError, ValueError):
            step_index = 1
        step_index = min(max(step_index, 1), max(step_count, 1))
        purpose = " ".join(str(intent.get("purpose") or "").strip().split())[:500]
        args = intent.get("args") if isinstance(intent.get("args"), dict) else {}
        return {
            "step_index": step_index,
            "tool": tool[:160],
            "args": args,
            "purpose": purpose,
        }

    def _save_receipt(
        self,
        *,
        request_id: str,
        step_index: int,
        tool: str,
        mode: str,
        args: dict[str, Any],
        status: str,
        started_at: str,
        finished_at: str,
        duration_ms: int,
        evidence_refs: list[str],
        output_sha256: str | None,
        output_preview: Any,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        receipt_id = uuid.uuid4().hex
        safe_preview = self._sanitize(output_preview)
        preview_json = self._json(safe_preview)
        if len(preview_json) > MAX_RECEIPT_PREVIEW_CHARS:
            safe_preview = {
                "truncated": True,
                "excerpt_json": self._bounded_text(safe_preview, MAX_RECEIPT_PREVIEW_CHARS - 120),
            }
            preview_json = self._json(safe_preview)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO tool_execution_receipts(
                    id, request_id, step_index, tool, mode, args_json, status,
                    started_at, finished_at, duration_ms, evidence_json,
                    output_sha256, output_preview_json, error_class, error_message
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    request_id,
                    step_index,
                    tool,
                    mode,
                    self._json(args),
                    status,
                    started_at,
                    finished_at,
                    max(int(duration_ms), 0),
                    self._json(evidence_refs[:20]),
                    output_sha256,
                    preview_json,
                    error_class,
                    (error_message or "")[:1000] or None,
                ),
            )
        return {
            "id": receipt_id,
            "request_id": request_id,
            "step_index": step_index,
            "tool": tool,
            "mode": mode,
            "args": args,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": max(int(duration_ms), 0),
            "evidence_refs": evidence_refs[:20],
            "output_sha256": output_sha256,
            "output_preview": safe_preview,
            "error_class": error_class,
            "error": (error_message or "")[:1000] or None,
        }

    @staticmethod
    def _automatic_read_only_intents(
        plan: dict[str, Any],
        explicit_tools: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        goal = str(plan.get("goal") or "")
        evidence = plan.get("evidence_needed") if isinstance(plan.get("evidence_needed"), list) else []
        goal_text = " ".join(goal.casefold().replace("ё", "е").split())
        evidence_text = " ".join(str(item) for item in evidence).casefold().replace("ё", "е")
        text = " ".join([goal_text, evidence_text]).strip()
        explicit = explicit_tools or set()
        intents: list[dict[str, Any]] = []

        def add(tool: str, *, args: dict[str, Any] | None = None, purpose: str) -> None:
            intents.append({
                "step": 1,
                "tool": tool,
                "args": args or {},
                "purpose": purpose,
            })

        if (
            "memory.continuity" not in explicit
            and any(
                marker in text
                for marker in (
                    "продолж", "дальше", "возобнов", "незаверш", "следующий шаг",
                    "активн задач", "текущая задача", "цель проекта",
                )
            )
        ):
            query = " ".join(goal.strip().split())[:1200] or "продолжить текущую задачу"
            add(
                "memory.continuity",
                args={"query": query, "limit": 6},
                purpose="Автоматически сверить незавершённые цели, задачи и ближайший шаг.",
            )
        if (
            not any(tool.startswith("memory.") for tool in explicit)
            and any(marker in text for marker in ("памят", "решени", "предыдущ", "истори", "контекст проекта"))
        ):
            query = " ".join(goal.strip().split())[:1200] or "текущая задача"
            add(
                "memory.search",
                args={"query": query, "scope": "all", "limit": 4},
                purpose="Автоматически сверить релевантную память по цели задачи.",
            )
        system_markers = (
            "состояние системы",
            "статус системы",
            "версия системы",
            "версия проекта",
            "provider",
            "cloud",
        )
        if (
            "system.status" not in explicit
            and (
                any(marker in evidence_text for marker in system_markers)
                or "состояние системы" in goal_text
                or "статус системы" in goal_text
            )
        ):
            add("system.status", purpose="Автоматически проверить текущее состояние системы.")
        if (
            "memory.integrity" not in explicit
            and any(marker in text for marker in ("целостност", "integrity", "поврежден", "sqlite"))
        ):
            add("memory.integrity", purpose="Автоматически проверить целостность памяти.")
        document_markers = (
            "документ", "договор", "счет", "счёт", "акт", "накладн", "справк",
            "сумм", "дата", "номер", "реквизит", "таблиц", "строк", "страниц",
            "подпис", "печат", "файл",
        )
        if (
            "context.current_document" not in explicit
            and any(marker in text for marker in ("текущ документ", "открыт документ", "этот документ"))
        ):
            add("context.current_document", purpose="Автоматически сверить текущий документ из UI-контекста.")
        if (
            "document.evidence_search" not in explicit
            and any(marker in text for marker in document_markers)
        ):
            query = " ".join(goal.strip().split())[:1600] or "основные факты документа"
            add(
                "document.evidence_search",
                args={"query": query, "limit": 6},
                purpose="Найти точные факты текущего документа с сохранёнными Spatial Evidence координатами.",
            )
        if (
            "experience.stats" not in explicit
            and any(marker in text for marker in ("опыт", "стратег", "ошибк прошлого", "не повтор"))
        ):
            add("experience.stats", purpose="Автоматически сверить накопленный опыт Sayuri.")
        return intents[:MAX_READ_ONLY_CALLS]

    def execute_plan(
        self,
        plan: Any,
        *,
        handlers: dict[str, Callable[[dict[str, Any]], Any]],
        request_id: str,
    ) -> dict[str, Any]:
        safe_plan = plan if isinstance(plan, dict) else {}
        steps = safe_plan.get("steps") if isinstance(safe_plan.get("steps"), list) else []
        intents = safe_plan.get("tool_intents") if isinstance(safe_plan.get("tool_intents"), list) else []
        explicit_tools = {
            str(intent.get("tool") or "").strip()
            for intent in intents
            if isinstance(intent, dict) and str(intent.get("tool") or "").strip()
        }
        intents = list(intents[:MAX_TOOL_INTENTS]) + self._automatic_read_only_intents(
            safe_plan,
            explicit_tools,
        )
        normalized = [
            item
            for item in (
                self._normalize_intent(intent, len(steps))
                for intent in intents[:MAX_TOOL_INTENTS]
            )
            if item is not None
        ]

        receipts: list[dict[str, Any]] = []
        seen: set[str] = set()
        read_only_calls = 0
        memory_ids: list[str] = []
        memory_explanations: list[dict[str, Any]] = []

        for intent in normalized:
            tool = intent["tool"]
            raw_args = intent["args"]
            started_wall = _utcnow()
            started = time.monotonic()

            if tool in TOOL_DEFINITIONS:
                receipt = self._save_receipt(
                    request_id=request_id,
                    step_index=intent["step_index"],
                    tool=tool,
                    mode="confirmation_gated",
                    args={},
                    status="requires_action_broker",
                    started_at=started_wall,
                    finished_at=_utcnow(),
                    duration_ms=round((time.monotonic() - started) * 1000),
                    evidence_refs=[],
                    output_sha256=None,
                    output_preview={
                        "purpose": intent["purpose"],
                        "policy": "Mutation was not executed. Use SayuriActionBroker with explicit user confirmation.",
                    },
                )
                receipts.append(receipt)
                continue

            if tool not in READ_ONLY_TOOLS:
                receipt = self._save_receipt(
                    request_id=request_id,
                    step_index=intent["step_index"],
                    tool=tool,
                    mode="rejected",
                    args={},
                    status="rejected",
                    started_at=started_wall,
                    finished_at=_utcnow(),
                    duration_ms=round((time.monotonic() - started) * 1000),
                    evidence_refs=[],
                    output_sha256=None,
                    output_preview={"purpose": intent["purpose"]},
                    error_class="ToolNotAllowed",
                    error_message="Инструмент не входит в allowlist.",
                )
                receipts.append(receipt)
                continue

            try:
                args = self._normalize_args(tool, raw_args)
            except ToolPlannerError as exc:
                receipt = self._save_receipt(
                    request_id=request_id,
                    step_index=intent["step_index"],
                    tool=tool,
                    mode="read_only",
                    args={},
                    status="rejected",
                    started_at=started_wall,
                    finished_at=_utcnow(),
                    duration_ms=round((time.monotonic() - started) * 1000),
                    evidence_refs=[],
                    output_sha256=None,
                    output_preview={"purpose": intent["purpose"]},
                    error_class=exc.__class__.__name__,
                    error_message=str(exc),
                )
                receipts.append(receipt)
                continue

            fingerprint = hashlib.sha256((tool + ":" + self._json(args)).encode("utf-8")).hexdigest()
            if fingerprint in seen:
                receipt = self._save_receipt(
                    request_id=request_id,
                    step_index=intent["step_index"],
                    tool=tool,
                    mode="read_only",
                    args=args,
                    status="skipped_duplicate",
                    started_at=started_wall,
                    finished_at=_utcnow(),
                    duration_ms=round((time.monotonic() - started) * 1000),
                    evidence_refs=[],
                    output_sha256=None,
                    output_preview={"purpose": intent["purpose"]},
                )
                receipts.append(receipt)
                continue
            seen.add(fingerprint)

            if read_only_calls >= MAX_READ_ONLY_CALLS:
                receipt = self._save_receipt(
                    request_id=request_id,
                    step_index=intent["step_index"],
                    tool=tool,
                    mode="read_only",
                    args=args,
                    status="skipped_limit",
                    started_at=started_wall,
                    finished_at=_utcnow(),
                    duration_ms=round((time.monotonic() - started) * 1000),
                    evidence_refs=[],
                    output_sha256=None,
                    output_preview={"purpose": intent["purpose"]},
                )
                receipts.append(receipt)
                continue

            read_only_calls += 1
            handler = handlers.get(tool)
            if handler is None:
                receipt = self._save_receipt(
                    request_id=request_id,
                    step_index=intent["step_index"],
                    tool=tool,
                    mode="read_only",
                    args=args,
                    status="failed",
                    started_at=started_wall,
                    finished_at=_utcnow(),
                    duration_ms=round((time.monotonic() - started) * 1000),
                    evidence_refs=[],
                    output_sha256=None,
                    output_preview={"purpose": intent["purpose"]},
                    error_class="HandlerUnavailable",
                    error_message="Локальный обработчик инструмента недоступен.",
                )
                receipts.append(receipt)
                continue

            try:
                raw_result = handler(args)
                if isinstance(raw_result, dict) and "data" in raw_result:
                    data = raw_result.get("data")
                    refs = raw_result.get("evidence_refs")
                    extra_memory_ids = raw_result.get("memory_ids")
                    extra_explanations = raw_result.get("memory_explanations")
                else:
                    data = raw_result
                    refs = []
                    extra_memory_ids = []
                    extra_explanations = []
                safe_data = self._sanitize(data)
                encoded = self._json(safe_data)
                digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
                evidence_refs = [
                    str(ref)[:220]
                    for ref in (refs if isinstance(refs, list) else [])
                    if isinstance(ref, str) and ref
                ][:18]
                evidence_refs.extend([f"sha256:{digest[:16]}"])
                for memory_id in extra_memory_ids if isinstance(extra_memory_ids, list) else []:
                    if isinstance(memory_id, str) and memory_id and memory_id not in memory_ids:
                        memory_ids.append(memory_id)
                for explanation in extra_explanations if isinstance(extra_explanations, list) else []:
                    if isinstance(explanation, dict):
                        memory_explanations.append(self._sanitize(explanation))
                receipt = self._save_receipt(
                    request_id=request_id,
                    step_index=intent["step_index"],
                    tool=tool,
                    mode="read_only",
                    args=args,
                    status="completed",
                    started_at=started_wall,
                    finished_at=_utcnow(),
                    duration_ms=round((time.monotonic() - started) * 1000),
                    evidence_refs=evidence_refs,
                    output_sha256=digest,
                    output_preview=safe_data,
                )
                receipt["evidence_refs"] = [f"receipt:{receipt['id']}"] + receipt["evidence_refs"]
                receipts.append(receipt)
            except Exception as exc:
                receipt = self._save_receipt(
                    request_id=request_id,
                    step_index=intent["step_index"],
                    tool=tool,
                    mode="read_only",
                    args=args,
                    status="failed",
                    started_at=started_wall,
                    finished_at=_utcnow(),
                    duration_ms=round((time.monotonic() - started) * 1000),
                    evidence_refs=[],
                    output_sha256=None,
                    output_preview={"purpose": intent["purpose"]},
                    error_class=exc.__class__.__name__,
                    error_message=str(exc),
                )
                receipts.append(receipt)

        cloud_evidence: list[dict[str, Any]] = []
        used = 0
        for receipt in receipts:
            output = receipt["output_preview"]
            output_json = self._bounded_text(output, 2800)
            if len(self._json(output)) > 2800:
                output = {"truncated": True, "excerpt_json": output_json}
            item = {
                "receipt_id": receipt["id"],
                "step_index": receipt["step_index"],
                "tool": receipt["tool"],
                "mode": receipt["mode"],
                "status": receipt["status"],
                "args": receipt["args"],
                "evidence_refs": receipt["evidence_refs"],
                "output_sha256": receipt["output_sha256"],
                "output": output,
                "error_class": receipt["error_class"],
                "error": receipt["error"],
            }
            encoded = self._json(item)
            if used + len(encoded) > MAX_CLOUD_EVIDENCE_CHARS:
                break
            cloud_evidence.append(item)
            used += len(encoded)

        return {
            "request_id": request_id,
            "receipts": receipts,
            "cloud_evidence": cloud_evidence,
            "memory_ids": memory_ids[:30],
            "memory_explanations": memory_explanations[:30],
            "read_only_calls": read_only_calls,
        }

    @staticmethod
    def _row_public(row: sqlite3.Row) -> dict[str, Any]:
        def decode(raw: str | None, fallback: Any) -> Any:
            if not raw:
                return fallback
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return fallback

        return {
            "id": row["id"],
            "request_id": row["request_id"],
            "step_index": row["step_index"],
            "tool": row["tool"],
            "mode": row["mode"],
            "args": decode(row["args_json"], {}),
            "status": row["status"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "duration_ms": row["duration_ms"],
            "evidence_refs": decode(row["evidence_json"], []),
            "output_sha256": row["output_sha256"],
            "output_preview": decode(row["output_preview_json"], None),
            "error_class": row["error_class"],
            "error": row["error_message"],
        }

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 100)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM tool_execution_receipts
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [self._row_public(row) for row in rows]
