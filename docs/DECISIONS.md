# Mary Studio — утверждённые решения

> **Статус:** решения утверждены человеком 2026-10-26. Документ описывает **только
> отклонения и дополнения** к архитектурному baseline.
> **Baseline:** `docs/ARCHITECTURE.md` — точная копия `VIDEO-ORCHESTRATOR.md` v1.3
> (sha256 `cd79be3d1fb8d277c5e9381f783e5e879521bfe586a66262e2083aecc17f3a1e`, 844 строки).
> Baseline не переписывается задним числом: всё, что меняется, зафиксировано здесь.
> **Roadmap:** `docs/ROADMAP_MARY_STUDIO.md`; предложение — `docs/PROPOSALS/MARY_STUDIO_INTEGRATION.md`.
> **Границы:** документ не является разрешением на миграции, изменение API или создание
> сервисов. Разрешение на реализацию выдаётся отдельно, по одному work package.

---

## 1. Порядок применения документов

1. `docs/ARCHITECTURE.md` (v1.3) — исходный контракт: сущности, API, worker-протокол,
   правила §14.
2. `docs/DECISIONS.md` (этот файл) — утверждённые изменения и дополнения. При конфликте
   приоритет у этого файла, но только в пределах перечисленных пунктов.
3. `docs/ROADMAP_MARY_STUDIO.md` — порядок работ и границы пакетов.

Всё, что не перечислено в §3–§6, остаётся как в v1.3. Если задача требует изменения,
не описанного здесь, — остановиться и оформить предложение.

---

## 2. Принципы проекта (P1–P4) — приняты

| ID | Решение | Следствие |
|---|---|---|
| P1 | `Mary_Guiness` — основной репозиторий Mary Studio; legacy CLI сохраняется | Новые компоненты добавляются рядом; `main.py`, `pipeline/`, `tests/` не переписываются |
| P2 | Библиотека персонажей входит в MVP | Первый сценарий начинается с Guinness; библиотека ограничена: персонажи, локации, предметы, референсы, approve |
| P3 | LTX-2.3 MLX Q4 — текущий provider, без жёсткой привязки архитектуры к одной модели | `provider`, `workflow_version`, `model_hash`, `parameters` хранятся в попытке; доменные таблицы не содержат полей LTX |
| P4 | `uv` + `pyproject.toml` для новых компонентов | Legacy `requirements.txt` не трогаем; backend и worker получают свои `pyproject.toml` + `uv.lock` |

---

## 3. Утверждённые изменения схемы (S1–S12)

Тип изменения: **A** — аддитивное (новая колонка/таблица), **C** — ограничение
(CHECK/FK/UNIQUE), **R** — переработка ранее предложенного.

| ID | Решение | Тип |
|---|---|---|
| S1 | `reference_assets`: nullable FK `character_id`, `location_id`, `prop_id` + CHECK «владелец соответствует `kind`», включая `uploaded` | A + C |
| S2 | `reference_assets`: `status`, `view`, `pose`, `expression`, `role`, `width`, `height`, `mime_type`, `approved_at` | A |
| S3 | Физическая колонка остаётся `metadata`; ORM-атрибут — `metadata_json` (`mapped_column("metadata", ...)`) | без миграции |
| S4 | Новая таблица `characters` + `UNIQUE(project_id, id)` | A |
| S5 | Новая таблица `character_bible_versions` | A |
| S6 | Новые таблицы `locations`, `props` (аналогично `characters`) | A |
| S7 | Новая таблица `shot_references` (`project_id`, `shot_id`, `reference_asset_id`, `purpose`) + составной FK на ассет | A + C |
| S8 | `shot_compositions` с ревизиями + `shot_composition_layers`; неизменяемые ревизии | A + C |
| S9 | `shots.start_keyframe_artifact_id` + `shots.start_keyframe_attempt_id` | A |
| S10 | `prompt_revisions`: `prompt_type` + `version`; `prompt` сохраняется | A |
| S11 | Новая таблица `episodes`; `scenes.episode_id` | A |
| S12 | Nullable-связи артефактов: `artifacts.attempt_id`, `artifacts.shot_composition_id`, `artifacts.source`, `render_attempts.job_id` + прослеживаемость | A + C |

### 3.1. S1. Владелец `reference_assets`

| `kind` | `character_id` | `location_id` | `prop_id` | Смысл |
|---|---|---|---|---|
| `character_reference` | NOT NULL | NULL | NULL | референс персонажа |
| `location_reference` | NULL | NOT NULL | NULL | референс локации |
| `prop_reference` | NULL | NULL | NOT NULL | референс предмета |
| `uploaded` | NULL | NULL | NULL | свободный ассет проекта |

`uploaded` — не «бесхозная» запись: владелец — `project_id`. Такой ассет не участвует в
approve-выборке библиотеки, но может быть слоем композиции и исходным PNG для keyframe.
Ограничение «не более одного владельца» заменено на «владелец строго соответствует `kind`»,
иначе `uploaded` с заполненным `character_id` неотличим от `character_reference`.

### 3.2. Принадлежность проекту

- на владельцах (`characters`, `locations`, `props`) — `UNIQUE(project_id, id)`;
- `reference_assets`: составные FK `(project_id, character_id)`, `(project_id, location_id)`,
  `(project_id, prop_id)` на соответствующие владельцы;
- `shot_references` и `shot_composition_layers`: `project_id` + составной FK
  `(project_id, reference_asset_id) → reference_assets(project_id, id)`;
- цепочка «шот принадлежит проекту» проверяется в сервисе и тестом целостности, поскольку
  выражается только через `shot → scene → project`.

### 3.3. S10. Типизированные промпты

```text
prompt_revisions
  id, shot_id, prompt_type, version,
  prompt, negative_prompt, model_id, parameters_json, created_at
  UNIQUE (shot_id, prompt_type, version)
```

- `prompt_type`: `keyframe` | `motion` | `composition` | `script` | `other`, default `motion`.
- `prompt` и `negative_prompt` не переименовываются и не удаляются.
- Существующие записи v1.3 читаются как `motion`; клиенты, не знающие о типе, работают без изменений.
- Для I2V-попытки обе ревизии (`keyframe`, `motion`) сохраняются в
  `parameters_json.prompt_revision_ids`; `render_attempts.prompt_revision_id` сохраняет
  прежний смысл одиночной ссылки.

### 3.4. S11. Episode → Scene → Shot

**Порядок сущностей:** `Project → Episode → Scene → Shot`. Shot всегда принадлежит сцене,
сцена — эпизоду, эпизод — проекту.

```text
episodes
  id            uuid pk
  project_id    uuid not null fk projects
  sequence_no   int not null
  title         text
  status        enum: draft | active | archived
  created_at, updated_at
  UNIQUE (project_id, sequence_no)

scenes.episode_id  uuid null fk episodes   -- nullable на переходный период
```

**Обратная совместимость с v1.3:**

- `GET/POST /api/projects/{id}/scenes` сохраняются: сцена создаётся с `episode_id = NULL`,
  если эпизод не указан. Такие сцены отображаются в UI как «Без эпизода».
- `GET /api/episodes/{id}/scenes` — новый путь; старый остаётся рабочим.
- `scenes.episode_id` становится обязательным только после импорта и backfill
  (WP-03), отдельным решением; до этого NULL допустим.
- Ответы API не удаляют поля v1.3; добавление `episode_id` — аддитивное.
- Импорт `episodes/<id>/` создаёт один эпизод на каталог; сцены и шоты вкладываются в него.

### 3.5. S12. Nullable-связи и прослеживаемость артефактов

Разрешённые источники артефакта — ровно один из перечисленных:

| Источник | Поля связи | Когда используется |
|---|---|---|
| `attempt` | `artifacts.attempt_id` NOT NULL | keyframe-попытка, I2V, постобработка |
| `composition` | `artifacts.shot_composition_id` NOT NULL | предпросмотр ревизии композиции |
| `upload` | `artifacts.source = 'upload'`, `storage_key`, `sha256` | ручная загрузка кадра/ассета |
| `import` | `artifacts.source = 'import'` | импорт существующих файлов (WP-03) |

**Инварианты происхождения (обязательны):**

1. У артефакта заполнен ровно один источник: `attempt_id` XOR `shot_composition_id` XOR
   (`source IN ('upload','import')`).
2. `artifacts.source` — enum `attempt | composition | upload | import`; значение обязано
   соответствовать заполненной связи (CHECK).
3. Артефакт иммутабелен: после создания не меняются `sha256`, `storage_key`, `bytes`,
   `mime_type`, источник. Исправление = новый артефакт.
4. `shots.start_keyframe_artifact_id` может указывать только на артефакт с источником
   `attempt(kind=keyframe)` или `upload`; проект артефакта совпадает с проектом шота.
5. Артефакт композиции обязан принадлежать той же ревизии и тому же шоту, что и
   `shot_composition_id`; подмена ревизии невозможна.
6. `render_attempts.job_id` nullable **только** для `kind='keyframe'` (синхронная попытка
   без очереди). Для `kind='video'` и `kind='postprocess'` `job_id` обязателен.
7. Завершённая попытка (`completed`) обязана иметь хотя бы один артефакт; `failed`
   и `cancelled` — не обязана.
8. Инварианты очереди v1.3 сохраняются: частичный уникальный индекс «не более одного
   активного render-job на шот», lease/heartbeat/`lease_expired`/`resume`, запрет
   автоматического перезапуска после истечения lease.
9. Артефакты не удаляются каскадно вместе с job/attempt/шотом; очистка — отдельная
   политика retention.

**Что это даёт:** происхождение любого файла восстанавливается из БД без анализа каталогов,
а ослабление FK не превращается в «файл неизвестного происхождения».

### 3.6. S8. Иммутабельность ревизий композиции

```text
shot_compositions
  id, project_id, shot_id, revision, width, height,
  status (draft | approved | superseded), preview_artifact_id, created_at, approved_at
  UNIQUE (shot_id, revision)

shot_composition_layers
  id, project_id, composition_id, reference_asset_id,
  z_index, x, y, scale, rotation, opacity
```

Правила:

1. Каждое сохранение изменений создаёт новую ревизию; существующая не перезаписывается.
2. Править можно только ревизию в статусе `draft`.
3. `approved`-ревизия иммутабельна: слои, геометрия, порядок наложения и ссылки на ассеты
   не меняются. Изменение = новая ревизия.
4. Повторный рендер ревизии создаёт новый артефакт; ревизия и её `preview_artifact_id`
   не переписываются.
5. Отзыв утверждения — только смена статуса `approved → superseded`; удаление запрещено.
6. Утверждение ревизии не утверждает стартовый кадр и не меняет
   `shots.start_keyframe_artifact_id`.
7. Слои ссылаются на конкретные `reference_asset_id`; смена approved-ассета в библиотеке
   не меняет старую ревизию.

### 3.7. Уточнения перед WP-02 (S13–S18)

Утверждены человеком 2026-10-26. Дополняют S1–S9 и закрывают неоднозначности
`docs/PROPOSALS/MARY_STUDIO_INTEGRATION.md` §5.2 и §5.3.

| ID | Решение | Следствие |
|---|---|---|
| S13 | `reference_assets.status`: `draft \| approved \| rejected \| superseded` | §5.2 и §5.3 п.4 согласованы: отзыв утверждения — `approved → superseded`, ошибка приёмки — `approved → rejected` |
| S14 | `shot_references.purpose`: `character \| location \| prop \| style \| other` | CHECK в БД; расширение набора — отдельной миграцией |
| S15 | Иммутабельность approved-записей обеспечивается триггерами PostgreSQL | `BEFORE UPDATE OR DELETE` на `reference_assets`, `character_bible_versions`, `shot_compositions`: контент и метаданные неизменны, разрешён только переход `approved → superseded` (для референса также `→ rejected`); удаление approved-записи запрещено |
| S16 | `character_bible_versions.project_id` — денормализация проекта | Нужна для составного FK `(project_id, character_id) → characters(project_id, id)`; bible чужого проекта невозможен |
| S17 | Единственность approved-ревизии композиции на шот | Обеспечивается сервисом, не БД; частичный уникальный индекс `approved` не добавляется, переключение ревизии остаётся двухшаговым |
| S18 | `characters.kind`: `cat \| human \| other`, default `other` | CHECK в БД |

Дополнительно к §5.2: `reference_assets.metadata` приводится к `NOT NULL DEFAULT '{}'::jsonb`.

### 3.8. S19. Visual Scene Plan (WP-05A)

Решение принято человеком 2026-10-26 вместе с разрешением на WP-05A.
Нумерация: S16 уже занят (`character_bible_versions.project_id`), поэтому план сцены —
**S19**.

```text
visual_scene_plans
  id, project_id, shot_id, revision, schema_version,
  status (draft | approved | superseded),
  source (manual | llm | fallback),
  plan (jsonb), warnings (jsonb), created_at, approved_at
  UNIQUE (shot_id, revision), UNIQUE (project_id, id)
  CHECK revision >= 1, schema_version >= 1, status/source — по спискам,
        status <> 'approved' OR approved_at IS NOT NULL
  INDEX (shot_id, status)
  UNIQUE INDEX (shot_id) WHERE status = 'approved'

shot_compositions.source_plan_id → visual_scene_plans.id (nullable, ON DELETE — обычный)
```

Правила:

1. `plan` — JSONB со `schema_version = 1`: `canvas {width,height}`, `camera {framing,movement}`,
   `references [{asset_id, role, alias, entity_id}]`, `initial_state`, `action_beats`,
   `motion_prompt`, `constraints`. Новые поля — только повышением `schema_version`;
   старые планы не переписываются.
2. План ссылается на существующие `reference_assets` по `asset_id`; копий изображений,
   новых механизмов хранения и второго storage нет. Роль и alias живут внутри плана и не
   меняют `shot_references`/`reference_assets`.
3. Каждое сохранение изменений создаёт новую ревизию; править можно только `draft`.
   `approved`-ревизия иммутабельна: триггер `mary_forbid_approved_change()` (S15) навешен
   на `visual_scene_plans`, разрешён только переход `approved → superseded`.
4. Единственность approved-плана на шот обеспечивается **БД** (частичный уникальный индекс
   `uq_visual_scene_plans_one_approved`), а не только сервисом: в отличие от S17, здесь
   индекс возможен без конфликта с историей. Смена утверждённого плана — только явный
   `supersede`, не двухшаговое переключение.
5. Композиция из плана пишет `shot_compositions.source_plan_id`; правка композиции не
   меняет план, правка плана не меняет уже созданную композицию. Происхождение цепочки
   `plan → composition → attempt → artifact` восстанавливается из БД.
6. Vision (`gemma3:4b`) — **только советующий источник**. Его вывод всегда даёт `source`
   и предупреждения; при сомнении/недоступности ставится `needs_review = true` и
   предлагается ручной ввод. Автоматического `approved` плана нет. Новые модели не
   скачиваются; модель должна быть уже установлена и реально принимать изображения.
7. Непрозрачный персонаж, закрывающий фон, помечает результат как `layout mockup`
   (`is_layout_mockup`), а не финальный keyframe. Matting/сегментация — отдельный
   эксперимент, в WP-05A не реализуются.
8. Canvas по умолчанию 768×512. Для LTX PoC — отдельный экспорт 512×512 с явным выбором
   `crop` или `pad` (без растяжения); параметры экспорта сохраняются рядом с артефактом.
9. Утверждённые ранее артефакты (референсы, композиции, кадры) задним числом не
   изменяются: план создаёт новые ревизии, а не правит прошлые.

**Что это даёт:** реальные изображения связываются с ролями и действиями явным
контрактом, а не только автоматически составленным текстовым prompt; при этом остаётся
прослеживаемость и ручное подтверждение.

### 3.9. S20. Калибровка области рта (WP-VOICE-02)

Решение принято человеком 2026-11-04 вместе с разрешением на WP-VOICE-02 и миграцию
`0011_mouth_calibrations`.

```text
mouth_calibrations
  id, project_id, shot_id,
  reference_asset_id → reference_assets.id (nullable),
  keyframe_artifact_id → artifacts.id (nullable),
  x, y, width, height, rotation, max_open, sensitivity, smoothing,
  created_at, updated_at
  CHECK ровно один источник: reference_asset_id XOR keyframe_artifact_id
  CHECK область в кадре: x >= 0, y >= 0, width > 0, height > 0,
        x + width <= 1, y + height <= 1
  CHECK rotation -180…180, max_open (0…1], sensitivity (0…5], smoothing [0…1)
  UNIQUE INDEX (shot_id, reference_asset_id) WHERE reference_asset_id IS NOT NULL
  UNIQUE INDEX (shot_id, keyframe_artifact_id) WHERE keyframe_artifact_id IS NOT NULL
```

Правила:

1. Калибровка — изменяемая запись, а не артефакт: одна строка на пару «шот, источник»,
   повторный `POST` обновляет её (upsert), история калибровок не ведётся.
2. Калибровка не меняет approved-референс и артефакт стартового кадра: S15 не ослаблен,
   approved-записи только читаются.
3. Источник калибровки обязан принадлежать шоту: референс — быть привязанным через
   `shot_references`, keyframe — быть keyframe-попыткой этого шота.
4. Калибровка не создаёт jobs, очередей, storage и новых артефактов.

---

## 4. Утверждённые изменения API (A1–A6)

| ID | Решение |
|---|---|
| A1 | CRUD `/api/characters` + версии bible |
| A2 | `approve`/`reject` для `/api/reference-assets/{id}` — только вручную |
| A3 | CRUD `/api/locations`, `/api/props` |
| A4 | `/api/shots/{id}/references` |
| A5 | Ревизии композиции + единый источник стартового кадра (см. §4.1) |
| A6 | `GET /api/shots/{id}/attempts` |

### 4.1. Семантика композиции, keyframe и review (A5)

| Эндпоинт | Создаёт | Меняет утверждённый кадр |
|---|---|---|
| `POST /api/shots/{id}/compositions` | новую ревизию `draft` | нет |
| `POST /api/shots/{id}/compositions/{revision}/render` | `artifact(source=composition)` | нет |
| `POST /api/shots/{id}/compositions/{revision}/approve` | статус ревизии `approved` | нет |
| `POST /api/shots/{id}/keyframe` | `render_attempt(kind=keyframe)` + артефакт | нет |
| `POST /api/shots/{id}/attempts/{id}/promote-keyframe` | указатели `start_keyframe_artifact_id`, `start_keyframe_attempt_id` | **да, единственный писатель** |
| `POST /api/shots/{id}/render` | job I2V | нет; требует заполненный `start_keyframe_artifact_id` |

Дополнительно:

- `promote-keyframe` идемпотентен по `(shot_id, attempt_id)`; попытка другого шота отклоняется.
- `approve`/`reject` попытки видео относится к версии результата и не подменяет
  `start_keyframe_artifact_id`.
- Два источника утверждённого стартового кадра не создаются: кадр утверждается только
  через `promote-keyframe`.
- `POST /api/shots/{id}/keyframe` принимает либо `composition_revision`, либо
  `reference_asset_id` (ровно одно). Второй вариант — стартовый кадр из **approved**
  референса без генерации: проверяются проект, статус, наличие файла и sha256; создаётся
  `render_attempt(kind=keyframe, workflow_version='approved-reference-v1')` с provenance в
  `parameters` и `artifact(source=attempt)`. Повтор с тем же референсом идемпотентен.
  Назначение кадра по-прежнему делает только `promote-keyframe`. Схема БД не менялась.

### 4.2. Серия «Ночной тыгыдык»: импорт и preflight (WP-N1)

| Эндпоинт | Назначение | Схема БД |
|---|---|---|
| `POST /api/projects/{id}/series/import` | идемпотентный импорт JSON-манифеста в Project/Episode/Scene/Shot/PromptRevision/ShotReference | не меняется |
| `POST /api/projects/{id}/series/preflight` | готовность серии к пакетному запуску; только чтение | не меняется |

1. Идентичность импорта — natural keys: `Shot(scene_id, sequence_no)`,
   `PromptRevision(shot_id, prompt_type, version)`,
   `ShotReference(shot_id, reference_asset_id, purpose)`. Повторный импорт создаёт 0 строк.
2. Порядок `Shot` = `order` манифеста → `shots.sequence_no`. `target_duration_frames` =
   `snap8k1(верхняя граница target_duration_seconds × fps)` (7–8 с при 24 fps → 193 кадра),
   `timeline_fps` = fps. Верхняя граница выбрана потому, что подрезка делается в монтаже.
3. Исходный prompt сохраняется дословно в `prompt_revisions.prompt`; provenance — в
   `parameters_json` (`source=nine_lives_band_manifest`, `manifest_sha256`, `shot_key`,
   `output_name_prefix`, `start_frame_filename`, `seed`, `generator`). Новая версия промпта
   создаётся только при изменении текста.
4. Имя референса — не идентификатор. Разрешение требует одновременно: совпадения имени
   (`metadata_json.original_name`, `legacy_path`, basename `storage_key`), принадлежности
   проекту, наличия файла в storage и совпадения sha256. Неоднозначность или несовпадение —
   ошибка, а не выбор «первого подходящего».
5. Отсутствующие файлы не подменяются: референс либо загружается из `--references-dir`
   со статусом `draft` (S16/D5), либо импорт фиксирует ошибку. `approved` — только вручную.
6. CSV-очередь — контрольный артефакт: расхождение с манифестом (порядок, ключи, промпты,
   префиксы) блокирует импорт (HTTP 422 / код возврата 2).
7. Шоты без `start_frame_filename` (сюжетные, 7 шт.) остаются без стартового кадра:
   preflight помечает их как блокированные, кадр утверждает человек.
8. Preflight не пишет в БД. Проверки: `manifest`, `queue_csv`, `project`, `shots`,
   `prompts`, `references`, `start_frames`, `workflow`, `video_params`, `disk`, `outputs`.
   `video_params` остаётся `warn` до подтверждения реальным рендером.

### 4.3. Реальный LTX-воркер (WP-N3)

1. `POST /api/worker/claim` отдаёт `inputs.prompt` и `inputs.shot_key` из последней
   `prompt_revisions` с `prompt_type='motion'`, если их нет в `jobs.payload`. Это
   соответствие baseline `docs/ARCHITECTURE.md` §5.2 (`inputs.prompt`), а не новый контракт:
   набор полей `inputs` был открытым, схема БД и эндпоинты не менялись.
2. `worker/ltx_worker.py` работает только через `/api/worker/*` и не пишет в БД напрямую.
   Стартовый кадр берётся из `inputs.start_image` (его назначает только `promote-keyframe`),
   sha256 проверяется до отправки в ComfyUI.
3. Payload ComfyUI собирает `pipeline/comfyui/ltx_adapter.py`; `num_frames` из шота
   сверяется с `8k+1` — при расхождении job падает с `frames_not_supported`, молчаливая
   подмена длительности запрещена.
4. Lease продлевается heartbeat-ом на каждом опросе `/history`; общий таймаут рендера
   ограничен (`--timeout`, по умолчанию 3600 с).
5. Модель и версия шаблона пишутся в `render_attempts` (`model_hash` = `model_dir` из
   `LTX2MLXModelLoader`, `workflow_version` = префикс + sha256 шаблона).
6. Отмена рендера в ComfyUI при потере lease не реализована: воркер завершает процесс
   с ошибкой, рендер остаётся в очереди ComfyUI. Это ограничение WP-N3, а не инвариант.

### 4.4. Управляемый прогон серии (WP-N4)

| Эндпоинт | Назначение | Схема БД |
|---|---|---|
| `POST /api/projects/{id}/series/runs` | создать прогон (`draft`); готовые шоты → `pending`, неготовые → `skipped` с причиной | `0007_render_series` |
| `GET /api/projects/{id}/series/runs` | список прогонов проекта | — |
| `GET /api/series/{run_id}` | прогон с item'ами, `counts` и прогрессом | — |
| `POST /api/series/{run_id}/{start\|pause\|resume\|stop-after-current\|cancel}` | управление прогоном | — |
| `POST /api/worker/series/next` | воркерский: закрыть текущий item и выдать следующую job серии | — |

1. Прогон — намерение человека и прогресс по шотам; тяжёлые рендеры по-прежнему живут в
   `jobs`. `concurrency = 1` соблюдается тем, что `series/next` создаёт job только после
   завершения текущей, а не отдельной очередью.
2. Таблицы `series_runs` / `series_items` не дублируют статусы job: `series_items.job_id`
   ссылается на `jobs`, а `job_status` читается JOIN-ом. `series_items."order"` — позиция
   внутри прогона (`>= 1`), уникальна вместе с `run_id`; повторный шот в одном прогоне
   запрещён (`uq_series_items_run_shot`).
3. Готовность выводится из данных (`blocked_reason`): `missing_start_frame` →
   `missing_prompt` → `missing_reference`. `enum Shot.status` и preflight не меняются.
4. Политика ошибок — `stop_on_error` (по умолчанию `true`, как в манифесте): item переходит
   в `failed`, прогон — в `paused`; продолжение только явным `resume`. Шоты, заблокированные
   на момент выдачи, получают `skipped` и не останавливают прогон.
5. `stop-after-current` переводит прогон в `stopping`: текущий шот досчитывается, новая job
   не создаётся, после завершения прогон уходит в `paused`.
6. Идемпотентность: `jobs.idempotency_key = series:{run_id}:{order}`; повторный
   `series/next` не создаёт вторую job для того же item. Если у шота уже есть активная
   render-job, ответ `busy` — прогон не дублирует рендер.
7. `POST /api/worker/series/next` требует worker-токен. Без `run_id` берётся самый ранний
   прогон в статусе `running`.
8. Уведомления (баннер macOS) — best-effort: запуск, пауза по ошибке, завершение прогона.
   Ошибки `osascript` подавляются, `MARY_DISABLE_NOTIFY=1` выключает их полностью.
9. Ворота: состав прогона задаётся `shot_orders` (номера шотов). Калибровочный рендер и
   два тестовых шота — отдельные прогоны; вся серия — только по отдельному разрешению.
10. `worker/ltx_worker.py --series-run <id>` (или `--series`) работает по протоколу
    `series/next` → `claim` → одна тяжёлая job. Отмена текущего рендера в ComfyUI
    по-прежнему не реализована (см. §4.3 п.6).

### 4.5. Разрешение рендера серии: 576×1024 (калибровка 2026-10-28)

1. Two-stage half-res в ComfyUI снапит стороны до кратных 64, поэтому 1080×1920 на этой
   машине не рендерится (фактически 1024×1920, 8:15). Точные 9:16 при кратности 64 —
   только 576×1024 (`--long-side 1024`).
2. Замеры на 16 ГБ RAM: 576×1024 / 193 кадра / 24 fps — stage 1 (3600 видео-токенов)
   8 шагов ≈ 7:07, stage 2 (14400 видео-токенов) 3 шага ≈ 11 мин; полный рендер ≈ 18 мин,
   thrash не возникал (swap пик 18.5 из 19.4 ГБ с учётом файла подкачки).
   Для сравнения: 1024×1920 — stage 1 (12000 токенов) 168 с/шаг, stage 2 (48000 токенов)
   не завершил ни одного шага за 24 мин.
3. Решение: шоты серии рендерятся в 576×1024 с `--long-side 1024`; апскейл до 1080×1920
   выполняется на этапе сборки (не реализован). `DEFAULT_LONG_SIDE = 1920` в адаптере и
   `--long-side` по умолчанию не меняются: это параметр запуска, а не новое умолчание.
4. Качество I2V в 576×1024 оценивается человеком по артефакту; до этой оценки серия не
   запускается. Схема БД, эндпоинты и контракты не менялись.
5. Исключение для общих планов (NLB-28…30, решение человека 2026-10-29): стартовый кадр —
   широкий план сцены 1536×1024 (3:2), при 9:16 от группы осталась бы только центральная
   часть. Эти три шота рендерятся в 16:9, 1024×576 (`--aspect-ratio 16:9 --long-side 1024`).
   При сборке широкий план вставляется в 9:16-таймлайн отдельным кадром. Индивидуальное
   разрешение шота по-прежнему задаётся параметрами запуска воркера, а не новым умолчанием.

### 4.6. Имя прогона серии (WP-08)

1. Прогон серии получает необязательное человеческое имя: `series_runs.title` (Text,
   nullable). Имя задаётся при создании прогона (`SeriesRunCreate.title`, 1…200 символов)
   и отдаётся в детали и в списке прогонов. Прогоны без имени остаются валидными и
   опознаются по `id`.
2. Миграция `0008_series_run_title` — только `ADD COLUMN`; downgrade удаляет колонку.
   Инварианты v1.3, `series_items`, идемпотентность `series:{run_id}:{order}` не меняются.
3. Первый именованный прогон — «NLB-single» (серия «Ночной тыгыдык»).

### 4.7. Сюжетные шоты NLB-21…27: identity-референс и внешние сцен-кадры

1. **Identity-референс персонажа.** Внешность Гиннесса задаётся отдельным референсом:
   `reference_assets` с `kind='uploaded'` и `role='guinness_identity'`, утверждённым
   человеком. Он используется как эталон внешности на этапе подготовки кадра, но **не**
   как универсальный стартовый кадр I2V. Сущность `Character` в проекте «Ночной тыгыдык»
   не создаётся (как и раньше, референсы проекта живут без персонажей).
2. **Сцен-кадры готовятся вне системы.** Генерации сцены с сохранением идентичности в
   системе нет: `app/planner.py` — только vision-советник (изображений не создаёт),
   `app/composer.py` — Pillow-композитинг слоёв с предупреждением «непрозрачный слой»
   (`layout mockup`), SDXL/IPAdapter в доступном ComfyUI отсутствуют. Поэтому кадры 9:16
   создаются внешним инструментом и подаются в систему штатным путём:
   `POST /api/projects/{id}/references?kind=uploaded&role=nlb_XX_start` → approve →
   `POST /api/shots/{id}/keyframe` (`reference_asset_id`) → `promote-keyframe`.
   Исключений в API нет; `start_frame_artifact_id` напрямую не пишется (§4.1).
3. **Промпты.** Замена motion-промпта оформляется новой ревизией
   (`prompt_type='motion'`, `version = latest + 1`) с провенансом
   `parameters_json.source='human_prompt_override'`, `shot_key`, `previous_version`.
   Прежние ревизии не перезаписываются. CLI: `python -m app.set_shot_prompts`
   (`--dry-run` / `--apply`, идемпотентен, поиск по `project.title` + `scene.title` +
   `sequence_no`).
4. **Провенанс рендера.** `render_attempts.parameters` заполняется воркером при
   `complete`: `width`, `height`, `num_frames`, `frame_rate`, `cfg_scale`, `seed`,
   `aspect_ratio`, `long_side`, `filename_prefix`, `shot_key`, `worker_name`,
   `job_attempt` + `workflow_snapshot` (фактический связанный workflow). Поле
   `parameters` в `WorkerCompleteRequest` необязательное — воркеры без него остаются
   совместимыми. Миграции нет (JSONB уже существует), у ранее созданных попыток поле
   не переписывается.
5. **Отвязка старой карточки.** Ссылки `shot_references` на многоракурсную карточку
   `Guiness_clean` сняты у 21–27; сам ассет остаётся `approved` (S15), прошлые
   RenderAttempt и MP4 не удаляются и не перезаписываются.
6. **Результат.** Семь сюжетных шотов имеют собственные утверждённые сцен-кадры и
   отрендерены заново (по одной новой попытке на шот): h264 576×1024, 24 fps, 193 кадра,
   8.04 с, `aac` 48 kHz stereo. NLB-01…20 и NLB-28…30 не затрагивались.

### 4.8. Сборка и экспорт вертикального MP4 (WP-M2)

1. **Хранение результата.** Экспорт — обычный `Artifact` с `source='export'`
   (S12 расширен: `attempt` XOR `composition` XOR `upload`/`import` XOR `export`),
   `kind='export_video'`, `mime_type='video/mp4'`. Провенанс лежит в новой колонке
   `artifacts.metadata` (JSONB, NOT NULL DEFAULT `'{}'`): `project_id`, `width`, `height`,
   `fps`, `duration_s`, `audio_artifact_id`, `ffmpeg_version` и `clips[]`
   (`shot_id`, `attempt_id`, `artifact_id`, `sha256`, `trim_start_s`, `trim_end_s`).
   Миграция `0009_export_artifacts` (`ADD COLUMN` + пересоздание трёх CHECK); downgrade
   удаляет `source='export'` и колонку. Отдельные таблицы экспортов не создаются.
2. **API.** `POST /api/projects/{id}/exports` (синхронно, без jobs/worker) и
   `GET /api/projects/{id}/exports` (свежие первыми). Клип задаётся парой
   `shot_id` + `attempt_id`; допускаются только `completed` видео-попытки проекта с
   MP4-артефактом. Необязательные `trim_start_s`/`trim_end_s` проверяются до ffmpeg
   (422 `invalid_trim` / `trim_out_of_range`). До 30 клипов на экспорт.
3. **Формат.** 1080×1920, 24 fps: `scale=1080:1920:force_original_aspect_ratio=decrease`
   + `pad` (без растяжения, широкий кадр получает поля согласно §4.5 п.5), `concat`,
   `libx264 -preset medium -crf 18 -pix_fmt yuv420p`, `aac 192k`, `+faststart`.
   Апскейл 576×1024 → 1080×1920 выполняется здесь (§4.5 п.3).
4. **Звук.** Без `audio_artifact_id` сохраняется звук клипов; клип без аудиодорожки
   получает тишину (`anullsrc`), дорожки ресемплируются в 48 kHz stereo. Если
   `audio_artifact_id` передан (артефакт `audio/*`), он заменяет звук целиком:
   видео-часть собирается без аудио клипов, дорожка обрезается по длине видео
   (`apad` + `-shortest`).
5. **Исходники неприкосновенны.** Блобы клипов только читаются, сборка идёт во временный
   каталог; `sha256` исходников до и после совпадают. Сбой ffmpeg — 500, исходные
   попытки и MP4 не меняются.

### 4.9. Ревью видео-попытки и мониторинг job (WP-M1)

1. **Писатель `shots.approved_attempt_id`.** Единственный путь — идемпотентный
   `POST /api/shots/{shot_id}/attempts/{attempt_id}/approve`: только `kind='video'`,
   только `status='completed'`, только попытка своего шота; выставляет
   `Shot.status='approved'`. Стартовый кадр (`start_keyframe_*`) не затрагивается (S9).
2. **Отклонение.** `POST .../reject` ставит `Shot.status='changes_requested'` и не удаляет
   артефакт. Если отклоняется ранее утверждённая попытка, `approved_attempt_id`
   снимается — иначе в данных остался бы «утверждённый» отклонённый дубль. Это
   осознанное уточнение формулировки roadmap («не меняется»); `enum Shot.status` не
   расширялся.
3. **Мониторинг.** `GET /api/jobs/{job_id}/events` — только чтение журнала `events`
   (sequence, event, stage, progress, payload); `GET /api/jobs/{job_id}` дополнен
   аддитивным `last_event`. В UI прогресс подписывается как «этап», а не как процент
   модели; для завершённой job stage не показывается.
4. Миграций нет: провенанс попытки (`workflow_version`, `model_hash`, `seed`,
   `duration_s`, параметры рендера) уже существовал в `render_attempts`.

### 4.10. Music timeline и производственный план (WP-M3)

1. **Песня проекта.** Миграция `0010_audio_timeline_plans` добавляет
   `projects.audio_artifact_id` (nullable, FK `artifacts.id`,
   `fk_projects_audio_artifact`). Один трек на проект: `POST /api/projects/{id}/audio`
   привязывает уже загруженный артефакт (404 — артефакта нет, 409 — не `audio/*`),
   `GET /api/projects/{id}/audio` отдаёт длительность по ffprobe. Блобы не копируются,
   артефакт остаётся `source='upload'`, `kind='project_audio'`.
2. **Таймлайн — локальная эвристика.** `app/audio_timeline.py` декодирует трек через
   FFmpeg в `s16le` 4 кГц моно, строит RMS-огибающую 100 Гц, автокорреляцией оценивает
   BPM 60…200 и `bpm_confidence`, по фазе ставит биты, каждый 4-й — `downbeat`
   (размер 4/4 предполагается), секции выделяются по энергии тактов (до 12,
   `energy_tier` low/mid/high). Новых библиотек анализа (librosa и подобных) нет.
   Неуверенность не блокирует: при `confidence < 0.35` — warning `low_bpm_confidence`,
   без ритма — `bpm=null` и warning `beats_not_detected`.
3. **Таблица `production_plans`.** `project_id`, `revision`, `schema_version`, `status`,
   `source`, `audio_artifact_id`, `timeline`/`plan` JSONB NOT NULL, `warnings` JSONB
   DEFAULT `'[]'`, UNIQUE `(project_id, revision)`, CHECK на `revision>=1`,
   `schema_version>=1`, `status IN ('draft','superseded')`,
   `source IN ('llm','manual','fallback')`, индекс `ix_production_plans_project_created`.
   Downgrade удаляет таблицу и колонку.
4. **Генерация.** `POST /api/projects/{id}/production-plans/generate` (`brief?` до 2000,
   `use_llm`): сначала серверный каркас из секций таймлайна (сцена = секция, шоты
   дробятся по долям), затем Ollama structured output (`format=json`, `temperature=0`)
   в `app/production_plan.py`. Тайминги модели игнорируются — в плане всегда серверные
   границы. Ответ проверяется Pydantic (`extra="forbid"`) и `validate_plan`; при провале
   — не более `planner_max_repair` (2) переспросов с текстом ошибки, затем `fallback`
   (каркас + `needs_review=true`). `source`: `llm` — принят план модели, `manual` —
   `use_llm=false`, `fallback` — модель недоступна или ответ не принят. Коды
   предупреждений: `plan_repair`, `plan_invalid`, `plan_model_unavailable`,
   `plan_llm_disabled`, `plan_section_ignored`, `plan_scene_defaulted`.
5. **Только черновики.** Ревизия = `max+1`; предыдущие `draft` при создании становятся
   `superseded`. Утверждение плана, применение к `scenes`/`shots`/`prompt_revisions` и
   запись в `events` в WP-M3 не входят: сцены, шоты и approved-записи не меняются.
   Список — `GET /api/projects/{id}/production-plans` (ревизии по убыванию), деталь —
   `GET /api/production-plans/{id}`.
6. **UI.** `#/plan`: песня (загрузка и плеер), таймлайн (длительность, BPM с
   уверенностью, размер, полоса секций), генерация с `brief`/`use_llm`, черновик плана и
   список ревизий.
7. **Живая проверка 2026-11-04** (проект NLB): синтетический клик-трек 24.03 с → BPM 60.0,
   уверенность 0.91, 24 бита, одна секция `high`; `use_llm=false` → ревизия 1 `manual`;
   `gemma3:4b` → ревизия 2 `llm` за ~21 с после двух `plan_repair` (первый ответ вернул
   неверный корень JSON), ревизия 1 стала `superseded`. Трек с импульсами каждые 0.5 с
   модель отсчитала как half-tempo (60 вместо 120): эвристика допускает полу- и двойной
   темп, поэтому `bpm_confidence` — не гарантия темпа, границы проверяются человеком.

### 4.11. Восстановление рендера после рестарта воркера (WP-M4)

1. **Внешний id.** `POST /api/worker/jobs/{job_id}/external` (`worker_name`,
   `external_id`) сохраняет `prompt_id` ComfyUI в существующую колонку
   `jobs.external_id`; миграций нет. Нужен lease этого воркера и активный статус
   (`leased`/`running`/`lease_expired`); повтор с тем же id идемпотентен, другой id —
   409 `external_id_conflict`. Нового события нет: `EVENT_NAMES` и `ck_events_event`
   не расширялись, факт виден в `jobs.external_id` и в ответе `resume`.
2. **Очистка.** `complete` и `fail` сбрасывают `external_id` — id относится только к
   текущему рендеру. `lease_expired` его не сбрасывает: именно он нужен для
   восстановления.
3. **State-файл воркера.** `~/.mary-studio/ltx-worker-state.json` (переопределяется
   `--state-file` или `MARY_WORKER_STATE`): `job_id → {prompt_id, attempt_id,
   native_fps, workflow_version, model_hash, seed, parameters}`. Запись атомарная
   (`.tmp` + `os.replace`) сразу после `/prompt` и до ожидания; удаляется после
   успешных `complete`/`fail`. Если `complete`/`fail` не дошли до сервера, запись
   остаётся до следующего старта. State-файл — **best-effort**: недоступный каталог
   или отказ `POST /external` дают предупреждение в stderr, но не прерывают уже
   поставленный рендер (источник истины — `jobs.external_id` на сервере).
4. **Восстановление при старте.** `POST /api/worker/resume` → job'ы с `external_id`
   (или только с локальной записью) → `heartbeat` (возвращает job и после
   `lease_expired`) → `GET /history/{prompt_id}`. Запись есть — MP4 скачивается,
   проверяется ffprobe, загружается артефактом, job завершается `complete` без
   повторного `/prompt`. Записи нет, но prompt в `/queue` — воркер ждёт завершения с
   heartbeat'ами (ComfyUI продолжает рендер после падения воркера); `/queue`
   перепроверяется на каждом опросе, поэтому prompt, исчезнувший из очереди во время
   ожидания, тоже считается потерянным. Prompt'а нет ни в `/history`, ни в `/queue` —
   `fail` с `error_code=external_prompt_lost`, `retryable=true`: job вернётся в
   `retry_wait` и отрендерится заново штатно.
5. **Провенанс восстановленной попытки.** `workflow_version`, `model_hash`, `seed`,
   `native_fps` и `parameters` берутся из state-файла, добавляются `recovered=true` и
   `prompt_id`. Если state-файла нет (удалён вручную), попытка завершается без этих
   полей, но с `recovered=true`.
6. **Устаревшие записи.** На старте записи о job'ах, которых нет в ответе `resume`,
   удаляются: сервер уже не считает их задачами этого воркера.

### 4.12. Список и сравнение попыток проекта (WP-M5)

1. **Выборка.** `GET /api/projects/{project_id}/attempts` — аддитивный эндпоинт чтения,
   миграций нет. Элемент списка — поля `AttemptOut` (включая то же подмножество
   `render_parameters` без `workflow_snapshot`) плюс `shot_id`, `shot_sequence_no`,
   `scene_id`, `scene_title`, `shot_status`, `approved`.
2. **Фильтры.** `scene_id`, `shot_id`, `kind` (`keyframe`/`video`/`postprocess`),
   `status`; по умолчанию фильтры пустые — видны все типы попыток. Неизвестный
   `kind`/`status` — 422; `scene_id`/`shot_id` чужого проекта — 404, а не пустая
   страница.
3. **Пагинация.** Ответ — страница `items/total/limit/offset`: `limit` 1…100
   (по умолчанию 50), `offset` ≥ 0, сортировка `created_at desc, id desc`; `total`
   считается тем же набором условий без `limit`/`offset`.
4. **«Сделать текущей» = approve.** UI не вводит нового писателя: кнопка вызывает
   существующий `POST /api/shots/{shot_id}/attempts/{attempt_id}/approve` (WP-M1),
   поэтому `approved_attempt_id` и `Shot.status='approved'` меняются по тем же правилам
   (только `kind='video'`, только `status='completed'`, обязателен артефакт,
   идемпотентно). Флаг `approved` в списке — вычисление из `shots.approved_attempt_id`,
   а не новое поле БД.
5. **Сравнение.** Side-by-side доступно только для двух завершённых видео-попыток
   с артефактом; список при этом показывает и `keyframe`/`postprocess`.
6. **Границы.** Эндпоинт только читает; артефакты, попытки, approved-записи и стартовые
   кадры не меняются.

### 4.13. Голос персонажа и многоракурсная карточка (WP-M6)

1. **Хранение голоса.** Голосовой образец — строка `reference_assets` с `role='voice'`,
   `kind='character_reference'`, `status='draft'`; миграции нет (`role` — существующий
   свободный `Text`). Approve/reject и иммутабельность approved (S15) переиспользуются без
   нового кода. Голос в рендере не участвует и стартовым кадром быть не может.
2. **Эндпоинт.** `POST /api/characters/{character_id}/voice` — тело запроса: сырые байты
   файла, тип из `Content-Type`: `audio/mpeg`/`audio/mp3` (mp3), `audio/wav`/`audio/x-wav`/
   `audio/wave` (wav), `audio/mp4`/`audio/x-m4a` (m4a), `audio/aac`; иначе 422. Лимит размера
   — `voice_upload_max_bytes` (16 МиБ). Дедупликация по `sha256` внутри проекта: повтор для
   того же персонажа — 200 (идемпотентно), для другого владельца — 409 `duplicate_reference`.
3. **Проверка файла.** ffprobe (`probe_audio`): аудиодорожка обязательна; длительность
   ≤ `voice_max_duration_s` (30 с), иначе 422. `duration_s` (3 знака) пишется в
   `metadata` референса и возвращается в `ReferenceOut.duration_s`.
4. **Многоракурсная карточка.** Флаг `multi_view` живёт в `reference_assets.metadata` —
   схема БД не меняется; выставляется через существующий `PATCH /api/reference-assets/{id}`
   (только `draft`/`rejected`, S15 не ослаблен), читается в `ReferenceOut.multi_view`;
   UI — чекбокс в лайтбоксе референса.
5. **Запрет стартового кадра.** `keyframe` из референса отклоняет (409) два случая:
   файл не изображение (`mime_type` не `image/*`, в том числе голос) и `multi_view=true`.
   Слои композиции и пикер референсов на шоте отфильтровывают не-изображения.
6. **UI.** На карточке персонажа — раздел «Голос»: загрузка файла, `<audio>`, длительность,
   статус и approve/reject. Голосовые референсы не попадают в сетку изображений.
   Синтез речи не выполняется.

### 4.14. Пресеты рендера под оборудование (WP-M7)

1. **Только измеренные пресеты.** В таблицу `backend/app/presets.py` попадают режимы,
   подтверждённые реальными прогонами: `safe` (576×1024, 24 шота «NLB-single», в среднем
   1062,5 с), `wide` (1024×576, 3 шота «NLB-single wide (28-30)») и `legacy_512`
   (512×512/73/24, один прогон WP-00A). У каждого — флаг `measured` и `measured_runs`.
   «Balanced»/«Quality» без замеров не создаются; обещания ускорения без benchmark
   запрещены.
2. **Детект железа.** Только stdlib и системные утилиты macOS: `platform.system()`/
   `platform.machine()`, `sysctl -n hw.memsize|hw.model|machdep.cpu.brand_string`,
   `vm_stat` (доступная память = free + inactive + speculative страницы). Новых
   зависимостей нет (`psutil` не добавляется), CUDA/NVML не используются.
3. **Рекомендация.** `recommend()` возвращает `safe` только для Apple Silicon с памятью
   ≥ 16 ГиБ; иначе — `None` и причина (нет Apple Silicon / память не определена /
   меньше 16 ГиБ). Не-Apple Silicon помечается `control_plane_only=true`.
4. **Эндпоинт.** `GET /api/presets` — аддитивный read-only ответ: `hardware`, `presets`,
   `recommended`, `reason`. Схема БД не меняется, миграций нет.
5. **Приоритет в воркере.** `--aspect-ratio`/`--long-side`/`--cfg-scale` важнее API
   (источник `cli`), затем рекомендация `GET /api/presets` (источник `api`), затем
   встроенные умолчания (источник `default`). При недоступном API — предупреждение в
   stderr и работа на встроенных значениях; `--no-preset` отключает запрос, `--preset`
   выбирает именованный пресет из ответа API.
6. **Провенанс.** Фактические `preset` и `preset_source` пишутся в существующие
   `render_attempts.parameters` вместе с `aspect_ratio`/`long_side`/`cfg_scale`; схема
   БД не меняется.

### 4.15. Интерфейс lip sync без движка (WP-M8)

1. **Только интерфейс.** Условия запуска реального движка не выполнены (MLX-совместимая
   модель не выбрана, лицензии весов и голоса не проверены, согласия на голос нет,
   память на 18 ГиБ не измерена), поэтому реализуется адаптер, а не движок. Веса, TTS,
   внешние сервисы и новые зависимости не добавляются.
2. **Адаптер.** `backend/app/lipsync.py`: `LipsyncEngine`, `SELECTED_ENGINE = None`,
   `LipsyncUnavailable` с кодами `lipsync_engine_not_selected` /
   `lipsync_engine_not_implemented`, точка входа `request_lip_sync()`. Legacy-заглушки
   `pipeline/stages/lipsync.py` и `pipeline/stages/voices.py` (Hedra/ElevenLabs) не
   затрагиваются — это отдельный старый episode-пайплайн.
3. **Эндпоинт.** `POST /api/shots/{shot_id}/lipsync`: 404 для несуществующего шота,
   409 с `detail='lipsync_engine_not_selected'` для валидного. В БД ничего не пишется,
   job не создаётся, схема БД не меняется, миграций нет.
4. **UI.** Панель «Озвучка / Lip sync» на карточке шота показывается только при
   `VITE_FEATURE_LIPSYNC=true` (по умолчанию выключена): поля «реплика», «аудио»,
   «персонаж», «голос» в disabled-состоянии с объяснением. Запрос к API из UI не
   отправляется, пока движок не выбран.

### 4.16. Thermal-safe планировщик рендера (WP-THERMAL-02)

Основание: `docs/OPEN_QUESTIONS.md` Q-27…Q-35, аудит
`docs/PROPOSALS/THERMAL_RENDER_AUDIT.md`, проект
`docs/PROPOSALS/THERMAL_SAFE_SCHEDULER.md`. Схема БД, миграции, пресеты и
production-параметры рендера не меняются.

1. **Источник теплового состояния (Q-27).** Единственный источник — Swift-helper
   `scripts/mac_thermal_state.swift` на `ProcessInfo.processInfo.thermalState`, сборка
   `swiftc` в `~/.mary-studio/bin/mary-thermal-state` (бинарник вне Git). Значения
   `nominal`/`fair`/`serious`/`critical`; ошибка запуска, таймаут или нераспознанный
   вывод → `unknown`. `pmset -g therm` источником `nominal` не считается: живых
   показаний он не отдаёт. Воркер опрашивает helper каждые `thermal_poll_seconds`
   (по умолчанию 60 с) и обновляет снимок состояния; во время рендера — не реже
   одного раза в `thermal_poll_seconds`.
2. **Серверный guard (Q-28).** `POST /api/worker/claim` выдаёт `render_video` только
   если нет другого `render_video` в статусе `leased`/`running`. Проверка — в той же
   транзакции, что и `_CLAIM_SQL`, под `pg_advisory_xact_lock(hashtext(
   'mary_studio:render_video_guard'))`; одного `NOT EXISTS` недостаточно: при
   READ COMMITTED два параллельных claim видят пустое множество и оба получают lease.
   `lease_expired` guard не блокирует: владелец lease утрачен, очередь восстанавливается
   через `resume` (WP-M4), а не через запрет новых claim. `series_next` при активном
   чужом рендере возвращает `{"status": "busy"}` и job не создаёт.
3. **Read-only статус (Q-29).** `GET /api/render-agent/status` читает снимок
   `~/.mary-studio/thermal-state.json`, хвост `thermal-events.jsonl` и очередь из БД.
   Обязательные поля свежести: `updated_at`, `age_seconds`, `stale`
   (`render_agent_stale_seconds`, по умолчанию 180 с). Нет файла → `worker_online=false`,
   `thermal.state="unknown"`. Управления очередью и записи через эндпоинт нет.
4. **Пороги (Q-30).** Eco: питание от сети, `kern.memorystatus_vm_pressure_level=1`,
   свободная память ≥ 4 ГиБ. Работа от батареи допускается только с `--allow-battery`
   и зарядом ≥ 50 %, иначе `battery_low`. Нехватка памяти или переход на батарею —
   пауза воркера (без новых job), а не завершение процесса и не `fail` job; текущий
   рендер досчитывается.
5. **caffeinate (Q-31).** `caffeinate -i -w <pid воркера>` запускается на время шага
   рендера и завершается в `finally`; `-w` гарантирует выход при падении воркера,
   orphan-процессов не остаётся. Отключается `--no-caffeinate`. `launchd` — отдельный этап.
6. **Профиль (Q-32).** `--thermal-profile off|balanced|eco` (env `MARY_THERMAL_PROFILE`),
   по умолчанию `balanced`; значение читается только при старте воркера. Нового write
   API и новых состояний в БД нет, динамическое переключение из UI — позже.
7. **Границы Eco (Q-33).** Eco не меняет `long_side`, `num_frames`, `cfg_scale`, seed и
   не включает `low_ram`; он управляет допуском, паузами и cooldown (480 с между
   шотами, 1200 с после партии из 3). `low_ram` — только после энергетического теста Q-38.
8. **Preview (Q-34).** Признак preview — `render_attempts.parameters.preview=true`,
   `kind` остаётся `video`, миграции нет; preview не заменяет утверждённый production
   render. В WP-THERMAL-02 preview-путь не реализуется (нет изменения параметров
   рендера); решение зафиксировано для отдельного WP preview-first.
9. **Журнал (Q-35).** `~/.mary-studio/thermal-events.jsonl`, фиксированный набор полей
   (`ts`, `event`, `profile`, `worker`, `thermal`, `power`, `memory`, `reason`,
   `job_id`), лимит размера `thermal_log_max_bytes` (5 МиБ) и `thermal_log_backups` (2)
   с ротацией `*.1`, `*.2`. Имена событий таблицы `events` не расширяются
   (`ck_events_event`), поэтому thermal-события живут только в JSONL.

---

### 4.17. Стабилизация thermal-защиты и preview-first (WP-THERMAL-03)

Основание: WP-THERMAL-03 «Stabilization, Thermal Validation & Production Readiness»,
`docs/OPEN_QUESTIONS.md` Q-32…Q-34, `docs/PROPOSALS/THERMAL_SAFE_SCHEDULER.md` §8–§13,
`docs/PROPOSALS/THERMAL_RENDER_AUDIT.md`. Схема БД, миграции, пресеты и
production-параметры рендера не меняются. Реальные GPU-прогоны в этом WP не выполнялись,
кроме одного контролируемого Eco acceptance теста NLB-25 по разрешению Q-41 (п.10).

1. **T-06, профиль в настройках рендера.** `RenderSettings` получил поле
   `thermal_profile` (по умолчанию `balanced`); значение приходит из CLI
   `--thermal-profile` / env `MARY_THERMAL_PROFILE` и передаётся в `_build_thermal_gate`
   явно, а не читается из `args` в момент сборки. Профиль по-прежнему управляет только
   допуском, паузами и cooldown; `long_side`, `num_frames`, `fps`, `seed`, `cfg_scale`
   и workflow не меняются. Профиля `Performance` в коде нет.
2. **Low Power Mode — только чтение.** `pmset -g` парсится в `low_power_mode: bool | None`
   (`parse_low_power_mode`); отсутствие источника или нераспознанное значение → `None`
   (Unknown). Поле аддитивно добавлено в `power` ответа `GET /api/render-agent/status`,
   в `render_attempts.parameters.thermal.low_power_mode` и в `thermal-state.json`.
   Глобальные настройки macOS не изменяются, `pmset` не вызывается с записью.
3. **Горячее состояние фиксируется сразу после job.** `ThermalGate.after_job` пишет
   снимок с `admission.allowed=false` и `reason=thermal_<serious|critical>`, если
   измерение после рендера уже горячее; пауза взводится в том же вызове. Раньше снимок
   до следующего опроса мог содержать `allowed=true`, и UI показывал ложный допуск.
4. **Ожидание thermal-допуска ограничено.** `--thermal-max-wait` (по умолчанию 6 ч)
   прекращает молчаливое ожидание: `_wait_for_admission` возвращает управление,
   `_job_loop` завершается с кодом 1, причина печатается и отправляется баннером.
   Это не завершает и не отменяет активный рендер.
5. **T-07, preview-first.** `POST /api/shots/{id}/render` принимает необязательное тело
   `{"preview": true}` (схема `ShotRenderRequest`); при preview в payload job пишутся
   `preview=true` и `frames=73` (`PREVIEW_FRAMES`), в `RenderAttempt.parameters` —
   `preview=true`, в ответе `RenderQueuedOut` — `preview`. Preview — отдельная
   `RenderAttempt` с `kind='video'`, она не заменяет production-артефакт и не меняет
   утверждённый стартовый кадр, seed, разрешение и workflow. 73 кадра (3.04 с при 24 fps)
   выбраны вместо проектных 41–49 как уже проверенная в WP-00A конфигурация.
6. **Preview нельзя утвердить автоматически или вручную.** `POST /api/shots/{id}/attempts/
   {attempt_id}/approve` для preview-попытки возвращает 409 `preview_cannot_be_approved`;
   `reject` остаётся доступным. UI показывает бейдж `preview` и не предлагает approve и
   «Сделать текущей» (в том числе в сравнении попыток).
7. **UI-панель «Термозащита».** На `#/series/{id}` показываются энергопрофиль, thermal
   state, источник питания, Low Power Mode, memory pressure, партия, очередь, допуск,
   cooldown, время до следующего задания и причина блокировки — в том числе вне паузы.
   Неизвестные значения выводятся как `Unknown`, прочерк `—` не используется; температура,
   мощность GPU и процент загрузки не синтезируются. Значения причин человекочитаемы
   (`thermal_serious` → «перегрев (Serious)»), неизвестная причина показывается как есть.
8. **Проверка UI.** Панель проверена на живом backend с временным снимком состояния
   (`MARY_RENDER_AGENT_STATE_PATH`/`MARY_RENDER_AGENT_EVENTS_PATH` указывали на `/tmp`,
   production-файлы `~/.mary-studio/*` не перезаписывались). В acceptance-прогоне
   долгоживущий воркер не смог писать production state/log из-за sandbox, поэтому
   `/api/render-agent/status` во время рендера отдавал `worker_online=false`;
   телеметрия сохранилась в `render_attempts.parameters`.
9. **Границы.** Новых миграций, эндпоинтов статуса, очередей, моделей и зависимостей нет.
   `export/` добавлен в `.gitignore` (≈241 МБ MP4 не отслеживаются, файлы не удалялись и
   не перемещались). `launchd` не устанавливается: предложение — раздел 9 в
   `docs/REPORTS/WP_THERMAL_03_REPORT.md`.
10. **Acceptance-прогон (2026-11-04).** Один Eco-рендер NLB-25 (`safe` 576×1024/193/24,
    seed `950087778`) и тест Thermal Pause (`thermal_serious` → `paused` → `resume` →
    `completed`) прошли; production-параметры и approved-записи не менялись.
    `peak_mem_mb=16295`, `min_available_mb=2137`, `max_pressure_level=4` — гейт проверяет
    память только до job, это зафиксированный риск. Cooldown 480 с выставляется, но
    live-проверка допуска после рендера дала `power_not_ac` (ноутбук был на батарее).
    Детали — `docs/REPORTS/WP_THERMAL_03_TEST_RESULTS.md` §5 и
    `docs/PROPOSALS/THERMAL_GPU_ACCEPTANCE_PLAN.md` §8. Решение о серии из 30 роликов
    этим пунктом не принимается.

### 4.18. Talking Character MVP: `mouth_animation_mvp` (WP-VOICE-02)

Основание: WP-VOICE-02 «Universal Audio Import & Talking Character MVP»,
`docs/PROPOSALS/WP_VOICE_02_MOUTH_ANIMATION.md`. Готовые записи пользователя,
без TTS, ElevenLabs, облачных API, LTX и ComfyUI. GPU не используется.

1. **Режим и честность названия.** Новый режим — `mouth_animation_mvp`
   (`parameters.mode`). Это приблизительная анимация рта по громкости, **не**
   phoneme-accurate lip sync; ограничение записывается в
   `parameters.limitation` и показывается в UI. Существующий lip sync API сохранён:
   `backend/app/lipsync.py` по-прежнему `SELECTED_ENGINE = None`, фиктивный ML-движок
   не подставляется.
2. **Источник кадра — только approved-изображение.** Либо approved-референс,
   привязанный к шоту, либо утверждённый стартовый кадр (`shots.start_keyframe_*`).
   Калибровка и генерация не меняют approved-референс, артефакт и стартовый кадр.
3. **Video Talking — Not Supported.** Надёжного tracking морды в проекте нет, поэтому
   видео-источник отклоняется кодом `video_talking_not_supported`; статичная маска на
   движущееся видео не накладывается, тяжёлые tracking-модели не устанавливаются.
   UI показывает режим как `Not Supported` и предлагает image-режим.
4. **Движок.** Чистый Python + Pillow, без новых зависимостей. Кривая раскрытия:
   RMS-огибающая 50 Гц → окно кадра → порог тишины 6 % от пика → `sensitivity` →
   однополюсный attack/release с разными коэффициентами → deadband 0.03 →
   `max_open`. В тишине раскрытие ровно 0, случайных движений нет; одинаковые вход и
   калибровка дают одинаковые кадры и MP4-структуру. Кадр с закрытым ртом — точная
   копия источника.
5. **Сборка результата.** FFmpeg: h264 (`yuv420p`) + исходная запись как `aac`,
   `-shortest`, `+faststart`, 24 fps (`mouth_animation_fps`), длинная сторона ≤ 1080
   (`mouth_animation_max_side`), чётные стороны для `yuv420p`. Исходная запись и
   изображение только читаются.
6. **Контракт без миграции.** Генерация синхронная и локальная, но результат проходит
   штатный жизненный цикл: `Job(kind='mouth_animation', status='completed')` +
   `RenderAttempt(kind='video', parameters.mode='mouth_animation_mvp')` +
   `Artifact(source='attempt', kind='talking_preview', mime='video/mp4')`. `jobs.kind`
   не имеет CHECK, новых таблиц jobs нет; guard одного активного рендера относится только
   к `kind='render_video'`, GPU-воркер выбирает `kinds` явно и эту job не увидит.
7. **Review — только человек.** Talking Preview — обычная завершённая видео-попытка:
   approve/reject идут существующими `POST /api/shots/{id}/attempts/{attempt_id}/
   approve|reject`, `approved_attempt_id` пишет только они. Автоматического утверждения
   нет; стартовый кадр и approved-записи не меняются.
8. **Блокировки вместо пустого MP4.** `POST /api/shots/{id}/mouth-animation` возвращает
   типизированные 409: `audio_required`, `audio_not_approved`, `source_image_required`,
   `source_reference_not_approved`, `reference_not_linked`, `video_talking_not_supported`,
   `calibration_required`, `calibration_source_mismatch`, `mouth_region_out_of_bounds`.
   При отсутствии записи/кадра/калибровки попытка, job и MP4 не создаются.
9. **Калибровка.** Хранится в `mouth_calibrations` (S20), одна запись на пару «шот,
   источник»; предпросмотр закрытого/открытого рта — PNG без записи в БД
   (`Cache-Control: no-store`). Параметры: X/Y/W/H (доли кадра), rotation, max_open,
   sensitivity, smoothing.
10. **UI.** В Shot Editor — панель «Озвучка»: Import Audio, Audio Library, play, select,
    Approve Audio, Calibrate Mouth с оверлеем области, предпросмотр закрытого/открытого
    рта, waveform, Talking Preview и результат со ссылкой на существующий блок «Попытки».
    Пока запись не выбрана и не утверждена, кнопка генерации заблокирована с понятной
    причиной.
11. **Границы.** LTX, ComfyUI, TTS, облачные API и тяжёлые ML-модели не используются;
    NLB не изменялся; commit/push не выполнялись.

### 4.19. Импорт и подготовка готового аудио шота (WP-VOICE-02)

Основание — то же, что §4.18. Новых таблиц и второго storage нет.

1. **Хранение.** Запись — `reference_assets(kind='uploaded', role='shot_audio')`,
   привязка к шоту — `shot_references(purpose='other')`. Дедуп по
   `UNIQUE(project_id, sha256)`. Approve/reject — существующие эндпоинты
   `POST /api/reference-assets/{id}/approve|reject`; «выбранная» запись — самая свежая
   approved. Замена записи — approve новой; старая остаётся в библиотеке (S15).
2. **Приём файла.** `POST /api/shots/{id}/audio`: WAV, MP3, M4A, AAC по `Content-Type`
   (список в `AUDIO_MIME_SUFFIX`), лимит `shot_audio_upload_max_bytes` (32 МиБ) и
   `shot_audio_max_duration_s` (120 с), необязательные `X-Content-SHA256` и
   `X-Original-Name`. Размер ограничивается до чтения тела (`read_body_with_limit` → 413).
3. **Подготовка.** Реальный формат определяется `ffprobe`, а не расширением: должен быть
   аудиопоток и положительная длительность. Оригинал кладётся в content-addressed storage
   побайтно без изменений; рядом создаётся рабочая копия PCM16 48 кГц mono. Автоматической
   нормализации с потерей динамики нет.
4. **Метаданные.** `duration_s`, `sample_rate`, `channels`, `codec`, `format_name`,
   `original_name`, `work_storage_key`, `work_sha256`, `work_sample_rate`,
   `work_channels`, `envelope_rate_hz`, `envelope` (50 Гц), `gate`, `peak_rms`,
   `speech_segments`, `silence_segments`, `speech_ratio`.
5. **Чтение.** `GET /api/shots/{id}/audio` — библиотека с флагом `selected`;
   `GET /api/shots/{id}/audio/{asset_id}/waveform?buckets=16…2000` — пики из metadata,
   при их отсутствии — пересчёт из рабочей копии.
6. **Идемпотентность.** Повторная загрузка того же файла в тот же проект возвращает
   существующий ассет (200) и при необходимости создаёт недостающую привязку к шоту;
   тот же sha256 с другой ролью — 409 `duplicate_reference`.
7. **Границы.** Новых очередей и pipeline нет; запись не запускает рендер и не меняет
   шот. Тестовые записи в рабочем проекте не создаются.

### 4.20. Движок рта v2: закрытие в паузах и мягкая маска (WP-VOICE-04)

Основание: WP-VOICE-03 (первый живой Talking Preview, `docs/REPORTS/WP_VOICE_03_REPORT.md`,
дефекты 1–5) и решение человека «фиксировать как есть, идти дальше». Контракт API,
таблицы и очередь не меняются; S20 не затрагивается.

1. **Версии.** `parameters.engine = "pillow_mouth_v2"`,
   `workflow_version = "mouth_animation_mvp_v2"`; режим остаётся `mouth_animation_mvp`.
   Старые попытки и MP4 не перезаписываются и не пересчитываются.
2. **Кривая.** В дополнение к §4.18 п.4: непрерывная тишина ≥ 0.08 с
   (`SILENCE_CLOSE_S`) закрывает рот принудительно (`openness = 0`), release
   ускорен (`max(0.08, base·(1 − 0.35·smoothing))`). Короткие паузы 0.12–0.2 с
   больше не оставляют приоткрытый рот.
3. **Маска.** Верх скруглённого прямоугольника фиксирован на линии рта (центр
   области), раскрытие идёт вниз; высота `rh·(0.10 + 0.55·norm)`, ширина `0.9·rw`,
   радиус скругления `0.4·min(w,h)`; край размывается (feather `0.12·open_height`),
   плотность `0.45 + 0.55·norm`. Глаза и нос не затрагиваются, если область задана
   корректно.
4. **Длительность и метаданные.** Вместо `-shortest` — `-af apad` и `-t` по длине
   кривой: хвост записи не срезается; `parameters.frames` берётся из фактической
   длительности MP4 (ffprobe), а не из длины кривой.
5. **Калибровка.** Геометрия GNS-05 обновляется существующим upsert
   `POST /api/shots/{id}/mouth-calibrations` (тот же `id`, без миграций); approved-
   изображение и стартовый кадр не меняются.
6. **Review.** Автоматического утверждения нет; новый Preview — обычная видео-попытка.
7. **Границы.** LTX, ComfyUI, GPU, TTS и облачные API не используются; миграций нет;
   NLB не изменялся; commit/push не выполнялись.

---

### 4.21. Фотографические viseme-кадры: `viseme_frame_blend_v1` (WP-VOICE-06)

Основание: WP-VOICE-05 (`docs/PROPOSALS/LIPSYNC_ENGINE_EVALUATION.md`, отказ от
pixel-level генеративного lip sync в пользу готовых кадров морды) и задание
WP-VOICE-06 Revised. Миграций нет: набор хранится в существующих таблицах.

1. **Хранение набора.** Пять `reference_assets(kind='uploaded', role='viseme_<state>')`,
   привязанных к шоту через `shot_references(purpose='other')`; `closed` может быть
   неявно взят из approved-источника (`reference_asset_id` или keyframe-артефакт).
   `metadata_json` содержит `viseme_set=true` и `viseme_state`; статус нового кадра —
   `draft`, `approved` ставит только человек. Approved-источник не перезаписывается.
2. **Импорт.** `POST /api/shots/{id}/viseme-set/{state}` (сырое тело, PNG/JPEG,
   ≤ 32 МиБ) и `GET /api/shots/{id}/viseme-set` (отчёт), `GET …/viseme-set/preview`
   (PNG-лист сравнения). Дедуп по `sha256` в проекте: тот же файл в другой роли →
   409 `duplicate_reference`.
3. **Проверка совместимости** (`backend/app/viseme_assets.py`, PIL без numpy):
   разрешение, сдвиг головы (поиск по сетке ±8 px вне области морды с порогом
   улучшения 0.5), изменения вне морды ≤ 1 %, `closed` совпадает с источником ≤ 1 %,
   заметная артикуляция ≥ 0.5 %, риск мерцания между вариантами ≤ 1 %. Блокеры:
   `viseme_set_incomplete`, `viseme_set_not_approved`, `viseme_resolution_mismatch`,
   `viseme_head_shift`, `viseme_outside_mouth_changes`, `viseme_closed_mismatch`,
   `viseme_no_articulation`, `viseme_flicker_risk`.
4. **Движок `viseme_frame_blend_v1`** (`backend/app/viseme_blend.py`): кадр не
   рисуется маской — патч области морды берётся из реальных изображений набора;
   остальные пиксели — из approved-источника. Переходы: сглаживание весов с
   постоянной времени `blend_ms` (по умолчанию 60 мс), на кадре не более двух
   изображений; виземы короче `min_hold_ms` (60 мс) отбрасываются; паузы из
   `shot_audio` закрывают рот. FFmpeg: h264 `veryfast`/`crf 20`, `yuv420p`,
   AAC 192k, `apad` + `-t`, `+faststart`; результат обязан пройти `probe_mp4`
   с аудиодорожкой.
5. **Генерация.** `POST /api/shots/{id}/mouth-animation` с
   `engine='viseme_frame_blend_v1'`; при неготовом наборе — 409 `viseme_set_blocked`
   с `missing`/`blockers` **до** создания Job/RenderAttempt. Тайминги: `timing` в теле
   (`timing_source='payload'`) либо `use_rhubarb`; без них — 409
   `viseme_timing_required`; невалидные — 422 `viseme_timing_invalid`. Результат —
   обычная видео-попытка (`workflow_version='viseme_frame_blend_v1'`), review и
   `approve` — существующими эндпоинтами; автоутверждения нет.
6. **Rhubarb 1.14.0 — только опциональный адаптер.** `backend/app/rhubarb.py`
   проверяет наличие бинарника, бит исполнения, каталог `res/` рядом с ним,
   архитектуру (`file -b`) и SHA-256 из `MARY_RHUBARB_SHA256`; при пустой настройке —
   `rhubarb_sha256_not_pinned`. Официальная сборка macOS v1.14.0 — `x86_64`
   (arm64-релиза у проекта нет): `arm64` принимается как есть, `x86_64` — только при
   доступной Rosetta 2, с `rosetta: true` и пометкой
   `notes[code='rhubarb_runs_under_rosetta']`; SHA-256 остаётся обязательным и строгим.
   Вход — только `.wav`/`.ogg` (`rhubarb_input_unsupported` иначе), временный JSON
   пишется вне `storage/`. Read-only `GET /api/rhubarb/status`
   (`download_performed=false`). Скачивание, установка и любые сетевые запросы
   не выполняются без отдельного разрешения.
7. **Legacy.** `mouth_animation_mvp` / `pillow_mouth_v2` сохранён без изменения
   поведения и выбирается по умолчанию; старые попытки и MP4 не перезаписываются.
8. **Границы.** Схема БД, очередь и enum-ы не менялись; LTX, ComfyUI, GPU и TTS не
   использовались; NLB не изменялся; commit/push не выполнялись.

---

### 4.22. Заморозка экспериментальной анимации рта и статус lip sync (WP-STABILIZE-01)

Основание: решения владельца D1–D4 от 2026-11-05, `docs/REPORTS/WP_VOICE_06_REPORT.md`
§10/§12 и аудит `docs/AUDITS/PROJECT_AUDIT_2026_11.md`. Миграций нет, approved-записи
и история попыток не переписываются.

1. **Сборка B отклонена как производственный результат.** Попытка
   `3eb3ca9f…` (artifact `a5326a3f…`, `workflow_version='viseme_frame_blend_v1'`)
   не принята: видна прямоугольная граница патча, освещение viseme-кадров не совпадает
   с `closed.png`. Видео, `render_attempts` и артефакт сохраняются как история A/B;
   `reject_attempt` не вызывался, статус в БД не переписывался, approved
   viseme-референсы и калибровки не менялись.
2. **Статус движков.** `mouth_animation_mvp`, `pillow_mouth_v2` и
   `viseme_frame_blend_v1` — **experimental**. Код, API, тесты, калибровки и UI
   сохраняются; скрытие панелей и смена режима по умолчанию — только Stage 2
   отдельного work package.
3. **Rhubarb 1.14.0** — диагностический источник таймингов, не автоматический
   production-процесс: запуск остаётся явным (`use_rhubarb`), сетевые запросы и
   скачивание запрещены без отдельного разрешения.
4. **Lip sync недоступен.** `SELECTED_ENGINE = None`; `POST /api/shots/{id}/lipsync`
   отвечает 409 `lipsync_engine_not_selected`, job не создаётся. Выбор движка —
   отдельное решение с оценкой лицензии и качества.
5. **Аудиоинфраструктура остаётся production-компонентом:** импорт готового аудио
   (`reference_assets(role='shot_audio')`, рабочая PCM 48 кГц mono, огибающая,
   waveform), `projects.audio_artifact_id`, таймлайн и производственный план.
   Заморозка анимации рта её не затрагивает.
6. **Возобновление экспериментов** — отдельный WP с визуальными критериями приёмки
   (отсутствие шва и прямоугольной границы, постоянство освещения, сохранение
   идентичности, измеримая артикуляция, отсутствие мерцания).
7. **Отмена одной job.** В контракте API нет эндпоинта отмены отдельной job —
   существует только `POST /api/series/{run_id}/cancel` для прогона серии. Отмена
   `pending`-job без lease выполняется операционным изменением статуса строки на
   `cancelled` в транзакции с guard-условиями (id + kind + status + attempts=0 +
   `lease_owner IS NULL`); новый эндпоинт требует отдельного утверждения и в этом WP
   не создавался.

---

## 5. Дополнительные утверждённые решения (D1–D8)

| ID | Решение | Следствие для реализации |
|---|---|---|
| D1 | Непрозрачное изображение персонажа — предупреждение, не запрет | API возвращает warning; UI показывает; рендер разрешён |
| D2 | Композитор MVP — синхронная операция FastAPI для небольших PNG | Ограничения по площади/размеру и времени задаются конфигурацией; при превышении — ошибка 413/422; очередь не используется |
| D3 | Storage — конфигурируемый локальный каталог, исключённый из Git; в БД только относительные `storage_key` | Абсолютные пути запрещены; `storage/` добавляется в `.gitignore` в WP-00B |
| D4 | Git — отдельный WP-00B после проверки `.gitignore` | В WP-00 `git init` не выполняется; существующий `.gitignore` проверяется и дополняется |
| D5 | Импортируемые bible и референсы получают статус `draft` | Автоматического `approved` нет; approve только человеком |
| D6 | 512×512, 73 кадра, 24 FPS — экспериментальный preset | Проверяется в WP-00A; до подтверждения не считается гарантированным |
| D7 | MVP — один локальный пользователь | Публичный доступ к UI не открывается; worker API защищён токеном; ComfyUI/Ollama только `127.0.0.1` |
| D8 | Облачные провайдеры исключены из MVP | Provider-интерфейс допускает добавление позже; по умолчанию данные не покидают локальную сеть |

---

## 6. Совместимость с v1.3

| Область | Характер изменения | Обратная совместимость |
|---|---|---|
| `reference_assets` | A: новые колонки; C: CHECK, составные FK | Существующие записи валидны; `kind` уже есть в v1.3 |
| `artifacts` | A: `shot_composition_id`, `source`; `attempt_id` nullable | Чтение v1.3 не меняется; старые записи получают `source='attempt'` |
| `render_attempts` | `job_id` nullable для `keyframe` | Видео- и postprocess-попытки по-прежнему требуют job |
| `prompt_revisions` | A: `prompt_type`, `version` | `prompt` сохранён; default `motion` |
| `episodes` | A: новая таблица; `scenes.episode_id` nullable | Старые пути `/api/projects/{id}/scenes` работают |
| `shot_compositions` | R: ревизии и слои вместо одной записи; A: `source_plan_id` nullable | Эндпоинт получает `revision`; старый одиночный доступ не сохраняется; композиции без плана валидны |
| `shots` | A: `start_keyframe_*` | `approved_attempt_id` остаётся для видео-версии |
| `visual_scene_plans` | A: новая таблица (S19) | План необязателен; существующие шоты и композиции не меняются |
| `projects` | A: `audio_artifact_id` (FK, nullable) | Проекты без песни валидны; экспорт и рендер не меняются |
| `production_plans` | A: новая таблица (WP-M3) | Только черновики; сцены, шоты и approved-записи не затрагиваются |
| `jobs.external_id` | Использование существующей колонки (WP-M4) | Миграции нет; заполняется только на время рендера и очищается в `complete`/`fail` |
| Worker API | A: `POST /api/worker/jobs/{id}/external` (WP-M4) | Существующие вызовы `claim`/`heartbeat`/`resume` не меняются |
| API | A: новые эндпоинты; A5 переработан | Существующие эндпоинты v1.3 сохраняют семантику |
| API | A: `GET /api/projects/{id}/attempts` (WP-M5) | Только чтение; схема БД и существующие ответы не меняются |
| `reference_assets` | `role='voice'` и `metadata.multi_view` без миграции (WP-M6) | Существующие CHECK и S15 не меняются |
| API | A: `POST /api/characters/{id}/voice`, `multi_view` в `PATCH /api/reference-assets/{id}` (WP-M6) | Только новый эндпоинт и поле разметки; ответы расширены `duration_s`/`multi_view` |
| API | A: `GET /api/presets` (WP-M7) | Только чтение профиля железа и таблицы измеренных пресетов; схема БД не меняется |
| `render_attempts.parameters` | Новые ключи `preset`/`preset_source` (WP-M7) | JSONB без миграции; старые попытки читаются как раньше |
| API | A: `POST /api/shots/{id}/lipsync` (WP-M8) | Новый эндпоинт; всегда 409, пока движок не выбран; БД и очередь не затрагиваются |
| Worker API | C: guard в `POST /api/worker/claim`, `series/next` → `busy` (WP-THERMAL-02) | Схема БД и миграции не меняются; claim `render_video` может вернуть `null` при чужом активном рендере |
| API | A: read-only `GET /api/render-agent/status` (WP-THERMAL-02) | Только чтение снимка воркера, журнала и очереди; управления очередью нет |
| API | A: необязательное тело `{"preview": true}` у `POST /api/shots/{id}/render`, поле `preview` в ответе; approve preview → 409 (WP-THERMAL-03) | Вызовы без тела и старые попытки читаются как раньше; схема БД не меняется |
| API | A: `power.low_power_mode: bool \| null` в `GET /api/render-agent/status` (WP-THERMAL-03) | Аддитивное поле; `null` = Unknown, глобальные настройки macOS не читаются с записью |
| `render_attempts.parameters` | Новые ключи `preview` и `thermal.low_power_mode` (WP-THERMAL-03) | JSONB без миграции; старые попытки не переписываются |
| Runtime | Локальные файлы воркера `~/.mary-studio/thermal-{state.json,events.jsonl}` (WP-THERMAL-02) | Вне БД и Git; формат фиксирован, журнал с ротацией; имена событий `events` не расширяются |
| `mouth_calibrations` | A: новая таблица (S20, WP-VOICE-02) | Калибровка необязательна; approved-референсы и стартовые кадры не меняются |
| `reference_assets` | `role='shot_audio'` и `metadata.envelope`/`work_storage_key` без миграции (WP-VOICE-02) | Существующие CHECK и S15 не меняются; рабочая PCM-копия — отдельный blob в том же storage |
| `jobs.kind` | Новое значение `mouth_animation` без миграции (WP-VOICE-02) | CHECK у колонки нет; GPU-воркер по-прежнему выбирает только перечисленные `kinds` |
| API | A: `POST/GET /api/shots/{id}/audio`, `…/audio/{asset_id}/waveform`, `POST/GET /api/shots/{id}/mouth-calibrations`, `…/preview`, `POST /api/shots/{id}/mouth-animation` (WP-VOICE-02) | Новые эндпоинты; существующий lip sync API (`SELECTED_ENGINE=None`) и его ответы не меняются |

**Правило:** baseline v1.3 не редактируется. Любое расхождение фиксируется здесь и в
`docs/ROADMAP_MARY_STUDIO.md`.

---

## 7. Решения, отложенные до соответствующих WP

| Вопрос | Где решается |
|---|---|
| Точные лимиты площади PNG и таймаута композитора | WP-05 |
| Точные значения preset 512×512/73/24fps | WP-00A |
| Каталог `storage/` и политика retention | WP-01/WP-03 |
| Remote и состав первого коммита | WP-00B |
| Обязательность `scenes.episode_id` после backfill | WP-03 |
| UI-стек | WP-04 (сначала API/OpenAPI) |
| `launchd`-агент для воркера (Q-31) | отдельный этап; предложение — `docs/REPORTS/WP_THERMAL_03_REPORT.md` §9 |
| `low_ram`, энергетические профили Performance и замеры (Q-33, Q-38) | после энергетического теста |

---

## 8. Журнал изменений документа

| Дата | Изменение |
|---|---|
| 2026-10-26 | Первая редакция: P1–P4, S1–S12, A1–A6, D1–D8 утверждены; зафиксированы инварианты S8/S11/S12 |
| 2026-10-26 | S13–S18: уточнения перед WP-02 (статусы референсов, `purpose`, триггеры иммутабельности, `project_id` в bible, единственность approved-ревизии, `characters.kind`) |
| 2026-10-26 | S19: Visual Scene Plan (WP-05A) — таблица `visual_scene_plans`, JSONB-план, триггер S15, one-approved индекс, `shot_compositions.source_plan_id`, `layout mockup`, vision как советующий источник |
| 2026-10-28 | §4.2: импорт серии «Ночной тыгыдык» и preflight (WP-N1) — два аддитивных эндпоинта `series/import` и `series/preflight`, natural keys, разрешение имён референсов по файлу и sha256, `snap8k1` для длительности; схема БД не менялась |
| 2026-10-28 | §4.1: `keyframe` из approved-референса (`reference_asset_id`) без генерации изображения; писатель стартового кадра остаётся единственным — `promote-keyframe`; миграции нет |
| 2026-10-28 | §4.3: реальный LTX-воркер (WP-N3) — `inputs.prompt`/`shot_key` из motion-ревизии (соответствие §5.2 baseline), проверка sha256 стартового кадра, `8k+1`, heartbeat на каждом опросе `/history`, provenance модели и шаблона; схема и эндпоинты не менялись |
| 2026-10-28 | §4.4: управляемый прогон серии (WP-N4) — миграция `0007_render_series` (`series_runs`, `series_items`), эндпоинты прогона и `POST /api/worker/series/next`, `stop_on_error`, `stop-after-current`, идемпотентность `series:{run_id}:{order}`, баннеры macOS |
| 2026-10-28 | §4.5: разрешение рендера серии — 576×1024 (`--long-side 1024`) по результатам калибровки; 1080×1920 не поддержан two-stage half-res на 16 ГБ RAM; умолчания адаптера и воркера не менялись |
| 2026-10-28 | §4.6: имя прогона серии (WP-08) — миграция `0008_series_run_title` (`series_runs.title`, nullable), поле `title` в create/list/detail, первый именованный прогон «NLB-single» |
| 2026-10-29 | §4.7: сюжетные шоты NLB-21…27 — identity-референс `role='guinness_identity'` отдельно от стартового кадра, внешние сцен-кадры 9:16 через штатный путь `references → keyframe → promote-keyframe`, motion v2 с `source='human_prompt_override'`, провенанс `render_attempts.parameters` (+`workflow_snapshot`) без миграции; старая карточка `Guiness_clean` отвязана, но остаётся approved |
| 2026-11-04 | §4.9: ревью видео-попытки и мониторинг job (WP-M1) — идемпотентный approve/reject как единственный писатель `approved_attempt_id`, `GET /api/jobs/{id}/events` и `last_event`, без миграций; reject утверждённой попытки снимает approve |
| 2026-11-04 | §4.8: сборка и экспорт вертикального MP4 (WP-M2) — миграция `0009_export_artifacts` (`artifacts.metadata` JSONB, `source='export'`), синхронный `POST/GET /api/projects/{id}/exports`, 1080×1920/24 fps через ffmpeg, звук клипов или внешняя дорожка, исходники неизменны |
| 2026-11-04 | §4.10: music timeline и производственный план (WP-M3) — миграция `0010_audio_timeline_plans` (`projects.audio_artifact_id`, таблица `production_plans`), FFmpeg-эвристика BPM/битов/секций без новых библиотек, `POST /api/projects/{id}/audio`, `GET …/timeline`, `POST …/production-plans/generate` (Ollama structured output + bounded repair), только черновые ревизии; UI `#/plan` |
| 2026-11-04 | §4.11: восстановление рендера после рестарта воркера (WP-M4) — `POST /api/worker/jobs/{id}/external` пишет `prompt_id` в существующий `jobs.external_id`, state-файл `~/.mary-studio/ltx-worker-state.json`, `resume` + `/history`/`/queue` вместо повторного `/prompt`, `external_prompt_lost` (retryable) при потере prompt'а; миграций и нового события нет |
| 2026-11-04 | §4.12: список и сравнение попыток проекта (WP-M5) — `GET /api/projects/{id}/attempts` с фильтрами `scene_id`/`shot_id`/`kind`/`status` и страницей `items/total/limit/offset`, флаг `approved` из `shots.approved_attempt_id`, UI `#/attempts`; «Сделать текущей» вызывает существующий approve; миграций нет |
| 2026-11-04 | §4.13: голос персонажа и многоракурсная карточка (WP-M6) — `POST /api/characters/{id}/voice` пишет `reference_assets(role='voice')` (ffprobe, ≤ 30 с, дедуп по sha256), `multi_view` в `metadata` через существующий PATCH, `keyframe` отклоняет голос и многоракурсную карточку; UI-раздел «Голос»; миграций нет |
| 2026-11-04 | §4.14: пресеты рендера под оборудование (WP-M7) — только измеренные `safe`/`wide`/`legacy_512` с флагами `measured`, детект Apple Silicon и памяти через `sysctl`/`vm_stat` без новых зависимостей, read-only `GET /api/presets`, приоритет «CLI > API > default» в воркере, `preset`/`preset_source` в `render_attempts.parameters`; миграций нет |
| 2026-11-04 | §4.15: интерфейс lip sync без движка (WP-M8) — `backend/app/lipsync.py` (`SELECTED_ENGINE = None`, коды `lipsync_engine_not_selected`/`_not_implemented`), `POST /api/shots/{id}/lipsync` → 409 без записей в БД и без job, UI-панель за `VITE_FEATURE_LIPSYNC`; legacy-заглушки `pipeline/stages/*` не тронуты, миграций нет |
| 2026-11-04 | §4.16: thermal-safe планировщик (WP-THERMAL-02) — Q-27 Swift-helper `ProcessInfo.thermalState` с fallback `unknown`; Q-28 атомарный guard одного `render_video` в `claim` (`pg_advisory_xact_lock` + `NOT EXISTS`), `series_next` → `busy`; Q-29 read-only `GET /api/render-agent/status` со свежестью данных; Q-30 сеть + normal memory pressure + 4 ГиБ, батарея только с ≥ 50 % и `--allow-battery`, пауза вместо завершения; Q-31 `caffeinate -i -w`, `launchd` отдельно; Q-32 профиль только при старте; Q-33 Eco не меняет production-параметры, `low_ram` — после Q-38; Q-34 preview через `parameters.preview=true` (реализация — отдельный WP); Q-35 JSONL с ротацией; миграций нет |
| 2026-11-04 | §4.17: стабилизация thermal-защиты и preview-first (WP-THERMAL-03) — `RenderSettings.thermal_profile`, Low Power Mode только чтение (`pmset -g` → `power.low_power_mode`, telemetry, state-файл), снимок `allowed=false` сразу после горячей job, ограниченное ожидание `--thermal-max-wait` (код 1), preview через тело `{"preview": true}` (73 кадра, `parameters.preview=true`, approve → 409), UI-панель с `Unknown` вместо прочерков и причиной блокировки вне паузы, `export/` в `.gitignore`; миграций нет |
| 2026-11-04 | S20: `mouth_calibrations` (WP-VOICE-02) — калибровка области рта, ровно один источник (approved-референс XOR keyframe), CHECK области и параметров, частичные уникальные индексы на пару «шот, источник»; approved-записи не меняются |
| 2026-11-04 | §4.18: Talking Character MVP `mouth_animation_mvp` (WP-VOICE-02) — приблизительная анимация рта по RMS (не phoneme-accurate), image-режим из approved-кадра и стартового кадра, Video Talking `Not Supported`, локальный движок Pillow + FFmpeg без GPU/TTS, результат — `Job(kind='mouth_animation')` + видео-попытка + артефакт `talking_preview` без миграции, review только человеком, типизированные 409 без пустого MP4 |
| 2026-11-04 | §4.19: импорт и подготовка готового аудио шота (WP-VOICE-02) — `reference_assets(role='shot_audio')` + `shot_references(purpose='other')`, `POST/GET /api/shots/{id}/audio` и waveform, лимиты 32 МиБ/120 с, ffprobe, оригинал без изменений + рабочая PCM 48 кГц mono, огибающая 50 Гц и речевые участки; новых таблиц и storage нет |
| 2026-11-04 | §4.20: движок рта v2 (WP-VOICE-04) — `engine='pillow_mouth_v2'`, `workflow_version='mouth_animation_mvp_v2'`, принудительное закрытие после 0.08 с тишины, ускоренный release, раскрытие вниз от линии рта, feather-край, `apad`/`-t` вместо `-shortest`, `frames` из ffprobe; upsert калибровки без миграций |
| 2026-11-05 | §4.22: заморозка анимации рта и статус lip sync (WP-STABILIZE-01) — сборка B (`viseme_frame_blend_v1`) отклонена как производственный результат без переписывания БД, все три движка рта переведены в experimental, Rhubarb — только диагностический источник таймингов, lip sync остаётся unavailable (`SELECTED_ENGINE = None`), аудиоинфраструктура остаётся production; зафиксировано отсутствие эндпоинта отмены отдельной job |
