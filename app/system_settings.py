from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any

from .database import Database
from .errors import BadRequestError


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    label: str
    description: str
    kind: str
    default: Any
    minimum: int | None = None
    maximum: int | None = None
    restart_required: bool = False

    def public(self, value: Any) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "type": self.kind,
            "value": value,
            "default": self.default,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "restart_required": self.restart_required,
        }


SETTING_SPECS: tuple[SettingSpec, ...] = (
    SettingSpec(
        "browser.auto_open",
        "Открывать сайт при запуске",
        "Автоматически открывать браузер после успешной проверки локального сервера.",
        "boolean",
        True,
        restart_required=True,
    ),
    SettingSpec(
        "ui.refresh_seconds",
        "Интервал обновления",
        "Как часто интерфейс обновляет состояние системы, в секундах.",
        "integer",
        10,
        minimum=5,
        maximum=60,
    ),
    SettingSpec(
        "events.display_limit",
        "Количество событий",
        "Сколько последних событий показывать в разделе настроек.",
        "integer",
        12,
        minimum=5,
        maximum=50,
    ),
    SettingSpec(
        "diagnostics.http_requests",
        "Журнал HTTP-запросов",
        "Записывать обычные локальные HTTP-запросы в logs/sayuri.log.",
        "boolean",
        True,
    ),
)
SPEC_BY_KEY = {item.key: item for item in SETTING_SPECS}


class SystemSettings:
    def __init__(self, database: Database):
        self.database = database
        self._values: dict[str, Any] = {}
        self._lock = RLock()

    def initialize(self) -> None:
        defaults = {spec.key: spec.default for spec in SETTING_SPECS}
        self.database.ensure_settings(defaults)
        with self._lock:
            self._values = self.database.read_settings()

    def value(self, key: str) -> Any:
        with self._lock:
            if key in self._values:
                return self._values[key]
        spec = SPEC_BY_KEY.get(key)
        if spec is None:
            raise KeyError(key)
        return spec.default

    def public(self) -> list[dict[str, Any]]:
        with self._lock:
            values = dict(self._values)
        return [spec.public(values.get(spec.key, spec.default)) for spec in SETTING_SPECS]

    def update(self, changes: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(changes, dict) or not changes:
            raise BadRequestError("Нужно передать хотя бы одну настройку.")

        validated: dict[str, Any] = {}
        for key, value in changes.items():
            spec = SPEC_BY_KEY.get(key)
            if spec is None:
                raise BadRequestError(f"Неизвестная настройка: {key}")
            validated[key] = self._validate(spec, value)

        self.database.write_settings(validated)
        with self._lock:
            self._values.update(validated)
        return self.public()

    @staticmethod
    def _validate(spec: SettingSpec, value: Any) -> Any:
        if spec.kind == "boolean":
            if type(value) is not bool:
                raise BadRequestError(f"«{spec.label}»: ожидается логическое значение.")
            return value

        if spec.kind == "integer":
            if type(value) is not int:
                raise BadRequestError(f"«{spec.label}»: ожидается целое число.")
            if spec.minimum is not None and value < spec.minimum:
                raise BadRequestError(f"«{spec.label}»: минимум {spec.minimum}.")
            if spec.maximum is not None and value > spec.maximum:
                raise BadRequestError(f"«{spec.label}»: максимум {spec.maximum}.")
            return value

        raise BadRequestError(f"Неподдерживаемый тип настройки: {spec.kind}")
