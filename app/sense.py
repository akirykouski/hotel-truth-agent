"""Профиль обращения с устройством → политика выдачи.

Профиль считает браузер (app/web/waitgames/sense.js): реакция, точность касаний, жесты, ритм, набор текста,
промахи в интерфейсе. Здесь только правила, как этот профиль меняет выдачу. Правила намеренно простые и
объяснимые: каждое изменение возвращается с причиной, которую видит пользователь. Факты об отелях не трогаем,
меняем только порядок внутри корзины и плотность карточек.
"""
import math
import time

from app import taste, visitors

_SESSIONS: dict[str, dict] = {}
MIN_CONFIDENCE = 0.15


def policy(profile: dict) -> dict:
    seg = profile.get("segment") or "unknown"
    conf = float(profile.get("confidence") or 0)
    dev = profile.get("device") or {}
    if profile.get("optOut") or conf < MIN_CONFIDENCE:
        seg = "unknown"
    reasons, density, limit, rank = [], "normal", None, "default"
    if seg == "careful":
        density, limit, rank = "comfy", 5, "trust"
        reasons += ["Кнопки и текст крупнее: касания в играх ложились неточно или неспешно.",
                    "Сначала отели, о которых много отзывов и высокая оценка: меньше риска, меньше сравнений.",
                    "Показываем до 5 вариантов, чтобы не перегружать."]
    elif seg == "confident":
        density, rank = "dense", "evidence"
        reasons += ["Карточки плотнее: вы быстро и точно управляетесь с устройством.",
                    "Выше отели, где подтверждено больше ваших условий, даже если о них мало отзывов."]
    elif seg == "regular":
        rank = "balanced"
        reasons += ["Порядок с учётом и совпадений, и отзывов."]
    if dev.get("kind") == "телефон" and profile.get("hand"):
        reasons.append(f"Большой палец: {profile['hand']} рука. Главные кнопки держим в зоне досягаемости.")
    if not reasons:
        reasons.append("Пока мало сигналов, выдача стандартная.")
    return {"segment": seg, "density": density, "limit": limit, "rank": rank, "reasons": reasons,
            "score": profile.get("score"), "confidence": conf}


def _trust(r: dict) -> float:
    return (r.get("rating") or 0) * math.log1p(r.get("reviews") or 0)


def rerank(profile: dict, results: list[dict], vid: str = "", demo: bool = False) -> dict:
    """Переставляет отели только внутри своей корзины: «подходит» всегда выше «возможно».
    Затем кластеры вкуса (app/taste.py) сдвигают порядок к вкусу похожих посетителей, если режим это разрешает."""
    pol = policy(profile)
    order = {"match": 0, "maybe": 1, "fail": 2}
    if pol["rank"] == "trust":
        key = lambda r: (order.get(r.get("bucket"), 3), -_trust(r))
    elif pol["rank"] == "evidence":
        key = lambda r: (order.get(r.get("bucket"), 3), -(r.get("good") or 0), r.get("unknown") or 0)
    elif pol["rank"] == "balanced":
        key = lambda r: (order.get(r.get("bucket"), 3), -((r.get("good") or 0) + 0.15 * _trust(r)))
    else:
        key = lambda r: order.get(r.get("bucket"), 3)
    ranked = sorted(results, key=key)
    if pol["limit"]:
        ranked = ranked[:pol["limit"]]
    notes = {"trust": "Подобрано под ваш темп: сначала проверенные отели, крупнее и короче",
             "evidence": "Подобрано под ваш темп: выше отели, где подтверждено больше условий",
             "balanced": "Подобрано под ваш темп"}
    out = {"order": [r["id"] for r in ranked], "density": pol["density"], "note": notes.get(pol["rank"]), "policy": pol,
           "rub": "Подобрано под ваш темп"}
    try:
        t = taste.apply(vid, [{"id": r["id"], "bucket": r.get("bucket")} for r in ranked], demo=demo,
                        opt_out=bool(profile.get("optOut")))
    except Exception as e:   # кластеры не должны ломать выдачу
        t = {"mode": "error", "applied": False, "why": type(e).__name__}
    if t.get("applied"):
        out["order"] = t["order"]
        if t.get("note"):
            out["note"] = t["note"]
            out["rub"] = "Демо: синтетические посетители" if t.get("mode") == "demo" else "Подобрано по выбору похожих посетителей"
    out["taste"] = {k: v for k, v in t.items() if k != "order"}
    return out


def record(sid: str, profile: dict, vid: str = "") -> dict:
    pol = policy(profile)
    slim = {k: profile.get(k) for k in ("score", "confidence", "segment", "parts", "device", "hand", "patience", "signals")}
    _SESSIONS[sid] = {"at": time.time(), "profile": slim, "policy": pol["segment"]}
    if vid and not profile.get("optOut"):
        try:
            visitors.save_profile(vid, profile)
        except Exception:
            pass
    return pol


def summary() -> dict:
    segs: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for s in _SESSIONS.values():
        segs[s["policy"]] = segs.get(s["policy"], 0) + 1
        k = (s["profile"].get("device") or {}).get("kind", "?")
        kinds[k] = kinds.get(k, 0) + 1
    return {"sessions": len(_SESSIONS), "segments": segs, "devices": kinds}
