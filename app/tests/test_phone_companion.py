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
from phone.companion import (
    COMPANION_DEVICE_PORT,
    COMPANION_PACKAGE,
    COMPANION_PROTOCOL_VERSION,
    CompanionRegistry,
)


ROOT = Path(__file__).resolve().parents[2]


class CompanionRegistryTests(unittest.TestCase):
    def test_token_authentication_and_event_order(self):
        registry = CompanionRegistry()
        token = registry.issue("R58M123ABC")

        self.assertTrue(registry.authenticate("R58M123ABC", token))
        self.assertFalse(registry.authenticate("R58M123ABC", token + "x"))

        first = registry.ingest(
            "R58M123ABC",
            token,
            {
                "type": "notification_posted",
                "package": "org.example.chat",
                "title": "Сообщение",
                "text": "Привет",
                "event_time": 123,
            },
        )
        second = registry.ingest(
            "R58M123ABC",
            token,
            {"type": "notification_removed", "package": "org.example.chat"},
        )

        self.assertLess(first["sequence"], second["sequence"])
        events = registry.events(serial="R58M123ABC", after=first["sequence"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "notification_removed")
        self.assertEqual(registry.status("R58M123ABC")["events"], 2)

    def test_invalid_token_and_unknown_event_are_rejected(self):
        registry = CompanionRegistry()
        token = registry.issue("SERIAL")

        with self.assertRaises(PermissionError):
            registry.ingest("SERIAL", "wrong", {"type": "heartbeat"})
        with self.assertRaises(ValueError):
            registry.ingest("SERIAL", token, {"type": "run_shell"})

    def test_event_text_is_bounded(self):
        registry = CompanionRegistry()
        token = registry.issue("SERIAL")
        registry.ingest(
            "SERIAL",
            token,
            {
                "type": "notification_posted",
                "title": "x" * 10_000,
                "text": "y" * 10_000,
            },
        )
        event = registry.events(serial="SERIAL")[0]
        self.assertEqual(len(event["title"]), 4096)
        self.assertEqual(len(event["text"]), 4096)


class CompanionServiceTests(unittest.TestCase):
    def test_enable_companion_creates_reverse_and_explicit_pairing_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            service.initialize()
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="ok",
                stderr="",
            )
            with patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ), patch.object(
                service,
                "_resolve_adb",
                return_value=Path("adb.exe"),
            ), patch.object(
                service,
                "_companion_installed",
                return_value=True,
            ), patch.object(
                service,
                "_companion_notification_access",
                return_value=False,
            ), patch.object(
                service,
                "_run",
                return_value=completed,
            ) as run:
                result = service.enable_companion(
                    "R58M123ABC",
                    host_port=8765,
                )

            self.assertEqual(result["protocol_version"], COMPANION_PROTOCOL_VERSION)
            self.assertTrue(result["user_action_required"])
            calls = [call.args[0] for call in run.call_args_list]
            self.assertIn(
                [
                    "adb.exe",
                    "-s",
                    "R58M123ABC",
                    "reverse",
                    f"tcp:{COMPANION_DEVICE_PORT}",
                    "tcp:8765",
                ],
                calls,
            )
            launch = next(argv for argv in calls if "am" in argv and "start" in argv)
            self.assertIn("--es", launch)
            self.assertIn("sayuri_token", launch)
            self.assertIn("sayuri_serial", launch)
            self.assertNotIn("token", result)

    def test_missing_companion_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = PhoneService(Path(tmp))
            service.initialize()
            with patch.object(
                service,
                "_select_authorized_device",
                return_value={"serial": "R58M123ABC", "authorized": True},
            ), patch.object(
                service,
                "_resolve_adb",
                return_value=Path("adb.exe"),
            ), patch.object(
                service,
                "_companion_installed",
                return_value=False,
            ):
                with self.assertRaises(FileNotFoundError):
                    service.enable_companion("R58M123ABC", host_port=8765)


class CompanionSourceContractTests(unittest.TestCase):
    def test_android_manifest_uses_notification_listener_permission(self):
        manifest = (
            ROOT / "companion" / "app" / "src" / "main" / "AndroidManifest.xml"
        ).read_text(encoding="utf-8")
        self.assertIn("android.permission.BIND_NOTIFICATION_LISTENER_SERVICE", manifest)
        self.assertIn("android.service.notification.NotificationListenerService", manifest)
        self.assertIn('android:name=".PairingActivity"', manifest)
        self.assertIn('android:exported="true"', manifest)

    def test_bridge_is_localhost_only_and_bearer_authenticated(self):
        bridge = (
            ROOT
            / "companion"
            / "app"
            / "src"
            / "main"
            / "java"
            / "com"
            / "sayuri"
            / "tsukishiro"
            / "companion"
            / "BridgeClient.java"
        ).read_text(encoding="utf-8")
        self.assertIn("http://127.0.0.1:", bridge)
        self.assertIn('Authorization", "Bearer " + token', bridge)
        self.assertIn("X-Sayuri-Phone-Serial", bridge)
        self.assertNotIn("https://", bridge)

    def test_companion_build_is_version_pinned(self):
        root_build = (ROOT / "companion" / "build.gradle").read_text(encoding="utf-8")
        workflow = (
            ROOT / ".github" / "workflows" / "companion.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('version "9.4.0"', root_build)
        self.assertIn('GRADLE_VERSION: "9.6.1"', workflow)
        self.assertIn(
            "9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14",
            workflow,
        )
        self.assertIn("platforms;android-36", workflow)


class CompanionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (root / "MODULES.json").write_text(
            json.dumps({"schema_version": 1, "modules": []}),
            encoding="utf-8",
        )
        (root / "web").mkdir()
        (root / "web" / "index.html").write_text("<h1>Sayuri</h1>", encoding="utf-8")

        settings = Settings(
            root=root,
            host="127.0.0.1",
            preferred_port=18800,
            port_scan_limit=100,
        )
        self.core = SayuriCore(settings)
        self.core.initialize()
        self.server = create_server(
            self.core,
            configure_logging(settings.logs_dir),
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def post_json(self, path: str, payload: dict, headers=None):
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_companion_status_events_and_enable_routes(self):
        self.core.phone.companion_status = MagicMock(
            return_value={"installed": True, "paired": False}
        )
        with urllib.request.urlopen(
            self.base + "/api/phone/companion?serial=R58M123ABC",
            timeout=3,
        ) as response:
            status = json.loads(response.read().decode("utf-8"))
        self.assertTrue(status["installed"])

        self.core.phone.companion_events = MagicMock(
            return_value={"events": [], "count": 0}
        )
        with urllib.request.urlopen(
            self.base + "/api/phone/companion/events?serial=R58M123ABC&after=7",
            timeout=3,
        ) as response:
            events = json.loads(response.read().decode("utf-8"))
        self.assertEqual(events["count"], 0)

        self.core.phone.enable_companion = MagicMock(
            return_value={
                "status": "ожидается подтверждение на телефоне",
                "serial": "R58M123ABC",
            }
        )
        enabled = self.post_json(
            "/api/phone/companion/enable",
            {"serial": "R58M123ABC"},
        )
        self.assertEqual(enabled["serial"], "R58M123ABC")
        self.core.phone.enable_companion.assert_called_once_with(
            "R58M123ABC",
            host_port=self.server.server_port,
        )

    def test_companion_event_requires_bearer_token(self):
        self.core.phone.companion_event = MagicMock(
            return_value={"status": "принято", "sequence": 1}
        )
        accepted = self.post_json(
            "/api/phone/companion/events",
            {"type": "heartbeat"},
            headers={
                "Authorization": "Bearer secret-token",
                "X-Sayuri-Phone-Serial": "R58M123ABC",
            },
        )
        self.assertEqual(accepted["sequence"], 1)
        self.core.phone.companion_event.assert_called_once_with(
            "R58M123ABC",
            "secret-token",
            {"type": "heartbeat"},
        )

        self.core.phone.companion_event = MagicMock(
            side_effect=PermissionError("Неверный токен Sayuri Companion.")
        )
        request = urllib.request.Request(
            self.base + "/api/phone/companion/events",
            data=b'{"type":"heartbeat"}',
            headers={
                "Content-Type": "application/json",
                "X-Sayuri-Phone-Serial": "R58M123ABC",
            },
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as captured:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(captured.exception.code, 403)
        body = json.loads(captured.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "SAYURI-COMPANION-403")


if __name__ == "__main__":
    unittest.main()
