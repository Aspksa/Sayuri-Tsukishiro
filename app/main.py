from __future__ import annotations

import argparse
import sys
import threading
import time
import urllib.request
import webbrowser

from .config import Settings
from .core import SayuriCore
from .logging_setup import configure_logging
from .server import create_server


def wait_until_ready(url: str, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=0.5) as response:
                body = response.read()
                return response.status == 200 and bool(body)
        except Exception:
            time.sleep(0.1)
    return False


def open_browser_when_ready(url: str, logger) -> None:
    if wait_until_ready(url):
        opened = webbrowser.open(url, new=2)
        logger.info("Браузер | адрес=%s | открыт=%s", url, "да" if opened else "нет")
    else:
        logger.error("SAYURI-WEB-003 | локальный сервер не прошёл проверку готовности | адрес=%s", url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Запуск локального приложения Sayuri Tsukishiro")
    parser.add_argument("--no-browser", action="store_true", help="Не открывать браузер автоматически")
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env()
        logger = configure_logging(settings.logs_dir)
        core = SayuriCore(settings)
        core.initialize()
        server = create_server(core, logger)
    except Exception as exc:
        print(f"SAYURI-BOOT-500: {exc}", file=sys.stderr)
        return 1

    url = f"http://{settings.host}:{server.server_port}"
    core.database.record_event("Сайт", "Сервер готов", details={"url": url})
    logger.info("Саюри Цукисиро %s", core.project_version())
    logger.info("Адрес сайта: %s", url)
    logger.info("База данных: %s", settings.database_path)
    logger.info("Журнал: %s", settings.logs_dir / "sayuri.log")

    auto_open = bool(core.setting_value("browser.auto_open"))
    if not args.no_browser and auto_open:
        threading.Thread(target=open_browser_when_ready, args=(url, logger), daemon=True).start()
    elif not auto_open:
        logger.info("Браузер | автоматическое открытие отключено в настройках")

    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        logger.info("Остановка по запросу пользователя")
    finally:
        server.server_close()
        try:
            core.database.record_event("Остановка", "Ядро остановлено")
        except Exception:
            logger.exception("Не удалось записать событие остановки")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
