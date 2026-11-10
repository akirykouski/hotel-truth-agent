"""Общее для скриптов загрузки данных: разбор --region/--bbox и пути региона.

Без --region скрипты пишут в data/ для демо-зоны (центр Сочи) с прежними рамками. С --region NAME и --bbox s,w,n,e
(рамка зоны отелей) пишут в data/regions/NAME/, а рамки OSM и карты высот берут из неё с запасом на видимость.
"""
import argparse
import json
import lzma
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OSM_MARGIN = 0.015   # градусов вокруг зоны отелей, как у демо-зоны
DEM_MARGIN = 0.07    # шире: море и горы на горизонте


def parse_bbox(s):
    b = tuple(float(v) for v in s.split(","))
    if len(b) != 4 or b[0] >= b[2] or b[1] >= b[3]:
        raise argparse.ArgumentTypeError("нужно s,w,n,e: юг,запад,север,восток в градусах")
    return b


def pad(b, m):
    return (round(b[0] - m, 4), round(b[1] - m, 4), round(b[2] + m, 4), round(b[3] + m, 4))


def region_args(desc, default_bbox, *, extra=None):
    """Возвращает (args, out_dir, bbox). Без --region: data/ и default_bbox, иначе data/regions/NAME/ и --bbox."""
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--region", help="имя региона: данные пойдут в data/regions/NAME/")
    ap.add_argument("--bbox", type=parse_bbox, help="рамка зоны отелей s,w,n,e (обязательна с --region)")
    if extra:
        extra(ap)
    a = ap.parse_args()
    if a.region:
        if not a.bbox:
            ap.error("с --region нужен --bbox s,w,n,e")
        out = ROOT / "data" / "regions" / a.region
        out.mkdir(parents=True, exist_ok=True)
        return a, out, a.bbox
    return a, ROOT / "data", a.bbox or default_bbox


def read_meta(out):
    f = Path(out) / "region.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def write_meta(out, **kv):
    f = Path(out) / "region.json"
    m = read_meta(out) | kv
    tmp = f.with_suffix(f".{os.getpid()}.tmp")  # скрипты шага идут параллельно: пишем атомарно
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


# ---------- проверка рамки до сборки: её же показывает интерфейс «Регионы» ----------

SKIP_KINDS = {"APARTMENT", "LIVING_QUARTERS"}   # квартиры: точка на карте неточная, этажность и сторона неизвестны
MAX_AREA_KM2 = 150      # больше Overpass отдаёт здания слоем по 10+ минут, а предрасчёт растёт с числом отелей
WARN_AREA_KM2 = 60
WARN_HOTELS = 800
SEC_PER_HOTEL = 0.2     # предрасчёт на Адлере: 65 с на 339 отелей
GLO30_BANDS = (50, 60, 70, 80, 85)  # на этих широтах у тайлов GLO-30 меняется сетка, склейка через границу не работает


def is_lfs_pointer(path):
    with open(path, "rb") as f:
        return f.read(40).startswith(b"version https://git-lfs")


def open_text(path):
    """Файл скрапа как текст: hotels.jsonl или сжатый hotels.jsonl.xz (так он лежит в data/sources/)."""
    return lzma.open(path, "rt", encoding="utf-8") if str(path).endswith(".xz") else open(path, encoding="utf-8")


def iter_hotels(src):
    """(lat, lon, kind) из hotels.jsonl скрапа, без разбора остальных полей строки."""
    with open_text(src) as f:
        for line in f:
            h = json.loads(line)
            if h.get("lat") is not None and h.get("lon") is not None:
                yield h["lat"], h["lon"], h.get("kind")


def area_km2(b):
    import math
    s, w, n, e = b
    return (n - s) * 111.32 * (e - w) * 111.32 * math.cos(math.radians((s + n) / 2))


def check_plan(src, bbox, points=None):
    """Что получится из рамки: отели, площадь, тайлы рельефа, оценка времени. errors блокируют сборку, warnings нет."""
    errors, warnings = [], []
    s, w, n, e = bbox
    if s < 0 or w < 0:
        errors.append("пока только северная широта и восточная долгота (так названы тайлы рельефа GLO-30)")
    band = lambda lat: sum(lat >= x for x in GLO30_BANDS)  # noqa: E731
    dem = pad(bbox, DEM_MARGIN)
    if band(dem[0]) != band(dem[2]):
        errors.append("рамка с запасом на горизонт пересекает границу широтных поясов карты высот: сдвиньте её")
    area = area_km2(bbox)
    if area > MAX_AREA_KM2:
        errors.append(f"рамка {area:.0f} км², предел {MAX_AREA_KM2} км²: возьмите плотное ядро отелей")
    elif area > WARN_AREA_KM2:
        warnings.append(f"рамка {area:.0f} км²: загрузка зданий из OSM может занять больше 10 минут")
    total = hotels = apartments = 0
    if src is None or not Path(src).exists():
        errors.append("нет файла отелей из скрапа")
    elif is_lfs_pointer(src):
        errors.append("файл отелей — заглушка Git LFS: выполните git lfs pull там, где он лежит")
    else:
        for lat, lon, kind in points if points is not None else iter_hotels(src):
            total += 1
            if s <= lat <= n and w <= lon <= e:
                if kind in SKIP_KINDS:
                    apartments += 1
                else:
                    hotels += 1
        if not hotels:
            errors.append("в рамке нет ни одного отеля")
        elif hotels > WARN_HOTELS:
            warnings.append(f"{hotels} отелей: предрасчёт займёт около {hotels * SEC_PER_HOTEL / 60:.0f} мин")
    tiles = (int(dem[2]) - int(dem[0]) + 1) * (int(dem[3]) - int(dem[1]) + 1)
    return {"ok": not errors, "errors": errors, "warnings": warnings, "hotels": hotels, "apartments_skipped": apartments,
            "source_total": total, "area_km2": round(area, 1), "dem_tiles": tiles,
            "estimate_s": {"compute": round(hotels * SEC_PER_HOTEL + 25 * tiles + 15), "osm": [120, 1500]}}
