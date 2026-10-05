from __future__ import annotations

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from agent.experience import ExperienceStore
from agent.memory import SayuriMemory
from agent.memory_intelligence import MemoryIntelligence
from agent.runtime import CloudRuClient, SayuriAgent
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

    def test_semantic_search_can_find_relevant_memory_beyond_first_300_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SayuriMemory(Path(tmp) / "memory.db")
            memory.initialize()
            target = memory.add(
                scope="project",
                kind="note",
                content="Редкий маркер: северный маяк обслуживает архив договоров",
                importance=3,
            )
            for index in range(360):
                memory.add(
                    scope="project",
                    kind="note",
                    content=f"Обычная техническая заметка номер {index}",
                    importance=3,
                )
            semantic = SemanticMemoryIndex(memory)

            found = semantic.search(
                "где упоминается северный маяк и архив договоров",
                scopes=("project",),
                limit=5,
            )

            self.assertTrue(found["project"])
            self.assertEqual(found["project"][0]["id"], target["id"])

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


    def test_relevant_experience_is_split_into_helpful_and_avoid(self):
        with tempfile.TemporaryDirectory() as tmp:
            experience = ExperienceStore(Path(tmp) / "experience.db")
            experience.record_chat_feedback(
                "good-1",
                "useful",
                prompt="Как сделать светлый интерфейс компактнее?",
                answer="Уменьшить визуальный шум и сохранить читаемость.",
                context={"view": "sayuri"},
            )
            experience.record_chat_feedback(
                "bad-1",
                "not_useful",
                prompt="Как сделать светлый интерфейс компактнее?",
                answer="Добавить больше декоративных панелей.",
                context={"view": "sayuri"},
            )

            context = experience.context("хочу компактный светлый дизайн", limit=6)

            self.assertTrue(context["helpful"])
            self.assertTrue(context["avoid"])
            self.assertEqual(context["retrieval"], "hybrid_semantic_v1")

    def test_runtime_injects_semantic_memory_and_relevant_experience(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = SayuriAgent(root)
            agent.memory.add(
                scope="personal",
                kind="preference",
                content="Господин предпочитает белый компактный интерфейс",
                importance=5,
            )
            agent.experience.record_chat_feedback(
                "feedback-1",
                "useful",
                prompt="Как улучшить компактный светлый интерфейс?",
                answer="Снизить визуальный шум и оставить чёткую иерархию.",
                context={"view": "sayuri"},
            )
            agent.memory_v4.create_goal(
                "Сохранить компактность светлого интерфейса",
                priority=5,
            )

            captured = {}

            def fake_chat(self, messages):
                captured["messages"] = messages
                return {
                    "answer": "Проверочный ответ",
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    "model": "deepseek-ai/DeepSeek-V4-Flash",
                }

            with patch.dict(os.environ, {"SAYURI_CLOUDRU_API_KEY": "test-key-1234567890"}):
                with patch.object(CloudRuClient, "chat", fake_chat):
                    result = agent.chat(
                        message="Как сделать светлую тему компактнее?",
                        context={"view": "sayuri", "title": "Личный кабинет Sayuri"},
                    )

            system_text = "\n".join(
                item["content"]
                for item in captured["messages"]
                if item["role"] == "system"
            )
            self.assertIn("белый компактный интерфейс", system_text)
            self.assertIn("Снизить визуальный шум", system_text)
            self.assertIn("Сохранить компактность светлого интерфейса", system_text)
            self.assertIn("Memory 4.0 Sayuri", system_text)
            self.assertGreaterEqual(result["memory_used"], 1)
            self.assertGreaterEqual(result["experience_used"], 1)
            self.assertGreaterEqual(result["memory_v4_used"], 1)
            self.assertEqual(result["memory_v4"]["version"], "4.0")
            self.assertTrue(result["response_id"])

            feedback = agent.record_chat_feedback(
                result["response_id"],
                "useful",
                prompt="Как сделать светлую тему компактнее?",
                answer="Проверочный ответ",
                context={"view": "sayuri"},
            )
            self.assertGreaterEqual(feedback["memory_feedback"]["updated"], 1)

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
