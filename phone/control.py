from __future__ import annotations

import struct
from typing import Protocol


CONTROL_PROTOCOL_VERSION = "scrcpy-4.1"
CONTROL_MSG_GET_CLIPBOARD = 8
CONTROL_MSG_SET_CLIPBOARD = 9
DEVICE_MSG_CLIPBOARD = 0
DEVICE_MSG_ACK_CLIPBOARD = 1
DEVICE_MSG_UHID_OUTPUT = 2
COPY_KEY_NONE = 0
SEQUENCE_INVALID = 0
MAX_DEVICE_MESSAGE_BYTES = 1 << 18
MAX_CLIPBOARD_BYTES = MAX_DEVICE_MESSAGE_BYTES - 14


class DuplexStream(Protocol):
    def recv(self, size: int) -> bytes: ...
    def sendall(self, data: bytes) -> None: ...


class ControlProtocolError(ValueError):
    pass


def recv_exact(stream: DuplexStream, size: int) -> bytes:
    if size < 0:
        raise ControlProtocolError("Отрицательный размер control-чтения.")
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.recv(remaining)
        if not chunk:
            if remaining == size:
                return b""
            raise ControlProtocolError("Control socket оборвался внутри сообщения.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def encode_get_clipboard(copy_key: int = COPY_KEY_NONE) -> bytes:
    if copy_key not in {0, 1, 2}:
        raise ControlProtocolError("Некорректный copy_key clipboard.")
    return bytes([CONTROL_MSG_GET_CLIPBOARD, copy_key])


def encode_set_clipboard(
    text: str,
    *,
    paste: bool = False,
    sequence: int = 1,
) -> bytes:
    if not isinstance(text, str):
        raise ControlProtocolError("Clipboard должен быть строкой.")
    raw = text.encode("utf-8")
    if len(raw) > MAX_CLIPBOARD_BYTES:
        raise ControlProtocolError(
            f"Clipboard превышает лимит {MAX_CLIPBOARD_BYTES} байт."
        )
    if sequence < 0 or sequence > 0xFFFFFFFFFFFFFFFF:
        raise ControlProtocolError("Некорректная sequence clipboard.")
    return (
        bytes([CONTROL_MSG_SET_CLIPBOARD])
        + struct.pack(">Q", sequence)
        + bytes([1 if paste else 0])
        + struct.pack(">I", len(raw))
        + raw
    )


def recv_device_message(stream: DuplexStream) -> dict:
    raw_type = recv_exact(stream, 1)
    if len(raw_type) != 1:
        raise ControlProtocolError("Устройство не отправило control-ответ.")
    message_type = raw_type[0]

    if message_type == DEVICE_MSG_CLIPBOARD:
        raw_length = recv_exact(stream, 4)
        if len(raw_length) != 4:
            raise ControlProtocolError("Clipboard-ответ оборвался до длины.")
        size = struct.unpack(">I", raw_length)[0]
        if size > MAX_DEVICE_MESSAGE_BYTES - 5:
            raise ControlProtocolError("Clipboard-ответ превышает безопасный лимит.")
        payload = recv_exact(stream, size)
        if len(payload) != size:
            raise ControlProtocolError("Clipboard-ответ получен не полностью.")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ControlProtocolError("Clipboard устройства содержит некорректный UTF-8.") from exc
        return {"type": "clipboard", "text": text}

    if message_type == DEVICE_MSG_ACK_CLIPBOARD:
        raw_sequence = recv_exact(stream, 8)
        if len(raw_sequence) != 8:
            raise ControlProtocolError("ACK clipboard получен не полностью.")
        return {
            "type": "ack_clipboard",
            "sequence": struct.unpack(">Q", raw_sequence)[0],
        }

    if message_type == DEVICE_MSG_UHID_OUTPUT:
        header = recv_exact(stream, 4)
        if len(header) != 4:
            raise ControlProtocolError("UHID output получен не полностью.")
        device_id, size = struct.unpack(">HH", header)
        if size > MAX_DEVICE_MESSAGE_BYTES - 5:
            raise ControlProtocolError("UHID output превышает безопасный лимит.")
        payload = recv_exact(stream, size)
        if len(payload) != size:
            raise ControlProtocolError("UHID output оборвался.")
        return {
            "type": "uhid_output",
            "id": device_id,
            "data": payload,
        }

    raise ControlProtocolError(f"Неизвестный device message type: {message_type}.")
