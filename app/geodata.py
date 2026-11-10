"""Геоданные демо-зоны: отели, вырезка OSM, карта высот, растр зданий.

Всё грузится один раз и кэшируется в памяти. Координаты внутри считаются в локальной плоской системе
в метрах (равнопромежуточная проекция вокруг центра зоны): на 10 км ошибка меньше 0,1%.
"""
import gzip
import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from app import region

DATA = region.DATA  # data/ для демо-зоны или data/regions/<REGION>/
LAT0, LON0 = region.META["center"]
KY = 110_540.0
KX = 111_320.0 * math.cos(math.radians(LAT0))
CELL = 10.0  # шаг растра зданий, м
FLOOR_M = 3.0

# Неопределённость высоты здания (сигма, м) в зависимости от того, откуда она взята.
HEIGHT_SIGMA = {"height": 1.5, "levels": 3.0, "default": 6.0}
DEFAULT_LEVELS = {"house": 2, "detached": 2, "garage": 1, "garages": 1, "shed": 1, "roof": 1, "kiosk": 1,
                  "apartments": 6, "hotel": 5, "residential": 4, "commercial": 3, "retail": 2}


def to_xy(lat, lon):
    return (np.asarray(lon) - LON0) * KX, (np.asarray(lat) - LAT0) * KY


def to_latlon(x, y):
    return LAT0 + np.asarray(y) / KY, LON0 + np.asarray(x) / KX


def bearing(dx, dy):
    """Азимут в градусах от севера по часовой стрелке."""
    return (math.degrees(math.atan2(dx, dy)) + 360) % 360


DIRS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]


def dir_name(az):
    return DIRS[int(((az + 22.5) % 360) // 45)]


def _num(s):
    m = re.match(r"\s*([0-9]+(?:[.,][0-9]+)?)", str(s or ""))
    return float(m.group(1).replace(",", ".")) if m else None


def _load_osm(name):
    with gzip.open(DATA / "osm" / f"{name}.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Building:
    idx: int
    osm_id: int
    xy: np.ndarray            # (N, 2) контур в метрах
    height: float             # м
    source: str               # height | levels | default
    levels: int | None
    tags: dict = field(repr=False)


@dataclass
class Geo:
    hotels: list
    hotel_by_id: dict
    buildings: list
    b_heights: np.ndarray     # высоты зданий по индексу
    b_sigma: np.ndarray       # сигма высоты по индексу
    grid_bid: np.ndarray      # растр: индекс здания или -1
    grid_x0: float
    grid_y0: float
    dem_dtm: np.ndarray
    dem_sea: np.ndarray
    dem_extra: np.ndarray     # DSM − рельеф: деревья и здания, которых нет в OSM (снимки 2010–2015)
    dem_meta: dict
    ways: list
    pois: list
    beaches: list
    osm_meta: dict


def _building_height(tags):
    h = _num(tags.get("height"))
    if h:
        return h, "height", int(_num(tags.get("building:levels")) or round(h / FLOOR_M))
    lv = _num(tags.get("building:levels"))
    if lv:
        return lv * FLOOR_M + 1.0, "levels", int(lv)
    lv = DEFAULT_LEVELS.get(tags.get("building"), 3)
    return lv * FLOOR_M + 1.0, "default", None


def _rasterize(buildings, x0, y0, nx, ny):
    """Растеризация контуров зданий: центр клетки внутри полигона (чёт-нечет)."""
    grid = np.full((ny, nx), -1, dtype=np.int32)
    for b in buildings:
        px, py = b.xy[:, 0], b.xy[:, 1]
        c0, c1 = int((px.min() - x0) // CELL), int((px.max() - x0) // CELL) + 1
        r0, r1 = int((py.min() - y0) // CELL), int((py.max() - y0) // CELL) + 1
        c0, r0 = max(c0, 0), max(r0, 0)
        c1, r1 = min(c1, nx - 1), min(r1, ny - 1)
        if c1 < c0 or r1 < r0:
            continue
        cx = x0 + (np.arange(c0, c1 + 1) + 0.5) * CELL
        cy = y0 + (np.arange(r0, r1 + 1) + 0.5) * CELL
        X, Y = np.meshgrid(cx, cy)
        inside = np.zeros(X.shape, dtype=bool)
        xj, yj = np.roll(px, 1), np.roll(py, 1)
        for xi_, yi_, xj_, yj_ in zip(px, py, xj, yj):
            if yi_ == yj_:
                continue
            cond = (yi_ > Y) != (yj_ > Y)
            xint = (xj_ - xi_) * (Y - yi_) / (yj_ - yi_) + xi_
            inside ^= cond & (X < xint)
        if not inside.any():  # маленькое здание меньше клетки: ставим в клетку центра
            mx, my = px.mean(), py.mean()
            r, c = int((my - y0) // CELL), int((mx - x0) // CELL)
            if 0 <= r < ny and 0 <= c < nx:
                grid[r, c] = b.idx
            continue
        sub = grid[r0:r1 + 1, c0:c1 + 1]
        sub[inside] = b.idx
    return grid


@lru_cache(maxsize=1)
def load() -> Geo:
    hd = json.loads((DATA / "hotels.json").read_text(encoding="utf-8"))
    hotels = hd["hotels"]
    for h in hotels:
        h["x"], h["y"] = (float(v) for v in to_xy(h["lat"], h["lon"]))

    bl = _load_osm("buildings")
    buildings = []
    for e in bl["elements"]:
        g = e.get("geometry") or []
        if len(g) < 4:
            continue
        x, y = to_xy([p["lat"] for p in g], [p["lon"] for p in g])
        hgt, src, lv = _building_height(e["tags"])
        buildings.append(Building(len(buildings), e["id"], np.column_stack([x, y]), hgt, src, lv, e["tags"]))
    s, w, n, ea = bl["meta"]["bbox"]
    x0, y0 = (float(v) for v in to_xy(s, w))
    x1, y1 = (float(v) for v in to_xy(n, ea))
    nx, ny = int((x1 - x0) // CELL) + 1, int((y1 - y0) // CELL) + 1
    cache = DATA / "cache" / "buildings_grid.npz"
    if cache.exists():
        grid = np.load(cache)["grid"]
    else:
        grid = _rasterize(buildings, x0, y0, nx, ny)
        cache.parent.mkdir(exist_ok=True)
        np.savez_compressed(cache, grid=grid)

    dem = np.load(DATA / "dem.npz")
    dsm = dem["dsm"].astype(np.float32)
    dtm = dem["dtm"].astype(np.float32)
    dem_meta = {k: float(dem[k]) for k in ("north", "west", "dlat", "dlon")}
    dem_meta["source"] = str(dem["source"])
    sea = (dsm <= 0.2) & (dtm <= 0.2)

    ways = _load_osm("ways")
    pl = _load_osm("pois")
    pois = []
    for e in pl["elements"]:
        if e["type"] == "node":
            lat, lon = e["lat"], e["lon"]
        elif e.get("geometry"):
            lat = sum(p["lat"] for p in e["geometry"]) / len(e["geometry"])
            lon = sum(p["lon"] for p in e["geometry"]) / len(e["geometry"])
        elif e.get("bounds"):
            b = e["bounds"]
            lat, lon = (b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2
        else:
            continue
        x, y = to_xy(lat, lon)
        pois.append({"id": f"{e['type']}/{e['id']}", "lat": lat, "lon": lon, "x": float(x), "y": float(y),
                     "tags": e["tags"]})
    wl = _load_osm("water")
    beaches = []
    for e in wl["elements"]:
        if e["tags"].get("natural") != "beach":
            continue
        geoms = [e["geometry"]] if e.get("geometry") else [m["geometry"] for m in e.get("members", []) if m.get("geometry")]
        for g in geoms:
            x, y = to_xy([p["lat"] for p in g], [p["lon"] for p in g])
            beaches.append({"id": f"{e['type']}/{e['id']}", "name": e["tags"].get("name"),
                            "xy": np.column_stack([x, y])})
    geo = Geo(hotels=hotels, hotel_by_id={h["id"]: h for h in hotels}, buildings=buildings,
               b_heights=np.array([b.height for b in buildings], dtype=np.float32),
               b_sigma=np.array([HEIGHT_SIGMA[b.source] for b in buildings], dtype=np.float32),
               grid_bid=grid, grid_x0=x0, grid_y0=y0, dem_dtm=dtm, dem_sea=sea, dem_meta=dem_meta,
               dem_extra=np.clip(dsm - dtm, 0, 30).astype(np.float32),
               ways=ways["elements"], pois=pois, beaches=beaches,
               osm_meta={"osm_base": bl["meta"].get("osm_base"), "fetched_at": bl["meta"].get("fetched_at"),
                         "source": bl["meta"].get("source")})
    from app.refresh import load_simulated  # симулированные новые здания (демо актуализации)
    load_simulated(geo)
    return geo


def dem_index(geo, lat, lon):
    m = geo.dem_meta
    r = ((m["north"] - np.asarray(lat)) / m["dlat"]).astype(int)
    c = ((np.asarray(lon) - m["west"]) / m["dlon"]).astype(int)
    h, w = geo.dem_dtm.shape
    ok = (r >= 0) & (r < h) & (c >= 0) & (c < w)
    return np.clip(r, 0, h - 1), np.clip(c, 0, w - 1), ok


def ground(geo, lat, lon):
    r, c, ok = dem_index(geo, lat, lon)
    return np.where(ok, geo.dem_dtm[r, c], 0.0)


def building_at(geo, x, y):
    r = int((y - geo.grid_y0) // CELL)
    c = int((x - geo.grid_x0) // CELL)
    if 0 <= r < geo.grid_bid.shape[0] and 0 <= c < geo.grid_bid.shape[1]:
        return int(geo.grid_bid[r, c])
    return -1


@lru_cache(maxsize=4096)
def hotel_building(hotel_id):
    """Здание отеля: контур, в который попадает точка, иначе ближайший контур в 40 м."""
    geo = load()
    h = geo.hotel_by_id[hotel_id]
    bid = building_at(geo, h["x"], h["y"])
    how = "точка внутри контура"
    if bid < 0:
        best, bd = -1, 40.0
        for dr in range(-4, 5):
            for dc in range(-4, 5):
                cand = building_at(geo, h["x"] + dc * CELL, h["y"] + dr * CELL)
                if cand >= 0:
                    d = math.hypot(dc * CELL, dr * CELL)
                    if d < bd:
                        best, bd = cand, d
        bid, how = best, (f"ближайший контур в {bd:.0f} м" if best >= 0 else "контур не найден")
    return bid, how
