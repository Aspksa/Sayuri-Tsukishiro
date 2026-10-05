from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class WebContractTests(unittest.TestCase):
    def test_sidebar_and_main_views_exist(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="sidebar"', html)
        self.assertIn('data-view="home"', html)
        self.assertIn('data-view="disk"', html)
        self.assertIn('>Диск Sayuri<', html)
        self.assertIn('data-view="settings"', html)
        self.assertIn('id="view-disk"', html)
        self.assertIn('id="system-settings"', html)
        self.assertIn('id="system-state"', html)
        self.assertIn('id="system-events"', html)
        self.assertIn('id="system-architecture"', html)

    def test_frontend_uses_real_system_settings_and_disk_api(self):
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("fetch('/api/settings'", script)
        self.assertIn("fetch('/api/system'", script)
        self.assertIn("fetch('/api/disk/folders'", script)
        self.assertIn("/api/disk/upload?", script)
        self.assertIn("method: 'DELETE'", script)


if __name__ == "__main__":
    unittest.main()
