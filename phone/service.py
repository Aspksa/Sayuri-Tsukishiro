from __future__ import annotations

from pathlib import Path
import os
import re
import shutil
import subprocess
import threading
from typing import Any


PHONE_BACKEND_VERSION = "0.1.0"
SCRCPY_VERSION = "4.1"
COMMAND_TIMEOUT_SECONDS = 20
PAIR_CODE_RE = re.compile(r"^\d{6}$")
ADDRESS_RE = re.compile(r"^[A-Za-z0-9._-]+:(\d{1,5})$")


class PhoneService:
    """Локальный Android bridge. Выполняет только allow-listed ADB/scrcpy действия."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.runtime_root = project_root / ".runtime" / "phone"
        self.scrcpy_root = self.runtime_root / "scrcpy"
        self._sessions: dict[str, subprocess.Popen] = {}
        self._lock = threading.RLock()

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
                "embedded_web_stream": False,
            },
            "security": {
                "loopback_project_only": True,
                "arbitrary_shell_exposed": False,
                "explicit_user_action_required": True,
            },
        }

    def pair(self, address: Any, pairing_code: Any) -> dict[str, Any]:
        adb = self._resolve_adb()
        if adb is None:
            raise OSError("ADB runtime не установлен.")
        target = self._validate_address(address, field="Адрес сопряжения")
        code = str(pairing_code or "").strip()
        if not PAIR_CODE_RE.fullmatch(code):
            raise ValueError("Код сопряжения должен содержать 6 цифр.")

        result = self._run([str(adb), "pair", target, code])
        combined = "\n".join(value for value in (result.stdout.strip(), result.stderr.strip()) if value)
        success = result.returncode == 0 and "failed" not in combined.casefold()
        if not success:
            raise OSError(combined or "ADB pairing не выполнен.")
        return {"status": "сопряжено", "address": target, "message": combined}

    def connect(self, address: Any) -> dict[str, Any]:
        adb = self._resolve_adb()
        if adb is None:
            raise OSError("ADB runtime не установлен.")
        target = self._validate_address(address, field="Адрес подключения")
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
        adb = self._resolve_adb()
        if adb is None:
            raise OSError("ADB runtime не установлен.")
        if not isinstance(serial, str) or not serial.strip():
            raise ValueError("Не указан идентификатор телефона.")
        device_serial = serial.strip()
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
                raise ValueError("Выбранный телефон не подключён или не авторизован.")
            return match
        if not devices:
            raise ValueError("Нет авторизованного Android-устройства.")
        if len(devices) > 1:
            raise ValueError("Подключено несколько телефонов — выберите конкретное устройство.")
        return devices[0]

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
