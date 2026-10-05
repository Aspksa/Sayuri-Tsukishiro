# Справочник разработки Sayuri Tsukishiro

Актуальная точка — [PROJECT_STATE.md](PROJECT_STATE.md). Правила версий — [VERSIONING.md](VERSIONING.md).

## Модули

| ID | Имя | Путь | Назначение |
| --- | --- | --- | --- |
| `sayuri-core` | Ядро Саюри | `app/` | SQLite, настройки, API, сервер, диагностика |
| `agent-core` | Агентное ядро | `agent/` | контракт будущего ИИ/памяти/инструментов |
| `sayuri-disk` | Диск Sayuri | `disk/` | профессиональный локальный файловый менеджер и предпросмотр |
| `web-ui` | Веб-интерфейс | `web/` | интерфейс, центральный просмотр Диска и настройки |
| `dev-tools` | Инструменты разработки | `scripts/` | версии, тесты, Windows bootstrap |

## Диск Sayuri 0.2.1

Схема данных Диска остаётся версии 2. Новые изменения касаются предпросмотра и UX, поэтому пользовательская БД не мигрирует повторно.

### Просмотр

- PDF: встроенный iframe.
- Изображения: встроенное изображение.
- Видео/аудио: встроенные HTML5-проигрыватели.
- TXT/MD/JSON/XML/CSV/LOG/INI/CFG/YAML/YML: локальный текстовый просмотр.
- DOCX: текст из `word/document.xml`.
- PPTX: текст из `ppt/slides/*.xml`.
- XLSX: первая таблица, до 200 строк и 50 значений на строку.
- ODT/ODS/ODP: текст из `content.xml`.
- Остальные форматы: сохранено скачивание и возможность открытия внешним приложением.

Предпросмотр Office Open XML/ODF реализован на Python standard library (`zipfile`, `xml.etree.ElementTree`) без внешней передачи документов.

### API просмотра

- `GET /api/disk/files/{id}/preview` — JSON-описание/извлечённое содержимое.
- `GET /api/disk/files/{id}/view` — исходный объект с `Content-Disposition: inline`.
- `GET /api/disk/items/{kind}/{id}` — свойства.

### Интерфейс

История действий больше не выводится снизу Диска. Drag-and-drop расположен перед статистикой. Добавлены контекстное меню правой кнопкой, дерево папок и центральное окно «Просмотр / Свойства».

## Проверки

```sh
python -m unittest discover -s app/tests -v
python -m unittest discover -s scripts/tests -v
python -m app.preflight
python scripts/versioning.py check
```
