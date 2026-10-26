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
| `shot_compositions` | R: ревизии и слои вместо одной записи | Эндпоинт получает `revision`; старый одиночный доступ не сохраняется |
| `shots` | A: `start_keyframe_*` | `approved_attempt_id` остаётся для видео-версии |
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
