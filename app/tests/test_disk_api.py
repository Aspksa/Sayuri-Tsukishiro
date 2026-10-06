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
            self.assertTrue(dna["cached"])
            self.assertTrue(dna["reanalysis_deduplicated"])

        deep_reanalyze_request = urllib.request.Request(
            self.base + f"/api/disk/files/{uploaded['id']}/dna/analyze",
            data=json.dumps({"deep": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(deep_reanalyze_request, timeout=3) as response:
            dna = json.loads(response.read().decode("utf-8"))
            self.assertFalse(dna["cached"])
            self.assertFalse(dna["reanalysis_deduplicated"])

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


    def test_dna_history_and_feedback_api(self):
        payload = (
            "СЧЁТ № 9\n"
            "Дата: 05.10.2026\n"
            "Итого 10 000 руб.\n"
        ).encode("utf-8")
        upload_request = urllib.request.Request(
            self.base + "/api/disk/upload",
            data=payload,
            headers={
                "Content-Type": "text/plain",
                "X-Sayuri-Filename": quote("счёт 9.txt"),
            },
            method="POST",
        )
        with urllib.request.urlopen(upload_request, timeout=3) as response:
            uploaded = json.loads(response.read().decode("utf-8"))["file"]

        with urllib.request.urlopen(
            self.base + f"/api/disk/files/{uploaded['id']}/dna",
            timeout=3,
        ) as response:
            dna = json.loads(response.read().decode("utf-8"))
        amount_fact = next(
            fact for fact in dna["molecules"]["facts"] if fact["type"] == "amount"
        )

        feedback = self.post_json(
            f"/api/disk/files/{uploaded['id']}/dna/feedback",
            {
                "fact_id": amount_fact["id"],
                "action": "correct",
                "corrected_value": "12 500 руб.",
                "note": "Проверено вручную",
            },
        )
        self.assertEqual(feedback["status"], "сохранено")

        with urllib.request.urlopen(
            self.base + f"/api/disk/files/{uploaded['id']}/dna",
            timeout=3,
        ) as response:
            corrected = json.loads(response.read().decode("utf-8"))
        corrected_amount = next(
            fact for fact in corrected["molecules"]["facts"]
            if fact["id"] == amount_fact["id"]
        )
        self.assertEqual(corrected_amount["normalized"]["canonical"], "12500.00 RUB")
        self.assertEqual(corrected_amount["status"], "corrected_by_user")

        with urllib.request.urlopen(
            self.base + f"/api/disk/files/{uploaded['id']}/dna/history?limit=10",
            timeout=3,
        ) as response:
            history = json.loads(response.read().decode("utf-8"))["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["version"], 1)


    def test_dna_05_ledger_and_package_api(self):
        folder = self.post_json("/api/disk/folders", {"name": "Комплект ДНК"})["folder"]
        payload = (
            "ДОГОВОР № 501\n"
            "Дата: 05.10.2026\n"
            "ООО Ромашка ИНН 1234567890\n"
            "Итого 50 000 руб.\n"
        ).encode("utf-8")
        upload_request = urllib.request.Request(
            self.base + f"/api/disk/upload?folder_id={folder['id']}",
            data=payload,
            headers={
                "Content-Type": "text/plain",
                "X-Sayuri-Filename": quote("договор 501.txt"),
            },
            method="POST",
        )
        with urllib.request.urlopen(upload_request, timeout=3) as response:
            uploaded = json.loads(response.read().decode("utf-8"))["file"]

        with urllib.request.urlopen(
            self.base + f"/api/disk/files/{uploaded['id']}/dna",
            timeout=3,
        ) as response:
            dna = json.loads(response.read().decode("utf-8"))
        self.assertEqual(dna["analyzer_version"], "0.7.0")
        self.assertEqual(dna["advanced_engine_version"], "0.5.1")
        self.assertIn("document_schema", dna)
        self.assertIn("ai_context", dna)

        with urllib.request.urlopen(
            self.base + f"/api/disk/files/{uploaded['id']}/dna/ledger",
            timeout=3,
        ) as response:
            ledger = json.loads(response.read().decode("utf-8"))
        self.assertTrue(ledger["valid"])
        self.assertGreaterEqual(ledger["total"], 1)

        with urllib.request.urlopen(
            self.base + f"/api/disk/package-dna?folder_id={folder['id']}",
            timeout=3,
        ) as response:
            package = json.loads(response.read().decode("utf-8"))
        self.assertEqual(package["files_total"], 1)
        self.assertEqual(package["analyzed"], 1)
        self.assertEqual(package["pending"], [])
        self.assertEqual(package["documents"][0]["file_id"], uploaded["id"])


    def test_dna_06_evolution_status_reanalysis_plan_and_cooldown_api(self):
        payload = (
            "ДОГОВОР № 906\n"
            "Дата: 05.10.2026\n"
            "ООО Ромашка ИНН 1234567890\n"
            "Итого 90 000 руб.\n"
        ).encode("utf-8")
        upload_request = urllib.request.Request(
            self.base + "/api/disk/upload",
            data=payload,
            headers={
                "Content-Type": "text/plain",
                "X-Sayuri-Filename": quote("договор 906.txt"),
            },
            method="POST",
        )
        with urllib.request.urlopen(upload_request, timeout=3) as response:
            uploaded = json.loads(response.read().decode("utf-8"))["file"]

        with urllib.request.urlopen(
            self.base + f"/api/disk/files/{uploaded['id']}/dna",
            timeout=3,
        ) as response:
            dna = json.loads(response.read().decode("utf-8"))
        self.assertEqual(dna["evolution"]["engine_version"], "0.6.0")
        self.assertIn("self_review", dna["evolution"])
        self.assertIn("adaptive_profile", dna["evolution"])
        self.assertIn("regression_guard", dna["evolution"])
        self.assertIn("active_learning", dna["evolution"])

        with urllib.request.urlopen(
            self.base + "/api/disk/dna/evolution",
            timeout=3,
        ) as response:
            status = json.loads(response.read().decode("utf-8"))
        self.assertEqual(status["engine_version"], "0.6.0")
        self.assertGreaterEqual(status["documents"], 1)

        with urllib.request.urlopen(
            self.base + "/api/disk/dna/reanalysis-plan?limit=20",
            timeout=3,
        ) as response:
            plan = json.loads(response.read().decode("utf-8"))
        self.assertEqual(plan["engine_version"], "0.6.0")
        self.assertEqual(plan["count"], 0)

        ordinary = self.post_json(
            f"/api/disk/files/{uploaded['id']}/dna/analyze",
            {},
        )
        self.assertTrue(ordinary["reanalysis_deduplicated"])

        deep = self.post_json(
            f"/api/disk/files/{uploaded['id']}/dna/analyze",
            {"deep": True},
        )
        self.assertFalse(deep["reanalysis_deduplicated"])
        self.assertEqual(deep["version_delta"]["reason"], "deep_reanalysis")


    def test_dna_07_spatial_status_and_document_api(self):
        payload = "Договор № 707\nДата: 05.10.2026".encode("utf-8")
        upload_request = urllib.request.Request(
            self.base + "/api/disk/upload",
            data=payload,
            headers={
                "Content-Type": "text/plain",
                "X-Sayuri-Filename": quote("договор 707.txt"),
            },
            method="POST",
        )
        with urllib.request.urlopen(upload_request, timeout=3) as response:
            uploaded = json.loads(response.read().decode("utf-8"))["file"]

        with urllib.request.urlopen(
            self.base + f"/api/disk/files/{uploaded['id']}/dna",
            timeout=3,
        ) as response:
            dna = json.loads(response.read().decode("utf-8"))
        self.assertEqual(dna["analyzer_version"], "0.7.0")
        self.assertEqual(dna["spatial"]["engine_version"], "0.8.0")
        self.assertIn(dna["spatial"]["status"], {"not_applicable", "unavailable"})

        with urllib.request.urlopen(
            self.base + "/api/disk/dna/spatial",
            timeout=3,
        ) as response:
            status = json.loads(response.read().decode("utf-8"))
        self.assertEqual(status["engine_version"], "0.8.0")
        self.assertIn("capabilities", status)

        with urllib.request.urlopen(
            self.base + f"/api/disk/files/{uploaded['id']}/dna/spatial",
            timeout=3,
        ) as response:
            spatial = json.loads(response.read().decode("utf-8"))
        self.assertEqual(spatial["engine_version"], "0.7.0")


if __name__ == "__main__":
    unittest.main()
