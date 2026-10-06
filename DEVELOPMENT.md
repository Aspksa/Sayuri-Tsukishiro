# Справочник разработки Sayuri Tsukishiro

Актуальная точка — [PROJECT_STATE.md](PROJECT_STATE.md). Правила версий — [VERSIONING.md](VERSIONING.md).

## Диск Sayuri 0.5 — ДНК Structural Intelligence & Safety

### Версии

- схема Диска: `5`;
- базовый анализатор ДНК: `0.5.0`;
- advanced engine: `0.5.0`;
- JSON-схема базовой ДНК: `3`.

### Файлы

- `disk/dna.py` — базовый Evidence Engine;
- `disk/dna_advanced.py` — внутренние слои 0.5;
- `disk/service.py` — кэш, версии, междокументный корпус, ledger, correction memory и package DNA;
- `app/server.py` — локальные API.

### Новые таблицы схемы 5

```text
disk_dna_ledger
  file_id
  sequence_no
  event_type
  created_at
  payload_sha256
  previous_chain_hash
  chain_hash
  details_json

disk_dna_correction_rules
  fact_type
  original_canonical
  corrected_json
  supporting_files_json
  support_count
  updated_at
```

Существующие `disk_dna`, `disk_dna_history` и `disk_dna_feedback` сохраняются.

### Advanced pipeline

```text
base evidence
→ spatial locator
→ learned correction (>=3 distinct files)
→ calibration
→ document schema
→ entity resolution
→ obligations
→ temporal checks
→ dependencies
→ security
→ sensitive classification
→ template fingerprint
→ knowledge promotion
→ selective AI context
→ dynamic cross-document/corpus enrichment
→ history + ledger
```

### Trust boundary

Содержимое документа всегда имеет `trust_domain=document_content`.

Фраза внутри файла не может:
- изменить системные инструкции;
- включить инструмент;
- заставить раскрыть секрет;
- повысить свой уровень доверия.

### Ledger

Каждый анализ и feedback создают элемент hash-chain. `dna_ledger()` пересчитывает payload hash и цепочку и возвращает `valid`.

Это tamper-evident журнал, а не WORM-хранилище.

### Correction Memory

Правило автокоррекции применяется только при:
- одинаковом типе факта;
- одинаковом исходном canonical value;
- одинаковом исправленном значении;
- поддержке минимум трёх различных file_id.

### API

- `GET /api/disk/files/{id}/dna`
- `POST /api/disk/files/{id}/dna/analyze`
- `GET /api/disk/files/{id}/dna/history?limit=N`
- `POST /api/disk/files/{id}/dna/feedback`
- `GET /api/disk/files/{id}/dna/ledger?limit=N`
- `GET /api/disk/package-dna?folder_id=...&analyze_missing=0|1`

### Ограничения

- координаты PDF/изображения требуют OCR;
- semantic AI не подключён;
- package DNA при `analyze_missing=1` выполняется синхронно;
- background worker в DISK-005 намеренно не включён.

## Проверки

```sh
python -m unittest discover -s app/tests -v
python -m unittest discover -s scripts/tests -v
python -m app.preflight
python scripts/versioning.py check
```

Windows launcher отдельно проверяется GitHub Actions.

## Диск Sayuri 0.6 — DNA Evolution Core

### Версии

- схема Диска: `6`;
- Evolution Core: `0.6.0`;
- базовый Evidence Engine остаётся `0.5.0`;
- Advanced DNA остаётся `0.5.0`.

### Новый модуль

`disk/dna_evolution.py`

Контуры:
- `self_review`;
- `adaptive_profile`;
- `regression_guard`;
- `rule_lifecycle`;
- `hypotheses`;
- `active_learning`;
- `experience`.

### Новые таблицы

```text
disk_dna_entities
  entity_id
  category
  canonical_id
  display_name
  first_seen_at
  last_seen_at
  document_count
  confidence
  attributes_json

disk_dna_entity_mentions
  file_id
  entity_id
  fact_ids_json
  evidence_json
  confidence
  updated_at
```

### Reanalysis cooldown

`REANALYZE_COOLDOWN_SECONDS = 10`.

`document_dna(..., force=True)` возвращает кэшированный результат, если предыдущий анализ того же SHA/анализатора был менее 10 секунд назад.

`document_dna(..., force=True, bypass_cooldown=True)` всегда выполняет новый анализ.

HTTP:
- обычный `POST /dna/analyze` — защищён от дублей;
- `POST /dna/analyze` с `{"deep": true}` — обход cooldown.

### Evolution API

- `GET /api/disk/dna/evolution`
- `GET /api/disk/dna/reanalysis-plan?limit=N`

Оба API диагностические и не добавлены в пользовательское меню.

### Границы

- Evolution Core не является самостоятельной LLM.
- Он не создаёт причинность из корреляции.
- Он не запускает автоматический массовый переанализ.
- Он не меняет пользовательские документы.
- OCR и реальный AI остаются отдельными слоями.

## Диск Sayuri 0.7 — Spatial Intelligence

### Версии

- схема Диска: `7`;
- DNA schema: `4`;
- Evidence Engine: `0.7.0`;
- Advanced DNA: `0.5.1`;
- Evolution Core: `0.6.0`;
- Spatial DNA: `0.7.0`.

### Runtime

Windows bootstrap закрепляет:
- `pypdfium2==5.13.0`;
- `Pillow==12.3.0`;
- Tesseract OCR `5.5.3` для автоматического AMD64 runtime;
- tessdata `4.1.0` `rus+eng`.

Wheel/binary/language files проверяются SHA-256.

Python embeddable получает дополнительный путь:
`..\\packages`.

### Spatial storage

```text
disk_dna_spatial
  file_id PK/FK
  sha256
  engine_version
  analyzed_at
  spatial_json
```

### Spatial limits

- MAX_PAGES = 120
- MAX_OCR_PAGES = 24
- OCR_DPI = 220
- OCR_TIMEOUT_SECONDS = 75
- MAX_NATIVE_CHARS_PER_PAGE = 120000
- MAX_LINES_PER_PAGE = 4000

### API

- `GET /api/disk/dna/spatial`
- `GET /api/disk/files/{id}/dna/spatial`
- `GET /api/disk/files/{id}/dna/spatial?ocr=1`
- `POST /api/disk/files/{id}/dna/analyze`:
  - `{"ocr": true}`
  - `{"deep": true}`

### Evidence

Spatial locator:

```json
{
  "page": 1,
  "line_id": "p1-ocr-l4",
  "line": 4,
  "bbox": {
    "space": "points",
    "values": [40, 120, 280, 142],
    "normalized": [0.066, 0.15, 0.466, 0.177]
  },
  "extraction_method": "ocr",
  "coordinate_status": "exact_from_document_engine"
}
```

### Ограничения

- Tesseract auto-install в bootstrap предусмотрен только для AMD64; ARM64 использует найденный внешний OCR либо работает без OCR.
- table/signature/stamp detection 0.7 создаёт кандидаты, а не подтверждённые semantic entities.
- реальный vision/LLM слой не подключён.

## Sayuri UI 0.12 — Unified Visual System

Канонический визуальный слой находится в конце `web/styles.css` и имеет маркер:

`SAYURI UI 0.12 — Unified Visual System`

### Font stack

```text
UI:
Segoe UI Variable Text
Segoe UI Variable
Segoe UI
system-ui

Display:
Segoe UI Variable Display
Segoe UI Variable
Segoe UI

Mono:
Cascadia Code
Cascadia Mono
Consolas
```

Внешняя загрузка web-font не используется, поэтому локальный запуск остаётся автономным.

### Typography baseline

- body: 14 px / 1.5;
- secondary: обычно 11.5–12.5 px;
- button: около 13 px;
- h1: 25 px;
- h2: 31 px;
- h3: 20 px;
- hero h2: clamp 32–45 px.

### Compatibility

Legacy selectors всё ещё присутствуют для Диска и системных компонентов. Канонический слой расположен последним и задаёт итоговые значения через cascade.

Compatibility aliases:
- `--text -> --ui-text`;
- `--muted -> --ui-muted`;
- `--line -> --ui-line`.

### Verification

- Python UI contract проверяет unified visual system и отсутствие удалённого device-интерфейса.
- Workflow выполняет `node --check web/app.js`.

## Архитектура после 0.1.36

Активные прикладные контуры разработки: `app/`, `agent/`, `disk/`, `web/`, `scripts/`.

Windows bootstrap устанавливает переносимый Python и optional Spatial/OCR runtime. Удалённая Android/device-интеграция не является частью runtime или API проекта.

## Sayuri Personal AI 0.1

### Runtime

Agent runtime находится в `agent/runtime.py`.

Фиксированные значения:

- provider: Cloud.ru Foundation Models;
- base URL: `https://foundation-models.api.cloud.ru/v1`;
- model: `deepseek-ai/DeepSeek-V4-Flash`.

Внешний Python SDK не требуется: запросы выполняются стандартной библиотекой через HTTPS.

### Secret boundary

`SecretStore` хранит ключ отдельно от системных настроек.

- `SAYURI_CLOUDRU_API_KEY` имеет приоритет;
- локальный файл: `data/sayuri-cloudru.secret`;
- Windows: DPAPI;
- development/CI на других ОС: локальный файл `0600`;
- наружу возвращается только маска.

Никогда не добавлять ключ в `.env.example`, тестовые fixtures, логи, события или Git.

### API

- `GET /api/sayuri/profile`
- `POST /api/sayuri/provider`
- `POST /api/sayuri/provider/test`
- `POST /api/sayuri/chat`

### UI

Глобальные компоненты находятся в `web/index.html`, `web/app.js`, `web/styles.css`.

- `#sayuri-orb` — плавающий аватар;
- `#sayuri-context-menu` — правый клик;
- `#sayuri-chat-window` — плавающий чат;
- `#view-sayuri` — Личный кабинет;
- `web/assets/sayuri-avatar.svg` — канонический пользовательский образ.

Положение аватара/чата и история сохраняются только в browser localStorage и могут быть отключены в Личном кабинете.

### Context boundary

В AI отправляется только структурированный интерфейсный контекст:
- активный раздел;
- route/hash;
- состояние Диска;
- имя/id выбранного объекта при открытом viewer.

Содержимое файла, OCR, ДНК и факты документа в stage 1 автоматически не передаются.

### Проверки

Кроме общего CI должны оставаться проверки:
- secret roundtrip + masking;
- фиксированного provider/model;
- Sayuri profile API;
- отсутствие полного ключа в ответе;
- web contract глобального аватара, кабинета, chat/provider endpoints;
- `node --check web/app.js`.

## Sayuri Memory 0.1

Реализация: `agent/memory.py`.

Хранилище: `data/sayuri-memory.db`.

Граница областей обязательна: каждая запись имеет `scope=personal|project`. Контекст для LLM сериализуется отдельными массивами. Нельзя превращать содержимое памяти в system instructions.

API:
- `GET /api/sayuri/memory`;
- `POST /api/sayuri/memory`;
- `DELETE /api/sayuri/memory/{id}`.

Deterministic intake:
- `запомни лично: ...` → personal;
- `запомни в проект: ...` → project.

Остальной чат автоматически не индексируется в долговременную память.

## Sayuri Avatar Studio 0.1

Реализация: `agent/avatar.py`.

Локальная директория: `data/sayuri-avatars/`.

Слоты:
- orb — 192×192;
- chat — 256×256;
- profile — 512×512;
- hero — 1024×1024.

При загрузке:
- максимум 8 МБ;
- только PNG/JPEG/WebP;
- проверяется сигнатура содержимого;
- имя локального файла строится по SHA-256;
- исходное пользовательское имя не используется как путь.

API:
- `GET /api/sayuri/avatars`;
- `GET /api/sayuri/avatar/{slot}`;
- `POST /api/sayuri/avatar/upload?slot=...`;
- `DELETE /api/sayuri/avatar/{slot}`.

## Sayuri Safe Actions 0.1

Реализация брокера: `agent/actions.py`.

Хранилище: `data/sayuri-actions.db`.

Поток:

```text
text + UI context
-> deterministic plan
-> pending action
-> user confirm
-> atomic claim
-> core tool executor
-> completed/failed audit
```

Allowlist stage 1:
- `disk.create_folder`;
- `disk.set_favorite`;
- `disk.trash_current`;
- `disk.move_current`;
- `memory.remember`.

Инварианты безопасности:
- все tools имеют `confirmation_required=true`;
- TTL pending action = 10 минут;
- payload сериализуется канонически и получает SHA-256;
- `BEGIN IMMEDIATE` защищает claim от двойного конкурентного confirm;
- `completed/cancelled/expired/failed` нельзя повторно исполнять;
- core выполняет только известный tool ID;
- LLM не вызывает executor напрямую.

API:
- `GET /api/sayuri/actions`;
- `POST /api/sayuri/actions/plan`;
- `POST /api/sayuri/actions/{id}/confirm`;
- `POST /api/sayuri/actions/{id}/cancel`.

UI:
- `.sayuri-action-proposal` — карточка подтверждения в чате;
- `#sayuri-tool-list` — allowlist в Личном кабинете;
- `#sayuri-actions-history` — локальный журнал.

## DNA Upload Reliability 0.1

Версии:
- project `0.1.40`;
- disk `0.7.1`;
- web `0.17.0`.

Web flow:

```text
uploadOneFile()
-> file persisted
-> loadDisk()
-> analyzeUploadedDna()
-> POST /api/disk/files/{id}/dna/analyze
-> row status + cached DNA
```

Автоанализ применяется только к форматам, для которых ДНК имеет практический смысл: PDF, text/config/data, Office Open XML, ODF и основные изображения.

Ключевой инвариант: успешная загрузка файла не откатывается из-за ошибки анализатора. Ошибка ДНК возвращается как отдельное состояние UI.

Viewer flow:
- `setDnaLoadState('loading')` перед запросом;
- `ready` после успешного анализа;
- `error` с текстом backend-ошибки и retry-кнопкой;
- `viewerDnaLoadedFor` выставляется только после успешного ответа.

Spatial diagnostics использует `capabilities.pdfium_available`. Старое имя `pymupdf_available` для текущего PDFium engine некорректно.

Следующее архитектурное улучшение — вынести тяжёлый OCR в persisted background queue с page-level progress. Это не входит в `0.1.40`.

## Memory Intelligence 2.0

Реализация: `agent/memory_intelligence.py`.

Хранилище использует ту же локальную SQLite БД `data/sayuri-memory.db`.

Таблицы:
- `memory_candidates`;
- `memory_intelligence_settings`.

Дополнительные поля `memory_entries`:
- `source_context_json`;
- `confidence`;
- `supersedes_id`.

Pipeline:

```text
user message
-> deterministic classifier
-> scope/kind/confidence
-> duplicate/conflict comparison
-> candidate
-> user review
-> SayuriMemory.add()
```

По умолчанию:
- `candidate_generation=true`;
- `conflict_detection=true`;
- `context_linking=true`;
- `auto_save_high_confidence=false`;
- `auto_save_threshold=0.96`.

High-confidence autosave intentionally разрешён только для `scope=project`, `kind=fact`. Он не применяется к personal, preference, decision или task.

API:
- `GET /api/sayuri/memory/candidates`;
- `POST /api/sayuri/memory/candidates/{id}/review`;
- `GET /api/sayuri/memory/intelligence`;
- `POST /api/sayuri/memory/intelligence`.

Memory context для LLM остаётся разделённым на personal/project и передаётся как недоверенные справочные данные.

## Semantic Memory & Experience Learning 0.1

### Semantic Memory

Реализация: `agent/semantic_memory.py`.

Engine: `hybrid-semantic-v1`.

Он использует Python stdlib и существующую SQLite memory DB. Новый внешний AI API не добавлен.

Scoring:
- token overlap;
- light stemming;
- concept expansion;
- character 3-gram cosine;
- phrase bonus;
- importance/confidence weighting.

`SemanticMemoryIndex.context()` возвращает personal/project отдельно и является каноническим memory-context для чата.

### Experience Learning

Реализация: `agent/experience.py`.

Хранилище: `data/sayuri-experience.db`.

Experience events дедуплицируются fingerprint. Повторный outcome одного action или повторная feedback-оценка одного response не должны размножать записи.

Стратегия имеет сглаженный success rate Beta(1,1) и evidence strength. Confidence adjustment включается после трёх meaningful outcomes и ограничен ±0.08.

Relevant experience извлекается тем же прозрачным semantic scorer и разделяется на:
- `helpful`;
- `avoid`.

В prompt это передаётся отдельным system-data блоком с запретом трактовать опыт как факт или инструкцию.

### Chat feedback

Cloud response получает `response_id`.

`POST /api/sayuri/experience/feedback` принимает:
- response_id;
- rating `useful|not_useful`;
- prompt;
- answer excerpt;
- безопасный UI context.

Prompt ограничивается 2000 символами, excerpt ответа — 1200. Полная browser chat history в experience DB не записывается.

### Проверки

- `python3 -m unittest discover -s app/tests -v`;
- `node --check web/app.js`;
- `python3 -m app.preflight`;
- `python3 scripts/versioning.py check --each-commit`.

При работе через GitHub API функциональные проверки промежуточной ветки выполняются до атомарной сборки релиза. Итоговый release commit обязан отдельно пройти полный workflow Versions.

## Semantic Memory 0.1

Реализация: `agent/semantic_memory.py`.

Engine: `hybrid-semantic-v1`.

Цель текущего этапа — улучшить retrieval локальной памяти без второй облачной модели и без тяжёлого embedding-runtime.

Используемые признаки:
- token overlap;
- light stemming;
- локальный словарь доменных concepts;
- character 3-grams;
- importance/confidence weighting.

Это **не neural embeddings**. В UI и документации нельзя называть текущий engine нейросетевой vector memory.

Поведение:
- `GET /api/sayuri/memory` без `q` возвращает обычный список;
- при `q=...` используется Semantic Memory;
- chat memory-context формируется через Semantic Memory;
- retrieval сохраняет области `personal/project`;
- сеть и Cloud.ru для retrieval не требуются.

## Experience Learning 0.1

Реализация: `agent/experience.py`.

Хранилище: `data/sayuri-experience.db`.

`experience_events` хранит category, strategy, outcome, reward, source, subject ID, безопасный context, ограниченные details и timestamps.

Поддерживаемые исходы:
- положительные: `success/accepted/useful/corrected_success`;
- отрицательные: `failure/rejected/not_useful/corrected_failure`;
- нейтральные: `produced/cancelled/expired`.

### Feedback

Каждый реальный DeepSeek-ответ получает локальный `response_id`.

`POST /api/sayuri/experience/feedback` принимает:
- `response_id`;
- `rating=useful|not_useful`;
- `prompt`;
- `answer`;
- безопасный UI-context.

В Experience DB сохраняются ограниченные `prompt` и `answer_excerpt`, а не полный чат.

Fingerprint feedback не зависит от rating: пользователь может изменить оценку того же ответа без создания второй записи.

### Strategy calibration

`ExperienceStore.strategy_stats()` применяет Beta(1,1) smoothing.

`confidence_adjustment()`:
- не применяется до 3 значимых исходов;
- учитывает evidence strength;
- ограничен диапазоном ±0.08.

Memory Intelligence использует adjustment только как небольшую калибровку deterministic confidence.

### Relevant experience

Перед AI-запросом `ExperienceStore.context(query)` локально ищет релевантный подтверждённый опыт через hybrid semantic scorer.

В модель передаются отдельные массивы:
- `helpful`;
- `avoid`.

Experience context является недоверенными справочными данными и не может расширять permissions, менять system prompt или считаться доказательством факта.

### Проверки

Обязательные проверки:
- related wording находится без точной фразы;
- boundary `personal/project` сохраняется;
- feedback idempotent и допускает пересмотр;
- action replay не создаёт duplicate experience;
- confidence adjustment требует evidence и остаётся bounded;
- Memory Intelligence учитывает review history;
- релевантный положительный/отрицательный опыт разделяется;
- chat runtime получает Semantic Memory и Experience context без реального сетевого вызова в тесте.

## Memory 3.0

Реализация: `agent/memory_v3.py`.

Используется существующая `data/sayuri-memory.db`; отдельный новый внешний сервис не требуется.

Таблицы:
- `working_memory`;
- `episodic_memory`;
- `knowledge_items`;
- `memory_graph_nodes`;
- `memory_graph_edges`;
- `memory_timeline`;
- `memory_conflicts`;
- `memory_consolidations`;
- `memory_v3_meta`.

### Working Memory

`update_working()` записывает `current_focus` и безопасный `current_context`.
TTL по умолчанию 24 часа. Истёкшие rows удаляются автоматически из working contour.

### Knowledge promotion

`ingest_memory()`:
1. синхронизирует graph nodes/edges;
2. обрабатывает provenance текущего документа;
3. строит supersedes/mentions links;
4. вызывает promotion только при достаточной importance/confidence/use evidence.

Knowledge item хранит исходные memory IDs.

### Consolidation

`consolidate()` работает только внутри одинаковых `scope/kind`.

Threshold: `0.72` по `SemanticMemoryIndex.score()`.

Она не удаляет исходные memories и не вызывает LLM. Канонической формулировкой становится запись с лучшим importance/confidence/use-count.

### Retention

`evaluate_retention()` рассчитывает 0..1 из:
- importance 38%;
- confidence 22%;
- use score 20%;
- recency 20%.

Важные decisions получают floor 0.82, важные preferences — 0.72.

`SemanticMemoryIndex.search()` применяет retention multiplier `0.70 + retention*0.30`.

Для large local memory semantic retrieval использует `scan_active(scope=..., limit<=5000)`, а не только первые 300 rows из пользовательского списка. Scope-фильтр применяется до scoring.

### Conflict resolver

После принятия candidate с `relation=conflict` runtime регистрирует old/new memory pair.

Разрешения:
- `prefer_new`;
- `prefer_old`;
- `keep_both`.

Проигравшая memory переводится в `active=0`, то есть мягко архивируется. Связанные confirmed knowledge items получают `valid_to`.

Перед показом конфликта обе memory гарантированно materialized в graph и получают edge `conflicts_with`. Архивированный graph node не удаляется: metadata обновляется до `active=false` с `archived_at`, чтобы граф сохранял temporal history.

### Automation

Startup:
- `bootstrap()`;
- `maybe_maintain(interval_hours=6)`.

Manual:
- `POST /api/sayuri/memory/v3/maintenance`.

Dashboard endpoint не запускает тяжёлую maintenance и остаётся read-only.

### AI context

`MemorySystemV3.context(query)` возвращает:
- working;
- semantic-ranked confirmed knowledge;
- semantic-ranked episodes;
- количество открытых конфликтов.

Этот JSON отправляется DeepSeek как недоверенный system-data block, отдельно от personal/project Semantic Memory и Experience Learning.

### Обязательные тесты

- Working Memory и context-linking;
- knowledge promotion;
- graph document provenance;
- consolidation сохраняет source IDs;
- retention снижает retrieval weight без удаления;
- conflict resolver мягко архивирует выбранную неактуальную память;
- timeline сохраняет conflict lifecycle;
- API dashboard/maintenance/conflict resolution;
- Web UI Memory 3.0 contract;
- полный versioning check на атомарном release commit.

Graph extraction дополнительно создаёт company nodes для консервативно распознанных ООО/АО/ПАО/ИП и event nodes для эпизодической памяти. Это локальные детерминированные сущности, без LLM entity extraction.

### Idempotency episodic

`episodic_memory.fingerprint` имеет частичный UNIQUE index. Для chat feedback используется `chat_feedback:{response_id}`, для Safe Action — `action:{action_id}`, для review candidate — `memory_candidate:{candidate_id}`. Retry обновляет существующий эпизод вместо создания дубля. Точный повтор без изменения payload не создаёт новый timeline event; изменившийся повтор фиксируется как `episode_updated`.

### Archive propagation

Ручное удаление memory выполняется как soft archive исходной записи. Memory 3.0 затем:
- удаляет архивированный source ID из knowledge, если есть другие активные источники;
- иначе переводит knowledge в `archived` и ставит `valid_to`;
- сохраняет timeline события.

AI-context открытого конфликта содержит ограниченные old/new значения и отдельный точный `open_conflicts` count.

Graph source-memory nodes всегда сохраняют реальный label исходной записи. Технические fallback-подписи вроде «Источник знания» не могут перезаписать существующий содержательный label.

## Memory 4.x

Реализация: `agent/memory_v4.py`.

Memory 4.x использует существующую `data/sayuri-memory.db` и не вводит внешнюю vector DB, embedding API или вторую LLM. Начиная с `0.1.46`, поверх hardening включён `Memory 4.1 Quality Gate`.

### Таблицы

- `memory_v4_state` — trust/freshness/utility/tier/sensitivity per memory;
- `memory_source_trust` — эмпирическое и ручное доверие к источникам;
- `memory_goals`;
- `memory_tasks`;
- `memory_decision_records`;
- `memory_failures`;
- `memory_causal_links`;
- `memory_questions`;
- `memory_recall_audit`;
- `memory_response_recall`;
- `memory_audit_log`;
- `memory_snapshots`;
- `memory_v4_meta`.

### Recall pipeline

```text
query
-> Semantic Memory candidates
-> Memory 4.0 state
-> source trust
-> freshness
-> utility
-> hot/warm/cold tier
-> sensitivity/cloud policy
-> instruction-risk quarantine
-> final score
-> diversity selection
-> context budget
-> explanation
-> successful Cloud response
-> recall audit
```

Cloud recall использует `for_cloud=True`. Secret/sensitive memories и high-risk instruction-like content отбрасываются до формирования JSON для DeepSeek. Локальный пользовательский поиск по-прежнему может показать quarantined запись с объяснением причины.

Начиная с `0.1.45`, privacy firewall применяется ко всем memory-derived blocks перед Cloud.ru:
- Memory 4.0 personal/project recall;
- Memory 3.0 working/knowledge/episodes/conflicts;
- Experience Learning helpful/avoid details;
- Goal Memory;
- Task Memory;
- Failure Memory;
- Question Memory.

Если производная сущность связана с source memory, имеющей `cloud_allowed=false`, она также исключается.

Локальный поиск Личного кабинета использует `for_cloud=False, record_usage=False`. Он может показывать защищённую запись с badge `LOCAL ONLY`, но не увеличивает `memory_entries.use_count`, `memory_v4_state.recall_count` и не создаёт `memory_recall_audit`.

Chat runtime использует two-phase recall:
1. `MemorySystemV4.context(..., record_usage=False)` готовит ranked context и private `_prepared_recall`;
2. выполняется Cloud.ru request;
3. только после успешного ответа `commit_prepared_recall()` увеличивает usage counters, создаёт recall audit и возвращает `recall_id`;
4. `response_id` связывается с committed recall.

Provider/network/timeout error до шага 3 не меняет usage/utility signals памяти.

### Utility feedback

Каждый chat response связывается с конкретным `recall_id`.

Feedback корректирует:
- helpful/unhelpful counters выбранных memories;
- utility score.

Generic «Полезно / Не помогло» **не меняет Source Trust**: полезность ответа не является доказательством истинности исходного документа или OCR. Source Trust изменяется только отдельной проверкой/ручным override. При пересмотре rating предыдущий utility-вклад сначала вычитается.

### Memory 4.1 Quality Gate

Quality Gate добавляет поверх v0.1.45 четыре независимых механизма.

1. **Instruction-risk quarantine.** `memory_v4_state` хранит `instruction_risk` и `instruction_risk_score`. High-risk directives получают local-only policy. `_cloud_text_allowed()` применяет тот же барьер к Memory 3.0 и Experience-derived blocks.
2. **Diversified Recall.** После relevance ranking выполняется greedy selection с semantic redundancy penalty и небольшим same-source penalty. Это не меняет текст или базовый score в БД.
3. **Verification Queue.** Maintenance после пересчёта states через SQLite JOIN создаёт idempotent Question Memory для важных volatile memories с freshness < 0.45 и важных records с source trust < 0.45.
4. **Bounded Context.** Direct recall ограничен `CLOUD_RECALL_CHAR_BUDGET=9000`, Goal/Task/Failure/Question context — `CLOUD_AUX_CHAR_BUDGET=7000`. Длинные поля сокращаются только в outbound payload.

Критический attribution invariant: `_prepared_recall` пересобирается **после** diversity/budget selection. Поэтому после успешного Cloud-ответа usage/feedback получают только memories, фактически вошедшие в model context.

### Goals / Tasks

Goal и Task — структурированные состояния, а не обычные notes.

Task хранит `next_action` и `blocked_reason`.

Goal/task nodes синхронизируются с Memory 3 Knowledge Graph.

### Decision Memory

`kind=decision` создаёт decision record.

Rationale/alternatives извлекаются только из явных языковых маркеров. Если причины нет — поле остаётся пустым.

### Failure / Causal Memory

Safe Action failure создаёт fingerprint по strategy/tool + symptom.

Повтор усиливает occurrences.

Поздний успешный action той же strategy **не закрывает** failure автоматически. Он создаёт только correlation-only observation:

`failure -> followed_by_success -> action`

с confidence `0.45`.

Доказанное закрытие выполняется только через explicit user-confirmed resolution:
- cause — если известна;
- resolution — обязательна;
- prevention — если известна.

API: `POST /api/sayuri/memory/v4/failures/{id}/resolve`.

Повтор одинакового resolution идемпотентен. Если тот же failure fingerprint возникает снова после resolved state, pattern автоматически переоткрывается, сохраняя прошлое resolution/prevention как историческое знание.

### Question Memory

Open conflict Memory 3 создаёт вопрос с old/new memory IDs.

Question закрывается после явного conflict resolution пользователя.

### Snapshots

Snapshot создаётся через SQLite online backup API в:

`data/memory-snapshots/`

Manifest хранит SHA-256.

Restore:
- требует exact string `RESTORE MEMORY`;
- проверяет hash;
- создаёт automatic pre-restore snapshot;
- восстанавливает SQLite через backup API;
- повторно инициализирует schemas;
- запускает integrity check.

### Integrity

Проверяются:
- SQLite `PRAGMA integrity_check`;
- orphan graph edges;
- dangling task → goal;
- confirmed knowledge с отсутствующим memory source;
- orphan response → recall.

### API

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

### Invariants

- trust/freshness/utility affect ranking, not stored truth;
- generic answer feedback affects utility, never factual Source Trust;
- high instruction-risk memory remains local-only and cannot execute as instruction;
- context budget/truncation never mutates the original stored memory;
- secrets cannot be re-enabled for Cloud through Source Trust;
- personal/project scopes remain separated;
- question is not knowledge;
- later success is correlation-only evidence until user-confirmed resolution;
- local UI recall never trains utility/use counters;
- failed Cloud calls never commit prepared recall usage;
- `cloud_allowed=false` applies transitively to every memory-derived Cloud-context;
- snapshots remain local under `data/`;
- restore never happens implicitly;
- Memory 4.0 cannot extend Action Broker permissions.

### Verification

Required release checks:
- `python3 -m unittest discover -s scripts/tests -v`;
- `python3 -m unittest discover -s app/tests -v`;
- `node --check web/app.js`;
- `python3 -m app.preflight`;
- `python3 scripts/versioning.py check --each-commit` on atomic release commit;
- Windows launcher workflow.



## Reasoning Planner + Result Verifier 0.1

Реализация: `agent/reasoning.py`, интеграция runtime — `agent/runtime.py`.

### Pipeline

```text
user task
→ deterministic complexity gate
→ [direct] answer
→ или [planned] Planner JSON
→ answer with structured plan
→ Result Verifier JSON
→ optional revised_answer
→ commit Memory 4.1 recall usage
```

### Structured plan

Planner возвращает только:
- `goal`;
- `steps`;
- `constraints`;
- `evidence_needed`;
- `done_when`;
- `risk_level`.

Это task-control artifact, а не chain-of-thought.

### Complexity gate

Gate локальный и deterministic. Он учитывает архитектурные/аналитические маркеры, длину, многошаговый формат, количество ограничений и document context. Простая беседа остаётся в `direct` режиме с одним Cloud.ru вызовом.

### Result Verifier

Verifier получает:
- исходную задачу;
- structured plan;
- основной ответ;
- уже Cloud-safe evidence context.

Результат:
- `pass` — ответ остаётся как есть;
- `revise` — используется полный `revised_answer`;
- `unavailable` — основной ответ сохраняется, но UI не показывает ложный статус проверки.

### Safety

- единственная внешняя модель: `deepseek-ai/DeepSeek-V4-Flash`;
- Planner/Verifier не расширяют Action Broker permissions;
- memory/document content остаётся недоверенными данными;
- chain-of-thought не сохраняется;
- recall attribution остаётся post-budget и commit-ится после успешного пользовательского ответа.

### Проверки

- direct/planned complexity gate;
- нормализация Planner/Verifier JSON;
- три model calls для planned режима;
- verifier revision применяется как финальный answer;
- direct режим использует один model call;
- Web chat показывает только structured reasoning summary.

## Evidence-aware Tool Planner 0.1

Реализация: `agent/tool_planner.py`; интеграция: `agent/reasoning.py`, `agent/runtime.py`.

### Pipeline

```text
planned task
→ Planner JSON + tool_intents
→ deterministic tool policy
→ read-only execution / mutation block
→ execution receipts + evidence refs
→ primary answer
→ Result Verifier with receipts
→ post-success Memory 4.1 attribution
```

### Read-only allowlist

- `system.status`;
- `memory.stats`;
- `memory.search`;
- `memory.integrity`;
- `experience.stats`;
- `context.current_document`.

Максимум 4 read-only вызова на planned request. Повтор одинакового tool+args не исполняется второй раз.

### Mutation boundary

Все IDs из `agent.actions.TOOL_DEFINITIONS` видны Planner как `confirmation_gated`, но Evidence Tool Planner не имеет mutation handler. Он создаёт receipt `requires_action_broker`. Изменение состояния по-прежнему выполняется только отдельным Action Broker после явного confirm.

### Receipts

SQLite: `data/sayuri-tool-receipts.db`.

Receipt содержит:
- request ID и step index;
- tool/mode;
- нормализованные args;
- status;
- started/finished/duration;
- evidence refs;
- SHA-256 output;
- sanitized preview;
- error class/message.

Диагностика: `GET /api/sayuri/tools/receipts?limit=N`.

### Privacy и Memory attribution

`memory.search` вызывает Memory 4.1 с `for_cloud=True` и `record_usage=False`. IDs реально отправленной tool-memory объединяются с обычным prepared recall. Commit usage выполняется только после успешного answer/verifier pipeline.

Tool evidence перед Cloud.ru ограничивается budget 9000 chars. Поля API key/password/authorization/cookie/token-like secrets удаляются до receipt preview и Cloud-context.

### Проверки

- allowlist и unknown-tool rejection;
- mutation isolation;
- duplicate suppression;
- secret sanitization;
- execution receipt persistence;
- planned runtime остаётся на трёх model calls;
- direct runtime остаётся на одном model call;
- Result Verifier получает execution evidence;
- API/Web contract.



## Background Evidence Automation 0.2

Начиная с проекта `0.1.49`, Evidence-aware Tool Planner остаётся внутренним execution/evidence слоем и не визуализируется как каталог инструментов.

### Automatic evidence selection

После Planner локальная deterministic policy анализирует `goal` и `evidence_needed`. Если модель не указала явный read-only intent, policy может добавить безопасную проверку из существующего allowlist:

- memory/project/history semantics -> `memory.search`;
- system/version/provider semantics -> `system.status`;
- integrity/SQLite semantics -> `memory.integrity`;
- current/open document semantics -> `context.current_document`;
- experience/previous failure semantics -> `experience.stats`.

Модель не получает право добавить новый tool ID. Этот слой не выводит mutation intent из текста автоматически.

### API response boundary

Для planned chat наружу возвращается только:

```text
reasoning.automation
  status
  read_only_checks
  evidence_receipts
  blocked_mutations
```

Полные receipts остаются в локальном `data/sayuri-tool-receipts.db` и в диагностическом API, а Result Verifier получает bounded evidence internally.

### UI policy

- нет tool catalog в Личном кабинете;
- нет receipt rows в chat reasoning summary;
- при фактической фоновой проверке показывается только `автопроверка N`;
- подтверждаемые mutation actions и их история сохраняются;
- меню не меняется.

### Evidence budget

Перед Cloud.ru каждый output ограничивается отдельно. Oversized output заменяется объектом `{truncated:true, excerpt_json:...}`, затем весь evidence-list укладывается в общий 9000-char budget. Локальный SHA-256 считается по sanitized полному output до Cloud truncation.


## Sayuri Presence UX 0.26

Релиз проекта: `0.1.50`.

### Floating avatar

Аватар Sayuri больше не обновляет `left/top` на каждом `pointermove`.

Pipeline:

```text
pointerdown
→ threshold 5px
→ pointer capture
→ pointermove
→ requestAnimationFrame
→ translate3d()
→ viewport clamp
→ pointerup
→ one-time left/top commit
→ one-time localStorage write
```

Это уменьшает layout/reflow во время движения и устраняет ощущение «залипания».

Local state:

- `sayuri-orb-position` — финальная позиция аватара;
- `sayuri-chat-position` — финальная позиция окна;
- `sayuri-chat-size` — ширина/высота окна;
- `sayuri-account-tab` — активная вкладка кабинета;
- `sayuri-memory-tab` — активный подраздел памяти.

### Floating chat

Desktop:

- default около 560×720;
- min 420×480;
- max ограничивается viewport;
- drag только за header;
- resize через `#sayuri-chat-resize`;
- размер сохраняется после `pointerup`;
- кнопка `#sayuri-chat-reset-size` сбрасывает только размер.

Mobile <=640 px:

- окно занимает безопасную область с отступом 6 px;
- manual resize отключён;
- сохранённый desktop size не ломает mobile layout.

Composer автоматически меняет высоту через `scrollHeight` до 180 px.

### Personal cabinet

Левого navigation entry больше нет. Доступ:

- ЛКМ по orb -> chat;
- ПКМ по orb -> context menu;
- context action `account` -> `showView('sayuri')`.

Top-level tabs:

`profile | ai | behavior | memory | appearance | diagnostics`.

Memory sub-tabs:

`overview | architecture | quality | experience`.

Скрытие выполняется нативным `hidden` на `data-sayuri-panel` и `data-sayuri-memory-panel`, поэтому функции остаются в DOM и существующие API/loaders не переписываются.


## UI System & Chat Polish 0.27

Релиз проекта: `0.1.51`.

### Command palette

DOM:

- `#command-palette-backdrop`;
- `#command-palette-input`;
- `#command-palette-list`.

Shortcut: `Ctrl+K` / `Cmd+K`.

Команды остаются локальными UI actions: chat, personal cabinet, home, disk, settings, memory и maximize chat. Новых backend permissions command palette не создаёт.

### Fullscreen chat

`toggleSayuriChatMaximize()` переключает класс `.is-maximized` на существующем `#sayuri-chat-window`.

- отдельного chat instance нет;
- history/composer остаются теми же;
- drag/resize блокируются в maximized mode;
- Esc возвращает floating mode до закрытия chat;
- desktop fullscreen сохраняет ограниченную читаемую ширину message stream/composer.

### Message actions

`renderSayuriMessages()` добавляет локальный action «Копировать». Clipboard failure не ломает message tree и показывается transient toast.

### Status policy

Постоянные значения:

- `Размышляет…`;
- `Готова`;
- `Нужно подтверждение`;
- `Ошибка`;
- `Запомнила локально`.

Подробности model/memory/reasoning остаются в metadata и reasoning summary, но не занимают постоянную status line.

### Product tokens

UI 0.27 расширяет существующий UI 0.12:

- `--ui-space-*`;
- `--ui-radius-*`;
- `--ui-shadow-*`;
- `--ui-duration-*`;
- surface/text/line/focus tokens.

### Accessibility

- command palette keyboard navigation: Up/Down/Enter/Escape;
- focus-visible для button/a/input/select/textarea/summary;
- `prefers-reduced-motion: reduce`;
- fullscreen и palette работают без декоративной animation dependency.


## Rich Answer UX & Lazy Diagnostics 0.28

Релиз проекта: `0.1.52`.

### Safe rich renderer

Основные функции Web UI:

- `appendSayuriInline()`;
- `renderSayuriRichText()`;
- `createSayuriCodeBlock()`;
- `createSayuriEvidenceSummary()`.

Renderer строит DOM через `createElement`, `createTextNode` и `textContent`. Не заменять его на `innerHTML` без отдельной security-модели и sanitizer.

Поддерживаются:

- paragraphs и line breaks;
- `#..####` headings, визуально маппятся внутрь chat hierarchy;
- unordered/ordered lists;
- blockquotes;
- inline code;
- fenced code + language label + copy;
- Markdown tables;
- bold/emphasis/strike;
- Markdown links только `http://` / `https://`;
- horizontal rules.

### Public evidence

`SayuriAgent._public_evidence()` строит пользовательский evidence projection из технического контекста.

Document evidence создаётся только из completed receipt `context.current_document`, но UI не получает имя инструмента/receipt/hash.

Schema:

```json
{
  "kind": "document",
  "label": "Договор.pdf",
  "ref": "ui:current-document:<id>",
  "target": {"type": "disk_item", "kind": "file", "id": "<id>"}
}
```

Memory evidence агрегируется по scope и содержит только label/count/ref scope.

### Lazy memory loading

Runtime state Web UI:

- `sayuriState.loadedSections`;
- `sayuriState.loadingSections`.

`ensureSayuriMemoryTabLoaded()` предотвращает повторный initial fetch и сопоставляет вкладки:

- overview → memory + candidates;
- architecture → Memory V3;
- quality → Memory V4;
- experience → Experience.

`refreshLoadedSayuriDiagnostics()` используется после mutations и не активирует ранее не открытые тяжёлые панели.

Skeleton state: `.sayuri-lazy-loading`, `aria-busy`.

### Security regression

Web contract должен проверять, что участок `renderSayuriRichText` не содержит `innerHTML`. Backend regression должен проверять, что public evidence не содержит `receipt:` и `sha256:`.


## Spatial Evidence Citations 0.1.53

### Версии

- Project: `0.1.53`.
- Core: `0.1.45`.
- Agent Core: `0.11.0`.
- Web UI: `0.29.0`.
- Disk: `0.8.0`.
- SpatialDNAEngine: `0.8.0`.
- DB schema и DNA JSON schema не меняются.

### Pipeline

```text
complex document question
→ Reasoning Planner
→ document.evidence_search (read-only)
→ cached disk_dna facts only
→ quality + exact locator gate
→ Memory 4.1 privacy/instruction filter
→ bounded D1..D6 evidence to Cloud.ru
→ answer with supported [D#]
→ Result Verifier
→ runtime removes unknown D#
→ public evidence metadata
→ click citation
→ file_id + fact_id
→ backend resolves stored locator
→ PDFium/Pillow Evidence Focus
```

### Read-only evidence search

`DiskService.search_cached_evidence(file_id, query, limit<=6)`:

- читает только существующий `disk_dna.dna_json`;
- не вызывает `document_dna()`;
- не запускает OCR;
- не обновляет cache/version/ledger;
- исключает rejected facts;
- требует exact Spatial locator;
- ранжирует локально по token overlap, phrase match, quality gate и confidence.

### Cloud boundary

`SayuriCore._sayuri_document_evidence_handlers()` владеет доступом к DiskService, потому что Agent Core не получает прямой файловый доступ.

Перед Cloud удаляются:

- bbox;
- физический path;
- raw receipt metadata;
- rejected/local-only evidence.

Остаются citation_id, безопасный fact/excerpt, page/line, quality/confidence.

### Citation firewall

D-ID имеют фиксированный формат `D1..D6`.

`SayuriAgent._strip_unknown_spatial_citations()` удаляет marker, которого нет в фактически выполненном `document.evidence_search`.

Public `evidence` содержит `target={type:"disk_evidence",file_id,fact_id}`, но не raw bbox.

### Evidence Focus

API:

`GET /api/disk/files/{file_id}/evidence-focus?fact_id={fact_id}`

Endpoint не принимает координаты. `DiskService.render_evidence_focus()`:

1. читает cached DNA;
2. находит exact fact_id;
3. проверяет non-rejected + exact locator;
4. локально передаёт сохранённый bbox SpatialDNAEngine;
5. возвращает PNG page/image с жёлтой подсветкой.

Для PDF используется PDFium, для image — Pillow. Если точной геометрии нет, endpoint отказывает вместо приблизительной подсветки.

### Web UI

- `[D1]` внутри safe rich renderer становится `.sayuri-inline-citation` только при наличии matching public evidence.
- нижний Evidence Summary показывает D-ID, документ, page/line и excerpt;
- клик открывает существующий Disk viewer и заменяет preview на Evidence Focus;
- «Обычный просмотр» возвращает штатный preview;
- menu/navigation structure не изменяется.


## Visual Refinement & Workspace UX 0.30

Релиз проекта: `0.1.54`.

### Версии

- Project: `0.1.54`.
- App/Core contract: `0.1.46`.
- Web UI: `0.30.0`.
- Agent Core: без изменений.
- Disk: без изменений.

### AI workspace

`toggleSayuriChatMaximize()` по-прежнему работает на единственном `#sayuri-chat-window`, но UI 0.30 добавляет класс `body.sayuri-workspace-open`.

Workspace mode:

- скрывает floating avatar от взаимодействия;
- показывает `#sayuri-workspace-badge`;
- сохраняет тот же message history/composer/context;
- ограничивает читаемую ширину ответов;
- использует sticky composer;
- Esc возвращает floating mode существующим keyboard contract.

При `openSayuriSpatialEvidence()` maximized chat сначала возвращается в floating mode, затем открывается Disk viewer.

### Avatar magnet

После обычного smooth drag:

```text
pointerup
→ commit compositor position
→ calculate distance to 4 viewport edges
→ if nearest edge <= bounded threshold
   → snap only to that edge
→ persist final position once
```

Threshold ограничен и не действует на mobile <=640px.

### Presence state

`setSayuriPresenceState()` устанавливает только визуальное состояние:

- `ready`;
- `thinking`;
- `attention`;
- `error`;
- `offline`.

Thinking animation существует только пока выполняется запрос и отключается через `prefers-reduced-motion`.

### Compact density

Local storage: `sayuri-compact-ui`.

CSS class: `body.ui-compact`.

Меняются padding/gap/min-height карточек и рабочих поверхностей; основной font-size ответов и long-form content не уменьшается.

### Unified UI states

`createUiState(kind, title, detail)` строит DOM через `createElement/textContent`.

Используется для:

- initial Disk loading;
- Disk empty/error;
- file preview loading/error;
- empty table preview;
- unsupported preview;
- empty command palette.

Disk использует `aria-busy` через `setDiskLoading()`.

### Command palette recent

До трёх последних command IDs хранятся в `sayuri-command-recent`. При пустом поиске они выводятся первыми. Повреждённое/не-массивное localStorage состояние не ломает palette.

### Regression contracts

`app/tests/test_web_contract.py` проверяет:

- sidebar не изменён и не содержит `sayuri-account-nav`;
- density/workspace DOM;
- magnet/presence/state/recent JS;
- UI 0.30 CSS;
- viewer/disk workspace surfaces;
- сохранение Spatial Evidence перехода.


## Sayuri 0.1.55 — Goal Continuity & Workspace Quality

### Goal Continuity

`MemorySystemV4.continuity_context(query, limit)` является read-only projection. Он:

1. берёт только active goals и задачи со статусом `planned / in_progress / blocked`;
2. повторно применяет memory/cloud privacy boundary;
3. ранжирует задачи по priority, status и token-overlap с текущим запросом;
4. возвращает `selected_task`, `selected_goal`, bounded списки и счётчики;
5. не меняет статусы, utility, use counters или task timestamps.

Reasoning Planner 0.4 получает continuity snapshot отдельно от UI и evidence context. Continuation-маркеры сами по себе не делают любой короткий запрос сложным: planned-mode включается только при наличии selected task/goal.

Evidence Tool Planner 0.3 разрешает `memory.continuity` только как read-only tool. Mutation payload по-прежнему не принимается от LLM.

### Workspace keyboard contract

- Command Palette сохраняет исходный focus и возвращает его после закрытия.
- Maximized chat выставляет `aria-modal=true` и удерживает Tab/Shift+Tab внутри dialog.
- При возврате во floating mode `aria-modal=false`.
- Avatar не участвует в tab-order, пока workspace maximized.
- На viewport <=760px maximized chat занимает доступный экран без rounded outer shell; floating chat ограничивается отступом 8px.
- Основной размер текста compact/responsive режимами не уменьшается.

### Проверки

К обычному workflow добавлены regressions в:
- `app/tests/test_memory_v4.py`;
- `app/tests/test_reasoning.py`;
- `app/tests/test_tool_planner.py`;
- `app/tests/test_web_contract.py`.

Новых runtime dependencies нет.


## Sayuri 0.1.56 — Task Lifecycle & Checkpoints

### Persistent checkpoint model

`memory_task_checkpoints` хранится в той же `data/sayuri-memory.db`, что Goal/Task Memory. Checkpoint содержит:
- `task_id / goal_id / action_id`;
- монотонный `sequence_no` внутри задачи;
- tool и action title;
- task status + next_action до и после;
- SHA-256 полного подтверждённого action result;
- безопасную локальную evidence summary;
- флаг `applied` и причину применения/отказа.

Полный action result не включается в cloud-facing resume projection.

### Link policy

`SayuriAgent.plan_action()` самостоятельно строит Goal Continuity snapshot и удаляет любой входной `_task_lifecycle` из пользовательского context. Внутренняя связь с task создаётся только когда:

1. selected task имеет status `planned` или `in_progress`;
2. текущая action-команда имеет реальный token overlap с title / next_action / goal;
3. task snapshot сохраняет `updated_at` и `next_action_before` для optimistic stale-state guard.

Blocked task автоматически не связывается с mutation lifecycle.

### Confirm policy

`SayuriAgent.complete_action()` сначала завершает Action Broker action, затем передаёт только `completed` result в `checkpoint_confirmed_action()`.

Автоматическое продвижение разрешено только если сохранённый snapshot всё ещё совпадает с текущей task state. Тогда:
- status становится `in_progress`;
- `next_action` получает deterministic tool-specific follow-up;
- task никогда автоматически не становится `done`.

Если task была изменена, заблокирована или закрыта, checkpoint может быть записан как доказательство прошлого action, но актуальная task state не переписывается.

### Restart restoration

`MemorySystemV4.continuity_context()` читает latest checkpoint выбранной задачи и возвращает bounded `resume` projection. Новый процесс Sayuri после повторной инициализации получает тот же selected task, checkpoint и актуальный `next_action` из SQLite.

Reasoning Planner 0.5 использует checkpoint только как подтверждение конкретного Action Broker шага. Он не может из checkpoint вывести `done`, разблокировать task или выполнить mutation.

### Regression coverage

- checkpoint idempotency по `action_id`;
- stale-state protection;
- restart restoration;
- internal-only Action Broker context;
- core confirm → checkpoint → next_action integration;
- Reasoning public capability flag.

Новых внешних зависимостей нет.


## Sayuri 0.2.0 — Cognitive Project Brain

### Architecture

`CognitiveProjectBrain` is a deterministic orchestration layer above `MemorySystemV4`; it does not replace Goal/Task Memory and it does not own direct tool execution.

Data flow:

`MODULES.json / task context → project+module scope → task graph → scheduler → Planner read-only context → Action Broker → checkpoint → strategy/evaluation state`

### Multi-project and multi-module contract

- `MODULES.json` schema 1-compatible metadata accepts `project_key`, `capabilities`, and `depends_on` metadata.
- Existing modules without an explicit project remain under `sayuri-tsukishiro`.
- A task may carry `context.project_key` and `context.module_key`.
- New project/module keys are registered by trusted local code during task synchronization; the LLM cannot register them through a tool intent.
- Cognitive tables live in the same WAL-enabled `sayuri-memory.db` so restart recovery is atomic with Memory 4.x state.

### Task Graph

`cognitive_task_edges` stores explicit relations:
- `requires`: source waits for target;
- `follows`: source may run only after target;
- `blocks`: source blocks target until source is done;
- `unlocks`: source must be done before target becomes actionable.

`scheduler()` excludes tasks with unresolved blockers. Dependency state is derived from Memory 4 task status and is never inferred from model prose.

### Completion Criteria

`cognitive_task_scope.completion_criteria_json` supports bounded criteria:
- `checkpoint_count`;
- `tool_completed` based on applied Memory 4 task checkpoints;
- `dependency_done`;
- `manual_confirmation`.

A full match produces `ready_for_completion_confirmation`. It never writes `status=done`.

### Scheduler and attention

Ranking uses task priority, planned/in_progress status, token overlap, project/module affinity, dependency blockers, open uncertainty severity, completion readiness and attention state. Output is bounded to eight candidates for cloud context.

### Uncertainty, replanning and strategy memory

- confirmed Action Broker failure increments strategy failure statistics;
- the same failure creates an uncertainty record with evidence needed;
- a plan revision is stored as `proposed` only;
- no failure path silently rewrites Memory 4 `next_action`;
- completed/failed actions update Bayesian-smoothed strategy confidence.

### Self-evaluation and metacognition

Self-evaluation is deterministic and read-only by default. It reports task totals, open/done counts, dependency blockers, completion-ready tasks and uncertainties.

Metacognitive states are: `idle`, `actionable`, `blocked`, `uncertain`, `replan_required`, `criteria_missing`, `ready_for_completion_confirmation`, `missing_task`.

### LLM boundary

- `cognition.status` and `cognition.next` are read-only Evidence Tool Planner tools.
- read-only tool calls do not synchronize or mutate cognitive tables.
- synchronization occurs at initialization, trusted task creation/update, chat ingestion, or action planning before policy selection.
- Planner/Verifier receive a cloud-safe bounded cognition projection.
- no cognitive signal grants direct mutation execution.

### Public diagnostics

`GET /api/sayuri/cognition?q=<query>` returns local status, scheduler/metacognition context and project self-evaluation. No mutating cognition endpoint is exposed.

### Regression coverage

`app/tests/test_cognition.py` covers manifest scoping, multiple projects/modules, dependencies, completion criteria, failure replanning, strategy memory, restart persistence and read-only status behavior.


## Sayuri 0.2.1 — Cognitive Brain Hardening 1.1

### Stable project/module context

Все task-producing модули используют единый bounded context contract:

```json
{
  "project_key": "sayuri-tsukishiro",
  "module_key": "sayuri-disk",
  "milestone": "optional",
  "labels": ["optional"],
  "completion_criteria": []
}
```

`normalize_task_context()` нормализует ключи. Для существующего UI используются только локальные aliases: `disk/drive/dna -> sayuri-disk`, `sayuri/chat -> agent-core`, `home/settings/system -> sayuri-core`.

### Synchronization ownership

`sync_tasks()` является registration sync, а не reconciliation writer. Если `cognitive_task_scope` уже существует, sync не меняет `attention_state`, `confidence`, `completion_criteria` или `plan_revision`. Управляемое состояние меняется только explicit local API или подтверждённым lifecycle.

### Task Graph invariants

- direct task edge разрешён только внутри одного project scope;
- confirmed edge не может создавать dependency cycle;
- `confirmed=false` edge хранится как гипотеза/черновик, но не блокирует scheduler;
- legacy invalid graph не исправляется молча.

### Completion and checkpoints

`completion_assessment()` считает только checkpoints с `applied=true`. Неактуальный/stale checkpoint остаётся evidence прошлого action, но не засчитывается как прогресс criteria. Наличие unresolved dependency имеет приоритет над fulfilled criteria.

Если configured criteria ещё не дали `ready_for_confirmation`, explicit local попытка `status=done` отклоняется. Даже `ready_for_confirmation` не выставляет `done` автоматически.

### Replan application

Failure создаёт `cognitive_plan_revisions.status=proposed`. Применение требует:

1. явного local confirmation `APPLY_REPLAN`;
2. status proposal всё ещё `proposed`;
3. текущий Memory 4 `next_action` равен `previous_next_action` proposal.

После успешного apply proposal становится `accepted`. LLM tools для apply отсутствуют.

### Conservative causal lineage

`cognitive_causal_links` хранит только локально наблюдаемые связи:
- confirmed completed action -> task checkpoint;
- confirmed failed action -> replan proposal;
- confirmed failed action -> uncertainty.

Эти edges означают provenance/trigger lineage, а не доказательство общей причинности проблемы.

### Multi-module isolation

`uncertainties()` и `strategies()` поддерживают `module_id` filter. Module-scoped self-evaluation не смешивает uncertainty другого модуля того же проекта. Cognitive cloud context получает только компактные project/module identifiers и безопасные titles; path/metadata остаются локальными.

### Local cognition API

Read-only:
- `GET /api/sayuri/cognition?q=...&project_key=...&module_key=...`.

Explicit local mutations:
- `POST /api/sayuri/cognition/projects`;
- `POST /api/sayuri/cognition/modules`;
- `POST /api/sayuri/cognition/dependencies`;
- `POST /api/sayuri/cognition/tasks/{task_id}/criteria`;
- `POST /api/sayuri/cognition/uncertainties/{id}/resolve`;
- `POST /api/sayuri/cognition/replans/{id}/apply` with `confirmation=APPLY_REPLAN`.

Эти endpoints не входят в Evidence Tool Planner catalog и не доступны модели как direct tools.

### Regression coverage

- managed scope preservation;
- cycle/cross-project guards;
- unconfirmed dependency behavior;
- applied checkpoint criteria;
- explicit completion guard;
- replan confirmation + stale state;
- uncertainty resolution;
- conservative causal lineage;
- module-scoped evaluation;
- Cloud metadata boundary;
- runtime/API contract.


## Sayuri 0.2.2 — Portfolio Milestones & Scalable Scheduler

### Portfolio coordination

`CognitiveProjectBrain 1.2` сохраняет project-local task DAG и добавляет отдельный межпроектный контур:

`source project milestone → external blocker → dependent project/module/task`.

Прямой cross-project task edge остаётся запрещён. Это не даёт одному глобальному графу случайно связать и заблокировать все проекты.

### Milestones

- milestone имеет stable key внутри проекта;
- membership хранит required/optional task links;
- readiness вычисляется из Memory 4 task status;
- `done` требует `COMPLETE_MILESTONE`;
- никакой LLM output, checkpoint или score не завершает milestone автоматически.

### External blockers

- blocker может быть project-, module- или task-scoped;
- source milestone другого проекта разрешён как доказуемое внешнее условие;
- source milestone `done` меняет только effective state blocker при чтении;
- persistent blocker record остаётся в истории;
- manual blocker закрывается explicit resolution.

### Batched scheduler

Planning cycle читает task scopes, projects, modules, confirmed edges, open uncertainties, applied checkpoints, milestones и external blockers одним cognitive SQLite snapshot. Per-task N+1 SQL path устранён из scheduler/self-evaluation/metacognition.

Scheduler учитывает project priority и active milestone priority. Explicit project context является hard scope; module context — affinity, чтобы разрешать prerequisites соседнего модуля.

### Safety gates

- high uncertainty запрещает автоматическую Action Broker lifecycle-привязку к task;
- task/external blockers имеют приоритет над completion readiness;
- deep graph integrity запускается явно и не утяжеляет обычный health-status;
- Cloud projection остаётся bounded и не содержит module path/metadata.

### Capacity

`MAX_TASKS` повышен до 5000; `sync_tasks()` сначала пакетно получает уже зарегистрированные task scopes и добавляет только отсутствующие.

### API

Добавлены local-only endpoints milestones/external blockers. Они не входят в Evidence Tool Planner catalog и не доступны DeepSeek как mutation tools.
