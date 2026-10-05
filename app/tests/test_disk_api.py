from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import quote
import urllib.request

from app.config import Settings
from app.core import SayuriCore
from app.logging_setup import configure_logging
from app.server import create_server


class DiskApiTests(unittest.TestCase):
    def test_create_upload_list_download_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            (root / "MODULES.json").write_text(
                json.dumps({"schema_version": 1, "modules": []}),
                encoding="utf-8",
            )
            (root / "web").mkdir()
            (root / "web" / "index.html").write_text("<h1>Саюри</h1>", encoding="utf-8")

            settings = Settings(
                root=root,
                host="127.0.0.1",
                preferred_port=18100,
                port_scan_limit=100,
            )
            core = SayuriCore(settings)
            core.initialize()
            server = create_server(core, configure_logging(settings.logs_dir))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                base = f"http://127.0.0.1:{server.server_port}"

                folder_request = urllib.request.Request(
                    base + "/api/disk/folders",
                    data=json.dumps({"name": "Работа"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(folder_request, timeout=3) as response:
                    folder = json.loads(response.read().decode("utf-8"))["folder"]

                payload = b"disk api test"
                upload_request = urllib.request.Request(
                    base + f"/api/disk/upload?folder_id={folder['id']}",
                    data=payload,
                    headers={
                        "Content-Type": "text/plain",
                        "X-Sayuri-Filename": quote("проверка.txt"),
                    },
                    method="POST",
                )
                with urllib.request.urlopen(upload_request, timeout=3) as response:
                    uploaded = json.loads(response.read().decode("utf-8"))["file"]

                with urllib.request.urlopen(
                    base + f"/api/disk?folder_id={folder['id']}",
                    timeout=3,
                ) as response:
                    listing = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(listing["files"][0]["name"], "проверка.txt")

                with urllib.request.urlopen(
                    base + f"/api/disk/files/{uploaded['id']}/download",
                    timeout=3,
                ) as response:
                    self.assertEqual(response.read(), payload)
                    self.assertEqual(
                        response.headers["X-Sayuri-SHA256"],
                        uploaded["sha256"],
                    )

                delete_file = urllib.request.Request(
                    base + f"/api/disk/files/{uploaded['id']}",
                    method="DELETE",
                )
                with urllib.request.urlopen(delete_file, timeout=3) as response:
                    self.assertEqual(
                        json.loads(response.read().decode("utf-8"))["status"],
                        "удалено",
                    )

                delete_folder = urllib.request.Request(
                    base + f"/api/disk/folders/{folder['id']}",
                    method="DELETE",
                )
                with urllib.request.urlopen(delete_folder, timeout=3) as response:
                    self.assertEqual(
                        json.loads(response.read().decode("utf-8"))["status"],
                        "удалено",
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
