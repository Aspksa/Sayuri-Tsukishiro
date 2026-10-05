from __future__ import annotations

import struct
from typing import Iterator, Protocol


BRIDGE_MAGIC = b"SYH1"
BRIDGE_RECORD_SESSION = 1
BRIDGE_RECORD_PACKET = 2
SCRCPY_CODEC_H264 = 0x68323634
SCRCPY_PACKET_FLAG_SESSION = 1 << 63
SCRCPY_PACKET_FLAG_CONFIG = 1 << 62
SCRCPY_PACKET_FLAG_KEY = 1 << 61
SCRCPY_PACKET_PTS_MASK = SCRCPY_PACKET_FLAG_KEY - 1
MAX_VIDEO_PACKET_BYTES = 32 * 1024 * 1024
MAX_CONFIG_BYTES = 2 * 1024 * 1024


class RecvStream(Protocol):
    def recv(self, size: int) -> bytes: ...


class H264ProtocolError(ValueError):
    pass


def recv_exact(stream: RecvStream, size: int) -> bytes:
    if size < 0:
        raise H264ProtocolError("Отрицательный размер чтения.")
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.recv(remaining)
        if not chunk:
            if remaining == size:
                return b""
            raise H264ProtocolError("H.264 поток оборвался внутри пакета.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _session_record(header: bytes) -> bytes:
    width = struct.unpack(">I", header[4:8])[0]
    height = struct.unpack(">I", header[8:12])[0]
    if width <= 0 or height <= 0 or width > 10000 or height > 10000:
        raise H264ProtocolError("scrcpy сообщил некорректный размер видео.")
    return bytes([BRIDGE_RECORD_SESSION]) + struct.pack(">II", width, height)


def iter_h264_bridge_records(stream: RecvStream) -> Iterator[bytes]:
    """Translate scrcpy 4.1 video framing into Sayuri's stable browser framing."""
    codec_raw = recv_exact(stream, 4)
    if len(codec_raw) != 4:
        raise H264ProtocolError("scrcpy не передал идентификатор видеокодека.")
    codec_id = struct.unpack(">I", codec_raw)[0]
    if codec_id != SCRCPY_CODEC_H264:
        raise H264ProtocolError(
            f"Ожидался H.264 codec id 0x{SCRCPY_CODEC_H264:08x}, получен 0x{codec_id:08x}."
        )

    yield BRIDGE_MAGIC
    pending_config = b""
    saw_session = False

    while True:
        header = recv_exact(stream, 12)
        if not header:
            return
        if len(header) != 12:
            raise H264ProtocolError("Некорректный заголовок scrcpy video packet.")

        pts_flags = struct.unpack(">Q", header[:8])[0]
        if pts_flags & SCRCPY_PACKET_FLAG_SESSION:
            saw_session = True
            pending_config = b""
            yield _session_record(header)
            continue

        if not saw_session:
            raise H264ProtocolError("Видео-пакет получен до session packet.")

        packet_size = struct.unpack(">I", header[8:12])[0]
        if packet_size <= 0 or packet_size > MAX_VIDEO_PACKET_BYTES:
            raise H264ProtocolError("Недопустимый размер H.264 пакета.")

        payload = recv_exact(stream, packet_size)
        if len(payload) != packet_size:
            raise H264ProtocolError("H.264 пакет получен не полностью.")

        is_config = bool(pts_flags & SCRCPY_PACKET_FLAG_CONFIG)
        is_key = bool(pts_flags & SCRCPY_PACKET_FLAG_KEY)
        if is_config:
            if len(pending_config) + len(payload) > MAX_CONFIG_BYTES:
                raise H264ProtocolError("Конфигурация H.264 превышает безопасный лимит.")
            pending_config += payload
            continue

        if pending_config:
            payload = pending_config + payload
            pending_config = b""

        pts = pts_flags & SCRCPY_PACKET_PTS_MASK
        flags = 1 if is_key else 0
        yield (
            bytes([BRIDGE_RECORD_PACKET, flags])
            + struct.pack(">QI", pts, len(payload))
            + payload
        )
