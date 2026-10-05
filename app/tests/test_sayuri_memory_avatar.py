from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from agent.avatar import AvatarStore
from agent.memory import SayuriMemory
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
