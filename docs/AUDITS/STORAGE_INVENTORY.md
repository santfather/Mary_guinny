# STORAGE INVENTORY — Mary Studio (WP-AUDIT-01)

Дата: 2026-11-05. Режим: READ-ONLY. Ничего не удалялось и не перемещалось.
Команды: `du -sh`, `find | wc -l`, `git ls-tree -r -l`, `git status`, `df -h`, SQL `SELECT`.

Корень: `/Users/vladislavkovalenko/Projects/Mary_Guiness`, суммарно **3.3 GB**.
Свободно на томе: **66 GiB** (занято 17 % по `df -h /`).

---

## 1. Крупные каталоги

| Путь | Размер | Файлов | Назначение | Ссылки из БД | Git | Восстановимость | Риск удаления |
|------|--------|--------|------------|--------------|-----|-----------------|---------------|
| `runtime/` | 2.5 GB | 65 585 | Внешняя установка ComfyUI + логи + PID + state | косвенно (HTTP воркера) | ignored (`.gitignore:9`) | полная (реинсталл ComfyUI) | средний: сломает рендер до реинсталла |
| `runtime/ComfyUI/` | 2.5 GB | — | движок, `models/` 48 KB, `custom_nodes/` 732 KB, `output/` 149 MB, `input/` 57 MB | output не в БД | ignored | реинсталл | средний |
| `runtime/ComfyUI/output/` | 149 MB | 55 | `ltx2mlx` 48 MB, `nlb` 100 MB — выходы ComfyUI | нет (копии уже в blob) | ignored | нет (повторный рендер) | низкий, но это доказательства старых прогонов |
| `runtime/ComfyUI/input/` | 57 MB | 18 | входные кадры для `/prompt` | нет | ignored | из blob | низкий |
| `runtime/logs/` | 2.9 MB | — | логи воркера/бэкенда | нет | ignored | нет | низкий |
| `runtime/ltx-worker-state.json` | 4 KB | 1 | recovery-состояние воркера (WP-M4) | нет | ignored | нет | низкий (потеря recovery) |
| `export/` | 251 MB | 95 | ручные материалы вне БД | нет | ignored (`.gitignore:28`) | нет | низкий/средний (см. §3) |
| `export/LLM-gen/` | 241 MB | 93 MP4 | ролики, сгенерированные внешними LLM | **нет** | ignored | нет | низкий после решения человека |
| `export/wp_voice_06_ab/` | 10 MB | 2 MP4 + кадры + 2 PNG-листа | доказательства A/B WP-VOICE-06 | нет | ignored | нет | низкий, но это приёмка |
| `storage/` | 149 MB | 103 | blob-хранилище приложения | **да** | ignored (`.gitignore:16`) | из БД + файлы | **высокий** |
| `backend/` | 93 MB | — | код; из них `.venv` 89 MB | — | код в Git, `.venv` ignored | `uv sync` | средний |
| `ui/` | 71 MB | — | `node_modules` 71 MB + `dist` | — | ignored | `npm ci` | низкий |
| `docs/` | 25 MB | — | документация; `docs/cats` 24 MB / 24 файла | да (источники reference) | **tracked** | Git | **высокий** |
| `characters/` | 9.1 MB | — | исходники персонажей (импортированы) | да, через `reference_assets` | PNG/JPG ignored, JSON tracked | Git + импорт | высокий |
| `episodes/` | 3.4 MB | — | исходники эпизодов | да | MP4/PNG/WAV/MP3 ignored | нет | высокий |
| `comfyui-workflows/` | 48 KB | — | API-workflow LTX | да (`workflow_version` = sha256) | tracked | Git | высокий |
| `pipeline/` | 252 KB | — | legacy-конвейер | частично (client/ltx_adapter) | tracked | Git | высокий |
| `comfyui-input/` | **0 B** | 0 | пустой каталог, **не** в `.gitignore` | нет | untracked | — | нет |
| `exports/` | **0 B** | 0 | пустой каталог-двойник `export/` | нет | ignored (`exports/*`) | — | нет |

Вне рабочего каталога (влияет на диск, но не на репозиторий):

| Путь | Размер | Назначение | Риск удаления |
|------|--------|------------|---------------|
| `~/.ollama` | 85 GB | все локальные LLM (в т.ч. `gemma3:4b` для planner/production plan) | высокий: planner и plan сломаются |
| `~/.cache/huggingface` | 65 GB | 63 GB в `hub/blobs`; `whisper-large-v3-turbo` 1.5 GB; LTX-2.3 MLX — символические ссылки (каталог `dgrauet--ltx-2.3-mlx-q4` 112 KB) | высокий: LTX-веса |
| `~/.mary-studio/tools/rhubarb-1.14.0/` | ~8.4 MB бинарник + `res/` | Rhubarb Lip Sync | средний: тайминги визем |

---

## 2. Blob-хранилище (`storage/blobs`)

103 файла, 155 656 663 Б (≈148.4 MiB). Расширения:

| Расширение | Файлов |
|------------|--------|
| `.mp4` | 49 |
| `.png` | 45 |
| `.jpg` | 3 |
| `.jpeg` | 2 |
| `.mp3` | 2 |
| `.wav` | 1 |
| `.DS_Store` | 1 |

### 2.1 Сопоставление с БД

| Проверка | Значение |
|----------|----------|
| `artifacts` всего | 297 |
| Из них файл существует | 99 (175 762 637 Б по полю `bytes`, с учётом дублей ключей) |
| Из них файла нет | **198** (18 924 421 Б) |
| `reference_assets` всего | 50 (29 approved / 19 draft / 2 rejected) |
| Уникальных `storage_key` у reference | 44 |
| Reference без файла | **0** |
| Файлов на диске | 103 |
| Файлов, на которые нет ссылок ни в `artifacts`, ни в `reference_assets` | **2** |

Артефакты по видам (SQL `group by kind`):

| kind | Записей | Сумма `bytes` | Файлы на диске |
|------|---------|---------------|----------------|
| `video` | 40 | 105 199 441 | есть |
| `keyframe` | 46 | 53 374 184 | есть (общие blob с reference) |
| `project_audio` | 198 | 19 309 395 | **197 из 198 отсутствуют** |
| `export_video` | 1 | 12 763 131 | есть |
| `talking_preview` | 4 | 2 633 352 | есть |
| `composition_preview` | 2 | 1 085 855 | есть |
| `video_draft` | 5 | 321 691 | есть |
| `note` | 1 | 9 | **отсутствует** |

### 2.2 Orphan-файлы (единственные два)

| Путь | Размер | Почему orphan |
|------|--------|----------------|
| `storage/blobs/.DS_Store` | 14 340 Б | macOS-мусор, не ссылается ни одна таблица |
| `storage/blobs/20/201bc4b0bd3a8a6785b292f46bc802d0b5ecc558706b9bd3c0245adb6b89d0f4.wav` | 1 136 138 Б | WAV не входит ни в `artifacts`, ни в `reference_assets` (вероятно, рабочая копия для Rhubarb/огибающей) |

Итого потенциально освобождается в Stage 1: **1 150 478 Б ≈ 1.1 MB** — цифра честная, но мала.

### 2.3 Дубли

- `reference_assets`: 6 групп одинакового `sha256` по 2 записи; во всех группах
  `count(distinct project_id) = 2` — это **межпроектные** копии (NLB и GNS/Mary Studio),
  а не мусор. Удаление одной из копий нарушит S13 (изоляция проектов).
- `artifacts`: 10 групп одинакового `storage_key` (28 «лишних» строк). Примеры:
  `blobs/38/38eb09d0….png` — 7 записей, `blobs/65/654dab02….png` — 7,
  `blobs/90/904cb044….mp4` — 2. Это **дедупликация на уровне blob**: несколько
  `artifacts` (keyframe разных попыток/шотов, повторный preview) ссылаются на один файл.
  Удалять строки нельзя — на них ссылаются `render_attempts` и `reference_assets`.

---

## 3. Классификация данных

| Класс | Примеры | Можно ли удалять |
|-------|---------|------------------|
| Ценные исходники (tracked) | `docs/cats/*` (24 files), `characters/`, `prompts/`, `comfyui-workflows/`, `comfyui-workflows/*.api.json` | нет |
| Approved-ассеты | 29 approved `reference_assets`, 5 viseme GNS-05, 7 NLB-персонажей | нет (S15) |
| Активные данные | 40 видео-артефактов, 46 keyframe, 1 export, 4 talking preview | нет |
| Воспроизводимые | `runtime/ComfyUI/output` 149 MB, `runtime/ComfyUI/input` 57 MB | только после согласования (Stage 3) |
| Временные | `runtime/logs` 2.9 MB, `storage/tmp` 0 B, `ui/dist` | да, Stage 1 |
| Внешние эксперименты | `export/LLM-gen` 241 MB / 93 MP4 | только по решению человека (Stage 3) |
| Материалы приёмки | `export/wp_voice_06_ab` 10 MB | нет, пока A/B не решён |
| Orphan | `.DS_Store` + `201bc4b0….wav` | да, Stage 1 |
| Битые ссылки БД | 198 `artifacts` без файла | **нет**: это записи БД (см. `DATABASE_INTEGRITY.md`) |

---

## 4. Git и хранение

- Игнорируются: `.env`, `storage/`, `runtime/`, `export/`, `exports/*`,
  `ui/node_modules/`, `ui/dist/`, `comfyui-input/**`, медиа в `characters/` и `episodes/`
  (`.gitignore:2,9,12,16,22–28`).
- Хранятся в Git: код, миграции, документы, `docs/cats/*.png` (крупнейший —
  `docs/cats/Feline Rock Band Under Neon Lights.png` 2 614 008 Б), workflow JSON.
- Git-объекты: 567 loose, 15.09 MiB, pack отсутствует (`git count-objects -vH`).
- **`comfyui-input/` не покрыт `.gitignore`** (пустой сегодня, но при появлении файлов
  попадёт в untracked).

---

## 5. Ограничения

- Размеры — `du` (allocated), суммы `bytes` из БД — логические; расхождение
  (155.6 MB файлов vs 175.8 MB суммы `bytes`) объясняется 28 дублирующими строками.
- `~/.cache/huggingface/hub/blobs` (63 GB) общий для нескольких моделей, разбивка по
  репозиториям на уровне symlink не показывает фактический объём — **NOT VERIFIED**
  по-модельно.
- `launchd`/автозапуск не проверены (permission denied) — **NOT VERIFIED**.
