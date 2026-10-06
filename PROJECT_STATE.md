# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `35bb9e6d5ab9e5b51075c28461b8e862f70a74e7` — опубликованный `main 0.1.56`.
- Рабочая ветка этапа: `cognitive-project-brain-v020`.
- Текущий целевой результат: **0.2.0 — Cognitive Project Brain**.
- Задача: **AI-011 — Global Multi-Module Cognitive Architecture**.

## Версии результата

- Project: `0.2.0`.
- App/Core: `0.1.49`.
- Agent Core: `0.14.0`.
- Reasoning Planner: `1.0`.
- Cognitive Project Brain: `1.0`.
- Evidence Tool Planner: `0.4`.
- Web UI: `0.31.0` — без изменений.
- Disk: `0.8.0` — без изменений.
- dev-tools: `0.1.6` — без изменений.

## Мозг

Sayuri теперь использует единый стек:

`Memory 4.x → Goal/Task Lifecycle → Cognitive Project Brain → Reasoning Planner → Evidence Tools → Result Verifier → Action Broker → Checkpoint/Strategy feedback`

Cognitive Project Brain включает:
- multi-project portfolio;
- multi-module registry;
- task graph `requires / blocks / unlocks / follows`;
- explicit completion criteria;
- dependency-aware cognitive scheduler;
- confidence + uncertainty ledger;
- existing causal/failure reasoning from Memory 4.x;
- strategy memory from confirmed action outcomes;
- persistent replan proposals;
- deterministic self-evaluation;
- metacognitive states;
- long-horizon restart restoration.

## Контракт будущих модулей

1. Новый модуль добавляется в `MODULES.json` и имеет собственный каталог/`VERSION` согласно общему versioning contract.
2. `project_key` определяет проект портфеля; без него используется `sayuri-tsukishiro`.
3. Task-producing module передаёт `project_key/module_key` в task context.
4. Cognitive Brain автоматически scope-ит задачу при trusted synchronization.
5. Модулю не нужно реализовывать отдельный Planner, scheduler, uncertainty или strategy memory.
6. Модуль может использовать общий read-only `/api/sayuri/cognition` для диагностики.

## Жёсткие инварианты

1. Единственная внешняя LLM — `deepseek-ai/DeepSeek-V4-Flash` через Cloud.ru.
2. LLM не меняет cognitive/task state напрямую.
3. Real mutations остаются confirmation-gated через Action Broker.
4. Read-only cognition tools не имеют скрытых write side-effects.
5. Dependency-blocked task не выбирается scheduler как actionable.
6. Completion criteria никогда автоматически не выставляют `done`.
7. Failure создаёт replan proposal/uncertainty, а не самовольную mutation.
8. Sensitive/local-only memory продолжает фильтроваться перед Cloud.
9. Chain-of-thought не сохраняется.

## Приёмка

Для публикации `0.2.0` обязательны:
- новый cognitive regression suite;
- весь существующий Python core suite;
- JavaScript syntax;
- app preflight;
- version check `--each-commit`;
- Windows launcher checks;
- PR CI;
- merge и зелёный final workflow на `main`.

## Следующая точка после 0.2.0

Не расширять мозг количеством новых концепций. Следующий этап — подключать реальные новые проектные модули к общему Cognitive Brain и измерять качество scheduler/criteria/strategy на настоящих многошаговых workflow.
