from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AgentRequest:
    """Нормализованный запрос будущему Agent Core."""

    text: str
    context: dict[str, Any] = field(default_factory=dict)
    allowed_tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Стабильный контракт результата без привязки к AI-провайдеру."""

    status: str
    answer: str = ""
    events: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentExecutor(Protocol):
    def execute(self, request: AgentRequest) -> AgentResult:
        """Выполнить запрос через конкретную реализацию Agent Core."""


class AgentCoreContract:
    """Граница между системным ядром и будущим AI/Memory/Tool runtime."""

    @staticmethod
    def snapshot() -> dict[str, Any]:
        return {
            "status": "контур готов",
            "status_code": "contract_ready",
            "execution_enabled": False,
            "provider_connected": False,
            "memory_connected": False,
            "tools_connected": False,
            "message": "Контракт Agent Core создан; AI-провайдер ещё не подключён.",
        }

    @staticmethod
    def describe_request(request: AgentRequest) -> dict[str, Any]:
        return asdict(request)
