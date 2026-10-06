from __future__ import annotations

from copy import deepcopy
from typing import Any
import re


class ReasoningLogicError(ValueError):
    pass


class ReasoningLogic:
    """Deterministic request-scoped reasoning state machine without chain-of-thought storage."""

    VERSION = "2.0"

    STATES = (
        "UNDERSTAND",
        "RETRIEVE",
        "FRAME",
        "PLAN",
        "CHECK",
        "ACT",
        "VERIFY",
        "REFLECT",
        "CONTINUE",
        "UNCERTAIN",
        "GATHER_EVIDENCE",
        "REPLAN",
        "FAILED",
        "DIAGNOSE",
        "READY_FOR_CONFIRMATION",
    )

    _CONTINUATION_MARKERS = (
        "продолж",
        "дальше",
        "вернись",
        "возобнов",
        "resume",
        "continue",
    )
    _ACTION_MARKERS = (
        "создай",
        "сделай",
        "добавь",
        "измени",
        "удали",
        "перемести",
        "переимен",
        "запусти",
        "опубликуй",
        "внедри",
        "реализ",
    )
    _ANALYSIS_MARKERS = (
        "анализ",
        "изучи",
        "проверь",
        "исслед",
        "оцени",
        "разбер",
    )
    _COMPARE_MARKERS = ("сравн", "вариант", "лучше", "выбери")
    _PLAN_MARKERS = ("план", "спроект", "архитект", "поэтап", "обдум")

    def public_status(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "state_machine": True,
            "decision_trace": True,
            "intent_resolver": True,
            "constraint_gate": True,
            "hypothesis_tracking": True,
            "option_comparison": True,
            "counterfactual_checks": True,
            "uncertainty_gate": True,
            "evidence_gate": True,
            "verification_gate": True,
            "replanning_gate": True,
            "chain_of_thought_storage": False,
            "persistence": "request_scoped_only",
        }

    @staticmethod
    def _clean(value: Any, limit: int = 600) -> str:
        return " ".join(str(value or "").strip().split())[:limit]

    @staticmethod
    def _safe_count(value: Any) -> int:
        if isinstance(value, list):
            return len(value)
        return 0

    @classmethod
    def _intent(cls, task: str) -> str:
        normalized = " ".join((task or "").casefold().replace("ё", "е").split())
        if any(marker in normalized for marker in cls._CONTINUATION_MARKERS):
            return "continue"
        if any(marker in normalized for marker in cls._COMPARE_MARKERS):
            return "compare"
        if any(marker in normalized for marker in cls._PLAN_MARKERS):
            return "plan"
        if any(marker in normalized for marker in cls._ACTION_MARKERS):
            return "action"
        if any(marker in normalized for marker in cls._ANALYSIS_MARKERS):
            return "analyze"
        if "?" in task:
            return "question"
        return "request"

    @staticmethod
    def _selected(cognitive_context: Any) -> dict[str, Any] | None:
        if not isinstance(cognitive_context, dict):
            return None
        scheduler = cognitive_context.get("scheduler")
        if not isinstance(scheduler, dict):
            return None
        selected = scheduler.get("selected")
        return selected if isinstance(selected, dict) else None

    @staticmethod
    def _metacognition(cognitive_context: Any) -> dict[str, Any]:
        if not isinstance(cognitive_context, dict):
            return {}
        meta = cognitive_context.get("metacognition")
        return meta if isinstance(meta, dict) else {}

    @staticmethod
    def _scope(selected: dict[str, Any] | None, ui_context: Any) -> dict[str, Any]:
        project_key = None
        module_key = None
        if isinstance(selected, dict):
            project = selected.get("project")
            module = selected.get("module")
            if isinstance(project, dict):
                project_key = project.get("key")
            if isinstance(module, dict):
                module_key = module.get("key")
        if isinstance(ui_context, dict):
            project_key = ui_context.get("project_key") or project_key
            module_key = ui_context.get("module_key") or module_key
        return {
            "project_key": str(project_key)[:160] if project_key else None,
            "module_key": str(module_key)[:160] if module_key else None,
        }

    @classmethod
    def _trace_item(
        cls,
        stage: str,
        status: str,
        summary: str,
        *,
        code: str,
    ) -> dict[str, str]:
        if stage not in cls.STATES:
            raise ReasoningLogicError("Неизвестное состояние reasoning logic.")
        return {
            "stage": stage,
            "status": status,
            "code": cls._clean(code, 120),
            "summary": cls._clean(summary, 500),
        }

    @staticmethod
    def _copy(logic: dict[str, Any]) -> dict[str, Any]:
        return deepcopy(logic)

    def start(
        self,
        task: str,
        *,
        decision: Any,
        ui_context: Any = None,
        continuity_context: Any = None,
        cognitive_context: Any = None,
    ) -> dict[str, Any]:
        selected = self._selected(cognitive_context)
        meta = self._metacognition(cognitive_context)
        blockers = selected.get("blockers") if isinstance(selected, dict) else []
        blockers = blockers if isinstance(blockers, list) else []
        meta_state = str(meta.get("state") or "")
        blocked = bool(blockers) or meta_state == "blocked"
        blocker_count = len(blockers)
        if blocked and blocker_count == 0:
            blocker_count = 1
        high_uncertainty = 0
        if isinstance(selected, dict):
            try:
                high_uncertainty = int(selected.get("high_uncertainty_count") or 0)
            except (TypeError, ValueError):
                high_uncertainty = 0
        meta_uncertain = meta.get("uncertain") if isinstance(meta, dict) else []
        if isinstance(meta_uncertain, list):
            high_uncertainty = max(
                high_uncertainty,
                sum(
                    1
                    for item in meta_uncertain
                    if isinstance(item, dict) and item.get("severity") == "high"
                ),
            )

        scope = self._scope(selected, ui_context)
        intent = self._intent(task)
        mode = str(getattr(decision, "mode", "direct") or "direct")
        confidence = 0.56
        if scope["project_key"]:
            confidence += 0.08
        if selected:
            confidence += 0.08
        if blocked:
            confidence -= 0.2
        if high_uncertainty:
            confidence -= 0.18
        confidence = max(0.1, min(confidence, 0.95))

        current_state = "FRAME"
        gate_code = "frame_ready"
        if blocked:
            current_state = "CHECK"
            gate_code = "blocked"
        elif high_uncertainty:
            current_state = "UNCERTAIN"
            gate_code = "high_uncertainty"

        continuity_present = bool(
            isinstance(continuity_context, dict)
            and (
                isinstance(continuity_context.get("selected_task"), dict)
                or isinstance(continuity_context.get("selected_goal"), dict)
            )
        )
        trace = [
            self._trace_item(
                "UNDERSTAND",
                "completed",
                f"Намерение определено как {intent}; режим сложности — {mode}.",
                code="intent_resolved",
            ),
            self._trace_item(
                "RETRIEVE",
                "completed",
                (
                    "Подключены разрешённые контексты: "
                    + ", ".join(
                        item
                        for item, enabled in (
                            ("continuity", continuity_present),
                            ("cognition", isinstance(cognitive_context, dict)),
                            ("ui_scope", bool(scope["project_key"] or scope["module_key"])),
                        )
                        if enabled
                    )
                    or "Дополнительный контекст отсутствует."
                ),
                code="context_retrieved",
            ),
            self._trace_item(
                "FRAME",
                "completed" if current_state == "FRAME" else "gated",
                (
                    f"Scope project={scope['project_key'] or 'default'}, "
                    f"module={scope['module_key'] or 'none'}; "
                    f"blockers={blocker_count}, high_uncertainty={high_uncertainty}."
                ),
                code=gate_code,
            ),
        ]
        return {
            "version": self.VERSION,
            "current_state": current_state,
            "intent": intent,
            "scope": scope,
            "confidence": round(confidence, 3),
            "risk_level": None,
            "gates": {
                "blocked": blocked,
                "blocker_count": blocker_count,
                "high_uncertainty": high_uncertainty > 0,
                "high_uncertainty_count": high_uncertainty,
                "mutation_allowed": False,
                "action_broker_required_for_mutation": True,
            },
            "plan_summary": {
                "options": 0,
                "hypotheses": 0,
                "counterfactual_checks": 0,
                "selected_option": None,
                "decision_summary": None,
            },
            "evidence_summary": {
                "requested": 0,
                "read_only_calls": 0,
                "completed_receipts": 0,
                "blocked_mutations": 0,
            },
            "trace": trace,
            "chain_of_thought_stored": False,
        }

    def after_plan(
        self,
        logic: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._copy(logic)
        risk = str(plan.get("risk_level") or "medium")
        hypotheses = plan.get("hypotheses") if isinstance(plan.get("hypotheses"), list) else []
        options = plan.get("options") if isinstance(plan.get("options"), list) else []
        counterfactual = (
            plan.get("counterfactual_checks")
            if isinstance(plan.get("counterfactual_checks"), list)
            else []
        )
        result["risk_level"] = risk
        result["plan_summary"] = {
            "options": len(options),
            "hypotheses": len(hypotheses),
            "counterfactual_checks": len(counterfactual),
            "selected_option": self._clean(plan.get("selected_option"), 120) or None,
            "decision_summary": self._clean(plan.get("decision_summary"), 500) or None,
        }
        result["evidence_summary"]["requested"] = self._safe_count(
            plan.get("evidence_needed")
        )
        result["trace"].append(
            self._trace_item(
                "PLAN",
                "completed",
                (
                    f"План содержит {len(plan.get('steps', []))} шагов, "
                    f"{len(options)} вариантов, {len(hypotheses)} гипотез; risk={risk}."
                ),
                code="structured_plan_ready",
            )
        )

        gates = result.get("gates", {})
        if gates.get("blocked"):
            result["current_state"] = "CHECK"
            result["trace"].append(
                self._trace_item(
                    "CHECK",
                    "blocked",
                    "Обнаружены активные dependency/external blockers; выполнение следующего шага запрещено.",
                    code="blockers_win",
                )
            )
        elif gates.get("high_uncertainty"):
            result["current_state"] = "GATHER_EVIDENCE"
            result["trace"].append(
                self._trace_item(
                    "CHECK",
                    "gated",
                    "Высокая неопределённость требует evidence до выбора действия.",
                    code="evidence_first",
                )
            )
            result["trace"].append(
                self._trace_item(
                    "GATHER_EVIDENCE",
                    "pending",
                    "Нужно получить проверяемые данные и затем пересчитать план.",
                    code="evidence_required",
                )
            )
        else:
            result["current_state"] = "ACT"
            result["trace"].append(
                self._trace_item(
                    "CHECK",
                    "completed",
                    "Блокирующих ограничений не найдено; разрешены только read-only проверки или подготовка ответа.",
                    code="constraints_passed",
                )
            )
        if risk == "high":
            result["confidence"] = round(
                max(0.1, float(result.get("confidence") or 0.5) - 0.08),
                3,
            )
        return result

    def after_evidence(
        self,
        logic: dict[str, Any],
        tool_execution: Any,
    ) -> dict[str, Any]:
        result = self._copy(logic)
        execution = tool_execution if isinstance(tool_execution, dict) else {}
        receipts = execution.get("receipts") if isinstance(execution.get("receipts"), list) else []
        completed = sum(1 for item in receipts if isinstance(item, dict) and item.get("status") == "completed")
        blocked_mutations = sum(
            1
            for item in receipts
            if isinstance(item, dict) and item.get("status") == "requires_action_broker"
        )
        try:
            read_only_calls = int(execution.get("read_only_calls") or 0)
        except (TypeError, ValueError):
            read_only_calls = 0
        result["evidence_summary"].update(
            {
                "read_only_calls": read_only_calls,
                "completed_receipts": completed,
                "blocked_mutations": blocked_mutations,
            }
        )
        if result.get("gates", {}).get("blocked"):
            result["current_state"] = "CHECK"
            return result

        requested = int(result.get("evidence_summary", {}).get("requested") or 0)
        if requested > 0 and completed == 0:
            result["current_state"] = "GATHER_EVIDENCE"
            result["trace"].append(
                self._trace_item(
                    "GATHER_EVIDENCE",
                    "incomplete",
                    "План запросил evidence, но подтверждённых read-only receipts пока нет.",
                    code="evidence_missing",
                )
            )
            return result

        result["trace"].append(
            self._trace_item(
                "ACT",
                "completed",
                (
                    f"Выполнено read-only checks={read_only_calls}, "
                    f"completed receipts={completed}; mutation attempts gated={blocked_mutations}."
                ),
                code="safe_actions_observed",
            )
        )
        result["current_state"] = "VERIFY"
        result["trace"].append(
            self._trace_item(
                "VERIFY",
                "pending",
                "Результат должен быть проверен против цели, ограничений и evidence.",
                code="verification_required",
            )
        )
        return result

    def finalize_direct(
        self,
        logic: dict[str, Any],
    ) -> dict[str, Any]:
        """Close a simple direct-answer path without pretending a verifier ran."""
        result = self._copy(logic)
        if result.get("gates", {}).get("blocked"):
            result["current_state"] = "CHECK"
            result["trace"].append(
                self._trace_item(
                    "CHECK",
                    "blocked",
                    "Прямой ответ не отменяет активные blockers и не разрешает mutation.",
                    code="direct_blocked",
                )
            )
            return result
        if result.get("gates", {}).get("high_uncertainty"):
            result["current_state"] = "GATHER_EVIDENCE"
            result["trace"].append(
                self._trace_item(
                    "GATHER_EVIDENCE",
                    "pending",
                    "Для прямого ответа сохранена high-uncertainty; требуется evidence перед сильным выводом.",
                    code="direct_evidence_required",
                )
            )
            return result
        result["trace"].append(
            self._trace_item(
                "ACT",
                "completed",
                "Сформирован прямой ответ без mutation и без дополнительного Planner/Verifier вызова.",
                code="direct_answer",
            )
        )
        result["trace"].append(
            self._trace_item(
                "REFLECT",
                "completed",
                "Дополнительная независимая верификация не требовалась по complexity gate.",
                code="direct_reflection",
            )
        )
        result["current_state"] = "CONTINUE"
        result["trace"].append(
            self._trace_item(
                "CONTINUE",
                "ready",
                "Можно продолжить диалог или определить следующий проверяемый шаг.",
                code="direct_continue",
            )
        )
        return result

    def finalize(
        self,
        logic: dict[str, Any],
        verification: Any,
        *,
        cognitive_context: Any = None,
    ) -> dict[str, Any]:
        result = self._copy(logic)
        verify = verification if isinstance(verification, dict) else {}
        status = str(verify.get("status") or "unavailable")
        score = verify.get("score")
        issues = verify.get("issues") if isinstance(verify.get("issues"), list) else []
        unsupported = (
            verify.get("unsupported_claims")
            if isinstance(verify.get("unsupported_claims"), list)
            else []
        )

        result["trace"] = [
            item
            for item in result.get("trace", [])
            if not (
                isinstance(item, dict)
                and item.get("stage") == "VERIFY"
                and item.get("status") == "pending"
            )
        ]
        result["trace"].append(
            self._trace_item(
                "VERIFY",
                "completed" if status in {"pass", "revise"} else "unavailable",
                (
                    f"Verifier status={status}, score={score}; "
                    f"issues={len(issues)}, unsupported={len(unsupported)}."
                ),
                code="verification_" + status,
            )
        )

        meta = self._metacognition(cognitive_context)
        meta_state = str(meta.get("state") or "")
        if status == "revise" or unsupported:
            next_state = "REPLAN"
            reflect_summary = "Проверка нашла проблемы; следующий безопасный шаг — пересчитать план или использовать revised result."
            code = "replan_after_verification"
        elif status not in {"pass", "revise"}:
            next_state = "UNCERTAIN"
            reflect_summary = "Независимая проверка недоступна; результат нельзя повышать до подтверждённого."
            code = "verification_unavailable"
        elif meta_state == "ready_for_completion_confirmation":
            next_state = "READY_FOR_CONFIRMATION"
            reflect_summary = "Критерии выглядят готовыми, но завершение требует явного подтверждения."
            code = "human_confirmation_required"
        elif result.get("gates", {}).get("blocked"):
            next_state = "CHECK"
            reflect_summary = "Активный blocker остаётся сильнее плана и ответа."
            code = "blocked_after_verify"
        elif result.get("gates", {}).get("high_uncertainty"):
            next_state = "GATHER_EVIDENCE"
            reflect_summary = "High uncertainty остаётся открытой; требуется дополнительное evidence."
            code = "uncertainty_after_verify"
        else:
            next_state = "CONTINUE"
            reflect_summary = "Результат проверен; можно определить следующий подтверждаемый шаг без автоматического mutation."
            code = "verified_continue"

        result["trace"].append(
            self._trace_item(
                "REFLECT",
                "completed",
                reflect_summary,
                code=code,
            )
        )
        result["current_state"] = next_state
        result["trace"].append(
            self._trace_item(
                next_state,
                "ready" if next_state in {"CONTINUE", "READY_FOR_CONFIRMATION"} else "pending",
                reflect_summary,
                code=code,
            )
        )
        if isinstance(score, (int, float)):
            confidence = float(result.get("confidence") or 0.5)
            result["confidence"] = round(
                max(0.1, min(0.98, (confidence + float(score)) / 2.0)),
                3,
            )
        return result
