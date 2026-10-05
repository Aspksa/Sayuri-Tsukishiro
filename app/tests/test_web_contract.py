from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class WebContractTests(unittest.TestCase):
    def test_disk_02_professional_layout_exists(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-view="disk"', html)
        self.assertIn('>Диск Sayuri<', html)
        self.assertIn('data-disk-scope="all"', html)
        self.assertIn('data-disk-scope="favorites"', html)
        self.assertIn('data-disk-scope="recent"', html)
        self.assertIn('data-disk-scope="trash"', html)
        self.assertIn('id="disk-bulk-toolbar"', html)
        self.assertIn('id="upload-queue"', html)
        self.assertIn('id="disk-properties"', html)
        self.assertIn('id="move-modal"', html)

    def test_frontend_uses_disk_02_api_and_upload_progress(self):
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/disk/rename", script)
        self.assertIn("/api/disk/move", script)
        self.assertIn("/api/disk/favorite", script)
        self.assertIn("/api/disk/trash", script)
        self.assertIn("/api/disk/restore", script)
        self.assertIn("/api/disk/delete-permanent", script)
        self.assertIn("/api/disk/actions", script)
        self.assertIn("xhr.upload.addEventListener('progress'", script)


if __name__ == "__main__":
    unittest.main()
