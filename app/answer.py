"""Ответ с развилками: один отель и, только когда есть настоящий компромисс, 1–3 «если важнее …».

Развилку не показываем всем подряд. Она нужна, когда среди подходящих отелей нет одного лучшего по всему,
что важно этому гостю. Поэтому:
- оси сравнения берём из запроса: цена (если гость не сказал, что она не важна), оценка гостей и то, о чём он
  спросил сам (море, тишина, вид, закат…);
- разница считается, только если она заметна человеку: 3 минуты до моря, 4 дБ ночью, 15% цены;
- если гость назвал главное («главное тишина», или выбрал в «Что важнее?»), победитель лучший по главному,
  и развилки, которые жертвуют главным, не показываем;
- если один отель не хуже остальных ни по одной оси, развилок нет: это и есть ответ, дальше просто список.
"""
import re

from app import registry, store

# ось: что меряем, что лучше, заметная разница, как сказать
DIMS = {
    "price": {"better": "lo", "title": "Если важнее цена", "best": "дешевле всех", "noun": "цену"},
    "beach": {"char": "beach_walk", "field": "minutes_there", "better": "lo", "material": 3,
              "title": "Если важнее море рядом", "best": "ближе всех к морю", "noun": "дорогу до моря"},
    "quiet": {"char": "night_quiet", "field": "night_db_quiet", "better": "lo", "material": 4,
              "title": "Если важнее тишина", "best": "тише всех ночью", "noun": "шум ночью"},
    "sea": {"char": "sea_view", "field": "from_floor", "better": "lo", "material": 2,
            "title": "Если важнее вид на море", "best": "море видно с самого низкого этажа", "noun": "вид на море"},
    "sunset": {"char": "sunset", "field": "from_floor", "better": "lo", "material": 2,
               "title": "Если важнее закат из окна", "best": "закат видно с самого низкого этажа", "noun": "закат из окна"},
    "kids": {"char": "kids", "field": "playground_m", "better": "lo", "material": 150,
             "title": "Если важнее площадка для детей", "best": "ближе всех к детской площадке", "noun": "детскую площадку"},
    "food": {"char": "food_near", "field": "count", "better": "hi", "material": 10,
             "title": "Если важнее, где поесть", "best": "больше всех кафе рядом", "noun": "кафе рядом"},
    "rating": {"better": "hi", "material": 0.4, "title": "Если важнее отзывы гостей", "best": "лучше всех оценки гостей", "noun": "оценки гостей"},
}
# характеристика из запроса → ось, по которой у неё есть «насколько хорошо»
CHAR_DIM = {"beach_walk": "beach", "night_quiet": "quiet", "sea_view": "sea", "sea_view_quiet": "sea",
            "sunset": "sunset", "sunset_quiet": "sunset", "kids": "kids", "food_near": "food"}
ORDER = ["price", "beach", "quiet", "sea", "sunset", "kids", "food", "rating"]

PRIORITY_RX = re.compile(r"(?:самое главное|главное|важнее всего|самое важное|в первую очередь|прежде всего|"
                         r"в приоритете|приоритет)\W+([^,.;!?]+)", re.I)
PRICE_FREE_RX = re.compile(r"цен\w* не важн|не важн\w* цен|не важно,? сколько стоит|бюджет не (?:важ|огранич)|"
                           r"любой цен|деньги не (?:важн|проблем)|не экономл|без ограничени\w* по (?:цене|бюджету)|"
                           r"за любые деньги|не постоим", re.I)
DIM_WORDS = [("sunset", r"закат"), ("sea", r"вид\w* на мор|вид\w* из окна|вид\b"), ("quiet", r"тих|тиш|шум|выспат|сон"),
             ("beach", r"мор|пляж|перв\w* лини"), ("price", r"дешев|недорог|цен|бюджет|эконом"),
             ("rating", r"отзыв|рейтинг|оценк"), ("kids", r"дет|ребен|ребён"), ("food", r"поесть|кафе|ресторан|еда")]


def _dims_in(phrase):
    out = []
    for d, rx in DIM_WORDS:
        if re.search(rx, phrase, re.I) and d not in out:
            if d == "beach" and "sea" in out:  # «вид на море» — про вид, не про дорогу до пляжа
                continue
            out.append(d)
    return out


def intent(text, parsed, priorities=None):
    """Что важно гостю: оси сравнения, главное по порядку, важна ли цена."""
    text = text or ""
    price_free = bool(PRICE_FREE_RX.search(text))
    prio = []
    for m in PRIORITY_RX.finditer(text):
        prio += [d for d in _dims_in(m.group(1)) if d not in prio]
    for c in priorities or []:  # выбор в «Что важнее?» идёт после сказанного словами
        d = CHAR_DIM.get(c)
        if d and d not in prio:
            prio.append(d)
    if price_free:
        prio = [d for d in prio if d != "price"]
    dims = set(prio)
    for c in (parsed or {}).get("constraints") or []:
        if CHAR_DIM.get(c.get("char")):
            dims.add(CHAR_DIM[c["char"]])
    if not price_free:
        dims.add("price")
    dims.add("rating")
    asked = set(prio) | {CHAR_DIM[c["char"]] for c in (parsed or {}).get("constraints") or [] if CHAR_DIM.get(c.get("char"))}
    if not price_free:
        asked.add("price")  # о цене думают все, кто не сказал обратного
    if re.search(r"отзыв|рейтинг|оценк", text, re.I):
        asked.add("rating")
    return {"dims": [d for d in ORDER if d in dims], "priorities": prio, "price_matters": not price_free,
            "fork_dims": [d for d in ORDER if d in asked]}


def _num(hid, d, month, brief):
    spec = DIMS[d]
    if d == "price":
        return brief.get("price_nov1") or None
    if d == "rating":
        return brief.get("rating") or None
    char = registry.get(spec["char"])
    if char is None:
        return None
    r = store.resolve(hid, char)
    if r["status"] == "unknown":
        return None
    v = r.get("value") or {}
    if isinstance(v, dict) and "by_month" in v:  # закат зависит от месяца поездки
        v = (v.get("by_month") or {}).get(str(month or 7)) or {}
    x = v.get(spec["field"]) if isinstance(v, dict) else None
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _material(d, a, b):
    """Заметна ли человеку разница между a и b по оси d."""
    if a is None or b is None:
        return False
    if d == "price":
        return abs(a - b) >= max(1500, 0.15 * min(a, b))
    return abs(a - b) >= DIMS[d]["material"]


def _better(d, a, b):
    """a заметно лучше b по оси d."""
    if not _material(d, a, b):
        return False
    return a < b if DIMS[d]["better"] == "lo" else a > b


def _money(n):
    return f"{round(n):,}".replace(",", " ") + " ₽"


def _say(d, v):
    return {"price": lambda: f"{_money(v)} за ночь", "beach": lambda: f"{max(1, v):.0f} мин до моря",
            "quiet": lambda: f"ночью {v:.0f} дБ", "sea": lambda: f"море видно с {v:.0f}-го этажа",
            "sunset": lambda: f"закат видно с {v:.0f}-го этажа", "kids": lambda: f"площадка в {v:.0f} м",
            "food": lambda: f"{v:.0f} мест поесть рядом", "rating": lambda: f"оценка {v:.1f}"}[d]()


def _gain(d, a, b):
    """Чем a лучше b, коротко: «дешевле на 3 000 ₽»."""
    x = abs(a - b)
    return {"price": lambda: f"дешевле на {_money(x)}", "beach": lambda: f"ближе к морю на {x:.0f} мин",
            "quiet": lambda: f"тише ночью на {x:.0f} дБ", "sea": lambda: f"море видно на {x:.0f} эт. ниже",
            "sunset": lambda: f"закат видно на {x:.0f} эт. ниже", "kids": lambda: f"площадка ближе на {x:.0f} м",
            "food": lambda: f"мест поесть больше на {x:.0f}", "rating": lambda: f"оценка выше на {x:.1f}"}[d]()


def _loss(d, a, b):
    """Чем a хуже b: «дороже на 3 000 ₽», «12 мин до моря вместо 7»."""
    return {"price": lambda: f"дороже на {_money(abs(a - b))}", "beach": lambda: f"до моря {max(1, a):.0f} мин вместо {max(1, b):.0f}",
            "quiet": lambda: f"ночью {a:.0f} дБ вместо {b:.0f}", "sea": lambda: f"море с {a:.0f}-го этажа вместо {b:.0f}-го",
            "sunset": lambda: f"закат с {a:.0f}-го этажа вместо {b:.0f}-го", "kids": lambda: f"площадка в {a:.0f} м вместо {b:.0f}",
            "food": lambda: f"мест поесть {a:.0f} вместо {b:.0f}", "rating": lambda: f"оценка {a:.1f} вместо {b:.1f}"}[d]()


def build(hotels, parsed, text="", priorities=None, month=None):
    """hotels — подходящие отели в порядке выдачи (краткие карточки из поиска)."""
    it = intent(text, parsed, priorities)
    base = {"show": False, **it}
    if len(hotels) < 2:
        return {**base, "reason": "single"}
    dims, prio = it["dims"], it["priorities"]
    pts = [{"h": h, "v": {d: _num(h["id"], d, month, h) for d in dims}} for h in hotels[:80]]

    def better_on(a, b, d):
        return _better(d, a["v"][d], b["v"][d])

    def dominates(a, b):  # a заметно лучше хотя бы в одном, не хуже ни в чём и известен везде, где известен b
        return (all(a["v"][d] is not None for d in dims if b["v"][d] is not None)
                and any(better_on(a, b, d) for d in dims) and not any(better_on(b, a, d) for d in dims))

    # победитель: при названном главном — лучший по главному (с допуском), дальше порядок выдачи
    cand = pts
    for p in prio:
        known = [x for x in cand if x["v"].get(p) is not None]
        if not known:
            continue
        best = (min if DIMS[p]["better"] == "lo" else max)(x["v"][p] for x in known)
        cand = [x for x in known if not _material(p, x["v"][p], best)]
    win = max(cand, key=lambda x: (sum(v is not None for v in x["v"].values()), -pts.index(x)))  # при равных — про кого знаем больше
    for _ in range(5):  # если кто-то лучше победителя без единой потери, он и есть ответ
        dom = next((x for x in pts if x is not win and dominates(x, win)
                    and not any(_better(p, win["v"].get(p), x["v"].get(p)) for p in prio)), None)
        if not dom:
            break
        win = dom

    top = prio[0] if prio else None
    forks, used = [], {win["h"]["id"]}
    fork_dims = it["fork_dims"]
    for d in [x for x in prio if x in fork_dims] + [x for x in fork_dims if x not in prio]:
        if d == top:
            continue  # по главному победитель и так лучший
        opts = [x for x in pts if x["h"]["id"] not in used and better_on(x, win, d)]
        if top:  # не предлагаем пожертвовать главным
            opts = [x for x in opts if not better_on(win, x, top)]
        scored = []
        for x in opts:
            losses = [e for e in dims if e != d and better_on(win, x, e)]
            blind = [e for e in dims if e != d and win["v"][e] is not None and x["v"][e] is None]
            if not losses and not blind:
                continue  # без потерь это не компромисс (такой отель стал бы победителем)
            scored.append((len(losses) + 0.5 * len(blind), -abs(x["v"][d] - win["v"][d]), pts.index(x), x, losses, blind))
        if not scored:
            continue
        _, _, _, x, losses, blind = min(scored, key=lambda s: s[:3])
        used.add(x["h"]["id"])
        forks.append({"dim": d, "title": DIMS[d]["title"], "hotel": x["h"], "gain": _gain(d, x["v"][d], win["v"][d]),
                      "loss": [_loss(e, x["v"][e], win["v"][e]) for e in losses[:2]]
                              + [f"про {DIMS[e]['noun']} данных нет" for e in blind[:max(0, 2 - len(losses))]]})
        if len(forks) == 3:
            break

    strengths = []
    for d in dims:
        vals = [x["v"][d] for x in pts if x["v"][d] is not None]
        w = win["v"][d]
        if w is None or len(vals) < 2:
            continue
        best = (min if DIMS[d]["better"] == "lo" else max)(vals)
        if not _material(d, w, best) and any(_material(d, w, v) for v in vals):
            strengths.append(DIMS[d]["best"])
    out = {**base, "winner": {**win["h"], "strengths": strengths[:3],
                              "facts": [_say(d, win["v"][d]) for d in dims if win["v"][d] is not None][:4]},
           "forks": forks, "considered": len(pts)}
    if forks:
        return {**out, "show": True, "reason": "tradeoff"}
    return {**out, "reason": "dominant" if strengths else "no_difference"}
