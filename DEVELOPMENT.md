# Справочник разработки Sayuri Tsukishiro

Актуальная точка — [PROJECT_STATE.md](PROJECT_STATE.md). Правила версий — [VERSIONING.md](VERSIONING.md).

## Диск Sayuri 0.5 — ДНК Structural Intelligence & Safety

### Версии

- схема Диска: `5`;
- базовый анализатор ДНК: `0.5.0`;
- advanced engine: `0.5.0`;
- JSON-схема базовой ДНК: `3`.

### Файлы

- `disk/dna.py` — базовый Evidence Engine;
- `disk/dna_advanced.py` — внутренние слои 0.5;
- `disk/service.py` — кэш, версии, междокументный корпус, ledger, correction memory и package DNA;
- `app/server.py` — локальные API.

### Новые таблицы схемы 5

```text
disk_dna_ledger
  file_id
  sequence_no
  event_type
  created_at
  payload_sha256
  previous_chain_hash
  chain_hash
  details_json

disk_dna_correction_rules
  fact_type
  original_canonical
  corrected_json
  supporting_files_json
  support_count
  updated_at
```

Существующие `disk_dna`, `disk_dna_history` и `disk_dna_feedback` сохраняются.

### Advanced pipeline

```text
base evidence
→ spatial locator
→ learned correction (>=3 distinct files)
→ calibration
→ document schema
→ entity resolution
→ obligations
→ temporal checks
→ dependencies
→ security
→ sensitive classification
→ template fingerprint
→ knowledge promotion
→ selective AI context
→ dynamic cross-document/corpus enrichment
→ history + ledger
```

### Trust boundary

Содержимое документа всегда имеет `trust_domain=document_content`.

Фраза внутри файла не может:
- изменить системные инструкции;
- включить инструмент;
- заставить раскрыть секрет;
- повысить свой уровень доверия.

### Ledger

Каждый анализ и feedback создают элемент hash-chain. `dna_ledger()` пересчитывает payload hash и цепочку и возвращает `valid`.

Это tamper-evident журнал, а не WORM-хранилище.

### Correction Memory

Правило автокоррекции применяется только при:
- одинаковом типе факта;
- одинаковом исходном canonical value;
- одинаковом исправленном значении;
- поддержке минимум трёх различных file_id.

### API

- `GET /api/disk/files/{id}/dna`
- `POST /api/disk/files/{id}/dna/analyze`
- `GET /api/disk/files/{id}/dna/history?limit=N`
- `POST /api/disk/files/{id}/dna/feedback`
- `GET /api/disk/files/{id}/dna/ledger?limit=N`
- `GET /api/disk/package-dna?folder_id=...&analyze_missing=0|1`

### Ограничения

- координаты PDF/изображения требуют OCR;
- semantic AI не подключён;
- package DNA при `analyze_missing=1` выполняется синхронно;
- background worker в DISK-005 намеренно не включён.

## Проверки

```sh
python -m unittest discover -s app/tests -v
python -m unittest discover -s scripts/tests -v
python -m app.preflight
python scripts/versioning.py check
```

Windows launcher отдельно проверяется GitHub Actions.


## Диск Sayuri 0.6 — DNA Evolution Core

### Версии

- схема Диска: `6`;
- Evolution Core: `0.6.0`;
- базовый Evidence Engine остаётся `0.5.0`;
- Advanced DNA остаётся `0.5.0`.

### Новый модуль

`disk/dna_evolution.py`

Контуры:
- `self_review`;
- `adaptive_profile`;
- `regression_guard`;
- `rule_lifecycle`;
- `hypotheses`;
- `active_learning`;
- `experience`.

### Новые таблицы

```text
disk_dna_entities
  entity_id
  category
  canonical_id
  display_name
  first_seen_at
  last_seen_at
  document_count
  confidence
  attributes_json

disk_dna_entity_mentions
  file_id
  entity_id
  fact_ids_json
  evidence_json
  confidence
  updated_at
```

### Reanalysis cooldown

`REANALYZE_COOLDOWN_SECONDS = 10`.

`document_dna(..., force=True)` возвращает кэшированный результат, если предыдущий анализ того же SHA/анализатора был менее 10 секунд назад.

`document_dna(..., force=True, bypass_cooldown=True)` всегда выполняет новый анализ.

HTTP:
- обычный `POST /dna/analyze` — защищён от дублей;
- `POST /dna/analyze` с `{"deep": true}` — обход cooldown.

### Evolution API

- `GET /api/disk/dna/evolution`
- `GET /api/disk/dna/reanalysis-plan?limit=N`

Оба API диагностические и не добавлены в пользовательское меню.

### Границы

- Evolution Core не является самостоятельной LLM.
- Он не создаёт причинность из корреляции.
- Он не запускает автоматический массовый переанализ.
- Он не меняет пользовательские документы.
- OCR и реальный AI остаются отдельными слоями.


## Диск Sayuri 0.7 — Spatial Intelligence

### Версии

- схема Диска: `7`;
- DNA schema: `4`;
- Evidence Engine: `0.7.0`;
- Advanced DNA: `0.5.1`;
- Evolution Core: `0.6.0`;
- Spatial DNA: `0.7.0`.

### Runtime

Windows bootstrap закрепляет:
- `pypdfium2==5.13.0`;
- `Pillow==12.3.0`;
- Tesseract OCR `5.5.3` для автоматического AMD64 runtime;
- tessdata `4.1.0` `rus+eng`.

Wheel/binary/language files проверяются SHA-256.

Python embeddable получает дополнительный путь:
`..\\packages`.

### Spatial storage

```text
disk_dna_spatial
  file_id PK/FK
  sha256
  engine_version
  analyzed_at
  spatial_json
```

### Spatial limits

- MAX_PAGES = 120
- MAX_OCR_PAGES = 24
- OCR_DPI = 220
- OCR_TIMEOUT_SECONDS = 75
- MAX_NATIVE_CHARS_PER_PAGE = 120000
- MAX_LINES_PER_PAGE = 4000

### API

- `GET /api/disk/dna/spatial`
- `GET /api/disk/files/{id}/dna/spatial`
- `GET /api/disk/files/{id}/dna/spatial?ocr=1`
- `POST /api/disk/files/{id}/dna/analyze`:
  - `{"ocr": true}`
  - `{"deep": true}`

### Evidence

Spatial locator:
```json
{
  "page": 1,
  "line_id": "p1-ocr-l4",
  "line": 4,
  "bbox": {
    "space": "points",
    "values": [40, 120, 280, 142],
    "normalized": [0.066, 0.15, 0.466, 0.177]
  },
  "extraction_method": "ocr",
  "coordinate_status": "exact_from_document_engine"
}
```

### Ограничения

- Tesseract auto-install в bootstrap предусмотрен только для AMD64; ARM64 использует найденный внешний OCR либо работает без OCR.
- table/signature/stamp detection 0.7 создаёт кандидаты, а не подтверждённые semantic entities.
- реальный vision/LLM слой не подключён.


## Телефон Sayuri 0.1

### Каталог

```text
phone/
  VERSION
  __init__.py
  service.py
```

### Runtime

Windows AMD64:
- scrcpy `4.1`;
- официальный архив `scrcpy-win64-v4.1.zip`;
- источник: `Genymobile/scrcpy`;
- SHA-256: `5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db`;
- локальный путь: `.runtime/phone/scrcpy/`.

Runtime optional: ошибка скачивания не блокирует запуск Sayuri.

### API

```text
GET  /api/phone
POST /api/phone/pair
POST /api/phone/connect
POST /api/phone/disconnect
POST /api/phone/control/start
POST /api/phone/control/stop
```

Payload pairing:

```json
{"address":"192.168.1.20:37125","pairing_code":"123456"}
```

Payload connect:

```json
{"address":"192.168.1.20:39587"}
```

Control:

```json
{"serial":"R58M123ABC"}
```

### Security boundary

- нет shell-строк;
- subprocess получает argv;
- pairing address валидируется как host:port;
- pairing code — ровно 6 цифр;
- управление разрешено только для устройства, которое присутствует в текущем `adb devices -l` и имеет state `device`;
- сервер Sayuri остаётся `127.0.0.1`.

### UI

Отдельный view `#phone`:
- runtime status;
- список устройств;
- USB-инструкция;
- Wireless Debugging pairing;
- connect/disconnect;
- open/stop control.

0.1 не содержит embedded browser stream.


## Телефон Sayuri 0.2 — Embedded Control

### Frame bridge

```text
Browser #phone
  ↓ GET /api/phone/frame?serial=...
PhoneService.screen_frame()
  ↓ validate authorized serial
adb -s SERIAL exec-out screencap -p
  ↓ PNG
350 ms cache
  ↓
<img id="phone-screen">
```

### Input bridge

```text
POST /api/phone/input/tap
POST /api/phone/input/swipe
POST /api/phone/input/key
```

Tap payload:

```json
{"serial":"R58M123ABC","x":0.42,"y":0.73}
```

Swipe payload:

```json
{
  "serial":"R58M123ABC",
  "x1":0.5,
  "y1":0.8,
  "x2":0.5,
  "y2":0.2,
  "duration_ms":280
}
```

Allowed key names:
- BACK
- HOME
- RECENTS
- ENTER
- DELETE
- POWER
- VOLUME_UP
- VOLUME_DOWN
- PLAY_PAUSE

UI 0.2 exposes Back/Home/Recents/Power.

### Security

- serial must be an authorized current ADB device;
- x/y are numeric and constrained to 0..1;
- key is mapped through a fixed dictionary;
- swipe duration is clamped to 50..1500 ms;
- shell command body is not accepted from HTTP;
- project remains loopback-only.

### Performance

- frame cache: 350 ms;
- browser target interval: ~420 ms;
- failed frame retry: ~1500 ms;
- only one frame capture is allowed at a time;
- leaving `#phone` stops browser polling.

### High-performance mode

The existing official scrcpy 4.1 window remains available from the same module for:
- up to 60 FPS;
- audio;
- lower perceived latency.

Embedded mode 0.2 intentionally does not claim equivalent FPS/audio.


## Телефон Sayuri 0.2.1 — Disconnect Recovery

Состояния embedded preview:

```text
authorized
  → LIVE frame loop
  → ADB disconnect
  → SAYURI-PHONE-409
  → stop frame loop
  → clear stale frame/session
  → WAITING
  → GET /api/phone every ~2.5s
  → authorized again
  → resume LIVE
```

Дополнительное правило:
если для выбранного serial открыт нативный scrcpy 60 FPS, embedded `screencap -p` polling ставится на паузу. После закрытия нативного окна встроенный preview возобновляется.

Это снижает одновременную нагрузку на ADB/USB и устраняет бесконечные запросы к исчезнувшему serial.


## Телефон Sayuri 0.3 — Floating Workspace

### DOM boundary

Floating phone находится за пределами отдельных `.view` и поэтому не уничтожается/не скрывается при переходах:

```text
app shell
  ├─ home
  ├─ disk
  ├─ phone connection center
  └─ settings

global layer
  ├─ phone-float-launcher
  └─ phone-float
```

### Window state

LocalStorage:
- `sayuri-phone-float-open`
- `sayuri-phone-float-layout`
- `sayuri-phone-rotation`

Layout:
- fixed position;
- drag by header;
- CSS `resize: both`;
- min/max viewport constraints;
- ResizeObserver refits the phone image.

### Rotation/input mapping

Display supports 0/90/180/270 degrees.
Pointer coordinates are normalized in the rotated visual rectangle and mapped back to native Android coordinates before POST.

### Mouse

- left click → tap;
- drag → swipe;
- wheel → swipe;
- right click → BACK.

### Keyboard

When `phone-float-screen-stage` has focus:
- Backspace → DELETE;
- Enter → ENTER;
- Escape → BACK;
- arrows → DPAD;
- Tab → TAB;
- Space → SPACE;
- safe printable character → buffered `/api/phone/input/text`.

Text endpoint:
`POST /api/phone/input/text`

It accepts at most 250 characters and rejects shell metacharacters. Arbitrary command execution is not exposed.

### CI

Ubuntu CI now performs:
`node --check web/app.js`

This complements Python unit/web-contract tests.


## Телефон Sayuri 0.4 — Pro Control

### Quality profiles

```text
economy  1024 px · 30 FPS · 4 Mbit/s
balanced 1600 px · 60 FPS · 8 Mbit/s
quality  1920 px · 60 FPS · 16 Mbit/s
```

Нативный scrcpy:
- H.264;
- `--keyboard=uhid`;
- `--mouse=sdk`;
- audio по стандартному scrcpy pipeline.

### Media API

```text
POST /api/phone/capture
POST /api/phone/recording/start
POST /api/phone/recording/stop
```

Capture сохраняется в корень Диск Sayuri как PNG.
Recording создаётся во временном runtime, после остановки импортируется в Диск Sayuri как MP4 и временный файл удаляется.

### File bridge

```text
POST /api/phone/files/push    # существующий file_id из Диска
POST /api/phone/files/upload  # binary body с компьютера
```

Политика:
- максимум 512 МБ;
- destination фиксирован: `/sdcard/Download/`;
- filename нормализуется;
- APK не устанавливается автоматически.

### App launcher

```text
GET  /api/phone/apps?serial=...
POST /api/phone/apps/launch
```

В 0.4 перечисляются только пользовательские пакеты `pm list packages -3`.
Запуск разрешён только если package присутствует в текущем списке устройства.

### Keyboard capture

Floating UI имеет явное состояние:
- `КЛАВ: SAYURI` — физическая клавиатура не перехватывается;
- `КЛАВ: ТЕЛЕФОН` — keydown внутри phone stage направляется в Android.

Нативный режим использует UHID и остаётся способом для полного IME/Unicode до появления собственного control-protocol bridge.


## Телефон Sayuri 0.5 — H.264 WebCodecs

### Backend flow

```text
browser
  GET /api/phone/stream?serial=...&profile=quality
    ↓
PhoneService.h264_stream
    ↓
adb push pinned scrcpy-server 4.1
    ↓
adb forward tcp:0 localabstract:scrcpy_<SCID>
    ↓
app_process com.genymobile.scrcpy.Server 4.1
  audio=false
  control=false
  video_codec=h264
  send_device_meta=false
  send_dummy_byte=false
    ↓
localhost TCP socket
    ↓
phone/h264.py
    ↓
sayuri-h264-v1
    ↓
HTTP stream
```

### sayuri-h264-v1

Stream starts with:
`SYH1`.

Record types:
- `0x01 + width:u32be + height:u32be` — video session;
- `0x02 + flags:u8 + pts:u64be + size:u32be + payload` — H.264 media packet.

Flag bit 0 = keyframe.

scrcpy config packets are not emitted separately. SPS/PPS are buffered and prepended to the next media packet.

Limits:
- media packet <= 32 MiB;
- accumulated config <= 2 MiB;
- exactly H.264 codec id `0x68323634`.

### Browser

Requirements for high-FPS path:
- Fetch ReadableStream;
- WebCodecs `VideoDecoder`;
- `EncodedVideoChunk`.

SPS is parsed to obtain the `avc1.PPCCLL` codec string.
Decoder config prefers hardware acceleration and low latency.

If unavailable or failed:
`fallbackPhoneVideo() -> PNG /api/phone/frame`.

### Resource lifecycle

When floating phone is:
- closed;
- minimized;
- switched to another device;
- switched to native scrcpy;
- disconnected;
- quality profile changed;

the active H.264 fetch is aborted, VideoDecoder is closed and the backend request closes its TCP socket/process/ADB forward.

### Security

- HTTP remains loopback-only;
- no arbitrary ADB shell is added;
- SCID is generated internally;
- quality profile is allow-listed;
- H.264 server args are generated internally;
- browser cannot choose server command or ADB destination.
