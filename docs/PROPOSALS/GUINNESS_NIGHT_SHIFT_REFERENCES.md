# Guinness: Night Shift — аудит референсов (preflight)

> Дата: 2026-11-04. Только чтение: файлы `docs/cats` не изменялись, референсы в БД
> не загружались, approved-ассеты не затрагивались. Метаданные получены `stat`,
> `shasum -a 256`, `ffprobe`; внешний вид проверен визуально по каждому файлу.

---

## 1. Рамки аудита

Проверено 14 файлов каталога `/Users/vladislavkovalenko/Projects/Mary_Guiness/docs/cats`.
Задача — ответить на четыре вопроса: кто на изображении, годится ли файл как
identity reference, годится ли как стартовый кадр I2V, и что мешает.

---

## 2. А. Полный список файлов

| # | Файл | Байт | Формат | Разрешение | SHA-256 |
|---|---|---|---|---|---|
| 1 | `01_vocalist_clean.png` | 707 444 | PNG RGB | 768×820 | `38eb09d07cf33cfbf89c02f6ef8cc8b586cb31cb1eea52cefdde05571bffb445` |
| 2 | `02_guitarist_clean.png` | 761 904 | PNG RGB | 768×820 | `01794bb27431aa801fc4a86ce4fe390dfd8f9c564372e73da968f9b96e677ea2` |
| 3 | `03_drummer_clean.png` | 665 792 | PNG RGB | 768×820 | `4c2c28fefe56483f28883782cf7a6ec9ac0d450b83afa72b401c9a82cacdeeea` |
| 4 | `04_bassist_clean.png` | 731 304 | PNG RGB | 768×820 | `38e7cd01abb8bc745288f1fed0883b3d894aa470c400d647e0bb54378a10c8ed` |
| 5 | `05_keyboardist_clean.png` | 722 493 | PNG RGB | 768×820 | `bee36a7c8a51bf0cffc43069f1a9656b016fd7677abcb79166a7ecb93ce03d78` |
| 6 | `Cat and moon.png` | 430 957 | PNG RGBA | 392×657 | `997b5986b1b61aa3566d35471fb5aeaf9dc89aea750eed7b780fc86f729216bd` |
| 7 | `Cat and no food.png` | 371 643 | PNG RGBA | 392×655 | `2cf6eec6a2b767e5c93f1de8ee909b075869694a3bf22e0544c9f4219f0839d8` |
| 8 | `Cat in bad.png` | 347 044 | PNG RGBA | 396×624 | `0032d2a4bb9c6ced9f8653a0f66e0fd4008f41aed162f8f7101c15bc9b575e5c` |
| 9 | `Cat playing.png` | 362 118 | PNG RGBA | 396×622 | `df718cdc8a22973fa3f2354982a3fb4c8519fd0afa77db70a046c78aae78803d` |
| 10 | `Cat wallking.png` | 315 933 | PNG RGBA | 394×618 | `8b61e4f59149643205b35530fe24d1697bf2868aa5297f647881ee6861cb7b16` |
| 11 | `Cat with cup.png` | 436 853 | PNG RGBA | 392×646 | `cb1c2fd3348d9150591cd7d6f6f8b225168634d2fd981075d0ce0d378193f3b3` |
| 12 | `Chocolate Burmese Cat Portrait.png` | 2 248 916 | PNG RGB | 1064×1479 | `f7ec5d84a935d06460909d728c458b8a68474c93aca2757a611ed24505891809` |
| 13 | `Feline Rock Band Under Neon Lights.png` | 2 614 008 | PNG RGB | 1536×1024 | `a64e8ba1d1e30d5ec0a815046460fcc32aa7732d6d33e37a1a98c14468ae7341` |
| 14 | `Regal Burmese Cat on Velvet Sofa.png` | 2 297 808 | PNG RGB | 941×1672 | `e197e3ec60dbcadad92a710d7afbca0501365a867c2c85663a68d846451dbfc9` |

---

## 3. B. Персонаж, назначение, пригодность

| # | Персонаж | Назначение | Многоракурсный лист | Текст / подписи | I2V |
|---|---|---|---|---|---|
| 1–5 | Участники группы NLB (кот-вокалист, гитарист, барабанщик, басист, клавишник) — **не Guinness** | Карточки персонажей другого проекта | нет (по одному коту, студийный фон) | нет | не для GNS |
| 6 | Guinness | GNS-01, кот у окна с луной и городом | нет | нет | да |
| 7 | Guinness | Кот у миски с едой; для пяти сцен не нужен | нет | нет | резерв |
| 8 | Guinness | Кот на кровати рядом со спящими хозяевами, луна в окне | нет | нет | альтернатива GNS-01 |
| 9 | Guinness | GNS-02, лапа на фантике, деревянный пол | нет | нет | да |
| 10 | Guinness | GNS-03, коридор, кот идёт/бежит на камеру | нет | нет | да |
| 11 | Guinness | GNS-04, лапа на керамической чашке, кухня | нет | нет | да |
| 12 | Guinness | **Identity reference** (студийный портрет на белом) | нет | нет | нет — фон не интерьерный |
| 13 | Ансамбль NLB на сцене (широкий план) | Широкий кадр NLB-28…30 | нет | нет | не для GNS |
| 14 | Guinness | GNS-05, кот на тёмно-бирюзовом велюровом диване, тёплая лампа | нет | нет | да |

Проверка identity-кандидата: файл существует, 1064×1479 PNG RGB, sha256
`f7ec5d84…` **совпадает** с approved-ассетом `6f999c54-2f80-46d8-9155-21cc375c4008`
(`role=guinness_identity`, проект `a7a6629e…`). Визуально: соболиный бурманский кот,
шоколадная маска и уши, тёмный хвост, тёплый коричневый корпус, жёлто-зелёные глаза,
естественная анатомия, белый фон, без текста и коллажа. Соответствует описанию
Guinness в задании. **Не изменяется и не используется как интерьерный стартовый кадр.**

### 3.1 Соответствие пяти сценам

| Сцена | Стартовый кадр | Файл | Статус в NLB | Нужен свой ассет в GNS |
|---|---|---|---|---|
| GNS-01 | кот у окна, луна, город | `Cat and moon.png` | `nlb_26_start`, approved | да — новая запись в новом проекте |
| GNS-02 | фантик на полу | `Cat playing.png` | `nlb_22_start`, approved | да |
| GNS-03 | коридор | `Cat wallking.png` | `nlb_23_start`, approved | да |
| GNS-04 | керамическая чашка | `Cat with cup.png` | `nlb_24_start`, approved | да |
| GNS-05 | велюровый диван | `Regal Burmese Cat on Velvet Sofa.png` | `nlb_25_start`, approved | да |

Резерв: `Cat in bad.png` (`nlb_21_start`) — сцена «хозяева уснули» со спящими людьми;
`Cat and no food.png` (`nlb_27_start`) — миска. Для GNS не требуются.

Все семь интерьерных кадров уже проходили полный путь `keyframe → promote-keyframe`
и успешно рендерились в NLB, включая RGBA-исходники, — это подтверждает пригодность
формата, но не отменяет требований к качеству конкретной сцены.

---

## 4. C. Пять start-frame specifications

Общие требования: один кот, ночь, фиксированная камера, без текста и водяных знаков,
без второго кота и людей, фон — квартира (не студия), вертикальная композиция с
запасом по краям. LTX сам приводит кадр к 576×1024 (масштаб по высоте + центральный
кроп по ширине); предварительная обрезка не требуется.

| Сцена | Роль ассета | Файл | Исходник | Приведение к 576×1024 | Срез по бокам |
|---|---|---|---|---|---|
| GNS-01 | `gns_01_start` | `Cat and moon.png` | 392×657 | ×1,558 → 611×1024 | 35 px (2,9 % с каждой стороны) |
| GNS-02 | `gns_02_start` | `Cat playing.png` | 396×622 | ×1,646 → 652×1024 | 76 px (5,8 %) |
| GNS-03 | `gns_03_start` | `Cat wallking.png` | 394×618 | ×1,657 → 653×1024 | 77 px (5,9 %) |
| GNS-04 | `gns_04_start` | `Cat with cup.png` | 392×646 | ×1,585 → 621×1024 | 45 px (3,6 %) |
| GNS-05 | `gns_05_start` | `Regal Burmese Cat on Velvet Sofa.png` | 941×1672 | ×0,613 → 576×1024 | ~0 px (0,1 %) |

### 4.1 Проверка содержания по сценам

| Сцена | Что в кадре сейчас | Чего не хватает / риск |
|---|---|---|
| GNS-01 | кот сидит у окна, смотрит вверх на луну; шторы, город, растение | взгляд направлен мимо камеры — поворот головы должен дать промпт, а не кадр |
| GNS-02 | кот с занесённой лапой над фантиком на лакированном полу | лапа уже в контакте: «tap once» может не прочитаться |
| GNS-03 | кот идёт на камеру по тёмному коридору, тёплый свет из дальней двери | поза шага, а промпт требует бег — риск, что модель продолжит шаг |
| GNS-04 | кот тянется лапой к керамической чашке на деревянном столе | лапа уже на чашке: «extends paw» может не прочитаться |
| GNS-05 | кот лежит на бирюзовом велюре, голова поднята, тёплая лампа слева | голова уже поднята: «raises head» — статичная фаза |

### 4.2 Что должно быть на кадре (контракт сцены)

1. **GNS-01.** Кот в профиль/три четверти у окна, морда освещена луной, город —
   мягкое боке; вторая половина кадра — тёмная комната.
2. **GNS-02.** Верхняя точка/уровень пола, фантик в нижней трети, лапа в кадре;
   блики на лакированном полу.
3. **GNS-03.** Низкая камера в коридоре, перспектива сходится к двери, кот в центре.
4. **GNS-04.** Уровень стола, чашка справа от кота, тёплый свет лампы.
5. **GNS-05.** Кот на диване, велюр тёмно-бирюзовый, лампа в кадре, вечерняя комната.

### 4.3 Fallback: production-ready промпты для внешней генерации кадра

Системной генерации изображений нет (SDXL/IPAdapter в ComfyUI отсутствуют, planner
не создаёт картинки). Промпты ниже — на случай, если человек решит заменить кадр
внешним инструментом; они не запускались.

```text
GNS-01: photorealistic cinematic still, vertical 9:16, sable Burmese cat sitting by a
large apartment window at night, moonlight and distant city bokeh outside, sheer
curtain, plant silhouette, warm dim interior, cat seen in three-quarter profile,
soft rim light, shallow depth of field, 35mm lens, no text, single cat.

GNS-02: photorealistic cinematic still, vertical 9:16, low camera on a dark wooden
floor of a night apartment, sable Burmese cat reaching one front paw toward a small
shiny candy wrapper, warm lamp light from the side, glossy reflections, no text,
single cat.

GNS-03: photorealistic cinematic still, vertical 9:16, low camera in a dim apartment
corridor at night, sable Burmese cat mid-stride toward the camera, moonlight and warm
door light, long perspective, subtle film grain, no text, single cat.

GNS-04: photorealistic cinematic still, vertical 9:16, night kitchen table, ceramic
speckled cup next to a sable Burmese cat, cat's paw resting near the cup, warm lamp,
soft shadows, shallow depth of field, no text, single cat.

GNS-05: photorealistic cinematic still, vertical 9:16, sable Burmese cat lying on a
dark teal velvet sofa, warm table lamp, cozy night living room, cat looking toward
camera, soft highlights on velvet, no text, single cat.
```

---

## 5. Правила загрузки (к исполнению после разрешения)

1. Файлы подаются как есть: `POST /api/projects/{project_id}/references?kind=uploaded&role=gns_0X_start`
   (сырое тело, PNG/JPEG). Сервер сам считает sha256 и создаёт `draft`-ассет.
2. Identity: `role=guinness_identity`, тот же файл `Chocolate Burmese Cat Portrait.png`.
3. Approve делает человек: `POST /api/reference-assets/{id}/approve`. После approve
   запись неизменяема (S15) — роль и файл больше не правятся.
4. Стартовый кадр шота: `POST /api/shots/{shot_id}/keyframe {"reference_asset_id": "…"}`
   → `POST /api/shots/{shot_id}/attempts/{attempt_id}/promote-keyframe`.
   Прямая запись `start_frame_artifact_id` запрещена (S9).
5. Дедупликация — по sha256 **внутри проекта**, поэтому те же файлы в новом проекте
   создают новые записи и не затрагивают approved-ассеты NLB.

---

## 6. Ограничения и риски

| Риск | Влияние | Что делаем |
|---|---|---|
| Исходники 392–396 px по ширине → апскейл 1,56–1,66× до 576 | мягкость деталей, «мыло» на шерсти | принимаем как потолок качества; альтернатива — новые кадры внешним инструментом с разрешением ≥576 по ширине |
| Срез 2,9–5,9 % с каждой стороны | может подрезать уши/хвост | кадры уже проверены в NLB; на ревью смотреть края |
| RGBA-исходники (5 интерьерных кадров) | композитинг/прозрачность | альфа игнорируется пайплайном (подтверждено рендерами NLB) |
| Identity-портрет на белом фоне | не интерьерный кадр | только identity reference, не start frame |
| Позы не совпадают с началом действия (GNS-02/03/04/05) | слабая читаемость движения | варианты промптов — PRODUCTION_PLAN §4.1, решение человека |
| Многоракурсные листы | запрещены как вход I2V | в каталоге таких листов для Guinness нет |
| Файлы принадлежат разным персонажам | риск подмены | пять `0X_*_clean.png` и `Feline Rock Band…` исключены из GNS |
