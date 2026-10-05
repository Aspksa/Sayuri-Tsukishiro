from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sqlite3
import zipfile
import tempfile
import unittest

from disk import DiskService
from disk.dna import DocumentDNAAnalyzer


class DiskServiceTests(unittest.TestCase):
    def make_service(self, root: Path) -> DiskService:
        service = DiskService(root / "sayuri.db", root / "disk")
        service.initialize()
        return service

    def test_professional_file_manager_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.make_service(root)

            projects = service.create_folder("Проекты")
            reports = service.create_folder("Отчёты", projects["id"])

            payload = b"sayuri professional disk"
            first = service.store_stream(
                name="отчёт.txt",
                content_type="text/plain",
                size_bytes=len(payload),
                stream=BytesIO(payload),
                folder_id=reports["id"],
            )
            duplicate = service.store_stream(
                name="копия.txt",
                content_type="text/plain",
                size_bytes=len(payload),
                stream=BytesIO(payload),
                folder_id=reports["id"],
            )
            self.assertEqual(duplicate["duplicate_of"], first["id"])

            folder_props = service.properties("folder", projects["id"])
            self.assertEqual(folder_props["size_bytes"], len(payload) * 2)
            self.assertEqual(folder_props["direct_folders"], 1)

            listing = service.list_entries(projects["id"])
            reports_card = listing["folders"][0]
            self.assertEqual(reports_card["file_count"], 2)
            self.assertEqual(reports_card["size_bytes"], len(payload) * 2)

            service.set_favorite([{"kind": "file", "id": first["id"]}], True)
            favorites = service.list_entries(scope="favorites")
            self.assertEqual([item["id"] for item in favorites["files"]], [first["id"]])

            service.rename("file", first["id"], "итог.txt")
            move_result = service.move([{"kind": "file", "id": first["id"]}], None)
            self.assertEqual(move_result["count"], 1)
            self.assertEqual(move_result["destination_name"], "Диск Sayuri")
            self.assertEqual(move_result["moves"][0]["from_id"], reports["id"])

            moved = service.properties("file", first["id"])
            self.assertEqual(moved["name"], "итог.txt")
            self.assertIsNone(moved["folder_id"])

            service.undo_move(move_result["moves"])
            restored_move = service.properties("file", first["id"])
            self.assertEqual(restored_move["folder_id"], reports["id"])

            service.move([{"kind": "file", "id": first["id"]}], None)
            moved = service.properties("file", first["id"])
            self.assertGreaterEqual(moved["duplicate_count"], 1)

            with self.assertRaises(FileExistsError):
                service.store_stream(
                    name="ИТОГ.TXT",
                    content_type="text/plain",
                    size_bytes=3,
                    stream=BytesIO(b"new"),
                    folder_id=None,
                )

            service.trash([{"kind": "folder", "id": projects["id"]}])
            trash = service.list_entries(scope="trash")
            self.assertEqual([item["id"] for item in trash["folders"]], [projects["id"]])
            self.assertEqual(trash["files"], [])

            service.restore([{"kind": "folder", "id": projects["id"]}])
            restored = service.get_file(duplicate["id"])
            self.assertEqual(restored["folder_id"], reports["id"])

            service.trash([{"kind": "file", "id": first["id"]}])
            trashed_file = service.get_file(first["id"], allow_trashed=True)
            object_path = trashed_file["path"]
            self.assertTrue(object_path.exists())
            service.delete_permanently([{"kind": "file", "id": first["id"]}])
            self.assertFalse(object_path.exists())

            actions = service.recent_actions(100)
            names = {action["action"] for action in actions}
            self.assertTrue(
                {"uploaded", "renamed", "moved", "move_undone", "favorite_on", "trashed", "restored", "deleted"}
                <= names
            )

    def test_folder_move_cycle_and_unicode_name_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.make_service(root)
            parent = service.create_folder("Документы")
            child = service.create_folder("Внутри", parent["id"])

            with self.assertRaises(FileExistsError):
                service.create_folder("документы")

            with self.assertRaises(ValueError):
                service.move(
                    [{"kind": "folder", "id": parent["id"]}],
                    child["id"],
                )

    def test_invalid_names_and_early_stream_end_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.make_service(root)

            with self.assertRaises(ValueError):
                service.create_folder("../опасно")

            with self.assertRaises(ValueError):
                service.store_stream(
                    name="broken.bin",
                    content_type="application/octet-stream",
                    size_bytes=10,
                    stream=BytesIO(b"123"),
                )

    def test_schema_one_database_migrates_to_disk_02(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "sayuri.db"
            storage = root / "disk"
            (storage / "objects").mkdir(parents=True)

            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE disk_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                db.execute(
                    """
                    CREATE TABLE disk_folders (
                        id TEXT PRIMARY KEY,
                        parent_id TEXT,
                        name TEXT NOT NULL,
                        name_key TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                db.execute(
                    """
                    CREATE TABLE disk_files (
                        id TEXT PRIMARY KEY,
                        folder_id TEXT,
                        name TEXT NOT NULL,
                        stored_name TEXT NOT NULL UNIQUE,
                        content_type TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        sha256 TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                db.execute("INSERT INTO disk_meta(key, value) VALUES('schema_version', '1')")
                db.execute(
                    "INSERT INTO disk_folders(id, parent_id, name, name_key, created_at) VALUES('f1', NULL, 'Старое', 'старое', '2026-10-01T00:00:00+00:00')"
                )
                db.execute(
                    """
                    INSERT INTO disk_files(
                        id, folder_id, name, stored_name, content_type, size_bytes, sha256, created_at
                    ) VALUES('x1', 'f1', 'старый.txt', 'x1', 'text/plain', 3, ?, '2026-10-01T00:00:00+00:00')
                    """,
                    ("a" * 64,),
                )
            (storage / "objects" / "x1").write_bytes(b"old")

            service = DiskService(database, storage)
            service.initialize()
            listing = service.list_entries("f1")
            self.assertEqual(listing["files"][0]["name"], "старый.txt")
            self.assertFalse(listing["files"][0]["favorite"])
            self.assertEqual(service.health()["schema_version"], 4)

    def test_office_and_text_previews(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.make_service(root)

            text_item = service.store_stream(
                name="заметка.txt",
                content_type="text/plain",
                size_bytes=len("Привет, Sayuri".encode("utf-8")),
                stream=BytesIO("Привет, Sayuri".encode("utf-8")),
            )
            text_preview = service.preview(text_item["id"])
            self.assertEqual(text_preview["mode"], "text")
            self.assertIn("Привет", text_preview["text"])

            def make_zip(files: dict[str, str]) -> bytes:
                buffer = BytesIO()
                with zipfile.ZipFile(buffer, "w") as archive:
                    for name, body in files.items():
                        archive.writestr(name, body)
                return buffer.getvalue()

            docx = make_zip({
                "word/document.xml":
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    '<w:body><w:p><w:r><w:t>Документ Sayuri</w:t></w:r></w:p></w:body></w:document>'
            })
            docx_item = service.store_stream(
                name="пример.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                size_bytes=len(docx),
                stream=BytesIO(docx),
            )
            docx_preview = service.preview(docx_item["id"])
            self.assertEqual(docx_preview["mode"], "document")
            self.assertIn("Документ Sayuri", docx_preview["text"])

            pptx = make_zip({
                "ppt/slides/slide1.xml":
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                    '<p:cSld><a:t>Слайд Sayuri</a:t></p:cSld></p:sld>'
            })
            pptx_item = service.store_stream(
                name="пример.pptx",
                content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                size_bytes=len(pptx),
                stream=BytesIO(pptx),
            )
            pptx_preview = service.preview(pptx_item["id"])
            self.assertEqual(pptx_preview["mode"], "presentation")
            self.assertIn("Слайд Sayuri", pptx_preview["text"])

            xlsx = make_zip({
                "xl/sharedStrings.xml":
                    '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    '<si><t>Ячейка Sayuri</t></si></sst>',
                "xl/worksheets/sheet1.xml":
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>'
            })
            xlsx_item = service.store_stream(
                name="пример.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                size_bytes=len(xlsx),
                stream=BytesIO(xlsx),
            )
            xlsx_preview = service.preview(xlsx_item["id"])
            self.assertEqual(xlsx_preview["mode"], "table")
            self.assertEqual(xlsx_preview["rows"][0][0], "Ячейка Sayuri")


    def test_document_dna_extracts_molecules_sources_integrity_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.make_service(root)

            text = (
                "СЛУЖЕБНАЯ ЗАПИСКА\n"
                "№ 17-26\n"
                "Дата: 05.10.2026\n"
                "ИНН 1234567890\n"
                "VIN XTA210930Y1234567\n"
                "Автомобиль А123ВС25\n"
                "Сумма 125 000 руб.\n"
                "Работа в выходной день.\n"
            )
            payload = text.encode("utf-8")
            item = service.store_stream(
                name="служебная записка.txt",
                content_type="text/plain",
                size_bytes=len(payload),
                stream=BytesIO(payload),
            )

            dna = service.document_dna(item["id"])
            self.assertEqual(dna["classification"]["document_type"], "Служебная записка")
            self.assertTrue(dna["integrity"]["matches"])
            self.assertGreaterEqual(dna["coverage_percent"], 85)
            self.assertFalse(dna["method"]["external_ai_used"])

            types = {fact["type"] for fact in dna["molecules"]["facts"]}
            self.assertTrue({"date", "inn", "vin", "vehicle_plate", "amount", "document_number"} <= types)
            date_fact = next(fact for fact in dna["molecules"]["facts"] if fact["type"] == "date")
            self.assertEqual(date_fact["source"]["line"], 3)
            self.assertIn("05.10.2026", date_fact["source"]["excerpt"])

            cached = service.document_dna(item["id"])
            self.assertTrue(cached["cached"])
            self.assertEqual(cached["analyzed_at"], dna["analyzed_at"])

            forced = service.document_dna(item["id"], force=True)
            self.assertFalse(forced["cached"])
            self.assertEqual(forced["molecules"]["total"], dna["molecules"]["total"])
            self.assertEqual(service.health()["dna_analyzer_version"], "0.1.0")


    def test_dna_04_normalization_profile_fingerprint_graph_and_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.make_service(root)
            text = (
                "СЛУЖЕБНАЯ ЗАПИСКА\n"
                "№ 17-26\n"
                "Дата: 05.10.2026\n"
                "ООО «Ромашка» ИНН 1234567890\n"
                "VIN XTA210930Y1234567\n"
                "Автомобиль А123ВС25\n"
                "Итого 125 000 руб.\n"
                "Просим согласовать работу в выходной день до 06.10.2026.\n"
            )
            payload = text.encode("utf-8")
            item = service.store_stream(
                name="служебная записка.txt",
                content_type="text/plain",
                size_bytes=len(payload),
                stream=BytesIO(payload),
            )

            dna = service.document_dna(item["id"])
            self.assertEqual(dna["analyzer_version"], "0.4.0")
            self.assertEqual(dna["schema_version"], 2)
            self.assertEqual(dna["classification"]["document_type"], "Служебная записка")
            self.assertEqual(dna["profile"]["missing_required"], [])
            self.assertTrue(dna["fingerprint"]["semantic_sha256"])
            self.assertTrue(dna["graph_ready"]["ready_for_merge"])
            self.assertGreater(len(dna["graph_ready"]["edges"]), 0)

            date_fact = next(
                fact for fact in dna["molecules"]["facts"]
                if fact["type"] == "date" and fact["role"] == "document_date"
            )
            self.assertEqual(date_fact["normalized"]["canonical"], "2026-10-05")
            self.assertIn(date_fact["quality_gate"], {"accepted", "review"})
            self.assertIn("confidence_breakdown", date_fact)
            self.assertIn("evidence_hash", date_fact["source"])

            amount_fact = next(fact for fact in dna["molecules"]["facts"] if fact["type"] == "amount")
            self.assertEqual(amount_fact["normalized"]["canonical"], "125000.00 RUB")

            plate_fact = next(fact for fact in dna["molecules"]["facts"] if fact["type"] == "vehicle_plate")
            self.assertEqual(plate_fact["normalized"]["canonical"], "А123ВС25")

            action_fact = next(fact for fact in dna["molecules"]["facts"] if fact["type"] == "action")
            self.assertEqual(action_fact["role"], "request")

            first_fact_id = date_fact["id"]
            forced = service.document_dna(item["id"], force=True)
            forced_date = next(
                fact for fact in forced["molecules"]["facts"]
                if fact["type"] == "date" and fact["role"] == "document_date"
            )
            self.assertEqual(forced_date["id"], first_fact_id)
            self.assertEqual(forced["history"]["version"], 2)
            self.assertEqual(len(service.dna_history(item["id"])), 2)

            service.record_dna_feedback(
                item["id"],
                fact_id=amount_fact["id"],
                action="correct",
                corrected_value="130 000 руб.",
                note="Проверено пользователем",
            )
            corrected = service.document_dna(item["id"])
            corrected_amount = next(
                fact for fact in corrected["molecules"]["facts"]
                if fact["id"] == amount_fact["id"]
            )
            self.assertEqual(corrected_amount["normalized"]["canonical"], "130000.00 RUB")
            self.assertEqual(corrected_amount["status"], "corrected_by_user")
            self.assertEqual(corrected["feedback"]["applied"], 1)

    def test_dna_metadata_only_change_reuses_content_without_new_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.make_service(root)
            payload = "Договор № 10 от 05.10.2026".encode("utf-8")
            item = service.store_stream(
                name="договор.txt",
                content_type="text/plain",
                size_bytes=len(payload),
                stream=BytesIO(payload),
            )
            first = service.document_dna(item["id"])
            self.assertEqual(first["history"]["version"], 1)

            service.rename("file", item["id"], "договор длинное новое имя.txt")
            reused = service.document_dna(item["id"])
            self.assertTrue(reused["cached"])
            self.assertTrue(reused["content_reused"])
            self.assertEqual(reused["identity"]["name"], "договор длинное новое имя.txt")
            self.assertEqual(len(service.dna_history(item["id"])), 1)

    def test_dna_cross_document_contradiction_and_near_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.make_service(root)

            first_text = (
                "ДОГОВОР № 77\n"
                "Дата: 05.10.2026\n"
                "ООО Ромашка ИНН 1234567890\n"
                "Итого 100 000 руб.\n"
                "Поставка оборудования для автомобиля А123ВС25.\n"
            )
            second_text = (
                "ДОГОВОР № 77\n"
                "Дата: 05.10.2026\n"
                "ООО Ромашка ИНН 1234567890\n"
                "Итого 120 000 руб.\n"
                "Поставка оборудования для автомобиля А123ВС25.\n"
            )
            one = service.store_stream(
                name="договор 77 первая редакция.txt",
                content_type="text/plain",
                size_bytes=len(first_text.encode("utf-8")),
                stream=BytesIO(first_text.encode("utf-8")),
            )
            two = service.store_stream(
                name="договор 77 вторая редакция.txt",
                content_type="text/plain",
                size_bytes=len(second_text.encode("utf-8")),
                stream=BytesIO(second_text.encode("utf-8")),
            )

            service.document_dna(one["id"])
            dna_two = service.document_dna(two["id"])
            self.assertTrue(dna_two["cross_document"]["related"])
            amount_conflicts = [
                item for item in dna_two["cross_document"]["contradictions"]
                if item["field"] == "amount"
            ]
            self.assertTrue(amount_conflicts)
            self.assertFalse(dna_two["quality_gate"]["memory_ready"])
            self.assertIn("cross_document_contradiction", dna_two["quality_gate"]["reasons"])

            refreshed_one = service.document_dna(one["id"])
            self.assertTrue(refreshed_one["cross_document"]["related"])

    def test_dna_table_arithmetic_engine_detects_wrong_total(self):
        analyzer = DocumentDNAAnalyzer()
        dna = analyzer.analyze(
            item={
                "id": "table-1",
                "name": "счёт.xlsx",
                "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "size_bytes": 100,
                "sha256": "a" * 64,
                "category": "tables",
                "created_at": "2026-10-05T00:00:00+00:00",
                "updated_at": "2026-10-05T00:00:00+00:00",
                "duplicate_count": 0,
            },
            properties={"path": []},
            preview={
                "mode": "table",
                "rows": [
                    ["Товар", "Количество", "Цена", "Сумма"],
                    ["Деталь", "2", "100", "250"],
                ],
                "truncated": False,
            },
            integrity={
                "expected_sha256": "a" * 64,
                "actual_sha256": "a" * 64,
                "matches": True,
            },
        )
        self.assertEqual(len(dna["arithmetic"]), 1)
        self.assertFalse(dna["arithmetic"][0]["matches"])
        self.assertTrue(any(risk["code"] == "arithmetic" for risk in dna["risks"]))
        self.assertFalse(dna["quality_gate"]["memory_ready"])


if __name__ == "__main__":
    unittest.main()
