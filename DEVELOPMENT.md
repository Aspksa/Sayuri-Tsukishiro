# Справочник разработки Sayuri Tsukishiro

Актуальная точка — [PROJECT_STATE.md](PROJECT_STATE.md). Правила версий — [VERSIONING.md](VERSIONING.md).

## Модули

| ID | Имя | Путь | Назначение |
| --- | --- | --- | --- |
| `sayuri-core` | Ядро Саюри | `app/` | SQLite, настройки, API, сервер, диагностика |
| `agent-core` | Агентное ядро | `agent/` | контракт AI/Memory/Tool исполнения |
| `web-ui` | Веб-интерфейс | `web/` | левое меню, главная, настройки |
| `dev-tools` | Инструменты разработки | `scripts/` | версии, тесты, Windows bootstrap |

## База данных

Файл: `data/sayuri.db`. Schema 2 содержит `schema_meta`, `system_events`, `error_events`, `system_settings`.

## API CORE-002

- `GET /api/health` — краткое состояние.
- `GET /api/system` — единое состояние системы и архитектура.
- `GET /api/settings` — текущие настройки и их спецификации.
- `POST /api/settings` — сохранение проверенных значений.
- `GET /api/events?limit=N` — последние события.

## Agent Core

`agent/contract.py` задаёт структуры `AgentRequest`, `AgentResult` и snapshot состояния. В CORE-002 выполнение выключено; AI-провайдер, память и инструменты подключаются позже отдельными слоями.

## Запуск и проверки

На Windows: `Sayuri Tsukishiro.bat`.

```sh
python -m unittest discover -s app/tests -v
python -m unittest discover -s scripts/tests -v
python -m app.preflight
python -m app.main --no-browser
python scripts/versioning.py check
```

Windows launcher дополнительно проверяется в GitHub Actions на `windows-latest`.
