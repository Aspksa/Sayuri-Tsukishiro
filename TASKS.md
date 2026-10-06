# Задачи

Актуальная контрольная точка — [PROJECT_STATE.md](PROJECT_STATE.md).

## Завершено

- DOC-001 — базовая передача работы.
- DOC-002 — правила продолжения работы.
- VER-001 — версии проекта и модулей.
- APP-001 — первая рабочая версия.
- FIX-001 — Windows HTTP disconnect и русификация.
- FIX-002 — кодировка Windows launcher.
- CORE-002 — состояние, настройки и границы Агентного ядра.
- DISK-001 — первый рабочий модуль «Диск Sayuri».
- DISK-002 — профессиональный файловый менеджер.
- DISK-002.1 — центральный просмотр и свойства.
- DISK-002.2 — drag-and-drop, плитки/список и широкий интерфейс.
- DISK-003 — базовая «ДНК документа».
- DISK-004 — Evidence Engine, нормализация, quality gate, версии и междокументная сверка.
- DISK-005 — ДНК 0.5 Structural Intelligence & Safety.
- DISK-006 — DNA Evolution Core.
- DISK-007 — Spatial Intelligence & OCR 0.7.
- UI-001 — единая визуальная система Sayuri 0.12.

## REM-001 — удаление ненужного Android-контура

- Статус: `done`.
- Источник: прямой запрос пользователя полностью убрать эту функциональность из проекта.
- Удалено:
  - отдельный backend-модуль Android;
  - приложение-компаньон;
  - device/media/control API;
  - ADB/scrcpy runtime и bootstrap;
  - весь связанный Web UI;
  - специализированные тесты и Android workflow;
  - регистрации удалённых модулей.
- Версии результата:
  - проект `0.1.36`;
  - Ядро Саюри `0.1.28`;
  - Web UI `0.13.0`;
  - dev-tools `0.1.6`.
- Критерий закрытия: полный workflow `Versions` на итоговом `main` завершён успешно.

## AI-003 — Подключение ИИ-провайдера

- Статус: `implemented stage 2`.
- Реализовано:
  - Cloud.ru Foundation Models;
  - только `deepseek-ai/DeepSeek-V4-Flash`;
  - локальное безопасное хранение API-ключа;
  - проверка доступности модели;
  - реальный `/api/sayuri/chat`;
  - интерфейсный контекст текущего раздела;
  - история чата локально в браузере.
- Stage 2 дополнительно:
  - долговременная раздельная память `personal/project`;
  - релевантный memory context для чата;
  - явные команды «запомни лично» / «запомни в проект»;
  - ручное управление памятью из Личного кабинета.
- Пока не входит:
  - автоматические инструменты;
  - отправка содержимого документа без явного действия;
  - neural/vector embeddings.

## UX-002 — глобальная Sayuri и Личный кабинет

- Статус: `implemented`.
- Глобальный плавающий аватар доступен на всех страницах.
- Левый клик открывает чат.
- Правый клик открывает быстрые контекстные действия.
- Добавлен нижний пункт «Личный кабинет Sayuri».
- В Личном кабинете находятся Cloud.ru, API-ключ, состояние AI и настройки присутствия.
- Используется пользовательский образ Sayuri как канонический аватар интерфейса.


## MEM-001 — долговременная память Sayuri

- Статус: `implemented`.
- Хранилище: `data/sayuri-memory.db`.
- Жёсткие области: `personal` и `project`.
- Типы: факт, предпочтение, решение, задача, заметка.
- Есть dedup, важность 1–5, источник, use-count, поиск и удаление.
- Обычный чат автоматически не сохраняется.
- Явные команды памяти сохраняются детерминированно.
- Релевантные воспоминания передаются AI раздельно по областям.

## UX-003 — студия аватаров Sayuri

- Статус: `implemented`.
- В Личном кабинете можно загрузить отдельные локальные варианты:
  - orb 192×192;
  - chat 256×256;
  - profile 512×512;
  - hero 1024×1024.
- Поддержка: PNG/JPEG/WebP, до 8 МБ.
- Пользовательские аватары не попадают в GitHub.
- Для каждого слота можно отдельно вернуть стандартный образ.

## ACT-001 — безопасные действия Sayuri

- Статус: `implemented`.
- Добавлен локальный Action Broker.
- Любое изменяющее действие проходит состояния `plan -> pending -> confirm -> execute`.
- Без подтверждения пользователя инструмент не выполняется.
- Allowlist stage 1:
  - создание папки;
  - добавить/убрать текущий объект из избранного;
  - переместить текущий объект в корзину;
  - переместить текущий объект в существующую папку;
  - сохранить подтверждённое решение в проектную память.
- Есть TTL 10 минут, SHA-256 payload, replay protection и журнал состояний.
- В чате есть карточки «Подтвердить / Отменить».
- В Личном кабинете есть список разрешённых инструментов и история действий.

## DNA-001 — загрузка файла автоматически строит ДНК

- Статус: `implemented`.
- После успешной загрузки поддерживаемого документа Web UI автоматически запускает `POST /api/disk/files/{id}/dna/analyze`.
- Файл появляется в Диске до завершения ДНК.
- Ошибка анализа не удаляет оригинал и не останавливает остальные загрузки.
- В очереди загрузки отображается отдельный статус ДНК.
- Во вкладке ДНК добавлены видимое состояние ошибки и кнопка повторного анализа.
- Исправлена диагностика PDFium readiness в Spatial DNA.

## MEM-002 — Memory Intelligence 2.0

- Статус: `implemented`.
- Sayuri автоматически анализирует новые сообщения и выделяет кандидаты памяти.
- Кандидаты разделяются на `personal/project`.
- Распознаются предпочтения, решения, правила, задачи и технические факты.
- Дубли не создают вторую запись.
- Возможные противоречия требуют проверки.
- Кандидат сохраняет confidence, причину и контекст открытого экрана/документа.
- В Личном кабинете доступны очередь кандидатов и настройки автоматизации.
- По умолчанию автосохранение кандидатов выключено.
- Опциональное автосохранение разрешено только для высокоуверенных проектных фактов.

## AI-004 — Semantic Memory + Experience Learning

- Статус: `implemented`.
- Добавлен локальный `hybrid-semantic-v1` без второй облачной модели.
- Поиск памяти учитывает ключевые слова, формы слов, концепты, char n-grams, importance и confidence.
- Personal/project граница сохраняется.
- Добавлена отдельная локальная база опыта `data/sayuri-experience.db`.
- В опыт попадают финальные исходы действий, review памяти и явная оценка ответов.
- Опыт используется для мягкой калибровки confidence Memory Intelligence после накопления достаточного числа оценок.
- Релевантный положительный/отрицательный опыт передаётся Sayuri как отдельный справочный контекст.
- В чате добавлены «Полезно / Не помогло».
- В Личном кабинете добавлена статистика стратегий.
- Критерий готовности: атомарный v0.1.42 проходит полный workflow Versions.

## MEM-003 — Semantic Memory

- Статус: `implemented`.
- Engine: `hybrid-semantic-v1`.
- Полностью локальный retrieval без второй облачной модели.
- Использует token overlap, лёгкую морфологию, локальные concepts и character n-grams.
- Сохраняет границу `personal/project`.
- Поиск в Личном кабинете использует semantic relevance.
- Chat memory context формируется через Semantic Memory.
- Neural embeddings/vector DB намеренно не добавлены на этом этапе.

## EXP-001 — Experience Learning

- Статус: `implemented`.
- Хранилище: `data/sayuri-experience.db`.
- Записываются подтверждённые исходы Safe Actions, review Memory Intelligence и явная оценка AI-ответов.
- Обратная связь ответа idempotent: повторная оценка заменяет outcome той же записи.
- Опыт калибрует confidence Memory Intelligence в ограниченном диапазоне ±8%.
- Релевантный положительный/отрицательный опыт передаётся в чат отдельным недоверенным context block.
- В Личном кабинете отображаются статистика и success rate стратегий.

## MEM-004 — Memory 3.0

- Статус: `implemented`.
- Working Memory с TTL 24 часа.
- Episodic Memory для значимых событий вместо копирования всего чата.
- Knowledge Memory с confidence, source IDs и temporal validity.
- Knowledge Graph с person/project/document/memory/knowledge/decision/vehicle nodes.
- Temporal Memory timeline.
- Memory Consolidation без удаления источников.
- Forgetting/Retention Engine без физического удаления.
- Contradiction Resolver с `prefer_new/prefer_old/keep_both`.
- Автоматический bootstrap и opportunistic maintenance каждые 6 часов.
- Memory 3.0 context подключён к DeepSeek-V4-Flash как отдельный недоверенный блок.
- В Личном кабинете добавлен полноценный Memory 3.0 dashboard.

## MEM-005 — Memory 4.0

- Статус: `implemented`.
- Добавлен orchestration/policy layer `agent/memory_v4.py` поверх Memory 3.0.
- Для каждой memory рассчитываются Source Trust, Freshness, Utility, sensitivity и tier `hot/warm/cold`.
- Secret/sensitive memory остаётся локальной и исключается из Cloud recall.
- Добавлен Explainable Recall с локальным audit и feedback только по реально использованным memories.
- Добавлены Goal Memory и Task Memory с priority/status/next-action/blocker.
- Добавлена Decision Memory с rationale/alternatives/project version без выдумывания отсутствующей причины.
- Добавлены Failure Memory и evidence-bearing Causal Memory.
- Добавлена Question/Uncertainty Memory; memory conflict открывает вопрос и закрывается после решения пользователя.
- Добавлены Entity Profiles и Preference Drift поверх существующего Knowledge Graph/temporal history.
- Добавлен Memory Audit.
- Добавлены SQLite snapshots с SHA-256, pre-restore safety snapshot и точным подтверждением `RESTORE MEMORY`.
- Добавлен integrity check для SQLite, graph, tasks/goals, knowledge provenance и recall links.
- Личный кабинет получил Memory 4.0 control center.
- Добавлены runtime/API/Web/unit tests.
- Релиз завершается только после зелёного атомарного workflow `0.1.44` и финального CI на `main`.

## MEM-006 — Memory 4.0 Hardening

- Статус: `implemented`; релиз считается проверенным только после зелёного atomic/main CI.
- Локальный поиск/просмотр больше не считается обучающим recall и не меняет utility/use counters.
- AI recall переведён на двухфазную схему prepare → successful Cloud response → commit; сбой провайдера не обучает память.
- Privacy firewall `cloud_allowed=false` распространён на все memory-derived Cloud-context слои: Memory 3.0, Experience, Goals, Tasks, Failures и Questions.
- Protected memory остаётся доступной локально, но не может попасть в Cloud.ru обходным путём через производный контекст.
- Последующий success после failure хранится как correlation-only `followed_by_success`, а не как доказанное исправление.
- Failure Memory требует явного подтверждения resolution пользователем.
- Повтор ранее исправленной ошибки переоткрывает failure pattern.
- Повтор одинакового подтверждения resolution идемпотентен.
- Добавлен API/UI для подтверждённого закрытия Failure Memory.
- Добавлены регрессионные тесты privacy firewall, read-only recall, causal semantics, повторного failure и HTTP/Web contract.
- Приёмка: атомарный release commit `0.1.45` от текущего `main` обязан пройти полный workflow Versions и финальный CI на `main`.

## MEM-007 — Memory 4.1 Quality Gate

- Статус: `implemented; final atomic CI pending`.
- База: `0.1.45 Memory 4.0 Hardening`.
- Generic feedback «Полезно / Не помогло» изменяет только retrieval utility реально использованной памяти и больше не меняет factual Source Trust.
- Добавлен локальный instruction-risk classifier. High-risk memory остаётся доступной локально, но получает quarantine/local-only и не попадает в Cloud.ru.
- Instruction-risk firewall применяется также к Memory 3.0, Experience и другим memory-derived context blocks.
- Recall диверсифицируется: почти одинаковые записи штрафуются, чтобы не заполнять контекст дубликатами.
- Важные volatile memories с низкой freshness и важные записи с низким source trust автоматически создают idempotent Question Memory на перепроверку.
- Cloud memory context ограничен отдельными char budgets; длинные записи безопасно сокращаются.
- Recall audit/use-count/feedback привязываются только к memory IDs, которые реально вошли в окончательный Cloud-context после budget selection.
- Обслуживание переиспользует уже рассчитанный `memory_v4_state`, не пересчитывая вторично до 5000 записей.
- Quality maintenance запускается opportunistically не чаще одного раза в 24 часа; не создаёт snapshot и не обращается к Cloud.ru.
- Личный кабинет показывает Quarantine и количество записей к перепроверке.
- Добавлены regression tests для quarantine, adjacent-layer firewall, diversified recall, stale review queue и context budget attribution.
- Приёмка: один атомарный release commit `0.1.46` от `main 0.1.45`, полный зелёный workflow Versions, merge через PR и зелёный финальный CI на `main`.


## AI-005 — Reasoning Planner + Result Verifier

- Статус: `implemented`; релиз считается проверенным только после зелёного atomic/main CI.
- Версия проекта: `0.1.47`.
- Добавлен adaptive complexity gate: простой чат не получает лишние модельные вызовы.
- Для сложных задач Planner формирует structured task-plan без хранения chain-of-thought.
- План включает goal, steps, constraints, evidence_needed, done_when и risk_level.
- Planner получает только Cloud-safe/quality-gated контекст Memory 4.1, Memory 3.0, Experience и UI.
- Основной ответ получает structured plan как контрольный data block.
- Result Verifier отдельным вызовом той же `deepseek-ai/DeepSeek-V4-Flash` проверяет цель, ограничения и evidence.
- Verifier может вернуть полную revised_answer в том же вызове; отдельная вторая модель не добавляется.
- Ошибка Planner использует локальный fallback-plan; ошибка Verifier помечается `unavailable` и не стирает основной ответ.
- Recall usage/feedback остаются связаны только с фактически отправленной Memory 4.1.
- Web chat показывает компактную раскрываемую сводку плана и результата проверки.
- Chain-of-thought не сохраняется и не показывается.
- Приёмка: один атомарный commit от `main 0.1.46`, полный workflow Versions, merge через PR и зелёный финальный main CI.

## AI-006 — Evidence-aware Tool Planner

- Статус: `released`; `main` commit `bcf047437f1274a412612563459dcb6406b89e88`, workflow Versions #473 — success.
- Версия проекта: `0.1.48`.
- Structured plan расширен `tool_intents` с привязкой к шагам.
- LLM может только предложить intent; deterministic Evidence Tool Planner решает, разрешён ли инструмент.
- Read-only allowlist выполняется локально без подтверждения; неизвестные инструменты отклоняются.
- Любое изменяющее действие получает `requires_action_broker`; модель не может передать исполняемый mutation payload.
- Existing `SayuriActionBroker` остаётся единственным путём plan -> pending -> confirm -> execute.
- Execution receipts хранят tool, args, status, timestamps, duration, evidence refs, output SHA-256 и sanitized preview.
- Есть duplicate-call suppression и лимит read-only вызовов.
- Cloud evidence bounded; секретные поля удаляются.
- `memory.search` проходит Memory 4.1 `for_cloud=True`, а usage attribution остаётся post-success.
- Result Verifier получает receipts как фактическое evidence.
- Web chat показывает цепочку «План -> Инструменты -> Доказательства -> Проверка» без изменения меню.
- Приёмка: один атомарный commit от `main 0.1.47`, полный workflow Versions, merge через PR и зелёный финальный main CI.



## AI-007 — Background Evidence Automation

- Статус: `implemented; release CI pending`.
- Версия проекта: `0.1.49`.
- Evidence Tool Planner остаётся внутренним контуром мозга, а не отдельным пользовательским разделом.
- По `goal` и `evidence_needed` deterministic policy может сама подобрать безопасные read-only проверки, даже если Planner не вернул явный intent.
- Поддерживаемый автоподбор: релевантная Memory 4.1, состояние системы, integrity памяти, текущий документ и статистика Experience.
- Read-only вызовы ограничены allowlist, duplicate suppression и лимитом 4 вызова на planned request.
- Mutation intent никогда не исполняется автоматически и остаётся за существующим `SayuriActionBroker` с явным подтверждением.
- Полные execution receipts остаются локальными для Verifier/диагностики; обычный chat API получает только агрегированную automation-сводку.
- Из Личного кабинета убирается каталог инструментов; история подтверждённых действий остаётся.
- Web reasoning summary не показывает технические receipt rows; при наличии evidence показывает только `автопроверка N`.
- Меню проекта не изменяется.
- Приёмка: один атомарный commit от подтверждённого `main 0.1.48`, полный workflow Versions, merge через PR и зелёный финальный main CI.


## UI-004 — Sayuri Presence UX Cleanup

- Статус: `implemented in target 0.1.50`; релиз считается проверенным только после зелёного PR/main CI.
- Версия проекта: `0.1.50`.
- Удалить только кнопку Личного кабинета из левого sidebar; остальные пункты меню не менять.
- Сохранить вход в кабинет через правый клик по плавающему аватару.
- Переписать avatar/chat drag на Pointer Events + requestAnimationFrame + translate3d с click-vs-drag threshold.
- Не писать позицию в localStorage на каждом движении; сохранять после pointerup.
- Добавить resizable floating chat с локальным сохранением размера и кнопкой сброса.
- Перестроить chat surface в ChatGPT-подобную компоновку без изменения backend chat pipeline.
- Разделить Личный кабинет на смысловые вкладки без удаления существующей функциональности.
- Добавить regression contract для avatar-only entry, tabs, smooth drag и resize.
- Приёмка: один атомарный commit от `main 0.1.49`, полный workflow Versions, PR merge и зелёный финальный main CI.


## UI-005 — UI System & Chat Polish

- Статус: `implemented in target 0.1.51`; выпуск считается проверенным только после зелёного branch/PR/main CI.
- Версия проекта: `0.1.51`.
- Сохранить текущую структуру левого меню.
- Добавить UI 0.27 design-system layer без новой зависимости и без переписывания backend.
- Добавить fullscreen/maximize существующего floating chat.
- Добавить Ctrl/⌘+K command palette без постоянной визуальной панели.
- Упростить постоянный chat status и оставить технические детали в reasoning summary.
- Добавить copy action для сообщений и transient toast feedback.
- Усилить focus-visible, responsive behavior, scrollbars и prefers-reduced-motion.
- Добавить Web contract regressions для всех новых UX-инвариантов.
- Приёмка: один атомарный commit от подтверждённого `main 0.1.50`, Versions workflow success, PR merge и зелёный финальный main CI.


## UI-006 — Rich Answer UX & Lazy Diagnostics

- Статус: `implemented in target 0.1.52`; релиз считается проверенным только после зелёного branch/PR/main CI.
- Версия проекта: `0.1.52`.
- Добавить safe rich-text renderer для chat без `innerHTML` и сторонних Markdown dependencies.
- Поддержать headings, lists, blockquotes, inline/fenced code, tables, safe links и copy code.
- Вывести компактный пользовательский Evidence Summary без tool/receipt IDs.
- Сделать evidence текущего документа кликабельным через существующий Disk viewer.
- Не раскрывать внутренние memory IDs в evidence UI.
- Перевести Memory 3.0, Memory 4.1 и Experience на lazy-load по активной memory-вкладке.
- Добавить skeleton/loading state и `aria-busy` для ленивых панелей.
- После mutations обновлять тяжёлые панели только если они уже были открыты.
- Добавить regressions на XSS boundary, evidence privacy и lazy loading.
- Приёмка: один атомарный commit от подтверждённого `main 0.1.51`, зелёный Versions workflow, PR merge и зелёный финальный main CI.


## AI-008 — Spatial Evidence Citations

- Статус: `implemented in target 0.1.53`; релиз считается проверенным только после зелёного branch/PR/main CI.
- База: `main 0.1.52`, commit `ab10ff8d0388c1f26c7dd7b635635298e9b129ba`, Versions #493 success.
- Добавить read-only `document.evidence_search` в Evidence Tool Planner.
- Искать evidence только по cached DNA текущего файла; автоматический reanalysis/OCR не запускать.
- Разрешать точные citations только для `exact_from_document_engine` locator.
- Не передавать bbox в Cloud.ru; DeepSeek получает bounded D1..D6 facts с page/line.
- Runtime обязан удалить неизвестные D-citations перед выдачей ответа.
- Evidence Focus endpoint принимает только file_id + fact_id и сам разрешает bbox из DNA.
- Web chat отображает inline D-citation и компактный источник; клик открывает точную подсветку в существующем viewer.
- Меню проекта не менять.
- Добавить regression tests tool policy, cached evidence, fact-id focus, privacy projection, citation firewall и Web/API contracts.
- Приёмка: один атомарный commit от подтверждённого `main 0.1.52`, branch CI, PR CI, merge и зелёный финальный main workflow.


## UI-007 — Visual Refinement & Workspace UX

- Статус: `implemented in target 0.1.54`; релиз считается проверенным только после зелёного branch/PR/main CI.
- База: `main 0.1.53`, commit `d232df512560155b31c8b6cf642229196efc38af`, Versions #499 success.
- Не менять структуру левого меню.
- Сделать maximized chat полноценным workspace-состоянием существующего окна.
- Добавить мягкие avatar magnet zones после drag без forced snap из центра.
- Добавить реальные presence-state для аватара.
- Добавить локальный compact-density mode без уменьшения основного текста.
- Унифицировать Disk/viewer/loading/empty/error через общий UI-state и aria-busy.
- Улучшить пустой chat state и переход chat → Spatial Evidence viewer.
- Добавить локальные recent commands в Ctrl/⌘+K без новой панели.
- Сохранить Memory, Agent, Action Broker и Spatial Evidence backend без изменения permissions.
- Добавить Web contract regressions на новые UX-инварианты и sidebar regression.
- Приёмка: один атомарный commit от `main 0.1.53`, branch CI, PR CI, merge и зелёный финальный main workflow.


## AI-009 / UI-008 — Goal Continuity & Workspace Quality

- Статус: `implemented in target 0.1.55`; релиз считается проверенным после зелёного branch/PR/main CI.
- База: `main 0.1.54`, commit `dd4907a5ba9626c7c171d064de1918e4426309a5`, Versions #37403591304 success.
- Memory 4.1:
  - добавить детерминированный read-only continuity snapshot;
  - ранжировать active goals и planned/in_progress/blocked tasks;
  - не отправлять в Cloud локально запрещённые goal/task источники;
  - передавать selected task/goal, next_action и blocker в Planner.
- Reasoning:
  - Planner 0.4 распознаёт continuation intent только при реальном сохранённом контексте;
  - fallback продолжает ближайший шаг, но не меняет статусы Goal/Task Memory;
  - текущий явный запрос пользователя имеет приоритет над старой задачей.
- Tools:
  - `memory.continuity` — только read-only;
  - mutation tools остаются только через confirmation-gated Action Broker.
- Workspace:
  - focus return после закрытия chat/palette;
  - focus trap в modal workspace/palette;
  - `aria-modal` только для maximized chat;
  - скрытый avatar исключается из tab-order;
  - responsive contract для узких/низких viewport.
- Версии результата:
  - проект `0.1.55`;
  - Ядро/App `0.1.47`;
  - Agent Core `0.12.0`;
  - Web UI `0.31.0`.
- Приёмка: unit tests, JS syntax, preflight, version each-commit, Windows launcher checks, PR merge и зелёный финальный workflow на `main`.


## AI-010 — Task Lifecycle & Checkpoints

- Статус: `implemented in target 0.1.56`; релиз считается проверенным после зелёного branch/PR/main CI.
- База: `main 0.1.55`, commit `dc1ca53926d32498da084ce34757eec8c8ee21f5`, Versions #37407648237 success.
- Добавить persistent `memory_task_checkpoints` в существующую SQLite Memory 4.x.
- Link action → task:
  - только внутренний Action Broker context;
  - только deterministic query overlap;
  - blocked task автоматически не привязывать к mutation lifecycle.
- Confirmed checkpoint:
  - источник — только Action Broker `completed`;
  - хранить sequence number, before/after task state и SHA-256 результата;
  - не копировать полный action result в cloud-facing checkpoint projection;
  - повтор того же action_id идемпотентен.
- Evidence-based advancement:
  - planned/in_progress task может получить deterministic follow-up;
  - task переводится максимум в `in_progress`;
  - `done` никогда не выставляется автоматически;
  - stale task state запрещает перезапись нового `next_action`;
  - blocked/done/cancelled status сохраняется.
- Restart restoration:
  - Goal Continuity возвращает latest checkpoint выбранной задачи;
  - следующий процесс Sayuri восстанавливает continuation из той же SQLite без фоновой mutation.
- Reasoning Planner 0.5 трактует checkpoint как доказательство конкретного шага, не как завершение всей задачи.
- Версии: проект `0.1.56`, App `0.1.48`, Agent `0.13.0`.
- Приёмка: Python tests, JS syntax, preflight, version each-commit, Windows launcher, PR merge и финальный зелёный `main` workflow.


## AI-011 — Cognitive Project Brain / Global Multi-Module Architecture

- Статус: `implemented in target 0.2.0`; релиз считается принятым только после зелёного branch/PR/main CI.
- База: `main 0.1.56`, commit `35bb9e6d5ab9e5b51075c28461b8e862f70a74e7`.
- Создать единый Cognitive Project Brain поверх Memory 4.x, без второго независимого источника истины для task status.
- Multi-project / multi-module:
  - persistent project/module registry;
  - bootstrap из `MODULES.json`; schema 1-compatible metadata поддерживает `project_key`, capabilities и depends_on metadata;
  - task scope через `project_key/module_key` context;
  - неизвестный будущий проект/модуль может регистрироваться локальным кодом без изменения Planner.
- Task Graph:
  - `requires / blocks / unlocks / follows`;
  - scheduler исключает dependency-blocked task;
  - graph сохраняется после restart.
- Completion Criteria:
  - checkpoint_count;
  - confirmed tool_completed;
  - dependency_done;
  - manual_confirmation;
  - только assessment; `done` автоматически не выставляется.
- Cognitive Scheduler:
  - priority/status/query overlap;
  - project/module affinity;
  - dependency blockers;
  - uncertainty penalty;
  - attention state;
  - bounded top candidates.
- Uncertainty & confidence:
  - persistent uncertainty ledger;
  - severity + evidence_needed;
  - explicit metacognitive `uncertain`.
- Strategy Memory:
  - Action Broker completed/failed outcomes;
  - success/failure counters;
  - Bayesian-smoothed confidence;
  - project/module scope.
- Replanning:
  - failed confirmed action → proposed plan revision;
  - proposal не меняет `next_action` автоматически;
  - Planner получает `replan_required` как read-only signal.
- Self-Evaluation / Metacognition:
  - project/module progress metrics;
  - blockers, completion-ready, uncertainties;
  - states actionable/blocked/uncertain/replan_required/criteria_missing/ready_for_completion_confirmation.
- Long Horizon:
  - portfolio/graph/criteria/strategy/replan persistence в `sayuri-memory.db`;
  - restart restoration без background mutation worker.
- Security:
  - Cognitive tools только read-only для LLM;
  - real mutations только Action Broker или explicit trusted local code;
  - blocked task не получает lifecycle linkage;
  - completion confirmation остаётся человеческой.
- Версии: Project `0.2.0`, App `0.1.49`, Agent `0.14.0`, Reasoning `1.0`, Cognitive Brain `1.0`, Tool Planner `0.4`.


## AI-012 — Cognitive Brain Hardening 1.1

- Статус: `implemented in target 0.2.1`; релиз принимается только после зелёного branch/PR/main CI.
- База: `main 0.2.0`, commit `8cc0df75a01924cbaf91001387cdadfee817774f`, Versions #37410683454 success.
- Цель: укрепить Cognitive Project Brain перед подключением большого числа прикладных модулей.
- Scope preservation:
  - `sync_tasks()` регистрирует только новые task scopes;
  - существующие attention/confidence/criteria не перезаписываются derived sync.
- Context contract:
  - единый `project_key/module_key`;
  - UI aliases для существующих разделов;
  - новый модуль не создаёт собственный Planner/Scheduler.
- Task Graph safety:
  - reject self/cycle dependencies;
  - reject direct cross-project task edges;
  - only confirmed edges block scheduler.
- Completion safety:
  - учитывать только `applied` checkpoints;
  - unresolved dependencies => `blocked_by_dependencies`;
  - explicit `done` блокируется при невыполненных configured criteria;
  - criteria никогда не закрывают task автоматически.
- Replanning/uncertainty:
  - failed action => proposed replan + uncertainty;
  - apply replan требует `APPLY_REPLAN`;
  - stale next_action запрещает применение старого proposal;
  - uncertainty разрешается отдельным explicit local action.
- Causal evidence:
  - хранить только conservative lineage `confirmed action -> checkpoint/replan/uncertainty`;
  - не выводить свободную причинность из текста LLM.
- Multi-module isolation:
  - strategies и uncertainty/self-evaluation фильтруются по module scope;
  - Cloud projection не содержит local path/manifest metadata.
- Public/local API:
  - scoped read-only `GET /api/sayuri/cognition`;
  - explicit local POST API для project/module/dependency/criteria/uncertainty/replan;
  - mutation API не добавляется в LLM tool catalog.
- Versions: project `0.2.1`, App/Core `0.1.50`, Agent Core `0.14.1`, Cognitive Brain `1.1`.
- Acceptance: full Python suite, JS syntax, app preflight, version each-commit, Windows launcher, PR CI, squash merge и зелёный final `main` workflow.


## AI-013 — Portfolio Scale & Integrity

- Статус: `implemented in target 0.2.3`; приёмка только после branch/PR/main CI.
- База: `main 0.2.1`, commit `bf9ffc499fbfa5b472c526f79f0e18166d6c7ce5`, Versions #37412163229 success.
- Цель: масштабировать уже существующий Cognitive Brain, не добавляя новый cognitive layer.
- Portfolio snapshot:
  - один bounded read snapshot для scheduler;
  - batch task scopes/projects/modules/confirmed edges/open uncertainty/applied checkpoint counters;
  - self-evaluation переиспользует snapshot;
  - top Cloud candidates остаются ограничены 8.
- Registry:
  - repeat module registration сохраняет title;
  - новые metadata merge-ятся с существующими;
  - sync получает known scopes пакетно и не меняет managed state.
- Integrity:
  - read-only `graph_integrity()`;
  - диагностировать legacy missing task / cross-project / cycle;
  - не чинить persisted graph молча.
- Uncertainty:
  - high severity => evidence-first recommendation.
- Cloud privacy:
  - project/module без DB ids/path/metadata;
  - strategy без local id/project_id/module_id/updated_at;
  - causal trace без source_id/effect_id/evidence_ref;
  - latest replan без internal id/task_id/revision/evidence_ref.
- Tool policy:
  - `cognition.next` auto-check только при специфическом cognitive intent;
  - generic «проект/модуль» недостаточно.
- Security:
  - LLM cognition только read-only;
  - explicit local cognition mutation API из 0.2.1 сохраняется, но не входит в LLM tool catalog;
  - real actions по-прежнему Action Broker confirmation-gated.
- Версии: Project `0.2.3`, App `0.1.52`, Agent `0.14.2`, Cognitive Brain `1.2`, Tool Planner `0.4.1`.
- Первый branch candidate `0.2.2` остановлен core test gate: старый reasoning regression ожидал 2 read-only checks, хотя новый narrow-trigger policy корректно дал 1. Runtime не откатывать; исправить тест-контракт в `0.2.3`.
- Приёмка: полный Python suite, JS syntax, preflight, version each-commit, Windows launcher, PR CI и final green main CI.

## AI-014 — Portfolio Milestones & Cross-Project Coordination

- Статус: `implemented in target 0.2.5`; candidate 0.2.4 не принят из-за import-time SyntaxError, приёмка только после branch/PR/main CI.
- База: `main 0.2.3`, commit `a609762d1f82763110d9b0a6fc88d3c1abbf389a`, Versions #37415897573 success.
- Цель: безопасно координировать несколько самостоятельных проектов без direct cross-project task edges и без нового автономного cognitive layer.
- Milestones:
  - persistent project milestone registry;
  - optional module scope;
  - required/optional task links;
  - cross-project task link запрещён;
  - required tasks done => `ready_for_confirmation`;
  - `done` только после `COMPLETE_MILESTONE`.
- External blockers:
  - project/module/task scope;
  - optional source project/source milestone;
  - source milestone `done` => derived effective resolution;
  - explicit resolution сохраняется отдельным local mutation.
- Portfolio safety:
  - new effective-open project dependency cycle отклоняется;
  - исторический blocker на уже `done` milestone не создаёт ложный cycle;
  - legacy portfolio cycle виден в read-only integrity diagnostics;
  - direct cross-project task graph остаётся запрещён.
- Scheduler:
  - milestones/external blockers входят в batch snapshot;
  - explicit `project_key` является hard boundary;
  - active milestone priority учитывается в ranking;
  - task dependency и external blocker считаются раздельно;
  - blocked target не считается actionable.
- Cloud:
  - не отправлять task/milestone/blocker/project DB IDs;
  - отправлять только bounded semantic summary.
- Reasoning Planner 1.1:
  - milestones/external blockers трактуются как read-only constraints;
  - не закрывать milestone и не снимать blocker по текстовой гипотезе.
- Evidence Tool Planner 0.4.2:
  - узкие triggers для milestone/external blocker/cross-project intent;
  - generic «проект/модуль» не запускает лишний cognition check.
- API:
  - read-only milestones/external-blockers endpoints;
  - explicit local create/link/complete/resolve endpoints;
  - mutation endpoints не входят в LLM tool catalog.
- Версии: Project `0.2.5`, App/Core `0.1.53`, Agent `0.15.1`, Cognitive Brain `1.3.1`, Reasoning Planner `1.1`, Tool Planner `0.4.2`.
- Candidate `0.2.4` commit `5c0532f1c92c56d921ce49eba327b39277eb9747` остановлен workflow #37417246205: duplicate `def self_evaluation(` вызвал SyntaxError. Fix оформляется отдельным versioned commit без переписывания истории.
- Приёмка: portfolio regressions, полный Python suite, JS syntax, preflight, version each-commit, Windows launcher, PR CI, squash merge и final green main CI.

