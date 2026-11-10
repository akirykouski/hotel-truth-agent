"""Новая характеристика по описанию словами.

LLM получает каталог инструментов и пишет рецепт: какие инструменты вызвать с какими аргументами и как
посчитать значение, уверенность и фразу. Рецепт проверяется схемой, пробно исполняется на 5 отелях
(при ошибке LLM получает её текст и исправляет один раз), сохраняется в registry/custom/ и сразу считается
для всех отелей. Код системы не меняется.

Без ключа LLM работает шаблонный компилятор: словарь частых пожеланий → теги OSM или слова в карточке.

Результат сохраняется черновиком (status: draft): факты считаются, чтобы запросивший получил ответ, но публичный
поиск характеристику не видит, пока админ не одобрит (registry.approve). Вместе с черновиком идёт авто-отчёт
(app/draft_eval.py). Шаги сборки пишутся в журнал и в JOBS: сборка через LLM идёт минуты, и её видно.
"""
import json
import re
import threading
import time
import uuid

from app import geodata as gd
from app import draft_eval, llm, registry, store
from app.tools import catalog

JOBS = {}  # id задачи → {id, text, status: running|done|failed, started, steps: [{t, step, msg}], char_id}
_JOBS_LOCK = threading.Lock()
KEEP_JOBS = 20


def start_job(text, session=None):
    job = {"id": uuid.uuid4().hex[:8], "text": text, "status": "running", "started": time.time(), "steps": [],
           "char_id": None, "_session": session}
    with _JOBS_LOCK:
        JOBS[job["id"]] = job
        for old in sorted(JOBS.values(), key=lambda j: j["started"])[:-KEEP_JOBS]:
            JOBS.pop(old["id"], None)
    return job


def step(job, kind, msg):
    """Шаг сборки: в память для опроса из UI и в журнал событий."""
    if job is None:
        return
    job["steps"].append({"t": round(time.time() - job["started"], 1), "step": kind, "msg": msg})
    store.log_event("compile_step", char_id=job.get("char_id"), payload={"job": job["id"], "step": kind, "msg": msg})


def public_job(job):
    return {k: v for k, v in job.items() if not k.startswith("_")} | {"elapsed_s": round(time.time() - job["started"], 1)}


SPEC_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "name", "description", "level", "keywords", "fields", "key", "default_constraint", "methods",
                 "ttl_days", "question"],
    "properties": {
        "id": {"type": "string", "description": "латиница, snake_case"},
        "name": {"type": "string"}, "description": {"type": "string"}, "level": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "fields": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                              "required": ["name", "type", "label", "better"],
                                              "properties": {"name": {"type": "string"},
                                                             "type": {"type": "string", "enum": ["bool", "number", "text"]},
                                                             "label": {"type": "string"},
                                                             "better": {"type": "string", "enum": ["lower", "higher", "none"]}}}},
        "key": {"type": "string"},
        "default_constraint": {"type": "object", "additionalProperties": False, "required": ["field", "op", "value"],
                               "properties": {"field": {"type": "string"}, "op": {"type": "string", "enum": ["==", "<=", ">="]},
                                              "value": {"type": ["boolean", "number"]}}},
        "ttl_days": {"type": "integer"},
        "question": {"type": "string", "description": "вопрос отельеру, если данных нет; пустая строка — не спрашивать"},
        "methods": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["source", "steps", "value", "confidence", "summary", "when"],
            "properties": {
                "source": {"type": "string", "enum": ["geo", "osm", "card", "reviews"]},
                "steps": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                     "required": ["as", "tool", "args_json"],
                                                     "properties": {"as": {"type": "string"},
                                                                    "tool": {"type": "string", "enum": list(catalog.TOOLS)},
                                                                    "args_json": {"type": "string"}}}},
                "when": {"type": "string", "description": "выражение; пусто — всегда"},
                "value": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                     "required": ["field", "expr"],
                                                     "properties": {"field": {"type": "string"}, "expr": {"type": "string"}}}},
                "confidence": {"type": "string"}, "summary": {"type": "string"}}}},
    },
}

SYSTEM = """Ты пишешь рецепт характеристики отеля для системы, которая считает факты кодом, а не угадывает.
Рецепт вызывает инструменты из каталога и вычисляет значение выражениями (Python-подобные: поля через точку,
and/or/not, сравнения, if-else, f-строки, len/min/max/any/all/round, генераторы списков). Имена шагов (as)
становятся переменными. Если инструмент ничего не нашёл, nearest_m = None.

Правила:
- Выбирай самый прямой источник: объекты вокруг — nearby (теги OSM), маршрут — walk_to, вид/закат — sea_view/sunset,
  шум — noise, удобства отеля — card_search, впечатления гостей — reviews_search. Можно несколько методов
  (например, card и reviews), тогда система сама сравнит их и покажет противоречия.
- Уверенность — число 0..1 или выражение: OSM ~0.7, карточка ~0.7, отзывы 0.3–0.7 по числу упоминаний.
- summary — короткая фраза по-русски с цифрами, f-строкой.
- Отсутствие в карточке — не доказательство отсутствия: в when для card ставь «c.found».
- Поля: одно главное (key) булево или числовое, его же используй в default_constraint.

Каталог инструментов:
{catalog}

Какие теги OSM реально есть в данных зоны (тег — сколько объектов). Бери теги отсюда; для поиска по названию
используй name: "~подстрока":
{inventory}

Пример готового рецепта (YAML):
{example}"""


def _example():
    return (registry.REG_DIR / "kids.yaml").read_text(encoding="utf-8")


def _to_spec(raw):
    spec = {k: raw[k] for k in ("id", "name", "description", "level", "keywords", "key", "default_constraint", "ttl_days")}
    spec["id"] = re.sub(r"[^a-z0-9_]", "_", spec["id"].lower()).strip("_") or "custom"
    spec["fields"] = {f["name"]: {"type": f.get("type", "bool"), "label": f.get("label", f["name"]),
                                  **({"better": f["better"]} if f.get("better") in ("lower", "higher") else {})}
                      for f in raw["fields"]}
    spec["methods"] = []
    for m in raw["methods"]:
        mm = {"source": m["source"], "steps": [{"as": s["as"], "tool": s["tool"], "args": json.loads(s["args_json"] or "{}")}
                                               for s in m["steps"]],
              "value": {v["field"]: v["expr"] for v in m["value"]}, "confidence": m["confidence"], "summary": m["summary"]}
        if m.get("when"):
            mm["when"] = m["when"]
        spec["methods"].append(mm)
    if raw.get("question"):
        spec["question"] = {"when": "unknown", "text": json.dumps(raw["question"], ensure_ascii=False)}
    spec["weight"] = 0.5
    spec["origin"] = "compiled"
    return spec


def _dry_run(spec, n=5):
    registry.validate(spec)
    hotels = [h["id"] for h in gd.load().hotels[:: max(1, len(gd.load().hotels) // n)][:n]]
    samples = []
    for hid in hotels:
        for m in spec["methods"]:
            r = registry.run_method(spec, m, hid)
            if r:
                samples.append({"hotel": gd.load().hotel_by_id[hid]["name"], "source": m["source"], "summary": r["summary"],
                                "confidence": r["confidence"], "key": (r["value"] or {}).get(spec.get("key"))
                                if isinstance(r["value"], dict) else r["value"]})
    return samples


def _degenerate(spec, samples):
    """Рецепт, который на всех пробных отелях дал одно и то же «ничего не найдено», скорее всего ищет не те теги."""
    if not samples:
        return "рецепт не дал ни одного значения на 5 пробных отелях"
    calc = [s for s in samples if s["source"] in ("osm", "geo")]
    if calc and all(not s["key"] for s in calc):
        return ("на всех 5 пробных отелях ничего не найдено: вероятно, в OSM этой зоны объект размечен другими тегами. "
                "Посмотри список реальных тегов и выбери подходящие, например по названию через name: '~...'")
    return None


def compile_llm(text, attempts=3, job=None):
    sysmsg = SYSTEM.format(catalog=catalog.describe(), example=_example(), inventory=catalog.tag_inventory())
    prompt, last_err = f"Новая характеристика: {text}", None
    for k in range(1, attempts + 1):
        step(job, "llm", f"LLM пишет рецепт, попытка {k} из {attempts}")
        raw = llm.json_call(sysmsg, prompt, SPEC_SCHEMA, effort="medium", max_tokens=8000)
        try:
            step(job, "dry_run", f"попытка {k}: пробный расчёт рецепта на 5 отелях")
            spec = _to_spec(raw)
            samples = _dry_run(spec)
            problem = _degenerate(spec, samples)
            if problem:
                raise ValueError(problem)
            return spec, samples, k
        except Exception as e:  # ошибку видит LLM и исправляет рецепт
            last_err = e
            step(job, "retry", f"попытка {k} не прошла: {str(e)[:200]}")
            prompt = (f"Новая характеристика: {text}\n\nПрошлый рецепт:\n{json.dumps(raw, ensure_ascii=False)}\n\n"
                      f"Проблема: {e}. Исправь рецепт.")
    raise ValueError(f"не получилось собрать рабочий рецепт за {attempts} попытки: {last_err}")


# Шаблонный компилятор без LLM: «рядом X» → теги OSM, «в отеле есть X» → слова в карточке.
TEMPLATES = [
    (r"собак|выгул", "dog_walk", "Где гулять с собакой", {"leisure": "dog_park|park"}, 800),
    (r"аквапарк", "water_park", "Аквапарк рядом", {"leisure": "water_park"}, 3000),
    (r"музе", "museum", "Музей рядом", {"tourism": "museum"}, 1500),
    (r"смотров|панорам", "viewpoint", "Смотровая площадка рядом", {"tourism": "viewpoint"}, 1500),
    (r"супермаркет|продукт", "supermarket", "Супермаркет рядом", {"shop": "supermarket|convenience"}, 500),
    (r"остановк|автобус", "bus_stop", "Остановка автобуса рядом", {"highway": "bus_stop"}, 400),
    (r"фитнес|спортзал|тренаж", "gym_near", "Фитнес-клуб рядом", {"leisure": "fitness_centre|sports_centre"}, 1000),
    (r"банкомат", "atm", "Банкомат рядом", {"amenity": "atm|bank"}, 500),
    (r"ресторан|кафе|поесть", "food_near", "Где поесть рядом", {"amenity": "restaurant|cafe"}, 300),
]
CARD_TEMPLATES = [
    (r"бассейн", "pool", "Бассейн в отеле", ["бассейн", "pool"]),
    (r"завтрак", "breakfast", "Завтрак в отеле", ["завтрак", "breakfast"]),
    (r"балкон", "balcony", "Балкон в номере", ["балкон", "balcony", "terrace", "террас"]),
    (r"кухн", "kitchen", "Кухня в номере", ["kitchen", "кухн"]),
    (r"трансфер", "transfer", "Трансфер", ["трансфер", "shuttle"]),
    (r"спа|сауна|хаммам", "spa", "СПА в отеле", ["спа", "spa", "саун", "хаммам"]),
    (r"ванн|джакузи", "bathtub", "Ванна в номере", ["^bath$", "bathtub", "джакуз", "душ/ванна", "с ванной"]),
]

# слова, рядом с которыми совпадение не считается: «полотенца для бассейна» и «бассейн в 500 м» не бассейн в отеле
CARD_EXCLUDE = {"pool": ["полотенц", "рядом с отелем", r"в \d+ ?м\b", r"в \d+ метр", r"\d+ минут\w* (?:ходьбы|пешком)", "towel"]}


def candidates(text):
    """Какие шаблонные характеристики просит запрос: кандидаты в parsed.missing для разбора без LLM."""
    t, out = text.lower(), []
    for rx, cid, name, *_ in TEMPLATES + CARD_TEMPLATES:
        m = re.search(rx, t)
        if m:
            word = re.search(r"\w*" + re.escape(m.group(0)) + r"\w*", t).group(0)
            out.append({"id": cid, "phrase": word, "proposal": name})
    return out


def compile_template(text):
    t = text.lower()
    for rx, cid, name, tags, radius in TEMPLATES:
        if re.search(rx, t):
            return {
                "id": cid, "name": name, "description": f"{text}. Ищем объекты OSM {tags} в {radius} м от отеля.",
                "level": "отель", "weight": 0.5, "ttl_days": 180, "key": "near", "origin": "template",
                "keywords": [w for w in rx.split("|")],
                "default_constraint": {"field": "near", "op": "==", "value": True},
                "fields": {"near": {"type": "bool", "label": f"{name.lower()} в {radius} м"},
                           "nearest_m": {"type": "number", "better": "lower", "label": "до ближайшего, м"}},
                "methods": [{"source": "osm", "steps": [{"as": "n", "tool": "nearby", "args": {"tags": tags, "radius_m": radius}}],
                             "value": {"near": "n.count > 0", "nearest_m": "n.nearest_m"}, "confidence": "0.7",
                             "summary": f"f'{{n.count}} шт. в {radius} м, ближайший в {{n.nearest_m}} м' if n.count else 'в {radius} м нет'",
                             "evidence": "{'items': n.items[:5]}"}]}
    for rx, cid, name, terms in CARD_TEMPLATES:
        if re.search(rx, t):
            ex = {"exclude": CARD_EXCLUDE[cid]} if cid in CARD_EXCLUDE else {}
            return {
                "id": cid, "name": name, "description": f"{text}. Ищем в карточке Островка и отзывах.",
                "level": "отель", "weight": 0.5, "ttl_days": 365, "key": "has", "origin": "template",
                "keywords": [w for w in rx.split("|")],
                "default_constraint": {"field": "has", "op": "==", "value": True},
                "fields": {"has": {"type": "bool", "label": name.lower()}},
                "methods": [{"source": "card", "steps": [{"as": "c", "tool": "card_search", "args": {"terms": terms, **ex}}],
                             "when": "c.found", "value": {"has": "True"}, "confidence": "0.75",
                             "summary": "'в карточке: ' + '; '.join(sorted(set(h.quote[:80] for h in c.hits))[:2])",
                             "evidence": "{'hits': c.hits}"},
                            {"source": "reviews", "steps": [{"as": "r", "tool": "reviews_search", "args": {"terms": terms, **ex}}],
                             "when": "r.positive > 0", "value": {"has": "True"},
                             "confidence": "min(0.6, 0.3 + 0.1 * r.positive)",
                             "summary": "f'упоминают в отзывах {r.positive} раз'",
                             "evidence": "{'quotes': r.positive_quotes}"}],
                "question": {"when": "unknown", "text": f"'Есть ли у вас: {name.lower()}? Если да, на каких условиях?'"}}
    return None


def add(text, session=None, job=None):
    """Скомпилировать, проверить, сохранить черновиком и посчитать для всех отелей. Публично станет после approve."""
    t0 = time.time()
    job = job or start_job(text, session)

    def fail(err):
        job["status"] = "failed"
        step(job, "failed", err)
        store.log_event("characteristic_failed", payload={"text": text, "error": err})
        return {"ok": False, "error": err, "job": job["id"]}

    attempts = 1
    if llm.available():
        try:
            spec, samples, attempts = compile_llm(text, job=job)
        except Exception as e:
            return fail(str(e))
        mode = "llm"
    else:
        mode = "template"
        step(job, "template", "LLM нет: подбираю шаблон частого пожелания")
        spec = compile_template(text)
        if spec is None:
            return fail("Без ключа LLM понимаю только шаблонные пожелания (собаки, музей, бассейн, "
                        "балкон, остановка, супермаркет…). Добавьте ключ в .env для произвольных.")
        step(job, "dry_run", "пробный расчёт рецепта на 5 отелях")
        samples = _dry_run(spec)
    old = registry.get(spec["id"])
    if old and old.get("origin") not in ("compiled", "template"):
        spec["id"] += "_custom"
    elif old and registry.status(old) == "approved":
        # уже одобрена раньше: не превращаем рабочую характеристику обратно в черновик
        job["status"], job["char_id"] = "done", spec["id"]
        step(job, "done", "такая характеристика уже одобрена")
        return {"ok": True, "mode": mode, "id": spec["id"], "status": "approved", "job": job["id"],
                "spec": registry.to_json(old), "samples": samples, "errors": 0, "coverage": _coverage(spec["id"]),
                "eval": old.get("eval") or draft_eval.build(spec["id"], mode, attempts, time.time() - t0, samples)}
    job["char_id"] = spec["id"]
    spec.update({"status": "draft", "requested_by": session, "drafted_at": store.now()})
    path = registry.save_custom(spec)
    step(job, "compute", f"считаю для {len(gd.load().hotels)} отелей")
    ids = [h["id"] for h in gd.load().hotels]
    errors = 0
    for a in range(0, len(ids), 60):
        errors += registry.compute_all([spec["id"]], ids[a:a + 60])
        step(job, "compute", f"посчитано {min(a + 60, len(ids))} из {len(ids)}")
    step(job, "eval", "собираю отчёт для админа")
    report = draft_eval.build(spec["id"], mode, attempts, time.time() - t0, samples)
    registry.save_custom({**registry.get(spec["id"]), "eval": report})
    cov = _coverage(spec["id"])
    store.log_event("characteristic_drafted", char_id=spec["id"],
                    payload={"text": text, "mode": mode, "coverage": cov, "verdict": report["verdict"], "session": bool(session)})
    job["status"] = "done"
    step(job, "done", "черновик готов, ждёт проверки админа")
    return {"ok": True, "mode": mode, "id": spec["id"], "status": "draft", "job": job["id"], "file": str(path.name),
            "spec": registry.to_json(registry.get(spec["id"])), "samples": samples, "errors": errors, "coverage": cov,
            "eval": report}


def build_async(text, session=None):
    """Запустить сборку в фоне и сразу вернуть id задачи: UI опрашивает public_job(JOBS[id])."""
    job = start_job(text, session)

    def run():
        try:
            add(text, session, job)
        except Exception as e:  # поток без обработчика оставил бы задачу «идёт» навсегда
            job["status"] = "failed"
            step(job, "failed", f"{type(e).__name__}: {e}")
            if job.get("char_id") and registry.get(job["char_id"]) and not registry.get(job["char_id"]).get("eval"):
                registry.reject(job["char_id"], f"сборка прервана: {type(e).__name__}")

    threading.Thread(target=run, daemon=True).start()
    return job["id"]


def _coverage(cid):
    spec = registry.get(cid)
    st = {"known": 0, "unknown": 0, "conflict": 0, "stale": 0}
    key_true = 0
    for h in gd.load().hotels:
        r = store.resolve(h["id"], spec)
        st[r["status"]] += 1
        if r["value"] and r["value"].get(spec.get("key")) is True:
            key_true += 1
    return {**st, "key_true": key_true, "total": len(gd.load().hotels)}
