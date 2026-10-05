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


## Телефон Sayuri 0.1

### Каталог

```text
phone/
  VERSION
  __init__.py
  service.py
```

### Runtime

Windows AMD64:
- scrcpy `4.1`;
- официальный архив `scrcpy-win64-v4.1.zip`;
- источник: `Genymobile/scrcpy`;
- SHA-256: `5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db`;
- локальный путь: `.runtime/phone/scrcpy/`.

Runtime optional: ошибка скачивания не блокирует запуск Sayuri.

### API

```text
GET  /api/phone
POST /api/phone/pair
POST /api/phone/connect
POST /api/phone/disconnect
POST /api/phone/control/start
POST /api/phone/control/stop
```

Payload pairing:

```json
{"address":"192.168.1.20:37125","pairing_code":"123456"}
```

Payload connect:

```json
{"address":"192.168.1.20:39587"}
```

Control:

```json
{"serial":"R58M123ABC"}
```

### Security boundary

- нет shell-строк;
- subprocess получает argv;
- pairing address валидируется как host:port;
- pairing code — ровно 6 цифр;
- управление разрешено только для устройства, которое присутствует в текущем `adb devices -l` и имеет state `device`;
- сервер Sayuri остаётся `127.0.0.1`.

### UI

Отдельный view `#phone`:
- runtime status;
- список устройств;
- USB-инструкция;
- Wireless Debugging pairing;
- connect/disconnect;
- open/stop control.

0.1 не содержит embedded browser stream.
