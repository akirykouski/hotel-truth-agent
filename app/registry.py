"""Реестр характеристик и исполнитель рецептов.

Характеристика — YAML-файл в registry/: описание словами, поля для поиска и рецепт — какие инструменты
вызвать и как из их результата получить значение, уверенность и короткую фразу. Рецепты исполняются
детерминированно, выражения считает app/expr.py (без eval). Новая характеристика = новый файл, код не меняется.
"""
import json
import os
import threading
from functools import lru_cache
from pathlib import Path

import yaml

from app import geodata as gd
from app import region, store
from app.expr import ExprError, evaluate
from app.tools import catalog

REG_DIR = Path(__file__).resolve().parent.parent / "registry"
CUSTOM_DIR = Path(os.getenv("CUSTOM_DIR") or (region.DATA / "custom" if region.NAME else REG_DIR / "custom"))  # сюда пишутся характеристики, добавленные словами
REQUIRED = ("id", "name", "description", "fields", "methods")


class RecipeError(ValueError):
    pass


def validate(spec):
    for k in REQUIRED:
        if k not in spec:
            raise RecipeError(f"нет поля {k}")
    if not isinstance(spec["fields"], dict) or not spec["fields"]:
        raise RecipeError("fields должен быть непустым словарём")
    for name, f in spec["fields"].items():
        if f.get("type") not in ("bool", "number", "enum", "text"):
            raise RecipeError(f"поле {name}: type должен быть bool|number|enum|text")
    for m in spec["methods"]:
        if m.get("source") not in store.SOURCE_WEIGHT:
            raise RecipeError(f"source {m.get('source')} неизвестен")
        for s in m.get("steps", []):
            if s.get("tool") not in catalog.TOOLS:
                raise RecipeError(f"инструмента {s.get('tool')} нет в каталоге")
            if not s.get("as"):
                raise RecipeError("у шага нет имени (as)")
        if "value" not in m or "confidence" not in m or "summary" not in m:
            raise RecipeError("у метода нужны value, confidence, summary")
    return spec


_LOCK = threading.RLock()  # сборки идут в фоновых потоках: чтение реестра не должно видеть недописанный файл


@lru_cache(maxsize=1)
def _load_all():
    with _LOCK:
        out = {}
        files = sorted(REG_DIR.glob("*.yaml")) + sorted(CUSTOM_DIR.glob("*.yaml"))
        for p in files:
            spec = yaml.safe_load(p.read_text(encoding="utf-8"))
            spec["_file"] = str(p.relative_to(REG_DIR.parent)) if p.is_relative_to(REG_DIR.parent) else p.name
            out[spec["id"]] = validate(spec)
        return out


_SIG = [None]


def _fresh():
    """Другой процесс (app при одобрении черновика, mcp в соседнем контейнере) пишет в общий registry/custom: заметим по mtime папки."""
    try:
        sig = CUSTOM_DIR.stat().st_mtime_ns
    except OSError:
        sig = None
    if sig != _SIG[0]:
        _SIG[0] = sig
        _load_all.cache_clear()
    return _load_all()


def all_chars():
    return _fresh()


def get(char_id):
    return _fresh().get(char_id)


def reload():
    with _LOCK:
        _load_all.cache_clear()


def save_custom(spec):
    validate(spec)
    p = CUSTOM_DIR / f"{spec['id']}.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in spec.items() if not k.startswith("_")}
    with _LOCK:
        tmp = p.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(clean, allow_unicode=True, sort_keys=False), encoding="utf-8")
        os.replace(tmp, p)
        reload()
    return p


# ---------- жизненный цикл: draft → approved | rejected ----------
# Встроенные YAML одобрены по умолчанию. Собранное словами (compiler.add) сначала черновик: его видит только
# запросивший (spec["requested_by"] = id сессии), публичный поиск и реестр для LLM его не показывают.

def status(spec):
    return spec.get("status", "approved")


def visible(spec, session=None):
    st = status(spec)
    return st == "approved" or (st == "draft" and bool(session) and spec.get("requested_by") == session)


def public_chars(session=None):
    """Характеристики, которые видит публика: одобренные плюс черновики этой сессии."""
    return {cid: s for cid, s in all_chars().items() if visible(s, session)}


def drafts(status_filter="draft"):
    return [s for s in all_chars().values() if s.get("origin") in ("compiled", "template")
            and (status_filter == "all" or status(s) == status_filter)]


def _set_status(char_id, new, **extra):
    spec = get(char_id)
    if spec is None:
        raise KeyError(char_id)
    if not (CUSTOM_DIR / f"{char_id}.yaml").exists():
        return spec  # встроенная: одобрена всегда, статус не меняется
    spec = {**spec, "status": new, **extra}
    save_custom(spec)
    return get(char_id)


def approve(char_id, by="admin"):
    """Админ одобряет черновик: с этого момента характеристику видит публичный поиск."""
    spec = _set_status(char_id, "approved", approved_by=by, approved_at=store.now())
    store.log_event("characteristic_approved", char_id=char_id, payload={"by": by})
    return spec


def reject(char_id, reason="", by="admin"):
    """Админ отклоняет черновик: он остаётся в файле для истории, но поиск его не видит ни у кого."""
    spec = _set_status(char_id, "rejected", rejected_reason=reason, rejected_by=by, rejected_at=store.now())
    store.log_event("characteristic_rejected", char_id=char_id, payload={"reason": reason, "by": by})
    return spec


def run_method(spec, m, hotel_id):
    env = {"hotel": gd.load().hotel_by_id[hotel_id]}
    calls = []
    for s in m.get("steps", []):
        args = s.get("args") or {}
        res = catalog.call(s["tool"], hotel_id, args)
        env[s["as"]] = res if res is not None else {}
        calls.append({"tool": s["tool"], "args": args})
    try:
        if "when" in m and not evaluate(m["when"], env):
            return None
        val = m["value"]
        value = {k: evaluate(v, env) for k, v in val.items()} if isinstance(val, dict) else evaluate(val, env)
        conf = evaluate(m["confidence"], env)
        summary = evaluate(m["summary"], env)
        evidence = evaluate(m["evidence"], env) if m.get("evidence") else {}
        scope = evaluate(m["scope"], env) if m.get("scope") else "отель"
    except (ExprError, TypeError, ZeroDivisionError, AttributeError) as e:
        raise RecipeError(f"{spec['id']}/{m['source']}: {e}") from e
    return {"value": value, "confidence": max(0.0, min(1.0, float(conf or 0))), "summary": str(summary),
            "evidence": {"calls": calls, **(evidence if isinstance(evidence, dict) else {"data": evidence})},
            "scope": scope}


def compute(char_id, hotel_id, persist=True):
    spec = get(char_id)
    out = []
    for m in spec["methods"]:
        r = run_method(spec, m, hotel_id)
        if r is None:
            continue
        method = m.get("method") or ", ".join(s["tool"] for s in m.get("steps", []))
        if persist:
            store.put_fact(hotel_id, char_id, m["source"], r["value"], r["confidence"], r["summary"], method,
                           spec.get("ttl_days", 180), r["evidence"], r["scope"], str(spec.get("version", 1)))
        out.append({"source": m["source"], **r})
    return out


def compute_all(char_ids=None, hotel_ids=None, log=None):
    geo = gd.load()
    char_ids = char_ids or list(all_chars())
    hotel_ids = hotel_ids or [h["id"] for h in geo.hotels]
    errors = 0
    for cid in char_ids:
        for hid in hotel_ids:
            try:
                compute(cid, hid)
            except RecipeError as e:
                errors += 1
                if log:
                    log(f"ошибка {e}")
        if log:
            log(f"{cid}: посчитано для {len(hotel_ids)} отелей")
    return errors


# ---------- вопросы отельеру по ценности информации ----------

def plan_questions(hotel_id, budget=3):
    """Выбирает до budget вопросов: где уверенность низкая или источники спорят, с учётом популярности."""
    from app import city  # city импортирует registry: импорт внутри функции
    popular = store.query_counts()
    cands = []
    for cid, spec in public_chars().items():
        q = spec.get("question")
        if not q:
            continue
        r = store.resolve(hotel_id, spec)
        env = {"fact": r.get("value") or {}, "conf": r["confidence"], "conflict": r["status"] == "conflict",
               "unknown": r["status"] == "unknown", "stale": r["status"] == "stale", "summary": r.get("summary"),
               "hotel": gd.load().hotel_by_id[hotel_id]}
        try:
            if not evaluate(q.get("when", "conf < 0.6"), env):
                continue
            text = evaluate(q["text"], env)
        except ExprError:
            continue
        weight = city.weight(cid, spec.get("weight", 0.5)) + 0.1 * popular.get(cid, 0)  # вес в профиле города
        voi = (1 - r["confidence"]) * weight * (1.3 if r["status"] == "conflict" else 1.0)
        reason = ("источники спорят" if r["status"] == "conflict" else "данных нет" if r["status"] == "unknown"
                  else "данные устарели" if r["status"] == "stale" else f"уверенность {r['confidence']:.2f}".replace(".", ","))
        from app.search import ru_text  # search импортирует registry: импорт внутри функции
        text, reason = ru_text(text), ru_text(reason)
        cands.append((voi, cid, text, reason))
    cands.sort(key=lambda t: -t[0])
    made = []
    for voi, cid, text, reason in cands[:budget]:
        qid = store.add_question(hotel_id, cid, text, reason, voi)
        if qid:
            made.append({"id": qid, "char_id": cid, "text": text, "reason": reason, "voi": round(voi, 3)})
    return made


def describe_for_llm(session=None):
    lines = []
    for cid, s in public_chars(session).items():
        fs = "; ".join(f"{k} ({v['type']}{', ' + v['label'] if v.get('label') else ''}"
                       f"{', значения: ' + '|'.join(v['values']) if v.get('values') else ''}"
                       f"{', по месяцам' if v.get('per_month') else ''})" for k, v in s["fields"].items())
        lines.append(f"- {cid}: {s['name']}. {s['description'].strip().splitlines()[0]} Поля: {fs}")
    return "\n".join(lines)


def to_json(spec):
    return json.loads(json.dumps({k: v for k, v in spec.items() if not k.startswith("_") and k != "requested_by"},
                                 ensure_ascii=False, default=str))
