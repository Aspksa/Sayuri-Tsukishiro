# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная функциональная ревизия: `bb7151baf72d7d681e84cd124f52e623bb3588c1` — опубликованный `main 0.2.7`, Versions #37418057599 success.
- Рабочая ветка публикационной синхронизации: `publish-sync-v0208`.
- Старый PR #27 (`0.2.2`) закрыт как superseded и не должен сливаться поверх `main 0.2.3+`.
- Текущий результат: **0.2.8 — GitHub Publication Sync**.
- Задача: **AI-014**.

## Версии результата

- Project: `0.2.8`.
- App/Core: `0.1.55`.
- Agent Core: `0.15.2`.
- Cognitive Project Brain: `1.3.2`.
- Reasoning Planner: `1.1`.
- Evidence Tool Planner: `0.4.2`.
- Web UI: `0.31.0` — без изменений.
- Disk: `0.8.0` — без изменений.
- dev-tools: `0.1.6` — без изменений.

## Фактическая публикация на GitHub

- Default branch: `main`.
- Main commit до publication-sync: `bb7151baf72d7d681e84cd124f52e623bb3588c1`.
- Main tree: `7b963ed5c12b89c2a3b347fd5fbd5984ba277cec`.
- В дереве: 81 файл и 10 каталогов; tree response не truncated.
- Рабочая ветка `portfolio-coordination-v0204` и `main` имеют идентичный tree SHA, поэтому функциональных файлов вне `main` не осталось.
- PR #28 merged.
- Финальный workflow #37418057599 — `success`.
- Причина визуальной путаницы: README оставался с верхним разделом `0.2.3`, хотя код и VERSION уже были `0.2.7`. В `0.2.8` это синхронизировано.

## Цель этапа

Сделать Cognitive Brain пригодным не только для десятков модулей одного проекта, но и для портфеля самостоятельных проектов, которые могут зависеть друг от друга без превращения task graph в один глобальный цикл.

## Реализуется

### Portfolio milestones
- persistent `cognitive_milestones`;
- optional module scope;
- required/optional task links;
- milestone может включать только tasks своего project scope;
- completed required tasks дают только `ready_for_confirmation`;
- переход milestone в `done` требует explicit `COMPLETE_MILESTONE`.

### Cross-project coordination
- direct cross-project task edges по-прежнему запрещены;
- межпроектная зависимость моделируется `cognitive_external_blockers`;
- blocker может быть project/module/task scoped;
- blocker может ссылаться на source project и source milestone;
- source milestone `done` даёт derived effective resolution;
- explicit resolution остаётся отдельным local mutation.

### Portfolio integrity
- при создании external dependency проверяется project-level cycle;
- проверка учитывает только effective-open dependencies: историческая blocker-запись на уже завершённый source milestone не создаёт ложный цикл;
- legacy portfolio cycle диагностируется read-only `graph_integrity()`;
- milestone-task link проверяется на project ownership;
- никакого автоматического repair persisted state.

### Scheduler
- milestones/external blockers входят в существующий batch snapshot;
- явный `project_key` — жёсткий scheduler boundary;
- milestone priority может повышать релевантность task;
- task dependency и external blocker считаются раздельно;
- blocked task не получает actionable status;
- context/metacognition переиспользуют текущий snapshot и не перескакивают на другой project при отсутствии actionable task.

### Cloud privacy
- Cloud projection не получает local task IDs, source project DB IDs, source milestone IDs, module paths или manifest metadata;
- model видит только bounded project/module keys/titles, blocker type/title/relation/key, milestone key/title/status/priority и completion summary;
- persistent mutations остаются локальными.

### Reasoning / tools
- Reasoning Planner 1.1 понимает milestones и external blockers как read-only constraints;
- модель не может объявить milestone завершённым;
- модель не может снять external blocker по предположению;
- Evidence Tool Planner 0.4.2 запускает cognition read-only check по milestone/external-blocker intent, но не по общим словам «проект/модуль»;
- Action Broker и explicit local cognition API остаются единственными mutation boundaries.

## Инварианты

1. Единственная внешняя LLM — `deepseek-ai/DeepSeek-V4-Flash` через Cloud.ru.
2. LLM cognition tools только read-only.
3. Milestone/external blocker mutation API не входит в LLM tool catalog.
4. Direct cross-project task dependency запрещена.
5. Межпроектные effective-open связи не должны образовывать portfolio cycle.
6. Milestone и task никогда не получают `done` автоматически от модели, Planner, Verifier или criteria.
7. Source milestone разблокирует target только после подтверждённого local `done`.
8. Graph/portfolio integrity диагностика ничего не исправляет автоматически.
9. Chain-of-thought не сохраняется.

## Последняя неуспешная проверка

- Candidate `0.2.4`: commit `5c0532f1c92c56d921ce49eba327b39277eb9747`, branch workflow #37417246205.
- Version tooling прошёл.
- Python core suite остановился на import-time `SyntaxError` в `agent/cognition.py`: двойная строка `def self_evaluation(`.
- Исправление SyntaxError оформлено отдельным `0.2.5`, историю `0.2.4` не переписывать.
- Candidate `0.2.5`: commit `c1816efdade9d44ff98bb925bb565319eb8f068b`, workflow #37417544393.
- Python suite запустил 169 tests; остались stale scheduler-version assertion и `NameError` в `graph_integrity()` из-за отсутствующих локальных milestone/portfolio queries.
- Оба дефекта исправлены candidate `0.2.6`; App bump был обязателен, потому что менялся regression test.
- Candidate `0.2.6`: commit `09ce260e6849587473ea3f7fd5e1ea61767ebcde`, workflow #37417751833.
- Результат core suite: 168/169 success; единственный failure — stale assertion Cognitive Brain `1.2` вместо фактического публичного contract `1.3.2`.
- Последний test-contract fix оформляется отдельным versioned candidate `0.2.7`.

## Приёмка

Релиз считается принятым только после:
- portfolio milestone/cross-project regressions;
- strict project scheduler regression;
- Cloud privacy regression;
- local API / LLM mutation-boundary regression;
- narrow cognition tool-trigger regression;
- полного Python test suite;
- JavaScript syntax;
- app preflight;
- version check `--each-commit`;
- Windows launcher checks;
- PR CI;
- squash merge;
- финального зелёного workflow на `main`.

## Следующий этап после 0.2.8

После стабилизации portfolio coordination не добавлять ещё один абстрактный cognitive layer. Подключить первый реальный крупный прикладной модуль к canonical contract и измерить качество scheduler, milestones, blockers, completion criteria и strategy transfer на настоящем workflow.
