from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PortableLauncherTests(unittest.TestCase):
    def test_launcher_uses_relative_project_root(self):
        launcher = (ROOT / "Sayuri Tsukishiro.bat").read_text(encoding="utf-8")
        self.assertIn('cd /d "%~dp0"', launcher)
        self.assertNotIn("C:\\", launcher)
        self.assertNotIn("D:\\", launcher)

    def test_bootstrap_pins_runtime_and_hashes(self):
        bootstrap = (ROOT / "scripts" / "bootstrap_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("3.14.8", bootstrap)
        self.assertIn("python.org/ftp/python/3.14.8", bootstrap)
        self.assertIn("80292f0e640e373a54bf09f3b94a1472f976f24a10c5bed0d9622e4e44d67447", bootstrap)
        self.assertIn("3d5cf5f4ec055b1dc2882fe6fbaaeb483d1984dd5335ae9ac692e0c6b3ce8785", bootstrap)
        self.assertIn("Get-FileHash", bootstrap)

    def test_runtime_and_data_are_project_local(self):
        bootstrap = (ROOT / "scripts" / "bootstrap_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("'.runtime'", bootstrap)
        self.assertIn("'logs'", bootstrap)
        config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
        self.assertIn('self.root / "data"', config)
        self.assertIn('self.root / "logs"', config)


if __name__ == "__main__":
    unittest.main()
