# Ошибки и диагностика Саюри Цукисиро

## Основные журналы

- `logs/launcher.log` — Windows launcher и предварительная проверка.
- `logs/sayuri.log` — ядро и HTTP-сервер.
- `data/sayuri.db` / `error_events` — настоящие серверные ошибки.

## Ошибка кодировки launcher

Симптомы версии 0.1.3:

- `'�ный' is not recognized as an internal or external command`;
- `The string is missing the terminator`;
- `Missing closing '}'`;
- `The Try statement is missing its Catch or Finally block`.

Причина: Windows CMD может начать разбирать BAT до переключения кодовой страницы, а Windows PowerShell 5.1 неоднозначно читает UTF-8 без BOM.

С версии 0.1.4:

- BAT содержит только ASCII;
- PowerShell bootstrap хранится в UTF-8 с BOM;
- CI отдельно проверяет файл через Windows PowerShell.

Если эти ошибки появляются на 0.1.4+, убедиться, что локальные `Sayuri Tsukishiro.bat` и `scripts/bootstrap_windows.ps1` действительно обновлены.

## WinError 10053

В версии 0.1.2 раннее закрытие локального health-check могло давать `ConnectionAbortedError [WinError 10053]`. С 0.1.3 отключение клиента обрабатывается отдельно и не считается `SAYURI-CORE-500`.

## Коды ошибок

| Код | Значение |
| --- | --- |
| `SAYURI-BOOT-001` | неподдерживаемая архитектура Windows |
| `SAYURI-BOOT-002` | SHA256 Python не совпал |
| `SAYURI-BOOT-003` | повреждённая/неполная распаковка runtime |
| `SAYURI-BOOT-004` | переносимый Python не прошёл проверку |
| `SAYURI-PREFLIGHT-001` | предварительная проверка не пройдена |
| `SAYURI-DB-001` | ошибка SQLite |
| `SAYURI-WEB-003` | локальный сервер не стал готов вовремя |
| `SAYURI-CORE-500` | непредвиденная ошибка ядра |
