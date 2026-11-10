"""Что ослабить, если подходящих мало.

Работает поверх проверок, которые поиск уже посчитал по каждому отелю (ничего не пересчитывает):
для каждого обязательного условия считаем, сколько отелей добавится, если его убрать или смягчить, и каков
лучший из новых. Плюс небольшой фронтир компромиссов по цене, дороге до пляжа и ночному шуму.
"""
import copy
import re

from app import registry, store

FEW = 10            # ослабления считаем, когда подходящих меньше
MAX_RELAX = 8
MAX_PARETO = 5


def _noun(n):
    return "отель" if n % 10 == 1 and n % 100 != 11 else ("отеля" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "отелей")


def prepare(parsed, drop=None, loosen=None):
    """Копия разбора без убранных условий и со смягчёнными порогами. Условиям проставляется сквозной номер idx:
    он не меняется после удаления, поэтому интерфейс всегда ссылается на условия исходного запроса."""
    parsed = copy.deepcopy(parsed)
    for i, c in enumerate(parsed["constraints"]):
        c.setdefault("idx", i)
    dropped, loosened = [], []
    gone = set()
    for d in drop or []:
        for c in parsed["constraints"]:
            if (isinstance(d, int) and c["idx"] == d) or (isinstance(d, str) and (
                    d == c["char"] or d == f"{c['char']}.{c['field']}" or (d.isdigit() and c["idx"] == int(d)))):
                gone.add(c["idx"])
    for k, v in (loosen or {}).items():
        for c in parsed["constraints"]:
            if str(c["idx"]) == str(k) and isinstance(c.get("value"), (int, float)):
                loosened.append({"idx": c["idx"], "char": c["char"], "field": c["field"], "from": c["value"], "to": v})
                c["value"] = v
                loosened[-1]["label"] = label(c)
    dropped = [c for c in parsed["constraints"] if c["idx"] in gone]
    parsed["constraints"] = [c for c in parsed["constraints"] if c["idx"] not in gone]
    return parsed, [{"idx": c["idx"], "char": c["char"], "field": c["field"], "label": label(c)} for c in dropped], loosened


# Подписи порогов для гостя: (характеристика, поле) -> (о чём речь, единица).
PHRASE = {("beach_walk", "minutes_there"): ("до пляжа", "мин"), ("beach_walk", "climb_back_m"): ("подъём", "м")}


def _n(x):
    """Число с десятичной запятой, без лишнего «.0»."""
    return f"{x:g}".replace(".", ",")


def parts(c, check=None):
    """(о чём условие, единица порога или None). Единицу берём из таблицы или из хвоста подписи поля («…, м»)."""
    if (c["char"], c["field"]) in PHRASE:
        return PHRASE[(c["char"], c["field"])]
    spec = registry.get(c["char"])
    f = ((spec or {}).get("fields") or {}).get(c["field"]) or {}
    lab = (check or {}).get("label") or f.get("label") or (spec or {}).get("name") or c["char"]
    base, _, tail = lab.partition(",")
    return base.strip(), (tail.strip() if _num(c.get("value")) and 0 < len(tail.strip()) <= 4 else None)


def label(c, check=None):
    """Короткая подпись условия для гостя, для чисел вместе с порогом и единицей («подъём ≤ 25 м»)."""
    base, unit = parts(c, check)
    if _num(c.get("value")) and c.get("op") in ("<=", "<", ">=", ">"):
        return f"{base} {'≤' if c['op'] in ('<=', '<') else '≥'} {_n(c['value'])}" + (f" {unit}" if unit else "")
    return base


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _nice(v, up):
    step = 5 if abs(v) >= 10 else 1
    return (int(-(-v // step)) if up else int(v // step)) * step


def _short(t, n=90):
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0].rstrip(",;:(")
    return cut + (")" * (cut.count("(") - cut.count(")"))) + "…"


def _lack(row, idxs):
    """Чего не хватает лучшему из новых отелей: строки из его проверок по ослабляемым условиям."""
    out = []
    for c in row["checks"]:
        if c.get("idx") in idxs and c["status"] != "pass":
            out.append(c.get("why") or (c.get("label") or c["char"]) + ": " + ("данных нет" if c["status"] == "unknown" else "не выполнено"))
    return _short(_clean("; ".join(out)))


def _clean(t):
    """Служебные остатки из пояснений поиска: «(—, не виден)», точка вместо запятой в числах."""
    t = t.replace("(—, не виден)", "(не виден)").replace("—, ", "").replace(" — ", ": ").replace("—", "нет")
    return re.sub(r"(\d)\.(\d)", r"\1,\2", t)


def _brief_item(row):
    h = row["hotel"]
    return {"id": h["id"], "name": h["name"], "price_nov1": h["price_nov1"], "rating": h["rating"]}


def _text(kind, c, chk, gain, best, lack, frm=None, to=None):
    base, unit = parts(c, chk)
    if kind == "drop":
        head = f"если не важно «{label(c, chk)}»"
    else:
        head = f"если смягчить «{base}» с {_n(frm)} до {_n(to)}" + (f" {unit}" if unit else "")
    tail = f", лучший {best['hotel']['name']}" + (f" ({lack})" if lack else "")
    return f"{head}: +{gain} {_noun(gain)}{tail}"


def compute(rows, parsed):
    """rows — строки поиска (с checks, bucket, base_fail). Возвращает список ослаблений по убыванию выгоды."""
    cons = parsed["constraints"]
    by_idx = {c["idx"]: c for c in cons}
    single, loose, pairs = {}, {}, {}
    for r in rows:
        if r["bucket"] == "match" or r["base_fail"]:
            continue
        bad = tuple(c["idx"] for c in r["checks"] if c.get("must", True) and c["status"] in ("fail", "unknown"))
        if not bad or len(bad) > 2:
            continue
        if len(bad) == 1:
            single.setdefault(bad[0], []).append(r)
            c = next(x for x in r["checks"] if x["idx"] == bad[0])
            if c["status"] == "fail" and _num(c.get("actual")) and _num(c.get("value")) and c["op"] in ("<=", "<", ">=", ">"):
                loose.setdefault(bad[0], []).append((c["actual"], r))
        else:
            pairs.setdefault(bad, []).append(r)
    out = []
    for i, rs in single.items():
        best = max(rs, key=lambda r: r["score"])
        chk = next(x for x in best["checks"] if x["idx"] == i)
        lab = label(by_idx[i], chk)
        lack = _lack(best, {i})
        out.append({"kind": "drop", "idxs": [i], "drop": lab, "gain": len(rs), "best": _brief_item(best),
                    "lack": lack, "text": _text("drop", by_idx[i], chk, len(rs), best, lack)})
    for i, vals in loose.items():
        c = by_idx[i]
        up = c["op"] in ("<=", "<")
        vals.sort(key=lambda t: t[0] if up else -t[0])
        near = vals[min(2, len(vals) - 1)][0]
        to = _nice(near, up) if up else -_nice(-near, True)
        cap = c["value"] * 2 if up else c["value"] / 2
        to = min(to, cap) if up else max(to, cap)
        if to == c["value"] or (to < c["value"]) == up:
            continue
        got = [r for a, r in vals if (a <= to if up else a >= to)]
        if not got:
            continue
        best = max(got, key=lambda r: r["score"])
        chk = next(x for x in best["checks"] if x["idx"] == i)
        lab = label(c, chk)
        up_sign = "≤" if up else "≥"
        unit = parts(c, chk)[1]
        out.append({"kind": "loosen", "idxs": [i], "drop": lab, "from": c["value"], "to": to, "gain": len(got),
                    "chip": f"{parts(c, chk)[0]} {up_sign} {_n(to)}" + (f" {unit}" if unit else "") + f" (было {_n(c['value'])})",
                    "best": _brief_item(best), "lack": _lack(best, {i}),
                    "text": _text("loosen", c, chk, len(got), best, _lack(best, {i}), c["value"], to)})
    if not any(x["gain"] > 0 for x in out):
        for idxs, rs in pairs.items():
            best = max(rs, key=lambda r: r["score"])
            labs = " и ".join(label(by_idx[i], next(x for x in best["checks"] if x["idx"] == i)) for i in idxs)
            lack = _lack(best, set(idxs))
            out.append({"kind": "drop", "idxs": list(idxs), "drop": labs, "gain": len(rs), "best": _brief_item(best),
                        "lack": lack, "text": f"если не важно «{labs}»: +{len(rs)} {_noun(len(rs))}, лучший {best['hotel']['name']}"
                                              + (f" ({lack})" if lack else "")})
    out.sort(key=lambda x: (-x["gain"], x["kind"] != "drop", x["idxs"]))
    return out[:MAX_RELAX]


def _val(hid, cid, field, month):
    spec = registry.get(cid)
    if spec is None:
        return None
    r = store.resolve(hid, spec)
    if r["status"] == "unknown":
        return None
    v = (r.get("value") or {})
    if field == "minutes_there":
        from app import search
        return search._field_value(spec, r["value"], field, month)
    return v.get(field)


def pareto(rows, month):
    """Фронтир компромиссов среди подходящих и возможных: цена на 1 ноября, минут до пляжа, ночной шум (дБ).
    Отель в фронтире, если ни один другой не лучше по всем осям, где есть данные у обоих."""
    pool = [r for r in rows if r["bucket"] in ("match", "maybe") and r["hotel"]["price_nov1"]][:60]
    pts = []
    for r in pool:
        hid = r["hotel"]["id"]
        pts.append({"row": r, "price": r["hotel"]["price_nov1"], "minutes": _val(hid, "beach_walk", "minutes_there", month),
                    "db": _val(hid, "night_quiet", "night_db_quiet", month)})
    dims = ("price", "minutes", "db")

    def dominates(a, b):
        common = [d for d in dims if a[d] is not None and b[d] is not None]
        return len(common) >= 2 and all(a[d] <= b[d] for d in common) and any(a[d] < b[d] for d in common)

    front = [p for p in pts if not any(dominates(q, p) for q in pts if q is not p)]
    if len(front) > MAX_PARETO:
        pick = []
        for d in dims:
            cand = [p for p in front if p[d] is not None and p not in pick]
            if cand:
                pick.append(min(cand, key=lambda p: p[d]))
        rest = sorted((p for p in front if p not in pick), key=lambda p: (p["row"]["bucket"] != "match", -p["row"]["score"]))
        front = (pick + rest)[:MAX_PARETO]
    front.sort(key=lambda p: p["price"])
    out = []
    for p in front:
        h = p["row"]["hotel"]
        out.append({"id": h["id"], "name": h["name"], "bucket": p["row"]["bucket"], "price_nov1": p["price"],
                    "minutes": None if p["minutes"] is None else round(p["minutes"]),
                    "db": None if p["db"] is None else round(p["db"]), "lat": h["lat"], "lon": h["lon"]})
    if len(out) > 1:
        cheap = min(out, key=lambda x: x["price_nov1"])
        near = min((x for x in out if x["minutes"] is not None), key=lambda x: x["minutes"], default=None)
        quiet = min((x for x in out if x["db"] is not None), key=lambda x: x["db"], default=None)
        for x, tag in ((cheap, "дешевле всех"), (near, "ближе всех к морю"), (quiet, "тише всех ночью")):
            if x:
                x.setdefault("tags", []).append(tag)
    return out
