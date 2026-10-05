from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib
import tempfile
import unittest

from disk import DiskService


class DiskServiceTests(unittest.TestCase):
    def test_folder_upload_list_download_metadata_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = DiskService(root / "sayuri.db", root / "disk")
            service.initialize()

            folder = service.create_folder("Документы")
            payload = b"hello sayuri"
            item = service.store_stream(
                name="example.txt",
                content_type="text/plain",
                size_bytes=len(payload),
                stream=BytesIO(payload),
                folder_id=folder["id"],
            )

            listing = service.list_entries(folder["id"])
            self.assertEqual(listing["folders"], [])
            self.assertEqual(len(listing["files"]), 1)
            self.assertEqual(listing["files"][0]["name"], "example.txt")
            self.assertEqual(
                listing["files"][0]["sha256"],
                hashlib.sha256(payload).hexdigest(),
            )

            stored = service.get_file(item["id"])
            self.assertEqual(stored["path"].read_bytes(), payload)
            self.assertEqual(stored["content_type"], "text/plain")

            health = service.health()
            self.assertEqual(health["status"], "готово")
            self.assertEqual(health["files"], 1)
            self.assertEqual(health["folders"], 1)

            service.delete_file(item["id"])
            service.delete_folder(folder["id"])
            health = service.health()
            self.assertEqual(health["files"], 0)
            self.assertEqual(health["folders"], 0)

    def test_folder_names_are_unicode_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = DiskService(root / "sayuri.db", root / "disk")
            service.initialize()
            service.create_folder("Документы")
            with self.assertRaises(FileExistsError):
                service.create_folder("документы")

    def test_invalid_names_and_early_stream_end_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = DiskService(root / "sayuri.db", root / "disk")
            service.initialize()

            with self.assertRaises(ValueError):
                service.create_folder("../опасно")

            with self.assertRaises(ValueError):
                service.store_stream(
                    name="broken.bin",
                    content_type="application/octet-stream",
                    size_bytes=10,
                    stream=BytesIO(b"123"),
                )


if __name__ == "__main__":
    unittest.main()
