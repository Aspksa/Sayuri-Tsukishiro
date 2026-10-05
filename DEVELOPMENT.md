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

## Memory 4.0

Реализация: `agent/memory_v4.py`.

Memory 4.0 использует существующую `data/sayuri-memory.db` и не вводит внешнюю vector DB, embedding API или вторую LLM.

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
-> final score
-> explanation
-> recall audit
```

Cloud recall использует `for_cloud=True`. Secret/sensitive memories отбрасываются до формирования JSON для DeepSeek.

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
- utility score;
- evidence/correction counters source profile;
- bounded empirical source trust.

При пересмотре rating предыдущий вклад сначала вычитается.

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

