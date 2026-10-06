# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `9387f351e951804e207f9e6451dc96ecb6fca535` — проект `0.1.51`, UI System & Chat Polish.
- Исходный финальный workflow: Versions #489 — success.
- Целевая версия: `0.1.52`.
- Текущая задача: **UI-006 — Rich Answer UX & Lazy Diagnostics**.

## Версии целевого дерева

- Проект: `0.1.52`.
- Ядро Саюри: `0.1.44`.
- Agent Core: `0.10.2`.
- Web UI: `0.28.0`.
- Диск Sayuri: `0.7.1` — не изменяется.
- Dev tools: `0.1.6` — не изменяются.

## Safe Rich Answer pipeline

```text
DeepSeek answer string
→ deterministic block parser
→ DOM createElement/textContent
→ headings/lists/quotes/code/tables/links
→ chat message
```

Инварианты:

- `innerHTML` не используется в rich renderer;
- HTML из ответа не исполняется;
- link node создаётся только для http/https Markdown links;
- fenced code всегда остаётся textContent;
- code copy — локальное clipboard-действие.

## User-facing evidence

Agent Core формирует `evidence` отдельно от execution receipts.

Допустимый UI:

- текущий документ, если Planner действительно выполнил read-only `context.current_document`;
- агрегированная проектная/личная память.

Недопустимо показывать в обычном UI:

- receipt ID;
- tool name;
- output SHA-256;
- raw args;
- internal memory IDs.

Клик по document evidence использует существующий `openViewer()`.

## Lazy diagnostics

Первое открытие вкладок:

- `Обзор` → base memory + candidates;
- `Архитектура` → Memory 3.0;
- `Quality Gate` → Memory 4.1;
- `Опыт` → Experience Learning.

Открытие Личного кабинета само по себе загружает только профиль и данные реально выбранной вкладки. Загруженные секции отмечаются локально в `sayuriState.loadedSections`.

Во время запроса panel получает `.sayuri-lazy-loading` + `aria-busy=true`.

## Релизный критерий 0.1.52

1. Один атомарный commit от `main 0.1.51`.
2. Agent/Core tests — success.
3. Web contracts — success.
4. JavaScript syntax — success.
5. Preflight и versioning each-commit — success.
6. Windows launcher checks — success.
7. PR merge.
8. Финальный `main` workflow — success.

## Следующий рациональный этап

После стабилизации 0.1.52 — улучшить работу непосредственно с содержимым документов: page/line/bbox citations из DNA/Spatial Evidence и контекстное открытие конкретного места документа, не превращая chat в техническую консоль.
