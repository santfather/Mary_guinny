# WP-QUALITY-06 — Guinness: Night Shift: подготовка проекта и аудио

> Дата: 2026-11-04. Режим: без GPU, без рендера, без approve, без commit/merge/push.
> Проект подготовлен штатным `import_series`; референсы — `draft`; keyframe и render
> заблокированы до решения человека.

---

## 1. Project ID

| Поле | Значение |
|---|---|
| Проект | `Guinness: Night Shift` |
| `project_id` | `f5846f96-994c-4737-8c3a-7f356d93bf10` |
| Статус | `draft` |
| Эпизод | `38d0177a-3434-44cc-ba2a-e9b25ee93f9f`, `sequence_no=1`, «Ночная смена» |
| Сцена | `191f7644-b444-4d1f-9bba-f074be618382`, `sequence_no=1` |
| Манифест импорта | `docs/PROPOSALS/GUINNESS_NIGHT_SHIFT_MANIFEST.json` |
| `manifest_sha256` | `0d309c8a58e801754923c48fb01c29173a3e2c97a878751cb31c5936bf80ea9e` |

Проверка перед импортом: в БД были только `Mary Studio` (`b6810db7…`) и
`The Nine Lives Band` (`a7a6629e…`); проекта GNS не существовало.

Идемпотентность: первый `--apply` — `shots_created=5 shots_existing=0`; повторный
`--apply` — `shots_created=0 shots_existing=5`, все категории (`project`, `episode`,
`scene`, `references` 6, `shots` 5, `prompts` 5, `shot_references` 10) в состоянии
`exists`. Дублей нет.

---

## 2. Shot IDs

`shots.title` в схеме отсутствует: название шота живёт в манифесте и в
`prompt_revisions.parameters_json` (поле `shot_key`), в БД — только `sequence_no`.

| # | Shot ID | `shot_key` | Название (манифест) | Статус | Кадры | fps |
|---|---|---|---|---|---|---|
| 1 | `f5e2c81d-1952-403f-9ebf-30d0d77087bd` | GNS-01 | Когда хозяева уснули | `prompt_ready` | 193 | 24 |
| 2 | `3b82fed6-af17-4546-88b2-3e5fa8644202` | GNS-02 | Первое задание | `prompt_ready` | 193 | 24 |
| 3 | `8f681a53-c535-4010-946c-74a8cb4ceccc` | GNS-03 | Ночной патруль | `prompt_ready` | 193 | 24 |
| 4 | `58d01a81-4e92-4cf4-83a4-b12077a3c61a` | GNS-04 | Научный эксперимент | `prompt_ready` | 193 | 24 |
| 5 | `6532e96d-1358-4d30-94ed-a88dc2e14607` | GNS-05 | Король дивана | `prompt_ready` | 193 | 24 |

`start_keyframe_artifact_id` и `start_keyframe_attempt_id` пусты у всех пяти шотов.

---

## 3. Reference IDs

Все референсы — `kind='uploaded'`, `status='draft'`, `source='series_import'`.
Роли проставлены штатным `PATCH /api/reference-assets/{id}` (разрешён только для
`draft`); approve не выполнялся.

| Роль | Reference ID | Исходный файл | Размер | `storage_key` |
|---|---|---|---|---|
| `gns_01_start` | `16940715-f022-4b02-af77-3f61c0162511` | `docs/cats/Cat and moon.png` | 392×657 | `blobs/99/997b5986….png` |
| `gns_02_start` | `9beecac8-5148-4bf6-ad3c-f5f9551cef8a` | `docs/cats/Cat playing.png` | 396×622 | `blobs/df/df718cdc….png` |
| `gns_03_start` | `a12e1605-79a9-4af6-94d5-a136e141794a` | `docs/cats/Cat wallking.png` | 394×618 | `blobs/8b/8b61e4f5….png` |
| `gns_04_start` | `bfd968d6-0ec7-479f-ad6b-97ca205423ef` | `docs/cats/Cat with cup.png` | 392×646 | `blobs/cb/cb1c2fd3….png` |
| `gns_05_start` | `6fa6064c-05c3-46d0-8c60-bff5e89f333e` | `docs/cats/Regal Burmese Cat on Velvet Sofa.png` | 941×1672 | `blobs/e1/e197e3ec….png` |
| `guinness_identity` | `c3e2fef3-7d06-4f30-8c6f-6cf8dff9d9f6` | `docs/cats/Chocolate Burmese Cat Portrait.png` | 1064×1479 | `blobs/f7/f7ec5d84….png` |

`shot_references`: 10 строк, по 2 на шот (`purpose='character'`: стартовый кадр +
identity). Физического копирования не было: все шесть `storage_key` — те же
content-addressed блобы, что у approved-референсов NLB (mtime 2026-10-29, до начала
WP). `BlobStore.put_file` вернул `created=False`.

---

## 4. SHA-256

`shasum -a 256` по исходным файлам совпал с `reference_assets.sha256` у всех шести:

| Роль | SHA-256 |
|---|---|
| `gns_01_start` | `997b5986b1b61aa3566d35471fb5aeaf9dc89aea750eed7b780fc86f729216bd` |
| `gns_02_start` | `df718cdc8a22973fa3f2354982a3fb4c8519fd0afa77db70a046c78aae78803d` |
| `gns_03_start` | `8b61e4f59149643205b35530fe24d1697bf2868aa5297f647881ee6861cb7b16` |
| `gns_04_start` | `cb1c2fd3348d9150591cd7d6f6f8b225168634d2fd981075d0ce0d378193f3b3` |
| `gns_05_start` | `e197e3ec60dbcadad92a710d7afbca0501365a867c2c85663a68d846451dbfc9` |
| `guinness_identity` | `f7ec5d84a935d06460909d728c458b8a68474c93aca2757a611ed24505891809` |

Те же пять sha256 уже присутствуют у approved NLB (`nlb_26_start`, `nlb_22_start`,
`nlb_23_start`, `nlb_24_start`, `nlb_25_start`) и identity (`guinness_identity`).
NLB-записи не менялись: созданы новые `draft`-строки на те же блобы.

---

## 5. Keyframe IDs

**Нет ни одного.** `start_keyframe_artifact_id` пуст, `render_attempts` по проекту GNS
— 0. Причина: `_keyframe_from_reference` требует `status='approved'`, а утверждение
— решение человека.

Проверка пути (без записи):
`POST /api/shots/f5e2c81d…/keyframe` → `409 {"detail":"reference asset must be approved"}`.
Ни артефакт, ни attempt не созданы.

---

## 6. Prompt revision IDs

API для `prompt_revisions` отсутствует; использован штатный путь — ревизии созданы
манифестом при `import_series` (тип `motion`, версия 1). Все тексты — переписанные под
фактическую позу стартовых кадров (не механические из WP-QUALITY-05 §5).

| Shot | Prompt revision ID | Версия | `source` |
|---|---|---|---|
| GNS-01 | `1ddbc7ca-529a-4b66-9e39-5ed6cb905b54` | 1 | `nine_lives_band_manifest` |
| GNS-02 | `c83ebf0d-2a98-4d88-9f21-52604bae2554` | 1 | `nine_lives_band_manifest` |
| GNS-03 | `9417c8e3-907f-4c6e-8a4c-4f45070b8730` | 1 | `nine_lives_band_manifest` |
| GNS-04 | `8a8fceb7-19af-4403-8927-5d73e4cedfdc` | 1 | `nine_lives_band_manifest` |
| GNS-05 | `64d94b0d-e5de-4abc-9cd5-1fb6cfc4cef5` | 1 | `nine_lives_band_manifest` |

Обоснование движений (сверено с самими кадрами):

- **GNS-01** — кот сидит на пледе у окна, смотрит вверх на луну. Движение: взгляд с
  луны на камеру, уши/усы, дыхание, кончик хвоста; камера и кадрирование неподвижны.
- **GNS-02** — лапа **уже лежит** на красно-золотом фантике на глянцевом полу.
  Движение: одно короткое толкающее движение лапой (фантик скользит), взгляд за
  фантиком, затем подъём головы к камере. Без бросков и прыжков.
- **GNS-03** — кот идёт **на камеру**, передняя лапа поднята, хвост вверх. Движение:
  несколько шагов вперёд по той же оси, замедление и остановка, уши вверх. Камера
  неподвижна, разворота нет.
- **GNS-04** — лапа **уже на кромке** крапчатой кружки на столе. Движение: короткое
  скольжение кружки по столешнице, кружка остаётся вертикальной, кот смотрит на неё;
  без опрокидывания и разлива.
- **GNS-05** — кот лежит на велюровом диване, голова **уже поднята** к камере.
  Движение: чуть глубже в велюр, медленное мигание, подъём подбородка, кончик хвоста;
  без артикуляции рта (речь только в пост-продакшене).

Действий, требующих резкой смены композиции (прыжок, разворот, смена ракурса,
появление новых объектов), в промптах нет.

---

## 7. Seeds

Запланированные seed зафиксированы **до** создания RenderAttempt; значения
детерминированы от `shot_key`: `int(sha256(shot_key)[:8], "big") % 2**31`.

| Shot | Planned seed |
|---|---|
| GNS-01 | `997974099` |
| GNS-02 | `1662782784` |
| GNS-03 | `1495917156` |
| GNS-04 | `2112430633` |
| GNS-05 | `1674001497` |

Расхождение план/факт (важно): `POST /api/shots/{id}/render` принимает только
`preview`, а `queue_render` не кладёт `seed` в payload job. Воркер берёт seed из
`payload.get("seed")`, при отсутствии — `sha256(attempt_id)[:8] % 2**31`
(`worker/ltx_worker.py`). Значит фактический seed будет производным от `attempt_id`,
а не от таблицы выше. Способы устранения — только с разрешения (см. §11, B-4:
аддитивное необязательное поле `seed` в запросе рендера/очереди либо ручная
фиксация фактического seed после прогона). Самовольно контракт не менялся.

---

## 8. Audio readiness

Подготовлено: `docs/PROPOSALS/GUINNESS_NIGHT_SHIFT_AUDIO_MANIFEST.json`,
`docs/PROPOSALS/GUINNESS_NIGHT_SHIFT_SUBTITLES.srt`.

| Shot | Реплика | Окно, с | Ожидаемый WAV | Статус |
|---|---|---|---|---|
| GNS-01 | «Люди уснули. Начинается моя смена» | 1,2–4,3 | `audio/gns/gns_01_dialogue.wav` | `pending_recording` |
| GNS-02 | «Проверка гравитации. Успешно» | 2,9–5,2 | `audio/gns/gns_02_dialogue.wav` | `pending_recording` |
| GNS-03 | «Подозрительный шум. Это был я» | 2,6–5,0 | `audio/gns/gns_03_dialogue.wav` | `pending_recording` |
| GNS-04 | «А если вот так?..» | 1,5–3,5 | `audio/gns/gns_04_dialogue.wav` | `pending_recording` |
| GNS-05 | «Рабочий день окончен. Кормить меня!» | 1,0–3,9 | `audio/gns/gns_05_dialogue.wav` | `pending_recording` |

- WAV отсутствуют: каталога `audio/gns/` нет, ни одного `.wav` в репозитории не
  найдено. Фиктивные записи не создавались, `artifacts` GNS — 0.
- Права: `rights_status=pending`; требуется письменное согласие исполнителя
  (вне репозитория), поле `rights_evidence` заполняет человек.
- Требования к записи: WAV 48 кГц stereo, `pcm_s16le`, −18 LUFS, TP ≤ −1,5 dBTP,
  шум ≤ −55 dBFS. Нормализация и проверка — FFmpeg (`loudnorm`, `ffprobe`);
  команды в манифесте (`verify_command`, `loudness_command`), сведение — `mix_command`.
- Субтитры: один SRT на мастер 40,21 с (5 × 8,0417 с), тайминги = окно реплики +
  смещение шота.
- Дорожка LTX (`aac` 48 кГц stereo) речью не является и при сведении приглушается.

Музыка: brief «Ночная смена Гиннесса» — `music_brief` в манифесте (84–92 BPM, свинг,
контрабас pizzicato, Rhodes/felt, щётки, редкий кларнет/вибрафон; форма intro → A → B →
question → coda; −18/−14 LUFS, мастер −16 LUFS / ≤ −1,5 dBTP). Статус **BLOCKED**:
генератора нет; MP3 NLB (`67af1e71…`) не используется — права не подтверждены.
Файл-заменитель не создавался.

---

## 9. Lip sync readiness

Адаптер проверен: `backend/app/lipsync.py`, `SELECTED_ENGINE = None`.
`POST /api/shots/f5e2c81d…/lipsync` → `409 {"detail":"lipsync_engine_not_selected"}`;
в БД ничего не записано, job не создан. Движок не устанавливался.

Спецификация для GNS-01 и GNS-05 — в манифесте (`lip_sync`):

| Поле | GNS-01 | GNS-05 |
|---|---|---|
| Reference image | `16940715…` (`gns_01_start`, 392×657) | `6fa6064c…` (`gns_05_start`, 941×1672) |
| Dialogue | «Люди уснули. Начинается моя смена» | «Рабочий день окончен. Кормить меня!» |
| Ожидаемый WAV | `audio/gns/gns_01_dialogue.wav` | `audio/gns/gns_05_dialogue.wav` |
| Окно речи | 1,2–4,3 с (29-й кадр) | 1,0–3,9 с (24-й кадр) |
| Целевая длительность | 3,1 с | 2,9 с |
| Формат видео | 576×1024, 24 fps, 193 кадра | то же |
| Статус | **BLOCKED** | **BLOCKED** |

Технические требования: WAV 48 кГц stereo; синхронизация от первого кадра по окну;
сохранение идентичности, окраса, фона, освещения и числа лап; выход — то же видео с
изменённой артикуляцией без сдвига тайминга. Выбор движка требует проверки лицензии и
памяти (≈18 ГиБ) — отдельное разрешение, поэтому статус BLOCKED.

---

## 10. Render readiness

| Проверка | GNS-01 | GNS-02 | GNS-03 | GNS-04 | GNS-05 |
|---|---|---|---|---|---|
| Identity approved | ✗ draft | ✗ draft | ✗ draft | ✗ draft | ✗ draft |
| Start frame approved | ✗ нет | ✗ нет | ✗ нет | ✗ нет | ✗ нет |
| Motion prompt | ✓ v1 | ✓ v1 | ✓ v1 | ✓ v1 | ✓ v1 |
| Preset `safe` | ✓ | ✓ | ✓ | ✓ | ✓ |
| Planned seed | ✓ | ✓ | ✓ | ✓ | ✓ |
| Audio plan | ✓ manifest | ✓ | ✓ | ✓ | ✓ |
| Активный GPU job | ✗ нет | ✗ нет | ✗ нет | ✗ нет | ✗ нет |

Профиль (зафиксирован): `safe`, `eco`, 576×1024, 24 fps, 193 кадра, cfg 3.0,
`low_ram=false`, workflow `ltx23-mlx-q4-i2v/a48ba1c43439`
(`comfyui-workflows/ltx23_mlx_q4_i2v.api.json`), шаги distilled 8/3.

Факты проверки:
- `GET /api/presets`: Apple M3 Pro, 18 ГиБ; `safe` измерен (24 прогона, 1 062,5 с/шот).
- `GET /api/render-agent/status`: `worker_online=false`, `rendering=false`,
  `current_job_id=null`, thermal `unknown`.
- Активных jobs в БД — 0; всего jobs 48 (без изменений), GNS `render_attempts` — 0.
- `POST /api/shots/f5e2c81d…/render` → `409 {"detail":"start keyframe is not approved"}`;
  job не создан.
- `python -m app.preflight --manifest … --project-id …` → `WARN`: 5 шотов, 6
  референсов, аспект 9:16, fps 24; `references` утверждено 0 из 6;
  `start_frames` 0 из 5; workflow-ноды `LoadImage=1, loader=2, generate=3`; диск 66,1 ГиБ.

---

## 11. Блокеры

| № | Блокер | Что нужно | Кто решает |
|---|---|---|---|
| B-1 | 6 референсов в `draft` | approve `guinness_identity` и `gns_0X_start` | человек |
| B-2 | Нет approved стартовых кадров | после B-1: `keyframe` → `promote-keyframe` | человек/агент по разрешению |
| B-3 | Нет WAV-реплик, права не оформлены | запись голоса + согласие | человек |
| B-4 | Seed не передаётся в job: план ≠ факт | одобрить аддитивное `seed` в запросе рендера **или** принять seed воркера | человек |
| B-5 | Lip sync: движок не выбран | выбор MLX-совместимого движка, лицензия, память | человек (Q-01) |
| B-6 | Музыка: генератора нет, права на MP3 NLB не подтверждены | оригинальный трек с правами или разрешение на генератор | человек (Q-02/Q-09) |
| B-7 | `low_ram=true` не измерен | отдельный preview-тест 73 кадра | человек |

Технические замечания (не блокеры): `import_series` жёстко пишет
`source="nine_lives_band_manifest"` в `prompt_revisions.parameters_json` (провенанс
косметически неточен); названия шотов не хранятся в БД; preflight печатает шаблон
`nlb/<...>` в строке `outputs`.

---

## 12. Следующее разрешённое действие

Остановка. Следующий шаг требует явного «ок» человека — один из вариантов:

1. Утвердить референсы (B-1): `POST /api/reference-assets/{id}/approve` для шести
   записей, затем создать и утвердить пять стартовых кадров (`keyframe` +
   `promote-keyframe`). GPU не нужен.
2. Записать пять WAV по требованиям §8 и подтвердить права на голос.
3. Принять решение по seed (B-4): аддитивное поле в контракте рендера или фиксация
   фактического seed после прогона.
4. После B-1/B-2 и отдельного разрешения на GPU — один рендер GNS-01 в профиле `safe`
   (`eco`, 576×1024, 193 кадра, 24 fps, cfg 3.0, `low_ram=false`).

---

## Проверка (WP-QUALITY-06 §8)

| Пункт | Результат |
|---|---|
| Пять шотов в новом проекте | ✓ 5 (`sequence_no` 1–5), `prompt_ready` |
| Project-scoped references | ✓ 6 референсов и 10 `shot_references` привязаны к GNS |
| Дубли | ✓ нет: 0 повторяющихся sha256, повторный импорт — всё `exists` |
| NLB не изменён | ✓ 31 шот, 31 keyframe, 15 approved-референсов, jobs/attempts не менялись |
| Новые GPU jobs | ✓ нет: активных 0, GNS attempts 0 |
| Approved NLB assets | ✓ без изменений (все 15 остались `approved`, те же sha256) |
| Метаданные | ✓ `metadata.original_name`, `source=series_import`, размеры, `has_alpha` |
| Resume возможен | ✓ состояние в БД полное: референсы, промпты, кадры-план; продолжение — с §12 |

Ограничения соблюдены: GPU не запускался, модели не устанавливались, фиктивные аудио
не создавались, NLB не менялся, commit/merge/push не выполнялись, автоматического
approve не было.
