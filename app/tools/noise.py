"""Шум по сторонам здания днём и ночью.

Модель простая и объяснимая: у каждого источника условный уровень на 10 м (дБ), затухание 20·lg(d/10)
для точечных и 10·lg(d/10) для линейных (дороги, ж/д, взлётные полосы: те слышны со всех сторон здания, до 1,5 км). Ночью трафик тише на 7 дБ, бары и клубы шумят,
только если по opening_hours открыты после 23:00. Источник учитывается для стороны здания, если он
перед ней (±90° от нормали). Уровни складываются энергетически. Здания-экраны не учитываются, поэтому
уверенность средняя; калибровать можно по жалобам в отзывах.
"""
import math

import numpy as np
from shapely.geometry import LineString, Point

from app import geodata as gd
from app.tools.places import is_open
from app.tools.view import _facades

ROAD_DB = {"trunk": 75, "trunk_link": 70, "primary": 72, "primary_link": 68, "secondary": 68, "secondary_link": 64,
           "tertiary": 63, "tertiary_link": 60, "unclassified": 58, "residential": 55}
RAIL_DB = 74
AIR_DB = 88  # взлётная полоса (aeroway=runway): шумит дальше дорог, поэтому свой радиус
AIR_RADIUS = 1500
NIGHT_TRAFFIC = -7
VENUE_DB = {"nightclub": 80, "bar": 70, "pub": 70, "karaoke_box": 74, "music_venue": 76}
RADIUS = 400


def _segments():
    geo = gd.load()
    segs = []
    for e in geo.ways:
        t = e["tags"]
        kind = "rail" if t.get("railway") == "rail" else "runway" if t.get("aeroway") == "runway" else t.get("highway")
        if kind not in ("rail", "runway") and kind not in ROAD_DB:
            continue
        g = e.get("geometry") or []
        if len(g) < 2:
            continue
        x, y = gd.to_xy([p["lat"] for p in g], [p["lon"] for p in g])
        segs.append((kind, t.get("name"), LineString(np.column_stack([x, y])), t.get("tunnel") not in (None, "no")))
    return segs


_SEGS = None


def _collect(hotel_id):
    """Стороны здания и источники шума вокруг отеля (общая часть compute и timeline)."""
    global _SEGS
    if _SEGS is None:
        _SEGS = _segments()
    geo = gd.load()
    h = geo.hotel_by_id[hotel_id]
    bid, _ = gd.hotel_building(hotel_id)
    b = geo.buildings[bid] if bid >= 0 else None
    facades = _facades(b)
    here = Point(h["x"], h["y"])
    sources = []
    for kind, name, line, tunnel in _SEGS:
        if tunnel:
            continue
        d = line.distance(here)
        if d > (AIR_RADIUS if kind == "runway" else RADIUS):
            continue
        p = line.interpolate(line.project(here))
        az = gd.bearing(p.x - h["x"], p.y - h["y"])
        base = RAIL_DB if kind == "rail" else AIR_DB if kind == "runway" else ROAD_DB[kind]
        lvl = base - 10 * math.log10(max(d, 10) / 10)
        label = "ж/д" if kind == "rail" else "аэропорт" if kind == "runway" else f"дорога {kind}"
        sources.append({"kind": label, "name": name, "distance_m": round(d),
                        "az": round(az), "day_db": lvl, "night_db": lvl + (0 if kind == "rail" else NIGHT_TRAFFIC),
                        "omni": kind == "runway"})  # самолёт шумит сверху: слышно со всех сторон здания
    for p in geo.pois:
        a = p["tags"].get("amenity")
        if a not in VENUE_DB:
            continue
        d = math.hypot(p["x"] - h["x"], p["y"] - h["y"])
        if d > RADIUS:
            continue
        oh = p["tags"].get("opening_hours")
        late = is_open(oh, 4, 23.5)
        lvl = VENUE_DB[a] - 20 * math.log10(max(d, 10) / 10)
        sources.append({"kind": a, "name": p["tags"].get("name"), "distance_m": round(d),
                        "az": round(gd.bearing(p["x"] - h["x"], p["y"] - h["y"])),
                        "day_db": lvl - 10, "night_db": lvl if late is not False else lvl - 15,
                        "hours": oh, "hours_known": late is not None})
    # один источник = одна дорога или линия ж/д: OSM режет их на много кусков, берём ближайший кусок
    best = {}
    for s in sources:
        k = (s["kind"], s["name"] or (s["kind"] if s["kind"] == "ж/д" else f"{s['kind']}@{s['az'] // 45}"))
        if k not in best or s["night_db"] > best[k]["night_db"]:
            best[k] = s
    return facades, list(best.values())


def _facing(s, f):
    """Источник перед стороной здания: ±90° от нормали."""
    return bool(s.get("omni")) or abs((s["az"] - f["az"] + 540) % 360 - 180) <= 90


def compute(hotel_id):
    facades, sources = _collect(hotel_id)
    out = []
    for f in facades:
        def total(key):
            e = sum(10 ** (s[key] / 10) for s in sources if _facing(s, f))
            return round(10 * math.log10(e), 1) if e > 0 else 30.0
        out.append({"dir": f["dir"], "az": f["az"], "day_db": total("day_db"), "night_db": total("night_db")})
    quiet = min(out, key=lambda f: f["night_db"])
    loud = max(out, key=lambda f: f["night_db"])
    top = sorted(sources, key=lambda s: -s["night_db"])[:4]
    unknown_venues = sum(1 for s in sources if s["kind"] in VENUE_DB and not s.get("hours_known"))
    return {
        "facades": out, "quietest": quiet, "loudest": loud,
        "night_level": "тихо" if quiet["night_db"] < 50 else "умеренно" if quiet["night_db"] < 58 else "шумно",
        "night_level_loud_side": "тихо" if loud["night_db"] < 50 else "умеренно" if loud["night_db"] < 58 else "шумно",
        "top_sources": [{k: (round(v) if isinstance(v, float) else v) for k, v in s.items() if k != "omni"}
                        for s in top],
        "venues_unknown_hours": unknown_venues,
        "method": "дороги и ж/д OSM по классу + бары/клубы с часами работы, затухание с расстоянием, без экранов",
    }


def timeline(hotel_id, month=7, weekday=5):
    """Шум по часам суток для каждой стороны здания (см. noise_timeline.py)."""
    from app.tools import noise_timeline
    return noise_timeline.build(hotel_id, int(month), int(weekday))
