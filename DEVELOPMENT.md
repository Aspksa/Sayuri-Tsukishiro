# Справочник разработки Sayuri Tsukishiro

Актуальная точка — [PROJECT_STATE.md](PROJECT_STATE.md). Правила версий — [VERSIONING.md](VERSIONING.md).

## Диск Sayuri 0.2.2

### Интерфейс

- внутреннего постоянного сайдбара у Диска нет;
- `Все файлы / Избранное / Недавние / Корзина` находятся сверху;
- рабочая область ограничена `max-width: 1380px`;
- доступны режимы `tiles` и `list`;
- выбор режима хранится в `localStorage` под ключом `sayuri-disk-view`;
- строка пути является кликабельной и принимает drop на предыдущий уровень;
- папки в плитках показывают `file_count` и `size_bytes`.

### Drag-and-drop

При начале drag:
- если объект входит в текущее массовое выделение — переносятся все выбранные объекты;
- иначе переносится только захваченный объект.

Цели:
- папка в списке/плитках;
- уровень в breadcrumbs;
- верхняя кнопка «Корзина».

Папка автоматически открывается примерно через 900 мс удержания при drag.

### Перемещение и отмена

`POST /api/disk/move` возвращает:
- `destination_name`;
- `moves[]` с `kind`, `id`, `from_id`, `to_id`.

`POST /api/disk/undo-move` принимает `moves[]` и возвращает объекты в исходные папки. Операция проверяет конфликты имён и запрещённые циклы папок.

### Проверки

```sh
python -m unittest discover -s app/tests -v
python -m unittest discover -s scripts/tests -v
python -m app.preflight
python scripts/versioning.py check
```
