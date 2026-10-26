# ENV-AUDIT — Mary Studio / Mary_Guiness

> **Дата аудита:** 2026-10-26
> **Хост:** MacBook (arm64), macOS 27.0.1 (build 26A434), 18 GiB RAM
> **Репозиторий:** `/Users/vladislavkovalenko/Projects/Mary_Guiness`
> **Назначение:** зафиксировать фактическое окружение до начала WP-01. Только факты и
> команды проверки; секреты не читались и не выводились.

---

## 1. Сводка

| Компонент | Факт | Статус |
|---|---|---|
| macOS | 27.0.1 (26A434), arm64 | OK |
| RAM | 19 327 352 832 байт (18 GiB) | OK |
| Python (системный) | 3.13.1, `/opt/homebrew/bin/python3` | OK |
| Python (venv) | 3.13.1, `.venv/` | OK |
| uv | 0.11.24 | OK |
| Node.js | v26.8.1 | OK |
| git | 2.45.2 установлен; репозиторий **не инициализирован** | WP-00B |
| ffmpeg | 7.1.1 | OK |
| ComfyUI | 0.42.0, commit `0b05cd8a` | установлен, **не запущен** во время аудита |
| comfyui-ltx2-mlx | 0.2.1, commit `d38b63a` | установлен |
| Ollama | сервис на `127.0.0.1:11434` недоступен | не запущен |
| API-формат LTX I2V | отсутствует | WP-00A |
| Тесты | 14 passed, 1 failed | WP-00C |

---

## 2. ОС и железо

```text
$ sw_vers
ProductName:            macOS
ProductVersion:         27.0.1
BuildVersion:           26A434

$ uname -m
arm64

$ sysctl -n hw.memsize
19327352832
```

18 GiB unified memory — соответствует целевому профилю из baseline (MacBook Pro M3, 18 GB).

---

## 3. Python и зависимости

```text
$ python3 --version
Python 3.13.1
$ which python3
/opt/homebrew/bin/python3
$ uv --version
uv 0.11.24 (5e04460c0 2026-06-23 aarch64-apple-darwin)
$ node --version
v26.8.1
$ ffmpeg -version | head -n 1
ffmpeg version 7.1.1 Copyright (c) 2000-2025 the FFmpeg developers
```

`requirements.txt` (legacy, не меняется):

```text
httpx>=0.27.0
python-dotenv>=1.0.0
litellm>=1.40.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
pytest-mock>=3.12.0
```

Фактически установлено в `.venv`:

| Пакет | Версия |
|---|---|
| httpx | 0.28.1 |
| litellm | 1.89.3 |
| pydantic | 2.13.4 |
| pytest | 9.1.1 |
| pytest-asyncio | 1.4.0 |
| pytest-mock | 3.15.1 |
| python-dotenv | 1.2.2 |
| requests | 2.34.2 |

`pytest.ini`: `asyncio_mode = auto`, `testpaths = tests`.

---

## 4. Git

```text
$ git --version
git version 2.45.2
$ git rev-parse --is-inside-work-tree
fatal: not a git repository (or any of the parent directories): .git
```

- git **установлен**, но репозиторий не инициализирован.
- В корне уже есть `.gitignore`:

```text
.venv/
.env
__pycache__/
*.pyc
.pytest_cache/
.DS_Store
```

- `.env` присутствует и не читался. `.env.example` присутствует.
- `git init` в WP-00 **не выполняется** — это WP-00B.

---

## 5. ComfyUI и LTX-2.3 MLX

```text
$ git -C runtime/ComfyUI rev-parse --short HEAD
0b05cd8a
$ git -C runtime/ComfyUI/custom_nodes/comfyui-ltx2-mlx rev-parse --short HEAD
d38b63a
```

| Компонент | Версия | Источник |
|---|---|---|
| ComfyUI | 0.42.0 | `runtime/ComfyUI/comfyui_version.py` |
| comfyui-ltx2-mlx | 0.2.1 | `runtime/ComfyUI/custom_nodes/comfyui-ltx2-mlx/pyproject.toml` |
| Веса примера | `dgrauet/ltx-2.3-mlx-q8` | `comfyui-workflows/ltx23_mlx_q4_test.json` |

Сервисы во время аудита:

```text
$ curl -s -m 3 http://127.0.0.1:8188/system_stats
comfyui: недоступен (HTTP 000)
$ curl -s -m 3 http://127.0.0.1:11434/api/tags
ollama: недоступен (HTTP 000)
```

Вывод: поведение `/prompt`, `/history/{prompt_id}`, `/view`, `/object_info`, `/free`,
`/interrupt` **не проверено** и остаётся **[ПРОВЕРИТЬ]** до WP-00A.

---

## 6. Workflow-файлы

| Файл | Формат | Фактическое содержимое |
|---|---|---|
| `character_pose_gen.api.json` | API | txt2img-референс персонажа |
| `character_pose_openpose.api.json` | API | поза через ControlNet OpenPose |
| `character_pose_ipadapter.api.json` | API | поза через IP-Adapter |
| `scene_draft_ipadapter.api.json` | API | keyframe сцены через IP-Adapter |
| `scene_draft_ltx.api.json` | API | LTX-workflow с `LoadImage` и `FRAMES` |
| `character_pose_gen.json` | метаданные | карта шаблонов |
| `controlnet_pose.json` | метаданные | описание вспомогательного workflow |
| `scene_draft_ltx.json` | метаданные | описание LTX-черновика |
| `workflow_config.json` | конфиг | checkpoint/models для SD/LTX 0.9.8, не для LTX-2.3 MLX |
| `ltx23_mlx_q4_test.json` | UI-граф | пример LTX-2 MLX, **T2V**, см. §7 |

---

## 7. Несовпадение сохранённого LTX workflow с I2V-экспериментами

Файл `comfyui-workflows/ltx23_mlx_q4_test.json`:

| Параметр | Значение в файле | Заявленные эксперименты |
|---|---|---|
| Имя файла | `..._q4_test.json` | Q4 |
| Веса в `LTX2MLXModelLoader` | `dgrauet/ltx-2.3-mlx-q8` | Q4 |
| Режим | T2V: вход `image` не подключён, `LoadImage` отсутствует | I2V из стартового PNG |
| `pipeline_type` | `distilled` | `distilled` |
| `low_ram` | `false` | не зафиксировано |
| Разрешение | 256×256 | 512×512 |
| `num_frames` | 25 | 73 |
| Seed / cfg / fps | 0 / 3.0 / 24.0 | не зафиксировано |

Итог: **сохранённый workflow не является I2V-конфигурацией**. Он не подтверждает ни режим
I2V, ни квантование Q4, ни целевые параметры 512×512/73 кадра. Имя файла (`q4`) противоречит
весам (`q8`).

Следствия:

1. API-формат LTX I2V в репозитории отсутствует.
2. `workflow_config.json` описывает другой стек (SD + LTX 0.9.8, `ComfyUI-LTXVideo`) и для
   LTX-2.3 MLX непригоден.
3. Проверка API-взаимодействия и фиксация реального I2V-графа вынесены в **WP-00A**;
   существующие workflow при этом не изменяются, новый API-файл создаётся отдельно.
4. Параметры 512×512 / 73 кадра / 24 FPS считаются экспериментальным preset до результата
   WP-00A.

---

## 8. Тесты

```text
$ .venv/bin/python -m pytest -q
1 failed, 14 passed in 0.33s
```

Падает `tests/test_pipeline.py::test_character_refs_stage_reports_missing`:

```text
AssertionError: assert True is False
StageResult(..., success=True, message='Все референсы на месте (14 ...')
```

Причина: тест создаёт `Orchestrator()` и только потом подменяет `orch.settings`; этапы
созданы в `Orchestrator.__init__` со старыми настройками и указывают на реальный каталог
`characters/`. Это ограничение внедрения зависимостей, а не ошибка бизнес-логики.
Исправление — только в WP-00C, без изменения production-кода.

---

## 9. Размеры каталогов

```text
$ du -sh . runtime .venv characters episodes
2.5G    .
2.3G    runtime
188M    .venv
9.1M    characters
2.9M    episodes
```

`runtime/` (ComfyUI и модели) и `.venv/` не должны попадать в Git. Пользовательские
`characters/`, `episodes/`, `comfyui-workflows/`, `prompts/` не перемещаются и не удаляются.

---

## 10. Что не проверено и кем проверяется

| Пункт | Почему | Где проверить |
|---|---|---|
| Поведение ComfyUI API (`/prompt`, `/history`, `/view`, `/free`, `/interrupt`) | сервис не запущен | WP-00A |
| Наличие `LTX2MLXGenerate` и `LTX2MLXModelLoader` через `/object_info` | сервис не запущен | WP-00A |
| Реальная поддержка I2V и Q4 | нет API-workflow | WP-00A |
| Фактические 512×512/73 кадра | не подтверждено | WP-00A |
| Версии моделей Ollama | сервис не запущен | WP-00A/WP-01 |
| Поведение ComfyUI при OOM, cancel, рестарте | требует запуска | WP-08 |
| Fillrate/время синхронного композитора | не реализован | WP-05 |
| Наличие `pyproject.toml` для backend | ещё не создан | WP-01 |

---

## 11. Команды аудита (воспроизводимость)

```bash
sw_vers; uname -m; sysctl -n hw.memsize
python3 --version; which python3
ffmpeg -version | head -n 1
git --version; git rev-parse --is-inside-work-tree
uv --version; node --version
.venv/bin/python --version
.venv/bin/pip list
git -C runtime/ComfyUI rev-parse --short HEAD
git -C runtime/ComfyUI/custom_nodes/comfyui-ltx2-mlx rev-parse --short HEAD
curl -s -m 3 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8188/system_stats
curl -s -m 3 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:11434/api/tags
du -sh . runtime .venv characters episodes
.venv/bin/python -m pytest -q
```

Секреты не выводились; содержимое `.env` не читалось.
