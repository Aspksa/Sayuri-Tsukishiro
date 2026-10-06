from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from agent.tool_planner import EvidenceToolPlanner


ROOT = Path(__file__).resolve().parents[2]


class EvidenceToolPlannerTests(unittest.TestCase):
    def test_read_only_execution_is_deduplicated_and_secret_fields_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = EvidenceToolPlanner(Path(tmp) / "receipts.db")
            calls = 0

            def handler(args):
                nonlocal calls
                calls += 1
                self.assertEqual(args, {})
                return {
                    "data": {
                        "ok": True,
                        "api_key": "must-not-leak",
                        "nested": {"secret": "must-not-leak", "count": 3},
                    },
                    "evidence_refs": ["system:test"],
                }

            plan = {
                "steps": ["Проверить систему"],
                "tool_intents": [
                    {"step": 1, "tool": "system.status", "args": {}, "purpose": "Статус"},
                    {"step": 1, "tool": "system.status", "args": {}, "purpose": "Дубликат"},
                ],
            }
            result = planner.execute_plan(
                plan,
                handlers={"system.status": handler},
                request_id="req-1",
            )

            self.assertEqual(calls, 1)
            self.assertEqual(result["read_only_calls"], 1)
            self.assertEqual(result["receipts"][0]["status"], "completed")
            self.assertEqual(result["receipts"][1]["status"], "skipped_duplicate")
            preview = result["receipts"][0]["output_preview"]
            self.assertNotIn("api_key", preview)
            self.assertNotIn("secret", preview["nested"])
            self.assertTrue(result["receipts"][0]["output_sha256"])
            self.assertTrue(result["cloud_evidence"])
            self.assertEqual(len(planner.recent(10)), 2)

    def test_evidence_needed_can_trigger_safe_background_check_without_model_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = EvidenceToolPlanner(Path(tmp) / "receipts.db")
            calls = 0

            def handler(args):
                nonlocal calls
                calls += 1
                self.assertEqual(args, {})
                return {
                    "data": {"status": "ok"},
                    "evidence_refs": ["system:auto"],
                }

            result = planner.execute_plan(
                {
                    "goal": "Проверить состояние системы перед выводом",
                    "steps": ["Сверить факты"],
                    "evidence_needed": ["Текущее состояние системы"],
                    "tool_intents": [],
                },
                handlers={"system.status": handler},
                request_id="req-auto",
            )

            self.assertEqual(calls, 1)
            self.assertEqual(result["read_only_calls"], 1)
            self.assertEqual(result["receipts"][0]["tool"], "system.status")
            self.assertEqual(result["receipts"][0]["status"], "completed")

    def test_mutation_intent_never_executes_without_action_broker(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = EvidenceToolPlanner(Path(tmp) / "receipts.db")
            called = False

            def forbidden_handler(_args):
                nonlocal called
                called = True
                raise AssertionError("mutation handler must never run")

            result = planner.execute_plan(
                {
                    "steps": ["Создать папку"],
                    "tool_intents": [
                        {
                            "step": 1,
                            "tool": "disk.create_folder",
                            "args": {"name": "Нельзя доверять модели"},
                            "purpose": "Изменение проекта",
                        }
                    ],
                },
                handlers={"disk.create_folder": forbidden_handler},
                request_id="req-2",
            )

            self.assertFalse(called)
            receipt = result["receipts"][0]
            self.assertEqual(receipt["mode"], "confirmation_gated")
            self.assertEqual(receipt["status"], "requires_action_broker")
            self.assertEqual(receipt["args"], {})
            self.assertEqual(result["read_only_calls"], 0)

    def test_unknown_tool_is_rejected_and_catalog_marks_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = EvidenceToolPlanner(Path(tmp) / "receipts.db")
            result = planner.execute_plan(
                {
                    "steps": ["Проверить"],
                    "tool_intents": [
                        {"step": 1, "tool": "shell.exec", "args": {"cmd": "whoami"}}
                    ],
                },
                handlers={},
                request_id="req-3",
            )
            self.assertEqual(result["receipts"][0]["status"], "rejected")
            catalog = {item["id"]: item for item in planner.catalog()}
            self.assertEqual(catalog["memory.search"]["mode"], "read_only")
            self.assertFalse(catalog["memory.search"]["confirmation_required"])
            self.assertEqual(catalog["memory.remember"]["mode"], "confirmation_gated")
            self.assertTrue(catalog["memory.remember"]["confirmation_required"])

    def test_large_output_is_bounded_before_cloud_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = EvidenceToolPlanner(Path(tmp) / "receipts.db")

            result = planner.execute_plan(
                {
                    "steps": ["Проверить"],
                    "tool_intents": [
                        {"step": 1, "tool": "system.status", "args": {}, "purpose": "Большой результат"}
                    ],
                },
                handlers={
                    "system.status": lambda _args: {
                        "data": {"payload": "x" * 20000},
                        "evidence_refs": ["system:large"],
                    }
                },
                request_id="req-large",
            )

            self.assertEqual(result["receipts"][0]["status"], "completed")
            self.assertTrue(result["cloud_evidence"])
            output = result["cloud_evidence"][0]["output"]
            self.assertTrue(isinstance(output, dict))
            self.assertTrue(output.get("truncated"))

    def test_receipt_api_contract_is_exposed(self):
        core = (ROOT / "app" / "core.py").read_text(encoding="utf-8")
        server = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
        runtime = (ROOT / "agent" / "runtime.py").read_text(encoding="utf-8")
        self.assertIn("def sayuri_tool_receipts", core)
        self.assertIn("/api/sayuri/tools/receipts", server)
        self.assertIn("for_cloud=True", runtime)
        self.assertIn("requires_action_broker", runtime)


if __name__ == "__main__":
    unittest.main()
