from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class WebContractTests(unittest.TestCase):
    def test_disk_layout_matches_requested_ux(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('>Диск Sayuri<', html)
        self.assertIn('id="disk-drop-zone"', html)
        self.assertIn('id="disk-folder-tree"', html)
        self.assertIn('id="file-viewer-modal"', html)
        self.assertIn('id="viewer-tab-preview"', html)
        self.assertIn('id="viewer-tab-properties"', html)
        self.assertIn('id="disk-context-menu"', html)
        self.assertNotIn('id="disk-actions-list"', html)
        self.assertLess(html.index('id="disk-drop-zone"'), html.index('class="disk-stats"'))

    def test_frontend_supports_context_menu_center_viewer_and_long_name_actions(self):
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("addEventListener('contextmenu'", script)
        self.assertIn("/api/disk/files/", script)
        self.assertIn("/preview", script)
        self.assertIn("openViewer(item.kind, item.id", script)
        self.assertIn("property-name-input", script)
        self.assertIn("loadFolderTree()", script)
        self.assertNotIn("loadDiskActions()", script)

    def test_preview_css_has_centered_modal_and_wrapped_names(self):
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".file-viewer-dialog", css)
        self.assertIn(".preview-table", css)
        self.assertIn(".disk-context-menu", css)
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertIn(".folder-tree-item", css)


if __name__ == "__main__":
    unittest.main()
