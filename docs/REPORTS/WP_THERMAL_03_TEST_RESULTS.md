# WP-THERMAL-03 — Test results

> Дата: 2026-11-04. Разделы 1–4 — проверки без GPU (ComfyUI не запускался, питание
> не отключалось). Раздел 5 — выполненный по разрешению Q-41 Eco GPU acceptance test
> NLB-25 и тест Thermal Pause. Ветка `wp-m0-maestro-audit`.

---

## 1. Итоговые прогоны

### 1.1 Backend

```
$ cd backend && .venv/bin/python -m pytest -q
........................................................................ [ 29%]
........................................................................ [ 58%]
........................................................................ [ 88%]
.............................                                            [100%]
245 passed, 1 warning in 9.40s
```

Warning — внешний (`StarletteDeprecationWarning` про `httpx` в `fastapi/testclient.py`),
к WP не относится.

### 1.2 Корневые тесты (воркер, адаптер, thermal gate)

```
$ .venv/bin/python -m pytest tests -q
........................................................................ [ 69%]
................................                                         [100%]
104 passed in 0.22s
```

### 1.3 Миграции

```
$ cd backend && .venv/bin/alembic check
SAWarning: Cannot correctly sort tables; there are unresolvable cycles ... (существующее)
No new upgrade operations detected.
```

Новых миграций в WP-THERMAL-03 нет.

### 1.4 Frontend

```
$ cd ui && npm run build
> tsc --noEmit && vite build
vite v7.3.7 building client environment for production...
✓ 58 modules transformed.
dist/assets/index-szl2-hU9.js   338.23 kB │ gzip: 96.56 kB
✓ built in 424ms
```

---

## 2. Новые и изменённые тесты

### 2.1 `tests/test_thermal_gate.py` (корень)

| Тест | Что проверяет |
|---|---|
| `test_after_job_hot_state_blocks_snapshot_immediately[serious\|critical]` | после горячей job снимок сразу `allowed=false`, `reason=thermal_<state>`, пауза активна |
| `test_after_job_nominal_keeps_admission_until_cooldown` | при `nominal` допуск остаётся, но действует cooldown |
| `test_parse_low_power_mode_only_when_present` | `lowpowermode 0/1` → bool, отсутствие/мусор → `None` |
| `test_low_power_mode_reaches_telemetry_and_state` | `True`/`None` доходят до телеметрии и state-файла |
| `StubProbes.low_power_mode` (изменение) | реальный `pmset` в тестах не вызывается |

Существующие 34 теста (thermal transitions, питание, memory pressure, cooldown,
партия, рестарт, гистерезис, ротация журнала, caffeinate, freshness) не изменялись
по смыслу — прогнаны повторно; всего в файле 38 тестов.

### 2.2 `tests/test_ltx_worker.py` (корень)

| Тест | Что проверяет |
|---|---|
| `test_job_loop_stops_after_thermal_timeout` | `should_stop_waiting()` → код 1, ни одного claim |
| `test_build_thermal_gate_prefers_render_settings_profile` | профиль из `RenderSettings` важнее `args` |
| `test_process_one_marks_preview_in_provenance` | `preview=true` и `num_frames=73` в `render_attempts.parameters` |
| `test_process_one_production_has_no_preview_flag` | production-путь не пишет `preview` |

### 2.3 `backend/tests/test_queue.py`

| Тест | Что проверяет |
|---|---|
| `test_preview_render_is_separate_short_attempt` | 202 + `preview=true`, payload `frames=73`, `inputs.preview`, approve → 409, затем production job без preview с 193 кадрами |
| `test_done_preview_does_not_block_production_approval` | завершённый preview не мешает утвердить production-попытку |
| `test_claim_takes_advisory_guard_before_claim_sql` | `pg_advisory_xact_lock` выполняется до `_CLAIM_SQL`, `COMMIT` между ними нет |
| `test_claim_guard_is_skipped_for_non_render_kinds` | guard не применяется к `postprocess`/истёкшим lease |

### 2.4 `backend/tests/test_series_runs.py`

| Тест | Что проверяет |
|---|---|
| `test_series_next_busy_while_foreign_render_is_leased` | пока чужой `render_video` в `leased` → `busy`; после `completed` → `queued`; ровно 2 job за прогон |

### 2.5 `backend/tests/test_render_agent_status.py`

| Тест | Что проверяет |
|---|---|
| `test_status_reports_low_power_mode_only_as_bool` | `true` → `true`, `"yes"` → `null` |
| `test_status_reads_fresh_state` (изменён) | `power` содержит три ключа, включая `low_power_mode: null` |

---

## 3. Матрица покрытия требований задания

| Требование (раздел WP) | Покрытие |
|---|---|
| thermal state transitions | `test_hot_thermal_state_pauses`, `test_fair_and_nominal_allow_new_job`, `test_unknown_thermal_*`, `test_thermal_recovery_needs_two_nominal_samples` |
| power source transitions | `test_eco_requires_ac_power`, `test_eco_battery_needs_permission_and_charge`, `test_power_pause_clears_when_power_returns` |
| memory pressure | `test_eco_memory_checks`, `test_memory_pause_is_not_a_stop`, `test_parse_memory_outputs` |
| admission control | `_evaluate` тесты + `test_eco_unconfirmed_power_source_is_blocked` |
| single-render guard | `test_claim_takes_advisory_guard_before_claim_sql`, `test_claim_guard_is_skipped_for_non_render_kinds`, `test_claim_guard_ignores_postprocess_and_expired_leases`, `test_series_next_busy_while_foreign_render_is_leased` |
| cooldown | `test_cooldown_blocks_until_next_allowed`, `test_batch_cooldown_and_reset`, `test_fair_doubles_cooldown`, `test_cooldown_survives_restart` |
| worker restart | `test_thermal_pause_survives_worker_restart`, `test_cooldown_survives_restart` |
| lease recovery | `test_lease_expiry_waits_for_owner_recovery` |
| prompt idempotency | `test_recover_completes_render_without_new_prompt`, `test_recover_waits_for_prompt_still_running` |
| preview/prod separation | `test_preview_render_is_separate_short_attempt`, `test_done_preview_does_not_block_production_approval`, `test_process_one_*` |
| status API | `backend/tests/test_render_agent_status.py` (7 тестов) + живой `curl` |
| JSONL logging | `test_event_log_rotates`, `test_event_log_records_fixed_fields` |
| Energy Profile resolution | `test_build_thermal_gate_prefers_render_settings_profile`, `test_off_profile_allows_without_checks` |

---

## 4. Живые проверки без GPU

### 4.1 `GET /api/render-agent/status`

Backend запущен штатно (`uvicorn app.main:app --port 8000`).

**Без файлов воркера** — `worker_online=false`, `stale=true`, `thermal.state="unknown"`,
`power.source=null`, `low_power_mode=null`, `memory.pressure=null`, `admission.allowed=null`;
очередь из БД прочитана (`current_run_status="paused"`).

**С временным снимком** (`MARY_RENDER_AGENT_STATE_PATH=/tmp/wp-thermal-03-verify/thermal-state.json`,
`MARY_RENDER_AGENT_EVENTS_PATH=.../thermal-events.jsonl`) ответ:

```json
{
  "worker_online": true, "stale": false, "profile": "eco",
  "thermal": {"state": "serious", "source": "process_info"},
  "power": {"source": "battery", "battery_percent": 42.0, "low_power_mode": null},
  "memory": {"pressure": "normal", "pressure_level": 1, "available_mb": 6144},
  "admission": {"allowed": false, "reason": "thermal_serious", "wait_seconds": 30.0},
  "cooldown": {"remaining_seconds": 420.0},
  "pause": {"active": true, "reason": "thermal_serious", "waited_seconds": 180.0},
  "batch": {"index": 1, "size": 3}
}
```

Production-файлы `~/.mary-studio/thermal-state.json` и `thermal-events.jsonl`
не создавались и не перезаписывались.

### 4.2 UI-панель «Термозащита» (`#/series/{id}`)

Vite dev server + тот же backend, браузер без GPU-рендера. Видимый текст панели:

```
Термозащита                                  воркер на связи
Профиль: Eco · thermal: Serious (process_info)
Питание: батарея · заряд 42% · Low Power Mode: Unknown
Память: Normal · свободно 6144 МБ
Партия: 1/3 · очередь: 0 активно, 0 ждёт
Допуск: заблокирован · до следующего задания: 1 мин
Пауза термозащиты: перегрев (Serious) · с 2026-11-04T16:18:30Z · ожидание 3 мин · до следующего шота 7 мин
Последнее событие: decision · перегрев (Serious) · 2026-11-04T16:18:30Z
```

Прочерков `—` в панели нет, запросов с ошибкой нет (`/api/render-agent/status` → 200,
консоль чистая).

### 4.3 Живые показания системы (только чтение)

```
~/.mary-studio/bin/mary-thermal-state  → {"source":"process_info","state":"nominal"}
pmset -g ps                            → 'AC Power' … 100%; finishing charge
pmset -g | grep lowpowermode           → lowpowermode 0
sysctl -n kern.memorystatus_vm_pressure_level → 1
sysctl -n hw.memsize                   → 19327352832 (18 ГиБ)
```

### 4.4 Гигиена репозитория

```
$ git branch --show-current
wp-m0-maestro-audit
$ git ls-files | grep -Ei '\.(mp4|mov|m4v)$'
(пусто)
$ git check-ignore -v export/
.gitignore:28:export/   export/
```

`export/` — 241 МБ, файлы на месте.

---

## 5. Живой Eco GPU acceptance test NLB-25 (2026-11-04)

Выполнен по `docs/PROPOSALS/THERMAL_GPU_ACCEPTANCE_PLAN.md` с разрешения человека
(Q-41). Подробный протокол — §8 плана.

### 5.1 Идентификаторы

| Сущность | Значение |
|---|---|
| Прогон | `f163f8b7-8c8b-47f6-a29a-8592eafcef19`, 1 item, `completed` |
| Job | `0aa6d22f-d886-4e29-b313-16b4fd45ea52`, `completed`, 1 попытка |
| RenderAttempt | `96e16d5a-bbfe-4e27-b3d2-241df980f3d7`, `completed`, 8.042 с |
| Артефакт | `af057b6c-13df-42ca-a785-5f319f4b98c9`, `video/mp4`, 3 137 749 B |
| ComfyUI prompt | `df8fc2e0-a61b-461d-911e-92aef9042775` |
| Seed / пик RAM | `950087778` / `16295` МБ (план: `925049040`; seed вычислен из `attempt_id`) |

### 5.2 Thermal Pause (без отключения питания)

- Воркер с `/tmp/mary-thermal-fake-helper` (`state=serious`): `thermal: thermal_serious;
  ждём 5 с`, `SeriesRun.status='paused'`, job не создан, ComfyUI `/history` пуст.
- `GET /api/render-agent/status` (по временному `/tmp`-снимку): `profile='eco'`,
  `thermal.state='serious'`, `thermal.source='test_helper'`, `pause.active=true`,
  `pause.reason='thermal_serious'`.
- `POST /api/series/{run_id}/resume` → `running`; далее production-путь завершился
  `completed` (шаг 3 раздела 4 плана).

### 5.3 Результаты рендера

```
ffprobe: h264 576x1024, 24/1 fps, aac 48000 Hz stereo, duration 8.041667, size 3137749
```

`render_attempts.parameters`: `preset='safe'`, `preset_source='cli'`,
`thermal.profile='eco'`, `thermal.thermal_state='nominal'`, `thermal.power_source='ac'`,
`battery_percent=100.0`, `low_power_mode=false`, `memory_pressure='normal'`,
`available_mb=7113`, `num_frames=193`, `preview` отсутствует, `workflow_snapshot.low_ram=false`.

`shots.approved_attempt_id` остался `NULL`; старые попытки `ef866aac…` и `565c910d…` целы.
После выхода воркера `pgrep -fl caffeinate` пуст, `/history` содержит ровно одну запись.

### 5.4 Cooldown и питание

- После `after_job` в state Eco: `remaining_seconds=479.9` (`next_allowed_at` = +480 с).
- Живая проверка допуска сразу после рендера: `allowed=false`, `reason='power_not_ac'` —
  к этому моменту ноутбук уже работал от батареи (во время рендера было `ac`).
  Правило Eco «только сеть» сработало; cooldown как единственную причину блокировки
  вживую проверить не удалось (покрыт тестами `test_cooldown_*`).

### 5.5 Ограничение sandbox

Долгоживущий воркер не может писать `~/.mary-studio/thermal-state.json` и
`thermal-events.jsonl` (`[Errno 13] Permission denied`), поэтому production-журнал не
вырос, а `GET /api/render-agent/status` во время рендера показывал `worker_online=false`;
телеметрия сохранилась в `render_attempts.parameters`, state/log снимались по путям в
`/tmp`. Короткие процессы в те же пути писали успешно — это ограничение среды, не кода.

### 5.6 Наблюдение по памяти

При `peak_mem_mb=16295` (≈88 % RAM) в процессе рендера зафиксированы
`min_available_mb=2137` и `max_pressure_level=4` (critical). Eco-гейт проверяет память
только до job, поэтому это не блокируется; фиксируется как риск.

---

## 6. Что осталось не проверенным

| Не проверено | Причина | Как проверить |
|---|---|---|
| Cooldown как единственная причина отказа в claim | после рендера ноутбук был на батарее — сработал `power_not_ac` | подключить сеть и сразу после рендера запустить воркер: ожидается `thermal: cooldown; ждём …` |
| Production `thermal-events.jsonl` и `/api/render-agent/status` во время рендера | sandbox запрещает запись в `~/.mary-studio` | штатный запуск воркера вне sandbox-обёртки, затем `curl /api/render-agent/status` |
| Orphan-процессы `caffeinate` после `kill -9` | живой рендер завершился штатно | убить воркер во время рендера и проверить `pgrep -fl caffeinate` |
| Многопоточная гонка двух claim | есть тест на порядок блокировки, не на параллельные потоки | два процесса `worker/ltx_worker.py --once` против временной БД |
| Панель на production-снимке во время рендера | тот же sandbox-запрет | после запуска вне sandbox открыть `#/series/{id}` |

---

## 7. Совместимость

- Схема БД не менялась: `alembic check` — «No new upgrade operations detected».
- Existing API без тела запроса работает как раньше: `POST /api/shots/{id}/render`
  с пустым телом = production (`preview=false`).
- Старые `RenderAttempt` без `parameters.preview` трактуются как production.
- Старые снимки `thermal-state.json` без `low_power_mode` → `null` (Unknown), ошибок нет.
