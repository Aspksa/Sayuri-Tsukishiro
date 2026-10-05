from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from disk import DiskService
from disk.dna_evolution import DNAEvolutionEngine


class DNAEvolutionEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = DNAEvolutionEngine()

    @staticmethod
    def fact(
        fact_id: str,
        fact_type: str,
        canonical: str,
        *,
        role: str = "",
        gate: str = "accepted",
        confidence: float = 0.95,
    ) -> dict:
        return {
            "id": fact_id,
            "type": fact_type,
            "role": role,
            "label": fact_type,
            "value": canonical,
            "normalized": {"canonical": canonical},
            "confidence": confidence,
            "quality_gate": gate,
            "source": {
                "line": 1,
                "excerpt": canonical,
                "evidence_hash": "a" * 64,
            },
        }

    def dna(self, file_id: str, facts: list[dict], *, document_type: str = "Договор") -> dict:
        return {
            "identity": {"file_id": file_id},
            "classification": {"document_type": document_type, "confidence": 0.9},
            "profile": {"completeness_percent": 90},
            "molecules": {"facts": facts},
            "entities": [],
            "dependencies": {"items": []},
            "quality_gate": {
                "accepted": sum(1 for fact in facts if fact["quality_gate"] == "accepted"),
                "review": sum(1 for fact in facts if fact["quality_gate"] == "review"),
                "rejected": sum(1 for fact in facts if fact["quality_gate"] == "rejected"),
                "memory_ready": True,
                "reasons": [],
            },
            "epistemics": {"facts": len(facts), "hypotheses": 0},
        }

    def test_regression_guard_blocks_loss_of_verified_facts(self):
        previous = self.dna(
            "old",
            [
                self.fact("f1", "date", "2026-10-05", role="document_date"),
                self.fact("f2", "document_number", "55", role="primary_document_number"),
                self.fact("f3", "amount", "100000.00 RUB", role="total_amount"),
                self.fact("f4", "inn", "1234567890"),
            ],
        )
        current = self.dna(
            "old",
            [
                self.fact("f1", "date", "2026-10-05", role="document_date"),
                self.fact("f2", "document_number", "55", role="primary_document_number"),
            ],
        )

        guard = self.engine._regression_guard(previous, current)
        self.assertEqual(guard["status"], "blocked")
        self.assertEqual(guard["lost_verified_facts"], 2)
        self.assertIn("lost_verified_facts", guard["reasons"])

    def test_adaptive_profile_learns_only_from_sufficient_corpus(self):
        current = self.dna(
            "current",
            [self.fact("f1", "date", "2026-10-05")],
            document_type="Счёт",
        )
        corpus = []
        for index in range(5):
            corpus.append(
                self.dna(
                    f"doc-{index}",
                    [
                        self.fact(f"d-{index}", "date", "2026-10-05"),
                        self.fact(f"a-{index}", "amount", "1000.00 RUB", role="total_amount"),
                        self.fact(f"n-{index}", "document_number", str(index + 1)),
                    ],
                    document_type="Счёт",
                )
            )

        profile = self.engine._adaptive_profile(current, corpus)
        self.assertEqual(profile["status"], "learned")
        missing_types = {item["type"] for item in profile["missing_learned_expected"]}
        self.assertIn("amount", missing_types)
        self.assertIn("document_number", missing_types)

    def test_rule_lifecycle_stays_shadow_when_corrections_conflict(self):
        lifecycle = self.engine._rule_lifecycle(
            [
                {
                    "fact_type": "amount",
                    "original_canonical": "10000.00 RUB",
                    "corrected": {"canonical": "12500.00 RUB"},
                    "support_count": 4,
                },
                {
                    "fact_type": "amount",
                    "original_canonical": "10000.00 RUB",
                    "corrected": {"canonical": "13000.00 RUB"},
                    "support_count": 2,
                },
            ]
        )
        self.assertEqual(lifecycle["counts"]["shadow"], 1)
        self.assertEqual(lifecycle["items"][0]["status"], "shadow")

    def test_repeated_cooccurrence_creates_hypothesis_not_fact(self):
        entity_a = {"canonical_key": "организация:ооо ромашка"}
        entity_b = {"canonical_key": "транспорт:а123вс25"}
        current = self.dna("current", [])
        current["entities"] = [entity_a, entity_b]

        corpus = []
        for index in range(3):
            item = self.dna(f"doc-{index}", [])
            item["entities"] = [entity_a, entity_b]
            corpus.append(item)

        hypotheses = self.engine._association_hypotheses(current, corpus)
        self.assertGreaterEqual(hypotheses["count"], 1)
        hypothesis = hypotheses["items"][0]
        self.assertEqual(hypothesis["status"], "hypothesis")
        self.assertFalse(hypothesis["causal"])
        self.assertFalse(hypothesis["promotion_allowed"])


class DNAEvolutionServiceTests(unittest.TestCase):
    def make_service(self, root: Path) -> DiskService:
        service = DiskService(root / "sayuri.db", root / "disk")
        service.initialize()
        return service

    def test_evolution_layer_registry_status_and_reanalysis_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.make_service(root)
            payload = (
                "ДОГОВОР № 55\n"
                "Дата: 05.10.2026\n"
                "ООО Ромашка ИНН 1234567890\n"
                "Автомобиль А123ВС25\n"
                "Итого 100 000 руб.\n"
            ).encode("utf-8")
            item = service.store_stream(
                name="договор 55.txt",
                content_type="text/plain",
                size_bytes=len(payload),
                stream=BytesIO(payload),
            )

            first = service.document_dna(item["id"])
            self.assertEqual(first["evolution"]["engine_version"], "0.6.0")
            self.assertIn("self_review", first["evolution"])
            self.assertIn("regression_guard", first["evolution"])
            self.assertIn("active_learning", first["evolution"])
            self.assertGreater(first["global_entities"]["count"], 0)
            self.assertEqual(service.health()["schema_version"], 7)
            self.assertEqual(service.health()["dna_evolution_version"], "0.6.0")

            history_before = service.dna_history(item["id"])
            repeated = service.document_dna(item["id"], force=True)
            history_after = service.dna_history(item["id"])
            self.assertTrue(repeated["reanalysis_deduplicated"])
            self.assertEqual(len(history_before), len(history_after))

            deep = service.document_dna(
                item["id"],
                force=True,
                bypass_cooldown=True,
            )
            self.assertFalse(deep["reanalysis_deduplicated"])
            self.assertEqual(len(service.dna_history(item["id"])), len(history_before) + 1)
            self.assertEqual(deep["version_delta"]["reason"], "deep_reanalysis")

            status = service.evolution_status()
            self.assertEqual(status["engine_version"], "0.6.0")
            self.assertEqual(status["documents"], 1)
            self.assertGreater(status["global_entities"], 0)

            plan = service.reanalysis_plan()
            self.assertEqual(plan["engine_version"], "0.6.0")
            self.assertEqual(plan["count"], 0)

    def test_global_entity_registry_merges_same_real_entity_across_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.make_service(root)

            for index in range(2):
                text = (
                    f"ДОГОВОР № {index + 1}\n"
                    "Дата: 05.10.2026\n"
                    "ООО Ромашка ИНН 1234567890\n"
                    "Итого 10 000 руб.\n"
                )
                item = service.store_stream(
                    name=f"договор {index + 1}.txt",
                    content_type="text/plain",
                    size_bytes=len(text.encode("utf-8")),
                    stream=BytesIO(text.encode("utf-8")),
                )
                service.document_dna(item["id"])

            status = service.evolution_status()
            self.assertEqual(status["documents"], 2)
            self.assertGreaterEqual(status["entity_mentions"], 2)

            with service._session() as db:
                rows = db.execute(
                    """
                    SELECT category, canonical_id, document_count
                    FROM disk_dna_entities
                    WHERE category = 'Организация'
                    ORDER BY document_count DESC
                    """
                ).fetchall()
            self.assertTrue(rows)
            self.assertGreaterEqual(rows[0]["document_count"], 2)


if __name__ == "__main__":
    unittest.main()
