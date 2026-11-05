# COMPONENT INVENTORY — Mary Studio (WP-AUDIT-01)

Дата аудита: 2026-11-05. Режим: READ-ONLY (ничего не изменялось, кроме этих документов).
Ветка: `wp-m0-maestro-audit`, HEAD `e3c391b`, миграции: `0011_mouth_calibrations`.

Статусы по §14 задания: **KEEP** / **KEEP_EXPERIMENTAL** / **DISABLE** / **ARCHIVE** /
**DELETE_CANDIDATE** / **INVESTIGATE**.

Все пути — относительно `/Users/vladislavkovalenko/Projects/Mary_Guiness`.

---

## 1. Сводная таблица

| ID | Компонент | Путь | Назначение | Ссылки из кода | Тесты | Данные пользователя | Статус |
|----|-----------|------|------------|----------------|-------|---------------------|--------|
| C-01 | HTTP API | `backend/app/main.py`, `backend/app/api/*.py` (23 модуля, 100 маршрутов) | Единственная точка доступа к данным | UI, worker, CLI | backend 298 тестов | да, БД | KEEP |
| C-02 | Ядро backend | `backend/app/config.py`, `db.py`, `models.py`, `deps.py` | Настройки, сессии, ORM-модели | всё | да | — | KEEP |
| C-03 | Миграции | `backend/alembic/versions/*` (0001–0011) | Схема БД | Alembic | `alembic check` | схема | KEEP |
| C-04 | Blob-хранилище | `backend/app/storage.py` | Content-addressed blob, atomic publish | artifacts, references, exports | да | 103 файла / 149 MB | KEEP |
| C-05 | Импорт legacy | `backend/app/legacy_import.py`, `app/import_legacy.py` | Разовый импорт `characters/`, `episodes/` | CLI | косвенно | нет (уже импортировано) | KEEP (одноразовый) |
| C-06 | Импорт серии | `backend/app/series_manifest.py`, `series_import.py`, `preflight.py`, `import_series.py` | Импорт NLB из манифеста + preflight | CLI, API `series` | да | 30 шотов NLB | KEEP |
| C-07 | Композиции | `backend/app/composer.py`, `api/shots.py` | Слои, layout mockup, keyframe, promote | UI Shot Editor | да | 2 композиции | KEEP |
| C-08 | Scene plans | `backend/app/planner.py`, `api/scene_plans.py` | Черновые планы сцен (Ollama как советчик) | UI | да | 0 записей `visual_scene_plans` | KEEP |
| C-09 | Очередь и job API | `backend/app/api/worker.py`, `jobs.py`, `video_probe.py` | claim/heartbeat/complete/fail/resume | worker, UI | да | 53 job, 102 attempt | KEEP |
| C-10 | LTX-воркер | `worker/client.py`, `worker/ltx_worker.py` | ComfyUI `/prompt` → MP4 → artifact | ручной запуск, `mary.sh worker` | 39 тестов | 45 completed job | KEEP |
| C-11 | Термозащита | `worker/thermal.py`, `api/render_agent.py`, UI «Термозащита» | Профили, admission, cooldown, журнал | воркер, `#/series/{id}` | 38 + 5 тестов | телеметрия в `render_attempts.parameters` | KEEP |
| C-12 | Пресеты | `backend/app/presets.py`, `api/presets.py` | Режимы `safe`/`wide`/`legacy_512` | воркер, UI | 11 + 7 тестов | — | KEEP |
| C-13 | Series orchestration | `backend/app/api/series_runs.py`, `notify.py`, UI `#/series/{id}` | Прогоны серии, пауза/резюм, уведомления | UI | да | 7 прогонов, 33 item | KEEP |
| C-14 | Сборка/экспорт | `backend/app/assembly.py`, `api/exports.py`, UI `#/exports` | FFmpeg trim→scale→concat→h264/aac | UI | да | 1 export artifact | KEEP |
| C-15 | План продакшена | `backend/app/audio_timeline.py`, `production_plan.py`, `api/production_plans.py`, UI `#/plan` | BPM/биты, черновой план сцен | UI | да | 2 плана, 1 аудио у NLB | KEEP |
| C-16 | Импорт аудио шота | `backend/app/shot_audio.py`, `api/shot_audio.py` | WAV/MP3/M4A/AAC → PCM 48k mono + огибающая | UI «Озвучка» | 15 тестов (mouth) | 4 `talking_preview` | KEEP |
| C-17 | Mouth animation (legacy) | `backend/app/mouth_animation.py`, `api/mouth_animation.py`, `api/mouth_calibrations.py`, `MouthAnimationPanel.tsx` | `mouth_animation_mvp` / `pillow_mouth_v2` | UI | 15 тестов | 2 калибровки, 4 job | KEEP_EXPERIMENTAL |
| C-18 | Viseme frame blend | `backend/app/viseme_blend.py`, `viseme_assets.py`, `viseme_service.py`, `api/viseme_set.py`, UI «Viseme-кадры» | Сборка кадра из 5 реальных фото | UI, GNS-05 | 26 тестов | 5 approved viseme + 2 attempt | KEEP_EXPERIMENTAL |
| C-19 | Rhubarb adapter | `backend/app/rhubarb.py`, внешний бинарник `~/.mary-studio/tools/rhubarb-1.14.0/` | Тайминги визем (CPU, x86_64/Rosetta) | `viseme_service` | 4 теста в `test_viseme_blend.py` | нет в БД | KEEP_EXPERIMENTAL |
| C-20 | Lip sync | `backend/app/lipsync.py`, `api/lipsync.py`, панель в `ShotDetailPage.tsx` | Заглушка без движка (`SELECTED_ENGINE = None`) | API, UI за `VITE_FEATURE_LIPSYNC` | 4 теста | нет | DISABLE |
| C-21 | Legacy pipeline | `main.py`, `pipeline/orchestrator.py`, `pipeline/stages/*`, `pipeline/comfyui/{generator,scene_draft,workflows}.py` | Старый CLI-конвейер эпизодов | `main.py`, `tests/test_pipeline.py`, `test_comfyui.py` | 15 legacy-тестов | нет | ARCHIVE |
| C-22 | `pipeline/comfyui/generator.py` | `pipeline/comfyui/generator.py:121` | Хардкод пути к чужому ComfyUI | только `main.py` | нет | нет | INVESTIGATE |
| C-23 | Менеджер сервисов | `mary.sh` | start/stop/status backend, frontend, comfy | человек | нет | PID в `runtime/pids` | KEEP |
| C-24 | UI | `ui/src` (9 страниц, `App.tsx`) | Весь интерфейс | — | `npm run build` | — | KEEP |
| C-25 | Базовые документы | `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/ROADMAP_MARY_STUDIO.md`, `docs/OPEN_QUESTIONS.md`, `README.md` | Правила и контракты | — | — | — | KEEP |
| C-26 | Отчёты WP | `docs/REPORTS/*` (7 файлов) | История приёмок | — | — | — | KEEP (история) |
| C-27 | Предложения | `docs/PROPOSALS/*` (21 файл) | Планы, аудиты, GNS-документы | — | — | — | KEEP (часть — ARCHIVE-кандидаты) |
| C-28 | `CLAUDE.md` | `CLAUDE.md` | Описывает чужой проект `github-crawler` | нет | нет | нет | DELETE_CANDIDATE |
| C-29 | Старые заметки | `AI_Tools_Analysis.md`, `scenario.md`, `docs/new_updates.md` | Черновики вне контракта | нет | нет | нет | ARCHIVE |
| C-30 | Личный бэклог | `i_will_do_it_later.md` | Идеи человека | нет | нет | нет | KEEP |
| C-31 | Внешние LLM-видео | `export/LLM-gen/` (93 MP4, 241 MB) | Ролики, сгенерированные вне системы | нет | нет | нет ссылок из БД | ARCHIVE |
| C-32 | A/B-материалы VOICE-06 | `export/wp_voice_06_ab/` (10 MB) | Доказательства A/B | нет | нет | нет | ARCHIVE (до решения) |
| C-33 | Runtime ComfyUI | `runtime/ComfyUI/` (2.5 GB, 65 585 файлов) | Внешняя установка ComfyUI | воркер через HTTP | нет | output 149 MB | KEEP локально (не в Git) |
| C-34 | Логи воркера | `runtime/logs/` (2.9 MB), `runtime/ltx-worker-state.json` | Операционные логи/состояние | воркер | нет | состояние recovery | KEEP локально |
| C-35 | `comfyui-input/` | `comfyui-input/` (0 B) | Пустой каталог, не покрыт `.gitignore` | нет | нет | нет | DELETE_CANDIDATE |
| C-36 | `exports/` | `exports/` (0 B) | Пустой каталог-двойник `export/`; в `.gitignore` есть `exports/*` | нет | нет | нет | DELETE_CANDIDATE |
| C-37 | `worker_lease_seconds` | `backend/app/config.py:53` | Поле настроек без читателей | нет | нет | нет | DELETE_CANDIDATE |
| C-38 | `MARY_DISABLE_NOTIFY` | `backend/app/notify.py:24` | Читается из `os.environ` вне `Settings` | `notify` | нет | нет | INVESTIGATE |
| C-39 | 198 artifact без файлов | БД `artifacts` + `storage/blobs` | Строки `project_audio`/`note` без blob | — | — | да (метаданные) | INVESTIGATE |
| C-40 | Orphan blobs | `storage/blobs/.DS_Store`, `storage/blobs/20/201bc4b0…wav` | Файлы без ссылок из БД | нет | нет | нет | DELETE_CANDIDATE |
| C-41 | 5 мёртвых методов клиента | `ui/src/api/client.ts:451,502,515,607,648` | Нет вызовов из UI | нет | сборка не ловит | нет | DELETE_CANDIDATE |
| C-42 | 10 API без UI | см. `PROJECT_AUDIT_2026_11.md` §11 | Worker/CLI/мониторинг/админ | частично | да | да | KEEP |

---

## 2. Компоненты с особыми пометками

### 2.1 C-17 Mouth animation — KEEP_EXPERIMENTAL

- Движки: `mouth_animation_mvp` (по умолчанию) и `pillow_mouth_v2`
  (`backend/app/mouth_animation.py`), API `POST /api/shots/{id}/mouth-animation`,
  таблица `mouth_calibrations` (2 записи), 4 завершённых `mouth_animation` job.
- Фактическое качество: **не принято человеком**. WP-VOICE-03 — рот накрывал глаз и нос;
  WP-VOICE-04 — сдвиг калибровки на линию губ, но утверждения не было.
- Отключать нельзя без потери воспроизводимости уже сделанных preview: 4 артефакта
  `attempt/talking_preview` ссылаются на этот движок.

### 2.2 C-18 Viseme frame blend — KEEP_EXPERIMENTAL

- 5 approved-состояний GNS-05 (`closed`, `small_open`, `medium_open`, `wide_open`,
  `rounded`), отчёт набора `ready=true`, `blockers=[]`.
- Сборка B (`attempt 3eb3ca9f-…`, `artifact a5326a3f…`, 960×960, 285 кадров, 11.875 с,
  702 273 Б) **не утверждена**. Визуальный дефект: прямоугольная граница патча
  (освещение viseme-кадров отличается от `closed.png`).
- Код не удалять: это единственный работающий путь «реальные фото + тайминги».

### 2.3 C-19 Rhubarb — KEEP_EXPERIMENTAL

- Бинарник `1.14.0`, архитектура `x86_64`, запуск через Rosetta 2 (`rosetta: true`),
  SHA-256 запинен: `93fa4a16ae1cc88a89d59743057521407843fc7139e23808c9e6587c6cc946d3`.
- Даёт **только тайминги**, не анимацию. 82 интервала на записи 11.86 с.
- Внешняя зависимость вне Git: потеря каталога `~/.mary-studio/tools/rhubarb-1.14.0/`
  восстанавливается только повторной установкой (см. `OPEN_RISKS.md` R-08).

### 2.4 C-20 Lip sync — DISABLE

- `backend/app/lipsync.py:35` — `SELECTED_ENGINE: LipsyncEngine | None = None`;
  `POST /api/shots/{id}/lipsync` всегда 409 `lipsync_engine_not_selected`.
- UI-панель включается только при `VITE_FEATURE_LIPSYNC=true`
  (`ui/src/pages/ShotDetailPage.tsx:24`) и содержит статичный текст, без вызовов API.
- Кода мало (4 теста), удаление допустимо только вместе с решением «lip sync не делаем»
  (см. `CLEANUP_CANDIDATES.md` CC-07).

### 2.5 C-21 Legacy pipeline — ARCHIVE

- `main.py` импортирует `pipeline.orchestrator` и `pipeline.comfyui.generator`;
  `pipeline/stages/{scene_draft,assembly,final_video,music,voices,lipsync,script}.py` —
  стабы старого конвейера, не используются API/воркером.
- Живыми остаются только:
  - `pipeline/utils.py` — используется `backend/app/legacy_import.py` (импорт bible);
  - `pipeline/comfyui/client.py` — используется `worker/ltx_worker.py` и тестами;
  - `pipeline/comfyui/ltx_adapter.py` — payload шота (12 тестов).
- **Удалять `pipeline/` целиком нельзя**: сломается `worker/ltx_worker.py` и legacy-тесты.

### 2.6 C-39 / C-40 — данные и файлы

- 198 записей `artifacts` (197 `upload/project_audio` + 1 `upload/note`, 18 924 421 Б)
  указывают на отсутствующие blob. Это **данные в БД**, а не файлы: удалять строки
  нельзя без отдельного решения (см. `DATABASE_INTEGRITY.md` §4, `OPEN_RISKS.md` R-02).
- На диске ровно 2 orphan-файла: `blobs/.DS_Store` (14 340 Б) и
  `blobs/20/201bc4b0….wav` (1 136 138 Б, не входит ни в `artifacts`, ни в
  `reference_assets`).

---

## 3. Что проверено, а что нет

| Утверждение | Доказательство | Статус |
|-------------|----------------|--------|
| 100 маршрутов в 23 модулях | подсчёт `len(router.routes)` по `backend/app/api/*` | проверено |
| 5 неиспользуемых методов клиента | `Grep` по `ui/src` — 0 вызовов `api.attempts(`, `api.compositions(`, `api.jobEvents(`, `api.productionPlan(`, `api.uploadReference(` | проверено |
| 298 backend-тестов | `pytest --collect-only` = 298 | проверено (сбор) |
| 104 корневых теста | `pytest --collect-only tests` = 104 | проверено (сбор) |
| Тесты проходят | не запускались в этом аудите | NOT VERIFIED |
| 15 legacy-тестов | заявлено в `AGENTS.md` | NOT VERIFIED (в сбор 104 не входят) |
| launchd-сервисы | `launchctl list` — permission denied | NOT VERIFIED |
