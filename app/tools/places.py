"""Что рядом с отелем по тегам OSM и что открыто в нужный час (по opening_hours)."""
import math
import re

import numpy as np

from app import geodata as gd

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def match_tags(tags, want):
    """want: {"amenity": "pharmacy|bar", "leisure": "*", "name": "~[Нн]абережн"}; значения через | — любое из них,
    * — любое, ~ в начале — поиск по подстроке (регулярное выражение, без учёта регистра)."""
    for k, v in want.items():
        tv = tags.get(k)
        if tv is None:
            return False
        v = "|".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)  # список значений = любое из них
        if v == "*":
            continue
        if v.startswith("~"):
            if not re.search(v[1:], tv, re.I):
                return False
        elif tv not in v.split("|"):
            return False
    return True


_WAYS = None


def _ways():
    """Линии OSM (дороги, тропы, ж/д, пляжи) как наборы вершин: для nearby по линейным объектам."""
    global _WAYS
    if _WAYS is None:
        geo = gd.load()
        _WAYS = []
        for e in geo.ways:
            g = e.get("geometry") or []
            if len(g) < 2:
                continue
            x, y = gd.to_xy([q["lat"] for q in g], [q["lon"] for q in g])
            _WAYS.append({"id": f"way/{e['id']}", "tags": e["tags"], "x": np.asarray(x), "y": np.asarray(y)})
        for b in geo.beaches:
            _WAYS.append({"id": b["id"], "tags": {"natural": "beach", **({"name": b["name"]} if b["name"] else {})},
                          "x": b["xy"][:, 0], "y": b["xy"][:, 1]})
    return _WAYS


def _days(spec):
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            if a in DAYS and b in DAYS:
                i, j = DAYS.index(a), DAYS.index(b)
                rng = range(i, j + 1) if i <= j else list(range(i, 7)) + list(range(0, j + 1))
                out.update(rng)
        elif part in DAYS:
            out.add(DAYS.index(part))
    return out


def is_open(oh, weekday, hour):
    """True/False, или None если строку не поняли. Понимает 24/7, «Mo-Fr 09:00-21:00; Sa off», ночные интервалы."""
    if not oh:
        return None
    oh = oh.strip()
    if oh == "24/7":
        return True
    result = None
    for rule in oh.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        m = re.match(r"^((?:[A-Z][a-z](?:-[A-Z][a-z])?,?\s*)+)?\s*(.*)$", rule)
        days = _days(m.group(1).replace(" ", "")) if m.group(1) else set(range(7))
        times = m.group(2).strip()
        if times in ("off", "closed"):
            if weekday in days:
                result = False
            continue
        if times in ("24/7", "00:00-24:00"):
            if weekday in days:
                result = True
            continue
        spans = re.findall(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", times)
        if not spans:
            continue
        for h1, m1, h2, m2 in spans:
            a, b = int(h1) + int(m1) / 60, int(h2) + int(m2) / 60
            if b <= a:  # через полночь
                if (weekday in days and hour >= a) or (((weekday - 1) % 7) in days and hour < b):
                    return True
            elif weekday in days and a <= hour < b:
                return True
        if weekday in days and result is None:
            result = False
    return result


def nearby(hotel_id, tags, radius_m=500, open_at=None, limit=10):
    """Объекты OSM с нужными тегами в радиусе (по прямой). open_at = (день недели 0–6, час)."""
    geo = gd.load()
    h = geo.hotel_by_id[hotel_id]
    found, unknown_hours = [], 0
    for p in geo.pois:
        if not match_tags(p["tags"], tags):
            continue
        d = math.hypot(p["x"] - h["x"], p["y"] - h["y"])
        if d > radius_m:
            continue
        item = {"name": p["tags"].get("name") or p["tags"].get("amenity") or p["tags"].get("leisure") or p["tags"].get("shop"),
                "distance_m": round(d), "osm": p["id"], "opening_hours": p["tags"].get("opening_hours")}
        if open_at is not None:
            st = is_open(item["opening_hours"], *open_at)
            if st is None:
                unknown_hours += 1
                continue
            if not st:
                continue
        found.append(item)
    if True:  # линии (улицы, тропы, пляжи) часов работы не имеют: учитываем их всегда
        seen = set()
        for w in _ways():
            if not match_tags(w["tags"], tags):
                continue
            d = float(np.min(np.hypot(w["x"] - h["x"], w["y"] - h["y"])))
            if d > radius_m:
                continue
            name = w["tags"].get("name") or w["tags"].get("highway") or w["tags"].get("natural")
            if name in seen:  # одна улица в OSM — много кусков, берём ближайший
                continue
            seen.add(name)
            found.append({"name": name, "distance_m": round(d), "osm": w["id"], "opening_hours": None})
    found.sort(key=lambda r: r["distance_m"])
    return {"count": len(found), "nearest_m": found[0]["distance_m"] if found else None,
            "items": found[:limit], "unknown_hours": unknown_hours, "radius_m": radius_m}
