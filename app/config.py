from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[1]


def _env_port(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name}: требуется целое число, получено {raw!r}") from exc
    if not 1024 <= value <= 65535:
        raise ValueError(f"{name}: допустимый диапазон портов 1024–65535")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    root: Path = ROOT
    host: str = "127.0.0.1"
    preferred_port: int = 8765
    port_scan_limit: int = 20

    @classmethod
    def from_env(cls) -> "Settings":
        host = os.getenv("SAYURI_HOST", "127.0.0.1").strip()
        if host != "127.0.0.1":
            raise ValueError("SAYURI_HOST в версии 0.1.x должен быть 127.0.0.1")
        return cls(
            root=ROOT,
            host=host,
            preferred_port=_env_port("SAYURI_PORT", 8765),
        )

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "sayuri.db"

    @property
    def disk_dir(self) -> Path:
        return self.data_dir / "disk"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def web_dir(self) -> Path:
        return self.root / "web"

    @property
    def project_version_file(self) -> Path:
        return self.root / "VERSION"

    @property
    def module_registry_file(self) -> Path:
        return self.root / "MODULES.json"

    def ensure_runtime_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.disk_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
