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
