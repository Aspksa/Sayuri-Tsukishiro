# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-05, часовой пояс Asia/Vladivostok.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Основная ветка: `main`.
- Проверенная исходная ревизия перед APP-001: `71325557b866f4cd308ceb161632199bf505aa45`.
- Активная задача: APP-001 — первая рабочая версия и каркас приложения.
- Версия результата: проект `0.1.2`; `sayuri-core 0.1.0`; `web-ui 0.1.0`; `dev-tools 0.1.1`.
- GitHub Release не создаётся.

## Реализовано

- Рабочее локальное ядро `app/` на Python standard library.
- SQLite-база `data/sayuri.db` создаётся автоматически; включены foreign keys, WAL, NORMAL synchronous и busy timeout.
- Таблицы `schema_meta`, `system_events`, `error_events`; схема БД версии 1.
- Локальный HTTP-сервер только на `127.0.0.1`; автоматический поиск свободного порта начиная с 8765.
- API первой версии: `GET /api/health`, `GET /api/events?limit=N`.
- Веб-интерфейс `web/` показывает состояние ядра, БД, порта, версии модулей и последние события.
- Защитные HTTP-заголовки, CSP и безопасный DOM-render без вставки данных через `innerHTML`.
- `Sayuri Tsukishiro.bat` запускает PowerShell bootstrap из корня независимо от буквы диска.
- Bootstrap хранит runtime внутри `.runtime/`, поддерживает Windows AMD64 и ARM64, скачивает Python 3.14.8 с python.org и проверяет зафиксированный SHA256 до распаковки.
- Перед запуском выполняется `app.preflight`; после готовности health-check сайт открывается в браузере автоматически.
- Логи: `logs/launcher.log`, `logs/sayuri.log`; структурированные ошибки также пишутся в SQLite.
- Справочник кодов и действий при ошибках: `ERRORS.md`.

## Проверки

| Проверка | Результат | Ограничение |
| --- | --- | --- |
| `python -m unittest discover -s app/tests -v` | 3/3 пройдено | Linux test environment, Python 3.13.5 |
| `python -m unittest discover -s scripts/tests -p 'test_portable_launcher.py' -v` | 3/3 пройдено | Проверяется контракт launcher; Windows BAT/PowerShell здесь не исполнялись |
| `python -m app.preflight` | `status=ok`, SQLite ready, версии прочитаны | Linux test environment |
| HTTP smoke test | `/api/health` = 200, `/` = 200 | Локальный тестовый сервер |
| GitHub Actions | Проверить после публикации коммита | Workflow должен прогнать version tooling, app tests и preflight |

## Ограничения первой рабочей версии

- AI-провайдер, чат, личность, память знаний и инструменты агента ещё не реализованы.
- Windows bootstrap требует интернет при первом получении runtime; после сохранения `.runtime/python` повторный запуск не требует повторной загрузки.
- Полный запуск `Sayuri Tsukishiro.bat` на ноутбуке пользователя пока не проверен из текущего Linux-окружения.
- Сервер намеренно не доступен из локальной сети: внешняя публикация без отдельной модели auth/authorization запрещена.

## Точка остановки

APP-001 реализована и проверена в доступном окружении. После публикации требуется проверить фактический HEAD и GitHub Actions. Следующий логичный этап — CORE-002: API состояния/настроек и границы будущего Agent Core, затем подключение модели и памяти отдельными модулями.
