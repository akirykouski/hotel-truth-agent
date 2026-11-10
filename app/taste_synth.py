"""Синтетические посетители для проверки и демо кластеров вкуса. Всегда помечены synthetic=1 и в порог не идут.

У каждой персоны скрытый вкус (веса по признакам отелей), типичный контекст (устройство, сеть, регион, час)
и моторика. signal — доля посетителей, чей контекст взят у персоны; остальные получают случайный контекст.
signal=0 — контроль: контекст ничего не говорит о вкусе, и честная перестановка не должна давать рост.
Сценарий: поиск по 1–2 характеристикам персоны → выдача без персонализации (по рейтингу с шумом) →
открытия с вероятностью ∝ exp(полезность) × поправка на позицию → время просмотра.
"""
import time

import numpy as np

from app import taste, visitors

PERSONAS = [
    {"name": "семья с детьми", "likes": {"kids": 1.2, "family": 1.2, "pool": 0.8, "food_near": 0.5, "beach_walk": 0.6},
     "query": ["family", "pool", "kids"], "device": "phone", "os": "Android", "net": "mobile",
     "region": "Moscow Oblast", "hour": 21, "motor": 45},
    {"name": "пара на закат", "likes": {"sunset": 1.2, "sea_view": 1.2, "adults_only": 0.9, "spa": 0.7, "balcony": 0.5},
     "query": ["sunset", "sea_view", "adults_only"], "device": "phone", "os": "iOS", "net": "home",
     "region": "Moscow", "hour": 23, "motor": 70},
    {"name": "командировка", "likes": {"wifi": 1.2, "night_checkin": 1.0, "transfer": 0.8, "night_open": 0.6, "rating_hi": 0.5},
     "query": ["wifi", "night_checkin"], "device": "desktop", "os": "Windows", "net": "corp",
     "region": "Saint Petersburg", "hour": 11, "motor": 80},
    {"name": "экономный", "likes": {"price_low": 1.5, "kitchen": 1.0, "food_near": 0.6, "stars_hi": -0.8},
     "query": ["kitchen"], "device": "phone", "os": "Android", "net": "mobile",
     "region": "Krasnodar Krai", "hour": 14, "motor": 55},
    {"name": "тишина и сон", "likes": {"night_quiet": 1.3, "soundproofing": 1.0, "construction": 0.8, "spa": 0.4},
     "query": ["night_quiet", "soundproofing"], "device": "desktop", "os": "macOS", "net": "home",
     "region": "Moscow", "hour": 9, "motor": 35},
]
REGIONS = ["Moscow", "Moscow Oblast", "Saint Petersburg", "Krasnodar Krai", "Sverdlovsk Oblast", "Tatarstan"]


def _motor(base, rng):
    return {k: int(np.clip(base + rng.normal(0, 12), 0, 100)) for k in taste.MOTOR_PARTS}


def _context(p, rng, from_persona):
    if from_persona:
        dev, os_, net, reg, hour = p["device"], p["os"], p["net"], p["region"], (p["hour"] + int(rng.integers(-2, 3))) % 24
    else:
        dev = str(rng.choice(taste.DEVICES))
        os_ = str(rng.choice(taste.OSES))
        net = str(rng.choice(taste.NETS))
        reg = str(rng.choice(REGIONS))
        hour = int(rng.integers(0, 24))
    return dev, os_, net, reg, hour


def generate(n=600, signal=0.8, seed=7, sessions=(1, 3), opens=(1, 3), shown=30, prefix="syn", db=None, start=None):
    """Пишет n синтетических посетителей с событиями. Возвращает {vid: имя персоны}."""
    rng = np.random.default_rng(seed)
    H = taste.hotels()
    cols = H["cols"]
    t0 = start or time.time() - 86400
    truth = {}
    for i in range(n):
        p = PERSONAS[i % len(PERSONAS)]
        vid = f"{prefix}-{seed}-{i}"
        truth[vid] = p["name"]
        from_p = rng.random() < signal
        dev, os_, net, reg, hour = _context(p, rng, from_p)
        ua = {"user-agent": {"phone": "Mozilla/5.0 (iPhone) Mobile Safari/604.1" if os_ == "iOS" else
                             "Mozilla/5.0 (Linux; Android 14) Mobile Chrome/130",
                             "tablet": "Mozilla/5.0 (iPad) Safari/604.1",
                             "desktop": "Mozilla/5.0 (Windows NT 10.0) Chrome/130" if os_ == "Windows" else
                             "Mozilla/5.0 (Macintosh; Mac OS X 14) Safari/605"}[dev], "accept-language": "ru-RU"}
        visitors.upsert_visit(vid, None, ua, {"hour": hour, "weekday": int(rng.integers(0, 7)), "langs": ["ru-RU"]},
                              synthetic=True, db=db)
        c = visitors.conn(db)
        c.execute("UPDATE visitors SET device=?, os=?, net=?, region=?, country='RU' WHERE vid=?", (dev, os_, net, reg, vid))
        visitors.save_profile(vid, {"parts": _motor(p["motor"] if from_p else int(rng.integers(20, 90)), rng),
                                    "segment": "regular", "confidence": 0.5}, db)
        w = np.zeros(len(cols))
        for k, x in p["likes"].items():
            if k in cols:
                w[cols.index(k)] = x
        util = H["raw"] @ w + rng.normal(0, 0.3, len(H["ids"]))
        t = t0 + i * 60
        for s in range(int(rng.integers(sessions[0], sessions[1] + 1))):
            q = [c_ for c_ in rng.choice(p["query"], size=min(len(p["query"]), int(rng.integers(1, 3))), replace=False)
                 if c_ in cols]
            match = np.ones(len(H["ids"]), bool)
            for c_ in q:
                match &= H["raw"][:, cols.index(c_)] >= 1
            base = H["raw"][:, cols.index("rating_hi")] + rng.normal(0, 0.7, len(H["ids"]))
            idx = sorted(range(len(H["ids"])), key=lambda j: (0 if match[j] else 1, -base[j]))[:shown]
            rows = [{"id": H["ids"][j], "bucket": "match" if match[j] else "maybe"} for j in idx]
            ev = [{"type": "search", "at": t, "data": {"chars": q}},
                  {"type": "serp", "at": t + 1, "data": {"rows": rows}}]
            u = np.array([util[j] for j in idx])
            pos_bias = 1 / np.log2(np.arange(len(idx)) + 2)
            pr = np.exp(u * 2.0) * pos_bias
            pr /= pr.sum()
            k = int(rng.integers(opens[0], opens[1] + 1))
            for m, j in enumerate(rng.choice(len(idx), size=min(k, len(idx)), replace=False, p=pr)):
                hid = rows[j]["id"]
                ev.append({"type": "open", "at": t + 5 + m * 30, "hotel_id": hid, "data": {"pos": int(j)}})
                ev.append({"type": "dwell", "at": t + 20 + m * 30, "hotel_id": hid,
                           "data": {"ms": int(max(1500, 8000 + 9000 * u[j] + rng.normal(0, 3000)))}})
            visitors.log_events(vid, ev, db)
            t += 3600
    return truth


def wipe(db=None):
    c = visitors.conn(db)
    vids = [r[0] for r in c.execute("SELECT vid FROM visitors WHERE synthetic=1")]
    for v in vids:
        visitors.forget(v, db)
    return len(vids)
