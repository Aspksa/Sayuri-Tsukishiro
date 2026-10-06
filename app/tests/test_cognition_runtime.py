from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.config import Settings
from app.core import SayuriCore
from app.errors import BadRequestError


class CognitiveRuntimeIntegrationTests(unittest.TestCase):
    def test_task_creation_binds_normalized_module_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = SayuriCore(Settings(root=Path(tmp)))
            core.initialize(record_event=False)

            created = core.create_sayuri_memory_v4_task(
                title="Подготовить DNA quality gate",
                priority=5,
                next_action="Добавить подтверждённую проверку качества.",
                context={
                    "view": "disk",
                    "completion_criteria": [
                        {"type": "checkpoint_count", "min": 1},
                    ],
                },
            )

            scope = created["cognitive_scope"]
            cognition = core.sayuri_cognition(
                query="DNA quality gate",
                context={"module_key": "sayuri-disk"},
            )
            selected = cognition["context"]["scheduler"]["selected"]

            self.assertEqual(scope["completion_criteria"][0]["type"], "checkpoint_count")
            module = next(
                item
                for item in core.agent.cognition.modules()
                if item["id"] == scope["module_id"]
            )
            self.assertEqual(module["key"], "sayuri-disk")
            self.assertEqual(selected["id"], created["task"]["id"])
            self.assertEqual(cognition["self_evaluation"]["module"]["key"], "sayuri-disk")

    def test_completion_guard_rejects_done_until_criteria_are_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = SayuriCore(Settings(root=Path(tmp)))
            core.initialize(record_event=False)
            created = core.create_sayuri_memory_v4_task(
                title="Проверить новый модуль",
                next_action="Выполнить подтверждённую проверку.",
                context={
                    "completion_criteria": [
                        {"type": "checkpoint_count", "min": 1},
                    ]
                },
            )

            with self.assertRaises(BadRequestError):
                core.update_sayuri_memory_v4_task(
                    created["task"]["id"],
                    status="done",
                )

            current = next(
                item
                for item in core.agent.memory_v4.tasks()
                if item["id"] == created["task"]["id"]
            )
            self.assertNotEqual(current["status"], "done")

    def test_explicit_replan_requires_confirmation_and_stale_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = SayuriCore(Settings(root=Path(tmp)))
            core.initialize(record_event=False)
            task = core.create_sayuri_memory_v4_task(
                title="Переместить документ",
                next_action="Переместить документ в Архив.",
                context={"module_key": "sayuri-disk"},
            )["task"]
            observation = core.agent.cognition.observe_action(
                {
                    "id": "failed-runtime-move",
                    "tool": "disk.move_current",
                    "status": "failed",
                    "error": "Папка назначения не найдена",
                },
                context={"_task_lifecycle": {"task_id": task["id"]}},
            )

            with self.assertRaises(BadRequestError):
                core.apply_sayuri_cognitive_replan(
                    observation["replan"]["id"],
                    confirmation="",
                )

            applied = core.apply_sayuri_cognitive_replan(
                observation["replan"]["id"],
                confirmation="APPLY_REPLAN",
            )
            self.assertTrue(applied["replan"]["applied"])

    def test_cognition_api_contract_keeps_mutations_out_of_llm_tool_catalog(self):
        root = Path(__file__).resolve().parents[2]
        server_source = (root / "app" / "server.py").read_text(encoding="utf-8")
        core_source = (root / "app" / "core.py").read_text(encoding="utf-8")
        tool_source = (root / "agent" / "tool_planner.py").read_text(encoding="utf-8")

        self.assertIn("/api/sayuri/cognition/projects", server_source)
        self.assertIn("/api/sayuri/cognition/modules", server_source)
        self.assertIn("/api/sayuri/cognition/dependencies", server_source)
        self.assertIn("/api/sayuri/cognition/milestones", server_source)
        self.assertIn("/api/sayuri/cognition/external-blockers", server_source)
        self.assertIn("/api/sayuri/cognition/tasks/", server_source)
        self.assertIn("/api/sayuri/cognition/uncertainties/", server_source)
        self.assertIn("/api/sayuri/cognition/replans/", server_source)
        self.assertIn("APPLY_REPLAN", server_source)
        self.assertIn("def add_sayuri_cognitive_dependency", core_source)
        self.assertIn("def register_sayuri_cognitive_milestone", core_source)
        self.assertIn("def add_sayuri_cognitive_external_blocker", core_source)
        self.assertIn("COMPLETE_MILESTONE", server_source)
        self.assertIn('"cognition.next"', tool_source)
        self.assertNotIn('"cognition.apply_replan"', tool_source)
        self.assertNotIn('"cognition.add_dependency"', tool_source)
        self.assertNotIn('"cognition.complete_milestone"', tool_source)
        self.assertNotIn('"cognition.add_external_blocker"', tool_source)


    def test_portfolio_milestone_and_external_blocker_local_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = SayuriCore(Settings(root=Path(tmp)))
            core.initialize(record_event=False)
            source_task = core.create_sayuri_memory_v4_task(
                title="Подготовить общий API",
                next_action="Проверить API.",
                context={"project_key": "platform"},
            )["task"]
            target_task = core.create_sayuri_memory_v4_task(
                title="Использовать общий API",
                next_action="Подключить API.",
                context={"project_key": "consumer"},
            )["task"]
            milestone = core.register_sayuri_cognitive_milestone(
                "platform",
                "api-ready",
                title="API Ready",
                priority=5,
            )["milestone"]
            core.link_sayuri_cognitive_milestone_task(
                milestone["id"],
                source_task["id"],
                required=True,
            )
            blocker = core.add_sayuri_cognitive_external_blocker(
                "consumer",
                "wait-platform",
                "Ожидается API Ready",
                task_id=target_task["id"],
                source_project_key="platform",
                source_milestone_id=milestone["id"],
            )["external_blocker"]

            before = core.sayuri_cognition(
                query="Использовать общий API",
                context={"project_key": "consumer"},
            )
            self.assertIsNone(before["context"]["scheduler"]["selected"])
            self.assertEqual(
                before["context"]["scheduler"]["blocked_by_external"],
                1,
            )

            core.update_sayuri_memory_v4_task(
                source_task["id"],
                status="done",
            )
            with self.assertRaises(BadRequestError):
                core.complete_sayuri_cognitive_milestone(
                    milestone["id"],
                    confirmation="",
                )
            completed = core.complete_sayuri_cognitive_milestone(
                milestone["id"],
                confirmation="COMPLETE_MILESTONE",
            )
            self.assertEqual(completed["milestone"]["status"], "done")

            after = core.sayuri_cognition(
                query="Использовать общий API",
                context={"project_key": "consumer"},
            )
            self.assertEqual(
                after["context"]["scheduler"]["selected"]["id"],
                target_task["id"],
            )
            listed = core.sayuri_cognitive_external_blockers(
                project_key="consumer",
                task_id=target_task["id"],
            )["external_blockers"]
            self.assertEqual(listed[0]["id"], blocker["id"])
            self.assertEqual(listed[0]["effective_status"], "resolved")


if __name__ == "__main__":
    unittest.main()
