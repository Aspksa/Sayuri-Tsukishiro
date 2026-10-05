from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import struct


AVATAR_SLOTS = {
    "orb": {"label": "Плавающий аватар", "recommended": 192},
    "chat": {"label": "Чат", "recommended": 256},
    "profile": {"label": "Профиль", "recommended": 512},
    "hero": {"label": "Большой портрет", "recommended": 1024},
}

_ALLOWED_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
_MAX_AVATAR_BYTES = 8 * 1024 * 1024


class AvatarError(ValueError):
    pass


class AvatarStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / "manifest.json"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _validate_slot(slot: str) -> str:
        value = (slot or "").strip().lower()
        if value not in AVATAR_SLOTS:
            raise AvatarError("Неизвестный слот аватара.")
        return value

    @staticmethod
    def _detect_type(data: bytes, declared: str | None) -> tuple[str, str]:
        content_type = (declared or "").split(";", 1)[0].strip().lower()
        detected = None
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            detected = "image/png"
        elif len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            detected = "image/webp"
        elif data.startswith(b"\xff\xd8\xff"):
            detected = "image/jpeg"
        if detected not in _ALLOWED_TYPES:
            raise AvatarError("Поддерживаются только PNG, JPEG и WebP.")
        if content_type and content_type in _ALLOWED_TYPES and content_type != detected:
            raise AvatarError("Тип файла не совпадает с содержимым изображения.")
        return detected, _ALLOWED_TYPES[detected]

    @staticmethod
    def _png_dimensions(data: bytes) -> tuple[int, int] | None:
        if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
            return struct.unpack(">II", data[16:24])
        return None

    @staticmethod
    def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
        if not data.startswith(b"\xff\xd8"):
            return None
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(data):
                break
            length = int.from_bytes(data[index:index + 2], "big")
            if length < 2 or index + length > len(data):
                break
            if marker in {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            } and length >= 7:
                height = int.from_bytes(data[index + 3:index + 5], "big")
                width = int.from_bytes(data[index + 5:index + 7], "big")
                return width, height
            index += length
        return None

    @staticmethod
    def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
        if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            return None
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return width, height
        if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
            b1, b2, b3, b4 = data[21:25]
            width = 1 + b1 + ((b2 & 0x3F) << 8)
            height = 1 + ((b2 & 0xC0) >> 6) + (b3 << 2) + ((b4 & 0x0F) << 10)
            return width, height
        if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
            width = int.from_bytes(data[26:28], "little") & 0x3FFF
            height = int.from_bytes(data[28:30], "little") & 0x3FFF
            return width, height
        return None

    @classmethod
    def _dimensions(cls, data: bytes, content_type: str) -> tuple[int, int] | None:
        if content_type == "image/png":
            return cls._png_dimensions(data)
        if content_type == "image/jpeg":
            return cls._jpeg_dimensions(data)
        if content_type == "image/webp":
            return cls._webp_dimensions(data)
        return None

    def _load_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {"version": 1, "slots": {}}
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "slots": {}}
        if not isinstance(payload, dict) or not isinstance(payload.get("slots"), dict):
            return {"version": 1, "slots": {}}
        return payload

    def _save_manifest(self, payload: dict[str, Any]) -> None:
        temp = self.manifest_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(self.manifest_path)

    def public(self) -> dict[str, Any]:
        manifest = self._load_manifest()
        result: dict[str, Any] = {}
        for slot, spec in AVATAR_SLOTS.items():
            saved = manifest["slots"].get(slot)
            if saved and (self.root / saved.get("stored_name", "")).is_file():
                result[slot] = {
                    "slot": slot,
                    "label": spec["label"],
                    "recommended": spec["recommended"],
                    "custom": True,
                    "filename": saved.get("filename"),
                    "content_type": saved.get("content_type"),
                    "size_bytes": saved.get("size_bytes"),
                    "width": saved.get("width"),
                    "height": saved.get("height"),
                    "updated_at": saved.get("updated_at"),
                    "url": f"/api/sayuri/avatar/{slot}?v={saved.get('sha256', '')[:12]}",
                }
            else:
                result[slot] = {
                    "slot": slot,
                    "label": spec["label"],
                    "recommended": spec["recommended"],
                    "custom": False,
                    "filename": None,
                    "content_type": "image/svg+xml",
                    "size_bytes": None,
                    "width": None,
                    "height": None,
                    "updated_at": None,
                    "url": "/assets/sayuri-avatar.svg",
                }
        return result

    def save(
        self,
        *,
        slot: str,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> dict[str, Any]:
        slot = self._validate_slot(slot)
        if not data:
            raise AvatarError("Файл аватара пустой.")
        if len(data) > _MAX_AVATAR_BYTES:
            raise AvatarError("Аватар не должен превышать 8 МБ.")
        detected_type, extension = self._detect_type(data, content_type)
        dimensions = self._dimensions(data, detected_type)
        if dimensions:
            width, height = dimensions
            if width < 32 or height < 32:
                raise AvatarError("Аватар слишком маленький: минимум 32×32.")
            if width > 8192 or height > 8192:
                raise AvatarError("Аватар слишком большой: максимум 8192×8192.")
        else:
            width = height = None

        digest = hashlib.sha256(data).hexdigest()
        stored_name = f"{slot}-{digest[:16]}{extension}"
        target = self.root / stored_name
        temp = self.root / f".{stored_name}.tmp"
        temp.write_bytes(data)
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(target)

        manifest = self._load_manifest()
        old = manifest["slots"].get(slot)
        manifest["slots"][slot] = {
            "stored_name": stored_name,
            "filename": (filename or f"{slot}{extension}")[:255],
            "content_type": detected_type,
            "size_bytes": len(data),
            "width": width,
            "height": height,
            "sha256": digest,
            "updated_at": self._now(),
        }
        self._save_manifest(manifest)

        if old:
            old_name = old.get("stored_name")
            if old_name and old_name != stored_name:
                old_path = self.root / old_name
                if old_path.exists():
                    old_path.unlink()

        return self.public()[slot]

    def reset(self, slot: str) -> dict[str, Any]:
        slot = self._validate_slot(slot)
        manifest = self._load_manifest()
        old = manifest["slots"].pop(slot, None)
        self._save_manifest(manifest)
        if old:
            old_name = old.get("stored_name")
            if old_name:
                old_path = self.root / old_name
                if old_path.exists():
                    old_path.unlink()
        return self.public()[slot]

    def get(self, slot: str) -> dict[str, Any]:
        slot = self._validate_slot(slot)
        manifest = self._load_manifest()
        saved = manifest["slots"].get(slot)
        if not saved:
            raise FileNotFoundError("Для этого слота используется стандартный аватар.")
        path = self.root / saved.get("stored_name", "")
        if not path.is_file():
            raise FileNotFoundError("Локальный аватар не найден.")
        return {
            "path": path,
            "content_type": saved["content_type"],
            "size_bytes": saved["size_bytes"],
            "sha256": saved["sha256"],
            "filename": saved["filename"],
        }
