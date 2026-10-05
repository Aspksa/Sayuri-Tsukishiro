from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from agent.memory import SayuriMemory
from agent.memory_v3 import MemorySystemV3
from agent.semantic_memory import SemanticMemoryIndex


class MemoryV3Tests(unittest.TestCase):
    def _build(self, root: Path):
        memory = SayuriMemory(root / "memory.db")
        memory.initialize()
        semantic = SemanticMemoryIndex(memory)
        v3 = MemorySystemV3(root / "memory.db", memory, semantic)
        return memory, semantic, v3

    def test_working_memory_tracks_current_focus_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3 = self._build(Path(tmp))

            working = v3.update_working(
                message="Проверь договор и найди противоречия",
                context={
                    "view": "disk",
                    "title": "Диск Sayuri",
                    "current_document": {
                        "id": "doc-1",
                        "name": "Договор.pdf",
                        "kind": "file",
                        "category": "contract",
                    },
                },
            )

            self.assertEqual(len(working["items"]), 2)
            focus = next(item for item in working["items"] if item["key"] == "current_focus")
            context = next(item for item in working["items"] if item["key"] == "current_context")
            self.assertIn("найди противоречия", focus["value"]["message"])
            self.assertEqual(context["value"]["current_document"]["name"], "Договор.pdf")

    def test_decision_promotes_to_knowledge_and_graph_keeps_document_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3 = self._build(Path(tmp))
            entry = memory.add(
                scope="project",
                kind="decision",
                content="Используем только DeepSeek-V4-Flash через Cloud.ru",
                importance=5,
                confidence=0.95,
                source_context={
                    "current_document": {
                        "id": "architecture-1",
                        "name": "ARCHITECTURE.md",
                        "kind": "file",
                        "category": "document",
                    }
                },
            )

            result = v3.ingest_memory(entry)
            graph = v3.graph()

            self.assertIsNotNone(result["knowledge"])
            self.assertEqual(result["knowledge"]["status"], "confirmed")
            node_types = {node["type"] for node in graph["nodes"]}
            self.assertIn("knowledge", node_types)
            self.assertIn("document", node_types)
            relations = {edge["relation"] for edge in graph["edges"]}
            self.assertIn("source_for", relations)
            self.assertIn("supports", relations)

    def test_consolidation_preserves_all_source_memory_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3 = self._build(Path(tmp))
            first = memory.add(
                scope="project",
                kind="fact",
                content="Интерфейс проекта Sayuri должен быть светлым и компактным",
                importance=4,
                confidence=0.76,
            )
            second = memory.add(
                scope="project",
                kind="fact",
                content="Интерфейс проекта Sayuri должен быть светлым и очень компактным",
                importance=4,
                confidence=0.78,
            )

            result = v3.consolidate()
            knowledge = v3.knowledge()

            self.assertGreaterEqual(result["created"], 1)
            source_sets = [set(item["source_memory_ids"]) for item in knowledge]
            self.assertTrue(any({first["id"], second["id"]}.issubset(ids) for ids in source_sets))

    def test_forgetting_engine_reduces_weight_without_deleting_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory, semantic, v3 = self._build(root)
            entry = memory.add(
                scope="project",
                kind="note",
                content="Старая малозначимая техническая заметка",
                importance=1,
                confidence=0.2,
            )
            old = (datetime.now(timezone.utc) - timedelta(days=900)).isoformat()
            with sqlite3.connect(root / "memory.db") as db:
                db.execute(
                    "UPDATE memory_entries SET updated_at = ?, last_used_at = NULL WHERE id = ?",
                    (old, entry["id"]),
                )

            retention = v3.evaluate_retention()
            after = memory.get(entry["id"])

            self.assertIsNotNone(after)
            self.assertLess(after["retention_score"], v3.STALE_THRESHOLD)
            self.assertEqual(retention["stale_count"], 1)

            found = semantic.search(
                "старая малозначимая техническая заметка",
                scopes=("project",),
                minimum_score=0.0,
            )
            self.assertEqual(found["project"][0]["id"], entry["id"])
            self.assertLess(found["project"][0]["semantic_match"]["retention_score"], 0.30)

    def test_conflict_resolver_soft_archives_old_memory_and_keeps_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3 = self._build(Path(tmp))
            old = memory.add(
                scope="personal",
                kind="preference",
                content="Я предпочитаю тёмный интерфейс",
                importance=4,
                confidence=0.9,
            )
            new = memory.add(
                scope="personal",
                kind="preference",
                content="Я предпочитаю светлый интерфейс",
                importance=4,
                confidence=0.95,
                supersedes_id=old["id"],
            )
            conflict = v3.register_conflict(
                candidate_id="candidate-1",
                old_memory_id=old["id"],
                new_memory_id=new["id"],
                scope="personal",
            )

            resolved = v3.resolve_conflict(conflict["id"], "prefer_new")

            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(resolved["resolution"], "prefer_new")
            self.assertIsNone(memory.get(old["id"]))
            self.assertIsNotNone(memory.get(new["id"]))
            events = [item["event_type"] for item in v3.timeline()]
            self.assertIn("memory_conflict_opened", events)
            self.assertIn("memory_conflict_resolved", events)

    def test_episodic_memory_reuses_fingerprint_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3 = self._build(Path(tmp))
            first = v3.record_episode(
                event_type="chat_feedback",
                summary="Ответ полезен",
                scope="system",
                source="user_feedback",
                importance=3,
                fingerprint="chat_feedback:resp-1",
            )
            second = v3.record_episode(
                event_type="chat_feedback",
                summary="Ответ не помог",
                scope="system",
                source="user_feedback",
                importance=3,
                fingerprint="chat_feedback:resp-1",
            )

            self.assertEqual(first["id"], second["id"])
            episodes = v3.episodes()
            self.assertEqual(len(episodes), 1)
            self.assertEqual(episodes[0]["summary"], "Ответ не помог")

    def test_knowledge_graph_preserves_source_memory_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3 = self._build(Path(tmp))
            entry = memory.add(
                scope="project",
                kind="decision",
                content="Проект использует только DeepSeek-V4-Flash",
                importance=5,
                confidence=0.98,
            )

            v3.ingest_memory(entry)
            graph = v3.graph()
            memory_node = next(
                node
                for node in graph["nodes"]
                if node["type"] == "memory" and node["key"] == entry["id"]
            )

            self.assertIn("DeepSeek-V4-Flash", memory_node["label"])
            self.assertNotEqual(memory_node["label"], "Источник знания")
            self.assertNotEqual(memory_node["label"], "Предыдущая версия памяти")

    def test_exact_episode_retry_does_not_duplicate_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3 = self._build(Path(tmp))
            kwargs = {
                "event_type": "chat_feedback",
                "summary": "Ответ полезен",
                "scope": "system",
                "source": "user_feedback",
                "importance": 3,
                "fingerprint": "chat_feedback:resp-idempotent",
            }

            first = v3.record_episode(**kwargs)
            timeline_after_first = len(v3.timeline())
            second = v3.record_episode(**kwargs)
            timeline_after_second = len(v3.timeline())

            self.assertEqual(first["id"], second["id"])
            self.assertEqual(timeline_after_first, timeline_after_second)

    def test_conflict_retry_does_not_duplicate_opened_timeline_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3 = self._build(Path(tmp))
            old = memory.add(
                scope="personal",
                kind="preference",
                content="Я предпочитаю тёмный интерфейс",
                importance=4,
                confidence=0.9,
            )
            new = memory.add(
                scope="personal",
                kind="preference",
                content="Я предпочитаю светлый интерфейс",
                importance=4,
                confidence=0.95,
                supersedes_id=old["id"],
            )

            first = v3.register_conflict(
                candidate_id="same-candidate",
                old_memory_id=old["id"],
                new_memory_id=new["id"],
                scope="personal",
            )
            second = v3.register_conflict(
                candidate_id="same-candidate",
                old_memory_id=old["id"],
                new_memory_id=new["id"],
                scope="personal",
            )
            opened = [
                item
                for item in v3.timeline()
                if item["event_type"] == "memory_conflict_opened"
            ]

            self.assertEqual(first["id"], second["id"])
            self.assertEqual(len(opened), 1)

    def test_graph_extracts_company_and_episode_event_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3 = self._build(Path(tmp))
            entry = memory.add(
                scope="project",
                kind="fact",
                content='Контрагент ООО «Альфа Сервис» указан в договоре',
                importance=4,
                confidence=0.9,
            )
            v3.ingest_memory(entry)
            v3.record_episode(
                event_type="document_reviewed",
                summary="Проверен договор с ООО Альфа Сервис",
                scope="project",
                source="test",
                importance=3,
            )

            graph = v3.graph()
            node_types = {node["type"] for node in graph["nodes"]}
            self.assertIn("company", node_types)
            self.assertIn("event", node_types)
            self.assertIn("experienced", {edge["relation"] for edge in graph["edges"]})

    def test_archiving_only_source_closes_derived_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3 = self._build(Path(tmp))
            entry = memory.add(
                scope="project",
                kind="decision",
                content="Memory 3.0 должна сохранять provenance",
                importance=5,
                confidence=0.98,
            )
            promoted = v3.ingest_memory(entry)["knowledge"]
            self.assertEqual(promoted["status"], "confirmed")

            self.assertTrue(memory.delete(entry["id"]))
            v3.archive_memory(entry)

            knowledge = v3.get_knowledge(promoted["id"])
            self.assertEqual(knowledge["status"], "archived")
            self.assertIsNotNone(knowledge["valid_to"])

    def test_open_conflict_is_explicit_in_ai_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3 = self._build(Path(tmp))
            old = memory.add(
                scope="personal",
                kind="preference",
                content="Я предпочитаю тёмный интерфейс",
                importance=4,
                confidence=0.9,
            )
            new = memory.add(
                scope="personal",
                kind="preference",
                content="Я предпочитаю светлый интерфейс",
                importance=4,
                confidence=0.95,
                supersedes_id=old["id"],
            )
            v3.register_conflict(
                candidate_id="candidate-context",
                old_memory_id=old["id"],
                new_memory_id=new["id"],
                scope="personal",
            )

            context = v3.context("какой интерфейс я предпочитаю")

            self.assertEqual(context["open_conflicts"], 1)
            self.assertEqual(len(context["conflicts"]), 1)
            self.assertIn("тёмный", context["conflicts"][0]["old_content"])
            self.assertIn("светлый", context["conflicts"][0]["new_content"])

    def test_maintenance_bootstraps_knowledge_graph_and_temporal_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory, semantic, v3 = self._build(Path(tmp))
            memory.add(
                scope="project",
                kind="decision",
                content="Любое изменение проекта требует новой версии",
                importance=5,
                confidence=0.98,
            )
            memory.add(
                scope="project",
                kind="note",
                content="Временная заметка для проверки retention",
                importance=2,
                confidence=0.5,
            )

            result = v3.maintenance()
            dashboard = v3.dashboard()

            self.assertEqual(result["status"], "готово")
            self.assertGreaterEqual(dashboard["stats"]["knowledge"], 1)
            self.assertGreaterEqual(dashboard["stats"]["graph_nodes"], 1)
            self.assertTrue(dashboard["timeline"])


if __name__ == "__main__":
    unittest.main()
