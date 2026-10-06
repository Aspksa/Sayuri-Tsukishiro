from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from agent.actions import SayuriActionBroker
from app.config import Settings
from app.core import SayuriCore


class SayuriActionBrokerTests(unittest.TestCase):
    def test_action_requires_confirmation_and_is_replay_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = SayuriActionBroker(Path(tmp) / "actions.db")
            action = broker.plan(
                "создай папку Отчёты",
                {"view": "disk", "disk": {"folder_id": None}},
            )

            self.assertIsNotNone(action)
            self.assertEqual(action["tool"], "disk.create_folder")
            self.assertEqual(action["status"], "pending")
            self.assertTrue(action["confirmation_required"])
            self.assertNotIn("context", action)
            self.assertEqual(
                broker.context(action["id"])["disk"]["folder_id"],
                None,
            )

            first = broker.begin(action["id"])
            self.assertTrue(first["claimed"])
            self.assertEqual(first["status"], "executing")

            second = broker.begin(action["id"])
            self.assertFalse(second["claimed"])
            self.assertEqual(second["status"], "executing")

            completed = broker.complete(action["id"], {"status": "выполнено"})
            self.assertEqual(completed["status"], "completed")

            replay = broker.begin(action["id"])
            self.assertFalse(replay["claimed"])
            self.assertEqual(replay["status"], "completed")

    def test_current_document_actions_use_context_and_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = SayuriActionBroker(Path(tmp) / "actions.db")
            context = {
                "view": "disk",
                "current_document": {
                    "id": "file-1",
                    "kind": "file",
                    "name": "Счёт.pdf",
                },
            }

            action = broker.plan("добавь этот документ в избранное", context)
            self.assertEqual(action["tool"], "disk.set_favorite")
            self.assertEqual(action["payload"]["item"]["id"], "file-1")
            self.assertTrue(action["payload"]["favorite"])

            cancelled = broker.cancel(action["id"])
            self.assertEqual(cancelled["status"], "cancelled")
            begin = broker.begin(action["id"])
            self.assertFalse(begin["claimed"])

    def test_project_decision_is_planned_not_saved_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = SayuriCore(Settings(root=root))
            core.initialize(record_event=False)

            planned = core.plan_sayuri_action(
                text="запомни как решение проекта: все изменения требуют новой версии",
                context={"view": "sayuri"},
            )
            action = planned["action"]

            self.assertEqual(action["tool"], "memory.remember")
            self.assertEqual(core.sayuri_memory(scope="project")["stats"]["project"]["count"], 0)

            completed = core.confirm_sayuri_action(action["id"])
            self.assertEqual(completed["status"], "completed")
            memory = core.sayuri_memory(scope="project")
            self.assertEqual(memory["stats"]["project"]["count"], 1)
            self.assertEqual(memory["entries"][0]["kind"], "decision")

    def test_confirmed_action_creates_task_checkpoint_and_advances_linked_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = SayuriCore(Settings(root=root))
            core.initialize(record_event=False)
            goal = core.agent.memory_v4.create_goal(
                "Организовать договоры",
                priority=5,
            )
            task = core.agent.memory_v4.create_task(
                "Создать папку Договоры",
                goal_id=goal["id"],
                priority=5,
                next_action="Создать папку Договоры.",
            )

            planned = core.plan_sayuri_action(
                text="создай папку Договоры",
                context={"view": "disk", "disk": {"folder_id": None}},
            )
            completed = core.confirm_sayuri_action(planned["action"]["id"])
            updated = next(
                item for item in core.agent.memory_v4.tasks()
                if item["id"] == task["id"]
            )

            self.assertEqual(completed["status"], "completed")
            self.assertIn("task_checkpoint", completed)
            self.assertTrue(completed["task_checkpoint"]["applied"])
            self.assertEqual(completed["task_checkpoint"]["task_id"], task["id"])
            self.assertEqual(updated["status"], "in_progress")
            self.assertIn("Проверить созданную папку", updated["next_action"])
            self.assertEqual(
                len(core.agent.memory_v4.task_checkpoints(task_id=task["id"])),
                1,
            )

    def test_create_folder_executes_only_after_core_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = SayuriCore(Settings(root=root))
            core.initialize(record_event=False)

            planned = core.plan_sayuri_action(
                text="создай папку Договоры",
                context={"view": "disk", "disk": {"folder_id": None}},
            )
            self.assertFalse(core.disk.list_entries()["folders"])

            completed = core.confirm_sayuri_action(planned["action"]["id"])
            self.assertEqual(completed["status"], "completed")
            experience = core.sayuri_experience()
            self.assertTrue(
                any(
                    item["strategy"] == "tool.disk.create_folder" and item["positive"] >= 1
                    for item in experience["stats"]["strategies"]
                )
            )
            folders = core.disk.list_entries()["folders"]
            self.assertEqual([item["name"] for item in folders], ["Договоры"])

            replay = core.confirm_sayuri_action(planned["action"]["id"])
            self.assertEqual(replay["status"], "completed")
            folders_after_replay = core.disk.list_entries()["folders"]
            self.assertEqual(len(folders_after_replay), 1)


if __name__ == "__main__":
    unittest.main()
