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
from .errors import ProviderError
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

    def sayuri_chat(self, *, message: str, history: Any = None, context: Any = None) -> dict[str, Any]:
        try:
            result = self.agent.chat(message=message, history=history, context=context)
        except AgentRuntimeError as exc:
            raise ProviderError(str(exc), status=502) from exc
        self.database.record_event(
            "Sayuri",
            "Ответ DeepSeek-V4-Flash получен",
            details={"model": result["model"], "usage": result.get("usage", {})},
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
