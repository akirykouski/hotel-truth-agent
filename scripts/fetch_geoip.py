"""Скачать офлайн-базы гео по IP (db-ip lite, CC BY 4.0) в data/cache/geoip/. Без них гео посетителя пустое.

Запуск: python scripts/fetch_geoip.py [--month 2026-10]
Источник: https://db-ip.com/db/lite.php (атрибуция: IP Geolocation by DB-IP).
"""
import argparse
import gzip
import shutil
import sys
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import visitors  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--month", default=date.today().strftime("%Y-%m"))
a = ap.parse_args()
visitors.GEO_DIR.mkdir(parents=True, exist_ok=True)
for kind in ("city", "asn"):
    url = f"https://download.db-ip.com/free/dbip-{kind}-lite-{a.month}.mmdb.gz"
    out = visitors.GEO_DIR / f"{kind}.mmdb"
    print("→", url)
    with urllib.request.urlopen(url) as r, gzip.GzipFile(fileobj=r) as g, open(out, "wb") as f:
        shutil.copyfileobj(g, f)
    print("  ", out, out.stat().st_size // 1024, "КБ")
