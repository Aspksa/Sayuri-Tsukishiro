from __future__ import annotations

import struct
import unittest

from phone.h264 import (
    BRIDGE_MAGIC,
    BRIDGE_RECORD_PACKET,
    BRIDGE_RECORD_SESSION,
    H264ProtocolError,
    SCRCPY_CODEC_H264,
    SCRCPY_PACKET_FLAG_CONFIG,
    SCRCPY_PACKET_FLAG_KEY,
    iter_h264_bridge_records,
)


class FakeRecvStream:
    def __init__(self, data: bytes, chunk_size: int = 7):
        self.data = data
        self.offset = 0
        self.chunk_size = chunk_size

    def recv(self, size: int) -> bytes:
        if self.offset >= len(self.data):
            return b""
        take = min(size, self.chunk_size, len(self.data) - self.offset)
        out = self.data[self.offset:self.offset + take]
        self.offset += take
        return out


def session(width: int, height: int) -> bytes:
    return struct.pack(">III", 0x80000000, width, height)


def packet(pts_flags: int, payload: bytes) -> bytes:
    return struct.pack(">QI", pts_flags, len(payload)) + payload


class H264BridgeProtocolTests(unittest.TestCase):
    def test_scrcpy_config_is_merged_into_first_keyframe(self):
        config = b"\x00\x00\x00\x01\x67\x64\x00\x28\xaa\xbb" + b"\x00\x00\x00\x01\x68\xee"
        key = b"\x00\x00\x00\x01\x65\x88\x99"
        delta = b"\x00\x00\x00\x01\x41\x01\x02"

        wire = (
            struct.pack(">I", SCRCPY_CODEC_H264)
            + session(1080, 2340)
            + packet(SCRCPY_PACKET_FLAG_CONFIG, config)
            + packet(SCRCPY_PACKET_FLAG_KEY | 1_000_000, key)
            + packet(1_016_666, delta)
        )

        records = list(iter_h264_bridge_records(FakeRecvStream(wire)))
        self.assertEqual(records[0], BRIDGE_MAGIC)

        self.assertEqual(records[1][0], BRIDGE_RECORD_SESSION)
        self.assertEqual(struct.unpack(">II", records[1][1:9]), (1080, 2340))

        first = records[2]
        self.assertEqual(first[0], BRIDGE_RECORD_PACKET)
        self.assertEqual(first[1], 1)
        pts, size = struct.unpack(">QI", first[2:14])
        self.assertEqual(pts, 1_000_000)
        self.assertEqual(size, len(config) + len(key))
        self.assertEqual(first[14:], config + key)

        second = records[3]
        self.assertEqual(second[0], BRIDGE_RECORD_PACKET)
        self.assertEqual(second[1], 0)
        pts, size = struct.unpack(">QI", second[2:14])
        self.assertEqual(pts, 1_016_666)
        self.assertEqual(size, len(delta))
        self.assertEqual(second[14:], delta)

    def test_rotation_session_is_forwarded(self):
        key = b"\x00\x00\x00\x01\x65\x01"
        wire = (
            struct.pack(">I", SCRCPY_CODEC_H264)
            + session(1080, 2340)
            + packet(SCRCPY_PACKET_FLAG_KEY | 10, key)
            + session(2340, 1080)
            + packet(SCRCPY_PACKET_FLAG_KEY | 20, key)
        )
        records = list(iter_h264_bridge_records(FakeRecvStream(wire, chunk_size=2)))
        sessions = [record for record in records if record and record[0] == BRIDGE_RECORD_SESSION]
        self.assertEqual(len(sessions), 2)
        self.assertEqual(struct.unpack(">II", sessions[1][1:9]), (2340, 1080))

    def test_unknown_codec_is_rejected(self):
        wire = struct.pack(">I", 0x68323635)
        with self.assertRaises(H264ProtocolError):
            list(iter_h264_bridge_records(FakeRecvStream(wire)))

    def test_media_before_session_is_rejected(self):
        key = b"\x00\x00\x00\x01\x65\x01"
        wire = (
            struct.pack(">I", SCRCPY_CODEC_H264)
            + packet(SCRCPY_PACKET_FLAG_KEY | 10, key)
        )
        with self.assertRaises(H264ProtocolError):
            list(iter_h264_bridge_records(FakeRecvStream(wire)))


if __name__ == "__main__":
    unittest.main()
