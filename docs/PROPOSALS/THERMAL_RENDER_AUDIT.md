# Аудит тепловой нагрузки и энергопотребления рендера (WP-THERMAL-01)

> **Статус:** предложение (этап 1 задания). Код не изменялся, миграций нет, GPU-прогонов
> не запускалось. Все измерения ниже — только чтение (`pmset`, `sysctl`, `vm_stat`,
> `curl` к локальному ComfyUI) на машине аудита.
> **Дата:** 2026-11-04. **Машина:** MacBook Pro, Apple M3 Pro, 12 CPU, 18 ГиБ unified
> memory, macOS 27.2 (build 26B123).
> **Связанные документы:** `docs/ARCHITECTURE.md` (C28, §6.2, §6.4, §7.1, §7.4, §11,
> WP-A3), `docs/PROPOSALS/THERMAL_SAFE_SCHEDULER.md`,
> `docs/PROPOSALS/RENDER_ENERGY_BENCHMARK.md`, `docs/OPEN_QUESTIONS.md`.

---

## 1. Итог аудита (шесть фактов, определяющих дизайн)

1. **Ограничение «одна тяжёлая job» сейчас держится только на том, что запущен ровно
   один процесс воркера.** Серверная гарантия отсутствует: `claim` не проверяет, есть
   ли уже другой активный `render_video` job, а `series/next` проверяет только job
   этого же шота. Второй воркер (или второй запуск того же воркера) даст два
   параллельных рендера на одной GPU.
2. **Между шотами серии нет паузы.** `worker/ltx_worker.py::_series_loop` после
   `_process_job` сразу вызывает `series/next`; сервер сразу создаёт следующую job.
   Прогон «NLB-single» — 24 шота × ≈1062 с подряд, ≈7 ч без перерыва. Это и есть
   источник длительной работы вентиляторов.
3. **Thermal state сейчас фактически Unknown.** На этой машине `pmset -g therm` не
   отдаёт живых значений («No thermal warning level has been recorded», «No CPU power
   status has been recorded»). `pmset -g thermlog` — поток, а не однократный запрос.
   Значит: основной честный источник — `ProcessInfo.thermalState` через нативный
   helper (Swift 6.4 и Xcode на машине есть), а без helper планировщик обязан работать
   в консервативном режиме «Unknown».
4. **Телеметрия рендера не пишется.** `render_attempts.peak_mem_mb` существует в схеме
   и в `WorkerCompleteRequest`, но `worker/client.py::complete()` его не отправляет.
   `render_attempts.duration_s` — длительность **видео** (≈8,04 с), а не время рендера;
   фактическое время шота нигде не сохраняется.
5. **Оптимизировать «inference steps» нельзя:** у ноды `LTX2MLXGenerate` нет входа
   `steps` (проверено `/object_info`). Доступные ручки рендера: `width/height`,
   `num_frames`, `frame_rate`, `cfg_scale`, `seed`, а на загрузчике — `low_ram` и
   `pipeline_type` (`two_stage`, `two_stage_hq`, `one_stage`, `distilled`).
6. **Устройство было не в том состоянии, в котором можно рендерить:** питание от
   батареи 10 %, swap занят 2,1 ГиБ, `caffeinate` не запущен. Требования C28/§6.4
   (питание от сети, `caffeinate -i`, телеметрия) в коде и в эксплуатации не выполнены.

---

## 2. Карта текущего pipeline

```
UI (#/shots, #/series/{id})
  └─ POST /api/shots/{id}/render            → Job(status=pending) + unique active per shot
  └─ POST /api/projects/{id}/series/runs    → SeriesRun(draft) + SeriesItem[]
  └─ POST /api/series/{run_id}/start|pause|resume|stop-after-current|cancel
        │
        ▼
worker/ltx_worker.py  (один процесс, один тяжёлый job за раз)
  ├─ recover()        → POST /api/worker/resume + ComfyUI /history + /queue
  ├─ _series_loop()   → POST /api/worker/series/next   (создаёт следующую job)
  │                     POST /api/worker/claim          (lease 300 с)
  ├─ process_one()
  │   ├─ GET /api/artifacts/{id}/content   (стартовый кадр, проверка sha256)
  │   ├─ pipeline/comfyui/ltx_adapter.py   (шаблон → payload шота)
  │   ├─ ComfyUI POST /upload/image, POST /prompt, GET /history каждые 5 с
  │   │     └─ каждый опрос → POST /api/worker/jobs/{id}/heartbeat (событие `progress`)
  │   ├─ GET /view → MP4 во временный файл → ffprobe (только чтение, без перекодирования)
  │   └─ POST /api/worker/jobs/{id}/artifacts → BlobStore → POST …/complete
  └─ state-файл ~/.mary-studio/ltx-worker-state.json (prompt_id, атомарная запись)
        │
        ▼
ComfyUI 127.0.0.1:8188 (0.42.0, torch 2.14.1, mps) → BlobStore (content-addressed)
```

Тяжёлые процессы по коду: **один** — ComfyUI sampling. Второй потенциально тяжёлый —
`ffmpeg` из `backend/app/assembly.py` при `POST /api/projects/{id}/exports` (кодирование
1080×1920 + aac вручную, вне очереди и вне планировщика).

---

## 3. Что уже реализовано и переиспользуется

| Механизм | Где | Что даёт для thermal-задачи |
|---|---|---|
| Одна тяжёлая job на шот | частичный уникальный индекс `one_active_render_per_shot` (`backend/app/models.py:261-269`) | защита от дублей по одному шоту |
| Последовательная серия, `concurrency = 1` | `backend/app/api/series_runs.py::series_next` | точка, где **можно не создавать** следующую job |
| `pause` / `resume` / `stop-after-current` | `series_runs.py` | готовые действия для Thermal Pause без новой очереди |
| Lease + heartbeat + `resume` | `backend/app/api/worker.py`, `worker/ltx_worker.py` | восстановление после сна/рестарта уже работает |
| Восстановление prompt'а | `recover()`, `~/.mary-studio/ltx-worker-state.json` | рестарт воркера не перезапускает рендер |
| Пресеты `safe`/`wide`/`legacy_512` | `backend/app/presets.py`, `GET /api/presets` | измеренные режимы + `detect_hardware` |
| `detect_hardware`, `parse_vm_stat` | `presets.py` | готовый stdlib-детект памяти, без зависимостей |
| `parameters` JSONB в попытке | `render_attempts.parameters` | место для thermal-метрик **без миграции** |
| `peak_mem_mb` | `WorkerCompleteRequest` | поле готово, воркер его не заполняет |
| Баннер macOS | `backend/app/notify.py` | уведомление о Thermal Pause |
| `pipeline_type` / `low_ram` | шаблон `comfyui-workflows/ltx23_mlx_q4_i2v.api.json` | задел под Eco без новых моделей |

Чего нет: пауз между job, счётчиков партии, чтения thermal state, проверки питания и
memory pressure, записи времени рендера, `caffeinate`/`launchd`, статуса в UI.

---

## 4. Результаты read-only замеров (2026-11-04, ~15:50 CET)

| Команда | Фактический вывод | Следствие |
|---|---|---|
| `pmset -g therm` | `No thermal warning level has been recorded`; `No CPU power status has been recorded` | живого thermal state нет → **Unknown**, нужен helper |
| `pmset -g thermlog` | поток (команда не завершается, пришлось остановить) | только фоновый sampler, не «проверить сейчас» |
| `pmset -g ps` | `drawing from 'Battery Power'`, `10%; discharging` | рендер на батарее при 10 % — недопустимо |
| `pmset -g` | `lowpowermode 0` (AC и Battery) | Low Power Mode читается без root |
| `pmset -g assertions` | `PreventUserIdleSystemSleep 1` только от `powerd`, `caffeinate` отсутствует | §6.4 не выполнен |
| `sysctl -n kern.memorystatus_vm_pressure_level` | `1` (normal) | рабочий guard памяти без зависимостей |
| `sysctl -n vm.swapusage` | `total = 3072.00M used = 2137.12M free = 934.88M` | swap уже 2,1 ГиБ при пустой очереди |
| `vm_stat` | page size 16384, free 11 324, inactive 400 427, speculative 803 | ≈6,7 ГиБ «доступно» |
| `sysctl hw.memsize hw.ncpu` | 19 327 352 832 Б (18 ГиБ), 12 | совпадает с `presets.MIN_APPLE_SILICON_GIB` |
| `curl :8188/system_stats` | ComfyUI 0.42.0, `ram_free` ≈6,77 ГБ, `torch_vram_free` ≈6,77 ГБ, `mps` | ComfyUI запущен, модель сейчас не считает |
| `curl :8188/queue` | `queue_running 0`, `queue_pending 0` | очередь пуста, фоновых рендеров нет |
| `curl :8188/object_info/LTX2MLXGenerate` | входов `steps`/`sampler` нет; есть `width/height/num_frames/seed/cfg_scale/frame_rate/filename_prefix` | оптимизация «шагов» невозможна |
| `curl :8188/object_info/LTX2MLXModelLoader` | `pipeline_type`: `two_stage`, `two_stage_hq`, `one_stage`, `distilled`; `low_ram` boolean | ручки Eco-режима без новых моделей |
| `swiftc --version` | Swift 6.4.2, Xcode 27.2 | нативный helper собирается локально |

---

## 5. Находки

Severity: **high** — прямой вклад в перегрев или риск для устройства; **medium** —
влияет на управляемость/диагностику; **low** — расход ресурсов без теплового эффекта.

### F-01. Нет глобальной гарантии «один тяжёлый job» — high

`_CLAIM_SQL` (`backend/app/api/worker.py:275`) выбирает **любую** готовую job и не
смотрит, есть ли уже `leased/running` рендер. `series_next` проверяет только активную
job **этого** шота. Два процесса воркера → два параллельных sampling'а и почти
двукратная память. Это и есть ответ на вопрос «нет ли параллельных тяжёлых процессов»:
по дизайну нет, по контракту — не гарантировано.

### F-02. Нет паузы между шотами серии — high

`_series_loop` → `_process_job` → снова `series_next`; между `complete` и следующим
`/prompt` проходит время только на загрузку кадра. Следствие: непрерывная нагрузка
≈7 ч, что и наблюдалось в прогоне 24 шотов.

### F-03. Thermal guard отсутствует — high

Ни воркер, ни сервер не читают thermal state и memory pressure. Нет ни блокировки
запуска, ни уведомления, ни журнала решений.

### F-04. Нет лимитов партии и cooldown — high

Параметров `max_consecutive_renders`, `cooldown_between_jobs_seconds`,
`cooldown_after_batch_seconds` нет ни в коде, ни в конфигурации.

### F-05. Телеметрия попытки неполная — medium

- `worker/client.py::complete()` не передаёт `peak_mem_mb` (поле есть в
  `worker_schemas.py:67` и пишется в `worker.py:597`).
- `duration_s` = длительность MP4 из ffprobe (8,04 с), а не время рендера.
- Время wall-clock можно вычислить косвенно (события `claimed`/`completed`), но в
  параметрах попытки его нет; thermal state, memory pressure, swap, питание — тоже.

### F-06. `pmset -g therm` непригоден как основной источник — medium

Проверено: на этой машине вывод содержит только «No thermal warning level…». Живой
`CPU_Speed_Limit` появляется лишь в `thermlog` и лишь после событий троттлинга.
Поэтому в дизайне: `ProcessInfo.thermalState` — опциональный helper; без него
**Unknown** и консервативные интервалы. Подделывать «среднюю температуру» запрещено.

### F-07. Нет `caffeinate`/`launchd`, сон приведёт к `lease_expired` — medium

`pmset -g assertions` показывает отсутствие `caffeinate`. При сне система снимает
воркер с lease; `_expire_leases` переводит job в `lease_expired`, автоповтора нет
(осознанное решение WP-06). Для серии это ручной разбор.

### F-08. Избыточный polling → лишние записи в БД — medium

`RenderSettings.poll_interval = 5.0`; на каждом опросе вызывается `on_poll` →
`POST /heartbeat` → `_append_event(event="progress")` + commit. На шот ≈17,7 мин это
≈212 HTTP-запросов и ≈212 строк `events`; на 24 шота ≈5 тыс. строк. Lease — 300 с,
поэтому heartbeat каждые 30 с достаточен; `/history` можно опрашивать чаще без записи
в БД. Теплового эффекта нет, но это шум, лишние транзакции и нагрузка на CPU.

### F-09. `low_ram: false` при 18 ГиБ — medium

Шаблон грузит модель целиком в unified memory. Это быстро, но оставляет мало запаса
под macOS и браузер (swap уже 2,1 ГиБ). `low_ram: true` — единственная ручка «экономнее
по памяти» без новых моделей; влияние на скорость/качество не измерено.

### F-10. Параметры генерации фиксированы длительностью шота — medium (для этапа 5)

`build_shot_binding()` берёт `num_frames = snap_frames(seconds, fps)` (=193 при 8,04 с
и 24 fps) и `long_side` из пресета (576×1024). `cfg_scale = 3.0`. Уменьшать кадры или
разрешение «на лету» нельзя: это изменит утверждённый кадр/длительность. Все
оптимизации этапа 5 — это **отдельные профили и preview**, а не тихая подмена
production-параметров.

### F-11. Модель не перезагружается между шотами, но и не выгружается — low

ComfyUI кеширует выход загрузчика по входам, поэтому при неизменном
`model_dir/pipeline_type/low_ram` модель остаётся в памяти между шотами: это хорошо
(нет повторных загрузок и тепловых пиков). `/free` не вызывается нигде; при этом
`system_stats` показывает ≈6,8 ГБ свободных. Выгружать модель между шотами
**не следует** — повторная загрузка даст новый пик памяти; выгрузка уместна только
при длительной паузе (после партии) и должна быть отдельным решением.

### F-12. Нет проверки питания и заряда — high

Сейчас машина на батарее при 10 %. Рендер в таком состоянии либо оборвётся, либо
разрядит устройство. C28 требует питание от сети; кода проверки нет.

### F-13. Memory pressure не контролируется — medium

`kern.memorystatus_vm_pressure_level` = 1 (normal) читается без root. При 18 ГиБ и
swap 2,1 ГиБ нужен порог: не начинать job при `warn/critical` или при доступной
памяти ниже порога.

### F-14. Дубли задач — low, но есть один сценарий

Идемпотентный ключ `series:{run_id}:{order}` и частичный уникальный индекс не дают
создать дубль в очереди. Но `external_prompt_lost` (prompt исчез из `/queue` и
`/history`) приводит к `retry_wait` и **полному повторному рендеру того же шота**.
Это корректно, но для thermal-профиля стоит считать повтором партии (счётчик).

### F-15. Двойное хранение MP4 — low

ComfyUI сохраняет MP4 в своём `output/`, воркер скачивает его через `/view` и
загружает в BlobStore. Диск растёт, тепло не растёт; чистка output — отдельная задача.

### F-16. Экспорт — второй тяжёлый процесс вне очереди — medium

`POST /api/projects/{id}/exports` запускает `ffmpeg` (scale/pad/encode 1080×1920, aac).
Он не виден планировщику и может совпасть с рендером. Требование: не начинать
рендер, если идёт экспорт (и наоборот — предупреждать).

### F-17. Нет индикатора статуса воркера в UI — medium

UI показывает прогресс job (`JobProgress`) и прогон серии, но не показывает: какой
пресет/профиль реально применён, когда следующий запуск, почему стоит пауза.

---

## 6. Какие метрики реально доступны

| Метрика | Источник | Root? | Надёжность | Использование |
|---|---|---|---|---|
| thermal state (nominal/fair/serious/critical) | `ProcessInfo.thermalState` через Swift-helper (сборка локальная) | нет | высокая, штатный API | главный источник guard'а |
| thermal state без helper | — | — | **Unknown** | консервативные интервалы |
| throttle-события | `pmset -g therm` | нет | только записи о прошедших событиях; сейчас пусто | журнал/диагностика |
| throttle в реальном времени | `pmset -g thermlog` (поток) | нет | зависит от событий | фоновый sampler бенчмарка |
| memory pressure | `sysctl kern.memorystatus_vm_pressure_level` (1/2/4) | нет | высокая | guard памяти |
| доступная память | `vm_stat` (`free+inactive+speculative`) | нет | высокая | guard памяти |
| swap | `sysctl vm.swapusage` | нет | высокая | телеметрия/guard |
| питание и заряд | `pmset -g ps` | нет | высокая | запрет рендера на батарее |
| Low Power Mode | `pmset -g` (`lowpowermode`) | нет | высокая | профиль/UI, только чтение |
| память ComfyUI | `GET /system_stats` (`ram_free`, `torch_vram_free`) | нет | высокая | телеметрия |
| мощность/температуры/вентиляторы | `powermetrics` | **да** (sudo) | высокая при наличии прав | только опциональный бенчмарк |
| вентиляторы/температуры без root | SMC/`ioreg` | нет | недокументировано | **не использовать** |

Практический вывод: обязательный минимум (без root, без новых зависимостей) —
`pmset -g ps`, `pmset -g`, `sysctl kern.memorystatus_vm_pressure_level`, `vm_stat`,
`sysctl vm.swapusage`, `/system_stats`. Thermal state — либо helper, либо Unknown.

---

## 7. Что можно изменить без новых зависимостей

1. **Gate в воркере** перед `series_next`/`claim`: проверки питания, памяти, cooldown,
   счётчика партии — stdlib (`subprocess`, `time`, `json`).
2. **Тайминги** — `time.sleep` + persisted timestamps в
   `~/.mary-studio/thermal-state.json` (атомарная запись, как у state-файла prompt'ов).
3. **Телеметрия** — блок `parameters["thermal"]` в существующем JSONB и
   `peak_mem_mb` в существующем поле; миграция не нужна.
4. **Журнал решений** — append-only `~/.mary-studio/thermal-events.jsonl`
   (имена событий БД менять нельзя без миграции: `ck_events_event`).
5. **Уведомления** — существующий `app/notify.py` (баннер macOS).
6. **Пауза/возобновление серии** — существующие `POST /api/series/{id}/pause|resume`.
7. **Профили** — `RenderSettings`/CLI/переменные окружения; параметры рендера берутся
   из уже существующих `presets.py` и шаблона (`low_ram`).
8. **`caffeinate`** — системный бинарник в обёртке запуска (без зависимостей).
9. **Один новый read-only эндпоинт** статуса рендер-агента — это изменение API-контракта,
   требует отдельного утверждения в `DECISIONS.md` (см. документ планировщика §9).

---

## 8. Ожидаемые компромиссы

| Решение | Выигрыш | Цена |
|---|---|---|
| cooldown 480 с между шотами | ниже средняя температура, нет непрерывных 7 ч | 24 шота: +3 ч к общему времени (≈10 ч) |
| cooldown 1200 с после партии 3 | даёт устройству остыть | ещё +20 мин на каждые 3 шота |
| `low_ram: true` (Eco) | меньше давление на память | не измерено: возможно медленнее и/или иная картинка |
| запрет рендера на батарее | защита устройства | нельзя рендерить «в дороге» |
| Unknown → консервативные интервалы | работает без helper | медленнее, чем могло бы быть |
| helper `ProcessInfo` | точный guard и UI | одна локальная сборка Swift (не зависимость) |
| пауза серии при Serious/Critical | безопасность | прогон может «зависнуть» на часы без действия человека |

Явно принимается: **скорость — вторичный приоритет** (задание, п.5).

---

## 9. Риски

| Риск | Оценка | Смягчение |
|---|---|---|
| Ложное «всё хорошо» без helper | средний | Unknown → консервативно; UI показывает Unknown, а не «норма» |
| Автопродолжение после pause, которого не ждали | средний | автовозобновление только для паузы, поставленной самим планировщиком (флаг в state-файле) |
| Потеря состояния cooldown при рестарте | низкий | wall-clock timestamps в state-файле, атомарная запись |
| Два воркера | высокий | серверный guard «один активный render_video» (требует утверждения) |
| Бенчмарк сам перегревает устройство | средний | 4 прогона по одному шоту, пауза ≥30 мин, стоп по Serious/Critical |
| Тихая потеря качества в Eco | высокий | Eco не меняет production-параметры без подтверждения; preview-first |
| `pmset`/`sysctl` меняют формат в будущей macOS | низкий | парсер «терпимый», при неудаче — Unknown |

---

## 10. Тесты и критерии приёмки аудита

Проверяемость находок (без GPU):

1. `F-01` — unit-тест на `claim`: при существующем `render_video(status='running')` у
   другого шота новый claim либо запрещён (после утверждения), либо явно разрешён.
2. `F-02` — тест `_series_loop` с fake API: между `complete` и следующим
   `series_next` вызывается gate, и при активном cooldown `series_next` не вызывается.
3. `F-05` — тест, что `complete()` передаёт `peak_mem_mb` и `parameters["thermal"]`.
4. `F-06` — тест парсера `pmset -g therm`: пустой вывод → `unknown`, а не `nominal`.
5. `F-08` — тест: число heartbeat ≤ ceil(время/poll_heartbeat) при `poll_interval=5`.
6. `F-12` — тест gate: `pmset -g ps` = «Battery Power» → отказ с кодом `power_not_ac`.
7. `F-13` — тест gate: `memorystatus_vm_pressure_level = 2` → отказ с кодом
   `memory_pressure_high`.

Критерии приёмки **этапа аудита**:
- каждая находка имеет ссылку на файл/строку или реальный вывод команды;
- ни одно утверждение о метриках не опирается на недокументированные датчики;
- в дизайне планировщика нет ни одного «выдуманного» значения температуры/мощности;
- GPU-прогоны не выполнялись.

Критерии приёмки реализации — в `THERMAL_SAFE_SCHEDULER.md` §11 и
`RENDER_ENERGY_BENCHMARK.md` §8.

---

## 11. Открытые вопросы (блокируют реализацию)

1. **Точный thermal-источник.** Собирать Swift-helper `ProcessInfo.thermalState`
   (рекомендуется) или жить в режиме Unknown с консервативными интервалами?
2. **Серверный guard «один тяжёлый job».** Разрешить изменение поведения
   `series/next`/`claim` (без миграций, но контракт очереди меняется) или ограничиться
   проверкой в воркере?
3. **Один read-only эндпоинт статуса** `GET /api/render-agent/status` для UI —
   утвердить как аддитивное расширение API.
4. **Порог памяти и запрет батареи** — какие значения считать нормой (предложение:
   рендер только от сети, ≥50 % заряда, memory pressure = normal, доступно ≥4 ГиБ).
5. **Место запуска.** Оставить ручной запуск воркера или оформить `launchd` +
   `caffeinate -i` (C28) в рамках этого WP?
