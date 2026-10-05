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


if __name__ == "__main__":
    unittest.main()
