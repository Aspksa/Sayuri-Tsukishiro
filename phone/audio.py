from __future__ import annotations

import struct
from typing import Iterator, Protocol


AUDIO_BRIDGE_VERSION = "sayuri-opus-v1"
AUDIO_BRIDGE_MAGIC = b"SYA1"
AUDIO_RECORD_CONFIG = 1
AUDIO_RECORD_PACKET = 2
SCRCPY_CODEC_OPUS = 0x6F707573
SCRCPY_PACKET_FLAG_SESSION = 1 << 63
SCRCPY_PACKET_FLAG_CONFIG = 1 << 62
SCRCPY_PACKET_PTS_MASK = (1 << 61) - 1
MAX_AUDIO_PACKET_BYTES = 2 * 1024 * 1024
MAX_AUDIO_CONFIG_BYTES = 64 * 1024


class RecvStream(Protocol):
    def recv(self, size: int) -> bytes: ...


class AudioProtocolError(ValueError):
    pass


def recv_exact(stream: RecvStream, size: int) -> bytes:
    if size < 0:
        raise AudioProtocolError("Отрицательный размер audio-чтения.")
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.recv(remaining)
        if not chunk:
            if remaining == size:
                return b""
            raise AudioProtocolError("Opus поток оборвался внутри пакета.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _validate_opus_head(payload: bytes) -> None:
    if len(payload) < 19 or not payload.startswith(b"OpusHead"):
        raise AudioProtocolError("scrcpy передал некорректный OpusHead.")
    channels = payload[9]
    if channels < 1 or channels > 8:
        raise AudioProtocolError("OpusHead содержит недопустимое число каналов.")


def iter_opus_bridge_records(stream: RecvStream) -> Iterator[bytes]:
    """Translate scrcpy 4.1 Opus framing into Sayuri's stable browser framing."""
    codec_raw = recv_exact(stream, 4)
    if len(codec_raw) != 4:
        raise AudioProtocolError("scrcpy не передал идентификатор аудиокодека.")
    codec_id = struct.unpack(">I", codec_raw)[0]
    if codec_id == 0:
        raise AudioProtocolError("Android отключил аудиопоток.")
    if codec_id == 1:
        raise AudioProtocolError("Android сообщил ошибку конфигурации аудио.")
    if codec_id != SCRCPY_CODEC_OPUS:
        raise AudioProtocolError(
            f"Ожидался Opus codec id 0x{SCRCPY_CODEC_OPUS:08x}, получен 0x{codec_id:08x}."
        )

    yield AUDIO_BRIDGE_MAGIC
    saw_config = False

    while True:
        header = recv_exact(stream, 12)
        if not header:
            return
        if len(header) != 12:
            raise AudioProtocolError("Некорректный заголовок scrcpy audio packet.")

        pts_flags = struct.unpack(">Q", header[:8])[0]
        if pts_flags & SCRCPY_PACKET_FLAG_SESSION:
            raise AudioProtocolError("Audio stream неожиданно содержит session packet.")

        packet_size = struct.unpack(">I", header[8:12])[0]
        if packet_size <= 0 or packet_size > MAX_AUDIO_PACKET_BYTES:
            raise AudioProtocolError("Недопустимый размер Opus пакета.")

        payload = recv_exact(stream, packet_size)
        if len(payload) != packet_size:
            raise AudioProtocolError("Opus пакет получен не полностью.")

        is_config = bool(pts_flags & SCRCPY_PACKET_FLAG_CONFIG)
        if is_config:
            if packet_size > MAX_AUDIO_CONFIG_BYTES:
                raise AudioProtocolError("Opus config превышает безопасный лимит.")
            _validate_opus_head(payload)
            saw_config = True
            yield bytes([AUDIO_RECORD_CONFIG]) + struct.pack(">I", packet_size) + payload
            continue

        if not saw_config:
            raise AudioProtocolError("Opus media packet получен до OpusHead.")

        pts = pts_flags & SCRCPY_PACKET_PTS_MASK
        yield (
            bytes([AUDIO_RECORD_PACKET])
            + struct.pack(">QI", pts, packet_size)
            + payload
        )
