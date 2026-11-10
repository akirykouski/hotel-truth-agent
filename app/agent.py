"""Чат-агент: LLM с инструментами системы. Он не знает ничего об отелях сам — только то, что вернули инструменты.

Без ключа LLM чат отвечает детерминированно: разбор запроса по ключевым словам + поиск + объяснение по шаблону.
"""
import inspect
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from app import actions, capcard, grounding, llm, region, search
from app.tools import catalog

SYSTEM = """Ты помощник Островка по подбору отелей {label_in}. Твои знания об отелях — только то, что вернули
инструменты: это проверяемые факты с источником, уверенностью и датой. Ничего не придумывай.

Как работать:
- Запрос гостя о подборе — вызывай search_hotels (гость уже видит карточки по своим условиям; их набор и порядок
  возвращает первый вызов; условия меняй, только если гость сам просит): в query слова гостя, а условия разбери сам и передай в constraints
  (схема характеристик и полей в описании инструмента; так поиск идёт без повторного разбора). Месяц — в month.
- Вопрос про конкретный отель — find_hotel, затем hotel_facts.
- Если нужной характеристики нет в реестре (search_hotels вернул её в parsed.missing) и она важна гостю —
  предложи собрать её и, если гость согласен или просит прямо, вызови add_characteristic, затем повтори поиск.
- Разовый вопрос, который не стоит заводить характеристикой («сколько идти до остановки») — compute_tool.
- Гость выбирает номер или хочет море, закат, тишину в конкретном отеле — room_advice: какую категорию брать и
  что попросить при бронировании (готовая просьба). Это вероятность, не гарантия, так и говори.
- Если данных нет или уверенность низкая — скажи честно и предложи спросить отельера (ask_hotelier); ответ придёт
  позже, не обещай мгновенно.

Как отвечать: по-русски, компактно. Ответ о подборе жёстко держи в 700–1000 символов (не длиннее): топ-3 отеля, по каждому три
строки до 110 символов каждая, без цены и рейтинга, если гость о них не спрашивал: почему подходит (с цифрами), главный минус именно для этого гостя, что попросить или сделать при
бронировании (готовая просьба из room_advice, если звал его). Затем одна строка о том, что неизвестно, и
предложение показать ещё. Уверенность называй словами и не в каждой строке: если расчёт надёжный (0.7 и выше), говори без пометки; 0.5–0.7 «скорее всего»; ниже 0.5 «примерно». Не пиши «устойчивый расчёт», «геоданные»; источник называй просто: «по карте», «по отзывам», «по карточке», «со слов отельера».
Пиши словами, а не сокращениями: «окна на юго-запад», не «ЮЗ»; «железная дорога», не «ж/д»; «около 30 дБ», не «~30 дБ». Децибелы поясняй: до 35 дБ тихо, как ночью в спальне; около 55 как оживлённая улица за окном; 65 и выше шумно, окна не открыть. Вероятность пиши полностью: «море из окна видно с вероятностью 86%».
Не используй превосходные степени («самый тихий», «ближе всего», «лучший», «единственный»), если вывод инструмента не отсортирован именно по этому полю; называй конкретные числа и сравнивай по ним.
Не говори, что вопрос отправлен или стоит в очереди, если ты не вызвал ask_hotelier в этом ответе.
В уточняющих ответах не повторяй готовую просьбу и факты из прошлого ответа, только новое. Тире ставь с пробелами.
Различай «подходит», «возможно — данных не хватает» и «не подходит». Если в ответе search_hotels all_checked=false
(есть caveats, parsed.missing, off_region или price_note), не говори, что отель подходит под все условия: назови, что не
проверено; при off_region скажи, что отели не в том городе; цену называй «на 1 ноября, на ваши даты уточните». Не пересказывай каждую характеристику
подряд и не повторяй запрос гостя: выбирай то, что важно именно ему.
Если подходящих мало — предложи, что ослабить, по relaxations; компромиссы по цене, пляжу и шуму бери из pareto.
На вопрос про один отель или про сравнение отвечай по существу, тоже коротко.

Правила точности: каждую цифру (дБ, м, минуты, этажи, °C, ₽) бери только из результатов инструментов, не округляй
грубее чем на единицу. Прежде чем сказать «этого система не считает», сверься с карточкой возможностей ниже и при
сомнении вызови hotel_facts / compute_tool. Каждую характеристику из запроса гостя покрой в ответе или скажи, что данных нет."""


# Живой ход ответа для гостевой страницы: run (id запроса от страницы) -> стадия.
# 0 разбор запроса, 1 инструменты (вид, путь, цифры), 2 сверка цифр, 3 ремонт текста. Нет записи: не идёт или кончилось.
_PROGRESS = {}


def _stage(run, k):
    if not run:
        return
    now = time.time()
    for r in [r for r, v in _PROGRESS.items() if now - v[1] > 900]:  # брошенные запуски не копим
        _PROGRESS.pop(r, None)
    _PROGRESS[run] = (k, now)


def progress(run):
    v = _PROGRESS.get(run)
    return v[0] if v else None


def _tool_defs():
    return [
        {"name": "search_hotels", "description": actions.search_hotels.__doc__,
         "input_schema": {"type": "object", "properties": {
             "query": {"type": "string"}, "limit": {"type": "integer"},
             "constraints": {"type": "array", "items": {"type": "object", "properties": {
                 "char": {"type": "string"}, "field": {"type": "string"},
                 "op": {"type": "string", "enum": ["==", "!=", "<=", ">=", "<", ">"]},
                 "value": {"type": ["boolean", "number", "string"]}, "must": {"type": "boolean"},
                 "phrase": {"type": "string"}}, "required": ["char", "field", "op", "value"]}},
             "month": {"type": "integer"},
             "base": {"type": "object", "properties": {"max_price": {"type": "number"}, "min_stars": {"type": "integer"},
                                                      "min_rating": {"type": "number"}}},
             "missing": {"type": "array", "items": {"type": "object", "properties": {
                 "phrase": {"type": "string"}, "proposal": {"type": "string"}}}}},
                          "required": ["query"]}},
        {"name": "find_hotel", "description": actions.find_hotel.__doc__,
         "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        {"name": "hotel_facts", "description": actions.hotel_facts.__doc__,
         "input_schema": {"type": "object", "properties": {"hotel_id": {"type": "string"},
                                                           "chars": {"type": "array", "items": {"type": "string"}}},
                          "required": ["hotel_id"]}},
        {"name": "compare_hotels", "description": actions.compare_hotels.__doc__,
         "input_schema": {"type": "object", "properties": {"hotel_ids": {"type": "array", "items": {"type": "string"}},
                                                           "chars": {"type": "array", "items": {"type": "string"}}},
                          "required": ["hotel_ids"]}},
        {"name": "list_characteristics", "description": actions.list_characteristics.__doc__,
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "add_characteristic", "description": actions.add_characteristic.__doc__,
         "input_schema": {"type": "object", "properties": {"description": {"type": "string"}}, "required": ["description"]}},
        {"name": "compute_tool", "description": actions.compute_tool.__doc__,
         "input_schema": {"type": "object", "properties": {
             "tool": {"type": "string", "enum": list(catalog.TOOLS)},
             "hotel_id": {"type": "string"}, "args": {"type": "object"}}, "required": ["tool", "hotel_id"]}},
        {"name": "ask_hotelier", "description": actions.ask_hotelier.__doc__,
         "input_schema": {"type": "object", "properties": {"hotel_id": {"type": "string"}, "char_id": {"type": "string"},
                                                           "question": {"type": "string"}},
                          "required": ["hotel_id", "char_id"]}},
        {"name": "room_advice", "description": actions.room_advice.__doc__,
         "input_schema": {"type": "object", "properties": {"hotel_id": {"type": "string"},
                                                           "wants": {"type": "array", "items": {"type": "string", "enum": ["sea", "sunset", "quiet"]}},
                                                           "month": {"type": "integer"}},
                          "required": ["hotel_id"]}},
    ]


def _execute(name, args, session=None):
    fn = getattr(actions, name)
    if session and "session" in inspect.signature(fn).parameters:
        args = {**args, "session": session}
    out = fn(**args)
    if name == "list_characteristics":
        out = {"characteristics": [{"id": c["id"], "name": c["name"], "fields": list(c["fields"])} for c in out["characteristics"]]}
    return out


def _system():
    return SYSTEM + "\n\n" + capcard.build()


def _finish(res, messages, parsed, can_repair, run=None):
    """Заземление: сверка цифр с инструментами, добор недостающих характеристик, один ремонт, отчёт."""
    users = [m["content"] for m in messages if m["role"] == "user"]
    t0 = time.time()
    _stage(run, 2)
    try:
        text, extra, rep = grounding.ground(res["text"], res["trace"], users, parsed, can_repair, on_repair=lambda: _stage(run, 3))
    except Exception as e:  # проверка не должна ронять ответ
        res["grounding"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
        res["trace"] = [{k: v for k, v in t.items() if k != "output"} for t in res["trace"]]
        return res
    if text != res["text"]:
        res["text_original"] = res["text"]
    res["text"] = text
    res["trace"] = [{k: v for k, v in t.items() if k != "output"} for t in res["trace"] + extra]  # выводы клиенту не нужны
    rep["sec"] = round(time.time() - t0, 1)
    res["grounding"] = rep
    return res


def _cands(obj, out, depth=0):
    """Отели {id, name} из выводов инструментов (любая вложенность): кандидаты на «агент советует»."""
    if depth > 6:
        return
    if isinstance(obj, dict):
        if obj.get("id") is not None and isinstance(obj.get("name"), str) and len(obj["name"]) >= 4 and ("stars" in obj or "address" in obj or "rating" in obj):
            out.setdefault(str(obj["id"]), obj["name"])
        for v in obj.values():
            _cands(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _cands(v, out, depth + 1)


def _norm(t):
    t = re.sub(r"[«»\"'`*_]", "", (t or "").lower().replace("ё", "е")).replace("&", " and ").replace("’", "")
    return re.sub(r"\s+", " ", t).strip()


_GENERIC = re.compile(r"\b(бутик-отель|мини-отель|апарт-отель|апарт|апартамент\w*|отель|гостиничный|гостиница|санаторно-курортный|комплекс|"
                      r"пансионат|с лечением|hotel|apart|sochi|сочи|resort)\b|\d\*", re.I)


def _alias(n):
    """Короткое имя, как отель называют в тексте: без типа заведения, звёзд и хвоста «by ...» («Портрум 1905»)."""
    a = _GENERIC.sub(" ", re.sub(r"\bby\b.*$", "", n))
    return re.sub(r"\s+", " ", a).strip()


def _has(low, phrase):
    return bool(phrase) and re.search(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", low) is not None


def _recommended(text, trace, search_data):
    """id отелей, названных в ответе (по порядку упоминания). Без догадок: полное имя из выводов инструментов дословно,
    либо короткое имя (без «Отель», звёзд, «by ...»), которое входит в название ровно одного отеля города."""
    from app import geodata as gd
    c = {}
    for t in trace:
        _cands(t.get("output"), c)
    _cands(search_data, c)
    allnames = [_norm(h["name"]) for h in gd.load().hotels]
    full = {}
    for i, n in c.items():
        full.setdefault(_norm(n), []).append(i)
    low = _norm(text)
    lows = re.sub(r"\s+", " ", _GENERIC.sub(" ", low)).strip()  # текст без типов заведений: «Luciano Hotel & Spa» и «Luciano Sochi» сходятся на одном имени
    found = []
    for i, n in c.items():
        nn = _norm(n)
        pos = low.find(nn) / max(len(low), 1) if len(full[nn]) == 1 and _has(low, nn) else -1
        if pos < 0:
            al = _alias(nn)
            if len(al) >= 5 and _has(lows, al) and sum(_has(_alias(x), al) for x in allnames) == 1:
                pos = re.search(r"(?<![\w-])" + re.escape(al), lows).start() / max(len(lows), 1)
        if pos >= 0:
            found.append((pos, i))
    return [i for _, i in sorted(found)]


def chat(messages, session=None, parsed_in=None, run=None):
    """messages: [{role, content}] от клиента. Возвращает ответ, журнал вызовов, последнюю выдачу для карточек
    и отчёт grounding о сверке цифр с инструментами. parsed_in: разбор быстрого поиска, по которому гость видит карточки;
    первый search_hotels агента идёт по нему же (одна история на экране), дальше агент ищет сам."""
    try:
        return _chat(messages, session, parsed_in, run)
    finally:
        _PROGRESS.pop(run, None)


def _chat(messages, session, parsed_in, run):
    _stage(run, 0)
    last_search, outputs = {}, {}
    pin = {"v": None}
    if parsed_in and sum(m["role"] == "user" for m in messages) == 1:
        from app.routes_front import _clean
        pin["v"] = _clean(parsed_in)
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    ex = ThreadPoolExecutor(1)
    # разбор запроса LLM идёт параллельно с агентом: нужен только для контроля покрытия
    parse_f = ex.submit(lambda: search.parse(user, session)) if llm.available() else None

    def on_step(step):
        pass

    def parsed():
        try:
            return [parse_f.result(timeout=120)] if parse_f else []
        except Exception:
            return []

    if llm.available():
        def execute(name, args):
            if name == "search_hotels" and pin["v"]:  # условия гостя уже разобраны: без повторного разбора, лимит как у агента
                args = {"query": args.get("query") or user, "limit": args.get("limit") or 5, "parsed": pin["v"]}
                pin["v"] = None
            _stage(run, 1)
            out = _execute(name, args, session)
            outputs[(name, json.dumps(args, sort_keys=True, ensure_ascii=False))] = out
            if name == "search_hotels":
                last_search["data"] = out
            return out
        try:
            t_agent = time.time()
            text, trace = llm.agent(_system().replace("{label_in}", region.META["label_in"]), messages, _tool_defs(), execute, on_step=on_step, session=session)
            t_agent = round(time.time() - t_agent, 1)
            for t in trace:  # провайдеры с локальным циклом знают выводы; claude-cli их не отдаёт, их переиграет grounding
                o = outputs.get((t["tool"], json.dumps(t.get("input") or {}, sort_keys=True, ensure_ascii=False)))
                if o is not None:
                    t["output"] = o
            if "data" not in last_search:  # агент работал в другом процессе (claude -p + MCP): карточки из его вывода
                got = next((t["output"] for t in reversed(trace) if t["tool"] == "search_hotels"
                            and isinstance(t.get("output"), dict) and "results" in t["output"]), None)
                if got is not None:
                    last_search["data"] = got
                else:  # вывод не пришёл: пересобираем (редкий путь)
                    q = next((t["input"].get("query") for t in reversed(trace) if t["tool"] == "search_hotels"), None)
                    if q:
                        last_search["data"] = actions.search_hotels(q, limit=5, session=session)
            res = {"text": text, "trace": trace, "search": last_search.get("data"), "mode": f"{llm.PROVIDER}:{llm.MODEL}"}
            cand_trace = list(res["trace"])
            res = _finish(res, messages, parsed(), True, run)
            res["recommended"] = _recommended(res["text"], cand_trace, res.get("search"))
            res.get("grounding", {})["agent_sec"] = t_agent
            return res
        except Exception as e:
            fallback = f"LLM недоступна ({type(e).__name__}), отвечаю без неё. "
        finally:
            ex.shutdown(wait=False)
    else:
        fallback = ""
    q = user
    data = actions.search_hotels(q, limit=5, parsed=pin["v"], session=session)
    res = {"text": fallback + _template_answer(data),
           "trace": [{"tool": "search_hotels", "input": {"query": q}, "output": data}], "search": data, "mode": "rules"}
    cand_trace = list(res["trace"])
    res = _finish(res, messages, [], False)
    res["recommended"] = _recommended(res["text"], cand_trace, data)
    return res


def _template_answer(d):
    cons, missing = d["parsed"]["constraints"], d["parsed"].get("missing") or []
    names = ", ".join(m["phrase"] for m in missing)
    if d.get("off_region"):
        return d.get("message") or f"Вы спросили про {d['off_region']['asked']}, а у нас отели только в регионе «{d['off_region']['active']}»."
    ign = d.get("ignored") or []
    ign_txt = (" Не учитывали, как вы просили: " + ", ".join(g["phrase"] for g in ign) + ".") if ign else ""
    if not cons:
        if missing:
            return (f"Мы не нашли условий, которые умеем проверять: {names}. Собрать характеристику? "
                    "Кнопка «＋» под запросом запускает сборку: источники, рецепт, расчёт по всем отелям.")
        return ("Мы не нашли в запросе характеристик, которые система уже собирает. Попробуйте: «тихий отель с видом на "
                "море», «без подъёма до пляжа», «с собакой», «закат из окна в июле».")
    c = d["counts"]
    understood = "; ".join(x.get("label") or x["char"] for x in cons) + (f"; {d['month']}" if d["month"] else "")
    parts = []
    if c["match"]:
        parts.append(f"{'Подходит' if c['match'] % 10 == 1 and c['match'] % 100 != 11 else 'Подходят'} {c['match']} "
                     + search.plural(c["match"], "отель", "отеля", "отелей") + (" по проверенным условиям" if missing else ""))
    if c["maybe"]:
        parts.append(f"возможно подходят {c['maybe']} (не хватает данных)")
    if c["fail"]:
        parts.append(f"не подходят {c['fail']}")
    lines = [f"Мы проверили: {understood}." + ign_txt + (f" Пока не умеем проверять, и это не закрыто: {names}." if missing else "")
             + (f" Цены: {d['price_note']}." if d.get("price_note") else ""),
             ("; ".join(parts)[:1].upper() + "; ".join(parts)[1:] if parts else "Подходящих отелей нет") + "."]
    for r in d["results"][:3]:
        h = r["hotel"]
        lines.append(f"\n**{h['name']}** ({'подходит' if r['bucket'] == 'match' else 'возможно' if r['bucket'] == 'maybe' else 'не подходит'})")
        lines += [f"✅ {g}" for g in r["good"][:3]] + [f"⚠ {b}" for b in r["bad"][:2]] + [f"❓ {u}" for u in r["unknown"][:2]]
    if d.get("relaxations") and d["relaxations"][0]["gain"] > 0:
        lines.append(f"\nПодходящих мало. Можно ослабить условия: {d['relaxations'][0]['text']}.")
    return "\n".join(lines)
