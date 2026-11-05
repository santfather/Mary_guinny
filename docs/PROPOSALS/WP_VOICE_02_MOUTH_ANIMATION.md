# WP-VOICE-02 — импорт аудио шота и `mouth_animation_mvp`

> Статус: **предложение, ожидает согласования**. Код не пишется до «ок».
> Основание: `AGENTS.md` §3 (миграции и контракты — только по разрешению),
> `docs/DECISIONS.md` §6 (изменения схемы/API сначала оформляются предложением),
> `docs/ARCHITECTURE.md` §14.1, §14.10 п.4.

## 1. Что переиспользуется без миграции (аудит)

| Механизм | Где | Как используется |
|---|---|---|
| `BlobStore` (content-addressed, atomic publish) | `backend/app/storage.py` | оригинал аудио и рабочий PCM WAV; файлы не перезаписываются |
| `POST /api/artifacts` (сырое тело + `X-Content-SHA256`) | `backend/app/api/artifacts.py` | образец валидации размера/хеша для нового эндпоинта |
| `reference_assets` (status, `role`, `metadata` JSONB, S15) | `models.py` | аудио хранится как `kind='uploaded'`, `role='shot_audio'` |
| `shot_references` (`purpose='other'`) | `models.py` | привязка аудиоассета к шоту без новой таблицы связей |
| approve/reject референса | `POST /api/reference-assets/{id}/approve\|reject` | ручное утверждение аудио; approved-запись неизменяема (S15) |
| `ffprobe`/`ffmpeg` 7.1.1, `probe_audio`, `_decode_envelope` | `audio_timeline.py` | реальный формат, длительность, огибающая |
| `jobs` (нет CHECK на `kind`) | `models.py` | новый тип `mouth_animation` **без миграции** |
| `render_attempts.kind` | CHECK `keyframe\|video\|postprocess` | используется `video` + `parameters.mode='mouth_animation_mvp'`, поэтому существующий review работает без правок |
| `artifacts.source` | CHECK `attempt\|composition\|upload\|import\|export` | аудио — `upload` (attempt_id NULL), результат — `attempt` |
| `GET /api/artifacts/{id}/content` | `api/artifacts.py` | воспроизведение и скачивание результата |
| `POST /api/shots/{id}/attempts/{aid}/approve\|reject` | `api/shots.py` | review Talking Preview без нового писателя |
| `probe_mp4` | `video_probe.py` | проверка результата (контейнер, видео/аудио дорожки, длительность) |

`one_active_render_per_shot` ограничен `kind='render_video'`, воркер запрашивает
`kinds` явно — `mouth_animation` не блокирует и не попадает в GPU-очередь.

## 2. Что требует миграции: таблица `mouth_calibrations`

Причина: калибровка рта должна сохраняться на сервере для конкретного
reference/keyframe, быть изменяемой и не менять approved-записи. Подходящего
mutable JSONB на уровне шота в схеме нет; `artifacts.metadata` и
`reference_assets.metadata` неизменяемы после approve (S15), `jobs.payload` —
временный. Дублировать калибровку в `prompt_revisions.body` — искажение модели данных.

Минимальное изменение: **одна новая таблица**, существующие таблицы не меняются.

```sql
CREATE TABLE mouth_calibrations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    shot_id uuid NOT NULL REFERENCES shots(id),
    reference_asset_id uuid REFERENCES reference_assets(id),
    keyframe_artifact_id uuid REFERENCES artifacts(id),
    x double precision NOT NULL,
    y double precision NOT NULL,
    width double precision NOT NULL,
    height double precision NOT NULL,
    rotation double precision NOT NULL DEFAULT 0,
    max_open double precision NOT NULL DEFAULT 0.8,
    sensitivity double precision NOT NULL DEFAULT 1.0,
    smoothing double precision NOT NULL DEFAULT 0.5,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_mouth_calibrations_single_source CHECK (
        (reference_asset_id IS NOT NULL)::int + (keyframe_artifact_id IS NOT NULL)::int = 1
    ),
    CONSTRAINT ck_mouth_calibrations_region CHECK (
        x >= 0 AND y >= 0 AND width > 0 AND height > 0
        AND x + width <= 1 AND y + height <= 1
    ),
    CONSTRAINT ck_mouth_calibrations_rotation CHECK (rotation >= -180 AND rotation <= 180),
    CONSTRAINT ck_mouth_calibrations_max_open CHECK (max_open > 0 AND max_open <= 1),
    CONSTRAINT ck_mouth_calibrations_sensitivity CHECK (sensitivity > 0 AND sensitivity <= 5),
    CONSTRAINT ck_mouth_calibrations_smoothing CHECK (smoothing >= 0 AND smoothing < 1)
);
CREATE UNIQUE INDEX uq_mouth_calibrations_shot_reference
    ON mouth_calibrations (shot_id, reference_asset_id) WHERE reference_asset_id IS NOT NULL;
CREATE UNIQUE INDEX uq_mouth_calibrations_shot_keyframe
    ON mouth_calibrations (shot_id, keyframe_artifact_id) WHERE keyframe_artifact_id IS NOT NULL;
```

Миграция: `0011_mouth_calibrations`, только `create_table` + индексы; откат —
`drop_table`. Существующие данные не трогаются, `alembic check` должен остаться
«no new operations» после `upgrade head`.

## 3. API (аддитивно)

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/shots/{shot_id}/audio` | сырое аудио (`audio/wav\|mpeg\|mp4\|aac`), ffprobe, оригинал + PCM 48 кГц mono, привязка к шоту (`shot_references.purpose='other'`) |
| GET | `/api/shots/{shot_id}/audio` | библиотека аудио шота: duration, sample_rate, channels, sha256, status, `selected` |
| GET | `/api/shots/{shot_id}/audio/{asset_id}/waveform` | пики для waveform (из сохранённой огибающей) |
| POST | `/api/shots/{shot_id}/mouth-calibrations` | сохранить калибровку (upsert по source) |
| GET | `/api/shots/{shot_id}/mouth-calibrations` | список калибровок шота |
| POST | `/api/shots/{shot_id}/mouth-calibrations/preview?state=closed\|open` | PNG кадра рта до генерации, без записи в БД |
| POST | `/api/shots/{shot_id}/mouth-animation` | синхронный Talking Preview → job/attempt/artifact |

Существующие контракты не меняются: `POST /api/shots/{id}/lipsync` остаётся
409 `lipsync_engine_not_selected`, `SELECTED_ENGINE` не подменяется.

Коды отказа `POST /mouth-animation` (409, тело `{"error": ...}`):
`audio_required`, `audio_not_approved`, `source_image_required`,
`source_reference_not_approved`, `calibration_required`,
`mouth_region_out_of_bounds`, `video_talking_not_supported`.

Лимиты: `shot_audio_upload_max_bytes = 32 МиБ`, `shot_audio_max_duration_s = 120`,
`mouth_animation_fps = 24`, кадров — `round(duration * fps)`.

## 4. Talking Preview: как проходит review

Генерация локальная и синхронная (как `exports` и `compositions/{rev}/render`),
без воркера и без второй очереди:

1. `Job(kind='mouth_animation', shot_id, status='completed')` — `jobs.kind` без CHECK,
   миграция не нужна; partial unique index касается только `render_video`.
2. `RenderAttempt(kind='video', status='completed', job_id=job.id,
   workflow_version='mouth_animation_mvp_v1',
   parameters={mode, audio_asset_id, calibration_id, source_kind, fps, frames})`.
3. `Artifact(source='attempt', attempt_id=..., kind='talking_preview', mime='video/mp4')`.

Review — существующие `approve`/`reject` шота (kind='video', completed).
Автоматического approve нет; `preview_cannot_be_approved` не затрагивается.

## 5. Движок (approximate mouth animation, не phoneme-accurate)

- огибающая RMS из рабочего PCM WAV (общая с `audio_timeline`), приведение к fps кадра;
- noise gate по порогу открытия; `sensitivity` масштабирует амплитуду;
- attack/release — однополюсный фильтр с разными коэффициентами (не дрожит);
- `max_open` ограничивает раскрытие; deadband подавляет микро-колебания;
- тишина → раскрытие ровно 0 (рот закрыт), случайных движений нет;
- кадр: вертикальное растяжение области рта + затемнённая «полость» внутри
  эллипса; область задаётся нормализованными X/Y/W/H и rotation;
- детерминизм: одинаковые вход и калибровка → побайтно одинаковые кадры.

Ограничение фиксируется в UI и в metadata: режим `mouth_animation_mvp`,
«приблизительная анимация рта, не phoneme-accurate lip sync».

## 6. Video Talking

В репозитории и зависимостях нет tracking-инструментов (`mediapipe`, `opencv`,
`dlib`, `face_recognition`). Статус — **Not Supported**; API отвечает
`video_talking_not_supported` с предложением image-режима. Тяжёлые модели не
устанавливаются.

## 7. Что не делается

LTX/ComfyUI не запускаются, TTS и облачные API не подключаются, NLB не меняется,
approved assets не удаляются и не перезаписываются, commit/push не выполняются.
