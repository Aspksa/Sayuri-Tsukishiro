# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `6ab578f9f61212bea92dc92d2c642d816dae5f79` (проект `0.1.44`, финальный CI зелёный).
- Целевая версия текущего релиза: `0.1.45`.
- Текущий этап: **Memory 4.0 Hardening — сквозная privacy-защита, read-only local recall и доказательная Failure/Causal Memory**.

## Версии активных модулей

- Ядро Саюри: `0.1.37`.
- Agent Core: `0.8.1`.
- Диск Sayuri: `0.7.1`.
- Web UI: `0.21.1`.
- Инструменты разработки: `0.1.6`.

## Архитектура памяти

Memory 4.0 не заменяет Memory 3.0. Она является orchestration/policy-слоем поверх:

1. долговременной `personal/project` памяти;
2. Memory Intelligence 2.0;
3. `hybrid-semantic-v1`;
4. Experience Learning;
5. Memory 3.0: Working / Episodic / Knowledge / Graph / Temporal / Retention.

Основная БД остаётся локальной:

`data/sayuri-memory.db`

Отдельный внешний сервис памяти или вторая AI-модель не добавлены.

## Memory 4.0 State

Для каждой активной долговременной записи рассчитывается отдельное состояние:

- `source_key`;
- `source_trust`;
- `freshness_class`;
- `freshness_score`;
- `utility_score`;
- `tier = hot | warm | cold`;
- `sensitivity`;
- `cloud_allowed`;
- recall/useful/unhelpful counters;
- время последнего recall.

Это состояние влияет на retrieval, но не переписывает сам факт.

## Source Trust

Источник знания теперь имеет собственную оценку доверия.

Примеры базовой политики:

- explicit/manual user memory — высокий trust;
- подтверждённый Memory Intelligence — высокий trust;
- документ / DNA — высокий, но не абсолютный trust;
- OCR — ниже из-за риска распознавания;
- автоматический анализ разговора — ниже подтверждённого факта.

Trust может корректироваться только ограниченно подтверждённым feedback и может иметь ручной override из Личного кабинета.

Низкий trust не удаляет запись. Он снижает вес recall и отображается пользователю.

## Freshness Policy

Разным знаниям назначается различная скорость устаревания.

Примеры:

- версия/API/цена/текущий статус — volatile;
- обычный факт — medium;
- задача — medium, но быстрее факта;
- preference — stable;
- важное decision — durable.

Freshness не равна истине. Она показывает, насколько давно запись могла требовать повторной проверки.

## Hot / Warm / Cold Memory

Tier рассчитывается из:

- Memory 3 retention;
- importance;
- freshness;
- utility;
- реального use-count.

`hot` — приоритетный активный контекст.

`warm` — нормальная долговременная память.

`cold` — редко используемая/устаревающая память, которая остаётся доступной.

Автоматического физического удаления нет.

## Sensitive Memory Policy

Перед передачей retrieval-context в Cloud.ru Memory 4.0 классифицирует содержимое.

Секреты и чувствительные идентификаторы получают:

`cloud_allowed = false`

и исключаются из `for_cloud=True` recall.

В `0.1.45` local-only policy стала сквозной: перед Cloud.ru дополнительно фильтруются производные данные Memory 3.0, Experience Learning, Goal/Task/Failure/Question Memory. Связанная сущность с protected source memory также не проходит в AI-context.

Локальный пользовательский поиск при этом может находить такую запись и показывает badge `LOCAL ONLY`.

Это дополнительная защита поверх существующей границы API-ключей.

## Explainable Recall

Chat runtime и поиск Личного кабинета используют Memory 4.0 recall.

Каждая выбранная запись получает объяснение:

- semantic score;
- source trust;
- freshness;
- utility;
- tier;
- sensitivity;
- итоговый relevance;
- список причин выбора.

В интерфейсе это показывается как:

`Почему вспомнила: ...`

Каждый recall, реально использованный для AI-ответа, получает локальный `recall_id` и аудитируется без копирования полного разговора.

AI recall двухфазный: сначала формируется `prepared_recall` без side effects, затем выполняется Cloud.ru request. Только после успешного ответа выбранные memories получают `use_count`/`recall_count` и recall-audit. Ошибка/timeout провайдера не считается использованием памяти.

Поиск/просмотр в Личном кабинете работает в режиме `record_usage=false`: он показывает Explainable Recall, но не увеличивает `use_count`/`recall_count` и не создаёт обучающий audit event.

## Utility Learning

После ответа Sayuri связывает `response_id` с использованным `recall_id`.

Оценка:

- `Полезно`;
- `Не помогло`;

изменяет utility только тех воспоминаний, которые реально были использованы при этом ответе.

Повторная оценка того же ответа корректно пересматривает previous rating вместо накопления дублей.

Feedback также слегка обновляет эмпирическое доверие к источнику.

## Goal Memory

Добавлена структурированная таблица `memory_goals`.

Цель содержит:

- personal/project scope;
- title;
- description;
- priority;
- status;
- source;
- source memory;
- timestamps.

Статусы:

- active;
- paused;
- achieved;
- cancelled.

Цель связывается с Knowledge Graph.

## Task Memory

Добавлена таблица `memory_tasks`.

Task Memory хранит:

- связанную goal;
- status;
- priority;
- next action;
- blocked reason;
- безопасный UI-context;
- provenance.

Статусы:

- planned;
- in_progress;
- blocked;
- done;
- cancelled.

Это позволяет Sayuri хранить «где остановились» и конкретный следующий шаг отдельно от обычных заметок.

## Decision Memory

Подтверждённые записи `kind=decision` получают структурированную decision-card:

- statement;
- rationale, если явно указан;
- alternatives, если явно указаны;
- project version;
- temporal status;
- source memory ID.

Decision Memory не придумывает причину, если пользователь её не указал.

## Failure Memory

Подтверждённый failed Safe Action создаёт или усиливает failure pattern:

- strategy/tool;
- symptom;
- occurrences;
- status;
- cause/resolution/prevention, когда они известны;
- source reference.

Поздний успешный outcome того же strategy **не закрывает** failure автоматически. Он сохраняется только как наблюдение:

`failure → followed_by_success → action`

с низкой causal confidence и `correlation_only` evidence.

Failure переводится в `resolved` только после явного пользовательского подтверждения причины/исправления. Повтор ранее исправленной ошибки переоткрывает pattern. Повтор одинакового resolution идемпотентен.

## Question / Uncertainty Memory

Memory 4.0 умеет хранить отдельные открытые вопросы.

Противоречие Memory 3.0 автоматически создаёт Question Memory с обеими сторонами конфликта.

После пользовательского решения связанный вопрос закрывается.

Это не позволяет системе превращать неопределённость в подтверждённый факт.

## Entity Profiles

Поверх Knowledge Graph формируются read-only profiles для:

- person;
- project;
- document;
- vehicle;
- company.

Профиль показывает количество и примеры связей.

Entity Profile не создаёт новую «истину»: он является представлением уже существующего графа.

## Preference Drift

Личный кабинет показывает историю preference memory включая:

- активные предпочтения;
- архивированные предыдущие версии;
- confidence;
- source;
- `supersedes_id`.

Это даёт временную картину изменения предпочтений вместо простого удаления старого значения.

## Memory Audit

Добавлен локальный `memory_audit_log`.

Аудитируются, в частности:

- recall;
- feedback recall;
- создание/изменение goal/task;
- изменение Source Trust;
- открытие/закрытие вопросов;
- archive;
- integrity checks;
- snapshots;
- bootstrap.

Audit не должен содержать API-ключи или полную browser chat history.

## Snapshots

Локальные резервные снимки хранятся в:

`data/memory-snapshots/`

Создание выполняется штатным SQLite backup API.

Для каждого snapshot сохраняются:

- SHA-256;
- размер;
- reason;
- timestamp;
- filename.

Restore:

1. требует точное подтверждение `RESTORE MEMORY`;
2. проверяет SHA-256 выбранного snapshot;
3. автоматически создаёт pre-restore safety snapshot;
4. восстанавливает БД через SQLite backup;
5. повторно инициализирует схемы;
6. запускает integrity check.

Автоматического restore нет.

## Memory Integrity

Проверяются:

- `PRAGMA integrity_check`;
- orphan graph edges;
- task → missing goal;
- confirmed knowledge → missing source memory;
- response → missing recall audit.

Dashboard integrity-check read-only. Явная ручная проверка записывает audit event.

## AI Context

DeepSeek-V4-Flash получает только контролируемые недоверенные blocks:

1. Memory 4.0 filtered personal/project recall;
2. Experience Learning helpful/avoid;
3. Memory 3.0 working/knowledge/episodes/conflicts;
4. Memory 4.0 goals/tasks/failures/questions;
5. UI-context.

Перед отправкой все memory-derived blocks проходят Memory 4.0 privacy firewall. Protected/local-only данные не должны попадать ни через прямой recall, ни через Memory 3.0, Experience, Goals, Tasks, Failures или Questions.

Цели и задачи не выдаются модели как выполненные только потому, что они присутствуют в памяти.

## Личный кабинет

Memory 4.0 control center показывает:

- Hot / Warm / Cold;
- protected/local-only count;
- Goal Memory;
- Task Memory;
- blocked tasks;
- Failure & Causal Memory;
- Question Memory;
- Source Trust;
- Explainable Recall;
- Decision Memory;
- Entity Profiles;
- Preference Drift;
- Memory Audit;
- Integrity;
- Snapshots.

Доступно ручное создание goal/task, изменение Source Trust, закрытие вопросов, integrity check, snapshot и защищённый restore.

## API

Добавлены:

- `GET /api/sayuri/memory/v4`;
- `POST /api/sayuri/memory/v4/maintenance`;
- `POST /api/sayuri/memory/v4/goals`;
- `POST /api/sayuri/memory/v4/goals/{id}/update`;
- `POST /api/sayuri/memory/v4/tasks`;
- `POST /api/sayuri/memory/v4/tasks/{id}/update`;
- `POST /api/sayuri/memory/v4/sources/trust`;
- `POST /api/sayuri/memory/v4/failures/{id}/resolve`;
- `POST /api/sayuri/memory/v4/questions/{id}/resolve`;
- `POST /api/sayuri/memory/v4/integrity`;
- `POST /api/sayuri/memory/v4/snapshots`;
- `POST /api/sayuri/memory/v4/snapshots/{id}/restore`.

Существующие v1/v2/v3 memory API не удалены.

## Тесты Memory 4.0

Проверяются:

- secret/sensitive local-only policy;
- local recall vs Cloud-safe recall;
- explainable recall;
- feedback → utility/source evidence;
- goal/task lifecycle;
- goal/task graph linking;
- automatic task/goal promotion;
- Decision Memory;
- Failure Memory: correlation-only success observation + explicit resolution + reopen lifecycle;
- conflict → Question Memory → close;
- freshness decay;
- Source Trust override;
- snapshot + SHA-256 + restore;
- обязательный restore confirmation;
- pre-restore safety copy;
- integrity;
- HTTP API;
- Web contract;
- runtime injection в DeepSeek-context без реального сетевого запроса;
- protected memory не проходит через соседние context layers;
- local cabinet recall не изменяет utility/use counters;
- failed Cloud request не commit-ит recall и не обучает memory usage.

## Инварианты

- единственный внешний AI-провайдер: Cloud.ru;
- единственная LLM: `deepseek-ai/DeepSeek-V4-Flash`;
- Memory 4.0 не добавляет embedding API или вторую LLM;
- personal/project не смешиваются;
- protected memory не передаётся в Cloud context;
- trust/freshness/utility меняют retrieval-вес, но не переписывают факт;
- неизвестное хранится как question, а не knowledge;
- failure не считается причинностью без evidence;
- goals/tasks не расширяют permissions;
- Safe Actions остаются confirmation-gated;
- restore всегда требует явного точного подтверждения.

## Релизный критерий

Рабочая ветка может иметь красный `check --each-commit` из-за промежуточных GitHub API-коммитов.

Канонический `0.1.45` считается готовым только после:

1. сборки одного атомарного commit поверх `main 0.1.44`;
2. полного зелёного workflow Versions на свежей validation-ветке;
3. merge через PR;
4. полного зелёного workflow на финальном `main`.

## Следующий этап после Memory 4.0

После hardening `0.1.45` следующий рациональный слой — **Reasoning Planner + Result Verifier**.

Planner должен использовать Goal/Task/Failure/Decision Memory, а Verifier — отдельно проверять результат против исходной задачи, ограничений и доказательств.
