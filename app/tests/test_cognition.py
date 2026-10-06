from __future__ import annotations

from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

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


    def test_register_module_merges_metadata_without_resetting_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, _, brain = self._build(root)
            before = brain.module_by_key("sayuri-tsukishiro", "agent-core")

            updated = brain.register_module(
                "sayuri-tsukishiro",
                "agent-core",
                metadata={"extra_contract": "kept"},
            )
            brain.bootstrap_manifest()
            after = brain.module_by_key("sayuri-tsukishiro", "agent-core")

            self.assertEqual(updated["title"], before["title"])
            self.assertEqual(after["title"], before["title"])
            self.assertEqual(after["metadata"]["extra_contract"], "kept")
            self.assertEqual(after["metadata"]["source"], "MODULES.json")
            self.assertEqual(
                brain.project_by_key("sayuri-tsukishiro")["priority"],
                5,
            )

    def test_scheduler_uses_portfolio_snapshot_not_per_task_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            for index in range(20):
                v4.create_task(
                    f"Масштабная задача {index}",
                    priority=(index % 5) + 1,
                    next_action=f"Проверить шаг {index}.",
                    context={"module_key": "agent-core"},
                )
            brain.sync_tasks()

            with patch.object(
                brain,
                "blockers",
                side_effect=AssertionError("scheduler must use snapshot blockers"),
            ), patch.object(
                brain,
                "uncertainties",
                side_effect=AssertionError("scheduler must use snapshot uncertainties"),
            ), patch.object(
                brain,
                "completion_assessment",
                side_effect=AssertionError("scheduler must use snapshot completion"),
            ):
                result = brain.scheduler("Масштабная задача 19")

            self.assertEqual(result["engine"], "cognitive-scheduler-v1.3")
            self.assertEqual(result["selected"]["id"], next(
                item["id"]
                for item in v4.tasks(limit=100)
                if item["title"] == "Масштабная задача 19"
            ))
            self.assertLessEqual(len(result["candidates"]), 8)

    def test_graph_integrity_detects_legacy_cycle_without_mutating_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            first = v4.create_task(
                "Legacy A",
                context={"project_key": "sayuri-tsukishiro"},
            )
            second = v4.create_task(
                "Legacy B",
                context={"project_key": "sayuri-tsukishiro"},
            )
            brain.sync_tasks()
            now = brain._now()
            with sqlite3.connect(root / "data" / "sayuri-memory.db") as db:
                db.execute(
                    """
                    INSERT INTO cognitive_task_edges(
                        id, source_task_id, target_task_id, relation,
                        evidence_ref, confirmed, created_at
                    ) VALUES(?, ?, ?, 'requires', 'legacy:test', 1, ?)
                    """,
                    ("legacy-edge-a", first["id"], second["id"], now),
                )
                db.execute(
                    """
                    INSERT INTO cognitive_task_edges(
                        id, source_task_id, target_task_id, relation,
                        evidence_ref, confirmed, created_at
                    ) VALUES(?, ?, ?, 'requires', 'legacy:test', 1, ?)
                    """,
                    ("legacy-edge-b", second["id"], first["id"], now),
                )

            integrity = brain.graph_integrity()

            self.assertEqual(integrity["status"], "issues")
            cycle = next(
                item for item in integrity["issues"]
                if item["type"] == "cycle"
            )
            self.assertEqual(
                set(cycle["task_ids"]),
                {first["id"], second["id"]},
            )
            self.assertEqual(len(brain.dependencies(first["id"])), 2)

    def test_high_uncertainty_forces_evidence_first_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            task = v4.create_task(
                "Подключить внешний API",
                priority=5,
                next_action="Выполнить интеграцию.",
                context={"module_key": "agent-core"},
            )
            brain.sync_tasks()
            scope = brain.task_scope(task["id"])
            brain.record_uncertainty(
                "Какой endpoint разрешён?",
                task_id=task["id"],
                project_id=scope["project_id"],
                module_id=scope["module_id"],
                severity="high",
                evidence_needed="Актуальная документация API",
            )

            result = brain.scheduler("Подключить внешний API")

            self.assertEqual(result["selected"]["id"], task["id"])
            self.assertEqual(
                result["selected"]["high_uncertainty_count"],
                1,
            )
            self.assertIn("доказательство", result["recommendation"].casefold())

    def test_cloud_context_strips_internal_strategy_causal_and_replan_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            task = v4.create_task(
                "Проверить безопасный контекст",
                priority=5,
                next_action="Выполнить проверку.",
                context={"module_key": "agent-core"},
            )
            brain.sync_tasks()
            failed = brain.observe_action(
                {
                    "id": "private-action-id",
                    "tool": "disk.move_current",
                    "status": "failed",
                    "error": "Проверочная ошибка",
                },
                context={"_task_lifecycle": {"task_id": task["id"]}},
            )
            self.assertIsNotNone(failed)

            cloud = brain.context(
                "Проверить безопасный контекст",
                ui_context={"module_key": "agent-core"},
                for_cloud=True,
            )

            self.assertTrue(cloud["strategies"])
            strategy = cloud["strategies"][0]
            self.assertNotIn("id", strategy)
            self.assertNotIn("project_id", strategy)
            self.assertNotIn("module_id", strategy)
            self.assertNotIn("updated_at", strategy)

            meta = cloud["metacognition"]
            self.assertNotIn("task_id", meta)
            self.assertTrue(meta["causal_trace"])
            causal = meta["causal_trace"][0]
            self.assertNotIn("source_id", causal)
            self.assertNotIn("effect_id", causal)
            self.assertNotIn("evidence_ref", causal)
            replan = meta["latest_replan"]
            self.assertIsNotNone(replan)
            self.assertNotIn("id", replan)
            self.assertNotIn("task_id", replan)
            self.assertNotIn("revision", replan)
            self.assertNotIn("evidence_ref", replan)

            module = cloud["scheduler"]["selected"]["module"]
            project = cloud["scheduler"]["selected"]["project"]
            self.assertEqual(set(module), {"key", "title"})
            self.assertEqual(set(project), {"key", "title"})


    def test_explicit_project_context_is_a_hard_scheduler_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            target = v4.create_task(
                "Задача проекта Alpha",
                priority=1,
                next_action="Продолжить Alpha.",
                context={"project_key": "alpha", "module_key": "alpha-core"},
            )
            v4.create_task(
                "Очень приоритетная задача Beta",
                priority=5,
                next_action="Продолжить Beta.",
                context={"project_key": "beta", "module_key": "beta-core"},
            )
            brain.sync_tasks()

            scheduled = brain.scheduler(
                "что дальше",
                context={"project_key": "alpha"},
            )

            self.assertEqual(scheduled["selected"]["id"], target["id"])
            self.assertTrue(
                all(
                    item["project"]["key"] == "alpha"
                    for item in scheduled["candidates"]
                )
            )

    def test_milestone_requires_done_tasks_and_explicit_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            task = v4.create_task(
                "Подготовить релиз Alpha",
                context={"project_key": "alpha", "module_key": "alpha-core"},
            )
            brain.sync_tasks()
            milestone = brain.register_milestone(
                "alpha",
                "alpha-release",
                title="Alpha Release",
                module_key="alpha-core",
                priority=5,
            )
            brain.link_milestone_task(milestone["id"], task["id"], required=True)

            before = brain.milestone_assessment(milestone["id"])
            self.assertEqual(before["status"], "incomplete")
            with self.assertRaises(CognitiveBrainError):
                brain.complete_milestone(
                    milestone["id"],
                    confirmation="COMPLETE_MILESTONE",
                )

            v4.update_task(task["id"], status="done")
            ready = brain.milestone_assessment(milestone["id"])
            self.assertEqual(ready["status"], "ready_for_confirmation")
            self.assertFalse(ready["automatic_completion"])
            self.assertEqual(
                brain.milestones(project_key="alpha")[0]["status"],
                "planned",
            )

            completed = brain.complete_milestone(
                milestone["id"],
                confirmation="COMPLETE_MILESTONE",
            )
            self.assertEqual(completed["milestone"]["status"], "done")

    def test_cross_project_external_blocker_unlocks_only_after_source_milestone_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            source_task = v4.create_task(
                "Подготовить платформенный API",
                priority=5,
                context={"project_key": "platform", "module_key": "platform-core"},
            )
            target_task = v4.create_task(
                "Подключить потребителя API",
                priority=5,
                next_action="Подключить API.",
                context={"project_key": "consumer", "module_key": "consumer-core"},
            )
            brain.sync_tasks()
            milestone = brain.register_milestone(
                "platform",
                "api-ready",
                title="API Ready",
                priority=5,
            )
            brain.link_milestone_task(
                milestone["id"],
                source_task["id"],
                required=True,
            )
            blocker = brain.add_external_blocker(
                "consumer",
                "platform-api",
                "Ожидается milestone API Ready",
                task_id=target_task["id"],
                source_project_key="platform",
                source_milestone_id=milestone["id"],
            )

            before = brain.scheduler(
                "Подключить потребителя API",
                context={"project_key": "consumer"},
            )
            self.assertIsNone(before["selected"])
            self.assertEqual(before["blocked_by_external"], 1)
            self.assertEqual(blocker["effective_status"], "open")

            v4.update_task(source_task["id"], status="done")
            self.assertEqual(
                brain.milestone_assessment(milestone["id"])["status"],
                "ready_for_confirmation",
            )
            still_blocked = brain.scheduler(
                "Подключить потребителя API",
                context={"project_key": "consumer"},
            )
            self.assertIsNone(still_blocked["selected"])

            brain.complete_milestone(
                milestone["id"],
                confirmation="COMPLETE_MILESTONE",
            )
            after = brain.scheduler(
                "Подключить потребителя API",
                context={"project_key": "consumer"},
            )
            self.assertEqual(after["selected"]["id"], target_task["id"])
            refreshed = brain.external_blockers(
                task_id=target_task["id"],
                effective_open_only=False,
            )
            self.assertEqual(refreshed[0]["effective_status"], "resolved")
            self.assertTrue(refreshed[0]["derived_resolution"])

    def test_portfolio_dependency_cycle_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, _, brain = self._build(root)
            brain.register_project("alpha", title="Alpha")
            brain.register_project("beta", title="Beta")
            brain.add_external_blocker(
                "beta",
                "wait-alpha",
                "Beta ожидает Alpha",
                source_project_key="alpha",
            )

            with self.assertRaises(CognitiveBrainError):
                brain.add_external_blocker(
                    "alpha",
                    "wait-beta",
                    "Alpha ожидает Beta",
                    source_project_key="beta",
                )

    def test_cloud_portfolio_projection_hides_local_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, v4, brain = self._build(root)
            source_task = v4.create_task(
                "Источник milestone",
                context={"project_key": "source-project"},
            )
            target_task = v4.create_task(
                "Целевая задача",
                priority=5,
                next_action="Продолжить после source milestone.",
                context={"project_key": "target-project"},
            )
            brain.sync_tasks()
            milestone = brain.register_milestone(
                "source-project",
                "source-ready",
                title="Source Ready",
            )
            brain.link_milestone_task(milestone["id"], source_task["id"])
            brain.add_external_blocker(
                "target-project",
                "source-wait",
                "Ожидается Source Ready",
                task_id=target_task["id"],
                source_project_key="source-project",
                source_milestone_id=milestone["id"],
            )

            cloud = brain.context(
                "Целевая задача",
                ui_context={"project_key": "target-project"},
                for_cloud=True,
            )

            candidates = cloud["scheduler"]["candidates"]
            self.assertTrue(candidates)
            candidate = candidates[0]
            self.assertNotIn("id", candidate)
            self.assertNotIn("project_id", candidate["project"])
            self.assertNotIn("module_id", candidate.get("module") or {})
            blocker = candidate["blockers"][0]
            self.assertNotIn("source_project_id", blocker)
            self.assertNotIn("source_milestone_id", blocker)
            self.assertNotIn("task_id", blocker)
            for item in cloud["portfolio"]["active_milestones"]:
                self.assertNotIn("id", item)

    def test_graph_integrity_reports_legacy_portfolio_cycle_without_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, _, brain = self._build(root)
            alpha = brain.register_project("alpha", title="Alpha")
            beta = brain.register_project("beta", title="Beta")
            now = brain._now()
            with sqlite3.connect(root / "data" / "sayuri-memory.db") as db:
                db.execute(
                    """
                    INSERT INTO cognitive_external_blockers(
                        id, project_id, module_id, task_id, blocker_key,
                        title, status, source_project_id, source_milestone_id,
                        evidence_ref, created_at
                    ) VALUES(?, ?, NULL, NULL, ?, ?, 'open', ?, NULL, ?, ?)
                    """,
                    (
                        "legacy-blocker-a",
                        alpha["id"],
                        "wait-beta",
                        "Alpha waits Beta",
                        beta["id"],
                        "legacy:test",
                        now,
                    ),
                )
                db.execute(
                    """
                    INSERT INTO cognitive_external_blockers(
                        id, project_id, module_id, task_id, blocker_key,
                        title, status, source_project_id, source_milestone_id,
                        evidence_ref, created_at
                    ) VALUES(?, ?, NULL, NULL, ?, ?, 'open', ?, NULL, ?, ?)
                    """,
                    (
                        "legacy-blocker-b",
                        beta["id"],
                        "wait-alpha",
                        "Beta waits Alpha",
                        alpha["id"],
                        "legacy:test",
                        now,
                    ),
                )

            integrity = brain.graph_integrity()
            self.assertEqual(integrity["status"], "issues")
            portfolio_cycle = next(
                item
                for item in integrity["issues"]
                if item["type"] == "portfolio_cycle"
            )
            self.assertEqual(
                set(portfolio_cycle["project_ids"]),
                {alpha["id"], beta["id"]},
            )
            self.assertEqual(
                len(brain.external_blockers(effective_open_only=True)),
                2,
            )



if __name__ == "__main__":
    unittest.main()
