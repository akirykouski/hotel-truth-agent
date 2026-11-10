"""Вид из окна: море и закат по сторонам здания и этажам.

Метод. Из точки окна (центр здания отеля, высота = рельеф + (этаж − 1) × 3 м + 1,5 м) пускаем лучи
через каждые 2° на 8 км. Препятствия: рельеф (Copernicus GLO-30, срезанный до земли) плюс здания OSM
с их высотой, с поправкой на кривизну Земли и рефракцию. Море — клетки карты высот с отметкой 0.
Клетка моря видна, если угол на неё круче, чем на все препятствия перед ней.

Уверенность. Высоты зданий неточные: из тега height ±1,5 м, из этажности ±3 м, без данных ±6 м.
Пересчитываем всё 24 раза со случайными высотами соседей (Монте-Карло) и смотрим, в какой доле прогонов
вывод тот же. Это устойчивость вывода к ошибкам данных, а не вероятность правды; калибруем на разметке.
"""
import math
from functools import lru_cache

import numpy as np
from shapely.geometry import Polygon

from app import geodata as gd
from app.tools.sun import sunset_azimuth

STEP_DEG = 2
AZ = np.arange(0, 360, STEP_DEG, dtype=np.float32)
DIST = np.concatenate([np.arange(10, 1500, 10), np.arange(1500, 8000, 40)]).astype(np.float32)
CURV = DIST ** 2 / (2 * 6_371_000) * 0.87
SEA_MIN_DEG = 10      # меньше 10° моря по горизонту — это «краешек», не вид
FAN = 70              # окно на стене видит ±70° от нормали стены
MC_RUNS = 24
MAX_UNKNOWN_FLOORS = 9
VEG_NOMINAL = 0.7     # деревья в DSM сняты с кроной и в разные сезоны: берём 70% высоты, в Монте-Карло 40–100%


def _facades(b):
    """4 стороны здания по минимальному описанному прямоугольнику; нормали наружу."""
    if b is None:
        return [{"az": float(a), "dir": gd.dir_name(a)} for a in range(0, 360, 45)]
    rect = Polygon(b.xy).minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    cx, cy = np.mean(xs[:-1]), np.mean(ys[:-1])
    out = []
    for i in range(4):
        mx, my = (xs[i] + xs[i + 1]) / 2, (ys[i] + ys[i + 1]) / 2
        az = gd.bearing(mx - cx, my - cy)
        out.append({"az": round(az), "dir": gd.dir_name(az), "length_m": round(math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]))})
    return out


def _fan_mask(az0):
    d = (AZ - az0 + 540) % 360 - 180
    return np.abs(d) <= FAN


@lru_cache(maxsize=512)
def _profile(hotel_id):
    """Что лежит вдоль каждого луча: рельеф, индекс здания, море."""
    geo = gd.load()
    h = geo.hotel_by_id[hotel_id]
    bid, how = gd.hotel_building(hotel_id)
    b = geo.buildings[bid] if bid >= 0 else None
    if b is not None:
        cx, cy = float(b.xy[:, 0].mean()), float(b.xy[:, 1].mean())
    else:
        cx, cy = h["x"], h["y"]
    rad = np.radians(AZ)[:, None]
    X = cx + DIST[None, :] * np.sin(rad)
    Y = cy + DIST[None, :] * np.cos(rad)
    lat, lon = gd.to_latlon(X, Y)
    r, c, ok = gd.dem_index(geo, lat, lon)
    ground = np.where(ok, geo.dem_dtm[r, c], 0.0).astype(np.float32)
    # деревья и неразмеченные в OSM здания: превышение DSM над рельефом, только вне контуров OSM и дальше 30 м
    extra = np.where(ok, geo.dem_extra[r, c], 0.0).astype(np.float32)
    extra[:, DIST < 30] = 0.0
    sea = np.where(ok, geo.dem_sea[r, c], False)
    gr = ((Y - geo.grid_y0) // gd.CELL).astype(int)
    gc = ((X - geo.grid_x0) // gd.CELL).astype(int)
    inside = (gr >= 0) & (gr < geo.grid_bid.shape[0]) & (gc >= 0) & (gc < geo.grid_bid.shape[1])
    bids = np.where(inside, geo.grid_bid[np.clip(gr, 0, geo.grid_bid.shape[0] - 1),
                                         np.clip(gc, 0, geo.grid_bid.shape[1] - 1)], -1)
    if bid >= 0:
        bids[bids == bid] = -1
    sea &= bids < 0
    extra[bids >= 0] = 0.0
    extra[sea] = 0.0
    g0 = float(gd.ground(geo, h["lat"], h["lon"]))
    return b, how, g0, ground, sea, bids, extra


def _run(ground, sea, bids, heights, eyes, extra=None, veg=VEG_NOMINAL):
    """Для набора высот глаза: какие лучи видят море, и угол горизонта по каждому лучу."""
    bh = np.where(bids >= 0, heights[np.clip(bids, 0, None)], 0.0)
    if extra is not None:
        bh = np.maximum(bh, extra * veg)
    obst = ground + bh - CURV[None, :]
    seas, horiz = [], []
    for e in eyes:
        t = (obst - e) / DIST[None, :]
        prev = np.maximum.accumulate(t, axis=1)
        prev = np.concatenate([np.full((t.shape[0], 1), -np.inf, dtype=np.float32), prev[:, :-1]], axis=1)
        tsea = (-CURV[None, :] - e) / DIST[None, :]
        vis = sea & (tsea > prev)
        seas.append(vis.any(axis=1))
        horiz.append(np.degrees(np.arctan(np.maximum(prev[:, -1], t[:, -1]))))
    return np.array(seas), np.array(horiz)


@lru_cache(maxsize=512)
def compute(hotel_id, months=tuple(range(1, 13))):
    geo = gd.load()
    b, how, g0, ground, sea, bids, extra = _profile(hotel_id)
    if b is not None and b.levels:
        levels, lv_src = b.levels, ("тег height" if b.source == "height" else "тег building:levels") + " в OSM"
    else:
        levels, lv_src = MAX_UNKNOWN_FLOORS, "этажность в OSM не указана, считаем до 9-го этажа"
    floors = np.arange(1, levels + 1)
    eyes = g0 + (floors - 1) * gd.FLOOR_M + 1.5
    facades = _facades(b)
    masks = [_fan_mask(f["az"]) for f in facades]

    rng = np.random.default_rng(int(hotel_id) % 2**32)
    sea_runs = []   # [run][floor][ray]
    hor_nominal = None
    for k in range(MC_RUNS):
        hts = geo.b_heights if k == 0 else np.maximum(
            geo.b_heights + geo.b_sigma * rng.standard_normal(len(geo.b_heights)).astype(np.float32), 2.0)
        veg = VEG_NOMINAL if k == 0 else float(rng.uniform(0.4, 1.0))
        s, hz = _run(ground, sea, bids, hts, eyes, extra, veg)
        sea_runs.append(s)
        if k == 0:
            hor_nominal = hz
    sea_runs = np.array(sea_runs)                       # (runs, floors, rays)

    out_f = []
    for f, m in zip(facades, masks):
        deg = sea_runs[:, :, m].sum(axis=2) * STEP_DEG    # (runs, floors)
        ok = deg >= SEA_MIN_DEG
        nominal = ok[0]
        from_floor = int(floors[nominal.argmax()]) if nominal.any() else None
        p_by_floor = ok.mean(axis=0)
        # уверенность в выводе про эту сторону: доля прогонов, где первый этаж с видом тот же ±1
        runs_ff = [int(floors[r.argmax()]) if r.any() else None for r in ok]
        if from_floor is None:
            conf = float(np.mean([x is None for x in runs_ff]))
        else:
            conf = float(np.mean([x is not None and abs(x - from_floor) <= 1 for x in runs_ff]))
        out_f.append({**f, "sea_from_floor": from_floor, "confidence": round(conf, 2),
                      "sea_deg_top_floor": int(deg[0, -1]),
                      "p_sea_by_floor": {int(fl): round(float(p), 2) for fl, p in zip(floors, p_by_floor)}})

    with_sea = [f for f in out_f if f["sea_from_floor"]]
    best = min(with_sea, key=lambda f: (f["sea_from_floor"], -f["confidence"])) if with_sea else None
    any_top = sea_runs[:, -1, :].reshape(MC_RUNS, -1)
    p_any = float(np.mean([any(((r[m].sum() * STEP_DEG) >= SEA_MIN_DEG) for m in masks) for r in any_top]))

    sunset = {}
    for mo in months:
        az = sunset_azimuth(mo)
        ray = int(round(az / STEP_DEG)) % len(AZ)
        best_s = None
        for f, m in zip(facades, masks):
            if not m[ray]:
                continue
            clear = hor_nominal[:, ray] <= 1.0
            if clear.any():
                fl = int(floors[clear.argmax()])
                over_sea = bool(sea_runs[0, clear.argmax(), ray])
                if best_s is None or fl < best_s["from_floor"]:
                    best_s = {"facade": f["dir"], "from_floor": fl, "over_sea": over_sea}
        sunset[mo] = {"azimuth": round(az), **(best_s or {"facade": None, "from_floor": None, "over_sea": False})}

    drivers = _drivers(geo, sea, bids, ground + extra * VEG_NOMINAL, eyes[-1], masks)
    return {
        "hotel_id": hotel_id,
        "building": {"osm_id": b.osm_id if b else None, "match": how, "levels": levels, "levels_source": lv_src,
                     "ground_m": round(g0, 1)},
        "facades": out_f,
        "sea_view": {"possible": best is not None, "facade": best["dir"] if best else None,
                     "from_floor": best["sea_from_floor"] if best else None,
                     "confidence": best["confidence"] if best else round(1 - p_any, 2),
                     "p_any_top_floor": round(p_any, 2)},
        "sunset": sunset,
        "uncertainty_drivers": drivers,
        "method": "лучи по DEM Copernicus GLO-30 + здания OSM + деревья из DSM, 2°, до 8 км, Монте-Карло 24 прогона",
        "inputs": {"osm_base": geo.osm_meta["osm_base"], "dem": "Copernicus GLO-30 (2010–2015)"},
    }


def _drivers(geo, sea, bids, ground, eye, masks):
    """Какие здания закрывают море с верхнего этажа и насколько неточна их высота: кандидаты на проверку."""
    fan = np.zeros(len(AZ), dtype=bool)
    for m in masks:
        fan |= m
    bh = np.where(bids >= 0, geo.b_heights[np.clip(bids, 0, None)], 0.0)
    t = (ground + bh - CURV[None, :] - eye) / DIST[None, :]
    counts = {}
    for r in np.where(fan & sea.any(axis=1))[0]:
        first_sea = int(sea[r].argmax())
        if first_sea == 0:
            continue
        j = int(t[r, :first_sea].argmax())
        bid = int(bids[r, j])
        if bid >= 0:
            counts[bid] = counts.get(bid, 0) + STEP_DEG
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    out = []
    for bid, deg in top:
        b = geo.buildings[bid]
        lat, lon = gd.to_latlon(b.xy[:, 0].mean(), b.xy[:, 1].mean())
        out.append({"osm_id": b.osm_id, "blocks_deg": deg, "height_m": round(b.height, 1), "height_source": b.source,
                    "address": " ".join(filter(None, [b.tags.get("addr:street"), b.tags.get("addr:housenumber")])) or None,
                    "lat": round(float(lat), 6), "lon": round(float(lon), 6)})
    return out
