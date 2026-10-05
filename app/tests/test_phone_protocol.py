from __future__ import annotations

import struct
import unittest

from phone.audio import (
    AUDIO_BRIDGE_MAGIC,
    AUDIO_RECORD_CONFIG,
    AUDIO_RECORD_PACKET,
    AudioProtocolError,
    iter_opus_bridge_records,
)
from phone.control import (
    ControlProtocolError,
    encode_get_clipboard,
    encode_set_clipboard,
    recv_device_message,
)


class FakeSocket:
    def __init__(self, incoming: bytes = b"") -> None:
        self.incoming = bytearray(incoming)
        self.sent = bytearray()

    def recv(self, size: int) -> bytes:
        if not self.incoming:
            return b""
        chunk = bytes(self.incoming[:size])
        del self.incoming[:size]
        return chunk

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)


class PhoneControlProtocolTests(unittest.TestCase):
    def test_get_clipboard_wire_format(self):
        self.assertEqual(encode_get_clipboard(), bytes([8, 0]))

    def test_set_clipboard_wire_format_is_utf8_and_ack_sequence(self):
        payload = encode_set_clipboard("Привет 🦊", paste=True, sequence=77)
        self.assertEqual(payload[0], 9)
        self.assertEqual(struct.unpack(">Q", payload[1:9])[0], 77)
        self.assertEqual(payload[9], 1)
        size = struct.unpack(">I", payload[10:14])[0]
        self.assertEqual(payload[14:14 + size].decode("utf-8"), "Привет 🦊")

        incoming = bytes([1]) + struct.pack(">Q", 77)
        message = recv_device_message(FakeSocket(incoming))
        self.assertEqual(message, {"type": "ack_clipboard", "sequence": 77})

    def test_device_clipboard_message_decodes_utf8(self):
        text = "Текст с телефона 📱"
        raw = text.encode("utf-8")
        message = recv_device_message(
            FakeSocket(bytes([0]) + struct.pack(">I", len(raw)) + raw)
        )
        self.assertEqual(message["type"], "clipboard")
        self.assertEqual(message["text"], text)

    def test_control_rejects_bad_sequence(self):
        with self.assertRaises(ControlProtocolError):
            encode_set_clipboard("x", sequence=-1)


class PhoneAudioProtocolTests(unittest.TestCase):
    @staticmethod
    def opus_head(channels: int = 2, sample_rate: int = 48000) -> bytes:
        return (
            b"OpusHead"
            + bytes([1, channels])
            + (312).to_bytes(2, "little")
            + sample_rate.to_bytes(4, "little")
            + b"\x00\x00\x00"
        )

    def test_opus_stream_translates_config_and_media(self):
        opus_head = self.opus_head()
        config_header = struct.pack(">QI", 1 << 62, len(opus_head))
        media = b"\xF8\xFF\xFE"
        media_header = struct.pack(">QI", 123456, len(media))
        source = FakeSocket(
            struct.pack(">I", 0x6F707573)
            + config_header
            + opus_head
            + media_header
            + media
        )

        records = list(iter_opus_bridge_records(source))
        self.assertEqual(records[0], AUDIO_BRIDGE_MAGIC)
        self.assertEqual(records[1][0], AUDIO_RECORD_CONFIG)
        config_size = struct.unpack(">I", records[1][1:5])[0]
        self.assertEqual(records[1][5:5 + config_size], opus_head)

        self.assertEqual(records[2][0], AUDIO_RECORD_PACKET)
        pts, size = struct.unpack(">QI", records[2][1:13])
        self.assertEqual(pts, 123456)
        self.assertEqual(size, len(media))
        self.assertEqual(records[2][13:], media)

    def test_opus_stream_rejects_wrong_codec(self):
        source = FakeSocket(struct.pack(">I", 0x00616163))
        with self.assertRaises(AudioProtocolError):
            list(iter_opus_bridge_records(source))

    def test_opus_stream_requires_config_before_media(self):
        media = b"abc"
        source = FakeSocket(
            struct.pack(">I", 0x6F707573)
            + struct.pack(">QI", 10, len(media))
            + media
        )
        with self.assertRaises(AudioProtocolError):
            list(iter_opus_bridge_records(source))


if __name__ == "__main__":
    unittest.main()
