# Roadmap Mary Studio

> **Статус:** архитектура утверждена; WP-00, WP-00A, WP-00B, WP-00C, WP-01, WP-02,
> WP-03, WP-04, WP-04A, WP-05, WP-05A и WP-06 выполнены (2026-10-26); серия
> «Ночной тыгыдык» — WP-N1, WP-N2, WP-N3, WP-N4 выполнены (2026-10-28); WP-05B,
> WP-N5 и WP-07 и далее не начаты.
> **Связанный документ:** `docs/PROPOSALS/MARY_STUDIO_INTEGRATION.md`,
> `VIDEO-ORCHESTRATOR.md` v1.3.
> **Принцип:** маленькие проверяемые пакеты; каждый следующий начинается только после
> приёмки предыдущего. Оценки сроков не приводятся.
> **Правило зависимостей:** пакет не может ссылаться на таблицу, колонку или эндпоинт,
> которые не созданы в нём самом или в уже принятых пакетах. Для каждого WP перечислены
> миграции, которые он добавляет.
> **Правило файлов:** существующие пользовательские файлы (`characters/`, `episodes/`,
> `comfyui-workflows/`, `prompts/`) не перемещаются и не удаляются ни в одном пакете.

---

## 1. Целевой пользовательский сценарий

1. Открыть веб-интерфейс Mary Studio.
2. Найти персонажа Guinness.
3. Просмотреть его референсы.
4. Выбрать и утвердить референс.
5. Создать шот.
6. Привязать стартовый кадр.
7. Поставить I2V-рендер в очередь.
8. Получить MP4.
9. Просмотреть и утвердить попытку.

Разметка по среде:

| Шаг | Компонент | FakeWorker | Реальный Mac |
|---|---|---|---|
| 1–2 | UI + backend + БД | Не нужен | Не нужен |
| 3–4 | UI + backend + storage | Не нужен | Не нужен |
| 5 | UI + backend | Не нужен | Не нужен |
| 6 | backend-композитор PNG | Не нужен | Не нужен |
| 7 | API → PostgreSQL queue | Да | Да |
| 8 | Worker + ffmpeg (fake) / ComfyUI LTX (real) | Да, синтетический MP4 | Да, реальный I2V |
| 9 | API + UI review | Да | Да |

Реальный Mac обязателен только для: LTX-2.3 MLX I2V, реального ComfyUI `prompt_id`,
телеметрии памяти и проверки OOM/recovery. Ранняя проверка API-взаимодействия вынесена
в WP-00A; всё остальное проверяется на FakeWorker.

---

## 2. Пакеты работ

Легенда: **Зависит** — без чего нельзя начинать; **Миграции** — какие миграции добавляет
пакет (или «нет»); **DoD** — критерии готовности.

### WP-00. Архитектурный baseline

**Объём:** только документы.

- Скопировать `VIDEO-ORCHESTRATOR.md` v1.3 в `docs/ARCHITECTURE.md` без правок.
- Создать `docs/DECISIONS.md` с решениями по §10.2 предложения.
- Создать `docs/ENV-AUDIT.md`: Python, пакеты, ComfyUI/Ollama, ffmpeg, отсутствующие
  API-workflow.
- Создать `AGENTS.md` для backend/ui/worker.
- Зафиксировать статус: архитектура предварительно одобрена, work packages не утверждены.

**Состояние:** выполнен 2026-10-26.

**Зависит:** ничего.
**Миграции:** нет.
**DoD:** документы существуют; ссылки валидны; `.env` не скопирован; нет кода.
**Проверка:** чтение файлов, поиск секретов, проверка относительных ссылок.

---

### WP-00A. Ранний LTX PoC (API-взаимодействие)

**Цель:** подтвердить рабочий API-workflow с уже работающим LTX-2.3 MLX Q4 I2V на Mac
**до** интеграции реального worker и до WP-08. Это технический PoC, а не часть backend.

**Объём:**

- Зафиксировать текущий рабочий I2V-граф: экспортировать API-формат в новый файл
  `comfyui-workflows/ltx23_mlx_q4_i2v.api.json` и рядом `ltx23_mlx_q4_i2v.meta.json`
  (модель, `pipeline_type`, `num_frames`, разрешение, fps, seed, cfg, версия node pack).
- Существующие workflow-файлы не изменяются; UI-граф `ltx23_mlx_q4_test.json` остаётся как есть.
- Проверить доступность: `GET /system_stats`, `GET /object_info/LTX2MLXGenerate`.
- Загрузить исходный PNG: `POST /upload/image`.
- Отправить prompt в ComfyUI: `POST /prompt` с API-workflow и параметрами.
- Получить и сохранить `prompt_id`.
- Отследить выполнение: `GET /history/{prompt_id}` с таймаутом и обработкой ошибок.
- Получить MP4: `GET /view`.
- Сохранить параметры генерации (seed, кадры, fps, разрешение, модель, workflow version,
  `prompt_id`, длительность) в JSON рядом с результатом.
- Проверить результат через `ffprobe`: контейнер, видеопоток, длительность, размер кадра.

**Состояние:** выполнен 2026-10-26. Подтверждён I2V-прогон 512×512 / 73 кадра / 24 fps
(seed 42, cfg 3.0, Q4 distilled) — MP4 3.04 с, `prompt_id` и параметры в
`episodes/ep01/poc/ltx23_mlx_q4_i2v.meta.json`. Повтор с тем же seed не выполнялся.

**Зависит:** WP-00; Mac с запущенным ComfyUI и рабочим LTX-2.3 MLX Q4 I2V; разрешение
человека на один реальный прогон.
**Миграции:** нет.
**DoD:** один воспроизводимый I2V-ролик из PNG; `prompt_id` и параметры сохранены;
`ffprobe` подтверждает валидный MP4; API-формат workflow лежит в `comfyui-workflows/`;
ни одна существующая модель, нода или workflow не изменена.
**Проверка:** журнал запросов и ответов; JSON параметров; `ffprobe`; повторный прогон
с тем же seed даёт сопоставимый результат.
**Не делать:** backend/worker/queue/UI; скачивание моделей; обновление custom nodes;
массовые прогоны; изменение существующих workflow.

---

### WP-00B. Git baseline (контролируемо)

**Объём:**

- Создать `.gitignore`: `runtime/`, `.venv/`, `storage/`, `__pycache__/`, `.pytest_cache/`,
  `.env`, временные файлы; пользовательские `characters/`, `episodes/`,
  `comfyui-workflows/`, `prompts/` **не** игнорируются.
- `git init -b main`; `git add -n` и `git check-ignore` для проверки перед добавлением.
- Точечный `git add` исходников и документов; первый коммит.
- Remote и push — только по отдельному решению человека.

**Состояние:** выполнен 2026-10-26. Remote — `git@github.com:santfather/Mary_guinny.git`
(SSH; HTTPS-учётные данные в keychain принадлежат другому аккаунту), ветка `main`.
Ассеты `characters/*.png|jpg`, `episodes/*.mp4|png|wav|mp3`, `exports/` и `comfyui-input/`
исключены по D3; текстовые `character_bible.txt` и `script.txt` включены.

**Зависит:** WP-00; подтверждение человека на инициализацию репозитория.
**Миграции:** нет.
**DoD:** репозиторий инициализирован; `.env` и `runtime/` не попали в индекс; первый коммит
содержит только исходники и документы; файлы на диске не перемещены и не удалены.
**Проверка:** `git status`, `git check-ignore -v .env runtime`, `git ls-files`.
**Не делать:** `git add .`, force-push, переписывание истории, удаление файлов.

---

### WP-00C. Исправление падающего теста (контролируемо)

**Объём:**

- Изменить только `tests/test_pipeline.py::test_character_refs_stage_reports_missing`:
  создать `Settings` до `Orchestrator` и передать их в конструктор.
- Production-код (`pipeline/orchestrator.py`) не меняется; проверка не ослабляется.

**Зависит:** WP-00B (изолированный коммит).
**Миграции:** нет.
**DoD:** `pytest` → `15 passed`; дифф ограничен одним тестом; поведение оркестратора
не изменилось.
**Проверка:** `pytest tests/test_pipeline.py -q`.
**Не делать:** изменение CLI, этапов, DI в production-коде без отдельного решения.

---

### WP-01. Каркас backend и базовая схема

**Объём:**

- `backend/` на FastAPI, Python 3.13, `uv`, `pyproject.toml`, lockfile.
- SQLAlchemy 2, Alembic, PostgreSQL (локально через контейнер или существующий сервер).
- Конфигурация через env; health endpoint.
- Полная базовая схема §4.1 v1.3 **без логики очереди**: `projects`, `scenes`, `shots`,
  `prompt_revisions`, `jobs`, `job_dependencies`, `render_attempts`, `artifacts`, `workers`,
  `reference_assets` (минимальный набор колонок v1.3).
- Если S11 утверждён — `episodes` и `scenes.episode_id` создаются здесь же.
- Если S10 утверждён — `prompt_revisions.prompt_type` и `version` создаются здесь же.
- Если S12 утверждён — nullable-связи `artifacts.attempt_id`,
  `artifacts.shot_composition_id`, `render_attempts.job_id` создаются здесь же.
- Тесты API и миграций.

**Миграции:** `0001_initial_core` — все таблицы выше, enum/CHECK статусов, индексы,
`UNIQUE(scene_id, sequence_no)`, частичный уникальный индекс активного render-job.

**Почему схема шире, чем «projects/scenes/shots»:** WP-02, WP-03 и WP-05 ссылаются на
`artifacts`, `render_attempts` и `prompt_revisions`. Если создать их позже, эти пакеты
будут зависеть от несуществующих таблиц. Поэтому каркас таблиц создаётся сразу, а
поведение очереди остаётся за WP-06.

**Состояние:** выполнен 2026-10-26. `backend/` на FastAPI + SQLAlchemy 2 + Alembic (uv,
`backend/uv.lock`), миграция `0001_initial_core` — 11 таблиц §4.1 v1.3 с S10/S11/S12;
эндпоинты `/health` и `/api/health`. Проверки: `uv run pytest -q` → 7 passed;
`alembic upgrade head` / `downgrade base` / `upgrade head` на локальном PostgreSQL 16.14;
`alembic check` → «No new upgrade operations detected»; legacy `pytest` → 15 passed.
`pipeline/` не изменён.

**Зависит:** WP-00, WP-00B (git), решение по uv; утверждение S10/S11/S12 для
соответствующих колонок.
**DoD:** `GET /health` → 200; `alembic upgrade head` и `downgrade base` проходят;
тесты зелёные; legacy `pipeline/` не изменён; таблицы соответствуют §4.1 v1.3.
**Проверка:** `pytest backend/tests`, `alembic upgrade head`, `alembic downgrade base`.
**Не делать:** очередь, worker, UI, character library, бизнес-логика jobs.

---

### WP-02. Схема библиотеки персонажей

**Предусловие (таблицы WP-01, на которые опирается пакет):** `projects`, `scenes`, `shots`,
`artifacts`, `reference_assets`. Если какая-то из них отсутствует, пакет не начинается.

**Объём (после утверждения S1–S9):**

- Новые таблицы `characters`, `character_bible_versions`, `locations`, `props`
  (`UNIQUE(project_id, id)` на владельцах для составных FK).
- Расширение существующей `reference_assets` (§5.2): владельцы, `status`, `view`, `pose`,
  `expression`, `role`, `width`, `height`, `mime_type`, `approved_at`,
  `UNIQUE(project_id, sha256)`; CHECK «владелец соответствует `kind`», включая `uploaded`.
- Новые таблицы `shot_references` (с `project_id` и составным FK на ассет),
  `shot_compositions` (`UNIQUE(shot_id, revision)`, `status`) и `shot_composition_layers`
  (нормализованные слои с составным FK на ассет).
- `shots.start_keyframe_artifact_id` и `shots.start_keyframe_attempt_id` (S9).
- Инварианты §5.3: approve только вручную, approved-версии иммутабельны, архивирование
  вместо удаления.

**Миграции:** `0002_character_library` — новые таблицы и колонки; `0003_reference_constraints`
— CHECK/составные FK/уникальные индексы; `0004_composition_revisions` — слои, ревизии,
указатели стартового кадра и триггеры иммутабельности. Каждая миграция обратима.

**Зависит:** WP-01; утверждение S1–S9 (и S11, если эпизод нужен в этой же миграции).
**DoD:** миграция вверх/вниз; нельзя создать ассет без владельца или с владельцем другого
типа; нельзя сослаться на ассет другого проекта; нельзя переписать approved-запись;
несколько ревизий композиции на один шот работают; шот хранит конкретный
`reference_asset_id`; тесты зелёные.
**Проверка:** `alembic upgrade head`, `alembic downgrade base`,
`pytest backend/tests/test_character_library.py`, `pytest backend/tests/test_constraints.py`.

**Состояние:** выполнен 2026-10-26. Миграции `0002_character_library`,
`0003_reference_constraints`, `0004_composition_revisions` (7 новых таблиц, расширение
`reference_assets`, S13–S18, триггеры `mary_forbid_approved_change`).
Проверки: `alembic upgrade head` / `downgrade base` / `upgrade head` на локальном
PostgreSQL 16.14; `alembic check` → «No new upgrade operations detected»;
`uv run pytest -q` → 32 passed; legacy `pytest` → 15 passed. API/UI/worker не создавались.

---

### WP-03. Storage и импорт существующих файлов

**Объём:**

- Сервис storage: относительные `storage_key`, atomic publish, sha256.
- Дедупликация по sha256; запрет абсолютных путей.
- Импорт `characters/` и `episodes/` в режиме dry-run и apply.
- При импорте PNG фиксируются `width`, `height`, `mime_type` и наличие альфа-канала
  (флаг в `metadata`); непрозрачные референсы персонажей попадают в отчёт.
- Отчёт миграции; оригиналы не перемещаются.
- Скачивание/загрузка артефактов через backend.

**Миграции:** нет (используются таблицы WP-01/WP-02; при необходимости — только data-миграция
в рамках dry-run/apply, без изменения схемы).

**Зависит:** WP-02.
**DoD:** dry-run показывает план; повторный запуск идемпотентен; в БД и storage нет
дубликатов; оригиналы на месте; отчёт создан; для PNG указан признак альфа-канала.
**Проверка:** импорт на копии данных; сравнение sha256; `pytest backend/tests/test_storage.py`.
**Не делать:** удаление/перемещение пользовательских файлов.

**Состояние:** выполнен 2026-10-26. Добавлены `backend/app/storage.py`
(content-addressed `blobs/<aa>/<sha256><ext>`, атомарная публикация через `os.replace`,
запрет абсолютных путей и `..`), `backend/app/image_probe.py` (PNG/JPEG: `width`,
`height`, `mime_type`, признак альфа-канала без новых зависимостей),
`backend/app/legacy_import.py` (dry-run/apply, идемпотентность по sha256),
CLI `uv run python -m app.import_legacy --dry-run|--apply`, `POST /api/artifacts` и
`GET /api/artifacts/{id}[/content]`. `MARY_STORAGE_ROOT` / `MARY_LEGACY_ROOT` в
`app/config.py`; `storage/` добавлен в `.gitignore`.
Проверки: `uv run pytest -q` → 51 passed; legacy `pytest` → 15 passed;
`alembic check` → «No new upgrade operations detected» (схема не менялась).
Dry-run на реальном дереве: 62 операции создания, 24 предупреждения.
Apply: создано 62 записи, 26 blob (16 референсов, 5 keyframe, 5 video), дубликатов в БД
и storage нет; повторный apply → `created=0`; sha256 всех 26 blob совпадает с БД;
sha256 34 исходных файлов до/после импорта идентичны. Отчёт —
`docs/MIGRATION-REPORT.md`. `characters.kind` для legacy-персонажей — `other`
(зафиксировано в отчёте как требующее уточнения); `shots.start_keyframe_artifact_id`
не заполнялся (S9/A5: единственный писатель — `promote-keyframe`).

---

### WP-04. API и UI библиотеки (read + approve)

**Объём:**

- API `characters`, `locations`, `props`, references, approve/reject (A1–A3).
- UI: список и карточка персонажа, сетка референсов, фильтры `view/pose/status`,
  approve/reject.
- UI: минимальные карточки локаций и предметов.
- Никакой генерации и рендера.

**Миграции:** нет.

**Зависит:** WP-02, WP-03.
**DoD:** сценарий 1–4 выполняется в браузере: Guinness найден, референсы видны,
один утверждён; после approve меняется только статус, файлы не перезаписываются.
**Проверка:** backend-тесты approve/reject; UI-тест или ручная проверка; SSE не нужен.

**Состояние:** выполнен 2026-10-26. Backend: `app/api/projects.py`, `characters.py`,
`locations.py`, `props.py`, `reference_assets.py`, `deps.py`, `schemas.py`; data-fix CLI
`python -m app.set_character_kinds` (`guinness → cat`, `marija → human`; меняет только
`characters.kind`, есть dry-run/apply). UI: `ui/` на React 19 + TypeScript + Vite
(hash-роутинг, Vite-proxy `/api` → `127.0.0.1:8000`): список персонажей, карточка с bible,
сетка референсов, фильтры `status/view/pose`, лайтбокс, approve/reject, каталоги локаций
и предметов, состояния loading/empty/error, предупреждение «Без прозрачности».
Схема БД не менялась, миграций нет.
Проверки: `uv run pytest -q` → 67 passed; legacy `pytest` → 15 passed; `npm run build`
(`tsc --noEmit && vite build`) — успешно. Ручной сценарий в браузере: Guinness — 8 референсов,
фильтр «Спереди» → 2, комбинация с «Стоит» → пустое состояние, лайтбокс, approve →
статус «Утверждён» и счётчик «Утверждено 1»; Locations/Props — пустые каталоги; ошибок
консоли и ответов 4xx/5xx нет. После approve меняются только `status`/`approved_at`.

---

### WP-05. Шоты, композиция и стартовый кадр

**Объём:**

- API сцен/шотов (создание, список, карточка).
- API `shot_references` и ревизий `shot_compositions` (A4–A5): создание ревизии, правка
  только `draft`, approve ревизии, список ревизий.
- Backend-композитор: PNG из approved-слоёв, координаты/масштаб/поворот/z-order/opacity.
- Композитор обязан корректно работать с прозрачными PNG:
  - сохранять альфа-канал (`RGBA`), не заливать фон;
  - проверять наличие альфа-канала у каждого слоя (`RGBA` или `tRNS`);
  - возвращать предупреждение, если `character_reference` полностью непрозрачен;
  - не изменять и не перезаписывать исходные ассеты.
- `POST /api/shots/{id}/compositions/{revision}/render` → artifact предпросмотра
  (не утверждает кадр).
- `POST /api/shots/{id}/keyframe` → keyframe-попытка из выбранной ревизии;
  `POST /api/shots/{id}/attempts/{id}/promote-keyframe` → единственная запись
  `shots.start_keyframe_artifact_id` и `start_keyframe_attempt_id`.
- UI: карточка шота, список слоёв с порядком наложения, сохранение ревизии,
  предпросмотр, предупреждение о непрозрачном персонаже.

**Миграции:** нет, если ревизии и слои созданы в WP-02; иначе — одна миграция
`0005_composition_revisions` (только если состав S8 был утверждён позже).

**Зависит:** WP-04; утверждение A5 и S9.
**DoD:** сценарий 5–6 выполняется: создан шот, привязаны референсы Guinness и локации,
сохранена ревизия, получен PNG с сохранённой альфой, keyframe подтверждён; без
подтверждённого keyframe render отклоняется; повторный `compositions/{revision}/render`
не меняет `start_keyframe_artifact_id`; несколько ревизий на шот сосуществуют.
**Проверка:** тесты композитора — (1) два персонажа + одна локация: размеры, порядок
наложения, альфа-канал; (2) непрозрачный персонаж: предупреждение; (3) исходные файлы
не изменены; Pillow для PNG; API-тесты `render`/`keyframe`/`promote-keyframe`; тест
«render без keyframe → 4xx».
**Не делать:** тени, сегментация, pose-control, автоматический подбор поз,
автоматический approve композиции или кадра.

**Состояние:** выполнен 2026-10-26. Backend: `app/composer.py` (Pillow; RGBA-холст,
`scale` → `rotation` → `opacity`, клип по холсту, предупреждения
`opaque_character_reference`/`layer_without_alpha`, лимиты `composition_max_pixels`/
`composition_max_layers`); `app/api/shot_schemas.py`, `app/api/shots.py` (сцены, шоты,
`shot_references`, `keyframe`, `promote-keyframe`, render-гейт), `app/api/compositions.py`
(ревизии, правка только `draft`, render, approve, явный `supersede`),
`GET /api/projects/{id}/references` для пикера слоёв. В слой допускаются только
`approved` или `uploaded`; `POST /api/shots/{id}/keyframe` требует approved-ревизию с
предпросмотром; без подтверждённого стартового кадра `POST /api/shots/{id}/render`
отклоняется 409; с кадром создаётся `jobs(status='pending', kind='render_video')` без
lease/heartbeat (они в WP-06). UI: `#/shots` и `#/shots/{id}` — сцены и шоты, привязка
референсов, редактор слоёв (`z`, `x`, `y`, `scale`, `rotation`, `opacity`), предпросмотр
с предупреждениями, approve/supersede, keyframe → promote, постановка рендера.
Схема БД не менялась, миграций нет.
Проверки: `uv run pytest -q` → 81 passed; legacy `pytest` → 15 passed;
`uv run alembic check` — no new upgrade operations; `npm run build` — успешно. Ручной
сценарий в браузере: сцена → шот → привязка approved-референса → ревизия 512×768 →
render (PNG) → approve → keyframe → promote (стартовый кадр подтверждён) → повторный
рендер шота отклонён с `render_already_active`; ошибок консоли и 5xx нет.

---

### WP-05A. Visual Scene Plan

**Цель:** связать реальные изображения с ролями и действиями явным контрактом
(`plan → composition → attempt → artifact`), а не только автоматически составленным
текстовым prompt.

**Объём:**

- Версионируемый Visual Scene Plan на шот: canvas, camera, references с ролями и alias,
  `initial_state`, `action_beats`, `constraints`, `motion_prompt`, `needs_review`.
- Загрузка реальных референсов PNG/JPEG: `POST /api/projects/{id}/references` в
  существующий storage (content-addressed, SHA256, MIME и лимиты, проектная изоляция,
  дедупликация), статус `draft` → ручной `approve`; новый механизм хранения не создаётся.
- Генерация черновика плана через `gemma3:4b` (vision) как **советующий** источник +
  детерминированный fallback; результат всегда требует ручной проверки.
- Approve/supersede плана с неизменяемостью approved (S15-триггер).
- Детерминированная передача плана в существующий композитор (draft-ревизия,
  `shot_compositions.source_plan_id`), provenance в `render_attempts.parameters`.
- Пометка `layout mockup`, если непрозрачный персонаж закрывает фон; matting не входит.
- Экспорт layout 512×512 для LTX PoC с явным `crop`/`pad` без растяжения.
- UI: панель плана на странице шота, пикер референсов с обязательными входами,
  approve front-референса, история ревизий, экспорт.

**Миграции:** `0005_visual_scene_plans` — таблица `visual_scene_plans` (S19), частичный
уникальный индекс one-approved, триггер S15, nullable `shot_compositions.source_plan_id`
с FK и индексом. Обратима (`downgrade` удаляет FK, колонку, триггер, индексы и таблицу).

**Зависит:** WP-05; S19.
**DoD:** план создаётся/правится/утверждается; approved-план неизменяем; композиция из
плана сохраняет `source_plan_id`; keyframe-попытка фиксирует `visual_plan_revision`;
непрозрачные слои дают `layout mockup`; экспорт 512×512 не растягивает изображение;
vision-сбой не блокирует ручной путь.
**Проверка:** backend-тесты (схема, иммутабельность, API, planner, композиция из плана,
экспорт), legacy 15 тестов, `alembic check`, `npm run build`, браузерный сценарий
«2 персонажа + локация».
**Не делать:** запуск LTX/видео, очередь и worker, matting/segmentation, автоматический
approve плана/композиции/кадра.

**Состояние:** выполнен 2026-10-26. Backend: миграция `0005_visual_scene_plans`;
`app/planner.py` (skeleton, vision-анализ, нормализация, `source ∈ manual|llm|fallback`);
`app/api/scene_plans.py` (list/create/get/put/generate/approve/supersede/composition,
детерминированная раскладка слоёв); `POST /api/projects/{id}/references`;
`app/api/shot_schemas.py` — `ReferenceOut` с владельцами ассета. Композитор помечает
результат `is_layout_mockup` (`layer_without_alpha`, `opaque_character_reference`).
Экспорт layout: 512×512, `crop` или `pad`. UI: `ScenePlanPanel.tsx`, `ScenePlanEditor.tsx`,
`ReferencePicker.tsx`, изменения `ShotDetailPage.tsx`, `CompositionPreview.tsx`,
`types.ts`, `styles.css`.
Проверки: `uv run pytest -q` → 123 passed; legacy → 15 passed;
`uv run alembic check` — no new upgrade operations; `npm run build` — успешно.
Приёмка «2 персонажа + локация» выполнена на изолированной БД/сторадже и тестовых
ассетах с явной маркировкой: upload → relabel `view=front` → ручной approve → generate
(vision: `source=llm`, `needs_review=true`, предупреждения об alias) → план rev1 →
approve → композиция 768×512 из 3 слоёв → render (`layout_mockup`) → экспорт 512
`crop`/`pad` → keyframe → promote (`visual_plan_revision=1`). Браузерный сценарий
проверен на пустом и заполненном состояниях; временная инфраструктура удалена.
**Открыто:** в основной БД нет реального изображения локации и approved front-референсов
Guinness/Marija; `gemma3:4b` не распознаёт alias и остаётся советующим источником.

---

### WP-05B. Multi-reference video PoC

**Цель:** проверить на реальном LTX, что даёт keyframe, собранный из нескольких
референсов, и зафиксировать ограничения до автоматизации.

**Объём:**

- Взять утверждённый `layout mockup` и его экспорт 512×512, выполнить один I2V-прогон
  по API-workflow WP-00A (без очереди и worker).
- Зафиксировать параметры (seed, кадры, fps, разрешение, модель) и сохранить MP4 как
  артефакт вручную.
- Сравнить: один персонаж vs два персонажа + локация; влияние непрозрачных слоёв.
- Сформулировать вывод: пригоден ли layout как стартовый кадр, нужен ли matting,
  какой canvas/экспорт выбирать.

**Миграции:** нет.
**Зависит:** WP-05A; реальные approved-референсы и изображение локации.
**DoD:** один MP4 получен и просмотрен; параметры и выводы зафиксированы; решение о
matting/изменении canvas оформлено предложением.
**Проверка:** `ffprobe` результата; визуальный просмотр; запись параметров.
**Не делать:** очередь, worker, автоматизацию, тяжёлые серии прогонов.

**Состояние:** не начат.

---

### WP-06. Очередь и FakeWorker

**Объём:**

- Таблица `events` (журнал job/attempt событий) — единственная новая таблица пакета;
  `jobs`, `render_attempts`, `artifacts`, `workers` уже созданы в WP-01.
- State machine с lease, heartbeat, retry, recovery; история попыток.
- Worker token, claim/heartbeat/complete/artifacts/resume.
- FakeWorker: получает job, генерирует валидный MP4 через ffmpeg, загружает artifact.
- Проверка MP4 (контейнер, длительность, наличие видеопотока).
- Идемпотентность render по `Idempotency-Key`.

**Миграции:** `0006_events` — таблица `events` и индексы; при необходимости
`0007_queue_constraints` — частичный уникальный индекс активного job и CHECK статусов.

**Зависит:** WP-01; может идти параллельно WP-02–WP-05.
**DoD:** два воркера не берут один job; kill -9 → recovery; повторный claim после
истечения lease; MP4 скачивается по artifact API; все попытки сохранены.
**Проверка:** `pytest backend/tests/test_queue.py`, `pytest worker/tests`,
`ffprobe` на результате FakeWorker.
**Не делать:** реальный ComfyUI.

**Состояние:** выполнен 2026-10-26. Backend: миграция `0006_events` (таблица `events`:
`sequence`, CHECK `event`/`progress`/`target`, частичный уникальный индекс
`uq_events_job_sequence`); `app/api/worker.py` — `claim` (`FOR UPDATE SKIP LOCKED`,
порядок priority/created_at, гонка двух воркеров), `heartbeat` (`leased → running`,
продление lease), `artifacts` (sha256 + структурная проверка MP4), `complete`,
`fail` (`retry_wait` с backoff или `failed`), `resume`; токен обязателен
(`Authorization: Bearer` или `X-Worker-Token`, иначе 401; пустой токен — 503);
просроченный lease переводится в `lease_expired` без автоперезапуска. `app/api/jobs.py`
— `GET /api/jobs`, `GET /api/jobs/{id}`. `app/video_probe.py` — разбор ISO BMFF
(`ftyp`, `moov`, `mvhd`, `hdlr`) без внешних зависимостей. `queue_render` принимает
`Idempotency-Key`: повтор возвращает тот же job, чужой шот — 409. `worker/fake_worker.py`
— stdlib-клиент протокола и ffmpeg (libx264, yuv420p, `+faststart`), флаги `--once`,
`--poll`, `--delay`, `--fail`, `--crash-after-claim`.
Проверки: `uv run pytest -q` → 137 passed (включая `tests/test_queue.py` и
`tests/test_fake_worker.py`); legacy → 15 passed; `alembic check` — no new upgrade
operations; `npm run build` — успешно; `ffprobe` на MP4 FakeWorker — валидный
h264-файл заданной длительности.
**Открыто:** SSE, публичный API рендера и отмена — WP-07; реальный ComfyUI/LTX — WP-08.

---

### WP-04A. Locations & Props Library Completion + аудит кода

Расширение WP-04: полноценная работа с локациями и предметами через веб-интерфейс
плюс обязательный аудит дублирования в затронутых модулях.

**Объём:**

- Backend: единый `app/api/library.py` для локаций и предметов (реестр
  `_LibraryKind`: модель, поле-владелец референса, label), общий
  `deps.require_project`, единые схемы `LibraryEntitySummary/Detail/Create/Update`.
- Загрузка изображений, SHA256/dedup, MIME/размер и approve/reject переиспользуются:
  `POST /api/projects/{id}/references`, `PATCH /api/reference-assets/{id}`,
  `POST .../approve|reject`. Новых таблиц и хранилищ нет.
- «Основной референс» = `reference_assets.role = 'primary'`; уникальность среди
  mutable-референсов владельца обеспечивает `_clear_other_primary` при PATCH.
- Frontend: `pages/LibraryPages.tsx` (параметризованные `LibraryListPage` и
  `LibraryDetailPage`), `hooks/useReferenceReview.ts`, `libraryApi` в `api/client.ts`,
  роуты `#/locations/{id}` и `#/props/{id}`, галерея через `ReferenceCard`,
  лайтбокс, выбор основного, предупреждение об отсутствии альфы у предмета.

**Миграции:** нет (используются существующие `locations`, `props`, `reference_assets`).

**Зависит:** WP-04, WP-05A.

**Состояние:** выполнен 2026-10-26. Удалены модули-близнецы `api/locations.py` и
`api/props.py`, `pages/LocationsPage.tsx`, `pages/PropsPage.tsx` и pass-through
`components/ReferenceGrid.tsx`. `api/reference_assets.py` получил правило единственного
основного референса (утверждённые строки не изменяются — S15). `ReferencePicker`
переведён на `ReferenceCard` и `libraryApi`, дубли карточек и `describe()` удалены.
Проверки: `uv run pytest -q` → 143 passed; legacy → 15 passed; `alembic check` —
no new upgrade operations; `npm run build` — успешно. Ручной сценарий в браузере:
создание локации и предмета из UI, галерея и лайтбокс, approve/reject, перенос
основного референса (ровно один бейдж), предупреждение об отсутствии альфа-канала
у предмета, зелёный статус локации в ReferencePicker шота, отсутствие регрессий
в библиотеке персонажей.

**Открыто:** загрузка файлов через браузерный файловый диалог не автоматизирована
(проверена на уровне API и backend-тестов); после approve основной референс
закрепляется навсегда — для смены нужна колонка primary на уровне владельца или
ослабление S15-триггера; у локаций/предметов нет DELETE/архивации.

---

### WP-07. Public API рендера, SSE и отмена

**Объём:**

- `POST /api/shots/{id}/render`, `POST /api/shots/{id}/cancel`.
- API истории попыток, approve/reject, promote-keyframe.
- SSE `/api/events` с job/attempt событиями.
- Формат ошибок, пагинация, права.

**Миграции:** нет.

**Зависит:** WP-06, WP-05.
**DoD:** постановка в очередь → SSE-события → терминальный статус; cancel отменяет
невыполненный job; повторный render не создаёт дубль при том же idempotency key.
**Проверка:** API-тесты; SSE-тест; ручная проверка через `curl`.

---

### WP-08. Реальный Mac Worker и LTX I2V

**Объём:**

- Использовать API-workflow, проверенный в WP-00A (`ltx23_mlx_q4_i2v.api.json`);
  при изменении параметров обновлять только `*.meta.json`, не ломая существующий файл.
- Handler `comfyui_i2v`: upload keyframe, submit, poll `prompt_id`, download, upload artifact.
- Resource lock: один тяжёлый job; проверка памяти; unload между job.
- Отмена через ComfyUI; resume после потери соединения; логи и ошибки.
- Селектор workflow по версии; сохранение workflow version и параметров.
- Типизированные ревизии промптов: `prompt_type='keyframe'` и `prompt_type='motion'`
  (после утверждения S10); попытка сохраняет обе ревизии в `parameters_json`.

**Миграции:** нет, если S10 утверждён на этапе WP-01; иначе — `0008_prompt_types`.

**Зависит:** WP-00A (проверенный API-workflow), WP-05, WP-06, WP-07; Mac с запущенным
ComfyUI; утверждение S9–S10.
**DoD:** 3–5 реальных I2V-роликов; seed/параметры/workflow version сохранены;
предыдущие артефакты не перезаписаны; OOM/потеря соединения не ломают очередь;
латентность и память зафиксированы.
**Проверка:** реальный рендер на Mac; `ffprobe`; журнал попыток; ручной restart worker.
**Не делать:** замена LTX на Wan без PoC и согласования.

---

### WP-09. Вертикальный срез Guinness

**Объём:** сквозной сценарий 1–9 на реальном стеке.

**Миграции:** нет.

**Зависит:** WP-04, WP-05, WP-07, WP-08, WP-10 (минимум review).
**DoD:** из UI: Guinness → approved ref → shot → keyframe → очередь → реальный MP4 →
просмотр → approve. В БД одна цепочка `Shot → Job → RenderAttempt → Artifact`,
нет второго источника статусов.
**Проверка:** демонстрация; SQL-проверка связей; `ffprobe`; повторный прогон с новым seed
создаёт новую попытку, старую не меняет.

---

### WP-10. Review UI

**Объём:**

- Список попыток шота, плеер, метаданные (seed, workflow version, параметры).
- Approve/reject, сравнение версий, переход к очереди.
- Прогресс job через SSE.

**Миграции:** нет.

**Зависит:** WP-07.
**DoD:** сценарий 9 выполняется; approve фиксирует `approved_attempt_id`; reject не
удаляет артефакт; UI показывает историю.
**Проверка:** UI-тест/ручная проверка; API-тесты approve/reject.

---

### WP-11. Надёжность и эксплуатация

**Объём:**

- Бэкап и восстановление PostgreSQL.
- Политика хранения артефактов и очистка `cancelled` (без удаления approved).
- Мониторинг worker: heartbeat, диск, память.
- Rate limit/токены, запрет внешнего доступа к ComfyUI/Ollama.

**Миграции:** нет (политики и настройки, не схема).

**Зависит:** WP-08, WP-09.
**DoD:** восстановление из бэкапа на чистой БД; политика хранения задокументирована;
worker не доступен из внешней сети.
**Проверка:** тест восстановления; проверка `ss`/`lsof`; чек-лист.

---

### WP-N1. Импорт серии «Ночной тыгыдык» и preflight (выполнен 2026-10-28)

**Объём:**

- `backend/app/series_manifest.py` — разбор и валидация `Nine_Lives_Band_Render_Manifest.json`,
  сверка с CSV-очередью, `snap8k1` для числа кадров.
- `backend/app/series_import.py` + CLI `python -m app.import_series --dry-run|--apply` —
  идемпотентный импорт в Project/Episode/Scene/Shot/PromptRevision/ShotReference,
  provenance в `prompt_revisions.parameters_json`.
- `backend/app/preflight.py` + CLI `python -m app.preflight` — отчёт готовности без записи.
- `backend/app/api/series.py` — `POST /api/projects/{id}/series/import`,
  `POST /api/projects/{id}/series/preflight` (см. `docs/DECISIONS.md` §4.2).

**Миграции:** нет.
**Зависит:** WP-04A, WP-06.
**DoD:** повторный импорт даёт 0 новых строк; preflight перечисляет блокировки без
фиктивных подстановок.
**Проверка:** `pytest` — 159 passed; `alembic check` — no new operations; реальный прогон:
30 шотов импортированы дважды без дублей, 5 из 7 референсов разрешены,
`Guiness_clean.png` и `wide_cinematic_concert_stage_scene_a_realistic.png` отсутствуют,
7 сюжетных шотов без стартовых кадров.

---

### WP-N2. Адаптер LTX-2.3 MLX I2V (выполнен 2026-10-28)

**Объём:**

- `pipeline/comfyui/ltx_adapter.py` — чистые функции без сети и БД: поиск нод по
  `class_type`, `snap_frames` (8k+1), `resolve_size` (9:16 → 1080×1920), уникальный
  `filename_prefix` вида `nlb/<shot_key>/<attempt_id>`, `bind_workflow`, `describe`,
  `workflow_version` (sha256 канонического шаблона).
- `tests/test_ltx_adapter.py` — 12 тестов на реальном `ltx23_mlx_q4_i2v.api.json`.

**Миграции:** нет.
**Зависит:** WP-00A, WP-N1.
**DoD:** адаптер подставляет кадр, prompt, seed, параметры видео и уникальный префикс;
шаблон не мутируется; отсутствие нод/входов — ошибка `BindingError`.
**Проверка:** `pytest tests/test_ltx_adapter.py` — 12 passed.
**Не подтверждено:** реальная совместимость 1080×1920 / 193 кадра проверяется только
рендером; ответ `object_info` живого ComfyUI в этом пакете не снимался (сервис не запущен).

### WP-N3. Реальный LTX-воркер (выполнен 2026-10-28)

**Объём:**

- `worker/client.py` — общий HTTP-клиент worker-протокола (`WorkerClient`, `ClaimedJob`,
  `WorkerError`) и `probe_duration`, перенесённые из `worker/fake_worker.py` без изменения
  поведения; fake-воркер импортирует их оттуда.
- `worker/ltx_worker.py` — одна тяжёлая job за раз: скачивание стартового кадра с проверкой
  sha256 → сборка payload через `ltx_adapter` → `/upload/image` → `/prompt` →
  heartbeat на каждом опросе `/history` → `/view` → `ffprobe` → artifact → `complete`
  с `workflow_version`, `model_hash`, `seed`.
- `POST /api/worker/claim` теперь отдаёт `inputs.prompt` и `inputs.shot_key` из последней
  motion-ревизии шота (соответствие `docs/ARCHITECTURE.md` §5.2). Схема БД не менялась.
- `pipeline/comfyui/client.py`: у `wait_for_prompt` появились `on_poll` и `timeout`.
- `tests/test_ltx_worker.py` — 12 тестов; `backend/tests/test_queue.py` — новый тест
  на `inputs.prompt`/`shot_key`.

**Миграции:** нет.
**Зависит:** WP-06, WP-N1, WP-N2.
**DoD:** воркер не пишет в БД напрямую; отсутствие кадра/промпта/8k+1 — явные коды ошибок;
lease не истекает во время рендера; загруженный MP4 проверяется ffprobe до отправки.
**Проверка:** `pytest tests/test_ltx_worker.py` — 12 passed; backend `pytest` — 163 passed.
**Не подтверждено:** реальный прогон в ComfyUI (сервис не запускался), совместимость
1080×1920/193 кадра, отмена рендера при потере lease (в WP-N3 не реализована).

### WP-N4. Управляемый прогон серии (выполнен 2026-10-28)

**Объём:**

- Миграция `0007_render_series`: `series_runs` (`draft/running/paused/stopping/completed/
  cancelled/failed`, `stop_on_error`, `total_items`, `started_at/finished_at`) и
  `series_items` (`order`, `status`, `job_id`, `error_code`); `uq_series_items_run_order`,
  `uq_series_items_run_shot`, CHECK на статусы и `"order" >= 1`.
- `backend/app/api/series_runs.py` — создание/список прогонов, `start/pause/resume/
  stop-after-current/cancel`, `GET /api/series/{run_id}` с `counts` и прогрессом job,
  воркерский `POST /api/worker/series/next` (закрывает текущий item, создаёт ровно одну
  job на следующий готовый шот, останавливается по `stop_on_error`).
- `backend/app/notify.py` — best-effort баннер macOS (`osascript`, `MARY_DISABLE_NOTIFY=1`).
- `worker/client.py` — `series_next`; `worker/ltx_worker.py` — `--series-run <id>` /
  `--series`: цикл `series/next` → `claim` → одна тяжёлая job.
- UI — страница `#/series/{id}` (прогресс, список шотов, управление, polling 3 с) и панель
  «Прогон серии» на `#/shots` (создание с `shot_orders` и `stop_on_error`).
- `backend/tests/test_series_runs.py` — 14 тестов; `tests/test_ltx_worker.py` — +4 теста
  цикла серии; `backend/tests/test_schema.py` — новые таблицы в ожидаемом наборе.

**Миграции:** `0007_render_series` (применена, `alembic check` — no new operations).
**Зависит:** WP-06, WP-N1, WP-N3.
**DoD:** `enum Shot.status` и `Event`-имена не расширялись; одна активная render-job на шот
сохраняется; повторный `series/next` не создаёт вторую job; пауза/остановка не теряют
текущий item; блокировки выводятся из данных.
**Проверка:** backend `pytest` — 177 passed; `pytest tests/test_ltx_worker.py` — 16 passed;
`uv run python -m pytest tests` (корень) — 43 passed; UI `npm run build`.
**Не подтверждено:** реальный прогон серии в ComfyUI (сервис не запускался); отмена
текущего рендера в ComfyUI; баннер macOS проверяется только вручную [ПРОВЕРИТЬ].

**Следующие пакеты серии:**

| Пакет | Содержание |
|---|---|
| WP-N5 | approve/reject попытки + чек-лист ручного QC |

**Ворота:** 1 калибровочный рендер → 2 тестовых шота → серия из 30 только по отдельному
разрешению человека. Merge/push — также по отдельному разрешению.

### Калибровка 2026-10-28 (NLB-01)

**Попытка 1 — 1080×1920, остановлена по ресурсам.** Прогон `series_run 13c86ba0…` →
`ltx_worker --series-run`:

- сквозной путь сработал: `start` → `series/next` → `claim` → upload кадра → `/prompt` →
  heartbeat 0.2…0.9 → рендер в ComfyUI; при ошибке прогон корректно ушёл в `paused`
  (`reason: job_failed`), item — `failed`.
- кадр `01_vocalist_clean.png` (768×820) прошёл как стартовый через
  `POST /api/shots/{id}/keyframe` + `promote-keyframe`, без генерации изображения.
- 193 кадра / 24 fps / `dgrauet/ltx-2.3-mlx-q4` приняты воркером и ComfyUI без ошибок
  валидации.

**Блокер (почему остановлено):**

1. Two-stage half-res снапит стороны до кратных 64: запрошенные 1080×1920 фактически
   рендерятся как **1024×1920** (8:15, не 9:16). Лог ComfyUI:
   `output will be 1024x1920 (requested 1080x1920). Use --single-stage for exact dims.`
2. Stage 1 (half-res, 12000 токенов): 8 шагов ≈ 22 мин (168 с/шаг). Stage 2
   (48000 токенов) не завершил ни одного шага за 24 мин; swap вырос до 36.5 из 37.9 ГБ
   на 16 ГБ RAM → thrash. ComfyUI перезапущен, очередь пуста, память освобождена.

**Попытка 2 — 576×1024, выполнена.** Прогон `series_run 5f6c5705…` (один шот, `stop_on_error`),
`ltx_worker --series-run --once --long-side 1024`:

- job `7735aa39…` → attempt `53878f4a…` → artifact `9cd53803…`
  (sha256 `32ba9936…`, 1 778 621 байт, `blobs/32/32ba9936…mp4`);
- `ffprobe`: h264, **576×1024**, `24/1`, 193 кадра, 8.04 с — параметры совпадают с
  запрошенными; два кратных 64 размера, снап не сработал;
- ComfyUI: stage 1 — 3600 видео + 201 аудио токенов, 8 шагов за 7:07 (≈53 с/шаг);
  stage 2 — 14400 видео токенов, 3 шага: первый 4:39, далее ≈197 с/шаг; полный рендер
  ≈ 18 мин. Swap пик 18.5 из 19.4 ГБ (файл подкачки вырос), thrash не возник;
  после рендера swap 8.4 из 9.2 ГБ;
- прогон закрыт `series/next` → `completed` (1 completed, 0 failed, 0 skipped).

**Решение:** серия рендерится в **576×1024** (`--long-side 1024`), см. `docs/DECISIONS.md`
§4.5. Апскейл до 1080×1920 на сборке не реализован.

**Не проверено:** качество I2V (нужен просмотр человеком), поведение `--single-stage`,
апскейл на сборке.

**Следующий шаг:** 2 тестовых шота (отдельный прогон) после приёмки качества калибровки;
серия из 30 — только по отдельному разрешению.

### Тестовые шоты NLB-02 и NLB-03 (2026-10-28, выполнены)

- Стартовые кадры: `POST /api/shots/{id}/keyframe` из уже утверждённого референса
  `01_vocalist_clean.png` (`fdd8d183…`, по манифесту это кадр для NLB-02/03) →
  `promote-keyframe` (attempt `4aeffaed…` и `d7fbc9ca…`). Новых approve не потребовалось.
- Прогон `series_run 7b0750a4…` (`shot_orders: [2, 3]`, `stop_on_error`),
  `ltx_worker --series-run --long-side 1024` без `--once`: воркер сам закрыл item 1,
  взял item 2 и завершил прогон (`completed`, 2 completed, 0 failed).
- Артефакты: NLB-02 — attempt `9e124b8c…` / artifact `abb45f74…` (1 691 054 байта);
  NLB-03 — attempt `f73650c5…` / artifact `cbc1f01d…` (1 755 673 байта).
  `ffprobe` для обоих: h264, 576×1024, `24/1`, 193 кадра, 8.04 с.
- Время: ~19 мин на шот (stage 1 ≈ 7 мин, stage 2 ≈ 11 мин); очередь ComfyUI пуста,
  swap после прогона 7.6 из 9.2 ГБ.
- Наблюдение: `Shot.status` остаётся `prompt_ready` после успешного рендера —
  видео-попытка не меняет статус шота, пока её не утвердят
  (`approved_attempt_id` пуст). Это ожидаемо для текущей модели, но означает, что
  «готово к монтажу» выводится из наличия `completed` видео-попытки, а не из статуса.

### Тестовый шот NLB-31 — танец и реплика (2026-10-28, выполнен)

Запрос человека: проверить не медленное раскрытие пасти, а танцевальное па и живую
мимику с репликой «Meanwhile I am unstoppable? But actually unstable.».

- Шот создан в существующей сцене: `POST /api/scenes/{scene_id}/shots`
  (`sequence_no=31`, 193 кадра, 24 fps), id `815ff3fb…`. Motion-ревизия v1 вставлена
  напрямую через модели: эндпоинта создания prompt-ревизий нет, ревизии пишет только
  импорт. Миграций и изменений API-контрактов не было.
  `parameters_json = {shot_key: NLB-31, reference_filename: 01_vocalist_clean.png,
  source: manual_dance_test_2026-10-28}`.
- Промпт: `Rock vocalist, sable Burmese cat in a studded leather jacket; performs an
  energetic dance move: rhythmic shoulder sway and hip bounce, head bobbing on the beat,
  free paw punching the air while the other paw holds the chrome microphone; lively
  expressive face with quick jaw, whisker and ear movement, mouthing the line "Meanwhile I
  am unstoppable? But actually unstable."; red stage lighting, moving light beams; stable
  medium shot, one continuous shot. Preserve the exact reference identity, costume,
  instrument and stage. Photorealistic, continuous motion, no captions, no morphing,
  no extra paws.`
- Стартовый кадр — approved `01_vocalist_clean.png` (`fdd8d183…`) →
  `keyframe` (attempt `a40b53db…`) → `promote-keyframe`; на шот добавлена
  `shot_reference` (`purpose=character`).
- Прогон `series_run b84a6983…` (один шот), `ltx_worker --series-run --once --long-side 1024`:
  job `be9cb599…` → attempt `2136447d…` → artifact `19fb5662…`
  (sha256 `46a2fd21…`, 3 481 956 байт). `ffprobe`: h264, 576×1024, `24/1`, 193 кадра,
  8.04 с; прогон закрыт `series/next` → `completed`.
- Ограничение: широкого кадра сцены в проекте нет (единственный approved-референс —
  крупный план), поэтому танцевальное движение читается только в верхней части корпуса.
  Аудио: LTX генерирует дорожку — `ffprobe` показывает второй поток `aac`, 48 kHz, stereo,
  8.01 с у всех четырёх роликов (NLB-01/02/03/31); у NLB-31 `volumedetect` mean −21.7 dB,
  max −5.3 dB. Наличие внятной речи и совпадение артикуляции с текстом реплики
  **[ПРОВЕРИТЬ]** прослушиванием.
- **Отклонение:** `python -m app.preflight` теперь даёт
  `[WARN] shots: в сцене 31 шотов при 30 в манифесте`; остальные проверки без изменений
  (`prompts` — OK, референсы/кадры — как раньше). Серия 30 рендерится по явным
  `shot_orders`, тестовый шот в неё не попадает.

### WP-08 — имя прогона и подготовка серии «NLB-single» (2026-10-28, выполнен)

- Миграция `0008_series_run_title`: `series_runs.title TEXT NULL` (`ADD COLUMN`),
  downgrade удаляет колонку. `alembic check` — no new operations.
- API: `SeriesRunCreate.title` (1…200 символов), `title` в ответе создания, в списке
  прогонов и в детали. UI: поле «Название прогона» на `#/shots`, заголовок `#/series/{id}`
  и подпись в списке прогонов. Тест `test_run_title_is_stored_and_returned`.
- Подготовка серии (решение человека: референсы и стартовые кадры утверждает агент):
  пять референсов переведены в `approved` — `02_guitarist_clean.png`, `03_drummer_clean.png`,
  `04_bassist_clean.png`, `05_keyboardist_clean.png`, `Guiness_clean.png` (лист породы).
  Стартовые кадры 4–27 созданы по референсу своего шота (`keyframe` +
  `promote-keyframe`, по одному attempt на шот) — 24 шота.
- Готовность по данным после подготовки: `READY 28 [1…27, 31]`,
  `BLOCKED 3 (missing_start_frame) [28, 29, 30]` — референса
  `wide_cinematic_concert_stage_scene_a_realistic.png` в проекте нет; человек пришлёт файл.
- Создан прогон **«NLB-single»** (`85e04a00-202a-44f2-ac0f-1fab86d37b43`), `draft`,
  24 item (шоты 4–27), `stop_on_error=true`. В него не включены: 1–3 (видео уже принято
  человеком) и 31 (тестовый шот); 28–30 — после появления референса.
- Оценка времени: 24 × ~19–22 мин ≈ 7.5–9 ч непрерывного рендера в 576×1024.
- Прогон выполнен: старт 2026-10-28 17:45:58, финиш 2026-10-29 00:51:02 (7 ч 05 мин),
  `completed 24 / failed 0 / skipped 0`, воркер вышел сам после `completed`. Средний темп
  17.7 мин/шот (первый шот 19.1 мин, дальше 17.1–19.3). Все 24 MP4 проверены `ffprobe`:
  h264, 576×1024, 24/1, 193 кадра, 8.041667 с, аудио `aac` — отклонений нет.
  Суммарный объём 61.6 МБ. Артефакты NLB-04…27 (`c6fde69f…`…`8fa55b3a…`), `Shot.status`
  остаётся `prompt_ready` до утверждения попытки (утверждение — WP-N5).
- Широкий референс получен (2026-10-29): `docs/cats/Feline Rock Band Under Neon Lights.png`
  (1536×1024, sha256 `a64e8ba1…`) — это и есть
  `wide_cinematic_concert_stage_scene_a_realistic.png`. Загружен через
  `POST /api/projects/{id}/references?kind=uploaded` → asset `e7af9bb1…`; в `metadata_json`
  добавлено `original_name` = имя из манифеста (иначе `preflight` не сопоставляет имя: при
  upload API имя файла не сохраняется). Человек разрешил approve агенту — asset переведён в
  `approved` через `POST /api/reference-assets/{id}/approve`.
- Стартовые кадры 28–30 созданы по этому референсу (`keyframe` + `promote-keyframe`,
  attempts `fbc1d956…`, `5b9b594a…`, `004f6607…`); ссылка на референс добавлена в каждый шот
  (`purpose=location`). Preflight после этого: `references` — OK (7 из 7 approved),
  `start_frames` — 30 из 30.
- Решение по аспекту (человек, 2026-10-29): общие планы 28–30 рендерятся в 16:9
  (1024×576), а не 9:16 — зафиксировано в `docs/DECISIONS.md` §4.5 п.5.
- Создан прогон **«NLB-single wide (28-30)»** (`ce0c1bfa-c61c-434d-a0fa-47d95861c44e`),
  3 item (шоты 28, 29, 30), `stop_on_error=true`, запущен воркером
  `--aspect-ratio 16:9 --long-side 1024`. В очереди ComfyUI подтверждено `1024 x 576, 193, 24.0`.
  Ожидаемое время ≈ 55–65 мин.

---

## 3. Граф зависимостей

```text
WP-00
 ├─ WP-00B ── WP-00C
 │     │
 │   WP-01 ──────────────┐
 │     │                 │
 │   WP-02               WP-06
 │     │                 │
 │   WP-03               WP-07
 │     │                 │   \
 │   WP-04               │    WP-10
 │     │                 │
 │   WP-05 ──────────────┘
 │     │
 │   WP-08  (также требует WP-00A)
 │     │
 │   WP-09
 │     │
 │   WP-11
 │
 └─ WP-00A  (не блокирует WP-01; требует Mac и разрешения на прогон)
```

Пояснения:

- WP-00B (git) и WP-00C (тест) — отдельные контролируемые пакеты, а не «попутные» правки
  внутри WP-01. Без git нельзя изолировать изменения; без зелёного теста нельзя отличить
  новую поломку от старой.
- WP-00A не блокирует backend и может выполняться параллельно WP-01–WP-05, но обязателен
  до WP-08.
- WP-06 может идти параллельно WP-02–WP-05, если утверждены модели очереди.
- WP-02 не начинается, пока WP-01 не создал `projects`, `scenes`, `shots`, `artifacts`,
  `reference_assets`.
- WP-08 нельзя начинать без результата WP-00A и реального Mac.
- WP-09 — единственный пакет, где встречаются все компоненты.

---

## 4. Маппинг на VIDEO-ORCHESTRATOR v1.3

| Roadmap | v1.3 |
|---|---|
| WP-00 | WP-00 |
| WP-00A | §7.1 (PoC кандидатов модели) — только проверка API, без интеграции |
| WP-00B | вне v1.3 — инфраструктура репозитория |
| WP-00C | вне v1.3 — тестовая база |
| WP-01 | B1 |
| WP-02 | B2 (часть схемы) + S1–S9 (+ S11, S12 после утверждения) |
| WP-03 | B3 |
| WP-04 | U1 (часть) + P2 — расширение MVP: библиотека |
| WP-05 | расширение MVP: композиция и стартовый кадр (A5, S9) |
| WP-06 | B2/B4/B5 |
| WP-07 | B6/B7 |
| WP-08 | A2–A4, I1 |
| WP-09 | I2/I3 |
| WP-10 | U1 |
| WP-11 | U2 |

---

## 5. Правила выполнения

1. Каждый WP начинается только после подтверждения предыдущего и утверждения
   затрагиваемых изменений схемы/API.
2. Не менять публичные контракты без отдельного решения.
3. Не запускать тяжёлый рендер на этапах WP-00–WP-07; WP-00A — единственное исключение
   и только по явному разрешению.
4. Не скачивать модели и не обновлять ComfyUI/custom nodes без разрешения.
5. `.env` не читать, не выводить, не коммитить.
6. Существующие тесты сохраняются; красный тест `test_character_refs_stage_reports_missing`
   исправляется только в WP-00C.
7. Git инициализируется только в WP-00B; до этого ветки и коммиты невозможны.
8. Существующие файлы и каталоги (`characters/`, `episodes/`, `comfyui-workflows/`,
   `prompts/`, `pipeline/`, `tests/`) не перемещаются и не удаляются ни в одном пакете.
9. Пакет не ссылается на таблицы, колонки и эндпоинты, которых нет в нём или в уже
   принятых пакетах; список миграций пакета обязателен.
10. После каждого пакета — отчёт по формату задания и остановка.

---

## 6. Кандидаты в следующий пакет после утверждения

Рекомендуемый порядок запуска: **WP-00 → WP-00B → WP-00C → WP-00A → WP-01**.
WP-00A может идти параллельно WP-01–WP-05 при доступном Mac; WP-08 без него не начинается.

**WP-00. Архитектурный baseline** — только документы, без кода.

Критерии приёмки:

- `docs/ARCHITECTURE.md` — копия v1.3;
- `docs/DECISIONS.md` — ответы на открытые вопросы (включая S10, S11, S12);
- `docs/ENV-AUDIT.md` — фактическое окружение;
- `AGENTS.md` — правила для backend/ui/worker;
- ссылки валидны; секретов нет; код не изменён.

**Следом (после приёмки WP-00):** WP-00B (git), затем WP-00C (тест). Ни один из них
не начинается автоматически.
