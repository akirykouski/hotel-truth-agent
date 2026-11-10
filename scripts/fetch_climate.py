"""Климат и море по месяцам для центра Сочи из Open-Meteo, кладёт в data/climate.json.

Воздух, осадки, солнце: архив реанализа ERA5 (2022–2025). Море: Marine API (модель MeteoFrance, сетка ~8 км,
ряд с 2022 года). Обе величины модельные, это пишется в провенанс фактов.
  python scripts/fetch_climate.py
  python scripts/fetch_climate.py --region adler --bbox 43.39,39.87,43.50,39.99   # точка = центр рамки
"""
import json
import statistics as st
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _region import region_args, write_meta  # noqa: E402

LAT, LON = 43.585, 39.715
SEA_LAT, SEA_LON = 43.57, 39.70
START, END = "2022-01-01", "2025-12-31"


def sea_series(lat, lon):
    """Морской ряд Open-Meteo. На суше ячейка модели пустая, поэтому для нового региона ищем воду шагами к югу и западу."""
    for k in range(0, 9):
        for dlat, dlon in ((0, 0),) if k == 0 else ((-0.04 * k, 0), (0, -0.04 * k), (-0.03 * k, -0.03 * k)):
            r = httpx.get("https://marine-api.open-meteo.com/v1/marine", timeout=120, params={
                "latitude": lat + dlat, "longitude": lon + dlon, "start_date": START, "end_date": END,
                "timezone": "Europe/Moscow", "hourly": "sea_surface_temperature"})
            h = r.json().get("hourly") if r.status_code == 200 else None
            print(f"морская точка {lat + dlat:.3f}, {lon + dlon:.3f}: {'есть вода' if h and any(v is not None for v in h['sea_surface_temperature']) else 'суша'}", flush=True)
            if h and any(v is not None for v in h["sea_surface_temperature"]):
                return h, (round(lat + dlat, 3), round(lon + dlon, 3))
    raise SystemExit("в окрестности точки нет морской ячейки Open-Meteo")


def main():
    global LAT, LON, SEA_LAT, SEA_LON
    args, root, zone = region_args("Климат и море по месяцам из Open-Meteo.", None)
    if args.region:
        LAT, LON = round((zone[0] + zone[2]) / 2, 3), round((zone[1] + zone[3]) / 2, 3)
        SEA_LAT, SEA_LON = LAT, LON
    a = httpx.get("https://archive-api.open-meteo.com/v1/archive", timeout=120, params={
        "latitude": LAT, "longitude": LON, "start_date": START, "end_date": END, "timezone": "Europe/Moscow",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,sunshine_duration"}).json()["daily"]
    if args.region:
        m, (SEA_LAT, SEA_LON) = sea_series(SEA_LAT, SEA_LON)
    else:
        m = httpx.get("https://marine-api.open-meteo.com/v1/marine", timeout=120, params={
            "latitude": SEA_LAT, "longitude": SEA_LON, "start_date": START, "end_date": END,
            "timezone": "Europe/Moscow", "hourly": "sea_surface_temperature"}).json()["hourly"]
    by = defaultdict(lambda: defaultdict(list))
    for i, d in enumerate(a["time"]):
        mo = int(d[5:7])
        for k in ("temperature_2m_max", "temperature_2m_min", "precipitation_sum", "sunshine_duration"):
            if a[k][i] is not None:
                by[mo][k].append(a[k][i])
    sea = defaultdict(list)
    sea_dec = defaultdict(list)  # (месяц, декада 1–3)
    for t, v in zip(m["time"], m["sea_surface_temperature"]):
        if v is not None:
            sea[int(t[5:7])].append(v)
            sea_dec[(int(t[5:7]), min(3, (int(t[8:10]) - 1) // 10 + 1))].append(v)
    years = len({d[:4] for d in a["time"]})
    months = {}
    for mo in range(1, 13):
        b = by[mo]
        rain_days = sum(1 for x in b["precipitation_sum"] if x >= 1.0)
        months[mo] = {
            "air_max_c": round(st.mean(b["temperature_2m_max"]), 1),
            "air_min_c": round(st.mean(b["temperature_2m_min"]), 1),
            "precip_mm": round(sum(b["precipitation_sum"]) / years),
            "rain_days": round(rain_days / years, 1),
            "sunshine_h_per_day": round(st.mean(b["sunshine_duration"]) / 3600, 1),
            "sea_c": round(st.mean(sea[mo]), 1) if sea[mo] else None,
            "sea_c_min": round(min(sea[mo]), 1) if sea[mo] else None,
            "sea_c_max": round(max(sea[mo]), 1) if sea[mo] else None,
            "sea_c_by_decade": [round(st.mean(sea_dec[(mo, d)]), 1) if sea_dec[(mo, d)] else None for d in (1, 2, 3)],
        }
    out = {"point": [LAT, LON], **({"sea_point": [SEA_LAT, SEA_LON]} if args.region else {}),
           "period": [START, END], "fetched_at": time.strftime("%Y-%m-%d"),
           "sources": {"air": "Open-Meteo Archive API (реанализ ERA5)",
                       "sea": "Open-Meteo Marine API (модель MeteoFrance, ~8 км)"},
           "months": months}
    p = root / "climate.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for mo in (6, 7, 8, 9, 10, 11):
        print(mo, months[mo])
    if args.region:
        write_meta(root, bbox=list(zone), climate_point=[LAT, LON], sea_point=[SEA_LAT, SEA_LON])


if __name__ == "__main__":
    main()
