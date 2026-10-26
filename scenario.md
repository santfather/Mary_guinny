# Marija + Guinness — AI Video Show

> Анимационное шоу с мультяшными персонажами. Полный локально-облачный пайплайн.

---

## 🗂 Структура проекта

```
~/Projects/cat-show/
│
├── 📁 characters/              ← Библиотека персонажей
│   ├── 📁 guinness/
│   │   ├── reference_front.png
│   │   ├── reference_side.png
│   │   ├── reference_3q.png
│   │   ├── reference_sit.png
│   │   ├── reference_walk.png
│   │   ├── reference_surprised.png
│   │   ├── reference_sleep.png
│   │   └── character_bible.txt
│   └── 📁 marija/
│       ├── reference_front.png
│       ├── reference_side.png
│       ├── reference_3q.png
│       ├── reference_sit.png
│       ├── reference_walk.png
│       └── character_bible.txt
│
├── 📁 episodes/
│   └── 📁 ep01/
│       ├── script.txt               ← Сценарий (из Ollama)
│       ├── 📁 scenes/
│       │   ├── scene_01_draft.mp4   ← Черновик (ComfyUI)
│       │   ├── scene_01_final.mp4   ← Финал (Grok / Kling)
│       │   └── scene_01_lipsync.mp4 ← После Hedra
│       ├── 📁 audio/
│       │   ├── guinness_line_01.mp3
│       │   ├── marija_line_01.mp3
│       │   └── bg_music.mp3
│       └── ep01_final.mp4
│
├── 📁 comfyui-workflows/
│   ├── character_pose_gen.json
│   ├── scene_draft_ltx.json
│   └── controlnet_pose.json
│
├── 📁 prompts/
│   ├── Modelfile_CatShow
│   ├── grok_video_template.txt
│   └── elevenlabs_voice_notes.txt
│
└── 📁 exports/                  ← Готовые эпизоды
```

---

## 🔧 Установка (уже есть: Pinokio, Ollama, ComfyUI)

### ComfyUI — кастомные ноды через Manager

|Нода|Назначение|Репозиторий|
|---|---|---|
|`ComfyUI_IPAdapter_plus`|Фиксация внешности персонажа через референс-фото|`github.com/cubiq/ComfyUI_IPAdapter_plus`|
|`ComfyUI-ControlNet-Aux`|Извлечение скелета позы из фото/видео|`github.com/Fannovel16/comfyui_controlnet_aux`|
|`ComfyUI-VideoHelperSuite`|Загрузка и сохранение видео внутри воркфлоу|`github.com/Kosinkadink/ComfyUI-VideoHelperSuite`|
|`ComfyUI-AnimateDiff-Evolved`|Анимация последовательности кадров|`github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved`|

### ComfyUI — модели (скачать вручную)

```
ComfyUI/models/checkpoints/
└── dreamshaper_8.safetensors       ← универсальная, хороша для иллюстраций
    или
└── ghostmix_v2.safetensors         ← аниме/мультяшный стиль

ComfyUI/models/ipadapter/
├── ip-adapter-plus-face_sdxl_vit-h.safetensors   ← фиксация лица
└── ip-adapter-plus_sdxl_vit-h.safetensors        ← фиксация общего стиля

ComfyUI/models/controlnet/
├── control_v11p_sd15_openpose.pth           ← позы для SD 1.5
└── controlnet-openpose-sdxl.safetensors     ← позы для SDXL
```

### InsightFace (нужен для FaceID)

```bash
# В терминале окружения ComfyUI
pip install insightface
pip install onnxruntime-silicon   # для Mac M3 — ускорение через Neural Engine
```

### Ollama — модель для сценариев

```bash
ollama pull llama3.1:8b
```

---

## 🐱 Character Bible

### Гиннесс (кот)

```
Стиль:             2D мультфильм, мягкие линии, пастельные цвета
Окрас:             рыжий с белыми пятнами на груди и лапах
Глаза:             зелёные, немного прищуренные
Телосложение:      пухлый, округлый, короткие лапы
Характерная деталь: всегда чуть-чуть недовольное выражение
Ошейник:           синий с серебряной бляшкой
Голос (ElevenLabs): низкий, ленивый, чуть хриплый
Характер:          ленивый, саркастичный, любит еду и сон.
                   Говорит короткими фразами, иногда философски.
```

### Мария (хозяйка)

```
Стиль:             2D мультфильм, тот же арт-стиль что и кот
Волосы:            каштановые, собраны в хвост
Одежда дома:       жёлтая толстовка, джинсы
Глаза:             карие, широко открытые
Характерная деталь: всегда с телефоном или кружкой кофе
Голос (ElevenLabs): живой, энергичный, немного рассеянный
Характер:          энергичная, заботливая, слегка рассеянная.
                   Всегда придумывает планы, которые кот игнорирует.
```

### Библиотека поз (генерировать один раз для каждого)

- [ ] `reference_front.png` — анфас, нейтральная поза
- [ ] `reference_side.png` — профиль
- [ ] `reference_3q.png` — 3/4 поворот (самый универсальный)
- [ ] `reference_sit.png` — сидит
- [ ] `reference_walk.png` — идёт
- [ ] `reference_surprised.png` — удивлён
- [ ] `reference_sleep.png` — спит (для кота особенно важно)

> **Совет по IP-Adapter:** вес 0.7–0.8 — оптимум. При 1.0 картинка становится жёсткой, при 0.5 персонаж теряет сходство.

---

## 🤖 Ollama — настройка сценарного агента

Создать файл `~/Projects/cat-show/prompts/Modelfile_CatShow`:

```
FROM llama3.1:8b

SYSTEM """
Ты — сценарист короткого анимационного шоу.

Главные герои:
- ГИННЕСС (кот): ленивый, саркастичный, любит еду и сон.
  Говорит короткими фразами, иногда философски.
- МАРИЯ (хозяйка): энергичная, заботливая, слегка рассеянная.
  Всегда придумывает планы, которые кот игнорирует.

Формат каждой сцены:
СЦЕНА [номер]: [краткое описание действия]
ГИННЕСС: [реплика]
МАРИЯ: [реплика]
ДЕЙСТВИЕ: [что происходит визуально]

Длина эпизода: 3–5 сцен, каждая 5–10 секунд.
"""

PARAMETER temperature 0.8
```

Зарегистрировать и запустить:

```bash
ollama create catshow -f ~/Projects/cat-show/prompts/Modelfile_CatShow
ollama run catshow "Напиши эпизод про то, как Гиннесс не даёт Марии работать"
```

---

## 🎬 Пайплайн — 7 этапов

### Этап 1 — Черновик сцены (локально, ComfyUI)

```
Ollama → сценарий
    ↓
ComfyUI — воркфлоу scene_draft_ltx.json
    ├── Промпт сцены
    ├── IP-Adapter ← reference_front.png персонажа
    └── ControlNet OpenPose ← поза из библиотеки
    ↓
Черновик .mp4 (5–15 мин)
    ↓
Итерация промпта → переход в облако
```

### Этап 2 — Библиотека персонажей (локально, разово)

```
ComfyUI — воркфлоу character_pose_gen.json
    ├── SDXL checkpoint (dreamshaper / ghostmix)
    ├── IP-Adapter Plus Face (вес 0.7–0.8)
    └── ControlNet OpenPose (7 поз × 2 персонажа)
    ↓
14 референсных изображений → папки characters/
```

### Этап 3 — Финальное видео (облако)

|Инструмент|Роль|Цена/мес|
|---|---|---|
|**Grok Imagine 1.5**|Основной · Reference-to-Video · мультяшный стиль · 720p · ~30 сек/клип|$30 (SuperGrok)|
|**Kling AI Standard**|Резерв · 1080p · сложные движения|$7|

**Шаблон промпта для Grok** (`grok_video_template.txt`):

```
Character reference: [описание из character_bible.txt]
Keep the character's face, fur pattern, collar and overall 
appearance consistent. 
[описание сцены и движения]
Animated cartoon style, 2D illustration, soft lines, 
pastel colors, consistent lighting throughout.
```

### Этап 4 — Голоса (ElevenLabs)

- Создать клонированный голос для Марии
- Создать уникальный голос для Гиннесса (низкий, ленивый)
- Экспорт каждой реплики отдельным `.mp3`

|Тариф|Лимит|Цена|
|---|---|---|
|Free|10 мин/мес|$0|
|Starter|30 мин/мес|$5|

### Этап 5 — Lip Sync (Hedra + Sync.so)

|Инструмент|Роль|Лимит|Цена|
|---|---|---|---|
|**Hedra Character-3**|Основной · анимирует животных · принимает аудио ElevenLabs|Free: 100 кр (вотермарк) · Basic: 1500 кр|$15|
|**Sync.so**|Резерв · максимальная точность синхронизации|Free tier|$5|

> Hedra: 6 кредитов/сек → Basic (1500 кр) = ~250 секунд готового lip sync в месяц

### Этап 6 — Музыка

|Инструмент|Роль|Цена|
|---|---|---|
|**Suno**|Фирменная тема шоу + ситуативные треки|Free: 10 кр/день · Standard $10/мес|
|**Mubert**|Royalty-free фоновые петли под настроение|Free|

### Этап 7 — Финальная сборка (локально)

**DaVinci Resolve** или CapCut:

- Видео (из Hedra) + голоса (ElevenLabs) + музыка (Suno/Mubert)
- Субтитры → экспорт

---

## 💰 Стоимость в месяц

|Инструмент|Тариф|Цена|
|---|---|---|
|ComfyUI + LTX-Video|Локально|$0|
|Ollama (llama3.1:8b)|Локально|$0|
|DaVinci Resolve|Локально|$0|
|Mubert|Free|$0|
|**Grok Imagine 1.5**|SuperGrok|**$30**|
|**Hedra Basic**|1500 кр/мес|**$15**|
|**Suno Standard**|~50 треков/мес|**$10**|
|**ElevenLabs Starter**|30 мин/мес|**$5**|
|**Kling AI Standard**|Резерв · опционально|**$7**|
||||
|**Рабочий минимум**|Grok + ElevenLabs + Hedra|**$50/мес**|
|**Полный стек**|Все инструменты|**$67/мес**|
|**Старт (free-tier)**|Всё на бесплатных лимитах|**$0/мес**|

---

## ✅ Чеклист запуска

### Установка (один раз)

- [ ] Установить кастомные ноды в ComfyUI через Manager (4 штуки)
- [ ] Скачать модели checkpoints, ipadapter, controlnet
- [ ] Установить `insightface` и `onnxruntime-silicon`
- [ ] Создать Modelfile в Ollama → `ollama create catshow`

### Библиотека персонажей (один раз, ~2–3 часа)

- [ ] Сгенерировать 7 поз Гиннесса в ComfyUI
- [ ] Сгенерировать 7 поз Марии в ComfyUI
- [ ] Написать character_bible.txt для каждого
- [ ] Создать голос Гиннесса в ElevenLabs
- [ ] Создать голос Марии в ElevenLabs (клон или уникальный)
- [ ] Сочинить фирменную тему шоу в Suno

### Первый эпизод

- [ ] Ollama → сценарий ep01
- [ ] ComfyUI → черновики сцен
- [ ] Grok / Kling → финальные клипы
- [ ] ElevenLabs → аудио реплик
- [ ] Hedra → lip sync
- [ ] DaVinci Resolve → финальная сборка

---

## 🔗 Ссылки

- [ComfyUI Manager](https://github.com/ltdrdata/ComfyUI-Manager)
- [IP-Adapter Plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus)
- [Hedra](https://hedra.com/)
- [Grok Imagine](https://x.ai/grok)
- [ElevenLabs](https://elevenlabs.io/)
- [Suno](https://suno.com/)
- [Kling AI](https://kling.ai/)
- [Sync.so](https://sync.so/)
- [Civitai (модели)](https://civitai.com/)
- [HuggingFace (модели)](https://huggingface.co/)