# Задачи

Актуальная контрольная точка — [PROJECT_STATE.md](PROJECT_STATE.md).

## Завершено

- DOC-001 — базовая передача работы.
- DOC-002 — правила продолжения работы.
- VER-001 — версии проекта и модулей.
- APP-001 — первая рабочая версия.
- FIX-001 — Windows HTTP disconnect и русификация.
- FIX-002 — кодировка Windows launcher.
- CORE-002 — состояние, настройки и границы Агентного ядра.
- DISK-001 — первый рабочий модуль «Диск Sayuri».
- DISK-002 — профессиональный файловый менеджер.
- DISK-002.1 — центральный просмотр и свойства.
- DISK-002.2 — drag-and-drop, плитки/список и широкий интерфейс.
- DISK-003 — базовая «ДНК документа».
- DISK-004 — Evidence Engine, нормализация, quality gate, версии и междокументная сверка.

## DISK-005 — ДНК 0.5 Structural Intelligence & Safety
- Статус: `done` после успешного CI.
- Источник: прямой запрос пользователя «Делай все профессионально» после списка внутренних улучшений ДНК.
- UI: новых визуальных элементов нет.
- Реализовано:
  - source locator / spatial-ready evidence;
  - Document Schema Engine;
  - Entity Resolution 2.0;
  - Obligation Engine;
  - temporal contradictions;
  - dependency resolution;
  - template fingerprint;
  - document family;
  - corpus anomaly engine;
  - semantic version diff;
  - confidence calibration;
  - conservative correction memory;
  - tamper-evident DNA ledger;
  - prompt-injection shield;
  - sensitive-data classification;
  - selective AI context;
  - knowledge promotion pipeline;
  - package DNA для папки.
- Версии после CI-исправления: проект `0.1.15`, ядро `0.1.11`, Диск Sayuri `0.5.1`, веб `0.3.0`.

## DISK-006 — DNA Evolution Core
- Статус: `done` после успешного CI.
- Источник: прямой запрос пользователя на «супер мощное эволюционное профессиональное обновление мозгов ДНК».
- UI: без новых пунктов меню и без новых постоянных визуальных блоков.
- Реализовано:
  - Self Review;
  - Regression Guard;
  - Adaptive Profiles;
  - Rule Lifecycle;
  - Hypothesis Lab;
  - Active Learning queue;
  - Experience Snapshot;
  - глобальный реестр сущностей;
  - reanalysis planner;
  - evolution status API;
  - защита от повторного переизучения;
  - deep reanalysis override.
- Версии: проект `0.1.16`, ядро `0.1.12`, Диск Sayuri `0.6.0`, веб `0.3.0`.

## DISK-007 — Spatial Intelligence & OCR 0.7
- Статус: `implemented; повторный CI pending`.
- Источник: прямой запрос пользователя на следующий эволюционный скачок ДНК 0.7.
- UI: без новых пунктов меню и постоянных визуальных блоков.
- Реализовано:
  - PDFium spatial engine;
  - native PDF text + geometry;
  - Tesseract OCR rus+eng;
  - реальные bbox и нормализованные координаты;
  - fact → page/line/bbox evidence;
  - OCR confidence;
  - spatial quality;
  - OCR page budget и timeout;
  - table candidates;
  - signature/stamp candidates без ложного подтверждения;
  - spatial cache;
  - spatial status/snapshot API;
  - OCR reanalysis;
  - portable Windows runtime без pip;
  - отдельный preflight-блок Диска.
- Версии после CI-корректировки: проект `0.1.20`, ядро `0.1.16`, Диск Sayuri `0.7.0`, dev-tools `0.1.4`, веб `0.3.0`.
- Критерий готовности: полный CI должен пройти после публикации.

## AI-003 — Подключение ИИ-провайдера
- Статус: `proposed`.
- Цель: семантические роли, сложные причинные связи и проверяемые выводы поверх ДНК.


## PHONE-001 — Телефон Sayuri
- Статус: `implemented; CI pending`.
- Цель: отдельный модуль и пункт меню для подключения собственного Android к проекту.
- Готово в коде:
  - меню «Телефон Sayuri»;
  - device status;
  - USB flow;
  - Wireless Debugging pair/connect;
  - scrcpy control start/stop;
  - optional verified runtime в Windows launcher;
  - allow-listed API без shell;
  - unit/API/web/bootstrap tests.
- Ограничение 0.1: экран scrcpy пока отдельное локальное окно, не встроен в браузер.
- Следующий этап: PHONE-002 — встроенный экран/управление внутри страницы через локальный streaming bridge.


## PHONE-002 — Встроенный экран телефона
- Статус: `implemented`.
- Цель: пользоваться подключённым Android прямо внутри страницы «Телефон Sayuri».
- Реализовано:
  - live PNG preview через локальный ADB;
  - frame cache/throttle;
  - автоматический выбор авторизованного телефона;
  - выбор устройства кликом по карточке;
  - tap по экрану;
  - swipe мышью/указателем;
  - Back / Home / Recents / Power;
  - polling только при открытом модуле;
  - сохранён нативный scrcpy 60 FPS как high-performance режим;
  - unit/API/web contract tests.
- Не входит в 0.2:
  - embedded audio;
  - 30/60 FPS браузерный H.264 stream;
  - произвольные shell-команды.
- Следующий возможный этап: PHONE-003 — локальный H.264/WebCodecs bridge и клавиатурный ввод.


## PHONE-002.1 — восстановление после отключения телефона
- Статус: `implemented; CI pending`.
- Реальный дефект: после `Device disconnected` браузер продолжал запрашивать кадры старого serial.
- Исправлено:
  - stale cache/session cleanup;
  - controlled HTTP 409 для disconnect;
  - остановка frame loop;
  - автоматическое ожидание переподключения;
  - автоматическое возобновление после возврата устройства;
  - пауза embedded screencap при активном нативном scrcpy 60 FPS.


## PHONE-003 — Floating Workspace
- Статус: `implemented; CI pending`.
- Приоритет изменён прямым запросом пользователя: свободное плавающее окно важнее H.264/WebCodecs.
- Реализовано:
  - глобальное окно поверх всех view;
  - drag мышью;
  - resize браузерным resize-handle;
  - сохранение позиции/размера;
  - поворот 0/90/180/270;
  - пересчёт input coordinates при повороте;
  - minimize/close + глобальный launcher;
  - click/tap, drag/swipe, wheel-scroll, right-click Back;
  - системные кнопки Android;
  - клавиатура ПК после фокуса экрана;
  - строка безопасного text input;
  - сохранён нативный scrcpy 60 FPS;
  - CI JavaScript syntax check.
- Не входит:
  - полноценный embedded H.264 30/60 FPS;
  - embedded audio;
  - гарантированный Unicode IME для всех Android-клавиатур.
- Следующий этап после проверки UX: PHONE-004 — high-FPS local video bridge и расширенный keyboard/clipboard protocol.


## PHONE-004A — Pro Control & Media
- Статус: `implemented; CI pending`.
- Готово:
  - keyboard capture switch;
  - scrcpy UHID keyboard;
  - quality profiles;
  - screenshot → Диск Sayuri;
  - screen+audio recording → Диск Sayuri;
  - disk/PC file push → Android Download;
  - user app list/launch;
  - clipboard-to-text helper;
  - security allow-lists and file/package validation.
- Критерий контрольной точки: полный CI зелёный.
- Продолжение после CI: PHONE-004B — H.264/WebCodecs video bridge.
