# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `87b4cc452665ca98df417effc882c06add2435f9` — проект `0.1.50`, Sayuri Presence UX Cleanup.
- Исходный финальный workflow: Versions #485 — success.
- Целевая версия: `0.1.51`.
- Текущая задача: **UI-005 — UI System & Chat Polish**.

## Версии целевого дерева

- Проект: `0.1.51`.
- Ядро Саюри: `0.1.43`.
- Agent Core: `0.10.1` — не изменяется.
- Web UI: `0.27.0`.
- Диск Sayuri: `0.7.1` — не изменяется.
- Dev tools: `0.1.6` — не изменяются.

## Основные UX-инварианты

### Навигация

- Структура левого меню не меняется.
- Личный кабинет по-прежнему открывается через аватар Sayuri.
- Ctrl/⌘+K открывает transient command palette поверх текущего экрана.
- Palette не создаёт новый модуль и не меняет route самостоятельно вне выбранной команды.

### Chat

- Сохраняются drag/resize v0.1.50.
- Добавляется fullscreen/maximize существующего окна.
- Esc сначала закрывает command palette, затем возвращает maximized chat в floating mode, затем может закрыть обычный chat.
- В обычной status line нет токенов, внутренних счётчиков Memory или model-call telemetry.
- Copy action сообщения появляется ненавязчиво и использует clipboard API с toast-feedback.

### Design system

UI 0.27 задаёт единые:

- spacing tokens;
- radius tokens;
- shadow tokens;
- surface/text/line tokens;
- focus-visible states;
- control heights;
- responsive constraints;
- reduced-motion behavior.

Новых CSS/JS зависимостей не добавляется.

## Релизный критерий 0.1.51

1. Один атомарный commit от `main 0.1.50`.
2. App/Web contract tests — success.
3. JavaScript syntax — success.
4. Preflight — success.
5. Version tooling и each-commit check — success.
6. Windows launcher checks — success.
7. PR merge.
8. Финальный `main` workflow — success.

## Следующий рациональный этап

После стабилизации UI 0.27 — улучшать контентные поверхности: безопасное форматирование ответов, document citations/evidence и lazy-loading тяжёлых диагностических вкладок, не возвращая технический шум в основной UI.
