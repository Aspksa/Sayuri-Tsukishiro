# Cognitive Project Brain

Версия контракта: **1.2**  
Проект: **Sayuri-Tsukishiro**

## Назначение

Cognitive Project Brain — локальный детерминированный orchestration layer над Memory 4.x, Goal/Task Lifecycle, Reasoning Planner и Action Broker. Он предназначен для долгоживущей работы Sayuri с несколькими проектами и большим количеством модулей.

Это не вторая LLM, не автономный агент исполнения и не хранилище chain-of-thought.

```text
Portfolio
└── Project
    ├── Module
    │   ├── Goal
    │   └── Task
    │       ├── Dependencies
    │       ├── Completion Criteria
    │       ├── Checkpoints
    │       ├── Uncertainty
    │       ├── Replan Proposals
    │       ├── Strategy Statistics
    │       └── Causal Evidence Lineage
    └── Module ...
```

## Источник истины

- Memory 4.x владеет Goal/Task status, `next_action`, blockers и checkpoints.
- Cognitive Brain владеет project/module scope, dependency graph, criteria, attention/confidence, uncertainty, strategy statistics, replan proposals и self-evaluation.
- Action Broker остаётся единственным контуром подтверждённых реальных действий.
- LLM читает bounded cognition projection, но не владеет persistent mutations.

## Контракт модуля

Прикладной модуль регистрируется в `MODULES.json` и имеет стабильный `id`, который используется как `module_key`. Task-producing module передаёт:

```json
{
  "project_key": "sayuri-tsukishiro",
  "module_key": "sayuri-disk",
  "milestone": "optional",
  "labels": ["optional"],
  "completion_criteria": [
    {"type": "checkpoint_count", "min": 1}
  ]
}
```

Если project key не задан, trusted local code использует `sayuri-tsukishiro`. UI aliases существуют только для уже известных экранов и не заменяют стабильный module_key нового модуля.

## Task Graph

Поддерживаются `requires`, `follows`, `blocks`, `unlocks`. Для confirmed edges:
- self-edge запрещён;
- dependency cycle запрещён;
- обе задачи должны принадлежать одному project scope;
- пока prerequisite не `done`, dependent task не считается actionable.

Unconfirmed edge может храниться как черновая гипотеза, но scheduler её игнорирует.

Межпроектная зависимость не создаётся прямым task edge. Для неё используется milestone/external blocker, чтобы портфель не превращался в один глобальный цикл.

## Completion Criteria

Поддерживаются:
- `checkpoint_count` — минимум applied checkpoints;
- `tool_completed` — минимум applied checkpoints конкретного Action Broker tool;
- `dependency_done` — конкретная dependency task имеет status `done`;
- `manual_confirmation` — явный локально зафиксированный criterion.

Результат `ready_for_confirmation` означает только готовность к явному завершению. Cognitive Brain сам никогда не выставляет task `done`.

## Scheduler

Scheduler учитывает priority, task status, query overlap, project/module affinity, confirmed blockers, uncertainty severity, attention state и completion state. Cloud projection ограничена восемью candidates.

## Uncertainty

Uncertainty является persistent объектом с severity и `evidence_needed`. Она не исчезает по уверенной формулировке модели. Закрытие выполняется explicit local resolution.

## Replanning

Failed confirmed action создаёт `proposed` revision. Proposal не меняет `next_action`. Apply требует explicit `APPLY_REPLAN` и совпадения текущего `next_action` с snapshot, на котором proposal был создан.

## Strategy Memory

Strategy Memory агрегирует observed completed/failed outcomes по tool в project/module scope. Confidence является статистической оценкой опыта, а не доказательством факта и не разрешением на mutation.

## Causal Evidence

Causal layer 1.1 хранит только provenance:
- `confirmed_action -> task_checkpoint`;
- `confirmed_action_failure -> replan_proposal`;
- `confirmed_action_failure -> uncertainty`.

Это означает «наблюдаемое событие породило данный системный объект», а не «это единственная реальная причина проблемы».

## Cloud boundary

В DeepSeek-V4-Flash допускаются только cloud-safe task text, compact project/module identifiers/titles, bounded scheduler state, safe uncertainty и strategy summary. Локальные module paths, manifest metadata и другие внутренние детали не включаются в cloud projection.

## API

Read-only diagnostics:

`GET /api/sayuri/cognition?q=<query>&project_key=<project>&module_key=<module>`

Explicit local state mutations:

- `POST /api/sayuri/cognition/projects`;
- `POST /api/sayuri/cognition/modules`;
- `POST /api/sayuri/cognition/dependencies`;
- `POST /api/sayuri/cognition/tasks/{task_id}/criteria`;
- `POST /api/sayuri/cognition/uncertainties/{id}/resolve`;
- `POST /api/sayuri/cognition/replans/{id}/apply` with `confirmation=APPLY_REPLAN`.

Эти mutation endpoints не являются LLM tools.

## Правило для будущих модулей

Новый модуль не должен создавать собственные копии Planner, scheduler, uncertainty ledger или strategy memory. Он регистрирует себя, создаёт задачи с project/module scope и предоставляет свои разрешённые tools/handlers. Общий Cognitive Brain решает, какая задача актуальна, что её блокирует и какие evidence/criteria нужны.


## Portfolio Scale & Integrity 1.2

### Snapshot model

Scheduler строит один read-only portfolio snapshot на цикл. В нём агрегируются task state, scopes, registry, confirmed blockers, uncertainty и applied checkpoint counters. Это устраняет повторные per-task SQLite/Memory чтения при росте числа модулей.

Self-evaluation переиспользует snapshot для task/dependency/completion metrics.

### Integrity diagnostics

`graph_integrity()` проверяет persisted confirmed graph на missing-task edges, legacy cross-project edges и cycles. Метод read-only: исправление требует отдельного явного решения.

### Evidence-first uncertainty

High-severity uncertainty имеет приоритет над обычным `next_action` в scheduler recommendation: сначала evidence, затем пересчёт плана.

### Cloud projection 1.2

Cloud-safe cognition не включает:
- database IDs project/module/strategy;
- module paths и metadata;
- causal source/effect IDs или evidence_ref;
- internal replan/task/revision/evidence IDs;
- blocker task IDs.

Сохраняются только значения, необходимые модели для рассуждения: keys/titles, task text/state, relation labels, uncertainty text/severity/evidence need, completion summary и агрегированная strategy statistics.

### Tool trigger

Read-only `cognition.next` не запускается от общего упоминания проекта/модуля. Нужен конкретный запрос о следующей задаче, dependencies/blockers, criteria/readiness, replanning, uncertainty, strategy, queue или priority.
