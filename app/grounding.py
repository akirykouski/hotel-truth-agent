"""Заземление ответов: каждая цифра с единицей в ответе агента должна нашаться в том, что вернули инструменты.

verify(text, trace) достаёт числовые утверждения (дБ, м, км, мин, этаж, °C, %, ₽, ч, «N отелей») и названия отелей,
сверяет их с выводами инструментов (trace[i]["output"]; если вывода нет, вызов детерминированно переигрывается
через app.actions) и с цифрами из сообщений самого гостя. LLM здесь не участвует.
repair_text() убирает то, что подтвердить не удалось.
"""
import json
import re
from functools import lru_cache

from app import actions

SIDE_EFFECTS = {"add_characteristic", "ask_hotelier", "answer_question"}  # переигрывать нельзя: меняют состояние

# класс единицы → регулярка на слово после числа
UNITS = [
    ("db", r"дб|db"),
    ("km", r"км"),
    ("m", r"м\b|метр\w*"),
    ("min", r"мин\w*"),
    ("floor", r"этаж\w*|эт\b\.?"),
    ("c", r"°\s?c?|градус\w*"),
    ("pct", r"%|процент\w*"),
    ("rub", r"₽|руб\w*|р\b"),
    ("h", r"ч\b|час\w*"),
    ("hotels", r"отел\w*|вариант\w*"),
]
_UNIT_RE = "|".join(f"(?P<u_{k}>{v})" for k, v in UNITS)
_NUM = r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
CLAIM = re.compile(r"(?<![\w.:/-])(?P<a>" + _NUM + r")(?:\s*[–—-]\s*(?P<b>" + _NUM + r"))?"
                   r"(?:\s?-?(?:й|го|м|ти|ми|е|х))?\s*(?:" + _UNIT_RE + r")", re.I)
NUM = re.compile(r"-?\d+(?:\.\d+)?")

# ключ числового поля в выводе инструмента → класс единицы
KEY_UNIT = [
    ("db", r"db"), ("min", r"minutes|min\b"), ("floor", r"floor|levels|этаж"),
    ("m", r"(^|_)m$|distance|climb|steps|straight|radius|height|nearest"), ("c", r"(^|_)c$|_c_|temp"),
    ("pct", r"share|^p_|prob|percent"), ("rub", r"price"), ("h", r"hours|sunshine|_h_"),
    ("hotels", r"count|total|^match$|^maybe$|^fail$|hotels|reviews|^n$"),
]
LOOSE = {"m", "min", "km", "rub", "h", "hotels", "c", "pct"}  # здесь допустима сверка с «любым» числом, но жёстко
STRICT = {"db", "floor"}  # только с числом того же типа: иначе любая единица «подтвердит» всё


def _num(s):
    return float(re.sub(r"[\s  ]", "", s).replace(",", "."))


def _unit_of(m):
    return next(k for k in (u for u, _ in UNITS) if m.group(f"u_{k}"))


def _context(text, a, b, w=32):
    """Фрагмент вокруг числа по границам слов: чтобы в списке утверждений читалось по-человечески."""
    lo, hi = max(0, a - w), min(len(text), b + 12)
    if lo:
        lo = text.find(" ", lo) + 1 or a
    if hi < len(text):
        hi = text.rfind(" ", b, hi)
        hi = b if hi < 0 else hi
    return text[lo:hi].replace("\n", " ").strip(" -*")


def extract_claims(text):
    """Числовые утверждения с единицей: [{value, unit, sentence, span}]. Диапазон «41–48 дБ» даёт два."""
    out = []
    for m in CLAIM.finditer(text):
        unit = _unit_of(m)
        vals = [_num(m.group("a"))] + ([_num(m.group("b"))] if m.group("b") else [])
        for v in vals:
            out.append({"value": v, "unit": unit, "text": _context(text, m.start(), m.end()),
                        "span": (m.start(), m.end())})
    return out


class Pool:
    """Числа из выводов инструментов: типизированные (по единице в строке или имени поля) и «любые»."""

    def __init__(self):
        self.typed = {u: [] for u, _ in UNITS}
        self.any = []

    def add(self, v, unit, src):
        if unit:
            self.typed[unit].append((v, src))
        else:
            self.any.append((v, src))

    def walk(self, obj, src, key=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("polyline", "photo", "url", "lat", "lon", "id", "hotel_id"):
                    continue
                self.walk(v, src, str(k))
        elif isinstance(obj, (list, tuple)):
            self.typed["hotels"].append((float(len(obj)), f"{src}.len({key})"))
            for v in obj:
                self.walk(v, src, key)
        elif isinstance(obj, bool) or obj is None:
            return
        elif isinstance(obj, (int, float)):
            unit = next((u for u, rx in KEY_UNIT if re.search(rx, key, re.I)), None)
            self.add(float(obj), unit, f"{src}.{key}")
        elif isinstance(obj, str):
            for m in CLAIM.finditer(obj):
                for g in ("a", "b"):
                    if m.group(g):
                        self.add(_num(m.group(g)), _unit_of(m), f"{src}: {self._snip(obj, m)}")

    @staticmethod
    def _snip(obj, m):
        """Фрагмент строки вокруг числа, обрезанный по границам слов."""
        lo, hi = max(0, m.start() - 20), min(len(obj), m.end() + 3)
        if lo and obj[lo - 1] != " ":
            nxt = obj.find(" ", lo)
            lo = nxt + 1 if 0 <= nxt < m.start() else m.start()
        if hi < len(obj) and obj[hi] != " ":
            nxt = obj.find(" ", hi)
            hi = len(obj) if nxt < 0 else nxt
        return obj[lo:hi].strip(" -*")

    def find(self, value, unit):
        """(источник, точное ли совпадение) или None. Допуск — на округление, который агенту разрешён."""
        tol = {"db": 1.5, "floor": 0.5, "c": 0.5, "pct": 1.0, "rub": max(1.0, 0.01 * value), "min": 0.75, "m": max(1.0, 0.03 * value), "km": max(0.1, 0.03 * value)}.get(
            unit, max(1.0, 0.05 * value))
        cands = [(value, unit)]
        if unit == "km":
            cands = [(value * 1000, "m"), (value, "km")]
        if unit == "m" and value < 10:  # «2,5 м» маловероятно, но «1,2 км» уже переведён выше
            cands.append((value / 1000, "km"))
        if unit == "pct":
            cands.append((value / 100, None))
        if unit == "h":
            cands.append((value * 60, "min"))
        for v, u in cands:
            t = tol if u != "m" or unit != "km" else max(1.0, 0.05 * v)
            for p, src in self.typed.get(u or unit, []):
                if abs(p - v) <= t:
                    return src
            if u is None:
                for p, src in self.any:
                    if abs(p - v) <= 0.006:
                        return src
        if unit in LOOSE:
            for p, src in self.any:
                if abs(p - value) <= min(tol, 0.5):
                    return src
        return None


@lru_cache(maxsize=512)
def _replay_cached(tool, inp):
    fn = getattr(actions, tool, None)
    if fn is None or tool in SIDE_EFFECTS:
        return None
    try:
        return fn(**json.loads(inp))
    except Exception as e:  # инструмент упал при проверке — число просто не подтвердится
        return {"error": str(e)}


def outputs_of(trace):
    """Выводы всех вызовов: из trace[i]["output"], а если его нет — детерминированный переигрыш."""
    outs = []
    for t in trace:
        o = t.get("output")
        if o is None:
            o = _replay_cached(t.get("tool"), json.dumps(t.get("input") or {}, sort_keys=True, ensure_ascii=False))
        if o is not None:
            outs.append((t.get("tool"), o))
    return outs


@lru_cache(maxsize=1)
def _hotel_names():
    from app import geodata as gd
    return {h["name"]: h["id"] for h in gd.load().hotels if len(h["name"]) >= 5}


def _norm(s):
    return re.sub(r"[^\wа-яё]+", " ", s.lower()).strip()


def mentioned_hotels(text):
    """Названия отелей демо-зоны, упомянутые в тексте (по полному названию)."""
    t = _norm(text)
    return {n: i for n, i in _hotel_names().items() if _norm(n) in t}


def verify(text, trace, user_texts=()):
    """Сверка ответа с выводами инструментов.
    Возвращает {"claims": [...], "unsupported": N, "total": N}; в каждом claim: kind (number|hotel), value, unit,
    text, supported, evidence (откуда подтверждено)."""
    outs = outputs_of(trace)
    pool = Pool()
    for i, (tool, o) in enumerate(outs):
        pool.walk(o, f"{tool}#{i}")
    for u in user_texts:
        for m in CLAIM.finditer(u):
            for g in ("a", "b"):
                if m.group(g):
                    pool.add(_num(m.group(g)), _unit_of(m), "сообщение гостя")
        for x in NUM.findall(u):
            pool.any.append((float(x), "сообщение гостя"))
    claims = []
    for c in extract_claims(text):
        src = pool.find(c["value"], c["unit"])
        claims.append({"kind": "number", "value": c["value"], "unit": c["unit"], "text": c["text"], "span": c["span"],
                       "supported": src is not None, "evidence": src})
    blob = json.dumps([o for _, o in outs], ensure_ascii=False, default=str)
    nblob = _norm(blob)
    blind = any(t.get("tool") in SIDE_EFFECTS for t in trace)  # их выводов не видно: название могло прийти оттуда
    for name, hid in ({} if blind else mentioned_hotels(text)).items():
        ok = _norm(name) in nblob or f'"{hid}"' in blob
        claims.append({"kind": "hotel", "value": None, "unit": None, "text": name, "span": None, "supported": ok,
                       "evidence": "есть в данных" if ok else None})
    bad = sum(1 for c in claims if not c["supported"])
    return {"claims": claims, "unsupported": bad, "total": len(claims)}


def _sentence_bounds(text, pos):
    """Границы предложения/пункта списка вокруг позиции."""
    start = max(text.rfind("\n", 0, pos), text.rfind(". ", 0, pos) + 1 if text.rfind(". ", 0, pos) >= 0 else -1,
                text.rfind("; ", 0, pos) + 1 if text.rfind("; ", 0, pos) >= 0 else -1) + 1
    ends = [e for e in (text.find("\n", pos), text.find(". ", pos) + 1 if text.find(". ", pos) >= 0 else -1,
                        text.find("; ", pos) + 1 if text.find("; ", pos) >= 0 else -1) if e > 0]
    return start, (min(ends) if ends else len(text))


def strip_unsupported(text, claims):
    """Убрать предложения с неподтверждёнными цифрами; для названий отелей — пометить. Возвращает (текст, убрано)."""
    cuts, removed = [], []
    for c in claims:
        if c["supported"] or c["kind"] != "number":
            continue
        s, e = _sentence_bounds(text, c["span"][0])
        if (s, e) not in cuts:
            cuts.append((s, e))
            removed.append(text[s:e].strip(" -*•\t\n"))
    for s, e in sorted(cuts, reverse=True):
        text = text[:s] + text[e:]
    for c in claims:
        if not c["supported"] and c["kind"] == "hotel":
            text = text.replace(c["text"], c["text"] + " (не подтверждено)", 1)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"^\s*(?:[-*•]\s*)+$", "", text, flags=re.M)
    return text.strip(), removed


# ---------- ремонт ответа и контроль покрытия ----------

REPAIR_SYSTEM = """Ты редактор ответов помощника по подбору отелей. Помощник мог написать цифры или утверждения, которых
нет в результатах инструментов. Перепиши ответ: каждую цифру с единицей бери только из ФАКТОВ ниже (или из слов гостя),
неподтверждённые цифры замени на подтверждённые либо убери вместе с выводом из них. Если гость просил характеристику,
которой в ответе нет, а в ФАКТАХ она есть, добавь её коротко, одной строкой, только если она по смыслу относится к вопросу гостя. Структуру, тон и язык сохрани, нового не выдумывай.
Ответь JSON {"text": "..."}."""

_DROP = {"polyline", "photo", "url", "evidence", "facts", "lat", "lon", "observed_at", "valid_until", "conflicts"}


def _slim(o):
    if isinstance(o, dict):
        return {k: _slim(v) for k, v in o.items() if k not in _DROP}
    if isinstance(o, list):
        return [_slim(v) for v in o]
    return o


def digest(outs, limit=16000):
    """Компактные факты для ремонта: выводы инструментов без тяжёлых полей."""
    parts, used = [], 0
    for tool, o in outs:
        s = f"[{tool}] " + json.dumps(_slim(o), ensure_ascii=False, default=str)
        s = s[:5000]
        if used + len(s) > limit:
            break
        parts.append(s)
        used += len(s)
    return "\n".join(parts)


def required_chars(user_texts, llm_parsed=None):
    """Какие характеристики гость запросил: правила из реестра плюс разбор LLM, если он есть."""
    from app import search
    want = {}
    for u in user_texts:
        for c in search.parse_rules(u)["constraints"]:
            want[c["char"]] = c.get("phrase")
    for p in llm_parsed or []:
        for c in (p or {}).get("constraints", []):
            if c.get("char") and c["char"] not in want and _is_known(c["char"]):
                want[c["char"]] = "разбор LLM"
    return want


def _is_known(cid):
    from app import registry
    return registry.get(cid) is not None


def coverage_gate(text, outs, want, query):
    """Характеристики, о которых просил гость, но инструменты их не вернули. Достаёт их детерминированно для
    отелей, о которых ответ. Возвращает (недостающие, новые вызовы trace)."""
    blob = json.dumps([o for _, o in outs], ensure_ascii=False, default=str)
    missing = sorted(c for c in want if c not in blob)
    if not missing:
        return [], []
    ids = list(mentioned_hotels(text).values())[:4]
    if not ids:  # ответ не про конкретные отели: берём верх выдачи по запросу гостя
        ids = [r["hotel"]["id"] for r in actions.search_hotels(query, limit=3)["results"]]
    extra = []
    for hid in ids:
        inp = {"hotel_id": hid, "chars": missing}
        try:
            extra.append({"tool": "hotel_facts", "input": inp, "output": actions.hotel_facts(**inp), "gate": True})
        except Exception:
            continue
    return missing, extra


def repair_text(text, bad, user_texts, outs, missing):
    """Один проход LLM по ответу. Бросает исключение, если LLM недоступна."""
    from app import llm
    issues = "\n".join(f"- «{c['text']}» ({c['kind']}: {c['value'] if c['value'] is not None else 'название'})"
                       for c in bad) or "нет"
    user = ("Сообщения гостя:\n" + "\n".join(user_texts) + "\n\nОтвет помощника:\n" + text +
            "\n\nНеподтверждённые утверждения:\n" + issues +
            ("\n\nХарактеристики, которые просил гость и которых нет в ответе: " + ", ".join(missing) if missing else "") +
            "\n\nФАКТЫ из инструментов:\n" + digest(outs))
    schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
              "additionalProperties": False}
    return llm.json_call(REPAIR_SYSTEM, user, schema, effort="low")["text"]


def _brief(v):
    return {"total": v["total"], "unsupported": v["unsupported"],
            "claims": [{k: c[k] for k in ("kind", "text", "supported", "evidence")} | {"value": c["value"], "unit": c["unit"]}
                       for c in v["claims"]]}


def ground(text, trace, user_texts, llm_parsed=None, can_repair=True, on_repair=None):
    """Полный цикл: проверка, добор недостающих характеристик, один ремонт, зачистка того, что не подтвердилось.
    Возвращает (текст, дополнительные вызовы trace, отчёт)."""
    _replay_cached.cache_clear()  # данные могли измениться с прошлого ответа
    outs = outputs_of(trace)
    v0 = verify(text, trace, user_texts)
    want = required_chars(user_texts, llm_parsed)
    missing, extra = coverage_gate(text, outs, want, user_texts[-1] if user_texts else "")
    trace2 = list(trace) + extra
    rep = {"before": {"total": v0["total"], "unsupported": v0["unsupported"]}, "required": sorted(want),
           "missing": missing, "fetched": [e["input"]["hotel_id"] for e in extra], "repaired": False, "removed": [],
           "repair_error": None}
    bad = [c for c in v0["claims"] if not c["supported"]]
    if (bad or extra) and can_repair:
        if on_repair:
            on_repair()
        try:
            text = repair_text(text, bad, user_texts, outputs_of(trace2), missing if extra else [])
            rep["repaired"] = True
        except Exception as e:  # ремонт не удался: оставляем исходный текст, зачистка ниже всё равно сработает
            rep["repair_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    v1 = verify(text, trace2, user_texts)
    if v1["unsupported"]:
        text, rep["removed"] = strip_unsupported(text, v1["claims"])
        v1 = verify(text, trace2, user_texts)
    rep["after"] = _brief(v1)
    rep["unsupported_fixed"] = v0["unsupported"] - v1["unsupported"] if not rep["removed"] else v0["unsupported"]
    return text, extra, rep
