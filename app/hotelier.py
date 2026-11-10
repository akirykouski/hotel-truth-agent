"""Отельер: вопросы по делу и разбор ответа свободным текстом по полям.

Вопросы выбирает registry.plan_questions (не больше 3 на отель, по ценности информации). Ответ отельера
LLM раскладывает по полям характеристики (answer_fields в YAML); без ключа — простые правила (да/нет, числа).
Ответ становится фактом с источником «ответ отельера»: он сильнее расчёта, но не прячет его — если отзывы
или расчёт говорят обратное, это видно как противоречие.

В кабинете ответ сначала возвращается эхом: «Мы поняли так: … Верно?» (preview). Факт появляется только после «да»
(confirm), «нет» возвращает текст на правку. Так ошибка разбора не становится фактом. Скрипты, MCP и агент
отвечают в один шаг (answer).
"""
import re

from app import llm, registry, store

HOTELIER_CONF = 0.9
HOTELIER_TTL = 365

SYSTEM = """Ты раскладываешь ответ отельера по полям. Бери только то, что он сказал; если про поле ничего нет — null.
Если ответ частичный или с оговорками («не во всех номерах», «с 5-го этажа»), отрази это в поле notes.
Вопрос: {q}
Поля: {fields}"""


def _schema(fields):
    props = {}
    for k, f in fields.items():
        t = {"bool": "boolean", "number": "number"}.get(f["type"], "string")
        props[k] = {"type": [t, "null"], "description": f.get("label", k)}
    props["notes"] = {"type": "string", "description": "оговорки и детали одной фразой"}
    props["certainty"] = {"type": "string", "enum": ["уверенно", "с оговорками", "не знает"]}
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def parse_rules(answer, fields):
    t = answer.lower()
    out = {}
    neg = bool(re.search(r"\bнет\b|не (пуска|разреш|допуска|видно)|запрещ|отсутств|к сожалению", t))
    pos = bool(re.search(r"\bда\b|есть|конечно|разреш|пускаем|принимаем|видно", t))
    nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", t)]
    for k, f in fields.items():
        if f["type"] == "bool":
            out[k] = False if neg and not pos else (True if pos else None)
        elif f["type"] == "number":
            hint = {"from_floor": r"(\d+)\s*-?\s*(?:го|й)?\s*этаж|с\s*(\d+)", "max_weight_kg": r"(\d+)\s*кг",
                    "fee_rub": r"(\d[\d\s]*)\s*(?:₽|руб)"}.get(k)
            m = re.search(hint, t) if hint else None
            out[k] = float(next(g for g in m.groups() if g).replace(" ", "")) if m else None
        else:
            out[k] = answer.strip()[:200] if f["type"] == "text" else None
    out["notes"] = answer.strip()[:300]
    out["certainty"] = "с оговорками" if re.search(r"не все|частич|некотор|кроме|только", t) else "уверенно"
    return out


def parse(question, answer, fields):
    if llm.available():
        try:
            fdesc = "; ".join(f"{k} ({v['type']}{', ' + v['label'] if v.get('label') else ''})" for k, v in fields.items())
            return llm.json_call(SYSTEM.format(q=question, fields=fdesc), answer, _schema(fields), effort="low"), "llm"
        except Exception:
            pass
    return parse_rules(answer, fields), "rules"


def _question(qid):
    q = next((x for x in store.questions() if x["id"] == qid), None)
    if q is None:
        raise KeyError(f"нет вопроса {qid}")
    return q


def _parse(q, text):
    spec = registry.get(q["char_id"])
    fields = spec.get("answer_fields") or {k: v for k, v in spec["fields"].items()}
    return parse(q["text"], text, fields)


def echo_text(char_id, parsed):
    """«Мы поняли так: …. Верно?» по разобранным полям, без комментария (он и так дословно из ответа)."""
    from app.search import field_view
    if (parsed or {}).get("certainty") == "не знает":
        return "Мы поняли так: вы пока не знаете точно. Верно?"
    notes = str((parsed or {}).get("notes") or "")
    # разбор правилами кладёт в текстовые поля весь ответ: такую дословную копию эхом не повторяем
    shown = {k: v for k, v in (parsed or {}).items() if not (isinstance(v, str) and k != "notes" and notes and notes.startswith(v))}
    items = [f"{x['label']} — {x['value']}" for x in field_view(char_id, shown)
             if x["label"] not in ("комментарий", "уверенность отельера")]
    tail = "; с оговорками" if (parsed or {}).get("certainty") == "с оговорками" else ""
    return f"Мы поняли так: {'; '.join(items) or 'ничего конкретного по вопросу'}{tail}. Верно?"


def preview(qid, text):
    """Разобрать ответ и вернуть эхо. Ответ и разбор лежат в вопросе (он ещё открыт), факта нет до confirm."""
    q = _question(qid)
    if q["status"] != "open":
        raise ValueError("на этот вопрос уже ответили")
    parsed, mode = _parse(q, text)
    store.stage_answer(qid, text, parsed | {"_parser": mode})
    from app.search import field_view
    return {"echo": echo_text(q["char_id"], parsed), "parsed": parsed, "parsed_view": field_view(q["char_id"], parsed),
            "mode": mode, "staged": True}


def confirm(qid, ok=True, by=None):
    """«Да, верно» — ответ становится фактом; «нет» — разбор сбрасывается, текст возвращается на правку."""
    q = _question(qid)
    if q["status"] != "open" or not q.get("answer"):
        raise ValueError("нечего подтверждать: сначала ответьте на вопрос")
    if not ok:
        store.stage_answer(qid, None, None)
        store.log_event("hotelier_echo_rejected", q["hotel_id"], q["char_id"], {"answer": q["answer"], "by": by})
        return {"rejected": True, "answer": q["answer"]}
    parsed = dict(q["parsed"] or {})
    return _commit(q, q["answer"], parsed, parsed.pop("_parser", "rules"), confirmed=True, by=by)


def answer(qid, text, by=None):
    q = _question(qid)
    parsed, mode = _parse(q, text)
    return _commit(q, text, parsed, mode, by=by)


def _commit(q, text, parsed, mode, confirmed=False, by=None):
    qid, spec = q["id"], registry.get(q["char_id"])
    store.answer_question(qid, text, parsed)
    if parsed.get("certainty") == "не знает":
        store.log_event("hotelier_unsure", q["hotel_id"], q["char_id"], {"answer": text, "by": by})
        from app.search import field_view
        return {"parsed": parsed, "parsed_view": field_view(q["char_id"], parsed), "mode": mode, "fact_id": None}
    before = store.resolve(q["hotel_id"], spec)
    value = {k: v for k, v in parsed.items() if v is not None and k != "certainty"}
    conf = HOTELIER_CONF * (0.8 if parsed.get("certainty") == "с оговорками" else 1.0)
    fid = store.put_fact(q["hotel_id"], q["char_id"], "hotelier", value, conf, f"отельер: «{text.strip()[:160]}»",
                         "ответ отельера свободным текстом, разобран по полям" + (" и подтверждён отельером" if confirmed else ""),
                         HOTELIER_TTL, {"question": q["text"], "answer": text, "parsed": parsed, "parser": mode,
                                        "echo": echo_text(q["char_id"], parsed) if confirmed else None})
    after = store.resolve(q["hotel_id"], spec)
    calib = _calibration(q, spec, before, parsed)
    store.log_event("hotelier_answer", q["hotel_id"], q["char_id"],
                    {"answer": text, "parsed": parsed, "before": before.get("summary"), "after": after.get("summary"),
                     "calibration": calib, "confirmed": confirmed, "by": by})
    from app.search import field_view
    return {"parsed": parsed, "parsed_view": field_view(q["char_id"], parsed), "mode": mode, "fact_id": fid, "before": _short(before), "after": _short(after),
            "calibration": calib, "confirmed": confirmed}


def _short(r):
    from app.search import ru_text  # search импортирует registry и hotelier косвенно: импорт внутри функции
    return ({k: r.get(k) for k in ("status", "summary", "source_label", "confidence")}
            | {"summary": ru_text(r.get("summary")),
               "conflicts": [{**c, "winner_says": ru_text(c.get("winner_says")), "other_says": ru_text(c.get("other_says"))}
                             for c in r.get("conflicts", [])]})


def _calibration(q, spec, before, parsed):
    """Отельер как датчик: если он называет этаж с видом на море не тот, что дал расчёт, это сигнал, что высоты
    соседних зданий в OSM неточны. Записываем расхождение — по нему видно, где проверить данные."""
    if q["char_id"] != "sea_view" or not before.get("value"):
        return None
    geo_floor = (before["value"] or {}).get("from_floor")
    h_floor = parsed.get("from_floor")
    if geo_floor and h_floor and geo_floor != h_floor:
        geo_fact = next((f for f in before["facts"] if f["source"] == "geo"), None)
        drivers = (geo_fact or {}).get("evidence", {}).get("drivers", [])
        return {"geo_from_floor": geo_floor, "hotelier_from_floor": h_floor,
                "hint": ("расчёт пессимистичнее отельера: высоты соседей, закрывающих море, вероятно завышены"
                         if h_floor < geo_floor else "расчёт оптимистичнее: вероятно, не учтены деревья или новые дома"),
                "check_buildings": drivers}
    return None
