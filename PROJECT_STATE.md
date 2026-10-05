# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-05, часовой пояс Asia/Vladivostok.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Основная ветка: `main`.
- Проверенная исходная ревизия перед FIX-002: `3855b58baf15ca52b132909e136ae1933ecf1d52`.
- Текущая задача: FIX-002 — совместимость BAT/PowerShell с русским текстом на Windows.
- Версия результата: проект `0.1.4`; `sayuri-core 0.1.1`; `web-ui 0.1.1`; `dev-tools 0.1.3`.

## Причина

На Windows пользователь получил ParserError в `scripts/bootstrap_windows.ps1` и обрывки кириллицы как отдельные команды в CMD. Причина — различная обработка UTF-8 без BOM в Windows PowerShell 5.1 и чтение BAT до применения `chcp 65001`.

## Исправлено в 0.1.4

- `Sayuri Tsukishiro.bat` сделан полностью ASCII-безопасным: до запуска PowerShell в нём нет кириллицы.
- `bootstrap_windows.ps1` сохраняется как UTF-8 с BOM, совместимый с Windows PowerShell 5.1.
- В PowerShell явно задаётся UTF-8 для консольного ввода/вывода.
- Русские сообщения остаются в PowerShell, сайте, preflight и ядре.
- Добавлены тесты: BAT обязан состоять только из ASCII-байтов, PS1 обязан начинаться UTF-8 BOM.
- GitHub Actions дополнен отдельным Windows job: Windows PowerShell парсит bootstrap до публикации, BAT проверяется на ASCII-safe содержимое.

## Версии

- Проект: `0.1.4`.
- Ядро Саюри: `0.1.1`.
- Веб-интерфейс: `0.1.1`.
- Инструменты разработки: `0.1.3`.

## Следующая проверка

После публикации CI должен пройти как на Ubuntu, так и отдельная проверка Windows launcher. Затем пользователь обновляет файлы и повторно запускает `Sayuri Tsukishiro.bat`.
