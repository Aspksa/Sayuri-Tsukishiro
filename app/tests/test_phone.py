from __future__ import annotations

import json
import struct
from io import BytesIO
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

from app.config import Settings
from app.core import SayuriCore
from app.logging_setup import configure_logging
from app.server import create_server
from phone import PhoneService


class FakePhoneSocket:
    def __init__(self, incoming: bytes = b"") -> None:
        self.incoming = bytearray(incoming)
        self.sent = bytearray()

    def recv(self, size: int) -> bytes:
        if not self.incoming:
            return b""
        data = bytes(self.incoming[:size])
        del self.incoming[:size]
        return data

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def close(self) -> None:
        pass


class PhoneServiceTests(unittest.TestCase):
    def test_parse_adb_devices(self):
        output = """List of devices attached
R58M123ABC device product:a56xeea model:SM_A556E device:a56x transport_id:1
192.168.1.20:39587 unauthorized product:test model:Phone_Test device:test transport_id:2
"""
        devices = PhoneService._parse_devices(output)
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0]["model"], "SM_A556E")
        self.assertTrue(devices[0]["authorized"])
        self.assertEqual(devices[0]["connection"], "usb")
        self.assertFalse(devices[1]["authorized"])
        self.assertEqual(devices[1]["connection"], "wifi")

    def test_address_and_pairing_code_validation_rejects_command_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            with self.assertRaises(ValueError):
                service.pair("127.0.0.1:37125;calc.exe", "123456")
            with patch.object(service, "_resolve_adb", return_value=Path("adb.exe")):
                with self.assertRaises(ValueError):
                    service.pair("127.0.0.1:37125", "12 3456")

    def test_pair_uses_allowlisted_argv_without_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="Successfully paired to 192.168.1.20:37125",
                stderr="",
            )
            with patch.object(service, "_resolve_adb", return_value=Path("adb.exe")), patch.object(
                service, "_run", return_value=completed
            ) as run:
                result = service.pair("192.168.1.20:37125", "123456")
            self.assertEqual(result["status"], "сопряжено")
            run.assert_called_once_with(
                ["adb.exe", "pair", "192.168.1.20:37125", "123456"]
            )

    def test_start_control_requires_authorized_device_and_uses_scrcpy_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            process = MagicMock()
            process.pid = 777
            process.poll.return_value = None
            with patch.object(service, "_resolve_scrcpy", return_value=Path("C:/runtime/scrcpy.exe")), patch.object(
                service,
                "devices",
                return_value=[
                    {
                        "serial": "R58M123ABC",
                        "state": "device",
                        "authorized": True,
                        "model": "SM_A556E",
                        "product": "a56xeea",
                        "device": "a56x",
                        "transport_id": "1",
                        "connection": "usb",
                    }
                ],
            ), patch("phone.service.subprocess.Popen", return_value=process) as popen:
                result = service.start_control("R58M123ABC", profile="quality")

            self.assertEqual(result["status"], "управление запущено")
            self.assertEqual(result["profile"], "quality")
            self.assertEqual(result["keyboard"], "uhid")
            argv = popen.call_args.args[0]
            self.assertEqual(argv[0], "C:/runtime/scrcpy.exe")
            self.assertIn("--serial", argv)
            self.assertIn("R58M123ABC", argv)
            self.assertIn("--window-title", argv)
            self.assertIn("--keyboard=uhid", argv)
            self.assertIn("--video-codec=h264", argv)
            self.assertIn("1920", argv)
            self.assertIn("16M", argv)
            self.assertNotIn("shell", popen.call_args.kwargs)



    @staticmethod
    def fake_png(width: int = 1080, height: int = 2340) -> bytes:
        return (
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\rIHDR"
            + width.to_bytes(4, "big")
            + height.to_bytes(4, "big")
            + b"\x08\x06\x00\x00\x00"
        )

    def test_screen_frame_is_cached_and_exposes_real_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            binary = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=self.fake_png(1080, 2340),
                stderr=b"",
            )
            with patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ), patch.object(
                service, "_resolve_adb", return_value=Path("adb.exe")
            ), patch.object(
                service, "_run_binary", return_value=binary
            ) as capture:
                first = service.screen_frame("R58M123ABC")
                second = service.screen_frame("R58M123ABC")

            self.assertEqual(first["width"], 1080)
            self.assertEqual(first["height"], 2340)
            self.assertFalse(first["cached"])
            self.assertTrue(second["cached"])
            capture.assert_called_once()

    def test_embedded_tap_maps_normalized_coordinates_to_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            with patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ), patch.object(
                service,
                "screen_frame",
                return_value={"width": 1000, "height": 2000},
            ), patch.object(
                service, "_resolve_adb", return_value=Path("adb.exe")
            ), patch.object(
                service, "_run", return_value=completed
            ) as run:
                result = service.tap("R58M123ABC", 0.25, 0.75)

            self.assertEqual(result["x"], 250)
            self.assertEqual(result["y"], 1499)
            self.assertEqual(
                run.call_args.args[0],
                ["adb.exe", "-s", "R58M123ABC", "shell", "input", "tap", "250", "1499"],
            )

    def test_embedded_swipe_and_keys_are_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            with patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ), patch.object(
                service,
                "screen_frame",
                return_value={"width": 1000, "height": 2000},
            ), patch.object(
                service, "_resolve_adb", return_value=Path("adb.exe")
            ), patch.object(
                service, "_run", return_value=completed
            ) as run:
                swipe = service.swipe("R58M123ABC", 0.5, 0.8, 0.5, 0.2, 300)
                key = service.key("R58M123ABC", "HOME")
                with self.assertRaises(ValueError):
                    service.key("R58M123ABC", "SHELL;RM")

            self.assertEqual(swipe["duration_ms"], 300)
            self.assertEqual(key["key"], "HOME")
            self.assertIn("KEYCODE_HOME", run.call_args.args[0])


    def test_disconnect_during_frame_is_classified_and_clears_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            service._frame_cache["R58M123ABC"] = {
                "captured_monotonic": 0.0,
                "data": self.fake_png(),
            }
            process = MagicMock()
            process.poll.return_value = None
            service._sessions["R58M123ABC"] = process

            invalid = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"",
                stderr=b"",
            )
            with patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ), patch.object(
                service, "_resolve_adb", return_value=Path("adb.exe")
            ), patch.object(
                service, "_run_binary", return_value=invalid
            ), patch.object(
                service, "devices", return_value=[]
            ):
                with self.assertRaises(ConnectionError):
                    service.screen_frame("R58M123ABC", force=True)

            self.assertNotIn("R58M123ABC", service._frame_cache)
            self.assertNotIn("R58M123ABC", service._sessions)
            process.terminate.assert_called_once()

    def test_health_reconciles_stale_session_after_usb_disconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            process = MagicMock()
            process.poll.return_value = None
            service._sessions["R58M123ABC"] = process
            service._frame_cache["R58M123ABC"] = {
                "captured_monotonic": 1.0,
                "data": self.fake_png(),
            }

            with patch.object(service, "_resolve_adb", return_value=Path("adb.exe")), patch.object(
                service, "_resolve_scrcpy", return_value=Path("scrcpy.exe")
            ), patch.object(service, "devices", return_value=[]):
                health = service.health()

            self.assertEqual(health["authorized_devices"], 0)
            self.assertEqual(health["control_sessions"], [])
            self.assertNotIn("R58M123ABC", service._frame_cache)
            process.terminate.assert_called_once()


    def test_keyboard_text_is_allowlisted_and_encoded_for_android_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            with patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ), patch.object(
                service, "_resolve_adb", return_value=Path("adb.exe")
            ), patch.object(
                service, "_run", return_value=completed
            ) as run:
                result = service.type_text("R58M123ABC", "Привет 123")

            self.assertEqual(result["status"], "текст введён")
            self.assertEqual(
                run.call_args.args[0],
                ["adb.exe", "-s", "R58M123ABC", "shell", "input", "text", "Привет%s123"],
            )

            with patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ):
                with self.assertRaises(ValueError):
                    service.type_text("R58M123ABC", "hello;rm")
                with self.assertRaises(ValueError):
                    service.type_text("R58M123ABC", "   ")



    def test_quality_profile_is_allowlisted(self):
        with self.assertRaises(ValueError):
            PhoneService._quality_profile("ultra;rm")
        name, profile = PhoneService._quality_profile("balanced")
        self.assertEqual(name, "balanced")
        self.assertEqual(profile["max_fps"], "60")
        self.assertEqual(profile["video_bit_rate"], "8M")

    def test_recording_uses_official_scrcpy_and_returns_finished_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            service.initialize()
            process = MagicMock()
            process.pid = 778
            process.poll.return_value = None
            process.wait.return_value = 0
            with patch.object(service, "_resolve_scrcpy", return_value=Path("C:/runtime/scrcpy.exe")), patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ), patch("phone.service.subprocess.Popen", return_value=process) as popen:
                started = service.start_recording("R58M123ABC", profile="balanced", audio=True)

            self.assertEqual(started["status"], "запись начата")
            argv = popen.call_args.args[0]
            self.assertIn("--no-playback", argv)
            self.assertIn("--no-window", argv)
            self.assertIn("--no-control", argv)
            self.assertIn("--video-codec=h264", argv)
            self.assertTrue(any(value.startswith("--record=") for value in argv))

            state = service._recordings["R58M123ABC"]
            state["path"].write_bytes(b"fake-mp4")
            stopped = service.stop_recording("R58M123ABC")
            self.assertEqual(stopped["status"], "запись остановлена")
            self.assertEqual(stopped["size_bytes"], 8)
            self.assertTrue(stopped["path"].is_file())

    def test_push_file_and_app_launch_are_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = PhoneService(root)
            service.initialize()
            source = root / "report.pdf"
            source.write_bytes(b"pdf")
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
            packages = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="package:org.example.safe\npackage:com.sample.app\n",
                stderr="",
            )

            with patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ), patch.object(
                service, "_resolve_adb", return_value=Path("adb.exe")
            ), patch.object(
                service,
                "_run",
                side_effect=[completed, completed],
            ) as run:
                pushed = service.push_file("R58M123ABC", source, "../Отчёт?.pdf")

            self.assertEqual(pushed["name"], "Отчёт_.pdf")
            self.assertEqual(pushed["remote_path"], "/sdcard/Download/Отчёт_.pdf")
            self.assertIn("push", run.call_args_list[0].args[0])

            with patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ), patch.object(
                service, "_resolve_adb", return_value=Path("adb.exe")
            ), patch.object(
                service,
                "_run",
                side_effect=[packages, completed],
            ) as run:
                launched = service.launch_app("R58M123ABC", "org.example.safe")

            self.assertEqual(launched["package"], "org.example.safe")
            self.assertIn("monkey", run.call_args_list[1].args[0])
            with self.assertRaises(ValueError):
                service.launch_app("R58M123ABC", "org.example.safe;rm")


    def test_clipboard_roundtrip_uses_scrcpy_control_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            text = "Буфер 🦊"
            raw = text.encode("utf-8")
            read_socket = FakePhoneSocket(bytes([0]) + struct.pack(">I", len(raw)) + raw)
            process = MagicMock()
            with patch.object(service, "_select_authorized_device", return_value={"serial": "R58M123ABC", "authorized": True}), patch.object(
                service, "_open_direct_scrcpy_channel", return_value=(Path("adb.exe"), 12345, process, read_socket)
            ), patch.object(service, "_close_direct_scrcpy_channel"):
                result = service.read_clipboard("R58M123ABC")
            self.assertEqual(result["text"], text)
            self.assertEqual(bytes(read_socket.sent), bytes([8, 0]))

            write_socket = FakePhoneSocket(bytes([1]) + struct.pack(">Q", 42))
            with patch.object(service, "_select_authorized_device", return_value={"serial": "R58M123ABC", "authorized": True}), patch.object(
                service, "_open_direct_scrcpy_channel", return_value=(Path("adb.exe"), 12346, process, write_socket)
            ), patch.object(service, "_close_direct_scrcpy_channel"), patch("phone.service.secrets.randbelow", return_value=41):
                written = service.write_clipboard("R58M123ABC", "Привет 🌙", paste=True)
            self.assertTrue(written["paste"])
            self.assertEqual(write_socket.sent[0], 9)
            self.assertEqual(struct.unpack(">Q", write_socket.sent[1:9])[0], 42)
            self.assertEqual(write_socket.sent[9], 1)

    def test_opus_stream_cleans_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            opus_head = b"OpusHead" + bytes([1, 2]) + (312).to_bytes(2, "little") + (48000).to_bytes(4, "little") + b"\x00\x00\x00"
            media = b"opus"
            incoming = struct.pack(">I", 0x6F707573) + struct.pack(">QI", 1 << 62, len(opus_head)) + opus_head + struct.pack(">QI", 1234, len(media)) + media
            sock = FakePhoneSocket(incoming)
            process = MagicMock()
            with patch.object(service, "_select_authorized_device", return_value={"serial": "R58M123ABC", "authorized": True}), patch.object(
                service, "_open_direct_scrcpy_channel", return_value=(Path("adb.exe"), 12345, process, sock)
            ), patch.object(service, "_close_direct_scrcpy_channel"):
                records = list(service.opus_stream("R58M123ABC"))
            self.assertEqual(records[0], b"SYA1")
            self.assertNotIn("R58M123ABC", service._audio_streams)


class PhoneApiTests(unittest.TestCase):
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

        settings = Settings(root=root, host="127.0.0.1", preferred_port=18200, port_scan_limit=100)
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

    def post_json(self, path: str, payload: dict):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_phone_routes(self):
        self.core.phone.health = MagicMock(
            return_value={
                "status": "готово",
                "status_code": "ready",
                "runtime": {"ready": True},
                "devices": [],
                "authorized_devices": 0,
                "control_sessions": [],
            }
        )
        with urllib.request.urlopen(self.base + "/api/phone", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["status_code"], "ready")

        self.core.phone.pair = MagicMock(return_value={"status": "сопряжено"})
        paired = self.post_json(
            "/api/phone/pair",
            {"address": "192.168.1.20:37125", "pairing_code": "123456"},
        )
        self.assertEqual(paired["status"], "сопряжено")

        self.core.phone.start_control = MagicMock(
            return_value={"status": "управление запущено", "serial": "R58M123ABC"}
        )
        started = self.post_json(
            "/api/phone/control/start",
            {"serial": "R58M123ABC", "profile": "quality"},
        )
        self.assertEqual(started["status"], "управление запущено")
        self.core.phone.start_control.assert_called_once_with(
            "R58M123ABC",
            profile="quality",
        )


    def test_embedded_frame_and_input_routes(self):
        frame_bytes = PhoneServiceTests.fake_png(1080, 2340)
        self.core.phone.screen_frame = MagicMock(
            return_value={
                "serial": "R58M123ABC",
                "data": frame_bytes,
                "width": 1080,
                "height": 2340,
                "cached": False,
            }
        )
        with urllib.request.urlopen(
            self.base + "/api/phone/frame?serial=R58M123ABC",
            timeout=3,
        ) as response:
            body = response.read()
            self.assertEqual(response.headers.get_content_type(), "image/png")
            self.assertEqual(response.headers["X-Sayuri-Phone-Width"], "1080")
            self.assertEqual(response.headers["X-Sayuri-Phone-Height"], "2340")
        self.assertEqual(body, frame_bytes)

        self.core.phone.tap = MagicMock(
            return_value={"status": "касание выполнено", "x": 540, "y": 1170}
        )
        tapped = self.post_json(
            "/api/phone/input/tap",
            {"serial": "R58M123ABC", "x": 0.5, "y": 0.5},
        )
        self.assertEqual(tapped["status"], "касание выполнено")

        self.core.phone.swipe = MagicMock(
            return_value={"status": "свайп выполнен"}
        )
        swiped = self.post_json(
            "/api/phone/input/swipe",
            {
                "serial": "R58M123ABC",
                "x1": 0.5,
                "y1": 0.8,
                "x2": 0.5,
                "y2": 0.2,
                "duration_ms": 280,
            },
        )
        self.assertEqual(swiped["status"], "свайп выполнен")

        self.core.phone.key = MagicMock(
            return_value={"status": "кнопка нажата", "key": "BACK"}
        )
        keyed = self.post_json(
            "/api/phone/input/key",
            {"serial": "R58M123ABC", "key": "BACK"},
        )
        self.assertEqual(keyed["key"], "BACK")

        self.core.phone.type_text = MagicMock(
            return_value={"status": "текст введён", "characters": 6}
        )
        typed = self.post_json(
            "/api/phone/input/text",
            {"serial": "R58M123ABC", "text": "Sayuri"},
        )
        self.assertEqual(typed["status"], "текст введён")


    def test_disconnected_frame_returns_phone_conflict(self):
        self.core.phone.screen_frame = MagicMock(
            side_effect=ConnectionError("Телефон отключён или потерял авторизацию ADB.")
        )
        request = urllib.request.Request(
            self.base + "/api/phone/frame?serial=R58M123ABC",
            method="GET",
        )
        with self.assertRaises(urllib.error.HTTPError) as captured:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(captured.exception.code, 409)
        payload = json.loads(captured.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "SAYURI-PHONE-409")
        self.assertIn("отключён", payload["error"]["message"])


    def test_phone_pro_routes_capture_recording_apps_and_file_push(self):
        frame_bytes = PhoneServiceTests.fake_png(1080, 2340)
        self.core.phone.screen_frame = MagicMock(
            return_value={
                "serial": "R58M123ABC",
                "data": frame_bytes,
                "width": 1080,
                "height": 2340,
                "cached": False,
            }
        )
        captured = self.post_json(
            "/api/phone/capture",
            {"serial": "R58M123ABC"},
        )
        self.assertEqual(captured["status"], "снимок сохранён")
        stored = self.core.disk.get_file(captured["file"]["id"])
        self.assertEqual(stored["content_type"], "image/png")
        self.assertEqual(stored["path"].read_bytes(), frame_bytes)

        self.core.phone.start_recording = MagicMock(
            return_value={
                "status": "запись начата",
                "serial": "R58M123ABC",
                "profile": "quality",
                "audio": True,
            }
        )
        recording = self.post_json(
            "/api/phone/recording/start",
            {"serial": "R58M123ABC", "profile": "quality", "audio": True},
        )
        self.assertEqual(recording["status"], "запись начата")

        recording_path = Path(self.temp.name) / "phone-record.mp4"
        recording_path.write_bytes(b"video")
        self.core.phone.stop_recording = MagicMock(
            return_value={
                "status": "запись остановлена",
                "serial": "R58M123ABC",
                "path": recording_path,
                "name": "phone-record.mp4",
                "size_bytes": 5,
                "profile": "quality",
                "audio": True,
            }
        )
        stopped = self.post_json(
            "/api/phone/recording/stop",
            {"serial": "R58M123ABC"},
        )
        self.assertEqual(stopped["status"], "запись остановлена")
        self.assertFalse(recording_path.exists())
        saved_video = self.core.disk.get_file(stopped["file"]["id"])
        self.assertEqual(saved_video["path"].read_bytes(), b"video")

        disk_item = self.core.disk.store_stream(
            name="report.txt",
            content_type="text/plain",
            size_bytes=4,
            stream=BytesIO(b"data"),
        )
        self.core.phone.push_file = MagicMock(
            return_value={
                "status": "файл отправлен",
                "serial": "R58M123ABC",
                "name": "report.txt",
                "size_bytes": 4,
                "remote_path": "/sdcard/Download/report.txt",
            }
        )
        pushed = self.post_json(
            "/api/phone/files/push",
            {"serial": "R58M123ABC", "file_id": disk_item["id"]},
        )
        self.assertEqual(pushed["status"], "файл отправлен")

        self.core.phone.list_apps = MagicMock(
            return_value=[{"package": "org.example.safe", "label": "org.example.safe"}]
        )
        with urllib.request.urlopen(
            self.base + "/api/phone/apps?serial=R58M123ABC",
            timeout=3,
        ) as response:
            apps = json.loads(response.read().decode("utf-8"))
        self.assertEqual(apps["apps"][0]["package"], "org.example.safe")

        self.core.phone.launch_app = MagicMock(
            return_value={
                "status": "приложение открыто",
                "serial": "R58M123ABC",
                "package": "org.example.safe",
            }
        )
        launched = self.post_json(
            "/api/phone/apps/launch",
            {"serial": "R58M123ABC", "package": "org.example.safe"},
        )
        self.assertEqual(launched["status"], "приложение открыто")


    def test_clipboard_and_audio_routes(self):
        self.core.phone.read_clipboard = MagicMock(
            return_value={
                "status": "буфер получен",
                "serial": "R58M123ABC",
                "text": "Привет 🦊",
                "characters": 8,
                "bytes": 17,
            }
        )
        with urllib.request.urlopen(
            self.base + "/api/phone/clipboard?serial=R58M123ABC",
            timeout=3,
        ) as response:
            clipboard = json.loads(response.read().decode("utf-8"))
        self.assertEqual(clipboard["text"], "Привет 🦊")

        self.core.phone.write_clipboard = MagicMock(
            return_value={
                "status": "буфер телефона обновлён",
                "serial": "R58M123ABC",
                "characters": 6,
                "bytes": 6,
                "paste": True,
            }
        )
        updated = self.post_json(
            "/api/phone/clipboard",
            {"serial": "R58M123ABC", "text": "Sayuri", "paste": True},
        )
        self.assertEqual(updated["status"], "буфер телефона обновлён")
        self.core.phone.write_clipboard.assert_called_once_with(
            "R58M123ABC",
            "Sayuri",
            paste=True,
        )

        opus_head = b"OpusHead" + bytes([1, 2]) + (312).to_bytes(2, "little") + (48000).to_bytes(4, "little") + b"\x00\x00\x00"
        self.core.phone.opus_stream = MagicMock(
            return_value=iter([
                b"SYA1",
                bytes([1]) + struct.pack(">I", len(opus_head)) + opus_head,
            ])
        )
        with urllib.request.urlopen(
            self.base + "/api/phone/audio?serial=R58M123ABC",
            timeout=3,
        ) as response:
            body = response.read()
            self.assertEqual(
                response.headers.get_content_type(),
                "application/x-sayuri-opus",
            )
            self.assertEqual(
                response.headers["X-Sayuri-Audio-Protocol"],
                "sayuri-opus-v1",
            )
        self.assertTrue(body.startswith(b"SYA1"))


if __name__ == "__main__":
    unittest.main()
