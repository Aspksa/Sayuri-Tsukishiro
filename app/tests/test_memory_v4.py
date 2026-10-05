from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from agent.memory import SayuriMemory
from agent.memory_v3 import MemorySystemV3
from agent.memory_v4 import MemorySystemV4, MemorySystemV4Error
from agent.semantic_memory import SemanticMemoryIndex


class MemoryV4Tests(unittest.TestCase):
    def _build(self, root: Path):
        (root / "VERSION").write_text("0.1.44\n", encoding="utf-8")
        memory = SayuriMemory(root / "data" / "sayuri-memory.db")
        memory.initialize()
        semantic = SemanticMemoryIndex(memory)
        v3 = MemorySystemV3(root / "data" / "sayuri-memory.db", memory, semantic)
        v4 = MemorySystemV4(root, memory, semantic, v3)
        return memory, semantic, v3, v4

    def test_secret_memory_is_local_only_and_normal_memory_has_trust_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3, v4 = self._build(Path(tmp))
            secret = memory.add(
                scope="personal",
                kind="note",
                content="API key: abcdefghijklmnopqrstuvwxyz",
                importance=5,
                source="manual",
            )
            normal = memory.add(
                scope="project",
                kind="decision",
                content="Используем только DeepSeek-V4-Flash через Cloud.ru",
                importance=5,
                confidence=0.98,
                source="memory_intelligence_confirmed",
            )

            secret_state = v4.ingest_memory(secret)["state"]
            normal_state = v4.ingest_memory(normal)["state"]

            self.assertEqual(secret_state["sensitivity"], "secret")
            self.assertFalse(secret_state["cloud_allowed"])
            self.assertGreaterEqual(normal_state["source_trust"], 0.90)
            self.assertEqual(normal_state["tier"], "hot")

    def test_cloud_recall_excludes_sensitive_memory_but_local_recall_can_show_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3, v4 = self._build(Path(tmp))
            secret = memory.add(
                scope="personal",
                kind="note",
                content="Пароль: verysecret12345 для тестового стенда",
                importance=5,
                source="manual",
            )
            normal = memory.add(
                scope="personal",
                kind="preference",
                content="Я предпочитаю светлый компактный интерфейс",
                importance=5,
                confidence=0.95,
                source="memory_intelligence_confirmed",
            )
            v4.ingest_memory(secret)
            v4.ingest_memory(normal)

            local = v4.recall(
                "пароль тестового стенда",
                scopes=("personal",),
                limit=10,
                for_cloud=False,
            )
            cloud = v4.recall(
                "пароль тестового стенда",
                scopes=("personal",),
                limit=10,
                for_cloud=True,
            )

            self.assertTrue(any(item["id"] == secret["id"] for item in local["personal"]))
            self.assertFalse(any(item["id"] == secret["id"] for item in cloud["personal"]))

    def test_explainable_recall_feedback_updates_utility_and_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3, v4 = self._build(Path(tmp))
            entry = memory.add(
                scope="project",
                kind="fact",
                content="ДНК документа автоматически запускается после загрузки PDF",
                importance=4,
                confidence=0.92,
                source="memory_intelligence_confirmed",
            )
            v4.ingest_memory(entry)

            recall = v4.recall(
                "когда запускается анализ днк pdf",
                scopes=("project",),
                limit=5,
                for_cloud=True,
            )
            self.assertTrue(recall["project"])
            selected = recall["project"][0]
            self.assertTrue(selected["recall_explanation"]["why"])
            self.assertIn(selected["v4"]["tier"], {"hot", "warm", "cold"})

            v4.bind_response("response-1", recall["recall_id"])
            result = v4.apply_response_feedback("response-1", "useful")
            state = v4.state_for(entry["id"])
            dashboard = v4.dashboard()
            source = next(
                item for item in dashboard["sources"]
                if item["source_key"] == "memory_intelligence_confirmed"
            )

            self.assertGreaterEqual(result["updated"], 1)
            self.assertEqual(state["helpful_count"], 1)
            self.assertGreater(state["utility_score"], 0.5)
            self.assertEqual(source["evidence_count"], 1)
            self.assertEqual(source["last_outcome"], "useful")

    def test_goal_task_and_decision_memory_are_structured_and_graph_linked(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3, v4 = self._build(Path(tmp))
            goal = v4.create_goal(
                "Создать устойчивую автономную Sayuri",
                description="Память, планирование и проверка результата.",
                priority=5,
            )
            task = v4.create_task(
                "Подключить Result Verifier",
                goal_id=goal["id"],
                priority=4,
                next_action="Спроектировать контракт проверки.",
            )
            updated = v4.update_task(
                task["id"],
                status="blocked",
                blocked_reason="Сначала нужен Reasoning Planner.",
            )
            decision_memory = memory.add(
                scope="project",
                kind="decision",
                content="Используем одну внешнюю модель, потому что архитектура должна оставаться управляемой",
                importance=5,
                confidence=0.98,
                source="manual",
            )
            result = v4.ingest_memory(decision_memory)
            graph = v3.graph(limit_nodes=200, limit_edges=400)

            self.assertEqual(updated["status"], "blocked")
            self.assertEqual(updated["goal_id"], goal["id"])
            self.assertIsNotNone(result["decision"])
            self.assertIn("архитектура должна оставаться управляемой", result["decision"]["rationale"])
            self.assertEqual(result["decision"]["project_version"], "0.1.44")
            self.assertIn("goal", {node["type"] for node in graph["nodes"]})
            self.assertIn("task", {node["type"] for node in graph["nodes"]})
            self.assertIn("has_task", {edge["relation"] for edge in graph["edges"]})

    def test_task_and_goal_can_be_created_automatically_from_confirmed_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3, v4 = self._build(Path(tmp))
            task_memory = memory.add(
                scope="project",
                kind="task",
                content="Проверить целостность памяти после миграции",
                importance=4,
                confidence=0.9,
                source="memory_intelligence_confirmed",
            )
            goal_memory = memory.add(
                scope="project",
                kind="fact",
                content="Главная цель проекта — сделать Sayuri устойчивой личной помощницей",
                importance=5,
                confidence=0.95,
                source="memory_intelligence_confirmed",
            )

            task_result = v4.ingest_memory(task_memory)
            goal_result = v4.ingest_memory(goal_memory)

            self.assertIsNotNone(task_result["task"])
            self.assertIsNotNone(goal_result["goal"])
            self.assertEqual(len(v4.tasks()), 1)
            self.assertEqual(len(v4.goals()), 1)

    def test_failure_memory_is_resolved_by_later_success_and_creates_causal_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3, v4 = self._build(Path(tmp))
            failed = {
                "id": "action-failed",
                "tool": "disk.create_folder",
                "status": "failed",
                "title": "Создать папку",
                "error": "Папка уже существует",
            }
            completed = {
                "id": "action-success",
                "tool": "disk.create_folder",
                "status": "completed",
                "title": "Создать папку",
                "result": {"folder": {"name": "Архив"}},
            }

            failure = v4.record_action_outcome(failed)
            resolved = v4.record_action_outcome(completed)

            self.assertEqual(failure["status"], "open")
            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(resolved["resolved_count"], 1)
            with v4._connect() as db:
                causal = db.execute(
                    """
                    SELECT relation FROM memory_causal_links
                    WHERE cause_id=? AND effect_id=?
                    """,
                    (failure["id"], "action-success"),
                ).fetchone()
            self.assertIsNotNone(causal)
            self.assertEqual(causal["relation"], "resolved_by")

    def test_conflict_opens_question_and_resolution_closes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3, v4 = self._build(Path(tmp))
            old = memory.add(
                scope="personal",
                kind="preference",
                content="Я предпочитаю тёмную тему",
                importance=4,
                confidence=0.9,
            )
            new = memory.add(
                scope="personal",
                kind="preference",
                content="Я предпочитаю светлую тему",
                importance=4,
                confidence=0.95,
                supersedes_id=old["id"],
            )
            conflict = v3.register_conflict(
                candidate_id="candidate-v4",
                old_memory_id=old["id"],
                new_memory_id=new["id"],
                scope="personal",
            )

            question = v4.register_conflict_question(conflict)
            self.assertEqual(question["status"], "open")
            self.assertIn(conflict["id"], question["related_ids"])

            v3.resolve_conflict(conflict["id"], "prefer_new")
            v4.resolve_conflict_question(conflict["id"], "prefer_new")
            questions = v4.questions(status=None)
            stored = next(item for item in questions if item["id"] == question["id"])
            self.assertEqual(stored["status"], "resolved")

    def test_freshness_decay_and_manual_source_trust_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory, semantic, v3, v4 = self._build(root)
            entry = memory.add(
                scope="project",
                kind="fact",
                content="Текущая версия API: 2025-01",
                importance=3,
                confidence=0.8,
                source="document",
            )
            old = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
            with sqlite3.connect(root / "data" / "sayuri-memory.db") as db:
                db.execute(
                    "UPDATE memory_entries SET updated_at=?, created_at=? WHERE id=?",
                    (old, old, entry["id"]),
                )
            entry = memory.get(entry["id"])
            state = v4.evaluate_entry(entry)

            self.assertEqual(state["freshness_class"], "volatile")
            self.assertLess(state["freshness_score"], 0.10)

            profile = v4.set_source_trust("document", 0.55)
            state = v4.state_for(entry["id"])
            self.assertAlmostEqual(profile["trust_score"], 0.55, places=4)
            self.assertAlmostEqual(state["source_trust"], 0.55, places=4)

    def test_integrity_and_snapshot_restore_with_pre_restore_safety_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory, semantic, v3, v4 = self._build(root)
            first = memory.add(
                scope="project",
                kind="decision",
                content="Снимки памяти должны быть проверяемыми",
                importance=5,
                confidence=0.98,
            )
            v3.ingest_memory(first)
            v4.ingest_memory(first)
            snapshot = v4.create_snapshot("unit-test")

            second = memory.add(
                scope="project",
                kind="note",
                content="Эта запись должна исчезнуть после восстановления снимка",
                importance=3,
            )
            v4.ingest_memory(second)
            self.assertIsNotNone(memory.get(second["id"]))

            restored = v4.restore_snapshot(snapshot["id"], "RESTORE MEMORY")

            self.assertEqual(restored["status"], "восстановлено")
            self.assertEqual(restored["integrity"]["status"], "ok")
            self.assertIsNotNone(memory.get(first["id"]))
            self.assertIsNone(memory.get(second["id"]))
            self.assertTrue(restored["pre_restore_snapshot"]["id"])
            listed = v4.snapshots()
            ids = {item["id"] for item in listed}
            self.assertIn(snapshot["id"], ids)
            self.assertIn(restored["pre_restore_snapshot"]["id"], ids)

    def test_snapshot_restore_rejects_missing_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3, v4 = self._build(Path(tmp))
            snapshot = v4.create_snapshot("confirmation-test")
            with self.assertRaises(MemorySystemV4Error):
                v4.restore_snapshot(snapshot["id"], "yes")

    def test_integrity_reports_clean_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3, v4 = self._build(Path(tmp))
            result = v4.integrity_check()
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["issues"], [])


if __name__ == "__main__":
    unittest.main()
