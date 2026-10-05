# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Исходная ревизия: `c9a0b955a21792e240265aa15ba7b8f1314b6137` (проект `0.1.42`).
- Целевая версия: `0.1.43`.
- Текущий этап: Memory 3.0 — рабочая, эпизодическая, knowledge, temporal и graph memory.

## Версии активных модулей

- Ядро Саюри: `0.1.35`.
- Agent Core: `0.7.0`.
- Диск Sayuri: `0.7.1`.
- Web UI: `0.20.0`.
- Инструменты разработки: `0.1.6`.

## Memory 3.0

Новый модуль: `agent/memory_v3.py`.

Memory 3.0 не заменяет существующие personal/project memory, Memory Intelligence, Semantic Memory и Experience Learning. Она оркестрирует их в несколько специализированных контуров.

### Working Memory

Хранит только текущий фокус и безопасный UI-context:

- последнее пользовательское намерение;
- текущий раздел;
- открытый документ;
- безопасный контекст Диска.

Working Memory имеет TTL 24 часа и автоматически обновляется при обычном чате и при планировании Safe Action.

### Episodic Memory

Хранит значимые события, а не весь чат:

- подтверждённое/ошибочное/отменённое действие;
- пользовательскую оценку ответа;
- отклонённый кандидат памяти;
- системные события обслуживания памяти.

Хранилище находится в общей локальной `data/sayuri-memory.db`.

Повторная обработка одного и того же action/feedback не раздувает Episodic Memory: для внешне идентифицируемых исходов используется idempotent fingerprint.

### Knowledge Memory

Подтверждённые факты, решения и устойчивые предпочтения могут быть повышены до `knowledge_items`.

У знания сохраняются:

- область `personal/project`;
- тип;
- statement;
- confidence;
- список исходных memory IDs;
- `valid_from`;
- `valid_to`;
- `supersedes_id`;
- статус.

Оригинальные источники не удаляются при promotion/consolidation. Если пользователь вручную архивирует единственный активный источник, производное Knowledge перестаёт считаться confirmed; при наличии других активных источников они сохраняются.

### Knowledge Graph

Memory 3.0 строит локальный граф:

- person;
- project;
- document;
- memory;
- knowledge;
- decision;
- vehicle;
- company;
- event.

Связи включают:

- `has_memory`;
- `source_for`;
- `grounded_in`;
- `supports`;
- `supersedes`;
- `mentions`.

Из context автоматически создаются связи с открытым документом. Для текста детерминированно распознаются VIN и госномер как vehicle nodes.

### Temporal Memory

Все важные изменения памяти записываются в `memory_timeline`:

- сохранение;
- принятие кандидата;
- открытие конфликта;
- разрешение конфликта;
- архивирование;
- консолидация;
- обслуживание памяти;
- значимые эпизоды.

Это позволяет различать «что было раньше» и «что актуально сейчас».

### Memory Consolidation

Похожие записи одного scope/kind сравниваются Semantic Memory.

При similarity >= `0.72` создаётся устойчивое knowledge item с полным списком исходных memory IDs.

Консолидация **не удаляет оригинальные записи** и не генерирует новый текст через LLM. Канонической формулировкой становится наиболее сильный исходный источник.

### Forgetting / Retention Engine

Физического автоматического удаления нет.

Каждая запись получает `retention_score 0..1`, рассчитанный по:

- importance;
- confidence;
- use-count;
- времени с последнего использования/изменения;
- защите важных decisions/preferences.

Semantic retrieval умножает relevance на retention factor. Устаревающая информация постепенно становится менее заметной, но остаётся доступной и проверяемой.

Порог stale candidate: `0.30`.

### Contradiction Resolver

После принятия конфликтующего memory candidate создаётся отдельная запись `memory_conflicts`.

Пользователь выбирает:

- `prefer_new` — новое актуально;
- `prefer_old` — старое актуально;
- `keep_both` — оба утверждения допустимы.

Проигравшая запись мягко архивируется (`active=0`), а не физически удаляется. Связанное knowledge получает временную границу `valid_to`.

### Автоматизация

При запуске Agent Core:

1. существующая долговременная память синхронизируется с Knowledge Graph;
2. подходящие записи повышаются до Knowledge Memory;
3. пересчитывается retention;
4. раз в 6 часов opportunistic maintenance запускает consolidation и общий аудит.

Также доступно ручное «Обслужить память» в Личном кабинете.

## AI Context

DeepSeek-V4-Flash получает отдельные недоверенные блоки:

1. Semantic Memory — personal/project;
2. Experience Learning — helpful/avoid;
3. Memory 3.0 — working focus, relevant knowledge и relevant episodes;
4. текущий UI-context.

Открытые конфликты передаются и точным количеством, и ограниченным old/new содержимым. Они не считаются автоматически разрешёнными.

## Личный кабинет

Добавлен полноценный Memory 3.0 dashboard:

- Working Memory;
- Episodic Memory metrics;
- Knowledge Memory;
- Temporal Memory timeline;
- Knowledge Graph;
- Contradiction Resolver;
- Forgetting Engine;
- consolidation metrics;
- stale-memory metrics;
- ручное обслуживание.

## API

- `GET /api/sayuri/memory/v3`
- `POST /api/sayuri/memory/v3/maintenance`
- `POST /api/sayuri/memory/v3/conflicts/{id}/resolve`

Существующие memory/intelligence/experience API сохраняются.

## Безопасность и инварианты

- данные Memory 3.0 остаются локальными;
- никаких дополнительных внешних AI-моделей;
- personal/project не смешиваются;
- Experience не становится фактом;
- consolidation не удаляет источники;
- forgetting не удаляет память;
- конфликт не разрешается без пользователя;
- Memory 3.0 не расширяет tool permissions;
- изменяющие действия по-прежнему confirmation-gated.

## Следующий этап

После стабилизации `0.1.43`:

1. Reasoning Planner;
2. Result Verifier;
3. controlled DNA-context с доказательствами;
4. planner strategy memory поверх Experience Learning.
