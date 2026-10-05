# Справочник разработки Sayuri Tsukishiro

Актуальная точка состояния — [PROJECT_STATE.md](PROJECT_STATE.md). Правила версий — [VERSIONING.md](VERSIONING.md).

## Рабочая структура

| Путь | Назначение |
| --- | --- |
| `app/` | ядро, конфигурация, SQLite, HTTP-сервер, preflight |
| `app/tests/` | тесты ядра и HTTP |
| `web/` | локальный веб-интерфейс |
| `scripts/` | версионирование и Windows bootstrap |
| `Sayuri Tsukishiro.bat` | пользовательский запуск Windows |
| `data/` | SQLite и runtime-данные, не коммитятся |
| `logs/` | журналы, не коммитятся |
| `.runtime/` | переносимый Python, не коммитится |

## Модули

Внутренние ID остаются стабильными для кода:

- `sayuri-core` → отображается как «Ядро Саюри»;
- `web-ui` → «Веб-интерфейс»;
- `dev-tools` → «Инструменты разработки».

Отображаемые имена находятся в `MODULES.json` в поле `display_name`.

## Запуск на Windows

Двойной щелчок по:

`Sayuri Tsukishiro.bat`

Корень вычисляется относительно BAT, поэтому проект работает независимо от буквы носителя. Реальный запуск подтверждён пользователем с `D:\Sayuri-Tsukishiro-main`.

## Команды разработки

```sh
python -m unittest discover -s app/tests -v
python -m unittest discover -s scripts/tests -v
python -m app.preflight
python -m app.main --no-browser
python scripts/versioning.py show
python scripts/versioning.py check
```

## Runtime

- база: `data/sayuri.db`;
- launcher log: `logs/launcher.log`;
- core log: `logs/sayuri.log`;
- начальный адрес: `http://127.0.0.1:8765`;
- API: `GET /api/health`, `GET /api/events?limit=N`.

## HTTP disconnect

`BrokenPipeError`, `ConnectionResetError`, `ConnectionAbortedError` при записи ответа означают, что локальный клиент уже закрыл соединение. Они обрабатываются отдельно и не должны превращаться в `SAYURI-CORE-500`.
