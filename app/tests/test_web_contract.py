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

    def test_dna_upload_starts_analysis_and_surfaces_retryable_errors(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="dna-load-state"', html)
        self.assertIn('id="dna-load-retry"', html)
        self.assertIn("DNA_AUTO_EXTENSIONS", script)
        self.assertIn("shouldAutoAnalyzeDna", script)
        self.assertIn("analyzeUploadedDna", script)
        self.assertIn("Файл загружен · ожидает ДНК", script)
        self.assertIn("Строю ДНК", script)
        self.assertIn("setDnaLoadState('error'", script)
        self.assertIn("dna-load-retry", script)
        self.assertIn(".dna-load-state.error", css)
        self.assertIn(".upload-item.dna-error", css)
        self.assertIn("SAYURI UI 0.17 — DNA Upload & Analysis Reliability", css)

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

    def test_memory_intelligence_candidate_review_is_present(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('MEMORY INTELLIGENCE 2.0', html)
        self.assertIn('id="memory-intelligence-candidates"', html)
        self.assertIn('id="memory-intelligence-conflicts"', html)
        self.assertIn('id="memory-intelligence-context"', html)
        self.assertIn('id="memory-intelligence-autosave"', html)
        self.assertIn('id="sayuri-memory-candidates"', html)
        self.assertIn('/api/sayuri/memory/candidates', script)
        self.assertIn('/api/sayuri/memory/intelligence', script)
        self.assertIn('reviewSayuriMemoryCandidate', script)
        self.assertIn('createMemoryCandidateChatNotice', script)
        self.assertIn('.sayuri-memory-candidate', css)
        self.assertIn('SAYURI UI 0.18 — Memory Intelligence 2.0', css)

    def test_semantic_memory_and_experience_learning_are_visible(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="sayuri-semantic-engine"', html)
        self.assertIn('EXPERIENCE LEARNING', html)
        self.assertIn('id="sayuri-experience-total"', html)
        self.assertIn('id="sayuri-experience-strategies"', html)
        self.assertIn('/api/sayuri/experience', script)
        self.assertIn('/api/sayuri/experience/feedback', script)
        self.assertIn('createSayuriFeedbackControls', script)
        self.assertIn('hybrid-semantic-v1', script)
        self.assertIn('.sayuri-experience-metrics', css)
        self.assertIn('.sayuri-response-feedback', css)
        self.assertIn('SAYURI UI 0.19 — Semantic Memory & Experience Learning', css)

    def test_memory_v3_dashboard_and_resolver_are_present(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('MEMORY 3.0', html)
        self.assertIn('id="memory-v3-working-list"', html)
        self.assertIn('id="memory-v3-knowledge-list"', html)
        self.assertIn('id="memory-v3-episodes-list"', html)
        self.assertIn('id="memory-v3-timeline"', html)
        self.assertIn('id="memory-v3-graph"', html)
        self.assertIn('id="memory-v3-conflicts-list"', html)
        self.assertIn('id="memory-v3-retention-list"', html)
        self.assertIn('Contradiction Resolver', html)
        self.assertIn('Forgetting Engine', html)
        self.assertIn('/api/sayuri/memory/v3', script)
        self.assertIn('/maintenance', script)
        self.assertIn('/resolve', script)
        self.assertIn('loadSayuriMemoryV3', script)
        self.assertIn('renderMemoryV3Episodes', script)
        self.assertIn('resolveMemoryV3Conflict', script)
        self.assertIn('.sayuri-memory-v3-metrics', css)
        self.assertIn('.memory-v3-conflict', css)
        self.assertIn('SAYURI UI 0.20 — Memory 3.0', css)

    def test_memory_v4_control_center_is_present(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('MEMORY 4.1 · QUALITY GATE', html)
        self.assertIn('id="memory-v4-goal-form"', html)
        self.assertIn('id="memory-v4-task-form"', html)
        self.assertIn('id="memory-v4-goal-list"', html)
        self.assertIn('id="memory-v4-task-list"', html)
        self.assertIn('id="memory-v4-failure-list"', html)
        self.assertIn('id="memory-v4-question-list"', html)
        self.assertIn('id="memory-v4-source-list"', html)
        self.assertIn('id="memory-v4-recall-list"', html)
        self.assertIn('id="memory-v4-decision-list"', html)
        self.assertIn('id="memory-v4-entity-list"', html)
        self.assertIn('id="memory-v4-preference-list"', html)
        self.assertIn('id="memory-v4-audit-list"', html)
        self.assertIn('id="memory-v4-integrity-state"', html)
        self.assertIn('id="memory-v4-snapshot-list"', html)
        self.assertIn('RESTORE MEMORY', html)

        self.assertIn('/api/sayuri/memory/v4', script)
        self.assertIn('/api/sayuri/memory/v4/goals', script)
        self.assertIn('/api/sayuri/memory/v4/tasks', script)
        self.assertIn('/api/sayuri/memory/v4/sources/trust', script)
        self.assertIn('/api/sayuri/memory/v4/failures/', script)
        self.assertIn('/api/sayuri/memory/v4/integrity', script)
        self.assertIn('/api/sayuri/memory/v4/snapshots', script)
        self.assertIn('renderSayuriMemoryV4', script)
        self.assertIn('resolveMemoryV4Failure', script)
        self.assertIn('Подтвердить исправление', script)
        self.assertIn('renderMemoryV4Decisions', script)
        self.assertIn('renderMemoryV4Entities', script)
        self.assertIn('renderMemoryV4Preferences', script)
        self.assertIn('renderMemoryV4Audit', script)
        self.assertIn('restoreMemoryV4Snapshot', script)
        self.assertIn('Почему вспомнила', script)
        self.assertIn('memory_v4_used', script)
        self.assertIn('INSTRUCTION RISK', script)
        self.assertIn('freshness_review', script)

        self.assertIn('.sayuri-memory-v4-metrics', css)
        self.assertIn('.memory-v4-source-row', css)
        self.assertIn('.memory-v4-causal-divider', css)
        self.assertIn('.memory-v4-row.preference.archived', css)
        self.assertIn('.sayuri-memory-recall-reason', css)
        self.assertIn('SAYURI UI 0.21 — Memory 4.0', css)
        self.assertIn('SAYURI UI 0.22 — Memory 4.1 Quality Gate', css)
        self.assertIn('.memory-v4-instruction-risk', css)

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
