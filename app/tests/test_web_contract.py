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

    def test_phone_module_is_absent_from_web_surface(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertNotIn('data-view="phone"', html)
        self.assertNotIn('id="view-phone"', html)
        self.assertNotIn('phone-float', html)
        self.assertNotIn("/api/phone", script)
        self.assertNotIn("phoneState", script)
        self.assertNotIn(".phone-", css)


    def test_sayuri_global_assistant_and_personal_cabinet_are_present(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="view-sayuri"', html)
        self.assertIn('id="sayuri-account-nav"', html)
        self.assertIn('id="sayuri-orb"', html)
        self.assertIn('id="sayuri-context-menu"', html)
        self.assertIn('id="sayuri-chat-window"', html)
        self.assertIn('id="sayuri-api-key"', html)
        self.assertIn('deepseek-ai/DeepSeek-V4-Flash', html)
        self.assertIn('Cloud.ru Foundation Models', html)
        self.assertIn('/assets/sayuri-avatar.svg', html)

        self.assertIn('/api/sayuri/profile', script)
        self.assertIn('/api/sayuri/provider', script)
        self.assertIn('/api/sayuri/provider/test', script)
        self.assertIn('/api/sayuri/chat', script)
        self.assertIn('currentSayuriContext', script)
        self.assertIn("addEventListener('contextmenu'", script)
        self.assertIn('initializeSayuri()', script)

        self.assertIn('.sayuri-orb', css)
        self.assertIn('.sayuri-chat-window', css)
        self.assertIn('.sayuri-account-grid', css)
        self.assertIn('SAYURI UI 0.14 — Global Assistant & Personal Cabinet', css)

    def test_personal_cabinet_has_memory_and_avatar_studio(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="sayuri-memory-form"', html)
        self.assertIn('id="sayuri-memory-list"', html)
        self.assertIn('id="sayuri-avatar-grid"', html)
        self.assertIn('Аватары разных размеров', html)
        self.assertIn('/api/sayuri/memory', script)
        self.assertIn('/api/sayuri/avatar/upload', script)
        self.assertIn('loadSayuriMemory', script)
        self.assertIn('uploadSayuriAvatar', script)
        self.assertIn('.sayuri-memory-entry', css)
        self.assertIn('.sayuri-avatar-slot', css)
        self.assertIn('SAYURI UI 0.15 — Long-term Memory & Avatar Studio', css)

    def test_sayuri_safe_actions_require_confirmation_in_ui(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="sayuri-tool-list"', html)
        self.assertIn('id="sayuri-actions-history"', html)
        self.assertIn('Только после подтверждения', html)
        self.assertIn('/api/sayuri/actions/plan', script)
        self.assertIn('/confirm', script)
        self.assertIn('/cancel', script)
        self.assertIn('createSayuriActionCard', script)
        self.assertIn('Подтвердить', script)
        self.assertIn('Отменить', script)
        self.assertIn('.sayuri-action-proposal', css)
        self.assertIn('SAYURI UI 0.16 — Confirmation-gated Actions', css)

    def test_unified_visual_system_is_readable_and_consistent(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("SAYURI UI 0.12 — Unified Visual System", css)
        self.assertIn('"Segoe UI Variable Text"', css)
        self.assertIn("--ui-text: #171b24", css)
        self.assertIn("--ui-muted: #6f7b8c", css)
        self.assertIn("font-size: 14px", css)
        self.assertIn("max-width: 1380px", css)
        self.assertNotIn(">Runtime<", html)


if __name__ == "__main__":
    unittest.main()
