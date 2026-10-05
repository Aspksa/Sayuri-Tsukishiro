from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha1
import math
from typing import Any


EVOLUTION_ENGINE_VERSION = "0.6.0"
MIN_ADAPTIVE_PROFILE_DOCUMENTS = 5
MIN_HYPOTHESIS_SUPPORT = 3
HIGH_IMPORTANCE_TYPES = {
    "document_number", "date", "amount", "inn", "vin",
    "vehicle_plate", "organization", "person", "action",
}


class DNAEvolutionEngine:
    """Метакогнитивный слой ДНК: учится только на проверяемом опыте и не создаёт знания самовольно."""

    def enrich(
        self,
        dna: dict[str, Any],
        *,
        previous: dict[str, Any] | None,
        corpus: list[dict[str, Any]],
        correction_rules: list[dict[str, Any]],
        feedback_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        self_review = self._self_review(dna)
        adaptive_profile = self._adaptive_profile(dna, corpus)
        regression_guard = self._regression_guard(previous, dna)
        rule_lifecycle = self._rule_lifecycle(correction_rules)
        hypotheses = self._association_hypotheses(dna, corpus)
        active_learning = self._active_learning(dna)
        experience = self._experience_snapshot(
            dna,
            corpus=corpus,
            feedback_metrics=feedback_metrics,
            rules=rule_lifecycle,
            hypotheses=hypotheses,
            self_review=self_review,
        )

        dna["evolution"] = {
            "engine_version": EVOLUTION_ENGINE_VERSION,
            "mode": "guarded_evolution",
            "self_review": self_review,
            "adaptive_profile": adaptive_profile,
            "regression_guard": regression_guard,
            "rule_lifecycle": rule_lifecycle,
            "hypotheses": hypotheses,
            "active_learning": active_learning,
            "experience": experience,
            "principles": {
                "verified_experience_only": True,
                "hypothesis_is_not_fact": True,
                "automatic_rule_promotion_is_guarded": True,
                "regression_blocks_memory_promotion": True,
            },
        }

        gate = dna.setdefault("quality_gate", {})
        reasons = list(gate.get("reasons") or [])
        if not self_review["passed"] and "self_review_failed" not in reasons:
            reasons.append("self_review_failed")
        if regression_guard["status"] == "blocked" and "analyzer_regression" not in reasons:
            reasons.append("analyzer_regression")
        gate["reasons"] = reasons
        if not self_review["passed"] or regression_guard["status"] == "blocked":
            gate["memory_ready"] = False

        epistemics = dna.setdefault("epistemics", {})
        epistemics["hypotheses"] = len(hypotheses["items"])
        epistemics["hypothesis_policy"] = (
            "Гипотеза хранится отдельно и может стать фактом только после прямого доказательства "
            "или подтверждённой обратной связи."
        )
        return dna

    @staticmethod
    def _fact_key(fact: dict[str, Any]) -> tuple[str, str, str]:
        normalized = fact.get("normalized") or {}
        canonical = normalized.get("canonical") or fact.get("value") or ""
        return (
            str(fact.get("type") or ""),
            str(fact.get("role") or ""),
            str(canonical),
        )

    def _self_review(self, dna: dict[str, Any]) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        fact_ids: set[str] = set()
        accepted = 0

        for fact in dna.get("molecules", {}).get("facts", []):
            fact_id = str(fact.get("id") or "")
            if not fact_id:
                issues.append({
                    "code": "missing_fact_id",
                    "level": "critical",
                    "message": "Факт не имеет стабильного ID.",
                })
            elif fact_id in fact_ids:
                issues.append({
                    "code": "duplicate_fact_id",
                    "level": "critical",
                    "message": f"Повторяется fact_id {fact_id}.",
                })
            else:
                fact_ids.add(fact_id)

            source = fact.get("source") or {}
            raw_value = str(fact.get("value") or "").strip()
            excerpt = str(source.get("excerpt") or "")
            if raw_value and excerpt:
                compact_value = "".join(raw_value.casefold().split())
                compact_excerpt = "".join(excerpt.casefold().split())
                if compact_value not in compact_excerpt and fact.get("type") != "action":
                    issues.append({
                        "code": "evidence_value_mismatch",
                        "level": "attention",
                        "fact_id": fact_id,
                        "message": "Исходное значение факта не найдено в сохранённом фрагменте доказательства.",
                    })

            normalized = fact.get("normalized") or {}
            if normalized.get("canonical") in {None, ""}:
                issues.append({
                    "code": "missing_canonical",
                    "level": "attention",
                    "fact_id": fact_id,
                    "message": "У факта отсутствует каноническое значение.",
                })

            confidence = float(fact.get("calibrated_confidence", fact.get("confidence") or 0))
            if fact.get("quality_gate") == "accepted":
                accepted += 1
                if confidence < 0.72:
                    issues.append({
                        "code": "accepted_low_confidence",
                        "level": "critical",
                        "fact_id": fact_id,
                        "message": "Факт принят quality gate при слишком низкой уверенности.",
                    })

            if not source.get("evidence_hash"):
                issues.append({
                    "code": "missing_evidence_hash",
                    "level": "critical",
                    "fact_id": fact_id,
                    "message": "У факта отсутствует evidence hash.",
                })

        critical = sum(1 for issue in issues if issue["level"] == "critical")
        attention = sum(1 for issue in issues if issue["level"] == "attention")
        base = max(1, len(fact_ids))
        score = max(0, int(round(100 - critical * 18 - min(attention / base, 1.0) * 25)))
        return {
            "passed": critical == 0,
            "score": score,
            "critical": critical,
            "attention": attention,
            "accepted_facts": accepted,
            "issues": issues[:100],
        }

    def _adaptive_profile(
        self,
        dna: dict[str, Any],
        corpus: list[dict[str, Any]],
    ) -> dict[str, Any]:
        document_type = dna.get("classification", {}).get("document_type")
        same_type = [
            item for item in corpus
            if item.get("classification", {}).get("document_type") == document_type
        ]
        sample_size = len(same_type)
        if sample_size < MIN_ADAPTIVE_PROFILE_DOCUMENTS:
            return {
                "status": "insufficient_data",
                "sample_size": sample_size,
                "minimum": MIN_ADAPTIVE_PROFILE_DOCUMENTS,
                "learned_expected_types": [],
                "learned_expected_roles": [],
                "missing_learned_expected": [],
            }

        type_presence: Counter[str] = Counter()
        role_presence: Counter[str] = Counter()
        for item in same_type:
            types = {
                str(fact.get("type"))
                for fact in item.get("molecules", {}).get("facts", [])
                if fact.get("quality_gate") != "rejected" and fact.get("type")
            }
            roles = {
                str(fact.get("role"))
                for fact in item.get("molecules", {}).get("facts", [])
                if fact.get("quality_gate") != "rejected" and fact.get("role")
            }
            type_presence.update(types)
            role_presence.update(roles)

        learned_types = [
            {
                "type": fact_type,
                "frequency": round(count / sample_size, 3),
                "support": count,
            }
            for fact_type, count in type_presence.items()
            if count / sample_size >= 0.70
        ]
        learned_roles = [
            {
                "role": role,
                "frequency": round(count / sample_size, 3),
                "support": count,
            }
            for role, count in role_presence.items()
            if count / sample_size >= 0.70
        ]
        learned_types.sort(key=lambda item: (-item["frequency"], item["type"]))
        learned_roles.sort(key=lambda item: (-item["frequency"], item["role"]))

        current_types = {
            str(fact.get("type"))
            for fact in dna.get("molecules", {}).get("facts", [])
            if fact.get("quality_gate") != "rejected" and fact.get("type")
        }
        missing = [
            item for item in learned_types
            if item["type"] not in current_types
        ]
        return {
            "status": "learned",
            "sample_size": sample_size,
            "minimum": MIN_ADAPTIVE_PROFILE_DOCUMENTS,
            "learned_expected_types": learned_types[:40],
            "learned_expected_roles": learned_roles[:60],
            "missing_learned_expected": missing[:30],
            "policy": "Адаптивные поля являются ожиданиями корпуса, но не становятся обязательными автоматически.",
        }

    def _regression_guard(
        self,
        previous: dict[str, Any] | None,
        current: dict[str, Any],
    ) -> dict[str, Any]:
        if not previous:
            return {
                "status": "baseline",
                "severity": "none",
                "lost_verified_facts": 0,
                "lost_ratio": 0.0,
                "profile_delta": 0,
                "classification_changed": False,
                "reasons": [],
            }

        previous_verified = {
            self._fact_key(fact)
            for fact in previous.get("molecules", {}).get("facts", [])
            if fact.get("quality_gate") == "accepted"
            or fact.get("feedback", {}).get("action") in {"confirm", "correct"}
        }
        current_keys = {
            self._fact_key(fact)
            for fact in current.get("molecules", {}).get("facts", [])
            if fact.get("quality_gate") != "rejected"
        }
        lost = previous_verified - current_keys
        lost_ratio = len(lost) / max(1, len(previous_verified))
        previous_profile = int(previous.get("profile", {}).get("completeness_percent") or 0)
        current_profile = int(current.get("profile", {}).get("completeness_percent") or 0)
        profile_delta = current_profile - previous_profile

        old_class = previous.get("classification", {})
        new_class = current.get("classification", {})
        classification_changed = old_class.get("document_type") != new_class.get("document_type")
        old_confidence = float(old_class.get("confidence") or 0)
        new_confidence = float(new_class.get("confidence") or 0)

        reasons = []
        severe = False
        if len(previous_verified) >= 4 and lost_ratio > 0.25:
            severe = True
            reasons.append("lost_verified_facts")
        if profile_delta <= -30:
            severe = True
            reasons.append("profile_completeness_drop")
        if classification_changed and old_confidence >= 0.80 and new_confidence <= old_confidence:
            severe = True
            reasons.append("classification_regression")

        return {
            "status": "blocked" if severe else "passed",
            "severity": "high" if severe else "none",
            "lost_verified_facts": len(lost),
            "lost_ratio": round(lost_ratio, 4),
            "lost_examples": [
                {"type": key[0], "role": key[1], "canonical": key[2]}
                for key in sorted(lost)[:30]
            ],
            "profile_delta": profile_delta,
            "classification_changed": classification_changed,
            "reasons": reasons,
        }

    @staticmethod
    def _rule_lifecycle(correction_rules: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for rule in correction_rules:
            grouped[
                (
                    str(rule.get("fact_type") or ""),
                    str(rule.get("original_canonical") or ""),
                )
            ].append(rule)

        items = []
        counts = Counter()
        for key, rules in grouped.items():
            ordered = sorted(
                rules,
                key=lambda rule: int(rule.get("support_count") or 0),
                reverse=True,
            )
            top = ordered[0]
            support = int(top.get("support_count") or 0)
            competing = [
                rule for rule in ordered[1:]
                if int(rule.get("support_count") or 0) >= 2
            ]
            if support >= 3 and not competing:
                status = "active"
            elif support >= 3 and competing:
                status = "shadow"
            else:
                status = "candidate"
            counts[status] += 1
            items.append({
                "fact_type": key[0],
                "original_canonical": key[1],
                "status": status,
                "support_count": support,
                "competing_rules": len(competing),
                "corrected": top.get("corrected"),
            })
        return {
            "counts": dict(counts),
            "items": items[:100],
            "policy": "Правило активно только при достаточной поддержке и отсутствии конкурирующей коррекции.",
        }

    def _association_hypotheses(
        self,
        dna: dict[str, Any],
        corpus: list[dict[str, Any]],
    ) -> dict[str, Any]:
        document_entities: dict[str, set[str]] = {}
        current_id = str(dna.get("identity", {}).get("file_id") or "")
        all_documents = [*corpus]
        if not any(str(item.get("identity", {}).get("file_id") or "") == current_id for item in all_documents):
            all_documents.append(dna)

        for item in all_documents:
            file_id = str(item.get("identity", {}).get("file_id") or "")
            if not file_id:
                continue
            keys = {
                str(entity.get("canonical_key"))
                for entity in item.get("entities", [])
                if entity.get("canonical_key")
            }
            document_entities[file_id] = keys

        current_entities = document_entities.get(current_id, set())
        pair_support: Counter[tuple[str, str]] = Counter()
        entity_docs: Counter[str] = Counter()

        for keys in document_entities.values():
            ordered = sorted(keys)
            entity_docs.update(ordered)
            for index, left in enumerate(ordered):
                for right in ordered[index + 1:]:
                    pair_support[(left, right)] += 1

        items = []
        for (left, right), support in pair_support.items():
            if support < MIN_HYPOTHESIS_SUPPORT:
                continue
            if left not in current_entities and right not in current_entities:
                continue
            denominator = max(1, min(entity_docs[left], entity_docs[right]))
            confidence = support / denominator
            hypothesis_id = "hyp-" + sha1(
                f"association|{left}|{right}".encode("utf-8")
            ).hexdigest()[:16]
            items.append({
                "id": hypothesis_id,
                "kind": "association",
                "left": left,
                "right": right,
                "support_documents": support,
                "confidence": round(min(confidence, 0.99), 3),
                "status": "hypothesis",
                "causal": False,
                "promotion_allowed": False,
            })
        items.sort(key=lambda item: (-item["support_documents"], -item["confidence"], item["id"]))
        return {
            "items": items[:60],
            "count": len(items),
            "minimum_support": MIN_HYPOTHESIS_SUPPORT,
            "policy": "Повторное совместное появление создаёт только гипотезу ассоциации, не факт и не причинность.",
        }

    @staticmethod
    def _active_learning(dna: dict[str, Any]) -> dict[str, Any]:
        queue = []
        for fact in dna.get("molecules", {}).get("facts", []):
            confidence = float(fact.get("calibrated_confidence", fact.get("confidence") or 0))
            gate = fact.get("quality_gate")
            fact_type = str(fact.get("type") or "")
            if gate == "review" or (
                fact_type in HIGH_IMPORTANCE_TYPES and confidence < 0.90
            ):
                importance = 2 if fact_type in HIGH_IMPORTANCE_TYPES else 1
                uncertainty = 1.0 - confidence
                priority = importance * 0.7 + uncertainty * 0.3
                queue.append({
                    "kind": "fact_review",
                    "fact_id": fact.get("id"),
                    "fact_type": fact_type,
                    "value": fact.get("value"),
                    "confidence": round(confidence, 3),
                    "priority": round(priority, 3),
                    "source": fact.get("source"),
                })

        for dependency in dna.get("dependencies", {}).get("items", []):
            if dependency.get("status") != "resolved":
                queue.append({
                    "kind": "dependency_review",
                    "dependency_id": dependency.get("id"),
                    "value": dependency.get("document_number"),
                    "priority": 0.92,
                    "source": dependency.get("source"),
                })

        queue.sort(key=lambda item: (-float(item.get("priority") or 0), str(item.get("kind"))))
        return {
            "items": queue[:80],
            "count": len(queue),
            "policy": "Приоритет получают важные и неопределённые факты; проверка пользователя повышает качество будущей калибровки.",
        }

    @staticmethod
    def _experience_snapshot(
        dna: dict[str, Any],
        *,
        corpus: list[dict[str, Any]],
        feedback_metrics: dict[str, Any],
        rules: dict[str, Any],
        hypotheses: dict[str, Any],
        self_review: dict[str, Any],
    ) -> dict[str, Any]:
        feedback_samples = sum(
            int(item.get("samples") or 0)
            for item in feedback_metrics.values()
        )
        active_rules = int(rules.get("counts", {}).get("active") or 0)
        verified_documents = sum(
            1 for item in corpus
            if item.get("quality_gate", {}).get("memory_ready")
        )
        self_review_score = int(self_review.get("score") or 0)
        accepted = int(dna.get("quality_gate", {}).get("accepted") or 0)
        review = int(dna.get("quality_gate", {}).get("review") or 0)
        total = max(1, accepted + review + int(dna.get("quality_gate", {}).get("rejected") or 0))
        evidence_quality = accepted / total

        maturity = (
            min(len(corpus) / 50, 1.0) * 0.25
            + min(feedback_samples / 100, 1.0) * 0.30
            + min(active_rules / 20, 1.0) * 0.20
            + evidence_quality * 0.25
        )
        return {
            "corpus_documents": len(corpus),
            "verified_documents": verified_documents,
            "feedback_samples": feedback_samples,
            "active_rules": active_rules,
            "hypotheses": int(hypotheses.get("count") or 0),
            "evidence_quality": round(evidence_quality, 4),
            "maturity_score": round(maturity * 100, 2),
            "self_review_proxy": self_review_score,
            "note": "Maturity — техническая метрика накопленного проверяемого опыта, а не процент интеллекта или сознания.",
        }
