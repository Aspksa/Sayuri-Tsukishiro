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
    def test_health_static_index_and_favicon(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(base + "/api/health", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["status"], "готово")
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
        handler._headers = lambda status, content_type, length: None
        self.assertFalse(handler._send(b"{}", "application/json", 200))


if __name__ == "__main__":
    unittest.main()
