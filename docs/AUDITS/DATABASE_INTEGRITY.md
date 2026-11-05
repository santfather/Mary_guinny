# DATABASE INTEGRITY — Mary Studio (WP-AUDIT-01)

Дата: 2026-11-05. Режим: **только SELECT**. Ни одна строка не изменена, ни одна job не
запущена и не отменена, ни один asset не утверждён/отклонён.

Подключение: `backend/.venv/bin/python` + `app.config.Settings` / `app.db.build_engine`.
СУБД: PostgreSQL, база **14 MB**, head Alembic `0011_mouth_calibrations`.

---

## 1. Точные размеры таблиц (`count(*)`, не `n_live_tup`)

| Таблица | Строк |
|---------|-------|
| `projects` | 3 |
| `episodes` | 3 |
| `scenes` | 9 |
| `shots` | 44 |
| `characters` | 2 |
| `character_bible_versions` | 2 |
| `locations` | 3 |
| `props` | 2 |
| `reference_assets` | 50 |
| `shot_references` | 48 |
| `prompt_revisions` | 48 |
| `shot_compositions` | 2 |
| `shot_composition_layers` | 2 |
| `visual_scene_plans` | **0** |
| `jobs` | 53 |
| `job_dependencies` | **0** |
| `render_attempts` | 102 |
| `artifacts` | 297 |
| `events` | 9 464 |
| `workers` | 4 |
| `mouth_calibrations` | 2 |
| `production_plans` | 2 |
| `series_runs` | 7 |
| `series_items` | 33 |
| `alembic_version` | 1 |

---

## 2. Внешние ключи

- Всего FK-ограничений: **54** (включая 6 составных `(project_id, …)` из S13).
- Нарушений по 48 одноколоночным FK: **0**.
- Нарушений по 6 составным FK (project isolation S13): **0**
  (`character_bible_versions`, `reference_assets` ×3, `shot_composition_layers`,
  `shot_references`).

Дополнительные проверки согласованности:

| Проверка | SQL-смысл | Результат |
|----------|-----------|-----------|
| `shots.approved_attempt_id` указывает на attempt другого шота | join `render_attempts` | **0** |
| `render_attempts.status='completed'` без artifact | NOT EXISTS artifacts | **0** |
| `artifacts` без `attempt_id` | `where attempt_id is null` | 202 (198 `project_audio`, 1 `note`, 2 `composition_preview`, 1 `export_video` — норма: не привязаны к попытке) |
| Ключи `artifacts` с файлом на диске | сверка `storage_key` с `storage/blobs` | 99 из 297 |
| Ключи `reference_assets` с файлом | то же | 44 из 44 |

---

## 3. Статусы

| Сущность | Значения |
|----------|----------|
| `shots.status` | `prompt_ready` 36, `draft` 8 |
| `shots.approved_attempt_id` | заполнен **0** (во всех трёх проектах) |
| `render_attempts` | `video/completed` 49, `video/failed` 7, `keyframe/completed` 46 |
| `jobs` | `completed` 49 (45 `render_video` + 4 `mouth_animation`), `failed` 3, `pending` **1** |
| `series_items` | `completed` 32, `failed` 1 |
| `series_runs` | `completed` 6, `paused` **1** |
| `reference_assets` | `approved` 29, `draft` 19, `rejected` 2 |
| `workers` | 4 строки, все `status='active'` |

### 3.1 Несогласованность: «активные» воркеры

Все 4 записи `workers` имеют `status='active'`, но `last_seen_at`:
2026-10-28 13:49, 2026-11-04 14:17, 2026-11-04 14:53, 2026-11-04 17:51.
На момент аудита (2026-11-05) ни один воркер не работает (`lsof` — ComfyUI/воркер не
слушают), то есть статус устарел. `GET /api/render-agent/status` использует порог
`render_agent_stale_seconds=180`, поэтому UI покажет stale — данные не портятся, но
таблица `workers` не отражает реальность.

### 3.2 Несогласованность: `prompt_ready` без стартового кадра

`status='prompt_ready'` и при этом `start_keyframe_artifact_id IS NULL` — **4 шота**
(GNS-01…GNS-04). Это ожидаемо (сцен-кадры не сгенерированы), но означает: render-гейт
их не пропустит, а `preflight` вернёт `missing_start_frame`.

Всего стартовых кадров: 33 из 44 (NLB 31/31, GNS 1/5, Mary Studio 1/8).

---

## 4. Критическая находка: 198 artifact без файла

| Показатель | Значение |
|------------|----------|
| `artifacts` всего | 297 |
| Файл существует | 99 |
| Файл **отсутствует** | **198** |
| Суммарный `bytes` отсутствующих | **18 924 421 Б** (≈18.0 MB) |
| Состав | 197 × `upload/project_audio`, 1 × `upload/note` |
| Даты создания (по данным прошлого прохода) | 180 — 2026-11-04, 18 — 2026-11-05 |
| `project.audio_artifact_id` среди них | **0** (единственная привязка — NLB `67af1e71…`, файл существует) |
| `scenes.audio_artifact_id` | 0 |
| `jobs`, ссылающихся на `project_audio` | 0 |

Интерпретация: записи появились от повторных/тестовых загрузок аудио проектов; сами blob
удалены или не были опубликованы. Данные в БД консистентны по FK, но **неполны по
содержимому**. Удаление строк без решения человека запрещено (это рабочие данные и
история), удаление файлов невозможно — их нет.

Риск: `GET /api/artifacts/{id}/content` для этих 198 записей вернёт ошибку чтения файла.
В UI эти записи не отображаются (у `project_audio` нет экрана), поэтому пользователь
дефект не видит.

---

## 5. Проекты

| Проект | Статус | Шотов | Сцен | Approved reference | Draft | Rejected |
|--------|--------|-------|------|--------------------|-------|----------|
| Mary Studio | active | 8 | — | 7 | 14 | 2 |
| The Nine Lives Band | draft | 31 | — | 15 | 0 | 0 |
| Guinness: Night Shift | draft | 5 | — | 7 | 5 | 0 |

(Сцены: 9 всего; по проектам детально не разбивались — **NOT VERIFIED** поштучно.)

### 5.1 NLB

- 31 шот, у **всех 31** есть стартовый кадр (`start_keyframe_artifact_id`).
- 15 approved `reference_assets` (состав по ролям детально не перечислялся, см. §8).
- `render_attempts`: 78 `completed`, 5 `failed`.
- **Approved attempts: 0** (`shots.approved_attempt_id` пуст во всех 44 шотах).
- `projects.audio_artifact_id` = `67af1e71-96a0-4ec8-aa84-05e693630bb5` (mp3, файл на диске есть).
- Прогоны: `NLB-single` (24/24 completed), `NLB-single wide (28-30)` (3/3), плюс 4
  безымянных completed и 1 paused (`13c86ba0…`, 1 item `failed`).

### 5.2 GNS (Guinness: Night Shift)

| Шот | seq | status | start keyframe | attempts | approved |
|-----|-----|--------|----------------|----------|----------|
| GNS-01…04 | 1–4 | `prompt_ready` | нет | 0 | нет |
| GNS-05 | 5 | `prompt_ready` | да | 5 (1 keyframe + 4 video-попытки) | нет |

Попытки GNS-05 (все `completed`, по `parameters->>'engine'`):

| created_at | engine | смысл |
|------------|--------|-------|
| 2026-11-04 20:19:47 | `pillow_ellipse_v1` | Talking Preview v1 (WP-VOICE-03) |
| 2026-11-04 20:49:20 | `pillow_mouth_v2` | Preview v2 |
| 2026-11-05 10:25:49 | `pillow_mouth_v2` | Preview после сдвига калибровки (WP-VOICE-04, artifact `bb96c6a0…`) |
| 2026-11-05 12:54:55 | `viseme_frame_blend_v1` | Сборка B (artifact `a5326a3f…`) |

Важно: **ни одной LTX-видеопопытки у GNS-05 нет**. 4 «video»-попытки — это talking
preview, а pending-job (см. §6) станет первой реальной I2V-генерацией этого шота.

Референсы GNS: approved — `gns_05_start`, `shot_audio`, 5 × `viseme_*`; draft —
`gns_01_start`…`gns_04_start`, `guinness_identity`.

Аудио: `shot_audio` approved (запись `Lana 6-4.mp3` по WP-VOICE-03), файл на диске есть.

---

## 6. Ожидающая job `852adc5d…` — operational risk

```
id           = 852adc5d-5a56-415b-8d3f-0fa6077c9653
kind/status  = render_video / pending
shot         = 6532e96d-1358-4d30-94ed-a88dc2e14607  (GNS-05, seq 5, сцена «Ночная смена»)
attempts     = 0 / max 3
lease_owner  = NULL, lease_until = NULL
created_at   = 2026-11-05 10:25:10 +01:00
payload      = {shot_id, queued_at, start_keyframe_artifact_id: d2767fbd-3eaf-4858-bb25-5caa90d2fff2}
events       = 0
```

**Может ли стартовать:** да. `claim` в `backend/app/api/worker.py` берёт `pending`-job с
`lease_owner IS NULL` и `run_after <= now()`; ни `cancel`, ни `fail` над ней не
выполнялись. Любой запуск `worker/ltx_worker.py` (в т.ч. `--series-run`, `--once`) или
`fake_worker.py` с валидным токеном подхватит её.

**Последствия запуска:** полноценный LTX-рендер GNS-05 (safe 576×1024/193 кадра,
≈1062 с/шот по WP-M7) на 18 GB памяти + thermal-нагрузка; при `preview-first` не
защищён — job создана как обычный рендер (`preview` в payload отсутствует).

**Статус:** не запускалась и не отменялась. Требует решения человека (см.
`OPEN_RISKS.md` R-01).

---

## 7. Что в БД выглядит здоровым

- S12 (происхождение артефактов): у всех 297 записей источник задан; 202 без
  `attempt_id` — это `upload`/`composition`/`export`, что соответствует контракту.
- S15: approved-референсы не перезаписывались; `reference_assets` 29/19/2.
- Иммутабельность композиций: `shot_compositions` 2, `shot_composition_layers` 2, без
  нарушений FK.
- Очередь: 53 job, 0 «зависших» с истёкшим lease (единственный pending — см. §6);
  `job_dependencies` пуста.
- Дубли blob (10 групп `storage_key`, 28 «лишних» строк) — это дедупликация, а не ошибка.
- 6 групп одинакового `sha256` в `reference_assets` — межпроектные копии (2 проекта в
  каждой группе), ожидаемо для S13.

---

## 8. Ограничения

- `events` 9 464 — содержимое не анализировалось построчно.
- Проверка «файл существует» делалась по `storage_key` относительно `Settings.storage_root`;
  для `project_audio`/`note` файлов нет (см. §4).
- Состав approved NLB-референсов по ролям детально не перечислялся — **NOT VERIFIED**.
- `mouth_calibrations` (2 записи) проверены по количеству; геометрия не сверялась.
