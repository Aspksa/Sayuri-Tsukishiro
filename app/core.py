from __future__ import annotations

from datetime import datetime, timezone
import json
import platform
import time
from typing import Any

from agent import AgentCoreContract
from disk import DiskService
from phone import PhoneService

from .config import Settings
from .database import Database
from .system_settings import SystemSettings


class SayuriCore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.ensure_runtime_dirs()
        self.database = Database(settings.database_path)
        self.system_settings = SystemSettings(self.database)
        self.disk = DiskService(settings.database_path, settings.disk_dir)
        self.phone = PhoneService(settings.root)
        self.started_monotonic = time.monotonic()

    def initialize(self, *, record_event: bool = True) -> None:
        self.database.initialize()
        self.system_settings.initialize()
        self.disk.initialize()
        self.phone.initialize()
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
            "agent": AgentCoreContract.snapshot(),
            "disk": self.disk.health(),
            "phone": self.phone.health(),
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
            "phone": health["phone"],
            "architecture": self.module_registry(),
            "time_utc": health["time_utc"],
        }
