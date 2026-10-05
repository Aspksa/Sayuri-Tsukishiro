# Справочник разработки Sayuri Tsukishiro

Актуальная точка — [PROJECT_STATE.md](PROJECT_STATE.md). Правила версий — [VERSIONING.md](VERSIONING.md).

## Диск Sayuri 0.4 — ДНК Evidence Engine

### Версии

- схема Диска: `4`;
- версия анализатора ДНК: `0.4.0`;
- JSON-схема ДНК: `2`.

### Таблицы

```text
disk_dna
  current snapshot

disk_dna_history
  file_id
  version_no
  sha256
  source_updated_at
  analyzer_version
  analyzed_at
  dna_json

disk_dna_feedback
  file_id
  fact_id
  action
  corrected_value_json
  note
  created_at
```

При миграции существующий current snapshot автоматически становится первой исторической версией, если история для файла ещё отсутствует.

### Evidence model

Каждый факт имеет:

```text
id
type
label
role
value
normalized
confidence
confidence_breakdown
status
quality_gate
source.line
source.excerpt
source.evidence_hash
```

Stable ID строится из типа, канонического значения, роли, строки и хэша доказательства.

### Нормализация

Поддерживается канонизация:

- дат;
- денежных сумм;
- процентов;
- пробега;
- количества и единиц;
- ИНН;
- КПП;
- ОГРН/ОГРНИП;
- БИК;
- расчётного/корреспондентского счёта;
- VIN;
- госномера;
- e-mail;
- телефона;
- времени;
- организации;
- ФИО;
- номера документа.

### Document Profiles

Профили определяют `required`, `expected` и `singleton_roles`.

Профили есть для служебной записки, путевого листа, договора, счёта-оферты, счёта, приказа, распоряжения, выписки ГСМ, акта, накладной и общего документа.

### Arithmetic Engine

Для preview mode `table` ищутся колонки:

- количество;
- цена;
- сумма/стоимость/итого.

Для строк с числовыми значениями проверяется:

```text
quantity * price == total
```

с небольшим допуском. Несовпадение является критическим риском.

### Fingerprint

ДНК хранит:

- `semantic_sha256`;
- `simhash64`;
- до 256 token hashes;
- количество токенов и уникальных токенов.

Fingerprint не заменяет физический SHA-256.

### Междокументная сверка

При чтении ДНК current snapshot динамически сравнивается с другими активными ДНК:

- exact duplicate;
- near duplicate;
- related;
- shared canonical entities.

Для документов одного типа с одинаковым номером сравниваются итоговая сумма, дата документа, ИНН, VIN и госномер.

### Quality Gate

`memory_ready` может быть true только если:

- физическая целостность подтверждена;
- есть accepted facts;
- нет критических рисков;
- нет внутренних противоречий;
- нет междокументного противоречия.

### Версионность

Каждый полный анализ создаёт `version_no` и `version_delta`.

Delta содержит:

- added facts;
- removed facts;
- changed types;
- classification changed;
- profile completeness delta;
- reason: initial/content_changed/analyzer_upgrade/reanalyzed.

Переименование и перемещение при неизменном SHA-256 переиспользуют контентный анализ.

### Feedback API

Движок уже умеет хранить и применять:

- `confirm`;
- `reject`;
- `correct`.

Это backend-возможность; визуальный интерфейс в DISK-004 не добавлялся.

### API

- `GET /api/disk/files/{id}/dna`
- `POST /api/disk/files/{id}/dna/analyze`
- `GET /api/disk/files/{id}/dna/history?limit=N`
- `POST /api/disk/files/{id}/dna/feedback`

### Безопасность и ограничения

- исходный файл не изменяется;
- Office/ODF XML ограничен существующим безопасным лимитом;
- макро-форматы DOCM/XLSM/PPTM помечаются risk rule;
- PDF/изображение без текста требует OCR;
- inference между сущностями не создаётся без семантического слоя;
- отдельный background worker пока не реализован: pipeline выполняется синхронно.

## Проверки

```sh
python -m unittest discover -s app/tests -v
python -m unittest discover -s scripts/tests -v
python -m app.preflight
python scripts/versioning.py check
```
