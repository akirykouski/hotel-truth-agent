"""Отбирает отели демо-зоны из скрапа Островка и пишет тонкую версию в data/hotels.json.

Источник: скрап Островка data/sources/sochi/hotels.jsonl.xz (копия ostrovok-hotels-data; карточки, номера, 5–20 отзывов,
цены на 1–2.11.2026). Зона: центр Сочи. Квартиры и жилые помещения не берём: их точка на карте часто
неточная, а этажность и сторона здания неизвестны.
  python scripts/prepare_hotels.py data/sources/sochi/hotels.jsonl.xz
  python scripts/prepare_hotels.py data/sources/sochi/hotels.jsonl.xz --region adler --bbox 43.39,39.87,43.50,39.99   # другой регион
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _region import SKIP_KINDS, open_text, region_args, write_meta  # noqa: E402

BBOX = (43.56, 39.69, 43.63, 39.78)


def policy(p, key):
    return ((p or {}).get(key) or {}).get("value")


def slim(h):
    pol = h.get("policies") or {}
    rooms = [{"name": r["name"], "bedding": r.get("bedding"), "size_m2": r.get("size_m2"),
              "amenities": r.get("amenities") or []} for r in h["rooms"]]
    reviews = [{"date": (r.get("review_date") or "")[:10], "plus": r.get("review_plus") or "",
                "minus": r.get("review_minus") or "", "rating": r.get("rating"),
                "room": (r.get("order_context") or {}).get("author_room"),
                "traveller": r.get("traveller_type"), "trip": r.get("trip_type"), "wifi": r.get("wifi_quality"),
                "scores": r.get("detailed"), "id": r.get("id")} for r in h["reviews"]]
    rates = h.get("rates") or {}
    return {
        "id": h["master_id"], "name": h["name"], "kind": h["kind"], "stars": h.get("stars") or 0,
        "address": h.get("address"), "lat": h["lat"], "lon": h["lon"], "url": h["url"],
        "description": "\n".join(f"{s['title']}: {s['text']}" if s.get("title") else s["text"]
                                 for s in h["description"]),
        "amenities": sorted({a for g in h["amenities"] for a in g["items"] if a}),
        "rooms": rooms,
        "policies": {"checkin": policy(pol, "checkInCheckOut"), "pets": policy(pol, "pets"),
                     "parking": policy(pol, "parking"), "children": policy(pol, "children"),
                     "extra_info": policy(pol, "extraInfo")},
        "rating": {"total": h["rating"].get("total"), "count": h["rating"].get("reviews_count"),
                   "aspects": h["rating"].get("aspects")},
        "reviews": reviews,
        "price_nov1": rates.get("min_price") if rates.get("available") else None,
        "photos": [p["url"].replace("{size}", "640x400") for p in h["photos"][:4] if p.get("url")],
        "ostrovok_beaches": h.get("nearest_beaches"),
        "scraped_at": h.get("scraped_at"),
    }


def main():
    a, root, bbox = region_args("Отбор отелей зоны из скрапа Островка.", BBOX,
                                extra=lambda ap: ap.add_argument("src", help="hotels.jsonl или .jsonl.xz из data/sources/<город>/"))
    out = []
    for line in open_text(a.src):
        h = json.loads(line)
        if h["kind"] in SKIP_KINDS or not (bbox[0] <= h["lat"] <= bbox[2] and bbox[1] <= h["lon"] <= bbox[3]):
            continue
        out.append(slim(h))
    p = root / "hotels.json"
    p.write_text(json.dumps({"source": "ostrovok.ru, скрап 25–26.10.2026", "zone": bbox, "hotels": out},
                            ensure_ascii=False), encoding="utf-8")
    print(len(out), "отелей,", p.stat().st_size // 1024, "KB")
    if a.region:
        write_meta(root, bbox=list(bbox), hotels=len(out))


if __name__ == "__main__":
    main()
