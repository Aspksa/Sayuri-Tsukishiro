# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `dc1ca53926d32498da084ce34757eec8c8ee21f5` — опубликованный `main 0.1.55`, Versions #37407648237 success.
- Рабочая ветка этапа: `task-lifecycle-v0156`.
- Текущий результат: **0.1.56 — Task Lifecycle & Checkpoints**.
- Задача: **AI-010**.

## Версии результата

- Проект: `0.1.56`.
- Ядро/App contract: `0.1.48`.
- Agent Core: `0.13.0`.
- Web UI: `0.31.0` — без изменений.
- Диск Sayuri: `0.8.0` — без изменений.
- dev-tools: `0.1.6` — без изменений.
- DB schema приложения и DNA schema: без изменений; Memory 4.x получает новую внутреннюю checkpoint table через idempotent CREATE TABLE.

## Что реализовано

### Task Lifecycle

- Persistent `memory_task_checkpoints` хранится в `sayuri-memory.db`.
- Action связывается с незавершённой task только локально и только при deterministic query overlap.
- Пользовательский `_task_lifecycle` игнорируется и пересоздаётся runtime.
- Checkpoint создаётся только после Action Broker `completed`.
- Повтор одного action id идемпотентен.
- Checkpoint хранит sequence, before/after task state и SHA-256 подтверждённого результата.

### Evidence-based next_action

- `planned / in_progress` task может получить deterministic follow-up только при совпадении сохранённого task snapshot с текущим.
- Stale snapshot не перезаписывает новый `next_action`.
- `blocked`, `done`, `cancelled` автоматически не меняются.
- Lifecycle никогда автоматически не выставляет `done`.

### Restart restoration

- Goal Continuity возвращает `resume.latest_checkpoint` выбранной задачи.
- После повторной инициализации Sayuri continuation восстанавливается из SQLite.
- Reasoning Planner 0.5 получает checkpoint как evidence конкретного шага, но не право менять lifecycle.

## Инварианты

1. Только `deepseek-ai/DeepSeek-V4-Flash` через Cloud.ru.
2. LLM не создаёт и не применяет task checkpoint.
3. Все реальные mutations остаются confirmation-gated через Action Broker.
4. Action context lifecycle остаётся внутренним.
5. Checkpoint не означает завершение всей задачи.
6. Stale/blocked/closed task state нельзя перезаписать старым action result.
7. Goal/Task restore не требует фонового worker.
8. Chain-of-thought не сохраняется.

## Проверка релиза

Для принятия `0.1.56` обязательны:
- Python unit tests;
- JavaScript syntax;
- app preflight;
- version check `--each-commit`;
- Windows launcher checks;
- PR merge;
- зелёный финальный workflow на `main`.

## Следующий рациональный этап

После `0.1.56` развивать Task Graph: зависимости между несколькими задачами, explicit completion criteria и автоматический выбор следующей разблокированной task только из подтверждённого lifecycle state — без автономных mutations.
