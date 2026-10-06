# Журнал изменений

## Невыпущенные изменения

### 0.2.6 — 2026-10-06 — Portfolio Coordination Regression Fix

- Второй branch candidate `0.2.5` прошёл import stage и запустил 169 app tests, что подтвердило исправление SyntaxError из `0.2.4`.
- Исправлен `graph_integrity()`: milestone/task/portfolio rows теперь явно читаются внутри собственного diagnostic snapshot; устранён `NameError: milestone_rows is not defined`.
- Обновлён scale regression на фактический scheduler contract `cognitive-scheduler-v1.3` вместо старого `v1.2`.
- Cognitive Project Brain повышен до `1.3.2`; Agent Core — `0.15.2`.
- Поскольку корректируется regression в `app/tests`, App/Core повышен до `0.1.54` согласно VERSIONING.md.
- Candidate `0.2.5` commit `c1816efdade9d44ff98bb925bb565319eb8f068b`, workflow #37417544393, не принят: 1 stale assertion + 5 ошибок, все 5 ошибок имели один корень в missing integrity queries.
- Project: `0.2.6`; App/Core: `0.1.54`; Agent Core: `0.15.2`; Cognitive Brain: `1.3.2`. Reasoning Planner `1.1`, Tool Planner `0.4.2`, Web UI, Disk и dev-tools без изменений.


### 0.2.5 — 2026-10-06 — Portfolio Coordination Acceptance Fix

- Исправлена синтаксическая ошибка branch candidate `0.2.4`: автоматическая сборка блока metacognition оставила двойную сигнатуру `def self_evaluation(`, из-за чего Python suite останавливался на import-time SyntaxError.
- Архитектура Portfolio Coordination не откатывается: milestones, external blockers, strict project boundary, Cloud privacy и cycle guards остаются без изменения semantics.
- Cognitive Project Brain повышен до `1.3.1`; Agent Core до `0.15.1`; Project до `0.2.5`.
- App/Core остаётся `0.1.53`: исправление не меняет app source/tests/API после уже versioned candidate `0.2.4`.
- Candidate `0.2.4` commit `5c0532f1c92c56d921ce49eba327b39277eb9747` не принят: branch workflow #37417246205 остановился на Python import SyntaxError. Версионная история не переписывается.
- Новый acceptance candidate строится поверх `0.2.4` отдельным versioned commit согласно VERSIONING.md.


### 0.2.4 — 2026-10-06 — Portfolio Milestones & Cross-Project Coordination

- Cognitive Project Brain обновлён до `1.3`: над существующим task graph добавлен портфельный уровень milestones и explicit external blockers без создания нового Planner или второй памяти.
- Milestone принадлежит одному проекту, может быть привязан к модулю и содержит required/optional task links; обязательные задачи другого проекта привязать нельзя.
- Milestone никогда не закрывается автоматически. Даже после выполнения всех required tasks он получает только `ready_for_confirmation`; переход в `done` требует явного `COMPLETE_MILESTONE`.
- Межпроектные зависимости больше не моделируются запрещёнными direct task edges: target project/module/task получает persistent external blocker, который может ссылаться на source project и source milestone.
- External blocker автоматически считается эффективно разрешённым только после подтверждённого `done` связанного source milestone либо после отдельного explicit local resolution.
- Добавлен portfolio-cycle guard: цепочки project A → B → … → A отклоняются при создании; legacy цикл выявляется read-only integrity diagnostics и не ремонтируется молча.
- Scheduler использует milestones/external blockers внутри существующего snapshot, учитывает milestone priority и различает `blocked_by_dependencies` и `blocked_by_external`.
- Явный `project_key` стал жёсткой границей scheduler: контекст одного проекта больше не может выбрать task другого проекта только из-за более высокого priority.
- Context path переиспользует один portfolio snapshot для scheduler + metacognition; при отсутствии actionable task metacognition анализирует лучший blocked candidate текущего project scope вместо ухода в другой проект.
- Cloud cognition projection скрывает task/milestone/blocker/project database IDs и оставляет только bounded key/title/status/relation/summary, необходимые DeepSeek-V4-Flash для рассуждения.
- Reasoning Planner обновлён до `1.1`: milestones и external blockers являются обязательными read-only ограничениями; модель не может объявить blocker снятым или milestone завершённым.
- Evidence Tool Planner обновлён до `0.4.2`: добавлены узкие read-only triggers для milestone/external-blocker/cross-project intent без возврата generic trigger от слов «проект/модуль».
- Добавлены explicit local API для milestones, task links, milestone completion, external blockers и resolution; эти mutation endpoints не включены в Evidence Tool Planner catalog.
- Добавлены regressions на strict project boundary, milestone confirmation, derived cross-project unlock, portfolio-cycle guard, Cloud ID privacy, integrity diagnostics, narrow tool trigger и local API boundary.
- Старый PR #27 закрыт как superseded после публикации `main 0.2.3`; `0.2.4` строится от проверенного commit `a609762d1f82763110d9b0a6fc88d3c1abbf389a`.
- Project: `0.2.4`; App/Core: `0.1.53`; Agent Core: `0.15.0`; Cognitive Brain: `1.3`; Reasoning Planner: `1.1`; Evidence Tool Planner: `0.4.2`. Web UI, Disk и dev-tools без изменений.

### 0.2.3 — 2026-10-06 — Portfolio Scale & Integrity

- Cognitive Project Brain обновлён до `1.2`: scheduler и self-evaluation используют пакетный portfolio snapshot вместо повторных per-task SQLite/Memory запросов.
- Snapshot за один цикл собирает task state, scopes, project/module registry, confirmed dependencies, open uncertainty и applied checkpoint counters.
- `sync_tasks()` читает существующие scope IDs одним запросом и сохраняет уже управляемые attention/confidence/criteria.
- Повторная регистрация модуля больше не сбрасывает title и не заменяет существующие metadata целиком: metadata merge-ятся.
- Добавлена явная read-only диагностика `graph_integrity()` для legacy missing-task, cross-project и cycle проблем без автоматического ремонта graph.
- Completion assessment переиспользует snapshot и продолжает считать только `applied=1` checkpoints.
- High-severity uncertainty теперь переводит recommendation scheduler в evidence-first шаг до следующего mutation.
- Cloud cognition projection минимизирована: project/module передаются без DB ids/path/metadata, strategy — без local scope IDs, causal trace — без source/effect IDs, replan — без internal revision/evidence IDs.
- Evidence Tool Planner обновлён до `0.4.1`: общие слова «проект» и «модуль» больше не запускают `cognition.next` без scheduler/dependency/criteria/replan intent.
- Явный local `/api/sayuri/cognition` diagnostics включает `graph_integrity`; лёгкий `cognition.status` остаётся без тяжёлого integrity scan.
- Новых mutation tools, автономного execution loop и второй LLM не добавлено.
- Добавлены regressions на snapshot scheduler, graph integrity, metadata preservation, evidence-first uncertainty, Cloud ID privacy и specific cognition auto-trigger.
- Branch acceptance: после первого `0.2.2` candidate устаревший reasoning regression всё ещё ожидал лишний generic `cognition.next`; тест-контракт исправлен на фактический policy `1` read-only evidence check.
- Project: `0.2.3`; App/Core: `0.1.52`; Agent Core: `0.14.2`; Cognitive Brain: `1.2`; Evidence Tool Planner: `0.4.1`.

### 0.2.1 — 2026-10-06 — Cognitive Brain Hardening

- Cognitive Project Brain обновлён до `1.1`: hardening существующей multi-project/multi-module архитектуры без добавления второй LLM или автономного mutation loop.
- `sync_tasks()` стал идемпотентным для уже управляемых task scope: повторная синхронизация больше не перезаписывает attention state, confidence или вручную уточнённые completion criteria.
- Добавлен единый normalizer project/module context и безопасные aliases текущего UI (`disk/dna → sayuri-disk`, `chat/sayuri → agent-core`, системные экраны → `sayuri-core`).
- Task Graph защищён от циклов и прямых межпроектных task dependencies; неподтверждённые edges больше не блокируют scheduler.
- Completion criteria считают только `applied` checkpoints; unresolved dependency имеет приоритет и переводит assessment в `blocked_by_dependencies`.
- Явное завершение task через локальный API теперь отклоняется, если для неё заданы criteria и они ещё не достигли `ready_for_confirmation`.
- Failure lineage стал консервативно причинным: подтверждённый failed action связывается с replan proposal и uncertainty как evidence lineage, без заявления недоказанной причинности.
- Replan по-прежнему создаётся только как `proposed`; применение требует явного `APPLY_REPLAN` и stale-state guard по актуальному `next_action`.
- Добавлено явное разрешение uncertainty; ни uncertainty, ни replan не исчезают автоматически по тексту модели.
- Strategy Memory и Self-Evaluation теперь корректно изолируются по module scope, а не только по project scope.
- Cloud projection сокращён: project/module path, metadata и локальные manifest details не отправляются DeepSeek; остаются безопасные key/title и релевантная task-state.
- Добавлены explicit local API для регистрации project/module, task dependencies, completion criteria, resolution uncertainty и подтверждённого применения replan; ни один из этих mutation endpoints не добавлен в LLM tool catalog.
- `GET /api/sayuri/cognition` принимает `project_key/module_key` для диагностики конкретного проекта/модуля.
- Добавлены regressions на cycle/cross-project guards, unconfirmed edges, managed-scope preservation, unapplied checkpoints, stale replan, causal lineage, explicit confirmation и Cloud metadata boundary.
- Проект: `0.2.1`; App/Core: `0.1.50`; Agent Core: `0.14.1`; Cognitive Project Brain: `1.1`. Reasoning Planner, Web UI, Disk и dev-tools без изменений.

### 0.2.0 — 2026-10-06 — Cognitive Project Brain

- Sayuri получила отдельный `CognitiveProjectBrain 1.0` поверх Memory 4.x и Task Lifecycle; это единая модель управления множеством проектов и модулей.
- `MODULES.json` обновлён до schema 1-compatible metadata: модуль может объявлять `project_key`, capabilities и будущие dependencies; Cognitive Brain автоматически регистрирует manifest при запуске.
- Добавлен persistent portfolio: `projects / modules / task_scope` в той же локальной SQLite без новой внешней зависимости.
- Добавлен Task Graph с отношениями `requires / blocks / unlocks / follows`; Cognitive Scheduler не выбирает задачу, пока её подтверждённые зависимости не разблокированы.
- Добавлены explicit completion criteria: checkpoint count, confirmed tool result, dependency done и manual confirmation. Даже полностью выполненные criteria дают только `ready_for_completion_confirmation`, но никогда автоматически не ставят `done`.
- Cognitive Scheduler ранжирует задачи по priority/status/query relevance/project/module context, blockers, uncertainty и attention state.
- Добавлен Uncertainty Layer: high/medium/low неизвестности, требуемое evidence и metacognitive state `uncertain`.
- Добавлена Strategy Memory: подтверждённые Action Broker исходы накапливают success/failure статистику и confidence по стратегии/tool в project/module scope.
- Ошибка подтверждённого действия создаёт persistent replan proposal и uncertainty, но не переписывает `next_action` автоматически.
- Добавлена deterministic Self-Evaluation для проекта/модуля: progress, blockers, completion-ready tasks и uncertainties без второй LLM.
- Добавлена Metacognition: `actionable / blocked / uncertain / replan_required / criteria_missing / ready_for_completion_confirmation / idle`.
- Long-horizon state восстанавливается после перезапуска из SQLite: portfolio, module scope, task graph, criteria, uncertainty, strategy statistics и replan history.
- Reasoning Planner обновлён до `1.0` и получает Cognitive Brain как read-only context; blockers, uncertainty и completion criteria становятся обязательными ограничениями Planner/Verifier.
- Evidence Tool Planner обновлён до `0.4` с read-only `cognition.status` и `cognition.next`; LLM по-прежнему не получает direct mutation execution.
- Action Broker linkage теперь использует Cognitive Scheduler: заблокированная зависимостями задача не получает lifecycle checkpoint через случайное action совпадение.
- Добавлен read-only API `GET /api/sayuri/cognition` для диагностики будущих модулей и интерфейсов.
- Проект: `0.2.0`; App/Core: `0.1.49`; Agent Core: `0.14.0`; Web UI, Disk и dev-tools без изменений.

### 0.1.56 — 2026-10-06 — Task Lifecycle & Checkpoints

- Добавлен `memory-v4.2-task-lifecycle` поверх существующей Goal/Task Memory без отдельного task manager.
- Подтверждённые Action Broker результаты могут создавать локальный task checkpoint только если действие детерминированно связано с незавершённой задачей по query overlap.
- Checkpoint хранит task/action linkage, sequence number, состояние до/после, SHA-256 результата и безопасную evidence summary без копирования полного результата в Cloud context.
- `next_action` обновляется только после реально завершённого confirmation-gated действия; planned task переводится в `in_progress`, но никогда автоматически не становится `done`.
- Добавлен stale-state guard: если задача была изменена после планирования действия, checkpoint сохраняется, но актуальный `next_action` не перезаписывается.
- Blocked/done/cancelled tasks автоматически не разблокируются и не переоткрываются.
- Goal Continuity теперь возвращает `resume.latest_checkpoint`, поэтому незавершённая многошаговая работа восстанавливается из SQLite после повторной инициализации Sayuri.
- Reasoning Planner обновлён до `0.5` и понимает checkpoint только как доказательство конкретного подтверждённого шага, а не как доказательство завершения всей задачи.
- Контекст Action Broker остаётся внутренним и не добавлен в public action payload.
- Добавлены regressions для idempotent checkpoints, stale-state protection, restart restoration и end-to-end confirm → checkpoint → next_action.
- Проект: `0.1.56`; Ядро/App: `0.1.48`; Agent Core: `0.13.0`. Web UI, Disk и dev-tools без изменений.

### 0.1.55 — 2026-10-06 — Workspace Quality & Goal Continuity

- Закрыт рассинхрон контрольной точки после опубликованного `0.1.54`; новая база разработки — проверенный `main dd4907a5ba`.
- Memory 4.1 получила read-only `goal-continuity-v1`: активные цели и незавершённые задачи ранжируются детерминированно по приоритету, статусу и релевантности текущему запросу.
- Для выбранной задачи Planner получает `next_action`, `blocked_reason` и связанную цель; короткие команды «продолжай / дальше / возобнови» переходят в planned-mode только при наличии реального незавершённого контекста.
- Reasoning Planner обновлён до `0.4`; fallback-plan умеет безопасно продолжать выбранную задачу, не объявляя её завершённой и не меняя её статус.
- Evidence Tool Planner обновлён до `0.3` и получил `memory.continuity` как отдельный read-only инструмент с execution receipt. Изменяющие действия по-прежнему не проходят мимо Action Broker.
- Workspace получил возврат клавиатурного фокуса, focus-trap для Command Palette и maximized chat, корректный `aria-modal` и исключение скрытого аватара из tab-order.
- Добавлены responsive-инварианты для maximized/floating chat на узких и низких экранах без уменьшения основного текста и без нового UI-фреймворка.
- Добавлены regression tests для Goal Continuity, Planner continuation gate, read-only continuity tool и workspace accessibility/responsive contract.
- Проект: `0.1.55`; Ядро/App: `0.1.47`; Agent Core: `0.12.0`; Web UI: `0.31.0`. Disk и dev-tools без изменений.

### 0.1.54 — 2026-10-06 — Visual Refinement & Workspace UX

- Fullscreen chat переработан в полноценное AI workspace-состояние существующего окна: отдельный workspace badge, более спокойная композиция, центрированная читаемая колонка и sticky composer.
- При открытии Spatial Evidence из fullscreen chat окно автоматически возвращается в floating mode, чтобы viewer не открывался под рабочим пространством.
- Плавающий аватар получил мягкие magnet zones: snap срабатывает только рядом с краем viewport, не тянет аватар из центра и сохраняет финальную позицию один раз после drag.
- Presence-state аватара отражает реальные состояния `ready / thinking / attention / error / offline`; анимация thinking активна только во время обработки запроса.
- Добавлен локальный режим «Компактный интерфейс» для ноутбуков: уменьшаются отступы и высоты поверхностей без уменьшения основного текста.
- Command Palette запоминает до трёх последних команд локально и поднимает их выше без добавления постоянной панели.
- Диск и viewer переведены на общий `ui-state` для loading / empty / error; добавлены `aria-busy` и единая визуальная система поверхностей.
- Начальная загрузка Диска и preview больше не показывает одиночный технический текст до запуска JS.
- Пустой чат заменён на спокойный contextual welcome-screen, который показывает текущий раздел или открытый документ без лишних кнопок.
- Viewer, Диск, Evidence Focus, Personal Cabinet и Chat получили единые border/shadow/surface правила UI 0.30.
- Структура левого меню не менялась; отдельный пункт Личного кабинета не возвращался.
- Добавлены Web contract regressions на workspace, snap, density, unified states, recent commands и сохранение sidebar.
- Проект: `0.1.54`; Ядро/App: `0.1.46`; Web UI: `0.30.0`. Agent Core и Disk без изменений.

### 0.1.53 — 2026-10-06 — Spatial Evidence Citations

- Добавлен read-only `document.evidence_search`: Planner может запросить проверяемые факты только из уже сохранённой ДНК текущего документа.
- Evidence search не запускает новый ДНК/OCR-анализ, не изменяет файл и не пишет новые факты.
- Spatial citation допускается только для факта с `coordinate_status=exact_from_document_engine` и нормализованным bbox, созданным Spatial Engine.
- Модель получает citation IDs `D1..D6`, страницу/строку и безопасный факт, но bbox остаётся локальным и не отправляется в Cloud.ru.
- Runtime удаляет неизвестные citation markers вида `[D9]`; Result Verifier инструктирован сохранять только реально поддержанные D-citations.
- Public evidence скрывает tool/receipt IDs и показывает понятный источник: документ, факт, страницу и строку.
- Добавлен `GET /api/disk/files/{id}/evidence-focus?fact_id=...`: endpoint принимает только fact_id и сам разрешает сохранённый locator; произвольный bbox от клиента не принимается.
- SpatialDNAEngine 0.8.0 умеет рендерить PDF/image evidence page через PDFium/Pillow и локально подсвечивать точный bbox.
- В чате `[D1]` превращается в компактную citation-кнопку; клик открывает существующий Disk viewer в режиме Evidence Focus.
- Evidence Focus показывает отрендеренную страницу с подсветкой, страницу/строку, исходный excerpt и кнопку возврата в обычный просмотр.
- Добавлены regressions на read-only policy, cached evidence search, fact-id-only focus, citation allowlist/privacy и Web/API contract.
- Структура меню не менялась.
- Проект: `0.1.53`; Ядро: `0.1.45`; Agent Core: `0.11.0`; Web UI: `0.29.0`; Disk: `0.8.0`.

### 0.1.52 — 2026-10-06 — Rich Answer UX & Lazy Diagnostics

- Ответы Sayuri получили безопасный rich-text renderer без `innerHTML` и без внешней Markdown-зависимости.
- Поддерживаются заголовки, абзацы, списки, цитаты, inline-code, fenced code, таблицы, безопасные http/https ссылки, выделения и горизонтальные разделители.
- Code blocks имеют собственную кнопку копирования и не исполняют содержимое ответа как HTML/JavaScript.
- Добавлен пользовательский Evidence Summary: под проверенными ответами могут отображаться понятные источники без tool/receipt ID.
- Если Evidence-aware Planner реально использовал текущий документ, источник отображается как «Документ · имя файла» и открывает существующий просмотрщик Диска.
- Использованная личная/проектная память отображается агрегированно как источник без раскрытия внутренних memory IDs.
- Agent runtime теперь возвращает компактное поле `evidence`, отдельно от внутренних execution receipts.
- Личный кабинет больше не загружает Memory 3.0, Memory 4.1 и Experience при каждом открытии.
- Memory 3.0 загружается при открытии «Архитектура», Memory 4.1 — «Quality Gate», Experience — «Опыт», обзор памяти — при открытии «Обзор».
- Для ленивых memory-панелей добавлены skeleton-состояния и `aria-busy`.
- После chat/actions/memory mutations тяжёлые панели обновляются только если уже были загружены пользователем.
- Добавлены regressions на safe renderer boundary, evidence privacy/openable document и lazy diagnostics.
- Проект: `0.1.52`; Ядро: `0.1.44`; Agent Core: `0.10.2`; Web UI: `0.28.0`. Disk не изменялся.

### 0.1.51 — 2026-10-06 — UI System & Chat Polish

- Добавлен единый UI 0.27 design layer: системные spacing/radius/shadow/focus tokens, согласованные поверхности, кнопки, поля и состояния по всему проекту.
- Структура левого меню не изменялась.
- Floating chat получил полноценный fullscreen/maximize режим без создания второго окна; Esc возвращает плавающий режим.
- Добавлена глобальная command palette по Ctrl/⌘+K без постоянной панели в интерфейсе: чат, Личный кабинет, Главная, Диск, Настройки, Память и fullscreen chat.
- Статус чата очищен от технической телеметрии: обычный пользователь видит только «Размышляет», «Готова», «Нужно подтверждение», «Ошибка» и компактную отметку автопроверки.
- У каждого сообщения появился ненавязчивый action «Копировать», показываемый при наведении; результат копирования подтверждается transient toast.
- Добавлена единая toast region для краткой обратной связи без постоянных системных карточек.
- Усилены keyboard/focus states, scrollbar styling, common laptop breakpoints и mobile behavior.
- Добавлена поддержка prefers-reduced-motion: интерфейс сохраняет функциональность без декоративной анимации.
- Fullscreen chat ограничивает ширину текста и composer для удобного чтения на широких экранах.
- Добавлены Web contract regressions на command palette, fullscreen chat, copy action, design tokens и reduced-motion.
- Проект: `0.1.51`; Ядро: `0.1.43`; Web UI: `0.27.0`. Agent Core и Disk не изменялись.

### 0.1.50 — 2026-10-06 — Sayuri Presence UX Cleanup

- Убран отдельный пункт «Личный кабинет» из левой панели; вход в кабинет остаётся через контекстное меню плавающего аватара Sayuri.
- Плавающий аватар переведён на compositor-friendly drag: Pointer Events + requestAnimationFrame + translate3d, без записи позиции на каждом движении.
- Drag различает клик и перенос, использует pointer capture и сохраняет позицию только после завершения жеста.
- Floating chat переработан в спокойную ChatGPT-подобную компоновку: чистая шапка, широкий поток сообщений, компактный composer и минимальный технический шум.
- Окно чата можно свободно растягивать по ширине и высоте; размер и позиция сохраняются локально, есть кнопка сброса размера.
- Поле ввода автоматически растёт до ограниченной высоты; Enter отправляет, Shift+Enter создаёт новую строку.
- Личный кабинет больше не является одной длинной страницей: функции распределены по вкладкам «Профиль», «AI», «Поведение», «Память», «Образ», «Диагностика»; внутри «Память» есть отдельные подразделы «Обзор», «Архитектура», «Quality Gate», «Опыт».
- Последняя вкладка кабинета запоминается локально; функции Memory 2/3/4, Experience, Cloud.ru, actions и avatar studio не удалены.
- На мобильном чат занимает безопасную полноэкранную область, manual resize отключён.
- Добавлены Web contract regressions на avatar-only cabinet entry, smooth drag, resize и tabbed cabinet.
- Проект: `0.1.50`; Ядро: `0.1.42`; Web UI: `0.26.0`. Agent Core и Disk не изменялись.

### 0.1.49 — 2026-10-06 — Background Evidence Automation

- Evidence-aware Tool Planner переведён в фоновый режим: технические инструменты и execution receipts больше не выводятся в обычный чат.
- Planner по-прежнему может предложить read-only intent, но локальная deterministic policy остаётся единственным решающим контуром исполнения.
- Добавлен deterministic автоподбор безопасных read-only проверок по goal/evidence_needed: память, состояние системы, integrity, текущий документ и статистика опыта.
- Любая mutation по-прежнему блокируется как `requires_action_broker`; исполняемый mutation payload от DeepSeek не принимается.
- Cloud evidence теперь жёстко ограничивается до добавления в контекст; большие outputs сокращаются до bounded excerpt без изменения локального receipt.
- В ответ API вместо списка receipts возвращается только компактная сводка automation: checks / evidence / blocked_mutations.
- Из Личного кабинета убран постоянный каталог инструментов. Карточки подтверждения реальных изменяющих действий и история действий сохранены.
- В существующей сводке reasoning показывается только короткое `автопроверка N`, когда фоновые проверки действительно выполнялись.
- Системный индикатор «Инструменты» заменён на «Автопроверка». Структура меню не менялась.
- Проект: `0.1.49`; Ядро: `0.1.41`; Agent Core: `0.10.1`; Web UI: `0.25.0`.


### 0.1.48 — 2026-10-06 — Evidence-aware Tool Planner

- Добавлен `agent/tool_planner.py`: deterministic allowlist для read-only инструментов и отдельная политика для confirmation-gated mutations.
- Reasoning Planner 0.2 может предлагать структурированные `tool_intents`, привязанные к номеру шага плана.
- DeepSeek не получает прямого execution path: unknown tools отклоняются, mutation payload от модели игнорируется, изменяющие действия помечаются `requires_action_broker`.
- Автоматически разрешены только read-only инструменты: состояние системы, статистика памяти, Cloud-safe поиск Memory 4.1, integrity, статистика опыта и метаданные текущего документа.
- Для каждого tool intent создаётся локальный SQLite execution receipt с нормализованными args, статусом, временем, duration, evidence refs и SHA-256 output.
- Добавлены дедупликация одинаковых tool calls и лимит до 4 read-only вызовов на один planned request.
- Tool output проходит secret-field sanitization и отдельный bounded evidence budget перед Cloud.ru.
- `memory.search` использует `for_cloud=True`; дополнительные memory IDs объединяются с prepared recall и фиксируются только после успешного reasoning pipeline.
- Result Verifier получает реальные execution receipts и отличает `completed` от `requires_action_broker`.
- Добавлен `GET /api/sayuri/tools/receipts` для локальной диагностики журнала.
- В чате reasoning summary показывает инструменты, статусы выполнения и необходимость подтверждения без изменения меню.
- Добавлены regression tests allowlist, mutation isolation, dedup, secret sanitization, runtime evidence injection и HTTP contract.
- Проект: `0.1.48`; Ядро: `0.1.40`; Agent Core: `0.10.0`; Web UI: `0.24.0`.

### 0.1.47 — 2026-10-06 — Reasoning Planner + Result Verifier

- Добавлен adaptive complexity gate: простые запросы остаются на одном вызове DeepSeek-V4-Flash, сложные переходят в planned mode.
- Новый `agent/reasoning.py` формирует только структурированный task-plan: goal, steps, constraints, evidence_needed, done_when и risk_level.
- Structured plan не является chain-of-thought; скрытые рассуждения не сохраняются в БД и не выводятся в UI.
- Planner использует только уже отфильтрованный Memory 4.1 / Memory 3.0 / Experience / UI context.
- Result Verifier независимо проверяет ответ против исходной задачи, плана, ограничений и доступных доказательств.
- При `status=revise` verifier возвращает полную исправленную версию ответа в том же вызове, без четвёртого model call.
- Сбой Planner приводит к безопасному fallback-plan; сбой Verifier не уничтожает уже полученный основной ответ и явно помечается как unavailable.
- Recall usage commit выполняется после завершения reasoning pipeline и по-прежнему учитывает только memory IDs реально отправленного контекста.
- Usage агрегируется по planner/answer/verifier.
- В чате добавлена раскрываемая сводка «План · N шагов · проверено/исправлено» без показа внутреннего reasoning.
- Добавлены unit/runtime/Web contract tests direct/planned режимов, verifier repair и ограничения chain-of-thought storage.
- Проект: `0.1.47`; Ядро: `0.1.39`; Agent Core: `0.9.0`; Web UI: `0.23.0`.


### 0.1.46 — 2026-10-06 — Memory 4.1 Quality Gate

- Generic chat feedback теперь обучает только retrieval utility и не меняет factual Source Trust.
- Добавлен instruction-risk classifier и local-only quarantine для high-risk directives внутри памяти.
- Quarantine действует также на Memory 3.0 и Experience-derived Cloud-context.
- Recall получил diversity selection, чтобы почти одинаковые воспоминания не вытесняли независимые источники.
- Важные stale volatile memories и важные low-trust records автоматически создают idempotent Question Memory на перепроверку.
- Добавлены отдельные char budgets для direct recall и Goal/Task/Failure/Question context.
- Длинные memories сокращаются только в outbound context; оригиналы не изменяются.
- Prepared recall после budget selection содержит только IDs реально отправленных модели memories.
- Usage/feedback остаются двухфазными и применяются только после успешного Cloud.ru ответа.
- Maintenance переиспользует рассчитанный `memory_v4_state` для review queue вместо повторной полной оценки.
- Личный кабинет показывает Quarantine и «К перепроверке», а локальный список памяти — instruction-risk badges.
- Добавлены regression tests для source-truth separation, instruction-risk firewall, diversified recall, stale review queue и bounded context attribution.
- Проект: `0.1.46`; Ядро: `0.1.38`; Agent Core: `0.8.2`; Web UI: `0.22.0`.


### 0.1.45 — 2026-10-06 — Memory 4.0 Hardening

- Локальный поиск/просмотр памяти больше не увеличивает `use_count`, `recall_count` и не создаёт обучающий recall-audit.
- AI recall стал двухфазным: usage/audit фиксируются только после успешного ответа Cloud.ru; ошибка провайдера не обучает память.
- Explainable Recall остаётся доступным в Личном кабинете без искусственного роста utility.
- Сквозной privacy firewall `cloud_allowed=false` распространён на Memory 3.0, Experience Learning, Goals, Tasks, Failures и Questions перед Cloud.ru.
- Protected memory не может попасть в AI-context обходным путём через производные слои памяти.
- Успех после failure больше не считается доказанным исправлением: создаётся `followed_by_success` с низкой confidence и `correlation_only`.
- Failure Memory закрывается только явным подтверждением пользователя через cause/resolution/prevention.
- Повтор уже исправленной ошибки переоткрывает failure pattern.
- Повтор одинакового подтверждения resolution идемпотентен и не увеличивает `resolved_count`.
- Добавлен `POST /api/sayuri/memory/v4/failures/{id}/resolve` и UI-кнопка «Подтвердить исправление».
- Добавлены регрессионные тесты privacy firewall, local read-only recall, causal semantics, failure reopen/idempotency, HTTP API и Web contract.
- Проект: `0.1.45`; Ядро: `0.1.37`; Agent Core: `0.8.1`; Web UI: `0.21.1`.


### 0.1.44 — 2026-10-06 — Memory 4.0

- Добавлен `agent/memory_v4.py` — orchestration layer поверх Memory 3.0.
- Для каждой memory рассчитываются Source Trust, Freshness, Utility, sensitivity и tier `hot/warm/cold`.
- Explainable Recall показывает, почему запись была выбрана, и сохраняет локальный recall audit.
- Feedback «Полезно / Не помогло» обновляет utility только реально использованных memories и ограниченно калибрует trust источника.
- Secret/sensitive memory получает `cloud_allowed=false` и исключается из Cloud.ru context.
- Добавлены Goal Memory, Task Memory, Decision Memory, Failure Memory, Causal Memory и Question/Uncertainty Memory.
- Добавлены Entity Profiles и Preference Drift поверх Knowledge Graph.
- Добавлен Memory Audit.
- Добавлены SQLite snapshots с SHA-256, обязательным `RESTORE MEMORY` и автоматическим pre-restore safety snapshot.
- Добавлен integrity check SQLite/graph/goals/tasks/knowledge provenance/recall links.
- Личный кабинет получил Memory 4.0 control center и badges tier/trust/local-only.
- Добавлены Memory 4.0 runtime/API/Web/unit tests.
- Проект: `0.1.44`; Ядро: `0.1.36`; Agent Core: `0.8.0`; Web UI: `0.21.0`.


### 0.1.43 — 2026-10-06 — Memory 3.0

- Добавлены Working Memory, Episodic Memory, Knowledge Memory и Temporal Memory.
- Добавлен локальный Knowledge Graph памяти.
- Добавлена консолидация похожих воспоминаний в устойчивые knowledge items без удаления источников.
- Добавлен Retention/Forgetting Engine: устаревшие записи получают меньший semantic retrieval-вес вместо автоматического удаления.
- Добавлен Contradiction Resolver с вариантами новое/старое/оба.
- Knowledge items получили temporal validity: `valid_from/valid_to`.
- Working Memory обновляется из чата и Safe Action planning и имеет TTL 24 часа.
- Значимые action/feedback/review события записываются как эпизоды.
- При старте выполняется bootstrap существующей памяти; opportunistic maintenance запускается не чаще одного раза в 6 часов.
- DeepSeek-V4-Flash получает отдельный Memory 3.0 context block.
- В Личном кабинете появился Memory 3.0 dashboard с графом, timeline, conflicts, retention и knowledge.
- Добавлены `GET /api/sayuri/memory/v3`, `POST /maintenance`, `POST /conflicts/{id}/resolve`.
- Episodic Memory дедуплицирует повторную обработку одного feedback/action по fingerprint; точный retry не засоряет timeline.
- Semantic Memory сканирует активные записи по scope до лимита 5000, поэтому релевантная старая память не теряется после первых 300 записей.
- Knowledge Graph сохраняет реальные подписи source-memory и помечает архивированные узлы через `active=false` / `archived_at`.
- Contradiction Resolver гарантирует обе стороны конфликта в графе и связь `conflicts_with`.
- Ручное архивирование исходной memory закрывает производное Knowledge, если не осталось других активных источников.
- Открытые противоречия передаются в AI-context явно как old/new, а не только счётчиком.
- Добавлены unit/API/Web contract tests Memory 3.0.
- Проект: `0.1.43`; Ядро: `0.1.35`; Agent Core: `0.7.0`; Web UI: `0.20.0`.


### 0.1.42 — 2026-10-06 — Semantic Memory + Experience Learning

- Добавлен локальный hybrid semantic поиск памяти `hybrid-semantic-v1`.
- Поиск учитывает формы слов, смысловые concepts, character n-grams, importance и confidence.
- Semantic retrieval подключён к контексту DeepSeek-V4-Flash без второй облачной модели.
- Добавлена отдельная локальная память опыта `data/sayuri-experience.db`.
- Sayuri учится на финальных исходах инструментов, review кандидатов памяти и явной оценке ответов.
- После достаточного числа примеров опыт мягко калибрует confidence Memory Intelligence в пределах ±8 п.п.
- Релевантный прошлый опыт делится на `helpful` и `avoid` и передаётся модели как недоверенный справочный контекст.
- В чате добавлена явная оценка «Полезно / Не помогло».
- В Личном кабинете добавлены Semantic Memory status, relevance поиска и статистика Experience Learning.
- Добавлены API `/api/sayuri/experience` и `/api/sayuri/experience/feedback`.
- Добавлены тесты semantic retrieval, feedback idempotency, relevant experience context, calibration и action learning.
- Проект: `0.1.42`; Ядро: `0.1.34`; Agent Core: `0.6.0`; Web UI: `0.19.0`.


### 0.1.41 — 2026-10-05 — Memory Intelligence 2.0

- Добавлен автоматический Memory Guardian для анализа сообщений.
- Sayuri создаёт кандидаты личной/проектной памяти вместо сохранения всего чата.
- Добавлены confidence, причина выделения, provenance и контекст открытого документа.
- Добавлены обнаружение дублей и возможных противоречий.
- В Личном кабинете появилась очередь кандидатов с «Сохранить / Не запоминать».
- Добавлены настройки генерации кандидатов, конфликтов, context-linking и безопасного high-confidence autosave.
- Память получила `source_context`, `confidence` и `supersedes_id`.
- Чат показывает уведомление, когда Sayuri заметила потенциально важное воспоминание.
- Добавлены Memory Intelligence API и тесты полного candidate lifecycle.
- Проект: `0.1.41`; Ядро: `0.1.33`; Agent Core: `0.5.0`; Web UI: `0.18.0`.


### 0.1.40 — 2026-10-05 — исправление загрузки и построения ДНК

- После загрузки PDF/Office/text/ODF/изображений ДНК запускается автоматически.
- Загрузка оригинала и построение ДНК теперь имеют отдельные статусы.
- Ошибка ДНК не отменяет успешную загрузку файла и не останавливает очередь.
- В очереди файлов показываются «ожидает ДНК», «строю ДНК», процент покрытия и ошибка.
- Во вкладке ДНК появилась собственная видимая диагностика и кнопка «Повторить анализ».
- Исправлена проверка готовности Spatial DNA: используется `pdfium_available`, а не устаревший/несуществующий `pymupdf_available`.
- Добавлены Web contract и Spatial diagnostics tests.
- Проект: `0.1.40`; Ядро: `0.1.32`; Диск: `0.7.1`; Web UI: `0.17.0`.


### 0.1.39 — 2026-10-05 — безопасные действия Sayuri

- Добавлен confirmation-gated Action Broker.
- Sayuri умеет подготовить создание папки, избранное, корзину, перемещение объекта и сохранение решения проекта.
- До нажатия «Подтвердить» проект не изменяется.
- Добавлены TTL, SHA-256 payload, replay protection и атомарное claim выполнения.
- В чате появились карточки действий с уровнем риска и кнопками подтверждения/отмены.
- В Личном кабинете появился список разрешённых инструментов и журнал последних действий.
- Добавлены API `/api/sayuri/actions`, `/plan`, `/{id}/confirm`, `/{id}/cancel`.
- Добавлены unit/API/web тесты подтверждения и повторного confirm.
- Проект: `0.1.39`; Ядро: `0.1.31`; Agent Core: `0.4.0`; Web UI: `0.16.0`.


### 0.1.38 — 2026-10-05 — память Sayuri и студия аватаров

- Добавлена долговременная локальная память Sayuri с областями `personal` и `project`.
- Добавлены типы памяти: fact, preference, decision, task, note; важность 1–5, dedup, поиск и use-count.
- Явные команды «запомни лично: …» и «запомни в проект: …» сохраняются без участия LLM.
- DeepSeek-V4-Flash получает только релевантную память с сохранением границы областей.
- В Личном кабинете добавлены просмотр, поиск, ручное добавление и удаление памяти.
- Добавлена локальная студия аватаров с независимыми слотами orb/chat/profile/hero.
- Пользовательские PNG/JPEG/WebP до 8 МБ сохраняются только в `data/sayuri-avatars/`.
- Добавлены HTTP API памяти и аватаров и тесты безопасности/разделения.
- Проект: `0.1.38`; Ядро: `0.1.30`; Agent Core: `0.3.0`; Web UI: `0.15.0`.


### 0.1.37 — 2026-10-05 — Sayuri Personal AI 0.1

- Sayuri стала глобальной помощницей во всём веб-интерфейсе.
- Пользовательский образ Sayuri добавлен как канонический аватар интерфейса.
- Обычный клик по аватару открывает отдельное окно чата; правый клик — контекстное меню действий.
- Добавлен нижний пункт «Личный кабинет Sayuri».
- В Личном кабинете реализованы настройки Cloud.ru и API-ключа.
- Единственная модель проекта: `deepseek-ai/DeepSeek-V4-Flash`.
- Добавлены `/api/sayuri/profile`, `/api/sayuri/provider`, `/api/sayuri/provider/test`, `/api/sayuri/chat`.
- На Windows локальный ключ защищается DPAPI; в GitHub и публичные API полный ключ не попадает.
- Чат получает интерфейсный контекст текущего раздела и выбранного объекта.
- Проект: `0.1.37`; Ядро: `0.1.29`; Agent Core: `0.2.0`; Web UI: `0.14.0`.


### 0.1.36 — 2026-10-05 — удаление Android/device-интеграции

- Полностью удалён ненужный Android/device-контур.
- Удалены backend-модуль, приложение-компаньон, HTTP API, media/control bridge и ADB/scrcpy runtime.
- Удалены связанный Web UI, стили, тесты и отдельный Android workflow.
- `MODULES.json` очищен от удалённых модулей.
- Ядро Саюри повышено до `0.1.28`, Web UI до `0.13.0`, dev-tools до `0.1.6`.
- Диск Sayuri, ДНК, OCR и Agent Core не изменены функционально.


### 0.1.35 — 2026-10-05 — Unified Sayuri UI 0.12

- Web UI повышен до `0.12.0`.
- Введён единый визуальный слой `SAYURI UI 0.12 — Unified Visual System`.
- Основная типографика переведена на `Segoe UI Variable` с системными fallback.
- Убраны экстремально мелкие пользовательские подписи и выровнена шкала размеров текста.
- Боковая навигация переведена на светлую оболочку.
- Главная, Диск, ДНК, Телефон и Настройки получили общие токены поверхностей, текста, границ и радиусов.
- Сокращены технические формулировки в пользовательском интерфейсе.
- Профили качества телефона теперь отображаются как «Экономно / Баланс / Качество / Максимум».
- Динамические статусы клавиатуры, видео и clipboard переписаны в понятной форме.
- UI-contract тест обновлён под новую пользовательскую терминологию.


### 0.1.34 — 2026-10-05 — Phone file-import validation order

- Телефон Sayuri повышен до `0.8.1`.
- Allow-list Android-каталога и basename импортируемого файла теперь проверяются до обращения к ADB.
- Некорректный location/path traversal отклоняется даже при отключённом телефоне.
- Функциональность PHONE 0.8 не изменялась и не ослаблялась.


### 0.1.33 — 2026-10-05 — Телефон Sayuri 0.8 Final Workspace

- Телефон Sayuri повышен до `0.8.0`, Web UI до `0.11.0`.
- Добавлен профиль MAX: 2560 px / 60 FPS / 24 Mbit/s.
- Добавлен fullscreen плавающего телефона.
- Добавлена AUTO-подстройка окна к portrait/landscape видеопотоку.
- Добавлены режимы Обычный / Компакт / Стекло.
- Добавлен hotkey `Ctrl+Alt+P` для показа/скрытия телефона.
- Позиция, размер и ручной поворот теперь сохраняются отдельно по serial устройства.
- Добавлен безопасный обратный файловый канал Android → Диск Sayuri.
- Импорт разрешён только из Download, DCIM/Camera и Pictures.
- Файл проверяется как обычный файл, ограничивается 512 МБ и только после этого скачивается через ADB pull.
- Добавлены service/API/web regression tests для file import и нового workspace UX.


### 0.1.32 — 2026-10-05 — Verified Sayuri Companion installer

- Телефон Sayuri повышен до `0.7.1`, Web UI до `0.10.1`.
- Закреплён реально собранный APK Sayuri Companion 0.1.1.
- APK download привязан к точному versioned GitHub Release.
- До `adb install -r` проверяются размер и SHA-256.
- Непроверенный/оборванный download удаляется.
- Установка запускается только явной кнопкой пользователя.
- После установки проверяется Android package.
- UI автоматически переключается с «Установить» на «Сопрячь».
- ADB reverse Companion автоматически восстанавливается после reconnect в пределах текущего desktop-процесса.
- Добавлены installer/reverse/API/web regression tests.


### 0.1.31 — 2026-10-05 — Companion Android CI bootstrap

- Sayuri Companion повышен до `0.1.1`.
- Исправлен Android workflow: runner не имел `sdkmanager`.
- Добавлен pinned `android-actions/setup-android v4.0.4` по commit SHA `be39fa834029ff78f1a44aa3bb0819b8fc2bd8fd`.
- Android SDK 36 и build-tools 36.0.0 теперь устанавливаются через setup action.
- Основной Sayuri CI для PHONE-005A уже подтверждён как success.


### 0.1.30 — 2026-10-05 — Sayuri Companion 0.1

- Телефон Sayuri повышен до `0.7.0`, Web UI до `0.10.0`.
- Добавлен новый зарегистрированный Android-модуль `Sayuri Companion 0.1.0`.
- Добавлен локальный authenticated Companion protocol через ADB reverse.
- Добавлен Android NotificationListenerService.
- Pairing требует явного подтверждения пользователя на телефоне.
- Notification Access остаётся системным Android-разрешением и не обходится.
- Добавлены Companion status/events/enable/disable API.
- В floating phone добавлен drawer уведомлений.
- Добавлен Android CI: AGP 9.4.0 / Gradle 9.6.1 / JDK 17 / API 36.
- Workflow публикует APK и checksum как versioned GitHub Release.
- Автоустановка APK намеренно отложена до следующего patch после получения digest реально собранного APK.


### 0.1.29 — 2026-10-05 — Телефон Sayuri 0.6 Audio & Clipboard

- Телефон Sayuri повышен до `0.6.0`, Web UI до `0.9.0`.
- Добавлен version-pinned scrcpy 4.1 clipboard protocol adapter.
- Добавлен двусторонний Unicode clipboard ПК↔Android.
- ПК→Тел может сразу выполнить Android paste.
- Строка ввода использует Android clipboard и поддерживает Unicode/эмодзи.
- Добавлен version-pinned Opus media adapter `sayuri-opus-v1`.
- Добавлен отдельный embedded audio stream и WebCodecs AudioDecoder/Web Audio playback.
- Звук включается только явным действием пользователя.
- Audio failure не ломает H.264 video/control.
- Audio очищается при смене устройства, disconnect, minimize/close и переходе в native scrcpy.
- Добавлены binary protocol/API/web regression tests.


### 0.1.28 — 2026-10-05 — Телефон Sayuri 0.5 H.264 WebCodecs

- Телефон Sayuri повышен до `0.5.0`, Web UI до `0.8.0`.
- Добавлен version-pinned адаптер официального scrcpy-server 4.1.
- Добавлен embedded H.264 stream через локальный ADB forward и существующий loopback HTTP server.
- Добавлен внутренний протокол `sayuri-h264-v1`.
- Web UI декодирует H.264 через WebCodecs и рисует кадры в canvas.
- ECO/BAL/HQ теперь управляют качеством встроенного H.264.
- Session packets поддерживают изменение размера при повороте/складывании устройства.
- SPS/PPS config объединяется с первым media frame.
- Добавлен decoder backlog guard для low-latency режима.
- При отсутствии WebCodecs или ошибке media bridge автоматически возвращается PNG fallback.
- Нативный scrcpy 60 FPS сохранён.
- Добавлены protocol/service/API/web regression tests.


### 0.1.27 — 2026-10-05 — Телефон Sayuri 0.4.1 input validation

- Android package name теперь валидируется до обращения к ADB/device state.
- Вредоносное или некорректное имя пакета отклоняется независимо от подключения телефона.
- Реализация PHONE-004A не ослаблялась.
- Требуется повторный полный CI.


### 0.1.26 — 2026-10-05 — Телефон Sayuri 0.4 Pro Control & Media

- Телефон Sayuri повышен до `0.4.0`, Web UI до `0.7.0`.
- Добавлен явный переключатель захвата клавиатуры компьютера.
- Нативный scrcpy использует рекомендованный режим `--keyboard=uhid`.
- Добавлены профили качества ECO/BAL/HQ.
- Добавлено сохранение снимков PNG в Диск Sayuri.
- Добавлена запись видео+аудио в MP4 через официальный scrcpy с последующим импортом в Диск Sayuri.
- Добавлен drag&drop файлов из Диска/ПК в Android Download.
- Добавлен безопасный список и запуск пользовательских приложений.
- Добавлена вставка текста из clipboard компьютера.
- Произвольный ADB shell не публикуется.
- PHONE-004B с H.264/WebCodecs остаётся следующим слоем этой же задачи.


### 0.1.25 — 2026-10-05 — Телефон Sayuri 0.3 Floating Workspace

- Телефон Sayuri повышен до `0.3.0`, Web UI до `0.6.0`.
- Убран большой встроенный дисплей из страницы модуля.
- Добавлено независимое плавающее окно поверх всего проекта.
- Окно можно таскать, менять размер, сворачивать, закрывать и возвращать глобальным launcher.
- Позиция, размер и поворот сохраняются локально.
- Добавлен поворот 0/90/180/270 с корректным обратным пересчётом координат touch/swipe.
- Добавлены колесо мыши как swipe и правый клик как Android Back.
- Добавлена физическая клавиатура ПК и allow-listed text input endpoint.
- Нативный scrcpy 60 FPS сохранён.
- В CI добавлен `node --check web/app.js`.
- Страница «Телефон Sayuri» упрощена до подключения и управления устройствами.


### 0.1.24 — 2026-10-05 — Телефон Sayuri 0.2.1 reconnect resilience

- Исправлена обработка реального USB/ADB disconnect Samsung SM-A556E.
- Потерянный serial больше не вызывает бесконечный цикл `/api/phone/frame` HTTP 400.
- Stale frame cache и scrcpy session очищаются после исчезновения устройства.
- Frame endpoint возвращает `SAYURI-PHONE-409` для controlled disconnect.
- UI останавливает live polling, очищает старый кадр и переходит в состояние ожидания.
- Добавлен лёгкий auto-reconnect через периодическую проверку `/api/phone`.
- После повторной авторизации embedded preview восстанавливается автоматически.
- Embedded screencap ставится на паузу, пока открыт нативный scrcpy 60 FPS.
- Добавлены regression tests по disconnect/reconcile/API 409/web recovery contract.


### 0.1.23 — 2026-10-05 — Телефон Sayuri 0.2 Embedded Control

- Телефон Sayuri повышен до `0.2.0`.
- Web UI повышен до `0.5.0`.
- В существующий модуль добавлен встроенный экран Android.
- Добавлен локальный PNG frame bridge через `adb exec-out screencap -p`.
- Добавлен кэш кадров ~350 мс и остановка polling вне вкладки телефона.
- Добавлены tap/swipe по нормализованным координатам.
- Добавлены allow-listed Android Back/Home/Recents/Power.
- Нативный официальный scrcpy 60 FPS сохранён отдельным high-performance режимом.
- Arbitrary ADB shell не публикуется.
- Добавлены unit/API/web contract tests.


### 0.1.22 — 2026-10-05 — Phone input validation order

- Телефон Sayuri повышен до `0.1.1`.
- Pair/connect/disconnect сначала валидируют пользовательский ввод и только затем обращаются к ADB runtime.
- Некорректный адрес/код отклоняется независимо от наличия ADB.
- Первый CI уже подтвердил Windows launcher, API и web contract; требуется повторный полный прогон.


### 0.1.21 — 2026-10-05 — Телефон Sayuri 0.1

- Добавлен новый зарегистрированный модуль `sayuri-phone` версии `0.1.0`.
- В левое меню добавлен **«Телефон Sayuri»**.
- Добавлены USB/Wi-Fi Android device discovery, Wireless Debugging pair/connect/disconnect.
- Добавлен запуск/остановка официального scrcpy из Sayuri.
- Добавлены allow-listed `/api/phone/*` endpoints; произвольный adb shell не публикуется.
- Windows AMD64 launcher получает официальный scrcpy 4.1 с проверкой SHA-256.
- Добавлены phone service/API/web/bootstrap tests.
- Встроенный видеопоток в браузер отложен на PHONE-002.


### 0.1.20 — 2026-10-05 — Исправление тестового синтаксиса Spatial DNA

- Исправлен буквальный `\\n` в `app/tests/test_disk.py`, из-за которого unittest не мог импортировать модуль.
- Реализация Spatial DNA 0.7 не изменялась.
- Первый CI уже подтвердил новые Spatial/OCR тесты и Windows parser; требуется повторный полный прогон.


### 0.1.19 — 2026-10-05 — Spatial Intelligence & OCR 0.7

- Диск Sayuri повышен до `0.7.0`.
- Evidence Engine повышен до `0.7.0`, DNA schema до 4.
- Добавлен `SpatialDNAEngine 0.7.0`.
- PDF spatial extraction переведён на permissive PDFium/pypdfium2.
- Добавлен локальный Tesseract OCR rus+eng с TSV confidence и координатами.
- Факты ДНК получают page/line/bbox locator, когда источник предоставляет реальную геометрию.
- Добавлены spatial quality, OCR page budget и timeout.
- Добавлены table/signature/stamp candidates без автоматического объявления их фактами.
- Схема Диска повышена до 7 и добавлен `disk_dna_spatial`.
- Добавлены internal API spatial status/snapshot и OCR reanalysis.
- Windows bootstrap умеет optional PDFium/Pillow/Tesseract runtime без pip и без блокировки основного запуска при ошибке optional-компонента.
- Preflight отдельно показывает состояние Диск Sayuri.
- Веб-меню не изменялось.


### 0.1.18 — 2026-10-05 — Финальная корректировка старого теста reanalysis

- Исправлен второй оставшийся старый unit-тест, который ожидал безусловный новый анализ от `force=True`.
- Явный повторный анализ теперь корректно использует `bypass_cooldown=True`.
- Код ДНК 0.6 не изменялся.


### 0.1.17 — 2026-10-05 — Корректировка тестового контракта Evolution Core

- Два старых unit-теста обновлены под новый reanalysis cooldown.
- Явный новый анализ в тестах теперь использует `bypass_cooldown=True`.
- Защита от повторных кликов и код ДНК 0.6 не ослаблялись.


### 0.1.16 — 2026-10-05 — DNA Evolution Core 0.6

- Диск Sayuri повышен до `0.6.0`.
- Добавлен отдельный `DNAEvolutionEngine`.
- Добавлена самопроверка фактов, доказательств, canonical values и quality gate.
- Добавлен Regression Guard для защиты от потери уже проверенных фактов.
- Добавлены адаптивные профили по корпусу документов.
- Добавлен lifecycle корректирующих правил: candidate / shadow / active.
- Добавлена лаборатория гипотез повторяющихся связей без автоматического превращения в факты.
- Добавлена очередь Active Learning для важных неопределённых фактов.
- Добавлена техническая метрика накопленного проверяемого опыта.
- Схема Диска повышена до 6.
- Добавлены глобальный реестр сущностей и таблица упоминаний.
- Добавлены API состояния эволюции и плана переанализа.
- Добавлена 10-секундная дедупликация повторного `dna/analyze`.
- Добавлен явный `deep=true` для настоящего повторного глубокого анализа.
- Веб-интерфейс не изменялся.


### 0.1.15 — 2026-10-05 — Исправление ссылок ДНК

- Диск Sayuri повышен до `0.5.1`.
- Исправлена канонизация номера документа: завершающая пунктуация больше не входит в canonical ID.
- Ссылка вида `договор № 55.` теперь корректно сопоставляется с документом `№ 55`.
- Исправление найдено новым тестом dependency resolution; сам тест не ослаблялся.


### 0.1.14 — 2026-10-05 — ДНК 0.5 Structural Intelligence & Safety

- Диск Sayuri повышен до `0.5.0`.
- Интерфейс ДНК не расширялся.
- Добавлен отдельный `dna_advanced.py`.
- Добавлены spatial-ready locators фактов.
- Добавлены Document Schema Engine и Entity Resolution 2.0.
- Добавлены Obligation Engine, временные проверки и зависимости документов.
- Добавлены нормализованный template fingerprint и семейства документов.
- Добавлен корпусный anomaly engine.
- Version delta теперь хранит изменения значений и проценты изменения сумм.
- Добавлены confidence calibration и conservative correction memory.
- Схема Диска повышена до 5.
- Добавлен tamper-evident `disk_dna_ledger`.
- Добавлена защита от prompt injection внутри документов.
- Добавлена классификация чувствительных данных и selective AI context.
- Добавлен knowledge promotion pipeline.
- Добавлена пакетная ДНК папки и внутренние API ledger/package DNA.


### 0.1.13 — 2026-10-05 — Исправление теста ДНК 0.4

- Исправлено устаревшее ожидание версии анализатора в `test_disk.py`: `0.1.0` → `0.4.0`.
- Код ДНК 0.4 не изменялся.

### 0.1.12 — 2026-10-05 — ДНК 0.4 Evidence Engine

- Диск Sayuri повышен до `0.4.0`.
- Интерфейс ДНК не расширялся.
- Анализатор ДНК повышен до `0.4.0`.
- Добавлены стабильные ID фактов, роли, нормализованные значения и evidence hash.
- Добавлена раздельная уверенность извлечения, нормализации и доказательства.
- Добавлены профили документов и контроль обязательных полей.
- Добавлены ИНН/КПП/ОГРН/БИК/счета, организации, ФИО, время, пробег и количество.
- Добавлены действия документа и временная модель.
- Добавлена арифметическая проверка XLSX.
- Добавлены внутренние и междокументные противоречия.
- Добавлены semantic SHA-256, SimHash и token fingerprint.
- Добавлены точные и почти-дубли.
- Добавлен graph-ready слой доказуемых связей.
- Добавлены quality gate, document quality и risk engine.
- Добавлено явное разделение фактов и гипотез.
- Схема Диска повышена до 4.
- Добавлены `disk_dna_history` и `disk_dna_feedback`.
- Добавлены версии ДНК и delta между анализами.
- Переименование/перемещение больше не вызывает повторный анализ содержимого при неизменном SHA-256.
- Добавлены backend API истории ДНК и обратной связи по фактам.

### 0.1.11 — 2026-10-05 — ДНК документа

- Создан базовый структурный слой «ДНК».

### 0.1.10 — 2026-10-05 — Диск Sayuri 0.2.2

- Drag-and-drop, плитки/список и отмена перемещения.
