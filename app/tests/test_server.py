from __future__ import annotations

import json
import logging
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from app.config import Settings
from app.core import SayuriCore
from app.logging_setup import configure_logging
from app.server import SayuriRequestHandler, create_server


class _AbortWriter:
    def write(self, body):
        raise ConnectionAbortedError(10053, "клиент закрыл соединение")


class ServerTests(unittest.TestCase):
    def _start_server(self, root: Path):
        (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (root / "MODULES.json").write_text(
            json.dumps({"schema_version": 1, "modules": []}),
            encoding="utf-8",
        )
        (root / "web").mkdir()
        (root / "web" / "index.html").write_text("<h1>Саюри</h1>", encoding="utf-8")
        settings = Settings(root=root, host="127.0.0.1", preferred_port=18000, port_scan_limit=100)
        core = SayuriCore(settings)
        core.initialize()
        server = create_server(core, configure_logging(settings.logs_dir))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_system_settings_static_index_and_favicon(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server, thread = self._start_server(root)
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(base + "/api/system", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["status"], "готово")
                    self.assertEqual(payload["agent"]["status_code"], "provider_not_configured")

                with urllib.request.urlopen(base + "/api/settings", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    keys = {item["key"] for item in payload["settings"]}
                    self.assertIn("ui.refresh_seconds", keys)

                with urllib.request.urlopen(base + "/api/sayuri/profile", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["provider"]["model"], "deepseek-ai/DeepSeek-V4-Flash")
                    self.assertFalse(payload["provider"]["configured"])

                secret = "test-cloudru-key-123456789"
                body = json.dumps({"api_key": secret}).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/sayuri/provider",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertTrue(payload["provider"]["configured"])
                    self.assertNotIn(secret, json.dumps(payload, ensure_ascii=False))

                body = json.dumps(
                    {"settings": {"ui.refresh_seconds": 15, "events.display_limit": 20}}
                ).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/settings",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    values = {item["key"]: item["value"] for item in payload["settings"]}
                    self.assertEqual(values["ui.refresh_seconds"], 15)
                    self.assertEqual(values["events.display_limit"], 20)

                with urllib.request.urlopen(base + "/", timeout=2) as response:
                    self.assertIn("Саюри", response.read().decode("utf-8"))

                try:
                    urllib.request.urlopen(base + "/favicon.ico", timeout=2)
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 204)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_client_disconnect_is_not_raised_as_server_error(self):
        handler = SayuriRequestHandler.__new__(SayuriRequestHandler)
        handler.path = "/api/health"
        handler.wfile = _AbortWriter()
        handler.server = type(
            "Server",
            (),
            {"logger": logging.getLogger("sayuri-test")},
        )()
        handler._headers = lambda status, content_type, length, extra_headers=None: None
        self.assertFalse(handler._send(b"{}", "application/json", 200))


if __name__ == "__main__":
    unittest.main()
