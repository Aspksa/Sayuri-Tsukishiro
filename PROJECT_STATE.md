# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `0fdb2512fc8d6595774c322a41c2c5c6ee7867a8` — проект `0.1.47`, Reasoning Planner + Result Verifier.
- Целевая версия: `0.1.48`.
- Текущая задача: **AI-006 — Evidence-aware Tool Planner**.
- Целевое дерево содержит реализацию; релиз подтверждается только PR CI и финальным workflow на `main`.

## Версии целевого дерева

- Проект: `0.1.48`.
- Ядро Саюри: `0.1.40`.
- Agent Core: `0.10.0`.
- Web UI: `0.24.0`.
- Диск Sayuri: `0.7.1` — не изменялся.
- Dev tools: `0.1.6` — не изменялись.

## Evidence-aware Tool Planner

```text
user task
→ complexity gate
→ Planner
→ structured steps + tool_intents
→ deterministic allowlist
→ read-only tools execute / mutations blocked
→ execution receipts + evidence
→ answer
→ Result Verifier
→ post-success memory attribution
```

### Security boundary

- DeepSeek не исполняет инструменты напрямую.
- Unknown tool отклоняется.
- Read-only инструменты ограничены allowlist и максимум четырьмя вызовами.
- Duplicate tool+args не выполняется повторно.
- Mutation intent не получает исполняемый payload от модели и возвращает `requires_action_broker`.
- Existing SayuriActionBroker остаётся единственным путём изменения данных после явного подтверждения пользователя.

### Evidence

Receipts хранятся локально в `data/sayuri-tool-receipts.db` и содержат tool, step, args, status, timestamps, duration, evidence refs, output SHA-256 и sanitized preview.

Result Verifier получает фактические receipts. `completed` доказывает выполнение локального tool call, но не делает любую интерпретацию модели истинной.

### Privacy

- tool output проходит secret sanitization;
- Cloud evidence budget: 9000 chars;
- `memory.search` использует Memory 4.1 `for_cloud=True`;
- tool-memory IDs добавляются в prepared recall;
- recall usage фиксируется только после успешного reasoning pipeline.

### UI

В reasoning summary добавлены строки инструментов и их статусы. Меню проекта не изменялось.

## Релизный критерий 0.1.48

1. Один атомарный commit от `main 0.1.47`.
2. App/core tests включая `test_reasoning.py` и `test_tool_planner.py` — success.
3. Scripts/versioning tests — success.
4. JavaScript syntax — success.
5. Preflight — success.
6. `versioning.py check --each-commit` — success.
7. Windows launcher checks — success.
8. Merge через PR.
9. Финальный `main` workflow — success.

## Следующий рациональный этап

После стабилизации v0.1.48 расширять evidence tools на документные read-only операции Диска/ДНК: безопасное чтение preview/DNA evidence, ссылки page/line/bbox и claim-to-evidence mapping, не меняя mutation boundary.
