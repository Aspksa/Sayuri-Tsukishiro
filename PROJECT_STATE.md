# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Рабочая ветка: `memory-quality-v0146`.
- Проверенная исходная ревизия: `69faaef2744d84a338e9c041326a1ed7eeaed8cb` — проект `0.1.45`, финальный main CI успешен.
- Целевая версия: `0.1.46`.
- Текущая задача: **MEM-007 — Memory 4.1 Quality Gate**.
- Статус: функциональная реализация готова; атомарный release CI/merge ещё не выполнены.

## Версии целевого дерева

- Проект: `0.1.46`.
- Ядро Саюри: `0.1.38`.
- Agent Core: `0.8.2`.
- Диск Sayuri: `0.7.1` — не изменялся.
- Web UI: `0.22.0`.
- Dev tools: `0.1.6` — не изменялись.

## Основа памяти

Memory 4.1 не заменяет предыдущие контуры. Она усиливает:

1. personal/project long-term memory;
2. Memory Intelligence 2.0;
3. локальный `hybrid-semantic-v1`;
4. Experience Learning;
5. Memory 3.0: Working/Episodic/Knowledge/Graph/Temporal/Retention;
6. Memory 4.0/4.0 Hardening: Goal/Task/Decision/Failure/Question, Source Trust, Freshness, Utility, privacy firewall, Explainable Recall, Audit, Snapshots.

Единственная внешняя LLM остаётся `deepseek-ai/DeepSeek-V4-Flash` через Cloud.ru. Новая embedding-модель, vector DB или второй AI-провайдер не добавлены.

## Memory 4.1 Quality Gate

### Utility не равна истинности

Обратная связь на ответ:

- `Полезно`;
- `Не помогло`;

обновляет только helpful/unhelpful counters и retrieval utility memories, реально использованных в ответе.

Generic feedback больше не изменяет factual Source Trust. Плохой ответ модели не является доказательством, что исходный документ/OCR/manual fact ложный.

D-048 явно заменяет соответствующую часть D-041.

## Instruction-risk quarantine

В `memory_v4_state` миграцией добавлены:

- `instruction_risk`;
- `instruction_risk_score`.

Локальный deterministic classifier выделяет:

- high-risk directives: игнорировать инструкции/правила, раскрыть system prompt/developer message и аналогичные команды;
- medium-risk упоминания prompt injection/system prompt.

High-risk memory:

- остаётся видимой локально;
- получает `cloud_allowed=false`;
- показывается с badge `INSTRUCTION RISK`;
- не проходит в direct Cloud recall;
- не проходит через Memory 3.0 / Experience-derived context благодаря общему `_cloud_text_allowed()`.

Memory text остаётся данными, а не инструкцией.

## Diversified Recall

После обычного relevance ranking применяется greedy diversity selection.

Selection учитывает:

- основной final relevance;
- semantic similarity к уже выбранным memories;
- небольшой same-source penalty.

Цель: почти одинаковые воспоминания не должны вытеснять независимые полезные источники.

Explainable Recall дополнительно сохраняет:

- selection score;
- redundancy penalty;
- причину diversity adjustment.

## Verification Queue

Maintenance автоматически ставит важную память на перепроверку, но не удаляет и не объявляет ложной.

Question Memory создаётся, если:

- importance >= 4;
- факт относится к volatile;
- freshness < 0.45;

или если важная запись имеет Source Trust < 0.45.

Повторный maintenance не создаёт дубликаты вопросов.

После `refresh_memory_states()` review queue использует уже рассчитанный `memory_v4_state` через SQLite JOIN и не выполняет второй полный пересчёт до 5000 records.

## Bounded Cloud Context

Quality Gate ограничивает размер memory-derived AI-context до сериализации для Cloud.ru:

- direct personal/project recall: `9000` chars;
- Goal/Task/Failure/Question context: `7000` chars.

Отдельная memory excerpt ограничена; при необходимости outbound content сокращается. Оригинал в SQLite не меняется.

Критический attribution invariant:

```text
semantic candidates
→ quality ranking
→ diversity selection
→ privacy/instruction firewall
→ context budget
→ final selected memory IDs
→ Cloud.ru response
→ commit recall
→ usage / feedback
```

`_prepared_recall` формируется после budget selection. Поэтому use-count, recall-count и feedback получают только memories, фактически вошедшие в окончательный model context.

Сохраняется правило v0.1.45: provider/network/timeout error до успешного AI-response не commit-ит recall.

## Личный кабинет

Memory card теперь обозначена как:

`MEMORY 4.1 · QUALITY GATE`

Дополнительно показываются:

- `Quarantine`;
- `К перепроверке`;
- `INSTRUCTION RISK / PROMPT RISK` badges в локальном списке памяти;
- friendly labels для freshness/source-trust review questions.

Security note уточняет, что generic response feedback влияет на utility, а не на истинность источника.

## Проверки рабочего дерева

На промежуточных revisions подтверждены:

- Python core/tests — success;
- Memory 3.0 — success;
- Memory 4.0 regression suite — success;
- новые Quality Gate tests — success;
- Semantic/Experience — success;
- Server/API tests — success;
- Web contract — success;
- JavaScript syntax — success;
- preflight — success;
- Windows launcher — success.

Последняя полностью просмотренная функциональная веточная проверка: workflow run #441, где все функциональные шаги прошли успешно; падал только `versioning.py check --each-commit`, ожидаемо из-за промежуточной GitHub API-истории рабочей ветки.

После неё добавлены только дополнительный context-budget test, adjacent-layer instruction-risk test, performance refactor и документация; их окончательная проверка входит в release pipeline.

## Релизный критерий 0.1.46

Рабочая ветка не используется напрямую как release history.

Перед завершением необходимо:

1. сверить текущий `main` с ожидаемым `69faaef2744d84a338e9c041326a1ed7eeaed8cb`;
2. взять финальное tree рабочей ветки;
3. создать один атомарный commit `feat: v0.1.46 — Memory 4.1 Quality Gate` с parent текущего `main`;
4. создать новую validation-ветку без force-update;
5. получить зелёные:
   - scripts tests;
   - app/core tests;
   - JS syntax;
   - preflight;
   - `versioning.py check --each-commit`;
   - Windows launcher;
6. merge через PR;
7. подтвердить финальный `main` и его зелёный CI.

## Следующий рациональный этап

После проверки `0.1.46` память не следует бесконечно расширять новыми таблицами без измеримой пользы.

Следующий системный слой — **Reasoning Planner + Result Verifier**, которые должны использовать:

- Goal/Task Memory;
- Decision Memory;
- Failure/Causal Memory;
- verified/quality-gated recall;
- исходные ограничения задачи.

Memory 4.1 должна стать стабильным входным контуром для этого reasoning layer.
