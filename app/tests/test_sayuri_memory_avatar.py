from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from agent.avatar import AvatarStore
from agent.memory import SayuriMemory
from agent.memory_intelligence import MemoryIntelligence
from agent.runtime import SayuriAgent


def fake_png(width: int = 64, height: int = 64) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


class SayuriMemoryTests(unittest.TestCase):
    def test_personal_and_project_memory_are_separated_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SayuriMemory(Path(tmp) / "memory.db")
            memory.initialize()

            personal = memory.add(
                scope="personal",
                kind="preference",
                content="Господин предпочитает белый интерфейс",
                importance=4,
            )
            duplicate = memory.add(
                scope="personal",
                kind="preference",
                content="  Господин   предпочитает белый интерфейс  ",
                importance=5,
            )
            project = memory.add(
                scope="project",
                kind="decision",
                content="Проект использует DeepSeek-V4-Flash",
                importance=5,
            )

            self.assertEqual(personal["id"], duplicate["id"])
            self.assertEqual(duplicate["importance"], 5)
            self.assertNotEqual(personal["id"], project["id"])
            self.assertEqual(len(memory.list(scope="personal")), 1)
            self.assertEqual(len(memory.list(scope="project")), 1)
            self.assertEqual(memory.stats()["total"], 2)

    def test_explicit_chat_memory_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = SayuriAgent(Path(tmp))

            result = agent.chat(message="запомни в проект: версия проекта всегда меняется при изменениях")

            self.assertEqual(result["model"], "local-memory")
            self.assertEqual(result["memory_saved"]["scope"], "project")
            entries = agent.memory.list(scope="project")
            self.assertEqual(len(entries), 1)
            self.assertIn("версия проекта", entries[0]["content"])

    def test_relevant_search_keeps_scope_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SayuriMemory(Path(tmp) / "memory.db")
            memory.initialize()
            memory.add(scope="personal", kind="fact", content="Любимая тема интерфейса — светлая", importance=4)
            memory.add(scope="project", kind="fact", content="Светлая тема закреплена для проекта Sayuri", importance=5)

            found = memory.search("светлая тема Sayuri", limit=10)

            self.assertEqual(found["personal"][0]["scope"], "personal")
            self.assertEqual(found["project"][0]["scope"], "project")


class SayuriMemoryIntelligenceTests(unittest.TestCase):
    def test_chat_message_creates_review_candidate_with_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = SayuriMemory(root / "memory.db")
            memory.initialize()
            intelligence = MemoryIntelligence(root / "memory.db", memory)

            candidates = intelligence.analyze_message(
                "В проекте Sayuri нужно хранить память отдельно от документов",
                {
                    "view": "disk",
                    "current_document": {
                        "id": "file-1",
                        "kind": "file",
                        "name": "ТЗ.pdf",
                        "category": "document",
                    },
                },
            )

            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertEqual(candidate["scope"], "project")
            self.assertIn(candidate["kind"], {"decision", "task"})
            self.assertEqual(candidate["status"], "pending")
            self.assertEqual(candidate["source_context"]["current_document"]["name"], "ТЗ.pdf")
            self.assertEqual(memory.stats()["total"], 0)

    def test_candidate_requires_review_before_becoming_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = SayuriMemory(root / "memory.db")
            memory.initialize()
            intelligence = MemoryIntelligence(root / "memory.db", memory)

            candidate = intelligence.analyze_message(
                "Я предпочитаю светлый интерфейс без лишней анимации",
                {"view": "sayuri"},
            )[0]

            self.assertEqual(candidate["scope"], "personal")
            self.assertEqual(candidate["kind"], "preference")
            self.assertEqual(memory.stats()["personal"]["count"], 0)

            reviewed = intelligence.review(candidate["id"], "accept")
            self.assertEqual(reviewed["status"], "accepted")
            entries = memory.list(scope="personal")
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["source"], "memory_intelligence_confirmed")
            self.assertIsNotNone(entries[0]["confidence"])
            self.assertEqual(entries[0]["source_context"]["view"], "sayuri")

    def test_duplicate_candidate_is_marked_without_second_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = SayuriMemory(root / "memory.db")
            memory.initialize()
            memory.add(
                scope="personal",
                kind="preference",
                content="Я предпочитаю светлый интерфейс",
                importance=4,
            )
            intelligence = MemoryIntelligence(root / "memory.db", memory)

            candidate = intelligence.analyze_message(
                "Я предпочитаю светлый интерфейс",
                {"view": "home"},
            )[0]

            self.assertEqual(candidate["relation"], "duplicate")
            self.assertEqual(candidate["status"], "duplicate")
            self.assertEqual(memory.stats()["personal"]["count"], 1)

    def test_automation_settings_are_local_and_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = SayuriMemory(root / "memory.db")
            memory.initialize()
            intelligence = MemoryIntelligence(root / "memory.db", memory)

            settings = intelligence.update_settings({
                "candidate_generation": False,
                "auto_save_high_confidence": True,
                "auto_save_threshold": 0.99,
            })

            self.assertFalse(settings["candidate_generation"])
            self.assertTrue(settings["auto_save_high_confidence"])
            self.assertEqual(settings["auto_save_threshold"], 0.99)
            self.assertEqual(
                intelligence.analyze_message("Я предпочитаю компактный интерфейс"),
                [],
            )


class SayuriAvatarTests(unittest.TestCase):
    def test_multiple_avatar_slots_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AvatarStore(Path(tmp) / "avatars")

            orb = store.save(
                slot="orb",
                filename="orb.png",
                content_type="image/png",
                data=fake_png(192, 192),
            )
            hero = store.save(
                slot="hero",
                filename="hero.png",
                content_type="image/png",
                data=fake_png(1024, 1024),
            )

            public = store.public()
            self.assertTrue(public["orb"]["custom"])
            self.assertTrue(public["hero"]["custom"])
            self.assertFalse(public["chat"]["custom"])
            self.assertEqual((orb["width"], orb["height"]), (192, 192))
            self.assertEqual((hero["width"], hero["height"]), (1024, 1024))

            store.reset("orb")
            self.assertFalse(store.public()["orb"]["custom"])
            self.assertTrue(store.public()["hero"]["custom"])


if __name__ == "__main__":
    unittest.main()
