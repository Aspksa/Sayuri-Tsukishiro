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

    def test_plan_and_verifier_json_are_normalized_without_hidden_reasoning(self):
        engine = ReasoningEngine()
        plan = engine.parse_plan(
            '{"goal":"Собрать модуль","steps":["Шаг 1","Шаг 2"],'
            '"constraints":["Без второй LLM"],"evidence_needed":["Memory 4.1"],'
            '"done_when":["Тесты зелёные"],"risk_level":"high"}'
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
                            '"constraints":["Одна внешняя LLM"],"evidence_needed":[],'
                            '"done_when":["Ответ проверен"],"risk_level":"medium"}'
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
            self.assertEqual(result["usage"]["total_tokens"], 6)

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

    def test_web_chat_exposes_structured_reasoning_summary(self):
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("createSayuriReasoningSummary", script)
        self.assertIn("result.reasoning", script)
        self.assertIn("план+проверка", script)
        self.assertIn("SAYURI UI 0.23 — Reasoning Planner + Result Verifier", css)
        self.assertIn(".sayuri-reasoning-summary", css)


if __name__ == "__main__":
    unittest.main()
