from __future__ import annotations

from datetime import datetime, timezone
import json
import platform
import time
from typing import Any

from agent import AgentRuntimeError, SayuriAgent
from disk import DiskService

from .config import Settings
from .database import Database
from .errors import BadRequestError, ProviderError
from .system_settings import SystemSettings


class SayuriCore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.ensure_runtime_dirs()
        self.database = Database(settings.database_path)
        self.system_settings = SystemSettings(self.database)
        self.agent = SayuriAgent(settings.root)
        self.disk = DiskService(settings.database_path, settings.disk_dir)
        self.started_monotonic = time.monotonic()

    def initialize(self, *, record_event: bool = True) -> None:
        self.database.initialize()
        self.system_settings.initialize()
        self.agent.initialize()
        self.disk.initialize()
        if not record_event:
            return
        self.database.record_event(
            "Запуск",
            "Ядро готово",
            details={"project_version": self.project_version()},
        )

    def project_version(self) -> str:
        return self.settings.project_version_file.read_text(encoding="utf-8").strip()

    def module_registry(self) -> list[dict[str, Any]]:
        registry = json.loads(self.settings.module_registry_file.read_text(encoding="utf-8"))
        modules: list[dict[str, Any]] = []
        for module in registry.get("modules", []):
            version_path = self.settings.root / module["path"] / "VERSION"
            modules.append(
                {
                    "id": module["id"],
                    "name": module.get("display_name") or module["id"],
                    "description": module.get("description", ""),
                    "path": module["path"],
                    "version": version_path.read_text(encoding="utf-8").strip(),
                    "status": "готово",
                }
            )
        return modules

    def module_versions(self) -> dict[str, str]:
        return {item["name"]: item["version"] for item in self.module_registry()}

    def setting_value(self, key: str) -> Any:
        return self.system_settings.value(key)

    def settings_payload(self) -> dict[str, Any]:
        return {"settings": self.system_settings.public()}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        settings = self.system_settings.update(changes)
        self.database.record_event(
            "Настройки",
            f"Изменено: {len(changes)}",
            details={"keys": sorted(changes)},
        )
        return {"status": "сохранено", "settings": settings}

    def sayuri_profile(self) -> dict[str, Any]:
        return self.agent.profile()

    def sayuri_memory(self, *, scope: str | None = None, query: str = "", limit: int = 100) -> dict[str, Any]:
        try:
            return self.agent.memory_payload(scope=scope, query=query, limit=limit)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc

    def sayuri_memory_v3(self) -> dict[str, Any]:
        return self.agent.memory_v3_payload()

    def maintain_sayuri_memory_v3(self) -> dict[str, Any]:
        result = self.agent.memory_v3_maintenance()
        self.database.record_event(
            "Sayuri",
            "Memory 3.0 обслужена",
            details={
                "stale_count": result["retention"]["stale_count"],
                "knowledge_promoted": result["knowledge_promoted"],
                "consolidations": result["consolidation"]["created"],
            },
        )
        return result

    def resolve_sayuri_memory_v3_conflict(self, conflict_id: str, resolution: str) -> dict[str, Any]:
        try:
            result = self.agent.resolve_memory_v3_conflict(conflict_id, resolution)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Конфликт памяти разрешён",
            details={"conflict_id": conflict_id, "resolution": resolution},
        )
        return result

    def sayuri_memory_v4(self) -> dict[str, Any]:
        return self.agent.memory_v4_payload()

    def maintain_sayuri_memory_v4(self, *, create_snapshot: bool = False) -> dict[str, Any]:
        result = self.agent.memory_v4_maintenance(create_snapshot=create_snapshot)
        self.database.record_event(
            "Sayuri",
            "Memory 4.0 обслужена",
            details={
                "hot": result["stats"]["hot"],
                "warm": result["stats"]["warm"],
                "cold": result["stats"]["cold"],
                "integrity": result["integrity"]["status"],
                "snapshot": bool(result.get("snapshot")),
            },
        )
        return result

    def create_sayuri_memory_v4_goal(
        self,
        *,
        title: str,
        description: str = "",
        scope: str = "project",
        priority: int = 4,
    ) -> dict[str, Any]:
        try:
            result = self.agent.create_memory_v4_goal(
                title=title,
                description=description,
                scope=scope,
                priority=priority,
            )
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Цель памяти создана",
            details={"goal_id": result["goal"]["id"], "scope": result["goal"]["scope"]},
        )
        return result

    def update_sayuri_memory_v4_goal(self, goal_id: str, *, status: str | None = None) -> dict[str, Any]:
        try:
            result = self.agent.update_memory_v4_goal(goal_id, status=status)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Цель памяти обновлена",
            details={"goal_id": goal_id, "status": result["goal"]["status"]},
        )
        return result

    def create_sayuri_memory_v4_task(
        self,
        *,
        title: str,
        scope: str = "project",
        goal_id: str | None = None,
        priority: int = 3,
        next_action: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            result = self.agent.create_memory_v4_task(
                title=title,
                scope=scope,
                goal_id=goal_id,
                priority=priority,
                next_action=next_action,
                context=context,
            )
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Задача памяти создана",
            details={"task_id": result["task"]["id"], "goal_id": result["task"].get("goal_id")},
        )
        return result

    def update_sayuri_memory_v4_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        next_action: str | None = None,
        blocked_reason: str | None = None,
    ) -> dict[str, Any]:
        try:
            result = self.agent.update_memory_v4_task(
                task_id,
                status=status,
                next_action=next_action,
                blocked_reason=blocked_reason,
            )
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Задача памяти обновлена",
            details={"task_id": task_id, "status": result["task"]["status"]},
        )
        return result

    def set_sayuri_memory_v4_source_trust(self, source_key: str, score: float | None) -> dict[str, Any]:
        try:
            result = self.agent.set_memory_v4_source_trust(source_key, score)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Доверие к источнику памяти изменено",
            details={"source_key": source_key, "manual_override": score},
        )
        return result

    def resolve_sayuri_memory_v4_question(self, question_id: str, resolution: str) -> dict[str, Any]:
        try:
            result = self.agent.resolve_memory_v4_question(question_id, resolution)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Вопрос памяти разрешён",
            details={"question_id": question_id},
        )
        return result

    def resolve_sayuri_memory_v4_failure(
        self,
        failure_id: str,
        *,
        resolution: str,
        cause: str = "",
        prevention: str = "",
    ) -> dict[str, Any]:
        try:
            result = self.agent.resolve_memory_v4_failure(
                failure_id,
                resolution=resolution,
                cause=cause,
                prevention=prevention,
            )
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Ошибка Failure Memory подтверждённо разрешена",
            details={
                "failure_id": failure_id,
                "has_cause": bool(cause.strip()),
                "has_prevention": bool(prevention.strip()),
            },
        )
        return result

    def create_sayuri_memory_v4_snapshot(self, reason: str = "manual") -> dict[str, Any]:
        result = self.agent.create_memory_v4_snapshot(reason)
        self.database.record_event(
            "Sayuri",
            "Снимок памяти создан",
            details={"snapshot_id": result["snapshot"]["id"], "reason": reason},
        )
        return result

    def restore_sayuri_memory_v4_snapshot(self, snapshot_id: str, confirmation: str) -> dict[str, Any]:
        try:
            result = self.agent.restore_memory_v4_snapshot(snapshot_id, confirmation)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Снимок памяти восстановлен",
            details={"snapshot_id": snapshot_id, "pre_restore_snapshot": result["pre_restore_snapshot"]["id"]},
        )
        return result

    def check_sayuri_memory_v4_integrity(self) -> dict[str, Any]:
        return self.agent.memory_v4_integrity()

    def sayuri_memory_candidates(self, *, status: str | None = None, limit: int = 100) -> dict[str, Any]:
        try:
            return self.agent.memory_candidates(status=status, limit=limit)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc

    def review_sayuri_memory_candidate(self, candidate_id: str, decision: str) -> dict[str, Any]:
        try:
            result = self.agent.review_memory_candidate(candidate_id, decision)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Кандидат памяти обработан",
            details={
                "candidate_id": candidate_id,
                "decision": decision,
                "status": result["candidate"]["status"],
            },
        )
        return result

    def sayuri_memory_intelligence_settings(self) -> dict[str, Any]:
        return self.agent.memory_intelligence_settings()

    def update_sayuri_memory_intelligence_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.agent.update_memory_intelligence_settings(changes)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Настройки Memory Intelligence изменены",
            details={"keys": sorted(changes)},
        )
        return result

    def remember_sayuri(
        self,
        *,
        scope: str,
        kind: str,
        content: str,
        importance: int = 3,
    ) -> dict[str, Any]:
        try:
            result = self.agent.remember(
                scope=scope,
                kind=kind,
                content=content,
                importance=importance,
                source="personal_cabinet",
            )
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Память сохранена",
            details={"scope": result["entry"]["scope"], "kind": result["entry"]["kind"]},
        )
        return result

    def forget_sayuri(self, entry_id: str) -> dict[str, Any]:
        result = self.agent.forget(entry_id)
        if result["deleted"]:
            self.database.record_event(
                "Sayuri",
                "Запись памяти удалена",
                details={"memory_id": entry_id},
            )
        return result

    def sayuri_experience(self, limit: int = 50) -> dict[str, Any]:
        return self.agent.experience_payload(limit)

    def rate_sayuri_response(
        self,
        response_id: str,
        rating: str,
        *,
        prompt: str = "",
        answer: str = "",
        context: Any = None,
    ) -> dict[str, Any]:
        try:
            result = self.agent.record_chat_feedback(
                response_id,
                rating,
                prompt=prompt,
                answer=answer,
                context=context,
            )
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Оценка ответа сохранена",
            details={"response_id": response_id, "rating": rating},
        )
        return result

    def sayuri_avatars(self) -> dict[str, Any]:
        return self.agent.avatar_payload()

    def save_sayuri_avatar(
        self,
        *,
        slot: str,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> dict[str, Any]:
        try:
            result = self.agent.save_avatar(
                slot=slot,
                filename=filename,
                content_type=content_type,
                data=data,
            )
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event(
            "Sayuri",
            "Аватар обновлён",
            details={
                "slot": slot,
                "width": result["avatar"].get("width"),
                "height": result["avatar"].get("height"),
            },
        )
        return result

    def reset_sayuri_avatar(self, slot: str) -> dict[str, Any]:
        try:
            result = self.agent.reset_avatar(slot)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        self.database.record_event("Sayuri", "Аватар сброшен", details={"slot": slot})
        return result

    def get_sayuri_avatar(self, slot: str) -> dict[str, Any]:
        try:
            return self.agent.get_avatar(slot)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc

    def plan_sayuri_action(self, *, text: str, context: Any = None) -> dict[str, Any]:
        try:
            result = self.agent.plan_action(text=text, context=context)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        if result.get("action"):
            self.database.record_event(
                "Sayuri",
                "Действие ожидает подтверждения",
                details={
                    "action_id": result["action"]["id"],
                    "tool": result["action"]["tool"],
                    "risk": result["action"]["risk"],
                },
            )
        return result

    def sayuri_actions(self, limit: int = 30) -> dict[str, Any]:
        return self.agent.recent_actions(limit)

    def sayuri_tool_receipts(self, limit: int = 30) -> dict[str, Any]:
        return self.agent.tool_receipts(limit)

    def _resolve_action_destination(self, destination: str) -> str | None:
        name = (destination or "").strip()
        if name.casefold() in {"", "/", "корень", "диск sayuri", "диск сayuри", "диск саюри"}:
            return None
        folders = self.disk.folder_tree()
        exact_path = [item for item in folders if item["path"].casefold() == name.casefold()]
        if len(exact_path) == 1:
            return exact_path[0]["id"]
        exact_name = [item for item in folders if item["name"].casefold() == name.casefold()]
        if len(exact_name) == 1:
            return exact_name[0]["id"]
        if not exact_name:
            raise ValueError(f"Папка назначения «{name}» не найдена.")
        raise ValueError(f"Найдено несколько папок «{name}». Укажите полный путь.")

    def _execute_sayuri_action(self, action: dict[str, Any]) -> dict[str, Any]:
        tool = action.get("tool")
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}

        if tool == "disk.create_folder":
            folder = self.disk.create_folder(
                str(payload.get("name") or ""),
                payload.get("parent_id") or None,
            )
            return {"status": "выполнено", "tool": tool, "folder": folder}

        if tool == "disk.set_favorite":
            item = payload.get("item")
            if not isinstance(item, dict):
                raise ValueError("Некорректный объект избранного.")
            result = self.disk.set_favorite([item], bool(payload.get("favorite")))
            return {"status": "выполнено", "tool": tool, **result}

        if tool == "disk.trash_current":
            item = payload.get("item")
            if not isinstance(item, dict):
                raise ValueError("Некорректный объект корзины.")
            result = self.disk.trash([item])
            return {"status": "выполнено", "tool": tool, **result}

        if tool == "disk.move_current":
            item = payload.get("item")
            if not isinstance(item, dict):
                raise ValueError("Некорректный объект перемещения.")
            destination_id = self._resolve_action_destination(str(payload.get("destination") or ""))
            result = self.disk.move([item], destination_id)
            return {"status": "выполнено", "tool": tool, **result}

        if tool == "memory.remember":
            result = self.agent.remember(
                scope=str(payload.get("scope") or ""),
                kind=str(payload.get("kind") or ""),
                content=str(payload.get("content") or ""),
                importance=int(payload.get("importance") or 3),
                source="confirmed_action",
            )
            return {
                "status": "выполнено",
                "tool": tool,
                "entry": result["entry"],
                "stats": result["stats"],
            }

        raise ValueError("Инструмент Sayuri не разрешён.")

    def confirm_sayuri_action(self, action_id: str) -> dict[str, Any]:
        try:
            action = self.agent.begin_action(action_id)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc

        if not action.get("claimed"):
            return action

        try:
            result = self._execute_sayuri_action(action)
        except Exception as exc:
            failed = self.agent.fail_action(action_id, str(exc))
            self.agent.record_action_experience(failed)
            self.database.record_event(
                "Sayuri",
                "Действие завершилось ошибкой",
                details={"action_id": action_id, "tool": action.get("tool"), "error": str(exc)[:500]},
            )
            return failed

        completed = self.agent.complete_action(action_id, result)
        self.agent.record_action_experience(completed)
        self.database.record_event(
            "Sayuri",
            "Подтверждённое действие выполнено",
            details={"action_id": action_id, "tool": action.get("tool")},
        )
        return completed

    def cancel_sayuri_action(self, action_id: str) -> dict[str, Any]:
        try:
            result = self.agent.cancel_action(action_id)
        except AgentRuntimeError as exc:
            raise BadRequestError(str(exc)) from exc
        if result.get("status") == "cancelled":
            self.agent.record_action_experience(result)
            self.database.record_event(
                "Sayuri",
                "Действие отменено пользователем",
                details={"action_id": action_id, "tool": result.get("tool")},
            )
        return result

    def configure_sayuri_provider(self, *, api_key: str | None, clear: bool = False) -> dict[str, Any]:
        try:
            result = self.agent.configure_provider(api_key=api_key, clear=clear)
        except AgentRuntimeError as exc:
            raise ProviderError(str(exc), status=400) from exc
        self.database.record_event(
            "Sayuri",
            "Настройки Cloud.ru изменены",
            details={"configured": result["provider"]["configured"], "model": result["provider"]["model"]},
        )
        return result

    def test_sayuri_provider(self) -> dict[str, Any]:
        try:
            result = self.agent.test_provider()
        except AgentRuntimeError as exc:
            raise ProviderError(str(exc), status=502) from exc
        self.database.record_event(
            "Sayuri",
            "Cloud.ru подключение проверено",
            details={"model": result["model"], "available": result["model_available"]},
        )
        return result

    def _sayuri_automation_handlers(self, context: Any) -> dict[str, Any]:
        safe_context = context if isinstance(context, dict) else {}
        current = safe_context.get("current_document")
        current_file_id = (
            str(current.get("id") or "")
            if isinstance(current, dict) and current.get("kind") == "file"
            else ""
        )

        def metadata(_args: dict[str, Any]) -> dict[str, Any]:
            if not current_file_id:
                return {
                    "data": {"available": False},
                    "evidence_refs": ["disk:current-document:none"],
                }
            item = self.disk.get_file(current_file_id)
            if not self.agent.cloud_text_allowed(
                item.get("name"),
                item.get("category"),
                item.get("content_type"),
            ):
                return {
                    "data": {"available": False, "local_only": True},
                    "evidence_refs": ["disk:current-document:local-only"],
                }
            sha256 = str(item.get("sha256") or "")
            return {
                "data": {
                    "available": True,
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "content_type": item.get("content_type"),
                    "size_bytes": item.get("size_bytes"),
                    "sha256": sha256,
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("updated_at"),
                },
                "evidence_refs": [
                    "disk:file:" + (sha256[:16] if sha256 else "current")
                ],
            }

        def ledger(_args: dict[str, Any]) -> dict[str, Any]:
            if not current_file_id:
                return {
                    "data": {"available": False},
                    "evidence_refs": ["dna-ledger:current-document:none"],
                }
            item = self.disk.get_file(current_file_id)
            if not self.agent.cloud_text_allowed(
                item.get("name"),
                item.get("category"),
                item.get("content_type"),
            ):
                return {
                    "data": {"available": False, "local_only": True},
                    "evidence_refs": ["dna-ledger:current-document:local-only"],
                }
            ledger_state = self.disk.dna_ledger(current_file_id, limit=24)
            entries = [
                {
                    "sequence_no": entry.get("sequence_no"),
                    "event_type": entry.get("event_type"),
                    "created_at": entry.get("created_at"),
                    "payload_sha256": entry.get("payload_sha256"),
                    "chain_hash": entry.get("chain_hash"),
                    "valid": entry.get("valid"),
                }
                for entry in ledger_state.get("entries", [])
                if isinstance(entry, dict)
            ]
            sha256 = str(item.get("sha256") or "")
            return {
                "data": {
                    "available": True,
                    "valid": bool(ledger_state.get("valid")),
                    "total": int(ledger_state.get("total") or 0),
                    "chain_head": ledger_state.get("chain_head"),
                    "entries": entries,
                },
                "evidence_refs": [
                    "dna-ledger:" + (sha256[:16] if sha256 else "current")
                ],
            }

        return {
            "disk.current_document.metadata": metadata,
            "disk.current_document.ledger": ledger,
        }

    def sayuri_chat(self, *, message: str, history: Any = None, context: Any = None) -> dict[str, Any]:
        try:
            result = self.agent.chat(
                message=message,
                history=history,
                context=context,
                external_tool_handlers=self._sayuri_automation_handlers(context),
            )
        except AgentRuntimeError as exc:
            raise ProviderError(str(exc), status=502) from exc
        self.database.record_event(
            "Sayuri",
            "Ответ Sayuri получен",
            details={
                "model": result["model"],
                "usage": result.get("usage", {}),
                "memory_used": result.get("memory_used", 0),
                "memory_saved": bool(result.get("memory_saved")),
                "response_id": result.get("response_id"),
                "automation_checks": int(
                    ((result.get("reasoning") or {}).get("automation") or {}).get("read_only_checks", 0)
                    or 0
                ),
            },
        )
        return result

    def health(self, *, port: int | None = None) -> dict[str, Any]:
        return {
            "status": "готово",
            "status_code": "ready",
            "name": "Саюри Цукисиро",
            "project_version": self.project_version(),
            "modules": self.module_versions(),
            "database": self.database.health(),
            "runtime": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
            },
            "server": {
                "host": self.settings.host,
                "port": port,
                "loopback_only": True,
            },
            "agent": self.agent.snapshot(),
            "disk": self.disk.health(),
            "uptime_seconds": round(time.monotonic() - self.started_monotonic, 3),
            "time_utc": datetime.now(timezone.utc).isoformat(),
        }

    def system_state(self, *, port: int | None = None) -> dict[str, Any]:
        health = self.health(port=port)
        return {
            "status": health["status"],
            "project": {
                "name": health["name"],
                "version": health["project_version"],
                "uptime_seconds": health["uptime_seconds"],
            },
            "core": {
                "status": "готово",
                "version": next(
                    (item["version"] for item in self.module_registry() if item["id"] == "sayuri-core"),
                    "—",
                ),
                "python": health["runtime"]["python"],
            },
            "database": health["database"],
            "server": health["server"],
            "events": {
                "count": health["database"]["events"],
                "errors": health["database"]["errors"],
            },
            "agent": health["agent"],
            "disk": health["disk"],
            "architecture": self.module_registry(),
            "time_utc": health["time_utc"],
        }
