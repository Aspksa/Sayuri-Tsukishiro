# Справочник разработки Sayuri Tsukishiro

Актуальная точка — [PROJECT_STATE.md](PROJECT_STATE.md). Правила версий — [VERSIONING.md](VERSIONING.md).

## Диск Sayuri 0.3.0 — ДНК документа

### Схема данных

Версия схемы Диска: `3`.

Новая таблица:

```text
disk_dna
  file_id             PRIMARY KEY → disk_files.id
  sha256
  source_updated_at
  analyzer_version
  analyzed_at
  dna_json
```

Удаление файла каскадно удаляет его ДНК.

### Анализатор

Файл: `disk/dna.py`.

Текущая версия анализатора: `0.1.0`.

Анализатор полностью локальный и не вызывает внешний ИИ. Он строит:

- identity;
- classification;
- anatomy;
- molecules;
- entity candidates;
- checks;
- integrity;
- stages;
- summary.

Молекулы содержат `type`, `label`, `value`, `confidence` и `source` с номером строки и фрагментом.

### Кэш

`DiskService.document_dna(file_id)` возвращает существующую ДНК, если совпадают:

- SHA-256;
- `updated_at` источника;
- версия анализатора.

`force=True` перестраивает ДНК независимо от кэша.

### API

- `GET /api/disk/files/{id}/dna`
- `POST /api/disk/files/{id}/dna/analyze`

### UI

Центральный просмотр файла:

```text
Просмотр | ДНК | Свойства
```

ДНК содержит:
- процент локального изучения;
- тип документа;
- 4 ключевые метрики;
- pipeline стадий;
- раскрываемую анатомию;
- молекулы;
- кандидаты сущностей;
- проверки;
- будущий семантический слой связей.

### Ограничения

- PDF/изображения без текстового слоя пока требуют OCR.
- Семантические отношения, роли и междокументные противоречия требуют будущего ИИ-слоя.
- ДНК не модифицирует оригинальный файл.

### Защита Office/ODF

XML внутри ZIP-контейнеров ограничен `16 MiB` для локального предпросмотра и ДНК. Это снижает риск чрезмерного распаковывания повреждённого или злонамеренного файла.

## Проверки

```sh
python -m unittest discover -s app/tests -v
python -m unittest discover -s scripts/tests -v
python -m app.preflight
python scripts/versioning.py check
```

Windows launcher отдельно проверяется GitHub Actions.
