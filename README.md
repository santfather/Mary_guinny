# Mary_Guiness — AI-видео шоу про кота Гиннесса и Марию

Пайплайн для производства коротких анимационных эпизодов с двумя персонажами:
котом Гиннессом и его хозяйкой Марией. Проект сочетает локальные инструменты
(Ollama + ComfyUI) для сценария и черновиков с облачными сервисами для финального
видео, озвучки, lip sync и музыки.

Управление — единый CLI (`main.py`) с асинхронным оркестратором этапов.

---

## Возможности

- Генерация сценария через локальную модель Ollama и парсинг на сцены.
- Библиотека референсов персонажей: 7 поз на каждого, генерация через ComfyUI.
- Черновики сцен: keyframe в ComfyUI + сборка mp4 через ffmpeg.
- Поэтапный пайплайн с двумя фазами: `local` (локально) и `cloud` (облачные API).
- Проверка готовности ComfyUI: доступность сервера, custom nodes, модели.
- Проверка статуса этапов и повторный запуск с места остановки.

---

## Структура проекта

```
Mary_Guiness/
├── main.py                        # CLI-точка входа
├── pipeline/
│   ├── config.py                  # Settings из .env, пути, список персонажей и поз
│   ├── models.py                  # PipelineStage, PipelinePhase, Scene, StageResult, EpisodeContext
│   ├── orchestrator.py            # Запуск этапов, порядок фаз, создание структуры папок
│   ├── utils.py                   # Парсер сценария, работа с character_bible, сборка промптов
│   ├── comfyui/
│   │   ├── client.py              # HTTP-клиент ComfyUI API (queue, history, upload, view)
│   │   ├── workflows.py           # Загрузка/рендер workflow-шаблонов, построение промптов
│   │   ├── generator.py           # Генерация референсов персонажей + проверка окружения
│   │   └── scene_draft.py         # Генерация keyframe сцены и сборка черновика mp4
│   └── stages/
│       ├── base.py                # Базовый абстрактный этап
│       ├── character_refs.py      # Проверка наличия референсов и bible
│       ├── script.py              # Генерация сценария через Ollama
│       ├── scene_draft.py         # Черновики сцен
│       ├── final_video.py         # Финальные клипы (Grok / Kling)
│       ├── voices.py              # Озвучка реплик (ElevenLabs)
│       ├── lipsync.py             # Lip sync (Hedra)
│       ├── music.py               # Фоновая музыка (Suno / Mubert)
│       └── assembly.py            # Проверка клипов и финальная сборка
├── characters/
│   ├── guinness/                  # reference_*.png + character_bible.txt
│   └── marija/                    # reference_*.png + character_bible.txt
├── episodes/
│   └── ep01/
│       ├── script.txt              # Сценарий эпизода
│       ├── scenes/                 # *_draft.mp4, *_keyframe.png, *_final.mp4, *_lipsync.mp4
│       └── audio/                  # реплики персонажей и bg_music.mp3
├── comfyui-workflows/              # JSON-шаблоны ComfyUI + workflow_config.json
├── comfyui-input/
│   └── poses/                      # скелеты поз (OpenPose) для ControlNet
├── prompts/
│   ├── Modelfile_CatShow           # Modelfile для Ollama
│   ├── character_poses.json        # описание 7 поз и настроек IP-Adapter
│   ├── grok_video_template.txt     # шаблон промпта для финального видео
│   └── elevenlabs_voice_notes.txt  # рекомендации по голосам
├── exports/                        # готовые эпизоды
├── tests/                          # pytest-тесты пайплайна и ComfyUI-хелперов
├── runtime/ComfyUI/                # локальный клон ComfyUI (рантайм, не код проекта)
├── scenario.md                     # исходное описание концепции и настройки окружения
├── AI_Tools_Analysis.md            # база знаний по AI-инструментам
├── CLAUDE.md / .cursorrules        # соглашения для AI-агентов
├── requirements.txt
├── pytest.ini
├── .env.example
└── .env                            # локальные секреты (не коммитится)
```

---

## Компоненты

### CLI (`main.py`)

| Команда | Назначение |
|---|---|
| `python main.py init` | Создать недостающие папки проекта |
| `python main.py run --episode ep01` | Запустить этапы фазы (по умолчанию `local`) |
| `python main.py run --phase full` | Все 8 этапов |
| `python main.py run --stage script --prompt "..."` | Один конкретный этап |
| `python main.py run --from script --to scene_draft` | Диапазон этапов |
| `python main.py run --continue-on-error` | Не останавливаться на ошибке |
| `python main.py status --episode ep01` | Проверить готовность этапов |
| `python main.py stages` | Показать порядок этапов по фазам |
| `python main.py comfy check` | Проверить ComfyUI, ноды и модели |
| `python main.py comfy generate-ref --character guinness --pose reference_front` | Одна поза |
| `python main.py comfy generate-all --character guinness [--skip-front] [--force]` | Все 7 поз |

Доступные персонажи: `guinness`, `marija`. Позы: `reference_front`, `reference_side`,
`reference_3q`, `reference_sit`, `reference_walk`, `reference_surprised`, `reference_sleep`.

### Этапы пайплайна

| Этап | Фаза | Что делает | Внешний сервис |
|---|---|---|---|
| `character_refs` | local | Проверяет наличие 7 референсов и `character_bible.txt` у каждого персонажа | ComfyUI (генерация через CLI) |
| `script` | local | Генерирует сценарий по `--prompt` и сохраняет `script.txt` | Ollama |
| `scene_draft` | local | Строит keyframe по сцене и собирает черновик mp4 | ComfyUI + ffmpeg |
| `final_video` | cloud | Готовит промпты для финальных клипов по сценам | Grok / Kling |
| `voices` | cloud | Проверяет наличие mp3-реплик по сценам | ElevenLabs |
| `lipsync` | cloud | Проверяет наличие клипов после lip sync | Hedra |
| `music` | cloud | Проверяет наличие `bg_music.mp3` | Suno / Mubert |
| `assembly` | cloud | Проверяет комплект клипов для финальной сборки | DaVinci Resolve |

Фазы:

- `local` (по умолчанию): `character_refs → script → scene_draft`
- `cloud`: `final_video → voices → lipsync → music → assembly`
- `full`: все этапы в порядке `PipelineStage`

### Формат сценария

Парсер (`pipeline/utils.py`) ожидает блоки следующего вида:

```
СЦЕНА 1: Краткое название
ГИННЕСС: реплика
МАРИЯ: реплика
ДЕЙСТВИЕ: визуальное описание сцены
```

### Оркестратор

`Orchestrator` создаёт экземпляры всех этапов, разрешает список этапов по фазе/диапазону
и последовательно запускает их через `EpisodeContext`. При ошибке этапа выполнение
прерывается, если не передан `stop_on_error=False`.

### ComfyUI-интеграция

- `ComfyUIClient` работает с HTTP API: `/system_stats`, `/object_info`, `/prompt`,
  `/history/{id}`, `/view`, `/upload/image`.
- `workflows.py` рендерит API-шаблоны: подставляет `{{ПЕРЕМЕННЫЕ}}` в JSON с сохранением
  типов (числа остаются числами).
- `generator.py` выбирает шаблон под позу: `ipadapter` (если есть якорный референс и
  разрешено в `character_poses.json`), `openpose` (если есть скелет в `comfyui-input/poses`),
  иначе `txt2img`.
- `scene_draft.py` генерирует keyframe и превращает его в mp4 через `ffmpeg`
  (по умолчанию 5 секунд, 24 fps, 768×512).

### Шаблоны ComfyUI (`comfyui-workflows/`)

API-шаблоны (`*.api.json`) — формат, который принимает `/prompt`:

- `character_pose_gen.api.json` — генерация референса персонажа (txt2img);
- `character_pose_openpose.api.json` — поза через ControlNet OpenPose;
- `character_pose_ipadapter.api.json` — поза через IP-Adapter;
- `scene_draft_ipadapter.api.json` — keyframe сцены через IP-Adapter;
- `scene_draft_ltx.api.json` — LTX-workflow с `LoadImage` и `FRAMES`.

Метаданные и конфигурация:

- `workflow_config.json` — общие параметры: checkpoint, ControlNet, IP-Adapter, размеры,
  sampler, CFG, negative prompt, длительность и fps сцены, список обязательных custom nodes;
- `character_pose_gen.json`, `controlnet_pose.json`, `scene_draft_ltx.json` — описания
  соответствующих шаблонов.

UI-граф:

- `ltx23_mlx_q4_test.json` — пример LTX-2 MLX text-to-video (q8, 256×256, 25 кадров).
  API-версии этого workflow в репозитории нет; параметры примера не совпадают с
  экспериментом 512×512 / 73 кадра / Q4.

---

## Зависимости

### Python

Требуется Python 3.13 (проект проверен на `.venv` с Python 3.13).
Пакеты из `requirements.txt`:

| Пакет | Назначение |
|---|---|
| `httpx` | Асинхронные HTTP-запросы к Ollama и ComfyUI |
| `python-dotenv` | Загрузка настроек из `.env` |
| `litellm` | Шлюз к облачным LLM/API (задел на облачную фазу) |
| `pytest`, `pytest-asyncio`, `pytest-mock` | Тесты |

### Внешние инструменты

| Инструмент | Роль | Обязательность |
|---|---|---|
| **Ollama** | Генерация сценария моделью `catshow` | Для этапа `script` |
| **ComfyUI** | Референсы персонажей и keyframe сцен | Для `character_refs`, `scene_draft` |
| **ffmpeg** | Сборка mp4 из keyframe | Для `scene_draft` |
| **Grok / Kling** | Финальные клипы | Для `final_video` |
| **ElevenLabs** | Синтез реплик | Для `voices` |
| **Hedra / Sync.so** | Lip sync | Для `lipsync` |
| **Suno / Mubert** | Музыка | Для `music` |
| **DaVinci Resolve / CapCut** | Финальная сборка эпизода | Для `assembly` |

### Модели и custom nodes ComfyUI

Custom nodes (устанавливаются через ComfyUI Manager):

- `ComfyUI_IPAdapter_plus`
- `comfyui_controlnet_aux`
- `ComfyUI-VideoHelperSuite`
- `ComfyUI-AnimateDiff-Evolved`
- `ComfyUI-LTXVideo`

Модели (имена задаются в `comfyui-workflows/workflow_config.json`):

- `checkpoints/dreamshaper_8.safetensors` — основной checkpoint
- `controlnet/control_v11p_sd15_openpose.pth` — OpenPose для SD 1.5
- `controlnet/controlnet-openpose-sdxl.safetensors` — OpenPose для SDXL (опционально)
- `ipadapter/ip-adapter-plus_sd15.safetensors` — IP-Adapter
- `clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` — CLIP Vision для IP-Adapter
- `diffusion_models/ltxv-13b-0.9.8-dev-fp8.safetensors` — LTX-Video (опционально)

Путь к ComfyUI задаётся через `COMFYUI_ROOT`, иначе используется путь по умолчанию
из `pipeline/comfyui/generator.py`.

---

## Установка и запуск

```bash
cd /Users/vladislavkovalenko/Projects/Mary_Guiness

python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env    # заполнить ключи по необходимости
python main.py init
```

Перед запуском локальных этапов должны быть доступны:

```bash
ollama serve                      # Ollama на http://localhost:11434
# ComfyUI на http://127.0.0.1:8188
```

Создание модели-сценариста:

```bash
ollama create catshow -f prompts/Modelfile_CatShow
```

Пример первого запуска:

```bash
python main.py comfy check
python main.py comfy generate-all --character guinness
python main.py run --episode ep01 --stage script \
  --prompt "Напиши эпизод про то, как Гиннесс не даёт Марии работать"
python main.py run --episode ep01 --stage scene_draft
python main.py status --episode ep01
```

---

## Конфигурация (`.env`)

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Адрес Ollama |
| `OLLAMA_MODEL` | `catshow` | Модель для сценария |
| `COMFYUI_BASE_URL` | `http://127.0.0.1:8188` | Адрес ComfyUI |
| `COMFYUI_ROOT` | — | Локальная папка ComfyUI (для проверки моделей) |
| `LITELLM_MODEL` | `ollama/catshow` | Модель для LiteLLM-шлюза |
| `GROK_API_KEY` | — | Финальное видео (Grok) |
| `KLING_API_KEY` | — | Резервное финальное видео (Kling) |
| `ELEVENLABS_API_KEY` | — | Озвучка |
| `HEDRA_API_KEY` | — | Lip sync |
| `SUNO_API_KEY` | — | Музыка |

Этапы облачной фазы без ключа возвращают неуспешный результат с пояснением,
а не падают с исключением.

---

## Тесты

```bash
pytest
```

Конфигурация: `pytest.ini` (`asyncio_mode = auto`, каталог `tests`).
Покрыты парсинг сценария, разрешение этапов оркестратором, рендер workflow-шаблонов и
выбор шаблона под позу.

Текущий результат: `14 passed, 1 failed`. Падает
`test_character_refs_stage_reports_missing`: тест подменяет настройки уже созданного
`Orchestrator`, а этапы держат настройки, переданные в `__init__`.

---

## Текущее состояние

- Локальная фаза реализована: сценарий через Ollama, референсы и keyframe через ComfyUI,
  сборка черновика через ffmpeg.
- Облачная фаза пока работает в режиме проверки артефактов: этапы `final_video`, `voices`,
  `lipsync`, `music`, `assembly` формируют задания/проверяют файлы, а генерация выполняется
  во внешних сервисах вручную.
- Все шаблоны, на которые ссылается код (`character_pose_gen.api.json`,
  `character_pose_openpose.api.json`, `character_pose_ipadapter.api.json`,
  `scene_draft_ltx.api.json`, `scene_draft_ipadapter.api.json`), присутствуют.
- Для LTX-2 MLX есть только UI-граф `ltx23_mlx_q4_test.json` (T2V, q8, 256×256,
  25 кадров); API-формата I2V Q4 в репозитории нет.
- `runtime/ComfyUI/` — сторонний рантайм, не относится к логике проекта.
- Репозиторий не инициализирован как git.

---

## Связанные документы

- [docs/PROPOSALS/MARY_STUDIO_INTEGRATION.md](docs/PROPOSALS/MARY_STUDIO_INTEGRATION.md) — предложение по интеграции с Mary Studio / Video Orchestrator.
- [docs/ROADMAP_MARY_STUDIO.md](docs/ROADMAP_MARY_STUDIO.md) — план работ по пакетам.
- [scenario.md](scenario.md) — концепция шоу, настройка ComfyUI/Ollama, состав облачного стека и бюджет.
- [characters/guinness/character_bible.txt](characters/guinness/character_bible.txt) — описание кота.
- [characters/marija/character_bible.txt](characters/marija/character_bible.txt) — описание Марии.
- [AI_Tools_Analysis.md](AI_Tools_Analysis.md) — база знаний по AI-инструментам.
