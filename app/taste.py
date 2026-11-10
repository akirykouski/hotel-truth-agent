"""Кластеры вкуса: выдача сдвигается к среднему вкусу похожих посетителей.

Посетитель = вектор из трёх блоков:
  контекст  — устройство, ОС, тип сети, регион, местный час, язык, медленная сеть;
  моторика  — 8 показателей мини-игр (app/web/waitgames/sense.js);
  вкус      — близость к признакам отелей: что открывал (с весом по времени просмотра) и что просил в запросе.
Кластеры: стандартизация → PCA → k-means++ (k по силуэту). У кластера свой вектор вкуса τc.
Новый посетитель без истории попадает в кластер по контексту и моторике, это и есть холодный старт.

Перестановка только внутри корзины («подходит» всегда выше «возможно»), цены и состав выдачи не меняются:
  s = база(позиция) + λ · cos(признаки отеля, вкус), λ = λmax · n_c / (n_c + K0), λmax выбирает офлайн-повтор,
  вкус = (1 − w) · τc + w · свой вкус, w = n_own / (n_own + K1).

Режимы (TASTE_MODE): off · shadow (считаем и пишем в лог, не применяем) · on · auto (по умолчанию: on после порога,
иначе shadow). Демо: запрос с demo=true и модель, обученная вместе с синтетическими посетителями.
Порог: ≥200 реальных посетителей с открытием, силуэт ≥ 0.15, офлайн-повтор даёт рост MRR с нижней границей
доверительного интервала выше нуля. Синтетика в порог не идёт никогда.
"""
import hashlib
import json
import math
import os
import threading
import time
from pathlib import Path

import numpy as np

from app import registry, store, visitors

MODEL_PATH = Path(os.getenv("TASTE_MODEL") or visitors.CACHE / "taste_model.json")
LMAX, K0, K1 = 0.6, 20, 3
SAFE_LMAX = 0.05     # ручной TASTE_MODE=on без пройденного порога
HOLDOUT_K = 7        # после порога каждый 7-й посетитель (по vid) остаётся без буста: с ним сравниваем
MIN_CLUSTER = 8
GATE = {"real_with_open": 200, "silhouette": 0.15}
REFIT_EVERY = 600
BLOCK_W = {"context": 1.0, "motor": 0.5, "taste": 1.0}
MOTOR_PARTS = ["реакция", "точность касаний", "уверенность жестов", "чувство ритма", "слежение за целью",
               "скорость решений", "набор текста", "промахи в интерфейсе"]
DEVICES = ["phone", "tablet", "desktop"]
OSES = ["iOS", "Android", "Windows", "macOS"]
NETS = ["mobile", "home", "hosting", "corp"]

SKIP_CHARS = {"sea_season"}   # одинаково у всех отелей региона
# признак в причине стоит после слова «отели»: «Выше отели с видом на море, …»
REASON = {"accessibility": "без лестниц или с лифтом", "adults_only": "только для взрослых", "balcony": "с балконом",
          "beach_walk": "в шаговой доступности от пляжа", "blackout": "с плотными шторами", "breakfast": "с завтраком",
          "car": "с парковкой", "construction": "без стройки рядом", "family": "для семей с детьми",
          "fitness": "с тренажёрным залом", "food_near": "с кафе рядом", "kids": "с детской площадкой рядом",
          "kitchen": "с кухней в номере", "meal_plan": "с пансионом или «всё включено»",
          "night_checkin": "с ночным заселением", "night_open": "с круглосуточной аптекой рядом",
          "night_quiet": "с тихими ночами", "pets": "для гостей с питомцами", "pool": "с бассейном",
          "private_beach": "со своим пляжем", "sea_view": "с видом на море", "sea_view_quiet": "с видом на море с тихой стороны",
          "soundproofing": "с шумоизоляцией", "spa": "со спа", "sunset": "с видом на закат",
          "sunset_quiet": "с видом на закат с тихой стороны", "transfer": "с трансфером", "wifi": "с интернетом для работы",
          "price_low": "дешевле среднего", "rating_hi": "с оценкой гостей от 9", "stars_hi": "на 4–5 звёзд",
          "bathtub": "с ванной", "center_walk": "в пешей доступности от центра", "station_walk": "в пешей доступности от вокзала",
          "stroller_beach": "с удобной дорогой с коляской до пляжа", "noise_floors": "с тихими этажами ночью"}   # характеристика не из словаря (новая, от агента) в причину не попадает
OPS = {"==": lambda a, b: a == b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b,
       ">=": lambda a, b: a >= b, ">": lambda a, b: a > b}


def _env_mode() -> str:
    m = (os.getenv("TASTE_MODE") or "auto").lower()
    return m if m in ("off", "shadow", "on", "auto") else "auto"


# ---------- признаки отелей ----------

_hotels = None


def _fact_bool(char_id, v):
    """Выполнено ли условие характеристики по умолчанию (то же, что проверяет поиск): так полярность признака
    всегда совпадает со смыслом («без стройки рядом» = none_near истинно)."""
    if not isinstance(v, dict):
        return None
    try:
        dc = registry.get(char_id).get("default_constraint") or {}
    except Exception:
        return None
    x, op = v.get(dc.get("field")), OPS.get(dc.get("op", "=="))
    if x is None or op is None or isinstance(x, (dict, list)):
        return None
    try:
        return bool(op(x, dc.get("value", True)))
    except TypeError:
        return None


def hotels():
    """id отелей, подписи признаков и матрица признаков: сырая (0/1 и шкалы) и центрированная для косинуса."""
    global _hotels
    if _hotels is not None:
        return _hotels
    from app import geodata as gd
    hs = gd.load().hotels
    best = {}
    for r in store.conn().execute("SELECT hotel_id, char_id, value, confidence FROM facts WHERE active=1"):
        k = (str(r[0]), r[1])
        if k not in best or (r[3] or 0) > best[k][1]:
            try:
                best[k] = (json.loads(r[2]), r[3] or 0)
            except (TypeError, ValueError):
                pass
    chars = sorted({c for (_, c) in best} - SKIP_CHARS)
    names = {}
    for c in chars:
        try:
            names[c] = registry.get(c)["name"]
        except Exception:
            names[c] = c
    cols = chars + ["price_low", "rating_hi", "stars_hi"]
    labels = {**names, "price_low": "недорогие", "rating_hi": "высокий рейтинг", "stars_hi": "4–5 звёзд"}
    prices = np.array([h.get("price_nov1") or np.nan for h in hs], float)
    med = np.nanmedian(prices) if np.isfinite(prices).any() else 0
    raw = np.zeros((len(hs), len(cols)))
    for i, h in enumerate(hs):
        for j, c in enumerate(chars):
            v = best.get((str(h["id"]), c))
            b = _fact_bool(c, v[0]) if v else None
            raw[i, j] = 0.5 if b is None else float(b)
        p = prices[i]
        raw[i, -3] = 0.5 if not np.isfinite(p) else float(p <= med)
        raw[i, -2] = float((h["rating"]["total"] or 0) >= 9)
        raw[i, -1] = float((h.get("stars") or 0) >= 4)
    mu, sd = raw.mean(0), raw.std(0)
    sd[sd < 1e-6] = 1
    cen = (raw - mu) / sd
    unit = cen / np.maximum(np.linalg.norm(cen, axis=1, keepdims=True), 1e-9)
    ids = [str(h["id"]) for h in hs]
    _hotels = {"ids": ids, "index": {x: i for i, x in enumerate(ids)}, "cols": cols, "labels": labels,
               "raw": raw, "cen": cen, "unit": unit, "price": prices}
    return _hotels


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v * 0


# ---------- признаки посетителя ----------

def own_taste(evs, H, before=None):
    """Вкус из своих действий: открытые отели (вес по времени просмотра) и характеристики из запросов."""
    d = len(H["cols"])
    v, n = np.zeros(d), 0.0
    dwell = {}
    for e in evs:
        if e["type"] == "dwell" and e.get("hotel_id"):
            dwell[e["hotel_id"]] = dwell.get(e["hotel_id"], 0) + float(e["data"].get("ms") or 0)
    for e in evs:
        if before is not None and e["at"] >= before:
            continue
        if e["type"] == "open" and e.get("hotel_id") in H["index"]:
            w = 1 + min(dwell.get(e["hotel_id"], 0) / 1000, 120) / 30
            v += w * H["cen"][H["index"][e["hotel_id"]]]
            n += 1
        elif e["type"] == "search":
            for c in e["data"].get("chars") or []:
                if c in H["cols"]:
                    j = H["cols"].index(c)
                    v[j] += 2.0
                    n += 0.5
    return _unit(v), n


def _onehot(val, vocab):
    return [1.0 if val == x else 0.0 for x in vocab]


def context_vec(v, regions):
    cl = v.get("client") or {}
    hour = cl.get("hour")
    hr = [math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24)] if isinstance(hour, (int, float)) else [0, 0]
    slow = 1.0 if (cl.get("saveData") or cl.get("effectiveType") in ("slow-2g", "2g", "3g")) else 0.0
    lang = (v.get("lang") or (cl.get("langs") or [""])[0] or "").lower()
    reg = v.get("region") if v.get("region") in regions else ("other" if v.get("region") else None)
    return (_onehot(v.get("device"), DEVICES) + _onehot(v.get("os"), OSES) + _onehot(v.get("net"), NETS)
            + _onehot(reg, regions + ["other"]) + hr
            + [1.0 if cl.get("weekday") in (0, 6) else 0.0, 1.0 if lang.startswith("ru") else 0.0, slow,
               1.0 if (cl.get("deviceMemory") or 8) <= 4 else 0.0])


def motor_vec(profile):
    parts = (profile or {}).get("parts") or {}
    vals = [parts.get(k) for k in MOTOR_PARTS]
    return [((x / 100) - 0.5) if isinstance(x, (int, float)) else 0.0 for x in vals] + \
           [1.0 if isinstance(x, (int, float)) else 0.0 for x in vals[:1]]


# ---------- k-means ----------

def _kmeans(X, k, rng, n_init=4, iters=60):
    best = None
    for _ in range(n_init):
        C = [X[rng.integers(len(X))]]
        for _ in range(1, k):
            d = np.min(((X[:, None, :] - np.array(C)[None]) ** 2).sum(-1), 1)
            p = d / d.sum() if d.sum() > 0 else None
            C.append(X[rng.choice(len(X), p=p)])
        C = np.array(C)
        for _ in range(iters):
            lab = ((X[:, None, :] - C[None]) ** 2).sum(-1).argmin(1)
            newC = np.array([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
            if np.allclose(newC, C):
                break
            C = newC
        inertia = ((X - C[lab]) ** 2).sum()
        if best is None or inertia < best[0]:
            best = (inertia, C, lab)
    return best[1], best[2]


def silhouette(X, lab, rng, sample=1500):
    if len(set(lab.tolist())) < 2:
        return 0.0
    idx = rng.choice(len(X), min(sample, len(X)), replace=False)
    Xs, ls = X[idx], lab[idx]
    D = np.sqrt(((Xs[:, None, :] - Xs[None]) ** 2).sum(-1))
    s = []
    for i in range(len(Xs)):
        same = ls == ls[i]
        if same.sum() < 2:
            s.append(0.0)
            continue
        a = D[i, same].sum() / (same.sum() - 1)
        b = min(D[i, ls == c].mean() for c in set(ls.tolist()) if c != ls[i])
        s.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return float(np.mean(s))


# ---------- модель ----------

def _dataset(include_synthetic, db=None, exclude=None, until=None):
    H = hotels()
    vs = [v for v in visitors.all_visitors(db) if (include_synthetic or not v["synthetic"])
          and not (exclude and v["vid"] in exclude) and v.get("device") != "bot"]
    evs = {}
    for e in visitors.events_of(types=("open", "dwell", "search"), db=db):
        evs.setdefault(e["vid"], []).append(e)
    return H, vs, evs


def fit(include_synthetic=False, db=None, exclude=None, seed=0, k_range=range(2, 11)):
    """Обучает кластеры. exclude — vid, которых не видеть (для честного офлайн-повтора)."""
    H, vs, evs = _dataset(include_synthetic, db, exclude)
    if len(vs) < 2 * MIN_CLUSTER:
        return None
    rc = {}
    for v in vs:
        if v.get("region"):
            rc[v["region"]] = rc.get(v["region"], 0) + 1
    regions = sorted([r for r, n in rc.items() if n >= 5], key=lambda r: -rc[r])[:12]
    rows, tastes, nown = [], [], []
    for v in vs:
        t, n = own_taste(evs.get(v["vid"], []), H)
        rows.append((context_vec(v, regions), motor_vec(v.get("profile")), t.tolist()))
        tastes.append(t)
        nown.append(n)
    blocks = {}
    for bi, name in enumerate(("context", "motor", "taste")):
        B = np.array([r[bi] for r in rows], float)
        mu, sd = B.mean(0), B.std(0)
        sd[sd < 1e-6] = 1
        blocks[name] = {"mu": mu, "sd": sd, "w": BLOCK_W[name] / math.sqrt(B.shape[1])}
    X = np.hstack([((np.array([r[bi] for r in rows]) - blocks[n]["mu"]) / blocks[n]["sd"]) * blocks[n]["w"]
                   for bi, n in enumerate(("context", "motor", "taste"))])
    Xc = X - X.mean(0)
    _, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    keep = max(2, min(12, int(np.searchsorted(np.cumsum(S ** 2) / (S ** 2).sum(), 0.9)) + 1))
    P = Xc @ Vt[:keep].T
    rng = np.random.default_rng(seed)
    best = None
    for k in k_range:
        if k * MIN_CLUSTER > len(vs):
            break
        C, lab = _kmeans(P, k, rng)
        s = silhouette(P, lab, rng)
        if best is None or s > best[0] + 1e-3:
            best = (s, k, lab)
    s, k, lab = best
    T, cent, size = [], [], []
    tastes, nown = np.array(tastes), np.array(nown)
    for j in range(k):
        m = lab == j
        size.append(int(m.sum()))
        cent.append(X[m].mean(0))
        w = np.minimum(nown[m], 10)
        T.append(_unit((tastes[m] * w[:, None]).sum(0)) if w.sum() > 0 else np.zeros(len(H["cols"])))
    return {"at": time.time(), "include_synthetic": include_synthetic, "k": k, "silhouette": round(s, 4),
            "n": len(vs), "regions": regions, "cols": H["cols"], "dims": {"pca": keep, "full": X.shape[1]},
            "blocks": {n: {"mu": b["mu"].tolist(), "sd": b["sd"].tolist(), "w": b["w"]} for n, b in blocks.items()},
            "centroids": np.array(cent).tolist(), "taste": np.array(T).tolist(), "size": size}


def assign(model, v, own=None):
    """Кластер посетителя по тем блокам, что у него есть (у нового только контекст и моторика)."""
    b = model["blocks"]
    parts, mask = [], []
    for name, vec, present in (("context", context_vec(v, model["regions"]), True),
                               ("motor", motor_vec(v.get("profile")), bool((v.get("profile") or {}).get("parts"))),
                               ("taste", (own if own is not None else np.zeros(len(model["cols"]))).tolist(),
                                own is not None and np.linalg.norm(own) > 0)):
        x = (np.array(vec, float) - np.array(b[name]["mu"])) / np.array(b[name]["sd"]) * b[name]["w"]
        parts.append(x)
        mask.append(np.full(len(x), present))
    x, m = np.concatenate(parts), np.concatenate(mask)
    C = np.array(model["centroids"])
    d = (((C - x) ** 2) * m).sum(1)
    elig = np.array(model["size"]) >= MIN_CLUSTER
    d[~elig] = np.inf
    return int(d.argmin()) if np.isfinite(d).any() else None


# ---------- перестановка ----------

def _taste_for(model, v, evs, H, before=None, lmax=None):
    own, n_own = own_taste(evs, H, before)
    c = assign(model, v, own if n_own > 0 else None)
    if c is None:
        return None
    tau = np.array(model["taste"][c])
    if np.linalg.norm(tau) == 0 and n_own == 0:
        return None
    w = n_own / (n_own + K1)
    t = _unit((1 - w) * tau + w * own)
    n_c = model["size"][c]
    if lmax is None:   # выученные повтором: холодный старт (только кластер) и с историей (свой вкус + кластер)
        lmax = model.get("lmax_warm" if n_own > 0 else "lmax_cold", LMAX)
    lm = lmax
    return {"cluster": c, "n_c": n_c, "lam": lm * n_c / (n_c + K0), "taste": t, "w_own": round(w, 3)}


def reorder(rows, tv, H):
    """rows: [{id, bucket}] в исходном порядке. Возвращает новый порядок id и сдвиги."""
    if tv is None:
        return [r["id"] for r in rows], {}
    order = {"match": 0, "maybe": 1, "fail": 2}
    by_b = {}
    for i, r in enumerate(rows):
        by_b.setdefault(r.get("bucket"), []).append((i, r))
    out, cos = [], {}
    for b in sorted(by_b, key=lambda x: order.get(x, 3)):
        grp = by_b[b]
        n = len(grp)
        sc = []
        for pos, (i, r) in enumerate(grp):
            hi = H["index"].get(str(r["id"]))
            c = float(H["unit"][hi] @ tv["taste"]) if hi is not None else 0.0
            cos[str(r["id"])] = c
            sc.append((1 - pos / max(n, 1)) + tv["lam"] * c * (1 if n > 1 else 0))
        out += [grp[j][1]["id"] for j in sorted(range(n), key=lambda j: (-sc[j], j))]
    return out, cos


def _reason(tv, H, moved_up, pool, skip=()):
    """Чем поднятые отели отличаются от остальных в той же выдаче. Характеристики из запроса не называем:
    их и так выполняют все отели в «Подходит», повторять их как причину бессмысленно."""
    t = tv["taste"]
    idx = lambda hs: [H["index"][str(h)] for h in hs if str(h) in H["index"]]
    up, rest = idx(moved_up), idx(pool)
    if not up or not rest:
        return None
    score = t * (H["raw"][up].mean(0) - H["raw"][rest].mean(0))
    top = [REASON[H["cols"][j]] for j in np.argsort(-score) if score[j] > 0 and H["cols"][j] in REASON
           and H["cols"][j] not in skip][:2]
    if not top:
        return None
    if tv["w_own"] >= 0.5:
        return f"Выше отели {', '.join(top)}: похожие на те, что вы уже открывали"
    return f"Выше отели {', '.join(top)}: такие чаще открывают похожие посетители"


# ---------- состояние, порог, режимы ----------

_state = {"prod": None, "demo": None, "gate": None, "fitting": False, "last_try": 0.0}
_lock = threading.Lock()


def _load():
    try:
        d = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
        _state.update({k: d.get(k) for k in ("prod", "demo", "gate")})
    except (OSError, ValueError):
        pass


def _save():
    try:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        MODEL_PATH.write_text(json.dumps({k: _state[k] for k in ("prod", "demo", "gate")}), encoding="utf-8")
    except OSError:
        pass


def refit(db=None, evaluate_gate=True):
    """Переобучает обе модели и пересчитывает порог. Вызывается фоном или вручную (/api/taste/refit)."""
    prod = fit(include_synthetic=False, db=db)
    demo = fit(include_synthetic=True, db=db)
    cnt = visitors.counts(db)
    old = _state["gate"] or {}
    ev = replay(include_synthetic=False, db=db) if (evaluate_gate and prod) else old.get("replay")
    ev_cold = replay(include_synthetic=False, db=db, cold_only=True) if (evaluate_gate and prod) else old.get("replay_cold")
    enough = bool(prod and cnt["real_with_open"] >= GATE["real_with_open"] and prod["silhouette"] >= GATE["silhouette"])
    ok = lambda e: bool(e and e["users"] >= 30 and e["ci_low"] > 0 and e["lmax"] > 0)
    passed = enough and (ok(ev) or ok(ev_cold))
    if prod:   # сила буста берётся из повтора, а не задаётся руками; 0 = в этом режиме не переставляем
        prod["lmax_warm"] = ev["lmax"] if passed and ok(ev) else 0.0
        prod["lmax_cold"] = ev_cold["lmax"] if passed and ok(ev_cold) else 0.0
    gate = {"at": time.time(), "passed": passed, "real_with_open": cnt["real_with_open"],
            "need": GATE["real_with_open"], "silhouette": prod and prod["silhouette"], "replay": ev, "replay_cold": ev_cold,
            "lmax_warm": prod and prod.get("lmax_warm"), "lmax_cold": prod and prod.get("lmax_cold")}
    with _lock:
        _state.update({"prod": prod, "demo": demo, "gate": gate})
    _save()
    return gate


def _maybe_refit():
    if _state["fitting"] or time.time() - _state["last_try"] < REFIT_EVERY:
        return
    _state["fitting"], _state["last_try"] = True, time.time()

    def run():
        try:
            refit()
        except Exception:
            pass
        finally:
            _state["fitting"] = False
    threading.Thread(target=run, daemon=True).start()


def mode() -> str:
    m = _env_mode()
    if m == "auto":
        return "on" if (_state["gate"] or {}).get("passed") else "shadow"
    return m


def apply(vid, rows, demo=False, opt_out=False, db=None):
    """Главный вход. rows: [{id, bucket}] после политики профиля. Возвращает {order, note, mode, ...}."""
    ids = [r["id"] for r in rows]
    m = mode()
    if opt_out or m == "off" or not vid or not rows:
        return {"order": ids, "mode": "off" if opt_out else m, "applied": False}
    if _state["prod"] is None and _state["demo"] is None:
        _load()
    _maybe_refit()
    use_demo = demo and os.getenv("TASTE_DEMO", "0") == "1"   # демо только там, где его включили явно
    model = _state["demo"] if use_demo else _state["prod"]
    v = visitors.visitor(vid, db)
    if v is not None and v.get("device") == "bot":
        return {"order": ids, "mode": m, "applied": False, "why": "бот"}
    if model is None or v is None:
        return {"order": ids, "mode": "demo" if use_demo else m, "applied": False, "why": "нет модели" if v else "нет посетителя"}
    H = hotels()
    # сила: выученная повтором (после порога) или по умолчанию для демо, тени и ручного TASTE_MODE=on
    evs = visitors.events_of(vid, ("open", "dwell", "search"), db)
    if use_demo or m == "shadow":
        lm = LMAX          # демо и теневой порядок для лога: посетитель их не видит (демо помечено)
    elif _state["gate"] and _state["gate"].get("passed"):
        lm = None          # выученные повтором lmax_cold / lmax_warm
    else:
        lm = SAFE_LMAX     # TASTE_MODE=on без пройденного порога: самая слабая сила, не 0,6
    tv = _taste_for(model, v, evs, H, lmax=lm)
    new, cos = reorder(rows, tv, H)
    info = {"cluster": tv and tv["cluster"], "cluster_size": tv and tv["n_c"], "lambda": tv and round(tv["lam"], 3),
            "w_own": tv and tv["w_own"]}
    holdout = m == "on" and not use_demo and _fold(vid, HOLDOUT_K) == 0
    if m == "on" and not use_demo:   # исходный порядок до буста: по нему честно меряет следующий повтор
        visitors.log_events(vid, [{"type": "serp_base", "data": {"rows": rows[:30], "holdout": holdout}}], db, server=True)
    if (use_demo or m == "on") and not holdout:
        moved = [h for i, h in enumerate(new[:10]) if h in ids and ids.index(h) > i]
        last = [e for e in evs if e["type"] == "search"]
        skip = set(last[-1]["data"].get("chars") or []) if last else set()
        note = _reason(tv, H, moved, ids[:30], skip) if tv and new != ids else None
        return {"order": new, "mode": "demo" if use_demo else "on", "applied": new != ids, "note": note, **info}
    if new != ids:
        visitors.log_events(vid, [{"type": "shadow", "data": {"shown": ids[:30], "taste": new[:30], **info}}], db, server=True)
    return {"order": ids, "mode": "holdout" if holdout else "shadow", "applied": False, **info}


def status(db=None) -> dict:
    if _state["gate"] is None:
        _load()
    pm = _state["prod"] or {}
    dm = _state["demo"] or {}
    return {"mode": mode(), "env_mode": _env_mode(), "counts": visitors.counts(db), "gate": _state["gate"],
            "prod": {k: pm.get(k) for k in ("k", "silhouette", "n", "size", "at", "dims")} if pm else None,
            "demo": {k: dm.get(k) for k in ("k", "silhouette", "n", "size", "at", "dims")} if dm else None,
            "clusters": [_describe(dm, j) for j in range(dm.get("k", 0))] if dm else []}


def _describe(model, j):
    H = hotels()
    t = np.array(model["taste"][j])
    top = [REASON.get(H["cols"][i], H["labels"][H["cols"][i]]) for i in np.argsort(-t)[:3] if t[i] > 0.05]
    return {"cluster": j, "size": model["size"][j], "likes": top}


# ---------- офлайн-повтор ----------

def _fold(vid, k=5):
    return int(hashlib.md5(vid.encode()).hexdigest(), 16) % k


LAMBDAS = (0.05, 0.1, 0.2, 0.4, 0.6)


def replay(include_synthetic=False, db=None, folds=5, boot=500, seed=1, cold_only=False, lams=LAMBDAS):
    """Честная проверка на логах: модель без пользователя (k-fold по посетителям), вкус только из того,
    что было до открытия. Сравниваем позицию открытого отеля в показанном порядке и в порядке по вкусу.
    Перебираем λmax: берём ту, что даёт наибольший рост среди значимых (нижняя граница 95% ДИ выше нуля); иначе λmax = 0
    (кластеры не помогают, буст выключен). Так на данных без сигнала перестановка не вредит."""
    allv = {v["vid"]: v for v in visitors.all_visitors(db) if (include_synthetic or not v["synthetic"]) and v.get("device") != "bot"}
    H = hotels()
    evs = {}
    for e in visitors.events_of(types=("serp", "serp_base", "open", "dwell", "search"), db=db):
        if e["vid"] in allv:
            evs.setdefault(e["vid"], []).append(e)
    cases = {}
    for vid, es in evs.items():
        shown = base = serp = None
        for e in es:
            if e["type"] in ("serp", "serp_base"):
                if e["type"] == "serp":
                    shown = e
                else:
                    base = e
                # исходный порядок с сервера честнее показанного: после порога показанный уже с бустом
                serp = base if (base and shown and base["at"] >= shown["at"] - 30) or (base and not shown) else shown
            elif e["type"] == "open" and serp and e.get("hotel_id") in [str(x["id"]) for x in serp["data"].get("rows", [])]:
                # клик под бустом смещает повтор в пользу буста: после порога честны только клики контрольной группы
                if serp["type"] == "serp_base" and not serp["data"].get("holdout"):
                    continue
                cases.setdefault(vid, []).append((serp, e))
    if not cases:
        return None
    per_user = {lm: [] for lm in lams}
    for f in range(folds):
        test = [v for v in cases if _fold(v, folds) == f]
        if not test:
            continue
        model = fit(include_synthetic=include_synthetic, db=db, exclude=set(test))
        if model is None:
            continue
        for vid in test:
            d = {lm: ([], []) for lm in lams}
            for serp, op in cases[vid]:
                rows = serp["data"]["rows"]
                prior = [] if cold_only else [e for e in evs[vid] if e["at"] < op["at"]]
                base = [str(r["id"]) for r in rows]
                for lm in lams:
                    tv = _taste_for(model, allv[vid], prior, H, before=op["at"], lmax=lm)
                    new, _ = reorder(rows, tv, H)
                    d[lm][0].append(1 / (base.index(op["hotel_id"]) + 1))
                    d[lm][1].append(1 / ([str(x) for x in new].index(op["hotel_id"]) + 1))
            for lm in lams:
                per_user[lm].append((float(np.mean(d[lm][0])), float(np.mean(d[lm][1]))))
    if not per_user[lams[0]]:
        return None
    rng = np.random.default_rng(seed)
    by = []
    for lm in lams:
        A = np.array(per_user[lm])
        diff = A[:, 1] - A[:, 0]
        bs = [diff[rng.integers(len(diff), size=len(diff))].mean() for _ in range(boot)]
        by.append({"lmax": lm, "users": len(A), "mrr_base": round(float(A[:, 0].mean()), 4),
                   "mrr_taste": round(float(A[:, 1].mean()), 4), "gain": round(float(diff.mean()), 4),
                   "ci_low": round(float(np.percentile(bs, 2.5)), 4), "ci_high": round(float(np.percentile(bs, 97.5)), 4)})
    ok = [r for r in by if r["ci_low"] > 0]
    if ok:
        best = max(ok, key=lambda r: r["gain"])
    else:
        top = max(by, key=lambda r: r["gain"])
        best = {**top, "lmax": 0.0, "best_tried_lmax": top["lmax"]}
    return {**best, "cold_only": cold_only, "by_lambda": by}
