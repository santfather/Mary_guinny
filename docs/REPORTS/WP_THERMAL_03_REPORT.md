# WP-THERMAL-03 — Stabilization, Thermal Validation & Production Readiness

> Дата: 2026-11-04. Ветка: `wp-m0-maestro-audit` (новая ветка не создавалась).
> Коммитов, merge, rebase, reset и push не выполнялось.
> В ходе WP GPU-рендеров не планировалось; по разрешению Q-41 отдельно выполнен один
> контролируемый Eco acceptance test NLB-25 (раздел 11.2). Решения — `docs/DECISIONS.md` §4.17.

---

## 1. Repository safety

| Проверка | Результат |
|---|---|
| `git status` до изменений | рабочее дерево содержало изменения WP-M1…M8, WP-THERMAL-02 и UI без коммитов; чужие изменения не перезаписывались |
| Ветка | `wp-m0-maestro-audit` |
| `.gitignore` | добавлено правило `export/` (`.gitignore:28`); `exports/*`/`.gitkeep` не тронуты |
| Отслеживаемые видео | `git ls-files \| grep -Ei '\.(mp4\|mov\|m4v)$'` → пусто |
| Что игнорируется | `git check-ignore -v export/` → `.gitignore:28:export/   export/` |
| Объём `export/` | 241 МБ; файлы **не удалялись и не перемещались** |
| Runtime-артефакты в индексе | нет: `~/.mary-studio/*` вне репозитория, `storage/` уже игнорируется |
| `git add -A` | не выполнялся; коммитов нет |

Изменённые файлы WP-THERMAL-03:

```
.gitignore
backend/app/api/render_agent.py
backend/app/api/shot_schemas.py
backend/app/api/shots.py
backend/app/api/worker.py
backend/tests/test_queue.py
backend/tests/test_render_agent_status.py
backend/tests/test_series_runs.py
tests/test_ltx_worker.py
tests/test_thermal_gate.py
ui/src/api/client.ts
ui/src/api/types.ts
ui/src/attemptMeta.ts
ui/src/pages/AttemptsPage.tsx
ui/src/pages/SeriesRunPage.tsx
ui/src/pages/ShotDetailPage.tsx
worker/ltx_worker.py
worker/thermal.py
```

Документация: `docs/DECISIONS.md` (§4.17, §6, §7, §8), `docs/OPEN_QUESTIONS.md`,
`docs/ROADMAP_MARY_STUDIO.md` §6, `docs/PROPOSALS/THERMAL_SAFE_SCHEDULER.md` §8–§13,
`i_will_do_it_later.md`, а также новые `docs/REPORTS/*` и
`docs/PROPOSALS/THERMAL_GPU_ACCEPTANCE_PLAN.md`.

---

## 2. Фактическое состояние WP-THERMAL-02 (аудит кода)

| № | Компонент | Файл | Статус |
|---|---|---|---|
| 1 | Thermal state reader | `worker/thermal.py` (`parse_thermal_output`, `ThermalSource`) | Implemented and tested (parse/helper-failure/unknown) + живой helper |
| 2 | Swift helper | `scripts/mac_thermal_state.swift` → `~/.mary-studio/bin/mary-thermal-state` | Implemented and tested (сборка и запуск проверены вручную) |
| 3 | Power source detection | `parse_pmset_ps`, `PowerProbe` | Implemented and tested + живой `pmset -g ps` (AC 100 %) |
| 4 | Memory pressure | `parse_pressure_level`, `vm_stat`/`sysctl` | Implemented and tested + живой уровень 1 |
| 5 | Server-side single-render guard | `backend/app/api/worker.py` (`pg_advisory_xact_lock` + `NOT EXISTS`), `series_runs.py` (`busy`) | Implemented and tested |
| 6 | Cooldown scheduler | `Profile`, `after_job`, `_next_allowed_at`, state-файл | Implemented and tested (включая рестарт) |
| 7 | Thermal Pause | `_series_loop`, `pause`/`resume` через существующий API | Implemented and tested |
| 8 | Automatic Resume | `_series_loop` + гистерезис 2×`nominal` | Implemented and tested |
| 9 | Energy Profiles | `PROFILES` (off/balanced/eco) | Implemented and tested |
| 10 | Thermal event logger | `EventLog` → `thermal-events.jsonl`, ротация 5 МиБ × 2 | Implemented and tested |
| 11 | `GET /api/render-agent/status` | `backend/app/api/render_agent.py` | Implemented and tested (+7 новых тестов) |
| 12 | UI-панель термозащиты | `ui/src/pages/SeriesRunPage.tsx` | Implemented; проверена вживую в браузере без GPU (автотестов UI нет) |
| 13 | Worker recovery | `_recover_at_startup`, `resume` + `/history`/`/queue` | Implemented and tested |

Вывод: WP-THERMAL-02 реализован, дублировать компоненты не потребовалось. В этом WP
закрыты 6 дефектов и два незавершённых пункта (T-06, T-07).

### Найденные и исправленные дефекты

1. **Ложный допуск после горячей job.** `after_job` не пересобирал снимок, если
   измерение уже `serious`/`critical`; до следующего опроса `admission.allowed` мог
   оставаться `true`. Теперь снимок с `allowed=false` и `reason=thermal_<state>`
   пишется сразу, пауза взводится в том же вызове.
2. **Бесконечное молчаливое ожидание.** `--thermal-max-wait` вычислялся, но
   `_job_loop` его не использовал. Добавлена проверка `gate.should_stop_waiting()`
   до `--once`: уведомление, причина в stderr, выход с кодом 1.
3. **Low Power Mode не читался.** `pmset -g` парсится в `low_power_mode: bool | None`;
   поле есть в статусе, телеметрии и state-файле. Неизвестно → `null`.
4. **Профиль не был частью `RenderSettings`.** Значение читалось из `args` в момент
   сборки gate; теперь `RenderSettings.thermal_profile` и явная передача в
   `_build_thermal_gate(args, settings.thermal_profile)`.
5. **UI показывал прочерки и не показывал причину блокировки вне паузы.**
   Заменено на `Unknown`, добавлены Low Power Mode, `admission`, время до следующего
   задания, cooldown и причина блокировки.
6. **Не было теста порядка advisory-lock.** Добавлены проверки, что
   `pg_advisory_xact_lock` выполняется до `_CLAIM_SQL`, между ними нет `COMMIT`, и что
   guard не применяется к не-`render_video`.

---

## 3. Thermal admission safety

Порядок проверок в `ThermalGate._evaluate` (Eco/Balanced): профиль `off` →
`serious`/`critical` → гистерезис восстановления → питание (`require_ac`) →
memory pressure и свободная память → cooldown → допуск.

| Требование задания | Реализация |
|---|---|
| Учитывается профиль | `Profile` (`off`/`balanced`/`eco`), Eco строже |
| Питание от сети | Eco: батарея → `power_not_ac`; неизвестный источник → `power_unknown` |
| Thermal state | `serious`/`critical` → блокировка; `unknown` → консервативный cooldown |
| Memory pressure | `critical` → блокировка; Eco требует `normal` |
| Запас памяти | Eco: ≥ 4 ГиБ (`memory_low`) |
| Активный GPU-рендер | серверный guard и `series/next` → `busy` |
| Cooldown | `cooldown` с остатком до `next_allowed_at` |
| SeriesRun | пауза через существующие `pause`/`resume`, чужую паузу gate не снимает |
| Не снижать production-разрешение | профиль не меняет `long_side`/`num_frames`/fps/seed/cfg/workflow |
| Unknown policy | консервативно: cooldown ≥ 900 с, партия ≤ 2 |
| Нет бесконечного ожидания | `--thermal-max-wait` (по умолчанию 6 ч) → выход с кодом 1 |
| Потеря питания во время рендера | текущий рендер досчитывается; ComfyUI принудительно не завершается |

---

## 4. Защита от параллельных job

| Сценарий | Покрытие |
|---|---|
| Два воркера одновременно | атомарность гарантируется `pg_advisory_xact_lock` + `NOT EXISTS` в одном UPDATE; тест фиксирует порядок и отсутствие промежуточного `COMMIT` |
| Два конкурентных claim | гонка исключена транзакционной блокировкой; отдельный многопоточный тест **не писался** [ПРОВЕРИТЬ при желании] |
| Crash воркера | `test_lease_expiry_waits_for_owner_recovery`: `lease_expired` не блокирует guard и не перевыдаётся автоматически |
| Истечение lease | то же |
| Recovery | `test_recover_*` (5 тестов): завершение через `/history` без повторного `/prompt`, потеря prompt'а → `external_prompt_lost` |
| Повторный polling | `claim` возвращает `null`, пока чужой `render_video` активен |
| Restart API | состояние в БД + `pg_advisory_xact_lock` (сессионная блокировка снимается вместе с транзакцией) |
| Повторный `series_next` | `test_series_next_busy_while_foreign_render_is_leased` → `busy`, после завершения → `queued` |

Ни один проверенный сценарий не приводит к двум одновременным `render_video` при
лимите 1.

---

## 5. Thermal Pause & Resume

Тестовый источник системных состояний — `StubProbes` в `tests/test_thermal_gate.py`
(наследник `Probes`, переопределяет `thermal`/`power`/`memory`/`low_power_mode`).
Он существует только в тестах и не участвует в production-путях. Живой UI проверялся
на временном снимке через `MARY_RENDER_AGENT_STATE_PATH` (файлы в `/tmp`), production
`~/.mary-studio/*` не перезаписывались.

Сценарий (по шагам задания):

| Шаг | Покрытие |
|---|---|
| 1. Активный рендер | `_series_loop` + `_render`, тест паузы/возобновления серии |
| 2. Переход в Thermal Pause | `thermal_serious`/`critical` → `pause`, snapshot `allowed=false` |
| 3. Завершение активной job | рендер досчитывается, `after_job` пишет телеметрию |
| 4. Запрет следующей job | `before_next` блокирует, `series_next` не создаёт job |
| 5. Возврат условий | два подряд `nominal` + выдержка, `power_pause_clears_when_power_returns` |
| 6. Resume | `resume` только для своей паузы |
| 7. Нет повторного `/prompt` | recovery-тесты: `/history` содержит ровно одну запись |

Питание физически не отключалось.

---

## 6. Energy Profiles (T-06)

- `RenderSettings.thermal_profile` (по умолчанию `balanced`), CLI `--thermal-profile`,
  env `MARY_THERMAL_PROFILE`; приоритет CLI > env > default.
- Профиль задаёт допуск, cooldown между шотами (Eco 480 с), cooldown после партии
  (1200 с), размер партии (3), требования к питанию и памяти.
- Production-параметры не меняются: `long_side`, `num_frames`, fps, seed, steps,
  sampler, workflow.
- `low_ram` **не включается** — ждёт Q-38.
- Low Power Mode читается (`pmset -g` → `lowpowermode`) и показывается в UI;
  глобальные настройки macOS не изменялись, команда записи не вызывалась.
- Профиля `Performance` в коде нет (только в проектной таблице).

Живые значения на момент проверки: `{"source":"process_info","state":"nominal"}`,
`pmset -g ps` → AC Power 100 % (finishing charge), `lowpowermode 0`,
`kern.memorystatus_vm_pressure_level` = 1, `hw.memsize` = 19 327 352 832 (18 ГиБ).

---

## 7. Preview-first (T-07)

- `POST /api/shots/{id}/render` принимает необязательное тело `{"preview": true}`.
- Preview — отдельная `RenderAttempt` (`kind='video'`), `parameters.preview=true`,
  job payload `preview=true`, `frames=73`; в ответе `RenderQueuedOut.preview`.
- 73 кадра (3.04 с при 24 fps) — согласовано с человеком; проектные 41–49 не
  использовались.
- Approve preview → 409 `preview_cannot_be_approved`; reject доступен.
- Production-артефакт и `shots.approved_attempt_id` не затрагиваются, стартовый кадр
  и seed не меняются.
- UI: кнопка «Preview (73 кадра)» на `#/shots/{id}`, бейдж `preview`, approve скрыт;
  на `#/attempts` preview исключён из сравнения и из «Сделать текущей».
- Реальные preview-прогоны не запускались.

---

## 8. Thermal logging и UI

- Журнал `~/.mary-studio/thermal-events.jsonl`: фиксированные поля `ts`, `event`,
  `profile`, `worker`, `thermal`, `power`, `memory`, `reason`, `job_id`; ротация
  5 МиБ × 2 (`thermal_log_max_bytes`, `thermal_log_backups`) — покрыто тестами
  `test_event_log_rotates`, `test_event_log_records_fixed_fields`.
- State-файл `~/.mary-studio/thermal-state.json`, атомарная запись, поля свежести
  `updated_at`/`age_seconds`/`stale` (180 с).
- `GET /api/render-agent/status` отдаёт `low_power_mode` (bool/`null`).
- UI `#/series/{id}`: профиль, thermal state с источником, питание и заряд, Low Power
  Mode, memory pressure и свободная память, партия, очередь, рендер идёт, допуск,
  cooldown, время до следующего задания, пауза с причиной и ожиданием, причина
  блокировки вне паузы, последнее событие. Неизвестные значения — `Unknown`.
- Проверено на живом backend (uvicorn) и живом UI (vite) без GPU-рендера: панель
  показала `Профиль: Eco`, `thermal: Serious (process_info)`, `Питание: батарея ·
  заряд 42% · Low Power Mode: Unknown`, `Память: Normal · свободно 6144 МБ`,
  `Допуск: заблокирован · до следующего задания: 1 мин`,
  `Пауза термозащиты: перегрев (Serious) · ожидание 3 мин · до следующего шота 7 мин`.
  Ошибок сети и прочерков `—` нет.

---

## 9. Worker lifecycle и предложение по launchd

- `KeepAwake` запускает `caffeinate -i -w <pid>` и всегда останавливает его в `finally`;
  `-w` снимает удержание при падении воркера. Тесты: `test_keep_awake_uses_caffeinate_and_stops`,
  `test_keep_awake_disabled_does_nothing`.
- Живой acceptance-прогон подтвердил: `caffeinate` запускается на время job и после
  выхода воркера не остаётся (`pgrep -fl caffeinate` пуст). Аварийное завершение
  (`kill -9`) в этом прогоне не проверялось — только тестами.
- `launchd` **не устанавливался**.

**Предложение (отдельный этап, требует разрешения):** `LaunchAgent` с
`KeepAlive=false`, `RunAtLoad=false`, запуском по требованию
`launchctl kickstart -k gui/$(id -u)/studio.mary.worker`, `StandardOutPath`
в `~/Library/Logs/mary-studio/worker.log`, `WorkingDirectory` = репозиторий, профиль
и пресет — в `ProgramArguments`. Плюс: воркер стартует после логина; минусы: `launchd`
не умеет «ждать окончания текущего рендера» и перезапустит процесс посреди job;
поэтому включать только вместе с `--once`-циклом или внешним watchdog. Без явного
«да» ничего не создаётся.

---

## 10. Документация

| Документ | Изменение |
|---|---|
| `AGENTS.md` §8 | добавлен статус WP-THERMAL-03 и фактические числа тестов (245/104) |
| `DECISIONS.md` | новый §4.17 (T-06, Low Power Mode, горячий снимок, max-wait, preview, UI, границы), строки совместимости §6, §7, журнал §8 |
| `OPEN_QUESTIONS.md` | Q-34 и Low Power Mode закрыты, добавлен Q-41 (разрешение на GPU acceptance test) |
| `ROADMAP_MARY_STUDIO.md` §6 | устаревший «порядок WP-00…» заменён фактической таблицей статусов |
| `PROPOSALS/THERMAL_SAFE_SCHEDULER.md` | §8 (факт по профилям и `low_ram`), §9 (реальный контракт статуса), §10 (отклонения preview: 73 кадра, 409), §12 (статусы T-02…T-09), §13 п.7 (245/104) |
| `i_will_do_it_later.md` | T-06/T-07 отмечены выполненными, `export/` закрыт, устаревшие числа тестов обновлены |

---

## 11. Результаты проверок

### 11.1 Автоматические и сборка

```
backend: 245 passed
корень:  104 passed
alembic check: No new upgrade operations detected
ui:      npm run build — ✓ built in 424ms (338.23 kB)
```

### 11.2 Живой Eco acceptance test NLB-25 (по разрешению Q-41)

Один контролируемый рендер и тест Thermal Pause без отключения питания; процедура —
`docs/PROPOSALS/THERMAL_GPU_ACCEPTANCE_PLAN.md` §8, подробности —
`docs/REPORTS/WP_THERMAL_03_TEST_RESULTS.md` §5.

```
прогон:   f163f8b7-8c8b-47f6-a29a-8592eafcef19  completed (1/1)
job:      0aa6d22f-d886-4e29-b313-16b4fd45ea52  completed
attempt:  96e16d5a-bbfe-4e27-b3d2-241df980f3d7  seed=950087778  duration=8.042 s
artifact: af057b6c-13df-42ca-a785-5f319f4b98c9  h264 576x1024, 24 fps, aac 48 kHz
prompt:   df8fc2e0-a61b-461d-911e-92aef9042775  (/history = 1, повтора нет)
память:   peak_mem_mb=16295, min_available_mb=2137, max_pressure_level=4
```

Thermal Pause: `thermal_serious` → `paused` → `resume` → `completed`, job во время
паузы не создавался. `caffeinate` после выхода воркера не висит.
`shots.approved_attempt_id` не изменён, старые попытки целы.

Отклонения от плана:
- seed `925049040` не применялся — payload шота не содержит `seed`, сработал
  детерминированный `render_seed(attempt_id, None)` → `950087778`;
- cooldown выставлен (480 с), но live-проверка допуска дала `power_not_ac`:
  к концу прогона ноутбук уже работал от батареи (во время рендера было `ac`);
- sandbox не дал воркеру писать `~/.mary-studio/thermal-state.json` и
  `thermal-events.jsonl`, поэтому телеметрия осталась в `render_attempts.parameters`,
  а state/log снимались в `/tmp`.

---

## 12. Оставшиеся риски

1. **Память во время рендера.** Eco-гейт проверяет свободную память только до job;
   в живом прогоне пик `16295` МБ (≈88 % RAM), `min_available_mb=2137`,
   `max_pressure_level=4` (critical). Порог «≥ 4 ГиБ» не гарантирует запас внутри рендера.
2. **Sandbox-ограничение записи в `~/.mary-studio`.** Production state/log и
   `/api/render-agent/status` в live-прогоне не отражали реальный снимок; вне sandbox
   это требует отдельной проверки.
3. **Cooldown как единственная причина блокировки** вживую не проверен: сработал
   `power_not_ac` (ноутбук на батарее).
4. **Порядок измерений.** После рендера состояние читается сразу; если система
   остывает медленно, пауза будет длиннее ожидаемой (это осознанно).
5. **`pmset`/`sysctl` форматы** могут измениться с обновлением macOS; при сбое —
   `Unknown` и консервативный режим.
6. **Гонка двух процессов** покрыта транзакционной блокировкой, но многопоточный
   интеграционный тест не писался.
7. **Preview 73 кадра** — компромисс; при 576×1024 это ~3 с, но сцена может не
   успеть «проявиться», визуальная оценка ограничена.
8. **`caffeinate` при `kill -9`** проверен тестами, не живым аварийным завершением.
9. **Температура/мощность GPU** по-прежнему недоступны без `powermetrics` (Q-39).

---

## 13. Требует разрешения пользователя

1. `launchd`-агент воркера (раздел 9) — отдельный этап.
2. `low_ram` в Eco — только после Q-38.
3. Дополнительные GPU-прогоны (включая повтор cooldown-проверки на сети и
   multi-reference/Lip Sync) — вне текущего WP.
4. Commit/merge/push текущих изменений (не выполнялись).

---

## 14. Следующий шаг

WP-THERMAL-03 и разрешённый acceptance test завершены; отчёты обновлены фактами.
Дальше — по решению человека: запуск серии из 30 роликов под Eco, либо отдельный
этап (launchd, low_ram по Q-38, следующий WP). До явного указания — остановка.
