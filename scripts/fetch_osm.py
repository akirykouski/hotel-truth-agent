"""Скачивает вырезку OpenStreetMap для демо-зоны через Overpass API и кладёт в data/osm/*.json.gz.

Зона: центр Сочи с запасом для расчёта видимости. Повторный запуск перезаписывает файлы.
  python scripts/fetch_osm.py
  python scripts/fetch_osm.py --region adler --bbox 43.39,39.87,43.50,39.99   # другой регион, запрос по слоям
"""
import gzip
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _region import OSM_MARGIN, pad, region_args, write_meta  # noqa: E402

BBOX = (43.545, 39.675, 43.645, 39.795)  # юг, запад, север, восток
MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
# Overpass просит представляться: без User-Agent часть зеркал отвечает 406
HEADERS = {"User-Agent": "ostrovok-hackathon-region-loader/1.0", "Accept": "*/*"}
LAYERS = {
    # здания с контурами: высоты для видимости и шума
    "buildings": 'way["building"]({b});',
    # всё, по чему ходят и ездят, плюс железная дорога и взлётные полосы (шум аэропорта)
    "ways": 'way["highway"]({b});way["railway"]({b});way["aeroway"~"runway|taxiway"]({b});',
    # море, пляжи, береговая линия
    "water": 'way["natural"~"coastline|beach"]({b});relation["natural"~"beach"]({b});way["leisure"="beach_resort"]({b});',
    # точки интереса: еда, бары, аптеки, магазины, детское, парковки, зарядки, транспорт, медицина
    "pois": ('nwr["amenity"]({b});nwr["shop"]({b});nwr["leisure"]({b});nwr["tourism"]({b});'
             'nwr["highway"="bus_stop"]({b});nwr["railway"~"station|halt|level_crossing|crossing"]({b});'
             'nwr["public_transport"]({b});nwr["healthcare"]({b});nwr["landuse"="construction"]({b});'
             'nwr["building"="construction"]({b});'),
}


def query(body):
    """Один запрос на слой. Зеркала перебираются по кругу: упавшее зеркало не задерживает остальные."""
    q = f"[out:json][timeout:180];({body});out geom tags;"
    for attempt in range(3):
        for url in MIRRORS:
            try:
                r = httpx.post(url, data={"data": q}, headers=HEADERS, timeout=httpx.Timeout(240, connect=15))
                if r.status_code == 200:
                    return r.json(), url
                print(f"  {url}: {r.status_code}", file=sys.stderr)
            except httpx.HTTPError as e:
                print(f"  {url}: {type(e).__name__} {e}", file=sys.stderr)
        time.sleep(10 * (attempt + 1))  # Overpass просит не давить: пауза растёт с каждым кругом
    raise SystemExit("ни одно зеркало Overpass не ответило")


def main():
    a, root, zone = region_args("Вырезка OSM через Overpass: по одному запросу на слой.", None,
                                extra=lambda ap: ap.add_argument("layers", nargs="*", choices=list(LAYERS),
                                                                 help="слои (по умолчанию все)"))
    bbox = pad(zone, OSM_MARGIN) if a.region else BBOX
    out = root / "osm"
    out.mkdir(parents=True, exist_ok=True)
    b = ",".join(map(str, bbox))
    first = True
    for name, body in LAYERS.items():
        if a.layers and name not in a.layers:
            continue
        if not first:
            time.sleep(3)  # вежливая пауза между слоями
        first = False
        t = time.time()
        data, url = query(body.format(b=b))
        meta = {"bbox": bbox, "source": url, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "osm_base": data.get("osm3s", {}).get("timestamp_osm_base")}
        with gzip.open(out / f"{name}.json.gz", "wt", encoding="utf-8") as f:
            json.dump({"meta": meta, "elements": data["elements"]}, f, ensure_ascii=False, separators=(",", ":"))
        print(f"{name}: {len(data['elements'])} объектов с {url} за {time.time() - t:.0f} с")
    if a.region:
        write_meta(root, bbox=list(zone), osm_bbox=list(bbox))


if __name__ == "__main__":
    main()
