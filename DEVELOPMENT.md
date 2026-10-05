# Справочник разработки Sayuri Tsukishiro

Актуальная точка — [PROJECT_STATE.md](PROJECT_STATE.md). Правила версий — [VERSIONING.md](VERSIONING.md).

## Модули

| ID | Имя | Путь | Назначение |
| --- | --- | --- | --- |
| `sayuri-core` | Ядро Саюри | `app/` | SQLite, настройки, API, сервер, диагностика |
| `agent-core` | Агентное ядро | `agent/` | контракт будущего ИИ/Memory/Tool исполнения |
| `sayuri-disk` | Диск Sayuri | `disk/` | локальное файловое хранилище |
| `web-ui` | Веб-интерфейс | `web/` | левое меню, главная, Диск Sayuri, настройки |
| `dev-tools` | Инструменты разработки | `scripts/` | версии, тесты, Windows bootstrap |

## Системная база данных

Файл: `data/sayuri.db`.

Системная schema 2 содержит `schema_meta`, `system_events`, `error_events`, `system_settings`. Модуль «Диск Sayuri» хранит собственную схему версии 1 в таблицах `disk_meta`, `disk_folders`, `disk_files`.

## Хранилище «Диск Sayuri»

- Объекты: `data/disk/objects/`.
- Временные загрузки: `data/disk/temp/`.
- Реальные имена файлов не используются как имена объектов на диске.
- Идентификаторы файлов и папок — UUID.
- Для каждого файла хранится SHA-256.
- Максимальный размер одного файла в версии 0.1.6 — 1 ГБ.
- Чтение/запись выполняются блоками по 1 МБ.
- `data/` не коммитится в Git.

## API

Система:
- `GET /api/health`
- `GET /api/system`
- `GET /api/settings`
- `POST /api/settings`
- `GET /api/events?limit=N`

Диск Sayuri:
- `GET /api/disk?folder_id=<id>&q=<поиск>`
- `POST /api/disk/folders`
- `POST /api/disk/upload?folder_id=<id>`
- `GET /api/disk/files/{id}/download`
- `DELETE /api/disk/files/{id}`
- `DELETE /api/disk/folders/{id}`

Загрузка использует тело запроса как поток файла; имя передаётся URL-кодированным в заголовке `X-Sayuri-Filename`.

## Запуск и проверки

На Windows: `Sayuri Tsukishiro.bat`.

```sh
python -m unittest discover -s app/tests -v
python -m unittest discover -s scripts/tests -v
python -m app.preflight
python -m app.main --no-browser
python scripts/versioning.py check
```

Windows launcher дополнительно проверяется GitHub Actions на `windows-latest`.
