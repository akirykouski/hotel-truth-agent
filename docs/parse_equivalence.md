# Эквивалентность разбора: агент против вложенного LLM

Сгенерировано `scripts/parse_equivalence.py`. Настоящий агент (claude-cli + MCP) получает слова гостя; из его вызова `search_hotels` берётся `constraints` (+ month, base), сравнивается с `search.parse` (вложенный разбор LLM) на тех же словах. Первые 12 запросов из `bench/llm_track.py`, остальные 20 написаны под отрицания, числа, месяцы, бюджеты, питомцев и нужды вне реестра. «Строже» и «мягче» относятся к условиям агента относительно вложенного разбора; отельные вопросы без подбора попадают в «no search».

## Итого

| Вердикт | Запросов |
|---|---|
| same | 4 |
| different | 3 |

## По запросам

| # | Запрос | Вердикт | Подходят (вложенный / агент) | Топ-3 совпал |
|---|---|---|---|---|
| 1 | Тихий номер с видом на закат недалеко от моря, едем в июле | same | 19+0м / 19+0м | да |
| 3 | Мы с ребёнком 3 лет и собакой 12 кг. Нужна детская площадка рядом и чт | same | 0+84м / 0+84м | да |
| 4 | Работаю удалённо две недели в ноябре: нужно тихо днём, хороший интерне | different | 20+12м / 36+22м | 1/3 |
| 17 | Нужна собака 12 кг разрешена, и парк рядом погулять | different | 0+116м / 0+119м | да |
| 20 | В марте хочу искупаться, насколько тёплое море в апреле и в какой отел | same | 0+0м / 0+0м | да |
| 22 | Нужен отель с лифтом, рядом с морем, мама в инвалидном кресле | different | 0+19м / 55+0м | да |
| 26 | Только не первая линия и не рядом с вокзалом, хочу спокойно спать | same | 137+0м / 137+0м | да |

(«N+Mм»: подходят + возможно, по числу отелей.)

## Расхождения

### 4. Работаю удалённо две недели в ноябре: нужно тихо днём, хороший интернет и чтобы рядом можно было поесть

Вердикт: **different**

- вложенный разбор: `night_quiet.day_quiet == True; construction.none_near == True; wifi.good == True; wifi.desk == True~; food_near.plenty == True; soundproofing.good == True~ | мес 11`
- условия агента: `night_quiet.day_quiet == True; wifi.good == True; food_near.plenty == True; wifi.desk == True~ | мес 11`
  - looser: агент не взял construction.none_near == True
  - stricter: агент не взял soundproofing.good == True (желание)
- подходят: {'match': 20, 'maybe': 12, 'fail': 197} против {'match': 36, 'maybe': 22, 'fail': 171}
- топ-3 вложенный: ['Отель HiLoft', 'Гостиница Морской Резорт', 'Архитектор Apart Hotel by Provence']; агент: ['Отель Ривьера парк отель', 'Отель HiLoft', 'Отель City Park Hotel Sochi']

### 17. Нужна собака 12 кг разрешена, и парк рядом погулять

Вердикт: **different**

- вложенный разбор: `pets.allowed == True; pets.max_weight_kg >= 12; pets.walk_m <= 800 | мес None`
- условия агента: `pets.allowed == True; pets.max_weight_kg >= 12; pets.walk_m <= 500~ | мес None`
  - other: pets.walk_m <= 800 -> pets.walk_m <= 500 (желание)
- подходят: {'match': 0, 'maybe': 116, 'fail': 113} против {'match': 0, 'maybe': 119, 'fail': 110}
- топ-3 вложенный: ['Отель Сочи-Бриз', 'Санаторий Октябрьский', 'Апартаменты Версаль Альфа Апартаменты']; агент: ['Отель Сочи-Бриз', 'Санаторий Октябрьский', 'Апартаменты Версаль Альфа Апартаменты']

### 22. Нужен отель с лифтом, рядом с морем, мама в инвалидном кресле

Вердикт: **different**

- вложенный разбор: `accessibility.lift == True; accessibility.step_free_entrance == True; beach_walk.minutes_there <= 12; beach_walk.steps_m == 0; beach_walk.climb_back_m <= 25; beach_walk.crosses_rail == False~ | мес None`
- условия агента: `accessibility.lift == True; accessibility.step_free_entrance == True~; beach_walk.minutes_there <= 10; beach_walk.climb_back_m <= 25~; beach_walk.steps_m <= 0~ | мес None`
  - looser: accessibility.step_free_entrance == True -> accessibility.step_free_entrance == True (желание)
  - looser: beach_walk.climb_back_m <= 25 -> beach_walk.climb_back_m <= 25 (желание)
  - stricter: агент не взял beach_walk.crosses_rail == False (желание)
  - stricter: beach_walk.minutes_there <= 12 -> beach_walk.minutes_there <= 10
  - other: beach_walk.steps_m == 0 -> beach_walk.steps_m <= 0 (желание)
- подходят: {'match': 0, 'maybe': 19, 'fail': 210} против {'match': 55, 'maybe': 0, 'fail': 174}
- топ-3 вложенный: ['Отель Санремо', 'HiLoft Hostel (ХайЛофт)', 'Отель Черноморъ']; агент: ['Отель Санремо', 'HiLoft Hostel (ХайЛофт)', 'Отель Черноморъ']
