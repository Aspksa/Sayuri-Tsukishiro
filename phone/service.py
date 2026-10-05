from __future__ import annotations

from pathlib import Path
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Any


PHONE_BACKEND_VERSION = "0.2.1"
SCRCPY_VERSION = "4.1"
COMMAND_TIMEOUT_SECONDS = 20
FRAME_TIMEOUT_SECONDS = 8
FRAME_CACHE_SECONDS = 0.35
MAX_SWIPE_DURATION_MS = 1500
ANDROID_KEYS = {
    "BACK": "KEYCODE_BACK",
    "HOME": "KEYCODE_HOME",
    "RECENTS": "KEYCODE_APP_SWITCH",
    "ENTER": "KEYCODE_ENTER",
    "DELETE": "KEYCODE_DEL",
    "POWER": "KEYCODE_POWER",
    "VOLUME_UP": "KEYCODE_VOLUME_UP",
    "VOLUME_DOWN": "KEYCODE_VOLUME_DOWN",
    "PLAY_PAUSE": "KEYCODE_MEDIA_PLAY_PAUSE",
}
PAIR_CODE_RE = re.compile(r"^\d{6}$")
ADDRESS_RE = re.compile(r"^[A-Za-z0-9._-]+:(\d{1,5})$")


class PhoneService:
    """Локальный Android bridge. Выполняет только allow-listed ADB/scrcpy действия."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.runtime_root = project_root / ".runtime" / "phone"
        self.scrcpy_root = self.runtime_root / "scrcpy"
        self._sessions: dict[str, subprocess.Popen] = {}
        self._frame_cache: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._frame_lock = threading.Lock()

    def initialize(self) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _creationflags() -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    def _runtime_binary(self, name: str) -> Path | None:
        candidates = [
            self.scrcpy_root / name,
            self.runtime_root / name,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def _resolve_adb(self) -> Path | None:
        local_name = "adb.exe" if os.name == "nt" else "adb"
        local = self._runtime_binary(local_name)
        if local:
            return local
        found = shutil.which(local_name) or shutil.which("adb")
        return Path(found) if found else None

    def _resolve_scrcpy(self) -> Path | None:
        local_name = "scrcpy.exe" if os.name == "nt" else "scrcpy"
        local = self._runtime_binary(local_name)
        if local:
            return local
        found = shutil.which(local_name) or shutil.which("scrcpy")
        return Path(found) if found else None

    def _run(self, argv: list[str], *, timeout: int = COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=self._creationflags(),
        )

    @staticmethod
    def _validate_address(value: Any, *, field: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field}: ожидается адрес вида 192.168.1.20:37125.")
        address = value.strip()
        match = ADDRESS_RE.fullmatch(address)
        if not match:
            raise ValueError(f"{field}: ожидается адрес вида 192.168.1.20:37125.")
        port = int(match.group(1))
        if port < 1 or port > 65535:
            raise ValueError(f"{field}: недопустимый порт.")
        return address

    @staticmethod
    def _parse_devices(output: str) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        for raw in output.splitlines():
            line = raw.strip()
            if not line or line.startswith("List of devices attached") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            metadata: dict[str, str] = {}
            for token in parts[2:]:
                if ":" in token:
                    key, value = token.split(":", 1)
                    metadata[key] = value
            devices.append(
                {
                    "serial": serial,
                    "state": state,
                    "authorized": state == "device",
                    "model": metadata.get("model"),
                    "product": metadata.get("product"),
                    "device": metadata.get("device"),
                    "transport_id": metadata.get("transport_id"),
                    "connection": "wifi" if ":" in serial else "usb",
                }
            )
        return devices

    def devices(self) -> list[dict[str, Any]]:
        adb = self._resolve_adb()
        if adb is None:
            return []
        result = self._run([str(adb), "devices", "-l"])
        if result.returncode != 0:
            raise OSError((result.stderr or result.stdout or "ADB не ответил.").strip())
        return self._parse_devices(result.stdout)

    def _prune_sessions(self) -> None:
        with self._lock:
            dead = [
                serial
                for serial, process in self._sessions.items()
                if process.poll() is not None
            ]
            for serial in dead:
                self._sessions.pop(serial, None)

    def _drop_device_state(self, serial: str) -> None:
        process = None
        with self._lock:
            self._frame_cache.pop(serial, None)
            process = self._sessions.pop(serial, None)
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _reconcile_device_state(self, devices: list[dict[str, Any]]) -> None:
        authorized = {
            item["serial"]
            for item in devices
            if item.get("authorized")
        }
        with self._lock:
            stale = (set(self._frame_cache) | set(self._sessions)) - authorized
        for serial in stale:
            self._drop_device_state(serial)

    def health(self) -> dict[str, Any]:
        self._prune_sessions()
        adb = self._resolve_adb()
        scrcpy = self._resolve_scrcpy()
        devices: list[dict[str, Any]] = []
        error = None
        if adb is not None:
            try:
                devices = self.devices()
            except OSError as exc:
                error = str(exc)

        self._reconcile_device_state(devices)
        authorized = sum(1 for item in devices if item["authorized"])
        runtime_ready = adb is not None and scrcpy is not None
        return {
            "status": (
                "подключено" if authorized
                else "готово" if runtime_ready
                else "требуется runtime"
            ),
            "status_code": (
                "connected" if authorized
                else "ready" if runtime_ready
                else "runtime_missing"
            ),
            "backend": "scrcpy",
            "backend_version": SCRCPY_VERSION,
            "module_version": PHONE_BACKEND_VERSION,
            "runtime": {
                "ready": runtime_ready,
                "adb": str(adb) if adb else None,
                "scrcpy": str(scrcpy) if scrcpy else None,
                "error": error,
            },
            "devices": devices,
            "authorized_devices": authorized,
            "control_sessions": sorted(self._sessions),
            "capabilities": {
                "usb": True,
                "wireless_pairing": True,
                "wireless_connect": True,
                "screen_control": runtime_ready,
                "audio": runtime_ready,
                "clipboard": runtime_ready,
                "file_transfer": False,
                "embedded_web_stream": adb is not None,
                "embedded_control": adb is not None,
                "embedded_frame_interval_ms": int(FRAME_CACHE_SECONDS * 1000),
                "embedded_audio": False,
            },
            "security": {
                "loopback_project_only": True,
                "arbitrary_shell_exposed": False,
                "explicit_user_action_required": True,
            },
        }

    def pair(self, address: Any, pairing_code: Any) -> dict[str, Any]:
        target = self._validate_address(address, field="Адрес сопряжения")
        code = str(pairing_code or "").strip()
        if not PAIR_CODE_RE.fullmatch(code):
            raise ValueError("Код сопряжения должен содержать 6 цифр.")
        adb = self._resolve_adb()
        if adb is None:
            raise OSError("ADB runtime не установлен.")

        result = self._run([str(adb), "pair", target, code])
        combined = "\n".join(value for value in (result.stdout.strip(), result.stderr.strip()) if value)
        success = result.returncode == 0 and "failed" not in combined.casefold()
        if not success:
            raise OSError(combined or "ADB pairing не выполнен.")
        return {"status": "сопряжено", "address": target, "message": combined}

    def connect(self, address: Any) -> dict[str, Any]:
        target = self._validate_address(address, field="Адрес подключения")
        adb = self._resolve_adb()
        if adb is None:
            raise OSError("ADB runtime не установлен.")
        result = self._run([str(adb), "connect", target])
        combined = "\n".join(value for value in (result.stdout.strip(), result.stderr.strip()) if value)
        failed = (
            result.returncode != 0
            or "failed" in combined.casefold()
            or "unable" in combined.casefold()
            or "cannot" in combined.casefold()
        )
        if failed:
            raise OSError(combined or "ADB connect не выполнен.")
        return {"status": "подключено", "address": target, "message": combined}

    def disconnect(self, serial: Any) -> dict[str, Any]:
        if not isinstance(serial, str) or not serial.strip():
            raise ValueError("Не указан идентификатор телефона.")
        device_serial = serial.strip()
        adb = self._resolve_adb()
        if adb is None:
            raise OSError("ADB runtime не установлен.")
        known = {item["serial"] for item in self.devices()}
        if device_serial not in known:
            raise ValueError("Телефон не найден среди подключённых устройств.")

        self.stop_control(device_serial, missing_ok=True)
        result = self._run([str(adb), "disconnect", device_serial])
        if result.returncode != 0:
            raise OSError((result.stderr or result.stdout or "Не удалось отключить телефон.").strip())
        return {
            "status": "отключено",
            "serial": device_serial,
            "message": (result.stdout or result.stderr).strip(),
        }

    def _select_authorized_device(self, serial: Any = None) -> dict[str, Any]:
        devices = [item for item in self.devices() if item["authorized"]]
        if isinstance(serial, str) and serial.strip():
            requested = serial.strip()
            match = next((item for item in devices if item["serial"] == requested), None)
            if match is None:
                self._drop_device_state(requested)
                raise ConnectionError("Телефон отключён или потерял авторизацию ADB.")
            return match
        if not devices:
            raise ValueError("Нет авторизованного Android-устройства.")
        if len(devices) > 1:
            raise ValueError("Подключено несколько телефонов — выберите конкретное устройство.")
        return devices[0]

    def _run_binary(
        self,
        argv: list[str],
        *,
        timeout: int = FRAME_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            argv,
            capture_output=True,
            text=False,
            timeout=timeout,
            check=False,
            creationflags=self._creationflags(),
        )

    @staticmethod
    def _png_dimensions(data: bytes) -> tuple[int, int]:
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("ADB вернул некорректный кадр экрана.")
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        if width <= 0 or height <= 0 or width > 10000 or height > 10000:
            raise ValueError("Некорректный размер кадра телефона.")
        return width, height

    def screen_frame(self, serial: Any = None, *, force: bool = False) -> dict[str, Any]:
        device = self._select_authorized_device(serial)
        device_serial = device["serial"]
        now = time.monotonic()

        with self._lock:
            cached = self._frame_cache.get(device_serial)
            if (
                not force
                and cached is not None
                and now - float(cached["captured_monotonic"]) < FRAME_CACHE_SECONDS
            ):
                return {**cached, "cached": True}

        adb = self._resolve_adb()
        if adb is None:
            raise OSError("ADB runtime не установлен.")

        with self._frame_lock:
            now = time.monotonic()
            with self._lock:
                cached = self._frame_cache.get(device_serial)
                if (
                    not force
                    and cached is not None
                    and now - float(cached["captured_monotonic"]) < FRAME_CACHE_SECONDS
                ):
                    return {**cached, "cached": True}

            result = self._run_binary(
                [str(adb), "-s", device_serial, "exec-out", "screencap", "-p"],
                timeout=FRAME_TIMEOUT_SECONDS,
            )
            if result.returncode != 0:
                error = (result.stderr or b"").decode("utf-8", errors="replace").strip()
                try:
                    still_connected = any(
                        item["serial"] == device_serial and item["authorized"]
                        for item in self.devices()
                    )
                except OSError:
                    still_connected = False
                if not still_connected:
                    self._drop_device_state(device_serial)
                    raise ConnectionError("Телефон отключён во время получения кадра.")
                raise OSError(error or "Не удалось получить экран телефона.")

            data = bytes(result.stdout or b"")
            try:
                width, height = self._png_dimensions(data)
            except ValueError as exc:
                try:
                    still_connected = any(
                        item["serial"] == device_serial and item["authorized"]
                        for item in self.devices()
                    )
                except OSError:
                    still_connected = False
                if not still_connected:
                    self._drop_device_state(device_serial)
                    raise ConnectionError("Телефон отключён во время получения кадра.") from exc
                raise
            frame = {
                "serial": device_serial,
                "data": data,
                "width": width,
                "height": height,
                "captured_monotonic": time.monotonic(),
                "cached": False,
            }
            with self._lock:
                self._frame_cache[device_serial] = frame
            return dict(frame)

    @staticmethod
    def _normalized_coordinate(value: Any, *, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field}: ожидается число от 0 до 1.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field}: ожидается число от 0 до 1.") from exc
        if not 0.0 <= number <= 1.0:
            raise ValueError(f"{field}: значение должно быть от 0 до 1.")
        return number

    def _pixel_point(
        self,
        serial: str,
        x: Any,
        y: Any,
    ) -> tuple[int, int]:
        nx = self._normalized_coordinate(x, field="x")
        ny = self._normalized_coordinate(y, field="y")
        frame = self.screen_frame(serial)
        px = min(frame["width"] - 1, max(0, int(round(nx * (frame["width"] - 1)))))
        py = min(frame["height"] - 1, max(0, int(round(ny * (frame["height"] - 1)))))
        return px, py

    def tap(self, serial: Any, x: Any, y: Any) -> dict[str, Any]:
        device = self._select_authorized_device(serial)
        device_serial = device["serial"]
        px, py = self._pixel_point(device_serial, x, y)
        adb = self._resolve_adb()
        if adb is None:
            raise OSError("ADB runtime не установлен.")
        result = self._run(
            [str(adb), "-s", device_serial, "shell", "input", "tap", str(px), str(py)]
        )
        if result.returncode != 0:
            raise OSError((result.stderr or result.stdout or "Не удалось выполнить касание.").strip())
        return {"status": "касание выполнено", "serial": device_serial, "x": px, "y": py}

    def swipe(
        self,
        serial: Any,
        x1: Any,
        y1: Any,
        x2: Any,
        y2: Any,
        duration_ms: Any = 260,
    ) -> dict[str, Any]:
        device = self._select_authorized_device(serial)
        device_serial = device["serial"]
        start_x, start_y = self._pixel_point(device_serial, x1, y1)
        end_x, end_y = self._pixel_point(device_serial, x2, y2)
        try:
            duration = int(duration_ms)
        except (TypeError, ValueError) as exc:
            raise ValueError("Длительность свайпа должна быть числом.") from exc
        duration = min(MAX_SWIPE_DURATION_MS, max(50, duration))
        adb = self._resolve_adb()
        if adb is None:
            raise OSError("ADB runtime не установлен.")
        result = self._run(
            [
                str(adb), "-s", device_serial,
                "shell", "input", "swipe",
                str(start_x), str(start_y), str(end_x), str(end_y), str(duration),
            ]
        )
        if result.returncode != 0:
            raise OSError((result.stderr or result.stdout or "Не удалось выполнить свайп.").strip())
        return {
            "status": "свайп выполнен",
            "serial": device_serial,
            "from": [start_x, start_y],
            "to": [end_x, end_y],
            "duration_ms": duration,
        }

    def key(self, serial: Any, key: Any) -> dict[str, Any]:
        device = self._select_authorized_device(serial)
        device_serial = device["serial"]
        if not isinstance(key, str):
            raise ValueError("Не указана системная кнопка.")
        normalized = key.strip().upper()
        keycode = ANDROID_KEYS.get(normalized)
        if keycode is None:
            raise ValueError("Эта системная кнопка не разрешена.")
        adb = self._resolve_adb()
        if adb is None:
            raise OSError("ADB runtime не установлен.")
        result = self._run(
            [str(adb), "-s", device_serial, "shell", "input", "keyevent", keycode]
        )
        if result.returncode != 0:
            raise OSError((result.stderr or result.stdout or "Не удалось нажать системную кнопку.").strip())
        return {"status": "кнопка нажата", "serial": device_serial, "key": normalized}

    def start_control(self, serial: Any = None) -> dict[str, Any]:
        scrcpy = self._resolve_scrcpy()
        if scrcpy is None:
            raise OSError("scrcpy runtime не установлен.")
        device = self._select_authorized_device(serial)
        device_serial = device["serial"]

        self._prune_sessions()
        with self._lock:
            existing = self._sessions.get(device_serial)
            if existing is not None and existing.poll() is None:
                return {
                    "status": "уже открыто",
                    "serial": device_serial,
                    "pid": existing.pid,
                }

            command = [
                str(scrcpy),
                "--serial", device_serial,
                "--window-title", "Телефон Sayuri",
                "--stay-awake",
                "--max-size", "1600",
                "--max-fps", "60",
                "--video-bit-rate", "8M",
            ]
            process = subprocess.Popen(command, cwd=str(scrcpy.parent))
            self._sessions[device_serial] = process
            return {
                "status": "управление запущено",
                "serial": device_serial,
                "pid": process.pid,
                "window": "Телефон Sayuri",
                "embedded": False,
            }

    def stop_control(self, serial: Any, *, missing_ok: bool = False) -> dict[str, Any]:
        if not isinstance(serial, str) or not serial.strip():
            if missing_ok:
                return {"status": "не запущено"}
            raise ValueError("Не указан идентификатор телефона.")
        device_serial = serial.strip()
        self._prune_sessions()
        with self._lock:
            process = self._sessions.pop(device_serial, None)
        if process is None:
            if missing_ok:
                return {"status": "не запущено", "serial": device_serial}
            raise ValueError("Для этого телефона управление сейчас не запущено.")
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
        return {"status": "управление остановлено", "serial": device_serial}
