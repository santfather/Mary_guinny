# Guinness: Night Shift — render configuration и план генерации (preflight)

> Дата: 2026-11-04. Аудит только чтением: `pip list`, исходники
> `runtime/ComfyUI/custom_nodes/comfyui-ltx2-mlx`, `ltx_pipelines_mlx`, `ffprobe`,
> `psql` (read-only). GPU не запускался, ComfyUI не поднимался, jobs не создавались.

---

## 1. Аудит стека

| Компонент | Версия / значение | Источник |
|---|---|---|
| ComfyUI | 0.42.0, commit `0b05cd8a` | `runtime/ComfyUI/comfyui_version.py`, `git` |
| comfyui-ltx2-mlx | 0.2.1, commit `d38b63a` | `pyproject.toml`, `git` |
| ltx-pipelines-mlx / ltx-core-mlx | 0.18.0 | `pip list` |
| MLX | 0.32.4 | `pip list` |
| PyTorch | 2.14.1 | `pip list` |
| Модель | `dgrauet/ltx-2.3-mlx-q4`, `pipeline_type=distilled` | `ltx23_mlx_q4_i2v.api.json` |
| Workflow | `LoadImage → LTX2MLXModelLoader → LTX2MLXGenerate` | тот же файл |
| `workflow_version` | `ltx23-mlx-q4-i2v/a48ba1c43439` | `pipeline/comfyui/ltx_adapter.py` |
| FFmpeg | 7.1.1 | `ffmpeg -version` |
| Пресеты | `safe`, `wide`, `legacy_512` | `backend/app/presets.py` |
| ComfyUI статус | **не запущен**, порт 8188 закрыт | `lsof`, `pgrep` |

Модели лежат в HF-кэше (`~/.cache/huggingface`, 63 ГБ блобов); `runtime/ComfyUI/models`
пустой. Ничего не скачивалось.

---

## 2. G. Подтверждённый безопасный профиль

| Параметр | Значение | Статус |
|---|---|---|
| Пресет | `safe` | **измерен** (24 прогона) |
| Разрешение | 576×1024 (9:16, кратно 64) | измерено |
| Кадры / fps | 193 / 24 | измерено |
| Длительность | 8,042 с | измерено `ffprobe` |
| `cfg_scale` | 3,0 | в пресете, применялся |
| steps | stage 1 — 8, stage 2 — 3 (distilled) | фиксированы пайплайном |
| Аудио | генерируется вместе с видео (`aac` 48 кГц stereo) | подтверждено в MP4 |
| Thermal | `eco` (сеть, pressure=normal, ≥ 4 ГиБ, cooldown 480 с) | измерено |
| `peak_mem_mb` | 16 295 из 18 432 | измерено 2026-11-04 |
| `min_available_mb` / `max_pressure_level` | 2 137 / 4 (critical) | измерено |
| `low_ram` | false | измерено |
| Время рендера | 995,7 с (acceptance), 1 062,5 с (среднее 24 шотов) | измерено |

Это **единственный** профиль, который можно ставить в production без новых замеров.
Любое отклонение (кадры, разрешение, cfg, `low_ram`) — отдельный тест.

### 2.1 Почему 576×1024

- 1080×1920: two-stage снапит стороны до кратных 64 → 1024×1920; в калибровке
  2026-10-28 stage 2 не завершил ни одного шага за 24 мин (DECISIONS §4.5).
- Точное 9:16 при обеих сторонах, кратных 64: `w=576k`, `h=1024k`. `k=1` — 576×1024;
  `k=2` — 1152×2048 (вчетверо больше пикселей, на 18 ГБ нереально).
- Апскейл до 1080×1920 выполняется на этапе экспорта, а не рендера.

### 2.2 Что не параметризуется

`LTX2MLXGenerate` не принимает `steps`, `sampler`, `scheduler`, `negative_prompt`,
`generate_audio` и `low_ram` — только `prompt`, `image`, `width`, `height`,
`num_frames`, `seed`, `cfg_scale`, `frame_rate`, `filename_prefix`. `low_ram`
принадлежит загрузчику модели (`LTX2MLXModelLoader`). Значит «улучшить» сэмплер
через наш workflow нельзя без правки адаптера и шаблона (изменение контракта —
отдельное разрешение).

---

## 3. Сравнение вариантов качества

| Вариант | Параметры | Влияние на память | Оценка времени | Вердикт |
|---|---|---|---|---|
| **A. Baseline** | 576×1024, 193 кадра, 24 fps, cfg 3,0 | измерено: 16,3 ГБ пик, pressure 4 | 996–1 063 с/шот | **рекомендован** |
| B. cfg 4,0 | то же, `--cfg-scale 4.0` | без изменений (память та же) | ≈ то же | не применять без теста: качество/артефакты неизвестны |
| C. 257 кадров (10,7 с) | +33 % кадров | токены видео +33 %, память вырастет (экстраполяция, не измерено) | ≈ +30–35 % | только после отдельного теста |
| D. 1152×2048 | 4× пикселей | экстраполяция > 24 ГБ → не влезет | — | отклонить |
| E. 1024×1920 | не завершился в калибровке | критично | — | отклонить |
| F. 1024×576 (wide) | 16:9 | измерено (3 шота) | — | неверный формат для 9:16 |
| G. 512×512/73 | legacy | ниже | быстрее | качество ниже baseline |
| H. safe + `low_ram=true` | потоковая загрузка весов | **не измерено** | вероятно медленнее | отдельный тест, §4 |

Матрица «одновременно нельзя»: разрешение + кадры + steps + число моделей.
В baseline всё уже на пределе, поэтому меняем **не более одного** параметра за тест.

---

## 4. План отдельной проверки `low_ram=true`

Условия: только preview (73 кадра), разрешение и cfg как в baseline, один GPU job,
профиль `eco`, сеть, после «холодного» старта ComfyUI.

1. Поднять ComfyUI, дождаться загрузки модели.
2. Прогнать **preview** одного шота с `low_ram=false` — зафиксировать `peak_mem_mb`,
   `min_available_mb`, `max_pressure_level`, время.
3. Изменить в шаблоне `LTX2MLXModelLoader.low_ram=true` **копией** шаблона (не править
   production-файл) и прогнать тот же preview с тем же seed.
4. Сравнить: пик памяти, минимальная доступная память, время, визуальное качество.
5. Решение фиксируется только в `DECISIONS.md`; при ухудшении качества вариант
   отклоняется.

Этот тест **не входит** в preflight и требует отдельного разрешения.

---

## 5. D. Пять motion prompts (дословно из задания)

```text
GNS-01: A sable Burmese cat sits by a moonlit apartment window, slowly turns its head
toward the camera, subtle ear and whisker movement, natural breathing, consistent
feline anatomy, stable cinematic framing, one continuous shot.

GNS-02: The sable Burmese cat gently taps a small candy wrapper once with its front
paw. The wrapper slides across the wooden floor. Natural feline paw movement, stable
body proportions, fixed cinematic camera, continuous realistic motion.

GNS-03: The sable Burmese cat runs naturally on all four paws through a dim apartment
corridor, slows down and stops, ears perk up, low fixed camera, consistent feline
anatomy, natural realistic gait, one continuous cinematic shot.

GNS-04: The sable Burmese cat slowly extends one front paw and gently nudges a ceramic
cup a short distance toward the table edge. The cup remains upright. Stable camera,
realistic feline movement, accurate paw-object interaction, continuous cinematic
motion.

GNS-05: The sable Burmese cat reclines on a dark teal velvet sofa, slowly raises its
head and looks directly toward the camera, natural breathing, subtle tail movement,
gentle mouth movement only when supported by an appropriate lip sync engine, stable
cinematic framing.
```

Варианты под фактическую позу стартового кадра — PRODUCTION_PLAN §4.1. Реплики в
промпт не вставляются: текст в промпте не даёт синхронизированной речи (AUDIO_PLAN §4).

---

## 6. Порядок подготовки (без GPU)

```bash
# 1. Проект, сцена, 5 шотов, motion-ревизии, референсы — штатный импорт
cd backend
.venv/bin/python -m app.import_series \
  --manifest ../docs/PROPOSALS/gns_manifest.json \
  --project-title "Guinness: Night Shift" --create-project \
  --references-dir ../docs/cats --fps 24 --dry-run
# после проверки отчёта — то же с --apply

# 2. Identity и стартовые кадры (сырое тело, статус draft)
curl -sS -X POST "$API/api/projects/$GNS/references?kind=uploaded&role=guinness_identity" \
  --data-binary @"../docs/cats/Chocolate Burmese Cat Portrait.png"
curl -sS -X POST "$API/api/projects/$GNS/references?kind=uploaded&role=gns_01_start" \
  --data-binary @"../docs/cats/Cat and moon.png"
# … gns_02_start … gns_05_start

# 3. Approve референсов — делает человек
curl -sS -X POST "$API/api/reference-assets/$REF/approve"

# 4. Стартовый кадр: keyframe из референса → promote
curl -sS -X POST "$API/api/shots/$SHOT/keyframe" \
  -H 'Content-Type: application/json' -d "{\"reference_asset_id\":\"$REF\"}"
curl -sS -X POST "$API/api/shots/$SHOT/attempts/$ATTEMPT/promote-keyframe"

# 5. Preflight серии: манифест передаётся телом запроса (пути на сервере не принимаются)
curl -sS -X POST "$API/api/projects/$GNS/series/preflight" \
  -H 'Content-Type: application/json' \
  -d "{\"manifest\": $(cat ../docs/PROPOSALS/gns_manifest.json), \"fps\": 24}"
# ожидание: start_frames 5 из 5, references ok, ни одного missing_*
```

Манифест собирается по контракту `backend/app/series_manifest.py`:
`schema_version`, `project_title`, `episode_title`, `target_aspect_ratio: "9:16"`,
`target_fps: 24`, `shots[{order, shot_key, title, category, prompt_original,
target_duration_seconds:[8,8], start_frame_filename, identity_reference_filename,
output_name_prefix}]`. `target_duration_seconds [8,8]` → 193 кадра.

Замечание: `series_import` пишет в параметры ревизии `source="nine_lives_band_manifest"`
(жёстко зашито). Для GNS это косметическая неточность провенанса; исправление —
правка кода, вне текущего объёма.

---

## 7. H. План последовательной генерации

Пять **отдельных** прогонов по одному шоту. Никакого batch из пяти.

| Шаг | Действие | Проверка перед следующим |
|---|---|---|
| 0 | Поднять backend и ComfyUI, дождаться загрузки модели | `/system_stats` 200, `render_video` активных = 0 |
| 1 | `POST /api/projects/{id}/series/runs {"title":"GNS-01","shot_orders":[1]}` | run `draft`, item `pending` |
| 2 | `POST /api/series/runs/{run}/start` | run `running` |
| 3 | Воркер: `.venv/bin/python worker/ltx_worker.py --preset safe --thermal-profile eco --series-run $RUN --once` | job `completed`, attempt `completed` |
| 4 | Ревью: MP4, память, thermal, журнал, качество (ACCEPTANCE §3) | отчёт + явное «дальше» |
| 5 | Повторить 1–4 для GNS-02…05 | то же |

Ожидаемый режим отказа: при `max_pressure_level=4` следующий run **не создаётся** и не
стартует; фиксируется событие и предложение по параметрам (ACCEPTANCE §4).

### 7.1 Команды запуска

```bash
# backend (из backend/)
.venv/bin/python -m uvicorn app.main:app --port 8000
# ComfyUI (из runtime/ComfyUI/) — штатный запуск проекта
# воркер (из корня репозитория), токен только из env, не печатать
.venv/bin/python worker/ltx_worker.py --preset safe --thermal-profile eco \
  --series-run "$RUN" --once
```

### 7.2 Проверки перед каждым шотом

```bash
psql -d mary_studio -At -c "select count(*) from jobs where kind='render_video' and status in ('pending','queued','leased','running');"   # 0
curl -sS "$API/api/render-agent/status"                    # worker_online, cooldown, memory
pmset -g ps | head -1                                      # питание от сети
sysctl -n kern.memorystatus_vm_pressure_level              # 1 = normal
```

---

## 8. I. Оценка времени и нагрузки

| Статья | Оценка | Основание |
|---|---|---|
| Один production-рендер | 996–1 063 с (16,6–17,7 мин) | `render_seconds` 995,7 с и среднее 1 062,5 с |
| Пять рендеров | 83–89 мин чистого GPU | 5 × диапазон |
| Паузы `eco` между jobs | ≈ 8 мин × 4 (32 мин); после партии из 3 — до 20 мин | cooldown 480 / 1200 с |
| Старт стека (backend + ComfyUI + загрузка модели) | ≈ 2–5 мин | `[ПРОВЕРИТЬ]` по факту первого шота |
| Preview 73 кадра (если нужен) | ≈ 6–10 мин на шот | оценка, **не измерено** |
| Итоговое GPU-окно на 5 шотов | ≈ 2,0–2,3 ч | сумма строк выше |
| Пик памяти | 16,3 ГБ из 18,4 ГБ; свободно было 2,1 ГБ | измерено |
| Диск | 5 MP4 ≈ 15–25 МБ + финальный 1080×1920 ≈ 30–60 МБ | при 66 ГиБ свободных — не ограничение |

Нагрузка на машину: один GPU job, `eco`, сеть, `caffeinate`, thermal guard включён.
Ollama не используется во время рендера (модели выгружаются, `keep_alive: 0`), тяжёлые
приложения закрываются — иначе `min_available_mb` уйдёт ниже 2 ГБ.

Косвенная метрика: 8,042 с видео за ≈17 мин — соотношение ≈1:127; это цена `safe`
на M3 Pro 18 ГБ и потолок текущего железа.

---

## 9. Косметические замечания (не блокеры)

1. `ltx_adapter._output_prefix` всегда пишет `nlb/<shot_key>/<attempt_id>` — файлы
   GNS появятся в ComfyUI-каталоге с префиксом `nlb/`. На данные и провенанс не влияет.
2. `series_import` маркирует ревизии как `nine_lives_band_manifest` (см. §6).
3. Identity-портрет нельзя использовать как стартовый кадр; для GNS он только
   identity reference.
