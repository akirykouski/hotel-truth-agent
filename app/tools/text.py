"""Текстовые источники: карточка Островка (удобства, номера, правила, описание) и отзывы гостей.

Поиск по словам (регулярные выражения), каждое найденное место возвращается цитатой с датой и полем,
чтобы факт можно было проверить глазами. Ничего не «угадывается»: нет упоминания — значит нет данных.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from app import geodata as gd, region

CLIMATE = region.DATA / "climate.json"


def _rx(terms):
    if isinstance(terms, str):
        terms = [terms]
    return re.compile("|".join(f"(?:{t})" for t in terms), re.I)


def _snip(text, m, width=90):
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return ("…" if a else "") + text[a:b].replace("\n", " ").strip() + ("…" if b < len(text) else "")


def card_search(hotel_id, terms, where=("amenities", "rooms", "policies", "description"), exclude=None):
    """Ищет слова в карточке отеля. Возвращает, где нашлось, с цитатой.
    exclude: слова-исключения; совпадение отбрасывается, если они стоят рядом (в строке удобства или в пределах 40 знаков)."""
    h = gd.load().hotel_by_id[hotel_id]
    rx = _rx(terms)
    ex = _rx(exclude) if exclude else None
    where = tuple(where)
    hits = []
    if "amenities" in where:
        for a in h["amenities"]:
            if rx.search(a) and not (ex and ex.search(a)):
                hits.append({"field": "удобства отеля", "quote": a})
    if "rooms" in where:
        for r in h["rooms"]:
            for a in [r["name"] or ""] + list(r["amenities"]):
                if rx.search(a) and not (ex and ex.search(a)):
                    hits.append({"field": f"номер «{r['name']}»", "quote": a})
    if "policies" in where:
        txt = json.dumps(h["policies"], ensure_ascii=False)
        for m in rx.finditer(h["policies"].get("extra_info") or ""):
            if ex and ex.search(_snip(h["policies"]["extra_info"], m, 40)):
                continue
            hits.append({"field": "правила отеля", "quote": _snip(h["policies"]["extra_info"], m)})
        if not hits and not ex and rx.search(txt):
            hits.append({"field": "правила отеля", "quote": rx.search(txt).group(0)})
    if "description" in where:
        for m in rx.finditer(h["description"] or ""):
            if ex and ex.search(_snip(h["description"], m, 40)):
                continue
            hits.append({"field": "описание", "quote": _snip(h["description"], m)})
    rooms_total = len(h["rooms"])
    rooms_hit = sorted({x["field"] for x in hits if x["field"].startswith("номер")})
    return {"found": bool(hits), "hits": hits[:12], "rooms_matched": len(rooms_hit), "rooms_total": rooms_total}


def reviews_search(hotel_id, terms, exclude=None):
    """Упоминания в отзывах: в «понравилось» или в «не понравилось», с датой и категорией номера."""
    h = gd.load().hotel_by_id[hotel_id]
    rx = _rx(terms)
    ex = _rx(exclude) if exclude else None
    pos, neg = [], []
    for r in h["reviews"]:
        for side, bucket in (("plus", pos), ("minus", neg)):
            t = r[side] or ""
            m = rx.search(t)
            if m and not (ex and ex.search(_snip(t, m, 40))):
                bucket.append({"date": r["date"], "room": r["room"], "quote": _snip(t, m), "review_id": r["id"]})
    return {"reviews_total": len(h["reviews"]), "positive": len(pos), "negative": len(neg),
            "positive_quotes": pos[:5], "negative_quotes": neg[:5],
            "latest": max([x["date"] for x in pos + neg], default=None)}


def review_stats(hotel_id):
    """Структурированные поля отзывов: оценка Wi-Fi гостями (perfect/slow/…), средние оценки по аспектам
    (чистота, расположение, номер, сервис, еда, wifi), кто ездит (семьи, пары, одиночки) и зачем (отдых, работа)."""
    h = gd.load().hotel_by_id[hotel_id]
    rv = h["reviews"]
    wifi = {}
    for r in rv:
        if r.get("wifi"):
            wifi[r["wifi"]] = wifi.get(r["wifi"], 0) + 1
    rated = sum(wifi.values())
    trav, trip = {}, {}
    for r in rv:
        for d, k in ((trav, r.get("traveller")), (trip, r.get("trip"))):
            if k:
                d[k] = d.get(k, 0) + 1
    return {"reviews_total": len(rv), "wifi_votes": wifi, "wifi_rated": rated,
            "wifi_good_share": round(wifi.get("perfect", 0) / rated, 2) if rated else None,
            "aspects": {k: round(v, 1) for k, v in (h["rating"].get("aspects") or {}).items() if v is not None},
            "travellers": trav, "trips": trip}


def card(hotel_id):
    h = gd.load().hotel_by_id[hotel_id]
    return {k: h[k] for k in ("id", "name", "kind", "stars", "address", "lat", "lon", "url", "rating", "price_nov1",
                              "photos")} | {"rooms": [r["name"] for r in h["rooms"]],
                                            "amenities": h["amenities"][:60],
                                            "description": (h["description"] or "")[:1500]}


@lru_cache(maxsize=1)
def _climate():
    return json.loads(CLIMATE.read_text(encoding="utf-8"))


def climate(month):
    c = _climate()
    return {"month": month, **c["months"][str(month)], "sources": c["sources"], "period": c["period"]}
