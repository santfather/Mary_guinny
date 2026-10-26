# WP-05A — Visual Scene Planner: предложение и ADR

> **Статус:** реализовано 2026-10-26 (см. §12). Решения по блокерам 1–8 приняты
> человеком; блокер 9 (merge/push) остаётся открытым.
> **Дата:** 2026-10-26. **Основание:** задание «WP-05A и WP-05B» (§2–§9, §19).
> **Ветка:** `wp-05a-visual-scene-planner` от `wp-05-composition-keyframe`
> (WP-05 влит в `main` fast-forward, `a47f60d`).
> **Согласовано:** миграция `0005` (вариант B), загрузка референсов через существующий
> storage, `gemma3:4b` как советующий источник, canvas 768×512 + экспорт 512×512
> `crop`/`pad`.

---

## 1. Фактическое состояние (аудит 2026-10-26)

### 1.1. Git и тесты

| Проверка | Результат |
|---|---|
| Ветка | `wp-05-composition-keyframe`, рабочее дерево чистое |
| Коммит | `a47f60d feat: add shot composition and start keyframe` |
| `main` | `8e2551f` (WP-04); WP-05 в `main` **не влит** |
| Backend | `uv run pytest -q` → **81 passed** |
| Legacy | 15 passed (по отчёту WP-05; повторно не запускался в этом аудите) |
| `alembic head` | `0004_composition_revisions` |

### 1.2. Что уже есть

| Объект | Фактическое состояние |
|---|---|
| `shots`, `scenes`, `episodes` | есть; `shots.start_keyframe_artifact_id/attempt_id`, `shots.current_prompt_revision_id` |
| `shot_references` | `(project_id, shot_id, reference_asset_id, purpose)`, `UNIQUE(shot_id, asset, purpose)`, `purpose CHECK IN ('character','location','prop','style','other')` — **`storyboard` отсутствует** |
| `shot_compositions` / `shot_composition_layers` | ревизии, слои `z/x/y/scale/rotation/opacity`; approve/supersede; S15-триггер |
| `prompt_revisions` | `(shot_id, prompt_type, version)`; `prompt_type IN ('keyframe','motion','composition','script','other')`; **нет `status`, `approved_at`, триггера неизменяемости** |
| `artifacts` | content-addressed blob, принимает `application/json`; нет жизненного цикла «ревизия/утверждён» |
| `render_attempts.parameters` | JSONB; keyframe-попытка уже пишет `composition_id`/`composition_revision` |
| API | `GET/POST scenes`, `GET/POST shots`, `shot_references`, `keyframe`, `promote-keyframe`, `render`; композиции: list/create/get/put/render/approve/supersede; `GET /api/projects/{id}/references` |
| UI | `#/shots`, `#/shots/{id}`: референсы, редактор слоёв, render/approve/supersede, keyframe → promote, рендер |
| Загрузка референса | **API создания `reference_assets` отсутствует**; `POST /api/artifacts` создаёт артефакт, не ассет |
| Локации/предметы | `GET` есть; в БД **0 локаций и 0 предметов**, референсов локаций нет |

### 1.3. Данные проекта (БД `mary_studio`)

| Сущность | Значение |
|---|---|
| Проекты | `Mary Studio` (`b6810db7-…`) |
| Персонажи | `guinness` (cat), `marija` (human) |
| Референсы | 16 `character_reference`: 15 `draft`, **1 `approved`** (guinness, `side`, 512×768, `has_alpha=false`) |
| Marija approved | **0** (все 8 — `draft`) |
| Локации/предметы | 0 / 0 |
| Сцены/шоты | 6 сцен, по 1 шоту; есть тестовый шот WP-05 |

### 1.4. Ollama и vision

- Установленные модели включают **`gemma3:4b`** (мультимодальная, 3.3 GB) и текстовые
  `qwen3:8b`, `qwen3:4b-instruct-*`.
- Проверка vision выполнена локально на реальных PNG (`characters/guinness/reference_side.png`,
  `characters/marija/reference_front.png`):
  - один кадр: ответ описывает кота, **~8.5 с**;
  - два кадра + `format=json`: валидный JSON, **~8.8 с**, но модель
    **проигнорировала alias** (`cat`, `woman` вместо `guinness`, `marija`),
    **выдумала детали фона** (окно, шторы, кошачье дерево) и не вернула
    `uncertainties`.
- Вывод: vision технически доступен, но его вывод — **советующий**, не источник истины.
  Серверная нормализация и ручное подтверждение обязательны.
- Legacy `ScriptStage` использует `OLLAMA_MODEL` (default `catshow`, не установлена);
  backend настроек Ollama не имеет.
- `httpx` в backend — только dev-зависимость.

### 1.5. LTX (для границ WP-05A)

- `comfyui-workflows/ltx23_mlx_q4_i2v.api.json`: `LoadImage` → `LTX2MLXModelLoader`
  (`dgrauet/ltx-2.3-mlx-q4`, `distilled`) → `LTX2MLXGenerate`.
- `/object_info/LTX2MLXGenerate`: **единственный необязательный вход `image`**; нет
  reference images, start/end frame, control-механизмов.
- Другие узлы (`LTXVImgToVideo`, `LTXVAddGuide`, `LtxApi25ImageToVideo`) в ComfyUI есть,
  но это другой backend/модели; совместимость с MLX Q4 **не проверена**.
- WP-05A LTX не запускает.

---

## 2. Границы WP-05A

### Входит

1. Версионируемый Visual Scene Plan, привязанный к шоту.
2. Выбор 2–3 референсов с ролями `character/location/prop/style/storyboard` и alias.
3. Описание действия, камера, начальные состояния, action beats, ограничения.
4. Генерация плана через LLM/vision **как черновика** + ручное редактирование.
5. Серверная валидация ссылок, ролей, alias, порядка действий.
6. Approve/supersede плана с неизменяемостью approved.
7. Детерминированная передача плана в существующий композитор (draft-ревизия).
8. Motion prompt (детерминированный шаблон, редактируемый).
9. UI в существующей странице шота.

### Не входит

- Запуск LTX/видео, очередь, worker.
- Автоматическое вырезание персонажа, inpainting, segmentation, pose-control.
- Автоматический approve плана, композиции или кадра.
- Новая библиотека персонажей/локаций.
- Загрузка ML-моделей.

---

## 3. Модель данных

### 3.1. Рассмотренные варианты

| Вариант | Суть | Плюсы | Минусы |
|---|---|---|---|
| A. Без миграции | план в `prompt_revisions.parameters_json` (`prompt_type='composition'`), «утверждён» = `shots.current_prompt_revision_id` | нет миграции; версии уже уникальны | нет `status/approved_at`; нельзя выразить supersede; нет неизменяемости approved на уровне БД; смешение prompt и плана |
| B. Новая таблица (рекомендуется) | `visual_scene_plans` + триггер S15 + частичный уникальный индекс approved | явный жизненный цикл; неизменяемость как у композиций; проверяемая provenance | миграция `0005` |
| C. Только artifacts/JSON | план как JSON-артефакт | content-addressed, без миграции | нет ревизий/статусов/связей; происхождение не выражается |

**Рекомендация: B.** Вариант A не обеспечивает требование «утверждённая версия плана
неизменяема» на уровне, принятом в проекте (S15).

### 3.2. Миграция `0005_visual_scene_plans`

Новая таблица:

```text
visual_scene_plans
  id              uuid pk default gen_random_uuid()
  project_id      uuid not null → projects.id
  shot_id         uuid not null → shots.id
  revision        int  not null check (revision >= 1)
  schema_version  int  not null default 1
  status          text not null check in ('draft','approved','superseded')
  source          text not null check in ('manual','llm','fallback')
  plan            jsonb not null
  warnings        jsonb not null default '[]'
  created_at      timestamptz not null default now()
  approved_at     timestamptz null
  UNIQUE (shot_id, revision)
  UNIQUE (project_id, id)
  CHECK (status <> 'approved' OR approved_at IS NOT NULL)
  INDEX ix_visual_scene_plans_shot_status (shot_id, status)
  UNIQUE INDEX uq_visual_scene_plans_one_approved ON (shot_id)
      WHERE status = 'approved'
```

- Триггер `mary_forbid_approved_change()` (функция создана в `0004`) на
  `visual_scene_plans`: контент approved неизменяем, разрешены только `approved →
  superseded` и `approved_at`; `DELETE` запрещён.
- `shot_compositions.source_plan_id` uuid null → `visual_scene_plans.id`
  (+ индекс). Нужен, чтобы происхождение keyframe было проверяемым:
  `artifact → attempt.parameters → composition → source_plan_id`.
- `shot_references.purpose` **не меняем**: `storyboard` — роль плана, а не
  обязательный purpose привязки. Если позже понадобится storyboard в
  `shot_references`, это отдельная миграция.
- `down_revision = '0004_composition_revisions'`; downgrade удаляет колонку, триггер,
  таблицу. Откат обратим, данные планов теряются.

### 3.3. JSON-схема плана (`schema_version = 1`)

Поля соответствуют заданию (§4) с добавлением `canvas`, `motion_prompt`, `warnings`,
`needs_review`:

```json
{
  "schema_version": 1,
  "canvas": {"width": 768, "height": 512},
  "references": [
    {"asset_id": "uuid", "role": "character", "entity_id": "uuid", "alias": "guinness"},
    {"asset_id": "uuid", "role": "location", "entity_id": "uuid", "alias": "living_room"},
    {"asset_id": "uuid", "role": "character", "entity_id": "uuid", "alias": "marija"}
  ],
  "camera": {"framing": "wide", "movement": "static"},
  "initial_state": [{"subject": "guinness", "position": "left_sofa", "action": "sitting"}],
  "action_beats": [{"order": 1, "subject": "marija", "action": "walk_toward", "target": "guinness"}],
  "constraints": {
    "preserve_character_identity": true,
    "preserve_location_layout": true,
    "no_unreferenced_characters": true
  },
  "motion_prompt": "wide static shot; ...",
  "needs_review": false
}
```

Серверные инварианты (422 при нарушении):

- `asset_id` существует, принадлежит проекту шота, `status='approved'` или
  `kind='uploaded'` (как в композиторе);
- `entity_id` (если задан) существует в проекте и совпадает с владельцем ассета;
- alias уникален, `^[a-z][a-z0-9_]{1,31}$`;
- `subject`/`target` в `initial_state`/`action_beats` — только объявленные alias;
- `order` — уникальные последовательные `1..N`;
- `camera.framing ∈ {wide, medium, close_up, other}`,
  `camera.movement ∈ {static, pan, tilt, dolly, zoom, handheld, other}`;
- `references` не пуст; `canvas` в пределах лимитов композитора;
- `motion_prompt` ≤ 4000 символов.

---

## 4. API (проект)

```text
GET    /api/shots/{shot_id}/scene-plans                      → list[ScenePlanSummary]
POST   /api/shots/{shot_id}/scene-plans                      → 201 ScenePlanOut (draft)
GET    /api/shots/{shot_id}/scene-plans/{revision}           → ScenePlanOut
PUT    /api/shots/{shot_id}/scene-plans/{revision}           → ScenePlanOut (только draft)
POST   /api/shots/{shot_id}/scene-plans/generate             → ScenePlanDraft (не сохраняется)
POST   /api/shots/{shot_id}/scene-plans/{revision}/approve   → ScenePlanOut
POST   /api/shots/{shot_id}/scene-plans/{revision}/supersede → ScenePlanOut
POST   /api/shots/{shot_id}/scene-plans/{revision}/composition
                                                              → 201 CompositionOut (draft)
```

- `generate` принимает `action`, `references[]`, `camera`, `canvas`, `use_vision`
  и возвращает кандидат + `warnings` + `source` (`llm`/`fallback`). В БД ничего не пишет:
  пользователь сначала проверяет/правит план.
- `POST` сохранения идемпотентен по содержимому: если последняя ревизия — `draft` с тем же
  нормализованным JSON, возвращается она (200), новая ревизия не создаётся.
- `approve`: только `draft` без блокирующих предупреждений; если другая ревизия approved →
  409 с текстом про `supersede` (как у композиций); повторный approve идемпотентен.
- `supersede`: только из `approved`, идемпотентен; триггер БД — последняя линия защиты.
- `composition`: создаёт draft-ревизию композиции из плана (см. §6), пишет
  `source_plan_id`; approve не выполняет.
- `POST /api/shots/{id}/keyframe` расширяется: в `render_attempts.parameters` добавляются
  `visual_plan_id` и `visual_plan_revision`, если композиция создана из плана.
- Ошибки: 404 — шот/ассет/ревизия; 409 — статус/approved-конфликт/чужой проект;
  413 — превышены лимиты; 422 — нарушения схемы.

---

## 5. LLM и vision

### 5.1. Архитектура

- Новый модуль `backend/app/planner.py`:
  - `build_skeleton(...)` — детерминированный план из выбранных референсов;
  - `analyze_images(...)` — вызов Ollama `/api/generate` с `images`, `format=json`;
  - `generate_candidate(...)` — сборка, нормализация, валидация, предупреждения.
- Настройки (`app/config.py`, префикс `MARY_`):
  `ollama_base_url` (default `http://127.0.0.1:11434`),
  `planner_model` (default `gemma3:4b`),
  `planner_timeout_s` (default 120),
  `planner_max_images` (default 3),
  `planner_image_max_side` (default 768, downscale перед отправкой).
- `httpx` переносится в основные зависимости backend (пакет уже установлен).

### 5.2. Защита от галлюцинаций

1. Список референсов и alias формирует **сервер** из запроса; LLM их не создаёт.
2. LLM не получает и не возвращает `asset_id`/`entity_id` — только наблюдения.
3. Ответ проходит Pydantic-валидацию; неизвестные поля отбрасываются;
   несовпадение alias → наблюдения отбрасываются с предупреждением
   `vision_alias_mismatch`.
4. Субъекты действий вне alias → отбрасываются с `unknown_subject_ignored`;
   если валидных beats не осталось — `needs_review=true`.
5. Любая ошибка транспорта/JSON/валидации → детерминированный skeleton,
   `source='fallback'`, предупреждение `vision_unavailable`.
6. Результат vision никогда не влияет на approve автоматически; UI явно различает
   «наблюдение модели» и «подтверждено человеком».
7. Запрет на выдуманную геометрию: начальные позиции и layout задаются человеком или
   детерминированными правилами; LLM может только предложить текст, не координаты.

### 5.3. Детерминированно vs зависит от ML

| Детерминированно | Зависит от ML |
|---|---|
| Валидация ссылок, ролей, alias, порядка | Распознавание содержания изображений |
| Статусы, ревизии, approve/supersede, триггеры | Интерпретация текста действия в beats |
| Motion prompt по шаблону | Литературная формулировка motion prompt |
| План → слои композиции | Оценка позы/взгляда персонажа |
| PNG-рендер, предупреждения о прозрачности | Качество итогового кадра |

---

## 6. План → композиция (детерминированные правила)

- Холст: `plan.canvas` (default 768×512, можно 512×512).
- `location` (z=0): fit-cover по холсту, `x/y` центрируют.
- `character` (z по порядку объявления): `scale = 0.55 * canvas_h / asset_h`;
  первый — `x = 0.10*w`, второй — `x = 0.55*w`, `y = h - scaled_h`.
- `prop`: `scale = 0.25`, правый нижний угол.
- `style` и `storyboard` в слои **не попадают** (используются как ориентиры плана).
- Если у персонажа нет альфа-канала, план получает предупреждение
  `composite_is_layout_only`, а композитор — существующие
  `opaque_character_reference`. Результат честно показывается как layout mockup,
  а не как финальный кинематографичный кадр.
- Все координаты редактируются в существующем редакторе; план создаёт только draft.

---

## 7. UI

Расширение `#/shots/{id}`, без второго редактора:

1. Панель **Visual Scene Plan** над композициями.
2. Reference picker: `GET /api/projects/{id}/references`, только `approved`/`uploaded`,
   группировка по типу; роли, включая `storyboard`.
3. Поле действия, camera framing/movement, constraints.
4. Кнопки «Построить план» (generate) и «Составить вручную».
5. Редактор: references (alias/role/entity), initial_state, action_beats,
   motion prompt (копирование), предупреждения.
6. Версии плана: список ревизий, статусы, approve/supersede.
7. «Создать композицию из плана» → draft в существующем редакторе слоёв.
8. Явные бейджи: `reference approved` / `plan draft` / `plan approved` /
   `keyframe готов` / `keyframe утверждён` / `video attempt`.

Новые файлы: `ScenePlanPanel.tsx`, `ScenePlanEditor.tsx`, `ReferencePicker.tsx`,
`PlanVersions.tsx`; изменения — `types.ts`, `client.ts`, `ShotDetailPage.tsx`,
`labels.ts`, `styles.css`.

---

## 8. Тесты

Backend (unit, без БД):

- неизвестный `asset_id`; чужой проект; неизвестный `entity_id`;
- дублирующийся alias; неизвестный subject/target; разрывы `order`;
- недопустимая роль/камера; пустые references;
- нормализация ответа LLM: alias mismatch, лишние поля, невалидный JSON;
- fallback при недоступной Ollama/vision.

Backend (API, транзакционная фикстура):

- создание/чтение/правка draft; повторное сохранение без дублей;
- approve → другой approve без supersede → 409; supersede идемпотентен;
- попытка UPDATE approved → ошибка триггера; DELETE запрещён;
- частичный уникальный индекс approved;
- generate с подменённым HTTP-клиентом: валидный JSON / мусор / таймаут;
- создание композиции из плана: порядок слоёв, геометрия, `source_plan_id`;
- keyframe-попытка содержит `visual_plan_id`/`visual_plan_revision`;
- существующие approve/promote-keyframe/render-гейт не сломаны.

Frontend: `npm run build`; ручной сценарий в браузере (см. §9 задания) с проверкой
консоли и сети.

Legacy: 15 тестов без изменений.

---

## 9. Порядок выполнения после согласования

1. Интегрировать WP-05 в `main` (fast-forward) — **по отдельному разрешению**.
2. Ветка `wp-05a-visual-scene-planner`.
3. Миграция `0005` + модели + тесты схемы/иммутабельности.
4. `app/planner.py`, схемы, API, тесты.
5. API композиции из плана + provenance в keyframe.
6. UI и CSS.
7. Прогоны: backend, legacy, `alembic check`, `npm run build`, ручной браузерный сценарий.
8. Документы: `docs/DECISIONS.md` (S19 — Visual Scene Plan; S16 занят),
   `docs/ROADMAP_MARY_STUDIO.md` (WP-05A/WP-05B), `AGENTS.md` §8.
9. Отчёт по §18 задания и остановка **перед merge/push и WP-05B**.

---

## 10. Блокеры и открытые вопросы

| № | Вопрос | Варианты | Рекомендация |
|---|---|---|---|
| 1 | Миграция `0005` | A: `prompt_revisions` без изменений; B: новая таблица + триггер | **B** |
| 2 | Локация | в БД нет локаций и изображений гостиной | Нужен реальный файл; нельзя подставлять произвольную картинку |
| 3 | Загрузка референса | нет API создания `reference_assets` | Добавить `POST /api/projects/{id}/references` (потоково, лимит, probe, dedupe, draft→approve) или загрузить данные CLI-скриптом |
| 4 | Approved-референсы | Guinness: 1 approved (side, 512×768); Marija: 0 | Утвердить front-референсы Guinness и Marija перед демонстрацией |
| 5 | Vision | `gemma3:4b` работает, но ошибается в alias/фоне | Разрешить только как советующий источник + обязательный review; либо text-only |
| 6 | `storyboard` | роль плана (без миграции) или ещё и `shot_references.purpose` (миграция) | Роль плана; `shot_references` не менять |
| 7 | Keyframe из плана | слои без альфы дают layout mockup | Принять как ограничение WP-05A; matting — отдельный эксперимент |
| 8 | Canvas | 768×512 или 512×512 | 768×512 для сохранения аспекта; 512×512 проверить в WP-05B |
| 9 | WP-05 в `main` | merge/push не выполнены | Отдельное разрешение |

---

## 11. Риски

- Без реального изображения локации и approved Marija сценарий приёмки невыполним.
- Импортированные PNG без альфа-канала: композиция будет «слоёным коллажем», а не
  кинематографичным кадром; нельзя выдавать это за согласованный keyframe.
- `gemma3:4b` склонна к галлюцинациям; при параллельной работе с ComfyUI возможна
  нехватка памяти (18 GB). WP-05A не запускает LTX одновременно.
- Миграция меняет схему; нужен бэкап и обратимость (downgrade).
- Длительный вызов генерации (8–20 с) требует таймаутов и понятного loading-состояния в UI.

---

## 12. Реализация (факт)

Реализовано на ветке `wp-05a-visual-scene-planner` от `main` (`a47f60d`).

| Блокер | Решение | Факт |
|---|---|---|
| 1. Миграция `0005` | Вариант B | `0005_visual_scene_plans`: таблица (S19), CHECK, `UNIQUE(shot_id, revision)`, `UNIQUE(project_id, id)`, частичный уникальный индекс approved, S15-триггер, `shot_compositions.source_plan_id` + FK + индекс; `downgrade` полный |
| 2. Локация | Не подставлять вымышленную | В UI отсутствие локации показано как незаполненный обязательный вход; для приёмки использованы тестовые ассеты с явной маркировкой, затем удалены |
| 3. Загрузка референсов | Существующий storage | `POST /api/projects/{id}/references`: PNG/JPEG, probe, SHA256/dedupe, MIME и лимиты, проектная изоляция, `draft`; второго механизма хранения нет |
| 4. Approved-референсы | Ручной approve | `ReferencePicker` умеет `view=front` и approve; существующие референсы не утверждались автоматически |
| 5. Vision | Советующий источник | `gemma3:4b` фактически видит изображения (`capabilities: [completion, vision]`), но на тесте не распознала alias и вернула `initial_state=[]`; API выставил `needs_review=true` и предупреждения; ручной путь работает без vision |
| 6. Непрозрачность | `layout mockup` | `is_layout_mockup=true` при `layer_without_alpha` / `opaque_character_reference`; UI и экспорт показывают бейдж и текст «не финальный keyframe»; matting не реализован |
| 7. Canvas | 768×512 + экспорт | План и композиция 768×512; экспорт 512×512 с `crop`/`pad` без растяжения, параметры рядом с артефактом |
| 8. Merge/push | Ожидает разрешения | Не выполнялись; WP-05A остаётся на ветке |

Проверки: `uv run pytest -q` → 123 passed; legacy → 15 passed; `uv run alembic check` →
no new upgrade operations; `npm run build` → успешно. Приёмочный сценарий «2 персонажа +
локация» пройден на изолированной БД/сторадже: upload → front → approve → generate →
план rev1 → approve → композиция 768×512 → render (`layout mockup`) → экспорт 512
`crop`/`pad` → keyframe → promote (`visual_plan_revision=1`).

Остаётся открытым: реальные изображения локации и approved front-референсы
Guinness/Marija в основной БД; решение о matting; WP-05B не начат.
