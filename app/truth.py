"""Движок правды: какому источнику верить по каждой характеристике.

Раньше победителем всегда был отельер (вес 1.0), а уверенность задавалась руками. Теперь по логическим
характеристикам (поле key типа bool) считается апостериорная вероятность значения в духе Dawid–Skene:
у каждого отеля есть скрытое истинное значение, каждый источник голосует за него со своей чувствительностью
и специфичностью, голос тем сильнее, чем выше уверенность самого факта. Надёжность источников оценивается EM
по всем отелям отдельно для каждой характеристики (scripts/fit_truth.py → data/truth_reliability.json) с
априорами по классу характеристики:
  physical     — геометрия, шум, расстояния, окружение по OSM: расчёту верим, слова отельера слабый довод;
  policy       — то, что решает сам отель (питомцы, заселение): отельер главный;
  experiential — то, как это ощущают гости (Wi-Fi, звукоизоляция): главные отзывы, свежие весомее.
Отельер получает репутацию: чем чаще его ответы расходятся с надёжным расчётом, тем меньше вес всех его ответов.
"""
import json
import math
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

FILE = Path(os.getenv("TRUTH_RELIABILITY") or Path(__file__).resolve().parent.parent / "data" / "truth_reliability.json")
CLASSES = ("physical", "policy", "experiential")
COMPUTED = ("geo", "osm", "open-meteo", "photos")

# априор надёжности источника: (чувствительность, специфичность, псевдонаблюдений). Сила априора = насколько
# данные должны переубедить, чтобы EM сдвинул оценку.
PRIORS = {
    "physical": {"geo": (0.93, 0.93, 8), "osm": (0.90, 0.90, 8), "open-meteo": (0.93, 0.93, 25),
                 "photos": (0.85, 0.85, 15), "card": (0.75, 0.65, 12), "reviews": (0.80, 0.80, 12),
                 "hotelier": (0.65, 0.55, 8)},
    "policy": {"hotelier": (0.96, 0.96, 30), "card": (0.88, 0.85, 20), "reviews": (0.70, 0.70, 10),
               "geo": (0.80, 0.80, 10), "osm": (0.80, 0.80, 10), "open-meteo": (0.80, 0.80, 10),
               "photos": (0.70, 0.70, 10)},
    "experiential": {"reviews": (0.85, 0.85, 25), "card": (0.70, 0.50, 10), "hotelier": (0.75, 0.65, 10),
                     "geo": (0.80, 0.80, 10), "osm": (0.80, 0.80, 10), "open-meteo": (0.80, 0.80, 10),
                     "photos": (0.75, 0.75, 10)},
}
DEFAULT_PRIOR = (0.70, 0.70, 6)
# вес источника для небулевых ключей (там остаётся прежний резолвер «вес × уверенность × свежесть»)
CLASS_WEIGHT = {
    "physical": {"geo": 1.0, "open-meteo": 1.0, "osm": 0.95, "photos": 0.85, "card": 0.7, "reviews": 0.6, "hotelier": 0.55},
    "policy": {"hotelier": 1.0, "card": 0.8, "reviews": 0.6, "geo": 0.8, "osm": 0.8, "open-meteo": 0.8, "photos": 0.7},
    "experiential": {"reviews": 1.0, "hotelier": 0.7, "card": 0.6, "geo": 0.8, "osm": 0.8, "open-meteo": 0.8, "photos": 0.7},
}
ONE_SIDED = 0.05          # доля редких голосов, ниже которой источник считается односторонним
PI_BOUNDS = (0.45, 0.55)  # база по отелям не должна перекрывать единственный голос источника
CONF_CAP = 0.99   # даже расчёт не бывает «стопроцентным»
FLIP_GUARD = 0.1          # |z| без отельера, начиная с которого физика считается решённой (p ≥ 0.525)
HOTELIER_PHYS_CAP = 0.4   # слово отельера о физике: лишь довод при равенстве, не способен перевесить уверенный расчёт
SOLO_CAP = 0.85   # единственный содержательный источник без второго мнения: уверенности выше не заслуживает
TRUST_PRIOR = 2   # псевдо-совпадения в репутации отельера: одно расхождение не убивает доверие
REP_MIN_CONF = 0.85  # с какой уверенностью физика считается эталоном для проверки отельера


def char_class(spec):
    """Класс характеристики из реестра; для своих (созданных словами) — по источникам рецепта."""
    c = spec.get("class")
    if c in CLASSES:
        return c
    srcs = {m.get("source") for m in spec.get("methods", [])}
    if srcs & {"geo", "osm", "open-meteo"}:
        return "physical"
    return "experiential" if "reviews" in srcs else "policy"


def class_weight(cls, source):
    return CLASS_WEIGHT[cls].get(source, 0.5)


LOW = ":lo"        # суффикс слабого голоса: у факта уверенность ниже порога, надёжность у таких голосов своя
LOW_CONF = 0.5


def prior(cls, source):
    """Априор источника; слабые голоса (source:lo) — тот же априор, сжатый к «монетке» и вдвое менее настойчивый."""
    if source.endswith(LOW):
        s, sp, n = prior(cls, source[:-len(LOW)])
        return (0.5 + 0.6 * (s - 0.5), 0.5 + 0.6 * (sp - 0.5), max(3, n // 2))
    return PRIORS[cls].get(source, DEFAULT_PRIOR)


def bucket(f):
    """Ключ надёжности факта: источник, а для слабого факта ещё и пометка :lo."""
    return f["source"] + (LOW if (f.get("confidence") or 0) < LOW_CONF else "")


def is_bool_key(spec):
    key = spec.get("key")
    return bool(key) and (spec.get("fields", {}).get(key) or {}).get("type") == "bool"


def _age_days(f, now=None):
    try:
        t = datetime.fromisoformat(f["observed_at"])
    except (TypeError, ValueError, KeyError):
        return 0.0
    return max(0.0, ((now or datetime.now(timezone.utc)) - t).total_seconds() / 86400)


def strength(f, cls, ttl_days=None):
    """Сила голоса факта 0..1: его собственная уверенность × свежесть (просрочено вдвое слабее; у мнений гостей
    ещё и затухание по возрасту наблюдения)."""
    w = float(f.get("confidence") or 0)
    vu = f.get("valid_until")
    if vu and datetime.fromisoformat(vu) < datetime.now(timezone.utc):
        w *= 0.5
    if cls == "experiential" and f.get("source") == "reviews" and ttl_days:
        w *= 0.5 ** (_age_days(f) / (2.0 * ttl_days))
    return max(0.0, min(1.0, w))


def _vote(f, key):
    v = (f.get("value") or {}).get(key)
    return v if isinstance(v, bool) else None


def _llr(sens, spec_, x):
    """Лог-отношение правдоподобия голоса x: насколько он двигает в пользу «истина»."""
    return math.log(sens / (1 - spec_)) if x else math.log((1 - sens) / spec_)


def _logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(z):
    return 1 / (1 + math.exp(-z))


# ---------- надёжность источников ----------

def _votes_by_hotel(spec, rows, exclude=()):
    key, cls, ttl = spec["key"], char_class(spec), spec.get("ttl_days")
    by = {}
    for r in rows:
        if r["source"] in exclude:
            continue
        x = _vote(r, key)
        if x is None:
            continue
        w = strength(r, cls, ttl)
        cur, b = by.setdefault(r["hotel_id"], {}), bucket(r)
        if b not in cur or w > cur[b][1]:
            cur[b] = (x, w)
    return by


def fit_char(spec, rows, exclude=(), iters=40):
    """EM по всем отелям для одной характеристики. rows — активные факты (dict с hotel_id, source, value,
    confidence, observed_at, valid_until). Источники из exclude в оценку не входят (проверка утечки)."""
    cls, by = char_class(spec), _votes_by_hotel(spec, rows, exclude)
    sources = sorted({s for v in by.values() for s in v})
    par = {s: list(prior(cls, s)[:2]) for s in sources}
    pi = 0.5
    # односторонние источники (почти всегда голосуют «да», как карточка) ничего не говорят о чужой надёжности:
    # их параметры остаются априорными и в обучение других не идут
    base = lambda s: s.split(":")[0]  # noqa: E731
    votes_of = {}
    for v in by.values():
        for s, (x, _) in v.items():
            votes_of.setdefault(base(s), []).append(x)
    two = {s for s, xs in votes_of.items() if len(xs) >= 20 and min(sum(xs), len(xs) - sum(xs)) / len(xs) >= ONE_SIDED}
    learn = {h: {s: t for s, t in v.items() if base(s) in two} for h, v in by.items()}
    multi = [h for h, v in learn.items() if len(v) >= 2]   # параметры учим только там, где независимые источники можно сверить
    post = {}
    for _ in range(iters):
        for h, v in by.items():
            z = _logit(pi) + sum(w * _llr(par[s][0], par[s][1], x) for s, (x, w) in v.items())
            post[h] = _sigmoid(z)
        pi = (2 + sum(post.values())) / (4 + len(post)) if post else 0.5
        pi = min(PI_BOUNDS[1], max(PI_BOUNDS[0], pi))
        for h in multi:   # апостериор для обучения: только двусторонние источники
            z = _logit(pi) + sum(w * _llr(par[s][0], par[s][1], x) for s, (x, w) in learn[h].items())
            post[h] = _sigmoid(z)
        for s in sources:
            if base(s) not in two:
                continue
            sens0, spec0, n0 = prior(cls, s)
            hs = [h for h in multi if s in learn[h]]
            a = n0 * sens0 + sum(post[h] * learn[h][s][1] * learn[h][s][0] for h in hs)
            b = n0 + sum(post[h] * learn[h][s][1] for h in hs)
            c = n0 * spec0 + sum((1 - post[h]) * learn[h][s][1] * (not learn[h][s][0]) for h in hs)
            d = n0 + sum((1 - post[h]) * learn[h][s][1] for h in hs)
            par[s] = [min(0.99, max(0.05, a / b)), min(0.99, max(0.05, c / d))]
    return {"class": cls, "pi": round(pi, 3), "hotels": len(by), "multi_source_hotels": len(multi),
            "excluded": sorted(exclude),
            "sources": {s: {"sens": round(par[s][0], 3), "spec": round(par[s][1], 3),
                            "votes": sum(1 for v in by.values() if s in v)} for s in sources}}


def _rows(char_id):
    from app import store
    return [dict(r) | {"value": json.loads(r["value"]) if r["value"] else None}
            for r in store.conn().execute(
                "SELECT hotel_id, source, value, confidence, observed_at, valid_until FROM facts "
                "WHERE char_id=? AND active=1", (char_id,)).fetchall()]


def fit_all(exclude=()):
    from app import registry
    out = {}
    for cid, spec in registry.all_chars().items():
        if is_bool_key(spec):
            out[cid] = fit_char(spec, _rows(cid), exclude)
    return out


def save(fit, path=None):
    p = Path(path or FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(fit, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


@lru_cache(maxsize=1)
def _file():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


_lazy = {}


def reliability(spec):
    """Параметры EM для характеристики: из data/truth_reliability.json, а для новых (нет в файле) —
    досчитываются по текущей базе при первом обращении."""
    cid = spec["id"]
    fit = _file().get(cid) or _lazy.get(cid)
    if fit is None:
        fit = _lazy[cid] = fit_char(spec, _rows(cid))
    return fit


def reset():
    _file.cache_clear()
    _lazy.clear()


# ---------- апостериор ----------

def posterior(spec, fs, rep_mult=1.0, exclude=(), fit=None):
    """P(значение = истина) по фактам fs. rep_mult — репутация отельера (множитель его голоса).
    Возвращает {"p", "votes": [{source, vote, w, llr, contrib}]} или None, если булевых голосов нет."""
    key, cls, ttl = spec["key"], char_class(spec), spec.get("ttl_days")
    fit = fit or reliability(spec)
    best = {}
    for f in fs:
        if f["source"] in exclude:
            continue
        x = _vote(f, key)
        if x is None:
            continue
        w = strength(f, cls, ttl)
        if f["source"] not in best or w > best[f["source"]][2]:
            best[f["source"]] = (f, x, w)
    if not best:
        return None
    prior_only = not fit.get("multi_source_hotels")   # сверять источники между собой не на чем: надёжности только из априора
    z, votes, z_others = _logit(fit.get("pi", 0.5)), [], 0.0
    for s, (f, x, w) in sorted(best.items(), key=lambda kv: kv[0] == "hotelier"):
        b = bucket(f)
        p = fit["sources"].get(b)
        sens, sp = (p["sens"], p["spec"]) if p else prior(cls, b)[:2]
        llr = _llr(sens, sp, x)
        mult = rep_mult if s == "hotelier" else 1.0
        contrib = w * mult * llr
        if s == "hotelier" and cls == "physical":
            contrib = max(-HOTELIER_PHYS_CAP, min(HOTELIER_PHYS_CAP, contrib))
            z_others = z
        z += contrib
        votes.append({"source": s, "vote": x, "w": round(w, 3), "llr": round(llr, 2), "contrib": round(contrib, 2),
                      "fact": f, "reliability": round(sens if x else sp, 2)})
    if cls == "physical" and abs(z_others) >= FLIP_GUARD and z * z_others < 0:
        z = math.copysign(FLIP_GUARD / 2, z_others)   # слова отельера не переворачивают решение уверенного расчёта, только сбивают уверенность
    return {"p": _sigmoid(z), "votes": votes, "prior_only": prior_only}


def decide(post):
    """Значение и калиброванная уверенность из апостериора."""
    p = post["p"]
    informative = sum(1 for v in post["votes"] if abs(v["llr"]) * v["w"] >= 0.3)
    cap = CONF_CAP if informative >= 2 else SOLO_CAP
    val = p >= 0.5
    conf = min(cap, max(p, 1 - p))
    if post.get("prior_only"):   # EM не видел ни одного отеля с несколькими источниками: уверенность не выше, чем у самого факта
        own = [v["fact"].get("confidence") or 0 for v in post["votes"] if v["vote"] == val]
        if own:
            conf = min(conf, max(own))
    return val, round(conf, 3)


# ---------- репутация отельера ----------

def hotelier_reputation(hotel_id, fs_all=None):
    """Как часто ответы отельера по физическим характеристикам совпадают с уверенным расчётом без его слов.
    trust 1.0 — нет расхождений или проверять нечего; падает с каждым расхождением."""
    from app import registry, store
    fs_all = fs_all if fs_all is not None else store.facts(hotel_id)
    checks = []
    for f in fs_all:
        if f["source"] != "hotelier":
            continue
        spec = registry.get(f["char_id"])
        if not spec or not is_bool_key(spec) or char_class(spec) != "physical":
            continue
        claim = _vote(f, spec["key"])
        others = [g for g in fs_all if g["char_id"] == f["char_id"] and g["source"] != "hotelier"]
        post = posterior(spec, others) if claim is not None else None
        if not post:
            continue
        val, conf = decide(post)
        if conf < REP_MIN_CONF:
            continue
        checks.append({"char": f["char_id"], "name": spec["name"], "claim": claim, "physics": val,
                       "physics_conf": conf, "agree": claim == val})
    agree = sum(c["agree"] for c in checks)
    trust = (agree + TRUST_PRIOR) / (len(checks) + TRUST_PRIOR)
    return {"checks": len(checks), "agree": agree, "trust": round(trust, 2), "details": checks,
            "label": "нет данных для проверки" if not checks else
            f"{agree} из {len(checks)} ответов совпали с надёжным расчётом"}


def rep_multiplier(cls, trust):
    """Как репутация меняет вес голоса отельера: на физике целиком, на политике отеля только слегка."""
    if cls == "physical":
        return trust
    if cls == "policy":
        return 1 - 0.3 * (1 - trust)
    return 1 - 0.5 * (1 - trust)
