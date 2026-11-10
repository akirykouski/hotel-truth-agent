"""Актуализация: пересчёт устаревших фактов и реакция на изменение мира («рядом построили дом»).

Каждый вычисленный факт знает, из каких данных он получен, поэтому при изменении данных пересчитываются только
затронутые отели. Изменился вывод — старый факт уходит в историю, отельеру ставится вопрос, событие в журнале.
"""
import json
import math
import os
from pathlib import Path
from datetime import datetime, timezone

import numpy as np

from app import geodata as gd
from app import registry, store
from app.tools import view

SIM_FILE = Path(os.getenv("SIM_FILE") or gd.DATA / "cache" / "sim_buildings.json")
AFFECTED_M = 1200


def _apply(geo, lat, lon, levels, radius_m):
    x, y = (float(v) for v in gd.to_xy(lat, lon))
    ang = np.linspace(0, 2 * math.pi, 13)
    xy = np.column_stack([x + radius_m * np.cos(ang), y + radius_m * np.sin(ang)])
    b = gd.Building(len(geo.buildings), -len(geo.buildings), xy, levels * gd.FLOOR_M + 1, "height", levels,
                    {"building": "apartments", "name": "новый дом (симуляция)"})
    geo.buildings.append(b)
    geo.b_heights = np.append(geo.b_heights, np.float32(b.height))
    geo.b_sigma = np.append(geo.b_sigma, np.float32(gd.HEIGHT_SIGMA["height"]))
    cells = gd._rasterize([b], geo.grid_x0, geo.grid_y0, geo.grid_bid.shape[1], geo.grid_bid.shape[0])
    geo.grid_bid[cells >= 0] = b.idx
    return x, y


def add_building(lat, lon, levels=16, radius_m=25):
    geo = gd.load()
    x, y = _apply(geo, lat, lon, levels, radius_m)
    sims = json.loads(SIM_FILE.read_text()) if SIM_FILE.exists() else []
    sims.append({"lat": lat, "lon": lon, "levels": levels, "radius_m": radius_m})
    SIM_FILE.parent.mkdir(exist_ok=True)
    SIM_FILE.write_text(json.dumps(sims))
    view._profile.cache_clear()
    view.compute.cache_clear()
    affected = [h for h in geo.hotels if math.hypot(h["x"] - x, h["y"] - y) <= AFFECTED_M]
    changes = []
    for h in affected:
        for cid in ("sea_view", "sunset"):
            spec = registry.get(cid)
            before = store.resolve(h["id"], spec)
            geo_before = next((f for f in before["facts"] if f["source"] == "geo"), None)
            registry.compute(cid, h["id"])
            after = store.resolve(h["id"], spec)
            geo_after = next((f for f in after["facts"] if f["source"] == "geo"), None)
            if geo_before and geo_after and geo_before["summary"] != geo_after["summary"]:
                changes.append({"hotel_id": h["id"], "hotel": h["name"], "char": spec["name"],
                                "before": geo_before["summary"], "after": geo_after["summary"],
                                "distance_m": round(math.hypot(h["x"] - x, h["y"] - y))})
                if cid == "sea_view":
                    store.add_question(h["id"], cid, f"Рядом (в {changes[-1]['distance_m']} м) появилось новое здание "
                                       f"в {levels} этажей. По расчёту: было «{geo_before['summary']}», стало "
                                       f"«{geo_after['summary']}». Подтвердите, изменился ли вид из ваших номеров.",
                                       "изменились данные", 1.5)
    store.log_event("world_changed", payload={"what": f"новое здание {levels} эт.", "lat": lat, "lon": lon,
                                              "checked_hotels": len(affected), "changes": changes})
    return {"checked_hotels": len(affected), "changed": changes}


def load_simulated(geo):
    if SIM_FILE.exists():
        for s in json.loads(SIM_FILE.read_text()):
            _apply(geo, s["lat"], s["lon"], s["levels"], s["radius_m"])


def recheck_stale(before=None):
    """Пересчитывает факты, срок годности которых истёк (или истечёт к дате before)."""
    cutoff = before or datetime.now(timezone.utc).isoformat()
    rows = store.conn().execute("SELECT DISTINCT hotel_id, char_id FROM facts WHERE active=1 AND valid_until < ? "
                                "AND source != 'hotelier'", (cutoff,)).fetchall()
    redone = 0
    for r in rows:
        if registry.get(r["char_id"]):
            registry.compute(r["char_id"], r["hotel_id"])
            redone += 1
    hot = store.conn().execute("SELECT DISTINCT hotel_id, char_id FROM facts WHERE active=1 AND valid_until < ? "
                               "AND source = 'hotelier'", (cutoff,)).fetchall()
    asked = sum(1 for r in hot if store.add_question(r["hotel_id"], r["char_id"],
                                                      "Ваш прошлый ответ устарел. Всё ещё так?", "ответ устарел", 0.8))
    store.log_event("recheck", payload={"cutoff": cutoff, "recomputed": redone, "asked_again": asked})
    return {"cutoff": cutoff, "recomputed": redone, "asked_hoteliers_again": asked}
