# Mary Studio × Maestro — roadmap интеграции (WP-M0)

> **Статус:** WP-M0…WP-M8 выполнены (2026-11-04); WP-M8 — только интерфейс, движок не
> выбран. Дальнейшие работы не начинаются без отдельного разрешения человека.
> **Дата:** 2026-11-04.
> **Основание:** `MAESTRO_CAPABILITY_AUDIT.md` (факты и пробелы),
> `MAESTRO_LICENSE_REVIEW.md` (что разрешено переносить).
> **Правила:** `AGENTS.md`, `docs/DECISIONS.md`, `docs/ROADMAP_MARY_STUDIO.md`
> (один WP за раз, миграции и API — только по решению, отчёт по §14.2, без merge/push).

---

## 1. Принципы этого roadmap

1. **Reuse First.** Каждый WP расширяет существующие сущности (`Shot`, `RenderAttempt`,
   `Artifact`, `Job`, `SeriesRun`), а не создаёт параллельные.
2. **KISS.** Первый WP не содержит миграций и меняет только существующие контракты
   аддитивно.
3. **Preserve Provenance.** Любой новый результат — новый `Artifact`/попытка; утверждённые
   артефакты не перезаписываются.
4. **Apple Silicon First.** Только инструменты, работающие на M3 Pro 18 GB без CUDA:
   Python, FFmpeg, Ollama, ComfyUI/MLX.
5. **License-safe.** Только независимая реализация идей; код Maestro не переносится
   (`MAESTRO_LICENSE_REVIEW.md` §5).
6. **Не обещать без измерения.** Presets, ETA, preview — только после собственных замеров.

---

## 2. Предлагаемый порядок и обоснование

Задание предлагает WP-M1…M8 в порядке Director → Characters → Render → Preview → Voice →
Presets → Media → Assembly. Аудит показывает, что этот порядок не оптимален для текущего
производства:

| Факт из аудита | Следствие |
|---|---|
| 30 шотов NLB уже отрендерены, но **финального клипа нет** (`pipeline/stages/assembly.py` только предлагает DaVinci) | сборка/экспорт даёт немедленный результат |
| `shots.approved_attempt_id` существует, но **никто его не пишет**; approve видео-попытки отсутствует | без ревью нельзя детерминированно выбрать попытку для сборки |
| Прогресс есть в `events`, но UI его не показывает для одиночной job | дешёвая наблюдаемость без миграций |
| Планирование следующей песни не блокирует выпуск текущего клипа | Phase B идёт после выпуска |
| Voice/lip sync упирается в отсутствие MLX-движка и лицензии моделей | ставится последним и условно |

**Рекомендуемая последовательность:**

```text
WP-M0 (этот аудит)
   └─ WP-M1 Review & Monitoring        ← первый implementation WP
        ├─ WP-M2 Assembly & Export
        │     └─ WP-M5 Media Review & Comparison
        ├─ WP-M3 Music Timeline & Plan
        │     └─ WP-M6 Character & Voice References
        │           └─ WP-M8 Voice & Lip Sync Adapter (условно)
        ├─ WP-M4 Render Recovery
        └─ WP-M7 Hardware-Aware Presets
```

Отображение на фазы задания:

| Фаза задания | WP | Приоритет |
|---|---|---|
| A — аудит | WP-M0 | выполнен |
| I — Assembly & Export | WP-M2 | выполнен |
| E — Render Agent (recovery) | WP-M4 | выполнен |
| F — Live Preview & Monitoring | WP-M1 | выполнен |
| H — Media Library & Review | WP-M1, WP-M5 | выполнен |
| B — Director / Planning | WP-M3 | выполнен |
| C — Character & Voice References | WP-M6 | выполнен |
| G — Hardware Presets | WP-M7 | выполнен |
| D — Voice & Lip Sync | WP-M8 | интерфейс выполнен, движок не выбран |

---

## 3. Пакеты работ

Обозначения сложности: **S** — до 1 дня работы агента, **M** — несколько сессий,
**L** — требует исследования/экспериментов.

---

### WP-M0. Аудит и лицензионный обзор

**Состояние:** выполнен 2026-11-04 (этот пакет).
**Результаты:** `MAESTRO_CAPABILITY_AUDIT.md`, `MAESTRO_LICENSE_REVIEW.md`,
`MAESTRO_INTEGRATION_ROADMAP.md`.
**Миграции:** нет. **Код:** не менялся.

---

### WP-M1. Ревью попытки и мониторинг job (первый implementation WP)

**Цель:** замкнуть цикл «рендер → просмотр → утверждение» и показать реальный прогресс
одиночного рендера.

**Состояние:** выполнен 2026-11-04. Реализовано; отклонение — `reject` утверждённой
попытки снимает `approved_attempt_id` (`docs/DECISIONS.md` §4.9).

**Почему первый:** 24 клипа уже отрендерены, но формально «утверждённой» попытки в данных
нет — `shots.approved_attempt_id` никем не записывается. Без этого сборка (WP-M2) не может
быть детерминированной. Оба изменения аддитивны и не требуют миграций.

**Объём:**

1. API ревью попытки:
   - `POST /api/shots/{shot_id}/attempts/{attempt_id}/approve` — только `kind='video'`,
     только `status='completed'`, только своя попытка; идемпотентно; пишет
     `shots.approved_attempt_id`, `Shot.status='approved'`;
   - `POST /api/shots/{shot_id}/attempts/{attempt_id}/reject` — `Shot.status='changes_requested'`,
     `approved_attempt_id` не меняется, артефакт не удаляется;
   - конфликт: попытка другого шота → 404/409, не `approved`.
2. API мониторинга:
   - `GET /api/jobs/{job_id}/events` — журнал `events` по job (sequence, event, stage,
     progress, payload), только чтение;
   - `GET /api/jobs/{job_id}` дополнить последним событием (аддитивное поле).
3. UI `ShotDetailPage`:
   - видео-плеер для completed video-попытки;
   - кнопки «Утвердить» / «Отклонить», бейдж статуса шота;
   - блок прогресса активной job: статус, stage, прогресс, elapsed, ошибка — polling
     каждые 3–5 с (как `SeriesRunPage`);
   - технические метаданные попытки (seed, разрешение, кадры, fps, `workflow_version`).
4. UI `SeriesRunPage`: ссылка на шот и переход к нему.

**Затрагиваемые файлы:**

- `backend/app/api/shots.py` — approve/reject;
- `backend/app/api/jobs.py`, `backend/app/api/worker_schemas.py` — events и последнее событие;
- `backend/tests/test_shots_api.py`, новый `backend/tests/test_attempt_review.py`;
- `ui/src/api/client.ts`, `ui/src/pages/ShotDetailPage.tsx`, `ui/src/labels.ts`.

**Данные/API:** без миграций. Новые эндпоинты аддитивны; существующие ответы не ломаются.
`enum Shot.status` не расширяется (`approved`, `changes_requested` уже есть).

**Риски:** approve «чужой» попытки; повторный approve меняет историю — закрывается
идемпотентностью и иммутабельностью артефактов. `approved_attempt_id` не должен влиять на
`start_keyframe_artifact_id` (S9).

**DoD / критерии приёмки:**

- approve/reject покрыты API-тестами, включая конфликт шотов и идемпотентность;
- `GET /api/jobs/{id}/events` возвращает упорядоченный журнал, 404 на неизвестный job;
- UI показывает прогресс активной job и плеер попытки;
- существующие 158 backend-тестов и 43 корневых остаются зелёными; `npm run build` проходит;
- утверждённый стартовый кадр и старые попытки не меняются.

**Проверка:** `pytest backend/tests -q`, `python -m pytest tests -q`, ручной сценарий
NLB-25 (прогресс → MP4 → approve).

**Сложность:** M. **Зависимости:** нет. **Миграции:** нет.

---

### WP-M2. Assembly & Export MVP

**Цель:** получить вертикальный 9:16 MP4 из утверждённых попыток с музыкальной дорожкой.

**Состояние:** выполнен 2026-11-04. Схема утверждена человеком — вариант A
(`docs/DECISIONS.md` §4.8); без утверждённых попыток в БД сборка из UI недоступна
(список клипов пуст до первого approve).

**Объём:**

1. `backend/app/assembly.py`: сборка через локальный `ffmpeg`
   (concat demuxer или `filter_complex`), триммы начала/конца, нормализация разрешения
   (576×1024 → 1080×1920, `scale`+`pad`), наложение `aac`-дорожки, проверка результата
   `probe_mp4`/ffprobe.
2. `POST /api/projects/{project_id}/exports` — принимает упорядоченный список
   `{shot_id, attempt_id, trim_start_s?, trim_end_s?}` + `audio_artifact_id`; валидирует,
   что попытки `completed` и принадлежат проекту; синхронно собирает MP4 (объём ≤ 30
   клипов, ожидаемое время — секунды/десятки секунд).
3. `GET /api/projects/{project_id}/exports` — список собранных экспортов.
4. UI: экран/панель «Сборка» — выбор утверждённых шотов, порядок, музыка, экспорт,
   ссылка на результат.

**Блокирующее решение (требуется до реализации):** куда писать результат.

| Вариант | Плюсы | Минусы |
|---|---|---|
| A. `artifacts.source='export'` + `artifacts.metadata` JSONB (миграция | CHECK + колонка) | честный провенанс, один storage | миграция и изменение CHECK (S12) |
| B. `RenderAttempt(kind='postprocess')` + job | укладывается в S12 без новых source | требует job-цели `scene_id` или `shot_id`, а экспорт проектный; job-таблица не поддерживает project-цель (CHECK `scene XOR shot`) |
| C. Синхронный экспорт + artifact `source='import'` + JSON-манифест рядом | без миграции | семантика `import` искажается |

Рекомендация: **вариант A** отдельной миграцией `0009_export_artifacts`
(`source='export'`, `artifacts.metadata`, пересоздание CHECK) — но только после
утверждения человеком. До утверждения WP-M2 не начинается.

**Затрагиваемые файлы:** `backend/app/assembly.py` (новый), `backend/app/api/exports.py`
(новый), `backend/app/models.py`, миграция `0009`, `backend/app/main.py`,
`ui/src/pages/ExportPage.tsx` (новый), `ui/src/api/client.ts`, тесты.

**Риски:** «затереть» исходники (запрещено: только чтение), рассинхрон длительности,
несовпадение fps (24 fps у всех NLB), разные аспекты (28–30 — 16:9). Проверять через
`ffprobe` и `probe_mp4`.

**DoD:** экспорт собирается из 3+ клипов; исходные MP4 не изменены (sha256 до/после);
результат — валидный h264 MP4; провенанс восстанавливается из БД.

**Сложность:** M. **Зависимости:** WP-M1 (утверждённые попытки), решение по схеме.

---

### WP-M3. Music timeline и производственный план

**Цель:** из аудиофайла песни получить таймлайн и черновик плана сцен/шотов.

**Состояние:** выполнен 2026-11-04. Схема утверждена человеком — вариант `0010`
(аудио проекта + `production_plans`); анализ — FFmpeg + чистый Python без `librosa`
(`docs/DECISIONS.md` §4.10). Отклонения от объёма: план сохраняется только в
`production_plans` (сцены/шоты/`prompt_revisions` не создаются), правка границ и
применение плана в UI не входят — ревизии только `draft`/`superseded`.

**Объём:**

1. Загрузка аудио в проект: `POST /api/projects/{id}/audio` (артефакт `audio/mpeg`/`wav`,
   `scenes.audio_artifact_id` либо связь с проектом — требует решения по схеме).
2. `backend/app/audio_timeline.py`: длительность, BPM, beat/downbeat, энергетические
   секции через FFmpeg + `librosa` (CPU); результат — JSON с таймкодами и `confidence`.
3. `POST /api/projects/{id}/production-plans/generate`: Ollama (structured output) +
   Pydantic-схема плана; bounded repair (не более 2 попыток); создаёт **только черновики**
   `scenes`/`shots`/`prompt_revisions` и план; `approved` не выставляется автоматически.
4. UI: просмотр таймлайна, правка границ, генерация плана, применение.

**Новые данные (требуют утверждения):** таблица `production_plans` (project_id, revision,
status, source, plan JSONB, warnings), связь с `scenes`.

**Риски:** эвристические границы выданы за структуру песни (запрещено — помечать
`confidence` и требовать ручного подтверждения); LLM-план ломает утверждённые шоты
(запрещено: только draft); новая зависимость `librosa`.

**DoD:** для тестовой песни строится таймлайн; план валиден по схеме; повторная генерация
создаёт новую ревизию; утверждённые записи не меняются; тесты на валидацию и repair.

**Сложность:** L. **Зависимости:** WP-M1 (утверждение/ревью), решение по схеме и
зависимостям.

---

### WP-M4. Восстановление рендера по `prompt_id`

**Состояние:** выполнен 2026-11-04. `POST /api/worker/jobs/{id}/external` пишет
`prompt_id` в существующий `jobs.external_id` (миграций нет, нового события нет);
воркер держит локальный state-файл `~/.mary-studio/ltx-worker-state.json`
(`--state-file`), `resume` отдаёт `external_id`, восстановление идёт через `/history`
с перепроверкой `/queue`; потерянный prompt — `external_prompt_lost` (retryable).
Решение — `docs/DECISIONS.md` §4.11. Живой прогон NLB-24 (576×1024): kill воркера
после `/prompt` → `resume` → MP4 загружен и job завершён без повторного рендера.

**Цель:** не терять рендер и не запускать дубликат после рестарта воркера.

**Объём:**

1. `POST /api/worker/jobs/{id}/external` (или поле в `heartbeat`) — воркер сообщает
   `prompt_id`; backend пишет `jobs.external_id` (колонка уже есть).
2. `worker/ltx_worker.py`: сохранять `prompt_id` в локальный state-файл перед ожиданием,
   при старте читать; `resume` отправляет известные `prompt_id`.
3. `POST /api/worker/resume`: для каждой job с `external_id` возвращать `external_id`,
   чтобы воркер мог сначала проверить `/history/{prompt_id}`, затем `complete`/`fail`/
   новый claim. Автоматический перезапуск при `lease_expired` по-прежнему запрещён.
4. Тест: kill воркера после `/prompt` → `resume` → `/history` подтверждает завершение →
   artifact загружается без повторного рендера.

**Файлы:** `backend/app/api/worker.py`, `worker_schemas.py`, `worker/ltx_worker.py`,
`worker/client.py`, `tests/test_ltx_worker.py`, `backend/tests/test_queue.py`.

**Миграции:** нет (`external_id` существует). **Риски:** дубликат рендера при гонке —
закрывается идемпотентностью и сверкой `/history`; stale `external_id` — очищать при
завершении.

**DoD:** сценарий рестарта проходит на fake-тесте и вручную на NLB-шоте (с разрешения);
дубликаты не создаются.

**Сложность:** M. **Зависимости:** нет (можно параллельно M2/M3).

---

### WP-M5. Сравнение попыток и медиаданные

**Цель:** выбирать лучший дубль осознанно.

**Состояние:** выполнен 2026-11-04. Реализовано; пагинация — страница
`items/total/limit/offset` (решение человека), «сделать текущей» вызывает существующий
approve попытки, по умолчанию видны все `kind` (`docs/DECISIONS.md` §4.12).

**Объём:** side-by-side плеер двух попыток, фильтр по шоту/сцене, метаданные, «сделать
текущей», ссылка на артефакт; список попыток проекта. Без новой модели данных —
только API-выборка (`GET /api/projects/{id}/attempts?scene=&shot=`) и UI.

**Риски:** рост ответов API; пагинация обязательна. **Сложность:** S/M.
**Зависимости:** WP-M1.

---

### WP-M6. Character & Voice References

**Цель:** довести библиотеку персонажей до требований Phase C без синтеза речи.

**Состояние:** выполнен 2026-11-04. Голос — `reference_assets(role='voice')` через
`POST /api/characters/{id}/voice` (ffprobe, ≤ 30 с, дедуп по sha256); `multi_view` — флаг в
`metadata` через существующий PATCH; `keyframe` отклоняет голос и многоракурсную карточку;
UI — раздел «Голос» на карточке персонажа и чекбокс в лайтбоксе. Миграций нет
(`docs/DECISIONS.md` §4.13).

**Объём:** `role='voice'`/`role='identity'` в `reference_assets` (если нужно — CHECK
`purpose`/`role` уже гибок), загрузка голосового файла через существующий artifact API,
проверка длительности (ffprobe), запрет использовать многоракурсную карточку как стартовый
кадр (валидация в `keyframe`), UI-раздел «Голос» на карточке персонажа.

**Миграции:** не понадобились (`reference_assets.role` уже свободный `Text`; `multi_view` и
`duration_s` — в `metadata`).
**Риски:** смешение identity и start frame — валидировать в сервисе.
**Сложность:** S/M. **Зависимости:** WP-M3 не обязателен, но логичен после него.

---

### WP-M7. Hardware-Aware Presets

**Цель:** пресеты Safe / Balanced / Quality на измеренных данных.

**Состояние:** выполнен 2026-11-04. В таблицу вошли только измеренные режимы —
`safe` (576×1024, 24 шота, 1062,5 с/шот), `wide` (1024×576, 3 шота), `legacy_512`
(512×512/73/24, WP-00A); Balanced/Quality не создавались без замеров. Детект железа —
stdlib + `sysctl`/`vm_stat` (`psutil` не добавлялся), `GET /api/presets` read-only,
воркер соблюдает приоритет «CLI > API > default», `preset`/`preset_source` пишутся в
`render_attempts.parameters`. Миграций нет (`docs/DECISIONS.md` §4.14).

**Объём:** `backend/app/presets.py` — детект Apple Silicon и доступной памяти
(`sysctl`, `vm_stat`), таблица пресетов, эндпоинт выдачи рекомендаций; параметры передаются
в `worker/ltx_worker.py` как значения по умолчанию **только если пользователь не задал
свои**; фиксация фактических замеров в существующем `render_attempts.parameters`.

**Запрещено:** CUDA-профили, NVML, DLSS/TensorRT, обещания ускорения без benchmark.
**Сложность:** M. **Зависимости:** накопленные замеры (≥ 3 рендеров на пресет).

---

### WP-M8. Voice & Lip Sync Adapter (условно)

**Цель:** интерфейс, а не движок.

**Состояние:** интерфейс выполнен 2026-11-04, движок не выбран. `backend/app/lipsync.py` —
адаптер с `SELECTED_ENGINE = None` и явными кодами `lipsync_engine_not_selected`/
`lipsync_engine_not_implemented`; `POST /api/shots/{id}/lipsync` отвечает 409 и ничего не
пишет в БД; UI-поля — за `VITE_FEATURE_LIPSYNC` (по умолчанию выключен). Legacy-заглушки
`pipeline/stages/lipsync.py` и `voices.py` не тронуты. Условия запуска реального движка
(MLX-модель, лицензии весов и голоса, согласие на голос, замер памяти на 18 ГиБ) не
выполнены (`docs/DECISIONS.md` §4.15).

**Объём:** адаптер с явной ошибкой «движок не выбран» реализован в
`backend/app/lipsync.py` (отклонение от буквы roadmap по решению человека: legacy-заглушки
`pipeline/stages/lipsync.py` и `voices.py` не тронуты); `POST /api/shots/{id}/lipsync`
отклоняет запрос с понятным кодом, пока не утверждён движок; UI-поля (текст, аудио,
персонаж, голос) — за фиче-флагом.

**Условия старта (все обязательны):** выбран MLX-совместимый движок; проверена лицензия
весов и голоса; есть согласие на использование голоса; измерена память на 18 GB.

**Сложность:** L. **Зависимости:** WP-M6 + решение человека.

---

## 4. Граф зависимостей

```text
WP-M0 (аудит)
  └─ WP-M1 (review + monitoring)          [без миграций]
       ├─ WP-M2 (assembly/export)         [нужна миграция 0009 + решение по схеме]
       │    └─ WP-M5 (comparison/media)
       ├─ WP-M4 (recovery by prompt_id)   [без миграций]
       ├─ WP-M3 (music timeline + plan)   [миграция 0010, без новых библиотек]
       │    └─ WP-M6 (voice references)   [без миграций]
       │         └─ WP-M8 (lip sync adapter, условно)   [интерфейс, без движка]
       └─ WP-M7 (presets)                 [без миграций, только замеры]
```

Правило: WP-M2 и WP-M3 не начинаются, пока человек не утвердит изменения схемы.
WP-M4 не требует решений по схеме и может идти параллельно.

---

## 5. Реестр рисков регрессии

| Риск | WP | Вероятность | Влияние | Мера |
|---|---|---|---|---|
| `approved_attempt_id` начнёт влиять на стартовый кадр | M1 | низкая | высокое | отдельный тест: approve не меняет `start_keyframe_*` |
| Расширение `enum Shot.status` | M1 | низкая | высокое | использовать существующие значения |
| Новый `artifacts.source` ломает CHECK S12 | M2 | средняя | высокое | отдельная миграция + тесты `test_constraints.py` |
| Экспорт перезапишет исходные MP4 | M2 | низкая | высокое | новый artifact, `storage.put_file`, sha256 до/после |
| LLM-план изменит утверждённые шоты | M3 | средняя | высокое | только draft-ревизии, approve вручную |
| `librosa` не собирается/тяжёлая | M3 | средняя | среднее | проверка wheels, lock, fallback на FFmpeg+numpy |
| Дубликат рендера после resume | M4 | средняя | высокое | сверка `/history` до retry, идемпотентность |
| Приблизительный прогресс выдан за реальный | M1 | средняя | среднее | подписывать «этап», не «% модели» |
| Похожесть кода на Maestro | все | средняя | высокое | clean-room чек-лист (`MAESTRO_LICENSE_REVIEW.md` §5–6) |
| Новая зависимость под неподходящей лицензией | все | низкая | высокое | фиксировать лицензию в отчёте WP |

---

## 6. Критерии приёмки программы (в целом)

1. Все WP-M* не меняют `docs/ARCHITECTURE.md` и не ломают существующие API/CLI.
2. Утверждённые артефакты и стартовые кадры не перезаписываются (проверяется тестами).
3. Сборка клипа воспроизводима: один и тот же список попыток + музыка → сопоставимый MP4,
   исходники неизменны.
4. План клипа создаёт только черновики; ни один шот не становится `approved` автоматически.
5. Все новые зависимости зафиксированы в `pyproject.toml` + `uv.lock` с лицензией.
6. Тесты: backend ≥ текущих 158 + новые, корневые 43 остаются зелёными,
   `alembic check` — no new operations после каждой миграции, UI `npm run build`.
7. Для каждого WP — отчёт по `docs/ARCHITECTURE.md` §14.2 и остановка.

---

## 7. Первый implementation WP: детализация приёмки (WP-M1)

**Ветка:** `wp-m1-attempt-review`.

**Что должно быть верно до начала:**

- [ ] человек подтвердил, что approve видео-попытки пишет `shots.approved_attempt_id`;
- [ ] подтверждено, что `Shot.status='approved'` выставляется только этим действием;
- [ ] подтверждено, что прогресс в UI подписывается как «этап», а не как точный процент.

**Что считается готовым:**

1. `POST /api/shots/{shot_id}/attempts/{attempt_id}/approve` — 200, идемпотентно,
   `approved_attempt_id` и `Shot.status` обновлены; 409 для не-completed попытки;
   404 для чужого шота.
2. `POST .../reject` — 200, статус `changes_requested`, `approved_attempt_id` не изменён.
3. `GET /api/jobs/{job_id}/events` — упорядоченный список; 404 на неизвестный job.
4. UI: плеер, approve/reject, прогресс активной job, метаданные; сборка проходит.
5. Тесты: новые + существующие зелёные; `alembic check` без операций.

**Отчёт:** по формату §14.2, с фактическим выводом команд.

---

## 8. Что не планируется (won't)

- Перенос кода, ассетов, весов, конфигов Maestro.
- Собственный видеоредактор, многодорожечный таймлайн, переходы, титры (MVP — склейка).
- Tiny VAE / live preview на текущем LTX-2.3 MLX workflow.
- Voice cloning и animal lip sync без проверенного MLX-движка и прав на голос.
- Вторая очередь, вторая таблица jobs, второй storage.
- Автоматическое утверждение (`approved`) чего-либо.
- Изменение `LICENSE` Mary Studio.

---

## 9. Журнал изменений

| Дата | Изменение |
|---|---|
| 2026-11-04 | Первая редакция: WP-M0 выполнен; предложены WP-M1…M8, порядок и обоснование, граф зависимостей, риски, критерии приёмки, детализация WP-M1 |
| 2026-11-04 | WP-M1 выполнен: approve/reject видео-попытки, `GET /api/jobs/{id}/events` + `last_event`, UI-плеер/прогресс/метаданные; без миграций (`docs/DECISIONS.md` §4.9) |
| 2026-11-04 | WP-M2 выполнен: миграция `0009_export_artifacts`, `app/assembly.py`, `POST/GET /api/projects/{id}/exports`, UI `#/exports` (`docs/DECISIONS.md` §4.8); вариант A утверждён человеком |
| 2026-11-04 | WP-M3 выполнен: миграция `0010_audio_timeline_plans`, `app/audio_timeline.py` (FFmpeg + чистый Python), `app/production_plan.py` (Ollama + bounded repair), `app/api/production_plans.py`, UI `#/plan` (`docs/DECISIONS.md` §4.10); только черновые ревизии |
| 2026-11-04 | WP-M4 выполнен: `POST /api/worker/jobs/{id}/external` → `jobs.external_id`, `worker/ltx_worker.py` (state-файл `~/.mary-studio/`, `resume` + `/history`/`/queue`, `external_prompt_lost`), тесты восстановления; без миграций и новых событий (`docs/DECISIONS.md` §4.11) |
| 2026-11-04 | WP-M5 выполнен: `GET /api/projects/{id}/attempts` (фильтры `scene_id`/`shot_id`/`kind`/`status`, страница `items/total/limit/offset`, флаг `approved`), UI `#/attempts` (фильтры, пагинация, сравнение двух видео, «Сделать текущей» через approve); без миграций (`docs/DECISIONS.md` §4.12) |
| 2026-11-04 | WP-M6 выполнен: голос персонажа — `POST /api/characters/{id}/voice` → `reference_assets(role='voice')` (ffprobe, ≤ 30 с, дедуп по sha256); `multi_view` в `metadata` через существующий PATCH; `keyframe` отклоняет голос и многоракурсную карточку; UI — раздел «Голос» и чекбокс в лайтбоксе; без миграций (`docs/DECISIONS.md` §4.13) |
| 2026-11-04 | WP-M7 выполнен: `backend/app/presets.py` (только измеренные `safe`/`wide`/`legacy_512`, детект Apple Silicon и памяти через `sysctl`/`vm_stat`), `GET /api/presets`, приоритет «CLI > API > default» в воркере, `preset`/`preset_source` в `render_attempts.parameters`; Balanced/Quality не создавались; без миграций (`docs/DECISIONS.md` §4.14) |
| 2026-11-04 | WP-M8 выполнен как интерфейс: `backend/app/lipsync.py` (`SELECTED_ENGINE = None`, явные коды), `POST /api/shots/{id}/lipsync` → 409 без записей в БД, UI за `VITE_FEATURE_LIPSYNC`; legacy-заглушки `pipeline/stages/*` не тронуты, веса/TTS/внешние сервисы не подключались; без миграций (`docs/DECISIONS.md` §4.15) |
