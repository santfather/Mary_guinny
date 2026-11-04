# AGENTS.md — правила работы над Mary Studio

> Репозиторий: `Mary_Guiness` — основной репозиторий Mary Studio.
> Документы-источники: `docs/ARCHITECTURE.md` (baseline v1.3),
> `docs/DECISIONS.md` (утверждённые изменения), `docs/ROADMAP_MARY_STUDIO.md` (порядок работ).
> Эти правила обязательны для любого агента и человека, работающего в репозитории.

---

## 1. Перед началом работы

1. Прочитать `docs/ARCHITECTURE.md` целиком (844 строки) и `docs/DECISIONS.md`.
2. Прочитать описание своего work package в `docs/ROADMAP_MARY_STUDIO.md`.
3. Если задача противоречит документам или они неоднозначны — **остановиться и задать
   вопрос**. Не выбирать молча.
4. До начала кодирования пересказать план: какие файлы будут созданы/изменены, какие
   миграции и контракты затрагиваются. Ждать явного «ок».

---

## 2. Один work package за раз

- Работать строго в рамках одного WP. Не начинать следующий WP без явного «продолжай».
- Ветка (после WP-00B): `wp-<id>-<кратко>`; небольшие коммиты; самостоятельно не мержить
  и не пушить в основную ветку.
- В конце WP — отчёт по формату из `docs/ARCHITECTURE.md` §14.2 и остановка.
- Идеи сверх плана — в `docs/IDEAS.md`, не в код.

---

## 3. Запреты без отдельного разрешения

Запрещено в рамках любого WP, если это не является его явной целью:

- **Миграции БД** — создавать, применять, откатывать, менять существующие.
- **Изменение API-контрактов** — схемы, эндпоинты, worker-протокол.
- **Обновление моделей и весов** — скачивание, замена, переквантование.
- **Обновление ComfyUI и custom nodes** — включая «безобидные» patch-версии.
- **Массовые рефакторинги** — переименования, переформатирование, переписывание стиля,
  «заодно почистил».
- **Перемещение и удаление файлов** — `characters/`, `episodes/`, `comfyui-workflows/`,
  `prompts/`, `pipeline/`, `tests/`, `main.py`.
- **Изменение `docs/ARCHITECTURE.md`** — baseline неприкосновенен; изменения только через
  `docs/DECISIONS.md`.
- **`git init`** — только WP-00B. **`git push --force`**, сброс истории, `rm -rf`, `sudo`,
  установка системных пакетов, открытие портов наружу.
- **Видеогенерация** — только WP-00A и только с разрешения человека.

Если для выполнения WP объективно нужен пункт из этого списка — остановиться и запросить
разрешение, а не обходить правило.

---

## 4. Контракты и происхождение данных

1. Схема БД и API меняются только в объёме, утверждённом в `docs/DECISIONS.md`.
2. Любое новое изменение схемы/API сначала оформляется предложением и утверждается.
3. Артефакты иммутабельны; происхождение обязательно (S12): `attempt` XOR `composition`
   XOR `upload`/`import`.
4. Approved-версии референсов, bible и ревизий композиции не перезаписываются.
5. `approved` выставляется только человеком; импортируемые данные — `draft`.
6. Стартовый кадр утверждается только через `promote-keyframe`.
7. Очередь сохраняет инварианты v1.3: lease, heartbeat, `lease_expired`, `resume`,
   частичный уникальный индекс активного render-job.

---

## 5. Безопасность

- `.env`, токены и ключи не читать, не печатать, не коммитить. В репозитории — только
  `.env.example`.
- ComfyUI и Ollama слушают только `127.0.0.1`; worker API защищён токеном.
- UI не публикуется в публичную сеть.
- В БД и API — только относительные `storage_key`; произвольные абсолютные пути отклоняются.
- Не принимать произвольные workflow JSON извне: custom nodes исполняют код.

---

## 6. Зависимости и окружение

- Новые компоненты: `uv` + `pyproject.toml` + `uv.lock`; версии пинить.
- Legacy `requirements.txt` не переводится на `uv` в рамках текущих WP.
- Перед добавлением зависимости проверить лицензию и поддержку.
- Custom nodes фиксировать по commit; автоматические обновления запрещены.
- Node/Python версии — через `mise`, контейнеры — OrbStack (`.cursor/rules/tooling.mdc`).

---

## 7. Проверки и отчётность

1. Не заявлять «готово» без фактического запуска проверок. В отчёт — реальный вывод команд.
2. Не ослаблять и не удалять тесты, чтобы они прошли. Красный тест
   `test_character_refs_stage_reports_missing` исправляется только в WP-00C.
3. Всё непроверяемое помечать **[ПРОВЕРИТЬ]** и давать человеку точную команду проверки.
4. Отчёт: что сделано, чем проверено, отклонения, что не удалось проверить, открытые
   вопросы, предложение следующего шага. После отчёта — остановка.

---

## 8. Текущее состояние (на 2026-11-04)

- WP-00 выполнен: `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/ENV-AUDIT.md`, `AGENTS.md`.
- WP-00B выполнен: git инициализирован, ветка `main`, remote `git@github.com:santfather/Mary_guinny.git`.
- WP-00C выполнен: 15 passed.
- WP-00A выполнен: I2V API-workflow `comfyui-workflows/ltx23_mlx_q4_i2v.api.json`, один прогон 512×512/73/24.
- WP-01 выполнен: `backend/` (FastAPI, SQLAlchemy 2, Alembic), миграция `0001_initial_core`
  — 11 таблиц §4.1 v1.3 с S10/S11/S12; `GET /health` → 200.
- WP-02 выполнен: миграции `0002_character_library`, `0003_reference_constraints`,
  `0004_composition_revisions` — библиотека персонажей, project isolation, ревизии
  композиций, S13–S18 и триггеры иммутабельности approved-записей.
- WP-03 выполнен: `app/storage.py` (content-addressed blob, atomic publish),
  `app/image_probe.py` (PNG/JPEG + альфа-канал), `app/legacy_import.py` и CLI
  `python -m app.import_legacy`, `POST /api/artifacts` + `GET /api/artifacts/{id}[/content]`.
  Импорт `characters/` и `episodes/` выполнен, отчёт — `docs/MIGRATION-REPORT.md`;
  оригиналы не перемещались (sha256 до/после совпадают), повторный запуск идемпотентен.
- WP-04 выполнен: API библиотеки (`projects`, `characters`, `bible`, `references`,
  `locations`, `props`, approve/reject) и data-fix CLI `python -m app.set_character_kinds`;
  UI `ui/` (React 19 + TypeScript + Vite) — список персонажей, bible, сетка референсов,
  фильтры, лайтбокс, approve/reject, каталоги локаций и предметов.
- WP-05 выполнен: `app/composer.py` (Pillow, RGBA, предупреждения о непрозрачных слоях),
  API сцен/шотов/`shot_references`/ревизий композиции, `keyframe` + `promote-keyframe`,
  render-гейт (`POST /api/shots/{id}/render` → pending job); UI `#/shots` и
  `#/shots/{id}` — шоты, референсы, редактор слоёв, render/approve/supersede, стартовый
  кадр. Схема БД не менялась.
- WP-05A выполнен: миграция `0005_visual_scene_plans` (таблица `visual_scene_plans`,
  S19; частичный уникальный индекс approved, S15-триггер, `shot_compositions.source_plan_id`),
  `app/planner.py` (vision `gemma3:4b` как советующий источник + fallback),
  `app/api/scene_plans.py` (list/create/get/put/generate/approve/supersede/composition),
  `POST /api/projects/{id}/references`, `layout mockup` и экспорт 512×512 `crop`/`pad`;
  UI — `ScenePlanPanel.tsx`, `ScenePlanEditor.tsx`, `ReferencePicker.tsx`.
- WP-06 выполнен: миграция `0006_events` (журнал `events`, `sequence`, CHECK,
  `uq_events_job_sequence`), `app/api/worker.py` (claim `FOR UPDATE SKIP LOCKED`,
  heartbeat, artifacts с sha256 и проверкой MP4, complete, fail с `retry_wait`,
  resume; обязательный токен), `app/api/jobs.py`, `app/video_probe.py`,
  `Idempotency-Key` в `POST /api/shots/{id}/render`, `worker/fake_worker.py`
  (ffmpeg → валидный MP4). `lease_expired` не перезапускается автоматически.
- WP-N1 выполнен: `app/series_manifest.py`, `app/series_import.py`, `app/preflight.py`,
  `app/import_series.py`, `app/api/series.py` — импорт «Ночного тыгыдыка» (30 шотов,
  30 motion-ревизий, 6 референсов) и preflight; блокировки `missing_reference`/
  `missing_start_frame` выводятся из данных, enum `Shot.status` не расширялся.
- WP-N2 выполнен: `pipeline/comfyui/ltx_adapter.py` — шаблон → payload шота
  (`snap_frames` 8k+1, 9:16 → 1080×1920, уникальный `filename_prefix`,
  `workflow_version` = sha256 шаблона).
- WP-N3 выполнен: `worker/client.py` (общий протокол), `worker/ltx_worker.py`
  (кадр → `/prompt` → heartbeat на каждом `/history` → `/view` → `ffprobe` → artifact →
  complete); `claim` отдаёт `inputs.prompt`/`shot_key` из motion-ревизии (§5.2 baseline).
  Реальный рендер в ComfyUI не запускался.
- WP-N4 выполнен: миграция `0007_render_series` (`series_runs`, `series_items`),
  `app/api/series_runs.py` (create/list, `start/pause/resume/stop-after-current/cancel`,
  воркерский `POST /api/worker/series/next` — одна тяжёлая job за раз, идемпотентность
  `series:{run_id}:{order}`), `app/notify.py` (баннер macOS), `--series-run` в
  `worker/ltx_worker.py`, UI `#/series/{id}` и панель прогона на `#/shots`.
  `enum Shot.status` и имена событий не расширялись.
- WP-05B (multi-reference video PoC) не начат: LTX в WP-05A не запускался.
- Калибровка 2026-10-28: первая попытка 1080×1920 остановлена по памяти (stage 2 не
  завершил ни одного шага; two-stage снапит до 1024×1920). Вторая попытка 576×1024
  (`--long-side 1024`) — MP4 получен: h264, 576×1024, 24 fps, 193 кадра, 8.04 с,
  полный рендер ≈ 18 мин. Разрешение серии зафиксировано в `docs/DECISIONS.md` §4.5.
- WP-04A выполнен: единый `app/api/library.py` (локации и предметы через реестр
  `_LibraryKind`), `deps.require_project`, схемы `LibraryEntity*`; удалены
  `api/locations.py`, `api/props.py`; UI — `pages/LibraryPages.tsx`,
  `hooks/useReferenceReview.ts`, `libraryApi`; удалены `LocationsPage`, `PropsPage`,
  `ReferenceGrid`. «Основной референс» — `role='primary'` с единственностью среди
  mutable-референсов (`_clear_other_primary`); approved остаётся неизменяемым (S15).
- Тестовые шоты 2026-10-28: NLB-02/NLB-03 (прогон `7b0750a4…`, воркер без `--once`
  закрыл оба сам) и NLB-31 (танец + реплика, artifact `19fb5662…`). Все MP4 — h264,
  576×1024, 24 fps, 193 кадра; аудиодорожка `aac` 48 kHz stereo есть у всех роликов.
  Человек принял качество («морфинга нет, герой не плывёт») и разрешил серию 30.
- WP-08 выполнен: миграция `0008_series_run_title` (`series_runs.title`, nullable),
  поле `title` в `POST /api/projects/{id}/series/runs`, в списке и в детали прогона;
  UI — поле «Название прогона» на `#/shots` и заголовок `#/series/{id}`. Первый
  именованный прогон — «NLB-single» (`85e04a00…`, 24 шота 4–27). Утверждены 5
  референсов (гитарист, барабанщик, басист, клавишник, Guiness) и созданы 24
  стартовых кадра через `keyframe` + `promote-keyframe`; NLB-28…30 ждут референс
  `wide_cinematic_concert_stage_scene_a_realistic.png`.
- Прогон «NLB-single» завершён: 24 из 24 completed, 7 ч 05 мин, все MP4 — 576×1024 / 193
  кадра / 24 fps с аудио `aac`.
- 2026-10-29: получен широкий референс (`docs/cats/Feline Rock Band Under Neon Lights.png`,
  asset `e7af9bb1…`, approved по разрешению человека), созданы стартовые кадры 28–30,
  preflight — `references` OK и `start_frames` 30 из 30. Прогон «NLB-single wide (28-30)»
  (`ce0c1bfa…`) рендерит 28–30 в 16:9, 1024×576 (`docs/DECISIONS.md` §4.5 п.5).
- 2026-10-29, NLB-21…27 (сюжетные шоты): новый портрет Гиннесса
  `docs/cats/Chocolate Burmese Cat Portrait.png` импортирован штатным API как
  `kind=uploaded`, `role=guinness_identity`, approved человеком (asset `6f999c54…`,
  1064×1479, sha256 `f7ec5d84…`); старая карточка `Guiness_clean` (`e4c57b2f…`) отвязана
  от 21–27, но осталась approved. Сцен-кадры 9:16 подготовлены внешне (системной
  генерации сцен с сохранением идентичности нет) и проведены штатным путём
  `POST /api/projects/{id}/references?role=nlb_XX_start` → `keyframe` → `promote-keyframe`.
- Motion-промпты NLB-21…27 заменены ревизиями v2 (`source=human_prompt_override`) через
  новый CLI `python -m app.set_shot_prompts` (dry-run/apply, идемпотентен); v1 сохранены.
- Провенанс рендера: необязательное `parameters` в `WorkerCompleteRequest` дописывается в
  `render_attempts.parameters` — width/height/num_frames/frame_rate/cfg_scale/seed/
  aspect_ratio/long_side/filename_prefix/shot_key + `workflow_snapshot`. У старых попыток
  поля нет (история не переписывалась); схема БД не менялась.
- Перегенерация NLB-21…27: по одному новому RenderAttempt на шот, все MP4 — h264
  576×1024 / 24 fps / 193 кадра / 8.04 с / `aac` 48 kHz stereo; старые попытки и MP4
  сохранены (всего 14 видео-попыток по семи шотам). Человек утвердил все семь роликов.
- Ограничения, подтверждённые при работе: planner не создаёт изображения, composer даёт
  только `layout mockup`, SDXL/IPAdapter в ComfyUI отсутствуют — сцен-кадры производятся
  вне системы; входные кадры 392–396 px шириной модель апскейлит (1.56–1.66×) с обрезкой
  3–6% по бокам.
- WP-M0 выполнен (2026-11-04): аудит open-source проекта Maestro по commit
  `05f5677f…` (`VERSION=3.2.5`), лицензионный обзор и roadmap интеграции —
  `docs/PROPOSALS/MAESTRO_CAPABILITY_AUDIT.md`, `MAESTRO_LICENSE_REVIEW.md`,
  `MAESTRO_INTEGRATION_ROADMAP.md`. Код Maestro не переносится (только clean-room идеи),
  Mary Studio не менялся.
- WP-M1 выполнен: ревью видео-попытки (`POST /api/shots/{id}/attempts/{attempt_id}/
  approve|reject`, идемпотентный писатель `shots.approved_attempt_id`, без миграций),
  `GET /api/jobs/{id}/events` и `last_event` в детали job, UI — плеер попытки, кнопки
  «Утвердить»/«Отклонить», бейдж утверждённого дубля, панель прогресса `JobProgress`
  (polling 3 с, «этап», elapsed) и метаданные попытки. Отклонение от roadmap: `reject`
  утверждённой попытки снимает `approved_attempt_id` (решение в отчёте WP-M1, §4.2
  baseline не нарушен).
- WP-M2 выполнен: миграция `0009_export_artifacts` (`artifacts.metadata` JSONB,
  `source='export'`, пересоздание CHECK S12), `app/assembly.py` (ffmpeg: trim → scale/pad
  1080×1920 → 24 fps → concat → h264/aac + `+faststart`; звук клипов или внешняя дорожка),
  `app/api/exports.py` (`POST/GET /api/projects/{id}/exports`, провенанс в metadata),
  UI `#/exports` (`ExportPage`, загрузка музыки); решение — `docs/DECISIONS.md` §4.8.
  Живая сборка NLB-21…23: 1080×1920 / 24 fps / 24.126 с / h264 + aac, sha256 исходников
  до и после совпадают.
- WP-M3 выполнен: миграция `0010_audio_timeline_plans` (`projects.audio_artifact_id`,
  таблица `production_plans` со статусами `draft`/`superseded`), `app/audio_timeline.py`
  (FFmpeg → RMS-огибающая 100 Гц → BPM/биты/downbeats/секции, чистый Python, без
  `librosa`), `app/production_plan.py` (каркас из секций + Ollama `gemma3:4b`
  structured output, Pydantic `extra="forbid"`, bounded repair ≤ 2, `fallback`),
  `app/api/production_plans.py` (`POST/GET /api/projects/{id}/audio`, `GET …/timeline`,
  `POST …/production-plans/generate`, list/detail), UI `#/plan` (песня, таймлайн,
  ревизии). Только черновые ревизии: сцены, шоты и approved-записи не меняются.
  Решение — `docs/DECISIONS.md` §4.10. Живая проверка NLB: трек 24.03 с → BPM 60.0
  (уверенность 0.91), ревизия 1 `manual`, ревизия 2 `llm` после двух `plan_repair`.
- WP-M4 выполнен: `POST /api/worker/jobs/{id}/external` пишет `prompt_id` в существующий
  `jobs.external_id` (миграций и нового события нет; `complete`/`fail` его сбрасывают),
  `GET /api/worker/resume` отдаёт `external_id`; `worker/client.py` — `link_external`,
  `ComfyUIClient.get_history`/`is_queued`; `worker/ltx_worker.py` — state-файл
  `~/.mary-studio/ltx-worker-state.json` (`--state-file`/`MARY_WORKER_STATE`, атомарная
  запись, best-effort), `recovered` через `resume` + `/history` с перепроверкой `/queue`,
  `external_prompt_lost` (retryable) при потере prompt'а. Решение — `docs/DECISIONS.md`
  §4.11. Живая проверка NLB-24 (576×1024): prompt `0f175737…` поставлен, воркер убит
  `kill -9`, recovery завершил job без повторного `/prompt` (в `/history` ровно одна
  запись), артефакт `7b71349b…` — h264 576×1024 / 193 кадра / 24 fps / 8.042 с + `aac`,
  `render_attempts.parameters` содержат `recovered=true` и `prompt_id`; на потерянном
  prompt'е (`6059528a…`, очистка очереди) получен `external_prompt_lost`.
- WP-M5 выполнен: `GET /api/projects/{id}/attempts` — аддитивная выборка чтения
  (фильтры `scene_id`/`shot_id`/`kind`/`status`, страница `items/total/limit/offset`,
  `limit` 1…100 по умолчанию 50, сортировка `created_at desc, id desc`), элемент —
  поля `AttemptOut` + `shot_id`/`shot_sequence_no`/`scene_id`/`scene_title`/`shot_status`/
  `approved`; флаг `approved` вычисляется из `shots.approved_attempt_id`. UI `#/attempts`:
  фильтры, пагинация, side-by-side двух завершённых видео-попыток, «Сделать текущей»
  вызывает существующий `approve` (новый писатель не вводился), ссылки на шот и артефакт;
  `attemptMeta` вынесен в `ui/src/attemptMeta.ts`. Решение — `docs/DECISIONS.md` §4.12.
  Схема БД не менялась, миграций нет. Живая выборка «The Nine Lives Band»: 82 попытки
  (39 завершённых видео); `approved`-попыток в данных пока 0 — флаг выставит человек
  кнопкой «Сделать текущей».
- WP-M6 выполнен: голос персонажа и многоракурсная карточка (Phase C, без синтеза речи).
  `POST /api/characters/{id}/voice` (сырое тело, `audio/mpeg|wav|mp4|aac`, ≤ 16 МиБ) пишет
  `reference_assets(role='voice')` — ffprobe проверяет аудиодорожку и длительность
  ≤ 30 с (`duration_s` в `metadata`), дедуп по sha256 в проекте (200 для того же
  персонажа, 409 `duplicate_reference` для другого). `multi_view` хранится в
  `reference_assets.metadata` и выставляется существующим `PATCH /api/reference-assets/{id}`
  (draft/rejected, S15 не ослаблен); `ReferenceOut` расширен `duration_s`/`multi_view`.
  `keyframe` из референса отклоняет (409) не-изображения и `multi_view=true`; слои
  композиции и пикер на шоте показывают только изображения. UI — раздел «Голос» на
  карточке персонажа (загрузка, `<audio>`, длительность, approve/reject) и чекбокс
  многоракурсной карточки в лайтбоксе. Решение — `docs/DECISIONS.md` §4.13.
  Схема БД не менялась, миграций нет; новый `tests/test_character_voice.py` — 7 тестов.
- WP-M7 выполнен: пресеты рендера под оборудование (Phase G). `backend/app/presets.py` —
  таблица **только измеренных** режимов: `safe` (576×1024, 24 шота «NLB-single»,
  1062,5 с/шот), `wide` (1024×576, 3 шота), `legacy_512` (512×512/73/24, WP-00A) с флагами
  `measured`/`measured_runs`; детект железа — stdlib + `sysctl`/`vm_stat` без новых
  зависимостей (доступная память = free + inactive + speculative), CUDA/NVML не
  используются. `GET /api/presets` (read-only) отдаёт `hardware`/`presets`/`recommended`/
  `reason`; `recommend()` — `safe` только для Apple Silicon ≥ 16 ГиБ, иначе `None` с
  причиной. Воркер (`resolve_preset`) соблюдает приоритет «CLI > API > default»,
  `--preset`/`--no-preset`, при недоступном API — предупреждение и встроенные значения;
  `preset`/`preset_source` пишутся в `render_attempts.parameters`. Решение —
  `docs/DECISIONS.md` §4.14. Схема БД не менялась, миграций нет;
  новый `tests/test_presets.py` — 11 тестов, в `tests/test_ltx_worker.py` +7.
- WP-M8 выполнен (только интерфейс): `backend/app/lipsync.py` — адаптер без движка
  (`SELECTED_ENGINE = None`, `LipsyncUnavailable` с кодами `lipsync_engine_not_selected`/
  `lipsync_engine_not_implemented`, `request_lip_sync()`); `POST /api/shots/{id}/lipsync`
  отдаёт 404 для неизвестного шота и 409 `lipsync_engine_not_selected` для валидного,
  ничего не пишет в БД и не создаёт job. UI-панель «Озвучка / Lip sync» (disabled-поля)
  только при `VITE_FEATURE_LIPSYNC=true`. Legacy-заглушки `pipeline/stages/lipsync.py` и
  `voices.py` не тронуты; веса, TTS и внешние сервисы не подключались. Решение —
  `docs/DECISIONS.md` §4.15. Миграций и новых зависимостей нет; новый
  `tests/test_lipsync.py` — 4 теста.
- WP-THERMAL-02 выполнен: thermal-safe планировщик без новых миграций и моделей.
  `backend/app/api/worker.py` — атомарный guard `render_video` в `claim` под
  `pg_advisory_xact_lock(hashtext('mary_studio:render_video_guard'))` + `NOT EXISTS`
  в одном операторе; `series_next` при чужом активном рендере отдаёт `busy` и
  `run_id`. `worker/thermal.py` — пробы (Swift-helper `ProcessInfo.thermalState`,
  `pmset -g ps`, `sysctl`/`vm_stat`), профили `off|balanced|eco` (Eco: сеть, normal
  pressure, ≥ 4 ГиБ), гистерезис после `serious`/`critical`, cooldown 480/1200 с,
  консервативный режим при `unknown` (900 с, партия ≤ 2), JSONL-журнал с ротацией,
  `KeepAwake` (`caffeinate -i -w <pid>`), состояние в `~/.mary-studio/thermal-state.json`.
  `worker/ltx_worker.py` — `--thermal-profile/--no-caffeinate/--allow-battery/
  --thermal-state-file/--thermal-log/--thermal-helper/--build-thermal-helper/--thermal-poll/
  --thermal-max-wait`, допуск до `claim`, Thermal Pause через существующие
  `pause`/`resume` (снимает только свою паузу), телеметрия в
  `render_attempts.parameters.thermal` + `peak_mem_mb`, `caffeinate` в `finally`.
  `GET /api/render-agent/status` (read-only: снимок воркера + хвост журнала + очередь
  из БД, `render_agent_stale_seconds`=180) и панель «Термозащита» на `#/series/{id}`.
  Решение — `docs/DECISIONS.md` §4.16. Схема БД не менялась; новые
  `tests/test_thermal_gate.py` — 33 теста, `backend/tests/test_render_agent_status.py` —
  5 тестов, в `tests/test_ltx_worker.py` +5.
- Тесты: legacy — 15 passed; backend — 239 passed; `tests/test_ltx_worker.py` — 35 passed;
  `tests/test_thermal_gate.py` — 33 passed; `tests/test_ltx_adapter.py` — 12 passed;
  корневой `python -m pytest tests` — 95 passed;
  `alembic check` — no new operations (после `0010_audio_timeline_plans`); UI — `npm run build`.
