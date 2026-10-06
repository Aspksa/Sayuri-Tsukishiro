# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `bf9ffc499fbfa5b472c526f79f0e18166d6c7ce5` — опубликованный `main 0.2.1`, Versions #37412163229 success.
- Рабочая ветка этапа: `portfolio-milestones-v0202`.
- Текущий целевой результат: **0.2.2 — Portfolio Milestones & Scalable Scheduler**.
- Задача: **AI-013**.

## Версии результата

- Project: `0.2.2`.
- App/Core: `0.1.51`.
- Agent Core: `0.15.0`.
- Cognitive Project Brain: `1.2`.
- Reasoning Planner: `1.1`.
- Evidence Tool Planner: `0.4` — без изменений.
- Web UI: `0.31.0` — без изменений.
- Disk: `0.8.0` — без изменений.
- dev-tools: `0.1.6` — без изменений.

## Новая архитектура портфолио

`Portfolio → Project → Milestone/Module → Goal/Task → Dependencies + External Blockers → Scheduler → Evidence/Checkpoint → Evaluation`

### Milestones
- persistent project/module milestones;
- required/optional task membership;
- readiness только по фактическим task status;
- `done` только после `COMPLETE_MILESTONE`.

### Cross-project coordination
- direct cross-project task edges по-прежнему запрещены;
- зависимость между проектами: source milestone → external blocker;
- source milestone снимает blocker только в effective read state;
- blocker history не стирается.

### Scale
- scheduler/metacognition/self-evaluation используют batched portfolio snapshot;
- task capacity: 5000;
- sync известных task scope пакетный;
- обычный status остаётся lightweight;
- deep graph integrity вызывается отдельно.

### Safety
- high uncertainty блокирует автоматическую lifecycle-привязку mutation к task;
- task/external blockers сильнее completion readiness;
- DeepSeek получает только bounded read-only portfolio context;
- milestone/blocker mutation API не входит в LLM tools;
- реальные действия проекта остаются за Action Broker.

## Приёмка

Для публикации `0.2.2` обязательны:
- полный Python regression suite;
- JavaScript syntax;
- app preflight;
- version check `--each-commit`;
- Windows launcher checks;
- branch CI;
- PR CI;
- squash merge;
- зелёный финальный workflow на `main`.

## Следующий этап после 0.2.2

Следующий мозговой слой — explicit Hypothesis & Evidence Ledger: отделить факт, гипотезу, предположение и неизвестность; уметь накапливать support/refute evidence и повышать/понижать confidence без превращения модели в источник истины.
