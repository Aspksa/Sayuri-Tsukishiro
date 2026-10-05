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

        settings = Settings(root=root, host="127.0.0.1", preferred_port=18100, port_scan_limit=100)
        core = SayuriCore(settings)
        core.initialize()
        self.server = create_server(core, configure_logging(settings.logs_dir))
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

    def test_full_disk_02_api_flow(self):
        folder = self.post_json("/api/disk/folders", {"name": "Работа"})["folder"]
        archive = self.post_json("/api/disk/folders", {"name": "Архив"})["folder"]

        payload = b"disk api 0.2"
        upload_request = urllib.request.Request(
            self.base + f"/api/disk/upload?folder_id={folder['id']}",
            data=payload,
            headers={
                "Content-Type": "text/plain",
                "X-Sayuri-Filename": quote("проверка.txt"),
            },
            method="POST",
        )
        with urllib.request.urlopen(upload_request, timeout=3) as response:
            uploaded = json.loads(response.read().decode("utf-8"))["file"]

        move_result = self.post_json(
            "/api/disk/move",
            {"items": [{"kind": "file", "id": uploaded["id"]}], "destination_id": archive["id"]},
        )
        self.assertEqual(move_result["count"], 1)
        self.assertEqual(move_result["destination_name"], "Архив")
        self.assertEqual(move_result["moves"][0]["from_id"], folder["id"])

        self.post_json("/api/disk/undo-move", {"moves": move_result["moves"]})
        with urllib.request.urlopen(
            self.base + f"/api/disk/items/file/{uploaded['id']}",
            timeout=3,
        ) as response:
            moved_back = json.loads(response.read().decode("utf-8"))
            self.assertEqual(moved_back["folder_id"], folder["id"])

        self.post_json(
            "/api/disk/favorite",
            {"items": [{"kind": "file", "id": uploaded["id"]}], "favorite": True},
        )
        self.post_json(
            "/api/disk/rename",
            {"kind": "file", "id": uploaded["id"], "name": "готово.txt"},
        )

        with urllib.request.urlopen(
            self.base + f"/api/disk/items/file/{uploaded['id']}",
            timeout=3,
        ) as response:
            properties = json.loads(response.read().decode("utf-8"))
            self.assertEqual(properties["name"], "готово.txt")
            self.assertTrue(properties["favorite"])
            self.assertEqual(properties["size_bytes"], len(payload))

        with urllib.request.urlopen(self.base + "/api/disk?scope=favorites", timeout=3) as response:
            favorites = json.loads(response.read().decode("utf-8"))
            self.assertEqual(favorites["files"][0]["id"], uploaded["id"])

        self.post_json("/api/disk/trash", {"items": [{"kind": "file", "id": uploaded["id"]}]})
        with urllib.request.urlopen(self.base + "/api/disk?scope=trash", timeout=3) as response:
            trash = json.loads(response.read().decode("utf-8"))
            self.assertEqual(trash["files"][0]["id"], uploaded["id"])

        self.post_json("/api/disk/restore", {"items": [{"kind": "file", "id": uploaded["id"]}]})

        with urllib.request.urlopen(
            self.base + f"/api/disk/files/{uploaded['id']}/preview",
            timeout=3,
        ) as response:
            preview = json.loads(response.read().decode("utf-8"))
            self.assertEqual(preview["mode"], "text")
            self.assertIn("disk api 0.2", preview["text"])

        with urllib.request.urlopen(
            self.base + f"/api/disk/files/{uploaded['id']}/dna",
            timeout=3,
        ) as response:
            dna = json.loads(response.read().decode("utf-8"))
            self.assertIn("coverage_percent", dna)
            self.assertTrue(dna["integrity"]["matches"])
            self.assertFalse(dna["method"]["external_ai_used"])

        reanalyze_request = urllib.request.Request(
            self.base + f"/api/disk/files/{uploaded['id']}/dna/analyze",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(reanalyze_request, timeout=3) as response:
            dna = json.loads(response.read().decode("utf-8"))
            self.assertFalse(dna["cached"])

        with urllib.request.urlopen(
            self.base + f"/api/disk/files/{uploaded['id']}/view",
            timeout=3,
        ) as response:
            self.assertEqual(response.read(), payload)
            self.assertIn("inline", response.headers["Content-Disposition"])

        with urllib.request.urlopen(
            self.base + f"/api/disk/files/{uploaded['id']}/download",
            timeout=3,
        ) as response:
            self.assertEqual(response.read(), payload)


if __name__ == "__main__":
    unittest.main()
