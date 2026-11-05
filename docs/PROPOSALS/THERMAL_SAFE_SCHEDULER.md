# Thermal-Aware Scheduler для Mary Studio (WP-THERMAL-01, проект)

> **Статус:** предложение к согласованию. Код не изменён. Сейчас — только дизайн.
> **Дата:** 2026-11-04.
> **Опирается на:** `docs/PROPOSALS/THERMAL_RENDER_AUDIT.md` (находки F-01…F-17),
> `docs/ARCHITECTURE.md` C28, §6.2, §6.4, §11; `docs/DECISIONS.md` §4.14 (пресеты).
> **Ограничения задания:** Reuse First / KISS / DRY / YAGNI; отдельная очередь не
> создаётся; настройки macOS и вентиляторы не переключаются; тяжёлые модели не
> добавляются; merge/push — только по разрешению.

---

## 1. Цель и границы

**Цель:** сделать так, чтобы серия рендеров не превращалась в 7-часовой непрерывный
нагрев. Между шотами и партиями появляются паузы, при перегреве запуск блокируется,
решения видны человеку и попадают в журнал.

**Не входит:** новая очередь, новый тип job, изменение схемы БД, управление
вентиляторами, отключение thermal throttling, автоматическое переключение
системных настроек macOS, гарантия конкретной мощности GPU.

**Принцип размещения.** Планировщик живёт **в воркере** — это единственный процесс,
который знает ComfyUI, локальное железо и момент запуска. Сервер остаётся источником
истины о job/серии. Проверки выполняются **до** того, как job будет создана или взята,
поэтому блокировка не приводит к «висящему» lease.

---

## 2. Точки интеграции (без новой очереди)

| Точка | Файл | Что меняется |
|---|---|---|
| G1. Перед созданием следующей job серии | `worker/ltx_worker.py::_series_loop` | вызов `scheduler.before_next()` **до** `api.series_next()` |
| G2. Перед взятием job из общей очереди | `worker/ltx_worker.py::_job_loop` | вызов `scheduler.before_next()` **до** `api.claim()` |
| G3. После завершения шота | `worker/ltx_worker.py::_process_job` | `scheduler.after_job(ok=...)` — счётчик партии, время окончания |
| G4. Перед `POST /prompt` | `worker/ltx_worker.py::_render` | повторная короткая проверка thermal state (устройство могло нагреться за время подготовки) |
| G5. Пауза/возобновление серии | `backend/app/api/series_runs.py` | используются существующие `pause`/`resume`; сервер только принимает решение воркера |
| G6. Уведомление | `backend/app/notify.py` | баннер на Thermal Pause / возобновление |
| G7. Телеметрия попытки | `worker/client.py::complete` + `worker.py` | `peak_mem_mb` и `parameters["thermal"]` (без миграции) |
| G8 (опция, требует утверждения) | `backend/app/api/series_runs.py::series_next` | серверный guard «нет другого активного `render_video`» — страховка от второго воркера |

Почему не сервер: сервер не может честно прочитать thermal state Mac и не должен
принимать аппаратные решения за воркер. Почему не отдельный процесс-демон: это была бы
вторая очередь/второй владелец состояния (нарушает KISS и «не создавать отдельную
очередь»).

---

## 3. Конфигурация

Все значения — конфигурируемые; приоритет **CLI > env > профиль > default**
(как в WP-M7 для пресетов).

| Параметр | Env | Default | Смысл |
|---|---|---|---|
| `max_concurrent_gpu_jobs` | `MARY_MAX_CONCURRENT_GPU_JOBS` | `1` | одновременно тяжёлых рендеров; >1 не поддерживается |
| `max_consecutive_renders` | `MARY_MAX_CONSECUTIVE_RENDERS` | `3` | шотов в партии до длинной паузы |
| `cooldown_between_jobs_seconds` | `MARY_COOLDOWN_BETWEEN_JOBS` | `480` | пауза между шотами (8 мин) |
| `cooldown_after_batch_seconds` | `MARY_COOLDOWN_AFTER_BATCH` | `1200` | пауза после партии (20 мин) |
| `thermal_guard_enabled` | `MARY_THERMAL_GUARD` | `true` | общий выключатель guard'а |
| `thermal_recovery_required` | `MARY_THERMAL_RECOVERY_REQUIRED` | `true` | после Serious/Critical нужен возврат в nominal и выдержка |
| `thermal_poll_seconds` | `MARY_THERMAL_POLL` | `60` | период опроса состояния во время ожидания |
| `thermal_recovery_samples` | `MARY_THERMAL_RECOVERY_SAMPLES` | `2` | сколько подряд `nominal` нужно |
| `thermal_recovery_cooldown_seconds` | `MARY_THERMAL_RECOVERY_COOLDOWN` | `600` | выдержка после восстановления |
| `thermal_max_wait_seconds` | `MARY_THERMAL_MAX_WAIT` | `21600` | 6 ч: дольше не ждём без человека |
| `min_available_memory_bytes` | `MARY_MIN_AVAILABLE_MEMORY` | `4 GiB` | порог свободной памяти |
| `require_ac_power` | `MARY_REQUIRE_AC` | `true` | рендер только от сети |
| `min_battery_percent` | `MARY_MIN_BATTERY_PERCENT` | `50` | при работе от батареи (если `require_ac=false`) |
| `heartbeat_every_polls` | `MARY_HEARTBEAT_EVERY_POLLS` | `6` | heartbeat раз в 30 с при `poll_interval=5` |
| `energy_profile` | `MARY_ENERGY_PROFILE` | `balanced` | `eco` / `balanced` / `performance` |

`max_concurrent_gpu_jobs > 1` — не ошибка конфигурации, а явный отказ на старте
(сообщение: «параллельный GPU-рендер не поддерживается»).

---

## 4. Состояние планировщика

Хранится локально, переживает рестарт воркера:

`~/.mary-studio/thermal-state.json`

```json
{
  "profile": "eco",
  "batch_index": 2,
  "batch_size": 3,
  "last_job_finished_at": "2026-11-04T14:22:10+00:00",
  "next_allowed_at": "2026-11-04T14:30:10+00:00",
  "consecutive_jobs": 2,
  "thermal_pause": {
    "active": true,
    "reason": "thermal_serious",
    "since": "2026-11-04T14:22:12+00:00",
    "run_id": "…",
    "paused_by_scheduler": true
  },
  "last_thermal_state": "serious",
  "last_thermal_source": "process_info",
  "updated_at": "2026-11-04T14:22:12+00:00"
}
```

Правила:
- запись атомарная (`*.tmp` + `os.replace`), как у state-файла prompt'ов (WP-M4);
- используется **wall clock**, а не `monotonic`, иначе cooldown «обнулится» при рестарте;
- если файла нет или он битый — состояние «как после холодного старта», но с
  обязательной паузой `cooldown_after_batch_seconds` перед первым шотом (безопаснее);
- `thermal_pause.paused_by_scheduler=true` — единственный случай, когда планировщик
  вправе сам снять паузу. Паузу, поставленную человеком, он не трогает.

Журнал решений (append-only, не БД):

`~/.mary-studio/thermal-events.jsonl` — по строке на решение:
`{ts, decision, reason, thermal_state, source, memory_pressure, available_mb, swap_mb,
power, battery_pct, lowpowermode, batch_index, waited_s, run_id, job_id}`.

Имена событий в таблице `events` не расширяются: `ck_events_event` разрешает только
`claimed/progress/artifact_uploaded/completed/failed/lease_expired/resumed`. Расширение
— отдельной миграцией по разрешению.

---

## 5. Источники thermal state

Абстракция `ThermalSource` с методом `read() -> ThermalReading(state, source)`:

| Источник | Реализация | Значения |
|---|---|---|
| `process_info` | Swift-helper (сборка локально, `swiftc`, без зависимостей) | `nominal` / `fair` / `serious` / `critical` |
| `pmset` | `pmset -g therm` — **только** записи о прошедших событиях | `unknown` при пустом выводе |
| `none` | по умолчанию, если helper не собран | `unknown` |

Правила:
- `serious`/`critical` — блокировка;
- `fair` — **дополнительная** пауза: `max(cooldown_between_jobs, 2 × cooldown_between_jobs)`
  (консервативно), без блокировки;
- `unknown` — консервативный режим: пауза между шотами
  `max(cooldown_between_jobs, 900)`, партия `min(max_consecutive_renders, 2)`, и
  обязательное уведомление один раз за прогон: «thermal state недоступен, работаем
  по консервативному расписанию»;
- `pmset -g therm` не считается источником `nominal` никогда.

---

## 6. Алгоритм решения

```
before_next():
  if not thermal_guard_enabled: return ALLOW("guard_disabled")
  1. если thermal_pause.active:
       if thermal_recovery_required and not recovered(): return WAIT("thermal_pause")
       if not recovered(): return ALLOW("recovery_not_required")
  2. thermal = read()
     serious|critical          → PAUSE("thermal_<state>")   # пауза серии + уведомление
  3. power = pmset -g ps
     require_ac and on_battery → BLOCK("power_not_ac")
     battery < min_battery_pct → BLOCK("battery_low")
  4. memory:
     pressure_level >= 2       → BLOCK("memory_pressure_high")
     available < min_memory    → BLOCK("memory_low")
     (swap > threshold — WARN, не блок)
  5. if now < next_allowed_at   → WAIT("cooldown", until=next_allowed_at)
  6. if other heavy job active  → WAIT("other_heavy_job")   # сервер/локальная проверка
  7. if consecutive_jobs >= batch_size → WAIT("batch_cooldown")
  8. return ALLOW
```

`WAIT` — не ошибка: воркер спит `min(thermal_poll_seconds, остаток)` и проверяет снова,
периодически продлевая баннер/статус. `BLOCK` — отказ с кодом в журнал и в UI; серия
переводится в `paused` с причиной (см. §7).

`after_job(ok)`:
- `consecutive_jobs += 1`, `batch_index += 1`;
- `last_job_finished_at = now`;
- если `consecutive_jobs >= batch_size` → `next_allowed_at = now + cooldown_after_batch`,
  `consecutive_jobs = 0`;
- иначе `next_allowed_at = now + cooldown_between_jobs` (при `fair`/`unknown` — больше);
- `ok=false` (в т.ч. `external_prompt_lost`) → повтор считается ещё одним шотом партии;
- состояние сохраняется на диск **до** возврата управления.

`recovered()`: `thermal_recovery_samples` подряд чтений `nominal` с интервалом
`thermal_poll_seconds`, затем ещё `thermal_recovery_cooldown_seconds` ожидания.

---

## 7. Thermal Pause: поведение

1. `serious`/`critical` → воркер **не** берёт новую job и **не** создаёт следующую.
   Текущий рендер **не убивается** (небезопасно и запрещено); он досчитывается,
   результат сохраняется.
2. Если воркер работает в режиме серии — вызывается существующий
   `POST /api/series/{run_id}/pause`, в state-файл пишется
   `thermal_pause.paused_by_scheduler = true`.
3. Уведомление человеку (баннер + строка в журнале + статус в UI): состояние, причина,
   сколько ждём, как остановить.
4. Ожидание восстановления; при `thermal_recovery_required` — гистерезис (§6).
5. После восстановления: если пауза поставлена планировщиком — `resume` и уведомление
   «продолжаю». Если пауза поставлена человеком — ничего не делаем.
6. Защита от бесконечного ожидания: `thermal_max_wait_seconds` (6 ч) → уведомление
   «жду слишком долго, останавливаюсь» и прогон остаётся `paused`; воркер выходит из
   режима серии. Никаких «тихих» многочасовых зависаний.
7. Ручная остановка: `cancel` работает всегда (существующий эндпоинт); `SIGINT/SIGTERM`
   — завершение после текущего рендера, без обрыва ComfyUI.

---

## 8. Energy Profiles

Профиль управляет **расписанием и параметрами рендера**, но не является гарантией
ватт. Пресет (`safe`/`wide`/`legacy_512`) остаётся отдельной сущностью: профиль задаёт
политику, пресет — разрешение/длину.

| Параметр | Eco | Balanced | Performance |
|---|---|---|---|
| `max_consecutive_renders` | 3 | 3 | 3 |
| `cooldown_between_jobs_seconds` | 480 | 480 | 180 |
| `cooldown_after_batch_seconds` | 1200 | 1200 | 600 |
| `thermal_max_wait_seconds` | 21600 | 21600 | 3600 |
| `low_ram` (шаблон) | `true` | `false` | `false` |
| `cfg_scale` | 3.0 (без изменений) | 3.0 | 3.0 |
| preview-first по умолчанию | да | нет | нет |
| требует подтверждения при снижении качества | да | нет | нет |
| `require_ac_power` | true | true | true |

Важно:
- значения по умолчанию **совпадают с заданием** (`3` / `480` / `1200`);
- Eco **не меняет** разрешение и число кадров production-шота без явного согласия:
  единственное отличие — `low_ram` и более строгие паузы. Снижение разрешения/кадров
  доступно только в preview-first (§10), не в production;
- `Performance` не отключает guard и не отключает throttling — он только сокращает
  cooldown; при `serious`/`critical` блокировка действует так же;
- **Low Power Mode**: только чтение (`pmset -g` → `lowpowermode`). UI показывает
  состояние и подсказывает включить вручную для Eco. Автоматическое переключение
  запрещено (задание, этап 4).

**Фактическое состояние (2026-11-04, WP-THERMAL-02/03):**

- реализованы профили `off` / `balanced` / `eco`; профиля `Performance` в коде **нет**
  (таблица выше — проектное предложение, а не реализация);
- `low_ram` в Eco **не включается**: строка `low_ram=true` в таблице не реализована,
  условие — энергетический тест Q-38 (`DECISIONS.md` §4.16 п.7);
- чтение Low Power Mode добавлено в WP-THERMAL-03: `pmset -g` → `low_power_mode`
  в `GET /api/render-agent/status`, в `render_attempts.parameters.thermal` и в
  `thermal-state.json`; `null` = Unknown. Глобальные настройки macOS не меняются;
- профиль передаётся в рендер через `RenderSettings.thermal_profile` (CLI `--thermal-profile`
  → `MARY_THERMAL_PROFILE` → `balanced`), сам профиль меняет только допуск, паузы и
  cooldown; разрешение, `num_frames`, FPS, seed, cfg и workflow не меняются.

---

## 9. UI (Render Agent)

Нужен один read-only источник состояния. Предложение (требует утверждения как
аддитивное расширение API):

`GET /api/render-agent/status` →

```json
{
  "worker_online": true,
  "profile": "eco",
  "thermal": {"state": "fair", "source": "process_info", "updated_at": "…"},
  "power": {"source": "ac", "battery_pct": 100},
  "lowpowermode": false,
  "memory": {"pressure_level": 1, "available_mb": 6800, "swap_used_mb": 2137},
  "queue": {"active_render_jobs": 1, "pending_jobs": 2, "current_run_id": "…"},
  "batch": {"index": 2, "size": 3},
  "next_job_at": "2026-11-04T14:30:10+00:00",
  "pause": {"active": true, "reason": "thermal_serious", "since": "…"},
  "last_events": [
    {"ts": "…", "decision": "pause", "reason": "thermal_serious"}
  ]
}
```

Реализация без новой таблицы: сервер читает `~/.mary-studio/thermal-state.json` и
хвост `thermal-events.jsonl` (воркер и сервер на одной машине). Если файлов нет —
`worker_online=false` и `thermal.state="unknown"`.

UI (на `#/series/{id}` и на `#/shots`):
- выбор Energy Profile (передаётся воркеру через CLI/env при следующем запуске, не
  на лету — либо через новый писатель, что требует отдельного решения);
- бейдж Thermal State с источником (`process_info` / `unknown`);
- состояние очереди и «время до следующего шота»;
- счётчик роликов в партии (2/3);
- Pause / Resume / Stop after current (существующие действия);
- история температурных событий (из `thermal-events.jsonl`);
- длительность рендеров (wall-clock из событий `claimed` → `completed`, а не
  `duration_s` видео).

Запрещено: показывать «температуру» или «% мощности GPU», если источник её не даёт;
Unknown отображается как Unknown.

**Фактическая реализация (WP-THERMAL-02/03).** Скетч выше — проект; реализован
контракт с другим составом полей (`docs/DECISIONS.md` §4.16 п.3, §4.17 п.3):
`worker_online`, `stale`/`age_seconds`/`updated_at`, `profile`, `rendering`,
`current_job_id`, `thermal{state,source}`, `power{source,battery_percent,low_power_mode}`,
`memory{pressure,pressure_level,available_mb}`, `admission{allowed,reason,wait_seconds}`,
`cooldown{next_allowed_at,remaining_seconds}`, `pause{active,reason,since,waited_seconds}`,
`batch{index,size}`, `queue{active_render_jobs,pending_render_jobs,current_run_id,current_run_status}`,
`last_events[]`. Выбора профиля в UI нет (write-API не вводился, Q-32); панель на
`#/series/{id}` показывает профиль, thermal state, питание, Low Power Mode, память,
партию, очередь, допуск, cooldown, время до следующего задания и причину блокировки,
неизвестные значения — `Unknown`.

---

## 10. Preview-first (этап 6)

- Preview и production — **разные** RenderAttempts (в существующем поле
  `render_attempts.kind` нового значения нет; preview остаётся `kind='video'`, отличие
  фиксируется в `parameters.preview=true` и `parameters.num_frames`).
- Preview: `num_frames` ≈ 41–49 (5–6 с) при том же разрешении и seed; production:
  утверждённые 193 кадра.
- Утверждение preview — существующий `POST /api/shots/{id}/attempts/{attempt_id}/approve`
  (WP-M1), без нового писателя.
- Предупреждение §7.4 обязательно в UI и в отчёте: смена числа кадров/параметров
  **не** обещает побитово идентичный результат даже при том же seed.
- Для production всегда используется утверждённый стартовый кадр и утверждённый
  motion-промпт; preview не имеет права их менять.

**Фактическая реализация (WP-THERMAL-03, `DECISIONS.md` §4.17 п.4).** Отклонения от
проекта:

- число кадров preview — **73** (3.04 с при 24 fps), а не 41–49: 73 — уже проверенная
  конфигурация WP-00A (`512×512/73/24`), и она даёт предсказуемую длину;
- превью **нельзя утвердить**: `POST /api/shots/{id}/attempts/{id}/approve` для
  preview-попытки возвращает 409 `preview_cannot_be_approved` (проект предполагал
  approve существующим эндпоинтом);
- тела запроса `{"preview": true}` у `POST /api/shots/{id}/render` достаточно; в job
  payload уходят `preview=true` и `frames=73`, в `RenderAttempt.parameters` — `preview=true`,
  в ответе — `preview`;
- production-рендер и `shots.approved_attempt_id` не затрагиваются; UI показывает бейдж
  `preview` и скрывает approve/«Сделать текущей» для таких попыток.

---

## 11. Тесты (без GPU)

Unit (новый `tests/test_thermal_scheduler.py`, `tests/test_ltx_worker.py` — расширение):

1. Gate-матрица: `serious` → PAUSE; `critical` → PAUSE; `unknown` → консервативный
   интервал; `fair` → удвоенный cooldown; `nominal` → ALLOW.
2. `require_ac_power=true` + «Battery Power» → BLOCK `power_not_ac`; заряд ниже порога →
   BLOCK `battery_low`.
3. `memorystatus_vm_pressure_level=2` → BLOCK `memory_pressure_high`; доступная память
   ниже порога → BLOCK `memory_low`.
4. Cooldown: после `after_job` до `next_allowed_at` вызов `series_next` не происходит.
5. Партия: 3 шота → третья пауза `cooldown_after_batch`; счётчик сбрасывается.
6. Персистентность: рестарт между шотами → cooldown сохраняется (wall clock).
7. Восстановление: 2 подряд `nominal` + выдержка → `resume` вызван; пауза человека
   (`paused_by_scheduler=false`) → `resume` не вызывается.
8. `thermal_max_wait` → уведомление и остановка, без бесконечного цикла.
9. `ThermalSource`: пустой `pmset -g therm` → `unknown`; отсутствие helper → `unknown`.
10. `max_concurrent_gpu_jobs=2` → ошибка старта.
11. Heartbeat: при `poll_interval=5` и `heartbeat_every_polls=6` число heartbeat ≤
    ceil(время/30) + 1.
12. Телеметрия: `complete()` отправляет `peak_mem_mb` и `parameters["thermal"]`;
    `worker.complete` их сохраняет.

Интеграционные (FakeWorker + существующий API, без ComfyUI и GPU):

13. Серия из 3 шотов с cooldown 0 → 3 completed; с cooldown 60 → между job есть
    `next_allowed_at`, job не создаётся раньше.
14. Thermal Pause → `SeriesRun.status='paused'`, причины в журнале, `resume` возвращает
    `running`.
15. Повторный запуск воркера во время паузы → пауза сохраняется, дублей job нет.
16. `GET /api/render-agent/status` без файлов → `worker_online=false`,
    `thermal.state='unknown'` (после утверждения эндпоинта).

Проверки проекта для отчёта: `backend/.venv/bin/python -m pytest tests -q`,
корневой `.venv/bin/python -m pytest tests -q`, `backend/.venv/bin/alembic check`
(должно быть «no new operations»), `cd ui && npm run build`.

---

## 12. Минимальный план реализации

| Шаг | Содержание | Миграции/API | Статус |
|---|---|---|---|
| T-02 | `worker/thermal.py`: `ThermalSource`, `MemoryProbe`, `PowerProbe`, state-файл, журнал; gate `before_next`/`after_job`; CLI/env | нет | Выполнен (WP-THERMAL-02) |
| T-03 | Интеграция gate в `_series_loop`/`_job_loop`/`_render`; Thermal Pause через существующие `pause`/`resume`; уведомления | нет | Выполнен (WP-THERMAL-02) |
| T-04 | Телеметрия: `peak_mem_mb`, `parameters["thermal"]`, `render_seconds`; heartbeat раз в 30 с | нет | Выполнен (WP-THERMAL-02) |
| T-05 | Эндпоинт статуса + UI-панель Render Agent | +1 read-only эндпоинт (утвердить) | Выполнен (WP-THERMAL-02; панель расширена в WP-THERMAL-03) |
| T-06 | Energy profiles в `RenderSettings` + Eco/Low Power Mode (только чтение) | нет | Выполнен (WP-THERMAL-03) |
| T-07 | Preview-first: параметры preview, запись `parameters.preview` | нет | Выполнен (WP-THERMAL-03, 73 кадра, approve → 409) |
| T-08 | Серверный guard «один активный render_video» (F-01) — по решению человека | поведение `series/next`, без схемы | Выполнен (WP-THERMAL-02) |
| T-09 | Опциональный Swift-helper `ProcessInfo.thermalState` (сборка в `scripts/`) | нет зависимостей | Выполнен (WP-THERMAL-02) |

Порядок обязательный: T-02 → T-03 → T-04 → T-05; профили и preview — после того, как
guard работает и измеряется. Все шаги закрыты; ни один живой GPU-прогон под Eco
не выполнялся — это отдельный acceptance test (`docs/PROPOSALS/THERMAL_GPU_ACCEPTANCE_PLAN.md`).

---

## 13. Критерии приёмки

1. При `thermal_guard_enabled=true` ни один шот не начинается без пройденных проверок
   (порядок §6), и это подтверждено тестами на fake-источниках.
2. При `serious`/`critical` новые job не создаются и не берутся; текущий рендер
   досчитывается; человек получает уведомление; журнал содержит причину.
3. При `unknown` работают консервативные интервалы, и UI не показывает выдуманное
   значение.
4. Cooldown и счётчик партии выдерживаются между шотами и переживают рестарт воркера.
5. Ни один сценарий не приводит к бесконечному ожиданию: `thermal_max_wait_seconds`
   останавливает прогон с уведомлением.
6. Ручные `pause`/`cancel`/`stop-after-current` работают как раньше; планировщик не
   снимает чужую паузу.
7. Существующие тесты не ослаблены: backend 245 passed, корень 104 passed,
   `alembic check` чист, `npm run build` ✓ (факт на 2026-11-04, WP-THERMAL-03).
8. Все автоматические решения планировщика присутствуют в журнале и в
   `render_attempts.parameters.thermal`.

---

## 14. Риски дизайна

| Риск | Смягчение |
|---|---|
| Паузы растягивают серию с 7 ч до 10–11 ч | принято сознательно (скорость — вторичный приоритет); профиль `Performance` сокращает паузы |
| Без helper состояние Unknown → медленнее | helper опционален, но рекомендуется; Unknown не блокирует работу |
| Планировщик конкурирует с человеком за `pause`/`resume` | флаг `paused_by_scheduler`; человек всегда приоритетнее |
| Сложность воркера растёт | выделенный `worker/thermal.py`, интеграция в 3 точках |
| Серверный guard меняет поведение очереди | вынесен в отдельный шаг T-08 и требует утверждения |
| `pmset`/`sysctl` меняют формат | терпимый парсер, при сбое — Unknown + консервативный режим |

---

## 15. Что нужно от человека перед реализацией

1. Утвердить дизайн (этот документ) и объём первого шага (T-02…T-04 без UI).
2. Решить по трём вопросам из `THERMAL_RENDER_AUDIT.md` §11: helper, серверный guard,
   read-only эндпоинт статуса.
3. Разрешить бенчмарк отдельно — см. `RENDER_ENERGY_BENCHMARK.md`.
