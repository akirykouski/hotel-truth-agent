"""Карта высот для демо-зоны: Copernicus GLO-30 (AWS Open Data), обрезка и сохранение в data/dem.npz.

GLO-30 — это DSM: в нём уже частично сидят здания и деревья (снимки 2010–2015). Поэтому кроме исходной
поверхности сохраняем грубую оценку рельефа (минимум в окне ~90 м), а здания потом ставим из OSM.
  python scripts/fetch_dem.py
"""
import io
import math
import sys
import time
from pathlib import Path

import httpx
import numpy as np
import tifffile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _region import DEM_MARGIN, pad, region_args, write_meta  # noqa: E402

TILE = ("https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM/"
        "Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM.tif")
BBOX = (43.50, 39.62, 43.70, 39.85)  # шире зоны отелей: море и горы на горизонте


def fetch_tile(lat, lon):
    url = TILE.format(lat=lat, lon=lon)
    for attempt in range(3):
        try:
            r = httpx.get(url, timeout=300, follow_redirects=True)
            r.raise_for_status()
            return tifffile.imread(io.BytesIO(r.content)).astype(np.float32), url
        except httpx.HTTPError as e:
            print(f"  {url}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"тайл {url} не скачался")


def main():
    a, root, zone = region_args("Карта высот Copernicus GLO-30: тайлы 1°×1°, склейка и обрезка.", None)
    bbox = pad(zone, DEM_MARGIN) if a.region else BBOX
    lats = range(math.floor(bbox[0]), math.floor(bbox[2]) + 1)
    lons = range(math.floor(bbox[1]), math.floor(bbox[3]) + 1)
    tiles = {}
    for la in lats:
        for lo in lons:
            tiles[(la, lo)] = fetch_tile(la, lo)
            print(f"тайл {len(tiles)}/{len(lats) * len(lons)}: N{la} E{lo}", flush=True)
    shapes = {t[0].shape for t in tiles.values()}
    if len(shapes) != 1:
        raise SystemExit(f"тайлы разной сетки {shapes}: рамка пересекает границу широтных поясов GLO-30")
    h, w = shapes.pop()  # тайл 1°×1°
    lat0, lon0 = max(lats) + 1.0, float(min(lons))  # верхний левый угол мозаики
    arr = np.vstack([np.hstack([tiles[(la, lo)][0] for lo in lons]) for la in sorted(lats, reverse=True)])
    url = next(iter(tiles.values()))[1]
    dlat, dlon = 1.0 / h, 1.0 / w
    r0, r1 = int((lat0 - bbox[2]) / dlat), int((lat0 - bbox[0]) / dlat)
    c0, c1 = int((bbox[1] - lon0) / dlon), int((bbox[3] - lon0) / dlon)
    dsm = arr[r0:r1, c0:c1]
    # грубый рельеф: минимум в окне 3×3 клетки (~90 м) срезает большую часть зданий
    pad_ = np.pad(dsm, 1, mode="edge")
    stack = [pad_[i:i + dsm.shape[0], j:j + dsm.shape[1]] for i in range(3) for j in range(3)]
    dtm = np.min(stack, axis=0)
    out = root / "dem.npz"
    np.savez_compressed(out, dsm=dsm.astype(np.float16), dtm=dtm.astype(np.float16),
                        north=lat0 - r0 * dlat, west=lon0 + c0 * dlon, dlat=dlat, dlon=dlon,
                        source=url)
    print(dsm.shape, float(dsm.min()), float(dsm.max()), out.stat().st_size // 1024, "KB")
    if a.region:
        write_meta(root, bbox=list(zone), dem_bbox=list(bbox))


if __name__ == "__main__":
    main()
