"""Радар изменений: что поменялось вокруг отеля.

Отельер отвечает через день-два, а факт уже устарел: рядом начали стройку, в отзывах пошли жалобы на шум,
оценка просела. Радар ищет четыре вида сигналов и ничего не придумывает: у каждого есть датированные улики.

1. review_spike: всплеск жалоб по теме в последние 90 дней против собственной истории отеля.
   Условие (все три): >= 3 свежих упоминания; точный тест Фишера (односторонний) p < 0.01 против истории;
   доля свежих упоминаний минимум втрое выше сглаженной доли в истории. Если своей истории мало (меньше 5 старых
   отзывов; в данных у отеля не больше 20 последних отзывов), базой служит типичный отель: доля упоминаний
   по всем отелям, биномиальный хвост p < 0.001 и >= 4 упоминаний (строже, потому что хронический шум не новость).
   Тестов много (отель x тема), поэтому p-значения всех тестов проходят поправку Бенджамини-Хохберга (q < 0.1).
   Прошедшие поправку это сигнал; остальные с сырым p < 0.01 помечены «сигнал, не доказательство» и идут с низкой серьёзностью.
2. rating_drift: средняя оценка свежих отзывов ниже исторической на >= 1.0 балла (шкала 10), свежих >= 5, и
   односторонний перестановочный тест p < 0.05; серьёзность «высокая» только при p < 0.01.
3. osm_construction: стройплощадка OSM в 150 м. Снимок OSM статичный, поэтому честно: «на снимке OSM от даты».
   Если стройка уже учтена в фактах отеля, это не изменение: сигнал помечен known и в сводку не входит.
4. stale_fact: срок годности важного факта (вес в реестре >= 0.6) истёк.

scan() только читает. apply() помечает затронутые факты на перепроверку (копия факта с истёкшим сроком, старый
уходит в историю, значит resolver покажет «устарело», а recheck_stale пересчитает) и ставит ОДИН вопрос
отельеру на сигнал через общую очередь вопросов, не больше трёх открытых на отель.
"""
import math
import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import numpy as np

from app import geodata as gd
from app import registry, store

WINDOW_DAYS = 90
MIN_RECENT_MENTIONS = 3
MIN_HISTORY = 5
P_MAX = 0.01
RATIO_MIN = 3.0
DRIFT_DROP = 1.0
DRIFT_MIN_N = 5
DRIFT_P = 0.05
DRIFT_P_HIGH = 0.01
PERMUTATIONS = 20000
FDR_Q = 0.1
OSM_RADIUS_M = 150
OSM_MIN_AREA_M2 = 1500
IMPORTANT_WEIGHT = 0.6
BUDGET = 3

# Темы: тема -> характеристика реестра, по которой стоит перепроверить факт. Ищем в «не понравилось».
# NEG: оговорки, после которых упоминание не жалоба («не шумно», «без стройки»).
TOPICS = {
    "construction": {"label": "стройка и ремонт", "char": "construction", "rx": re.compile(
        r"стройк|строител|стройплощад|отбойн|перфоратор|сверлил|долбил|ремонтн\w* работ|"
        r"(?:идёт|идет|шёл|шел|шли|велся|велись|делали|делают|начали|начался)\s+ремонт|"
        r"ремонт\s+(?:фасад|соседн|на этаж|в коридор|в отел|здания|крыш)", re.I),
        "neg": re.compile(r"не было (?:стройк|ремонт)|без (?:стройк|ремонт)|нет стройк|стройк\w* нет", re.I)},
    "noise": {"label": "шум", "char": "night_quiet", "rx": re.compile(
        r"шум|громк|музык|слышн|тонкие стен|не выспал|не спал|бары|клуб|стучат|крики", re.I),
        "neg": re.compile(r"не (?:было|очень|так) (?:шум|слышн|громк)|не шумно|не слышно|без шума|шума нет|тихо", re.I)},
    "beach": {"label": "пляж и вода", "char": "beach_walk", "rx": re.compile(
        r"грязн\w* (?:пляж|вод|мор)|(?:пляж|вода|море)\s+(?:грязн|мутн|захламл|переполн)|мутн\w* (?:вод|мор)|"
        r"мазут|медуз|пляж\w*\s+(?:мусор|камн|узк)|мусор\w* на пляж|нельзя купаться|купаться нельзя", re.I),
        "neg": re.compile(r"не грязн|чист", re.I)},
    "wifi": {"label": "Wi-Fi", "char": "wifi", "rx": re.compile(
        r"wi-?fi|вай-?фай|интернет|связь не", re.I),
        "neg": re.compile(r"не (?:было )?проблем|без проблем|хорош\w* (?:wi|вай|интернет)|отличн\w* (?:wi|вай|интернет)", re.I)},
    "clean": {"label": "чистота", "char": None, "rx": re.compile(
        r"грязн|пыльн|пыль|таракан|клоп|плесен|затхл|не убира|не убрал|вонь|воняет|пахнет|неприятн\w* запах|мусор|волосы", re.I),
        "neg": re.compile(r"не грязн|было чисто|чисто и", re.I)},
    "staff": {"label": "персонал", "char": None, "rx": re.compile(
        r"груб|хамств|хамил|хамит|невежлив|неприветлив|игнорир|безразлич|не реагир", re.I),
        "neg": re.compile(r"не груб|не хамил", re.I)},
}
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
ASPECT_RU = {"cleanness": "чистота", "location": "расположение", "price": "цена", "services": "сервис", "room": "номер",
             "meal": "питание", "wifi": "Wi-Fi"}
KIND_LABEL = {"review_spike": "всплеск жалоб", "rating_drift": "падение оценки", "osm_construction": "стройка рядом",
              "stale_fact": "факт устарел"}
VOI = {"high": 1.6, "medium": 1.2, "low": 0.8}


def _num(x, nd=1):
    """Число с десятичной запятой."""
    return f"{x:.{nd}f}".replace(".", ",")


def _ru(d):
    """ISO-дата в 24.07.2026."""
    return ".".join(reversed(str(d or "")[:10].split("-")))


def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _perm_p(a, b, seed):
    """Односторонний перестановочный тест: средняя оценка свежих отзывов `a` ниже исторических `b` только случайно.
    Генератор с фиксированным зерном, поэтому результат воспроизводим. p = (число перестановок не слабее + 1) / (N + 1)."""
    x = np.array(list(a) + list(b), dtype=float)
    obs = x[len(a):].mean() - x[:len(a)].mean()
    rng = np.random.default_rng(seed)
    idx = rng.random((PERMUTATIONS, len(x))).argsort(axis=1)
    sh = x[idx]
    d = sh[:, len(a):].mean(axis=1) - sh[:, :len(a)].mean(axis=1)
    return float((np.sum(d >= obs - 1e-12) + 1) / (PERMUTATIONS + 1))


def _bh(pvals, q):
    """Бенджамини-Хохберг: множество индексов, прошедших поправку на множественные проверки при уровне q."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    cut = -1
    for rank, i in enumerate(order, 1):
        if pvals[i] <= q * rank / m:
            cut = rank
    return {order[j] for j in range(cut)}


def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        now = datetime.fromisoformat(now)
    if isinstance(now, date) and not isinstance(now, datetime):
        now = datetime(now.year, now.month, now.day, 23, 59, tzinfo=timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _fisher_upper(k, n, k0, n0):
    """P(X >= k) при гипергеометрическом распределении: доля упоминаний в свежих отзывах не выше, чем в истории
    (односторонний точный тест Фишера по таблице 2x2)."""
    total, hits = n + n0, k + k0
    den = math.comb(total, n)
    return sum(math.comb(hits, i) * math.comb(total - hits, n - i) for i in range(k, min(n, hits) + 1)) / den


def _binom_upper(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


@lru_cache(maxsize=1)
def _global_rates(_key):
    """Доля отзывов с жалобой по теме у типичного отеля (все отзывы датасета)."""
    rs = [r for h in gd.load().hotels for r in h["reviews"]]
    return {t: (sum(1 for r in rs if _mention(r, t)) + 1) / (len(rs) + 2) for t in TOPICS}


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?;\n])\s+|\n", text or "") if s.strip()]


def _mention(review, topic):
    """Цитата-жалоба по теме в отзыве или None."""
    spec = TOPICS[topic]
    for s in _sentences(review.get("minus")):
        if spec["rx"].search(s) and not spec["neg"].search(s):
            return s[:220]
    if topic == "wifi" and review.get("wifi") == "slow":
        return "оценка Wi-Fi гостем: медленный"
    return None


def _review_date(r):
    try:
        return date.fromisoformat((r.get("date") or "")[:10])
    except ValueError:
        return None


def _split(hotel, now_d):
    start = now_d - timedelta(days=WINDOW_DAYS)
    recent, hist = [], []
    for r in hotel.get("reviews") or []:
        d = _review_date(r)
        if d is None or d > now_d:
            continue
        (recent if d > start else hist).append(r)
    return recent, hist


def _spikes(hotel, recent, hist):
    """Все проверки отель x тема: [(p, алерт или None)]. Алерт есть, если тест прошёл свои пороги; поправка на
    множественные проверки применяется в scan() ко всем p сразу."""
    out = []
    n, n0 = len(recent), len(hist)
    if n < MIN_RECENT_MENTIONS:
        return out
    thin = n0 < MIN_HISTORY
    for topic, spec in TOPICS.items():
        rec = [(r, _mention(r, topic)) for r in recent]
        rec = [(r, q) for r, q in rec if q]
        k = len(rec)
        if thin:
            g = _global_rates(len(gd.load().hotels))[topic]
            k0, n0_, ratio, p = 0, 0, (k / n) / g, _binom_upper(k, n, g)
            ok = k >= MIN_RECENT_MENTIONS + 1 and p < P_MAX / 10 and ratio >= RATIO_MIN
        else:
            k0 = sum(1 for r in hist if _mention(r, topic))
            n0_ = n0
            ratio = (k / n) / ((k0 + 0.5) / (n0 + 1))
            p = _fisher_upper(k, n, k0, n0)
            ok = k >= MIN_RECENT_MENTIONS and p < P_MAX and ratio >= RATIO_MIN
        if not ok:
            out.append((p, None))
            continue
        quotes = [{"date": r["date"], "quote": q, "review_id": r.get("id")}
                  for r, q in sorted(rec, key=lambda t: t[0]["date"], reverse=True)[:5]]
        sev = "high" if (p < 1e-4 and k >= 4) else "medium"
        text = (f"{WINDOW_DAYS} дней: {k} из {n} {plural(n, 'свежего отзыва', 'свежих отзывов', 'свежих отзывов')} жалуются на «{spec['label']}», "
                + (f"у типичного отеля такая жалоба в {_num(g * 100)}% отзывов. Своей истории мало, p={_num(p, 5)}." if thin
                    else f"в истории {k0} из {n0}"
                         + (f". Доля выросла в {_num(ratio)} {plural(ratio, 'раз', 'раза', 'раз')}, p={_num(p, 4)}." if k0 else f", p={_num(p, 4)}.")))
        out.append((p, _alert(hotel, "review_spike", sev, spec["char"], topic, text, quotes,
                              {"recent_mentions": k, "recent_reviews": n, "history_mentions": k0, "history_reviews": n0_,
                               "baseline": "global" if thin else "own", "rate_ratio": round(ratio, 1) if k0 else None,
                               "p_value": round(p, 6), "window_days": WINDOW_DAYS})))
    return out


ASPECT_RX = {
    "wifi": TOPICS["wifi"]["rx"],
    "cleanness": TOPICS["clean"]["rx"],
    "services": re.compile(r"персонал|администратор|ресепшн|рецепшн|сервис|обслуживан|" + TOPICS["staff"]["rx"].pattern, re.I),
    "location": re.compile(r"расположен|локаци|далеко|до моря|до пляжа|до центра|вдали|шум", re.I),
    "price": re.compile(r"цен[аыуе]|дорог|стоимост|переплат|завышен", re.I),
    "room": re.compile(r"номер|комнат|кровать|матрас|окн|вид|ремонт|мебел|кондиционер|душ|санузел|ванн", re.I),
    "meal": re.compile(r"завтрак|питани|еда|кормя|ужин|обед", re.I),
}


def _drift(hotel, recent, hist):
    rate = lambda rs: [r["rating"] for r in rs if isinstance(r.get("rating"), (int, float))]  # noqa: E731
    a, b = rate(recent), rate(hist)
    if len(a) < DRIFT_MIN_N or len(b) < DRIFT_MIN_N:
        return []
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    if mb - ma < DRIFT_DROP:
        return []
    p = _perm_p(a, b, int(hotel["id"]) % (2 ** 32) if str(hotel["id"]).isdigit() else sum(map(ord, str(hotel["id"]))))
    if p >= DRIFT_P:
        return []
    # аспект, просевший сильнее всего: по нему можно привязать вопрос к характеристике (пока только Wi-Fi)
    drops = {}
    for asp in ("cleanness", "location", "price", "services", "room", "meal", "wifi"):
        x = [r["scores"][asp] for r in recent if (r.get("scores") or {}).get(asp) is not None]
        y = [r["scores"][asp] for r in hist if (r.get("scores") or {}).get(asp) is not None]
        if len(x) >= 3 and len(y) >= 3:
            drops[asp] = sum(y) / len(y) - sum(x) / len(x)
    worst = max(drops, key=drops.get) if drops else None
    # цитата должна говорить о том же аспекте, что заявлен; если такой нет, берём самые низкие отзывы и честно подписываем
    cand = sorted((r for r in recent if isinstance(r.get("rating"), (int, float)) and r["rating"] < mb
                   and len((r.get("minus") or "").strip("- ")) > 8), key=lambda r: (r["rating"], r["date"]))
    on_topic = [r for r in cand if worst in ASPECT_RX and ASPECT_RX[worst].search(r.get("minus") or "")] if worst else []
    low = (on_topic or cand)[:3]
    tag = "" if on_topic else "отзыв целиком, "
    quotes = [{"date": r["date"], "quote": f"{tag}оценка {_num(r['rating']) if r['rating'] % 1 else int(r['rating'])}: " + _snip(_pick(r.get("minus") or "", worst if on_topic else None)),
               "review_id": r.get("id")} for r in low]
    text = (f"Средняя оценка за {WINDOW_DAYS} дней {_num(ma)} при {_num(mb)} в истории (свежих отзывов {len(a)}, "
            f"старых {len(b)}), минус {_num(mb - ma)}, p={_num(p, 4)}." + (f" Сильнее всего просел аспект «{ASPECT_RU[worst]}»." if worst else ""))
    return [_alert(hotel, "rating_drift", "high" if p < DRIFT_P_HIGH else "medium", "wifi" if worst == "wifi" else None,
                   worst or "rating", text, quotes,
                   {"recent_mean": round(ma, 2), "history_mean": round(mb, 2), "drop": round(mb - ma, 2), "p_value": round(p, 5),
                    "recent_reviews": len(a), "history_reviews": len(b), "worst_aspect": worst})]


def _pick(text, aspect):
    """Фраза отзыва про аспект (или весь минус, если аспект не задан)."""
    text = text.strip("- ").strip()
    if aspect in ASPECT_RX:
        for s in _sentences(text):
            if ASPECT_RX[aspect].search(s):
                return s.lstrip("- ")
    return text


def _snip(t, n=180):
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def _area(xy):
    x, y = xy[:, 0], xy[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2)


@lru_cache(maxsize=2)
def _sites(_key):
    """Стройплощадки OSM: контуры landuse/building=construction. Мелкие (< 1500 м²) и точки отбрасываем:
    это не стройка, слышная из окон, а ремонт крыльца или пристройки."""
    geo = gd.load()
    sites = []
    for b in geo.buildings:
        t = b.tags
        if t.get("building") == "construction" or t.get("landuse") == "construction":
            if _area(b.xy) >= OSM_MIN_AREA_M2:
                sites.append((b.xy, t, b.osm_id))
    return sites


def _osm(hotel):
    geo = gd.load()
    x, y = (hotel["x"], hotel["y"]) if "x" in hotel else (float(v) for v in gd.to_xy(hotel["lat"], hotel["lon"]))
    best = None
    for xy, t, oid in _sites(geo.osm_meta["osm_base"]):
        d = float(np.min(np.hypot(xy[:, 0] - x, xy[:, 1] - y)))
        if d <= OSM_RADIUS_M and (best is None or d < best[0]):
            best = (d, t, oid)
    if best is None:
        return []
    d, t, oid = best
    base = str(geo.osm_meta["osm_base"])[:10]
    known = next((f for f in store.facts(hotel["id"], "construction") if f["source"] == "osm"), None)
    known_near = bool(known and (known["value"] or {}).get("none_near") is False)
    text = (f"На снимке OSM от {_ru(base)} в {round(d)} м от отеля стройплощадка. "
            + ("Факт «Стройка рядом» это уже учитывает, но OSM не знает, идёт ли стройка сейчас."
               if known_near else "В фактах отеля стройки рядом нет: данные расходятся."))
    return [_alert(hotel, "osm_construction", "low" if known_near else "medium", "construction", "construction", text, [],
                   {"distance_m": round(d), "osm_id": oid, "osm_snapshot": base, "tags": {k: t[k] for k in list(t)[:6]},
                    "known_in_facts": known_near}, known=known_near)]


def _stale(hotels, now_dt):
    ids = {h["id"]: h for h in hotels}
    chars = {cid: s for cid, s in registry.all_chars().items() if s.get("weight", 0.5) >= IMPORTANT_WEIGHT}
    rows = store.conn().execute("SELECT hotel_id, char_id, source, observed_at, valid_until, evidence FROM facts "
                                "WHERE active=1 AND valid_until IS NOT NULL AND valid_until < ?", (now_dt.isoformat(),)).fetchall()
    grouped = {}
    for r in rows:
        if r["hotel_id"] in ids and r["char_id"] in chars and '"radar"' not in (r["evidence"] or ""):
            grouped.setdefault((r["hotel_id"], r["char_id"]), []).append(r)
    out = []
    for (hid, cid), rs in grouped.items():
        until = max(r["valid_until"] for r in rs)[:10]
        text = f"Срок годности факта «{chars[cid]['name']}» истёк {_ru(until)}: данные надо перепроверить."
        out.append(_alert(ids[hid], "stale_fact", "low", cid, cid, text, [],
                          {"valid_until": until, "sources": sorted({r["source"] for r in rs})}))
    return out


def _alert(hotel, kind, severity, char_id, topic, text, quotes, stats, known=False):
    return {"known": known, "id": f"{kind}:{hotel['id']}:{topic}", "hotel_id": hotel["id"], "hotel_name": hotel.get("name"),
            "kind": kind, "severity": severity, "char_id": char_id, "topic": topic,
            "title": KIND_LABEL[kind] + (f": {TOPICS[topic]['label']}" if kind == "review_spike" else ""),
            "evidence": {"text": text, "quotes": quotes, "stats": stats}}


def scan(hotels=None, now=None):
    """Все сигналы по отелям (по умолчанию весь датасет), от серьёзных к слабым. Ничего не пишет.
    Всплески жалоб проходят поправку Бенджамини-Хохберга по всем проверкам отель x тема."""
    now_dt = _now(now)
    hotels = hotels if hotels is not None else gd.load().hotels
    alerts, tests = [], []
    for h in hotels:
        recent, hist = _split(h, now_dt.date())
        tests += _spikes(h, recent, hist)
        alerts += _drift(h, recent, hist)
        alerts += _osm(h)
    passed = _bh([p for p, _ in tests], FDR_Q)
    for i, (p, a) in enumerate(tests):
        if a is None:
            continue
        a["evidence"]["stats"]["tests_total"] = len(tests)
        a["evidence"]["stats"]["fdr_pass"] = i in passed
        if i not in passed:
            a["severity"] = "low"
            a["weak"] = True
            a["title"] += " (сигнал, не доказательство)"
            a["evidence"]["text"] += f" Проверок по отелям и темам: {len(tests)}, поправка на множественные проверки этот результат не пропускает."
        alerts.append(a)
    alerts += _stale(hotels, now_dt)
    alerts.sort(key=lambda a: (SEVERITY_RANK[a["severity"]], a["hotel_name"] or "", a["kind"]))
    return alerts


def summary(alerts, hotels_total=None):
    """Сводка по изменениям. Известные стройки (уже учтены в фактах) не изменения и считаются отдельно."""
    hotels_total = hotels_total or len(gd.load().hotels)
    changes = [a for a in alerts if not a.get("known")]
    known = [a for a in alerts if a.get("known")]
    by_kind, by_sev = {}, {}
    for a in changes:
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1
        by_sev[a["severity"]] = by_sev.get(a["severity"], 0) + 1
    hot = {a["hotel_id"] for a in changes}
    return {"alerts": len(changes), "hotels_with_alerts": len(hot), "hotels_total": hotels_total,
            "alert_rate": round(len(hot) / hotels_total, 3), "by_kind": by_kind, "by_severity": by_sev,
            "known_construction": len(known), "known_hotels": len({a["hotel_id"] for a in known})}


# ---------- apply ----------

def _mark_recheck(alert, now_dt):
    """Копия активных фактов характеристики с истёкшим сроком и уверенностью x0.8. Старый факт уходит в историю
    (put_fact), resolver покажет «устарело», recheck_stale пересчитает. Повторный apply ничего не меняет."""
    marked = 0
    for f in store.facts(alert["hotel_id"], alert["char_id"]):
        if "radar" in (f["evidence"] or {}):
            continue
        observed = datetime.fromisoformat(f["observed_at"])
        ttl = (now_dt - timedelta(seconds=1) - observed) / timedelta(days=1)
        ev = dict(f["evidence"] or {}) | {"radar": {"alert": alert["id"], "at": now_dt.isoformat(), "kind": alert["kind"],
                                                    "why": alert["evidence"]["text"]}}
        store.put_fact(f["hotel_id"], f["char_id"], f["source"], f["value"], (f["confidence"] or 0) * 0.8, f["summary"],
                       f["method"], ttl, ev, f["scope"], f["recipe_version"], observed_at=f["observed_at"])
        marked += 1
    return marked


def _question_text(a):
    ev = a["evidence"]
    s = ev["stats"]
    if a["kind"] == "review_spike":
        q = ev["quotes"][0] if ev["quotes"] else None
        return (f"За последние {s['window_days']} дней {s['recent_mentions']} из {s['recent_reviews']} {plural(s['recent_reviews'], 'отзыва', 'отзывов', 'отзывов')} упоминают "
                f"«{TOPICS[a['topic']]['label']}»"
                + (", это заметно больше, чем у типичного отеля." if s["baseline"] == "global"
                   else f" (раньше {s['history_mentions']} из {s['history_reviews']}).")
                + (f" Например: «{q['quote'][:140]}» ({_ru(q['date'])})." if q else "")
                + " Что изменилось и как это сейчас выглядит для гостей?")
    if a["kind"] == "osm_construction":
        return (f"На снимке OSM от {_ru(s['osm_snapshot'])} в {s['distance_m']} м от отеля отмечена стройплощадка. "
                f"Идёт ли стройка сейчас и слышно ли её гостям?")
    if a["kind"] == "stale_fact":
        cname = (registry.get(a["char_id"]) or {}).get("name") or a["char_id"]
        return f"Уточните, пожалуйста, «{cname}»: данные устарели ({_ru(s['valid_until'])}). Всё ещё так?"
    if a["kind"] == "rating_drift":
        w = s.get("worst_aspect")
        return (f"Свежие отзывы оценивают отель ниже обычного ({_num(s['recent_mean'])} против {_num(s['history_mean'])})"
                + (f", сильнее всего «{ASPECT_RU[w]}»" if w else "") + ". Что-то изменилось?")
    return ev["text"] + " Что изменилось?"


def _make_room(hotel_id, voi):
    """Бюджет вопросов на отель (BUDGET открытых). Если он занят, радар вытесняет самый дешёвый вопрос,
    но только если сигнал ценнее: реальное изменение важнее общего «уверенность низкая»."""
    opened = store.questions(hotel_id=hotel_id, status="open")
    if len(opened) < BUDGET:
        return True
    low = min(opened, key=lambda q: q["voi"])
    if low["voi"] >= voi:
        return False
    c = store.conn()
    c.execute("UPDATE questions SET status='replaced' WHERE id=?", (low["id"],))
    c.commit()
    store.log_event("radar_replaced_question", hotel_id, low["char_id"], {"question_id": low["id"], "voi": low["voi"]})
    return True


def apply(alerts, now=None):
    """Помечает факты на перепроверку и ставит по одному вопросу отельеру на сигнал. Возвращает итог по каждому."""
    now_dt = _now(now)
    alerts = sorted(alerts, key=lambda a: SEVERITY_RANK.get(a["severity"], 9))
    results = []
    for a in alerts:
        res = {"id": a["id"], "hotel_id": a["hotel_id"], "marked_facts": 0, "question_id": None, "state": "event_only"}
        if a.get("char_id") and registry.get(a["char_id"]):
            if a["kind"] != "stale_fact":
                res["marked_facts"] = _mark_recheck(a, now_dt)
            voi = VOI[a["severity"]] * registry.get(a["char_id"]).get("weight", 0.5) + 0.3
            if any(q["char_id"] == a["char_id"] for q in store.questions(hotel_id=a["hotel_id"], status="open")):
                res["state"] = "already_queued"
            elif _make_room(a["hotel_id"], voi):
                qid = store.add_question(a["hotel_id"], a["char_id"], _question_text(a), f"радар: {KIND_LABEL[a['kind']]}", voi)
                res["question_id"] = qid
                res["state"] = "queued" if qid else "already_queued"
            else:
                res["state"] = "budget_full"
        store.log_event("radar_alert", a["hotel_id"], a.get("char_id"),
                        {"id": a["id"], "kind": a["kind"], "severity": a["severity"], "text": a["evidence"]["text"],
                         "quotes": a["evidence"]["quotes"][:3], "result": res["state"], "question_id": res["question_id"],
                         "marked_facts": res["marked_facts"]})
        results.append(res)
    return results


def states(alerts):
    """Статус каждого сигнала по очереди вопросов и журналу: new / queued / answered / event_only."""
    c = store.conn()
    out = {}
    applied = {}
    for r in c.execute("SELECT payload FROM events WHERE kind='radar_alert'").fetchall():
        import json
        p = json.loads(r["payload"])
        applied[p["id"]] = p.get("result")
    for a in alerts:
        st = "new"
        if a.get("char_id"):
            q = c.execute("SELECT status FROM questions WHERE hotel_id=? AND char_id=? AND reason LIKE 'радар%' "
                          "ORDER BY id DESC LIMIT 1", (a["hotel_id"], a["char_id"])).fetchone()
            if q:
                st = {"open": "queued", "answered": "answered"}.get(q["status"], "new")
        if st == "new" and a["id"] in applied:
            st = "queued" if applied[a["id"]] in ("queued", "already_queued") else "event_only"
        out[a["id"]] = st
    return out
