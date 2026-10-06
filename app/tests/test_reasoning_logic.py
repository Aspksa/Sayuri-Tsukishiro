from __future__ import annotations

from types import SimpleNamespace
import unittest

from agent.reasoning_logic import ReasoningLogic


class ReasoningLogicTests(unittest.TestCase):
    def test_direct_path_finishes_without_fake_verifier_or_chain_of_thought(self):
        logic = ReasoningLogic()
        state = logic.start(
            "Привет, Sayuri.",
            decision=SimpleNamespace(mode="direct"),
            ui_context={"project_key": "sayuri-tsukishiro"},
            continuity_context={},
            cognitive_context={},
        )
        final = logic.finalize_direct(state)

        self.assertEqual(final["current_state"], "CONTINUE")
        self.assertFalse(final["chain_of_thought_stored"])
        self.assertFalse(final["gates"]["mutation_allowed"])
        self.assertEqual(final["trace"][0]["stage"], "UNDERSTAND")
        self.assertEqual(final["trace"][-1]["stage"], "CONTINUE")
        self.assertFalse(any(item["stage"] == "VERIFY" for item in final["trace"]))

    def test_blocker_wins_over_plan_and_prevents_act_state(self):
        logic = ReasoningLogic()
        state = logic.start(
            "Продолжай задачу",
            decision=SimpleNamespace(mode="planned"),
            cognitive_context={
                "scheduler": {
                    "selected": {
                        "project": {"key": "alpha"},
                        "module": {"key": "core"},
                        "blockers": [{"type": "task_dependency", "title": "Prerequisite"}],
                        "high_uncertainty_count": 0,
                    }
                },
                "metacognition": {"state": "blocked", "uncertain": []},
            },
        )
        planned = logic.after_plan(
            state,
            {
                "steps": ["Проверить dependency", "Продолжить после разблокировки"],
                "risk_level": "medium",
                "evidence_needed": [],
                "hypotheses": [],
                "options": [],
                "counterfactual_checks": [],
            },
        )

        self.assertEqual(planned["current_state"], "CHECK")
        self.assertTrue(planned["gates"]["blocked"])
        self.assertFalse(any(item["stage"] == "ACT" for item in planned["trace"]))

    def test_metacognition_blocked_gates_when_scheduler_has_no_selected_task(self):
        logic = ReasoningLogic()
        state = logic.start(
            "Что дальше?",
            decision=SimpleNamespace(mode="planned"),
            cognitive_context={
                "scheduler": {
                    "selected": None,
                    "candidates": [
                        {
                            "project": {"key": "alpha"},
                            "blockers": [{"type": "external", "title": "Wait"}],
                        }
                    ],
                },
                "metacognition": {"state": "blocked", "uncertain": []},
            },
        )

        self.assertEqual(state["current_state"], "CHECK")
        self.assertTrue(state["gates"]["blocked"])
        self.assertEqual(state["gates"]["blocker_count"], 1)

    def test_high_uncertainty_requires_evidence_before_action(self):
        logic = ReasoningLogic()
        state = logic.start(
            "Проверь причину сбоя",
            decision=SimpleNamespace(mode="planned"),
            cognitive_context={
                "scheduler": {
                    "selected": {
                        "project": {"key": "alpha"},
                        "blockers": [],
                        "high_uncertainty_count": 1,
                    }
                },
                "metacognition": {
                    "state": "uncertain",
                    "uncertain": [
                        {"severity": "high", "question": "Почему упал шаг?"}
                    ],
                },
            },
        )
        planned = logic.after_plan(
            state,
            {
                "steps": ["Собрать evidence"],
                "risk_level": "high",
                "evidence_needed": ["Лог ошибки"],
                "hypotheses": [
                    {
                        "claim": "Ошибка конфигурации",
                        "status": "unknown",
                        "evidence_needed": ["Лог"],
                    }
                ],
                "options": [],
                "counterfactual_checks": ["Если конфигурация верна, проверить входные данные."],
            },
        )

        self.assertEqual(planned["current_state"], "GATHER_EVIDENCE")
        self.assertTrue(planned["gates"]["high_uncertainty"])
        self.assertTrue(any(item["stage"] == "GATHER_EVIDENCE" for item in planned["trace"]))

    def test_evidence_then_verification_pass_moves_to_continue(self):
        logic = ReasoningLogic()
        state = logic.start(
            "Спроектируй безопасный шаг",
            decision=SimpleNamespace(mode="planned"),
            cognitive_context={
                "scheduler": {
                    "selected": {
                        "project": {"key": "alpha"},
                        "blockers": [],
                        "high_uncertainty_count": 0,
                    }
                },
                "metacognition": {"state": "actionable", "uncertain": []},
            },
        )
        state = logic.after_plan(
            state,
            {
                "steps": ["Сверить данные", "Подготовить ответ"],
                "risk_level": "medium",
                "evidence_needed": ["Статус"],
                "hypotheses": [],
                "options": [
                    {
                        "id": "A",
                        "action": "Сначала проверить статус",
                        "benefits": ["Меньше риска"],
                        "risks": [],
                        "evidence_needed": ["Статус"],
                    }
                ],
                "selected_option": "A",
                "decision_summary": "Сначала проверить статус.",
                "counterfactual_checks": [],
            },
        )
        state = logic.after_evidence(
            state,
            {
                "read_only_calls": 1,
                "receipts": [{"status": "completed", "tool": "system.status"}],
            },
        )
        final = logic.finalize(
            state,
            {
                "status": "pass",
                "score": 0.94,
                "confidence": 0.91,
                "issues": [],
                "unsupported_claims": [],
            },
            cognitive_context={"metacognition": {"state": "actionable"}},
        )

        self.assertEqual(state["current_state"], "VERIFY")
        self.assertEqual(final["current_state"], "CONTINUE")
        self.assertGreater(final["confidence"], 0.7)
        self.assertEqual(final["plan_summary"]["selected_option"], "A")

    def test_verifier_revision_moves_to_replan(self):
        logic = ReasoningLogic()
        state = logic.start(
            "Проверь архитектуру",
            decision=SimpleNamespace(mode="planned"),
            cognitive_context={"metacognition": {"state": "actionable"}},
        )
        state = logic.after_plan(
            state,
            {
                "steps": ["Проверить"],
                "risk_level": "medium",
                "evidence_needed": [],
                "hypotheses": [],
                "options": [],
                "counterfactual_checks": [],
            },
        )
        state = logic.after_evidence(state, {"read_only_calls": 0, "receipts": []})
        final = logic.finalize(
            state,
            {
                "status": "revise",
                "score": 0.6,
                "issues": ["Нужна корректировка"],
                "unsupported_claims": [],
            },
            cognitive_context={"metacognition": {"state": "actionable"}},
        )

        self.assertEqual(final["current_state"], "REPLAN")
        self.assertEqual(final["trace"][-1]["stage"], "REPLAN")

    def test_ready_completion_never_auto_completes_task(self):
        logic = ReasoningLogic()
        state = logic.start(
            "Проверь готовность",
            decision=SimpleNamespace(mode="planned"),
            cognitive_context={
                "metacognition": {"state": "ready_for_completion_confirmation"},
            },
        )
        state = logic.after_plan(
            state,
            {
                "steps": ["Сверить criteria"],
                "risk_level": "low",
                "evidence_needed": [],
                "hypotheses": [],
                "options": [],
                "counterfactual_checks": [],
            },
        )
        state = logic.after_evidence(state, {"read_only_calls": 0, "receipts": []})
        final = logic.finalize(
            state,
            {
                "status": "pass",
                "score": 1.0,
                "issues": [],
                "unsupported_claims": [],
            },
            cognitive_context={
                "metacognition": {"state": "ready_for_completion_confirmation"}
            },
        )

        self.assertEqual(final["current_state"], "READY_FOR_CONFIRMATION")
        self.assertFalse(final["gates"]["mutation_allowed"])
        self.assertIn("подтвержден", final["trace"][-1]["summary"].casefold())


if __name__ == "__main__":
    unittest.main()
