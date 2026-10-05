from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest

from disk import DiskService


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

            service.set_favorite([{"kind": "file", "id": first["id"]}], True)
            favorites = service.list_entries(scope="favorites")
            self.assertEqual([item["id"] for item in favorites["files"]], [first["id"]])

            service.rename("file", first["id"], "итог.txt")
            service.move([{"kind": "file", "id": first["id"]}], None)
            moved = service.properties("file", first["id"])
            self.assertEqual(moved["name"], "итог.txt")
            self.assertEqual(moved["folder_id"], None)
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
            self.assertTrue({"uploaded", "renamed", "moved", "favorite_on", "trashed", "restored", "deleted"} <= names)

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
                db.execute(
                    "INSERT INTO disk_meta(key, value) VALUES('schema_version', '1')"
                )
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
            self.assertEqual(service.health()["schema_version"], 2)


if __name__ == "__main__":
    unittest.main()
