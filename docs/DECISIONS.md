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
| API | A: новые эндпоинты; A5 переработан | Существующие эндпоинты v1.3 сохраняют семантику |

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
