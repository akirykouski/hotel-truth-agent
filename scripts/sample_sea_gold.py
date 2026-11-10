"""Выборка отелей для независимой разметки «вид на море» (data/eval/sea_view_sample.json).

Страты: результат расчёта (море видно / нет, уверенность выше или ниже 0.9) × расстояние до берега
(<300 м, 300–800 м, >800 м) + все отели, где карточка или отзывы спорят с расчётом.
Фиксированный seed; выборка сохраняется ДО разметки и больше не меняется. Метки сюда не смотрят.
Расстояние до берега считается по той же маске моря (Copernicus), что и в расчёте вида, поэтому
baseline «до берега ≤ X м» независим от зданий, но не от береговой линии.

  FACTS_DB=data/facts.sqlite LLM_PROVIDER=none python scripts/sample_sea_gold.py
"""
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FACTS_DB", str(ROOT / "data" / "facts.sqlite"))
os.environ.setdefault("LLM_PROVIDER", "none")

import numpy as np  # noqa: E402

from app import geodata as gd, store  # noqa: E402

SEED = 20261028
OUT = ROOT / "data" / "eval" / "sea_view_sample.json"
# квоты по ячейкам (счёт включает отели из страты «спор»)
QUOTA = {("yes", "hi", "near"): 7, ("yes", "hi", "mid"): 7, ("yes", "hi", "far"): 6, ("yes", "low", "any"): 6,
         ("no", "hi", "near"): 2, ("no", "hi", "mid"): 6, ("no", "hi", "far"): 6, ("no", "low", "any"): 6}


def coast_distances(geo):
    sea = geo.dem_sea
    edge = sea & ~(np.roll(sea, 1, 0) & np.roll(sea, -1, 0) & np.roll(sea, 1, 1) & np.roll(sea, -1, 1))
    r, c = np.where(edge)
    m = geo.dem_meta
    x, y = gd.to_xy(m["north"] - (r + .5) * m["dlat"], m["west"] + (c + .5) * m["dlon"])
    pts = np.column_stack([x, y])
    return {h["id"]: float(np.sqrt(((pts - [h["x"], h["y"]]) ** 2).sum(1)).min()) for h in geo.hotels}


def band(d):
    return "near" if d < 300 else ("mid" if d < 800 else "far")


def main():
    geo = gd.load()
    cd = coast_distances(geo)
    rows = []
    for h in geo.hotels:
        by = {f["source"]: f for f in store.facts(h["id"], "sea_view")}
        g = by["geo"]
        card = "card" in by
        rev = by["reviews"]["value"]["has"] if "reviews" in by else None
        has = bool(g["value"]["has"])
        disagree = (card and not has) or (rev is not None and rev != has)
        rows.append({"id": h["id"], "name": h["name"], "coast_dist_m": round(cd[h["id"]]), "band": band(cd[h["id"]]),
                     "geo_has": has, "geo_conf_hi": g["confidence"] >= 0.9, "disagree": bool(disagree)})
    rnd = random.Random(SEED)
    chosen = {}
    for r in rows:
        if r["disagree"]:
            chosen[r["id"]] = "спор"
    def cell(r):
        hi = "hi" if r["geo_conf_hi"] else "low"
        return ("yes" if r["geo_has"] else "no", hi, r["band"] if hi == "hi" else "any")
    for k, q in QUOTA.items():
        have = sum(1 for r in rows if r["id"] in chosen and cell(r) == k)
        pool = sorted((r for r in rows if cell(r) == k and r["id"] not in chosen), key=lambda r: r["id"])
        rnd.shuffle(pool)
        for r in pool[:max(0, q - have)]:
            chosen[r["id"]] = "ячейка"
    sample = []
    for r in rows:
        if r["id"] in chosen:
            c = cell(r)
            sample.append({"id": r["id"], "name": r["name"], "stratum": "/".join(c), "from": chosen[r["id"]],
                           "coast_dist_m": r["coast_dist_m"], "band": r["band"], "disagree": r["disagree"]})
    sample.sort(key=lambda s: s["id"])
    OUT.write_text(json.dumps({"seed": SEED, "n": len(sample), "universe": len(rows), "sample": sample},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(sample), "->", OUT)


if __name__ == "__main__":
    main()
