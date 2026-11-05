# WP-STABILIZE-01 — Recovery, Git Baseline & Pending Job Safety

Дата: 2026-11-05
Ветка: `backup/wp-stabilize-01-2026-11-05`
Commit: `566cc3e5c75de68d105aa36ada6c279761dc1f64`
Резервная копия: `~/.mary-studio/backups/wp-stabilize-01/20261105T134650`
Статус: выполнен, работа остановлена (Stage 1/2 не начинались)

---

## 1. Executive Summary

Состояние проекта зафиксировано и обезопашено. Создана полная резервная копия БД и
рабочих файлов, единственная незавершённая job (GNS-05) переведена в терминальный
статус без запуска воркера, ComfyUI и рендера, вся незакоммиченная работа сохранена в
защитной ветке и отправлена на remote. Решения владельца по экспериментам записаны в
`docs/DECISIONS.md` (§4.22).

Три существенных отклонения от плана, зафиксированные честно:

1. **В API нет эндпоинта отмены отдельной job.** Существует только
   `POST /api/series/{run_id}/cancel` для прогона серии, а job GNS-05 не входит ни в один
   прогон. Отмена выполнена операционным изменением статуса строки в транзакции с
   guard-условиями; новый эндпоинт не создавался (запрещено заданием).
2. **Backend-тесты изменили рабочую БД.** Набор `backend/tests` пишет 6 строк
   `artifacts` (`project_audio`) в рабочую PostgreSQL, несмотря на транзакционный
   fixture: 297 → 303 artifact, «файл отсутствует» 198 → 204. Строки не удалялись
   (прямой запрет), факт зафиксирован как дефект изоляции тестов.
3. **`launchctl` недоступен** в окружении агента — launchd-агенты остались
   `NOT VERIFIED`.

Ни одна строка `artifacts`, `render_attempts`, `events` не удалена, ни один approved
референс не изменён, blob-хранилище не переписывалось, миграции не применялись.

---

## 2. Preflight (PHASE A)

### 2.1. A1. Git

| Параметр | Значение |
|---|---|
| Абсолютный путь | `/Users/vladislavkovalenko/Projects/Mary_Guiness` |
| Ветка | `wp-m0-maestro-audit` (до WP) |
| HEAD | `e3c391bb44585551f41a079857ee5435833735e4` — `feat: complete WP-M1–M8 and WP-THERMAL-02` |
| Remote | `git@github.com:santfather/Mary_guinny.git` |
| Upstream | `origin/wp-m0-maestro-audit` |
| `git status --porcelain=v1 -uall` | 82 строки: **31 modified + 51 untracked**, 0 deleted, 0 renamed |
| Stash | отсутствует |
| Worktree | один (`/Users/vladislavkovalenko/Projects/Mary_Guiness`) |
| Незавершённый merge/rebase/cherry-pick | нет (`MERGE_HEAD`, `rebase-*`, `CHERRY_PICK_HEAD` отсутствуют) |
| Alembic head в файлах | `0011_mouth_calibrations` (untracked), 0001–0010 tracked |
| Alembic в БД | `0011_mouth_calibrations` |
| Ветки | `main` (`2d3fc72`), 7 WP-веток, `wp-m0-maestro-audit` (`e3c391b`) |

Расхождение с аудитом: аудит ожидал 69 изменений (31 modified + 38 untracked), фактически
82 (51 untracked). Известная часть прироста — 7 новых документов `docs/AUDITS/`
(созданы WP-AUDIT-01), остальные файлы существовали до аудита; поимённая сверка
снимка аудита не выполнялась, потому что аудит не сохранял список untracked.

### 2.2. A2. Процессы (фактическая проверка, без доверия PID-файлам)

| Компонент | Состояние |
|---|---|
| PostgreSQL 16 | работает (`/opt/homebrew/opt/postgresql@16`, PID 788) |
| Backend uvicorn | работает: PID 15028 (`uv run` 15027), `127.0.0.1:8000`, `GET /health` → 200 |
| Frontend Vite | работает: PID 13707, `127.0.0.1:5173` |
| Ollama | работает: PID 868, `127.0.0.1:11434` |
| ComfyUI | **не запущен**, порт 8188 не слушается |
| LTX worker | **не запущен** |
| `fake_worker.py` | **не запущен** |
| `caffeinate` | **не запущен** |
| `ffmpeg` | не выполняется |
| launchd-агенты | `NOT VERIFIED` — `launchctl list` → `permission denied` |
| GPU-задачи | отсутствуют (нет процессов с CPU > 20 %) |
| Память | 18.0 GiB; free 6 428 + inactive 190 358 + speculative 1 765 страниц по 16 KiB ≈ 3.1 GiB |

Активного воркера нет → отмена job не могла затронуть выполняющуюся GPU-работу.

### 2.3. A3. База данных (только SELECT)

| Показатель | Значение (до WP) |
|---|---|
| alembic | `0011_mouth_calibrations` |
| projects / scenes / shots | 3 / 9 / 44 |
| jobs | 53: `completed` 49, `failed` 3, `pending` 1 |
| render_attempts | 102 |
| artifacts | 297 |
| events | 9 464 |
| reference_assets | 50 (`approved` 29, `draft` 19, `rejected` 2) |
| `shots.approved_attempt_id` заполнен | 0 |
| FK-ограничения | 54, все validated, **0 нарушений** (проверены все 54, включая 6 составных project-isolation) |
| artifact без файла | 198 (`project_audio` 197, `note` 1; 18 924 421 Б) |
| reference без файла | 0 из 50 |
| workers | 4, все `active`, `last_seen_at` от 2026-10-28 до 2026-11-04 (stale 19 ч … 8 сут) |

Job `852adc5d-5a56-415b-8d3f-0fa6077c9653` — все существенные условия совпали с аудитом:

| Поле | Значение |
|---|---|
| kind / status | `render_video` / `pending` |
| attempts / max_attempts | 0 / 3 |
| lease_owner / lease_until / heartbeat_at | NULL / NULL / NULL |
| external_id / error_code | NULL / NULL |
| shot_id | `6532e96d-1358-4d30-94ed-a88dc2e14607` — GNS-05, seq 5, сцена «Ночная смена», проект «Guinness: Night Shift» |
| payload | `{shot_id, queued_at: 2026-11-05T09:25:10.971006+00:00, start_keyframe_artifact_id: d2767fbd-3eaf-4858-bb25-5caa90d2fff2}` |
| render_attempts с этим job_id | 0 |
| events с этим job_id | 0 |
| series_items с этим job_id | 0 (job не входит ни в один прогон) |

Это была единственная незавершённая job в системе (`status NOT IN ('completed','failed',
'cancelled')` → 1 строка).

---

## 3. Backup Manifest (PHASE B)

| Параметр | Значение |
|---|---|
| Каталог | `/Users/vladislavkovalenko/.mary-studio/backups/wp-stabilize-01/20261105T134650` |
| Права | каталог `0700`, дамп `0600`, `secrets/env.root` `0600` |
| Размер | 196 MB, 199 файлов |
| Git | каталог вне репозитория; в commit не попал |
| Создано | 2026-11-05 13:46:50 CET |
| Свободно на томе | 62 GiB на момент копии |

Состав:

| Элемент | Содержимое | Размер / SHA-256 |
|---|---|---|
| `db/mary_studio.dump` | `pg_dump -Fc`, exit 0 | 509 510 Б, `549abca3221dc05231c70d40a0d4ec9a70d583f921c5baa70b1d1befce3a2b91` |
| `db/pg_restore_list.txt` | `pg_restore --list`, exit 0, stderr пуст | 191 строка, 180 TOC entries |
| `db/snapshot_counts.txt` | снимок `count(*)` и статусов | — |
| `files/storage/` | blob-хранилище | 104 файла, 155 662 811 Б |
| `files/characters/` | 20 файлов | 9 547 907 Б |
| `files/episodes/` | 17 файлов | 3 491 666 Б |
| `files/docs/cats/` | 24 файла | 24 944 061 Б |
| `files/comfyui-workflows/` | 11 файлов | 15 527 Б |
| `files/export/wp_voice_06_ab/` | 12 файлов (A/B WP-VOICE-06) | 10 862 364 Б |
| `files/runtime/ltx-worker-state.json`, `files/home/ltx-worker-state.json` | state воркера | 2 Б каждый |
| `files.manifest.sha256` | SHA-256 всех 190 файлов копии | SHA-256 самого manifest `c9dbb7e0…` |
| `secrets/env.root` | корневой `.env` | 181 Б, не попал в отчёт и Git |
| `git_state.txt` | ветка/HEAD/remote/число изменений | — |

Проверки: количество файлов и суммарные байты совпадают с источником по каждому
каталогу; выборочный `cmp` (`docs/cats/closed.png`, `storage/blobs/3e/3e64617a….mp4`) —
совпадение; `shasum -c` по manifest — все файлы OK.

Не копировалось осознанно: `runtime/ComfyUI` целиком (2.5 GB), `~/.ollama` (85 GB),
`~/.cache/huggingface` (65 GB), `node_modules`, `.venv`, `export/LLM-gen`.
Версия ComfyUI зафиксирована текстом: **0.42.0**, commit
`0b05cd8a3683cbf0c291b1472bb8b64da41de9ae`; custom node **comfyui-ltx2-mlx**, commit
`d38b63abfffc32520cb31dd8b8471ba7bba52991`.

Согласованность: на момент копии не было ни воркера, ни ComfyUI, ни ffmpeg — записи в
`storage/` не велись, поэтому дамп и файлы отражают одно состояние.

Восстановление (описание, **не выполнялось**): файлы — `rsync -a <backup>/files/ <repo>/`
с последующей проверкой `shasum -a 256 -c`; БД — только в изолированную базу
(`createdb mary_studio_restore_test && pg_restore -d mary_studio_restore_test --no-owner
--no-privileges db/mary_studio.dump`) со сверкой `db/snapshot_counts.txt`. Восстановление
поверх рабочей БД запрещено заданием и не выполнялось.

Контрольная точка B4 пройдена: дамп существует и читается, копия совпадает по составу,
суммы сохранены, критические файлы доступны, места достаточно, исходное состояние Git и
БД зафиксировано в `git_state.txt` и `db/snapshot_counts.txt`.

Расхождение с аудитом: `storage/` — 103 файла / 155 656 663 Б в аудите против
104 файлов / 155 662 811 Б фактически (+6 148 Б). Новый blob
`storage/blobs/3e/3e64617a….mp4` (702 273 Б, 12:54:58) — artifact `a5326a3f…` сборки B
WP-VOICE-06. Арифметически дельта не сходится (добавленный файл больше прироста суммы),
поэтому методика подсчёта в аудите и сейчас различается; текущее измерение точное
(`find -type f | stat`), вопрос вынесен в риски.

---

## 4. Pending Job Cancellation (PHASE C)

### 4.1. Что было изучено

`backend/app/api/jobs.py` содержит только чтение: `GET /api/jobs`, `GET /api/jobs/{id}`,
`GET /api/jobs/{id}/events`. Полный перечень маршрутов из `openapi.json` с «cancel» или
«jobs»: `POST /api/series/{run_id}/cancel`, `POST /api/worker/jobs/{id}/{artifacts,
complete,external,fail,heartbeat}`. **Эндпоинта отмены одной job нет.** Модель статусов
(`JOB_STATUSES`): `pending, leased, running, completed, failed, cancel_requested,
cancelled, retry_wait, lease_expired`; `cancelled` — терминальный статус контракта.
`claim` выбирает только `pending`/`retry_wait`, поэтому `cancelled` гарантированно не
будет захвачен воркером. Частичный уникальный индекс `one_active_render_per_shot` не
включает `cancelled`.

### 4.2. Preflight перед отменой (повторный)

Повторно проверено непосредственно перед изменением: нет процессов ComfyUI, `ltx_worker`,
`fake_worker`, `caffeinate`, `ffmpeg`; порт 8188 не слушается; job — `render_video`,
`pending`, attempts 0/3, `lease_owner IS NULL`, `lease_until IS NULL`, `external_id IS
NULL`, shot совпадает; attempts по job = 0. Условия совпали полностью.

### 4.3. Выполненное действие

Штатного API нет (см. §4.1), поэтому выполнена одна транзакция с guard-условиями
(`SELECT … FOR UPDATE`, проверка kind/status/attempts/lease/shot, затем UPDATE с теми же
условиями в `WHERE`); при несовпадении — `ROLLBACK`. Фактический результат:

| Поле | До | После |
|---|---|---|
| id | `852adc5d-5a56-415b-8d3f-0fa6077c9653` | тот же |
| status | `pending` | **`cancelled`** |
| error_code | NULL | `cancelled` |
| attempts | 0 | 0 |
| lease_owner / lease_until / heartbeat_at | NULL | NULL |
| external_id | NULL | NULL |
| updated_at | 2026-11-05 10:25:10.966687+01 | 2026-11-05 13:48:41.839152+01 |

Событие в `events` не создавалось: `EVENT_NAMES` не содержит `cancelled`, а CHECK
таблицы запрещает новое имя без миграции (миграции в этом WP запрещены).

### 4.4. Подтверждение отсутствия побочных эффектов

Сверка «до/после» отмены: jobs 53 → 53; render_attempts 102 → 102 (по job — 0 → 0);
artifacts 297 → 297 (на момент проверки отмены); events 9 464 → 9 464; approved
reference_assets 29 → 29; `shots.approved_attempt_id` заполнен 0 → 0; шот GNS-05 остался
`prompt_ready` с тем же `start_keyframe_artifact_id` и `updated_at` 2026-11-04 19:56:06.
Активных `render_video` job: 0. `GET /api/jobs?status=pending` → `[]`.
`GET /api/jobs/852adc5d…` → `status: "cancelled"`, `attempts: 0`, `lease_owner: null`,
`last_event: null`. Новая render job, попытка и видео-артефакт не созданы; GNS-05
генерацию не начинал.

---

## 5. Git Baseline (PHASE D)

| Параметр | Значение |
|---|---|
| Исходная ветка / HEAD | `wp-m0-maestro-audit` / `e3c391b` |
| Защитная ветка | `backup/wp-stabilize-01-2026-11-05` (создана от `e3c391b`, работа сохранена) |
| Commit | `566cc3e5c75de68d105aa36ada6c279761dc1f64` — `chore: preserve Mary Studio pre-cleanup baseline` |
| Файлов в commit | **82** (31 modified + 51 new), +14 695 −107 |
| Remote branch | `origin/backup/wp-stabilize-01-2026-11-05` → `566cc3e…` (совпадает с локальным) |
| Push | выполнен, без `--force`, без merge/rebase, без удаления веток |
| Рабочее дерево после commit | чистое (`git status --porcelain -uall` → 0 строк) |

Проверка секретов и крупных файлов до commit (локально, без отправки во внешние
сканеры): подозрительных имён (`.env`, `id_rsa`, `*.pem`, `*.key`, `credentials`,
`secrets`, `token`) среди изменённых/untracked нет; поиск приватных ключей, AWS/ghp/sk/
xox-токенов и паролей по содержимому — 0 совпадений. `git check-ignore` подтвердил, что
`.env`, `storage/`, `runtime/`, `export/`, `ui/node_modules/`, `.venv/`, `.DS_Store`
исключены. Крупнейшие файлы commit — исходные изображения `docs/cats/*.png`
(2.5, 2.3, 2.3 МБ); дампов, backup-каталогов, blob-хранилища, временных экспортов и
моделей в индексе нет.

Состав commit: `backend/app` 18, `docs/PROPOSALS` 13, `ui/src` 9, `docs/cats` 9,
`docs/REPORTS` 7, `docs/AUDITS` 7, `backend/tests` 7, миграция
`backend/alembic/versions/0011_mouth_calibrations.py`, `worker/`, `tests/`,
`docs/DECISIONS.md` (§4.22), `AGENTS.md`, `.gitignore`, `backend/.env.example`.
`git add .` не использовался: пути проверялись по белому списку каталогов.

`git fsck --connectivity-only` до и после commit — чисто.

---

## 6. Validation

| Check | Expected | Actual | Result |
|---|---|---|---|
| Git preflight | ветка, HEAD, remote, upstream доступны | `wp-m0-maestro-audit`, `e3c391b`, `git@github.com:santfather/Mary_guinny.git`, upstream совпадает | PASS |
| Незавершённые операции Git | отсутствуют | отсутствуют, stash пуст, worktree один | PASS |
| Процессы: ComfyUI / worker / fake_worker / caffeinate | не запущены | не запущены, 8188 закрыт | PASS |
| launchd-агенты | проверены | `launchctl` → permission denied | NOT VERIFIED |
| FK integrity | 0 нарушений | 54 ограничения, 0 нарушений | PASS |
| Сверка job `852adc5d…` с аудитом | все условия совпадают | совпали | PASS |
| `pg_dump -Fc` | exit 0, файл создан | 509 510 Б, exit 0 | PASS |
| `pg_restore --list` | читается, без ошибок | 191 строка, 180 TOC, stderr пуст | PASS |
| Файловая копия | совпадение по числу и байтам | 190 файлов, все каталоги совпали | PASS |
| SHA-256 manifest | все файлы OK | 190/190 OK | PASS |
| Свободное место | достаточно | 62 GiB до, 66 GiB после | PASS |
| Отмена job | `status=cancelled`, lease пуст | `cancelled`, lease NULL, `error_code=cancelled` | PASS |
| Побочные эффекты отмены | 0 новых attempts/artifacts/events, шот не изменён | 0 / 0 / 0, шот без изменений | PASS |
| Backend tests | зелёные | **298 passed**, 1 warning, 17.98 s | PASS |
| Изоляция backend tests | не меняют рабочую БД | 6 строк `artifacts` закоммичены в `mary_studio` | **FAIL** |
| Root tests | 104 passed | 104 passed (`.venv/bin/python -m pytest tests`) | PASS |
| Root tests с `backend/.venv` | — | 102 passed, 2 failed (нет async-плагина) — ошибка окружения, не кода | NOT APPLICABLE |
| `alembic check` | no new operations | «No new upgrade operations detected», head `0011` | PASS |
| UI build | успешная сборка | `tsc --noEmit && vite build` → 59 модулей, 478 ms | PASS |
| `git diff --check` (рабочее дерево и индекс) | без ошибок | чисто | PASS |
| Секреты в изменениях | не найдены | не найдены | PASS |
| Миграция `0011` в Git | присутствует | `git ls-tree` → 1 файл | PASS |
| Backup-файлы в Git | отсутствуют | отсутствуют | PASS |
| Push защитной ветки | remote = локальный commit | `566cc3e…` на обоих | PASS |
| Целостность blob-хранилища | без изменений | 104 файла, 155 662 811 Б, реальные файлы не тронуты | PASS |
| Artifact ↔ файл | 198 расхождений (из аудита) | **204** расхождения (198 + 6 от тестового прогона) | **FAIL (регресс)** |

Тесты, требующие ComfyUI/моделей/GPU, не запускались: LTX-рендер, ComfyUI, реальные
видео-генерации в этом WP запрещены.

---

## 7. Decisions

Записаны в `docs/DECISIONS.md` §4.22 (baseline `docs/ARCHITECTURE.md` не изменялся):

1. Сборка B (attempt `3eb3ca9f…`, artifact `a5326a3f…`, `viseme_frame_blend_v1`)
   отклонена как производственный результат; попытка, видео и артефакт сохранены как
   история A/B; статус в БД не переписывался, `reject_attempt` не вызывался, approved
   viseme-референсы и калибровки не менялись.
2. `mouth_animation_mvp`, `pillow_mouth_v2`, `viseme_frame_blend_v1` — **experimental**.
   Код, API, тесты, UI и калибровки сохраняются; скрытие панелей и смена режима по
   умолчанию — только Stage 2 отдельного WP.
3. Rhubarb 1.14.0 — только диагностический источник таймингов (явный `use_rhubarb`), не
   автоматический production-процесс.
4. Lip sync — unavailable (`SELECTED_ENGINE = None`, 409 `lipsync_engine_not_selected`).
5. Аудиоинфраструктура (импорт аудио, PCM 48 кГц mono, огибающая, waveform,
   `projects.audio_artifact_id`, таймлайн/план) остаётся production-компонентом.
6. Возобновление экспериментов — отдельный WP с визуальными критериями приёмки.
7. Отсутствие эндпоинта отмены отдельной job зафиксировано как свойство контракта;
   операционная отмена выполняется сменой статуса строки на `cancelled` в транзакции с
   guard-условиями; новый эндпоинт требует отдельного утверждения.

---

## 8. Remaining Risks

| ID | Риск | Факт | Следствие |
|---|---|---|---|
| SR-01 | Artifact без файла | **204** строки (203 `project_audio`, 1 `note`), 19 500 829 Б | UI/экспорт могут ссылаться на несуществующий blob; нужно расследование |
| SR-02 | Изоляция backend-тестов | прогон добавил 6 `artifacts` в рабочую БД | повторные прогоны будут накапливать мусор; чинить в отдельном WP |
| SR-03 | Stale workers | 4 записи `active`, `last_seen_at` 19 ч … 8 сут | статус «воркер активен» недостоверен; lease-логика не затронута |
| SR-04 | GNS-01…04 | `prompt_ready`, стартового кадра нет (4 шота) | preflight заблокирует рендер этих шотов |
| SR-05 | 0 approved video attempts | `shots.approved_attempt_id` пуст во всех 44 шотах | финальный отбор дублей не зафиксирован |
| SR-06 | Память 18 GiB | доступно ≈3.1–3.9 GiB при пороге Eco 4 GiB | тяжёлый рендер возможен только после освобождения памяти |
| SR-07 | launchd | `NOT VERIFIED` (permission denied) | нельзя исключить скрытый агент воркера |
| SR-08 | Нет отмены отдельной job | только `POST /api/series/{id}/cancel` | операционные отмены требуют SQL или нового утверждённого эндпоинта |
| SR-09 | Расхождение с аудитом по storage | 103 файла / 155 656 663 Б против 104 / 155 662 811 Б | методика подсчёта требует унификации |
| SR-10 | Экспериментальный код в main-линии | 3 движка рта заморожены, но активны в API/UI | случайное использование в production до Stage 2 |

Примечание: версия ComfyUI и custom node, ранее помеченная как неподтверждённая, теперь
зафиксирована (0.42.0 / `0b05cd8a`, `d38b63ab`).

---

## 9. Next Work Package (только предложение, не выполнение)

**WP-STABILIZE-02 — Data Integrity Investigation**

1. Классифицировать 204 artifact без файла: тестовые (`project_audio` 2026-11-04…05,
   96 068 Б, 6 шт. за последний прогон) против реальных пользовательских; проверить, не
   ссылаются ли на них `projects.audio_artifact_id`, `shot_audio`, `production_plans`.
2. Устранить дефект изоляции backend-тестов (путь `POST /api/shots/{id}/audio`
   коммитит вне тестовой транзакции), затем подтвердить, что прогон не меняет рабочую БД.
3. Разобрать 4 stale workers и 2 orphan-blob (`storage/blobs/.DS_Store`,
   `storage/blobs/20/201bc4b0….wav`) — только с утверждённым планом.
4. Унифицировать методику подсчёта storage и пересобрать STORAGE_INVENTORY.
5. Только после этого — Stage 1 очистки (`CLEANUP_EXECUTION_PLAN.md`), отдельным WP.

Остановка. Stage 1/2 не начинались, рендер не запускался, 198/204 artifact-записи не
исправлялись, experimental-код не изменялся, миграции не создавались, merge в `main`
не выполнялся.
