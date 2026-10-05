from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha1, sha256
import json
import re
from typing import Any


ADVANCED_DNA_VERSION = "0.5.0"
MAX_AI_CONTEXT_FACTS = 80
MAX_EVIDENCE_CHAINS = 180

INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ignore_instructions", re.compile(r"(?i)(игнорируй|игнорировать|ignore)\s+(?:все\s+)?(?:предыдущ|previous).{0,40}(?:инструкц|instruction)")),
    ("system_override", re.compile(r"(?i)(system\s*prompt|системн(?:ый|ые)\s+промпт|system\s+message|системн(?:ое|ые)\s+сообщен)")),
    ("role_override", re.compile(r"(?i)(ты\s+теперь|you\s+are\s+now|act\s+as|притворись|роль\s*:)")),
    ("tool_command", re.compile(r"(?i)(выполни|execute|run)\s+(?:команд|command|shell|powershell|cmd|bash)")),
    ("secret_exfiltration", re.compile(r"(?i)(api[-_ ]?key|токен|token|парол|password|secret).{0,50}(?:покажи|отправ|вывед|print|send|reveal)")),
)

SENSITIVE_TYPES = {
    "person": ("personal", "ФИО"),
    "phone": ("personal", "Телефон"),
    "email": ("personal", "E-mail"),
    "settlement_account": ("financial", "Расчётный счёт"),
    "correspondent_account": ("financial", "Корреспондентский счёт"),
    "bik": ("financial", "БИК"),
    "inn": ("business_identifier", "ИНН"),
    "kpp": ("business_identifier", "КПП"),
    "ogrn": ("business_identifier", "ОГРН"),
}

DEPENDENCY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Договор", ("договор", "контракт")),
    ("Счёт", ("счет", "счёт")),
    ("Счёт-оферта", ("оферта", "счет-оферта", "счёт-оферта")),
    ("Приказ", ("приказ",)),
    ("Распоряжение", ("распоряжение",)),
    ("Акт", ("акт",)),
    ("Накладная", ("накладная",)),
    ("Служебная записка", ("служебн",)),
    ("Путевой лист", ("путев",)),
)

OBLIGATION_ACTIONS = {"request", "order", "approve", "pay", "deliver"}


class AdvancedDNAEngine:
    """Дополняет базовую ДНК 0.4 доказуемыми внутренними слоями без внешнего ИИ."""

    def enrich(
        self,
        dna: dict[str, Any],
        *,
        preview: dict[str, Any],
        calibration: dict[str, Any] | None = None,
        learned_rules: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        facts = dna.get("molecules", {}).get("facts", [])
        self._apply_spatial_evidence(facts, preview)
        correction_hits = self._apply_learned_corrections(facts, learned_rules or [])
        calibration_result = self._apply_calibration(facts, calibration or {})

        schema = self._document_schema(dna)
        clusters = self._entity_resolution(dna)
        obligations = self._obligations(dna)
        temporal_contradictions = self._temporal_contradictions(dna, obligations)
        dependencies = self._dependencies(dna)
        security = self._security_layer(dna, preview)
        sensitive = self._sensitive_data(dna)
        template = self._template_fingerprint(dna)
        promotion = self._knowledge_promotion(dna)
        evidence_chains = self._evidence_chains(
            dna,
            obligations=obligations,
            temporal_contradictions=temporal_contradictions,
        )
        ai_context = self._selective_ai_context(
            dna,
            security=security,
            sensitive=sensitive,
            obligations=obligations,
        )

        dna["advanced_engine_version"] = ADVANCED_DNA_VERSION
        dna["document_schema"] = schema
        dna["entity_resolution"] = clusters
        dna["obligations"] = obligations
        dna.setdefault("contradictions", {})["temporal"] = temporal_contradictions
        dna["dependencies"] = dependencies
        dna["security"] = security
        dna["sensitive_data"] = sensitive
        dna["template_fingerprint"] = template
        dna["knowledge_promotion"] = promotion
        dna["evidence_chains"] = evidence_chains
        dna["ai_context"] = ai_context
        dna["calibration"] = calibration_result
        dna["learned_corrections"] = {
            "applied": correction_hits,
            "policy": "Только точные канонические коррекции с поддержкой минимум в 3 разных документах.",
        }

        if security["prompt_injection"]["detected"]:
            self._append_risk(
                dna,
                code="prompt-injection",
                severity="attention",
                title="Потенциальная prompt injection",
                reason="В содержимом найдены фразы, похожие на инструкции модели. Они считаются только данными документа.",
            )

        blocking_temporal = [
            item for item in temporal_contradictions
            if item.get("level") in {"attention", "critical"}
        ]
        if blocking_temporal:
            self._append_risk(
                dna,
                code="temporal-contradiction",
                severity="attention",
                title="Временное противоречие",
                reason=f"Найдено временных противоречий: {len(blocking_temporal)}.",
            )

        gate = dna.setdefault("quality_gate", {})
        reasons = list(gate.get("reasons") or [])
        if security["prompt_injection"]["detected"] and "prompt_injection_review" not in reasons:
            reasons.append("prompt_injection_review")
        if blocking_temporal and "temporal_contradiction" not in reasons:
            reasons.append("temporal_contradiction")
        gate["reasons"] = reasons
        gate["memory_ready"] = bool(gate.get("memory_ready")) and not (
            security["prompt_injection"]["detected"] or blocking_temporal
        )
        dna["knowledge_promotion"] = self._knowledge_promotion(dna)

        return dna

    @staticmethod
    def _append_risk(
        dna: dict[str, Any],
        *,
        code: str,
        severity: str,
        title: str,
        reason: str,
    ) -> None:
        risks = dna.setdefault("risks", [])
        if any(item.get("code") == code for item in risks):
            return
        risks.append(
            {
                "code": code,
                "severity": severity,
                "title": title,
                "reason": reason,
            }
        )

    @staticmethod
    def _apply_spatial_evidence(facts: list[dict[str, Any]], preview: dict[str, Any]) -> None:
        mode = preview.get("mode")
        rows = preview.get("rows") or []
        for fact in facts:
            source = fact.setdefault("source", {})
            line = int(source.get("line") or 0)
            locator: dict[str, Any] = {
                "page": None,
                "block": "line",
                "line": line or None,
                "coordinates": None,
                "coordinate_status": "not_available",
            }

            if mode == "table" and line > 0 and line <= len(rows):
                row = rows[line - 1]
                value = str(fact.get("value") or "").casefold()
                canonical = str((fact.get("normalized") or {}).get("canonical") or "").casefold()
                matching_columns = []
                for column_index, cell in enumerate(row, start=1):
                    cell_text = str(cell)
                    lowered = cell_text.casefold()
                    if value and value in lowered:
                        matching_columns.append(column_index)
                    elif canonical and canonical in lowered:
                        matching_columns.append(column_index)
                locator.update(
                    {
                        "block": "table_cell" if matching_columns else "table_row",
                        "table": 1,
                        "row": line,
                        "columns": matching_columns,
                        "cell": (
                            {"row": line, "column": matching_columns[0]}
                            if len(matching_columns) == 1
                            else None
                        ),
                    }
                )
            elif mode in {"pdf", "image"}:
                locator.update(
                    {
                        "block": "visual_document",
                        "coordinate_status": "pending_ocr",
                    }
                )

            source["locator"] = locator

    @staticmethod
    def _apply_calibration(
        facts: list[dict[str, Any]],
        calibration: dict[str, Any],
    ) -> dict[str, Any]:
        applied = 0
        for fact in facts:
            stats = calibration.get(str(fact.get("type"))) or {}
            samples = int(stats.get("samples") or 0)
            if samples < 5:
                continue
            reliability = float(stats.get("reliability") or 1.0)
            factor = min(1.05, max(0.80, 0.85 + reliability * 0.20))
            original = float(fact.get("confidence") or 0)
            calibrated = min(1.0, max(0.0, original * factor))
            fact["calibrated_confidence"] = round(calibrated, 3)
            fact["calibration"] = {
                "samples": samples,
                "reliability": round(reliability, 3),
                "factor": round(factor, 3),
            }
            if calibrated < 0.72 and fact.get("quality_gate") == "accepted":
                fact["quality_gate"] = "review"
            applied += 1
        return {
            "fact_types": calibration,
            "applied_to_facts": applied,
            "minimum_samples": 5,
        }

    @staticmethod
    def _apply_learned_corrections(
        facts: list[dict[str, Any]],
        rules: list[dict[str, Any]],
    ) -> int:
        lookup = {
            (str(rule.get("fact_type")), str(rule.get("original_canonical"))): rule
            for rule in rules
            if int(rule.get("support_count") or 0) >= 3
        }
        hits = 0
        for fact in facts:
            normalized = fact.get("normalized") or {}
            canonical = str(normalized.get("canonical") or "")
            rule = lookup.get((str(fact.get("type")), canonical))
            if not rule:
                continue
            corrected = rule.get("corrected")
            if not isinstance(corrected, dict) or not corrected:
                continue
            fact["learned_correction"] = {
                "from": canonical,
                "support_count": int(rule.get("support_count") or 0),
                "source": "confirmed_user_corrections",
            }
            fact["original_normalized"] = dict(normalized)
            fact["normalized"] = dict(corrected)
            fact["quality_gate"] = "accepted"
            fact["confidence"] = max(float(fact.get("confidence") or 0), 0.995)
            hits += 1
        return hits

    @staticmethod
    def _document_schema(dna: dict[str, Any]) -> dict[str, Any]:
        facts = dna.get("molecules", {}).get("facts", [])
        slots: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fact in facts:
            if fact.get("quality_gate") == "rejected":
                continue
            role = str(fact.get("role") or fact.get("type") or "fact")
            slots[role].append(
                {
                    "fact_id": fact.get("id"),
                    "type": fact.get("type"),
                    "value": fact.get("value"),
                    "canonical": (fact.get("normalized") or {}).get("canonical"),
                    "confidence": fact.get("confidence"),
                    "source": fact.get("source"),
                }
            )

        profile = dna.get("profile", {})
        logical_sections = []
        section_map = {
            "identity": ("primary_document_number", "document_date"),
            "parties": ("organization", "person", "inn", "kpp", "ogrn"),
            "transport": ("primary_vehicle_plate", "vehicle_plate_mention", "primary_vin", "vin_mention"),
            "finance": ("total_amount", "amount", "vat_amount", "quantity"),
            "time": ("deadline", "period_date", "departure_time", "return_time", "date_mention", "time_mention"),
            "actions": ("request", "order", "approve", "pay", "deliver", "inform"),
        }
        for section, roles in section_map.items():
            fact_ids = [
                item["fact_id"]
                for role in roles
                for item in slots.get(role, [])
                if item.get("fact_id")
            ]
            logical_sections.append(
                {
                    "id": section,
                    "roles": list(roles),
                    "fact_ids": fact_ids,
                    "present": bool(fact_ids),
                }
            )

        return {
            "document_type": dna.get("classification", {}).get("document_type"),
            "profile_completeness_percent": profile.get("completeness_percent", 0),
            "slots": dict(slots),
            "sections": logical_sections,
            "missing_required": list(profile.get("missing_required") or []),
        }

    @staticmethod
    def _entity_resolution(dna: dict[str, Any]) -> dict[str, Any]:
        entities = dna.get("entities", [])
        facts = dna.get("molecules", {}).get("facts", [])
        by_line: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for fact in facts:
            line = int((fact.get("source") or {}).get("line") or 0)
            if line:
                by_line[line].append(fact)

        clusters: list[dict[str, Any]] = []
        used: set[str] = set()

        for entity in entities:
            entity_id = str(entity.get("id"))
            if not entity_id or entity_id in used:
                continue
            category = entity.get("category")
            cluster_entities = [entity]
            used.add(entity_id)

            if category == "Организация":
                source_line = int((entity.get("source") or {}).get("line") or 0)
                line_facts = by_line.get(source_line, [])
                identifiers = {
                    fact.get("type"): (fact.get("normalized") or {}).get("canonical")
                    for fact in line_facts
                    if fact.get("type") in {"inn", "kpp", "ogrn"}
                }
                for candidate in entities:
                    candidate_id = str(candidate.get("id"))
                    if candidate_id in used or candidate.get("category") != "Организация":
                        continue
                    candidate_line = int((candidate.get("source") or {}).get("line") or 0)
                    if candidate_line == source_line and source_line:
                        cluster_entities.append(candidate)
                        used.add(candidate_id)

                canonical_id = (
                    f"organization:inn:{identifiers['inn']}"
                    if identifiers.get("inn")
                    else str(entity.get("canonical_key"))
                )
            elif category == "Транспорт":
                source_line = int((entity.get("source") or {}).get("line") or 0)
                line_facts = by_line.get(source_line, [])
                vin = next(
                    ((fact.get("normalized") or {}).get("canonical") for fact in line_facts if fact.get("type") == "vin"),
                    None,
                )
                plate = next(
                    ((fact.get("normalized") or {}).get("canonical") for fact in line_facts if fact.get("type") == "vehicle_plate"),
                    None,
                )
                canonical_id = f"vehicle:{vin or plate or entity.get('canonical')}"
            else:
                canonical_id = str(entity.get("canonical_key"))

            cluster_key = sha1(canonical_id.encode("utf-8")).hexdigest()[:16]
            clusters.append(
                {
                    "id": f"cluster-{cluster_key}",
                    "category": category,
                    "canonical_id": canonical_id,
                    "entity_ids": [item.get("id") for item in cluster_entities],
                    "values": [item.get("value") for item in cluster_entities],
                    "evidence_fact_ids": sorted(
                        {
                            fact_id
                            for item in cluster_entities
                            for fact_id in (item.get("source_fact_ids") or [])
                        }
                    ),
                    "resolution": "deterministic",
                }
            )

        return {
            "clusters": clusters,
            "count": len(clusters),
            "policy": "ИНН/VIN имеют приоритет над написанием имени; совместное появление в одной строке используется как доказательство.",
        }

    @staticmethod
    def _obligations(dna: dict[str, Any]) -> dict[str, Any]:
        actions = dna.get("actions", [])
        facts = dna.get("molecules", {}).get("facts", [])
        by_line: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for fact in facts:
            line = int((fact.get("source") or {}).get("line") or 0)
            if line:
                by_line[line].append(fact)

        obligations = []
        for action in actions:
            if action.get("type") not in OBLIGATION_ACTIONS:
                continue
            source = action.get("source") or {}
            line = int(source.get("line") or 0)
            candidates = []
            for near_line in (line - 1, line, line + 1):
                candidates.extend(by_line.get(near_line, []))

            deadlines = [
                fact for fact in candidates
                if fact.get("type") == "date" and fact.get("role") in {"deadline", "date_mention"}
            ]
            actors = [
                fact for fact in candidates
                if fact.get("type") in {"person", "organization"}
            ]
            related_documents = [
                fact for fact in candidates
                if fact.get("type") == "document_number"
            ]

            obligation_id = "obligation-" + sha1(
                f"{action.get('id')}|{line}|{action.get('text')}".encode("utf-8")
            ).hexdigest()[:16]
            obligations.append(
                {
                    "id": obligation_id,
                    "action_id": action.get("id"),
                    "type": action.get("type"),
                    "text": action.get("text"),
                    "actor_fact_ids": [fact.get("id") for fact in actors],
                    "deadline_fact_ids": [fact.get("id") for fact in deadlines],
                    "basis_fact_ids": [fact.get("id") for fact in related_documents],
                    "status": "open",
                    "confidence": min(
                        0.98,
                        float(action.get("confidence") or 0.8)
                        + (0.04 if deadlines else 0)
                        + (0.03 if actors else 0),
                    ),
                    "evidence": source,
                }
            )
        return {
            "items": obligations,
            "count": len(obligations),
            "open_count": sum(1 for item in obligations if item["status"] == "open"),
        }

    @staticmethod
    def _temporal_contradictions(
        dna: dict[str, Any],
        obligations: dict[str, Any],
    ) -> list[dict[str, Any]]:
        contradictions = []
        facts = {
            fact.get("id"): fact
            for fact in dna.get("molecules", {}).get("facts", [])
            if fact.get("id")
        }

        document_dates = [
            str((fact.get("normalized") or {}).get("canonical"))
            for fact in facts.values()
            if fact.get("type") == "date" and fact.get("role") == "document_date"
        ]
        deadlines = [
            str((fact.get("normalized") or {}).get("canonical"))
            for fact in facts.values()
            if fact.get("type") == "date" and fact.get("role") == "deadline"
        ]
        if document_dates and deadlines:
            document_date = min(document_dates)
            for deadline in deadlines:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline) and deadline < document_date:
                    contradictions.append(
                        {
                            "code": "deadline-before-document",
                            "level": "attention",
                            "message": "Крайний срок указан раньше даты документа.",
                            "document_date": document_date,
                            "deadline": deadline,
                        }
                    )

        departure = [
            str((fact.get("normalized") or {}).get("canonical"))
            for fact in facts.values()
            if fact.get("type") == "time" and fact.get("role") == "departure_time"
        ]
        returned = [
            str((fact.get("normalized") or {}).get("canonical"))
            for fact in facts.values()
            if fact.get("type") == "time" and fact.get("role") == "return_time"
        ]
        if departure and returned and min(returned) < min(departure):
            contradictions.append(
                {
                    "code": "return-before-departure",
                    "level": "attention",
                    "message": "Время возвращения раньше времени выезда.",
                    "departure": min(departure),
                    "return": min(returned),
                }
            )

        for obligation in obligations.get("items", []):
            if obligation.get("type") == "pay" and not obligation.get("basis_fact_ids"):
                contradictions.append(
                    {
                        "code": "payment-without-basis",
                        "level": "info",
                        "message": "Обнаружено требование оплаты без номера документа-основания рядом с действием.",
                        "obligation_id": obligation.get("id"),
                    }
                )
        return contradictions

    @staticmethod
    def _dependencies(dna: dict[str, Any]) -> dict[str, Any]:
        items = []
        current_number = next(
            (
                str((fact.get("normalized") or {}).get("canonical") or fact.get("value"))
                for fact in dna.get("molecules", {}).get("facts", [])
                if fact.get("type") == "document_number"
                and fact.get("role") == "primary_document_number"
            ),
            None,
        )
        for fact in dna.get("molecules", {}).get("facts", []):
            if fact.get("type") != "document_number":
                continue
            number = str((fact.get("normalized") or {}).get("canonical") or fact.get("value"))
            if current_number and number == current_number:
                continue
            excerpt = str((fact.get("source") or {}).get("excerpt") or "").casefold().replace("ё", "е")
            expected_type = None
            for dependency_type, keywords in DEPENDENCY_RULES:
                if any(keyword.replace("ё", "е") in excerpt for keyword in keywords):
                    expected_type = dependency_type
                    break
            items.append(
                {
                    "id": "dependency-" + sha1(
                        f"{expected_type}|{number}|{fact.get('id')}".encode("utf-8")
                    ).hexdigest()[:16],
                    "document_number": number,
                    "expected_type": expected_type,
                    "source_fact_id": fact.get("id"),
                    "source": fact.get("source"),
                    "status": "unresolved",
                    "resolved_file_ids": [],
                }
            )
        return {
            "items": items,
            "count": len(items),
            "unresolved_count": len(items),
        }

    @staticmethod
    def _security_layer(dna: dict[str, Any], preview: dict[str, Any]) -> dict[str, Any]:
        text = str(preview.get("text") or "")
        if preview.get("mode") == "table":
            text = "\n".join(
                "\t".join(str(value) for value in row)
                for row in (preview.get("rows") or [])
            )

        findings = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            for code, pattern in INJECTION_PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                findings.append(
                    {
                        "code": code,
                        "line": line_number,
                        "excerpt": line[:260],
                        "evidence_hash": sha256(
                            f"{line_number}|{line}".encode("utf-8")
                        ).hexdigest(),
                        "trust_domain": "document_content",
                    }
                )
        return {
            "trust_domain": "document_content",
            "document_instructions_are_commands": False,
            "prompt_injection": {
                "detected": bool(findings),
                "count": len(findings),
                "findings": findings[:60],
                "policy": "Текст документа никогда не повышается до системной/инструментальной инструкции.",
            },
        }

    @staticmethod
    def _sensitive_data(dna: dict[str, Any]) -> dict[str, Any]:
        findings = []
        counts = Counter()
        for fact in dna.get("molecules", {}).get("facts", []):
            classification = SENSITIVE_TYPES.get(str(fact.get("type")))
            if not classification:
                continue
            category, label = classification
            counts[category] += 1
            findings.append(
                {
                    "fact_id": fact.get("id"),
                    "category": category,
                    "label": label,
                    "source": fact.get("source"),
                    "external_ai_policy": (
                        "redact"
                        if category in {"personal", "financial"}
                        else "allow_if_needed"
                    ),
                }
            )
        return {
            "counts": dict(counts),
            "findings": findings[:160],
            "requires_redaction_for_external_ai": any(
                item["external_ai_policy"] == "redact" for item in findings
            ),
        }

    @staticmethod
    def _template_fingerprint(dna: dict[str, Any]) -> dict[str, Any]:
        headings = []
        for item in dna.get("anatomy", {}).get("headings", []):
            heading = str(item.get("text") or "").casefold().replace("ё", "е")
            heading = re.sub(r"\b(?:19|20)\d{2}[-./]\d{1,2}[-./]\d{1,2}\b", "<date>", heading)
            heading = re.sub(r"\b\d{1,2}[-./]\d{1,2}[-./](?:19|20)\d{2}\b", "<date>", heading)
            heading = re.sub(r"(?:№|\bno?\.?)\s*[a-zа-я0-9./_-]+", "№<id>", heading, flags=re.IGNORECASE)
            heading = re.sub(r"\d+(?:[\s\u00a0]\d{3})*(?:[,.]\d+)?", "<n>", heading)
            heading = re.sub(r"\s+", " ", heading).strip()
            headings.append(heading)
        roles = sorted(
            {
                str(fact.get("role"))
                for fact in dna.get("molecules", {}).get("facts", [])
                if fact.get("role")
            }
        )
        material = json.dumps(
            {
                "document_type": dna.get("classification", {}).get("document_type"),
                "preview_mode": dna.get("anatomy", {}).get("preview_mode"),
                "headings": headings,
                "roles": roles,
                "table_columns": dna.get("anatomy", {}).get("table_columns", 0),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "sha256": sha256(material.encode("utf-8")).hexdigest(),
            "headings": headings[:24],
            "roles": roles,
            "structural_signature": material[:1000],
        }

    @staticmethod
    def _knowledge_promotion(dna: dict[str, Any]) -> dict[str, Any]:
        stages = Counter()
        facts = []
        contradictions = (
            list(dna.get("contradictions", {}).get("internal") or [])
            + list(dna.get("contradictions", {}).get("cross_document") or [])
        )
        blocked = bool(contradictions) or not dna.get("integrity", {}).get("matches")

        for fact in dna.get("molecules", {}).get("facts", []):
            gate = fact.get("quality_gate")
            if gate == "rejected":
                stage = "rejected"
            elif gate == "accepted" and not blocked:
                stage = "checked"
            elif (fact.get("normalized") or {}).get("canonical") is not None:
                stage = "normalized"
            else:
                stage = "extracted"
            if fact.get("feedback", {}).get("action") in {"confirm", "correct"}:
                stage = "confirmed"
            stages[stage] += 1
            facts.append(
                {
                    "fact_id": fact.get("id"),
                    "stage": stage,
                    "memory_eligible": stage == "confirmed" and not blocked,
                }
            )

        return {
            "pipeline": ["extracted", "normalized", "matched", "checked", "confirmed", "knowledge"],
            "counts": dict(stages),
            "facts": facts[:420],
            "document_memory_ready": bool(dna.get("quality_gate", {}).get("memory_ready")),
            "policy": "knowledge требует подтверждения; checked не равен knowledge",
        }

    @staticmethod
    def _evidence_chains(
        dna: dict[str, Any],
        *,
        obligations: dict[str, Any],
        temporal_contradictions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        facts = {
            fact.get("id"): fact
            for fact in dna.get("molecules", {}).get("facts", [])
            if fact.get("id")
        }
        chains = []

        for obligation in obligations.get("items", []):
            fact_ids = (
                list(obligation.get("actor_fact_ids") or [])
                + list(obligation.get("deadline_fact_ids") or [])
                + list(obligation.get("basis_fact_ids") or [])
            )
            chains.append(
                {
                    "claim_id": obligation.get("id"),
                    "claim_type": "obligation",
                    "rule": "action_near_actor_deadline_basis",
                    "fact_ids": fact_ids,
                    "evidence": [
                        facts[fact_id].get("source")
                        for fact_id in fact_ids
                        if fact_id in facts
                    ] + [obligation.get("evidence")],
                    "inferred": True,
                    "confidence": obligation.get("confidence"),
                }
            )

        for contradiction in temporal_contradictions:
            chains.append(
                {
                    "claim_id": "check-" + sha1(
                        json.dumps(contradiction, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    ).hexdigest()[:16],
                    "claim_type": "temporal_check",
                    "rule": contradiction.get("code"),
                    "fact_ids": [],
                    "evidence": [contradiction],
                    "inferred": False,
                    "confidence": 1.0,
                }
            )

        return chains[:MAX_EVIDENCE_CHAINS]

    @staticmethod
    def _redacted_value(fact: dict[str, Any], sensitive_ids: set[str]) -> str:
        fact_id = str(fact.get("id") or "")
        if fact_id in sensitive_ids:
            return f"[СКРЫТО:{fact.get('label') or fact.get('type')}]"
        return str((fact.get("normalized") or {}).get("canonical") or fact.get("value") or "")

    def _selective_ai_context(
        self,
        dna: dict[str, Any],
        *,
        security: dict[str, Any],
        sensitive: dict[str, Any],
        obligations: dict[str, Any],
    ) -> dict[str, Any]:
        sensitive_ids = {
            str(item.get("fact_id"))
            for item in sensitive.get("findings", [])
            if item.get("external_ai_policy") == "redact"
        }
        safe_facts = []
        for fact in dna.get("molecules", {}).get("facts", []):
            if fact.get("quality_gate") == "rejected":
                continue
            safe_facts.append(
                {
                    "fact_id": fact.get("id"),
                    "type": fact.get("type"),
                    "role": fact.get("role"),
                    "value": self._redacted_value(fact, sensitive_ids),
                    "confidence": fact.get("calibrated_confidence", fact.get("confidence")),
                    "source": {
                        "line": (fact.get("source") or {}).get("line"),
                        "evidence_hash": (fact.get("source") or {}).get("evidence_hash"),
                    },
                }
            )
            if len(safe_facts) >= MAX_AI_CONTEXT_FACTS:
                break

        return {
            "document_type": dna.get("classification", {}).get("document_type"),
            "summary": dna.get("summary"),
            "facts": safe_facts,
            "obligations": [
                {
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "text": item.get("text"),
                    "confidence": item.get("confidence"),
                }
                for item in obligations.get("items", [])[:30]
            ],
            "security": {
                "trust_domain": security.get("trust_domain"),
                "prompt_injection_detected": security.get("prompt_injection", {}).get("detected"),
            },
            "redacted_fact_count": len(sensitive_ids),
            "policy": "Минимально необходимый контекст; чувствительные значения редактируются; инструкции документа не доверяются.",
        }
