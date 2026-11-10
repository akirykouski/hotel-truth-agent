"""Авто-оценка новой характеристики: отчёт, который админ читает перед тем, как одобрить черновик.

Всё считается кодом по уже посчитанным фактам: покрытие, распределение главного поля и его энтропия,
подозрительная однородность, согласие с независимым сигналом (слова характеристики в карточке и отзывах,
если рецепт эти источники не использует), пять примеров с доказательствами, из чего собран рецепт.
"""
import json
import math
import re
import statistics

from app import geodata as gd
from app import registry, store
from app.tools import text as text_tools

DEGENERATE_SHARE = 0.9  # один вариант значения у стольких известных отелей и больше: признак не различает отели
MIN_COVERAGE = 0.2


def _key_value(spec, r):
    v = r.get("value")
    return v.get(spec.get("key")) if isinstance(v, dict) else None


def _truth(spec, r):
    """Булево значение главного поля: само, либо через условие по умолчанию для числового."""
    from app import search
    v = _key_value(spec, r)
    if isinstance(v, bool):
        return v
    c = spec.get("default_constraint") or {}
    if isinstance(v, (int, float)) and c.get("field") == spec.get("key") and c.get("op") in search.OPS:
        return bool(search.OPS[c["op"]](v, c["value"]))
    return None


def _pl(n, one, few, many):
    """1 отель / 2 отеля / 5 отелей."""
    m, k = n % 100, n % 10
    return f"{n} {many if 10 < m < 15 else one if k == 1 else few if 1 < k < 5 else many}"


def _entropy(counts):
    n = sum(counts)
    if n == 0 or len(counts) < 2:
        return 0.0
    h = -sum(c / n * math.log2(c / n) for c in counts if c)
    return round(h / math.log2(len(counts)), 2) + 0.0


def _distribution(spec, values):
    """Распределение главного поля среди известных отелей + энтропия 0..1 (1: значения поровну)."""
    if not values:
        return {"kind": "none", "n": 0, "entropy": 0.0}
    if all(isinstance(v, bool) for v in values):
        t = sum(values)
        return {"kind": "bool", "n": len(values), "true": t, "false": len(values) - t,
                "entropy": _entropy([t, len(values) - t]), "top_share": round(max(t, len(values) - t) / len(values), 3)}
    nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(nums) == len(values):
        lo, hi = min(nums), max(nums)
        bins = [0] * 6
        for v in nums:
            bins[min(5, int((v - lo) / (hi - lo) * 6)) if hi > lo else 0] += 1
        return {"kind": "number", "n": len(nums), "min": lo, "median": statistics.median(nums), "max": hi,
                "entropy": _entropy([b for b in bins if b] if hi > lo else [len(nums)]),
                "top_share": round(max(bins) / len(nums), 3) if hi > lo else 1.0}
    cnt = {}
    for v in values:
        cnt[str(v)] = cnt.get(str(v), 0) + 1
    return {"kind": "enum", "n": len(values), "counts": cnt, "entropy": _entropy(list(cnt.values())),
            "top_share": round(max(cnt.values()) / len(values), 3)}


def _degenerate(dist, cov):
    total = cov["total"]
    if dist.get("kind") == "bool" and dist["false"] == 0 and cov["unknown"] >= 0.2 * total and dist["n"] >= 1:
        return {"flag": False, "reason": "", "note": f"«нет» рецепт не выставляет никому: у {_pl(cov['unknown'], 'отеля', 'отелей', 'отелей')} просто нет данных "
                                                    "(отсутствие в карточке не доказывает отсутствие признака)"}
    if cov["known"] + cov["conflict"] + cov["stale"] < MIN_COVERAGE * total:
        return {"flag": True, "reason": f"данных нет у {cov['unknown']} из {_pl(total, 'отеля', 'отелей', 'отелей')}: по такой характеристике почти нечего искать"}
    if dist.get("top_share", 0) >= DEGENERATE_SHARE and dist["n"] >= 20:
        if dist["kind"] == "bool":
            top, top_n = ("да", dist["true"]) if dist["true"] >= dist["false"] else ("нет", dist["false"])
            return {"flag": True, "reason": f"{top_n} из {_pl(dist['n'], 'известного отеля', 'известных отелей', 'известных отелей')} получили «{top}»: признак почти не различает "
                                            "отели, скорее всего рецепт ловит слишком общее или ищет не там"}
        return {"flag": True, "reason": f"{round(dist['top_share'] * 100)}% отелей дали одно и то же значение: признак почти не различает отели"}
    return {"flag": False, "reason": ""}


def _presence_only(spec):
    """Рецепт умеет выставить главному полю только одно константное значение (обычно «да»): «нет» ему недоступно,
    остаётся «да» или «нет данных». Тогда однородное распределение не говорит о качестве рецепта."""
    key = spec.get("key")
    vals = [m["value"].get(key) for m in spec["methods"] if isinstance(m.get("value"), dict) and key in m["value"]]
    return bool(vals) and all(isinstance(v, bool) or str(v).strip() in ("True", "False") for v in vals)


def _signal(spec, truth):
    """Согласие с независимым сигналом: слова характеристики в источниках, которые рецепт не использует."""
    used = {m["source"] for m in spec["methods"]}
    terms = [re.escape(k) for k in spec.get("keywords", []) if len(k) >= 3]
    free = [s for s in ("card", "reviews") if s not in used]
    if not terms:
        return {"available": False, "note": "у характеристики нет ключевых слов, искать независимо нечем"}
    if not free:
        return {"available": False, "note": "рецепт уже использует карточку и отзывы, независимого сигнала нет"}
    pairs = []
    for hid, t in truth.items():
        if t is None:
            continue
        hit = False
        if "card" in free:
            hit = hit or text_tools.card_search(hid, terms)["found"]
        if "reviews" in free:
            rs = text_tools.reviews_search(hid, terms)
            hit = hit or rs["positive"] > 0
        pairs.append((t, hit))
    if not pairs:
        return {"available": False, "note": "нет известных значений для сравнения"}
    t_n = sum(1 for t, _ in pairs if t)
    h_n = sum(1 for _, h in pairs if h)
    both = sum(1 for t, h in pairs if t and h)
    return {"available": True, "via": free, "terms": [k for k in spec.get("keywords", []) if len(k) >= 3][:6], "n": len(pairs),
            "computed_true": t_n, "signal_hits": h_n, "both": both,
            "of_true_with_signal": round(both / t_n, 2) if t_n else None,
            "of_signal_with_true": round(both / h_n, 2) if h_n else None,
            "note": "Отсутствие слов в карточке не доказывает отсутствие признака, поэтому главное число: доля совпадений по словам, "
                    "которые подтвердил расчёт."}


def _short_evidence(fact):
    ev = {k: v for k, v in (fact.get("evidence") or {}).items() if k != "calls"}
    s = json.dumps(ev, ensure_ascii=False, default=str)
    return s if len(s) <= 320 else s[:317] + "…"


def _samples(spec, rows, n=5):
    """Пять отелей: поровну «да» и «нет», затем без данных или спорные. Порядок по id, чтобы отчёт не плавал."""
    buckets = {"yes": [], "no": [], "other": []}
    for hid, r, t in rows:
        buckets["other" if r["status"] in ("unknown", "conflict") else "yes" if t is not False else "no"].append((hid, r, t))
    for b in buckets.values():
        b.sort(key=lambda x: -(x[1].get("confidence") or 0))  # сначала самые уверенные: пример должен убеждать, а не случайно попасть в отчёт
    pick = buckets["yes"][:2] + buckets["no"][:2] + buckets["other"][:1]
    for b in ("yes", "no", "other"):
        for x in buckets[b]:
            if len(pick) < n and x not in pick:
                pick.append(x)
    out = []
    for hid, r, t in pick[:n]:
        f = (r.get("facts") or [{}])[0]
        out.append({"hotel_id": hid, "hotel": gd.load().hotel_by_id[hid]["name"], "status": r["status"],
                    "value": _key_value(spec, r), "summary": r.get("summary") or "нет данных", "source": r.get("source_label"),
                    "confidence": r.get("confidence"), "evidence": _short_evidence(f) if f else ""})
    return out


def build(char_id, mode, attempts=1, wall_s=0.0, dry_run=None):
    spec = registry.get(char_id)
    hotels = gd.load().hotels
    rows, st, key_values, truth = [], {"known": 0, "unknown": 0, "conflict": 0, "stale": 0}, [], {}
    for h in sorted(hotels, key=lambda h: h["id"]):
        r = store.resolve(h["id"], spec)
        t = _truth(spec, r)
        rows.append((h["id"], r, t))
        st[r["status"]] += 1
        truth[h["id"]] = t
        v = _key_value(spec, r)
        if r["status"] != "unknown" and v is not None:
            key_values.append(v)
    cov = {**st, "total": len(hotels), "key_true": sum(1 for t in truth.values() if t)}
    dist = _distribution(spec, key_values)
    deg = _degenerate(dist, cov)
    sig = _signal(spec, truth)
    tools = sorted({s["tool"] for m in spec["methods"] for s in m.get("steps", [])})
    warnings = [deg["reason"]] if deg["flag"] else []
    if sig.get("available") and sig["of_signal_with_true"] is not None and sig["of_signal_with_true"] < 0.5 and sig["signal_hits"] >= 5:
        warnings.append(f"слова характеристики есть в источниках у {_pl(sig['signal_hits'], 'отеля', 'отелей', 'отелей')}, расчёт подтвердил только "
                        f"{round(sig['of_signal_with_true'] * 100)}%: рецепт, возможно, пропускает очевидное")
    if dist.get("kind") == "bool" and dist["true"] > 0 and dist["false"] == 0 and _presence_only(spec):
        warnings.append("рецепт умеет только «да» или «нет данных»: «нет» он не выставляет никому, поэтому ровное «да» у всех известных "
                        "отелей ничего не доказывает. Откройте примеры и проверьте глазами, что в каждом найден именно признак")
    if (dry_run is not None) and not dry_run:
        warnings.append("пробный расчёт на 5 отелях не дал ни одного значения")
    verdict = "нужна проверка" if warnings else "можно одобрять"
    return {"verdict": verdict, "warnings": warnings, "coverage": cov, "key": spec.get("key"), "distribution": dist,
            "degenerate": deg, "signal": sig, "samples": _samples(spec, rows),
            "recipe": {"mode": mode, "sources": sorted({m["source"] for m in spec["methods"]}), "tools": tools,
                       "methods": len(spec["methods"]), "attempts": attempts, "wall_s": round(wall_s, 1)}}
