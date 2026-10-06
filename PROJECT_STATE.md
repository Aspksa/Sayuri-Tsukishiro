# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `bcf047437f1274a412612563459dcb6406b89e88` — проект `0.1.48`; финальный workflow Versions #473 завершён `success`.
- Целевая версия: `0.1.49`.
- Текущая задача: **AI-007 — Invisible Evidence Automation**.
- Основание: пользователь потребовал не перегружать интерфейс внутренними инструментами и сохранить возможность автоматизации.

## Версии целевого дерева

- Проект: `0.1.49`.
- Ядро Саюри: `0.1.41`.
- Agent Core: `0.11.0`.
- Web UI: `0.25.0`.
- Диск Sayuri: `0.7.1` — не изменяется.
- Dev tools: `0.1.6` — не изменяются.

## Архитектура

```text
сложная задача
→ Reasoning Planner
→ при включённой автопроверке: deterministic read-only evidence automation
→ внутренние execution receipts
→ основной ответ
→ Result Verifier получает receipts/evidence
→ пользователь видит только компактный итог автопроверки
```

### UI

- Меню не изменяется.
- Индивидуальные tool/receipt rows из reasoning summary удаляются.
- Список разрешённых инструментов из Личного кабинета удаляется.
- Существующий блок безопасных действий превращается в компактный блок «Автоматизация».
- Один переключатель: «Автопроверка сложных задач».
- История подтверждённых изменяющих действий сохраняется, но raw tool ID больше не показывается.

### Automation policy

- По умолчанию автопроверка включена.
- Настройка хранится локально в браузере.
- При выключении Planner/Verifier продолжают работать, но tool catalog не передаётся Planner и read-only tools не выполняются.
- Mutation intent всегда остаётся за SayuriActionBroker и явным confirm.

### Документные доказательства

- `disk.current_document.metadata`: только безопасные metadata, без локального пути и содержимого.
- `disk.current_document.ledger`: только состояние hash-chain существующего DNA-ledger, без `details_json`.
- `document_dna()` автоматически не вызывается, потому что может записывать обновлённые metadata/cache.

## Релизный критерий 0.1.49

1. Один атомарный commit от `main 0.1.48`.
2. App/core tests, включая reasoning/tool automation regressions — success.
3. Scripts/versioning tests — success.
4. JavaScript syntax — success.
5. Preflight — success.
6. `versioning.py check --each-commit` — success.
7. Windows launcher checks — success.
8. Merge через PR.
9. Финальный `main` workflow — success.

## Следующий рациональный этап

После стабилизации Invisible Evidence Automation — claim-to-evidence mapping для документов: связывать конкретные утверждения ответа с уже существующими page/line/bbox evidence, не включая автоматический анализ документа и не расширяя mutation permissions.
