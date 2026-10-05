from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import secrets
import threading
import time
from typing import Any


COMPANION_PROTOCOL_VERSION = "0.1.0"
COMPANION_PACKAGE = "com.sayuri.tsukishiro.companion"
COMPANION_ACTIVITY = f"{COMPANION_PACKAGE}/.PairingActivity"
COMPANION_LISTENER = f"{COMPANION_PACKAGE}/.SayuriNotificationListener"
COMPANION_DEVICE_PORT = 8766
MAX_COMPANION_EVENTS = 240
MAX_EVENT_TEXT = 4096
MAX_PACKAGE = 255
MAX_TAG = 512
ALLOWED_EVENT_TYPES = {
    "listener_connected",
    "listener_disconnected",
    "notification_posted",
    "notification_removed",
    "heartbeat",
}


@dataclass
class CompanionSession:
    token: str
    serial: str
    issued_at: float
    last_seen_at: float | None = None


class CompanionRegistry:
    """Ephemeral authenticated state for the Android companion bridge."""

    def __init__(self) -> None:
        self._sessions: dict[str, CompanionSession] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_COMPANION_EVENTS)
        self._lock = threading.RLock()
        self._sequence = 0

    def issue(self, serial: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._sessions[serial] = CompanionSession(
                token=token,
                serial=serial,
                issued_at=now,
            )
        return token

    def revoke(self, serial: str) -> None:
        with self._lock:
            self._sessions.pop(serial, None)

    def paired(self, serial: str) -> bool:
        with self._lock:
            return serial in self._sessions

    def authenticate(self, serial: str, token: str) -> bool:
        if not serial or not token:
            return False
        with self._lock:
            session = self._sessions.get(serial)
            if session is None:
                return False
            return secrets.compare_digest(session.token, token)

    @staticmethod
    def _string(value: Any, *, maximum: int, field: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        value = value.replace("\x00", "").strip()
        if len(value) > maximum:
            value = value[:maximum]
        return value or None

    @staticmethod
    def _integer(value: Any, *, default: int = 0) -> int:
        if isinstance(value, bool):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def ingest(
        self,
        serial: str,
        token: str,
        payload: Any,
    ) -> dict[str, Any]:
        if not self.authenticate(serial, token):
            raise PermissionError("Неверный токен Sayuri Companion.")
        if not isinstance(payload, dict):
            raise ValueError("Событие Companion должно быть JSON-объектом.")

        event_type = self._string(
            payload.get("type"),
            maximum=64,
            field="type",
        )
        if event_type not in ALLOWED_EVENT_TYPES:
            raise ValueError("Неизвестный тип события Sayuri Companion.")

        now = time.time()
        with self._lock:
            session = self._sessions[serial]
            session.last_seen_at = now
            self._sequence += 1
            event = {
                "sequence": self._sequence,
                "serial": serial,
                "type": event_type,
                "received_at": now,
                "event_time": self._integer(payload.get("event_time"), default=0),
                "package": self._string(
                    payload.get("package"),
                    maximum=MAX_PACKAGE,
                    field="package",
                ),
                "title": self._string(
                    payload.get("title"),
                    maximum=MAX_EVENT_TEXT,
                    field="title",
                ),
                "text": self._string(
                    payload.get("text"),
                    maximum=MAX_EVENT_TEXT,
                    field="text",
                ),
                "subtext": self._string(
                    payload.get("subtext"),
                    maximum=MAX_EVENT_TEXT,
                    field="subtext",
                ),
                "notification_id": self._integer(
                    payload.get("notification_id"),
                    default=0,
                ),
                "tag": self._string(
                    payload.get("tag"),
                    maximum=MAX_TAG,
                    field="tag",
                ),
            }
            self._events.append(event)
        return {
            "status": "принято",
            "sequence": event["sequence"],
            "protocol_version": COMPANION_PROTOCOL_VERSION,
        }

    def events(
        self,
        *,
        serial: str | None = None,
        limit: int = 50,
        after: int = 0,
    ) -> list[dict[str, Any]]:
        limit = min(200, max(1, int(limit)))
        after = max(0, int(after))
        with self._lock:
            rows = [
                dict(event)
                for event in self._events
                if event["sequence"] > after
                and (serial is None or event["serial"] == serial)
            ]
        return rows[-limit:]

    def status(self, serial: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(serial)
            event_count = sum(
                1 for event in self._events if event["serial"] == serial
            )
            last_event = next(
                (
                    event
                    for event in reversed(self._events)
                    if event["serial"] == serial
                ),
                None,
            )
            return {
                "paired": session is not None,
                "issued_at": session.issued_at if session else None,
                "last_seen_at": session.last_seen_at if session else None,
                "events": event_count,
                "last_sequence": last_event["sequence"] if last_event else 0,
                "protocol_version": COMPANION_PROTOCOL_VERSION,
            }
