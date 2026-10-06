# Reasoning Logic 2.0

Версия контракта: **2.0**

Reasoning Logic — локальный deterministic слой внутри Agent Core. Он не является второй LLM, второй памятью, вторым Planner или автономным агентом. Его задача — управлять безопасным жизненным циклом рассуждения вокруг существующего DeepSeek-V4-Flash Planner/Verifier.

## Цель

Sayuri должна не просто получать ответ модели, а проходить управляемый цикл:

```text
UNDERSTAND
  → RETRIEVE
  → FRAME
  → PLAN
  → CHECK
  → ACT
  → VERIFY
  → REFLECT
  → CONTINUE
```

Ветви безопасности:

```text
CHECK → UNCERTAIN → GATHER_EVIDENCE → PLAN
ACT   → FAILED → DIAGNOSE → REPLAN
VERIFY → REPLAN
VERIFY → READY_FOR_CONFIRMATION
```

## Источник истины

Reasoning Logic не владеет persisted task status.

- Goal/Task lifecycle — Memory 4.x.
- Project/module/task blockers — Cognitive Project Brain.
- Реальные mutations — SayuriActionBroker.
- Read-only evidence — Evidence Tool Planner.
- Внешняя модель — только `deepseek-ai/DeepSeek-V4-Flash`.
- Reasoning Logic хранится только в памяти текущего request/response и не создаёт отдельную БД.

## Состояния

| State | Назначение |
| --- | --- |
| UNDERSTAND | Определить intent запроса |
| RETRIEVE | Отметить доступные безопасные контексты |
| FRAME | Зафиксировать project/module scope и ограничения |
| PLAN | Принять structured plan Planner |
| CHECK | Проверить blockers, uncertainty и policy |
| ACT | Выполнить разрешённые read-only checks или сформировать ответ |
| VERIFY | Проверить результат Result Verifier |
| REFLECT | Сформировать краткий безопасный итог проверки |
| CONTINUE | Разрешить следующий проверяемый шаг |
| UNCERTAIN | Зафиксировать высокий уровень неопределённости |
| GATHER_EVIDENCE | Требовать evidence до сильного вывода |
| REPLAN | Перестроить маршрут после verifier/failure |
| FAILED | Зафиксировать неуспешный шаг |
| DIAGNOSE | Определить, какое evidence нужно для причины сбоя |
| READY_FOR_CONFIRMATION | Критерии готовы, но нужен человек |

## Intent Resolver

Deterministic resolver различает как минимум:

- `continue`;
- `compare`;
- `plan`;
- `action`;
- `analyze`;
- `question`;
- `request`.

Intent не даёт права на mutation. Он влияет только на маршрут reasoning.

## Structured Planner 2.0

Planner по-прежнему не отдаёт chain-of-thought. Разрешённый JSON расширен:

- `goal`;
- `intent`;
- `steps`;
- `constraints`;
- `assumptions`;
- `hypotheses`;
- `options`;
- `selected_option`;
- `decision_summary`;
- `counterfactual_checks`;
- `evidence_needed`;
- `done_when`;
- `risk_level`;
- `tool_intents`.

`assumptions/hypotheses/options/counterfactual_checks` — краткие проверяемые структуры, а не скрытый ход рассуждения.

## Constraint Gate

Локальные правила имеют приоритет над Planner:

1. Active task/external blocker → `CHECK`; executable ACT запрещён.
2. High uncertainty → `GATHER_EVIDENCE`.
3. Mutation intent от Planner → только `requires_action_broker`.
4. `ready_for_completion_confirmation` → только `READY_FOR_CONFIRMATION`, никогда автоматический `done`.
5. Stale/blocked lifecycle state сильнее старого plan.

## Evidence Gate

Если structured plan требует evidence и нет completed read-only receipt, состояние остаётся `GATHER_EVIDENCE`.

Completed receipt доказывает только факт выполнения конкретной локальной read-only проверки и её результат. Он не доказывает произвольный вывод модели.

## Verification Gate

Result Verifier возвращает:

- `status=pass|revise`;
- `score`;
- `confidence`;
- checks;
- issues;
- unsupported claims;
- optional full revised answer.

Локальная state machine интерпретирует результат:

- `pass` → REFLECT → CONTINUE;
- `revise`/unsupported claim → REPLAN;
- verifier unavailable → UNCERTAIN;
- completion ready → READY_FOR_CONFIRMATION.

## Decision Trace

Пользовательский Decision Trace содержит только безопасные структурированные записи:

```json
{
  "stage": "CHECK",
  "status": "completed",
  "code": "constraints_passed",
  "summary": "Блокирующих ограничений не найдено."
}
```

Trace не содержит:
- скрытый chain-of-thought;
- внутренние токены модели;
- system prompt;
- API secrets;
- raw tool receipts;
- локальные database IDs, если они не нужны пользовательскому слою.

Trace предназначен для ответа на вопросы:
- что Sayuri поняла;
- какой state сейчас активен;
- что блокирует следующий шаг;
- есть ли evidence;
- прошла ли проверка;
- почему требуется replan или подтверждение.

## UI

Existing reasoning summary показывает компактно:

- количество шагов;
- verification status;
- текущий Reasoning Logic state;
- confidence;
- последние безопасные trace entries;
- количество model calls/read-only checks.

Новая постоянная панель не создаётся.

## Инварианты безопасности

1. `chain_of_thought_storage=false`.
2. State machine request-scoped и не создаёт отдельного task store.
3. DeepSeek не может изменить state machine напрямую.
4. Planner/Verifier не могут выполнить mutation.
5. Blockers и high uncertainty сильнее уверенного текста модели.
6. Completion readiness не означает completion.
7. Decision Trace — summary/provenance, а не внутренний reasoning transcript.
8. Простые запросы не вызывают Planner/Verifier: direct path остаётся одним model call.

## Интеграция будущих модулей

Новый модуль не создаёт собственный Reasoning Logic. Он передаёт canonical project/module/task context в Cognitive Brain и предоставляет read-only evidence/confirmation-gated actions через существующие contracts.

Таким образом, все будущие модули — VK, Лаборатория Sayuri и другие — используют одну общую логику принятия решений.
