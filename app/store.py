"""Хранилище фактов (SQLite) и разбор противоречий между источниками.

Факт = (отель, характеристика, источник, область) → значение + уверенность + дата + срок годности + улики.
Одна и та же характеристика может иметь факты из нескольких источников: расчёт, карточка, отзывы, отельер.
Итоговое значение выбирает резолвер: для булевых ключей апостериор по надёжности источников (app/truth.py),
для остальных вес источника × уверенность × свежесть. Противоречия показываются явно, а не прячутся.
"""
import json
import os
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import region, truth

SEED_PATH = region.DATA / "facts.sqlite"   # предрасчёт, лежит в репозитории (у региона: data/regions/<REGION>/)
# Рабочая копия: ответы отельеров, новые характеристики и запросы пишутся сюда, а не в репозиторий.
# Удалите data/cache/facts.runtime.sqlite, чтобы вернуться к исходному состоянию демо.
DB_PATH = Path(os.getenv("FACTS_DB") or SEED_PATH.parent / "cache" / "facts.runtime.sqlite")
SOURCE_WEIGHT = {"hotelier": 1.0, "geo": 0.9, "open-meteo": 0.9, "osm": 0.85, "card": 0.75, "photos": 0.7, "reviews": 0.6}
SOURCE_LABEL = {"hotelier": "ответ отельера", "geo": "расчёт по геоданным", "open-meteo": "Open-Meteo",
                "osm": "OpenStreetMap", "card": "карточка Островка", "photos": "фото отеля", "reviews": "отзывы гостей"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY, hotel_id TEXT, char_id TEXT, source TEXT, scope TEXT DEFAULT 'отель',
  value TEXT, summary TEXT, confidence REAL, method TEXT, observed_at TEXT, valid_until TEXT,
  evidence TEXT, recipe_version TEXT, active INTEGER DEFAULT 1, superseded_by INTEGER);
CREATE INDEX IF NOT EXISTS facts_hc ON facts(hotel_id, char_id, active);
CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY, hotel_id TEXT, char_id TEXT, text TEXT, reason TEXT, voi REAL, status TEXT,
  created_at TEXT, answered_at TEXT, answer TEXT, parsed TEXT);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, at TEXT, kind TEXT, hotel_id TEXT, char_id TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS queries (
  id INTEGER PRIMARY KEY, at TEXT, text TEXT, parsed TEXT, missing TEXT);
CREATE TABLE IF NOT EXISTS parse_cache (
  key TEXT PRIMARY KEY, at TEXT, text TEXT, parsed TEXT);
"""

_local = threading.local()

SCALE_KIND = "источники говорят о разном масштабе"   # уточнение, а не спор: карточка и расчёт отвечают на вопросы разного размера


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def conn(path=None):
    c = getattr(_local, "conn", None)
    if c is None or path:
        target = Path(path or DB_PATH)
        if not target.exists() and target != SEED_PATH and SEED_PATH.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")   # app и mcp стартуют вместе: копия атомарна
            shutil.copy(SEED_PATH, tmp)
            os.replace(tmp, target)
        c = sqlite3.connect(target, check_same_thread=False, timeout=10)
        c.row_factory = sqlite3.Row
        try:   # WAL: читатели из другого процесса (mcp) не блокируют запись ответа отельера
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=10000")
        except sqlite3.OperationalError:
            pass
        c.executescript(SCHEMA)
        _local.conn = c
    return c


def put_fact(hotel_id, char_id, source, value, confidence, summary, method, ttl_days, evidence=None,
             scope="отель", recipe_version="1", observed_at=None):
    c = conn()
    observed_at = observed_at or now()
    valid_until = (datetime.fromisoformat(observed_at) + timedelta(days=ttl_days)).isoformat() if ttl_days else None
    old = c.execute("SELECT id FROM facts WHERE hotel_id=? AND char_id=? AND source=? AND scope=? AND active=1",
                    (hotel_id, char_id, source, scope)).fetchall()
    cur = c.execute(
        "INSERT INTO facts(hotel_id, char_id, source, scope, value, summary, confidence, method, observed_at, valid_until,"
        " evidence, recipe_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (hotel_id, char_id, source, scope, json.dumps(value, ensure_ascii=False), summary,
         None if confidence is None else round(float(confidence), 3), method, observed_at, valid_until,
         json.dumps(evidence or {}, ensure_ascii=False, default=str), recipe_version))
    for r in old:
        c.execute("UPDATE facts SET active=0, superseded_by=? WHERE id=?", (cur.lastrowid, r["id"]))
    c.commit()
    return cur.lastrowid


def facts(hotel_id, char_id=None, active=True):
    q = "SELECT * FROM facts WHERE hotel_id=?" + (" AND char_id=?" if char_id else "") + (" AND active=1" if active else "")
    rows = conn().execute(q + " ORDER BY id", (hotel_id, char_id) if char_id else (hotel_id,)).fetchall()
    return [_row(r) for r in rows]


def _row(r):
    d = dict(r)
    d["value"] = json.loads(d["value"]) if d["value"] else None
    d["evidence"] = json.loads(d["evidence"]) if d["evidence"] else {}
    d["source_label"] = SOURCE_LABEL.get(d["source"], d["source"])
    return d


def history(hotel_id, char_id):
    return facts(hotel_id, char_id, active=False)


def log_event(kind, hotel_id=None, char_id=None, payload=None):
    conn().execute("INSERT INTO events(at, kind, hotel_id, char_id, payload) VALUES (?,?,?,?,?)",
                   (now(), kind, hotel_id, char_id, json.dumps(payload or {}, ensure_ascii=False, default=str)))
    conn().commit()


def events(limit=50, hotel_id=None):
    q = "SELECT * FROM events" + (" WHERE hotel_id=?" if hotel_id else "") + " ORDER BY id DESC LIMIT ?"
    rows = conn().execute(q, (hotel_id, limit) if hotel_id else (limit,)).fetchall()
    return [dict(r) | {"payload": json.loads(r["payload"])} for r in rows]


# ---------- резолвер ----------

def _fresh(f):
    if not f["valid_until"]:
        return 1.0, False
    stale = datetime.fromisoformat(f["valid_until"]) < datetime.now(timezone.utc)
    return (0.5, True) if stale else (1.0, False)


def _conflict_kind(a, b, cls=None):
    s = {a["source"], b["source"]}
    if "hotelier" in s and cls == "physical" and s & set(truth.COMPUTED):
        return "заявление отельера против расчёта"
    if "hotelier" in s and "reviews" in s:
        return "отельер против отзывов"
    if "geo" in s and ("card" in s or "hotelier" in s):
        return "расчёт против заявления"
    if "hotelier" in s and "card" in s:
        return "отельер против карточки"
    return "источник против источника"


def _differs(v, bv):
    """Числа в пределах 25% считаются совпадением, остальное сравнивается как есть."""
    if isinstance(v, (int, float)) and isinstance(bv, (int, float)) and not isinstance(v, bool) and not isinstance(bv, bool):
        return abs(v - bv) > 0.25 * max(abs(v), abs(bv), 1e-9)
    return v != bv


def _n(x):
    return f"{x:.2f}".replace(".", ",")


def _why(cls, post, win_val, rep, rep_mult):
    """Одной фразой: кому поверили и почему."""
    sup = [v for v in post["votes"] if v["vote"] == win_val]
    top = max(sup, key=lambda v: v["contrib"] * (1 if win_val else -1), default=None)
    if top is None:
        return "ни один источник не набрал веса: значение выбрано по совокупности"
    label = SOURCE_LABEL.get(top["source"], top["source"])
    kind = {"physical": "это измеряется", "policy": "это решает отель", "experiential": "это мнение гостей"}[cls]
    txt = f"{kind}: больше веса у источника «{label}» (надёжность {_n(top['reliability'])})"
    if rep["checks"] and rep["trust"] < 1:
        txt += f"; доверие к отельеру {_n(rep['trust'])} ({rep['label']})"
    return txt


def _resolve_bool(hotel_id, char, fs, cls, key):
    """Булевый ключ: апостериор по надёжности источников (app/truth.py) вместо «побеждает самый весомый»."""
    rep, rep_mult = {"checks": 0, "trust": 1.0, "label": ""}, 1.0
    if any(f["source"] == "hotelier" for f in fs):
        rep = truth.hotelier_reputation(hotel_id)
        rep_mult = truth.rep_multiplier(cls, rep["trust"])
    for f in fs:
        f["stale"] = _fresh(f)[1]
    post = truth.posterior(char, fs, rep_mult)
    if post is None:
        return None
    val, conf = truth.decide(post)
    # значение-победитель: факт, который голосовал за него, с наибольшим вкладом
    sup = sorted((v for v in post["votes"] if v["vote"] == val), key=lambda v: -abs(v["contrib"]))
    best = sup[0]["fact"] if sup else max((v["fact"] for v in post["votes"]), key=lambda f: f["confidence"] or 0)
    value = dict(best["value"] or {})
    value[key] = val
    why = _why(cls, post, val, rep, rep_mult)
    conflicts = []
    for v in post["votes"] if sup else []:   # без поддержки значения спорить не с чем: см. summary ниже
        f = v["fact"]
        if v["vote"] == val or (f["confidence"] or 0) < 0.4:
            continue
        conflicts.append({"kind": _conflict_kind(best, f, cls), "winner": best["source_label"],
                          "other": f["source_label"], "winner_says": best["summary"], "other_says": f["summary"],
                          "trusted": best["source_label"], "why": why})
    if sup and best["source"] == "geo":   # «стороны с видом есть, но с N-го этажа» — уточнение, не спор
        for v in post["votes"]:
            f = v["fact"]
            if v["vote"] == val and f["source"] == "card" and (best["value"] or {}).get("from_floor", 1) > 1:
                conflicts.append({"kind": SCALE_KIND, "winner": best["source_label"], "other": f["source_label"],
                                  "winner_says": best["summary"], "other_says": f["summary"]})
    real = [c for c in conflicts if c["kind"] != SCALE_KIND]
    stale = bool(best.get("stale"))
    if sup:
        summary = best["summary"]
    else:   # все источники говорят обратное, но им мы верим слабо: значение по априору, уверенность ниже 0.5
        conf = min(conf, 0.49)
        summary = (f"не подтверждено: «{best['source_label']}» утверждает {'да' if not val else 'нет'}, но этому источнику "
                   f"мы верим слабо (надёжность {_n(post['votes'][0]['reliability'])}); по большинству отелей скорее {'да' if val else 'нет'}")
    return {"status": "conflict" if real else ("stale" if stale else "known"),
            "value": value, "summary": summary, "source": best["source"] if sup else post["votes"][0]["source"],
            "source_label": best["source_label"] if sup else "совокупность источников", "confidence": conf,
            "observed_at": best["observed_at"], "valid_until": best["valid_until"],
            "facts": [v["fact"] for v in sorted(post["votes"], key=lambda v: -abs(v["contrib"]))] + [f for f in fs if f not in [v["fact"] for v in post["votes"]]],
            "conflicts": conflicts, "class": cls,
            "trust": {"p_true": round(post["p"], 3), "why": why, "class": cls,
                      "votes": [{k: v[k] for k in ("source", "vote", "w", "contrib", "reliability")} for v in post["votes"]],
                      "hotelier": rep if rep["checks"] else None}}


def resolve(hotel_id, char, fs=None):
    """Итог по характеристике: значение, уверенность, откуда, противоречия. char — описание из реестра.
    Булевы ключи решает движок правды (надёжность источников по классу характеристики), остальные — вес × уверенность."""
    fs = fs if fs is not None else facts(hotel_id, char["id"])
    if not fs:
        return {"status": "unknown", "value": None, "confidence": 0.0, "facts": [], "conflicts": []}
    key, cls = char.get("key"), truth.char_class(char)
    if truth.is_bool_key(char):
        r = _resolve_bool(hotel_id, char, fs, cls, key)
        if r:
            return r
    scored = []
    for f in fs:
        w, stale = _fresh(f)
        f["stale"] = stale
        scored.append((truth.class_weight(cls, f["source"]) * (f["confidence"] or 0) * w, f))
    scored.sort(key=lambda t: -t[0])
    best = scored[0][1]
    conflicts = []
    if key:
        bv = (best["value"] or {}).get(key)
        for _, f in scored[1:]:
            v = (f["value"] or {}).get(key)
            if v is None or bv is None or (f["confidence"] or 0) < 0.4 or (best["confidence"] or 0) < 0.4:
                continue
            if _differs(v, bv):
                conflicts.append({"kind": _conflict_kind(best, f, cls), "winner": best["source_label"],
                                  "other": f["source_label"], "winner_says": best["summary"], "other_says": f["summary"],
                                  "trusted": best["source_label"],
                                  "why": f"{cls}: вес источника «{best['source_label']}» выше"})
            elif best["source"] == "geo" and f["source"] == "card" and (best["value"] or {}).get("from_floor", 1) > 1:
                conflicts.append({"kind": SCALE_KIND, "winner": best["source_label"],
                                  "other": f["source_label"], "winner_says": best["summary"], "other_says": f["summary"]})
    real = [c for c in conflicts if c["kind"] != SCALE_KIND]
    conf = (best["confidence"] or 0) * (0.6 if real else 1.0) * (0.7 if best.get("stale") else 1.0)
    return {"status": "conflict" if real else ("stale" if best.get("stale") else "known"),
            "value": best["value"], "summary": best["summary"], "source": best["source"],
            "source_label": best["source_label"], "confidence": round(conf, 2), "observed_at": best["observed_at"],
            "valid_until": best["valid_until"], "facts": [f for _, f in scored], "conflicts": conflicts, "class": cls}


# ---------- вопросы отельеру ----------

def add_question(hotel_id, char_id, text, reason, voi):
    c = conn()
    if c.execute("SELECT 1 FROM questions WHERE hotel_id=? AND char_id=? AND status='open'", (hotel_id, char_id)).fetchone():
        return None
    cur = c.execute("INSERT INTO questions(hotel_id, char_id, text, reason, voi, status, created_at) VALUES (?,?,?,?,?,?,?)",
                    (hotel_id, char_id, text, reason, round(voi, 3), "open", now()))
    c.commit()
    return cur.lastrowid


def questions(hotel_id=None, status=None):
    q, args = "SELECT * FROM questions WHERE 1=1", []
    if hotel_id:
        q += " AND hotel_id=?"
        args.append(hotel_id)
    if status:
        q += " AND status=?"
        args.append(status)
    rows = conn().execute(q + " ORDER BY voi DESC, id", args).fetchall()
    return [dict(r) | {"parsed": json.loads(r["parsed"]) if r["parsed"] else None} for r in rows]


def answer_question(qid, answer, parsed):
    c = conn()
    c.execute("UPDATE questions SET status='answered', answered_at=?, answer=?, parsed=? WHERE id=?",
              (now(), answer, json.dumps(parsed, ensure_ascii=False), qid))
    c.commit()


def stage_answer(qid, answer, parsed):
    """Ответ ждёт подтверждения эха: вопрос остаётся открытым, ответ и разбор лежат в нём (None — сбросить)."""
    conn().execute("UPDATE questions SET answer=?, parsed=? WHERE id=? AND status='open'",
                   (answer, None if parsed is None else json.dumps(parsed, ensure_ascii=False), qid))
    conn().commit()


def log_query(text, parsed, missing):
    conn().execute("INSERT INTO queries(at, text, parsed, missing) VALUES (?,?,?,?)",
                   (now(), text, json.dumps(parsed, ensure_ascii=False), json.dumps(missing, ensure_ascii=False)))
    conn().commit()


def parse_cache_get(key):
    """Готовый разбор запроса LLM по ключу или None. Общий для процесса чата и MCP-сервера (один файл базы)."""
    r = conn().execute("SELECT parsed FROM parse_cache WHERE key=?", (key,)).fetchone()
    return json.loads(r["parsed"]) if r else None


def parse_cache_put(key, text, parsed):
    conn().execute("INSERT OR REPLACE INTO parse_cache(key, at, text, parsed) VALUES (?,?,?,?)",
                   (key, now(), text, json.dumps(parsed, ensure_ascii=False)))
    conn().commit()


def query_counts():
    rows = conn().execute("SELECT parsed FROM queries").fetchall()
    cnt = {}
    for r in rows:
        for c in (json.loads(r["parsed"]) or {}).get("constraints", []):
            cnt[c.get("char")] = cnt.get(c.get("char"), 0) + 1
    return cnt
