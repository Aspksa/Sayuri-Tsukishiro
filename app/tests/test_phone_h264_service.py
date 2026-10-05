from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
import urllib.request

from app.config import Settings
from app.core import SayuriCore
from app.logging_setup import configure_logging
from app.server import create_server
from phone import PhoneService


class FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class PhoneH264ServiceTests(unittest.TestCase):
    def test_h264_stream_uses_pinned_scrcpy_server_and_local_forward(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            service.initialize()

            pushed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
            forwarded = subprocess.CompletedProcess(args=[], returncode=0, stdout="43127\n", stderr="")
            removed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            process = MagicMock()
            process.poll.return_value = None
            process.wait.return_value = 0
            connection = FakeConnection()

            with patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ), patch.object(
                service, "_resolve_adb", return_value=Path("adb.exe")
            ), patch.object(
                service, "_resolve_scrcpy_server", return_value=Path("scrcpy-server")
            ), patch.object(
                service, "_run", side_effect=[pushed, forwarded, removed]
            ) as run, patch.object(
                service, "_connect_local_video", return_value=connection
            ), patch(
                "phone.service.subprocess.Popen", return_value=process
            ) as popen, patch(
                "phone.service.iter_h264_bridge_records",
                return_value=iter([b"SYH1", b"packet"]),
            ):
                output = list(service.h264_stream("R58M123ABC", profile="quality"))

            self.assertEqual(output, [b"SYH1", b"packet"])
            self.assertTrue(connection.closed)
            self.assertNotIn("R58M123ABC", service._h264_streams)

            self.assertIn("push", run.call_args_list[0].args[0])
            forward_argv = run.call_args_list[1].args[0]
            self.assertIn("forward", forward_argv)
            self.assertIn("tcp:0", forward_argv)
            self.assertTrue(any(value.startswith("localabstract:scrcpy_") for value in forward_argv))

            command = popen.call_args.args[0]
            self.assertIn("com.genymobile.scrcpy.Server", command)
            self.assertIn("4.1", command)
            self.assertIn("tunnel_forward=true", command)
            self.assertIn("audio=false", command)
            self.assertIn("control=false", command)
            self.assertIn("send_device_meta=false", command)
            self.assertIn("send_dummy_byte=false", command)
            self.assertIn("video_codec=h264", command)
            self.assertIn("video_bit_rate=16000000", command)
            self.assertIn("max_size=1920", command)
            self.assertIn("max_fps=60", command)

            remove_argv = run.call_args_list[2].args[0]
            self.assertEqual(remove_argv[-2:], ["--remove", "tcp:43127"])

    def test_only_one_h264_stream_per_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            service._h264_streams.add("R58M123ABC")
            with patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ), patch.object(
                service, "_resolve_adb", return_value=Path("adb.exe")
            ), patch.object(
                service, "_resolve_scrcpy_server", return_value=Path("scrcpy-server")
            ):
                with self.assertRaises(ValueError):
                    next(service.h264_stream("R58M123ABC"))

    def test_forward_port_and_bitrate_validation(self):
        good = subprocess.CompletedProcess(args=[], returncode=0, stdout="43127\n", stderr="")
        self.assertEqual(PhoneService._recv_forward_port(good), 43127)
        self.assertEqual(PhoneService._bit_rate_bps("16M"), 16_000_000)
        self.assertEqual(PhoneService._bit_rate_bps("800K"), 800_000)
        bad = subprocess.CompletedProcess(args=[], returncode=0, stdout="not-a-port", stderr="")
        with self.assertRaises(OSError):
            PhoneService._recv_forward_port(bad)


class PhoneH264ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (root / "MODULES.json").write_text(
            json.dumps({"schema_version": 1, "modules": []}),
            encoding="utf-8",
        )
        (root / "web").mkdir()
        (root / "web" / "index.html").write_text("<h1>Саюри</h1>", encoding="utf-8")
        settings = Settings(root=root, host="127.0.0.1", preferred_port=18300, port_scan_limit=100)
        self.core = SayuriCore(settings)
        self.core.initialize()
        self.server = create_server(self.core, configure_logging(settings.logs_dir))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def test_stream_endpoint_forwards_binary_protocol(self):
        self.core.phone.h264_stream = MagicMock(
            return_value=iter([b"SYH1", b"\x01session", b"\x02packet"])
        )
        with urllib.request.urlopen(
            self.base + "/api/phone/stream?serial=R58M123ABC&profile=balanced",
            timeout=3,
        ) as response:
            body = response.read()
            content_type = response.headers.get_content_type()
            protocol = response.headers.get("X-Sayuri-Stream-Protocol")

        self.assertEqual(content_type, "application/x-sayuri-h264")
        self.assertEqual(protocol, "sayuri-h264-v1")
        self.assertEqual(body, b"SYH1\x01session\x02packet")
        self.core.phone.h264_stream.assert_called_once_with(
            "R58M123ABC",
            profile="balanced",
        )


if __name__ == "__main__":
    unittest.main()
