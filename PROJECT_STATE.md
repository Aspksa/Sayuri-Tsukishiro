# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `bf9ffc499fbfa5b472c526f79f0e18166d6c7ce5` — опубликованный `main 0.2.1`, Versions #37412163229 success.
- Рабочая ветка этапа: `portfolio-scale-v0202`.
- Текущий целевой результат: **0.2.2 — Portfolio Scale & Integrity**.
- Задача: **AI-013**.

## Версии результата

- Project: `0.2.2`.
- App/Core: `0.1.51`.
- Agent Core: `0.14.2`.
- Cognitive Project Brain: `1.2`.
- Reasoning Planner: `1.0` — без изменений.
- Evidence Tool Planner: `0.4.1`.
- Web UI: `0.31.0` — без изменений.
- Disk: `0.8.0` — без изменений.
- dev-tools: `0.1.6` — без изменений.

## Цель этапа

Не добавлять новый cognitive layer. Подготовить существующий Brain к десяткам модулей и сотням задач за счёт scale/integrity/privacy hardening.

## Реализовано в target snapshot

### Portfolio scale
- scheduler использует единый `_scheduler_snapshot()` вместо per-task N+1 чтений;
- self-evaluation переиспользует snapshot для task/dependency/completion;
- top Cloud candidates остаются bounded до 8;
- sync получает known task scopes пакетно.

### Registry / modules
- repeat module registration сохраняет существующий title;
- metadata merge-ятся, а не заменяются целиком;
- существующий project priority не меняется без explicit priority.

### Integrity
- explicit read-only `graph_integrity()` обнаруживает missing-task/cross-project/cycle legacy state;
- integrity diagnostics не выполняет автоматический repair.

### Uncertainty
- high-severity uncertainty переводит recommendation в evidence-first режим.

### Cloud / tool policy
- project/module Cloud scope: только key/title;
- strategy/causal/replan/metacognition лишены ненужных внутренних IDs;
- generic «проект/модуль» не запускает `cognition.next` без специфического cognitive intent;
- explicit `/api/sayuri/cognition` diagnostics включает graph integrity, лёгкий status остаётся дешёвым.

## Инварианты

1. Единственная внешняя LLM — `deepseek-ai/DeepSeek-V4-Flash` через Cloud.ru.
2. LLM cognition tools только read-only.
3. Explicit local cognition mutation API из 0.2.1 не включён в LLM tool catalog.
4. Real project actions остаются confirmation-gated через Action Broker.
5. Completion criteria не выставляют `done` автоматически.
6. Graph integrity не ремонтирует state молча.
7. High uncertainty требует evidence-first recommendation, но не меняет task автоматически.
8. Sensitive/local metadata и внутренние causal/replan identifiers не отправляются в Cloud.
9. Chain-of-thought не сохраняется.

## Приёмка

Релиз считается принятым только после:
- cognitive scale/integrity regressions;
- полного Python test suite;
- JavaScript syntax;
- app preflight;
- version check `--each-commit`;
- Windows launcher checks;
- PR CI;
- squash merge;
- финального зелёного workflow на `main`.

## Ограничение проверки до публикации

Локальная загрузка непривязанной GitHub archive ревизии была заблокирована средой, поэтому локальный suite не заявляется как выполненный. Источником исполняемой проверки является GitHub Actions после атомарного branch commit.

## Следующий этап после 0.2.2

Не наращивать абстрактный мозг дальше без реального workflow. Подключить первый крупный прикладной модуль к canonical contract и измерять scheduler accuracy, graph blockers, criteria quality, uncertainty handling и strategy transfer на реальной работе.
