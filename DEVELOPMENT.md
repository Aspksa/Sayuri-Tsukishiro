# Справочник разработки Sayuri Tsukishiro

Актуальная точка — [PROJECT_STATE.md](PROJECT_STATE.md). Правила версий — [VERSIONING.md](VERSIONING.md).

## Модули

| ID | Имя | Путь | Назначение |
| --- | --- | --- | --- |
| `sayuri-core` | Ядро Саюри | `app/` | SQLite, настройки, API, сервер, диагностика |
| `agent-core` | Агентное ядро | `agent/` | контракт будущего ИИ/памяти/инструментов |
| `sayuri-disk` | Диск Sayuri | `disk/` | профессиональный локальный файловый менеджер |
| `web-ui` | Веб-интерфейс | `web/` | левое меню, Диск Sayuri, настройки |
| `dev-tools` | Инструменты разработки | `scripts/` | версии, тесты, Windows bootstrap |

## Диск Sayuri 0.2

Схема модуля Диска: 2. Она живёт в общей `data/sayuri.db` и использует таблицы:

- `disk_meta`;
- `disk_folders`;
- `disk_files`;
- `disk_actions`.

Бинарные объекты находятся в `data/disk/objects/`, временные загрузки — в `data/disk/temp/`.

### Основные свойства

- UUID вместо пользовательского имени как физического имени файла;
- SHA-256 каждого файла;
- рекурсивный размер папки;
- favorite/trashed/updated metadata;
- мягкое удаление и восстановление;
- история действий;
- выявление дубликатов по SHA-256;
- миграция схемы 1 → 2;
- лимит одного файла 1 ГБ;
- потоковая запись блоками 1 МБ.

### API Диска

- `GET /api/disk?folder_id=&q=&scope=&sort=&direction=&category=`
- `GET /api/disk/actions?limit=N`
- `GET /api/disk/folders-tree`
- `GET /api/disk/items/{file|folder}/{id}`
- `POST /api/disk/folders`
- `POST /api/disk/upload`
- `POST /api/disk/rename`
- `POST /api/disk/move`
- `POST /api/disk/favorite`
- `POST /api/disk/trash`
- `POST /api/disk/restore`
- `POST /api/disk/delete-permanent`
- `GET /api/disk/files/{id}/download`

### Интерфейс

Веб-слой предоставляет «Мой диск», «Избранное», «Недавние», «Корзина», массовый выбор, фильтры, сортировки, очередь загрузки, свойства и окно перемещения. Для процента загрузки используется `XMLHttpRequest.upload.progress`, потому что стандартный Fetch API не даёт стабильный upload progress.

## Проверки

```sh
python -m unittest discover -s app/tests -v
python -m unittest discover -s scripts/tests -v
python -m app.preflight
python -m app.main --no-browser
python scripts/versioning.py check
```

Windows launcher отдельно проверяется в GitHub Actions на `windows-latest`.
