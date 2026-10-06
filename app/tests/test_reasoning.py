from __future__ import annotations

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from agent.reasoning import ReasoningEngine
from agent.runtime import CloudRuClient, SayuriAgent


ROOT = Path(__file__).resolve().parents[2]


class ReasoningEngineTests(unittest.TestCase):
    def test_complexity_gate_keeps_simple_chat_direct_and_plans_complex_work(self):
        engine = ReasoningEngine()
        self.assertEqual(engine.classify("Привет, Sayuri.").mode, "direct")
        complex_task = engine.classify(
            "Спроектируй архитектуру нового модуля, проанализируй риски, "
            "сравни варианты и проверь результат по критериям готовности."
        )
        self.assertEqual(complex_task.mode, "planned")
        self.assertGreaterEqual(complex_task.score, 3)

    def test_continuation_request_uses_goal_continuity_and_fallback_next_action(self):
        engine = ReasoningEngine()
        continuity = {
            "selected_goal": {"id": "g1", "title": "Развивать мозг Sayuri", "priority": 5},
            "selected_task": {
                "id": "t1",
                "goal_id": "g1",
                "title": "Усилить Planner",
                "status": "in_progress",
                "priority": 5,
                "next_action": "Добавить восстановление незавершённой задачи.",
                "blocked_reason": None,
            },
        }

        decision = engine.classify(
            "Продолжай",
            {"view": "sayuri"},
            continuity_context=continuity,
        )
        fallback = engine.fallback_plan("Продолжай", continuity_context=continuity)
        planner_messages = engine.planner_messages(
            "Продолжай",
            evidence_context={},
            ui_context={},
            tool_catalog=[],
            continuity_context=continuity,
        )

        self.assertEqual(decision.mode, "planned")
        self.assertIn("active_continuation", decision.reasons)
        self.assertIn("Добавить восстановление", fallback["steps"][1])
        self.assertTrue(engine.public_status()["goal_continuity_planner"])
        self.assertTrue(engine.public_status()["task_lifecycle_checkpoints"])
        self.assertIn("continuity_context", planner_messages[1]["content"])

    def test_plan_and_verifier_json_are_normalized_without_hidden_reasoning(self):
        engine = ReasoningEngine()
        plan = engine.parse_plan(
            '{"goal":"Собрать модуль","steps":["Шаг 1","Шаг 2"],'
            '"constraints":["Без второй LLM"],"evidence_needed":["Memory 4.1"],'
            '"done_when":["Тесты зелёные"],"risk_level":"high",'
            '"tool_intents":[{"step":1,"tool":"memory.stats","args":{},"purpose":"Сверить память"}]}'
        )
        verification = engine.parse_verification(
            '{"status":"revise","score":0.82,'
            '"checks":{"goal":true,"constraints":true,"evidence":false},'
            '"issues":["Не хватает доказательства"],'
            '"unsupported_claims":["Один факт"],'
            '"revised_answer":"Исправленный ответ"}'
        )
        self.assertEqual(plan["risk_level"], "high")
        self.assertEqual(plan["steps"], ["Шаг 1", "Шаг 2"])
        self.assertEqual(plan["tool_intents"][0]["tool"], "memory.stats")
        self.assertTrue(engine.public_status()["evidence_aware_tool_planner"])
        self.assertEqual(verification["status"], "revise")
        self.assertEqual(verification["revised_answer"], "Исправленный ответ")
        self.assertFalse(engine.public_status()["chain_of_thought_storage"])

    def test_complex_chat_runs_planner_answer_verifier_and_uses_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = SayuriAgent(Path(tmp))
            calls: list[list[dict[str, str]]] = []

            def fake_chat(self, messages, **kwargs):
                calls.append(messages)
                system = messages[0]["content"]
                usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
                if "Reasoning Planner" in system:
                    return {
                        "answer": (
                            '{"goal":"Спроектировать модуль","steps":["Собрать требования","Проверить риски"],'
                            '"constraints":["Одна внешняя LLM"],"evidence_needed":["Состояние памяти"],'
                            '"done_when":["Ответ проверен"],"risk_level":"medium",'
                            '"tool_intents":[{"step":1,"tool":"memory.stats","args":{},'
                            '"purpose":"Получить фактические метрики памяти"}]}'
                        ),
                        "usage": usage,
                        "model": "deepseek-ai/DeepSeek-V4-Flash",
                    }
                if "Result Verifier" in system:
                    return {
                        "answer": (
                            '{"status":"revise","score":0.9,'
                            '"checks":{"goal":true,"constraints":true,"evidence":true},'
                            '"issues":["Нужна более точная формулировка"],'
                            '"unsupported_claims":[],"revised_answer":"Проверенный исправленный ответ"}'
                        ),
                        "usage": usage,
                        "model": "deepseek-ai/DeepSeek-V4-Flash",
                    }
                return {
                    "answer": "Первичный ответ",
                    "usage": usage,
                    "model": "deepseek-ai/DeepSeek-V4-Flash",
                }

            with patch.dict(os.environ, {"SAYURI_CLOUDRU_API_KEY": "test-key-1234567890"}):
                with patch.object(CloudRuClient, "chat", fake_chat):
                    result = agent.chat(
                        message=(
                            "Спроектируй архитектуру модуля, проанализируй риски, "
                            "сравни варианты и проверь результат."
                        ),
                        context={"view": "sayuri"},
                    )

            self.assertEqual(len(calls), 3)
            self.assertEqual(result["answer"], "Проверенный исправленный ответ")
            self.assertEqual(result["reasoning"]["mode"], "planned")
            self.assertEqual(result["reasoning"]["planner_status"], "ready")
            self.assertEqual(result["reasoning"]["verification"]["status"], "revise")
            self.assertTrue(result["reasoning"]["revised"])
            self.assertEqual(result["reasoning"]["model_calls"], 3)
            automation = result["reasoning"]["automation"]
            self.assertEqual(automation["status"], "completed")
            self.assertEqual(automation["read_only_checks"], 1)
            self.assertEqual(automation["evidence_receipts"], 1)
            self.assertEqual(automation["blocked_mutations"], 0)
            self.assertNotIn("tool_execution", result["reasoning"])
            self.assertTrue(
                any(
                    "Execution receipts" in item.get("content", "")
                    for item in calls[1]
                    if item.get("role") == "system"
                )
            )
            self.assertIn("tool_receipts", calls[2][1]["content"])
            self.assertEqual(result["usage"]["total_tokens"], 6)

    def test_public_evidence_hides_receipts_and_exposes_openable_document(self):
        evidence = SayuriAgent._public_evidence(
            {
                "receipts": [
                    {
                        "status": "completed",
                        "tool": "context.current_document",
                        "output_preview": {
                            "available": True,
                            "id": "doc-123",
                            "name": "Договор.pdf",
                            "kind": "file",
                            "category": "documents",
                        },
                        "evidence_refs": [
                            "receipt:internal-secret",
                            "ui:current-document:doc-123",
                            "sha256:deadbeef",
                        ],
                    }
                ]
            },
            {
                "project": [{"memory_id": "m-project"}],
                "personal": [],
            },
        )

        self.assertEqual(evidence[0]["kind"], "document")
        self.assertEqual(evidence[0]["label"], "Договор.pdf")
        self.assertEqual(evidence[0]["target"], {
            "type": "disk_item",
            "kind": "file",
            "id": "doc-123",
        })
        self.assertEqual(evidence[1]["kind"], "memory")
        self.assertEqual(evidence[1]["label"], "Проектная память Sayuri")
        self.assertNotIn("receipt:", str(evidence))
        self.assertNotIn("sha256:", str(evidence))

    def test_spatial_citations_are_allowlisted_and_public_projection_hides_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = SayuriAgent(Path(tmp))
            calls = []

            def fake_chat(self, messages, **kwargs):
                calls.append(messages)
                system = messages[0]["content"]
                usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
                if "Reasoning Planner" in system:
                    return {
                        "answer": (
                            '{"goal":"Проверить сумму договора","steps":["Сверить факт"],'
                            '"constraints":[],"evidence_needed":["Spatial Evidence"],'
                            '"done_when":["Источник указан"],"risk_level":"low",'
                            '"tool_intents":[{"step":1,"tool":"document.evidence_search",'
                            '"args":{"query":"сумма договора","limit":3},'
                            '"purpose":"Найти точное доказательство"}]}'
                        ),
                        "usage": usage,
                        "model": "deepseek-ai/DeepSeek-V4-Flash",
                    }
                if "Result Verifier" in system:
                    return {
                        "answer": (
                            '{"status":"pass","score":1.0,'
                            '"checks":{"goal":true,"constraints":true,"evidence":true},'
                            '"issues":[],"unsupported_claims":[],"revised_answer":null}'
                        ),
                        "usage": usage,
                        "model": "deepseek-ai/DeepSeek-V4-Flash",
                    }
                return {
                    "answer": "Сумма договора — 25 000 руб. [D1]. Лишний маркер [D9].",
                    "usage": usage,
                    "model": "deepseek-ai/DeepSeek-V4-Flash",
                }

            def evidence_handler(args):
                self.assertEqual(args["query"], "сумма договора")
                return {
                    "data": {
                        "available": True,
                        "document": {
                            "id": "doc-1",
                            "name": "Договор.pdf",
                            "content_type": "application/pdf",
                        },
                        "items": [
                            {
                                "citation_id": "D1",
                                "fact_id": "fact-amount",
                                "label": "Сумма",
                                "role": "amount",
                                "value": "25 000 руб.",
                                "excerpt": "Итого к оплате 25 000 руб.",
                                "confidence": 0.98,
                                "quality_gate": "accepted",
                                "locator": {
                                    "page": 2,
                                    "line": 18,
                                    "line_id": "p2-native-l8",
                                    "extraction_method": "native",
                                    "coordinate_status": "exact_from_document_engine",
                                },
                            }
                        ],
                    },
                    "evidence_refs": ["dna-spatial:doc-1:fact-amount"],
                }

            with patch.dict(os.environ, {"SAYURI_CLOUDRU_API_KEY": "test-key-1234567890"}):
                with patch.object(CloudRuClient, "chat", fake_chat):
                    result = agent.chat(
                        message="Спроектируй проверку договора, сравни варианты и проверь результат по сумме и источнику.",
                        context={"view": "disk"},
                        external_tool_handlers={"document.evidence_search": evidence_handler},
                    )

            self.assertEqual(len(calls), 3)
            self.assertIn("[D1]", result["answer"])
            self.assertNotIn("[D9]", result["answer"])
            spatial = next(item for item in result["evidence"] if item["kind"] == "spatial_document")
            self.assertEqual(spatial["citation_id"], "D1")
            self.assertEqual(spatial["page"], 2)
            self.assertEqual(spatial["line"], 18)
            self.assertEqual(spatial["target"], {
                "type": "disk_evidence",
                "file_id": "doc-1",
                "fact_id": "fact-amount",
            })
            self.assertNotIn("bbox", str(spatial))
            self.assertNotIn("receipt:", str(result["evidence"]))
            self.assertNotIn("document.evidence_search", str(result["evidence"]))
            self.assertTrue(
                any(
                    "Spatial Evidence citations" in item.get("content", "")
                    for item in calls[1]
                    if item.get("role") == "system"
                )
            )

    def test_simple_chat_uses_one_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = SayuriAgent(Path(tmp))
            calls = 0

            def fake_chat(self, messages, **kwargs):
                nonlocal calls
                calls += 1
                return {
                    "answer": "Короткий ответ",
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                    "model": "deepseek-ai/DeepSeek-V4-Flash",
                }

            with patch.dict(os.environ, {"SAYURI_CLOUDRU_API_KEY": "test-key-1234567890"}):
                with patch.object(CloudRuClient, "chat", fake_chat):
                    result = agent.chat(message="Привет, Sayuri.", context={"view": "home"})

            self.assertEqual(calls, 1)
            self.assertEqual(result["reasoning"]["mode"], "direct")
            self.assertEqual(result["reasoning"]["model_calls"], 1)
            self.assertEqual(result["reasoning"]["verification"]["status"], "skipped")
            self.assertEqual(result["reasoning"]["automation"]["status"], "skipped")
            self.assertIn("evidence", result)

    def test_web_chat_exposes_structured_reasoning_summary(self):
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("createSayuriReasoningSummary", script)
        self.assertIn("result.reasoning", script)
        self.assertIn("результат проверен", script)
        self.assertIn("автопроверка", script)
        self.assertIn("SAYURI UI 0.25 — Background Evidence Automation", css)
        self.assertIn(".sayuri-reasoning-summary", css)
        self.assertNotIn("sayuri-tool-receipts", script)
        self.assertNotIn(".sayuri-tool-receipts", css)
        self.assertNotIn("sayuri-tool-list", script)


if __name__ == "__main__":
    unittest.main()
