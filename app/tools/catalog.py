"""Каталог инструментов-примитивов. Его видят рецепты, компилятор характеристик (LLM), MCP и чат-агент.

Каждый инструмент — детерминированный код над данными из data/. Описание и поля результата здесь
единственный источник правды: из них собирается подсказка для LLM и схема MCP.
"""
import json
from functools import lru_cache

from app import region
from app.tools import noise, photos, places, text, view, walk, window

OSM_TAG_HINTS = (
    "Частые теги OSM: amenity=pharmacy|cafe|restaurant|bar|pub|nightclub|fast_food|parking|charging_station|"
    "hospital|clinic|doctors|kindergarten|toilets|atm|bank|ice_cream; shop=supermarket|convenience|alcohol|bakery|"
    "mall; leisure=playground|park|dog_park|fitness_centre|swimming_pool|water_park|sports_centre; "
    "tourism=attraction|museum|viewpoint|theme_park|zoo; healthcare=hospital|clinic|pharmacy; "
    "highway=bus_stop; railway=station|halt; landuse=construction; building=construction; "
    "детская больница: healthcare=hospital плюс healthcare:speciality=paediatrics (размечено редко)."
)


def _walk_to(hotel_id, target="beach", tags=None):
    if tags:
        return walk.route_to_tags(hotel_id, tuple(sorted(tags.items())))
    return walk.route_to(hotel_id, target)


def _sea_view(hotel_id):
    v = view.compute(hotel_id)
    return {k: v[k] for k in ("building", "facades", "sea_view", "uncertainty_drivers", "method", "inputs")}


def _sunset(hotel_id):
    v = view.compute(hotel_id)
    return {"months": {str(m): s for m, s in v["sunset"].items()}, "building": v["building"], "method": v["method"]}


def _window_view(hotel_id, facade=None, floor=None, month=7):
    w = window.render(hotel_id, facade, floor, month)
    out = {k: w[k] for k in ("facade", "floor", "month", "sea_fraction", "sea_p", "sun", "verdict", "levels", "facades")}
    out["picture"] = f"/api/hotels/{hotel_id}/window?facade={w['facade']}&floor={w['floor']}&month={w['month']}"
    return out


@lru_cache(maxsize=1)
def _mapapp():
    """Готовые расчёты соседнего репозитория map-app (scripts/import_mapapp.py) для отелей этого региона."""
    f = region.DATA / "mapapp.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"meta": {}, "hotels": {}}


def _leg(x):
    return {"min": x["min"], "m": x["m"], "up_m": x["up_m"], "down_m": x["down_m"], "steps": x["steps"],
            "rail_crossings": x["rail_crossings"]} if x else None


def _mapapp_walk(hotel_id, target="beach"):
    d = _mapapp()
    w = ((d["hotels"].get(hotel_id) or {}).get("walk") or {}).get(target)
    if not w or not w.get("there"):
        return {"available": False}
    s = w.get("stroller") or {}
    return {"available": True, "target": w["target"], "kind": w["kind"], "there": _leg(w["there"]), "back": _leg(w["back"]),
            "straight_m": w["straight_m"], "detour": w["detour"],
            "stroller": {"possible": bool(s.get("possible")), "there": _leg(s.get("there")), "back": _leg(s.get("back"))},
            "match": d["hotels"][hotel_id]["match"], "method": d["meta"]["walk"]["method"], "commit": d["meta"].get("commit")}


def _mapapp_noise(hotel_id):
    d = _mapapp()
    n = (d["hotels"].get(hotel_id) or {}).get("noise")
    if not n:
        return {"available": False}
    return {"available": True, **{k: n[k] for k in ("quietest", "loudest", "spread_db", "by_floor")},
            "facades": [{k: f[k] for k in ("dir", "night", "day", "night_source")} for f in n["facades"]],
            "uncert_db": d["meta"]["noise"].get("uncert_db"), "match": d["hotels"][hotel_id]["match"],
            "method": d["meta"]["noise"]["method"], "commit": d["meta"].get("commit")}


def _nearby(hotel_id, tags, radius_m=500, open_at_hour=None, weekday=5, limit=10):
    oa = (int(weekday), float(open_at_hour)) if open_at_hour is not None else None
    return places.nearby(hotel_id, tags, radius_m, oa, limit=int(limit))


TOOLS = {
    "mapapp_walk": {
        "fn": _mapapp_walk, "source": "geo",
        "description": "Путь пешком из расчёта map-app (пешеходный граф OSM + FABDEM, Тоблер, лестницы маршем, переходы "
                       "через ж/д), туда и обратно отдельно, и тот же путь для коляски без лестниц. Цели: beach — пляж, "
                       "station — ж/д станция, center — центр (Морской вокзал). Есть не у всех отелей (available).",
        "params": {"target": {"type": "string", "enum": ["beach", "station", "center"]}},
        "returns": "available, target, kind, there{min, m, up_m, down_m, steps, rail_crossings}, back{…}, straight_m, "
                   "detour, stroller{possible, there{…}, back{…}}, match, method",
    },
    "mapapp_noise": {
        "fn": _mapapp_noise, "source": "geo",
        "description": "Шум ночью и днём по каждому фасаду и этажу из расчёта map-app (CNOSSOS-EU для дорог, Schall 03 "
                       "для ж/д, бары по часам работы; экраны из домов и рельефа), ± 5 дБ. Есть не у всех отелей (available).",
        "params": {},
        "returns": "available, quietest{night_db, dir, floor}, loudest{night_db, dir, floor}, spread_db, "
                   "by_floor[{floor, quiet_dir, quiet_db, loud_db}], facades[{dir, night[], day[], night_source}], uncert_db",
    },
    "sea_view": {
        "fn": _sea_view, "source": "geo",
        "description": "Видно ли море из окон: по каждой стороне здания с какого этажа (лучи по карте высот, "
                       "зданиям OSM и деревьям из DSM, Монте-Карло по неточным высотам).",
        "params": {},
        "returns": "sea_view{possible, facade, from_floor, confidence, p_any_top_floor}; facades[{dir, az, "
                   "sea_from_floor, confidence, sea_deg_top_floor, p_sea_by_floor}]; building{levels, levels_source}; "
                   "uncertainty_drivers[{address, height_source, blocks_deg}]",
    },
    "sunset": {
        "fn": _sunset, "source": "geo",
        "description": "Виден ли закат из окон по месяцам: азимут заката, какая сторона, с какого этажа, садится "
                       "ли солнце в море.",
        "params": {},
        "returns": "months{'1'..'12': {azimuth, facade, from_floor, over_sea}}",
    },
    "window_view": {
        "fn": _window_view, "source": "geo",
        "description": "Вид из окна: что видно с конкретного этажа и стороны здания в выбранном месяце. Доля азимутов "
                       "с морем, вероятность моря, садится ли солнце над морем, готовая фраза-вывод и "
                       "ссылка на картинку-панораму. Без аргументов: лучшая сторона, верхний этаж, июль.",
        "params": {"facade": {"type": "string", "description": "сторона здания: С, СВ, В, ЮВ, Ю, ЮЗ, З, СЗ"},
                   "floor": {"type": "integer"}, "month": {"type": "integer"}},
        "returns": "facade, floor, month, sea_fraction (0–1), sea_p (0–1), sun{az, alt, visible, over_sea, visible_min}, "
                   "verdict (фраза), levels, facades[{dir, az, sea_from_floor, confidence}], picture (ссылка)",
    },
    "walk_to": {
        "fn": _walk_to, "source": "geo",
        "description": "Пеший маршрут по дорожкам OSM до ближайшего пляжа (target='beach') или до ближайшего объекта "
                       "с тегами (tags={...}): время туда и обратно с учётом подъёма, лестницы, переходы через ж/д и "
                       "крупные дороги.",
        "params": {"target": {"type": "string", "enum": ["beach"]},
                   "tags": {"type": "object", "description": "теги OSM цели, например {\"highway\": \"bus_stop\"}"}},
        "returns": "target, distance_m, straight_m, minutes_there, minutes_back, climb_back_m, climb_there_m, steps_m, "
                   "crossings[{what, how}]",
    },
    "noise": {
        "fn": noise.compute, "source": "geo",
        "description": "Оценка шума днём и ночью по сторонам здания: дороги по классу, ж/д, бары и клубы с часами "
                       "работы.",
        "params": {},
        "returns": "night_level (тихо|умеренно|шумно, самая тихая сторона), night_level_loud_side, quietest{dir, "
                   "night_db}, loudest{dir, night_db}, facades[{dir, day_db, night_db}], top_sources[{kind, name, "
                   "distance_m}], venues_unknown_hours",
    },
    "noise_timeline": {
        "fn": noise.timeline, "source": "geo",
        "description": "Ночь по часам: уровень шума на каждой стороне здания в каждый час суток (дороги с суточным "
                       "профилем, ж/д, бары и клубы по часам работы на выбранный день), оценка внутри номера при "
                       "открытом и закрытом окне, часы выше порога сна ВОЗ (30 дБ внутри) и совет на месяц. "
                       "Для вопросов «хорошо ли спать с открытым окном», «до скольки шумно».",
        "params": {"month": {"type": "integer", "description": "месяц 1–12, по умолчанию 7; уровни от месяца не зависят"},
                   "weekday": {"type": "integer", "description": "день недели 0=пн..6=вс, по умолчанию 5"}},
        "returns": "advice (одна строка), window_assumed (open|closed, closed если в карточке есть кондиционер), "
                   "quietest, loudest, facades[{dir, hours{0..23: дБ снаружи}, indoor_open, indoor_closed, "
                   "sleep{open|closed: {hours_above, noisy_hours, noisy_until, cause}}}], threshold, uncertainty",
    },
    "nearby": {
        "fn": _nearby, "source": "osm",
        "description": "Объекты OSM с тегами в радиусе от отеля: точки и здания (кафе, аптеки, парки) и линии "
                       "(улицы, тропы, пешеходные зоны, пляжи). open_at_hour (0–24, weekday 0=пн..6=вс) оставляет только "
                       "заведения, открытые в этот час; задавай его, только если вопрос про часы работы. " + OSM_TAG_HINTS,
        "params": {"tags": {"type": "object"}, "radius_m": {"type": "number"},
                   "open_at_hour": {"type": "number"}, "weekday": {"type": "integer"}},
        "returns": "count, nearest_m, items[{name, distance_m, opening_hours}], unknown_hours (сколько объектов без "
                   "часов работы при open_at_hour)",
    },
    "card_search": {
        "fn": text.card_search, "source": "card",
        "description": "Поиск слов (регулярные выражения) в карточке Островка: удобства отеля, номера и их удобства "
                       "(коды вроде blackout-blinds, pets-allowed, soundproofing, balcony, sea-view), правила, описание.",
        "params": {"terms": {"type": "array", "items": {"type": "string"}},
                   "where": {"type": "array", "items": {"type": "string",
                                                        "enum": ["amenities", "rooms", "policies", "description"]}}},
        "returns": "found, hits[{field, quote}], rooms_matched, rooms_total",
    },
    "reviews_search": {
        "fn": text.reviews_search, "source": "reviews",
        "description": "Упоминания в отзывах гостей (до 20 последних): сколько раз в «понравилось» и в «не "
                       "понравилось», с цитатами и датами.",
        "params": {"terms": {"type": "array", "items": {"type": "string"}},
                   "exclude": {"type": "array", "items": {"type": "string"}}},
        "returns": "reviews_total, positive, negative, positive_quotes[{date, room, quote}], negative_quotes, latest",
    },
    "review_stats": {
        "fn": text.review_stats, "source": "reviews",
        "description": "Структурированные поля отзывов Островка: как гости оценили Wi-Fi (perfect/slow/…), средние оценки "
                       "отеля по аспектам (cleanness, location, room, services, meal, price, wifi, hygiene — из 10), "
                       "кто ездит (family, couple, solo, friends) и зачем (leisure, business).",
        "params": {},
        "returns": "reviews_total, wifi_votes{perfect, slow, …}, wifi_rated, wifi_good_share, aspects{…}, travellers{…}, trips{…}",
    },
    "photo_labels": {
        "fn": photos.photo_labels, "source": "photos",
        "description": "Что видно на фото отеля из карточки (разметка зрением Claude, заморожена): есть ли кадры из "
                       "номера с видом на море, плотные шторы, ступеньки у входа, лифт. Отели снимают лучшие номера, "
                       "поэтому отсутствие моря на фото слабее, чем его присутствие.",
        "params": {},
        "returns": "photos, room_photos (кадры номеров, балконов, видов из окна), sea_from_room, sea_any, best_conf, "
                   "views[], blackout{yes, no}, steps{yes, no}, elevator{yes, no}, evidence[{url, kind, note, sea, "
                   "sea_from_room, confidence}]",
    },
    "climate": {
        "fn": lambda hotel_id, month: text.climate(int(month)), "source": "open-meteo",
        "description": f"Климат и море {region.META['place_in']} по месяцу (модели Open-Meteo, 2022–2025).",
        "params": {"month": {"type": "integer"}},
        "returns": "air_max_c, air_min_c, precip_mm, rain_days, sunshine_h_per_day, sea_c, sea_c_min, sea_c_max, sea_c_by_decade[1–10, 11–20, 21–31]",
    },
}


_INV = None


def tag_inventory(top=140):
    """Какие теги реально есть в данных демо-зоны и сколько их: LLM выбирает теги из этого списка, а не по памяти."""
    global _INV
    if _INV is None:
        from collections import Counter
        from app import geodata as gd
        c = Counter()
        keys = ("amenity", "leisure", "tourism", "shop", "highway", "natural", "landuse", "healthcare", "railway",
                "historic", "man_made", "sport", "public_transport", "building")
        geo = gd.load()
        for e in list(geo.pois) + list(geo.ways):
            for k in keys:
                if k in e["tags"]:
                    c[f"{k}={e['tags'][k]}"] += 1
        _INV = ", ".join(f"{k} ({n})" for k, n in c.most_common(top))
    return _INV


def call(name, hotel_id, args=None):
    if name not in TOOLS:
        raise KeyError(f"нет инструмента {name}")
    return TOOLS[name]["fn"](hotel_id, **(args or {}))


def describe():
    lines = []
    for n, t in TOOLS.items():
        ps = ", ".join(f"{k}: {v.get('type')}" for k, v in t["params"].items()) or "—"
        lines.append(f"- {n}({ps}) [источник: {t['source']}]: {t['description']}\n  Результат: {t['returns']}")
    return "\n".join(lines)
