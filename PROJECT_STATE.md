# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `dd4907a5ba9626c7c171d064de1918e4426309a5` — опубликованный `main 0.1.54`, Versions #37403591304 success.
- Рабочая ветка этапа: `workspace-continuity-v0155`.
- Текущий результат: **0.1.55 — Workspace Quality & Goal Continuity**.
- Задача: **AI-009 / UI-008**.

## Версии результата

- Проект: `0.1.55`.
- Ядро/App contract: `0.1.47`.
- Agent Core: `0.12.0`.
- Web UI: `0.31.0`.
- Диск Sayuri: `0.8.0` — без изменений.
- dev-tools: `0.1.6` — без изменений.
- DB schema и DNA schema: без изменений.

## Что реализовано

### Goal Continuity

- Memory 4.1 строит cloud-safe read-only snapshot активных целей и незавершённых задач.
- Задачи ранжируются по priority, status и релевантности текущему запросу.
- Выбранная задача передаёт Planner поля `next_action`, `blocked_reason` и связанную цель.
- Команды «продолжай / дальше / возобнови» включают planned-mode только при наличии реального continuation context.
- Fallback Planner продолжает ближайший шаг, но не меняет Goal/Task status.
- Новый `memory.continuity` разрешён только как read-only Evidence Tool с execution receipt.

### Workspace Quality

- Command Palette и maximized chat имеют управляемый Tab/Shift+Tab focus.
- После закрытия focus возвращается к исходному control.
- Maximized chat получает `aria-modal=true`; floating chat — `false`.
- Floating avatar исключается из tab-order, пока открыт workspace.
- Добавлены responsive правила для viewport <=760px и низких экранов.
- Сохраняется один и тот же DOM/chat instance; новый UI-фреймворк не добавлен.

## Инварианты

1. Используется только `deepseek-ai/DeepSeek-V4-Flash` через Cloud.ru.
2. LLM не меняет Goal/Task Memory напрямую.
3. Все mutations остаются confirmation-gated через Action Broker.
4. Sensitive/local-only memory не попадает в Cloud через continuity.
5. Sidebar остаётся Главная / Диск Sayuri / Настройки; Личный кабинет — avatar-only entry.
6. Spatial Evidence fact-id/bbox boundary не меняется.
7. Compact/responsive UI не уменьшает основной текст.
8. Chain-of-thought не сохраняется и не показывается.

## Проверка релиза

Для принятия `0.1.55` обязательны:
- Python unit tests;
- JavaScript syntax;
- app preflight;
- version check `--each-commit`;
- Windows launcher checks;
- PR merge;
- зелёный финальный workflow на `main`.

## Следующий рациональный этап

После `0.1.55` развивать lifecycle задач: checkpoint после подтверждённых действий, доказательное обновление `next_action` и восстановление многошаговой работы между сессиями — без фоновых mutations и без передачи LLM права самостоятельно закрывать задачи.
