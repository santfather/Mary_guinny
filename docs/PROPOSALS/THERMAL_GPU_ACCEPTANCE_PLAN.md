# Thermal GPU Acceptance Plan — один контролируемый Eco-рендер (NLB-25)

> Статус: **выполнено 2026-11-04** по разрешению человека (Q-41). Один Eco-рендер
> NLB-25 и тест Thermal Pause пройдены; фактические результаты — §5 ниже и
> `docs/REPORTS/WP_THERMAL_03_TEST_RESULTS.md` §5. Серия из 30 роликов не запускалась,
> модели не скачивались, production-параметры не менялись. Ветка `wp-m0-maestro-audit`,
> коммит не требуется.

---

## 1. Зафиксированные параметры

| Параметр | Значение |
|---|---|
| Проект | «The Nine Lives Band», `a7a6629e-6059-4aad-bb7f-eca0133085cf` |
| Шот | NLB-25 «Король дивана», `b4b7b70d-28ea-47e0-81f8-cca4456f29c9` |
| Статус шота | `prompt_ready`, `target_duration_frames=193`, `timeline_fps=24.000` |
| Стартовый кадр (artifact) | `0d62568e-5ff1-49d6-9a0a-209e5cba07f0`, `source=attempt`, `keyframe` |
| Keyframe-попытка | `8d317f26-5e1a-44ce-a5fe-1739cddba094` |
| Файл стартового кадра | `storage/blobs/e1/e197e3ec…png`, `image/png`, 941×1672 RGB, 2 297 808 B, sha256 `e197e3ec60dbcadad92a710d7afbca0501365a867c2c85663a68d846451dbfc9` |
| Motion-промпт | ревизия v2, `25e731fe-a09b-4203-aba8-cd376cba7258`, 182 символа (v1 сохранена) |
| Seed | `925049040` (из последней завершённой попытки `565c910d-5f07-47ce-aedc-fb5c4edfe820`) |
| Workflow | `comfyui-workflows/ltx23_mlx_q4_i2v.api.json`, `workflow_version=ltx23-mlx-q4-i2v/a48ba1c43439` |
| Модель | `dgrauet/ltx-2.3-mlx-q4`, I2V, two-stage |
| Пресет | `safe` — 576×1024 (`long_side=1024`), 193 кадра, 24 fps, ≈8.04 с, `cfg_scale=3.0` |
| Energy Profile | `eco` (сеть обязательна, memory pressure normal, ≥ 4 ГиБ, cooldown 480 с) |
| Ожидаемый рендер | один шот, ≈18 мин (по калибровке WP-00A/серии), без изменения production-параметров |

Ожидаемый результат: новая `RenderAttempt` (`kind='video'`) **в дополнение** к
`565c910d…` и `ef866aac…`; существующие попытки, MP4 и approved-записи не изменяются.

---

## 2. Предусловия (проверить до запуска)

1. `~/.mary-studio/bin/mary-thermal-state` существует и печатает JSON
   (`scripts/mac_thermal_state.swift` уже собран вне Git).
2. Backend запущен: `cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000`.
3. ComfyUI слушает `127.0.0.1:8188`, LTX-2.3 MLX q4 загружается.
4. Нет активных `render_video`:
   `psql -d mary_studio -X -A -c "select count(*) from jobs where kind='render_video' and status in ('pending','queued','leased','running');"` → `0`.
5. Питание от сети, заряд ≥ 50 %, memory pressure = 1, свободно ≥ 4 ГиБ.
6. Токен воркера доступен через env (`MARY_WORKER_TOKEN`), **не** печатается в лог.

---

## 3. Процедура (10 шагов)

### Шаг 1. Питание от сети

```bash
pmset -g ps
pmset -g | grep lowpowermode
```
Ожидается `AC Power`, заряд ≥ 50 %. Иначе — стоп (Eco не стартует).

### Шаг 2. Thermal state

```bash
~/.mary-studio/bin/mary-thermal-state
```
Ожидается `nominal` или `fair`. `serious`/`critical`/`unknown` → стоп, дождаться
остывания (unknown допускает работу, но только с консервативным cooldown).

### Шаг 3. Memory pressure

```bash
sysctl -n kern.memorystatus_vm_pressure_level
vm_stat | head -6
```
Ожидается уровень `1` (normal) и свободно ≥ 4 ГиБ (Eco).

### Шаг 4. Запуск одного Eco-рендера

Изолировать прогон одним шотом, чтобы guard и cooldown были измеримы:

```bash
curl -s -X POST http://127.0.0.1:8000/api/projects/a7a6629e-6059-4aad-bb7f-eca0133085cf/series/runs \
  -H 'Content-Type: application/json' \
  -d '{"title": "WP-THERMAL-03 eco acceptance", "shot_orders": [25], "stop_on_error": true}'
```
Убедиться, что в прогоне ровно 1 item (шот NLB-25). Затем **один** запуск воркера:

```bash
cd /Users/vladislavkovalenko/Projects/Mary_Guiness
.venv/bin/python worker/ltx_worker.py \
  --series-run <run_id> --once \
  --preset safe --thermal-profile eco
```

Никаких `--long-side`, `--aspect-ratio`, `--cfg-scale` не передавать: параметры
берутся из пресета `safe` и шота. В другом терминале — контроль:

```bash
~/.mary-studio/bin/mary-thermal-state; pmset -g ps
curl -s http://127.0.0.1:8000/api/render-agent/status | python3 -m json.tool
```

### Шаг 5. Проверить MP4

```bash
psql -d mary_studio -X -A -F ' | ' -c "select ra.id, ra.status, ra.seed, a.id, a.bytes, a.sha256, a.storage_key from render_attempts ra join artifacts a on a.attempt_id=ra.id where ra.shot_id='b4b7b70d-28ea-47e0-81f8-cca4456f29c9' order by ra.created_at desc limit 1;"
```
Ожидается: новая попытка `completed`, `kind='video'`, артефакт `video/mp4`.
Проверить контейнер:

```bash
ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate -show_entries format=duration \
  storage/blobs/<xx>/<sha256>.mp4
```
Ожидается h264, 576×1024, 24 fps, длительность ≈8 с, при наличии — `aac`.

### Шаг 6. Проверить `RenderAttempt.parameters`

```bash
psql -d mary_studio -X -A -c "select parameters::text from render_attempts where id='<new_attempt_id>';"
```
Ожидается: `preset='safe'`, `preset_source` (`cli`), `thermal.profile='eco'`,
`thermal.thermal_state`, `thermal.power_source='ac'`, `thermal.available_mb`,
`thermal.low_power_mode`, `peak_mem_mb`, `num_frames=193`, `seed=925049040`,
`workflow_version=ltx23-mlx-q4-i2v/a48ba1c43439`, `preview` отсутствует.

### Шаг 7. Проверить `thermal-events.jsonl`

```bash
ls -l ~/.mary-studio/thermal-events*.jsonl
tail -n 20 ~/.mary-studio/thermal-events.jsonl
```
Ожидается JSON-строки с `ts`, `event` (`decision`/`job_finished`/…), `profile='eco'`,
`thermal`, `power='ac'`, `memory`, `reason`, `job_id`. Файл не превышает лимит,
ротация `*.1` появляется только после 5 МиБ.

### Шаг 8. Проверить status API

```bash
curl -s http://127.0.0.1:8000/api/render-agent/status | python3 -m json.tool
```
Ожидается `worker_online=true` во время работы, `rendering=true`, `current_job_id`
новой job, `power.source='ac'`, `low_power_mode` bool/`null`, `admission` и `cooldown`
без выдуманных полей.

### Шаг 9. Убедиться, что повторного prompt нет

```bash
curl -s http://127.0.0.1:8188/history | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d))"
# до запуска и после — прирост ровно 1
grep -c '"event"' ~/.mary-studio/thermal-events.jsonl   # до/после
pgrep -fl caffeinate
```
Ожидается: ровно один новый prompt за прогон, ни одного повторного `/prompt`,
`caffeinate` отсутствует после завершения воркера.

### Шаг 10. Дождаться cooldown

```bash
curl -s http://127.0.0.1:8000/api/render-agent/status | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['cooldown'])"
```
Ожидается `remaining_seconds` > 0 (Eco: 480 с между шотами). Повторный запуск воркера
в этот интервал не должен брать новую job; проверить `admission.reason='cooldown'`.

---

## 4. Отдельный тест Thermal Pause без физического отключения питания

Цель: пройти production-путь gate → pause → resume, не трогая питание и не убивая
ComfyUI.

1. Создать тестовый helper **только для этого прогона** (вне репозитория):

```bash
cat > /tmp/mary-thermal-fake-helper <<'SH'
#!/bin/sh
echo '{"source":"test_helper","state":"serious"}'
SH
chmod +x /tmp/mary-thermal-fake-helper
```

2. Создать прогон из одного шота (как в шаге 4) и запустить воркер с подменой helper:

```bash
.venv/bin/python worker/ltx_worker.py \
  --series-run <run_id> --once --preset safe --thermal-profile eco \
  --thermal-helper /tmp/mary-thermal-fake-helper --thermal-poll 5 --thermal-max-wait 120
```

Ожидается:
- воркер не берёт job, печатает `thermal: thermal_serious`;
- `SeriesRun.status` → `paused` (существующий `pause`), в журнале `decision` с
  `reason='thermal_serious'`;
- второй экземпляр воркера тоже не берёт job;
- `GET /api/render-agent/status` показывает `pause.active=true`,
  `pause.reason='thermal_serious'`, UI-панель — «Пауза термозащиты»;
- по истечении `--thermal-max-wait` воркер выходит с кодом 1 и уведомлением,
  prompt в ComfyUI **не отправлялся**.

3. Убрать подмену и вернуть нормальные условия (симуляция «питание вернулось»):

```bash
.venv/bin/python worker/ltx_worker.py --series-run <run_id> --once \
  --preset safe --thermal-profile eco --thermal-helper "$HOME/.mary-studio/bin/mary-thermal-state"
```

Ожидается: пауза снята (только своя), `SeriesRun.status` → `running` → `completed`,
новый `/prompt` ровно один, `thermal-events.jsonl` содержит `job_finished`.

4. Удалить временный helper `/tmp/mary-thermal-fake-helper`.

Ограничения теста: не вынимать кабель, не менять настройки macOS, не копировать
helper в репозиторий и не оставлять его в `PATH`, не менять `scripts/mac_thermal_state.swift`.

---

## 5. Критерии приёмки

1. Один шот отрендерен под `eco`, MP4 валиден (h264, 576×1024, 24 fps, ≈8 с).
2. Новая `RenderAttempt` не заменила предыдущие; `shots.approved_attempt_id` не изменён
   автоматически.
3. `render_attempts.parameters` содержит профиль, пресет, seed, workflow и thermal-метрики.
4. `thermal-events.jsonl` вырос и валиден построчно.
5. `GET /api/render-agent/status` показывает реальные значения; нет выдуманных
   температуры/мощности.
6. Повторного `/prompt` нет; после выхода воркера `caffeinate` не висит.
7. Cooldown действует: следующий claim до его окончания не проходит.
8. Тест Thermal Pause (раздел 4) прошёл: paused → resume → completed без отключения питания.

---

## 6. Откат

- Отмена: `POST /api/projects/{id}/series/runs/{run_id}/cancel` (существующий эндпоинт).
- Удалять артефакты и попытки не нужно: они иммутабельны и остаются историей.
- Если рендер не понравился — `reject` попытки; approved-записи не затрагиваются.

---

## 7. Что требует разрешения

- Разрешение на один GPU-прогон (шаг 4) и на тест Thermal Pause с подменой helper
  (раздел 4). До разрешения обе процедуры не выполняются.

---

## 8. Фактические результаты (2026-11-04)

### 8.1 Идентификаторы

| Сущность | Значение |
|---|---|
| Прогон | `f163f8b7-8c8b-47f6-a29a-8592eafcef19`, «WP-THERMAL-03 eco acceptance», 1 item |
| Job | `0aa6d22f-d886-4e29-b313-16b4fd45ea52`, `render_video`, 1 попытка |
| RenderAttempt | `96e16d5a-bbfe-4e27-b3d2-241df980f3d7`, `completed`, `duration_s=8.042` |
| Артефакт | `af057b6c-13df-42ca-a785-5f319f4b98c9`, `video/mp4`, 3 137 749 B, sha256 `c3c0f743…` |
| ComfyUI prompt | `df8fc2e0-a61b-461d-911e-92aef9042775` (в `/history` ровно одна запись) |
| Seed (факт) | `950087778` — детерминированный `render_seed(attempt_id, None)`, план `925049040` не применялся |
| Пик памяти | `peak_mem_mb=16295` из 18 432 МБ (≈88 %), `render_seconds=995.707` |

### 8.2 Хронология

```
17:50:24  создан прогон
17:51:02  тест Thermal Pause: fake-helper → decision thermal_serious, run → paused,
          job не создан, /prompt не отправлялся
17:51:28  resume (пауза снята, ≈26 с)
17:51:34  создан job, /prompt, lease и heartbeat
18:08:09  job completed, артефакт загружен
18:13:37  series/next закрыл item и прогон → completed
```

### 8.3 Проверенные факты

- MP4: h264 576×1024, 24 fps, 8.0417 с, аудио `aac` 48 kHz stereo — соответствует пресету `safe`.
- `render_attempts.parameters`: `preset='safe'`, `preset_source='cli'`, `thermal.profile='eco'`,
  `thermal.thermal_state='nominal'`, `thermal.power_source='ac'`, `battery_percent=100.0`,
  `low_power_mode=false`, `memory_pressure='normal'`, `available_mb=7113`,
  `num_frames=193`, `workflow_snapshot` (`low_ram=false`), `preview` отсутствует;
  в самой попытке `workflow_version='ltx23-mlx-q4-i2v/a48ba1c43439'`.
- `shots.approved_attempt_id` не изменился (`NULL`), старые попытки `ef866aac…`/`565c910d…` целы.
- `pgrep -fl caffeinate` после завершения пуст; ComfyUI `/history` — 1 запись (повторного `/prompt` нет).
- Cooldown Eco выставлен: `remaining_seconds=479.9` (`next_allowed_at` = +480 с). Живая проверка
  допуска сразу после рендера дала `allowed=false`, `reason='power_not_ac'` — ноутбук к этому
  моменту уже работал от батареи (во время рендера `power_source='ac'`). Это подтверждает
  работу Eco-правила «только сеть», но cooldown как единственную причину блокировки вживую
  проверить не удалось.
- Ограничение sandbox: воркер не смог писать `~/.mary-studio/thermal-state.json` и
  `thermal-events.jsonl` (`[Errno 13] Permission denied`), поэтому телеметрия сохранилась
  только в `render_attempts.parameters`; state/log снимались по временным путям в `/tmp`.
  Это ограничение среды запуска, не дефект кода: короткие процессы писали в те же пути успешно.

### 8.4 Критерии приёмки

| № | Критерий | Результат |
|---|---|---|
| 1 | MP4 валиден (h264, 576×1024, 24 fps, ≈8 с) | выполнен |
| 2 | Прошлые попытки и `approved_attempt_id` не изменены | выполнен |
| 3 | `parameters` содержат профиль, пресет, seed, workflow, thermal-метрики | выполнен |
| 4 | `thermal-events.jsonl` вырос | не выполнен: запись в `~/.mary-studio` запрещена sandbox'ом; журнал писался в `/tmp` (`decision` + `job_finished` в проверке cooldown) |
| 5 | `/api/render-agent/status` показывает реальные значения | частично: API читает production-пути и во время рендера отдавал `worker_online=false`; значения проверены по `/tmp`-снимку и `parameters` |
| 6 | Нет повторного `/prompt`, `caffeinate` не висит | выполнен |
| 7 | Cooldown блокирует следующий claim | логика подтверждена (480 с в state), live-причина блокировки — `power_not_ac` |
| 8 | Thermal Pause → resume → completed без отключения питания | выполнен |

### 8.5 Наблюдение по памяти

Во время рендера `thermal.min_available_mb=2137` и `thermal.max_pressure_level=4`
(критическое давление), при `peak_mem_mb=16295`. Eco-гейт проверяет память только
**до** job, поэтому рендер прошёл, хотя в процессе система уходила в critical pressure.
Это не меняет поведение WP-THERMAL-03, но фиксируется как риск: порог «≥ 4 ГиБ» не
гарантирует запас на всём протяжении рендера.
