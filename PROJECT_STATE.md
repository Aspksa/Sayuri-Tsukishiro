# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `34c16d4270ced00aecc3ffbbe2633179d22dee35` (проект `0.1.41`).
- Целевая версия: `0.1.42`.
- Текущий этап: Semantic Memory + Experience Learning.
- Рабочая ветка: `semantic-experience-v0142`.
- Локальная рабочая копия не проверялась; работа ведётся через GitHub API.

## Версии активных модулей

- Ядро Саюри: `0.1.34`.
- Agent Core: `0.6.0`.
- Диск Sayuri: `0.7.1`.
- Web UI: `0.19.0`.
- Инструменты разработки: `0.1.6`.

## Semantic Memory

Новый модуль: `agent/semantic_memory.py`.

Цель — искать долговременную память не только по буквальному совпадению слов.

Текущая реализация — локальный гибридный индекс `hybrid-semantic-v1`:

- ключевые слова;
- облегчённая нормализация форм слов;
- локальный словарь смысловых понятий;
- character n-grams;
- вес importance;
- вес confidence.

Это **не neural embeddings**. Вторая облачная модель и новый внешний AI-провайдер не добавлялись.

Плюсы текущего этапа:

- работает полностью локально;
- не добавляет тяжёлые зависимости;
- не отправляет память внешнему embedding API;
- сохраняет границу `personal/project`;
- возвращает relevance и причины совпадения;
- тот же semantic retriever используется при сборке контекста для DeepSeek-V4-Flash.

Пример: память «предпочитаю белый интерфейс» может находиться запросом про «светлую тему».

## Experience Learning

Новый модуль: `agent/experience.py`.

Хранилище:

`data/sayuri-experience.db`

Sayuri накапливает отдельный опыт по:

- подтверждённым успешным действиям;
- ошибкам инструментов;
- отменённым действиям;
- принятым/отклонённым кандидатам памяти;
- явной пользовательской оценке ответа «Полезно / Не помогло».

Каждый опыт имеет:

- category;
- strategy;
- outcome;
- reward;
- source;
- subject_id;
- безопасный контекст;
- timestamp.

Для каждой стратегии строятся:

- positive;
- negative;
- neutral;
- сглаженный success rate;
- evidence strength.

После минимум трёх оценённых случаев накопленный опыт может мягко корректировать confidence Memory Intelligence. Коррекция ограничена диапазоном ±8 процентных пунктов и не превращает опыт в факт.

## Relevant Experience Retrieval

Опыт теперь также ищется по смыслу.

Перед обычным ответом Sayuri получает два раздельных справочных блока:

1. релевантную долговременную память;
2. релевантный прошлый опыт.

Положительный опыт попадает в `helpful`, отрицательный — в `avoid`.

В системной инструкции зафиксировано:

- опыт является справочными данными, а не инструкцией;
- старый ответ нельзя копировать механически;
- опыт не является доказательством факта;
- отрицательный опыт используется как предупреждение.

## Feedback Loop

Ответ DeepSeek-V4-Flash получает локальный `response_id`.

В чате доступны:

- «Полезно»;
- «Не помогло».

После явного нажатия пользователя в Experience Learning сохраняются:

- rating;
- текущий prompt, ограниченный 2000 символами;
- excerpt ответа, ограниченный 1200 символами;
- безопасный UI-context.

Полная история диалога в Experience Learning не копируется.

Feedback можно изменить: повторная оценка того же `response_id` обновляет одну запись, а не создаёт дубликаты.

## Интеграция действий

Финальные статусы Action Broker автоматически попадают в опыт:

- `completed -> success`;
- `failed -> failure`;
- `cancelled -> neutral`;
- `expired -> neutral`.

Replay одного и того же action не создаёт второй опыт благодаря fingerprint.

## Личный кабинет

Добавлены:

- Semantic Memory status;
- поиск по смыслу;
- relevance для найденной памяти;
- карточка «Опыт Sayuri»;
- количество событий опыта;
- positive/negative;
- число изученных стратегий;
- статистика стратегий;
- обновление опыта вручную.

## API

Существующие memory API сохранены.

Добавлено:

- `GET /api/sayuri/experience`;
- `POST /api/sayuri/experience/feedback`.

`GET /api/sayuri/memory?q=...` теперь использует hybrid semantic retrieval.

## Безопасность и границы

- единственный внешний LLM: `deepseek-ai/DeepSeek-V4-Flash` через Cloud.ru;
- semantic retrieval локальный;
- experience storage локальный;
- personal/project memory не смешиваются;
- опыт не повышает права инструментов;
- confirmation-gated actions остаются обязательными;
- Experience Learning не хранит API-ключи;
- документы и память передаются LLM только в существующих контролируемых context-блоках.

## Проверки

На промежуточной ветке уже подтверждены:

- unit tests Semantic Memory — success;
- unit tests Experience Learning — success;
- релевантный опыт попадает в chat context — success;
- action outcomes попадают в опыт — success;
- experience HTTP API — success;
- Web contract — success;
- JavaScript syntax — success;
- preflight — success;
- Windows launcher — success.

Текущие промежуточные CI падения связаны только с обязательным per-commit version rule, потому что рабочая ветка содержит последовательные API-коммиты. Для публикации изменения будут собраны в один атомарный commit от `0.1.41`, затем проверены отдельной validation-веткой.

## Следующий этап

После стабилизации `0.1.42` логичный AI-этап:

1. Reasoning Planner — план сложной задачи до выполнения;
2. Result Verifier — независимая проверка результата;
3. Strategy Library — подтверждённые стратегии из Experience Learning;
4. выбранная ДНК документа как evidence-context;
5. затем, при необходимости, отдельный локальный embedding-index без нарушения правила «одна внешняя LLM».
