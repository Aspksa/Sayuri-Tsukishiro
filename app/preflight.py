from __future__ import annotations

import json
import platform
import sqlite3

from .config import Settings
from .core import SayuriCore


def main() -> int:
    try:
        settings = Settings.from_env()
        core = SayuriCore(settings)
        core.initialize(record_event=False)
        report = {
            "состояние": "готово",
            "версия_проекта": core.project_version(),
            "модули": core.module_versions(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "база_данных": core.database.health(),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps(
            {"состояние": "ошибка", "код": "SAYURI-PREFLIGHT-001", "сообщение": str(exc)},
            ensure_ascii=False,
        ))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
