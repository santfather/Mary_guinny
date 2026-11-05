# PROJECT AUDIT 2026-11 — Mary Studio

**WP-AUDIT-01: Full Project Audit, Consolidation & Safe Cleanup Plan**

Дата: **2026-11-05**. Рабочий каталог: `/Users/vladislavkovalenko/Projects/Mary_Guiness`.
Режим: **READ-ONLY**. Не добавлено ни одной функции, не изменён ни один файл кода или
существующий документ, не выполнено ни одной миграции, не изменена ни одна строка БД,
не запущена и не отменена ни одна job, ни один asset не утверждён/отклонён, коммитов нет.

Единственное изменение в репозитории — создание этого каталога документов
`docs/AUDITS/` (7 файлов, разрешено §16 задания).

Сопутствующие документы:

- `COMPONENT_INVENTORY.md` — инвентарь компонентов и классификация;
- `STORAGE_INVENTORY.md` — диск, blob, дубли, orphan;
- `DATABASE_INTEGRITY.md` — SELECT-аудит БД;
- `CLEANUP_CANDIDATES.md` — кандидаты с полными карточками;
- `CLEANUP_EXECUTION_PLAN.md` — 3 этапа (не выполнялись);
- `OPEN_RISKS.md` — риски и решения, которые нужны от человека.

---

## 1. Executive Summary

1. **Ядро Mary Studio работает и подтверждено данными, а не только тестами.**
   44 шота в 3 проектах, 49 завершённых `video`-попыток, 40 видео-артефактов на диске
   (105 199 441 Б), 46 keyframe-артефактов, 1 собранный экспорт
   (`artifact export_video`, 12 763 131 Б), 7 прогонов серий, 9 464 события.
2. **Полноценная LTX-видеогенерация подтверждена только на NLB.** 31/31 шот имеют
   стартовый кадр, `NLB-single` — 24/24 `completed`, `NLB-single wide (28-30)` — 3/3,
   плюс одиночный Eco-рендер NLB-25 (WP-THERMAL-03). **GNS ни разу не рендерился LTX**:
   у GNS-05 четыре video-попытки — это talking preview, а не I2V.
3. **Три подхода к анимации рта не дали приемлемого качества.** `mouth_animation_mvp`
   (рот накрыл глаз/нос), `pillow_mouth_v2` (калибровка сдвинута, не утверждено),
   `viseme_frame_blend_v1` + Rhubarb (сборка B не утверждена из-за прямоугольного шва
   патча). Это экспериментальная ветка, а не production-функция.
4. **Аудио-инфраструктура — рабочая и самостоятельная ценность**: импорт
   WAV/MP3/M4A/AAC, рабочая PCM 48 кГц mono, огибающая, waveform, approval,
   FFmpeg-assembly. Её нельзя удалять из-за плохого lip sync.
5. **БД структурно здорова, но содержательно неполна.** 54 FK, **0 нарушений**
   (включая 6 составных project-isolation), 0 «битых» approved-ссылок. При этом
   **198 artifacts (18 924 421 Б) ссылаются на отсутствующие файлы** — 197
   `project_audio` + 1 `note`.
6. **Эталона качества нет:** `shots.approved_attempt_id` пуст во всех 44 шотах
   (0 approved attempts во всех проектах).
7. **Главный операционный риск — незакоммиченная работа:** ветка
   `wp-m0-maestro-audit`, HEAD `e3c391b`, **69 изменений** (31 modified + 38 untracked),
   включая применённую миграцию `0011_mouth_calibrations` и весь код WP-M2…WP-VOICE-06.
   `main` отстаёт (`2d3fc72`).
8. **Второй операционный риск — pending job `852adc5d…`** (GNS-05,
   `render_video`, `pending`, `lease_owner NULL`): стартует при любом запуске воркера.
9. **Диск:** проект 3.3 GB (`runtime` 2.5 GB, `export/LLM-gen` 241 MB, `storage` 149 MB),
   свободно 66 GiB. Реально безопасно освободить **≈4.8 MB** (Stage 1) и до **≈457 MB**
   (Stage 3, после решений). Основной вес — вне проекта: `~/.ollama` 85 GB,
   `~/.cache/huggingface` 65 GB.
10. **Документация в целом актуальна, но есть мусор:** `CLAUDE.md` описывает чужой
    проект `github-crawler`; `docs/VIDEO-ORCHESTRATOR.md` отсутствует; три черновика
    (`AI_Tools_Analysis.md`, `scenario.md`, `docs/new_updates.md`) вне контракта.
11. **Ничего не удалено и не изменено.** Все действия вынесены в план из трёх этапов и
    требуют отдельного разрешения.

---

## 2. Ответы на 12 вопросов (§17)

### 1. Что в Mary Studio действительно работает?

**Работает и проверено реальными данными/рендерами:**

| Что | Доказательство |
|-----|----------------|
| Библиотека и референсы | 50 `reference_assets` (29 approved / 19 draft / 2 rejected), 44 уникальных blob, 0 отсутствующих файлов |
| Шоты, сцены, композиции | 44 шота / 9 сцен / 2 композиции / 48 `shot_references` / 48 `prompt_revisions` |
| Keyframe-пайплайн | 46 `keyframe`-артефактов; 33/44 шота имеют `start_keyframe_artifact_id` |
| RTX/LTX I2V для NLB | 40 видео-артефактов; `NLB-single` 24/24 completed; `wide` 3/3; MP4 — h264 576×1024/193 кадра/24 fps + aac |
| Очередь job | 53 job: 45 `render_video` completed, 3 failed, 1 pending, 4 `mouth_animation` completed; 0 зависших lease |
| Series orchestrator | 7 прогонов, 33 item (32 completed, 1 failed) |
| Экспорт/сборка | 1 `export_video` артефакт (12.8 MB), UI `#/exports` |
| Thermal-гейт | 38 тестов + один живой Eco-рендер NLB-25 (`WP_THERMAL_03_REPORT.md` §11.2) |
| Импорт аудио | `shot_audio` approved у GNS-05, файл на диске |
| Планировщик/план | 2 `production_plans`, 1 аудио у NLB, BPM 60.0 (уверенность 0.91) |

**Работает, но не проверено живым рендером:** recovery воркера (WP-M4 — проверен),
preview-first (только тесты), `safe`/`wide` пресеты (safe — 24 рендера, wide — 3),
scene planner (0 записей `visual_scene_plans`).

**Не работает как продукт:** lip sync (всегда 409), talking character (качество не
принято), GNS-видео (0 LTX-рендеров).

### 2. Какие функции полезны и должны остаться?

1. Библиотека персонажей/локаций/предметов + approval (S13–S15).
2. Импорт изображений и аудио в content-addressed blob с провенансом (S12).
3. Шоты → композиции → keyframe → promote-keyframe → render-gate.
4. Очередь job с lease/heartbeat/resume и worker API.
5. LTX-воркер + ComfyUI + presets + thermal-гейт (единственный проверенный путь
   получения видео).
6. Series orchestrator + экспорт FFmpeg (сборка ролика).
7. Аудио-инфраструктура: импорт, конвертация, огибающая, waveform, approval.
8. Production plan (черновой) и scene plans (советующие).
9. UI-обзор попыток, прогресса job и термозащиты.

### 3. Какие эксперименты не оправдали себя?

| Эксперимент | Почему |
|-------------|--------|
| `mouth_animation_mvp` / `pillow_mouth_v2` | рот накрывал глаз и нос; после сдвига калибровки визуально не принято; 0 approved |
| `viseme_frame_blend_v1` + Rhubarb | технически работает (82 интервала), но прямоугольный шов патча; A/B не утверждён |
| Lip sync adapter | движок не выбран, API всегда 409 |
| Visual scene plans | 0 записей, живой сценарий не использовался |
| Legacy pipeline (`pipeline/stages/*`, `main.py`) | заменён API+воркером, остался историческим кодом |

### 4. Что можно отключить без потери данных?

- Lip sync (DI-01): API и UI-панель ничего не пишут.
- `mouth_animation_mvp` как режим по умолчанию (переключение на него — только вручную);
  данные калибровок и preview сохраняются.
- `viseme_frame_blend_v1` — эксперимент, данные (5 approved кадров, 2 попытки) остаются.
- Rhubarb как автоматический источник таймингов — только ручной вызов.
- Legacy `main.py`/`pipeline/stages` — не вызываются приложением.

### 5. Какие файлы можно безопасно удалить?

Только два файла и кэши (полные карточки — `CLEANUP_CANDIDATES.md`):

| Файл | Размер | Почему безопасно |
|------|--------|------------------|
| `storage/blobs/.DS_Store` | 14 340 Б | 0 ссылок из БД |
| `storage/blobs/20/201bc4b0….wav` | 1 136 138 Б | 0 ссылок из БД |
| `ui/dist`, `.pytest_cache`, `__pycache__` | ≈3.6 MB | воспроизводимо |

Плюс после отдельного согласования: `CLAUDE.md` (3 012 Б, чужой проект), пустые
`exports/` и `comfyui-input/`, 5 мёртвых методов клиента (≈40 строк), строка
`worker_lease_seconds` в `config.py:53`.

**Нельзя удалять:** `storage/blobs/*` (кроме двух orphan), 198 строк `artifacts`,
29 approved references, `characters/`, `episodes/`, `docs/cats`, `comfyui-workflows`,
`pipeline/utils.py`, `pipeline/comfyui/{client,ltx_adapter}.py`.

### 6. Сколько дискового пространства потенциально освободится?

| Этап | Освобождение | Состав |
|------|--------------|--------|
| Stage 1 | **≈4.8 MB** | 2 orphan (1.15 MB) + кэши (3.6 MB) |
| Stage 2 | ≈0.05 MB | мёртвый код/документы |
| Stage 3 | **до ≈457 MB** | `export/LLM-gen` 241 MB + `ComfyUI/output` 149 MB + `ComfyUI/input` 57 MB + `wp_voice_06_ab` 10 MB |
| Опционально | 160 MB | `ui/node_modules` 71 MB + `backend/.venv` 89 MB (восстановимы) |

Итог: 3.3 GB → ≈2.85 GB. Модели (`~/.ollama` 85 GB, HF 65 GB) в этот план не входят и
удалению не подлежат.

### 7. Какие данные нельзя трогать?

- `storage/blobs` — 99 живых артефактов и 44 reference-blob.
- Строки `artifacts` (297) — история и провенанс; 198 «битых» — тоже данные.
- `reference_assets` — 29 approved, иммутабельны (S15).
- `shots`, `scenes`, `series_*`, `render_attempts`, `events` — рабочие данные.
- `characters/`, `episodes/`, `docs/cats/*` — исходники approved-референсов.
- `comfyui-workflows/*.api.json` — `workflow_version` привязан к sha256 шаблона.
- `backend/alembic/versions/*` — применённые миграции (head `0011`).
- `.env` (181 Б) — не читался и в отчёт не попал.
- pending job `852adc5d…` — нельзя ни запускать, ни отменять в аудите.
- `~/.ollama`, `~/.cache/huggingface`, `~/.mary-studio/tools/rhubarb-1.14.0/`.

### 8. Есть ли опасные jobs или фоновые процессы?

**Да, одна job:** `852adc5d-5a56-415b-8d3f-0fa6077c9653` — `render_video`, `pending`,
shot `6532e96d…` (GNS-05), `attempts 0/3`, `lease_owner NULL`, 0 событий, payload
содержит `start_keyframe_artifact_id d2767fbd…`. Она **стартует при следующем запуске
воркера** и станет первым LTX-рендером GNS (≈1062 с, 18 GB RAM).

Фоновые процессы на момент аудита (`lsof`): Ollama `127.0.0.1:11434` (PID 868),
Vite `127.0.0.1:5173` (PID 13707), uvicorn `127.0.0.1:8000` (PID 15028).
**ComfyUI не запущен**, воркер не запущен, `caffeinate` не запущен.
`launchctl` проверить не удалось (permission denied) — **NOT VERIFIED**.

### 9. Есть ли проблемы целостности БД?

Структурно — **нет**: 54 FK, 0 нарушений (в т.ч. 6 составных project-isolation),
0 approved-ссылок на чужой шот, 0 completed-попыток без артефакта.

Содержательно — **три проблемы**:

1. **198 artifacts без файлов** (18 924 421 Б): 197 `upload/project_audio` + 1 `upload/note`.
2. **0 approved attempts** во всех проектах — нет эталона.
3. **4 строки `workers` со stale `status='active'`** (последний `last_seen_at`
   2026-11-04 17:51, воркеров нет).

Плюс 4 шота `prompt_ready` без стартового кадра (GNS-01…04) — данные корректны, но
статус завышен относительно готовности к рендеру.

### 10. Какие части архитектуры стоит упростить?

1. **Legacy pipeline**: `main.py` + `pipeline/orchestrator.py` + `pipeline/stages/*` +
   `pipeline/comfyui/{generator,scene_draft,workflows}.py` дублируют современный поток.
   Оставить только `pipeline/utils.py`, `pipeline/comfyui/client.py`,
   `pipeline/comfyui/ltx_adapter.py`.
2. **Два движка рта** с общим API — оставить один экспериментальный путь (viseme) либо
   явно пометить оба как experimental.
3. **Мёртвый lip sync** (код + UI + 4 теста) — один из двух: удалить или убрать UI.
4. **UI-клиент**: 5 неиспользуемых методов; 10 API-маршрутов без UI (worker/CLI — норма,
   но 3 из них — кандидаты на документирование как «внутренние»).
5. **Документация**: 21 файл в `docs/PROPOSALS` и 7 в `docs/REPORTS` без индекса;
   предложена компактная структура (§14).
6. **Конфигурация**: `worker_lease_seconds` не читается; `MARY_DISABLE_NOTIFY` читается
   вне `Settings` (несогласованность).

### 11. Что мешает стабильной видеогенерации?

| Препятствие | Доказательство |
|-------------|----------------|
| Память 18 GB на границе | `hw.memsize` 18.0 GiB; 1080×1920 уже останавливался по памяти (`AGENTS.md`); safe-режим 576×1024 |
| Thermal-гейт | доступно ≈3.9 GiB при пороге Eco ≥4 GiB (`vm_stat`); cooldown 480/1200 с |
| Долгий рендер | ≈1062 с/шот safe; `NLB-single` 24 шота — 7 ч 05 мин |
| Нет эталонных дублей | 0 approved attempts |
| Recovery зависит от ComfyUI | потеря prompt'а → `external_prompt_lost`; state-файл `~/.mary-studio/ltx-worker-state.json` |
| ComfyUI не в Git | версия/commit custom node не зафиксированы |
| Сцен-кадры вне системы | planner не генерирует изображения; SDXL/IPAdapter отсутствуют |
| Плохое качество talking/lip sync | не влияет на LTX, но блокирует «говорящего персонажа» |

### 12. Какой минимальный набор функций должен остаться в Mary Studio?

**MVP, который уже работает и покрывает NLB end-to-end:**

1. Проекты → сцены → шоты; библиотека персонажей/локаций/предметов; референсы + approval.
2. Prompt revisions + композиция/слои + keyframe + `promote-keyframe`.
3. Render-gate → job → воркер → LTX I2V (presets `safe`/`wide`) → artifact → попытка.
4. Review попытки (approve/reject) + прогресс job.
5. Series run (порядок, пауза/резюм) + thermal-гейт.
6. Экспорт: FFmpeg-сборка ролика.
7. Импорт аудио проекта/шота (для будущего звука и для сборки).
8. UI: `#/characters`, `#/shots`, `#/shot/{id}`, `#/attempts`, `#/exports`,
   `#/series/{id}`, `#/plan`.

**Вне MVP (оставить как experimental/archive):** mouth animation, viseme blend, Rhubarb,
lip sync, talking preview, scene planner.

---

## 3. Git & Repository Audit (§3)

| Параметр | Значение |
|----------|----------|
| Ветка | `wp-m0-maestro-audit` (отслеживает `origin/wp-m0-maestro-audit`) |
| HEAD | `e3c391b feat: complete WP-M1–M8 and WP-THERMAL-02` |
| `main` | `2d3fc72` — **отстаёт** от текущей работы |
| Remote | `git@github.com:santfather/Mary_guinny.git` |
| Незакоммичено | **69** (31 modified + 38 untracked) |
| Untracked по каталогам | `backend/app` 18, `docs/PROPOSALS` 13, `ui/src` 9, `docs/cats` 8, `backend/tests` 7, остальное — по 1 |
| Git-объекты | 567 loose, 15.09 MiB, pack 0 |
| Секреты | `git grep` по `sk-…`, `ghp_…`, `BEGIN … PRIVATE KEY` → **0** совпадений |
| `.env` | есть в корне (181 Б), ignored; `backend/.env` отсутствует |

Крупнейшие tracked-файлы — `docs/cats/*.png`: 2 614 008 Б (`Feline Rock Band Under Neon
Lights.png`), 2 297 808 Б, 2 248 916 Б; далее 6 PNG по 665–762 KB. MP4/WAV в Git нет.

**Что должно быть в Git:** код, миграции, документы, workflow JSON, `docs/cats/*.png`
(источники approved-референсов), `prompts/`.

**Только локально:** `storage/`, `runtime/`, `export/`, `exports/`, `ui/node_modules`,
`ui/dist`, `backend/.venv`, `.env`, медиа в `characters/` и `episodes/`.

**Риск очистки:** любые Stage-1/2 действия не затрагивают tracked-файлы, кроме
`CLAUDE.md` и 5 методов клиента; 69 незакоммиченных изменений **не затрагиваются**, но
именно они — главный риск потери (см. `OPEN_RISKS.md` R-02).

---

## 4. Architecture Audit (§4)

Фактическая цепочка:

```
Project → Episode → Scene → Shot → ShotReference → ReferenceAsset
        → PromptRevision → (Composition → Layer)
        → start_keyframe_artifact_id
        → Job(render_video) → RenderAttempt → Artifact(blob)
        → Review (approve_attempt / reference approve)
        → SeriesRun → SeriesItem → Job
        → Export(assembly) → Artifact(export_video)
```

Соответствие БД: `projects` 3 → `episodes` 3 → `scenes` 9 → `shots` 44;
`reference_assets` 50, `shot_references` 48, `prompt_revisions` 48;
`shot_compositions` 2 / layers 2; `jobs` 53 → `render_attempts` 102 → `artifacts` 297;
`series_runs` 7 → `series_items` 33; `events` 9 464.

**Найденные проблемы:**

- **Дублирующий механизм:** legacy `pipeline/orchestrator.py` + `stages/*` и современный
  API/worker-поток решают одну задачу; legacy не используется приложением.
- **Два движка рта** (`mouth_animation_mvp`/`pillow_mouth_v2` и `viseme_frame_blend_v1`)
  с раздельными API и UI-панелями.
- **Мёртвые API:** 10 маршрутов без UI, из них `POST /api/shots/{id}/lipsync` —
  гарантированный 409, `GET /api/rhubarb/status` — только диагностика.
- **UI без backend:** нет (все страницы бьются в существующие маршруты).
- **Мёртвые кнопки:** панель lip sync (статичный текст), `<select value="image" disabled>`
  «Video Talking — Not Supported» в `MouthAnimationPanel.tsx`.
- **Устаревший feature flag:** единственный `VITE_FEATURE_LIPSYNC`
  (`ShotDetailPage.tsx:24`), включает нерабочую функцию.
- **Конфликтующие конфигурации:** `worker_lease_seconds` в `Settings` не читается;
  `MARY_DISABLE_NOTIFY` читается напрямую из `os.environ` (`notify.py:24`).

---

## 5. Video Generation Audit (§5)

### 5.1 Что реально передаётся в модель

`pipeline/comfyui/ltx_adapter.py` требует обязательные входы
`prompt, image, seed, width, height, num_frames, frame_rate, filename_prefix` (+
`cfg_scale`, по умолчанию 3.0). Модель: `dgrauet/ltx-2.3-mlx-q4`
(`comfyui-workflows/ltx23_mlx_q4_i2v.api.json:11`), `workflow_version` = префикс +
sha256 шаблона.

Реально настраивается:

| Параметр | Источник | Где видно |
|----------|----------|-----------|
| `seed` | воркер (детерминированный/переданный) | `render_attempts.parameters.seed` |
| `width`/`height` | preset (`safe` 576×1024, `wide` 1024×576, `legacy_512` 512×512) | `parameters` + `presets.py` |
| `num_frames` | `snap_frames` (8k+1, 9…257) | `parameters.num_frames` |
| `frame_rate` | 24 | `parameters.frame_rate` |
| `cfg_scale` | 3.0 | `parameters.cfg_scale` |
| `filename_prefix` | уникальный на попытку | `parameters.filename_prefix` |
| `preview` | только preview-first (73 кадра) | `parameters.preview`, `preview_cannot_be_approved` |

**Только в документации/UI, но не в модели:** thermal-профиль (влияет на допуск, не на
кадр), `long_side` (используется для расчёта размера), «название прогона».

**Вывод:** отдельного UI-экрана render settings нет; пресеты выбираются в воркере
(`--preset`), preview — чекбоксом на шоте. Это соответствует WP-M7/THERMAL-03, но
означает, что «настройки рендера в UI» — не функция системы.

### 5.2 Пять категорий §5

| Категория | Что |
|-----------|-----|
| **1. Работает и проверено реальным рендером** | LTX I2V `safe` 576×1024/193/24 (24 шота NLB + NLB-25 Eco), `wide` 1024×576 (3 шота), экспорт FFmpeg, recovery (`external_prompt_lost`), thermal pause/resume |
| **2. Реализовано, не проверено на GPU** | `preview-first` (только тесты), `legacy_512` preset (исторический WP-00A), `wide`-повтор после аудита |
| **3. Экспериментально** | talking preview (4 попытки), viseme blend (1 сборка B) |
| **4. Не работает** | lip sync (409), GNS-видео (0 LTX-попыток), talking character (качество) |
| **5. Не используется** | `visual_scene_plans` (0), `job_dependencies` (0), legacy pipeline stages |

---

## 6. Audio & Lip Sync Audit (§6)

### A. Полезная универсальная инфраструктура — **KEEP**

| Компонент | Доказательство |
|-----------|----------------|
| Импорт аудио шота (`shot_audio.py`) | `reference_assets(role='shot_audio')` approved у GNS-05; WAV/MP3/M4A/AAC, ≤16 МиБ |
| Конвертация в PCM 48 кГц mono + огибающая | `WP_VOICE_02_REPORT.md`; artifact `talking_preview` 4 шт. |
| Waveform | `GET …/shot-audio/waveform` |
| Хранение | blob + `artifacts`/`reference_assets` |
| Approval/review | 29 approved, UI approve/reject |
| Синхронизация/сборка | `assembly.py` — trim → scale/pad 1080×1920 → 24 fps → concat → h264/aac; 1 export artifact |

### B. Экспериментальные алгоритмы — **KEEP_EXPERIMENTAL**

| Алгоритм | Технически | Качество | Стоимость сопровождения | Отключаемость | Удаление без потери данных |
|----------|-----------|----------|--------------------------|----------------|----------------------------|
| `mouth_animation_mvp` | работает (4 job) | не принято | низкая (Pillow) | да | нет: 4 preview ссылаются |
| `pillow_mouth_v2` | работает (2 попытки) | не принято | низкая | да | нет |
| `viseme_frame_blend_v1` | работает (сборка B) | шов патча | средняя (5 кадров, калибровка) | да | нет: 5 approved viseme |
| Rhubarb timing | работает (82 интервала) | только тайминги | средняя (Rosetta, внешний бинарник) | да | да, но потеря воспроизводимости B |

**Правило из задания соблюдено:** аудит не предлагает удалять аудио-инфраструктуру
из-за качества lip sync; `shot_audio`, waveform, огибающая и assembly остаются.

---

## 7. Database Audit (§7)

Полный отчёт — `DATABASE_INTEGRITY.md`. Кратко:

- 24 таблицы, БД 14 MB, head `0011_mouth_calibrations`.
- 54 FK, **0 нарушений**; 0 approved-ссылок на чужой шот; 0 completed-попыток без артефакта.
- 198 artifacts без файлов (18 924 421 Б) — `INVESTIGATE`.
- 4 `workers` со stale `status='active'`.
- 4 `prompt_ready` шота без стартового кадра (GNS-01…04).
- 0 approved attempts.
- `visual_scene_plans` 0, `job_dependencies` 0.
- Pending job `852adc5d…` — детально §6 `DATABASE_INTEGRITY.md`.

---

## 8. Storage & Disk Audit (§8)

Полный отчёт — `STORAGE_INVENTORY.md`. Кратко:

- 3.3 GB проект; `runtime` 2.5 GB (65 585 файлов), `export` 251 MB, `storage` 149 MB,
  `backend` 93 MB (в т.ч. `.venv` 89 MB), `ui` 71 MB (`node_modules`), `docs` 25 MB
  (`docs/cats` 24 MB), `characters` 9.1 MB, `episodes` 3.4 MB.
- `storage/blobs`: 103 файла, 155 656 663 Б; 49 mp4, 45 png, 3 jpg, 2 jpeg, 2 mp3, 1 wav,
  1 `.DS_Store`.
- 2 orphan: `.DS_Store` и `201bc4b0….wav` (1 150 478 Б суммарно).
- Дубли: 6 межпроектных пар `sha256` в `reference_assets`; 10 групп `storage_key` в
  `artifacts` (28 строк) — дедупликация, не мусор.
- Вне проекта: `~/.ollama` 85 GB, `~/.cache/huggingface` 65 GB.

---

## 9. Models & Dependencies (§9)

| Компонент | Путь | Размер | Архитектура / версия | Лицензия | Потребитель | Восстановление |
|-----------|------|--------|----------------------|----------|-------------|----------------|
| LTX-2.3 MLX Q4 | `~/.cache/huggingface/hub/models--dgrauet--ltx-2.3-mlx-q4` (+ общие blobs) | каталог 112 KB, веса в 63 GB blobs | MLX, Q4 | по репозиторию HF — **NOT VERIFIED** | `LTX2MLXModelLoader` в workflow | скачать повторно |
| Whisper large-v3-turbo | HF hub | 1.5 GB | — | — | не используется в Mary Studio (**INVESTIGATE**) | скачать |
| Ollama `gemma3:4b` | `~/.ollama` | 3.3 GB | 4B | — | planner, production plan | `ollama pull` |
| Ollama прочие (qwen3, deepseek, и т.д.) | `~/.ollama` | 85 GB всего | — | — | не Mary Studio | — |
| Rhubarb Lip Sync 1.14.0 | `~/.mary-studio/tools/rhubarb-1.14.0/` | 8.4 MB bin + `res/` | x86_64 + Rosetta 2 | MIT | `rhubarb.py` | переустановка, SHA-256 `93fa4a16…` |
| ComfyUI | `runtime/ComfyUI` | 2.5 GB | версия **NOT VERIFIED** | GPL-3.0 (ComfyUI) | воркер | git clone |
| custom node `comfyui-ltx2-mlx` | `runtime/ComfyUI/custom_nodes` | 732 KB | commit **NOT VERIFIED** | — | LTX-рендер | git clone по commit (требование AGENTS) |
| FFmpeg | система | — | версия **NOT VERIFIED** | LGPL/GPL | сборка, probe, огибающая | brew |
| Python | `backend/.venv` | 89 MB | 3.13 | — | backend/worker | `uv sync` |
| Node | `ui/node_modules` | 71 MB | — | — | UI | `npm ci` |

Модели **не удалялись и не скачивались**. Ни одна модель не является «мёртвой» в смысле
«можно удалить»: LTX и `gemma3:4b` — production-зависимости. Лишние Ollama-модели
(deepseek, qwen2.5-coder и др.) к Mary Studio отношения не имеют, но это личные
установки — вне периметра очистки.

---

## 10. Runtime & Thermal Audit (§10)

| Процесс | Порт | PID | Состояние |
|---------|------|-----|-----------|
| Ollama | 127.0.0.1:11434 | 868 | слушает |
| Vite | 127.0.0.1:5173 | 13707 | слушает |
| uvicorn (backend) | 127.0.0.1:8000 | 15027/15028 | слушает |
| ComfyUI | — | — | **не запущен** |
| ltx_worker | — | — | **не запущен** |
| caffeinate / thermal helper | — | — | не запущены |
| launchd | — | — | **NOT VERIFIED** (`launchctl` permission denied) |

Механизмы:

| Механизм | Реализация | Чем проверен |
|----------|-----------|--------------|
| single-heavy-job guard | `pg_advisory_xact_lock` + `NOT EXISTS` в `claim` (`api/worker.py`) | mock-тесты |
| thermal pause | `worker/thermal.py` → существующие `pause`/`resume` | **живой тест** (WP-THERMAL-03: `thermal_serious` → paused → resume → completed) |
| memory admission | доступная память = free + inactive + speculative; Eco ≥4 GiB | mock-тесты; живой Eco-рендер NLB-25 прошёл |
| power gate | `pmset -g ps`, `--allow-battery`, Low Power Mode (чтение) | mock-тесты |
| cooldown | 480/1200 с, гистерезис после serious/critical | mock-тесты |
| Eco/Balanced/Off | профили `thermal.py` | mock-тесты + 1 Eco-рендер |
| worker lifecycle | state-файл, `caffeinate -i -w`, `finally` | живой тест recovery WP-M4 |

Текущая память: 18.0 GiB, доступно ≈3.9 GiB (`vm_stat` на момент аудита) — **ниже
порога Eco 4 GiB**, то есть следующий Eco-рендер может быть отложен.

---

## 11. UI & API Audit (§11)

- **100 маршрутов** в 23 модулях (98 + `/health`, `/api/health`).
- **75** вызываются из UI, **15** — частично/только worker/CLI/мониторинг,
  **10** не используются UI:

| Маршрут | Почему не используется | Решение |
|---------|------------------------|---------|
| `GET /api/artifacts/{id}` | UI берёт `/content` | KEEP |
| `GET /api/shots/{id}/compositions` | UI берёт ревизию напрямую | KEEP |
| `GET /api/scene-plans/{revision}` | редактор использует другой путь | KEEP |
| `GET /api/shots/{id}/references` | данные приходят в детали шота | KEEP |
| `GET /api/shots/{id}/attempts` | заменён `GET /api/projects/{id}/attempts` | **DELETE_CANDIDATE** (метод клиента уже мёртв) |
| `GET /api/scenes/{scene_id}` | не вызывается | KEEP (нужен worker/CLI) |
| `GET /api/production-plans/{id}` | UI берёт список | KEEP |
| `GET /api/reference-assets/{id}` | не вызывается | KEEP |
| `POST /api/shots/{id}/lipsync` | всегда 409 | DISABLE |
| `GET /api/rhubarb/status` | только диагностика | KEEP |

- **Мёртвые методы клиента (5):** `client.ts:451, 502, 515, 607, 648`.
- **Feature flags:** 1 — `VITE_FEATURE_LIPSYNC` (`ShotDetailPage.tsx:24`), включает
  нерабочую панель.
- **Orphan-компонентов/страниц нет.**
- **Расхождения frontend/backend:** статус `workers` stale; `prompt_ready` у GNS-01…04
  без keyframe; панель lip sync создаёт впечатление функции.

Экраны: `#/characters`, `#/characters/{id}`, `#/locations`, `#/props`, `#/shots`,
`#/shot/{id}`, `#/attempts`, `#/exports`, `#/plan`, `#/series/{id}`.

---

## 12. Tests & Quality (§12)

| Набор | Собрано | Запущено в аудите | Комментарий |
|-------|---------|-------------------|-------------|
| `backend` | **298** | **нет** | `pytest --collect-only`; тесты не запускались, чтобы не создавать job/данные |
| корневой `tests` | **104** | **нет** | включает `test_ltx_worker` 39, `test_thermal_gate` 38, `test_ltx_adapter` 12, `test_mouth_animation` 15 |
| legacy 15 | — | нет | заявлено в `AGENTS.md`, в сбор 104 не входят — **NOT VERIFIED** |
| UI | `npm run build` | нет | в `AGENTS.md` зафиксировано 367.03 kB |
| миграции | `alembic check` | нет | в `AGENTS.md` — no new operations |

Чего нет: E2E, тестов визуального качества видео, тестов на 198 «битых» artifacts,
тестов на stale `workers`, frontend unit-тестов (только сборка).

**Вывод:** «зелёные unit-тесты» не являются доказательством качества видео — это
отдельно оговорено в задании и подтверждается историей (дефект шва B тестами не ловится).

---

## 13. Documentation Audit (§13)

| Документ | Состояние |
|----------|-----------|
| `README.md` | актуален, краткий |
| `AGENTS.md` | актуален, но §8 — длинный журнал; счётчики тестов не перепроверены |
| `docs/ARCHITECTURE.md` | baseline v1.3, не менялся |
| `docs/DECISIONS.md` | §4.1…§4.21, актуален |
| `docs/ROADMAP_MARY_STUDIO.md` | актуален; WP-05B не начат |
| `docs/OPEN_QUESTIONS.md` | часть вопросов закрыта отчётами WP-VOICE-02…06 (**NOT VERIFIED** построчно) |
| `docs/VIDEO-ORCHESTRATOR.md` | **отсутствует** |
| `docs/PROPOSALS/*` (21) | смесь живых планов и исторических аудитов, нет индекса |
| `docs/REPORTS/*` (7) | история приёмок, актуальна |
| `CLAUDE.md` | **чужой проект** (`github-crawler`) |
| `AI_Tools_Analysis.md`, `scenario.md`, `docs/new_updates.md` | черновики вне контракта |
| `i_will_do_it_later.md` | личный бэклог, оставить |

**Предлагаемая компактная структура (не создавалась):**

```
docs/
  ARCHITECTURE.md        # baseline (не менять)
  DECISIONS.md           # журнал решений
  ROADMAP.md             # текущий роадмап
  OPEN_QUESTIONS.md
  REPORTS/               # отчёты WP (история)
  PROPOSALS/             # только актуальные предложения
  ARCHIVE/               # AI_Tools_Analysis.md, scenario.md, new_updates.md
  AUDITS/                # эти 7 документов
```

Историю решений (`DECISIONS.md`, `REPORTS/`) не удалять.

---

## 14. Classification (§14)

| Статус | Компоненты |
|--------|------------|
| **KEEP** | API/ядро backend, миграции, blob storage, импорт legacy/series, композиции, scene plans, очередь job, LTX-воркер, thermal, presets, series, экспорт/assembly, production plan, shot audio, `mary.sh`, UI, базовые документы, отчёты WP |
| **KEEP_EXPERIMENTAL** | mouth animation (`pillow_mouth_v2`/`mvp`), viseme frame blend, Rhubarb adapter |
| **DISABLE** | lip sync (adapter + UI + 4 теста) |
| **ARCHIVE** | legacy `pipeline/stages/*`, `main.py`, `pipeline/comfyui/{generator,scene_draft,workflows}.py`, `export/LLM-gen`, `export/wp_voice_06_ab` (после A/B), `AI_Tools_Analysis.md`, `scenario.md`, `docs/new_updates.md`, `requirements.txt` |
| **DELETE_CANDIDATE** | `storage/blobs/.DS_Store`, orphan WAV, `comfyui-input/`, `exports/`, `CLAUDE.md`, `worker_lease_seconds`, 5 мёртвых методов клиента, `ui/dist` + кэши |
| **INVESTIGATE** | 198 artifacts без файлов, `pipeline/comfyui/generator.py:121` (чужой путь), `MARY_DISABLE_NOTIFY` вне `Settings`, stale `workers.status`, Whisper в HF-кэше |

Полные карточки — `COMPONENT_INVENTORY.md` и `CLEANUP_CANDIDATES.md`.

---

## 15. Cleanup Plan (§15) — только план

| Этап | Что | Экономия | Риск | Трудоёмкость |
|------|-----|----------|------|--------------|
| **1. Safe** | 2 orphan-файла, `ui/dist`, pytest/`__pycache__` | ≈4.8 MB | очень низкий | 10 мин |
| **2. Consolidation** | `.gitignore`, пустые каталоги, `CLAUDE.md`, 5 методов клиента, `worker_lease_seconds`, lip sync (DI/delete), архив черновиков, актуализация AGENTS/ROADMAP | ≈0.05 MB + сложность | низкий | 2–4 ч, по одному WP |
| **3. Deep** | `export/LLM-gen` 241 MB, `ComfyUI/output` 149 MB, `ComfyUI/input` 57 MB, `wp_voice_06_ab` 10 MB; опционально `node_modules`+`.venv` 160 MB | до ≈457 MB (или 617 MB) | средний/высокий, необратимо | 1–2 ч + `pg_dump` |

Подробно, с командами и критериями проверки — `CLEANUP_EXECUTION_PLAN.md`.
**Ни один этап не выполнялся.**

---

## 16. Ограничения аудита (NOT VERIFIED)

- Тесты не запускались (только `--collect-only`) — «298 passed» взято из `AGENTS.md`.
- `launchctl`/автозапуск — permission denied.
- Версия ComfyUI и commit custom node `comfyui-ltx2-mlx` не зафиксированы.
- Лицензия LTX-весов на HF не проверялась.
- Разбивка 63 GB `huggingface/hub/blobs` по моделям невозможна (общий пул).
- 9 464 события `events` не анализировались построчно.
- Все 49 видео-артефактов визуально не пересматривались.
- Состав approved-референсов NLB по ролям детально не перечислялся.

---

## 17. Следующий шаг

Аудит завершён. **Остановка и ожидание решения человека** по пунктам:

1. Подтвердить этап очистки (Stage 1 / 2 / 3) или отложить.
2. Решить судьбу pending job `852adc5d…` (оставить / отменить / запустить осознанно).
3. Разрешить коммит и пуш 69 изменений (вне рамок этого аудита).
4. Утвердить/отклонить сборку B (`attempt 3eb3ca9f…`) либо переснять viseme-кадры.
5. Утвердить эталонные дубли (сейчас 0 approved attempts).

Никаких изменений кода, БД, ассетов и файлов не произведено.
