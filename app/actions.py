"""Действия системы — одни и те же для веб-чата (агент с инструментами), MCP-сервера и HTTP API."""
import os

from app import capcard, compiler, hotelier, registry, search, store, truth
from app import geodata as gd
from app.tools import catalog


def _sid(session):
    """Сессия запросившего: из аргумента или, когда агент работает в другом процессе (claude -p + MCP), из окружения."""
    return session or os.getenv("OSTROVOK_SESSION") or None


def _resolved(hotel_id, cid):
    spec = registry.get(cid)
    r = store.resolve(hotel_id, spec)
    tx = search.ru_text
    conflicts = [{**c, "winner_says": tx(c.get("winner_says")), "other_says": tx(c.get("other_says"))} for c in r.get("conflicts", [])]
    return {"char": cid, "name": spec["name"], "status": r["status"], "summary": tx(r.get("summary")) or "нет данных",
            "value": r.get("value"), "source": r.get("source_label"), "confidence": r["confidence"],
            "observed_at": r.get("observed_at"), "valid_until": r.get("valid_until"),
            "conflicts": conflicts, "class": r.get("class"), "trust": r.get("trust"),
            "facts": [{"id": f["id"], "source": f["source_label"], "summary": tx(f["summary"]), "confidence": f["confidence"],
                       "method": f["method"], "observed_at": f["observed_at"], "valid_until": f["valid_until"],
                       "stale": f.get("stale"), "evidence": f["evidence"]} for f in r.get("facts", [])]}


def search_hotels(query: str, limit: int = 5, parsed: dict | None = None, drop: list | None = None,
                  loosen: dict | None = None, session: str | None = None, constraints: list[dict] | None = None,
                  month: int | None = None, base: dict | None = None, missing: list[dict] | None = None):
    """Найти отели по запросу словами. Возвращает разбор запроса, корзины и объяснение по каждому отелю. Если
    подходящих мало, есть relaxations (что ослабить и сколько отелей добавится) и pareto (компромиссы цена, пляж, шум)."""
    rejected = []
    if constraints and parsed is None:  # агент разобрал запрос сам: вложенный разбор LLM не нужен
        parsed, rejected = search.parse_agent(query, constraints, month, base, missing, _sid(session))
    r = search.search(query, limit=limit, parsed=parsed, drop=drop, loosen=loosen, session=_sid(session))
    out = {"parsed": r["parsed"], "month": r["month_name"], "counts": r["counts"],
           "results": [{"hotel": x["hotel"], "bucket": x["bucket"], **search.explain(x)} for x in r["results"]],
           "near_misses": [{"hotel": x["hotel"], **search.explain(x)} for x in r["near_misses"]],
           "dropped": r["dropped"], "loosened": r["loosened"],
           "nothing_to_check": r.get("nothing_to_check", False), "ignored": r.get("ignored") or [],
           "off_region": r.get("off_region"), "price_note": r.get("price_note"), "caveats": r.get("caveats") or [],
           # true только если нечего оговаривать: ни непроверенных уточнений, ни другого города, ни цен на чужую дату
           "all_checked": not r.get("caveats") and not r.get("off_region")}
    if r.get("message"):
        out["message"] = r["message"]
    if rejected:
        out["constraints_rejected"] = rejected
    if "relaxations" in r:
        out["relaxations"] = [{k: x[k] for k in ("kind", "idxs", "gain", "text", "from", "to", "chip") if k in x}
                              | {"best": x["best"]["name"], "best_id": x["best"]["id"]} for x in r["relaxations"]]
        out["pareto"] = r["pareto"]
    return out


search_hotels.__doc__ += capcard.constraints_schema()


def hotel_facts(hotel_id: str, chars: list[str] | None = None, full: bool = False, session: str | None = None):
    """Всё, что система знает об отеле: по каждой характеристике итог, источник, уверенность, дата, противоречия."""
    h = gd.load().hotel_by_id[hotel_id]
    out = []
    visible = registry.public_chars(_sid(session))
    for cid in chars or list(visible):
        if cid not in visible:
            continue
        r = _resolved(hotel_id, cid)
        if not full:
            r.pop("facts")
            r.pop("value")
            r.pop("trust")
        out.append(r)
    return {"hotel": search._brief(h), "facts": out, "reputation": truth.hotelier_reputation(hotel_id),
            "open_questions": [{"id": q["id"], "char": q["char_id"], "text": search.ru_text(q["text"]),
                                "reason": search.ru_text(q["reason"])}
                               for q in store.questions(hotel_id, "open")]}


def find_hotel(name: str):
    """Найти отель демо-зоны по части названия."""
    n = name.lower()
    return [search._brief(h) for h in gd.load().hotels if n in h["name"].lower()][:10]


def compare_hotels(hotel_ids: list[str], chars: list[str] | None = None):
    """Сравнить несколько отелей по собранным характеристикам."""
    return search.compare(hotel_ids, chars)


def list_characteristics(session: str | None = None):
    """Какие характеристики система умеет собирать: поля, источники, сколько отелей покрыто."""
    out = []
    hotels = gd.load().hotels
    for cid, s in registry.public_chars(_sid(session)).items():
        out.append({"id": cid, "name": s["name"], "description": s["description"].strip(), "level": s.get("level"),
                    "fields": s["fields"], "sources": [m["source"] for m in s["methods"]],
                    "origin": s.get("origin", "built-in"), "status": registry.status(s), "ttl_days": s.get("ttl_days"), "file": s.get("_file")})
    return {"characteristics": out, "hotels": len(hotels)}


def add_characteristic(description: str, session: str | None = None):
    """Добавить новую характеристику по описанию словами: агент пишет рецепт, проверяет и считает для всех отелей.
    Результат предварительный: это черновик, его видит только запросивший, пока админ не одобрит."""
    r = compiler.add(description, session=_sid(session))
    if r.get("ok"):
        r["label"] = "предварительно, только для вас, ждёт проверки"
    return r


def compute_tool(tool: str, hotel_id: str, args: dict | None = None):
    """Вызвать инструмент-примитив напрямую (для разовых вопросов): sea_view, sunset, walk_to, noise, nearby,
    card_search, reviews_search, climate."""
    try:
        res = catalog.call(tool, hotel_id, args or {})
    except TypeError as e:  # неверные аргументы: подсказываем правильные, чтобы агент исправился сам
        return {"error": f"неверные аргументы для {tool}: {e}", "allowed_args": catalog.TOOLS[tool]["params"]}
    if isinstance(res, dict):
        res = {k: v for k, v in res.items() if k != "polyline"}
    return {"tool": tool, "source": catalog.TOOLS[tool]["source"], "result": res}


compute_tool.__doc__ = (
    "Вызвать инструмент-примитив напрямую для разового вопроса. Аргументы args строго такие:\n"
    + "\n".join(f"- {n}: " + (", ".join(f"{k} ({v.get('type')})" for k, v in t["params"].items()) or "без аргументов")
                + f". {t['description'][:160]}" for n, t in catalog.TOOLS.items()))


def ask_hotelier(hotel_id: str, char_id: str, question: str | None = None):
    """Поставить вопрос отельеру в очередь (ответ придёт позже, в кабинете). Если текст не задан — берётся из реестра."""
    spec = registry.get(char_id)
    if question is None:
        made = [q for q in registry.plan_questions(hotel_id, budget=10) if q["char_id"] == char_id]
        if made:
            return {"queued": made[0]}
        question = f"Уточните, пожалуйста: {spec['name'].lower()}: {spec['description'].strip().splitlines()[0]}"
    qid = store.add_question(hotel_id, char_id, question, "вопрос гостя", 1.0)
    store.log_event("question_asked", hotel_id, char_id, {"text": question})
    return {"queued": {"id": qid, "text": question} if qid else "такой вопрос уже ждёт ответа"}


def answer_question(question_id: int, answer: str):
    """Ответ отельера свободным текстом: раскладывается по полям и становится фактом с источником «отельер»."""
    return hotelier.answer(int(question_id), answer)


def answer_preview(question_id: int, answer: str):
    """Ответ отельера в кабинете: разбор и эхо «Мы поняли так: … Верно?»; факт появится после confirm_answer."""
    return hotelier.preview(int(question_id), answer)


def confirm_answer(question_id: int, ok: bool = True):
    """Отельер подтвердил эхо (ok) — ответ становится фактом; не подтвердил — текст возвращается на правку."""
    return hotelier.confirm(int(question_id), ok)


def room_advice(hotel_id: str, wants: list[str] | None = None, month: int | None = None):
    """Какую категорию номера бронировать и что попросить у отеля, чтобы получить море, закат или тишину.
    wants: список из sea, sunset, quiet (по умолчанию sea); month 1-12 нужен для заката. Возвращает лучшую категорию
    с готовой просьбой для брони, запасные варианты и категории со скрытым видом на море."""
    from app import rooms
    return rooms.advice(hotel_id, wants, month)


def hotelier_inbox(hotel_id: str):
    """Кабинет отельера: что система узнала об отеле, открытые вопросы, сильные стороны и риски."""
    facts = hotel_facts(hotel_id)["facts"]
    strengths = [f for f in facts if f["status"] == "known" and f["confidence"] >= 0.7 and _positive(f["char"], hotel_id)]
    risks = [f for f in facts if f["status"] == "conflict" or (f["char"] in ("night_quiet", "construction") and not _positive(f["char"], hotel_id))]
    unknown = [f for f in facts if f["status"] == "unknown"]
    from app import rooms
    hidden = [{"room": r["room"], "ask": r["ask"], "sea_view_p": r["sea_view_p"], "best_side_p": r["best_side_p"],
               "text": f"Категория «{r['room']}», вероятно, видит море из окон на {rooms.TO_DIR.get(r['ask']['side'], r['ask']['side'])} с {r['ask']['min_floor']}-го этажа "
                       f"(на лучшей стороне вероятность {round(r['best_side_p'] * 100)}%): можно продавать как «с видом на море» после проверки."}
              for r in rooms.resolve_rooms(hotel_id) if r["hidden_view"]]
    return {"hidden_strengths": hidden, "hotel": search._brief(gd.load().hotel_by_id[hotel_id]), "facts": facts, "strengths": strengths,
            "risks": risks, "unknown": unknown, "questions": question_views(store.questions(hotel_id)),
            "reputation": truth.hotelier_reputation(hotel_id),
            "completeness": round(1 - len(unknown) / max(1, len(facts)), 2)}


def question_views(qs):
    """Вопросы отельеру для показа: тексты по-русски, название характеристики, разобранный ответ парами «поле: значение»."""
    out = []
    for q in qs:
        spec = registry.get(q["char_id"]) or {}
        staged = q["status"] == "open" and q.get("answer") and q.get("parsed")
        out.append({**q, "text": search.ru_text(q["text"]), "reason": search.ru_text(q["reason"]),
                    "char_name": spec.get("name", q["char_id"]), "parsed_view": search.field_view(q["char_id"], q.get("parsed")),
                    "echo": hotelier.echo_text(q["char_id"], q["parsed"]) if staged else None})
    return out


def _positive(cid, hotel_id):
    spec = registry.get(cid)
    r = store.resolve(hotel_id, spec)
    v = (r.get("value") or {}).get(spec.get("key"))
    return bool(v) if isinstance(v, bool) else True
