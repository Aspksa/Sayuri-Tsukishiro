# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `32761c2e1d56f2e824a6d5a8c266245bab436c3f` — проект `0.1.46`, финальный main workflow Versions #467 успешен.
- Целевая версия: `0.1.47`.
- Текущая задача: **AI-005 — Reasoning Planner + Result Verifier**.
- Статус целевого дерева: функциональная реализация подготовлена; атомарный release CI/merge требуется подтвердить.

## Версии целевого дерева

- Проект: `0.1.47`.
- Ядро Саюри: `0.1.39`.
- Agent Core: `0.9.0`.
- Диск Sayuri: `0.7.1` — не изменялся.
- Web UI: `0.23.0`.
- Dev tools: `0.1.6` — не изменялись.

## Reasoning architecture

Новый слой использует стабильную Memory 4.1 как входной контур и не создаёт вторую память или вторую LLM.

```text
user task
→ deterministic complexity gate
→ direct answer
  или
→ Reasoning Planner
→ structured task-plan
→ answer
→ Result Verifier
→ optional revised_answer
→ final response
```

### Planner

Structured plan содержит только goal, steps, constraints, evidence_needed, done_when и risk_level. Planner не просит и не хранит chain-of-thought.

### Adaptive gate

Простые сообщения остаются в `direct` mode и используют один запрос к Cloud.ru. Сложные архитектурные, многошаговые, аналитические и verification-oriented задачи переходят в `planned` mode.

### Result Verifier

Verifier отдельным вызовом той же `deepseek-ai/DeepSeek-V4-Flash` проверяет цель, constraints, evidence и unsupported claims. При `revise` полный исправленный ответ возвращается прямо из verifier call; четвёртый модельный вызов не требуется.

### Failure policy

- Planner unavailable / invalid JSON -> deterministic fallback-plan.
- Verifier unavailable / invalid JSON -> основной answer сохраняется, status = `unavailable`.
- Planner/Verifier не расширяют Safe Action permissions.
- UI не показывает unavailable verifier как успешно пройденную проверку.

## Memory integration

Planner и Verifier получают только уже отфильтрованные Memory 4.1, Memory 3.0, Experience и UI context. Instruction-risk/local-only память не получает обходной путь через reasoning layer. Memory usage commit остаётся post-budget и выполняется после reasoning pipeline.

## Observability

Ответ API содержит `reasoning`: mode, complexity_score/reasons, planner_status, structured plan, verification, revised, model_calls и `chain_of_thought_stored=false`.

Web chat показывает компактный details-блок: `План · N шагов · проверено/исправлено/проверка недоступна`.

## Релизный критерий 0.1.47

1. Один атомарный commit от `main 0.1.46`.
2. Python scripts tests — success.
3. App/core tests включая `test_reasoning.py` — success.
4. JavaScript syntax — success.
5. Preflight — success.
6. `versioning.py check --each-commit` — success.
7. Windows launcher — success.
8. Merge через PR.
9. Финальный main push workflow — success.

## Следующий рациональный этап

После стабилизации Planner/Verifier следующий шаг — **Evidence-aware Tool Planner**: связывать structured steps с разрешёнными read-only/confirmation-gated инструментами, сохраняя execution receipts и не позволяя LLM напрямую обходить Action Broker.
