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
                return response.status == 200
        except Exception:
            time.sleep(0.1)
    return False


def open_browser_when_ready(url: str, logger) -> None:
    if wait_until_ready(url):
        opened = webbrowser.open(url, new=2)
        logger.info("browser | url=%s | opened=%s", url, opened)
    else:
        logger.error("SAYURI-WEB-003 | health endpoint did not become ready | url=%s", url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start Sayuri Tsukishiro local web application")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the default browser")
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
    core.database.record_event("web.ready", "Local web server ready", details={"url": url})
    logger.info("Sayuri Tsukishiro %s", core.project_version())
    logger.info("Local URL: %s", url)
    logger.info("Database: %s", settings.database_path)
    logger.info("Logs: %s", settings.logs_dir / "sayuri.log")

    if not args.no_browser:
        threading.Thread(target=open_browser_when_ready, args=(url, logger), daemon=True).start()

    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    finally:
        server.server_close()
        try:
            core.database.record_event("core.stop", "Sayuri Core stopped")
        except Exception:
            logger.exception("Failed to record shutdown event")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
