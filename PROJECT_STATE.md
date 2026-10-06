# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `8cc0df75a01924cbaf91001387cdadfee817774f` — опубликованный `main 0.2.0`, Versions #37410683454 success.
- Рабочая ветка этапа: `cognitive-brain-hardening-v0201`.
- Текущий целевой результат: **0.2.1 — Cognitive Brain Hardening 1.1**.
- Задача: **AI-012**.

## Версии результата

- Project: `0.2.1`.
- App/Core: `0.1.50`.
- Agent Core: `0.14.1`.
- Cognitive Project Brain: `1.1`.
- Reasoning Planner: `1.0` — без изменений.
- Evidence Tool Planner: `0.4` — без изменений.
- Web UI: `0.31.0` — без изменений.
- Disk: `0.8.0` — без изменений.
- dev-tools: `0.1.6` — без изменений.

## Что усиливается

### State ownership
- repeat sync не перезаписывает managed cognitive task scope;
- explicit task creation сразу нормализует project/module context и bind-ит scope.

### Graph safety
- confirmed cycles запрещены;
- direct cross-project task edges запрещены;
- unconfirmed edges не блокируют scheduler;
- unresolved dependency имеет приоритет над completion readiness.

### Evidence-based completion
- criteria учитывают только applied checkpoints;
- configured criteria guard запрещает преждевременный `done`;
- automatic completion отсутствует.

### Replanning / uncertainty
- failure создаёт proposal/uncertainty, но не применяет их;
- apply требует `APPLY_REPLAN` и актуального `next_action`;
- uncertainty закрывается только explicit resolution.

### Causal evidence
- observed completed action -> checkpoint;
- observed failed action -> replan/uncertainty;
- causal trace является provenance lineage, не свободной гипотезой LLM.

### Multi-module scaling
- scheduler понимает stable UI/module aliases;
- strategy/uncertainty/self-evaluation изолируются по module scope;
- cloud context не содержит module path/metadata;
- explicit local cognition API позволяет будущим модулям регистрироваться и строить dependencies без собственного Planner.

## Инварианты

1. Единственная внешняя LLM — `deepseek-ai/DeepSeek-V4-Flash` через Cloud.ru.
2. LLM имеет только read-only cognition tools.
3. Реальные project mutations остаются за Action Broker; cognitive mutation API является explicit local API.
4. Replan application требует отдельного подтверждения.
5. Completion criteria не выставляют `done` автоматически.
6. Старый checkpoint/replan не может перезаписать более новое task state.
7. Sensitive/local module metadata не отправляется в Cloud projection.
8. Chain-of-thought не сохраняется.

## Приёмка

Для публикации `0.2.1` обязательны:
- полный Python regression suite;
- JavaScript syntax;
- app preflight;
- version check `--each-commit`;
- Windows launcher checks;
- PR CI;
- squash merge;
- зелёный финальный workflow на `main`.

## Следующий этап после 0.2.1

Подключать реальные новые прикладные модули к общему Cognitive Brain через `project_key/module_key`, а не добавлять новый тип памяти/Planner. Первые хорошие кандидаты: Лаборатория Sayuri и VK-модуль. На их реальных workflow измерять scheduler accuracy, blocker handling, criteria quality и strategy transfer.
