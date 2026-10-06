# Текущее состояние Sayuri-Tsukishiro

## Контрольная точка

- Дата: 2026-10-06.
- Репозиторий: https://github.com/Aspksa/Sayuri-Tsukishiro
- Проверенная исходная ревизия: `ab10ff8d0388c1f26c7dd7b635635298e9b129ba` — проект `0.1.52`, Rich Answer UX & Lazy Diagnostics.
- Исходный финальный workflow: Versions #493 — success.
- Целевая версия: `0.1.53`.
- Текущая задача: **AI-008 — Spatial Evidence Citations**.

## Версии целевого дерева

- Проект: `0.1.53`.
- Ядро Саюри: `0.1.45`.
- Agent Core: `0.11.0`.
- Web UI: `0.29.0`.
- Диск Sayuri: `0.8.0`.
- SpatialDNAEngine: `0.8.0`.
- Dev tools: `0.1.6` — не изменяются.
- DB schema: `7` — не изменяется.
- DNA schema: без изменения.

## Архитектура

```text
Planner
→ deterministic document.evidence_search
→ ONLY cached DNA of current UI file
→ accepted/review fact + exact_from_document_engine locator
→ privacy/instruction firewall
→ bbox stays local
→ D1..D6 + fact/page/line to DeepSeek
→ Answer
→ Result Verifier
→ unknown D citations stripped locally
→ public evidence
→ click D#
→ file_id + fact_id
→ backend resolves stored bbox
→ PDFium/Pillow highlighted Evidence Focus
```

## Инварианты

1. DeepSeek не получает filesystem path и bbox.
2. Browser не передаёт bbox в evidence-focus API.
3. Citation geometry не выводится из текста модели.
4. Только cached DNA; chat не запускает `document_dna()`/OCR автоматически.
5. Rejected facts не цитируются.
6. Exact citation требует `coordinate_status=exact_from_document_engine`.
7. Unknown `[D#]` удаляется runtime firewall.
8. Mutation permissions не расширяются; Action Broker остаётся единственным путём изменений.
9. Raw receipts/tool IDs не появляются в пользовательском evidence.
10. Структура меню не меняется.

## Evidence Focus API

`GET /api/disk/files/{id}/evidence-focus?fact_id=...`

Backend повторно разрешает fact_id в cached DNA и только затем использует locator bbox.

## Проверки

- Tool Planner: read-only allowlist + deterministic document intent.
- Agent: D-citation allowlist, unknown marker stripping, public evidence privacy.
- Disk/Spatial: cached evidence search, exact locator, fact-id-only rendering.
- Web: inline citation, Evidence Summary, Evidence Focus, no bbox query.
- Existing Action Broker, Memory, DNA, launcher regressions сохраняются.

## Неудачная проверка, которую не повторять

- Ветка: `spatial-citations-v0153`.
- Commit: `de37a39b6dd9eacf384bb73b2641a826e162a181`.
- Workflow: Versions #494 — failure.
- Windows launcher и version tooling: success.
- Падение 1: старый API-тест ожидал Spatial Engine `0.7.0`; целевая версия корректно повышена до `0.8.0`.
- Падение 2: новый runtime citation test сформулировал запрос без достаточных complexity markers и поэтому корректно попал в direct-mode; тест не проверил planned pipeline.
- Исправление r2: обновить API expectation до `0.8.0` и сделать тестовый запрос однозначно planned через существующий deterministic complexity gate.
- Production policy, citation firewall, fact-id-only endpoint и spatial geometry не ослабляются.
- Failed-ветка не merge-ится; r2 строится одним чистым commit от `main 0.1.52`.

## Релизный критерий 0.1.53

1. Один атомарный commit от `main 0.1.52`.
2. Agent/Core/Disk/Web tests — success.
3. JavaScript syntax — success.
4. Preflight — success.
5. Version tooling / each-commit — success.
6. Windows launcher checks — success.
7. PR merge.
8. Финальный `main` workflow — success.

## Следующий рациональный этап

После стабилизации v0.1.53 — claim-to-evidence coverage: измерять долю важных фактических утверждений, у которых есть поддержанная D-citation, и добавлять multi-page/multi-fact evidence groups без раскрытия технических receipts.
