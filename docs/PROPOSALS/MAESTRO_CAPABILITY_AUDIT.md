# Mary Studio × Maestro — аудит возможностей (WP-M0)

> **Статус:** предложение; код не менялся. Требуется решение человека.
> **Дата аудита:** 2026-11-04.
> **Mary Studio:** `/Users/vladislavkovalenko/Projects/Mary_Guiness`, ветка `main`,
> коммит `2d3fc72`.
> **Maestro:** `https://github.com/Blizaine/Maestro`, commit
> `05f5677ff30e8fd4d1ad890be8752ee9ef4f6583` (2026-10-31), `VERSION` = `3.2.5`.
> Клон для чтения: `/tmp/maestro-audit` (вне рабочего дерева Mary Studio).
> **Связанные документы:** `MAESTRO_LICENSE_REVIEW.md`, `MAESTRO_INTEGRATION_ROADMAP.md`,
> `docs/ARCHITECTURE.md` (baseline v1.3), `docs/DECISIONS.md`, `docs/ROADMAP_MARY_STUDIO.md`.
> **Границы:** документ не является разрешением на миграции, изменение API, добавление
> зависимостей или установку моделей. Разрешение выдаётся отдельно на каждый WP-M*.

---

## 1. Метод и границы аудита

**Что сделано:**

1. Прочитаны документы Mary Studio: `AGENTS.md`, `docs/ARCHITECTURE.md` (§4–§6, §14),
   `docs/DECISIONS.md`, `docs/ROADMAP_MARY_STUDIO.md`, `docs/ENV-AUDIT.md`,
   `docs/PROPOSALS/MARY_STUDIO_INTEGRATION.md`.
2. Прочитан фактический код Mary Studio: `backend/app/models.py`, все миграции
   `backend/alembic/versions/0001…0008`, все роутеры `backend/app/api/*.py`, сервисные
   модули `backend/app/*.py`, `worker/*.py`, `pipeline/comfyui/*.py`,
   `pipeline/stages/*.py`, `ui/src/**`, тесты `backend/tests/` и `tests/`.
3. Изучены исходники Maestro: `LICENSE`, `app/LICENSE.txt`, `app/mmgp/LICENSE.txt`,
   `THIRD_PARTY_NOTICES.md`, `README.md`, `CHANGELOG.md`, `docs/**` (Director, Studio,
   Editor, Auto-Tune, Generation preview, TTS, Characters, Performance),
   `app/services/**`, `app/services/director/**`, `app/models/**`, `ui/src/**`, `tests/**`.
4. Зафиксирован commit SHA Maestro и дата анализа.

**Чего НЕ делалось (и не могло быть сделано в WP-M0):**

- Maestro не устанавливался, зависимости не ставились, модели не скачивались.
- Ни один сценарий Maestro не запускался: все утверждения о его runtime-поведении —
  вывод из чтения исходников. Такие пункты помечены **[ПРОВЕРИТЬ запуском]**.
- Реальный рендер Mary Studio не запускался, production-БД не изменялась.
- Тесты Mary Studio в WP-M0 не перезапускались (код не менялся). Последний
  зафиксированный результат: `backend` — 182 passed, корневой `tests/` — 43 passed,
  `alembic check` — no new operations (`AGENTS.md`, §8).

---

## 2. Фактическое наличие документов Mary Studio

| Документ | Наличие | Актуальность |
|---|---|---|
| `AGENTS.md` | есть | актуален на 2026-10-29 (раздел §8 «Текущее состояние») |
| `docs/ARCHITECTURE.md` | есть, 844 строки | baseline v1.3, не редактируется (sha256 в шапке `docs/DECISIONS.md`) |
| `docs/ROADMAP_MARY_STUDIO.md` | есть | актуален: WP-00…WP-08, WP-N1…N4 отмечены выполненными |
| `docs/DECISIONS.md` | есть | актуален: S1–S19, A1–A6, D1–D8, §4.1–§4.7 |
| `docs/ENV-AUDIT.md` | есть | окружение на 2026-10-26; фактические версии ComfyUI/MLX указаны |
| `docs/PROPOSALS/MARY_STUDIO_INTEGRATION.md` | есть | историческое предложение, не переписывается |
| `VIDEO-ORCHESTRATOR.md` (в корне) | **отсутствует** | содержимое v1.3 перенесено в `docs/ARCHITECTURE.md` (см. шапку `docs/DECISIONS.md`) |

Вывод: документ-источник из задания `VIDEO-ORCHESTRATOR.md` в репозитории отсутствует;
его роль выполняет `docs/ARCHITECTURE.md`. Это расхождение с текстом задания, а не с
архитектурой: baseline сохранён дословно.

---

## 3. Mary Studio: фактическое состояние (as-is)

### 3.1. Backend и данные

| Слой | Факт | Файлы |
|---|---|---|
| Каркас | FastAPI, `create_app()`, `/health`, `/api/health` | `backend/app/main.py` |
| ORM | SQLAlchemy 2, 22 таблицы | `backend/app/models.py` |
| Миграции | `0001_initial_core` … `0008_series_run_title` | `backend/alembic/versions/` |
| Storage | content-addressed `blobs/<aa>/<sha256><ext>`, atomic publish через `os.replace` | `backend/app/storage.py` |
| Импорт | legacy `characters/`/`episodes/`, серия NLB | `backend/app/legacy_import.py`, `app/series_import.py`, `app/import_series.py` |
| Композитор | Pillow, RGBA-слои, `layout mockup`, экспорт 512×512 `crop`/`pad` | `backend/app/composer.py` |
| Планировщик | per-shot план, vision `gemma3:4b` как советующий источник, fallback | `backend/app/planner.py` |
| Preflight | 11 проверок готовности серии, только чтение | `backend/app/preflight.py` |
| Уведомления | баннер macOS через `osascript`, best-effort | `backend/app/notify.py` |

### 3.2. Очередь, воркер, рендер

| Возможность | Факт | Файлы |
|---|---|---|
| Очередь | `jobs` + `workers`, lease, heartbeat, `FOR UPDATE SKIP LOCKED` | `backend/app/api/worker.py:304` |
| Идемпотентность | `jobs.idempotency_key` + частичный уникальный индекс; `Idempotency-Key` в `render` | `backend/app/models.py`, `api/shots.py:634` |
| Активная job на шот | частичный уникальный индекс `one_active_render_per_shot` | `alembic/versions/0001_initial_core.py` |
| События | `events` с `sequence`, `stage`, `progress`, CHECK 0..1 | `models.py`, `alembic/versions/0006_events.py` |
| Публичное чтение job | `GET /api/jobs`, `GET /api/jobs/{id}` (без списка событий) | `api/jobs.py` |
| Воркер LTX | кадр → `/prompt` → `/history` (heartbeat на каждом опросе) → `/view` → ffprobe → artifact → complete | `worker/ltx_worker.py` |
| Проверка MP4 | структурный разбор ISO BMFF (`ftyp`/`moov`/`mvhd`/`hdlr`) | `backend/app/video_probe.py` |
| Провенанс | `render_attempts.parameters` + `workflow_snapshot`, `seed`, `model_hash`, `workflow_version` | `worker/ltx_worker.py:199`, `api/worker.py:528` |
| Серийный прогон | `series_runs`/`series_items`, concurrency = 1 через `series/next` | `api/series_runs.py`, `alembic/versions/0007_render_series.py` |
| Восстановление по `prompt_id` | **не реализовано**: колонка `jobs.external_id` есть, но ни один endpoint её не пишет; воркер держит `prompt_id` только в памяти | `models.py:288`, `api/worker.py:672`, `worker/ltx_worker.py:236` |

### 3.3. UI

Маршруты (`ui/src/hooks/useHashRoute.ts`): `#/characters`, `#/character/{id}`,
`#/locations`, `#/location/{id}`, `#/props`, `#/prop/{id}`, `#/shots`, `#/shot/{id}`,
`#/series/{id}`.

Есть: библиотека персонажей и bible, сетка референсов с approve/reject, лайтбокс, шоты,
редактор композиции, панель сцен-плана, список попыток шота, панель прогона серии с
поллингом и процентом по завершённым item'ам (`SeriesRunPage.tsx`).

Нет: плеера и сравнения видео-попыток, избранного, медиатеки проекта, монтажа/экспорта,
прогресса одиночной job, отдельного экрана списка прогонов.

### 3.4. Что уже покрыто тестами

158 тестовых функций в `backend/tests/` (24 файла) и 43 в корневом `tests/` (4 файла).
Покрыты: очередь и lease, идемпотентность render и `series/next`, иммутабельность
approved-записей, ограничения схемы, композитор, planner, серийные прогоны,
storage/artifacts, preflight, fake worker, LTX adapter/worker.
Не покрыто: восстановление по `prompt_id`, сравнение попыток, монтаж, аудио-анализ
(этих возможностей нет и в коде).

---

## 4. Maestro: фактическое состояние (as-is)

### 4.1. Продукт и стек

- **Director** — планирование клипа (music video / short film / podcast / viral),
  подготовка референсов и ключевых кадров, генерация клипов, сборка.
- **Studio** — генерация видео/изображений/аудио, очередь, prompt enhance, Auto-Tune.
- **Editor** — неразрушающий многодорожечный таймлайн, экспорт.

| Компонент | Факт |
|---|---|
| Backend | монолит FastAPI, `app/launch.py` (~31 400 строк, ~180 эндпоинтов `/api/v1/*`) |
| Движок | вендоренный WanGP (`app/wgp.py`, ~16 000 строк) + MMGP 4 |
| UI | React 19 + TypeScript + Vite 7 + Zustand + Tailwind 4; `ui/src/editor/*` |
| Домен | **не БД**: JSON-файлы в `uploads/` и рабочих каталогах; SQLite только для метрик |
| Очередь | in-process dict `_jobs` под `threading.RLock`; `app/services/job_lifecycle.py` |
| Восстановление | JSON-чекпойнты только для `enhancement` задач (`StudioJobArchive`) |
| Платформа | **только NVIDIA/CUDA**; README: «AMD GPUs and macOS are not currently supported» |

### 4.2. Ключевые модули, изученные для аудита

| Тема | Файлы Maestro |
|---|---|
| Director-схемы | `app/services/director/schema.py` (`ShotPlan`, `ProductionPlan`, `AudioPlan`) |
| Оркестратор | `app/services/director/orchestrator.py` (`_PLANNER_MAP`, `_RENDERER_MAP`) |
| Music-to-shot | `app/services/director/planners/music_video.py` (~4 571 строка) |
| Пайплайн | `app/services/director_pipeline.py` (8 332 строки, фазы + паузы на ревью) |
| Аудио-анализ | `app/services/audio_analysis.py` (1 437 строк: beat/downbeat, секции, onset, Whisper) |
| Тайминг клипов | `app/services/audio_analysis.py:813` `suggest_clip_boundaries`, `:928` `plan_clip_structure`, `:864` `_snap_to_valid_frames` |
| LLM | `app/services/llm_service.py` (llama-server, grammar-constrained JSON) |
| Валидация | `app/services/director/validators/*`, `contract_repair.py`, `physical_continuity.py`, `policies.py` |
| Очередь | `app/services/job_lifecycle.py` (519 строк) |
| Прогресс | `/api/v1/status/{job_id}`, `app/services/generation_preview.py`, `generation_eta.py` |
| Персонажи | `app/services/character_library.py` (634 строки, JSON-индекс + медиа) |
| Голоса/TTS | `app/models/TTS/*`, `docs/TTS-Characters.md`, `app/services/dialogue_timing.py` |
| Lip sync | отдельных postprocess-моделей нет; audio-driven video: `app/models/minimax_h3`, `app/models/longcat`, `app/services/director/renderers/ltx_a2v.py` |
| Монтаж | `app/services/editor_projects.py` (1 635 строк, `compile_editor_render` :1209 — один FFmpeg filter graph) |
| Auto-Tune | `hardware_detect.py` (320), `perf_recommend.py` (1 115), `performance_tuning.py` |
| Тесты | 415 файлов `tests/test_*.py`, CI в `.github/workflows/ci.yml` |

---

## 5. Сравнительная таблица возможностей

Статусы: **AI** — Already implemented, **PI** — Partially implemented, **M** — Missing,
**NA** — Not applicable, **BH** — Blocked by hardware, **BL** — Blocked by license.

| Capability | Maestro implementation | Mary Studio current state | Gap | Recommendation | Priority | Risk |
|---|---|---|---|---|---|---|
| Иерархия Project → Episode → Scene → Shot | нет доменной БД; проекты/папки в `uploads/` и JSON (`editor_projects.py`, `gallery_library.py`) | `Project/Episode/Scene/Shot`, FK, `UNIQUE(scene_id, sequence_no)` — `backend/app/models.py:133–215` — **AI** | нет | не переносить | — | — |
| Библиотека персонажей | `character_library.py`: `visual.<ext>`, `voice.<ext>`, `reference.safetensors`, JSON-индекс, **без версий** | `characters`, `character_bible_versions`, `reference_assets`, approve/reject, триггеры иммутабельности — **AI** | нет | не переносить | — | — |
| Локации и предметы | отдельных сущностей нет (галерея + reference-файлы) | `locations`, `props`, `library.py` — **AI** | нет | — | — | — |
| Reference Assets с provenance | файлы в `uploads/`, без sha256-индекса и без статусов | `reference_assets` + sha256 + `status` + `approved_at`, `artifacts` с S12 — **AI** | нет | — | — | — |
| Разделение identity / start frame / voice / motion / prop reference | частично: `visual`, `voice`, `image_views`; типы не формализованы | разделение задаётся `kind`/`role`, но **voice reference отсутствует**; motion reference отсутствует — **PI** | нет голосового и motion-референса | ввести `role`-набор и хранение голоса в `reference_assets`/`artifacts` без копирования кода | Средний | низкий |
| Per-shot visual scene plan | `ShotPlan` (~40 полей) в `director/schema.py` | `visual_scene_plans` (S19), `planner.py` (vision советник), API `scene_plans.py` — **PI** | план есть только per-shot, нет плана всей песни | расширить планировщик, а не создавать Director | Высокий | средний |
| Music-to-shot planning | `director/planners/music_video.py`, `_plan_music_arc`, narrative contract, review-раунд | **M** (нет анализа аудио и плана клипа; промпты вводятся вручную/импортом) | целиком отсутствует | независимая реализация: `audio timeline → scene plan → shots` | Высокий | средний |
| Music timeline / beat detection | `audio_analysis.py`: `librosa.beat_track`, downbeats, onset envelope, секции; Whisper/pyannote | **M** (только `Mp4Info.has_audio`) | отсутствует | лёгкий анализ через FFmpeg + librosa (Apple Silicon, CPU) | Высокий | низкий |
| Snap клипов к beat/downbeat и к 8k+1 кадрам | `suggest_clip_boundaries`, `_snap_to_valid_frames` | `snap8k1` есть только в импорте/адаптере (`series_manifest.py`, `ltx_adapter.py`) — **PI** | нет привязки к музыкальной сетке | использовать существующий `snap8k1` + добавить beat-snap | Средний | низкий |
| LLM-планирование со структурированным выводом | `llm_service.py`: grammar-constrained JSON, батчи, repair | `planner.py`: Ollama `/api/generate`, vision, `validate_plan`, fallback — **PI** | нет JSON-schema контракта, нет bounded repair | Ollama structured outputs + Pydantic-схема + ограниченный repair | Высокий | средний |
| Production continuity (инструменты, костюмы, реквизит, лишние персонажи) | `physical_continuity.py`, `music_narrative.py`, `policies.py` | **M** (есть только `shot_references` и предупреждения композитора) | отсутствует | чек-лист непрерывности на данных + опциональная LLM-проверка | Средний | средний |
| Композиция кадра из нескольких референсов | нет (референсы передаются в модель) | `shot_compositions` + `shot_composition_layers` + Pillow, `layout mockup` — **AI** | нет matting (осознанно отложено) | не переносить | — | — |
| Генерация keyframe изображения | `image_gen` renderer, H3/Flux/Qwen image | **M** для генерации; есть `keyframe` из approved-референса и из approved-композиции (`api/shots.py:502`) — **PI** | нет txt2img-генерации кадра в системе | не добавлять без модели, совместимой с Apple Silicon | Низкий | высокий |
| `promote-keyframe` как единственный писатель стартового кадра | нет аналога (нет такой модели данных) | `POST /api/shots/{id}/attempts/{id}/promote-keyframe` — **AI** | нет | сохранить инвариант при любых новых WP | — | — |
| Очередь с lease/heartbeat/claim | in-process `_jobs`, без lease/heartbeat, без идемпотентности | PostgreSQL `jobs` + `FOR UPDATE SKIP LOCKED`, `lease_expired`, `retry_wait` — **AI (сильнее Maestro)** | нет | не переносить Maestro-очередь | — | — |
| Идемпотентность постановки | отсутствует | `Idempotency-Key`, частичный уникальный индекс — **AI** | нет | — | — | — |
| Восстановление после рестарта | JSON-чекпойнты для `enhancement`, `queued/running → held` | частично: `resume` + lease; **потеря связи с ComfyUI не восстанавливается** — **PI** | `jobs.external_id` не заполняется, `prompt_id` не сохраняется | WP-M4: записывать `prompt_id`, `resume` сверяет `/history` перед retry | Высокий | средний |
| Pause / Resume / Stop after current / Cancel pending / Retry failed | `job_lifecycle.request_cancel`, `try_requeue`; паузы Director | pause/resume/stop-after-current/cancel — только для **прогона серии** (`api/series_runs.py`); retry job — нет; cancel отдельной job — нет — **PI** | нет управления отдельной job | добавить cancel/retry на уровне существующих статусов, без новой таблицы | Средний | средний |
| Последовательность тяжёлых задач (concurrency = 1) | GPU-lock `acquire_generation_slot` | `series/next` выдаёт одну тяжёлую job; одиночные job могут конкурировать — **PI** | нет глобального лимита для одиночных рендеров | опциональный глобальный слот через существующие статусы | Средний | средний |
| Проверка MP4 через ffprobe | `probe_media` (`editor_projects.py:731`) | `probe_mp4` структурно, плюс ffprobe в воркере — **AI** | нет | — | — | — |
| Провенанс seed / workflow snapshot | модель-центричный, без workflow snapshot | `render_attempts.parameters` + `workflow_snapshot` — **AI** | нет | — | — | — |
| История попыток, иммутабельность | нет (файлы перезаписываются) | `render_attempts`, `artifacts` immutable, триггеры — **AI** | нет | — | — | — |
| Approve/reject результата шота | «accepted/rejected» в ревью Director | модели есть (`shots.approved_attempt_id`, `Shot.status='approved'`), **эндпоинта и UI нет** — **PI** | нет писателя `approved_attempt_id` | WP-M1: approve/reject попытки (без миграции) | Высокий | низкий |
| Прогресс рендера (реальный) | `/api/v1/status` из движка, polling, Tiny VAE preview | `events.progress` пишется heartbeat'ом и показывается только в `SeriesRunPage`; для одиночной job — нет — **PI** | нет UI и нет событий в `GET /api/jobs/{id}` | WP-M1: `GET /api/jobs/{id}` + events, polling в UI | Высокий | низкий |
| ETA по истории | `generation_eta.py`, SQLite-история | **M** | отсутствует | опционально после накопления замеров | Низкий | низкий |
| Live preview (кадры/Tiny VAE) | `generation_preview.py` (LRU, 2 ревизии, JPEG/MP4) | **M**, и в MLX-workflow preview-узлов нет | недоступно на текущем стеке | fallback: этапы + прогресс; preview не обещать | Низкий | средний |
| Аудио как артефакт | `uploads/` + `probe_media` | `POST /api/artifacts` принимает `audio/mpeg`, `audio/wav`; `scenes.audio_artifact_id` — **PI** | нет API-сценария «аудио песни → проект» | WP-M2: загрузка аудио и привязка к сцене/проекту | Высокий | низкий |
| TTS / синтез речи | Fish Audio, IndexTTS2, Chatterbox, Qwen3, KugelAudio (CUDA) | `pipeline/stages/voices.py` — заглушка (проверяет наличие mp3) — **M** | отсутствует | **BL/BH**: локальный TTS на MLX не выбран; только интерфейс адаптера | Средний | высокий |
| Voice reference персонажа | `voice.<ext>` в каталоге персонажа | **M** | отсутствует | WP-M3: хранить voice reference как `reference_assets(role='voice')` после выбора движка | Средний | высокий |
| Voice cloning | SeedVC (GPL, вне дерева) + модели TTS | **M** | отсутствует | не переносить; только при наличии прав и совместимого движка | Низкий | высокий |
| Lip sync (человек) | нет postprocess-моделей; audio-driven video (H3/LongCat/LTX a2v) — CUDA | `pipeline/stages/lipsync.py` — заглушка (Hedra) — **M** | отсутствует | изучить MLX-совместимые audio-driven модели; иначе — только адаптер | Средний | высокий |
| Lip sync (животные, кошачья морда) | отдельных animal-моделей нет; заявленной поддержки кошачьих морд нет | **M** | отсутствует | **BH**: считать неподтверждённым; тест только после выбора движка | Низкий | очень высокий |
| Сборка/экспорт финального видео | `compile_editor_render` — один FFmpeg filter graph, `editor_export` job | **M**: `pipeline/stages/assembly.py` не склеивает, предлагает DaVinci; экспорт есть только PNG-layout — **M** | отсутствует | WP-M2: FFmpeg concat + музыка + триммы, без редактора | Высокий | средний |
| Медиатека / сравнение попыток / favorites | галерея, поиск, избранное, «send back to Studio» | **M** (есть список попыток на шоте без плеера и сравнения) | отсутствует | WP-M5: сравнение попыток и метаданные поверх existing API | Средний | низкий |
| Auto-Tune / hardware presets | `detect_hardware` + `perf_recommend` + локальная история | **M** (только CLI-флаги и `TARGET_RESOLUTIONS` в preflight) | отсутствует | WP-M6: preset Safe/Balanced/Quality на измеренных данных | Средний | низкий |
| Hardware detection | NVML/CUDA-тиры | **M** | отсутствует | `sysctl`/`system_profiler` + `psutil` (лёгкая зависимость) | Средний | низкий |
| Персонаж как портативный контейнер | `.maestro.safetensors` (RefMod + медиа) | **NA/BL** (RefMod — технология H3, safetensors-веса модели) | нет смысла | не переносить | — | — |
| Тесты / CI | 415 файлов, CI с lint + build | 158 backend + 43 корневых; UI `npm run build` — **AI** | нет | сохранять, добавлять тесты на новые WP | — | — |
| Локальные уведомления | Web Push (VAPID) | баннер macOS `notify.py` — **AI** | нет | — | — | — |

---

## 6. Разбор ключевых пробелов

### 6.1. Планирование клипа (Phase B)

Mary Studio планирует **один шот**: `visual_scene_plans` описывает canvas, camera,
references, action beats и motion prompt (`backend/app/planner.py`,
`api/scene_plans.py`). Плана всей песни нет: нет длительности аудио, нет временной сетки,
нет распределения действий между шотами, нет монтажного плана.

Maestro решает это тремя независимыми блоками, каждый из которых воспроизводим без
копирования кода:

1. **Audio timeline** — BPM, beat/downbeat, энергетические секции, onset envelope
   (`audio_analysis.py:110`, `:129`, `:140`, `:148`). Требуемые зависимости на Apple
   Silicon: `librosa` (CPU) или чистый FFmpeg + numpy.
2. **Clip planning** — границы клипов с snap к downbeat и ограничениями
   `MIN_CLIP_SECONDS = 8.0`, `MAX_CLIP_SECONDS = 26.0` (`audio_analysis.py:813`, `:928`).
3. **LLM-план** — структурированный JSON через схему, батчи, repair-раунд
   (`director/planners/music_video.py`, `llm_service.py`).

Для Mary Studio это означает новый слой над существующими `scenes/shots/prompt_revisions`:
план создаёт **черновики** шотов и ревизии промптов, а утверждение остаётся ручным
(S15/S19-логика уже есть).

### 6.2. Надёжность рендера (Phase E)

Mary Studio по большинству пунктов **сильнее** Maestro: durable-очередь в PostgreSQL,
lease/heartbeat, `lease_expired`, idempotency key, частичный уникальный индекс активного
рендера, провенанс и история попыток. Из требований Phase E реально отсутствуют три
вещи:

1. **Связь с внешним job id.** Колонка `jobs.external_id` создана в `0001_initial_core`,
   отдаётся в `POST /api/worker/resume`, но никем не заполняется.
   `worker/ltx_worker.py:236` получает `prompt_id` и не публикует его.
2. **Resume по `prompt_id`.** При падении воркера рендер остаётся в очереди ComfyUI,
   job истекает в `lease_expired` и не перезапускается автоматически (это инвариант
   baseline, но сверка `/history` перед retry не реализована).
3. **Управление отдельной job** (cancel/retry) — сейчас есть только управление прогоном
   серии.

Всё остальное из Phase E либо уже есть, либо является политикой, а не кодом.

### 6.3. Наблюдаемость (Phase F)

`events` — реальный журнал с `stage` и `progress` (`models.py`, `0006_events.py`),
запись идёт из heartbeat (`api/worker.py:392`). Не хватает:

- `GET /api/jobs/{id}` не возвращает события и прогресс;
- UI не показывает прогресс одиночной job (только `SeriesRunPage` по item'ам);
- SSE/WebSocket отсутствуют (WP-07 в старом roadmap не начат).

Tiny VAE preview из Maestro **неприменим**: текущий LTX-2.3 MLX workflow
(`comfyui-workflows/ltx23_mlx_q4_i2v.api.json`) не отдаёт промежуточные кадры.
Корректное решение — этапы и прогресс, без искусственного процента.

### 6.4. Аудио, голос, lip sync (Phase C/D)

Mary Studio уже принимает `audio/mpeg` и `audio/wav` как артефакты
(`backend/app/api/artifacts.py:19–27`) и имеет `scenes.audio_artifact_id`, но нет
сценария «аудио песни → проект → таймлайн». Голосовых референсов персонажа нет.

Maestro подтверждает: **отдельных lip-sync postprocess-моделей у него нет**. Там
используются audio-driven video модели (MiniMax H3, LongCat Avatar, LTX a2v, Wan
InfiniteTalk/MultiTalk), все — CUDA-ориентированные. Животные отдельно не поддержаны.

Следствие: Phase D для Mary Studio делится на «сделать сейчас» (хранение аудио, voice
reference, интерфейс адаптера) и «не обещать» (реальный animal lip sync на M3 Pro 18 GB).

### 6.5. Монтаж (Phase I)

`pipeline/stages/assembly.py` — проверка наличия клипов и предложение собрать в DaVinci.
Экспорт есть только для layout-PNG (`POST /api/shots/{id}/compositions/{revision}/export`).

Maestro собирает одним FFmpeg filter graph (`compile_editor_render`), но его модель —
свободный таймлайн с оверлеями, текстом и переходами. Для Mary Studio MVP достаточно
последовательной склейки утверждённых попыток с музыкальной дорожкой и триммами; это
не требует ни новой таблицы, ни редактора.

---

## 7. Совместимость с оборудованием (M3 Pro, 18 GB unified memory)

| Функция | Вывод | Обоснование |
|---|---|---|
| Перенос inference-стека Maestro | **Невозможно** | PyTorch+CUDA 13, NVIDIA-only кернелы (Sage/Flash/Sol), MMGP C++-аллокатор только Linux x86_64/Windows amd64, `pynvml` |
| Director-планирование (LLM) | Возможно | Ollama `gemma3:4b` уже используется; JSON-schema поддержка Ollama **[ПРОВЕРИТЬ]** на установленной версии |
| Аудио-анализ (beat/sections) | Возможно | librosa на CPU; пик RAM ниже 1 GB; замеры нужны |
| Preview через Tiny VAE | Неприменимо | LTX-2.3 MLX workflow не публикует промежуточные латенты |
| TTS/voice cloning | Ограничено | локальные модели в Maestro CUDA-only; на MLX движок не выбран |
| Lip sync человека | Ограничено | нет MLX-совместимого движка, проверенного на 18 GB |
| Lip sync животного (кошачья морда) | Не подтверждено | ни Maestro, ни доступные модели не заявляют animal-поддержку; тест невозможен без модели |
| Сборка/экспорт FFmpeg | Возможно | ffmpeg 7.1.1 присутствует; 576×1024 → 1080×1920 — CPU/VideoToolbox |
| Auto-Tune/presets | Возможно, в упрощённом виде | определять Apple Silicon/RAM/доступную память; без NVML и профилей VRAM |
| Второй Mac (2012, Intel HD 4000) | Только control plane | не GPU-worker для видеогенерации |

---

## 8. Минимальный набор новых функций

Отобрано по критерию «нужно текущему производственному процессу» (серия NLB, 30 шотов,
финальный клип) и «реализуемо без Maestro-кода и CUDA».

**Обязательно (must):**

1. **M-1. Ревью попытки** — approve/reject видео-попытки, писатель
   `shots.approved_attempt_id`; без миграции.
2. **M-2. Прогресс и мониторинг одиночной job** — события в `GET /api/jobs/{id}`,
   polling в `ShotDetailPage`; без миграции.
3. **M-3. Сборка и экспорт** — FFmpeg concat утверждённых попыток, музыкальная дорожка,
   триммы, 9:16 MP4; без миграции (новый `kind` job при необходимости **[ПРОВЕРИТЬ]**).
4. **M-4. Музыкальный таймлайн и план клипа** — аудио-анализ + план сцен/шотов
   с LLM и Pydantic-валидацией; новые таблицы обсуждаются отдельно.
5. **M-5. Восстановление по `prompt_id`** — заполнять `jobs.external_id`, сверять
   `/history` в `resume`.

**Желательно (should):**

6. Сравнение попыток и метаданные в UI (без новой модели данных).
7. Voice reference персонажа (хранение и approve), без синтеза.
8. Hardware-aware presets Safe/Balanced/Quality на измеренных данных.
9. Continuity-чеклист (инструменты, костюмы, реквизит) на существующих данных.

**Не делать (won't, в рамках обозримых WP):**

- Перенос кода, моделей, весов, ассетов Maestro.
- Полноценный видеоредактор и сложный timeline UI.
- Tiny VAE preview.
- Voice cloning и animal lip sync до появления проверенного MLX-движка.
- Установка CUDA-зависимостей и любых моделей без отдельного разрешения.

---

## 9. Риски регрессии

| Риск | Вероятность | Влияние | Мера |
|---|---|---|---|
| Новый слой планирования начнёт писать в `shots`/`prompt_revisions` и нарушит S15/S19 | Средняя | Высокое | планирование создаёт только `draft`-ревизии; approve — вручную |
| Экспорт «затрёт» исходные MP4 | Низкая | Высокое | только чтение исходных артефактов, новый artifact как результат |
| Отдельная job-очередь для монтажа | Средняя | Среднее | переиспользовать `jobs` с новым `kind`, без второй таблицы |
| Изменение enum `Shot.status` | Низкая | Высокое | не расширять enum; производные статусы считать из данных |
| Новые зависимости (librosa/numpy) на Apple Silicon | Средняя | Среднее | `uv` + lock, пинить версии, проверить лицензию и wheels |
| Похожесть на Maestro в коде | Средняя | Высокое (лицензия) | clean-room: спецификация → своя реализация; см. `MAESTRO_LICENSE_REVIEW.md` |
| Рост времени рендера из-за новых шагов | Низкая | Среднее | все новые шаги — отдельные и отключаемые |

---

## 10. Открытые вопросы к человеку

1. Приоритет: сначала **финальный клип** (сборка/экспорт) или сначала **планирование
   следующей песни** (Phase B)?
2. Есть ли утверждённый список шотов клипа (какие попытки считать финальными)?
   Для сборки нужен выбор попыток — либо ручной approve (M-1), либо явный список.
3. Аудио песни: файл уже доступен, где он должен храниться (артефакт проекта/сцены)
   и нужна ли поддержка стемов?
4. Нужен ли монтаж с переходами/текстом сразу или достаточно склейки + музыки?
5. Для голоса: планируется ли внешний TTS-сервис (правовые ограничения) или только
   локальный движок?
6. Разрешение на добавление `librosa`/`numpy` в backend (WP-M4) — да/нет.

---

## 11. [ПРОВЕРИТЬ]

| Пункт | Почему | Команда/способ |
|---|---|---|
| JSON-schema support в установленной Ollama | не проверялось в WP-M0 | `curl -s http://127.0.0.1:11434/api/tags`, затем тест `format`/`schema` на `gemma3:4b` |
| Поведение ComfyUI `/history` после рестарта воркера | требует запуска | ручной сценарий: старт рендера → kill воркера → `resume` |
| Совместимость librosa/numpy с Python 3.13 (если backend на 3.13) | не проверялось | `uv add librosa` в отдельной ветке и `python -c "import librosa"` |
| Точный размер и длительность MP4 NLB для оценки параметров сборки | не измерялось в WP-M0 | `ffprobe export/LLM-gen/NLB-*.mp4` |
| Лицензии моделей, которые будут использованы для TTS/lip sync | не выбраны модели | см. `MAESTRO_LICENSE_REVIEW.md` §7 |
| Фактическое runtime-поведение Director/Maestro | Maestro не запускался | не требуется для реализации; идеи проверяются собственными тестами |
