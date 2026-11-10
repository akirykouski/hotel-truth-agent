"""Метрики качества.

Ручной разметки «правды» по 229 отелям у нас нет, поэтому сверяем расчёт с независимыми источниками, которые
в расчёт не входят: категории номеров «с видом на море» в карточке и отзывы гостей (в том числе гостей, живших
в номере «с видом на море»). Это слабая разметка: карточка может преувеличивать, отзывы — молчать.
Плюс покрытие, доля вопросов отельеру и аудит обещаний в описаниях отелей («5 минут до моря»).
"""
import re
from collections import Counter

from app import geodata as gd
from app import registry, store
from app.tools import photos, text

SEA_POS = ["вид на море", "видно море", "вид из окна на море", "морем из окна", "вид на мор", "видом на море"]
SEA_NEG = ["нет вида на море", "моря не видно", "море не видно", "вид на стену", "вид во двор", "вида на море нет"]


def _geo(hid, cid):
    f = next((f for f in store.facts(hid, cid) if f["source"] == "geo"), None)
    return f


def sea_view_check():
    rows = []
    for h in gd.load().hotels:
        g = _geo(h["id"], "sea_view")
        if not g:
            continue
        card = text.card_search(h["id"], ["вид(ом)? на море", "sea[- ]view", "морск(ой|им) вид"])
        rev_pos = text.reviews_search(h["id"], SEA_POS, exclude=["нет вида", "не видно", "без вида"])
        rev_neg = text.reviews_search(h["id"], SEA_NEG)
        rows.append({"geo": bool(g["value"]["has"]), "conf": g["confidence"], "card": card["found"],
                     "rev_pos": rev_pos["positive"], "rev_neg": rev_neg["negative"] + rev_neg["positive"]})
    n_card = [r for r in rows if r["card"]]
    n_rev = [r for r in rows if r["rev_pos"] >= 1]
    n_neg = [r for r in rows if r["rev_neg"] >= 1 and r["rev_pos"] == 0]
    strong = [r for r in rows if r["card"] and r["rev_pos"] >= 1]
    geo_yes_no_claim = [r for r in rows if r["geo"] and not r["card"] and r["rev_pos"] == 0]
    calib = []
    for lo, hi in ((0.0, 0.6), (0.6, 0.8), (0.8, 0.95), (0.95, 1.01)):
        b = [r for r in rows if (r["card"] or r["rev_pos"] >= 1) and lo <= r["conf"] < hi]
        if b:
            calib.append({"bucket": f"{lo:.2f}–{min(hi, 1):.2f}", "n": len(b),
                          "agree": round(sum(r["geo"] for r in b) / len(b), 2)})
    pct = lambda xs, f: round(sum(1 for r in xs if f(r)) / len(xs), 2) if xs else None  # noqa: E731
    return {
        "hotels": len(rows),
        "geo_says_sea": sum(r["geo"] for r in rows),
        "card_claims": len(n_card), "recall_vs_card": pct(n_card, lambda r: r["geo"]),
        "reviews_praise": len(n_rev), "recall_vs_reviews": pct(n_rev, lambda r: r["geo"]),
        "strong_positive": len(strong), "recall_vs_strong": pct(strong, lambda r: r["geo"]),
        "reviews_complain_no_view": len(n_neg), "geo_agrees_no_view": pct(n_neg, lambda r: not r["geo"]),
        "geo_yes_not_advertised": len(geo_yes_no_claim),
        "calibration": calib,
        "note": "Разметка слабая: карточка и отзывы независимы от расчёта, но сами неточны. «Вид заявлен, расчёт "
                "говорит нет» — кандидаты на вопрос отельеру; «расчёт видит море, а в карточке об этом ни слова» — "
                "сильная сторона, о которой отель не рассказывает.",
    }


def noise_check():
    rows = []
    for h in gd.load().hotels:
        g = _geo(h["id"], "night_quiet")
        if not g:
            continue
        r = text.reviews_search(h["id"], ["шум", "шумно", "слышн", "тонкие стены", "громк", "не выспал"],
                                exclude=["не было слышно", "не шумно", "без шума", "тихо"])
        rows.append({"loud": g["value"]["night_db_loud"], "quiet_db": g["value"]["night_db_quiet"],
                     "complaints": r["negative"], "total": r["reviews_total"]})
    out = []
    for lo, hi, name in ((0, 50, "< 50 дБ"), (50, 58, "50–58 дБ"), (58, 200, "≥ 58 дБ")):
        b = [r for r in rows if lo <= r["loud"] < hi]
        if b:
            out.append({"loud_side": name, "hotels": len(b),
                        "complaints_per_100_reviews": round(100 * sum(r["complaints"] for r in b) / max(1, sum(r["total"] for r in b)), 1)})
    return {"by_loudest_side": out,
            "note": "Если модель шума осмысленна, жалоб должно быть больше там, где расчёт громче."}


CLAIM_MIN = re.compile(r"(\d{1,2})\s*(?:-|–)?\s*(?:минут\w*|мин\.?)\s*(?:ходьбы\s*|пешком\s*|пешей прогулки\s*)?(?:до|от)\s*(?:моря|пляж\w*|берега)", re.I)
CLAIM_M = re.compile(r"(\d{2,4})\s*(?:м\.?|метр\w*)\s*(?:до|от)\s*(?:моря|пляж\w*|берега)", re.I)


def claims_audit():
    out = []
    for h in gd.load().hotels:
        d = h["description"] or ""
        g = _geo(h["id"], "beach_walk")
        if not g:
            continue
        v = g["value"]
        m = CLAIM_MIN.search(d)
        if m:
            out.append({"hotel": h["name"], "hotel_id": h["id"], "claim": m.group(0), "claimed_min": int(m.group(1)),
                        "computed_min": v["minutes_there"], "computed_back_min": v["minutes_back"], "climb_m": v["climb_back_m"]})
            continue
        m = CLAIM_M.search(d)
        if m:
            out.append({"hotel": h["name"], "hotel_id": h["id"], "claim": m.group(0), "claimed_m": int(m.group(1)),
                        "computed_m": v["distance_m"], "computed_min": v["minutes_there"], "climb_m": v["climb_back_m"]})
    worse = [r for r in out if ("claimed_min" in r and r["computed_min"] > r["claimed_min"] * 1.5 + 2)
             or ("claimed_m" in r and r["computed_m"] > r["claimed_m"] * 1.5 + 100)]
    return {"hotels_with_claims": len(out), "overstated": len(worse), "examples": sorted(worse, key=lambda r: -(r.get("computed_min") or 0))[:8],
            "all": out}


def coverage():
    out = []
    hotels = gd.load().hotels
    for cid, spec in registry.public_chars().items():
        st = Counter(store.resolve(h["id"], spec)["status"] for h in hotels)
        out.append({"char": cid, "name": spec["name"], "known": st["known"], "conflict": st["conflict"],
                    "stale": st["stale"], "unknown": st["unknown"], "coverage": round(1 - st["unknown"] / len(hotels), 2)})
    return out


def questions_stats():
    qs = store.questions()
    hotels = len(gd.load().hotels)
    per = Counter(q["hotel_id"] for q in qs)
    return {"total": len(qs), "answered": sum(1 for q in qs if q["status"] == "answered"),
            "hotels_with_questions": len(per), "share_hotels": round(len(per) / hotels, 2),
            "per_hotel_avg": round(len(qs) / hotels, 2), "max_per_hotel": max(per.values()) if per else 0,
            "by_char": Counter(q["char_id"] for q in qs), "by_reason": Counter(q["reason"].split(" ")[0] for q in qs),
            "facts_total": store.conn().execute("SELECT COUNT(*) FROM facts WHERE active=1").fetchone()[0]}


def photos_check():
    """Сверка с фото: независимый датчик, в расчёт не входит. Море из номера на фото → видит ли его расчёт (полнота);
    на фото номеров и балконов моря нет → согласен ли расчёт (первая проверка точности «нет»)."""
    pos, neg, labeled = [], [], 0
    for h in gd.load().hotels:
        g = _geo(h["id"], "sea_view")
        ev = photos.photo_labels(h["id"])   # меток напрямую: отрицательных фактов в базе нет, это только диагностика
        if not g or not ev["room_photos"]:
            continue
        labeled += 1
        row = {"id": h["id"], "name": h["name"], "geo": bool(g["value"]["has"]), "geo_conf": g["confidence"],
               "from_floor": g["value"].get("from_floor")}
        (pos if ev["sea_from_room"] else neg).append(row)
    pct = lambda xs, f: round(sum(1 for r in xs if f(r)) / len(xs), 2) if xs else None  # noqa: E731
    miss = [r for r in pos if not r["geo"]]
    base = round(sum(1 for r in pos + neg if r["geo"]) / len(pos + neg), 2) if pos + neg else None  # доля «море» по расчёту среди отелей с фото
    return {
        "hotels_with_room_photos": labeled,
        "geo_sea_base_rate": base, "geo_no_sea_chance": None if base is None else round(1 - base, 2),
        "photo_sea_from_room": len(pos), "recall_geo_vs_photos": pct(pos, lambda r: r["geo"]),
        "geo_misses": [{"hotel": r["name"], "hotel_id": r["id"], "geo_conf": r["geo_conf"]} for r in miss][:8],
        "photo_no_sea": len(neg), "geo_agrees_no_sea": pct(neg, lambda r: not r["geo"]),
        "geo_sea_but_not_on_photos": sum(1 for r in neg if r["geo"]),
        "note": "Отели снимают лучшие номера, а не все: «моря на фото нет» не доказывает, что его нет ни в одном номере, "
                "поэтому второе число занижает согласие расчёта. Отрицательный итог только диагностика, фактом в базе он не становится. Фасад и пляж не считаются: учитываются только кадры "
                "номеров, балконов и видов из окна. Разметка зрением модели, ручной сверки пока нет.",
    }


def report():
    return {"sea_view": sea_view_check(), "photos": photos_check(), "noise": noise_check(), "claims": {k: v for k, v in claims_audit().items() if k != "all"},
            "coverage": coverage(), "questions": questions_stats()}
