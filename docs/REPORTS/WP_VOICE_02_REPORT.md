# WP-VOICE-02 — Universal Audio Import & Talking Character MVP

> Дата: 2026-11-04. Режим: без GPU, без LTX, без ComfyUI, без TTS и облачных API,
> без тяжёлых ML-моделей, без commit/push. NLB и утверждённые ассеты не менялись.
> Основание: `docs/PROPOSALS/WP_VOICE_02_MOUTH_ANIMATION.md` (согласован),
> `docs/DECISIONS.md` §3.9 (S20), §4.18, §4.19.

---

## 1. Статус

**готово** — реализация, миграция, API, UI и тесты; проверки зелёные.

Оговорки, не влияющие на статус:

- живая проверка интерфейса не выполнялась: API на `127.0.0.1:8000` — процесс,
  запущенный до WP, в его `openapi.json` нет новых маршрутов (см. §8);
- контрольный результат GNS-05 остаётся заблокированным по данным, а не по коду:
  исходный референс шота — `draft`, записи нет, калибровки нет (см. §9).

## 2. Что сделано

### 2.1. Аудит и переиспользование

Просмотрены `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`,
`docs/OPEN_QUESTIONS.md`, `docs/REPORTS/WP_QUALITY_06_REPORT.md`,
`backend/app/lipsync.py`, а также существующие audio/artifact/job/render/review
компоненты (`app/api/reference_assets.py`, `app/api/worker.py`, `app/api/jobs.py`,
`app/api/shots.py`, `app/assembly.py`, `app/storage.py`, `app/video_probe.py`,
`app/models.py`, `ui/src/pages/ShotDetailPage.tsx`).

Переиспользовано без дублирования:

| Механизм | Как использован |
|---|---|
| `reference_assets` | запись — `kind='uploaded'`, `role='shot_audio'`, `metadata` JSONB |
| `shot_references` | привязка записи к шоту, `purpose='other'` (enum не расширялся) |
| `BlobStore` | оригинал и рабочая WAV-копия — content-addressed блобы |
| `jobs` / `render_attempts` / `artifacts` | `Job(kind='mouth_animation')`, `RenderAttempt(kind='video')`, `Artifact(source='attempt')` |
| review | существующие `approve`/`reject` референса и попытки, без новых писателей |
| FFmpeg / ffprobe | вся обработка аудио и сборка MP4 |
| `app/api/shots.py`, `app/deps.py` | `require_shot`, `shot_project_id`, `get_session`, `get_store` |

Отчёт `docs/REPORTS/WP_QUALITY_07_REPORT.md` в репозитории отсутствует (есть только
`WP_QUALITY_06_REPORT.md`, `WP_THERMAL_03_REPORT.md`, `WP_THERMAL_03_TEST_RESULTS.md`) —
аудит опирался на WP-QUALITY-06 и `docs/OPEN_QUESTIONS.md`.

### 2.2. Миграция `0011_mouth_calibrations`

Новая таблица `mouth_calibrations` (S20): нормализованные координаты области рта
(0…1), `rotation`, `max_open`, `sensitivity`, `smoothing`, XOR «референс | стартовый
кадр», CHECK границ области и диапазонов, два частичных уникальных индекса на пару
«шот + источник». Approved-записи только читаются: триггеры S15 не ослаблены,
история калибровки не ведётся (upsert, как в §3.9 DECISIONS).

### 2.3. Импорт и подготовка аудио

`backend/app/shot_audio.py`:

- `probe_audio_details` — ffprobe: `format_name`, `codec`, `sample_rate`, `channels`,
  `duration`, наличие аудиопотока;
- `write_work_wav` — рабочая копия PCM16 **48 кГц mono** (исходник не изменяется,
  нормализация не выполняется);
- `decode_envelope` — RMS-огибающая **50 Гц** (анализ 4 кГц, окно 80 сэмплов);
- `speech_and_silence` / `analyse_envelope` — порог тишины **6 % от пика**,
  минимальная пауза **0.12 с**, `speech_ratio`, сегменты речи и паузы;
- `waveform_peaks` — ровно N бакетов (min/max) для отрисовки.

Ограничения: 32 МиБ и 120 с на файл (настраиваются `MARY_SHOT_AUDIO_*`), MIME-список
`audio/wav`, `audio/mpeg`, `audio/mp4`, `audio/aac`; тело читается с лимитом
(`read_body_with_limit`), необязательный `X-Content-SHA256` сверяется с фактом.
FFmpeg/ffprobe вызываются списком аргументов (без shell), с таймаутами 60/300 с;
произвольные пути в БД не принимаются — только относительные `storage_key`.

### 2.4. Talking Character Engine (`mouth_animation_mvp`)

`backend/app/mouth_animation.py`:

- `open_threshold` / `openness_curve`: окно кадра → порог тишины → масштаб
  чувствительности → однополюсный attack/release (`base = max(0.05, 1 − 0.9·smoothing)`)
  → deadband **0.03** → ограничение `max_open`. В тишине ровно `0.0`;
- `render_frame`: эллипс-«пасть» внутри области калибровки, поворот области,
  маска по краям — Pillow, без случайных движений; при `openness=0` кадр равен
  исходному;
- `render_talking_preview`: кадры → FFmpeg h264 + `aac` (исходная запись),
  `-shortest -movflags +faststart`, 24 fps, длинная сторона ≤ 1080, чётные размеры;
- `preview_parameters`: провенанс (mode, engine, region, audio sha256, gate,
  peak_rms, speech_ratio, сегменты, limitation).

Название движка честное: `MODE="mouth_animation_mvp"`, `ENGINE="pillow_ellipse_v1"`,
`SELECTED_ENGINE = None` в `app/lipsync.py` не изменён, `LIMITATION`
возвращается клиенту и показывается в UI: приблизительная анимация рта,
не phoneme-accurate lip sync.

### 2.5. Калибровка рта

`backend/app/api/mouth_calibrations.py`: `POST /api/shots/{id}/mouth-calibrations`
(upsert, 201/200), `GET …` (список), `POST …/preview?state=closed|open` → PNG
(`Cache-Control: no-store`, в БД и storage ничего не пишет). Область проверяется
на границы кадра; источник калибровки обязан принадлежать шоту.

### 2.6. Video Talking — Not Supported

`backend/app/api/mouth_sources.py`: аудит tracking не нашёл ни модели, ни адаптера
(тяжёлые модели не устанавливались). Запрос с `source_kind="video"` отклоняется
`409 video_talking_not_supported` с предложением image-режима; статичная маска на
движущуюся морду не накладывается, фальшивый результат не создаётся.

### 2.7. Job pipeline и review

Новых таблиц jobs и второго storage нет. `jobs.kind` не имеет CHECK, поэтому
`kind='mouth_animation'` не потребовал миграции; воркеры запрашивают `kinds` явно,
поэтому новая job в GPU-очередь не попадает. Генерация синхронная: в одной
транзакции создаются `Job(status='completed')` → `RenderAttempt(kind='video',
parameters.mode='mouth_animation_mvp')` → `Artifact(source='attempt',
kind='talking_preview', mime_type='video/mp4')`. Попытка не утверждается
автоматически: `approved_attempt_id` остаётся `NULL`, review — существующие
`POST /api/shots/{id}/attempts/{attempt_id}/approve|reject`.

### 2.8. UI

`ui/src/components/MouthAnimationPanel.tsx` (782 строки), смонтирована в
`ShotDetailPage` перед `ScenePlanPanel`:

- **Import Audio** (`.wav/.mp3/.m4a/.aac`), `X-Content-SHA256` считается на клиенте;
- **Audio Library** — все записи шота: статус, бейдж «выбрана», `<audio controls>`,
  Approve Audio / Отклонить, waveform (400 бакетов), рабочая копия
  (48 кГц / mono / 50 Гц / доля речи);
- **Calibrate Mouth** — оверлей области поверх изображения, X/Y/ширина/высота/поворот
  в процентах, `max_open`/`sensitivity`/`smoothing`, предпросмотр PNG «Рот закрыт» /
  «Рот открыт», сохранение калибровки;
- **Talking Preview** — селектор источника (`image`; `Video Talking — Not Supported`
  показан disabled с пояснением), кнопка генерации, при блокировке — карточка
  «Генерация заблокирована» со списком причин и явным «Пустой MP4 не создаётся»;
- результат: `<video controls>`, mode/размеры/fps/кадры/duration, attempt/job/sha256,
  текст ограничения.

`ShotReferences.tsx` теперь рендерит аудио-референс как `<audio>`, а не как битую
картинку. Существующая панель Lip Sync (`VITE_FEATURE_LIPSYNC`) не изменялась.

## 3. Изменённые файлы

Новые:

| Файл | Строк |
|---|---|
| `backend/alembic/versions/0011_mouth_calibrations.py` | 120 |
| `backend/app/shot_audio.py` | 292 |
| `backend/app/mouth_animation.py` | 396 |
| `backend/app/api/shot_audio.py` | 404 |
| `backend/app/api/mouth_calibrations.py` | 239 |
| `backend/app/api/mouth_sources.py` | 199 |
| `backend/app/api/mouth_animation.py` | 352 |
| `backend/tests/test_shot_audio.py` | 378 |
| `backend/tests/test_mouth_animation.py` | 682 |
| `ui/src/components/MouthAnimationPanel.tsx` | 782 |
| `docs/PROPOSALS/WP_VOICE_02_MOUTH_ANIMATION.md` | 139 |
| `docs/REPORTS/WP_VOICE_02_REPORT.md` | этот отчёт |

Изменённые:

- `backend/app/models.py` — модель `MouthCalibration`;
- `backend/app/config.py` — лимиты `shot_audio_upload_max_bytes`,
  `shot_audio_max_duration_s`, `mouth_animation_fps`, `mouth_animation_max_side`;
- `backend/app/main.py` — регистрация трёх роутеров;
- `backend/tests/test_schema.py` — `mouth_calibrations` в `EXPECTED_TABLES`;
- `ui/src/api/types.ts`, `ui/src/api/client.ts` — типы, загрузка, waveform,
  калибровки, предпросмотр, генерация, тексты ошибок;
- `ui/src/pages/ShotDetailPage.tsx`, `ui/src/components/ShotReferences.tsx`,
  `ui/src/styles.css`;
- `docs/DECISIONS.md` — §3.9 (S20), §4.18, §4.19, строки в §6 и журнал §8.

## 4. API

| Метод | Путь | Ответ |
|---|---|---|
| `POST` | `/api/shots/{shot_id}/audio` | 201 `ShotAudioOut`; 200 при повторном импорте того же файла |
| `GET` | `/api/shots/{shot_id}/audio` | список записей шота, свежие сверху, флаг `selected` |
| `GET` | `/api/shots/{shot_id}/audio/{asset_id}/waveform?buckets=16…2000` | `peaks[]` |
| `POST` | `/api/shots/{shot_id}/mouth-calibrations` | 201/200 upsert калибровки |
| `GET` | `/api/shots/{shot_id}/mouth-calibrations` | список калибровок шота |
| `POST` | `/api/shots/{shot_id}/mouth-calibrations/preview?state=closed\|open` | `image/png` |
| `POST` | `/api/shots/{shot_id}/mouth-animation` | `MouthAnimationOut` (job/attempt/artifact/content_url) |

Типизированные ошибки: `unsupported_audio_type`, `empty_body`, `sha256_mismatch`,
`ffprobe_failed`, `missing_audio_stream`, `invalid_audio`, `audio_too_long`,
`audio_work_copy_missing`, `audio_work_copy_invalid`, `envelope_missing`,
`work_audio_missing`, `duplicate_reference`, `audio_required`, `audio_not_approved`,
`source_image_required`, `source_reference_not_approved`, `source_file_missing`,
`source_image_invalid`, `reference_not_linked`, `video_talking_not_supported`,
`calibration_required`, `calibration_source_mismatch`, `calibration_conflict`,
`mouth_region_out_of_bounds`, `ffmpeg_missing`, `ffmpeg_failed`, `invalid_preview`.

Существующий Lip Sync API (`POST /api/shots/{id}/lipsync`, 409
`lipsync_engine_not_selected`) сохранён без изменений.

## 5. Как проверено

```text
$ cd backend && .venv/bin/python -m pytest tests -q
270 passed, 1 warning in 13.20s

$ cd backend && .venv/bin/python -m pytest tests/test_shot_audio.py tests/test_mouth_animation.py -q
25 passed, 1 warning in 3.84s

$ cd backend && .venv/bin/alembic check
SAWarning: Cannot correctly sort tables; there are unresolvable cycles ... (известное)
No new upgrade operations detected.

$ cd backend && .venv/bin/alembic current
0011_mouth_calibrations (head)

$ cd ui && npm run build
✓ 59 modules transformed.
dist/index.html                   0.40 kB │ gzip:   0.27 kB
dist/assets/index-1FDmAKsj.css   14.24 kB │ gzip:   3.10 kB
dist/assets/index-BAJiMAxJ.js   357.82 kB │ gzip: 102.23 kB
✓ built in 464ms
```

Покрытие новых тестов (25, только синтетический сигнал — WAV, сгенерированный в
тесте; пользовательские записи не создавались):

- `test_shot_audio.py` (10 функций, 12 прогонов с параметризацией): WAV/MP3/M4A/AAC,
  неверный MIME, пустое тело, несовпадение
  `X-Content-SHA256`, битый файл без аудиопотока, лимит длительности, повторный
  импорт (200 и та же запись), 409 `duplicate_reference` при чужой роли,
  привязка `shot_references`, WAV 48 кГц mono, envelope/тишина, waveform;
- `test_mouth_animation.py` (13): кривая раскрытия (0 в тишине, отсутствие дрожания,
  детерминизм), границы области, калибровка (upsert, конфликт источника, границы,
  предпросмотр PNG), генерация MP4 (размеры, fps, кадры, синхронизация длительности
  с аудио), review-цикл (approve/reject попытки), неизменность approved-референса,
  `video_talking_not_supported`, `audio_required`/`audio_not_approved`,
  отсутствие автоподтверждения.

## 6. Отклонения от документа

1. **Video Talking — Not Supported.** Tracking в репозитории отсутствует; тяжёлые
   модели не устанавливались. `409 video_talking_not_supported`, image-режим предложен.
2. **`RenderAttempt.kind='video'` + `parameters.mode='mouth_animation_mvp'`** вместо
   нового значения enum: CHECK `ck_render_attempts_kind` не расширялся, миграция для
   этого не потребовалась. Режим виден в провенансе и в UI.
3. **`jobs.kind='mouth_animation'`** без миграции (`jobs.kind` — свободный текст),
   генерация синхронная, job создаётся уже `completed`; события `events` не пишутся,
   т.к. нет асинхронных стадий. GPU-очередь не затрагивается.
4. **Audio Library = записи шота.** Общепроектной библиотеки аудио не появилось:
   запись живёт в `reference_assets`, но выборка идёт по привязкам к шоту. Это
   соответствует §4.19; «выбранная» запись — самый свежий approved-ассет шота.
5. **Калибровка без истории ревизий** (upsert) — зафиксировано в §3.9 DECISIONS.
6. **Предпросмотр рта — PNG на лету**, не артефакт: в storage ничего не пишется,
   `Cache-Control: no-store`.

Нарушений запретов нет: миграции только `0011` (согласована), API-контракты
расширены аддитивно (согласовано), approved-записи не перезаписывались, NLB не
изменялся, commit/push не выполнялись.

## 7. Не удалось проверить [ПРОВЕРИТЬ]

1. **Живой UI.** Процесс API на `127.0.0.1:8000` запущен до WP:

   ```text
   $ curl -s http://127.0.0.1:8000/openapi.json | python3 -c "…"
   ['/api/projects/{project_id}/audio']
   $ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/shots/00000000-0000-0000-0000-000000000000/audio
   404
   ```

   Проверить человеку:

   ```bash
   cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   cd ui && npm run dev
   ```

   затем открыть `#/shots/6532e96d-1358-4d30-94ed-a88dc2e14607` и пройти сценарий
   «Import Audio → Approve Audio → Calibrate Mouth → Talking Preview → Approve Result».

2. **Реальная пользовательская запись.** Все тесты — на синтетическом WAV; на живых
   MP3/M4A из диктофона не проверялось (использовать только с разрешения человека).
3. **AAC в нестандартном контейнере** — поведение ffprobe предсказуемо по коду, но
   реальным файлом не проверялось.
4. **Восприятие анимации человеком** — субъективная оценка «морфинга нет» возможна
   только после первого живого Talking Preview.

## 8. Готовность GNS-05

| Параметр | Значение |
|---|---|
| Проект | `Guinness: Night Shift`, `f5846f96-994c-4737-8c3a-7f356d93bf10` |
| Шот | GNS-05 «Король дивана», `6532e96d-1358-4d30-94ed-a88dc2e14607` |
| Референс-источник | `gns_05_start`, `6fa6064c-05c3-46d0-8c60-bff5e89f333e`, 941×1672, `status='draft'` |
| Аудио | нет |
| Калибровка | нет |
| Talking Preview | не создавался |

По решению человека использовался только синтетический тест, поэтому запись в
проект не импортировалась и пустой MP4 не создавался. Сейчас панель показывает
блокировку: «нужен approved-референс изображения или утверждённый стартовый кадр»,
«запись не выбрана: импортируйте аудио», «калибровка области рта не сохранена».

Путь до первого Talking Preview (действия человека):

1. утвердить `gns_05_start` в карточке референса (`draft → approved`) или создать и
   утвердить стартовый кадр через `keyframe` + `promote-keyframe`;
2. импортировать свою запись в панели «Озвучка» и нажать Approve Audio;
3. выставить область рта и сохранить калибровку;
4. «Сделать Talking Preview» → проверить MP4 → утвердить в существующем review.

## 9. Пример использования

```bash
# 1. импорт записи (SHA-256 обязателен для сверки)
curl -s -X POST "http://127.0.0.1:8000/api/shots/6532e96d-1358-4d30-94ed-a88dc2e14607/audio" \
  -H "Content-Type: audio/mpeg" \
  -H "X-Content-SHA256: $(shasum -a 256 voice.mp3 | cut -d' ' -f1)" \
  -H "X-Original-Name: voice.mp3" \
  --data-binary @voice.mp3

# 2. утверждение записи (существующий review референса)
curl -s -X POST "http://127.0.0.1:8000/api/reference-assets/<asset_id>/approve"

# 3. калибровка области рта (доли кадра)
curl -s -X POST "http://127.0.0.1:8000/api/shots/6532e96d-1358-4d30-94ed-a88dc2e14607/mouth-calibrations" \
  -H "Content-Type: application/json" \
  -d '{"reference_asset_id":"6fa6064c-05c3-46d0-8c60-bff5e89f333e",
       "x":0.38,"y":0.55,"width":0.24,"height":0.16,"rotation":0,
       "max_open":0.8,"sensitivity":1.0,"smoothing":0.5}'

# 4. генерация Talking Preview
curl -s -X POST "http://127.0.0.1:8000/api/shots/6532e96d-1358-4d30-94ed-a88dc2e14607/mouth-animation" \
  -H "Content-Type: application/json" \
  -d '{"source_kind":"image","reference_asset_id":"6fa6064c-05c3-46d0-8c60-bff5e89f333e",
       "audio_asset_id":"<asset_id>","calibration_id":"<calibration_id>"}'
```

## 10. Открытые вопросы к человеку

1. Нужна ли общепроектная библиотека аудио (переиспользование одной записи на
   нескольких шотах) — сейчас каждая запись привязана к шоту.
2. Нужен ли «preview-first» режим (короткий фрагмент) для калибровки, или полный
   рендер записи достаточен: MVP собирает MP4 на всю длину записи (≤ 120 с).
3. Нужно ли расширять набор параметров движка (например, вертикальный сдвиг «пасти»
   и форма) или эллипса достаточно для кошачьей морды.
4. Утверждать ли `gns_05_start` (сейчас `draft`) — без этого GNS-05 останется
   заблокированным.

## 11. Предложение следующего шага

**WP-VOICE-03 — живая приёмка GNS-05**: утверждение источника, импорт реальной записи
человеком, калибровка, Talking Preview, человеческая оценка и, при необходимости,
доработка формы рта/огибающей. Commit и push — по отдельному разрешению.
