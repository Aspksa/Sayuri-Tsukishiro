from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.database import Database, SCHEMA_VERSION
from app.errors import BadRequestError
from app.system_settings import SystemSettings


class SettingsTests(unittest.TestCase):
    def test_schema_two_and_persistent_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "sayuri.db")
            db.initialize()
            settings = SystemSettings(db)
            settings.initialize()
            self.assertEqual(SCHEMA_VERSION, 2)
            self.assertTrue(settings.value("browser.auto_open"))
            self.assertEqual(settings.value("ui.refresh_seconds"), 10)

            settings.update({"ui.refresh_seconds": 15, "events.display_limit": 20})
            reloaded = SystemSettings(db)
            reloaded.initialize()
            self.assertEqual(reloaded.value("ui.refresh_seconds"), 15)
            self.assertEqual(reloaded.value("events.display_limit"), 20)

    def test_validation_rejects_unknown_and_out_of_range_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "sayuri.db")
            db.initialize()
            settings = SystemSettings(db)
            settings.initialize()
            with self.assertRaises(BadRequestError):
                settings.update({"unknown.key": True})
            with self.assertRaises(BadRequestError):
                settings.update({"ui.refresh_seconds": 1})
            with self.assertRaises(BadRequestError):
                settings.update({"browser.auto_open": "yes"})


if __name__ == "__main__":
    unittest.main()
