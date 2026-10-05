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
from .errors import SayuriError, StaticFileError


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
        self.server.logger.info("http | %s | " + format, self.client_address[0], *args)

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _error(self, error: Exception, request_id: str) -> None:
        if isinstance(error, SayuriError):
            code, status, message = error.code, error.status, error.message
        else:
            code, status, message = "SAYURI-CORE-500", 500, "Internal server error"
        self.server.logger.error("%s | request_id=%s | %s", code, request_id, traceback.format_exc())
        try:
            self.server.core.database.record_error(
                code,
                str(error),
                {"request_id": request_id, "path": self.path},
            )
        except Exception:
            self.server.logger.exception("Failed to persist error event")
        self._json({"error": {"code": code, "message": message, "request_id": request_id}}, status)

    def do_GET(self) -> None:
        request_id = uuid.uuid4().hex[:12]
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self._json(self.server.core.health(port=self.server.server_port))
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
            self._serve_static(parsed.path)
        except Exception as exc:
            self._error(exc, request_id)

    def _serve_static(self, url_path: str) -> None:
        relative = "index.html" if url_path in {"", "/"} else url_path.lstrip("/")
        base = self.server.core.settings.web_dir.resolve()
        candidate = (base / relative).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            raise StaticFileError(f"Static file not found: {url_path}")
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self._headers(HTTPStatus.OK, content_type, len(body))
        self.wfile.write(body)


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
    raise OSError(f"No free local port in range {start}-{start + core.settings.port_scan_limit - 1}") from last_error
