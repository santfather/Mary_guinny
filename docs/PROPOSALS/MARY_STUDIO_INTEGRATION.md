# Mary Studio — предложение по интеграции

> **Статус:** архитектура предварительно одобрена как основа проекта. Документ уточнён
> перед WP-00: S1–S9, A1–A4, A6 приняты в проект архитектуры с уточнениями; S10 и A5
> переработаны; предложены S11 (Episode) и S12 (nullable-связи артефактов).
> P1–P4 зафиксированы как рекомендации к утверждению.
> Это **не** разрешение на миграции, изменение API, создание сервисов или запуск WP-00.
> **Дата:** 2026-10-26, редакция с уточнениями.
> **Основание:** задание «развитие Mary_Guiness в Mary Studio», `README.md`, `scenario.md`,
> `VIDEO-ORCHESTRATOR.md` v1.3 (§4, §5, §7, §14), фактический код репозитория.
> **Обозначения:** **[ФАКТ]** — проверено по коду/команде; **[ПРЕДЛОЖЕНИЕ]** — рекомендация;
> **[ПРИНЯТО В АРХИТЕКТУРУ]** — согласовано как проектное решение, но не как разрешение
> на реализацию; **[ТРЕБУЕТ УТВЕРЖДЕНИЯ]** — меняет схему БД, API или контракт v1.3;
> **[ПРОВЕРИТЬ]** — нельзя подтвердить без Mac/ComfyUI/эксперимента.

---

## 1. Текущая архитектура

### 1.1. Что есть сейчас

**[ФАКТ]** Проект — файловый Python-пайплайн без БД, API и очереди.

```text
main.py (argparse)
   |
   v
Orchestrator (pipeline/orchestrator.py)
   |
   +-- CharacterRefsStage  -> проверка characters/*/*.png + bible
   +-- ScriptStage         -> Ollama /api/generate -> episodes/<id>/script.txt
   +-- SceneDraftStage     -> ComfyUI keyframe -> ffmpeg -> scenes/*_draft.mp4
   +-- FinalVideoStage     -> подготовка Grok-промптов, файлов не создаёт
   +-- VoicesStage         -> проверка наличия mp3
   +-- LipsyncStage        -> проверка наличия *_lipsync.mp4
   +-- MusicStage          -> проверка bg_music.mp3
   +-- AssemblyStage       -> проверка комплекта клипов
```

Компоненты:

| Компонент | Файлы | Фактическая роль |
|---|---|---|
| CLI | `main.py` | `init`, `run`, `status`, `stages`, `comfy …` |
| Модели этапов | `pipeline/models.py` | `PipelineStage`, `PipelinePhase`, `Scene`, `StageResult`, `EpisodeContext` |
| Оркестратор | `pipeline/orchestrator.py` | последовательный запуск этапов в памяти |
| Настройки | `pipeline/config.py` | `.env` → `Settings`, пути, персонажи, позы |
| Утилиты | `pipeline/utils.py` | парсинг `СЦЕНА N`, reading bible, промпты |
| ComfyUI-клиент | `pipeline/comfyui/client.py` | HTTP API: `/prompt`, `/history/{id}`, `/view`, `/upload/image` |
| Workflow-хелперы | `pipeline/comfyui/workflows.py` | рендер `{{VAR}}` в API-JSON, выбор шаблона |
| Референсы | `pipeline/comfyui/generator.py` | генерация 7 поз, проверка окружения |
| Черновик сцены | `pipeline/comfyui/scene_draft.py` | keyframe + ffmpeg → mp4 |

**[ФАКТ]** Состояние хранится только в файлах:

- `characters/<slug>/character_bible.txt`, `reference_*.png`;
- `episodes/<id>/script.txt`, `scenes/*_keyframe.png`, `scenes/*_draft.mp4`, `audio/*.mp3`;
- `comfyui-workflows/*.api.json` — шаблоны для `/prompt`;
- `prompts/*` — текстовые шаблоны.

**[ФАКТ]** Существующие workflow:

| Файл | Формат | Назначение |
|---|---|---|
| `character_pose_gen.api.json` | API | txt2img-референс персонажа |
| `character_pose_openpose.api.json` | API | поза через ControlNet OpenPose |
| `character_pose_ipadapter.api.json` | API | поза через IP-Adapter |
| `scene_draft_ipadapter.api.json` | API | keyframe сцены через IP-Adapter |
| `scene_draft_ltx.api.json` | API | LTX-workflow с `LoadImage` и `FRAMES` |
| `character_pose_gen.json` | метаданные | карта шаблонов |
| `controlnet_pose.json` | метаданные | описание вспомогательного workflow |
| `scene_draft_ltx.json` | метаданные | описание LTX-черновика |
| `workflow_config.json` | конфиг | checkpoint, модели, параметры, required nodes |
| `ltx23_mlx_q4_test.json` | UI-граф | пример LTX-2 MLX **T2V**, q8, 256×256, 25 кадров |

**[ФАКТ]** API-версии workflow для LTX-2.3 MLX I2V в репозитории нет.
`ltx23_mlx_q4_test.json` — UI-граф с нодами `LTX2MLXModelLoader`/`LTX2MLXGenerate`,
без `LoadImage`, с пустым входом `image`; параметры примера не совпадают с заявленными
в задании 512×512/73 кадра/Q4. Проверка реального API-workflow вынесена в WP-00A.

**[ФАКТ]** Тесты: `14 passed, 1 failed`. Падает
`tests/test_pipeline.py::test_character_refs_stage_reports_missing`: тест подменяет
`orch.settings`, но этапы созданы в `Orchestrator.__init__` и держат старые настройки.
Это ограничение внедрения зависимостей, а не ошибка бизнес-логики. Исправление — отдельный
контролируемый пакет WP-00C; production-код при этом не меняется.

**[ФАКТ]** Репозиторий не под git. `git status` возвращает
`fatal: not a git repository`.

### 1.2. Ограничения текущей архитектуры

- Нет единого источника истины для статусов, версий и истории попыток.
- Нет понятия `Shot`, `Job`, `RenderAttempt`, `Artifact`.
- Нет версионирования референсов и character bible.
- Нет approve/reject и привязки конкретной версии референса к шоту.
- Нет очереди, lease, heartbeat, retry, recovery.
- Нет API для UI и воркера.
- Пути абсолютные/хостовые; fallback ComfyUI зашит в
  `pipeline/comfyui/generator.py`.
- `PipelineStage` описывает стадии производства, а не задания очереди; смешивать их нельзя.

---

## 2. Целевая архитектура

**[ПРЕДЛОЖЕНИЕ]** Mary Studio — одно приложение из четырёх частей с PostgreSQL как
единственным источником истины.

```text
Browser
   |
   v
React + TypeScript + Vite (Mary Studio UI)
   |
   v
FastAPI backend  ----  PostgreSQL (projects, characters, shots, jobs, attempts, artifacts)
   |                        |
   |                   storage metadata (sha256)
   v
Artifact storage (относительные storage_key; файлы на диске контроллера)
   ^
   |
Mac Worker (pull: claim / heartbeat / artifacts / complete / resume)
   |
   +-- resource lock (один тяжёлый job)
   +-- ComfyUI 127.0.0.1  (LTX-2.3 MLX I2V)
   +-- Ollama 127.0.0.1   (сценарий/промпты)
   +-- ffmpeg             (постобработка, проверки, FakeWorker)
```

Границы:

| Компонент | Ответственность | Не делает |
|---|---|---|
| Backend | API, валидация, БД, очередь, версии, аудит, storage metadata | Не запускает модели |
| Worker | claim/lease, подготовка workflow, вызов ComfyUI/Ollama, upload, resume | Не меняет approved |
| UI | библиотека, шоты, композиция, очередь, review | Не хранит бизнес-состояние |
| `pipeline/` | Переиспользуемые адаптеры ComfyUI/Ollama/ffmpeg/парсеры | Не источник истины |
| Storage | Байты артефактов по `storage_key` + sha256 | Не хранит статусы |

**[ПРИНЯТО В АРХИТЕКТУРУ]** Провайдер генерации — сменный адаптер, а не часть домена.
LTX-2.3 MLX Q4 (I2V) — текущий provider, но схема и API не привязаны к одной модели:
`render_attempts` хранит `provider`, `workflow_version`, `model_hash`, `parameters`, а
таблицы `shots`/`artifacts` не содержат полей, специфичных для LTX. Смена модели =
новый handler + новый API-шаблон + новая версия параметров, без миграции этих таблиц.

**[ПРЕДЛОЖЕНИЕ]** Целевая раскладка внутри текущего репозитория:

```text
Mary_Guiness/
├── backend/
│   ├── app/            # FastAPI, конфигурация, зависимости
│   ├── api/            # роуты public/worker
│   ├── models/         # SQLAlchemy 2
│   ├── services/       # доменные сервисы, state machine, storage
│   ├── alembic/        # миграции
│   └── tests/
├── worker/
│   ├── agent.py        # pull-цикл
│   ├── handlers/       # comfyui_i2v, keyframe, ollama_script
│   └── resource.py     # lock, память, unload
├── ui/                 # React + TS + Vite
├── pipeline/           # существующий код, режим legacy-адаптеров
├── characters/         # исходные пользовательские файлы (не перемещать)
├── episodes/           # исходные пользовательские файлы (не перемещать)
├── comfyui-workflows/  # шаблоны, включая API-формат I2V
├── prompts/
├── storage/            # runtime-хранилище артефактов, вне git
├── docs/
│   ├── ARCHITECTURE.md # копия/ссылка на VIDEO-ORCHESTRATOR v1.3
│   ├── PROPOSALS/
│   └── ROADMAP_MARY_STUDIO.md
├── main.py             # legacy CLI, сохраняется на время миграции
└── tests/              # существующие тесты
```

**[ТРЕБУЕТ УТВЕРЖДЕНИЯ]** Выбор «Mary_Guiness — корень Mary Studio» вместо отдельного
репозитория. Это противоречит §14.1 п.7 `VIDEO-ORCHESTRATOR.md`, где Mary_Guiness
объявлен read-only. Рекомендация: считать Mary_Guiness доменным репозиторием Mary Studio,
а `VIDEO-ORCHESTRATOR.md` — архитектурным контрактом; пункт 7 применять к другим
проектам монорепо, не к Mary_Guiness.

---

## 3. План переиспользования существующего кода

| Существующий код | Решение | Как использовать |
|---|---|---|
| `pipeline/comfyui/client.py` | Переиспользовать | HTTP-клиент ComfyUI внутри worker handler; добавить конфиг таймаутов |
| `pipeline/comfyui/workflows.py` | Переиспользовать | Рендер API-шаблонов по именованным параметрам; не править JSON по номерам нод |
| `pipeline/comfyui/generator.py` | Переиспользовать частично | Логика выбора шаблона и upload; убрать хостовый fallback пути |
| `pipeline/comfyui/scene_draft.py` | Переиспользовать частично | Разделить «keyframe» и «сборка mp4»; ffmpeg-часть → worker/backend |
| `pipeline/config.py` | Переиспользовать | Чтение `.env` как источник настроек worker’а |
| `pipeline/utils.py` | Переиспользовать | `parse_script`, `load_character_bible`, построение промптов |
| `pipeline/orchestrator.py` | Не использовать как очередь | Оставить для legacy CLI; в backend не импортировать |
| `pipeline/stages/*` | Адаптировать | Превратить в job handlers или оставить legacy |
| `main.py` | Сохранить | Legacy CLI работает, пока backend не заменит сценарии |
| `tests/` | Сохранить | Добавить тесты backend/worker; не удалять существующие |
| `characters/`, `episodes/` | Не перемещать | Импортировать метаданные, оригиналы оставить на месте |

**[ПРЕДЛОЖЕНИЕ]** Зависимости между слоями:

```text
backend  ->  models/services (БД, storage)
worker   ->  pipeline/comfyui/*, pipeline/utils.py, pipeline/config.py
ui       ->  backend HTTP API
pipeline ->  не импортирует backend и worker
```

---

## 4. Границы Mary_Guiness и Video Orchestrator

**[ФАКТ]** `VIDEO-ORCHESTRATOR.md` v1.3 находится вне репозитория:
`/Users/vladislavkovalenko/Projects/My_Projects/VIDEO-ORCHESTRATOR.md`.

**[ПРЕДЛОЖЕНИЕ]** Разделение ответственности:

| Mary_Guiness (домен) | Video Orchestrator (платформа) |
|---|---|
| Character bible и референсы | Схема БД, статусы, версии |
| Локации, предметы, композиции | Очередь, lease, retry, recovery |
| Сценарии, промпты, workflow-шаблоны | API, SSE, аудит, storage metadata |
| Legacy CLI и адаптеры ComfyUI/Ollama | Worker protocol и артефакты |
| Тестовые эпизоды | Приёмка, approve/reject |

Контракты v1.3 сохраняются: pull-модель воркера, PostgreSQL-очередь, `render_attempts`,
`artifacts`, относительные `storage_key`, sha256, SSE, 202 Accepted, cancel вместо delete.
Все отклонения перечислены в §11; принятие в архитектуру не означает разрешение на
реализацию, миграции или изменение API.

---

## 5. Модель библиотеки персонажей

### 5.1. Сущности

**[ПРИНЯТО В АРХИТЕКТУРУ]** Минимальная модель (уточнения — в §5.2 и §11.1):

| Таблица | Поля (ключевые) | Назначение |
|---|---|---|
| `characters` | `id`, `project_id`, `slug`, `name`, `kind` (`cat`/`human`/`other`), `description`, `status`, `created_at`, `updated_at` | Постоянный персонаж |
| `character_bible_versions` | `id`, `character_id`, `version`, `body`, `sha256`, `status` (`draft`/`approved`/`superseded`), `created_at`, `approved_at` | Версионированный bible |
| `reference_assets` | см. §5.2 | Изображения-референсы |
| `shot_references` | `id`, `project_id`, `shot_id`, `reference_asset_id`, `purpose`, `created_at` | Привязка конкретного ассета к шоту |
| `shot_compositions` | `id`, `project_id`, `shot_id`, `revision`, `width`, `height`, `status` (`draft`/`approved`/`superseded`), `preview_artifact_id`, `created_at`, `approved_at` | Ревизия композиции; `UNIQUE(shot_id, revision)` — ревизий на шот может быть много |
| `shot_composition_layers` | `id`, `project_id`, `composition_id`, `reference_asset_id`, `z_index`, `x`, `y`, `scale`, `rotation`, `opacity` | Слои ревизии: порядок наложения и трансформации |

`locations` и `props` — аналогичные простые таблицы (`id`, `project_id`, `name`,
`description`, `status`) со своими `reference_assets`.

**[ПРЕДЛОЖЕНИЕ]** Геометрия слоёв вынесена из `shot_references` в `shot_composition_layers`:
привязка «какой ассет участвует в шоте» и «как он размещён в конкретной ревизии» — разные
факты. Один ассет может входить в несколько ревизий с разными трансформациями, а удаление
слоя из ревизии не затрагивает привязку к шоту. Нормализованная таблица (вместо `layers_json`)
даёт внешний ключ на `reference_assets` и тем самым проверку принадлежности ассета проекту
на уровне БД.

**[ПРЕДЛОЖЕНИЕ]** `episodes` — отдельная сущность (детали в §11.1 S11): в v1.3 её нет,
а `scenes` привязаны к `projects` напрямую. Эпизод нужен, потому что существующие данные
(`episodes/<id>/script.txt`) и пользовательский сценарий оперируют эпизодом как единицей
производства, а не только проектом.

### 5.2. Совместимость с `reference_assets` v1.3

**[ФАКТ]** В v1.3: `reference_assets(id, project_id, kind, storage_key, sha256, metadata)`.

**[ПРИНЯТО В АРХИТЕКТУРУ]** Таблица расширяется, а не дублируется:

```text
reference_assets
  id                uuid pk
  project_id        uuid not null fk projects
  kind              enum: character_reference | location_reference | prop_reference | uploaded
  character_id      uuid null fk characters
  location_id       uuid null fk locations
  prop_id           uuid null fk props
  role              text null        -- напр. face, full_body, style
  view              text null        -- front | side | three_quarter | back | other
  pose              text null        -- stand | sit | walk | lie | sleep | custom
  expression        text null
  status            enum: draft | approved | rejected
  storage_key       text not null
  sha256            char(64) not null
  width, height     int null
  mime_type         text
  metadata          jsonb not null default '{}'   -- физическое имя колонки, как в v1.3
  created_at, approved_at
  UNIQUE (project_id, id)          -- цель составных FK владельцев
  UNIQUE (project_id, sha256)      -- дедупликация в рамках проекта
```

**[ПРИНЯТО В АРХИТЕКТУРУ]** Инвариант владельца зависит от `kind` (CHECK, а не «не более
одного из трёх»):

| `kind` | `character_id` | `location_id` | `prop_id` | Смысл |
|---|---|---|---|---|
| `character_reference` | NOT NULL | NULL | NULL | референс персонажа |
| `location_reference` | NULL | NOT NULL | NULL | референс локации |
| `prop_reference` | NULL | NULL | NOT NULL | референс предмета |
| `uploaded` | NULL | NULL | NULL | свободный ассет проекта |

`uploaded` не «бесхозный»: его владелец — `project_id`. Он не попадает в выборку
референсов персонажа, но может быть слоем композиции и исходным PNG для keyframe.
Поэтому исходное ограничение «не более одного владельца» заменено на «владелец строго
соответствует `kind`» — иначе `uploaded` с заполненным `character_id` был бы неотличим
от `character_reference`.

**[ПРИНЯТО В АРХИТЕКТУРУ]** Принадлежность ассетов проекту проверяется декларативно:

- владелец ассета обязан принадлежать тому же проекту: составные FK
  `(project_id, character_id) → characters(project_id, id)`, аналогично `locations`/`props`;
  на владельцах добавляется `UNIQUE(project_id, id)`;
- `shot_references`: `(project_id, reference_asset_id) → reference_assets(project_id, id)`;
- `shot_composition_layers`: тот же составной FK; принадлежность самого шота проекту
  проверяется в сервисе и тестом целостности (цепочка `shot → scene → project` не выражается
  одним FK без денормализации).

**[ПРИНЯТО В АРХИТЕКТУРУ]** `metadata_json` — только имя ORM-атрибута. Физическое имя
колонки в PostgreSQL остаётся `metadata` (совместимость с v1.3), а в SQLAlchemy
Declarative используется alias:

```python
metadata_json = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
```

S3 переклассифицирован: это не изменение схемы, а деталь ORM; миграция переименования
колонки не нужна.

Причины остальных полей:

- `status` `draft`/`approved`/`rejected` обязателен по заданию; автоматически `approved`
  не выставляется;
- `view`/`pose`/`expression` нужны для фильтрации библиотеки и выбора стартового кадра.

### 5.3. Инварианты

1. Любая сгенерированная поза создаётся со статусом `draft`.
2. `approved` выставляется только человеком через API/UI; автоматического `approved` нет.
3. `reference_assets` и `character_bible_versions` иммутабельны: изменение содержимого,
   владельца, `storage_key`, `sha256`, `view`/`pose`/`expression` = новая запись.
4. У утверждённой записи допустим только переход статуса `approved → superseded`
   (отзыв) либо `approved → rejected` (ошибка приёмки). Сам контент и метаданные
   утверждённой версии не переписываются; история решения сохраняется.
5. Шот ссылается на конкретный `reference_asset_id`; последующее изменение персонажа не
   меняет историю шота.
6. Bible версионируется; попытка рендера хранит использованную версию или её sha256.
7. Удаление персонажа/локации/предмета не удаляет ассеты и историю: только архивирование
   статусом, без каскадного удаления артефактов.
8. Все сущности библиотеки и композиции принадлежат одному `project_id` с владельцем и
   шотом; межпроектные ссылки запрещены (составные FK из §5.2).
9. `uploaded`-ассет не привязывается к персонажу/локации/предмету и не участвует в
   approve-выборке библиотеки; он используется как слой композиции или исходный кадр.
10. Композиция версионируется: каждое сохранение создаёт новую ревизию
    `(shot_id, revision)`. Утверждённая ревизия иммутабельна; изменение = новая ревизия.
11. Стартовый кадр имеет единственный источник истины — `shots.start_keyframe_artifact_id`
    (плюс `start_keyframe_attempt_id`). Записывает его только `promote-keyframe`;
    рендер композиции и создание keyframe-попытки статус шота не меняют.
12. Смена approved-ревизии композиции не переписывает уже утверждённый стартовый кадр:
    требуется новая keyframe-попытка и явное повторное подтверждение.

---

## 6. Связи Characters → ReferenceAssets → Shots

```text
Project   1--N Episode 1--N Scene 1--N Shot      (Episode — S11, §11.1)
Character 1--N CharacterBibleVersion
Character 1--N ReferenceAsset (kind=character_reference)
Location  1--N ReferenceAsset (kind=location_reference)
Prop      1--N ReferenceAsset (kind=prop_reference)
Project   1--N ReferenceAsset (kind=uploaded, без владельца-сущности)
Shot      1--N ShotReference --1 ReferenceAsset
Shot      1--N ShotComposition (revision) 1--N ShotCompositionLayer --1 ReferenceAsset
ShotComposition 0..1 Artifact (preview PNG)
Shot      0..1 Artifact (start keyframe)         <- единственный указатель
Shot      1--N RenderAttempt --1..N Artifact
```

**[ПРИНЯТО В АРХИТЕКТУРУ]** Стартовый кадр — не отдельная сущность, а указатель на
артефакт keyframe-попытки. Композиция — «рецепт», keyframe-попытка — его рендер,
`promote-keyframe` — единственное действие, делающее кадр утверждённым.

**[ПРЕДЛОЖЕНИЕ]** Первый сценарий:

1. Пользователь открывает карточку Guinness.
2. Видит `reference_assets` с фильтром по `view`/`pose`/`status`.
3. Утверждает один или несколько референсов (`approved`).
4. Создаёт шот; привязывает approved-референсы персонажа, локации и предметов.
5. Сохраняет композицию: координаты, масштаб, порядок слоёв (новая ревизия).
6. Backend рендерит один PNG (`shot_compositions.preview_artifact_id`); это ещё не keyframe.
7. `POST /keyframe` создаёт keyframe-попытку из выбранной ревизии; пользователь
   подтверждает её через `promote-keyframe`, и только тогда фиксируется
   `shots.start_keyframe_artifact_id`.
8. Только после этого разрешён `POST /api/shots/{id}/render`.
9. Worker выполняет I2V; создаётся `render_attempt` и `artifact` MP4.
10. Пользователь просматривает попытку и утверждает/отклоняет.

**[ПРЕДЛОЖЕНИЕ]** Композиция не генерирует тени, не делает сегментацию и pose-control.
Это явно вне первой реализации.

---

## 7. Предложение API библиотеки

**[ФАКТ]** Базовые эндпоинты v1.3: `projects`, `scenes`, `shots`, `render`, `approve`,
`reject`, `jobs`, `cancel`, `events`, worker API.

**[ПРИНЯТО В АРХИТЕКТУРУ]** Новые эндпоинты в дополнение к существующим, без изменения
их семантики. Исключение — A5 (композиция): он переработан и требует утверждения.

```http
# Персонажи и bible
GET    /api/characters?project_id=&status=
POST   /api/characters
GET    /api/characters/{character_id}
PATCH  /api/characters/{character_id}
GET    /api/characters/{character_id}/bibles
POST   /api/characters/{character_id}/bibles
POST   /api/characters/{character_id}/bibles/{version_id}/approve

# Референсы персонажа
GET    /api/characters/{character_id}/references?status=&view=&pose=
POST   /api/characters/{character_id}/references        # upload + метаданные
POST   /api/reference-assets/{asset_id}/approve
POST   /api/reference-assets/{asset_id}/reject

# Локации и предметы
GET    /api/locations
POST   /api/locations
GET    /api/props
POST   /api/props
GET    /api/locations/{id}/references
GET    /api/props/{id}/references

# Привязки и композиция шота
GET    /api/shots/{shot_id}/references
POST   /api/shots/{shot_id}/references
DELETE /api/shots/{shot_id}/references/{link_id}
GET    /api/shots/{shot_id}/compositions                 # список ревизий
POST   /api/shots/{shot_id}/compositions                 # новая ревизия (черновик)
GET    /api/shots/{shot_id}/compositions/{revision}
PUT    /api/shots/{shot_id}/compositions/{revision}      # только draft-ревизия
POST   /api/shots/{shot_id}/compositions/{revision}/render   # PNG → artifact, без approve
POST   /api/shots/{shot_id}/compositions/{revision}/approve  # утвердить ревизию-рецепт
GET    /api/shots/{shot_id}/attempts
```

Существующие эндпоинты v1.3 сохраняются; ниже зафиксирована их семантика.

Правила: `202 Accepted` на постановку job, `Idempotency-Key` для повторного render,
единый формат ошибок, пагинация списков, проверка storage keys, токен воркера.

### 7.1. Стартовый кадр: один источник истины

**[ПРИНЯТО В АРХИТЕКТУРУ]** Три эндпоинта не конкурируют, а образуют одну цепочку:

| Эндпоинт | Что создаёт | Меняет `shots.start_keyframe_artifact_id` |
|---|---|---|
| `POST /api/shots/{id}/compositions/{revision}/render` | `artifact(kind=composition_preview)`, привязанный к ревизии | Нет |
| `POST /api/shots/{id}/keyframe` | `render_attempt(kind=keyframe)` + `artifact(kind=keyframe)` из указанной ревизии (или из `reference_asset_id` для привязки загруженного кадра) | Нет |
| `POST /api/shots/{id}/attempts/{id}/promote-keyframe` | только указатели `start_keyframe_artifact_id` и `start_keyframe_attempt_id` | **Да, единственный писатель** |

Следствия:

- `POST /composition/render` — предпросмотр «рецепта», не утверждение. Повторный вызов
  создаёт новый артефакт той же ревизии; ревизия при этом не меняется.
- `POST /compositions/{revision}/approve` утверждает только ревизию-рецепт; статус шота и
  `start_keyframe_artifact_id` не меняются, `keyframe_ready` не выставляется.
- `POST /keyframe` без аргументов берёт последнюю сохранённую ревизию; при передаче
  `composition_revision` — конкретную. Два вызова подряд создают две попытки, а не две
  «истины»: утверждённой остаётся та, что прошла `promote-keyframe`.
- `promote-keyframe` идемпотентен по `(shot_id, attempt_id)`: повторный вызов не создаёт
  дубль, а возвращает текущее состояние. Попытка другого шота отклоняется.
- `POST /api/shots/{id}/render` требует непустой `start_keyframe_artifact_id`;
  артефакт композиции сам по себе недостаточен.
- Смена approved-ревизии композиции не меняет утверждённый кадр; нужен новый
  `keyframe` + `promote-keyframe` (§5.3 п. 12).

**[ПРИНЯТО В АРХИТЕКТУРУ]** В БД для этого нужны два поля: `shots.start_keyframe_artifact_id`
(S9) и `shots.start_keyframe_attempt_id` (уточнение к S9). Второе поле — ссылка на попытку,
из которой взят кадр, чтобы история и параметры были восстановимы.

### 7.2. Типизированные ревизии промптов (S10, переработан)

**[ПРЕДЛОЖЕНИЕ]** Вместо двух новых колонок (`keyframe_prompt`/`motion_prompt`) —
одна колонка типа:

```text
prompt_revisions
  id                  uuid pk
  shot_id             uuid not null fk shots
  prompt_type         enum: keyframe | motion | composition | script | other   -- default 'motion'
  version             int not null
  prompt              text not null          -- колонка v1.3, сохраняется
  negative_prompt     text null
  model_id            text null
  parameters_json     jsonb not null default '{}'
  created_at          timestamptz not null
  UNIQUE (shot_id, prompt_type, version)
```

Совместимость с v1.3:

- `prompt` и `negative_prompt` не переименовываются и не удаляются;
- `prompt_type` имеет `default 'motion'`, поэтому существующие записи и клиенты v1.3
  читаются без изменений (`prompt` = motion-промпт);
- `version` нумеруется в рамках `(shot_id, prompt_type)`;
- `keyframe` — что в кадре; `motion` — что происходит; `composition` — служебный промпт
  рендера композиции; `script` — текст сцены. Добавление нового типа не требует миграции
  (значение enum расширяется).
- `render_attempts.prompt_revision_id` продолжает указывать на конкретную запись; для
  I2V-попытки обе ревизии (`keyframe` + `motion`) сохраняются в
  `parameters_json.prompt_revision_ids`, не меняя смысл одиночного FK.

Это изменение остаётся **[ТРЕБУЕТ УТВЕРЖДЕНИЯ]**, потому что добавляет колонку и тип в
таблицу v1.3, но оно аддитивно и не ломает существующие чтения.

---

## 8. План веб-интерфейса

**[ПРЕДЛОЖЕНИЕ]** React + TypeScript + Vite.

Разделы MVP:

| Раздел | Экран | Минимальный функционал |
|---|---|---|
| Characters | список + карточка | поиск, bible-версии, сетка референсов, approve/reject |
| Locations | список + карточка | референсы локаций |
| Props | список + карточка | референсы предметов |
| Episodes | список + карточка | сцены и шоты (после утверждения S11) |
| Shots | карточка шота | референсы, композиция, keyframe, render, попытки, плеер |
| Render Queue | очередь | статус, прогресс через SSE, cancel |
| Review | очередь ревью | попытки, approve/reject, сравнение версий |

Редактор композиции MVP:

- список слоёв с явным порядком наложения (`z_index`), перестановка вверх/вниз;
- координаты `x`, `y`, масштаб, поворот, `z-index`, прозрачность;
- выбор approved-ассетов;
- сохранение композиции как новой ревизии и предпросмотр PNG;
- без теней, маскирования и автоматического pose-control.

**[ПРИНЯТО В АРХИТЕКТУРУ]** Прозрачность PNG — обязательное требование, а не пожелание:

- композитор сохраняет альфа-канал (`RGBA`) и не «сплющивает» изображение на белом фоне;
- при загрузке/привязке ассета проверяется наличие альфа-канала: `RGBA`-режим либо
  `tRNS`-палитра; полностью непрозрачный PNG считается валидным, но помечается флагом;
- для ассета с `kind=character_reference` непрозрачное изображение вызывает предупреждение
  в UI («персонаж закроет фон прямоугольником») и запись в ответе API; блокировки нет,
  человек может подтвердить;
- UI показывает список слоёв, порядок наложения и превью каждого слоя, чтобы порядок был
  видим до рендера, а не только в результате;
- тесты композиции: (а) два персонажа + одна локация — проверяются размеры, порядок
  наложения, сохранение альфы; (б) непрозрачный персонаж — проверяется предупреждение;
  (в) отсутствие исходных файлов в результате (композитор не перезаписывает ассеты).

Автоматическая сегментация фона и генерация теней в MVP не реализуются.

Технические решения: React Router, TanStack Query, SSE-клиент; без Kanban и таймлайна
до MVP. UI получает API через reverse proxy `/api`, без runtime-подстановки `VITE_*`.

---

## 9. Миграционная стратегия существующих файлов

**[ПРЕДЛОЖЕНИЕ]** Импорт без перемещения и без удаления.

1. Инвентаризация: обойти `characters/`, `episodes/`, `comfyui-workflows/`, `prompts/`.
2. Для каждого файла вычислить sha256; дубликаты не создавать.
3. Создать записи в БД со `status=draft` (кроме явно согласованных исключений).
4. Скопировать байты в `storage/` под относительным `storage_key`; оригиналы оставить.
5. Сформировать отчёт `docs/MIGRATION-REPORT.md`: что импортировано, что пропущено.
6. Повторный запуск идемпотентен по sha256.
7. Только после проверки отчёта человеком — переключать UI/API на БД.
8. Legacy CLI продолжает работать.

Маппинг:

| Источник | Куда |
|---|---|
| `characters/<slug>/character_bible.txt` | `characters` + `character_bible_versions` v1 (`draft`) |
| `characters/<slug>/reference_*.png` | `reference_assets` (`draft`, view/pose из имени) |
| `characters/<slug>/reference_front.jpeg` | `reference_assets` как дополнительный ассет |
| `characters/guinness/1.png` | не импортировать автоматически; показать в отчёте |
| `episodes/<id>/script.txt` | `episodes` (после утверждения S11) + `scenes`/`shots` через `parse_script`; без S11 — сразу `projects`/`scenes`/`shots` |
| `episodes/<id>/scenes/*_keyframe.png` | `artifacts` + keyframe-попытка |
| `episodes/<id>/scenes/*_draft.mp4` | `render_attempts` + `artifacts` (`video_draft`) |
| `episodes/<id>/scenes/*_final.mp4`, `*_lipsync.mp4` | импорт после MVP/озвучки, иначе пропуск |
| `episodes/<id>/audio/*.mp3` | артефакты аудио (post-MVP) |

**[ПРЕДЛОЖЕНИЕ]** Статусы после импорта: bible `draft`, референсы `draft`,
видео/кадры — существующие попытки без автоматического `approved`.

---

## 10. Риски и открытые вопросы

### 10.1. Риски

| Риск | Уровень | Снижение |
|---|---|---|
| Нет API-формата LTX-2.3 MLX I2V | Высокий | WP-00A: API-workflow на рабочем ComfyUI; WP-08: интеграция в worker |
| I2V искажает анатомию/последовательность | Высокий | Ручной review, seed/параметры, повторные попытки, не обещать консистентность |
| 18 GB memory pressure/OOM | Высокий | Один job, resource lock, unload, телеметрия |
| Конфликт с v1.3 (read-only, MVP scope) | Высокий | Решения в §11 и в `docs/DECISIONS.md` |
| Изменение схемы ломает контракт | Высокий | Отдельное утверждение; миграции Alembic; аддитивные колонки с default |
| Межпроектные ссылки на ассеты | Высокий | Составные FK `(project_id, id)` из §5.2 + тест целостности |
| Два источника утверждённого кадра | Высокий | Единственный писатель `promote-keyframe` (§7.1) + тест |
| Непрозрачный PNG персонажа | Средний | Проверка альфы, предупреждение в UI/API, тест композиции |
| Потеря/дубли файлов при импорте | Средний | sha256, dry-run, отчёт, оригиналы не двигать |
| Абсолютные пути | Средний | Только относительные `storage_key` |
| Нет git | Средний | Отдельный контролируемый пакет WP-00B; без него ветки/коммиты невозможны |
| `metadata` как имя атрибута SQLAlchemy | Низкий | ORM-alias `metadata_json` поверх колонки `metadata`; миграции нет |
| Жёсткая привязка к LTX-2.3 | Средний | Provider-абстракция (§2), `provider`/`workflow_version` в попытке |
| Тестовая база красная | Средний | Отдельный пакет WP-00C: исправить DI теста, не ослабляя проверку |
| Секреты/сеть | Высокий | `.env` не читать/не коммитить; ComfyUI/Ollama только `127.0.0.1`; токен воркера |

### 10.2. Открытые вопросы к человеку

| Вопрос | Статус | Решение / что осталось |
|---|---|---|
| Mary_Guiness — корень Mary Studio или отдельный репозиторий? | Закрыт (P1) | Mary_Guiness — основной репозиторий; legacy CLI сохраняется |
| Включать библиотеку персонажей в MVP? | Закрыт (P2) | Входит в MVP |
| Где физически хранить `storage/` и копировать ли оригиналы? | Открыт | Предложение: `storage/` внутри репозитория, вне git; оригиналы не перемещать |
| Нужен ли `git init` и какой remote? | Открыт | Нужен; remote и момент инициализации — за человеком (WP-00B) |
| Backend на `uv` + `pyproject.toml`? | Закрыт (P4) | `uv` + `pyproject.toml` для новых компонентов; legacy не трогаем |
| Статус импортируемых bible/референсов | Открыт | Предложение: `draft`; автоматического `approved` нет |
| Кто рендерит композицию: backend синхронно или job? | Открыт | Предложение: синхронно (Pillow), т.к. без модели и быстро; job — если PNG станет тяжёлым |
| Целевые параметры шота: разрешение, кадры, fps, длительность | Открыт | Предложение: 512×512, `num_frames` кратно `8k+1`, 24 fps — как в текущих экспериментах; подтвердить на WP-00A |
| Один пользователь или несколько? Аутентификация UI? | Открыт | Предложение MVP: один пользователь, локальный доступ, токен воркера обязателен |
| Облачный fallback (Grok/Kling) как явный provider? | Открыт | Предложение: не в MVP; архитектура готова к добавлению provider’а |
| Принять S10 в виде `prompt_type` + `version`? | Открыт | Аддитивно, совместимо с v1.3 |
| Принять S11 (`episodes`) и `scenes.episode_id`? | Открыт | Иначе импорт `episodes/<id>` теряет уровень эпизода |
| Нормализованные слои вместо `layers_json` (S8)? | Открыт | Даёт FK-проверку принадлежности ассетов проекту |
| Предупреждение о непрозрачном PNG — блокировать или только предупреждать? | Открыт | Предложение: только предупреждать |

---

## 11. Изменения относительно Video Orchestrator v1.3

**S1–S9 и A1–A4, A6 приняты в проект архитектуры с уточнениями ниже.** S10 переработан,
A5 переработан, S11 и S12 предложены. Принятие в архитектуру не является разрешением
на миграции и изменение API.

### 11.1. Схема БД

| ID | Изменение | Статус | Причина |
|---|---|---|---|
| S1 | `reference_assets`: `character_id`, `location_id`, `prop_id` (nullable FK) + CHECK «владелец соответствует `kind`», включая `uploaded` | Принято с уточнением | библиотека персонажей/локаций/предметов; `uploaded` остаётся без владельца-сущности |
| S2 | `reference_assets`: `status`, `view`, `pose`, `expression`, `width`, `height`, `role`, `approved_at` | Принято | фильтрация и approve |
| S3 | `reference_assets.metadata`: физическое имя колонки сохраняется; ORM-атрибут `metadata_json` | Принято как деталь ORM | конфликт с SQLAlchemy Declarative; миграции нет |
| S4 | Новая таблица `characters` (`UNIQUE(project_id, id)` для составных FK) | Принято | постоянный персонаж |
| S5 | Новая таблица `character_bible_versions` | Принято | версионирование bible |
| S6 | Новые таблицы `locations`, `props` (аналогично `characters`) | Принято | библиотека локаций/предметов |
| S7 | Новая таблица `shot_references`: `project_id`, `shot_id`, `reference_asset_id`, `purpose`; составной FK на ассет | Принято с уточнением | привязка версии референса к шоту; геометрия вынесена в S8 |
| S8 | Новая таблица `shot_compositions` (`UNIQUE(shot_id, revision)`, `status`) + `shot_composition_layers` | Принято с уточнением | несколько ревизий на шот; нормализованные слои дают FK-проверку владельца |
| S9 | `shots.start_keyframe_artifact_id` + `shots.start_keyframe_attempt_id` | Принято с уточнением | единственный источник утверждённого кадра (§7.1) |
| S10 | `prompt_revisions`: `prompt_type` enum (`keyframe`/`motion`/`composition`/`script`/`other`) + `version`; `prompt` сохраняется | **Переработан, требует утверждения** | раздельные промпты (C32) без ломки v1.3 |
| S11 | Новая таблица `episodes` + `scenes.episode_id` (nullable на переходный период) | **Предложен, требует утверждения** | в v1.3 эпизода нет, а данные и сценарий им оперируют |
| S12 | `artifacts.attempt_id` nullable + `artifacts.shot_composition_id`; `render_attempts.job_id` nullable | **Предложен, требует утверждения** | артефакт композиции не имеет попытки; keyframe-попытка не имеет job |

### 11.2. API

| ID | Изменение | Статус | Причина |
|---|---|---|---|
| A1 | CRUD `/api/characters` + bible-версии | Принято | библиотека |
| A2 | approve/reject `/api/reference-assets/{id}` | Принято | ручная приёмка |
| A3 | CRUD `/api/locations`, `/api/props` | Принято | библиотека |
| A4 | `/api/shots/{id}/references` | Принято | привязка и версия референса |
| A5 | Ревизии композиции: `/api/shots/{id}/compositions`, `/{revision}`, `/{revision}/render`, `/{revision}/approve`; keyframe через существующие `keyframe`/`promote-keyframe`; собственного «утвердить кадр» эндпоинт не вводится | **Переработан, требует утверждения** | не создавать второй источник утверждённого кадра (§7.1) |
| A6 | `GET /api/shots/{id}/attempts` | Принято | история версий в UI |

### 11.3. Отклонения от процесса v1.3

| ID | Отклонение | Статус | Причина |
|---|---|---|---|
| P1 | Mary_Guiness развивается, а не read-only; legacy CLI сохраняется | Рекомендация к утверждению | задание на Mary Studio |
| P2 | Библиотека персонажей входит в MVP (ограниченная) | Рекомендация к утверждению | пользовательский сценарий начинается с Guinness |
| P3 | LTX-2.3 MLX Q4 — текущий provider, без жёсткой привязки архитектуры к одной модели | Рекомендация к утверждению | фактический экспериментальный стек; provider-абстракция в §2 |
| P4 | `uv` + `pyproject.toml` для новых компонентов; legacy `requirements.txt` не трогаем | Рекомендация к утверждению | `.cursor/rules/tooling.mdc` |

---

## 12. Вне рамок первой реализации

- Полный Web UI и Kanban.
- PostgreSQL-миграции пользовательской БД в первом пакете.
- Mac Worker и реальная очередь в первом пакете.
- Автоматическая сегментация, тени, pose-control композитора.
- T2I keyframe-сервис, TTS, lip sync, музыка, монтаж.
- Замена LTX на Wan или другую модель.
- Автоматическое обновление ComfyUI/custom nodes.
- Автоматическое присвоение `approved`.
