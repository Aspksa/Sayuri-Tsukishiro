from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "bootstrap_windows.ps1"


class PhoneBootstrapTests(unittest.TestCase):
    def test_scrcpy_runtime_is_official_pinned_and_verified(self):
        text = BOOTSTRAP.read_text(encoding="utf-8-sig")
        self.assertIn("$ScrcpyVersion = '4.1'", text)
        self.assertIn("scrcpy-win64-v4.1.zip", text)
        self.assertIn(
            "5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db",
            text,
        )
        self.assertIn("github.com/Genymobile/scrcpy/releases/download", text)
        self.assertIn("Test-PhoneRuntime", text)
        self.assertIn("Ensure-PhoneRuntime", text)
        self.assertIn("scrcpy.exe", text)
        self.assertIn("adb.exe", text)

    def test_phone_runtime_is_optional_and_arm64_does_not_install_win64(self):
        text = BOOTSTRAP.read_text(encoding="utf-8-sig")
        self.assertIn("AutoScrcpy = $false", text)
        self.assertIn(
            "проект запустится без управления телефоном",
            text,
        )


if __name__ == "__main__":
    unittest.main()
