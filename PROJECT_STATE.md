# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `bcf047437f1274a412612563459dcb6406b89e88` — проект `0.1.48`, Evidence-aware Tool Planner.
- Проверка базы: финальный workflow Versions #473 (`37392794275`) — success.
- Целевая версия: `0.1.49`.
- Текущая задача: **AI-007 — Background Evidence Automation**.
- Статус целевого дерева: реализация подготовлена; release считается завершённым только после PR CI, merge и зелёного финального workflow на `main`.

## Версии целевого дерева

- Проект: `0.1.49`.
- Ядро Саюри: `0.1.41`.
- Agent Core: `0.10.1`.
- Web UI: `0.25.0`.
- Диск Sayuri: `0.7.1` — не изменялся.
- Dev tools: `0.1.6` — не изменялись.

## Background Evidence Automation

```text
complex user task
→ Reasoning Planner
→ structured goal / steps / evidence_needed / optional intents
→ deterministic background evidence policy
→ safe read-only checks only
→ local execution receipts
→ primary answer
→ Result Verifier with bounded receipts
→ compact automation summary to Web UI
```

### Автоподбор

Локальная policy может дополнить Planner безопасной read-only проверкой по `goal/evidence_needed`:

- релевантная память / история / прежние решения -> `memory.search`;
- состояние системы / версия / provider -> `system.status`;
- integrity / SQLite -> `memory.integrity`;
- текущий документ -> `context.current_document`;
- опыт / прежние ошибки -> `experience.stats`.

Если Planner уже выбрал проверку той же категории, автоподбор не создаёт лишний дублирующий вызов.

### Security boundary

- DeepSeek не выполняет инструмент напрямую.
- Unknown tool отклоняется.
- Read-only вызовы ограничены allowlist, duplicate suppression и максимум 4 вызовами.
- Mutation intent не получает исполняемый payload и возвращает `requires_action_broker`.
- Единственный путь изменения состояния: существующий `SayuriActionBroker` после явного подтверждения пользователя.

### Evidence и privacy

- Полные sanitized execution receipts остаются локально в `data/sayuri-tool-receipts.db`.
- Result Verifier получает только bounded evidence.
- Oversized output сокращается до controlled excerpt перед Cloud.ru.
- `memory.search` использует Memory 4.1 `for_cloud=True`; attribution commit остаётся post-success.
- Секретные поля не попадают в receipt preview или Cloud evidence.

## UI policy

По прямому указанию пользователя технические инструменты не должны перегружать интерфейс.

- меню не меняется;
- постоянный каталог инструментов в Личном кабинете убирается;
- строки execution receipts в чате убираются;
- история подтверждаемых изменяющих действий сохраняется;
- в reasoning summary при фактической фоновой проверке показывается только короткое `автопроверка N`;
- системный индикатор называется «Автопроверка».

## Релизный критерий 0.1.49

1. Один атомарный commit от подтверждённого `main 0.1.48`.
2. App/core tests включая reasoning/tool-planner automation tests — success.
3. Scripts/versioning tests — success.
4. JavaScript syntax — success.
5. Preflight — success.
6. `versioning.py check --each-commit` — success.
7. Windows launcher checks — success.
8. Merge через PR.
9. Финальный `main` workflow — success.

## Следующий рациональный этап

После стабилизации фоновой automation расширять только **read-only document evidence** Диска/ДНК: preview/DNA facts/page-line-bbox/ledger evidence. Не добавлять отдельный инструментальный UI и не ослаблять Action Broker.
