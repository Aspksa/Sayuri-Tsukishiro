# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `d232df512560155b31c8b6cf642229196efc38af` — проект `0.1.53`, Spatial Evidence Citations.
- Исходный финальный workflow: Versions #499 — success.
- Целевая версия: `0.1.54`.
- Текущая задача: **UI-007 — Visual Refinement & Workspace UX**.

## Версии целевого дерева

- Проект: `0.1.54`.
- Ядро/App contract: `0.1.46`.
- Agent Core: `0.11.0` — не изменяется.
- Web UI: `0.30.0`.
- Диск Sayuri: `0.8.0` — не изменяется.
- SpatialDNAEngine: `0.8.0` — не изменяется.
- DB schema и DNA schema: без изменений.

## Что меняется

### Workspace chat

- Maximized chat остаётся тем же DOM/chat instance.
- `body.sayuri-workspace-open` отделяет workspace визуально от floating mode.
- Появляется `#sayuri-workspace-badge`.
- Floating avatar не конкурирует с workspace.
- Пустой чат использует contextual welcome state.
- Spatial Evidence из fullscreen сначала возвращает chat в floating mode, затем открывает viewer.

### Floating avatar

- Smooth compositor drag v0.1.50 сохраняется.
- Добавляется bounded magnet threshold после pointerup.
- Snap выполняется только рядом с ближайшим краем.
- Позиция сохраняется один раз после magnet result.
- Presence-state: ready/thinking/attention/error/offline.
- Reduced-motion отключает thinking animation и snap transitions.

### Compact density

- `sayuri-compact-ui` хранится только в localStorage.
- Настройка доступна во вкладке «Поведение».
- Уменьшаются только gaps/padding/min-height; основной текст не становится мельче.

### Disk / viewer / states

- `createUiState()`: loading / empty / error.
- Disk: `setDiskLoading()` + `aria-busy`.
- Viewer preview: единый loading/error state.
- Empty table и unsupported preview используют тот же компонент.
- Initial HTML уже содержит UI-state вместо одиночной строки загрузки.

### Command Palette

- `sayuri-command-recent` хранит до 3 последних command IDs.
- При пустом query недавние команды выводятся первыми.
- Повреждённый localStorage не ломает palette.

## Инварианты

1. Sidebar идентичен v0.1.53: Главная / Диск Sayuri / Настройки.
2. Личный кабинет остаётся avatar-only entry.
3. Backend Agent/Disk permissions не меняются.
4. Spatial Evidence fact-id/bbox security boundary не меняется.
5. Нет нового UI-фреймворка или сторонней зависимости.
6. Compact mode не уменьшает основной текст.
7. UI state строится безопасным DOM, без innerHTML.
8. Motion остаётся совместимым с prefers-reduced-motion.

## Релизный критерий 0.1.54

1. Один атомарный commit от `main 0.1.53`.
2. App/Web contracts — success.
3. JavaScript syntax — success.
4. Preflight — success.
5. Version tooling / each-commit — success.
6. Windows launcher checks — success.
7. PR merge.
8. Финальный `main` workflow — success.

## Следующий рациональный этап

После стабилизации UI 0.30 — не новый глобальный редизайн, а usability measurement: keyboard/tab-order audit, responsive visual regression на 1366×768/1920×1080/mobile и claim-to-evidence coverage для ответов с D-citations.
