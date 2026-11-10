"""Импорт готовых расчётов из соседнего репозитория map-app (карта Сочи с 3D-зданиями): путь пешком и шум по этажам.

map-app считает точнее нашего ядра и по методологии ресерча:
  - путь: пешеходный граф OSM + FABDEM (рельеф без домов), Тоблер, модель марша для лестниц, переходы через ж/д,
    туда и обратно отдельно; цели — пляж, станция (Сочи, Мацеста, Хоста), центр (Морской вокзал); вариант для коляски
    (тот же поиск без лестниц);
  - шум: CNOSSOS-EU 2020 для дорог, Schall 03 для ж/д, модель террасы для баров; экраны (дома и рельеф) и высота
    окна каждого этажа, по каждому фасаду.
Мы не переписываем эти расчёты, а берём их результат: web/data/{walk,noise}.json. Отели map-app — объекты OSM,
у 92 из них есть сверка с карточкой Островка (web/data/ostrovok.json, ссылка с mid = наш id отеля). Остальные
сопоставляем по зданию: путь и шум map-app считает от контура здания, поэтому другой отель в том же здании OSM получает
те же числа; иначе по координатам (≤ 40 м) и похожему названию. Покрыты только отели OSM в районах map-app (центр
Сочи и Хоста), мини-отели без тега tourism=hotel там не считались.

Выход: <данные региона>/mapapp.json — компактные записи по нашим id отелей (без геометрии маршрутов) + meta
(источник, коммит, методы, лицензии). Факты из него считают характеристики registry/{stroller_beach,station_walk,
center_walk,noise_floors}.yaml через инструменты mapapp_walk и mapapp_noise.

  python scripts/import_mapapp.py                       # map-app рядом: ../app или ../map-app
  python scripts/import_mapapp.py --src ~/map-app --region hosta
  python scripts/precompute.py stroller_beach station_walk center_walk noise_floors   # факты (рабочая база пересоздастся)
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATCH_M = 40
NAME_SIM = 0.5


def _src_dir(arg):
    for p in ([Path(arg).expanduser()] if arg else [ROOT.parent / "map-app", ROOT.parent / "app"]):
        if (p / "web" / "data" / "walk.json").exists():
            return p
    sys.exit("не найден map-app с web/data/walk.json: укажите --src")


def _region_dir(name):
    return ROOT / "data" if name in (None, "", "default") else ROOT / "data" / "regions" / name


def _norm(s):
    s = re.sub(r"[«»\"'*]|\d\s*\*|\b(отель|гостиница|гостевой дом|апарт-отель|мини-отель|hotel|сочи)\b", " ", str(s or "").lower())
    return " ".join(s.split())


def _dist(a, b):
    k = math.cos(math.radians(a[0]))
    return math.hypot((a[0] - b[0]) * 111_320, (a[1] - b[1]) * 111_320 * k)


def _our_buildings(hotels, region):
    """Наш id отеля → osm id его здания (тот же выбор контура, что у расчётов агента)."""
    os.environ["REGION"] = "" if region in (None, "", "default") else region
    sys.path.insert(0, str(ROOT))
    from app import geodata as gd
    geo = gd.load()
    out = {}
    for h in hotels:
        bid, _ = gd.hotel_building(h["id"])
        if bid >= 0:
            out[h["id"]] = int(geo.buildings[bid].osm_id)
    return out


def match(hotels, src, region=None):
    """Наш id отеля → (osm id map-app, как сопоставлено)."""
    osk = json.loads((src / "web" / "data" / "ostrovok.json").read_text(encoding="utf-8"))
    by_mid = {}
    for oid, o in osk.items():
        m = re.search(r"/mid(\d+)", o.get("url") or "")
        if m and o.get("confidence") in ("high", "medium", None):
            by_mid[m.group(1)] = oid
    feats = json.loads((src / "web" / "data" / "hotels.geojson").read_text(encoding="utf-8"))["features"]
    pts = [(f["properties"]["osm_id"], (f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]),
            f["properties"].get("name")) for f in feats if f.get("geometry")]
    by_bld = {}
    for f in feats:
        m = re.fullmatch(r"w(\d+)", str(f["properties"].get("building_id") or ""))
        if m:
            by_bld.setdefault(int(m.group(1)), f["properties"]["osm_id"])
    ours = _our_buildings(hotels, region)
    out = {}
    for h in hotels:
        if h["id"] in by_mid:
            out[h["id"]] = (by_mid[h["id"]], "карточка Островка в map-app")
        elif ours.get(h["id"]) in by_bld:
            out[h["id"]] = (by_bld[ours[h["id"]]], f"то же здание OSM w{ours[h['id']]}")
    for h in hotels:
        if h["id"] in out:
            continue
        ll = (float(h["lat"]), float(h["lon"]))
        best = None
        for oid, p, name in pts:
            d = _dist(ll, p)
            sim = SequenceMatcher(None, _norm(h["name"]), _norm(name)).ratio() if name else 0.0
            if d <= MATCH_M and sim >= NAME_SIM and (best is None or d < best[1]):
                best = (oid, d, sim)
        if best:
            out[h["id"]] = (best[0], f"координаты {round(best[1])} м, сходство названий {best[2]:.2f}")
    return out


def _leg(x):
    """Одна сторона маршрута: минуты (движение + лестницы + ожидание), метры, подъём и спуск, ступени, ж/д."""
    if not x:
        return None
    return {"min": round((x["mv"] + x["st"] + x["wait"]) / 60, 1), "m": x["m"], "up_m": round(x["up"], 1),
            "down_m": round(x["down"], 1), "steps": x.get("st_up", 0) + x.get("st_down", 0), "steps_estimated": x.get("st_est", False),
            "rail_crossings": len(x.get("rail") or []), "wait_s": x["wait"]}


def walk_record(w):
    out = {}
    for target in ("beach", "station", "center"):
        t = w.get(target)
        if not t or not t.get("to"):
            continue
        rec = {"target": (t.get("target") or {}).get("name"), "kind": (t.get("target") or {}).get("kind"),
               "there": _leg(t["to"]), "back": _leg(t["back"]), "straight_m": t.get("straight_m"), "detour": t.get("di")}
        s = t.get("stroller")
        rec["stroller"] = ({"possible": True, "target": (s.get("target") or {}).get("name"), "there": _leg(s["to"]), "back": _leg(s["back"])}
                           if s and s.get("to") else {"possible": False})
        out[target] = rec
    return out


def _top_source(src):
    """Главный источник шума ночью на нижнем этаже: [[[имя, доля], …] по этажам]."""
    return src[0][0][0] if src and src[0] else None


def noise_record(n):
    facades = []
    for fid, f in n.items():
        if not isinstance(f, dict) or not f.get("n"):
            continue
        facades.append({"id": fid, "dir": f.get("compass"), "floors": f.get("floors") or len(f["n"]),
                        "night": [round(v, 1) for v in f["n"]], "day": [round(v, 1) for v in f["d"]],
                        "night_source": _top_source(f.get("src_n"))})
    if not facades:
        return None
    cells = [(v, fc["dir"], i + 1) for fc in facades for i, v in enumerate(fc["night"])]
    q, l = min(cells), max(cells)
    floors = max(fc["floors"] for fc in facades)
    by_floor = []
    for fl in range(1, floors + 1):
        row = [(fc["night"][fl - 1], fc["dir"]) for fc in facades if fl <= len(fc["night"])]
        if row:
            by_floor.append({"floor": fl, "quiet_dir": min(row)[1], "quiet_db": min(row)[0], "loud_db": max(row)[0]})
    return {"quietest": {"night_db": q[0], "dir": q[1], "floor": q[2]}, "loudest": {"night_db": l[0], "dir": l[1], "floor": l[2]},
            "spread_db": round(l[0] - q[0], 1), "by_floor": by_floor, "facades": facades}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", help="папка map-app (по умолчанию ../map-app или ../app)")
    ap.add_argument("--region", default="default", help="регион агента: default (центр Сочи) или имя из data/regions")
    a = ap.parse_args()
    src, dst = _src_dir(a.src), _region_dir(a.region)
    hotels = json.loads((dst / "hotels.json").read_text(encoding="utf-8"))["hotels"]
    walk = json.loads((src / "web" / "data" / "walk.json").read_text(encoding="utf-8"))
    noise = json.loads((src / "web" / "data" / "noise.json").read_text(encoding="utf-8"))
    pairs = match(hotels, src, a.region)
    out, n_walk, n_noise = {}, 0, 0
    for hid, (oid, how) in pairs.items():
        rec = {"osm_id": oid, "match": how}
        if oid in walk["hotels"]:
            rec["walk"] = walk_record(walk["hotels"][oid])
            n_walk += bool(rec["walk"])
        if oid in noise["hotels"]:
            rec["noise"] = noise_record(noise["hotels"][oid])
            n_noise += bool(rec["noise"])
        out[hid] = rec
    try:
        commit = subprocess.run(["git", "-C", str(src), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = None
    wm, nm = walk["meta"], noise["meta"]
    meta = {"source": "map-app (github.com/hackathon-ostrovok-felicita-2026/map-app)", "commit": commit,
            "walk": {"computed_at": wm.get("computed_at"), "method": wm.get("method")},
            "noise": {"computed_at": nm.get("computed_at"), "method": nm.get("method"), "uncert_db": nm.get("uncert_db"),
                      "confidence": nm.get("confidence")},
            "licenses": "OSM ODbL 1.0 © OpenStreetMap contributors; FABDEM V1-2 © University of Bristol, CC BY-NC-SA 4.0 "
                        "(только некоммерческое использование); числа директивы CNOSSOS-EU из NoiseModelling (GPL-3.0, код не используется)",
            "hotels_total": len(hotels), "matched": len(out), "with_walk": n_walk, "with_noise": n_noise}
    (dst / "mapapp.json").write_text(json.dumps({"meta": meta, "hotels": out}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    by_how = {}
    for _, how in pairs.values():
        k = how.split(" ")[0]
        by_how[k] = by_how.get(k, 0) + 1
    print(f"{dst / 'mapapp.json'}: сопоставлено {len(out)} из {len(hotels)} отелей ({by_how}), путь у {n_walk}, шум у {n_noise}")


if __name__ == "__main__":
    main()
