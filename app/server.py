from __future__ import annotations

from http import HTTPStatus
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
import time
import traceback
from urllib.parse import parse_qs, quote, unquote, urlparse
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

    def _headers(
        self,
        status: int,
        content_type: str,
        length: int,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _send(
        self,
        body: bytes,
        content_type: str,
        status: int = 200,
        extra_headers: dict[str, str] | None = None,
    ) -> bool:
        try:
            self._headers(status, content_type, len(body), extra_headers)
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

    def _json(self, payload: dict | list, status: int = 200) -> bool:
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
            raise BadRequestError("Тело JSON-запроса слишком большое.")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BadRequestError("Ожидается корректный JSON в UTF-8.") from exc
        if not isinstance(payload, dict):
            raise BadRequestError("Корневой JSON должен быть объектом.")
        return payload

    @staticmethod
    def _query_folder(query: dict[str, list[str]]) -> str | None:
        value = query.get("folder_id", [""])[0].strip()
        return value or None

    @staticmethod
    def _parse_items(payload: dict) -> list[dict[str, str]]:
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise BadRequestError("Нужно выбрать хотя бы один объект.")
        normalized: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                raise BadRequestError("Некорректный список объектов.")
            kind = item.get("kind")
            object_id = item.get("id")
            if kind not in {"file", "folder"} or not isinstance(object_id, str) or not object_id:
                raise BadRequestError("Некорректный объект.")
            normalized.append({"kind": kind, "id": object_id})
        return normalized

    def _send_download(self, item: dict) -> None:
        path = item["path"]
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(item['name'])}",
            "ETag": f'"{item["sha256"]}"',
            "X-Sayuri-SHA256": item["sha256"],
        }
        try:
            self._headers(HTTPStatus.OK, item["content_type"], item["size_bytes"], headers)
            with path.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except CLIENT_DISCONNECT_ERRORS as exc:
            self.server.logger.info(
                "HTTP | скачивание прервано клиентом | файл=%s | %s",
                item["id"],
                exc.__class__.__name__,
            )

    def _send_phone_h264_stream(self, iterator) -> None:
        started = False
        try:
            first = next(iterator)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-sayuri-h264")
            self.send_header("Connection", "close")
            self.send_header("X-Sayuri-Stream-Protocol", "sayuri-h264-v1")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store, no-transform")
            self.end_headers()
            self.close_connection = True
            started = True
            self.wfile.write(first)
            self.wfile.flush()
            for chunk in iterator:
                self.wfile.write(chunk)
                self.wfile.flush()
        except StopIteration:
            if not started:
                raise OSError("H.264 поток завершился до передачи данных.")
        except CLIENT_DISCONNECT_ERRORS as exc:
            self.server.logger.info(
                "HTTP | H.264 поток закрыт клиентом | путь=%s | %s",
                self.path,
                exc.__class__.__name__,
            )
        except (OSError, ValueError) as exc:
            if not started:
                raise
            self.server.logger.warning(
                "Телефон Sayuri | H.264 поток завершён | путь=%s | %s",
                self.path,
                exc,
            )
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()

    def _send_phone_audio_stream(self, iterator) -> None:
        started = False
        try:
            first = next(iterator)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-sayuri-opus")
            self.send_header("Connection", "close")
            self.send_header("X-Sayuri-Audio-Protocol", "sayuri-opus-v1")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store, no-transform")
            self.end_headers()
            self.close_connection = True
            started = True
            self.wfile.write(first)
            self.wfile.flush()
            for chunk in iterator:
                self.wfile.write(chunk)
                self.wfile.flush()
        except StopIteration:
            if not started:
                raise OSError("Opus поток завершился до передачи данных.")
        except CLIENT_DISCONNECT_ERRORS as exc:
            self.server.logger.info(
                "HTTP | Opus поток закрыт клиентом | путь=%s | %s",
                self.path,
                exc.__class__.__name__,
            )
        except (OSError, ValueError) as exc:
            if not started:
                raise
            self.server.logger.warning(
                "Телефон Sayuri | Opus поток завершён | путь=%s | %s",
                self.path,
                exc,
            )
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()

    def _send_inline_file(self, item: dict) -> None:
        path = item["path"]
        headers = {
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(item['name'])}",
            "ETag": f'"{item["sha256"]}"',
            "X-Sayuri-SHA256": item["sha256"],
        }
        try:
            self._headers(HTTPStatus.OK, item["content_type"], item["size_bytes"], headers)
            with path.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except CLIENT_DISCONNECT_ERRORS as exc:
            self.server.logger.info(
                "HTTP | просмотр прерван клиентом | файл=%s | %s",
                item["id"],
                exc.__class__.__name__,
            )

    def _disk_error(self, error: Exception, request_id: str) -> None:
        if isinstance(error, FileNotFoundError):
            self._error(StaticFileError(str(error)), request_id)
            return
        if isinstance(error, (ValueError, FileExistsError, OSError)):
            self._error(BadRequestError(str(error)), request_id)
            return
        self._error(error, request_id)

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
            query = parse_qs(parsed.query)

            if parsed.path == "/api/health":
                self._json(self.server.core.health(port=self.server.server_port))
                return
            if parsed.path == "/api/system":
                self._json(self.server.core.system_state(port=self.server.server_port))
                return
            if parsed.path == "/api/settings":
                self._json(self.server.core.settings_payload())
                return
            if parsed.path == "/api/phone":
                self._json(self.server.core.phone.health())
                return
            if parsed.path == "/api/phone/companion":
                serial = query.get("serial", [None])[0]
                self._json(self.server.core.phone.companion_status(serial))
                return
            if parsed.path == "/api/phone/companion/events":
                serial = query.get("serial", [None])[0]
                try:
                    limit = int(query.get("limit", ["50"])[0])
                except ValueError:
                    limit = 50
                try:
                    after = int(query.get("after", ["0"])[0])
                except ValueError:
                    after = 0
                self._json(
                    self.server.core.phone.companion_events(
                        serial,
                        limit=limit,
                        after=after,
                    )
                )
                return
            if parsed.path == "/api/phone/apps":
                serial = query.get("serial", [None])[0]
                self._json({
                    "apps": self.server.core.phone.list_apps(serial),
                })
                return
            if parsed.path == "/api/phone/files":
                serial = query.get("serial", [None])[0]
                location = query.get("location", ["downloads"])[0]
                self._json(
                    self.server.core.phone.list_phone_files(
                        serial,
                        location=location,
                    )
                )
                return
            if parsed.path == "/api/phone/clipboard":
                serial = query.get("serial", [None])[0]
                try:
                    self._json(self.server.core.phone.read_clipboard(serial))
                except ConnectionError as exc:
                    self._error(
                        SayuriError(
                            "SAYURI-PHONE-409",
                            str(exc),
                            HTTPStatus.CONFLICT,
                        ),
                        request_id,
                    )
                return
            if parsed.path == "/api/phone/audio":
                serial = query.get("serial", [None])[0]
                try:
                    iterator = self.server.core.phone.opus_stream(serial)
                    self._send_phone_audio_stream(iterator)
                except ConnectionError as exc:
                    self._error(
                        SayuriError(
                            "SAYURI-PHONE-409",
                            str(exc),
                            HTTPStatus.CONFLICT,
                        ),
                        request_id,
                    )
                return
            if parsed.path == "/api/phone/stream":
                serial = query.get("serial", [None])[0]
                profile = query.get("profile", ["quality"])[0]
                try:
                    iterator = self.server.core.phone.h264_stream(
                        serial,
                        profile=profile,
                    )
                    self._send_phone_h264_stream(iterator)
                except ConnectionError as exc:
                    self._error(
                        SayuriError(
                            "SAYURI-PHONE-409",
                            str(exc),
                            HTTPStatus.CONFLICT,
                        ),
                        request_id,
                    )
                return
            if parsed.path == "/api/phone/frame":
                serial = query.get("serial", [None])[0]
                try:
                    frame = self.server.core.phone.screen_frame(serial)
                except ConnectionError as exc:
                    self._error(
                        SayuriError(
                            "SAYURI-PHONE-409",
                            str(exc),
                            HTTPStatus.CONFLICT,
                        ),
                        request_id,
                    )
                    return
                self._send(
                    frame["data"],
                    "image/png",
                    extra_headers={
                        "X-Sayuri-Phone-Width": str(frame["width"]),
                        "X-Sayuri-Phone-Height": str(frame["height"]),
                        "X-Sayuri-Phone-Cached": "1" if frame.get("cached") else "0",
                    },
                )
                return
            if parsed.path == "/api/disk":
                self._json(
                    self.server.core.disk.list_entries(
                        self._query_folder(query),
                        query.get("q", [""])[0],
                        scope=query.get("scope", ["all"])[0],
                        sort=query.get("sort", ["name"])[0],
                        direction=query.get("direction", ["asc"])[0],
                        category=query.get("category", ["all"])[0],
                    )
                )
                return
            if parsed.path == "/api/disk/actions":
                raw_limit = query.get("limit", ["30"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = 30
                self._json({"actions": self.server.core.disk.recent_actions(limit)})
                return
            if parsed.path == "/api/disk/folders-tree":
                self._json({"folders": self.server.core.disk.folder_tree()})
                return
            if parsed.path == "/api/disk/package-dna":
                folder_id = query.get("folder_id", [None])[0] or None
                analyze_missing = query.get("analyze_missing", ["0"])[0] in {"1", "true", "yes"}
                self._json(
                    self.server.core.disk.package_dna(
                        folder_id,
                        analyze_missing=analyze_missing,
                    )
                )
                return
            if parsed.path == "/api/disk/dna/evolution":
                self._json(self.server.core.disk.evolution_status())
                return
            if parsed.path == "/api/disk/dna/spatial":
                self._json(self.server.core.disk.spatial_status())
                return
            if parsed.path == "/api/disk/dna/reanalysis-plan":
                raw_limit = query.get("limit", ["100"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = 100
                self._json(self.server.core.disk.reanalysis_plan(limit))
                return
            if parsed.path.startswith("/api/disk/items/"):
                parts = parsed.path.strip("/").split("/")
                if len(parts) != 5 or parts[:3] != ["api", "disk", "items"]:
                    raise FileNotFoundError("Объект не найден.")
                self._json(self.server.core.disk.properties(parts[3], parts[4]))
                return
            if parsed.path.startswith("/api/disk/files/") and parsed.path.endswith("/dna/spatial"):
                file_id = parsed.path[len("/api/disk/files/"):-len("/dna/spatial")].strip("/")
                if not file_id:
                    raise FileNotFoundError("Файл не найден.")
                force_ocr = query.get("ocr", ["0"])[0] in {"1", "true", "yes"}
                self._json(
                    self.server.core.disk.spatial_document(
                        file_id,
                        force=force_ocr,
                        force_ocr=force_ocr,
                    )
                )
                return
            if parsed.path.startswith("/api/disk/files/") and parsed.path.endswith("/dna/ledger"):
                file_id = parsed.path[len("/api/disk/files/"):-len("/dna/ledger")].strip("/")
                if not file_id:
                    raise FileNotFoundError("Файл не найден.")
                raw_limit = query.get("limit", ["100"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = 100
                self._json(self.server.core.disk.dna_ledger(file_id, limit))
                return
            if parsed.path.startswith("/api/disk/files/") and parsed.path.endswith("/dna/history"):
                file_id = parsed.path[len("/api/disk/files/"):-len("/dna/history")].strip("/")
                if not file_id:
                    raise FileNotFoundError("Файл не найден.")
                raw_limit = query.get("limit", ["20"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = 20
                self._json({"history": self.server.core.disk.dna_history(file_id, limit)})
                return
            if parsed.path.startswith("/api/disk/files/") and parsed.path.endswith("/dna"):
                file_id = parsed.path[len("/api/disk/files/"):-len("/dna")].strip("/")
                if not file_id:
                    raise FileNotFoundError("Файл не найден.")
                self._json(self.server.core.disk.document_dna(file_id))
                return
            if parsed.path.startswith("/api/disk/files/") and parsed.path.endswith("/preview"):
                file_id = parsed.path[len("/api/disk/files/"):-len("/preview")].strip("/")
                if not file_id:
                    raise FileNotFoundError("Файл не найден.")
                self._json(self.server.core.disk.preview(file_id))
                return
            if parsed.path.startswith("/api/disk/files/") and parsed.path.endswith("/view"):
                file_id = parsed.path[len("/api/disk/files/"):-len("/view")].strip("/")
                if not file_id:
                    raise FileNotFoundError("Файл не найден.")
                self._send_inline_file(self.server.core.disk.get_file(file_id))
                return
            if parsed.path.startswith("/api/disk/files/") and parsed.path.endswith("/download"):
                file_id = parsed.path[len("/api/disk/files/"):-len("/download")].strip("/")
                if not file_id:
                    raise FileNotFoundError("Файл не найден.")
                self._send_download(self.server.core.disk.get_file(file_id))
                return
            if parsed.path == "/api/events":
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
        except (FileNotFoundError, ValueError, FileExistsError, OSError) as exc:
            self._disk_error(exc, request_id)
        except Exception as exc:
            self._error(exc, request_id)

    def do_POST(self) -> None:
        request_id = uuid.uuid4().hex[:12]
        try:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)

            if parsed.path == "/api/settings":
                payload = self._read_json()
                changes = payload.get("settings")
                if not isinstance(changes, dict):
                    raise BadRequestError("Поле settings должно быть объектом.")
                self._json(self.server.core.update_settings(changes))
                return

            if parsed.path == "/api/phone/companion/events":
                payload = self._read_json()
                authorization = self.headers.get("Authorization", "")
                token = (
                    authorization[len("Bearer "):].strip()
                    if authorization.startswith("Bearer ")
                    else ""
                )
                serial = self.headers.get("X-Sayuri-Phone-Serial", "").strip()
                try:
                    self._json(
                        self.server.core.phone.companion_event(
                            serial,
                            token,
                            payload,
                        )
                    )
                except PermissionError as exc:
                    self._error(
                        SayuriError(
                            "SAYURI-COMPANION-403",
                            str(exc),
                            HTTPStatus.FORBIDDEN,
                        ),
                        request_id,
                    )
                return

            if parsed.path == "/api/phone/companion/install":
                payload = self._read_json()
                result = self.server.core.phone.install_companion(
                    payload.get("serial")
                )
                self.server.core.database.record_event(
                    "Телефон Sayuri",
                    "Sayuri Companion установлен",
                    details={
                        "serial": result.get("serial"),
                        "version": result.get("version"),
                        "sha256": result.get("sha256"),
                    },
                )
                self._json(result)
                return

            if parsed.path == "/api/phone/companion/enable":
                payload = self._read_json()
                result = self.server.core.phone.enable_companion(
                    payload.get("serial"),
                    host_port=self.server.server_port,
                )
                self.server.core.database.record_event(
                    "Телефон Sayuri",
                    "Sayuri Companion: сопряжение запущено",
                    details={"serial": result.get("serial")},
                )
                self._json(result)
                return

            if parsed.path == "/api/phone/companion/disable":
                payload = self._read_json()
                result = self.server.core.phone.disable_companion(
                    payload.get("serial")
                )
                self.server.core.database.record_event(
                    "Телефон Sayuri",
                    "Sayuri Companion отключён",
                    details={"serial": result.get("serial")},
                )
                self._json(result)
                return

            if parsed.path == "/api/phone/pair":
                payload = self._read_json()
                result = self.server.core.phone.pair(
                    payload.get("address"),
                    payload.get("pairing_code"),
                )
                self.server.core.database.record_event("Телефон Sayuri", "Телефон сопряжён по Wi-Fi")
                self._json(result)
                return

            if parsed.path == "/api/phone/connect":
                payload = self._read_json()
                result = self.server.core.phone.connect(payload.get("address"))
                self.server.core.database.record_event("Телефон Sayuri", "Телефон подключён по Wi-Fi")
                self._json(result)
                return

            if parsed.path == "/api/phone/disconnect":
                payload = self._read_json()
                result = self.server.core.phone.disconnect(payload.get("serial"))
                self.server.core.database.record_event("Телефон Sayuri", "Телефон отключён")
                self._json(result)
                return

            if parsed.path == "/api/phone/control/start":
                payload = self._read_json()
                result = self.server.core.phone.start_control(
                    payload.get("serial"),
                    profile=payload.get("profile", "quality"),
                )
                self.server.core.database.record_event(
                    "Телефон Sayuri",
                    "Управление телефоном запущено",
                    details={"profile": result.get("profile")},
                )
                self._json(result)
                return

            if parsed.path == "/api/phone/control/stop":
                payload = self._read_json()
                result = self.server.core.phone.stop_control(payload.get("serial"))
                self.server.core.database.record_event("Телефон Sayuri", "Управление телефоном остановлено")
                self._json(result)
                return

            if parsed.path == "/api/phone/input/tap":
                payload = self._read_json()
                self._json(
                    self.server.core.phone.tap(
                        payload.get("serial"),
                        payload.get("x"),
                        payload.get("y"),
                    )
                )
                return

            if parsed.path == "/api/phone/input/swipe":
                payload = self._read_json()
                self._json(
                    self.server.core.phone.swipe(
                        payload.get("serial"),
                        payload.get("x1"),
                        payload.get("y1"),
                        payload.get("x2"),
                        payload.get("y2"),
                        payload.get("duration_ms", 260),
                    )
                )
                return

            if parsed.path == "/api/phone/input/key":
                payload = self._read_json()
                self._json(
                    self.server.core.phone.key(
                        payload.get("serial"),
                        payload.get("key"),
                    )
                )
                return

            if parsed.path == "/api/phone/input/text":
                payload = self._read_json()
                self._json(
                    self.server.core.phone.type_text(
                        payload.get("serial"),
                        payload.get("text"),
                    )
                )
                return

            if parsed.path == "/api/phone/clipboard":
                payload = self._read_json()
                self._json(
                    self.server.core.phone.write_clipboard(
                        payload.get("serial"),
                        payload.get("text"),
                        paste=bool(payload.get("paste", False)),
                    )
                )
                return

            if parsed.path == "/api/phone/capture":
                payload = self._read_json()
                frame = self.server.core.phone.screen_frame(
                    payload.get("serial"),
                    force=True,
                )
                stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
                name = f"Телефон Sayuri {stamp}-{uuid.uuid4().hex[:6]}.png"
                item = self.server.core.disk.store_stream(
                    name=name,
                    content_type="image/png",
                    size_bytes=len(frame["data"]),
                    stream=BytesIO(frame["data"]),
                    folder_id=None,
                )
                self.server.core.database.record_event(
                    "Телефон Sayuri",
                    "Снимок экрана сохранён в Диск Sayuri",
                    details={"file_id": item["id"], "name": item["name"]},
                )
                self._json({"status": "снимок сохранён", "file": item}, HTTPStatus.CREATED)
                return

            if parsed.path == "/api/phone/recording/start":
                payload = self._read_json()
                result = self.server.core.phone.start_recording(
                    payload.get("serial"),
                    profile=payload.get("profile", "quality"),
                    audio=payload.get("audio") is not False,
                )
                self.server.core.database.record_event(
                    "Телефон Sayuri",
                    "Запись экрана начата",
                    details={"profile": result.get("profile"), "audio": result.get("audio")},
                )
                self._json(result)
                return

            if parsed.path == "/api/phone/recording/stop":
                payload = self._read_json()
                result = self.server.core.phone.stop_recording(payload.get("serial"))
                path = result.pop("path")
                try:
                    with path.open("rb") as source:
                        item = self.server.core.disk.store_stream(
                            name=result["name"],
                            content_type="video/mp4",
                            size_bytes=result["size_bytes"],
                            stream=source,
                            folder_id=None,
                        )
                finally:
                    path.unlink(missing_ok=True)
                self.server.core.database.record_event(
                    "Телефон Sayuri",
                    "Запись экрана сохранена в Диск Sayuri",
                    details={"file_id": item["id"], "name": item["name"]},
                )
                self._json({**result, "file": item})
                return

            if parsed.path == "/api/phone/files/push":
                payload = self._read_json()
                file_id = payload.get("file_id")
                if not isinstance(file_id, str) or not file_id:
                    raise BadRequestError("Нужно указать file_id.")
                item = self.server.core.disk.get_file(file_id)
                result = self.server.core.phone.push_file(
                    payload.get("serial"),
                    item["path"],
                    item["name"],
                )
                self.server.core.database.record_event(
                    "Телефон Sayuri",
                    "Файл из Диск Sayuri отправлен на телефон",
                    details={"file_id": file_id, "name": item["name"]},
                )
                self._json(result)
                return

            if parsed.path == "/api/phone/files/upload":
                raw_length = self.headers.get("Content-Length", "")
                try:
                    size_bytes = int(raw_length)
                except ValueError as exc:
                    raise BadRequestError("Для передачи файла требуется корректный Content-Length.") from exc
                encoded_name = self.headers.get("X-Sayuri-Filename", "")
                name = unquote(encoded_name).strip()
                serial = self.headers.get("X-Sayuri-Phone-Serial", "").strip()
                if not name or not serial:
                    raise BadRequestError("Не передано имя файла или serial телефона.")
                result = self.server.core.phone.push_stream(
                    serial,
                    name=name,
                    size_bytes=size_bytes,
                    stream=self.rfile,
                )
                self.server.core.database.record_event(
                    "Телефон Sayuri",
                    "Файл с компьютера отправлен на телефон",
                    details={"name": result["name"], "size_bytes": result["size_bytes"]},
                )
                self._json(result, HTTPStatus.CREATED)
                return

            if parsed.path == "/api/phone/files/import":
                payload = self._read_json()
                result = self.server.core.phone.pull_phone_file(
                    payload.get("serial"),
                    location=payload.get("location"),
                    name=payload.get("name"),
                )
                path = result.pop("path")
                try:
                    content_type = mimetypes.guess_type(result["name"])[0] or "application/octet-stream"
                    with path.open("rb") as source:
                        item = self.server.core.disk.store_stream(
                            name=result["name"],
                            content_type=content_type,
                            size_bytes=result["size_bytes"],
                            stream=source,
                            folder_id=None,
                        )
                finally:
                    path.unlink(missing_ok=True)
                self.server.core.database.record_event(
                    "Телефон Sayuri",
                    "Файл с телефона импортирован в Диск Sayuri",
                    details={
                        "file_id": item["id"],
                        "name": item["name"],
                        "location": result["location"],
                    },
                )
                self._json({**result, "status": "импортировано", "file": item}, HTTPStatus.CREATED)
                return

            if parsed.path == "/api/phone/apps/launch":
                payload = self._read_json()
                result = self.server.core.phone.launch_app(
                    payload.get("serial"),
                    payload.get("package"),
                )
                self.server.core.database.record_event(
                    "Телефон Sayuri",
                    "Приложение запущено",
                    details={"package": result["package"]},
                )
                self._json(result)
                return

            if parsed.path == "/api/disk/folders":
                payload = self._read_json()
                name = payload.get("name")
                parent_id = payload.get("parent_id") or None
                if not isinstance(name, str):
                    raise BadRequestError("Поле name должно содержать имя папки.")
                folder = self.server.core.disk.create_folder(name, parent_id)
                self.server.core.database.record_event(
                    "Диск Sayuri", "Папка создана", details={"name": folder["name"]}
                )
                self._json({"status": "создано", "folder": folder}, HTTPStatus.CREATED)
                return

            if parsed.path == "/api/disk/upload":
                raw_length = self.headers.get("Content-Length", "")
                try:
                    size_bytes = int(raw_length)
                except ValueError as exc:
                    raise BadRequestError("Для загрузки требуется корректный Content-Length.") from exc
                encoded_name = self.headers.get("X-Sayuri-Filename", "")
                name = unquote(encoded_name).strip()
                if not name:
                    raise BadRequestError("Не передано имя файла.")
                folder_id = self._query_folder(query)
                item = self.server.core.disk.store_stream(
                    name=name,
                    content_type=self.headers.get("Content-Type"),
                    size_bytes=size_bytes,
                    stream=self.rfile,
                    folder_id=folder_id,
                )
                self.server.core.database.record_event(
                    "Диск Sayuri",
                    "Файл загружен",
                    details={
                        "name": item["name"],
                        "size_bytes": item["size_bytes"],
                        "duplicate_of": item.get("duplicate_of"),
                    },
                )
                self._json({"status": "загружено", "file": item}, HTTPStatus.CREATED)
                return

            if parsed.path.startswith("/api/disk/files/") and parsed.path.endswith("/dna/analyze"):
                file_id = parsed.path[len("/api/disk/files/"):-len("/dna/analyze")].strip("/")
                if not file_id:
                    raise FileNotFoundError("Файл не найден.")
                payload = self._read_json()
                deep = payload.get("deep") is True
                force_ocr = payload.get("ocr") is True
                dna = self.server.core.disk.document_dna(
                    file_id,
                    force=True,
                    bypass_cooldown=deep,
                    force_ocr=force_ocr,
                )
                self.server.core.database.record_event(
                    "ДНК документа",
                    "Документ переизучен",
                    details={
                        "file_id": file_id,
                        "coverage_percent": dna["coverage_percent"],
                        "facts": dna["molecules"]["total"],
                        "spatial_engine_version": dna.get("spatial", {}).get("engine_version"),
                        "ocr_pages": dna.get("spatial", {}).get("ocr", {}).get("used_pages", 0),
                    },
                )
                self._json(dna)
                return

            if parsed.path.startswith("/api/disk/files/") and parsed.path.endswith("/dna/feedback"):
                file_id = parsed.path[len("/api/disk/files/"):-len("/dna/feedback")].strip("/")
                if not file_id:
                    raise FileNotFoundError("Файл не найден.")
                payload = self._read_json()
                fact_id = payload.get("fact_id")
                action = payload.get("action")
                if not isinstance(fact_id, str) or not fact_id:
                    raise BadRequestError("Нужно указать fact_id.")
                if not isinstance(action, str):
                    raise BadRequestError("Нужно указать действие обратной связи.")
                result = self.server.core.disk.record_dna_feedback(
                    file_id,
                    fact_id=fact_id,
                    action=action,
                    corrected_value=payload.get("corrected_value"),
                    note=payload.get("note"),
                )
                self.server.core.database.record_event(
                    "ДНК документа",
                    "Сохранена обратная связь по факту",
                    details={"file_id": file_id, "fact_id": fact_id, "action": action},
                )
                self._json(result)
                return

            if parsed.path == "/api/disk/rename":
                payload = self._read_json()
                kind = payload.get("kind")
                object_id = payload.get("id")
                name = payload.get("name")
                if kind not in {"file", "folder"} or not isinstance(object_id, str) or not isinstance(name, str):
                    raise BadRequestError("Некорректные данные переименования.")
                result = self.server.core.disk.rename(kind, object_id, name)
                self.server.core.database.record_event("Диск Sayuri", "Объект переименован")
                self._json(result)
                return

            if parsed.path == "/api/disk/move":
                payload = self._read_json()
                result = self.server.core.disk.move(
                    self._parse_items(payload),
                    payload.get("destination_id") or None,
                )
                self.server.core.database.record_event(
                    "Диск Sayuri", f"Перемещено: {result['count']}"
                )
                self._json(result)
                return

            if parsed.path == "/api/disk/undo-move":
                payload = self._read_json()
                moves = payload.get("moves")
                if not isinstance(moves, list) or not moves:
                    raise BadRequestError("Нет данных для отмены перемещения.")
                result = self.server.core.disk.undo_move(moves)
                self.server.core.database.record_event(
                    "Диск Sayuri", f"Отменено перемещений: {result['count']}"
                )
                self._json(result)
                return

            if parsed.path == "/api/disk/favorite":
                payload = self._read_json()
                favorite = payload.get("favorite")
                if type(favorite) is not bool:
                    raise BadRequestError("Поле favorite должно быть логическим.")
                result = self.server.core.disk.set_favorite(self._parse_items(payload), favorite)
                self._json(result)
                return

            if parsed.path == "/api/disk/trash":
                payload = self._read_json()
                result = self.server.core.disk.trash(self._parse_items(payload))
                self.server.core.database.record_event(
                    "Диск Sayuri", f"В корзину: {result['count']}"
                )
                self._json(result)
                return

            if parsed.path == "/api/disk/restore":
                payload = self._read_json()
                result = self.server.core.disk.restore(self._parse_items(payload))
                self.server.core.database.record_event(
                    "Диск Sayuri", f"Восстановлено: {result['count']}"
                )
                self._json(result)
                return

            if parsed.path == "/api/disk/delete-permanent":
                payload = self._read_json()
                result = self.server.core.disk.delete_permanently(self._parse_items(payload))
                self.server.core.database.record_event(
                    "Диск Sayuri", f"Удалено навсегда: {result['count']}"
                )
                self._json(result)
                return

            raise StaticFileError(f"API не найден: {parsed.path}")
        except CLIENT_DISCONNECT_ERRORS as exc:
            self.server.logger.info(
                "HTTP | клиент закрыл соединение | путь=%s | %s",
                self.path,
                exc.__class__.__name__,
            )
        except (FileNotFoundError, ValueError, FileExistsError, OSError) as exc:
            self._disk_error(exc, request_id)
        except Exception as exc:
            self._error(exc, request_id)

    def do_DELETE(self) -> None:
        request_id = uuid.uuid4().hex[:12]
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/disk/files/"):
                file_id = parsed.path[len("/api/disk/files/"):].strip("/")
                result = self.server.core.disk.trash([{"kind": "file", "id": file_id}])
                self._json(result)
                return
            if parsed.path.startswith("/api/disk/folders/"):
                folder_id = parsed.path[len("/api/disk/folders/"):].strip("/")
                result = self.server.core.disk.trash([{"kind": "folder", "id": folder_id}])
                self._json(result)
                return
            raise StaticFileError(f"API не найден: {parsed.path}")
        except CLIENT_DISCONNECT_ERRORS as exc:
            self.server.logger.info(
                "HTTP | клиент закрыл соединение | путь=%s | %s",
                self.path,
                exc.__class__.__name__,
            )
        except (FileNotFoundError, ValueError, FileExistsError, OSError) as exc:
            self._disk_error(exc, request_id)
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
        if content_type.startswith("text/") or content_type in {
            "application/javascript",
            "application/json",
            "image/svg+xml",
        }:
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
