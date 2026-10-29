# Импорт производственного плана

- Режим: `apply`
- Проект: `a7a6629e-6059-4aad-bb7f-eca0133085cf`
- Эпизод: `1a5599e4-586b-41c7-a713-998c4737ad04`
- Сцена: `e2a264e2-e57e-40e5-804d-d06f0d72d131`
- Шотов создано: 30, уже было: 0

- Проект: создано 1, уже было 0, пропущено 0, ошибок 0
- Эпизод: создано 1, уже было 0, пропущено 0, ошибок 0
- Сцена: создано 1, уже было 0, пропущено 0, ошибок 0
- Референс: создано 5, уже было 0, пропущено 0, ошибок 2
- Шот: создано 30, уже было 0, пропущено 0, ошибок 0
- Промпт: создано 30, уже было 0, пропущено 0, ошибок 0
- Связь референса: создано 20, уже было 0, пропущено 17, ошибок 0

## Ошибки

- Guiness_clean.png: референс не найден ни в библиотеке, ни в --references-dir; фиктивная подстановка запрещена
- wide_cinematic_concert_stage_scene_a_realistic.png: референс не найден ни в библиотеке, ни в --references-dir; фиктивная подстановка запрещена

## Детали

| Объект | Действие | Метка | Детали |
| --- | --- | --- | --- |
| Проект | create | «The Nine Lives Band» | status='draft' |
| Эпизод | create | Ночной тыгыдык | sequence_no=1, status='draft' |
| Сцена | create | Ночной тыгыдык | sequence_no=1 |
| Референс | create | 01_vocalist_clean.png | 768x820, image/png, source='series_import' |
| Референс | create | 02_guitarist_clean.png | 768x820, image/png, source='series_import' |
| Референс | create | 03_drummer_clean.png | 768x820, image/png, source='series_import' |
| Референс | create | 04_bassist_clean.png | 768x820, image/png, source='series_import' |
| Референс | create | 05_keyboardist_clean.png | 768x820, image/png, source='series_import' |
| Референс | error | Guiness_clean.png | референс не найден ни в библиотеке, ни в --references-dir; фиктивная подстановка запрещена |
| Референс | error | wide_cinematic_concert_stage_scene_a_realistic.png | референс не найден ни в библиотеке, ни в --references-dir; фиктивная подстановка запрещена |
| Шот | create | 01 NLB-01 | Вокалист — агрессивный куплет; frames=193, fps=24 |
| Промпт | create | 01 NLB-01 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 01 NLB-01 | character: 01_vocalist_clean.png → fdd8d183-5b78-4e20-9c02-9240c31f71f6 |
| Шот | create | 02 NLB-02 | Вокалист — крик припева; frames=193, fps=24 |
| Промпт | create | 02 NLB-02 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 02 NLB-02 | character: 01_vocalist_clean.png → fdd8d183-5b78-4e20-9c02-9240c31f71f6 |
| Шот | create | 03 NLB-03 | Вокалист — крупный план; frames=193, fps=24 |
| Промпт | create | 03 NLB-03 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 03 NLB-03 | character: 01_vocalist_clean.png → fdd8d183-5b78-4e20-9c02-9240c31f71f6 |
| Шот | create | 04 NLB-04 | Вокалист — мрачный бридж; frames=193, fps=24 |
| Промпт | create | 04 NLB-04 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 04 NLB-04 | character: 01_vocalist_clean.png → fdd8d183-5b78-4e20-9c02-9240c31f71f6 |
| Шот | create | 05 NLB-05 | Вокалист — вокальный акцент; frames=193, fps=24 |
| Промпт | create | 05 NLB-05 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 05 NLB-05 | character: 01_vocalist_clean.png → fdd8d183-5b78-4e20-9c02-9240c31f71f6 |
| Шот | create | 06 NLB-06 | Вокалист — финальный крик; frames=193, fps=24 |
| Промпт | create | 06 NLB-06 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 06 NLB-06 | character: 01_vocalist_clean.png → fdd8d183-5b78-4e20-9c02-9240c31f71f6 |
| Шот | create | 07 NLB-07 | Гитарист — тяжёлый рифф; frames=193, fps=24 |
| Промпт | create | 07 NLB-07 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 07 NLB-07 | character: 02_guitarist_clean.png → e624c8e1-1715-4c5d-8452-bc844af29434 |
| Шот | create | 08 NLB-08 | Гитарист — соло; frames=193, fps=24 |
| Промпт | create | 08 NLB-08 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 08 NLB-08 | character: 02_guitarist_clean.png → e624c8e1-1715-4c5d-8452-bc844af29434 |
| Шот | create | 09 NLB-09 | Гитарист — крупно струны; frames=193, fps=24 |
| Промпт | create | 09 NLB-09 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 09 NLB-09 | character: 02_guitarist_clean.png → e624c8e1-1715-4c5d-8452-bc844af29434 |
| Шот | create | 10 NLB-10 | Гитарист — финальный рифф; frames=193, fps=24 |
| Промпт | create | 10 NLB-10 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 10 NLB-10 | character: 02_guitarist_clean.png → e624c8e1-1715-4c5d-8452-bc844af29434 |
| Шот | create | 11 NLB-11 | Барабанщик — основной ритм; frames=193, fps=24 |
| Промпт | create | 11 NLB-11 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 11 NLB-11 | character: 03_drummer_clean.png → 06c6ff0d-8c11-444e-9c14-d084b95409ae |
| Шот | create | 12 NLB-12 | Барабанщик — барабанная сбивка; frames=193, fps=24 |
| Промпт | create | 12 NLB-12 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 12 NLB-12 | character: 03_drummer_clean.png → 06c6ff0d-8c11-444e-9c14-d084b95409ae |
| Шот | create | 13 NLB-13 | Барабанщик — крупный план; frames=193, fps=24 |
| Промпт | create | 13 NLB-13 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 13 NLB-13 | character: 03_drummer_clean.png → 06c6ff0d-8c11-444e-9c14-d084b95409ae |
| Шот | create | 14 NLB-14 | Барабанщик — финальный удар; frames=193, fps=24 |
| Промпт | create | 14 NLB-14 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 14 NLB-14 | character: 03_drummer_clean.png → 06c6ff0d-8c11-444e-9c14-d084b95409ae |
| Шот | create | 15 NLB-15 | Басист — медленный грув; frames=193, fps=24 |
| Промпт | create | 15 NLB-15 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 15 NLB-15 | character: 04_bassist_clean.png → eba60fa8-502e-4ca5-ba51-b2c8c759fa0a |
| Шот | create | 16 NLB-16 | Басист — ритмический кач; frames=193, fps=24 |
| Промпт | create | 16 NLB-16 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 16 NLB-16 | character: 04_bassist_clean.png → eba60fa8-502e-4ca5-ba51-b2c8c759fa0a |
| Шот | create | 17 NLB-17 | Басист — крупный план баса; frames=193, fps=24 |
| Промпт | create | 17 NLB-17 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 17 NLB-17 | character: 04_bassist_clean.png → eba60fa8-502e-4ca5-ba51-b2c8c759fa0a |
| Шот | create | 18 NLB-18 | Клавишник — мелодия; frames=193, fps=24 |
| Промпт | create | 18 NLB-18 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 18 NLB-18 | character: 05_keyboardist_clean.png → 3d510ecc-fae2-4eff-8eda-8b84560c0456 |
| Шот | create | 19 NLB-19 | Клавишник — музыкальный акцент; frames=193, fps=24 |
| Промпт | create | 19 NLB-19 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 19 NLB-19 | character: 05_keyboardist_clean.png → 3d510ecc-fae2-4eff-8eda-8b84560c0456 |
| Шот | create | 20 NLB-20 | Клавишник — клавиши крупно; frames=193, fps=24 |
| Промпт | create | 20 NLB-20 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | create | 20 NLB-20 | character: 05_keyboardist_clean.png → 3d510ecc-fae2-4eff-8eda-8b84560c0456 |
| Шот | create | 21 NLB-21 | Сюжет — Спящие люди; frames=193, fps=24 |
| Промпт | create | 21 NLB-21 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | skip | 21 NLB-21 | Guiness_clean.png: референс не разрешён |
| Связь референса | skip | 21 NLB-21 | Guiness_clean.png: референс не разрешён |
| Шот | create | 22 NLB-22 | Сюжет — Фантик; frames=193, fps=24 |
| Промпт | create | 22 NLB-22 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | skip | 22 NLB-22 | Guiness_clean.png: референс не разрешён |
| Связь референса | skip | 22 NLB-22 | Guiness_clean.png: референс не разрешён |
| Шот | create | 23 NLB-23 | Сюжет — Тыгыдык; frames=193, fps=24 |
| Промпт | create | 23 NLB-23 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | skip | 23 NLB-23 | Guiness_clean.png: референс не разрешён |
| Связь референса | skip | 23 NLB-23 | Guiness_clean.png: референс не разрешён |
| Шот | create | 24 NLB-24 | Сюжет — Чашка; frames=193, fps=24 |
| Промпт | create | 24 NLB-24 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | skip | 24 NLB-24 | Guiness_clean.png: референс не разрешён |
| Связь референса | skip | 24 NLB-24 | Guiness_clean.png: референс не разрешён |
| Шот | create | 25 NLB-25 | Сюжет — Король дивана; frames=193, fps=24 |
| Промпт | create | 25 NLB-25 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | skip | 25 NLB-25 | Guiness_clean.png: референс не разрешён |
| Связь референса | skip | 25 NLB-25 | Guiness_clean.png: референс не разрешён |
| Шот | create | 26 NLB-26 | Сюжет — Мартовская луна; frames=193, fps=24 |
| Промпт | create | 26 NLB-26 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | skip | 26 NLB-26 | Guiness_clean.png: референс не разрешён |
| Связь референса | skip | 26 NLB-26 | Guiness_clean.png: референс не разрешён |
| Шот | create | 27 NLB-27 | Сюжет — Где моя еда; frames=193, fps=24 |
| Промпт | create | 27 NLB-27 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | skip | 27 NLB-27 | Guiness_clean.png: референс не разрешён |
| Связь референса | skip | 27 NLB-27 | Guiness_clean.png: референс не разрешён |
| Шот | create | 28 NLB-28 | Группа — Открытие концерта; frames=193, fps=24 |
| Промпт | create | 28 NLB-28 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | skip | 28 NLB-28 | wide_cinematic_concert_stage_scene_a_realistic.png: референс не разрешён |
| Шот | create | 29 NLB-29 | Группа — Перед финальным припевом; frames=193, fps=24 |
| Промпт | create | 29 NLB-29 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | skip | 29 NLB-29 | wide_cinematic_concert_stage_scene_a_realistic.png: референс не разрешён |
| Шот | create | 30 NLB-30 | Группа — Финальный общий план; frames=193, fps=24 |
| Промпт | create | 30 NLB-30 | motion v1, manifest=d5cbb114eb79 |
| Связь референса | skip | 30 NLB-30 | wide_cinematic_concert_stage_scene_a_realistic.png: референс не разрешён |
