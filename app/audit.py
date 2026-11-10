"""Аудит заявлений: что отель или отельер сказал об отеле и что из этого подтверждается независимыми источниками.

Проверяем три вида заявлений:
  1) обещания расстояния до моря в описании («5 минут до моря») против расчёта маршрута с подъёмом;
  2) булевы заявления карточки и ответы отельера против апостериора по остальным источникам (расчёт, OSM, отзывы),
     причём сам проверяемый источник в апостериор не входит;
  3) «вид на море» в названиях категорий номеров против геометрии (с какого этажа и с какой стороны видно).
Вердикты: подтверждено / завышено / скрытая сильная сторона (расчёт видит больше, чем заявлено) / спорно.
«Завышено» говорим только когда сами входы расчёта надёжны (здание найдено точно, этажность известна, маршрут уверенный):
иначе «спорно» с причиной. Нечем проверить — заявление в аудит не попадает.
"""
from app import geodata as gd
from app import registry, store, truth
from app.metrics import CLAIM_M, CLAIM_MIN

OK, OVER, HIDDEN, DISPUTED = "подтверждено", "завышено", "скрытая сильная сторона", "спорно"
VERDICTS = (OK, OVER, HIDDEN, DISPUTED)
CHECKED_SOURCES = ("card", "hotelier")
SURE = 0.75   # с такой уверенностью независимая оценка считается достаточной, чтобы назвать заявление завышенным
MIN_COMPLAINTS = {"soundproofing": 2}   # одна жалоба в отзывах ещё не спор с карточкой
WALK_M_MIN = 80   # метров в минуту по ровной дороге: переводим «N минут» в прямую


ROADS_RU = {"trunk_link": "съезд с трассы", "trunk": "трасса", "primary_link": "съезд с магистрали", "primary": "магистраль",
            "secondary_link": "съезд", "secondary": "оживлённая улица", "tertiary_link": "съезд", "tertiary": "улица",
            "unclassified": "улица", "residential": "жилая улица"}
NIGHT_VENUES_RU = {"nightclub": "ночной клуб", "bar": "бар", "pub": "паб", "karaoke_box": "караоке", "music_venue": "концертная площадка"}


SIDES_GEN = {"СЗ": "северо-запада", "СВ": "северо-востока", "ЮЗ": "юго-запада", "ЮВ": "юго-востока",
             "С": "севера", "Ю": "юга", "З": "запада", "В": "востока"}
_SIDE = "|".join(sorted(SIDES_GEN, key=len, reverse=True))


def plain(text):
    """Сырые теги карты и сокращения сторон света из сводок фактов → слова для гостя."""
    import re
    text = re.sub(rf"(со стороны|на стороне) ({_SIDE})(?![А-Яа-яЁёA-Za-z])", lambda m: f"{m.group(1)} {SIDES_GEN[m.group(2)]}", text)
    text = re.sub(rf"(шумнее всего) ({_SIDE})(?![А-Яа-яЁёA-Za-z])", lambda m: f"{m.group(1)} со стороны {SIDES_GEN[m.group(2)]}", text)
    text = re.sub(r"\s*\((?:карточка|отзывы|OSM)\)", "", text)   # источник и так назван рядом: «(карточка) (карточка Островка)» дважды
    for k, v in {**ROADS_RU, **NIGHT_VENUES_RU}.items():
        text = re.sub(rf"дорога {k}\b", v, text)
        text = re.sub(rf"\b{k}\b", v, text)
    return text


def _beach_claims(h):
    g = next((f for f in store.facts(h["id"], "beach_walk") if f["source"] == "geo"), None)
    if not g:
        return []
    v, d, out = g["value"], h["description"] or "", []
    straight = (g["evidence"] or {}).get("straight_m")
    sure = g["confidence"] >= SURE
    m = CLAIM_MIN.search(d)
    if m:
        c, comp = int(m.group(1)), v["minutes_there"]
        verdict = OK if comp <= c * 1.25 + 1 else OVER if comp > c * 1.5 + 2 else DISPUTED
        far_straight = straight is None or straight / WALK_M_MIN > c * 1.5 + 2
        ev = f"расчёт маршрута: {comp:.0f} мин до моря, обратно {v['minutes_back']:.0f} мин (подъём {v['climb_back_m']:.0f} м)"
        note = f"{c} мин, вероятно, по прямой, пешком {comp:.0f} мин"
    else:
        m = CLAIM_M.search(d)
        if not m:
            return []
        c, comp = int(m.group(1)), v["distance_m"]
        verdict = OK if comp <= c * 1.25 + 50 else OVER if comp > c * 1.5 + 100 else DISPUTED
        far_straight = straight is None or straight > c * 1.5 + 100
        ev = f"расчёт маршрута: {comp:.0f} м пешком, {v['minutes_there']:.0f} мин, обратно {v['minutes_back']:.0f} мин (подъём {v['climb_back_m']:.0f} м)"
        note = f"{c} м, вероятно, по прямой, пешком {comp:.0f} м"
    evidence = [ev]
    if verdict == OVER and not (sure and far_straight):   # маршрут неуверенный или по прямой заявление честное
        verdict = DISPUTED
        evidence.insert(0, note if not far_straight else "маршрут посчитан неуверенно: расстояние может быть меньше")
    return [{"kind": "описание отеля", "char": "beach_walk", "who": "карточка Островка", "claim": f"«{m.group(0)}»",
             "verdict": verdict, "evidence": evidence, "confidence": g["confidence"]}]


def _building_solid(geo):
    """Расчёт вида опирается на надёжные входы: точка внутри контура здания и этажность взята из карты, не угадана."""
    b = (geo["evidence"] or {}).get("building") or {}
    return (b.get("match") == "точка внутри контура" and str(b.get("levels_source", "")).startswith("тег")
            and (b.get("levels") or 0) > 1)


def _weak_input_reason(geo):
    b = (geo["evidence"] or {}).get("building") or {}
    if b.get("match") != "точка внутри контура":
        return "этажность здания не известна: отель сопоставлен с ближайшим контуром, а не с точным зданием"
    return "этажность здания не известна: на карте один этаж или она не указана, море могут видеть верхние этажи"


def _sea_floor_note(h):
    """Названия категорий «с видом на море» против геометрии: вид есть, но не с первых этажей — уточнение.
    Карточка молчит, а расчёт видит море — скрытая сильная сторона."""
    fs = store.facts(h["id"], "sea_view")
    geo = next((f for f in fs if f["source"] == "geo"), None)
    card = next((f for f in fs if f["source"] == "card" and f["value"].get("has")), None)
    if not geo:
        return None
    v = geo["value"]
    if not card:
        if v.get("has") and geo["confidence"] >= SURE:
            return {"kind": "карточка молчит", "char": "sea_view", "who": "расчёт по геоданным",
                    "claim": "в карточке про вид на море ничего нет", "verdict": HIDDEN,
                    "evidence": [geo["summary"], "это можно написать в описании и в названиях категорий номеров"],
                    "confidence": geo["confidence"]}
        return None
    allhits = card["evidence"].get("hits") or []
    rooms = [x for x in allhits if str(x.get("field", "")).startswith("номер")]
    hits = [f"{x.get('field')}: {x.get('quote')}"[:140] for x in allhits][:3]
    q = str((allhits[0] if allhits else {}).get("quote") or "")
    if q.startswith("…") and " " in q:   # обрезанное слово в начале цитаты убираем
        q = "…" + q[1:].split(" ", 1)[1]
    claim = "«" + (q if len(q) <= 150 else q[:150].rsplit(" ", 1)[0] + "…") + "»" if q else card["summary"]
    names = {str(x.get("field")) for x in rooms}
    if len(names) >= 2:   # категорий несколько: цитируем число, а не первое название
        n = len(names)
        m10, m100 = n % 10, n % 100
        word = "категория" if m10 == 1 and m100 != 11 else "категории" if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else "категорий"
        claim = f"«{n} {word} с видом на море»"
    if not rooms:   # вид упомянут в описании (террасы, общие зоны), а не в категориях номеров
        if v.get("has") and geo["confidence"] >= SURE:   # карточка о море пишет, значит это не «скрытая» сторона
            return {"kind": "описание отеля", "char": "sea_view", "who": "карточка Островка", "claim": claim,
                    "verdict": OK, "evidence": [geo["summary"], "вид на море назван в описании отеля, расчёт его подтверждает "
                                                              "(в названиях категорий номеров его нет)"],
                    "confidence": geo["confidence"]}
        return {"kind": "описание отеля", "char": "sea_view", "who": "карточка Островка", "claim": claim,
                "verdict": DISPUTED, "evidence": [geo["summary"], "вид заявлен в описании, не в категориях номеров: террасы и общие зоны "
                                                  "могут быть выше высоты здания на карте"] + hits[:1], "confidence": geo["confidence"]}
    if not v.get("has"):
        over = geo["confidence"] >= SURE and _building_solid(geo)
        ev = [geo["summary"]] + ([] if over else [_weak_input_reason(geo)]) + ([f"в карточке: {'; '.join(hits)}"] if hits else [])
        return {"kind": "категории номеров", "char": "sea_view", "who": "карточка Островка", "claim": claim,
                "verdict": OVER if over else DISPUTED, "evidence": ev, "confidence": geo["confidence"]}
    if (v.get("from_floor") or 1) > 3:
        return {"kind": "категории номеров", "char": "sea_view", "who": "карточка Островка", "claim": claim,
                "verdict": DISPUTED, "evidence": [geo["summary"], "этаж в названии категории не указан: на нижних этажах моря может не быть"],
                "confidence": geo["confidence"]}
    return {"kind": "категории номеров", "char": "sea_view", "who": "карточка Островка", "claim": claim, "verdict": OK,
            "evidence": [geo["summary"]], "confidence": geo["confidence"]}


def _complaints(others):
    """Сколько жалоб в отзывах стоит за оценкой (цитат с жалобами в факте отзывов)."""
    rv = next((g for g in others if g["source"] == "reviews"), None)
    return len((rv["evidence"] or {}).get("bad") or []) if rv else 0


def _bool_claims(h, skip=()):
    out = []
    for cid, spec in registry.all_chars().items():
        if cid in skip or not truth.is_bool_key(spec):
            continue
        fs = store.facts(h["id"], cid)
        for f in fs:
            claim = (f["value"] or {}).get(spec["key"])
            if f["source"] not in CHECKED_SOURCES or not isinstance(claim, bool) or (f["confidence"] or 0) < 0.4:
                continue
            others = [g for g in fs if g["source"] != f["source"]]
            post = truth.posterior(spec, others) if others else None
            if not post or all(abs(v["llr"]) * v["w"] < 0.3 for v in post["votes"]):
                continue   # независимых свидетельств нет: проверить нечем
            val, conf = truth.decide(post)
            ev = [f"{g['source_label']}: {g['summary']}" for g in others][:3]
            if claim == val and conf >= 0.7:
                verdict = OK
            elif claim == val:
                continue   # независимая оценка согласна, но слабо: ни подтвердить, ни оспорить
            elif claim and cid in MIN_COMPLAINTS and _complaints(others) < MIN_COMPLAINTS[cid]:
                continue
            elif claim != val and conf >= SURE:
                verdict = OVER if claim else DISPUTED
            else:
                verdict = DISPUTED
            if verdict == OVER and cid == "sea_view":   # то же правило надёжных входов, что у категорий номеров
                geo = next((g for g in others if g["source"] == "geo"), None)
                if geo and not _building_solid(geo):
                    verdict = DISPUTED
                    ev.insert(0, _weak_input_reason(geo))
            ev.append(f"независимая оценка без этого источника: {'да' if val else 'нет'}, уверенность {conf:.2f}".replace(".", ","))
            out.append({"kind": "ответ отельера" if f["source"] == "hotelier" else "карточка", "char": cid,
                        "who": f["source_label"], "claim": f"{spec['name']}: {f['summary']}", "verdict": verdict,
                        "evidence": ev, "confidence": conf})
    return out


def audit_hotel(hotel_id):
    h = gd.load().hotel_by_id[hotel_id]
    claims = _beach_claims(h)
    sea = _sea_floor_note(h)
    if sea:
        claims.append(sea)
    claims += _bool_claims(h, skip=("sea_view",) if sea else ())
    count = {v: sum(1 for c in claims if c["verdict"] == v) for v in VERDICTS}
    for c in claims:
        c["confidence"] = min(0.99, c["confidence"]) if c.get("confidence") is not None else c.get("confidence")
        c["claim"] = c["claim"] if c["claim"].startswith("«") else plain(c["claim"])   # цитату карточки не правим
        c["evidence"] = [plain(e) for e in c["evidence"]]
    return {"hotel": {"id": h["id"], "name": h["name"]}, "claims": claims, "counts": count,
            "reputation": truth.hotelier_reputation(hotel_id)}


def audit_all(limit=30):
    """Отели, где больше всего завышенных заявлений, и общие доли вердиктов по всему списку."""
    rows, total = [], {v: 0 for v in VERDICTS}
    for h in gd.load().hotels:
        a = audit_hotel(h["id"])
        for k, v in a["counts"].items():
            total[k] += v
        if a["counts"][OVER] or a["counts"][DISPUTED]:
            rows.append({"hotel": a["hotel"], "counts": a["counts"],
                         "top": next((c for c in a["claims"] if c["verdict"] == OVER), None)
                    or next((c for c in a["claims"] if c["verdict"] == DISPUTED), None)})
    rows.sort(key=lambda r: (-r["counts"][OVER], -r["counts"][DISPUTED]))
    return {"totals": total, "hotels": len(gd.load().hotels), "hotels_with_issues": len(rows), "worst": rows[:limit]}
