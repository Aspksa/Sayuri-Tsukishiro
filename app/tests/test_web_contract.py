from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class WebContractTests(unittest.TestCase):
    def test_disk_layout_has_no_second_sidebar_and_has_top_scopes(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('>Диск Sayuri<', html)
        self.assertNotIn('class="disk-rail"', html)
        self.assertNotIn('id="disk-folder-tree"', html)
        self.assertIn('class="disk-scope-tabs"', html)
        self.assertIn('data-disk-scope="favorites"', html)
        self.assertIn('data-disk-scope="recent"', html)
        self.assertIn('id="disk-trash-target"', html)
        self.assertIn('data-view-mode="tiles"', html)
        self.assertIn('data-view-mode="list"', html)
        self.assertIn('id="disk-undo-toast"', html)
        self.assertIn('class="move-dialog move-dialog-wide"', html)

    def test_frontend_supports_real_drag_drop_mass_move_and_undo(self):
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("addEventListener('dragstart'", script)
        self.assertIn("attachFolderDropTarget", script)
        self.assertIn("diskDragItems", script)
        self.assertIn("selectedDiskItems()", script)
        self.assertIn("/api/disk/undo-move", script)
        self.assertIn("trashByDrag", script)
        self.assertIn("window.setTimeout(() =>", script)
        self.assertIn("900", script)
        self.assertNotIn("loadFolderTree()", script)

    def test_document_viewer_order_is_preview_dna_properties(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="viewer-tab-preview"', html)
        self.assertIn('id="viewer-tab-dna"', html)
        self.assertIn('id="viewer-tab-properties"', html)
        self.assertLess(html.index('data-viewer-tab="preview"'), html.index('data-viewer-tab="dna"'))
        self.assertLess(html.index('data-viewer-tab="dna"'), html.index('data-viewer-tab="properties"'))
        self.assertIn('id="dna-coverage"', html)
        self.assertIn('id="dna-molecules"', html)
        self.assertIn('id="dna-checks"', html)
        self.assertIn('id="dna-reanalyze"', html)

    def test_frontend_uses_document_dna_api(self):
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("/dna", script)
        self.assertIn("/dna/analyze", script)
        self.assertIn("renderDocumentDna", script)
        self.assertIn("loadViewerDna", script)
        self.assertIn("ДНК документа", script)

    def test_css_has_tiles_dna_and_low_noise_details(self):
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("#view-disk", css)
        self.assertIn("max-width: 1380px", css)
        self.assertIn(".disk-list.tiles", css)
        self.assertIn(".disk-list.list", css)
        self.assertIn(".disk-drop-target-active", css)
        self.assertIn(".move-dialog-wide", css)
        self.assertIn(".dna-shell", css)
        self.assertIn(".dna-section", css)
        self.assertIn(".dna-pipeline", css)
        self.assertIn(".dna-metrics", css)


if __name__ == "__main__":
    unittest.main()
