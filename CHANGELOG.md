# Журнал изменений

## Невыпущенные изменения

### 0.1.45 — 2026-10-06 — Memory 4.0 Hardening

- Локальный поиск/просмотр памяти больше не увеличивает `use_count`, `recall_count` и не создаёт обучающий recall-audit.
- AI recall стал двухфазным: usage/audit фиксируются только после успешного ответа Cloud.ru; ошибка провайдера не обучает память.
- Explainable Recall остаётся доступным в Личном кабинете без искусственного роста utility.
- Сквозной privacy firewall `cloud_allowed=false` распространён на Memory 3.0, Experience Learning, Goals, Tasks, Failures и Questions перед Cloud.ru.
- Protected memory не может попасть в AI-context обходным путём через производные слои памяти.
- Успех после failure больше не считается доказанным исправлением: создаётся `followed_by_success` с низкой confidence и `correlation_only`.
- Failure Memory закрывается только явным подтверждением пользователя через cause/resolution/prevention.
- Повтор уже исправленной ошибки переоткрывает failure pattern.
- Повтор одинакового подтверждения resolution идемпотентен и не увеличивает `resolved_count`.
- Добавлен `POST /api/sayuri/memory/v4/failures/{id}/resolve` и UI-кнопка «Подтвердить исправление».
- Добавлены регрессионные тесты privacy firewall, local read-only recall, causal semantics, failure reopen/idempotency, HTTP API и Web contract.
- Проект: `0.1.45`; Ядро: `0.1.37`; Agent Core: `0.8.1`; Web UI: `0.21.1`.


### 0.1.44 — 2026-10-06 — Memory 4.0

- Добавлен `agent/memory_v4.py` — orchestration layer поверх Memory 3.0.
- Для каждой memory рассчитываются Source Trust, Freshness, Utility, sensitivity и tier `hot/warm/cold`.
- Explainable Recall показывает, почему запись была выбрана, и сохраняет локальный recall audit.
- Feedback «Полезно / Не помогло» обновляет utility только реально использованных memories и ограниченно калибрует trust источника.
- Secret/sensitive memory получает `cloud_allowed=false` и исключается из Cloud.ru context.
- Добавлены Goal Memory, Task Memory, Decision Memory, Failure Memory, Causal Memory и Question/Uncertainty Memory.
- Добавлены Entity Profiles и Preference Drift поверх Knowledge Graph.
- Добавлен Memory Audit.
- Добавлены SQLite snapshots с SHA-256, обязательным `RESTORE MEMORY` и автоматическим pre-restore safety snapshot.
- Добавлен integrity check SQLite/graph/goals/tasks/knowledge provenance/recall links.
- Личный кабинет получил Memory 4.0 control center и badges tier/trust/local-only.
- Добавлены Memory 4.0 runtime/API/Web/unit tests.
- Проект: `0.1.44`; Ядро: `0.1.36`; Agent Core: `0.8.0`; Web UI: `0.21.0`.


### 0.1.43 — 2026-10-06 — Memory 3.0

- Добавлены Working Memory, Episodic Memory, Knowledge Memory и Temporal Memory.
- Добавлен локальный Knowledge Graph памяти.
- Добавлена консолидация похожих воспоминаний в устойчивые knowledge items без удаления источников.
- Добавлен Retention/Forgetting Engine: устаревшие записи получают меньший semantic retrieval-вес вместо автоматического удаления.
- Добавлен Contradiction Resolver с вариантами новое/старое/оба.
- Knowledge items получили temporal validity: `valid_from/valid_to`.
- Working Memory обновляется из чата и Safe Action planning и имеет TTL 24 часа.
- Значимые action/feedback/review события записываются как эпизоды.
- При старте выполняется bootstrap существующей памяти; opportunistic maintenance запускается не чаще одного раза в 6 часов.
- DeepSeek-V4-Flash получает отдельный Memory 3.0 context block.
- В Личном кабинете появился Memory 3.0 dashboard с графом, timeline, conflicts, retention и knowledge.
- Добавлены `GET /api/sayuri/memory/v3`, `POST /maintenance`, `POST /conflicts/{id}/resolve`.
- Episodic Memory дедуплицирует повторную обработку одного feedback/action по fingerprint; точный retry не засоряет timeline.
- Semantic Memory сканирует активные записи по scope до лимита 5000, поэтому релевантная старая память не теряется после первых 300 записей.
- Knowledge Graph сохраняет реальные подписи source-memory и помечает архивированные узлы через `active=false` / `archived_at`.
- Contradiction Resolver гарантирует обе стороны конфликта в графе и связь `conflicts_with`.
- Ручное архивирование исходной memory закрывает производное Knowledge, если не осталось других активных источников.
- Открытые противоречия передаются в AI-context явно как old/new, а не только счётчиком.
- Добавлены unit/API/Web contract tests Memory 3.0.
- Проект: `0.1.43`; Ядро: `0.1.35`; Agent Core: `0.7.0`; Web UI: `0.20.0`.


### 0.1.42 — 2026-10-06 — Semantic Memory + Experience Learning

- Добавлен локальный hybrid semantic поиск памяти `hybrid-semantic-v1`.
- Поиск учитывает формы слов, смысловые concepts, character n-grams, importance и confidence.
- Semantic retrieval подключён к контексту DeepSeek-V4-Flash без второй облачной модели.
- Добавлена отдельная локальная память опыта `data/sayuri-experience.db`.
- Sayuri учится на финальных исходах инструментов, review кандидатов памяти и явной оценке ответов.
- После достаточного числа примеров опыт мягко калибрует confidence Memory Intelligence в пределах ±8 п.п.
- Релевантный прошлый опыт делится на `helpful` и `avoid` и передаётся модели как недоверенный справочный контекст.
- В чате добавлена явная оценка «Полезно / Не помогло».
- В Личном кабинете добавлены Semantic Memory status, relevance поиска и статистика Experience Learning.
- Добавлены API `/api/sayuri/experience` и `/api/sayuri/experience/feedback`.
- Добавлены тесты semantic retrieval, feedback idempotency, relevant experience context, calibration и action learning.
- Проект: `0.1.42`; Ядро: `0.1.34`; Agent Core: `0.6.0`; Web UI: `0.19.0`.


### 0.1.41 — 2026-10-05 — Memory Intelligence 2.0

- Добавлен автоматический Memory Guardian для анализа сообщений.
- Sayuri создаёт кандидаты личной/проектной памяти вместо сохранения всего чата.
- Добавлены confidence, причина выделения, provenance и контекст открытого документа.
- Добавлены обнаружение дублей и возможных противоречий.
- В Личном кабинете появилась очередь кандидатов с «Сохранить / Не запоминать».
- Добавлены настройки генерации кандидатов, конфликтов, context-linking и безопасного high-confidence autosave.
- Память получила `source_context`, `confidence` и `supersedes_id`.
- Чат показывает уведомление, когда Sayuri заметила потенциально важное воспоминание.
- Добавлены Memory Intelligence API и тесты полного candidate lifecycle.
- Проект: `0.1.41`; Ядро: `0.1.33`; Agent Core: `0.5.0`; Web UI: `0.18.0`.


### 0.1.40 — 2026-10-05 — исправление загрузки и построения ДНК

- После загрузки PDF/Office/text/ODF/изображений ДНК запускается автоматически.
- Загрузка оригинала и построение ДНК теперь имеют отдельные статусы.
- Ошибка ДНК не отменяет успешную загрузку файла и не останавливает очередь.
- В очереди файлов показываются «ожидает ДНК», «строю ДНК», процент покрытия и ошибка.
- Во вкладке ДНК появилась собственная видимая диагностика и кнопка «Повторить анализ».
- Исправлена проверка готовности Spatial DNA: используется `pdfium_available`, а не устаревший/несуществующий `pymupdf_available`.
- Добавлены Web contract и Spatial diagnostics tests.
- Проект: `0.1.40`; Ядро: `0.1.32`; Диск: `0.7.1`; Web UI: `0.17.0`.


### 0.1.39 — 2026-10-05 — безопасные действия Sayuri

- Добавлен confirmation-gated Action Broker.
- Sayuri умеет подготовить создание папки, избранное, корзину, перемещение объекта и сохранение решения проекта.
- До нажатия «Подтвердить» проект не изменяется.
- Добавлены TTL, SHA-256 payload, replay protection и атомарное claim выполнения.
- В чате появились карточки действий с уровнем риска и кнопками подтверждения/отмены.
- В Личном кабинете появился список разрешённых инструментов и журнал последних действий.
- Добавлены API `/api/sayuri/actions`, `/plan`, `/{id}/confirm`, `/{id}/cancel`.
- Добавлены unit/API/web тесты подтверждения и повторного confirm.
- Проект: `0.1.39`; Ядро: `0.1.31`; Agent Core: `0.4.0`; Web UI: `0.16.0`.


### 0.1.38 — 2026-10-05 — память Sayuri и студия аватаров

- Добавлена долговременная локальная память Sayuri с областями `personal` и `project`.
- Добавлены типы памяти: fact, preference, decision, task, note; важность 1–5, dedup, поиск и use-count.
- Явные команды «запомни лично: …» и «запомни в проект: …» сохраняются без участия LLM.
- DeepSeek-V4-Flash получает только релевантную память с сохранением границы областей.
- В Личном кабинете добавлены просмотр, поиск, ручное добавление и удаление памяти.
- Добавлена локальная студия аватаров с независимыми слотами orb/chat/profile/hero.
- Пользовательские PNG/JPEG/WebP до 8 МБ сохраняются только в `data/sayuri-avatars/`.
- Добавлены HTTP API памяти и аватаров и тесты безопасности/разделения.
- Проект: `0.1.38`; Ядро: `0.1.30`; Agent Core: `0.3.0`; Web UI: `0.15.0`.


### 0.1.37 — 2026-10-05 — Sayuri Personal AI 0.1

- Sayuri стала глобальной помощницей во всём веб-интерфейсе.
- Пользовательский образ Sayuri добавлен как канонический аватар интерфейса.
- Обычный клик по аватару открывает отдельное окно чата; правый клик — контекстное меню действий.
- Добавлен нижний пункт «Личный кабинет Sayuri».
- В Личном кабинете реализованы настройки Cloud.ru и API-ключа.
- Единственная модель проекта: `deepseek-ai/DeepSeek-V4-Flash`.
- Добавлены `/api/sayuri/profile`, `/api/sayuri/provider`, `/api/sayuri/provider/test`, `/api/sayuri/chat`.
- На Windows локальный ключ защищается DPAPI; в GitHub и публичные API полный ключ не попадает.
- Чат получает интерфейсный контекст текущего раздела и выбранного объекта.
- Проект: `0.1.37`; Ядро: `0.1.29`; Agent Core: `0.2.0`; Web UI: `0.14.0`.


### 0.1.36 — 2026-10-05 — удаление Android/device-интеграции

- Полностью удалён ненужный Android/device-контур.
- Удалены backend-модуль, приложение-компаньон, HTTP API, media/control bridge и ADB/scrcpy runtime.
- Удалены связанный Web UI, стили, тесты и отдельный Android workflow.
- `MODULES.json` очищен от удалённых модулей.
- Ядро Саюри повышено до `0.1.28`, Web UI до `0.13.0`, dev-tools до `0.1.6`.
- Диск Sayuri, ДНК, OCR и Agent Core не изменены функционально.


### 0.1.35 — 2026-10-05 — Unified Sayuri UI 0.12

- Web UI повышен до `0.12.0`.
- Введён единый визуальный слой `SAYURI UI 0.12 — Unified Visual System`.
- Основная типографика переведена на `Segoe UI Variable` с системными fallback.
- Убраны экстремально мелкие пользовательские подписи и выровнена шкала размеров текста.
- Боковая навигация переведена на светлую оболочку.
- Главная, Диск, ДНК, Телефон и Настройки получили общие токены поверхностей, текста, границ и радиусов.
- Сокращены технические формулировки в пользовательском интерфейсе.
- Профили качества телефона теперь отображаются как «Экономно / Баланс / Качество / Максимум».
- Динамические статусы клавиатуры, видео и clipboard переписаны в понятной форме.
- UI-contract тест обновлён под новую пользовательскую терминологию.


### 0.1.34 — 2026-10-05 — Phone file-import validation order

- Телефон Sayuri повышен до `0.8.1`.
- Allow-list Android-каталога и basename импортируемого файла теперь проверяются до обращения к ADB.
- Некорректный location/path traversal отклоняется даже при отключённом телефоне.
- Функциональность PHONE 0.8 не изменялась и не ослаблялась.


### 0.1.33 — 2026-10-05 — Телефон Sayuri 0.8 Final Workspace

- Телефон Sayuri повышен до `0.8.0`, Web UI до `0.11.0`.
- Добавлен профиль MAX: 2560 px / 60 FPS / 24 Mbit/s.
- Добавлен fullscreen плавающего телефона.
- Добавлена AUTO-подстройка окна к portrait/landscape видеопотоку.
- Добавлены режимы Обычный / Компакт / Стекло.
- Добавлен hotkey `Ctrl+Alt+P` для показа/скрытия телефона.
- Позиция, размер и ручной поворот теперь сохраняются отдельно по serial устройства.
- Добавлен безопасный обратный файловый канал Android → Диск Sayuri.
- Импорт разрешён только из Download, DCIM/Camera и Pictures.
- Файл проверяется как обычный файл, ограничивается 512 МБ и только после этого скачивается через ADB pull.
- Добавлены service/API/web regression tests для file import и нового workspace UX.


### 0.1.32 — 2026-10-05 — Verified Sayuri Companion installer

- Телефон Sayuri повышен до `0.7.1`, Web UI до `0.10.1`.
- Закреплён реально собранный APK Sayuri Companion 0.1.1.
- APK download привязан к точному versioned GitHub Release.
- До `adb install -r` проверяются размер и SHA-256.
- Непроверенный/оборванный download удаляется.
- Установка запускается только явной кнопкой пользователя.
- После установки проверяется Android package.
- UI автоматически переключается с «Установить» на «Сопрячь».
- ADB reverse Companion автоматически восстанавливается после reconnect в пределах текущего desktop-процесса.
- Добавлены installer/reverse/API/web regression tests.


### 0.1.31 — 2026-10-05 — Companion Android CI bootstrap

- Sayuri Companion повышен до `0.1.1`.
- Исправлен Android workflow: runner не имел `sdkmanager`.
- Добавлен pinned `android-actions/setup-android v4.0.4` по commit SHA `be39fa834029ff78f1a44aa3bb0819b8fc2bd8fd`.
- Android SDK 36 и build-tools 36.0.0 теперь устанавливаются через setup action.
- Основной Sayuri CI для PHONE-005A уже подтверждён как success.


### 0.1.30 — 2026-10-05 — Sayuri Companion 0.1

- Телефон Sayuri повышен до `0.7.0`, Web UI до `0.10.0`.
- Добавлен новый зарегистрированный Android-модуль `Sayuri Companion 0.1.0`.
- Добавлен локальный authenticated Companion protocol через ADB reverse.
- Добавлен Android NotificationListenerService.
- Pairing требует явного подтверждения пользователя на телефоне.
- Notification Access остаётся системным Android-разрешением и не обходится.
- Добавлены Companion status/events/enable/disable API.
- В floating phone добавлен drawer уведомлений.
- Добавлен Android CI: AGP 9.4.0 / Gradle 9.6.1 / JDK 17 / API 36.
- Workflow публикует APK и checksum как versioned GitHub Release.
- Автоустановка APK намеренно отложена до следующего patch после получения digest реально собранного APK.


### 0.1.29 — 2026-10-05 — Телефон Sayuri 0.6 Audio & Clipboard

- Телефон Sayuri повышен до `0.6.0`, Web UI до `0.9.0`.
- Добавлен version-pinned scrcpy 4.1 clipboard protocol adapter.
- Добавлен двусторонний Unicode clipboard ПК↔Android.
- ПК→Тел может сразу выполнить Android paste.
- Строка ввода использует Android clipboard и поддерживает Unicode/эмодзи.
- Добавлен version-pinned Opus media adapter `sayuri-opus-v1`.
- Добавлен отдельный embedded audio stream и WebCodecs AudioDecoder/Web Audio playback.
- Звук включается только явным действием пользователя.
- Audio failure не ломает H.264 video/control.
- Audio очищается при смене устройства, disconnect, minimize/close и переходе в native scrcpy.
- Добавлены binary protocol/API/web regression tests.


### 0.1.28 — 2026-10-05 — Телефон Sayuri 0.5 H.264 WebCodecs

- Телефон Sayuri повышен до `0.5.0`, Web UI до `0.8.0`.
- Добавлен version-pinned адаптер официального scrcpy-server 4.1.
- Добавлен embedded H.264 stream через локальный ADB forward и существующий loopback HTTP server.
- Добавлен внутренний протокол `sayuri-h264-v1`.
- Web UI декодирует H.264 через WebCodecs и рисует кадры в canvas.
- ECO/BAL/HQ теперь управляют качеством встроенного H.264.
- Session packets поддерживают изменение размера при повороте/складывании устройства.
- SPS/PPS config объединяется с первым media frame.
- Добавлен decoder backlog guard для low-latency режима.
- При отсутствии WebCodecs или ошибке media bridge автоматически возвращается PNG fallback.
- Нативный scrcpy 60 FPS сохранён.
- Добавлены protocol/service/API/web regression tests.


### 0.1.27 — 2026-10-05 — Телефон Sayuri 0.4.1 input validation

- Android package name теперь валидируется до обращения к ADB/device state.
- Вредоносное или некорректное имя пакета отклоняется независимо от подключения телефона.
- Реализация PHONE-004A не ослаблялась.
- Требуется повторный полный CI.


### 0.1.26 — 2026-10-05 — Телефон Sayuri 0.4 Pro Control & Media

- Телефон Sayuri повышен до `0.4.0`, Web UI до `0.7.0`.
- Добавлен явный переключатель захвата клавиатуры компьютера.
- Нативный scrcpy использует рекомендованный режим `--keyboard=uhid`.
- Добавлены профили качества ECO/BAL/HQ.
- Добавлено сохранение снимков PNG в Диск Sayuri.
- Добавлена запись видео+аудио в MP4 через официальный scrcpy с последующим импортом в Диск Sayuri.
- Добавлен drag&drop файлов из Диска/ПК в Android Download.
- Добавлен безопасный список и запуск пользовательских приложений.
- Добавлена вставка текста из clipboard компьютера.
- Произвольный ADB shell не публикуется.
- PHONE-004B с H.264/WebCodecs остаётся следующим слоем этой же задачи.


### 0.1.25 — 2026-10-05 — Телефон Sayuri 0.3 Floating Workspace

- Телефон Sayuri повышен до `0.3.0`, Web UI до `0.6.0`.
- Убран большой встроенный дисплей из страницы модуля.
- Добавлено независимое плавающее окно поверх всего проекта.
- Окно можно таскать, менять размер, сворачивать, закрывать и возвращать глобальным launcher.
- Позиция, размер и поворот сохраняются локально.
- Добавлен поворот 0/90/180/270 с корректным обратным пересчётом координат touch/swipe.
- Добавлены колесо мыши как swipe и правый клик как Android Back.
- Добавлена физическая клавиатура ПК и allow-listed text input endpoint.
- Нативный scrcpy 60 FPS сохранён.
- В CI добавлен `node --check web/app.js`.
- Страница «Телефон Sayuri» упрощена до подключения и управления устройствами.


### 0.1.24 — 2026-10-05 — Телефон Sayuri 0.2.1 reconnect resilience

- Исправлена обработка реального USB/ADB disconnect Samsung SM-A556E.
- Потерянный serial больше не вызывает бесконечный цикл `/api/phone/frame` HTTP 400.
- Stale frame cache и scrcpy session очищаются после исчезновения устройства.
- Frame endpoint возвращает `SAYURI-PHONE-409` для controlled disconnect.
- UI останавливает live polling, очищает старый кадр и переходит в состояние ожидания.
- Добавлен лёгкий auto-reconnect через периодическую проверку `/api/phone`.
- После повторной авторизации embedded preview восстанавливается автоматически.
- Embedded screencap ставится на паузу, пока открыт нативный scrcpy 60 FPS.
- Добавлены regression tests по disconnect/reconcile/API 409/web recovery contract.


### 0.1.23 — 2026-10-05 — Телефон Sayuri 0.2 Embedded Control

- Телефон Sayuri повышен до `0.2.0`.
- Web UI повышен до `0.5.0`.
- В существующий модуль добавлен встроенный экран Android.
- Добавлен локальный PNG frame bridge через `adb exec-out screencap -p`.
- Добавлен кэш кадров ~350 мс и остановка polling вне вкладки телефона.
- Добавлены tap/swipe по нормализованным координатам.
- Добавлены allow-listed Android Back/Home/Recents/Power.
- Нативный официальный scrcpy 60 FPS сохранён отдельным high-performance режимом.
- Arbitrary ADB shell не публикуется.
- Добавлены unit/API/web contract tests.


### 0.1.22 — 2026-10-05 — Phone input validation order

- Телефон Sayuri повышен до `0.1.1`.
- Pair/connect/disconnect сначала валидируют пользовательский ввод и только затем обращаются к ADB runtime.
- Некорректный адрес/код отклоняется независимо от наличия ADB.
- Первый CI уже подтвердил Windows launcher, API и web contract; требуется повторный полный прогон.


### 0.1.21 — 2026-10-05 — Телефон Sayuri 0.1

- Добавлен новый зарегистрированный модуль `sayuri-phone` версии `0.1.0`.
- В левое меню добавлен **«Телефон Sayuri»**.
- Добавлены USB/Wi-Fi Android device discovery, Wireless Debugging pair/connect/disconnect.
- Добавлен запуск/остановка официального scrcpy из Sayuri.
- Добавлены allow-listed `/api/phone/*` endpoints; произвольный adb shell не публикуется.
- Windows AMD64 launcher получает официальный scrcpy 4.1 с проверкой SHA-256.
- Добавлены phone service/API/web/bootstrap tests.
- Встроенный видеопоток в браузер отложен на PHONE-002.


### 0.1.20 — 2026-10-05 — Исправление тестового синтаксиса Spatial DNA

- Исправлен буквальный `\\n` в `app/tests/test_disk.py`, из-за которого unittest не мог импортировать модуль.
- Реализация Spatial DNA 0.7 не изменялась.
- Первый CI уже подтвердил новые Spatial/OCR тесты и Windows parser; требуется повторный полный прогон.


### 0.1.19 — 2026-10-05 — Spatial Intelligence & OCR 0.7

- Диск Sayuri повышен до `0.7.0`.
- Evidence Engine повышен до `0.7.0`, DNA schema до 4.
- Добавлен `SpatialDNAEngine 0.7.0`.
- PDF spatial extraction переведён на permissive PDFium/pypdfium2.
- Добавлен локальный Tesseract OCR rus+eng с TSV confidence и координатами.
- Факты ДНК получают page/line/bbox locator, когда источник предоставляет реальную геометрию.
- Добавлены spatial quality, OCR page budget и timeout.
- Добавлены table/signature/stamp candidates без автоматического объявления их фактами.
- Схема Диска повышена до 7 и добавлен `disk_dna_spatial`.
- Добавлены internal API spatial status/snapshot и OCR reanalysis.
- Windows bootstrap умеет optional PDFium/Pillow/Tesseract runtime без pip и без блокировки основного запуска при ошибке optional-компонента.
- Preflight отдельно показывает состояние Диск Sayuri.
- Веб-меню не изменялось.


### 0.1.18 — 2026-10-05 — Финальная корректировка старого теста reanalysis

- Исправлен второй оставшийся старый unit-тест, который ожидал безусловный новый анализ от `force=True`.
- Явный повторный анализ теперь корректно использует `bypass_cooldown=True`.
- Код ДНК 0.6 не изменялся.


### 0.1.17 — 2026-10-05 — Корректировка тестового контракта Evolution Core

- Два старых unit-теста обновлены под новый reanalysis cooldown.
- Явный новый анализ в тестах теперь использует `bypass_cooldown=True`.
- Защита от повторных кликов и код ДНК 0.6 не ослаблялись.


### 0.1.16 — 2026-10-05 — DNA Evolution Core 0.6

- Диск Sayuri повышен до `0.6.0`.
- Добавлен отдельный `DNAEvolutionEngine`.
- Добавлена самопроверка фактов, доказательств, canonical values и quality gate.
- Добавлен Regression Guard для защиты от потери уже проверенных фактов.
- Добавлены адаптивные профили по корпусу документов.
- Добавлен lifecycle корректирующих правил: candidate / shadow / active.
- Добавлена лаборатория гипотез повторяющихся связей без автоматического превращения в факты.
- Добавлена очередь Active Learning для важных неопределённых фактов.
- Добавлена техническая метрика накопленного проверяемого опыта.
- Схема Диска повышена до 6.
- Добавлены глобальный реестр сущностей и таблица упоминаний.
- Добавлены API состояния эволюции и плана переанализа.
- Добавлена 10-секундная дедупликация повторного `dna/analyze`.
- Добавлен явный `deep=true` для настоящего повторного глубокого анализа.
- Веб-интерфейс не изменялся.


### 0.1.15 — 2026-10-05 — Исправление ссылок ДНК

- Диск Sayuri повышен до `0.5.1`.
- Исправлена канонизация номера документа: завершающая пунктуация больше не входит в canonical ID.
- Ссылка вида `договор № 55.` теперь корректно сопоставляется с документом `№ 55`.
- Исправление найдено новым тестом dependency resolution; сам тест не ослаблялся.


### 0.1.14 — 2026-10-05 — ДНК 0.5 Structural Intelligence & Safety

- Диск Sayuri повышен до `0.5.0`.
- Интерфейс ДНК не расширялся.
- Добавлен отдельный `dna_advanced.py`.
- Добавлены spatial-ready locators фактов.
- Добавлены Document Schema Engine и Entity Resolution 2.0.
- Добавлены Obligation Engine, временные проверки и зависимости документов.
- Добавлены нормализованный template fingerprint и семейства документов.
- Добавлен корпусный anomaly engine.
- Version delta теперь хранит изменения значений и проценты изменения сумм.
- Добавлены confidence calibration и conservative correction memory.
- Схема Диска повышена до 5.
- Добавлен tamper-evident `disk_dna_ledger`.
- Добавлена защита от prompt injection внутри документов.
- Добавлена классификация чувствительных данных и selective AI context.
- Добавлен knowledge promotion pipeline.
- Добавлена пакетная ДНК папки и внутренние API ledger/package DNA.


### 0.1.13 — 2026-10-05 — Исправление теста ДНК 0.4

- Исправлено устаревшее ожидание версии анализатора в `test_disk.py`: `0.1.0` → `0.4.0`.
- Код ДНК 0.4 не изменялся.

### 0.1.12 — 2026-10-05 — ДНК 0.4 Evidence Engine

- Диск Sayuri повышен до `0.4.0`.
- Интерфейс ДНК не расширялся.
- Анализатор ДНК повышен до `0.4.0`.
- Добавлены стабильные ID фактов, роли, нормализованные значения и evidence hash.
- Добавлена раздельная уверенность извлечения, нормализации и доказательства.
- Добавлены профили документов и контроль обязательных полей.
- Добавлены ИНН/КПП/ОГРН/БИК/счета, организации, ФИО, время, пробег и количество.
- Добавлены действия документа и временная модель.
- Добавлена арифметическая проверка XLSX.
- Добавлены внутренние и междокументные противоречия.
- Добавлены semantic SHA-256, SimHash и token fingerprint.
- Добавлены точные и почти-дубли.
- Добавлен graph-ready слой доказуемых связей.
- Добавлены quality gate, document quality и risk engine.
- Добавлено явное разделение фактов и гипотез.
- Схема Диска повышена до 4.
- Добавлены `disk_dna_history` и `disk_dna_feedback`.
- Добавлены версии ДНК и delta между анализами.
- Переименование/перемещение больше не вызывает повторный анализ содержимого при неизменном SHA-256.
- Добавлены backend API истории ДНК и обратной связи по фактам.

### 0.1.11 — 2026-10-05 — ДНК документа

- Создан базовый структурный слой «ДНК».

### 0.1.10 — 2026-10-05 — Диск Sayuri 0.2.2

- Drag-and-drop, плитки/список и отмена перемещения.
