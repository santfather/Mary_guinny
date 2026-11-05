# `viseme_frame_blend_v1` — анимация рта из набора готовых кадров морды

Статус: **предложение + реализованная инфраструктура, живая приёмка заблокирована**.
Дата: 2026-11-05. Work package: WP-VOICE-06 Revised.

Замена «нарисованной маски» (`pillow_mouth_v2`) на сборку кадров из **пяти
согласованных изображений морды** Гиннесса. Старый движок `mouth_animation_mvp`
остаётся в коде как legacy/fallback и не удаляется (§1 задания).

---

## 1. Что показал аудит

| Элемент | Состояние | Вывод для нового движка |
|---|---|---|
| `backend/app/mouth_animation.py` | 416 строк, `pillow_mouth_v2`, маска `CAVITY_COLOR` поверх патча | fallback; переиспользуются `MouthRegion`, `decode_source_image`, FFmpeg-конвейер |
| `backend/app/shot_audio.py` | рабочая PCM 48 кГц mono, огибающая 50 Гц, `speech_segments`/`silence_segments` | паузы для принудительного закрытия рта |
| `mouth_calibrations` | геометрия области рта, ровно один источник (референс XOR keyframe) | остаётся «областью морды» и для нового движка |
| `backend/app/lipsync.py` | `SELECTED_ENGINE = None`, 409 без записей (DECISIONS §4.15) | не трогаем; виземный движок — отдельный путь |
| `Artifact` / `RenderAttempt` / `Job` | `source='attempt'`, `kind='talking_preview'`, `mime='video/mp4'` | контракт не меняется |
| review | `POST /api/shots/{id}/attempts/{aid}/approve\|reject` | автоматического утверждения нет |
| storage | content-addressed blob, `reference_assets(project_id, sha256)` UNIQUE | 5 разных PNG сосуществуют без миграций |
| `reference_assets.role` | свободная строка (64), без CHECK | роль `viseme_<state>` допустима без миграции |

**Блокер:** у GNS-05 (`6532e96d-…`) нет ни одного изображения с формой рта.
Референсы шота: `gns_05_start` (approved, 941×1672), `guinness_identity` (draft),
`shot_audio` (approved). Поиск по `docs/` и `storage/` не дал ни одного viseme-кадра.
Живая сборка GNS-05 поэтому **не запускалась** (§8 задания).

---

## 2. Модель хранения набора (без миграций)

Набор — это пять записей `reference_assets` + привязки `shot_references`:

```
kind        = 'uploaded'
role        = 'viseme_closed' | 'viseme_small_open' | 'viseme_medium_open'
              | 'viseme_wide_open' | 'viseme_rounded'
status      = 'draft' → 'approved' (только человек)
metadata    = {
  "viseme_set": true,
  "viseme_state": "closed",
  "source": "upload",
  "has_alpha": false,
  "source_reference_asset_id": "<approved-кадр, с которого сделан вариант>"
}
shot_references.purpose = 'other'
```

Почему без миграций:

- `role` не имеет CHECK-ограничения, длина 18 символов < 64;
- `metadata_json` — JSONB, свободная схема;
- дедуп `UNIQUE(project_id, sha256)` безопасен: пять вариантов — пять разных файлов;
- approved-записи неизменяемы (S15), поэтому набор после утверждения стабилен;
- `shot_references.purpose` уже допускает `'other'`.

Ограничение: один набор на шот. Второй набор = конфликт ролей; вводить версии
набора в этом WP не требуется (см. §9, открытый вопрос).

---

## 3. Требования к viseme-ассетам (что именно нужно от человека)

Один и тот же кадр Гиннесса, пять форм рта. Файлы **PNG** (JPEG допустим, но PNG
предпочтителен: без потерь и без артефактов на шерсти).

| Состояние | Роль | Форма рта |
|---|---|---|
| `closed` | `viseme_closed` | губы сомкнуты, как в approved-кадре |
| `small_open` | `viseme_small_open` | щель 2–4 % высоты головы |
| `medium_open` | `viseme_medium_open` | раскрытие примерно вдвое больше |
| `wide_open` | `viseme_wide_open` | широкое раскрытие, видна пасть |
| `rounded` | `viseme_rounded` | губы вытянуты в «о», для О/У |

Обязательные условия (иначе проверка совместимости заблокирует генерацию):

1. **Разрешение** — ровно как у approved-источника: 941×1672 для `gns_05_start`
   (или кратно, но тогда все пять одинаково и без интерполяции не обойтись).
2. **Один кадр, один ракурс.** Голова не поворачивается и не наклоняется: сдвиг
   морды между вариантами ≤ 1 % короткой стороны.
3. **Глаза, нос, усы, уши, фон** — попиксельно те же, что в источнике
   (допуск по площади изменений вне области морды — 1 %).
4. **Освещение и текстура шерсти** не меняются: никакого «перерисованного» кадра.
5. **Меняется только область морды** — прямоугольник калибровки плюс 4 % запаса.
6. `closed` совпадает с approved-кадром в области морды (это опорный кадр).
7. Approve каждого варианта делает человек; approved-источник не перезаписывается.

Способ подготовки (вне системы, без автогенерации): ручная правка одного кадра в
графическом редакторе слоями — отдельный слой «пасть» на пять состояний, экспорт
пяти PNG с неизменными остальными слоями. Автоматическая генерация изображений в
рамках WP не выполнялась и не разрешена (§3 задания).

---

## 4. Интерфейс импорта

`POST /api/shots/{shot_id}/viseme-set/{state}` — сырое тело `image/png|jpeg`,
лимит `MARY_VISEME_UPLOAD_MAX_BYTES` (32 МиБ):

- 422 `viseme_image_invalid` — не PNG/JPEG или > `reference_max_pixels`;
- 409 `duplicate_reference` — этот sha256 уже занят другим состоянием/набором;
- 200 — тот же файл уже импортирован для этого состояния (идемпотентно);
- 201 — создан draft-ассет, привязан к шоту (`purpose='other'`).

`GET /api/shots/{shot_id}/viseme-set` — состав набора + готовность + отчёт
совместимости.

`GET /api/shots/{shot_id}/viseme-set/preview` — PNG-лист сравнения: источник и
пять вариантов в одном масштабе, с рамкой области морды (`Cache-Control: no-store`).

---

## 5. Проверка совместимости

`backend/app/viseme_assets.py::check_compatibility(source, variants, region)`.
Всё детерминированно, только PIL, без numpy.

| Проверка | Метрика | Блокирующий код |
|---|---|---|
| Разрешение | `width`/`height` каждого варианта | `viseme_resolution_mismatch` |
| Сдвиг головы | поиск минимума различий по сетке сдвигов ±6 px | `viseme_head_shift` |
| Изменения вне морды | доля пикселей с дельтой > 12 вне области | `viseme_outside_mouth_changes` |
| `closed` ≠ источник | доля изменений внутри области | `viseme_closed_mismatch` |
| Открытые варианты без артикуляции | доля изменений внутри области | `viseme_no_articulation` |
| Мерцание между вариантами | максимум попарных изменений вне области | `viseme_flicker_risk` |
| Неполный набор | отсутствующие состояния | `viseme_set_incomplete` |
| Не утверждено человеком | статус любого варианта | `viseme_set_not_approved` |

Генерация при любом блокере не начинается: `POST …/mouth-animation` возвращает
409 с кодом и списком причин. Пустая попытка и job не создаются.

---

## 6. Движок `viseme_frame_blend_v1`

Вход: approved-источник, пять approved-вариантов, рабочая WAV-копия, viseme timing
JSON, конфигурация (`fps`, `blend_ms`, `max_change_rate`).

1. **Тайминги** (`VisemeSpan`: `start`, `end`, `viseme`) валидируются: монотонность,
   границы `0 ≤ start < end ≤ duration`, допустимые состояния, минимум одно
   закрытие в паузах.
2. **Паузы** из `shot_audio` (`silence_segments`) принудительно переводят рот в
   `closed`, даже если тайминг говорит иное (`close_in_silence=True`).
3. **Веса кадров**: на кадр выбирается активный визем; на границе — кросс-фейд
   `blend_ms`; затем однополюсное ограничение скорости (`max_change_rate`,
   по умолчанию 12 изменений/с), чтобы артикуляция не дёргалась.
4. **Сборка кадра**: патч области морды (калибровка + 4 % запаса) смешивается из
   двух изображений по весам; остальные пиксели берутся из источника байт-в-байт.
   Нарисованная маска и заливка «пасти» не используются.
5. **Кодирование**: тот же FFmpeg-конвейер, что у MVP: `rawvideo/rgb24` →
   `libx264 -crf 20 -pix_fmt yuv420p` + `aac 192k`, звук — исходная дорожка
   (`apad -t frames/fps`), `+faststart`.
6. **Результат**: `Job(kind='mouth_animation')`, `RenderAttempt(kind='video',
   workflow_version='viseme_frame_blend_v1')`, `Artifact(kind='talking_preview')`.
   В `parameters` — набор (`state → sha256`), тайминги, конфигурация, `region`,
   аудио, исходник.

Первый режим — только Image Talking. Video Talking по-прежнему 409
`video_talking_not_supported`.

---

## 7. Rhubarb 1.14.0

Лицензия MIT (проверено по `LICENSE.md`), бинарник macOS arm64, CPU-only.
**Не скачан и не будет скачан без разрешения.**

`backend/app/rhubarb.py`:

- `find_binary()` — только `~/.mary-studio/tools/rhubarb-1.14.0/rhubarb` или
  `MARY_RHUBARB_BINARY`; ничего не ищет в сети;
- `verify_binary()` — Mach-O arm64 через `file`, sha256 файла против
  `MARY_RHUBARB_SHA256`; пустая настройка = `rhubarb_sha256_not_pinned` → блок;
- `parse_output()` — JSON Rhubarb (`mouthCues`) → `VisemeSpan`;
- `A/B/C/D/E/F/G/H/X` → `closed/small_open/medium_open/wide_open/rounded`
  (G → `small_open`, H → `medium_open`, X → `closed`) — **пометка [ПРОВЕРИТЬ]**
  на живом прогоне;
- `check_pauses()` — сверка виземных пауз с `silence_segments` записи;
- `python -m app.rhubarb_check` — статус без запуска рендера;
- `GET /api/rhubarb/status` — read-only статус для UI.

Пока SHA-256 релиза не запинен человеком, автотайминг через Rhubarb недоступен:
UI принимает **готовый timing JSON** (или тайминги, снятые вручную), движок
работает без Rhubarb.

---

## 8. Тесты

- `backend/tests/test_viseme_blend.py` — веса/паузы/ограничение скорости,
  сборка MP4 (h264 + aac), проверка совместимости (все блокеры), API импорта,
  полный проход до reviewable попытки.
- Существующие `test_mouth_animation.py` (legacy) не меняются.
- `alembic check` — миграций нет.

---

## 9. Ограничения и открытые вопросы

- Живая приёмка GNS-05 невозможна без пяти изображений (§3).
- Один набор на шот; версионирование наборов не вводится.
- Глаза/уши/фон не анализируются семантически: проверка статистическая
  (площадь и сдвиг), «перерисованный» кадр она поймает, но не объяснит анатомию.
- Rhubarb не установлен: `phonetic`-распознавание русского не проверено живьём.
- Порог `max_change_rate` и `blend_ms` подбираются на живой записи после
  получения ассетов.
