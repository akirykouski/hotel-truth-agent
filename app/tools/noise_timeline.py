"""Ночь по часам: тот же набор источников, что в noise.compute, но с суточным профилем у каждого.

Что откалибровано: у каждой стороны здания и каждого источника энергетический средний уровень (Leq) за 23–06
равен ночному уровню статической модели noise.compute (night_db). Профиль по часам задаёт только форму ночи
(трафик стихает к 3–4 утра, ж/д тише в 02–05 и громче в 23 и 06, бар шумит по opening_hours выбранного дня),
масштаб подгоняется под статическое число, поэтому ночное число факта night_quiet сохраняется. Сезонности нет:
месяц влияет только на формулировку, уровни от него не зависят. Всё, что считается как «среднее за ночь»,
считается энергетически (через 10^(L/10)), а не средним арифметическим дБ. Затухание фасад -> спальня и фон
спальни (20 дБ) не откалиброваны, это допущения.

Порог сна: в спальне ВОЗ (Guidelines for Community Noise, 1999) считает 30 дБ LAeq предельным для непрерывного
шума, это внутренний уровень, поэтому он применим к обеим позициям окна. Снаружи ему отвечает Lnight 40–45 дБ
(ВОЗ 2009/2018), при открытом окне (−10…15 дБ) это те же ~30 дБ внутри. Считаем часы выше 30 дБ внутри.
"""
import math

from app.tools import noise
from app.tools.noise import VENUE_DB, _collect, _facing
from app.tools.places import is_open
from app.tools import text

NIGHT = (23, 0, 1, 2, 3, 4, 5, 6)  # ночное окно: 23:00–07:00
THRESHOLD_INDOOR = 30.0
THRESHOLD_OUTDOOR = 45.0
WINDOW_DB = {"open": (10, 15), "closed": (25, 30)}  # затухание фасад -> спальня, дБ (min, max)
AMBIENT_INDOOR = 20.0  # фон тихой спальни: ниже внутри не бывает, даже если снаружи источников нет
# форма ночи ж/д, дБ относительно среднего: крайние пассажирские в 23:30 и 05:30, между ними товарные и редкие составы
RAIL_SHAPE = {23: 3.0, 0: 1.0, 1: -2.0, 2: -4.0, 3: -4.0, 4: -3.0, 5: 0.0, 6: 3.0}
DIR_FULL = {"С": "север", "СВ": "северо-восток", "В": "восток", "ЮВ": "юго-восток", "Ю": "юг", "ЮЗ": "юго-запад",
            "З": "запад", "СЗ": "северо-запад"}
DIR_ADJ = {"С": "северной", "СВ": "северо-восточной", "В": "восточной", "ЮВ": "юго-восточной", "Ю": "южной",
           "ЮЗ": "юго-западной", "З": "западной", "СЗ": "северо-западной"}
VENUE_RU = {"nightclub": "клуба", "bar": "бара", "pub": "паба", "karaoke_box": "караоке", "music_venue": "концертной площадки"}

# доля суточного трафика по часам, % (типичный городской профиль: минимум 2–5 ночи, пики 8 и 17–18)
TRAFFIC_SHARE = [1.2, 0.8, 0.6, 0.6, 0.9, 1.8, 3.7, 6.0, 7.0, 6.0, 5.5, 5.5, 5.6, 5.6, 5.6, 6.0, 6.6, 7.2, 6.8, 5.2,
                 3.7, 2.8, 2.2, 1.7]
_TRAFFIC_DB = [10 * math.log10(x) for x in TRAFFIC_SHARE]
_TRAFFIC_SHAPE = _TRAFFIC_DB  # форма; масштаб источнику задаёт калибровка по ночи (см. _calibrated)


def _rail_shape(h):
    return RAIL_SHAPE.get(h, 0.0)


def _venue_level(s, h, weekday):
    """Форма вечера бара или клуба в час h (абсолютный уровень до калибровки); после закрытия гости расходятся."""
    lvl = s["day_db"] + 10
    oh = s.get("hours")
    if not s.get("hours_known"):  # часов нет в OSM: как и в статической модели, считаем работающим до глубокой ночи
        opened = h >= 18 or h < 2
        return lvl if opened else lvl - 15
    if is_open(oh, weekday, h + 0.5):
        return lvl
    if is_open(oh, weekday if h > 0 else (weekday - 1) % 7, (h - 1) % 24 + 0.5):
        return lvl - 6
    return lvl - 15


def _raw(s, h, weekday):
    if s["kind"] == "ж/д":
        return _rail_shape(h)
    if s["kind"] in VENUE_DB:
        return _venue_level(s, h, weekday)
    return _TRAFFIC_SHAPE[h]


def _leq(levels):
    """Энергетическое среднее уровней, дБ."""
    levels = list(levels)
    return 10 * math.log10(sum(10 ** (v / 10) for v in levels) / len(levels))


def _calibrated(s, weekday):
    """24 часовых уровня источника; энергетическое среднее за 23–06 равно s['night_db'] (как в noise.compute)."""
    raw = [_raw(s, h, weekday) for h in range(24)]
    k = s["night_db"] - _leq(raw[h] for h in NIGHT)
    return [r + k for r in raw]


def _label(s):
    if s["kind"] == "ж/д":
        return "железной дороги"
    if s["kind"] in VENUE_DB:
        return VENUE_RU[s["kind"]] + (f" «{s['name']}»" if s.get("name") else "")
    return "дороги" + (f" ({s['name']})" if s.get("name") else "")


def _sum_db(levels):
    e = sum(10 ** (v / 10) for v in levels)
    return 10 * math.log10(e) if e > 0 else 30.0  # нет источников: тот же пол 30 дБ, что в noise.compute


def air_conditioning(hotel_id):
    """Есть ли кондиционер по карточке: в удобствах отеля или не меньше чем в половине категорий номеров."""
    r = text.card_search(hotel_id, ["air.?condition", "кондиционер"], where=("amenities", "rooms"))
    hotel_level = any(x["field"] == "удобства отеля" for x in r["hits"])
    share = r["rooms_matched"] / r["rooms_total"] if r["rooms_total"] else 0
    return {"has": hotel_level or share >= 0.5, "rooms_share": round(share, 2), "hotel_level": hotel_level,
            "quote": r["hits"][0]["quote"] if r["hits"] else None}


def _sleep(hours, offset, srcs_at):
    """Сводка сна для одной позиции окна: часы выше порога внутри, когда шумно и из-за чего."""
    inner = {h: max(AMBIENT_INDOOR, hours[h] - offset) for h in range(24)}
    noisy = [h for h in NIGHT if inner[h] > THRESHOLD_INDOOR]
    mean_in = _leq(inner[h] for h in NIGHT)  # энергетически: среднее арифметическое дБ занижает пики
    ev = [h for h in (22,) + NIGHT if inner[h] > THRESHOLD_INDOOR]  # с 22:00: вечерний хвост тоже мешает заснуть
    seq = [h for h in (22,) + NIGHT]
    run = []  # непрерывный шум с вечера
    for h in seq:
        if inner[h] > THRESHOLD_INDOOR:
            run.append(h)
        else:
            break
    until = (run[-1] + 1) % 24 if run and len(run) < len(seq) else None
    since = None  # непрерывный шум до утра (утренний трафик, первые электрички)
    tail = []
    for h in reversed(seq):
        if inner[h] > THRESHOLD_INDOOR:
            tail.append(h)
        else:
            break
    if tail and len(tail) < len(seq) and not run:
        since = tail[-1]
    cause = srcs_at(ev[-1] if ev else None)
    return {"hours_above": len(noisy), "noisy_hours": noisy, "night_mean_indoor": round(mean_in, 1),
            "at_floor": mean_in <= AMBIENT_INDOOR + 0.5,  # это фон спальни, а не измерение
            "night_max_indoor": round(max(inner[h] for h in NIGHT), 1), "noisy_until": until, "noisy_since": since,
            "cause": cause}


def _phrase(sl):
    n, until, since, cause = sl["hours_above"], sl["noisy_until"], sl["noisy_since"], sl["cause"]
    why = f" из-за {cause}" if cause else ""
    if n == 0:
        return "тихо всю ночь"
    if until is not None:
        return f"шумно до {until:02d}:00{why}"
    if since is not None:
        return f"тихо до {since:02d}:00, дальше шумно{why}"
    if n == len(NIGHT):
        return f"шумно всю ночь{why}"
    return f"шумно {n} из {len(NIGHT)} ночных часов{why}"


def build(hotel_id, month=7, weekday=5):
    """month принимается для совместимости: сезонности в модели нет, уровни от месяца не зависят."""
    month = min(12, max(1, int(month)))
    facades, sources = _collect(hotel_id)
    ac = air_conditioning(hotel_id)
    state = "closed" if ac["has"] else "open"
    out = []
    for f in facades:
        srcs = [s for s in sources if _facing(s, f)]
        prof = [(s, _calibrated(s, weekday)) for s in srcs]
        per_hour = {h: [(s, p[h]) for s, p in prof] for h in range(24)}
        hours = {h: round(_sum_db(l for _, l in per_hour[h]), 1) for h in range(24)}

        def cause(h, per_hour=per_hour):
            if h is None or not per_hour[h]:
                return None
            return _label(max(per_hour[h], key=lambda x: x[1])[0])

        mid = {k: (a + b) / 2 for k, (a, b) in WINDOW_DB.items()}
        out.append({
            "dir": f["dir"], "dir_name": DIR_FULL.get(f["dir"], f["dir"]), "az": f["az"], "hours": hours,
            "indoor_open": {h: round(max(AMBIENT_INDOOR, v - mid["open"]), 1) for h, v in hours.items()},
            "indoor_closed": {h: round(max(AMBIENT_INDOOR, v - mid["closed"]), 1) for h, v in hours.items()},
            "sleep": {k: _sleep(hours, mid[k], cause) for k in ("open", "closed")},
            "night_mean_outdoor": round(_leq(_sum_db(l for _, l in per_hour[h]) for h in NIGHT), 1),
            "rail_facing": any(s["kind"] == "ж/д" for s in srcs),
            "sources": len(srcs),
        })
    quiet = min(out, key=lambda f: f["night_mean_outdoor"])
    loud = max(out, key=lambda f: f["night_mean_outdoor"])
    for f in out:
        f["quietest"] = f is quiet
    rail = any(f["rail_facing"] for f in out)
    unknown = sum(1 for s in sources if s["kind"] in VENUE_DB and not s.get("hours_known"))
    unc = []
    if rail:
        unc.append("Ночью у железной дороги возможны товарные и ночные составы, их реальное расписание неизвестно: "
                   "в расчёте ожидаемый уровень, ночью он тише всего в 02–05.")
    if unknown:
        unc.append(f"У {unknown} баров и клубов нет часов работы в OpenStreetMap: считаем, что они шумят с 18:00 до 02:00.")
    unc.append("Не учтены дома, которые закрывают от шума. Насколько окно глушит шум, мы знаем с точностью ±2,5 дБ.")
    sides = [quiet] if quiet is loud else [loud, quiet]

    def advice_for(w):
        wtxt = "С закрытым окном" if w == "closed" else "С открытым окном"
        if w == state and ac["has"]:
            wtxt += " (в номерах есть кондиционер)"
        if len(sides) == 2 and all(f["sleep"][w]["hours_above"] == 0 for f in sides):
            return f"{wtxt} тихо всю ночь с обеих сторон."
        parts = [f"на {DIR_ADJ.get(f['dir'], f['dir'])} стороне {_phrase(f['sleep'][w])}" for f in sides]
        return f"{wtxt} " + "; ".join(parts) + "."

    advice = advice_for(state)
    return {
        "hotel_id": hotel_id, "month": month, "weekday": weekday, "facades": out,
        "quietest": quiet["dir"], "loudest": loud["dir"], "night_window": list(NIGHT),
        "threshold": {"indoor_db": THRESHOLD_INDOOR, "outdoor_db": THRESHOLD_OUTDOOR,
                      "why": "ВОЗ: в спальне ночью не громче 30 дБ",
                      "basis": "ВОЗ: 30 дБ LAeq в спальне (1999), снаружи Lnight 40–45 дБ; порог внутри, "
                               "потому что окно меняет уровень на 10–30 дБ",
                      "search_quiet_outdoor_db": 55},
        "window_loss_db": WINDOW_DB, "air_conditioning": ac, "window_assumed": state,
        "advice": advice, "advice_by_window": {w: advice_for(w) for w in ("open", "closed")}, "uncertainty": unc,
        "search_quiet": quiet["night_mean_outdoor"] < 55,  # определение «тихо» в поиске: снаружи ночью < 55 дБ
        "quiet_hours_above": {k: quiet["sleep"][k]["hours_above"] for k in ("open", "closed")},
        "quiet_hours_above_assumed": quiet["sleep"][state]["hours_above"],
        "method": "Дороги, железная дорога, бары и клубы из OpenStreetMap. Машины по часам суток, поезда по пассажирскому расписанию, бары по часам работы.",
    }
