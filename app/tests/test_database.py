from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.database import Database, SCHEMA_VERSION


class DatabaseTests(unittest.TestCase):
    def test_initialize_and_record_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "sayuri.db")
            db.initialize()
            db.record_event("test.event", "hello", details={"ok": True})
            db.record_error("TEST-001", "boom", {"source": "unit"})
            health = db.health()
            self.assertEqual(health["status"], "ready")
            self.assertEqual(health["schema_version"], SCHEMA_VERSION)
            self.assertEqual(health["events"], 1)
            self.assertEqual(health["errors"], 1)
            events = db.recent_events(10)
            self.assertEqual(events[0]["event_type"], "test.event")
            self.assertEqual(events[0]["details"], {"ok": True})


if __name__ == "__main__":
    unittest.main()
