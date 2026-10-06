from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from disk import DiskService
from disk.dna_spatial import SPATIAL_ENGINE_VERSION, SpatialDNAEngine


class FakeTextPage:
    def count_chars(self):
        return 0

    def get_text_range(self, index=0, count=-1):
        return ""

    def get_charbox(self, index):
        raise IndexError(index)

    def close(self):
        pass


class FakeObject:
    type = "image"

    def get_bounds(self):
        # PDF coordinates: left, bottom, right, top.
        return 390, 200, 470, 280


class FakeImage:
    size = (1833, 2444)

    def save(self, path, format=None):
        Path(path).write_bytes(b"fake-png")

    def close(self):
        pass


class FakeBitmap:
    def to_pil(self):
        return FakeImage()

    def close(self):
        pass


class FakePage:
    def get_size(self):
        return 600, 800

    def get_rotation(self):
        return 0

    def get_textpage(self):
        return FakeTextPage()

    def get_objects(self):
        return [FakeObject()]

    def render(self, scale=1, rotation=0):
        return FakeBitmap()


class FakePdfDocument:
    def __init__(self, path):
        self.path = path

    def __len__(self):
        return 1

    def __getitem__(self, index):
        if index != 0:
            raise IndexError(index)
        return FakePage()

    def close(self):
        pass


class FakePdfium:
    PdfDocument = FakePdfDocument


class FakeImageModule:
    pass


def fake_ocr_runner(image, tessdata, page_number):
    # Tesseract TSV, with several aligned rows and a signature marker.
    return (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t120\t180\t360\t50\t96\tСЛУЖЕБНАЯ\n"
        "5\t1\t1\t1\t1\t2\t500\t180\t250\t50\t96\tЗАПИСКА\n"
        "5\t1\t1\t1\t1\t3\t770\t180\t70\t50\t95\t№\n"
        "5\t1\t1\t1\t1\t4\t860\t180\t100\t50\t95\t17\n"
        "5\t1\t2\t1\t1\t1\t120\t420\t180\t45\t94\tДата:\n"
        "5\t1\t2\t1\t1\t2\t480\t420\t250\t45\t94\t05.10.2026\n"
        "5\t1\t2\t1\t2\t1\t120\t500\t220\t45\t93\tСумма\n"
        "5\t1\t2\t1\t2\t2\t480\t500\t220\t45\t93\t25000\n"
        "5\t1\t2\t1\t2\t3\t720\t500\t120\t45\t93\tруб.\n"
        "5\t1\t2\t1\t3\t1\t120\t580\t220\t45\t92\tТовар\n"
        "5\t1\t2\t1\t3\t2\t480\t580\t220\t45\t92\tДеталь\n"
        "5\t1\t3\t1\t1\t1\t120\t1900\t260\t45\t90\tПодпись\n"
        "5\t1\t3\t1\t1\t2\t400\t1900\t260\t45\t90\tдиректора\n"
        "5\t1\t3\t1\t1\t3\t680\t1900\t120\t45\t90\tМ.П.\n"
    )


class SpatialDNAEngineTests(unittest.TestCase):
    def make_tessdata(self, root: Path) -> Path:
        tessdata = root / "tessdata"
        tessdata.mkdir()
        (tessdata / "rus.traineddata").write_bytes(b"rus")
        (tessdata / "eng.traineddata").write_bytes(b"eng")
        return tessdata

    def make_engine(self, root: Path) -> SpatialDNAEngine:
        return SpatialDNAEngine(
            tessdata_path=self.make_tessdata(root),
            pdfium_module=FakePdfium(),
            image_module=FakeImageModule(),
            ocr_runner=fake_ocr_runner,
        )

    def test_ocr_coordinates_table_candidates_and_visual_hypotheses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "scan.pdf"
            path.write_bytes(b"%PDF-fake")
            engine = self.make_engine(root)

            spatial = engine.extract(
                path,
                content_type="application/pdf",
                suffix=".pdf",
            )

            self.assertEqual(spatial["engine_version"], SPATIAL_ENGINE_VERSION)
            self.assertEqual(spatial["status"], "ready")
            self.assertEqual(spatial["page_count"], 1)
            self.assertEqual(spatial["ocr"]["used_pages"], 1)
            self.assertGreaterEqual(spatial["tables"]["candidate_count"], 1)
            self.assertGreaterEqual(spatial["visual_candidates"]["count"], 2)
            self.assertIn("СЛУЖЕБНАЯ ЗАПИСКА", spatial["combined_text"])
            self.assertTrue(spatial["line_map"])
            first = spatial["line_map"][0]
            self.assertEqual(first["page"], 1)
            self.assertEqual(first["extraction_method"], "ocr")
            self.assertEqual(len(first["bbox"]["normalized"]), 4)
            self.assertGreater(spatial["quality"]["score"], 0)
            self.assertGreater(
                spatial["pages"][0]["quality"]["average_ocr_confidence"],
                80,
            )

            dna = {
                "molecules": {
                    "facts": [
                        {
                            "id": "fact-1",
                            "type": "date",
                            "source": {"line": 2},
                        }
                    ]
                },
                "document_quality": {},
                "evidence_chains": [],
                "ai_context": {"facts": [{"fact_id": "fact-1", "source": {}}]},
            }
            engine.attach_fact_locations(dna, spatial)
            locator = dna["molecules"]["facts"][0]["source"]["locator"]
            self.assertEqual(locator["page"], 1)
            self.assertEqual(locator["coordinate_status"], "exact_from_document_engine")
            self.assertEqual(dna["spatial_evidence"]["coverage_percent"], 100.0)
            self.assertEqual(
                dna["ai_context"]["facts"][0]["source"]["locator"]["page"],
                1,
            )

    def test_analysis_preview_uses_spatial_text_without_mutating_original(self):
        original = {"mode": "pdf", "url": "/view"}
        spatial = {
            "combined_text": "Договор № 12\nДата: 05.10.2026",
            "truncated": False,
        }
        preview = SpatialDNAEngine.analysis_preview(original, spatial)
        self.assertEqual(preview["mode"], "spatial-text")
        self.assertIn("Договор", preview["text"])
        self.assertEqual(original["mode"], "pdf")

    def test_non_applicable_format_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "note.txt"
            path.write_text("текст", encoding="utf-8")
            engine = self.make_engine(root)
            spatial = engine.extract(
                path,
                content_type="text/plain",
                suffix=".txt",
            )
            self.assertEqual(spatial["status"], "not_applicable")
            self.assertEqual(spatial["reason"], "format_without_page_geometry")


class SpatialDNAServiceTests(unittest.TestCase):
    def test_scanned_pdf_flows_from_ocr_into_dna_facts_and_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = DiskService(root / "sayuri.db", root / "disk")
            service.initialize()
            tessdata = root / "tessdata"
            tessdata.mkdir()
            (tessdata / "rus.traineddata").write_bytes(b"rus")
            (tessdata / "eng.traineddata").write_bytes(b"eng")
            service.spatial_dna = SpatialDNAEngine(
                tessdata_path=tessdata,
                pdfium_module=FakePdfium(),
                image_module=FakeImageModule(),
                ocr_runner=fake_ocr_runner,
            )
            self.assertEqual(service.spatial_status()["status"], "готово")

            payload = b"%PDF-fake-scan"
            item = service.store_stream(
                name="служебная скан.pdf",
                content_type="application/pdf",
                size_bytes=len(payload),
                stream=BytesIO(payload),
            )

            dna = service.document_dna(item["id"])
            self.assertEqual(dna["spatial"]["engine_version"], "0.8.0")
            self.assertEqual(dna["spatial"]["ocr"]["used_pages"], 1)
            self.assertEqual(dna["classification"]["document_type"], "Служебная записка")

            types = {fact["type"] for fact in dna["molecules"]["facts"]}
            self.assertIn("date", types)
            self.assertIn("amount", types)
            self.assertIn("document_number", types)

            amount = next(fact for fact in dna["molecules"]["facts"] if fact["type"] == "amount")
            self.assertEqual(amount["source"]["locator"]["page"], 1)
            self.assertEqual(
                amount["source"]["locator"]["coordinate_status"],
                "exact_from_document_engine",
            )
            self.assertGreater(dna["spatial_evidence"]["coverage_percent"], 0)

            evidence = service.search_cached_evidence(item["id"], "сумма", limit=3)
            self.assertTrue(evidence["available"])
            self.assertEqual(evidence["items"][0]["citation_id"], "D1")
            self.assertEqual(evidence["items"][0]["fact_id"], amount["id"])
            self.assertEqual(
                evidence["items"][0]["locator"]["coordinate_status"],
                "exact_from_document_engine",
            )

            captured = {}
            def fake_focus(path, **kwargs):
                captured["path"] = path
                captured.update(kwargs)
                return {
                    "content_type": "image/png",
                    "body": b"png-evidence",
                    "page": kwargs["page_number"],
                    "width": 900,
                    "height": 1200,
                    "bbox": {"normalized": kwargs["bbox"]["normalized"]},
                }

            service.spatial_dna.render_evidence_focus = fake_focus
            focused = service.render_evidence_focus(item["id"], amount["id"])
            self.assertEqual(focused["body"], b"png-evidence")
            self.assertEqual(focused["page"], 1)
            self.assertEqual(focused["fact_id"], amount["id"])
            self.assertEqual(captured["page_number"], 1)
            self.assertEqual(
                captured["bbox"]["normalized"],
                amount["source"]["locator"]["bbox"]["normalized"],
            )
            with self.assertRaises(TypeError):
                service.render_evidence_focus(
                    item["id"],
                    amount["id"],
                    bbox={"normalized": [0, 0, 1, 1]},
                )

            cached_spatial = service.spatial_document(item["id"])
            self.assertTrue(cached_spatial["cached"])
            self.assertEqual(cached_spatial["spatial_sha256"], dna["spatial"]["spatial_sha256"])

            deep_ocr = service.document_dna(
                item["id"],
                force=True,
                bypass_cooldown=True,
                force_ocr=True,
            )
            self.assertEqual(deep_ocr["version_delta"]["reason"], "forced_ocr")
            self.assertEqual(deep_ocr["spatial"]["ocr"]["used_pages"], 1)


if __name__ == "__main__":
    unittest.main()
