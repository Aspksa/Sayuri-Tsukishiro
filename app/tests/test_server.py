from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request

from app.config import Settings
from app.core import SayuriCore
from app.logging_setup import configure_logging
from app.server import create_server


class ServerTests(unittest.TestCase):
    def test_health_and_static_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            (root / "MODULES.json").write_text(json.dumps({"schema_version": 1, "modules": []}), encoding="utf-8")
            (root / "web").mkdir()
            (root / "web" / "index.html").write_text("<h1>Sayuri</h1>", encoding="utf-8")
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
                    self.assertEqual(payload["status"], "ready")
                with urllib.request.urlopen(base + "/", timeout=2) as response:
                    self.assertIn("Sayuri", response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
