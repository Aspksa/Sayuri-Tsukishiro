# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `c3b2af6b9ca9c28a6f7de618fda26828ca35cd9e` — проект `0.1.49`, Background Evidence Automation.
- Проверка базы: финальный workflow Versions #481 — success.
- Целевая версия: `0.1.50`.
- Текущая задача: **UI-004 — Sayuri Presence UX Cleanup**.

## Версии целевого дерева

- Проект: `0.1.50`.
- Ядро Саюри: `0.1.42`.
- Agent Core: `0.10.1` — не изменяется.
- Web UI: `0.26.0`.
- Диск Sayuri: `0.7.1` — не изменяется.
- Dev tools: `0.1.6` — не изменяются.

## Что меняется

### Sidebar

Левое меню не перерабатывается. Единственное изменение — удаляется отдельная кнопка «Личный кабинет». Кабинет остаётся доступен через ПКМ по плавающему аватару Sayuri.

### Avatar drag

```text
pointerdown
→ click/drag threshold
→ pointer capture
→ pointermove
→ requestAnimationFrame
→ translate3d
→ clamp viewport
→ pointerup
→ commit left/top once
→ persist final position
```

Цель: убрать рывки, layout churn и застревание.

### Chat

- ChatGPT-подобная чистая поверхность.
- Default desktop size около 560×720 с min/max constraints.
- Drag за шапку.
- Resize за правый нижний угол.
- Позиция и размер хранятся раздельно.
- Composer сам увеличивает высоту до лимита.
- Mobile layout занимает доступный экран и не показывает resize handle.

### Личный кабинет

Вместо одной длинной страницы используются вкладки:

1. Профиль.
2. AI.
3. Поведение.
4. Память.
5. Образ.
6. Диагностика.

Существующие Cloud.ru, actions, Memory 2/3/4, Experience и avatar studio сохраняются, но показываются только в своём разделе. Вкладка «Память» дополнительно делится на «Обзор», «Архитектура», «Quality Gate» и «Опыт», поэтому Memory 2/3/4 больше не образуют одно длинное полотно.

## Релизный критерий 0.1.50

1. Один атомарный commit от `main 0.1.49`.
2. App/Web contract tests — success.
3. Scripts/versioning tests — success.
4. JavaScript syntax — success.
5. Preflight — success.
6. `versioning.py check --each-commit` — success.
7. Windows launcher checks — success.
8. Merge через PR.
9. Финальный `main` workflow — success.

## Следующий рациональный этап

После стабилизации UX вернуться к мозгу и документным evidence-функциям, не добавляя технический шум в интерфейс.
