from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
import traceback
from urllib.parse import parse_qs, urlparse
import uuid

from .core import SayuriCore
from .errors import BadRequestError, SayuriError, StaticFileError


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
    ),
}
CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
MAX_JSON_BODY = 64 * 1024


class SayuriHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], core: SayuriCore, logger: logging.Logger):
        self.core = core
        self.logger = logger
        super().__init__(address, SayuriRequestHandler)


class SayuriRequestHandler(BaseHTTPRequestHandler):
    server: SayuriHTTPServer

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        if self.server.core.setting_value("diagnostics.http_requests"):
            self.server.logger.info("HTTP | %s | " + format, self.client_address[0], *args)

    def finish(self) -> None:
        try:
            super().finish()
        except CLIENT_DISCONNECT_ERRORS as exc:
            self.server.logger.info(
                "HTTP | клиент закрыл соединение при завершении запроса | %s",
                exc.__class__.__name__,
            )

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()

    def _send(self, body: bytes, content_type: str, status: int = 200) -> bool:
        try:
            self._headers(status, content_type, len(body))
            if body:
                self.wfile.write(body)
            return True
        except CLIENT_DISCONNECT_ERRORS as exc:
            self.server.logger.info(
                "HTTP | клиент закрыл соединение | путь=%s | %s",
                self.path,
                exc.__class__.__name__,
            )
            return False

    def _json(self, payload: dict, status: int = 200) -> bool:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._send(body, "application/json; charset=utf-8", status)

    def _read_json(self) -> dict:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise BadRequestError("Некорректный Content-Length.") from exc
        if length <= 0:
            raise BadRequestError("Пустое тело запроса.")
        if length > MAX_JSON_BODY:
            raise BadRequestError("Тело запроса слишком большое.")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BadRequestError("Ожидается корректный JSON в UTF-8.") from exc
        if not isinstance(payload, dict):
            raise BadRequestError("Корневой JSON должен быть объектом.")
        return payload

    def _error(self, error: Exception, request_id: str) -> None:
        if isinstance(error, SayuriError):
            code, status, message = error.code, error.status, error.message
            self.server.logger.warning(
                "%s | запрос=%s | путь=%s | %s",
                code,
                request_id,
                self.path,
                message,
            )
        else:
            code, status, message = "SAYURI-CORE-500", 500, "Внутренняя ошибка сервера"
            self.server.logger.error(
                "%s | запрос=%s | %s",
                code,
                request_id,
                traceback.format_exc(),
            )
            try:
                self.server.core.database.record_error(
                    code,
                    str(error),
                    {"request_id": request_id, "path": self.path},
                )
            except Exception:
                self.server.logger.exception("Не удалось записать ошибку в базу данных")
        self._json({"error": {"code": code, "message": message, "request_id": request_id}}, status)

    def do_GET(self) -> None:
        request_id = uuid.uuid4().hex[:12]
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self._json(self.server.core.health(port=self.server.server_port))
                return
            if parsed.path == "/api/system":
                self._json(self.server.core.system_state(port=self.server.server_port))
                return
            if parsed.path == "/api/settings":
                self._json(self.server.core.settings_payload())
                return
            if parsed.path == "/api/events":
                query = parse_qs(parsed.query)
                raw_limit = query.get("limit", ["20"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = 20
                self._json({"events": self.server.core.database.recent_events(limit)})
                return
            if parsed.path == "/favicon.ico":
                self._send(b"", "image/x-icon", HTTPStatus.NO_CONTENT)
                return
            self._serve_static(parsed.path)
        except CLIENT_DISCONNECT_ERRORS as exc:
            self.server.logger.info(
                "HTTP | клиент закрыл соединение | путь=%s | %s",
                self.path,
                exc.__class__.__name__,
            )
        except Exception as exc:
            self._error(exc, request_id)

    def do_POST(self) -> None:
        request_id = uuid.uuid4().hex[:12]
        try:
            parsed = urlparse(self.path)
            if parsed.path != "/api/settings":
                raise StaticFileError(f"API не найден: {parsed.path}")
            payload = self._read_json()
            changes = payload.get("settings")
            if not isinstance(changes, dict):
                raise BadRequestError("Поле settings должно быть объектом.")
            result = self.server.core.update_settings(changes)
            self._json(result)
        except CLIENT_DISCONNECT_ERRORS as exc:
            self.server.logger.info(
                "HTTP | клиент закрыл соединение | путь=%s | %s",
                self.path,
                exc.__class__.__name__,
            )
        except Exception as exc:
            self._error(exc, request_id)

    def _serve_static(self, url_path: str) -> None:
        relative = "index.html" if url_path in {"", "/"} else url_path.lstrip("/")
        base = self.server.core.settings.web_dir.resolve()
        candidate = (base / relative).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            raise StaticFileError(f"Файл не найден: {url_path}")
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json", "image/svg+xml"}:
            content_type += "; charset=utf-8"
        self._send(body, content_type, HTTPStatus.OK)


def create_server(core: SayuriCore, logger: logging.Logger) -> SayuriHTTPServer:
    last_error: OSError | None = None
    start = core.settings.preferred_port
    for port in range(start, start + core.settings.port_scan_limit):
        try:
            return SayuriHTTPServer((core.settings.host, port), core, logger)
        except OSError as exc:
            last_error = exc
            if exc.errno not in {None, 48, 98, 10048}:
                raise
    raise OSError(
        f"Нет свободного локального порта в диапазоне "
        f"{start}-{start + core.settings.port_scan_limit - 1}"
    ) from last_error
