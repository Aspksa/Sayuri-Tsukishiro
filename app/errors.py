from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SayuriError(Exception):
    code: str
    message: str
    status: int = 500

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class DatabaseError(SayuriError):
    def __init__(self, message: str):
        super().__init__("SAYURI-DB-001", message, 500)


class StaticFileError(SayuriError):
    def __init__(self, message: str):
        super().__init__("SAYURI-WEB-002", message, 404)


class BadRequestError(SayuriError):
    def __init__(self, message: str):
        super().__init__("SAYURI-API-400", message, 400)


class ProviderError(SayuriError):
    def __init__(self, message: str, *, status: int = 502):
        super().__init__("SAYURI-AI-502", message, status)
