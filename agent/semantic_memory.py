from __future__ import annotations

from collections import Counter
from math import sqrt
from typing import Any, Iterable
import re

from .memory import MEMORY_SCOPES, SayuriMemory


_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё_-]{2,}", re.UNICODE)

# Небольшой локальный словарь понятий. Он не заменяет embeddings, но позволяет
# находить устойчивые смысловые соответствия без второй облачной модели.
_CONCEPTS: dict[str, tuple[str, ...]] = {
    "ui_light": ("светлый", "светлая", "белый", "белая", "white", "light", "тема", "интерфейс"),
    "ui_dark": ("тёмный", "темный", "чёрный", "черный", "dark", "night"),
    "ui_compact": ("компактный", "минимальный", "лаконичный", "меньше", "узкий", "compact"),
    "memory": ("память", "запомнить", "воспоминание", "memory", "remember"),
    "document": ("документ", "файл", "pdf", "docx", "document"),
    "contract": ("договор", "контракт", "contract"),
    "invoice": ("счёт", "счет", "оферта", "invoice"),
    "service_note": ("служебная", "служебка", "записка", "memo"),
    "vehicle": ("машина", "автомобиль", "авто", "vehicle", "vin", "госномер"),
    "fuel": ("гсм", "топливо", "бензин", "дизель", "fuel"),
    "provider": ("cloud.ru", "cloud", "провайдер", "provider"),
    "model": ("deepseek", "модель", "model", "llm"),
    "version": ("версия", "version", "релиз", "release"),
    "delete": ("удалить", "удаление", "корзина", "delete", "trash"),
    "move": ("переместить", "перенести", "move"),
    "create": ("создать", "добавить", "create", "add"),
    "error": ("ошибка", "сбой", "не работает", "failure", "error"),
    "preference": ("предпочитаю", "нравится", "удобнее", "люблю", "preference"),
    "decision": ("решили", "решение", "фиксируем", "используем", "decision"),
    "task": ("задача", "надо", "нужно", "следующий этап", "task"),
}

_STOP_WORDS = {
    "это", "эта", "этот", "эти", "для", "как", "что", "чтобы", "или", "она", "они",
    "его", "её", "ему", "мне", "мой", "моя", "мы", "вы", "про", "при", "над", "под",
    "the", "and", "for", "with", "this", "that", "from", "into",
}


class SemanticMemoryIndex:
    """Гибридный локальный поиск: токены + морфология + концепты + char n-grams."""

    engine_id = "hybrid-semantic-v1"
    neural_embeddings = False

    def __init__(self, memory: SayuriMemory):
        self.memory = memory

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join((text or "").casefold().replace("ё", "е").split())

    @classmethod
    def _tokens(cls, text: str) -> set[str]:
        tokens = {
            match.group(0)
            for match in _WORD_RE.finditer(cls._normalize(text))
            if match.group(0) not in _STOP_WORDS
        }
        return tokens

    @staticmethod
    def _stem(token: str) -> str:
        if len(token) <= 4:
            return token
        endings = (
            "иями", "ями", "ами", "ого", "ему", "ому", "ими", "ыми", "иях", "ах", "ях",
            "ение", "ения", "ений", "ировать", "ировать", "овать", "евать",
            "ая", "яя", "ое", "ее", "ый", "ий", "ой", "ые", "ие", "ого", "его",
            "ами", "ями", "ом", "ем", "ам", "ям", "ах", "ях", "ов", "ев",
            "а", "я", "ы", "и", "е", "у", "ю", "о",
            "ing", "ed", "es", "s",
        )
        for ending in endings:
            if token.endswith(ending) and len(token) - len(ending) >= 4:
                return token[:-len(ending)]
        return token

    @classmethod
    def _stems(cls, text: str) -> set[str]:
        return {cls._stem(token) for token in cls._tokens(text)}

    @classmethod
    def _concepts(cls, text: str) -> set[str]:
        normalized = cls._normalize(text)
        tokens = cls._tokens(text)
        found: set[str] = set()
        for concept, aliases in _CONCEPTS.items():
            for alias in aliases:
                alias_norm = cls._normalize(alias)
                if " " in alias_norm:
                    if alias_norm in normalized:
                        found.add(concept)
                        break
                elif alias_norm in tokens or cls._stem(alias_norm) in {cls._stem(t) for t in tokens}:
                    found.add(concept)
                    break
        return found

    @classmethod
    def _char_ngrams(cls, text: str, n: int = 3) -> Counter[str]:
        normalized = re.sub(r"\s+", " ", cls._normalize(text))
        compact = f" {normalized} "
        if len(compact) < n:
            return Counter({compact: 1}) if compact.strip() else Counter()
        return Counter(compact[i:i + n] for i in range(len(compact) - n + 1))

    @staticmethod
    def _cosine(left: Counter[str], right: Counter[str]) -> float:
        if not left or not right:
            return 0.0
        common = left.keys() & right.keys()
        numerator = sum(left[key] * right[key] for key in common)
        left_norm = sqrt(sum(value * value for value in left.values()))
        right_norm = sqrt(sum(value * value for value in right.values()))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)

    @staticmethod
    def _jaccard(left: set[str], right: set[str]) -> float:
        union = left | right
        return len(left & right) / len(union) if union else 0.0

    @classmethod
    def score(cls, query: str, content: str, *, importance: int = 3, confidence: float | None = None) -> dict[str, Any]:
        query_tokens = cls._tokens(query)
        content_tokens = cls._tokens(content)
        query_stems = cls._stems(query)
        content_stems = cls._stems(content)
        query_concepts = cls._concepts(query)
        content_concepts = cls._concepts(content)

        token_overlap = cls._jaccard(query_tokens, content_tokens)
        stem_overlap = cls._jaccard(query_stems, content_stems)
        concept_overlap = cls._jaccard(query_concepts, content_concepts)
        char_similarity = cls._cosine(cls._char_ngrams(query), cls._char_ngrams(content))

        normalized_query = cls._normalize(query)
        normalized_content = cls._normalize(content)
        phrase_bonus = 1.0 if normalized_query and normalized_query in normalized_content else 0.0

        base = (
            token_overlap * 0.24
            + stem_overlap * 0.20
            + concept_overlap * 0.36
            + char_similarity * 0.14
            + phrase_bonus * 0.06
        )
        quality = min(max(float(importance), 1.0), 5.0) / 5.0
        confidence_factor = 0.5 if confidence is None else max(0.0, min(float(confidence), 1.0))
        final = min(1.0, base * 0.93 + quality * 0.045 + confidence_factor * 0.025)

        reasons: list[str] = []
        if concept_overlap > 0:
            reasons.append("совпали смысловые понятия")
        if stem_overlap > 0:
            reasons.append("совпали формы слов")
        if token_overlap > 0:
            reasons.append("совпали ключевые слова")
        if char_similarity >= 0.45:
            reasons.append("похожая формулировка")
        if phrase_bonus:
            reasons.append("точная фраза")

        return {
            "score": round(final, 6),
            "features": {
                "token_overlap": round(token_overlap, 4),
                "stem_overlap": round(stem_overlap, 4),
                "concept_overlap": round(concept_overlap, 4),
                "char_similarity": round(char_similarity, 4),
                "phrase_bonus": phrase_bonus,
            },
            "reasons": reasons,
            "query_concepts": sorted(query_concepts),
            "memory_concepts": sorted(content_concepts),
        }

    def search(
        self,
        query: str,
        *,
        scopes: Iterable[str] = MEMORY_SCOPES,
        limit: int = 10,
        minimum_score: float = 0.12,
        mark_used: bool = True,
    ) -> dict[str, list[dict[str, Any]]]:
        normalized_query = self._normalize(query)
        valid_scopes = tuple(dict.fromkeys(scope for scope in scopes if scope in MEMORY_SCOPES))
        if not normalized_query or not valid_scopes:
            return {scope: [] for scope in valid_scopes}

        scored: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        per_scope_limit = min(max(int(limit) * 12, 80), 300)
        for scope in valid_scopes:
            for entry in self.memory.list(scope=scope, limit=per_scope_limit):
                details = self.score(
                    query,
                    entry["content"],
                    importance=entry.get("importance", 3),
                    confidence=entry.get("confidence"),
                )
                if details["score"] < minimum_score:
                    continue
                scored.append((details["score"], entry, details))

        scored.sort(
            key=lambda item: (
                item[0],
                item[1].get("importance", 0),
                item[1].get("updated_at", ""),
            ),
            reverse=True,
        )
        selected = scored[: min(max(int(limit), 1), 30)]

        if mark_used:
            self.memory.mark_used(entry["id"] for _, entry, _ in selected)

        result = {scope: [] for scope in valid_scopes}
        for score, entry, details in selected:
            item = dict(entry)
            item["relevance"] = round(score, 4)
            item["retrieval"] = self.engine_id
            item["semantic_match"] = details
            result[entry["scope"]].append(item)
        return result


    def context(self, query: str, *, limit: int = 10) -> dict[str, Any]:
        found = self.search(query, limit=limit)
        return {
            "retrieval": self.engine_id,
            "personal": [
                {
                    "kind": item["kind"],
                    "content": item["content"],
                    "importance": item["importance"],
                    "relevance": item["relevance"],
                    "source_context": item.get("source_context"),
                }
                for item in found.get("personal", [])
            ],
            "project": [
                {
                    "kind": item["kind"],
                    "content": item["content"],
                    "importance": item["importance"],
                    "relevance": item["relevance"],
                    "source_context": item.get("source_context"),
                }
                for item in found.get("project", [])
            ],
        }

    def public_status(self) -> dict[str, Any]:
        return {
            "status": "готово",
            "engine": self.engine_id,
            "mode": "local_hybrid",
            "neural_embeddings": self.neural_embeddings,
            "features": [
                "token overlap",
                "light stemming",
                "concept expansion",
                "character n-grams",
                "importance/confidence weighting",
            ],
            "external_model_required": False,
        }
