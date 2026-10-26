# Отчёт миграции legacy-файлов

- Режим: `apply`
- Legacy root: `/Users/vladislavkovalenko/Projects/Mary_Guiness`
- Storage root: `/Users/vladislavkovalenko/Projects/Mary_Guiness/storage`
- Проект: `Mary Studio`
- Начало (UTC): 2026-10-26 14:57:54
- Окончание (UTC): 2026-10-26 14:57:54
- Записано новых blob: 26; переиспользовано существующих: 0

## Сводка

| Категория | Создано | Уже есть | Пропущено |
|---|---|---|---|
| Проект | 1 | 0 | 0 |
| Персонаж | 2 | 0 | 0 |
| Bible | 2 | 0 | 0 |
| Референс | 16 | 0 | 1 |
| Эпизод | 1 | 0 | 0 |
| Сцена | 5 | 0 | 0 |
| Шот | 5 | 0 | 0 |
| Промпт | 5 | 0 | 0 |
| Ключевой кадр | 10 | 0 | 0 |
| Черновик видео | 15 | 0 | 0 |
| Файл | 0 | 0 | 2 |

## Создано

| Категория | Объект | Детали |
|---|---|---|
| Проект | Mary Studio | новый проект (status='active') |
| Персонаж | guinness | kind='other' — требует уточнения человеком |
| Bible | guinness v1 | draft, source='import', sha256=74894a8f37f3 |
| Референс | characters/guinness/reference_3q.png | 512x768, image/png, alpha=нет, view=three_quarter, pose=None, expression=None |
| Референс | characters/guinness/reference_front.jpeg | 960x1280, image/jpeg, alpha=нет, view=front, pose=None, expression=None |
| Референс | characters/guinness/reference_front.png | 960x1280, image/png, alpha=нет, view=front, pose=None, expression=None |
| Референс | characters/guinness/reference_side.png | 512x768, image/png, alpha=нет, view=side, pose=None, expression=None |
| Референс | characters/guinness/reference_sit.png | 512x768, image/png, alpha=нет, view=None, pose=sit, expression=None |
| Референс | characters/guinness/reference_sleep.png | 512x768, image/png, alpha=нет, view=None, pose=sleep, expression=None |
| Референс | characters/guinness/reference_surprised.png | 512x768, image/png, alpha=нет, view=None, pose=None, expression=surprised |
| Референс | characters/guinness/reference_walk.png | 512x768, image/png, alpha=нет, view=None, pose=walk, expression=None |
| Персонаж | marija | kind='other' — требует уточнения человеком |
| Bible | marija v1 | draft, source='import', sha256=283b8a21ba1b |
| Референс | characters/marija/reference_3q.png | 512x768, image/png, alpha=нет, view=three_quarter, pose=None, expression=None |
| Референс | characters/marija/reference_front.jpeg | 960x1280, image/jpeg, alpha=нет, view=front, pose=None, expression=None |
| Референс | characters/marija/reference_front.png | 960x1280, image/png, alpha=нет, view=front, pose=None, expression=None |
| Референс | characters/marija/reference_side.png | 512x768, image/png, alpha=нет, view=side, pose=None, expression=None |
| Референс | characters/marija/reference_sit.png | 512x768, image/png, alpha=нет, view=None, pose=sit, expression=None |
| Референс | characters/marija/reference_sleep.png | 512x768, image/png, alpha=нет, view=None, pose=sleep, expression=None |
| Референс | characters/marija/reference_surprised.png | 512x768, image/png, alpha=нет, view=None, pose=None, expression=surprised |
| Референс | characters/marija/reference_walk.png | 512x768, image/png, alpha=нет, view=None, pose=walk, expression=None |
| Эпизод | ep01 | sequence_no=1, status='draft' |
| Сцена | episode 1 / scene 1 | Морозильная камера полна едой |
| Шот | episode 1 / scene 1 / shot 1 | status='draft' |
| Промпт | episode 1 / scene 1 | prompt_type='script', version=1 |
| Сцена | episode 1 / scene 2 | Гиннесс игнорирует Марии |
| Шот | episode 1 / scene 2 / shot 1 | status='draft' |
| Промпт | episode 1 / scene 2 | prompt_type='script', version=1 |
| Сцена | episode 1 / scene 3 | Мария становится все более раздраженной |
| Шот | episode 1 / scene 3 / shot 1 | status='draft' |
| Промпт | episode 1 / scene 3 | prompt_type='script', version=1 |
| Сцена | episode 1 / scene 4 | Успех Марии |
| Шот | episode 1 / scene 4 / shot 1 | status='draft' |
| Промпт | episode 1 / scene 4 | prompt_type='script', version=1 |
| Сцена | episode 1 / scene 5 | Новая задача |
| Шот | episode 1 / scene 5 / shot 1 | status='draft' |
| Промпт | episode 1 / scene 5 | prompt_type='script', version=1 |
| Ключевой кадр | episodes/ep01/scenes/scene_01_keyframe.png | 768x512, image/png, alpha=нет |
| Ключевой кадр | episodes/ep01/scenes/scene_01_keyframe.png | artifact kind='keyframe', sha256=5bd6ff5bdeb5 |
| Ключевой кадр | episodes/ep01/scenes/scene_02_keyframe.png | 768x512, image/png, alpha=нет |
| Ключевой кадр | episodes/ep01/scenes/scene_02_keyframe.png | artifact kind='keyframe', sha256=7e23a64a1052 |
| Ключевой кадр | episodes/ep01/scenes/scene_03_keyframe.png | 768x512, image/png, alpha=нет |
| Ключевой кадр | episodes/ep01/scenes/scene_03_keyframe.png | artifact kind='keyframe', sha256=46b6332f9535 |
| Ключевой кадр | episodes/ep01/scenes/scene_04_keyframe.png | 768x512, image/png, alpha=нет |
| Ключевой кадр | episodes/ep01/scenes/scene_04_keyframe.png | artifact kind='keyframe', sha256=1853a3a2b181 |
| Ключевой кадр | episodes/ep01/scenes/scene_05_keyframe.png | 768x512, image/png, alpha=нет |
| Ключевой кадр | episodes/ep01/scenes/scene_05_keyframe.png | artifact kind='keyframe', sha256=36291ac886cc |
| Черновик видео | episodes/ep01/scenes/scene_01_draft.mp4 | синтетический job(kind='render_video', status='completed'), idempotency_key=legacy:7b29df5608e0… |
| Черновик видео | episodes/ep01/scenes/scene_01_draft.mp4 | attempt kind='video' + artifact kind='video_draft' |
| Черновик видео | episodes/ep01/scenes/scene_01_draft.mp4 | artifact kind='video_draft', sha256=7b29df5608e0 |
| Черновик видео | episodes/ep01/scenes/scene_02_draft.mp4 | синтетический job(kind='render_video', status='completed'), idempotency_key=legacy:3790b5c6606e… |
| Черновик видео | episodes/ep01/scenes/scene_02_draft.mp4 | attempt kind='video' + artifact kind='video_draft' |
| Черновик видео | episodes/ep01/scenes/scene_02_draft.mp4 | artifact kind='video_draft', sha256=3790b5c6606e |
| Черновик видео | episodes/ep01/scenes/scene_03_draft.mp4 | синтетический job(kind='render_video', status='completed'), idempotency_key=legacy:dbe7ff537a66… |
| Черновик видео | episodes/ep01/scenes/scene_03_draft.mp4 | attempt kind='video' + artifact kind='video_draft' |
| Черновик видео | episodes/ep01/scenes/scene_03_draft.mp4 | artifact kind='video_draft', sha256=dbe7ff537a66 |
| Черновик видео | episodes/ep01/scenes/scene_04_draft.mp4 | синтетический job(kind='render_video', status='completed'), idempotency_key=legacy:18c56e05b9db… |
| Черновик видео | episodes/ep01/scenes/scene_04_draft.mp4 | attempt kind='video' + artifact kind='video_draft' |
| Черновик видео | episodes/ep01/scenes/scene_04_draft.mp4 | artifact kind='video_draft', sha256=18c56e05b9db |
| Черновик видео | episodes/ep01/scenes/scene_05_draft.mp4 | синтетический job(kind='render_video', status='completed'), idempotency_key=legacy:3b900f56f557… |
| Черновик видео | episodes/ep01/scenes/scene_05_draft.mp4 | attempt kind='video' + artifact kind='video_draft' |
| Черновик видео | episodes/ep01/scenes/scene_05_draft.mp4 | artifact kind='video_draft', sha256=3b900f56f557 |

## Уже существует

Нет записей.

## Пропущено

| Источник | Причина |
|---|---|
| characters/guinness/1.png | имя не соответствует reference_*; автоматический импорт не выполняется |
| episodes/ep01/poc/ltx23_mlx_q4_i2v.meta.json | POC-эксперимент — вне MVP |
| episodes/ep01/poc/ltx23_mlx_q4_i2v.mp4 | POC-эксперимент — вне MVP |

## Предупреждения

- characters/guinness: kind='other' — семантика персонажа требует уточнения в библиотеке (S13)
- characters/guinness/1.png: файл не импортирован автоматически — требуется решение человека
- characters/guinness/reference_3q.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/guinness/reference_front.jpeg: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/guinness/reference_front.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/guinness/reference_side.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/guinness/reference_sit.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/guinness/reference_sleep.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/guinness/reference_surprised.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/guinness/reference_walk.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/marija: kind='other' — семантика персонажа требует уточнения в библиотеке (S13)
- characters/marija/reference_3q.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/marija/reference_front.jpeg: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/marija/reference_front.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/marija/reference_side.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/marija/reference_sit.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/marija/reference_sleep.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/marija/reference_surprised.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- characters/marija/reference_walk.png: нет альфа-канала — непрозрачный референс, проверить при композиции
- episodes/ep01/scenes/scene_01_keyframe.png: нет альфа-канала — непрозрачный кадр
- episodes/ep01/scenes/scene_02_keyframe.png: нет альфа-канала — непрозрачный кадр
- episodes/ep01/scenes/scene_03_keyframe.png: нет альфа-канала — непрозрачный кадр
- episodes/ep01/scenes/scene_04_keyframe.png: нет альфа-канала — непрозрачный кадр
- episodes/ep01/scenes/scene_05_keyframe.png: нет альфа-канала — непрозрачный кадр

## Оригиналы

Импорт только читает исходные файлы: ничего не перемещено и не удалено.
Повторный запуск идемпотентен по sha256; дубликаты в БД и storage не создаются.
