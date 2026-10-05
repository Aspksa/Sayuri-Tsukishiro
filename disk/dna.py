from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha1, sha256
from pathlib import Path
import json
import math
import re
from typing import Any


DNA_ANALYZER_VERSION = "0.4.0"
DNA_SCHEMA_VERSION = 2
MAX_FACTS = 420
MAX_HEADINGS = 24
MAX_GRAPH_NODES = 320
MAX_TOKEN_HASHES = 256

STOPWORDS = {
    "для", "или", "при", "это", "как", "что", "его", "она", "они", "мы", "вы",
    "из", "на", "по", "от", "до", "за", "под", "над", "без", "не", "да", "и", "в",
    "к", "о", "об", "с", "со", "у", "а", "но", "же", "бы", "быть", "также",
}

LEGAL_FORMS = ("ООО", "АО", "ПАО", "ИП", "ГУП", "МУП", "ФГУП")

DOCUMENT_PROFILES: dict[str, dict[str, Any]] = {
    "Служебная записка": {
        "required": ("date",),
        "expected": ("document_number", "person", "organization", "vehicle_plate", "action"),
        "singleton_roles": ("document_date", "primary_document_number"),
    },
    "Путевой лист": {
        "required": ("date", "vehicle_plate"),
        "expected": ("person", "vin", "mileage", "time"),
        "singleton_roles": ("document_date", "primary_vehicle_plate"),
    },
    "Договор": {
        "required": ("document_number", "date"),
        "expected": ("organization", "inn", "amount"),
        "singleton_roles": ("document_date", "primary_document_number"),
    },
    "Счёт-оферта": {
        "required": ("amount",),
        "expected": ("document_number", "date", "organization", "inn", "quantity"),
        "singleton_roles": ("document_date", "primary_document_number"),
    },
    "Счёт": {
        "required": ("amount",),
        "expected": ("document_number", "date", "organization", "inn"),
        "singleton_roles": ("document_date", "primary_document_number"),
    },
    "Приказ": {
        "required": ("document_number", "date"),
        "expected": ("person", "action"),
        "singleton_roles": ("document_date", "primary_document_number"),
    },
    "Распоряжение": {
        "required": ("document_number", "date"),
        "expected": ("person", "action"),
        "singleton_roles": ("document_date", "primary_document_number"),
    },
    "Выписка ГСМ": {
        "required": ("date",),
        "expected": ("amount", "quantity", "vehicle_plate"),
        "singleton_roles": (),
    },
    "Акт": {
        "required": ("date",),
        "expected": ("document_number", "organization", "amount"),
        "singleton_roles": ("document_date", "primary_document_number"),
    },
    "Накладная": {
        "required": ("date",),
        "expected": ("document_number", "organization", "amount", "quantity"),
        "singleton_roles": ("document_date", "primary_document_number"),
    },
    "Документ": {
        "required": (),
        "expected": ("date", "document_number", "organization"),
        "singleton_roles": (),
    },
}


class DocumentDNAAnalyzer:
    """Детерминированный локальный Evidence Engine без внешнего ИИ-провайдера."""

    FACT_PATTERNS: tuple[tuple[str, str, re.Pattern[str], float], ...] = (
        (
            "date", "Дата",
            re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:19|20)\d{2}\b"),
            0.98,
        ),
        (
            "date", "Дата",
            re.compile(r"\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b"),
            0.98,
        ),
        (
            "inn", "ИНН",
            re.compile(r"(?i)\bИНН\s*[:№]?\s*(\d{10}|\d{12})\b"),
            0.995,
        ),
        (
            "kpp", "КПП",
            re.compile(r"(?i)\bКПП\s*[:№]?\s*(\d{9})\b"),
            0.995,
        ),
        (
            "ogrn", "ОГРН",
            re.compile(r"(?i)\bОГРН(?:ИП)?\s*[:№]?\s*(\d{13}|\d{15})\b"),
            0.995,
        ),
        (
            "bik", "БИК",
            re.compile(r"(?i)\bБИК\s*[:№]?\s*(\d{9})\b"),
            0.995,
        ),
        (
            "settlement_account", "Расчётный счёт",
            re.compile(r"(?i)(?:р/с|расч[её]тн(?:ый|ого)\s+сч[её]т)\s*[:№]?\s*(\d{20})"),
            0.99,
        ),
        (
            "correspondent_account", "Корреспондентский счёт",
            re.compile(r"(?i)(?:к/с|корр(?:еспондентский)?\s+сч[её]т)\s*[:№]?\s*(\d{20})"),
            0.99,
        ),
        (
            "vin", "VIN",
            re.compile(r"(?i)(?:\bVIN\s*[:№]?\s*)?\b([A-HJ-NPR-Z0-9]{17})\b"),
            0.965,
        ),
        (
            "vehicle_plate", "Госномер",
            re.compile(r"(?i)\b([АВЕКМНОРСТУХ]\s?\d{3}\s?[АВЕКМНОРСТУХ]{2}\s?\d{2,3})\b"),
            0.945,
        ),
        (
            "amount", "Сумма",
            re.compile(r"(?i)\b(\d+(?:[\s\u00a0]\d{3})*(?:[,.]\d{1,2})?\s*(?:₽|руб\.?|рублей|рубля|RUB))\b"),
            0.935,
        ),
        (
            "percent", "Процент",
            re.compile(r"\b(\d+(?:[,.]\d+)?\s*%)"),
            0.94,
        ),
        (
            "mileage", "Пробег",
            re.compile(r"(?i)\b(\d+(?:[\s\u00a0]\d{3})*(?:[,.]\d+)?\s*км)\b"),
            0.91,
        ),
        (
            "quantity", "Количество",
            re.compile(r"(?i)\b(\d+(?:[,.]\d+)?\s*(?:шт\.?|кг|г|л|литр(?:а|ов)?|т|м|м2|м²|компл\.?))\b"),
            0.89,
        ),
        (
            "time", "Время",
            re.compile(r"\b((?:[01]?\d|2[0-3])[:.]\d{2})\b"),
            0.93,
        ),
        (
            "email", "E-mail",
            re.compile(r"\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b", re.IGNORECASE),
            0.995,
        ),
        (
            "phone", "Телефон",
            re.compile(r"(?<!\d)((?:\+7|8)[\s\-(]*(?:\d[\s\-()]*){10})(?!\d)"),
            0.91,
        ),
        (
            "document_number", "Номер документа",
            re.compile(r"(?:№|\bN(?:o)?\.?)\s*([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9./_-]{0,40})"),
            0.90,
        ),
        (
            "organization", "Организация",
            re.compile(
                r"(?i)\b((?:ООО|АО|ПАО|ГУП|МУП|ФГУП)\s*[«\"„]?[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9 .&'\-]{1,80}[»\"“]?)"
            ),
            0.86,
        ),
        (
            "person", "ФИО",
            re.compile(
                r"(?i)(?:водитель|директор|руководитель|исполнитель|сотрудник|автор|адресат|ФИО)\s*[:\-]?\s*"
                r"([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)"
            ),
            0.82,
        ),
    )

    TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Путевой лист", ("путевой лист", "путевой")),
        ("Служебная записка", ("служебная записка", "служебная")),
        ("Счёт-оферта", ("счет-оферта", "счёт-оферта", "оферта")),
        ("Договор", ("договор", "контракт")),
        ("Приказ", ("приказ",)),
        ("Распоряжение", ("распоряжение",)),
        ("Выписка ГСМ", ("выписка гсм", "топливная карта", "горюче-смаз")),
        ("Счёт", ("счет", "счёт")),
        ("Акт", ("акт ", "акт\n", "акт_")),
        ("Накладная", ("накладная",)),
    )

    ACTION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("request", ("просим", "прошу", "необходимо", "требуется")),
        ("order", ("приказываю", "обязать", "назначить")),
        ("approve", ("согласовать", "утвердить", "одобрить")),
        ("inform", ("сообщаю", "уведомляю", "информируем")),
        ("pay", ("оплатить", "произвести оплату")),
        ("deliver", ("поставить", "передать", "предоставить")),
    )

    def analyze(
        self,
        *,
        item: dict[str, Any],
        properties: dict[str, Any],
        preview: dict[str, Any],
        integrity: dict[str, Any],
    ) -> dict[str, Any]:
        text, content_meta = self._text_and_structure(preview)
        classification = self._classify(item["name"], text, item.get("category", "other"))
        facts = self._extract_facts(text)
        actions = self._extract_actions(text)
        for action in actions:
            facts.append(self._action_as_fact(action))

        fact_counts = Counter(fact["type"] for fact in facts)
        headings = self._headings(text)
        profile = self._profile(classification["document_type"], facts)
        arithmetic = self._arithmetic_checks(preview)
        internal_contradictions = self._internal_contradictions(facts, profile)
        risks = self._risk_rules(item, preview, integrity, profile, arithmetic, internal_contradictions)
        checks = self._checks(
            item, preview, integrity, facts, profile, arithmetic, internal_contradictions, risks
        )
        quality_gate = self._quality_gate(facts, integrity, risks, internal_contradictions)
        document_quality = self._document_quality(preview, content_meta, profile, quality_gate, integrity)
        entities = self._entity_candidates(facts)
        temporal = self._temporal_model(facts)
        fingerprint = self._semantic_fingerprint(text, facts)
        graph = self._graph_ready(item, facts, entities, actions)
        stages = self._stages(
            preview, facts, classification, integrity, profile, quality_gate, fingerprint
        )
        coverage = self._coverage(stages)

        return {
            "schema_version": DNA_SCHEMA_VERSION,
            "analyzer_version": DNA_ANALYZER_VERSION,
            "status": "изучено" if coverage >= 85 else "частично изучено",
            "coverage_percent": coverage,
            "method": {
                "name": "Локальный Evidence Engine ДНК",
                "external_ai_used": False,
                "semantic_ai_status": "не подключён",
                "layers": [
                    "structure", "normalization", "evidence", "profiles",
                    "arithmetic", "contradictions", "quality_gate", "fingerprint",
                ],
                "note": (
                    "Факты, нормализация, проверки и доказательства построены локально. "
                    "ИИ не используется и смысловые выводы без доказательств не создаются."
                ),
            },
            "identity": {
                "file_id": item["id"],
                "name": item["name"],
                "format": Path(item["name"]).suffix.lower().lstrip(".") or "без расширения",
                "content_type": item["content_type"],
                "size_bytes": item["size_bytes"],
                "sha256": item["sha256"],
                "category": item.get("category", "other"),
                "path": properties.get("path", []),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            },
            "classification": classification,
            "profile": profile,
            "anatomy": {
                **content_meta,
                "headings": headings,
                "preview_mode": preview.get("mode", "unknown"),
            },
            "molecules": {
                "total": len(facts),
                "counts": dict(sorted(fact_counts.items())),
                "facts": facts,
            },
            "entities": entities,
            "actions": actions,
            "temporal_model": temporal,
            "arithmetic": arithmetic,
            "contradictions": {
                "internal": internal_contradictions,
                "cross_document": [],
            },
            "risks": risks,
            "quality_gate": quality_gate,
            "document_quality": document_quality,
            "epistemics": {
                "facts": len(facts),
                "hypotheses": 0,
                "policy": "Факты требуют источника; гипотезы хранятся отдельно и не считаются знанием до проверки.",
            },
            "fingerprint": fingerprint,
            "graph_ready": graph,
            "relations": {
                "status": "доказуемые локальные связи",
                "items": graph["edges"],
                "note": (
                    "Показаны только связи «документ содержит факт/сущность/действие». "
                    "Причинные и смысловые связи между сущностями требуют семантического слоя."
                ),
            },
            "checks": checks,
            "integrity": integrity,
            "stages": stages,
            "summary": self._summary(
                classification, content_meta, facts, checks, integrity, profile, quality_gate
            ),
        }

    @staticmethod
    def _normalize_text(value: str) -> str:
        return value.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")

    def _text_and_structure(self, preview: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        mode = preview.get("mode")
        if mode == "table":
            rows = preview.get("rows") or []
            text = "\n".join("\t".join(str(value) for value in row) for row in rows)
            max_columns = max((len(row) for row in rows), default=0)
            return self._normalize_text(text), {
                "characters": len(text),
                "words": len(re.findall(r"\S+", text)),
                "lines": len(rows),
                "paragraphs": 0,
                "table_rows": len(rows),
                "table_columns": max_columns,
                "text_available": bool(text.strip()),
                "truncated": bool(preview.get("truncated")),
            }

        text = self._normalize_text(str(preview.get("text") or ""))
        lines = text.splitlines()
        paragraphs = [part for part in re.split(r"\n\s*\n", text) if part.strip()]
        return text, {
            "characters": len(text),
            "words": len(re.findall(r"\S+", text)),
            "lines": len(lines) if text else 0,
            "paragraphs": len(paragraphs),
            "table_rows": 0,
            "table_columns": 0,
            "text_available": bool(text.strip()),
            "truncated": bool(preview.get("truncated")),
        }

    def _classify(self, name: str, text: str, category: str) -> dict[str, Any]:
        haystack = f"{name}\n{text[:16000]}".casefold().replace("ё", "е")
        best_type = "Документ"
        best_score = 0
        reasons: list[str] = []

        for document_type, keywords in self.TYPE_RULES:
            matches = [keyword for keyword in keywords if keyword.casefold().replace("ё", "е") in haystack]
            score = len(matches)
            if score > best_score:
                best_type = document_type
                best_score = score
                reasons = matches[:4]

        if best_score == 0:
            fallback = {
                "tables": "Таблица",
                "presentations": "Презентация",
                "images": "Изображение",
                "pdf": "PDF-документ",
            }
            best_type = fallback.get(category, "Документ")
            confidence = 0.45
        else:
            confidence = min(0.98, 0.74 + 0.08 * best_score)

        return {
            "document_type": best_type,
            "confidence": round(confidence, 3),
            "reasons": reasons,
            "method": "rules",
        }

    @staticmethod
    def _line_role(fact_type: str, line: str) -> str:
        lowered = line.casefold().replace("ё", "е")
        if fact_type == "date":
            if re.search(r"\b(?:срок|до|не позднее)\b", lowered):
                return "deadline"
            if re.search(r"\b(?:период|с\s+\d|по\s+\d)\b", lowered):
                return "period_date"
            if re.search(r"\bдата\b", lowered):
                return "document_date"
            return "date_mention"
        if fact_type == "document_number":
            return "primary_document_number" if "№" in line or "номер" in lowered else "document_reference"
        if fact_type == "vin":
            return "primary_vin" if "vin" in lowered else "vin_mention"
        if fact_type == "vehicle_plate":
            return "primary_vehicle_plate" if any(x in lowered for x in ("гос", "автомоб", "транспорт")) else "vehicle_plate_mention"
        if fact_type == "amount":
            if "итого" in lowered or "всего" in lowered:
                return "total_amount"
            if "ндс" in lowered:
                return "vat_amount"
            return "amount"
        if fact_type == "time":
            if "выезд" in lowered:
                return "departure_time"
            if "возврат" in lowered or "возвращ" in lowered:
                return "return_time"
            return "time_mention"
        return fact_type

    def _extract_facts(self, text: str) -> list[dict[str, Any]]:
        if not text:
            return []

        facts: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int]] = set()

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue

            for fact_type, label, pattern, extraction_confidence in self.FACT_PATTERNS:
                for match in pattern.finditer(line):
                    value = match.group(1) if match.lastindex else match.group(0)
                    value = re.sub(r"\s+", " ", value).strip()
                    normalized = self._normalize_fact(fact_type, value)
                    canonical = str(normalized.get("canonical") or value).casefold()
                    key = (fact_type, canonical, line_number)
                    if key in seen:
                        continue
                    seen.add(key)

                    role = self._line_role(fact_type, line)
                    evidence_hash = sha256(
                        f"{line_number}|{line}".encode("utf-8")
                    ).hexdigest()
                    normalization_confidence = float(normalized.get("confidence", 0.8))
                    evidence_confidence = 1.0 if line else 0.0
                    overall = round(
                        min(extraction_confidence, normalization_confidence, evidence_confidence),
                        3,
                    )
                    stable_key = json.dumps(
                        [fact_type, canonical, role, line_number, evidence_hash],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    fact_id = "fact-" + sha1(stable_key.encode("utf-8")).hexdigest()[:16]
                    gate = "accepted" if overall >= 0.90 else "review" if overall >= 0.72 else "rejected"

                    facts.append(
                        {
                            "id": fact_id,
                            "type": fact_type,
                            "label": label,
                            "role": role,
                            "value": value,
                            "normalized": normalized,
                            "confidence": overall,
                            "confidence_breakdown": {
                                "extraction": round(extraction_confidence, 3),
                                "normalization": round(normalization_confidence, 3),
                                "evidence": round(evidence_confidence, 3),
                            },
                            "status": "fact",
                            "quality_gate": gate,
                            "source": {
                                "kind": "line",
                                "line": line_number,
                                "excerpt": line[:260],
                                "evidence_hash": evidence_hash,
                            },
                        }
                    )
                    if len(facts) >= MAX_FACTS:
                        return facts
        return facts

    @staticmethod
    def _decimal_text(value: str) -> Decimal | None:
        cleaned = (
            value.replace("\u00a0", " ")
            .replace(" ", "")
            .replace(",", ".")
        )
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        try:
            return Decimal(match.group(0))
        except InvalidOperation:
            return None

    def _normalize_fact(self, fact_type: str, value: str) -> dict[str, Any]:
        compact = re.sub(r"\s+", " ", value).strip()

        if fact_type == "date":
            raw = compact.replace("/", ".").replace("-", ".")
            parts = raw.split(".")
            try:
                if len(parts) == 3 and len(parts[0]) == 4:
                    date = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
                else:
                    date = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
                return {"kind": "date", "canonical": date.date().isoformat(), "confidence": 1.0}
            except (ValueError, IndexError):
                return {"kind": "date", "canonical": compact, "confidence": 0.6}

        if fact_type == "amount":
            number = self._decimal_text(compact)
            currency = "RUB" if re.search(r"(?i)₽|руб|RUB", compact) else None
            return {
                "kind": "money",
                "canonical": f"{number:.2f} {currency}" if number is not None and currency else compact,
                "amount": f"{number:.2f}" if number is not None else None,
                "currency": currency,
                "confidence": 1.0 if number is not None and currency else 0.7,
            }

        if fact_type in {"percent", "mileage", "quantity"}:
            number = self._decimal_text(compact)
            unit_match = re.search(r"(?i)(%|км|шт\.?|кг|г|л|литр(?:а|ов)?|т|м2|м²|м|компл\.?)", compact)
            unit = unit_match.group(1).casefold().rstrip(".") if unit_match else None
            unit_alias = {
                "литра": "л", "литров": "л", "литр": "л", "шт": "шт",
                "м²": "м2", "компл": "компл",
            }
            unit = unit_alias.get(unit or "", unit)
            return {
                "kind": "measurement",
                "canonical": f"{number} {unit}" if number is not None and unit else compact,
                "number": str(number) if number is not None else None,
                "unit": unit,
                "confidence": 0.98 if number is not None and unit else 0.7,
            }

        if fact_type in {"inn", "kpp", "ogrn", "bik", "settlement_account", "correspondent_account"}:
            digits = "".join(ch for ch in compact if ch.isdigit())
            return {"kind": "identifier", "canonical": digits, "confidence": 1.0 if digits else 0.5}

        if fact_type == "vin":
            canonical = re.sub(r"\s+", "", compact).upper()
            return {"kind": "identifier", "canonical": canonical, "confidence": 1.0 if len(canonical) == 17 else 0.6}

        if fact_type == "vehicle_plate":
            canonical = re.sub(r"\s+", "", compact).upper()
            return {"kind": "identifier", "canonical": canonical, "confidence": 0.99}

        if fact_type == "email":
            return {"kind": "contact", "canonical": compact.casefold(), "confidence": 1.0}

        if fact_type == "phone":
            digits = "".join(ch for ch in compact if ch.isdigit())
            if len(digits) == 11 and digits.startswith("8"):
                digits = "7" + digits[1:]
            canonical = f"+{digits}" if digits else compact
            return {"kind": "contact", "canonical": canonical, "confidence": 0.98 if len(digits) == 11 else 0.7}

        if fact_type == "time":
            canonical = compact.replace(".", ":")
            if re.match(r"^\d:\d{2}$", canonical):
                canonical = "0" + canonical
            return {"kind": "time", "canonical": canonical, "confidence": 0.98}

        if fact_type == "organization":
            canonical = self._canonical_organization(compact)
            return {"kind": "entity_name", "canonical": canonical, "confidence": 0.88 if canonical else 0.6}

        if fact_type == "person":
            canonical = " ".join(part.capitalize() for part in compact.split())
            return {"kind": "person_name", "canonical": canonical, "confidence": 0.86}

        if fact_type == "document_number":
            canonical = re.sub(r"\s+", "", compact).upper()
            return {"kind": "identifier", "canonical": canonical, "confidence": 0.94}

        return {"kind": "text", "canonical": compact, "confidence": 0.8}

    @staticmethod
    def _canonical_organization(value: str) -> str:
        clean = value.upper().replace("Ё", "Е")
        clean = clean.replace("«", " ").replace("»", " ").replace('"', " ")
        clean = re.sub(r"[^A-ZА-Я0-9]+", " ", clean)
        return re.sub(r"\s+", " ", clean).strip()

    def _extract_actions(self, text: str) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.casefold().replace("ё", "е")
            for action_type, keywords in self.ACTION_RULES:
                matched = next((keyword for keyword in keywords if keyword in lowered), None)
                if not matched:
                    continue
                action_key = f"{action_type}|{line_number}|{line}"
                actions.append(
                    {
                        "id": "action-" + sha1(action_key.encode("utf-8")).hexdigest()[:16],
                        "type": action_type,
                        "text": line[:320],
                        "confidence": 0.86,
                        "source": {
                            "kind": "line",
                            "line": line_number,
                            "excerpt": line[:320],
                            "evidence_hash": sha256(f"{line_number}|{line}".encode("utf-8")).hexdigest(),
                        },
                    }
                )
                break
        return actions[:80]

    @staticmethod
    def _action_as_fact(action: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": "fact-" + action["id"].split("-", 1)[1],
            "type": "action",
            "label": "Действие",
            "role": action["type"],
            "value": action["text"],
            "normalized": {
                "kind": "action",
                "canonical": action["text"].casefold(),
                "action_type": action["type"],
                "confidence": 0.86,
            },
            "confidence": action["confidence"],
            "confidence_breakdown": {
                "extraction": action["confidence"],
                "normalization": 0.86,
                "evidence": 1.0,
            },
            "status": "fact",
            "quality_gate": "review",
            "source": action["source"],
        }

    @staticmethod
    def _headings(text: str) -> list[dict[str, Any]]:
        headings: list[dict[str, Any]] = []
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or len(line) > 140:
                continue
            letters = [char for char in line if char.isalpha()]
            upper_ratio = (
                sum(1 for char in letters if char.isupper()) / len(letters)
                if letters else 0
            )
            looks_like_heading = (
                upper_ratio >= 0.72
                or line.endswith(":")
                or bool(re.match(r"^\d+(?:\.\d+)*[.)]?\s+\S+", line))
            )
            if looks_like_heading:
                headings.append({"line": line_number, "text": line})
            if len(headings) >= MAX_HEADINGS:
                break
        return headings

    def _profile(self, document_type: str, facts: list[dict[str, Any]]) -> dict[str, Any]:
        spec = DOCUMENT_PROFILES.get(document_type, DOCUMENT_PROFILES["Документ"])
        counts = Counter(fact["type"] for fact in facts if fact["quality_gate"] != "rejected")
        required = list(spec["required"])
        expected = list(spec["expected"])
        missing_required = [fact_type for fact_type in required if not counts.get(fact_type)]
        found_required = [fact_type for fact_type in required if counts.get(fact_type)]
        expected_found = [fact_type for fact_type in expected if counts.get(fact_type)]
        denominator = max(1, len(required) * 2 + len(expected))
        score = (len(found_required) * 2 + len(expected_found)) / denominator
        return {
            "name": document_type,
            "required": required,
            "expected": expected,
            "missing_required": missing_required,
            "found_required": found_required,
            "expected_found": expected_found,
            "completeness_percent": int(round(score * 100)),
            "singleton_roles": list(spec.get("singleton_roles", ())),
        }

    def _entity_candidates(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mapping = {
            "vin": ("Транспорт", "VIN"),
            "vehicle_plate": ("Транспорт", "Госномер"),
            "inn": ("Организация", "ИНН"),
            "kpp": ("Организация", "КПП"),
            "ogrn": ("Организация", "ОГРН"),
            "organization": ("Организация", "Название"),
            "person": ("Человек", "ФИО"),
            "email": ("Контакт", "E-mail"),
            "phone": ("Контакт", "Телефон"),
            "amount": ("Финансы", "Сумма"),
            "date": ("Время", "Дата"),
            "document_number": ("Документ", "Номер"),
        }
        grouped: dict[tuple[str, str], dict[str, Any]] = {}

        for fact in facts:
            if fact["quality_gate"] == "rejected":
                continue
            category, role = mapping.get(fact["type"], ("Факт", fact["label"]))
            canonical = str(fact["normalized"].get("canonical") or fact["value"])
            key = (category, canonical.casefold())
            if key not in grouped:
                entity_id = "entity-" + sha1(f"{category}|{canonical}".encode("utf-8")).hexdigest()[:16]
                grouped[key] = {
                    "id": entity_id,
                    "category": category,
                    "role": role,
                    "value": fact["value"],
                    "canonical": canonical,
                    "canonical_key": f"{category.casefold()}:{canonical.casefold()}",
                    "confidence": fact["confidence"],
                    "source": fact["source"],
                    "source_fact_ids": [fact["id"]],
                }
            else:
                grouped[key]["source_fact_ids"].append(fact["id"])
                grouped[key]["confidence"] = max(grouped[key]["confidence"], fact["confidence"])

        return list(grouped.values())[:160]

    @staticmethod
    def _temporal_model(facts: list[dict[str, Any]]) -> dict[str, Any]:
        items = []
        for fact in facts:
            if fact["type"] not in {"date", "time"}:
                continue
            role_map = {
                "document_date": "Дата документа",
                "deadline": "Крайний срок",
                "period_date": "Период",
                "departure_time": "Выезд",
                "return_time": "Возврат",
            }
            items.append(
                {
                    "fact_id": fact["id"],
                    "kind": fact["type"],
                    "role": fact["role"],
                    "label": role_map.get(fact["role"], "Упоминание времени"),
                    "value": fact["normalized"].get("canonical"),
                    "confidence": fact["confidence"],
                    "source": fact["source"],
                }
            )
        return {"items": items[:100], "count": len(items)}

    def _arithmetic_checks(self, preview: dict[str, Any]) -> list[dict[str, Any]]:
        rows = preview.get("rows") or []
        if preview.get("mode") != "table" or len(rows) < 2:
            return []

        header = [str(value).casefold().replace("ё", "е") for value in rows[0]]
        quantity_index = self._find_header(header, ("кол", "количество", "qty"))
        price_index = self._find_header(header, ("цена", "price"))
        total_index = self._find_header(header, ("сумма", "стоимость", "итого", "total"))
        if None in {quantity_index, price_index, total_index}:
            return []

        results: list[dict[str, Any]] = []
        for row_number, row in enumerate(rows[1:], start=2):
            if max(quantity_index, price_index, total_index) >= len(row):
                continue
            quantity = self._decimal_text(str(row[quantity_index]))
            price = self._decimal_text(str(row[price_index]))
            total = self._decimal_text(str(row[total_index]))
            if quantity is None or price is None or total is None:
                continue
            expected = quantity * price
            tolerance = max(Decimal("0.02"), abs(total) * Decimal("0.001"))
            matches = abs(expected - total) <= tolerance
            results.append(
                {
                    "row": row_number,
                    "quantity": str(quantity),
                    "price": str(price),
                    "total": str(total),
                    "expected": str(expected),
                    "matches": matches,
                    "level": "ok" if matches else "critical",
                    "message": (
                        "Количество × цена совпадает с суммой."
                        if matches
                        else "Количество × цена не совпадает с суммой."
                    ),
                }
            )
        return results[:200]

    @staticmethod
    def _find_header(header: list[str], needles: tuple[str, ...]) -> int | None:
        for index, value in enumerate(header):
            if any(needle in value for needle in needles):
                return index
        return None

    @staticmethod
    def _internal_contradictions(
        facts: list[dict[str, Any]],
        profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        contradictions: list[dict[str, Any]] = []
        by_role: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        singleton_roles = set(profile.get("singleton_roles") or [])

        for fact in facts:
            role = fact.get("role")
            if role not in singleton_roles or fact["quality_gate"] == "rejected":
                continue
            canonical = str(fact["normalized"].get("canonical") or fact["value"])
            by_role[role][canonical].append(fact)

        for role, values in by_role.items():
            if len(values) <= 1:
                continue
            samples = []
            for canonical, grouped in values.items():
                samples.append(
                    {
                        "value": canonical,
                        "fact_ids": [fact["id"] for fact in grouped],
                        "sources": [fact["source"] for fact in grouped[:3]],
                    }
                )
            contradictions.append(
                {
                    "code": f"singleton:{role}",
                    "level": "attention",
                    "role": role,
                    "message": "Для одного ключевого поля найдены разные значения.",
                    "values": samples,
                }
            )
        return contradictions

    @staticmethod
    def _risk_rules(
        item: dict[str, Any],
        preview: dict[str, Any],
        integrity: dict[str, Any],
        profile: dict[str, Any],
        arithmetic: list[dict[str, Any]],
        contradictions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []

        def add(code: str, severity: str, title: str, reason: str) -> None:
            risks.append({"code": code, "severity": severity, "title": title, "reason": reason})

        if not integrity.get("matches"):
            add("integrity", "critical", "Нарушена целостность", "Физический SHA-256 не совпадает с метаданными.")
        if profile.get("missing_required"):
            add(
                "profile-missing",
                "attention",
                "Неполный профиль документа",
                "Не найдены обязательные типы фактов: " + ", ".join(profile["missing_required"]),
            )
        if any(not item.get("matches") for item in arithmetic):
            add("arithmetic", "critical", "Арифметическое расхождение", "В таблице найдено несоответствие количество × цена = сумма.")
        if contradictions:
            add("internal-contradiction", "attention", "Внутренние противоречия", "Ключевые поля содержат несколько разных значений.")
        if preview.get("mode") in {"pdf", "image"}:
            add("ocr-needed", "attention", "Нужен OCR", "Для полного анализа изображения/скана требуется текстовый слой.")
        suffix = Path(str(item.get("name") or "")).suffix.casefold()
        if suffix in {".docm", ".xlsm", ".pptm"}:
            add("macro-format", "attention", "Формат с макросами", "Документ относится к Office-форматам, способным содержать макросы.")
        return risks

    @staticmethod
    def _quality_gate(
        facts: list[dict[str, Any]],
        integrity: dict[str, Any],
        risks: list[dict[str, Any]],
        contradictions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        counts = Counter(fact["quality_gate"] for fact in facts)
        critical_risks = [risk for risk in risks if risk["severity"] == "critical"]
        memory_ready = (
            bool(integrity.get("matches"))
            and not critical_risks
            and not contradictions
            and counts.get("accepted", 0) > 0
        )
        reasons = []
        if not integrity.get("matches"):
            reasons.append("integrity_failed")
        if critical_risks:
            reasons.append("critical_risk")
        if contradictions:
            reasons.append("contradiction_requires_review")
        if counts.get("accepted", 0) == 0:
            reasons.append("no_accepted_facts")
        return {
            "accepted": counts.get("accepted", 0),
            "review": counts.get("review", 0),
            "rejected": counts.get("rejected", 0),
            "memory_ready": memory_ready,
            "reasons": reasons,
            "policy": "source + normalization + confidence + contradiction gate",
        }

    @staticmethod
    def _document_quality(
        preview: dict[str, Any],
        structure: dict[str, Any],
        profile: dict[str, Any],
        quality_gate: dict[str, Any],
        integrity: dict[str, Any],
    ) -> dict[str, Any]:
        accepted = int(quality_gate.get("accepted") or 0)
        review = int(quality_gate.get("review") or 0)
        rejected = int(quality_gate.get("rejected") or 0)
        total = accepted + review + rejected
        evidence_ratio = accepted / total if total else 0.0
        text_available = bool(structure.get("text_available"))
        profile_score = int(profile.get("completeness_percent") or 0)
        integrity_score = 100 if integrity.get("matches") else 0
        text_score = 100 if text_available else 25 if preview.get("mode") in {"pdf", "image"} else 50
        evidence_score = int(round(evidence_ratio * 100)) if total else 0
        score = int(round(
            integrity_score * 0.30
            + text_score * 0.25
            + profile_score * 0.25
            + evidence_score * 0.20
        ))
        return {
            "score": score,
            "integrity_score": integrity_score,
            "text_layer_score": text_score,
            "profile_score": profile_score,
            "evidence_score": evidence_score,
            "needs_ocr": preview.get("mode") in {"pdf", "image"} and not text_available,
            "truncated": bool(structure.get("truncated")),
        }

    def _checks(
        self,
        item: dict[str, Any],
        preview: dict[str, Any],
        integrity: dict[str, Any],
        facts: list[dict[str, Any]],
        profile: dict[str, Any],
        arithmetic: list[dict[str, Any]],
        contradictions: list[dict[str, Any]],
        risks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = [
            {
                "code": "integrity",
                "level": "ok" if integrity.get("matches") else "critical",
                "title": "Целостность файла",
                "message": (
                    "SHA-256 совпадает с сохранённым значением."
                    if integrity.get("matches")
                    else "SHA-256 файла не совпадает с сохранённым значением."
                ),
            }
        ]

        if preview.get("mode") in {"pdf", "image", "video", "audio", "unsupported"}:
            checks.append({
                "code": "text-layer",
                "level": "attention",
                "title": "Текстовый слой",
                "message": "Для полного анализа содержимого нужен текстовый слой или OCR.",
            })
        elif not (preview.get("text") or preview.get("rows")):
            checks.append({
                "code": "empty-content",
                "level": "attention",
                "title": "Содержимое",
                "message": "Извлекаемый текст или таблицы не найдены.",
            })

        if preview.get("truncated"):
            checks.append({
                "code": "truncated",
                "level": "attention",
                "title": "Большой документ",
                "message": "Локальный предпросмотр ограничен; ДНК построена по доступной части.",
            })

        if profile.get("missing_required"):
            checks.append({
                "code": "profile-completeness",
                "level": "attention",
                "title": "Полнота профиля",
                "message": "Не найдены обязательные поля: " + ", ".join(profile["missing_required"]),
            })
        else:
            checks.append({
                "code": "profile-completeness",
                "level": "ok",
                "title": "Полнота профиля",
                "message": f"Обязательные поля профиля «{profile['name']}» найдены.",
            })

        mismatch_count = sum(1 for check in arithmetic if not check["matches"])
        if arithmetic:
            checks.append({
                "code": "arithmetic",
                "level": "critical" if mismatch_count else "ok",
                "title": "Арифметика таблиц",
                "message": (
                    f"Найдено арифметических расхождений: {mismatch_count}."
                    if mismatch_count
                    else f"Проверено строк: {len(arithmetic)}; расхождений нет."
                ),
            })

        if contradictions:
            checks.append({
                "code": "internal-contradictions",
                "level": "attention",
                "title": "Внутренние противоречия",
                "message": f"Требуют проверки: {len(contradictions)}.",
            })

        duplicate_count = int(item.get("duplicate_count") or 0)
        if duplicate_count:
            checks.append({
                "code": "duplicates",
                "level": "info",
                "title": "Совпадающее содержимое",
                "message": f"Найдено файлов с тем же SHA-256: {duplicate_count}.",
            })

        if facts:
            checks.append({
                "code": "facts",
                "level": "ok",
                "title": "Молекулы",
                "message": f"Извлечено структурированных фактов: {len(facts)}.",
            })

        critical = sum(1 for risk in risks if risk["severity"] == "critical")
        if risks:
            checks.append({
                "code": "risks",
                "level": "critical" if critical else "attention",
                "title": "Риски",
                "message": f"Правил риска сработало: {len(risks)}; критических: {critical}.",
            })
        return checks

    @staticmethod
    def _semantic_fingerprint(text: str, facts: list[dict[str, Any]]) -> dict[str, Any]:
        normalized = text.casefold().replace("ё", "е")
        tokens = re.findall(r"[a-zа-я0-9]{3,}", normalized)
        tokens = [token for token in tokens if token not in STOPWORDS]
        counts = Counter(tokens)
        for fact in facts:
            canonical = str(fact.get("normalized", {}).get("canonical") or "").casefold()
            if canonical:
                counts[f"fact:{fact['type']}:{canonical}"] += 3

        semantic_material = " ".join(
            f"{token}:{count}" for token, count in sorted(counts.items())
        )
        token_hashes = sorted(
            {
                sha1(token.encode("utf-8")).hexdigest()[:16]
                for token in counts
            }
        )[:MAX_TOKEN_HASHES]

        vector = [0] * 64
        for token, count in counts.items():
            hashed = int.from_bytes(sha256(token.encode("utf-8")).digest()[:8], "big")
            weight = max(1, min(int(count), 8))
            for bit in range(64):
                vector[bit] += weight if (hashed >> bit) & 1 else -weight
        simhash = 0
        for bit, score in enumerate(vector):
            if score >= 0:
                simhash |= 1 << bit

        return {
            "semantic_sha256": sha256(semantic_material.encode("utf-8")).hexdigest(),
            "simhash64": f"{simhash:016x}",
            "token_hashes": token_hashes,
            "token_count": len(tokens),
            "unique_tokens": len(counts),
        }

    @staticmethod
    def _graph_ready(
        item: dict[str, Any],
        facts: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        document_node = {
            "id": f"document:{item['id']}",
            "kind": "document",
            "label": item["name"],
            "canonical_key": f"document:{item['id']}",
        }
        nodes: list[dict[str, Any]] = [document_node]
        edges: list[dict[str, Any]] = []

        for entity in entities:
            nodes.append({
                "id": entity["id"],
                "kind": "entity",
                "category": entity["category"],
                "label": entity["value"],
                "canonical_key": entity["canonical_key"],
            })
            edges.append({
                "from": document_node["id"],
                "to": entity["id"],
                "type": "mentions",
                "evidence_fact_ids": entity["source_fact_ids"],
                "inferred": False,
            })

        for action in actions:
            action_node = f"action:{action['id']}"
            nodes.append({
                "id": action_node,
                "kind": "action",
                "label": action["text"],
                "canonical_key": action_node,
            })
            edges.append({
                "from": document_node["id"],
                "to": action_node,
                "type": "contains_action",
                "evidence": action["source"],
                "inferred": False,
            })

        return {
            "nodes": nodes[:MAX_GRAPH_NODES],
            "edges": edges[:MAX_GRAPH_NODES],
            "ready_for_merge": True,
        }

    @staticmethod
    def _stages(
        preview: dict[str, Any],
        facts: list[dict[str, Any]],
        classification: dict[str, Any],
        integrity: dict[str, Any],
        profile: dict[str, Any],
        quality_gate: dict[str, Any],
        fingerprint: dict[str, Any],
    ) -> list[dict[str, Any]]:
        text_ready = bool(preview.get("text") or preview.get("rows"))
        return [
            {"id": "identity", "label": "Идентичность", "status": "done", "weight": 10},
            {"id": "integrity", "label": "Целостность", "status": "done" if integrity.get("matches") else "warning", "weight": 10},
            {"id": "structure", "label": "Структура", "status": "done", "weight": 10},
            {"id": "content", "label": "Содержимое", "status": "done" if text_ready else "pending", "weight": 15},
            {"id": "normalization", "label": "Нормализация", "status": "done" if facts else "pending", "weight": 15},
            {"id": "profile", "label": "Профиль", "status": "done" if not profile.get("missing_required") else "partial", "weight": 10},
            {"id": "quality", "label": "Проверки", "status": "done" if quality_gate.get("memory_ready") else "partial", "weight": 10},
            {"id": "fingerprint", "label": "Отпечаток", "status": "done" if fingerprint.get("semantic_sha256") else "pending", "weight": 10},
            {"id": "semantic", "label": "Семантические связи", "status": "pending", "weight": 10},
        ]

    @staticmethod
    def _coverage(stages: list[dict[str, Any]]) -> int:
        total = sum(int(stage["weight"]) for stage in stages)
        achieved = 0.0
        for stage in stages:
            status = stage["status"]
            weight = int(stage["weight"])
            if status == "done":
                achieved += weight
            elif status == "partial":
                achieved += weight * 0.5
            elif status == "warning":
                achieved += weight * 0.25
        return int(round((achieved / total) * 100)) if total else 0

    @staticmethod
    def _summary(
        classification: dict[str, Any],
        structure: dict[str, Any],
        facts: list[dict[str, Any]],
        checks: list[dict[str, Any]],
        integrity: dict[str, Any],
        profile: dict[str, Any],
        quality_gate: dict[str, Any],
    ) -> str:
        document_type = classification.get("document_type", "Документ")
        words = int(structure.get("words") or 0)
        alerts = sum(1 for item in checks if item["level"] in {"attention", "critical"})
        integrity_text = "целостность подтверждена" if integrity.get("matches") else "есть проблема целостности"
        gate_text = "готово к проверяемой памяти" if quality_gate.get("memory_ready") else "нужна проверка"
        return (
            f"{document_type}: {integrity_text}; профиль {profile.get('completeness_percent', 0)}%; "
            f"слов {words}; молекул {len(facts)}; замечаний {alerts}; {gate_text}."
        )
