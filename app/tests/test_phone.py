from __future__ import annotations

import json
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
                result = service.start_control("R58M123ABC")

            self.assertEqual(result["status"], "управление запущено")
            argv = popen.call_args.args[0]
            self.assertEqual(argv[0], "C:/runtime/scrcpy.exe")
            self.assertIn("--serial", argv)
            self.assertIn("R58M123ABC", argv)
            self.assertIn("--window-title", argv)
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
            {"serial": "R58M123ABC"},
        )
        self.assertEqual(started["status"], "управление запущено")


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


if __name__ == "__main__":
    unittest.main()
