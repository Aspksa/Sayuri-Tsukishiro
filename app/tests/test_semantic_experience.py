from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from agent.experience import ExperienceStore
from agent.memory import SayuriMemory
from agent.memory_intelligence import MemoryIntelligence
from agent.semantic_memory import SemanticMemoryIndex


class SemanticMemoryTests(unittest.TestCase):
    def test_semantic_search_matches_related_wording_without_exact_phrase(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SayuriMemory(Path(tmp) / "memory.db")
            memory.initialize()
            entry = memory.add(
                scope="personal",
                kind="preference",
                content="Господин предпочитает белый интерфейс без лишней анимации",
                importance=5,
            )
            semantic = SemanticMemoryIndex(memory)

            found = semantic.search(
                "Какая светлая тема оформления мне нравится?",
                scopes=("personal",),
                limit=5,
            )

            self.assertEqual(found["personal"][0]["id"], entry["id"])
            self.assertEqual(found["personal"][0]["retrieval"], "hybrid-semantic-v1")
            self.assertGreater(found["personal"][0]["relevance"], 0.20)
            self.assertIn(
                "совпали смысловые понятия",
                found["personal"][0]["semantic_match"]["reasons"],
            )

    def test_semantic_search_preserves_personal_project_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SayuriMemory(Path(tmp) / "memory.db")
            memory.initialize()
            memory.add(
                scope="personal",
                kind="preference",
                content="Я предпочитаю белый интерфейс",
                importance=4,
            )
            memory.add(
                scope="project",
                kind="decision",
                content="Для проекта используем светлый интерфейс",
                importance=5,
            )
            semantic = SemanticMemoryIndex(memory)

            found = semantic.search("светлая тема", scopes=("project",), limit=5)

            self.assertTrue(found["project"])
            self.assertTrue(all(item["scope"] == "project" for item in found["project"]))


class ExperienceLearningTests(unittest.TestCase):
    def test_chat_feedback_is_idempotent_and_can_be_revised(self):
        with tempfile.TemporaryDirectory() as tmp:
            experience = ExperienceStore(Path(tmp) / "experience.db")

            experience.record_chat_feedback("resp-1", "useful")
            experience.record_chat_feedback("resp-1", "not_useful")

            stats = experience.stats()
            self.assertEqual(stats["total"], 1)
            self.assertEqual(stats["positive"], 0)
            self.assertEqual(stats["negative"], 1)

    def test_strategy_adjustment_requires_evidence_and_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            experience = ExperienceStore(Path(tmp) / "experience.db")
            strategy = "memory.personal.preference"

            self.assertEqual(experience.confidence_adjustment(strategy), 0.0)
            for index in range(6):
                experience.record_memory_review(
                    f"candidate-{index}",
                    scope="personal",
                    kind="preference",
                    decision="reject",
                    relation="new",
                )

            adjustment = experience.confidence_adjustment(strategy)
            self.assertLess(adjustment, 0.0)
            self.assertGreaterEqual(adjustment, -0.08)

    def test_memory_intelligence_learns_from_review_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = SayuriMemory(root / "memory.db")
            memory.initialize()
            experience = ExperienceStore(root / "experience.db")
            for index in range(6):
                experience.record_memory_review(
                    f"old-{index}",
                    scope="personal",
                    kind="preference",
                    decision="reject",
                    relation="new",
                )
            intelligence = MemoryIntelligence(root / "memory.db", memory, experience)

            candidate = intelligence.analyze_message(
                "Я предпочитаю очень крупные кнопки",
                {"view": "sayuri"},
            )[0]

            self.assertLess(candidate["confidence"], 0.86)
            self.assertIn("опыт Sayuri", candidate["reason"])

    def test_action_outcome_replay_updates_single_experience(self):
        with tempfile.TemporaryDirectory() as tmp:
            experience = ExperienceStore(Path(tmp) / "experience.db")

            experience.record_action(
                "action-1",
                "disk.create_folder",
                "completed",
            )
            experience.record_action(
                "action-1",
                "disk.create_folder",
                "completed",
            )

            stats = experience.stats()
            self.assertEqual(stats["total"], 1)
            self.assertEqual(stats["positive"], 1)


if __name__ == "__main__":
    unittest.main()
