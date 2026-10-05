# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-05.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Ветка разработки удаления: `remove-phone-sayuri`.
- Проверенная исходная ревизия: `2175a4c22b5143a08c628a542579ecd7f5dbca3a` (проект `0.1.35`).
- Текущая задача: `REM-001` — удалить из проекта ненужный Android/телефонный контур целиком.
- Целевая версия результата: проект `0.1.36`.

## Версии активных модулей после REM-001

- Ядро Саюри: `0.1.28`.
- Агентное ядро: `0.1.0`.
- Диск Sayuri: `0.7.0`.
- Web UI: `0.13.0`.
- Инструменты разработки: `0.1.6`.

## Активная архитектура

1. `app/` — локальное ядро, SQLite, настройки, HTTP API и диагностика.
2. `agent/` — контракт будущего Agent Core.
3. `disk/` — Диск Sayuri, ДНК документов, Evolution Core, Spatial Intelligence и OCR.
4. `web/` — единый светлый интерфейс проекта.
5. `scripts/` — переносимый Windows bootstrap, версионирование и проверки.

## REM-001 — результат

Из текущего дерева проекта удалён весь Android-интеграционный контур:

- отдельный backend-модуль управления Android;
- приложение-компаньон и Android build/release workflow;
- HTTP API управления устройством;
- видеопоток, аудио, clipboard и control bridge;
- ADB/scrcpy runtime и его Windows bootstrap;
- пользовательский экран, плавающее окно и клиентская логика;
- специализированные unit/API/web/bootstrap тесты;
- регистрация удалённых модулей в `MODULES.json`.

Ядро, Диск, ДНК, OCR и системные настройки не должны зависеть от удалённого контура.

## Сохранённая функциональность

- Диск Sayuri и файловый менеджер;
- ДНК 0.7 и Evidence Engine;
- Evolution Core;
- PDFium spatial extraction;
- Tesseract OCR `rus+eng`;
- локальное SQLite-хранилище;
- системные настройки, события и диагностика;
- единая светлая визуальная система.

## Следующий крупный этап

`AI-003` остаётся предложенной задачей: подключение реального ИИ-провайдера и развитие Agent Core поверх существующей ДНК, памяти, контекста и инструментов.

## Проверка REM-001

Перед публикацией в `main` обязательны:

- `python3 -m unittest discover -s scripts/tests -v`;
- `python3 -m unittest discover -s app/tests -v`;
- `node --check web/app.js`;
- `python3 -m app.preflight`;
- `python3 scripts/versioning.py check`;
- Windows PowerShell parser;
- проверка ASCII-safe BAT;
- проверка итогового дерева на отсутствие удалённых runtime/source/test файлов.

Локальный запуск на компьютере пользователя через GitHub API не выполнялся. Итоговая проверка выполняется GitHub Actions после публикации.
