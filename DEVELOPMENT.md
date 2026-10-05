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
