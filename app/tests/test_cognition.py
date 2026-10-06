from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from agent.cognition import CognitiveBrainError, CognitiveProjectBrain
from agent.memory import SayuriMemory
from agent.memory_v3 import MemorySystemV3
from agent.memory_v4 import MemorySystemV4
from agent.semantic_memory import SemanticMemoryIndex


class CognitiveProjectBrainTests(unittest.TestCase):
    def _build(self, root: Path):
        (root / "VERSION").write_text("0.2.1\n", encoding="utf-8")
        (root / "MODULES.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "modules": [
                        {
                            "id": "agent-core",
                            "display_name": "Агентное ядро",
                            "description": "Мозг Sayuri",
                            "path": "agent",
                        },
                        {
                            "id": "vk-automation",
                            "display_name": "VK Automation",
                            "description": "Будущий модуль VK",
                            "path": "modules/vk",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        memory = SayuriMemory(root / "data" / "sayuri-memory.db")
        memory.initialize()
        semantic = SemanticMemoryIndex(memory)
        v3 = MemorySystemV3(root / "data" / "sayuri-memory.db", memory, semantic)
        v4 = MemorySystemV4(root, memory, semantic, v3)
        brain = CognitiveProjectBrain(root, v4)
        brain.bootstrap_manifest()
        return memory, semantic, v3, v4, brain

    def test_manifest_and_task_scope_support_many_projects_and_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            vk_task = v4.create_task(
                "Подготовить VK-публикацию",
                priority=4,
                next_action="Собрать материал.",
                context={
                    "project_key": "sayuri-tsukishiro",
                    "module_key": "vk-automation",
                    "completion_criteria": [
                        {"type": "checkpoint_count", "min": 1},
                    ],
                },
            )
            external = v4.create_task(
                "Подготовить публикацию Madclips",
                priority=3,
                context={
                    "project_key": "madclips",
                    "module_key": "posting",
                },
            )

            brain.sync_tasks()

            status = brain.status()
            self.assertGreaterEqual(status["counts"]["projects"], 2)
            self.assertGreaterEqual(status["counts"]["modules"], 3)
            vk_scope = brain.task_scope(vk_task["id"])
            mad_scope = brain.task_scope(external["id"])
            self.assertEqual(vk_scope["completion_criteria"][0]["type"], "checkpoint_count")
            vk_module = next(item for item in brain.modules() if item["id"] == vk_scope["module_id"])
            mad_project = next(item for item in brain.projects() if item["id"] == mad_scope["project_id"])
            self.assertEqual(vk_module["key"], "vk-automation")
            self.assertEqual(mad_project["key"], "madclips")
            self.assertTrue(status["capabilities"]["multi_project"])
            self.assertTrue(status["capabilities"]["multi_module"])

    def test_manifest_registration_preserves_project_priority_and_view_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, _, brain = self._build(root)

            project = brain.project_by_key("sayuri-tsukishiro")
            self.assertEqual(project["priority"], 5)
            self.assertEqual(
                brain.normalize_task_context({"view": "disk"})["module_key"],
                "sayuri-disk",
            )

    def test_sync_does_not_overwrite_managed_cognitive_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            task = v4.create_task(
                "Долгая задача",
                next_action="Продолжить позже.",
                context={
                    "project_key": "sayuri-tsukishiro",
                    "module_key": "agent-core",
                    "completion_criteria": [{"type": "checkpoint_count", "min": 1}],
                },
            )
            brain.sync_tasks()
            brain.bind_task(
                task["id"],
                attention_state="later",
                confidence=0.91,
            )
            brain.set_completion_criteria(
                task["id"],
                [{"type": "checkpoint_count", "min": 3}],
            )

            brain.sync_tasks()
            scope = brain.task_scope(task["id"])

            self.assertEqual(scope["attention_state"], "later")
            self.assertAlmostEqual(scope["confidence"], 0.91)
            self.assertEqual(scope["completion_criteria"][0]["min"], 3)

    def test_dependency_graph_blocks_then_unlocks_scheduler(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            prerequisite = v4.create_task(
                "Собрать исходный материал",
                priority=4,
                next_action="Получить подтверждённый материал.",
                context={"module_key": "vk-automation"},
            )
            publish = v4.create_task(
                "Опубликовать материал VK",
                priority=5,
                next_action="Опубликовать подготовленный материал.",
                context={"module_key": "vk-automation"},
            )
            brain.sync_tasks()
            brain.add_dependency(
                publish["id"],
                prerequisite["id"],
                relation="requires",
                evidence_ref="test:explicit",
            )

            before = brain.scheduler("Опубликовать материал VK")
            blockers = brain.blockers(publish["id"])
            self.assertEqual(blockers[0]["task_id"], prerequisite["id"])
            self.assertNotEqual(before["selected"]["id"], publish["id"])
            self.assertGreaterEqual(before["blocked_by_dependencies"], 1)

            v4.update_task(prerequisite["id"], status="done")
            after = brain.scheduler("Опубликовать материал VK")
            self.assertEqual(brain.blockers(publish["id"]), [])
            self.assertEqual(after["selected"]["id"], publish["id"])

    def test_dependency_graph_rejects_cycles_and_cross_project_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            first = v4.create_task(
                "Первая задача",
                context={"project_key": "sayuri-tsukishiro"},
            )
            second = v4.create_task(
                "Вторая задача",
                context={"project_key": "sayuri-tsukishiro"},
            )
            external = v4.create_task(
                "Внешняя задача",
                context={"project_key": "external-project"},
            )
            brain.sync_tasks()
            brain.add_dependency(second["id"], first["id"], relation="requires")

            with self.assertRaises(CognitiveBrainError):
                brain.add_dependency(first["id"], second["id"], relation="requires")
            with self.assertRaises(CognitiveBrainError):
                brain.add_dependency(first["id"], external["id"], relation="requires")

    def test_unconfirmed_dependency_does_not_block_scheduler(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            prerequisite = v4.create_task("Черновой prerequisite", priority=1)
            target = v4.create_task("Главная задача", priority=5)
            brain.sync_tasks()
            brain.add_dependency(
                target["id"],
                prerequisite["id"],
                relation="requires",
                confirmed=False,
            )

            self.assertEqual(brain.blockers(target["id"]), [])
            self.assertEqual(brain.scheduler("Главная задача")["selected"]["id"], target["id"])

    def test_completion_criteria_become_ready_but_never_auto_complete_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            task = v4.create_task(
                "Создать структуру папок",
                priority=5,
                next_action="Создать папку Договоры.",
                context={
                    "module_key": "agent-core",
                    "completion_criteria": [
                        {"type": "tool_completed", "tool": "disk.create_folder", "min": 1},
                    ],
                },
            )
            brain.sync_tasks()
            before = brain.completion_assessment(task["id"])
            self.assertEqual(before["status"], "incomplete")

            checkpoint = v4.checkpoint_confirmed_action(
                {
                    "id": "action-folder-1",
                    "tool": "disk.create_folder",
                    "title": "Создать папку Договоры",
                    "status": "completed",
                    "result": {"status": "выполнено", "folder": {"id": "f1"}},
                },
                context={
                    "_task_lifecycle": {
                        "task_id": task["id"],
                        "task_updated_at": task["updated_at"],
                        "next_action_before": task["next_action"],
                    }
                },
            )
            observation = brain.observe_action(
                {
                    "id": "action-folder-1",
                    "tool": "disk.create_folder",
                    "title": "Создать папку Договоры",
                    "status": "completed",
                    "result": {"status": "выполнено", "folder": {"id": "f1"}},
                },
                context={"_task_lifecycle": {"task_id": task["id"]}},
                checkpoint=checkpoint,
            )
            after = brain.completion_assessment(task["id"])
            current = next(item for item in v4.tasks() if item["id"] == task["id"])

            self.assertEqual(after["status"], "ready_for_confirmation")
            self.assertEqual(after["score"], 1.0)
            self.assertFalse(after["automatic_completion"])
            self.assertEqual(current["status"], "in_progress")
            self.assertEqual(observation["strategy"]["success_count"], 1)
            self.assertEqual(
                brain.metacognition(task["id"])["state"],
                "ready_for_completion_confirmation",
            )

    def test_stale_unapplied_checkpoint_does_not_satisfy_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            task = v4.create_task(
                "Проверить структуру",
                next_action="Создать папку Проверка.",
                context={
                    "completion_criteria": [
                        {"type": "checkpoint_count", "min": 1},
                    ]
                },
            )
            brain.sync_tasks()
            snapshot = {
                "_task_lifecycle": {
                    "task_id": task["id"],
                    "task_updated_at": task["updated_at"],
                    "next_action_before": task["next_action"],
                }
            }
            v4.update_task(task["id"], next_action="Сначала проверить конфигурацию.")
            checkpoint = v4.checkpoint_confirmed_action(
                {
                    "id": "stale-checkpoint",
                    "tool": "disk.create_folder",
                    "title": "Создать папку Проверка",
                    "status": "completed",
                    "result": {"status": "выполнено"},
                },
                context=snapshot,
            )
            assessment = brain.completion_assessment(task["id"])

            self.assertFalse(checkpoint["applied"])
            self.assertEqual(assessment["status"], "incomplete")
            self.assertEqual(assessment["satisfied"], 0)

    def test_failure_creates_strategy_uncertainty_and_replan_without_mutating_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            task = v4.create_task(
                "Переместить документ",
                priority=5,
                next_action="Переместить договор в Архив.",
                context={"module_key": "agent-core"},
            )
            brain.sync_tasks()
            original_next = task["next_action"]
            result = brain.observe_action(
                {
                    "id": "action-move-failed",
                    "tool": "disk.move_current",
                    "status": "failed",
                    "error": "Папка назначения не найдена",
                },
                context={"_task_lifecycle": {"task_id": task["id"]}},
            )

            current = next(item for item in v4.tasks() if item["id"] == task["id"])
            self.assertEqual(current["next_action"], original_next)
            self.assertEqual(result["strategy"]["failure_count"], 1)
            self.assertEqual(result["uncertainty"]["severity"], "high")
            self.assertEqual(result["replan"]["status"], "proposed")
            self.assertFalse(result["replan"]["automatic_apply"])
            self.assertEqual(len(result["causal_links"]), 2)
            self.assertEqual(brain.metacognition(task["id"])["state"], "uncertain")
            self.assertTrue(brain.metacognition(task["id"])["causal_trace"])

            applied = brain.apply_replan(result["replan"]["id"])
            resolved = brain.resolve_uncertainty(
                result["uncertainty"]["id"],
                "Выбрать существующую папку назначения.",
            )
            current_after = next(item for item in v4.tasks() if item["id"] == task["id"])
            self.assertTrue(applied["applied"])
            self.assertIn("Проверить причину ошибки", current_after["next_action"])
            self.assertEqual(resolved["status"], "resolved")

    def test_replan_is_rejected_after_next_action_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            task = v4.create_task("Проверить импорт", next_action="Запустить импорт.")
            brain.sync_tasks()
            result = brain.observe_action(
                {
                    "id": "failed-import",
                    "tool": "disk.move_current",
                    "status": "failed",
                    "error": "Ошибка",
                },
                context={"_task_lifecycle": {"task_id": task["id"]}},
            )
            v4.update_task(task["id"], next_action="Сначала проверить конфигурацию.")

            with self.assertRaises(CognitiveBrainError):
                brain.apply_replan(result["replan"]["id"])

    def test_restart_restores_portfolio_graph_strategy_and_replan_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory, semantic, v3, v4, brain = self._build(root)
            prerequisite = v4.create_task(
                "Подготовить данные",
                priority=4,
                context={"module_key": "vk-automation"},
            )
            target = v4.create_task(
                "Запустить публикацию",
                priority=5,
                next_action="Опубликовать.",
                context={"module_key": "vk-automation"},
            )
            brain.sync_tasks()
            brain.add_dependency(target["id"], prerequisite["id"], relation="requires")
            brain.observe_action(
                {
                    "id": "restart-failure",
                    "tool": "disk.move_current",
                    "status": "failed",
                    "error": "Нет назначения",
                },
                context={"_task_lifecycle": {"task_id": target["id"]}},
            )

            memory2 = SayuriMemory(root / "data" / "sayuri-memory.db")
            memory2.initialize()
            semantic2 = SemanticMemoryIndex(memory2)
            v3_2 = MemorySystemV3(root / "data" / "sayuri-memory.db", memory2, semantic2)
            v4_2 = MemorySystemV4(root, memory2, semantic2, v3_2)
            brain2 = CognitiveProjectBrain(root, v4_2)
            brain2.bootstrap_manifest()

            self.assertEqual(brain2.blockers(target["id"])[0]["task_id"], prerequisite["id"])
            self.assertEqual(brain2.replan_proposals(target["id"])[0]["status"], "proposed")
            self.assertGreaterEqual(brain2.status()["counts"]["strategies"], 1)
            self.assertGreaterEqual(brain2.status()["counts"]["uncertainties"], 1)

    def test_read_only_status_does_not_implicitly_scope_new_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            before = brain.status()["counts"]["task_scopes"]
            v4.create_task("Новая несинхронизированная задача", priority=3)

            unchanged = brain.status()["counts"]["task_scopes"]
            self.assertEqual(unchanged, before)

            brain.sync_tasks()
            after = brain.status()["counts"]["task_scopes"]
            self.assertEqual(after, before + 1)

    def test_cloud_context_is_bounded_and_llm_mutation_policy_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            v4.create_task(
                "Развивать модуль VK",
                priority=5,
                next_action="Проверить зависимости.",
                context={"module_key": "vk-automation"},
            )
            brain.sync_tasks()

            context = brain.context(
                "что дальше по модулю VK",
                ui_context={"module_key": "vk-automation"},
                for_cloud=True,
            )

            self.assertEqual(context["mutation_policy"], "read_only_for_llm")
            module = context["scheduler"]["selected"]["module"]
            self.assertEqual(module["key"], "vk-automation")
            self.assertNotIn("path", module)
            self.assertNotIn("metadata", module)
            self.assertIn(
                context["metacognition"]["state"],
                {"actionable", "criteria_missing", "ready_for_completion_confirmation"},
            )
            self.assertLessEqual(len(context["scheduler"]["candidates"]), 8)


if __name__ == "__main__":
    unittest.main()
