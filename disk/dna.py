from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any


DNA_ANALYZER_VERSION = "0.1.0"
MAX_FACTS = 240
MAX_HEADINGS = 16


class DocumentDNAAnalyzer:
    """Детерминированный локальный анализ документа без внешнего ИИ-провайдера."""

    FACT_PATTERNS: tuple[tuple[str, str, re.Pattern[str], float], ...] = (
        (
            "date",
            "Дата",
            re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:19|20)\d{2}\b"),
            0.98,
        ),
        (
            "date",
            "Дата",
            re.compile(r"\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b"),
            0.98,
        ),
        (
            "inn",
            "ИНН",
            re.compile(r"(?i)\bИНН\s*[:№]?\s*(\d{10}|\d{12})\b"),
            0.99,
        ),
        (
            "vin",
            "VIN",
            re.compile(r"(?i)\b[A-HJ-NPR-Z0-9]{17}\b"),
            0.96,
        ),
        (
            "vehicle_plate",
            "Госномер",
            re.compile(r"(?i)\b[АВЕКМНОРСТУХ]\s?\d{3}\s?[АВЕКМНОРСТУХ]{2}\s?\d{2,3}\b"),
            0.94,
        ),
        (
            "amount",
            "Сумма",
            re.compile(
                r"(?i)\b\d+(?:[\s\u00a0]\d{3})*(?:[,.]\d{1,2})?\s*(?:₽|руб\.?|рублей|рубля|RUB)\b"
            ),
            0.93,
        ),
        (
            "percent",
            "Процент",
            re.compile(r"\b\d+(?:[,.]\d+)?\s*%"),
            0.94,
        ),
        (
            "email",
            "E-mail",
            re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
            0.99,
        ),
        (
            "phone",
            "Телефон",
            re.compile(r"(?<!\d)(?:\+7|8)[\s\-(]*(?:\d[\s\-()]*){10}(?!\d)"),
            0.90,
        ),
        (
            "document_number",
            "Номер документа",
            re.compile(r"(?:№|\bN(?:o)?\.?)[\s]*([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9./_-]{0,40})"),
            0.89,
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
        fact_counts = Counter(fact["type"] for fact in facts)
        headings = self._headings(text)
        issues = self._checks(item, preview, integrity, facts)
        stages = self._stages(preview, facts, classification, integrity)
        coverage = self._coverage(stages)

        return {
            "schema_version": 1,
            "analyzer_version": DNA_ANALYZER_VERSION,
            "status": "изучено" if coverage >= 80 else "частично изучено",
            "coverage_percent": coverage,
            "method": {
                "name": "Локальный анализ ДНК",
                "external_ai_used": False,
                "semantic_ai_status": "не подключён",
                "note": (
                    "Структура, молекулы и проверки выполнены локально. "
                    "Семантический ИИ-слой будет добавлен поверх этой же ДНК."
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
            "entities": self._entity_candidates(facts),
            "relations": {
                "status": "ожидает семантического слоя",
                "items": [],
                "note": "Связи между сущностями не выдумываются без семантической проверки.",
            },
            "checks": issues,
            "integrity": integrity,
            "stages": stages,
            "summary": self._summary(classification, content_meta, facts, issues, integrity),
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
        haystack = f"{name}\n{text[:12000]}".casefold()
        best_type = "Документ"
        best_score = 0
        reasons: list[str] = []

        for document_type, keywords in self.TYPE_RULES:
            matches = [keyword for keyword in keywords if keyword.casefold() in haystack]
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
            confidence = min(0.97, 0.72 + 0.08 * best_score)

        return {
            "document_type": best_type,
            "confidence": round(confidence, 2),
            "reasons": reasons,
        }

    def _extract_facts(self, text: str) -> list[dict[str, Any]]:
        if not text:
            return []

        facts: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int]] = set()

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue

            for fact_type, label, pattern, confidence in self.FACT_PATTERNS:
                for match in pattern.finditer(line):
                    value = match.group(1) if match.lastindex else match.group(0)
                    value = re.sub(r"\s+", " ", value).strip()
                    key = (fact_type, value.casefold(), line_number)
                    if key in seen:
                        continue
                    seen.add(key)
                    facts.append(
                        {
                            "id": f"fact-{len(facts) + 1:04d}",
                            "type": fact_type,
                            "label": label,
                            "value": value,
                            "confidence": confidence,
                            "source": {
                                "kind": "line",
                                "line": line_number,
                                "excerpt": line[:220],
                            },
                        }
                    )
                    if len(facts) >= MAX_FACTS:
                        return facts
        return facts

    @staticmethod
    def _headings(text: str) -> list[dict[str, Any]]:
        headings: list[dict[str, Any]] = []
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or len(line) > 120:
                continue
            letters = [char for char in line if char.isalpha()]
            upper_ratio = (
                sum(1 for char in letters if char.isupper()) / len(letters)
                if letters
                else 0
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

    @staticmethod
    def _entity_candidates(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mapping = {
            "vin": ("Транспорт", "VIN"),
            "vehicle_plate": ("Транспорт", "Госномер"),
            "inn": ("Организация", "ИНН"),
            "email": ("Контакт", "E-mail"),
            "phone": ("Контакт", "Телефон"),
            "amount": ("Финансы", "Сумма"),
            "date": ("Время", "Дата"),
            "document_number": ("Документ", "Номер"),
        }
        candidates: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for fact in facts:
            category, role = mapping.get(fact["type"], ("Факт", fact["label"]))
            key = (category, fact["value"].casefold())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "category": category,
                    "role": role,
                    "value": fact["value"],
                    "confidence": fact["confidence"],
                    "source": fact["source"],
                }
            )
        return candidates[:120]

    @staticmethod
    def _checks(
        item: dict[str, Any],
        preview: dict[str, Any],
        integrity: dict[str, Any],
        facts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        checks.append(
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
        )

        if preview.get("mode") in {"pdf", "image", "video", "audio", "unsupported"}:
            checks.append(
                {
                    "code": "text-layer",
                    "level": "attention",
                    "title": "Текстовый слой",
                    "message": "Для полного анализа содержимого нужен текстовый слой или OCR.",
                }
            )
        elif not (preview.get("text") or preview.get("rows")):
            checks.append(
                {
                    "code": "empty-content",
                    "level": "attention",
                    "title": "Содержимое",
                    "message": "Извлекаемый текст или таблицы не найдены.",
                }
            )

        if preview.get("truncated"):
            checks.append(
                {
                    "code": "truncated",
                    "level": "attention",
                    "title": "Большой документ",
                    "message": "Локальный предпросмотр ограничен; ДНК построена по доступной части.",
                }
            )

        duplicate_count = int(item.get("duplicate_count") or 0)
        if duplicate_count:
            checks.append(
                {
                    "code": "duplicates",
                    "level": "info",
                    "title": "Совпадающее содержимое",
                    "message": f"Найдено файлов с тем же SHA-256: {duplicate_count}.",
                }
            )

        if facts:
            checks.append(
                {
                    "code": "facts",
                    "level": "ok",
                    "title": "Молекулы",
                    "message": f"Извлечено структурированных фактов: {len(facts)}.",
                }
            )

        return checks

    @staticmethod
    def _stages(
        preview: dict[str, Any],
        facts: list[dict[str, Any]],
        classification: dict[str, Any],
        integrity: dict[str, Any],
    ) -> list[dict[str, Any]]:
        text_ready = bool(preview.get("text") or preview.get("rows"))
        return [
            {"id": "identity", "label": "Идентичность", "status": "done", "weight": 15},
            {
                "id": "integrity",
                "label": "Целостность",
                "status": "done" if integrity.get("matches") else "warning",
                "weight": 15,
            },
            {"id": "structure", "label": "Структура", "status": "done", "weight": 15},
            {
                "id": "content",
                "label": "Содержимое",
                "status": "done" if text_ready else "pending",
                "weight": 20,
            },
            {
                "id": "molecules",
                "label": "Молекулы",
                "status": "done" if text_ready else "pending",
                "weight": 20,
            },
            {
                "id": "classification",
                "label": "Тип документа",
                "status": "done" if classification.get("confidence", 0) >= 0.6 else "partial",
                "weight": 10,
            },
            {
                "id": "semantic",
                "label": "Семантические связи",
                "status": "pending",
                "weight": 5,
            },
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
        issues: list[dict[str, Any]],
        integrity: dict[str, Any],
    ) -> str:
        document_type = classification.get("document_type", "Документ")
        words = int(structure.get("words") or 0)
        alerts = sum(1 for item in issues if item["level"] in {"attention", "critical"})
        integrity_text = "целостность подтверждена" if integrity.get("matches") else "есть проблема целостности"
        return (
            f"{document_type}: {integrity_text}; слов {words}; "
            f"молекул {len(facts)}; замечаний {alerts}."
        )
