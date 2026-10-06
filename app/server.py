from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
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
MAX_AVATAR_UPLOAD = 8 * 1024 * 1024


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
            if parsed.path == "/api/sayuri/profile":
                self._json(self.server.core.sayuri_profile())
                return
            if parsed.path == "/api/sayuri/memory/candidates":
                raw_limit = query.get("limit", ["100"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = 100
                status = query.get("status", [""])[0].strip() or None
                self._json(self.server.core.sayuri_memory_candidates(status=status, limit=limit))
                return
            if parsed.path == "/api/sayuri/memory/intelligence":
                self._json(self.server.core.sayuri_memory_intelligence_settings())
                return
            if parsed.path == "/api/sayuri/memory/v3":
                self._json(self.server.core.sayuri_memory_v3())
                return
            if parsed.path == "/api/sayuri/memory/v4":
                self._json(self.server.core.sayuri_memory_v4())
                return
            if parsed.path == "/api/sayuri/memory":
                raw_limit = query.get("limit", ["100"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = 100
                scope = query.get("scope", [""])[0].strip() or None
                search = query.get("q", [""])[0]
                self._json(self.server.core.sayuri_memory(scope=scope, query=search, limit=limit))
                return
            if parsed.path == "/api/sayuri/avatars":
                self._json(self.server.core.sayuri_avatars())
                return
            if parsed.path == "/api/sayuri/experience":
                raw_limit = query.get("limit", ["50"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = 50
                self._json(self.server.core.sayuri_experience(limit))
                return
            if parsed.path == "/api/sayuri/actions":
                raw_limit = query.get("limit", ["30"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = 30
                self._json(self.server.core.sayuri_actions(limit))
                return
            if parsed.path == "/api/sayuri/tools/receipts":
                raw_limit = query.get("limit", ["30"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = 30
                self._json(self.server.core.sayuri_tool_receipts(limit))
                return
            if parsed.path.startswith("/api/sayuri/avatar/"):
                slot = parsed.path[len("/api/sayuri/avatar/"):].strip("/")
                if not slot:
                    raise FileNotFoundError("Аватар не найден.")
                item = self.server.core.get_sayuri_avatar(slot)
                self._send_inline_file({
                    "path": item["path"],
                    "content_type": item["content_type"],
                    "size_bytes": item["size_bytes"],
                    "sha256": item["sha256"],
                    "name": item["filename"],
                    "id": slot,
                })
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
            if parsed.path.startswith("/api/disk/files/") and parsed.path.endswith("/evidence-focus"):
                file_id = parsed.path[len("/api/disk/files/"):-len("/evidence-focus")].strip("/")
                if not file_id:
                    raise FileNotFoundError("Файл не найден.")
                fact_id = query.get("fact_id", [""])[0].strip()
                if not fact_id:
                    raise BadRequestError("Не указан fact_id evidence.")
                rendered = self.server.core.disk.render_evidence_focus(file_id, fact_id)
                self._send(
                    rendered["body"],
                    rendered["content_type"],
                    extra_headers={
                        "Cache-Control": "no-store",
                        "X-Sayuri-Evidence-Page": str(rendered.get("page") or ""),
                        "X-Sayuri-Evidence-Line": str(rendered.get("line") or ""),
                    },
                )
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

            if parsed.path == "/api/sayuri/provider":
                payload = self._read_json()
                api_key = payload.get("api_key")
                clear = payload.get("clear") is True
                if api_key is not None and not isinstance(api_key, str):
                    raise BadRequestError("Поле api_key должно быть строкой.")
                self._json(
                    self.server.core.configure_sayuri_provider(
                        api_key=api_key,
                        clear=clear,
                    )
                )
                return

            if parsed.path == "/api/sayuri/provider/test":
                self._json(self.server.core.test_sayuri_provider())
                return

            if parsed.path == "/api/sayuri/experience/feedback":
                payload = self._read_json()
                response_id = payload.get("response_id")
                rating = payload.get("rating")
                if not isinstance(response_id, str) or not response_id.strip():
                    raise BadRequestError("Не указан response_id.")
                if not isinstance(rating, str):
                    raise BadRequestError("Поле rating должно быть строкой.")
                prompt = payload.get("prompt")
                answer = payload.get("answer")
                if prompt is not None and not isinstance(prompt, str):
                    raise BadRequestError("Поле prompt должно быть строкой.")
                if answer is not None and not isinstance(answer, str):
                    raise BadRequestError("Поле answer должно быть строкой.")
                self._json(
                    self.server.core.rate_sayuri_response(
                        response_id.strip(),
                        rating,
                        prompt=prompt or "",
                        answer=answer or "",
                        context=payload.get("context"),
                    )
                )
                return

            if parsed.path == "/api/sayuri/chat":
                payload = self._read_json()
                message = payload.get("message")
                if not isinstance(message, str):
                    raise BadRequestError("Поле message должно быть строкой.")
                self._json(
                    self.server.core.sayuri_chat(
                        message=message,
                        history=payload.get("history"),
                        context=payload.get("context"),
                    )
                )
                return

            if parsed.path == "/api/sayuri/actions/plan":
                payload = self._read_json()
                text = payload.get("text")
                if not isinstance(text, str):
                    raise BadRequestError("Поле text должно быть строкой.")
                self._json(
                    self.server.core.plan_sayuri_action(
                        text=text,
                        context=payload.get("context"),
                    )
                )
                return

            if parsed.path.startswith("/api/sayuri/actions/") and parsed.path.endswith("/confirm"):
                action_id = parsed.path[len("/api/sayuri/actions/"):-len("/confirm")].strip("/")
                if not action_id:
                    raise BadRequestError("Не указано действие.")
                self._json(self.server.core.confirm_sayuri_action(action_id))
                return

            if parsed.path.startswith("/api/sayuri/actions/") and parsed.path.endswith("/cancel"):
                action_id = parsed.path[len("/api/sayuri/actions/"):-len("/cancel")].strip("/")
                if not action_id:
                    raise BadRequestError("Не указано действие.")
                self._json(self.server.core.cancel_sayuri_action(action_id))
                return

            if parsed.path == "/api/sayuri/memory/intelligence":
                payload = self._read_json()
                changes = payload.get("settings")
                if not isinstance(changes, dict):
                    raise BadRequestError("Поле settings должно быть объектом.")
                self._json(self.server.core.update_sayuri_memory_intelligence_settings(changes))
                return

            if parsed.path == "/api/sayuri/memory/v3/maintenance":
                self._read_json()
                self._json(self.server.core.maintain_sayuri_memory_v3())
                return

            if parsed.path == "/api/sayuri/memory/v4/maintenance":
                payload = self._read_json()
                create_snapshot = payload.get("create_snapshot") is True
                self._json(
                    self.server.core.maintain_sayuri_memory_v4(
                        create_snapshot=create_snapshot,
                    )
                )
                return

            if parsed.path == "/api/sayuri/memory/v4/goals":
                payload = self._read_json()
                title = payload.get("title")
                if not isinstance(title, str):
                    raise BadRequestError("Поле title должно быть строкой.")
                description = payload.get("description", "")
                scope = payload.get("scope", "project")
                priority = payload.get("priority", 4)
                if not isinstance(description, str) or not isinstance(scope, str):
                    raise BadRequestError("Поля description и scope должны быть строками.")
                self._json(
                    self.server.core.create_sayuri_memory_v4_goal(
                        title=title,
                        description=description,
                        scope=scope,
                        priority=priority,
                    ),
                    HTTPStatus.CREATED,
                )
                return

            if parsed.path.startswith("/api/sayuri/memory/v4/goals/") and parsed.path.endswith("/update"):
                goal_id = parsed.path[len("/api/sayuri/memory/v4/goals/"):-len("/update")].strip("/")
                if not goal_id:
                    raise BadRequestError("Не указана цель.")
                payload = self._read_json()
                status = payload.get("status")
                if status is not None and not isinstance(status, str):
                    raise BadRequestError("Поле status должно быть строкой.")
                self._json(
                    self.server.core.update_sayuri_memory_v4_goal(
                        goal_id,
                        status=status,
                    )
                )
                return

            if parsed.path == "/api/sayuri/memory/v4/tasks":
                payload = self._read_json()
                title = payload.get("title")
                if not isinstance(title, str):
                    raise BadRequestError("Поле title должно быть строкой.")
                scope = payload.get("scope", "project")
                goal_id = payload.get("goal_id")
                next_action = payload.get("next_action", "")
                priority = payload.get("priority", 3)
                if not isinstance(scope, str) or not isinstance(next_action, str):
                    raise BadRequestError("Поля scope и next_action должны быть строками.")
                if goal_id is not None and not isinstance(goal_id, str):
                    raise BadRequestError("Поле goal_id должно быть строкой.")
                context = payload.get("context")
                if context is not None and not isinstance(context, dict):
                    raise BadRequestError("Поле context должно быть объектом.")
                self._json(
                    self.server.core.create_sayuri_memory_v4_task(
                        title=title,
                        scope=scope,
                        goal_id=goal_id or None,
                        priority=priority,
                        next_action=next_action,
                        context=context,
                    ),
                    HTTPStatus.CREATED,
                )
                return

            if parsed.path.startswith("/api/sayuri/memory/v4/tasks/") and parsed.path.endswith("/update"):
                task_id = parsed.path[len("/api/sayuri/memory/v4/tasks/"):-len("/update")].strip("/")
                if not task_id:
                    raise BadRequestError("Не указана задача.")
                payload = self._read_json()
                status = payload.get("status")
                next_action = payload.get("next_action")
                blocked_reason = payload.get("blocked_reason")
                for key, value in (
                    ("status", status),
                    ("next_action", next_action),
                    ("blocked_reason", blocked_reason),
                ):
                    if value is not None and not isinstance(value, str):
                        raise BadRequestError(f"Поле {key} должно быть строкой.")
                self._json(
                    self.server.core.update_sayuri_memory_v4_task(
                        task_id,
                        status=status,
                        next_action=next_action,
                        blocked_reason=blocked_reason,
                    )
                )
                return

            if parsed.path.startswith("/api/sayuri/memory/v4/failures/") and parsed.path.endswith("/resolve"):
                failure_id = parsed.path[len("/api/sayuri/memory/v4/failures/"):-len("/resolve")].strip("/")
                if not failure_id:
                    raise BadRequestError("Не указана ошибка Failure Memory.")
                payload = self._read_json()
                resolution = payload.get("resolution")
                cause = payload.get("cause", "")
                prevention = payload.get("prevention", "")
                if not isinstance(resolution, str):
                    raise BadRequestError("Поле resolution должно быть строкой.")
                if not isinstance(cause, str) or not isinstance(prevention, str):
                    raise BadRequestError("Поля cause и prevention должны быть строками.")
                self._json(
                    self.server.core.resolve_sayuri_memory_v4_failure(
                        failure_id,
                        resolution=resolution,
                        cause=cause,
                        prevention=prevention,
                    )
                )
                return

            if parsed.path == "/api/sayuri/memory/v4/sources/trust":
                payload = self._read_json()
                source_key = payload.get("source_key")
                if not isinstance(source_key, str):
                    raise BadRequestError("Поле source_key должно быть строкой.")
                score = payload.get("score")
                if score is not None and not isinstance(score, (int, float)):
                    raise BadRequestError("Поле score должно быть числом или null.")
                self._json(
                    self.server.core.set_sayuri_memory_v4_source_trust(
                        source_key,
                        None if score is None else float(score),
                    )
                )
                return

            if parsed.path.startswith("/api/sayuri/memory/v4/questions/") and parsed.path.endswith("/resolve"):
                question_id = parsed.path[len("/api/sayuri/memory/v4/questions/"):-len("/resolve")].strip("/")
                if not question_id:
                    raise BadRequestError("Не указан вопрос памяти.")
                payload = self._read_json()
                resolution = payload.get("resolution")
                if not isinstance(resolution, str):
                    raise BadRequestError("Поле resolution должно быть строкой.")
                self._json(
                    self.server.core.resolve_sayuri_memory_v4_question(
                        question_id,
                        resolution,
                    )
                )
                return

            if parsed.path == "/api/sayuri/memory/v4/snapshots":
                payload = self._read_json()
                reason = payload.get("reason", "manual")
                if not isinstance(reason, str):
                    raise BadRequestError("Поле reason должно быть строкой.")
                self._json(
                    self.server.core.create_sayuri_memory_v4_snapshot(reason),
                    HTTPStatus.CREATED,
                )
                return

            if parsed.path.startswith("/api/sayuri/memory/v4/snapshots/") and parsed.path.endswith("/restore"):
                snapshot_id = parsed.path[len("/api/sayuri/memory/v4/snapshots/"):-len("/restore")].strip("/")
                if not snapshot_id:
                    raise BadRequestError("Не указан снимок памяти.")
                payload = self._read_json()
                confirmation = payload.get("confirmation")
                if not isinstance(confirmation, str):
                    raise BadRequestError("Поле confirmation должно быть строкой.")
                self._json(
                    self.server.core.restore_sayuri_memory_v4_snapshot(
                        snapshot_id,
                        confirmation,
                    )
                )
                return

            if parsed.path == "/api/sayuri/memory/v4/integrity":
                self._read_json()
                self._json(self.server.core.check_sayuri_memory_v4_integrity())
                return

            if parsed.path.startswith("/api/sayuri/memory/v3/conflicts/") and parsed.path.endswith("/resolve"):
                conflict_id = parsed.path[len("/api/sayuri/memory/v3/conflicts/"):-len("/resolve")].strip("/")
                if not conflict_id:
                    raise BadRequestError("Не указан конфликт памяти.")
                payload = self._read_json()
                resolution = payload.get("resolution")
                if not isinstance(resolution, str):
                    raise BadRequestError("Поле resolution должно быть строкой.")
                self._json(
                    self.server.core.resolve_sayuri_memory_v3_conflict(
                        conflict_id,
                        resolution,
                    )
                )
                return

            if parsed.path.startswith("/api/sayuri/memory/candidates/") and parsed.path.endswith("/review"):
                candidate_id = parsed.path[len("/api/sayuri/memory/candidates/"):-len("/review")].strip("/")
                if not candidate_id:
                    raise BadRequestError("Не указан кандидат памяти.")
                payload = self._read_json()
                decision = payload.get("decision")
                if not isinstance(decision, str):
                    raise BadRequestError("Поле decision должно быть строкой.")
                self._json(self.server.core.review_sayuri_memory_candidate(candidate_id, decision))
                return

            if parsed.path == "/api/sayuri/memory":
                payload = self._read_json()
                scope = payload.get("scope")
                kind = payload.get("kind")
                memory_content = payload.get("content")
                importance = payload.get("importance", 3)
                if not isinstance(scope, str) or not isinstance(kind, str) or not isinstance(memory_content, str):
                    raise BadRequestError("Для памяти нужны строковые поля scope, kind и content.")
                self._json(
                    self.server.core.remember_sayuri(
                        scope=scope,
                        kind=kind,
                        content=memory_content,
                        importance=importance,
                    ),
                    HTTPStatus.CREATED,
                )
                return

            if parsed.path == "/api/sayuri/avatar/upload":
                slot = query.get("slot", [""])[0].strip()
                raw_length = self.headers.get("Content-Length", "")
                try:
                    size_bytes = int(raw_length)
                except ValueError as exc:
                    raise BadRequestError("Для аватара требуется корректный Content-Length.") from exc
                if size_bytes <= 0:
                    raise BadRequestError("Файл аватара пустой.")
                if size_bytes > MAX_AVATAR_UPLOAD:
                    raise BadRequestError("Аватар не должен превышать 8 МБ.")
                encoded_name = self.headers.get("X-Sayuri-Filename", "")
                filename = unquote(encoded_name).strip() or "avatar"
                data = self.rfile.read(size_bytes)
                if len(data) != size_bytes:
                    raise BadRequestError("Файл аватара передан не полностью.")
                self._json(
                    self.server.core.save_sayuri_avatar(
                        slot=slot,
                        filename=filename,
                        content_type=self.headers.get("Content-Type"),
                        data=data,
                    ),
                    HTTPStatus.CREATED,
                )
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
            if parsed.path.startswith("/api/sayuri/memory/"):
                entry_id = parsed.path[len("/api/sayuri/memory/"):].strip("/")
                if not entry_id:
                    raise BadRequestError("Не указана запись памяти.")
                self._json(self.server.core.forget_sayuri(entry_id))
                return
            if parsed.path.startswith("/api/sayuri/avatar/"):
                slot = parsed.path[len("/api/sayuri/avatar/"):].strip("/")
                if not slot:
                    raise BadRequestError("Не указан слот аватара.")
                self._json(self.server.core.reset_sayuri_avatar(slot))
                return
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
