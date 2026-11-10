"""Подбор номера: какую категорию брать и что попросить на стойке, чтобы море, закат и тишина достались гостю.

Отель с видом на море не значит номер с видом на море: конкретный номер выбирают при заселении. Геометрия
(`sea_view`: вероятность моря по сторонам здания и этажам, `night_quiet`: шум по сторонам, `sunset`) говорит, где
вид есть. Карточка говорит, что обещает категория. Отзывы гостей, жившие именно в этой категории, говорят, что
получилось. Здесь это сводится в вероятность и в готовую просьбу в бронь. Модель ничего не выдумывает:
каждая цифра в `evidence` с источником, а вероятность названа вероятностью.
"""
import math
import re

from app import geodata as gd
from app import metrics, store
from app.tools import text

QUIET_DB = 55           # как в реестре night_quiet: ниже 55 дБ ночью считаем тихой стороной
QUIET_GAIN_DB = 4       # просим тихую сторону только если она заметно тише самой шумной
SEA_OK = 0.8            # с какой вероятностью считаем «этаж, откуда море точно видно»
HIDDEN_EXPO = 0.25      # и чтобы просьба была реальной: море видит хотя бы четверть комнат категории
HIDDEN_P = 0.8          # порог для «скрытого вида»: море видно из какой-то стороны почти наверняка
GUEST_POS_LR = 3.0      # отзыв гостя именно этой категории про море: шансы ×3
GUEST_NEG_LR = 0.2      # жалоба: шансы ×0,2
GUEST_CAP = 4           # больше четырёх отзывов в одну сторону не накапливаем

SEA_WORDS = r"sea[- ]?front|sea[- ]?view|ocean[- ]?view|с\s+видом\s+на\s+(?:мор(?:е|я)|залив)"
CLAIM_SEA = re.compile(r"вид\w*\s+на\s+мор(?:е|я)\b|морск(?:ой|им|ого)\s+вид\w*|вид\w*\s+на\s+[а-яё\s,]{0,25}?\sи\s+мор(?:е|я)\b|" + SEA_WORDS, re.I)
ROH = re.compile(r"run\s+of\s+(?:the\s+)?house|любо[йе]|без\s+вида|basic|\broh\b", re.I)
OTHER_VIEW = [
    ("город", "город", re.compile(r"вид\w*\s+на\s+(?:город|улиц|центр)", re.I)),
    ("горы", "горы", re.compile(r"вид\w*\s+на\s+гор", re.I)),
    ("двор", "двор", re.compile(r"вид\w*\s+(?:во?\s+)?(?:внутренн\w+\s+)?двор", re.I)),
    ("сад", "сад", re.compile(r"вид\w*\s+на\s+(?:сад|дендрарий)", re.I)),
    ("парк", "парк", re.compile(r"вид\w*\s+на\s+парк", re.I)),
    ("бассейн", "бассейн", re.compile(r"вид\w*\s+на\s+бассейн", re.I)),
    ("терраса", "террасу", re.compile(r"вид\w*\s+на\s+террас", re.I)),
    ("река", "реку", re.compile(r"вид\w*\s+на\s+рек", re.I)),
    ("набережная", "набережную", re.compile(r"вид\w*\s+на\s+набережн", re.I)),
    ("порт", "порт", re.compile(r"вид\w*\s+на\s+(?:морск\w+\s+)?порт", re.I)),
    ("другой", None, re.compile(r"вид\w*\s+на\s+навагинск", re.I)),
]
OTHER_ACC = {k: acc for k, acc, _ in OTHER_VIEW}
TOP = re.compile(r"мансард|пентхаус|лофт|чердак", re.I)
UPPER = re.compile(r"высок\w+\s+этаж|верхн\w+\s+этаж", re.I)
ONE_FLOOR = re.compile(r"на\s+(\d+)(?:-?[мй])?\s+этаже", re.I)
GROUND = re.compile(r"цокольн|первом\s+этаже", re.I)
WINDOWLESS = re.compile(r"без\s+окн|имитаци\w*\s+окн|без\s+окон|окно\s+в\s+коридор|мансард\w*\s+без\s+окн", re.I)
BALCONY = re.compile(r"балкон|террас", re.I)

TO_DIR = {"С": "север", "СВ": "северо-восток", "В": "восток", "ЮВ": "юго-восток", "Ю": "юг", "ЮЗ": "юго-запад",
          "З": "запад", "СЗ": "северо-запад"}


def _logit(p):
    p = min(0.97, max(0.03, p))
    return math.log(p / (1 - p))


def _sigm(x):
    return 1 / (1 + math.exp(-x))


def _geo(hotel_id, char_id):
    return next((f for f in store.facts(hotel_id, char_id) if f["source"] == "geo"), None)


def _base(name):
    """Название категории без хвоста в скобках (в отзывах к нему дописана кровать и условия)."""
    return re.split(r"\s+\(", (name or "").strip())[0].strip().lower()


def parse_category(name, amenities=()):
    """Что категория обещает про вид и этаж: по названию и удобствам карточки."""
    claims = bool(CLAIM_SEA.search(name))
    other = None
    if not claims:
        other = next((k for k, _, rx in OTHER_VIEW if rx.search(name)), None)
    return {"claims_sea": claims, "other_view": other, "windowless": bool(WINDOWLESS.search(name)),
            "balcony": bool(BALCONY.search(name) or "balcony" in amenities),
            "top": bool(TOP.search(name)), "upper": bool(UPPER.search(name)), "ground": bool(GROUND.search(name)),
            "floor": int(ONE_FLOOR.search(name).group(1)) if ONE_FLOOR.search(name) else None}


def _floor_range(cat, levels):
    if cat["floor"]:
        f = min(levels, cat["floor"])
        return f, f
    if cat["top"]:
        return max(1, levels - 1), levels
    if cat["upper"]:
        return max(1, math.ceil(levels * 2 / 3)), levels
    if cat["ground"]:
        return 1, 1
    return 1, levels


def _building(hotel_id):
    """Стороны здания: вероятность моря по этажам (sea_view) и шум ночью (night_quiet), по одному словарю на сторону."""
    sv, nq = _geo(hotel_id, "sea_view"), _geo(hotel_id, "night_quiet")
    faces = {}
    levels = 0
    if sv:
        for f in sv["evidence"].get("facades", []):
            p = {int(k): v for k, v in f["p_sea_by_floor"].items()}
            faces[f["dir"]] = {"dir": f["dir"], "az": f["az"], "w": f.get("length_m") or 1, "p": p,
                               "sea_from": f.get("sea_from_floor"), "db": None}
            levels = max(levels, max(p, default=0))
        levels = (sv["value"] or {}).get("levels") or levels
    if nq:
        for f in nq["evidence"].get("facades", []):
            faces.setdefault(f["dir"], {"dir": f["dir"], "az": f["az"], "w": 1, "p": {}, "sea_from": None, "db": None})["db"] = f["night_db"]
    return {"faces": list(faces.values()), "levels": max(levels, 1), "sea_fact": sv, "quiet_fact": nq,
            "loud_db": max((f["db"] for f in faces.values() if f["db"] is not None), default=None)}


def _p(face, floor):
    return face["p"].get(floor, face["p"].get(max(face["p"]), 0.0) if face["p"] else 0.0)


def _exposure(faces, lo, hi):
    """Вероятность моря у случайного номера категории: среднее по сторонам (с весом по длине) и этажам диапазона."""
    ws = [(f["w"], sum(_p(f, fl) for fl in range(lo, hi + 1)) / (hi - lo + 1)) for f in faces if f["p"]]
    tw = sum(w for w, _ in ws)
    return sum(w * v for w, v in ws) / tw if tw else 0.0


def _potential(faces, lo, hi):
    """Лучший случай: вероятность моря на самой удачной стороне в диапазоне этажей."""
    return max((_p(f, fl) for f in faces if f["p"] for fl in range(lo, hi + 1)), default=0.0)


def _guests(hotel_id):
    """Отзывы по базовому названию категории: сколько хвалят вид на море, сколько жалуются."""
    h = gd.load().hotel_by_id[hotel_id]
    by = {}
    for r in h["reviews"]:
        if not r.get("room"):
            continue
        plus, minus = r.get("plus") or "", r.get("minus") or ""
        pos = re.search("|".join(metrics.SEA_POS), plus, re.I) and not re.search("|".join(metrics.SEA_NEG), plus, re.I)
        neg = re.search("|".join(metrics.SEA_NEG), plus + " " + minus, re.I)
        d = by.setdefault(_base(r["room"]), {"n": 0, "pos": [], "neg": []})
        d["n"] += 1
        if neg:
            d["neg"].append(r)
        elif pos:
            d["pos"].append(r)
    return by


def _ordinal_floor(n):
    return f"{n}-го этажа"


def from_floor(n):
    """«с 6-го этажа», но «со 2-го этажа»."""
    return f"{'со' if n == 2 else 'с'} {n}-го этажа"


def _floor_phrase(floor, levels):
    """«с 5-го этажа» («со 2-го»), а на верхнем этаже здания: «на последнем (9-м) этаже»."""
    if not floor or floor <= 1:
        return ""
    if levels and floor >= levels:
        return f"на последнем ({levels}-м) этаже"
    return from_floor(floor)


SHOW_MAX = 0.99   # наружу не отдаём 100%: расчёт вероятностный, «точно» мы не знаем


def _shown(x, nd=2):
    """Вероятность для показа: не выше 0,99."""
    return round(min(SHOW_MAX, float(x)), nd)


def _pct(x):
    return f"{round(min(SHOW_MAX, x) * 100)}%"


def _pick_side(b, lo, hi, wants, month, sunset):
    """Лучшая сторона и этаж «не ниже» под пожелания гостя. Возвращает словарь или None.

    Сторона считается «с морем» в зачёте только при вероятности не ниже SEA_OK: тишина не должна молча менять
    надёжное море на 50 на 50. Слабое море (от 0,5) берём, только если сильного нет ни на одной стороне."""
    def run(thr):
        best = None
        for f in b["faces"]:
            sea_floor = next((fl for fl in range(lo, hi + 1) if f["p"] and _p(f, fl) >= thr), None)
            quiet = f["db"] is not None and f["db"] < QUIET_DB
            sun = sunset is not None and f["dir"] == sunset["facade"] and sunset["from_floor"] <= hi
            floor = max([x for x in (sea_floor if "sea" in wants else None, sunset["from_floor"] if sun and "sunset" in wants else None, lo) if x])
            score = ("sea" in wants and sea_floor is not None, "quiet" in wants and quiet, "sunset" in wants and sun)
            key = (-sum(score), -(sea_floor is not None), -quiet, floor, -round(_p(f, floor), 2), f["db"] if f["db"] is not None else 99)
            if best is None or key < best["key"]:
                best = {"key": key, "face": f, "sea_floor": sea_floor, "quiet": quiet, "sun": sun, "floor": floor}
        return best
    best = run(SEA_OK)
    if best is not None and best["sea_floor"] is None and "sea" in wants:
        weak = run(0.5)
        if weak is not None and weak["sea_floor"] is not None:
            best = weak
    return best


def _sunset_for(hotel_id, month):
    f = _geo(hotel_id, "sunset")
    if not f:
        return None
    months = f["evidence"].get("months", {})
    if month and str(month) in months and months[str(month)].get("from_floor"):
        m = months[str(month)]
        return {"facade": m["facade"], "from_floor": m["from_floor"], "month": month}
    return None


def _request_floor(floor, levels):
    """Этаж в тексте просьбы для брони: «не на первом этаже», «не ниже 5-го этажа», на верхнем: «на последнем (9-м) этаже»."""
    if levels and floor >= levels:
        return _floor_phrase(floor, levels)
    return "не на первом этаже" if floor == 2 else f"не ниже {floor}-го этажа"


def _request(side, floor, why, levels=None):
    """Короткая вежливая просьба для поля «пожелания» в брони."""
    if not side or not why:
        return ""
    fl = f", {_request_floor(floor, levels)}" if floor and floor > 1 else ""
    reason = why[0] if len(why) == 1 else ", ".join(why[:-1]) + " и " + why[-1]
    return f"Здравствуйте. Если получится, поселите нас, пожалуйста, в номер с окнами на {TO_DIR.get(side, side)}{fl}, чтобы {reason}. Спасибо."


def resolve_rooms(hotel_id, wants=None, month=None):
    """По одной записи на категорию номера из карточки: вид на море, что попросить, скрытый вид, доказательства.

    wants: ["sea", "quiet", "sunset"], по умолчанию ["sea"]; month нужен только для заката.
    """
    wants = list(wants or ["sea"])
    h = gd.load().hotel_by_id[hotel_id]
    b = _building(hotel_id)
    L, faces = b["levels"], b["faces"]
    guests = _guests(hotel_id)
    sunset = _sunset_for(hotel_id, month) if "sunset" in wants else None
    sv_val = (b["sea_fact"] or {}).get("value") or {}
    cats = {}
    for r in h["rooms"]:
        c = cats.setdefault(r["name"], {"name": r["name"], "amenities": set(), "size": []})
        c["amenities"] |= set(r["amenities"])
        if r.get("size_m2"):
            c["size"].append(r["size_m2"])
    # отель молчит про море: ни в одной категории, ни в удобствах, ни в описании (как в metrics: geo_yes_not_advertised)
    silent = not text.card_search(hotel_id, ["вид(ом)? на море", "морск(ой|им) вид", "sea[- ]?front", "sea[- ]?view", "ocean[- ]?view", "с видом на (?:море|залив)"])["found"]
    out = []
    for name, c in cats.items():
        cat = parse_category(name, c["amenities"])
        lo, hi = _floor_range(cat, L)
        expo, pot = _exposure(faces, lo, hi), _potential(faces, lo, hi)
        ev = []
        if cat["claims_sea"]:
            p0 = 0.15 + 0.85 * pot
            ev.append("Карточка Островка: в названии категории заявлен вид на море")
        elif cat["other_view"]:
            p0 = 0.3 * expo
            acc = OTHER_ACC.get(cat["other_view"])
            ev.append(f"Карточка Островка: в названии указан вид на {acc}, море не обещано" if acc
                      else "Карточка Островка: вид из названия категории, море не обещано")
        else:
            p0 = expo
            ev.append("Карточка Островка: вид из категории не указан, сторону выбирают при заселении")
        if cat["top"] or cat["upper"]:
            ev.append(f"Категория на верхних этажах ({lo}-{hi}-й из {L})")
        g = guests.get(_base(name), {"n": 0, "pos": [], "neg": []})
        pos, neg = g["pos"], g["neg"]
        lg = _logit(p0) + min(len(pos), GUEST_CAP) * math.log(GUEST_POS_LR) + min(len(neg), GUEST_CAP) * math.log(GUEST_NEG_LR)
        p = 0.0 if cat["windowless"] else round(min(SHOW_MAX, max(0.01, _sigm(lg))), 2)
        if cat["windowless"]:
            ev.insert(1, "В номере нет настоящего окна: море из него не видно, сторону и этаж просить незачем")
        if pos or neg:
            q = (pos or neg)[0]
            quote = ((q.get("plus") if pos else q.get("minus")) or "").strip().replace("\n", " ")
            m = re.search("|".join(metrics.SEA_POS if pos else metrics.SEA_NEG), quote, re.I)
            if m:
                a = max(0, m.start() - 50)
                quote = ("…" if a else "") + quote[a:m.end() + 50]
            ev.append(f"Гости, жившие в этой категории: хвалят вид на море {len(pos)}, жалуются {len(neg)} "
                      f"(всего отзывов {g['n']}); {q['date']}: «{quote[:140]}»")
        else:
            ev.append(f"Гости, жившие в этой категории: про море не писали (всего отзывов {g['n']})")
        if cat["claims_sea"] and pot < 0.5 and not pos:
            ev.append("Карточка и расчёт расходятся: вид заявлен, а геометрия его не подтверждает. Стоит уточнить у отеля")

        ask, sea_face = {"side": None, "min_floor": None, "levels": L}, None
        pick = (_pick_side(b, lo, hi, wants if not cat["other_view"] else [w for w in wants if w != "sea"], month, sunset)
                if faces and not cat["windowless"] else None)
        if pick and pick["sea_floor"] is not None and not cat["other_view"]:
            sea_face = pick["face"]
            ask = {"side": sea_face["dir"], "min_floor": pick["floor"], "levels": L, "p": _shown(_p(sea_face, pick["floor"]))}
        sea_dir = (sea_face or {}).get("dir") or max((f for f in faces if f["p"]), key=lambda f: _p(f, hi), default={}).get("dir")
        from_fl = ask["min_floor"] or next((f["sea_from"] for f in faces if f["sea_from"]), None)
        fl_clause = f" {from_floor(from_fl)}" if from_fl else ""
        if not cat["windowless"]:
            ev.insert(1 + (cat["top"] or cat["upper"]), (
                "Расчёт по геоданным: для отеля нет данных о виде на море" if not b["sea_fact"] else
                f"Расчёт по геоданным: моря не видно ни с одной стороны (здание {L} эт.)" if pot < 0.1 else
                f"Расчёт по геоданным: море видно из окон на {TO_DIR.get(sea_dir, sea_dir)}{fl_clause}; у номера на случайной "
                f"стороне {_pct(expo)}, на лучшей стороне {_pct(pot)} (здание {L} эт.)"))
        hidden = (not cat["windowless"] and not cat["claims_sea"] and not cat["other_view"] and silent and pot >= HIDDEN_P and expo >= HIDDEN_EXPO and sea_face is not None)
        side_ru = TO_DIR.get(ask["side"], ask["side"])
        fl_ru = f" {from_floor(ask['min_floor'])}" if ask["min_floor"] else ""
        if sea_face and not hidden and not cat["windowless"] and not cat["claims_sea"] and not cat["other_view"] and pot >= HIDDEN_P:
            ev.append(f"Море, возможно, видно из окон на {side_ru}{fl_ru}: категория его не обещает, "
                      f"но отель продаёт другие категории с видом на море, так что сторону стоит попросить")
        if hidden:
            ev.append(f"Скрытый вид: отель нигде не заявляет вид на море, категория море не обещает, но из окон на {side_ru}{fl_ru} "
                      f"оно, вероятно, видно. Окончательно решает отель при заселении")
        if "quiet" in wants and sea_face and not pick["quiet"]:
            qf = next((f for f in faces if f["db"] is not None and f["db"] < QUIET_DB), None)
            ev.append("Стороны с морем и стороны тише 55 дБ ночью не совпадают" + (f": тише в окнах на {TO_DIR.get(qf['dir'], qf['dir'])}" if qf else ""))
        req_side, req_floor, why = ask["side"], ask["min_floor"], []
        if sea_face:
            why.append("из окна было видно море")
        elif pick:  # моря нет или категория обещает другой вид: просим хотя бы тихую сторону
            req_side, req_floor = pick["face"]["dir"], (hi if cat["top"] else None)
        f = (sea_face or (pick or {}).get("face"))
        if f and f["db"] is not None and b["loud_db"] is not None and f["db"] < QUIET_DB and b["loud_db"] - f["db"] >= QUIET_GAIN_DB:
            why.append("ночью было тихо")
        elif not sea_face:
            req_side = None
        if cat["windowless"]:
            req_side = None
        if sea_face and pick["sun"] and "sunset" in wants:
            why.insert(1, "был виден закат")
        special = _request(req_side, req_floor, why, L)
        claim_note = None
        if cat["claims_sea"] and sea_face and expo < 0.5 and not cat["windowless"]:
            fp = _floor_phrase(ask["min_floor"], L)
            claim_note = (f"Категорию продают как «с видом на море», по расчёту море видно только из окон на "
                          f"{TO_DIR.get(sea_face['dir'], sea_face['dir'])}{', ' + fp if fp else ''}. Попросите это при бронировании.")
        out.append({"room": name, "claims_sea_view": cat["claims_sea"], "sea_view_p": p, "random_p": _shown(expo), "best_side_p": _shown(pot), "windowless": cat["windowless"], "ask": ask,
                    "special_request": special, "claim_note": claim_note, "hidden_view": hidden, "evidence": ev,
                    "other_view": cat["other_view"], "balcony": cat["balcony"],
                    "size_m2": min(c["size"]) if c["size"] else None, "floors": [lo, hi],
                    "guests": {"stayed": g["n"], "praise_sea": len(pos), "deny_sea": len(neg)}})
    return out


def _rank(rooms, wants):
    if "sea" in wants:
        # скрытую априорную оценку (sea_view_p) в выбор лучшей не берём: сначала то, что даёт геометрия
        return sorted(rooms, key=lambda r: (-r["random_p"], -(r["ask"].get("p") or 0), not r["claims_sea_view"], not r["balcony"],
                                            -r["guests"]["praise_sea"], -(r["size_m2"] or 0), r["room"]))
    return sorted(rooms, key=lambda r: (not r["special_request"], r["room"]))


def advice(hotel_id, wants=None, month=None):
    """Какую категорию брать и что написать в просьбе: лучшая категория, запасные и скрытые виды отеля."""
    wants = [w for w in (wants or ["sea"]) if w in ("sea", "quiet", "sunset")] or ["sea"]
    rooms = resolve_rooms(hotel_id, wants, month)
    ranked = _rank(rooms, wants)
    b = _building(hotel_id)
    # номер «любой» из пула не несёт просьбу: в лучшие не берём, в запасные оставляем
    named = [r for r in ranked if not ROH.search(r["room"]) and not r["windowless"]]
    best = (named or [r for r in ranked if not r["windowless"]] or [None])[0]
    alts = [r for r in ranked if r is not best][:2]
    # лучшие категории с одинаковыми шансами: одну не называем, говорим «любая из N»
    tied = [r for r in named if best and (r["random_p"], r["ask"].get("p")) == (best["random_p"], best["ask"].get("p"))] if best else []
    tie = {"n": len(tied), "claims_n": sum(1 for r in tied if r["claims_sea_view"])} if len(tied) > 1 else None
    real = [r for r in rooms if not r["windowless"]]
    sea_possible = any(r["sea_view_p"] >= 0.5 or r["ask"]["side"] for r in rooms)
    note = None
    if not rooms:
        note = "В карточке нет категорий номеров."
    elif "sea" in wants and not sea_possible:
        praised = any(r["guests"]["praise_sea"] for r in rooms)
        note = ("По расчёту моря не видно ни из одной категории: просить на стойке нечего, кроме тихой стороны." if praised else
                "По расчёту и отзывам моря не видно ни из одной категории: просить на стойке нечего, кроме тихой стороны.")
    return {"hotel": hotel_id, "wants": wants, "month": month, "best": best, "alternatives": alts,
            "hidden_view": [r["room"] for r in rooms if r["hidden_view"]],
            "sides": [{"side": f["dir"], "sea_from_floor": f["sea_from"], "night_db": f["db"]} for f in b["faces"]],
            "levels": b["levels"], "rooms": ranked, "note": note,
            "same_p": len({r["random_p"] for r in real}) == 1 and len(real) > 1,
            "same_p_value": real[0]["random_p"] if real else None, "tie": tie,
            "honesty": "Конкретный номер отель назначает при заселении, поэтому мы показываем шанс увидеть море."}
