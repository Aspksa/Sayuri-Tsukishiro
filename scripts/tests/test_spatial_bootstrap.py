from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "bootstrap_windows.ps1"


class SpatialBootstrapTests(unittest.TestCase):
    def test_spatial_runtime_is_pinned_verified_and_does_not_use_pip(self):
        text = BOOTSTRAP.read_text(encoding="utf-8-sig")
        self.assertIn("$PdfiumVersion = '5.13.0'", text)
        self.assertIn("$PillowVersion = '12.3.0'", text)
        self.assertIn("$TesseractVersion = '5.5.3'", text)

        self.assertIn("pypdfium2-5.13.0-py3-none-win_amd64.whl", text)
        self.assertIn("47dcca2a8d507b5fd24f94c3c9d48fb379430f097bc20f01beff6c963ffbcedb", text)
        self.assertIn("pypdfium2-5.13.0-py3-none-win_arm64.whl", text)
        self.assertIn("554a0b23376460af1410e3c915906895e2dac67a086b9e6ccde0643a795d3b0d", text)

        self.assertIn("pillow-12.3.0-cp314-cp314-win_amd64.whl", text)
        self.assertIn("fdafc9cce40277e0f7a0feabce0ee50dd2fa1800f3b38015e51296b5e814048d", text)
        self.assertIn("pillow-12.3.0-cp314-cp314-win_arm64.whl", text)
        self.assertIn("e91206ee562682b51b98ef4b26a6ef48fd84e15fd4c4bc5ec768eb641d206838", text)

        self.assertIn("tesseract-ocr-w64-setup-5.5.3.20260724.exe", text)
        self.assertIn("bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4", text)
        self.assertIn("eng.traineddata", text)
        self.assertIn("rus.traineddata", text)
        self.assertIn("8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba", text)
        self.assertIn("b617eb6830ffabaaa795dd87ea7fd251adfe9cf0efe05eb9a2e8128b7728d6b6", text)

        self.assertIn("..\\packages", text)
        self.assertIn("$env:SAYURI_TESSERACT = $tesseract", text)
        self.assertIn("$env:TESSDATA_PREFIX = $TessdataRoot", text)
        self.assertIn("$env:SAYURI_TESSDATA = $TessdataRoot", text)
        self.assertNotIn("pip install", text)
        self.assertNotIn("PyMuPDF", text)

    def test_optional_spatial_runtime_does_not_break_main_launch(self):
        text = BOOTSTRAP.read_text(encoding="utf-8-sig")
        self.assertIn("запуск продолжится в ограниченном режиме", text)
        self.assertIn("запуск продолжится без OCR", text)
        self.assertIn("Ensure-SpatialRuntime", text)
        self.assertIn("AutoTesseract = $false", text)


if __name__ == "__main__":
    unittest.main()
