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
            db.record_event("Проверка", "Готово", details={"ok": True})
            db.record_error("TEST-001", "ошибка", {"source": "unit"})
            health = db.health()
            self.assertEqual(health["status"], "готово")
            self.assertEqual(health["schema_version"], SCHEMA_VERSION)
            self.assertEqual(health["events"], 1)
            self.assertEqual(health["errors"], 1)
            events = db.recent_events(10)
            self.assertEqual(events[0]["event_type"], "Проверка")
            self.assertEqual(events[0]["details"], {"ok": True})

    def test_legacy_system_events_are_translated(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "sayuri.db")
            db.initialize()
            db.record_event("core.start", "Sayuri Core initialized")
            db.record_event("web.ready", "Local web server ready")
            db.initialize()
            events = db.recent_events(10)
            pairs = {(item["event_type"], item["message"]) for item in events}
            self.assertIn(("Запуск", "Ядро готово"), pairs)
            self.assertIn(("Сайт", "Сервер готов"), pairs)
            self.assertNotIn(("core.start", "Sayuri Core initialized"), pairs)


if __name__ == "__main__":
    unittest.main()
