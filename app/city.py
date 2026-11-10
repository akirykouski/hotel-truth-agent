"""Профиль города: что важно гостям именно в этом регионе и с каким весом.

Шаг 1 масштабирования. Для каждой характеристики реестра вес 0..1 считается кодом по данным региона:
- текст (половина веса): у какой доли отзывов тема звучит в плюсах или минусах и у какой доли отелей — в описании
  и названиях номеров (слова темы city_terms из YAML, иначе ключевые слова запроса);
- разброс (30%): насколько по ней различаются отели здесь (энтропия главного поля × доля отелей, где оно известно).
  Если поле нигде не известно или признак не встречается ни у одного отеля (море в городе без моря), вес 0 и пометка
  «неприменимо»;
- спрос (20%): сколько запросов гостей уже было с этой характеристикой.
Админ правит вес руками или выключает характеристику для города; ручной вес главнее авто, «сбросить» возвращает авто.
Вес масштабирует вклад условия в порядок выдачи внутри корзины и ценность вопроса отельеру.

Запросы, которых реестр не покрывает (parsed.missing), копятся здесь же как параметры-кандидаты со счётчиком спроса.
Близкие формулировки склеиваются по основам слов («паркет» и «паркет в номере»). Следующий запрос с теми же словами
попадает в тот же кандидат и получает пометку «уже просили N раз», даже если разбор его не заметил. С порога
(THRESHOLD запросов) кандидат помечается «пора добавлять»; админ собирает из него характеристику (тот же компилятор,
что «Свой критерий»), одобряет черновик, и характеристика входит в профиль города и в поиск.

Хранится в рабочей базе фактов активного региона (таблица city_params), поэтому у каждого города свой профиль.
"""
import json
import math
import re
import time
from functools import lru_cache

from app import geodata as gd
from app import region, registry, store

THRESHOLD = 3
MIX = {"text": 0.5, "spread": 0.3, "demand": 0.2}
STATUSES = ("active", "off")

SCHEMA = """
CREATE TABLE IF NOT EXISTS city_params (
  id TEXT PRIMARY KEY, kind TEXT, name TEXT, phrase TEXT, proposal TEXT, status TEXT DEFAULT 'active',
  auto_weight REAL, manual_weight REAL, signals TEXT, demand INTEGER DEFAULT 0, char_id TEXT, job_id TEXT,
  examples TEXT, note TEXT, created_at TEXT, updated_at TEXT, last_asked TEXT);
"""
_STOP = {"в", "во", "на", "с", "со", "и", "или", "а", "но", "не", "что", "чтобы", "был", "была", "было", "были", "быть",
         "хочу", "хотим", "нужно", "нужен", "нужна", "надо", "есть", "чтоб", "для", "от", "до", "по", "под", "при", "без",
         "это", "как", "так", "мне", "нам", "нас", "меня", "очень", "бы", "же", "ли", "там", "тут", "где", "когда"}
_GENERIC = {"номер", "отел", "гости", "комна", "рядом", "хорош", "место", "чтобы", "можн"}


def conn():
    c = store.conn()
    c.executescript(SCHEMA)
    return c


# ---------- тексты региона ----------

@lru_cache(maxsize=1)
def _texts():
    """(карточки по отелям, отзывы) в нижнем регистре: описание + названия номеров; плюсы + минусы.
    Списки удобств не берём: это одинаковый у всех каталог, а не то, чем отель себя продаёт."""
    cards, reviews = [], []
    for h in gd.load().hotels:
        rooms = " ".join(r.get("name", "") for r in h.get("rooms") or [])
        cards.append(((h.get("description") or "") + " " + rooms).lower())
        for r in h.get("reviews") or []:
            reviews.append(((r.get("plus") or "") + " " + (r.get("minus") or "")).lower())
    return cards, reviews


def _matcher(spec):
    """Слова темы: city_terms из YAML (регулярки), иначе ключевые слова и фразы запроса."""
    pats = []
    for p in spec.get("city_terms") or list(spec.get("phrases") or {}):
        try:
            re.compile(p)
            pats.append(p)
        except re.error:
            pass
    if not spec.get("city_terms"):
        pats += [re.escape(k.lower()) for k in spec.get("keywords") or [] if k]
    return re.compile("|".join(f"(?:{p})" for p in pats)) if pats else None


def _signals(cid, spec, demand):
    from app import draft_eval  # draft_eval импортирует search, тот импортирует этот модуль
    rx = _matcher(spec)
    cards, reviews = _texts()
    card_share = sum(1 for t in cards if rx.search(t)) / len(cards) if rx and cards else 0.0
    review_share = sum(1 for t in reviews if rx.search(t)) / len(reviews) if rx and reviews else 0.0
    values, known = [], 0
    for h in gd.load().hotels:
        r = store.resolve(h["id"], spec)
        if r["status"] == "unknown":
            continue
        known += 1
        v = draft_eval._truth(spec, r)
        v = draft_eval._key_value(spec, r) if v is None else v
        if v is not None:
            values.append(v)
    n = len(gd.load().hotels) or 1
    dist = draft_eval._distribution(spec, values)
    present = not (dist["kind"] == "bool" and dist.get("true", 0) == 0) and bool(values)
    return {"card_share": round(card_share, 3), "review_share": round(review_share, 4),
            "known_share": round(known / n, 3), "entropy": dist.get("entropy", 0.0), "kind": dist["kind"],
            "true_share": round(dist["true"] / dist["n"], 3) if dist["kind"] == "bool" and dist["n"] else None,
            "applicable": present, "reason": None if present else ("no_data" if not known else "absent"), "demand": demand}


def _text(sig):
    """Текстовый сигнал. Отзывы весомее: там гости сами говорят, зачем ехали; доля отзывов ×4, не больше 1
    (самая частая тема в отзывах Сочи, море, звучит в 17% отзывов). Карточка показывает, чем отели себя продают."""
    return 0.3 * sig["card_share"] + 0.7 * min(1.0, sig["review_share"] * 4)


def _mix(sig, top_text, top_demand):
    """Авто-вес из сигналов; текст и спрос нормируются на максимум по городу."""
    if not sig["applicable"]:
        sig["parts"] = {k: 0.0 for k in MIX}
        return 0.0
    parts = {"text": _text(sig) / top_text if top_text else 0.0,
             "spread": sig["entropy"] * sig["known_share"],
             "demand": math.log1p(sig["demand"]) / math.log1p(top_demand) if top_demand else 0.0}
    sig["parts"] = {k: round(v, 2) for k, v in parts.items()}
    return round(sum(MIX[k] * parts[k] for k in MIX), 2)


def _demand():
    """Спрос по характеристикам: распознанные условия в журнале запросов плюс спрос привязанных кандидатов."""
    cnt = dict(store.query_counts())
    for r in conn().execute("SELECT char_id, demand FROM city_params WHERE kind='request' AND char_id IS NOT NULL"):
        cnt[r["char_id"]] = cnt.get(r["char_id"], 0) + (r["demand"] or 0)
    return cnt


def recompute(only_missing=False):
    """Пересчитать авто-веса характеристик города. only_missing: только если у какой-то характеристики строки нет.
    Ручные веса и выключенные характеристики пересчёт не трогает."""
    c = conn()
    chars = registry.public_chars()
    have = {r["id"] for r in c.execute("SELECT id FROM city_params WHERE kind='char'")}
    if only_missing and set(chars) <= have:
        return 0
    dem = _demand()
    sigs = {cid: _signals(cid, s, dem.get(cid, 0)) for cid, s in chars.items()}
    top_text = max((_text(s) for s in sigs.values() if s["applicable"]), default=0)
    top_dem = max((s["demand"] for s in sigs.values()), default=0)
    now = store.now()
    for cid, s in sigs.items():
        w = _mix(s, top_text, top_dem)
        c.execute("INSERT INTO city_params(id, kind, name, status, auto_weight, signals, created_at, updated_at)"
                  " VALUES (?, 'char', ?, 'active', ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET"
                  " name=excluded.name, auto_weight=excluded.auto_weight, signals=excluded.signals, updated_at=excluded.updated_at",
                  (cid, chars[cid]["name"], w, json.dumps(s, ensure_ascii=False), now, now))
    c.commit()
    _W["at"] = 0
    store.log_event("city_profile", payload={"chars": len(sigs), "region": region.META["label"]})
    return len(sigs)


def ensure():
    """Профиль заполняется сам: при первом обращении поднимаем историю запросов в кандидаты и считаем веса всех
    характеристик (около 2 секунд); дальше досчитываются только новые характеристики."""
    c = conn()
    if c.execute("INSERT OR IGNORE INTO city_params(id, kind, created_at) VALUES ('meta:history', 'meta', ?)",
                 (store.now(),)).rowcount:  # история поднимается один раз, даже если ensure зовут два потока
        for r in c.execute("SELECT at, text, missing FROM queries ORDER BY id").fetchall():
            note_missing(r["text"], json.loads(r["missing"] or "[]"), at=r["at"], _history=True)
        c.commit()
    recompute(only_missing=True)


# ---------- веса для поиска и вопросов ----------

_W = {"at": 0.0, "w": {}}


def weights():
    """{char_id: действующий вес}; выключенные для города — 0. Кэш на 5 секунд, запись сбрасывает его."""
    if time.monotonic() - _W["at"] > 5:
        try:
            rows = conn().execute("SELECT id, status, auto_weight, manual_weight FROM city_params WHERE kind='char'").fetchall()
        except Exception:
            rows = []
        _W["w"] = {r["id"]: 0.0 if r["status"] == "off" else
                   (r["manual_weight"] if r["manual_weight"] is not None else r["auto_weight"] or 0.0) for r in rows}
        _W["at"] = time.monotonic()
    return _W["w"]


def weight(char_id, default=None):
    return weights().get(char_id, default)


def set_char(char_id, weight=None, reset=False, status=None):
    c = conn()
    row = c.execute("SELECT * FROM city_params WHERE id=? AND kind='char'", (char_id,)).fetchone()
    if row is None:
        raise KeyError(char_id)
    if status is not None and status not in STATUSES:
        raise ValueError("status: active или off")
    mw = None if reset else (row["manual_weight"] if weight is None else round(min(1.0, max(0.0, float(weight))), 2))
    c.execute("UPDATE city_params SET manual_weight=?, status=?, updated_at=? WHERE id=?",
              (mw, status or row["status"], store.now(), char_id))
    c.commit()
    _W["at"] = 0
    store.log_event("city_weight", char_id=char_id, payload={"weight": mw, "auto": row["auto_weight"], "status": status or row["status"]})
    return _row(c.execute("SELECT * FROM city_params WHERE id=?", (char_id,)).fetchone())


# ---------- параметры, которых нет в реестре ----------

def stems(text):
    words = re.findall(r"[а-яёa-z0-9]+", str(text).lower().replace("ё", "е"))
    return {w[:5] for w in words if len(w) >= 3 and w not in _STOP and w[:5] not in _GENERIC}


def _find(st):
    if not st:
        return None
    best = None
    for r in conn().execute("SELECT * FROM city_params WHERE kind='request'"):
        s = set(json.loads(r["signals"] or "{}").get("stems", []))
        if s and (s <= st or st <= s) and (best is None or (r["demand"] or 0) > (best["demand"] or 0)):
            best = r
    return best


def note_missing(text, missing, at=None, _history=False, covered=None):
    """Учесть запрос: каждый пункт missing — в кандидата города (новый или существующий, +1 к спросу за запрос).
    Кандидаты, чьи слова есть в запросе, тоже получают +1 и добавляются в missing. Возвращает missing с пометками.
    covered — фразы запроса, которые уже разобраны в условия реестра: их слова кандидатов не будят («у моря» не вернёт «Без моря»)."""
    if not _history:
        ensure()
    c, at = conn(), at or store.now()
    out, seen = [], set()
    items = [m for m in missing or [] if isinstance(m, dict) and m.get("phrase")]
    qst = stems(text)
    for ph in covered or []:
        qst -= stems(ph)
    for r in c.execute("SELECT * FROM city_params WHERE kind='request' AND status!='off'").fetchall():
        s = set(json.loads(r["signals"] or "{}").get("stems", []))
        live = r["char_id"] and registry.get(r["char_id"]) and registry.status(registry.get(r["char_id"])) == "approved"
        if s and s <= qst and not live and not any(stems(m["phrase"]) & s for m in items):
            items.append({"phrase": r["phrase"], "proposal": r["proposal"] or r["phrase"]})
    for m in items:
        st = stems(m["phrase"]) or stems(m.get("proposal", ""))
        if not st:
            out.append(m)
            continue
        r = _find(st)
        if r is not None and r["id"] in seen:
            out.append({**m, "city": {"id": r["id"], "demand": r["demand"], "status": _req_status(r)}})
            continue
        if r is None:
            rid = "q:" + " ".join(sorted(st))
            c.execute("INSERT OR IGNORE INTO city_params(id, kind, name, phrase, proposal, status, demand, signals, examples,"
                      " created_at, updated_at, last_asked) VALUES (?, 'request', ?, ?, ?, 'active', 0, ?, '[]', ?, ?, ?)",
                      (rid, m["phrase"], m["phrase"], m.get("proposal") or m["phrase"],
                       json.dumps({"stems": sorted(st)}, ensure_ascii=False), at, at, at))
            r = c.execute("SELECT * FROM city_params WHERE id=?", (rid,)).fetchone()
        ex = json.loads(r["examples"] or "[]")
        if text and text not in ex:
            ex = (ex + [text])[-3:]
        c.execute("UPDATE city_params SET demand=demand+1, examples=?, last_asked=?, updated_at=? WHERE id=?",
                  (json.dumps(ex, ensure_ascii=False), at, at, r["id"]))
        seen.add(r["id"])
        r = c.execute("SELECT * FROM city_params WHERE id=?", (r["id"],)).fetchone()
        out.append({**m, "city": {"id": r["id"], "demand": r["demand"], "status": _req_status(r)}})
    c.commit()
    return out


def add_request(phrase, proposal=None):
    """Админ добавляет параметр городу сам, без запросов гостей (спрос 0)."""
    st = stems(phrase)
    if not st:
        raise ValueError("нужны слова: что именно важно гостям")
    r = _find(st)
    if r is None:
        rid, now = "q:" + " ".join(sorted(st)), store.now()
        conn().execute("INSERT INTO city_params(id, kind, name, phrase, proposal, status, demand, signals, examples,"
                       " created_at, updated_at) VALUES (?, 'request', ?, ?, ?, 'active', 0, ?, '[]', ?, ?)",
                       (rid, phrase, phrase, proposal or phrase, json.dumps({"stems": sorted(st)}, ensure_ascii=False), now, now))
        conn().commit()
        r = conn().execute("SELECT * FROM city_params WHERE id=?", (rid,)).fetchone()
    return _row(r)


def _req_status(r):
    if r["status"] == "off":
        return "off"
    spec = registry.get(r["char_id"]) if r["char_id"] else None
    if spec is not None:
        return {"approved": "live", "draft": "draft"}.get(registry.status(spec), "rejected")
    if r["job_id"]:
        return "building"
    return "ready" if (r["demand"] or 0) >= THRESHOLD else "candidate"


def _sync_jobs():
    """Связать кандидатов с результатом сборки: задачи компилятора живут в памяти процесса."""
    from app import compiler
    c = conn()
    for r in c.execute("SELECT id, job_id FROM city_params WHERE kind='request' AND job_id IS NOT NULL").fetchall():
        job = compiler.JOBS.get(r["job_id"])
        if job is None or job["status"] != "running":
            ok = job is not None and job["status"] == "done" and job.get("char_id")
            note = None if ok else (job["steps"][-1]["msg"] if job and job.get("steps") else "сборка прервана")
            c.execute("UPDATE city_params SET job_id=NULL, char_id=COALESCE(?, char_id), note=? WHERE id=?",
                      (job.get("char_id") if ok else None, note, r["id"]))
    c.commit()


def _link_covered():
    """Кандидат, которого реестр уже понимает (характеристику добавили позже запроса), привязать к ней: спрос уходит
    в её вес, а кандидат получает статус «в поиске»."""
    from app import search  # search импортирует этот модуль
    c = conn()
    for r in c.execute("SELECT id, phrase FROM city_params WHERE kind='request' AND char_id IS NULL AND job_id IS NULL").fetchall():
        p = search.parse_rules(r["phrase"])
        if p["constraints"] and not p["missing"]:
            c.execute("UPDATE city_params SET char_id=? WHERE id=?", (p["constraints"][0]["char"], r["id"]))
    c.commit()


def build_request(rid):
    from app import compiler
    r = conn().execute("SELECT * FROM city_params WHERE id=? AND kind='request'", (rid,)).fetchone()
    if r is None:
        raise KeyError(rid)
    job = compiler.build_async(r["proposal"] or r["phrase"])
    conn().execute("UPDATE city_params SET job_id=?, note=NULL, status='active', updated_at=? WHERE id=?", (job, store.now(), rid))
    conn().commit()
    return job


def set_request(rid, status):
    if status not in STATUSES:
        raise ValueError("status: active или off")
    conn().execute("UPDATE city_params SET status=?, updated_at=? WHERE id=? AND kind='request'", (status, store.now(), rid))
    conn().commit()


# ---------- выдача для админки ----------

def _row(r):
    d = dict(r)
    d["signals"] = json.loads(d["signals"] or "{}")
    d["examples"] = json.loads(d.get("examples") or "[]")
    if d["kind"] == "char":
        d["weight"] = 0.0 if d["status"] == "off" else (d["manual_weight"] if d["manual_weight"] is not None else d["auto_weight"])
    return d


def profile():
    ensure()
    _sync_jobs()
    _link_covered()
    chars = registry.public_chars()
    rows = [_row(r) for r in conn().execute("SELECT * FROM city_params ORDER BY id")]
    out_c = [r | {"description": chars[r["id"]]["description"].strip().splitlines()[0], "custom": chars[r["id"]].get("origin") is not None}
             for r in rows if r["kind"] == "char" and r["id"] in chars]
    out_c.sort(key=lambda r: (-(r["weight"] or 0), r["name"]))
    reqs = []
    for r in rows:
        if r["kind"] != "request":
            continue
        st = _req_status(r)
        spec = registry.get(r["char_id"]) if r["char_id"] else None
        reqs.append(r | {"state": st, "char_name": spec["name"] if spec else None})
    order = {"ready": 0, "building": 1, "draft": 2, "candidate": 3, "live": 4, "rejected": 5, "off": 6}
    reqs.sort(key=lambda r: (order.get(r["state"], 9), -(r["demand"] or 0)))
    last = conn().execute("SELECT MAX(updated_at) FROM city_params WHERE kind='char'").fetchone()[0]
    return {"region": region.NAME or "default", "label": region.META["label"], "label_in": region.META["label_in"],
            "hotels": len(gd.load().hotels), "queries": conn().execute("SELECT COUNT(*) FROM queries").fetchone()[0],
            "threshold": THRESHOLD, "mix": MIX, "computed_at": last, "chars": out_c, "requests": reqs}
