# Cognitive Project Brain

Версия контракта: **1.2**  
Проект: **Sayuri-Tsukishiro**

## Назначение

Cognitive Project Brain — локальный детерминированный orchestration layer над Memory 4.x, Goal/Task Lifecycle, Reasoning Planner и Action Broker. Он предназначен для долгоживущей работы Sayuri с несколькими проектами и большим количеством модулей.

Это не вторая LLM, не автономный агент исполнения и не хранилище chain-of-thought.

```text
Portfolio
└── Project
    ├── Milestone
    │   └── required / optional Tasks
    ├── Module
    │   ├── Goal
    │   └── Task
    │       ├── Dependencies
    │       ├── External Blockers
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

Межпроектная зависимость не создаётся прямым task edge. Для неё используется `milestone → external blocker`, чтобы портфель не превращался в один глобальный цикл.

## Portfolio Milestones

Milestone принадлежит одному project scope и может дополнительно быть связан с module scope. В milestone входят required и optional tasks.

- required tasks определяют readiness;
- `ready_for_confirmation` ещё не означает `done`;
- завершение требует explicit local `COMPLETE_MILESTONE`;
- milestone не закрывается по тексту модели или только по self-evaluation score.

## External Blockers

External blocker связывает зависимый project/module/task с внешним условием. Для межпроектной координации blocker может ссылаться на source milestone другого проекта.

Persistent blocker history не удаляется автоматически. Если source milestone завершён, его `effective_status` становится `resolved` для scheduler, но исходная запись blocker сохраняется. Независимый blocker закрывается explicit local resolution.

## Completion Criteria

Поддерживаются:
- `checkpoint_count` — минимум applied checkpoints;
- `tool_completed` — минимум applied checkpoints конкретного Action Broker tool;
- `dependency_done` — конкретная dependency task имеет status `done`;
- `manual_confirmation` — явный локально зафиксированный criterion.

Результат `ready_for_confirmation` означает только готовность к явному завершению. Cognitive Brain сам никогда не выставляет task `done`.

## Scheduler

Scheduler 1.2 строит один batched portfolio snapshot на planning cycle и учитывает task priority/status, project priority, query overlap, module affinity, active milestones, confirmed task dependencies, external blockers, uncertainty severity, attention state и completion state.

`project_key` в явном context ограничивает выбор данным проектом. `module_key` остаётся affinity, чтобы scheduler мог выбрать prerequisite из соседнего модуля того же проекта. Cloud projection ограничена восемью candidates.

Deep `graph_integrity()` проверяет confirmed dependency cycles, cross-project task edges и milestone/task scope. Обычный `status()` не запускает эту тяжёлую проверку при каждом открытии интерфейса.

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
- `POST /api/sayuri/cognition/replans/{id}/apply` with `confirmation=APPLY_REPLAN`;
- `POST /api/sayuri/cognition/milestones`;
- `POST /api/sayuri/cognition/milestones/{id}/tasks`;
- `POST /api/sayuri/cognition/milestones/{id}/complete` with `confirmation=COMPLETE_MILESTONE`;
- `POST /api/sayuri/cognition/external-blockers`;
- `POST /api/sayuri/cognition/external-blockers/{id}/resolve`.

Read-only portfolio lists:
- `GET /api/sayuri/cognition/milestones`;
- `GET /api/sayuri/cognition/external-blockers`.

Эти mutation endpoints не являются LLM tools.

## Правило для будущих модулей

Новый модуль не должен создавать собственные копии Planner, scheduler, uncertainty ledger или strategy memory. Он регистрирует себя, создаёт задачи с project/module scope и предоставляет свои разрешённые tools/handlers. Общий Cognitive Brain решает, какая задача актуальна, что её блокирует и какие evidence/criteria нужны.
