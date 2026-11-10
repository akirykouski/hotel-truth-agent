"""Поиск по запросу словами.

1. Разбор: LLM переводит запрос в условия над полями реестра (или, без ключа, правила по ключевым словам из
   YAML). Что реестр не покрывает, LLM возвращает в missing — это кандидаты в новые характеристики.
2. Проверка: каждое условие сверяется с итоговым фактом из хранилища → выполнено / не выполнено / не знаем.
3. Три корзины: подходит, возможно (не хватает данных — спросим отельера), не подходит. Внутри — по доле
   выполненных условий с учётом уверенности и веса характеристики в профиле города (app/city.py), затем по рейтингу.
4. Чего реестр не покрывает (missing), копится в профиле города как параметр-кандидат со спросом.
"""
import copy
import hashlib
import json
import re

from app import geodata as gd
from app import city, llm, qsem, region, registry, relax, store
from app.tools.sun import MONTHS_RU

OPS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b, "<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b,
       "<": lambda a, b: a < b, ">": lambda a, b: a > b}
MONTH_WORDS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма[йяе]": 5, "июн": 6, "июл": 7, "август": 8,
               "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12, "летом": 7, "зимой": 1, "весной": 4,
               "осенью": 10, "в сезон": 7, "бархатн": 9}


def _schema(session=None):
    chars = list(registry.public_chars(session))
    return {
        "type": "object", "additionalProperties": False,
        "required": ["constraints", "month", "base", "missing", "intent"],
        "properties": {
            "intent": {"type": "string", "description": "одна фраза: что ищет человек"},
            "month": {"type": ["integer", "null"], "description": "месяц поездки 1–12, если понятен"},
            "constraints": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["char", "field", "op", "value", "must", "phrase"],
                "properties": {
                    "char": {"type": "string", "enum": chars}, "field": {"type": "string"},
                    "op": {"type": "string", "enum": list(OPS)},
                    "value": {"type": ["boolean", "number", "string"]},
                    "must": {"type": "boolean", "description": "true — обязательное, false — пожелание"},
                    "phrase": {"type": "string", "description": "кусок запроса, из которого условие"}}}},
            "base": {"type": "object", "additionalProperties": False,
                     "required": ["max_price", "min_stars", "min_rating"],
                     "properties": {"max_price": {"type": ["number", "null"]}, "min_stars": {"type": ["integer", "null"]},
                                    "min_rating": {"type": ["number", "null"]}}},
            "missing": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["phrase", "proposal"],
                "properties": {"phrase": {"type": "string"},
                               "proposal": {"type": "string", "description": "описание новой характеристики словами"}}}},
        },
    }


THRESHOLDS = ("Числа ставь разумные: «близко к морю» — minutes_there <= 12, «рядом» — 10 минут пешком, "
              "«без подъёма» — climb_back_m <= 25, «тихо» — quiet == true.")

SYSTEM = """Ты разбираешь запрос путешественника про отели {label_in} в условия над характеристиками реестра.
Используй только характеристики и поля из списка. """ + THRESHOLDS + """
Обязательные условия — то, что человек явно требует; пожелания — «хорошо бы», «желательно».
Если в запросе есть важная для человека вещь, которой нет в реестре, положи её в missing с описанием
новой характеристики (что измерять, откуда можно взять данные). Ничего не выдумывай про отели.

Характеристики:
{chars}"""


# Потребности, которых нет в реестре: без LLM по ним нельзя ничего проверить, поэтому честно говорим об этом.
# (регулярка, как называем, описание новой характеристики)
MISSING_SEEDS = [
    (r"бассейн", "бассейн", "в отеле есть бассейн"),
    (r"аквапарк", "аквапарк", "рядом есть аквапарк"),
    (r"балкон|терраса|террасу", "балкон", "в номере есть балкон или терраса"),
    (r"\bспа\b|спа-центр|сауна|баня|хаммам|джакузи", "спа", "в отеле есть спа или сауна"),
    (r"завтрак|шведск\w+ стол|всё включено|все включено", "завтрак", "в стоимость входит завтрак"),
    (r"кухн|холодильник|микроволновк|посудомо|стиральн\w+ машин", "кухня", "в номере есть кухня или мини-кухня"),
    (r"трансфер|встреча в аэропорт", "трансфер", "отель организует трансфер из аэропорта"),
    (r"кондиционер", "кондиционер", "в номере есть кондиционер"),
    (r"фитнес|тренажёрн|тренажерн|спортзал", "фитнес", "в отеле есть тренажёрный зал"),
    (r"детск\w+ клуб|аниматор|анимаци", "детский клуб", "в отеле есть детский клуб или анимация"),
    (r"собственн\w+ пляж|свой пляж", "свой пляж", "у отеля есть собственный пляж"),
]
_NUM_PLURALS = {"мест": ("место", "места", "мест")}


def plural(n, one, few, many):
    """1 отель, 2 отеля, 5 отелей."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


_ROAD_RU = {"trunk": "магистраль", "trunk_link": "съезд с магистрали", "primary": "оживлённая улица",
            "primary_link": "съезд с оживлённой улицы", "secondary": "городская улица",
            "secondary_link": "съезд с городской улицы", "tertiary": "местная улица",
            "tertiary_link": "съезд с местной улицы", "unclassified": "второстепенная улица",
            "residential": "жилая улица"}
# заведения: только как вид источника шума, в начале перечня («..., bar Light в 14 м»)
_VENUE_RU = {"bar": "бар", "pub": "паб", "nightclub": "ночной клуб", "karaoke_box": "караоке", "music_venue": "концертная площадка"}
# теги OSM и карточки, которые не должны доходить до гостя; ключи в нижнем регистре, как отдают инструменты
_TAG_RU = {"cafe": "кафе", "restaurant": "ресторан", "fast_food": "фастфуд", "pharmacy": "аптека", "hospital": "больница",
           "clinic": "поликлиника", "doctors": "врач", "parking": "парковка", "charging_station": "зарядка",
           "kindergarten": "детский сад", "pets-allowed": "размещение с животными", "soundproofing": "шумоизоляция",
           "supermarket": "супермаркет", "convenience": "магазин у дома", "playground": "детская площадка"}
_DIR_RU = {"С": "север", "СВ": "северо-восток", "В": "восток", "ЮВ": "юго-восток", "Ю": "юг", "ЮЗ": "юго-запад",
           "З": "запад", "СЗ": "северо-запад"}
_SUN = r"\((—|[СЮВЗ]{1,2}), (не виден|с (\d+)-го эт\.)\)"


def _sunset(m):
    """«закат летом (—, не виден), зимой (ЮЗ, с 3-го эт.)» словами, с полными сторонами света."""
    def part(dr, tail, fl):
        if dr == "—" or tail == "не виден":
            return None
        return f"из окон на {_DIR_RU.get(dr, dr)} с {fl}-го этажа"
    summer, winter = part(m[1], m[2], m[3]), part(m[4], m[5], m[6])
    if summer is None and winter is None:
        return "закат из окон не виден ни летом, ни зимой"
    a = "летом закат из окон не виден" if summer is None else f"летом закат виден {summer}"
    b = "зимой не виден" if winter is None else f"зимой виден {winter}"
    return f"{a}; {b}"


def ru_text(t):
    """Тексты фактов из хранилища для человека: десятичная запятая, «3 места», классы дорог и теги OSM словами,
    без длинных тире, закат словами."""
    if not isinstance(t, str):
        return t
    t = re.sub(r"закат летом " + _SUN + ", зимой " + _SUN, _sunset, t)
    t = re.sub(r"([\d,]+)\.00 RUB", lambda m: f"{int(m[1].replace(',', '')):,}".replace(",", " ") + " ₽", t)
    t = re.sub(r"(?<=\d)\.(?=\d)", ",", t)
    t = re.sub(r"(\d+) мест(?![а-яё])", lambda m: f"{m.group(1)} {plural(m.group(1), *_NUM_PLURALS['мест'])}", t)
    # дорога primary Курортный проспект в 80 м -> оживлённая улица (Курортный проспект) в 80 м
    t = re.sub(r"дорога (\w+)(?: ([^,;]+?))?(?= в \d+ м)",
               lambda m: _ROAD_RU.get(m[1], "дорога") + (f" ({m[2]})" if m[2] else "") if m[1] in _ROAD_RU else m[0], t)
    t = re.sub(r"дорога (\w+) \(", lambda m: _ROAD_RU[m[1]] + " (" if m[1] in _ROAD_RU else m[0], t)
    t = re.sub(r"(^|[:,;(] ?)(bar|pub|nightclub|karaoke_box|music_venue)(?=[ ,;)]|$)",
               lambda m: m[1] + _VENUE_RU[m[2]], t)
    t = re.sub(r"(?<![\w-])(" + "|".join(map(re.escape, _TAG_RU)) + r")(?![\w-])", lambda m: _TAG_RU[m[1]], t)
    t = t.replace("парковок OSM", "парковок на карте").replace("по OSM", "по карте").replace("OSM", "карты")
    t = re.sub(r"(?<=: )пляж: |^пляж: ", "", t)
    t = re.sub(r"Мы посчитали по карте высот и соседним зданиям: море видно со стороны None начиная с None-го этажа\.",
               "Мы посчитали по карте высот и соседним зданиям: море из окон закрыто.", t)
    return t.replace(" — ", ": ").replace("—", "-")


_ANSWER_LABELS = {"fee_rub": "доплата, ₽", "animals": "какие животные", "notes": "комментарий", "categories": "категории номеров",
                  "quiet_categories": "самые тихие категории номеров"}


def field_view(char_id, parsed):
    """Разобранный ответ отельера как пары «поле: значение» с подписями из реестра."""
    spec = registry.get(char_id) or {}
    out = []
    for k, v in (parsed or {}).items():
        if v is None or v == "" or k.startswith("_"):
            continue
        if k == "certainty":
            out.append({"label": "уверенность отельера", "value": str(v)})
            continue
        f = {**(spec.get("answer_fields") or {}).get(k, {}), **(spec.get("fields") or {}).get(k, {})}
        label, _, unit = re.sub(r"\s*\([^)]*\)", "", f.get("label") or _ANSWER_LABELS.get(k) or k).partition(",")
        val = ("да" if v else "нет") if isinstance(v, bool) else f"{v:g}".replace(".", ",") if isinstance(v, (int, float)) else str(v)
        out.append({"label": label.strip(), "value": f"{val} {unit.strip()}" if unit and not isinstance(v, bool) else val})
    return out


_OPS_RU = {"<=": "≤", ">=": "≥", "<": "<", ">": ">", "==": "", "!=": "≠"}


def constraint_label(c):
    """Условие человеческими словами из подписи поля реестра: «до пляжа ≤ 15 мин», «закат виден из окна»."""
    spec = registry.get(c.get("char")) or {}
    f = (spec.get("fields") or {}).get(c.get("field")) or {}
    label = re.sub(r"\s*\([^)]*\)", "", f.get("label") or spec.get("name") or c.get("char") or "")
    v, op = c.get("value"), c.get("op")
    if isinstance(v, bool):
        want = v if op == "==" else not v
        if want:
            return label
        return "не " + label if label.startswith("надо ") else "нет: " + label
    if isinstance(v, (int, float)):
        label, _, unit = label.partition(",")
        unit = unit.strip()
        if label.startswith("минут "):
            label, unit = re.sub(r"^минут (пешком )?", "", label), "мин"
        num = f"{v:g}".replace(".", ",")
        return f"{label.strip()} {_OPS_RU.get(op, op)} {num}{' ' + unit if unit else ''}"
    return f"{label}: {v}"


def _annotate(parsed):
    """Каждому условию подпись для людей (общая для интерфейса и текстового ответа)."""
    for c in parsed.get("constraints", []):
        c["label"] = constraint_label(c)
    return parsed


def _month(text):
    t = text.lower()
    for w, m in MONTH_WORDS.items():
        if re.search(w, t):
            return m
    return None


def _flip(spec, c):
    """«Не у моря»: для числового поля «чем меньше, тем лучше» условие переворачивается (минут до пляжа > 15), иначе None."""
    f = (spec.get("fields") or {}).get(c.get("field")) or {}
    if f.get("type") == "number" and f.get("better") == "lower" and c.get("op") in ("<=", "<") and isinstance(c.get("value"), (int, float)):
        return c | {"op": ">" if c["op"] == "<=" else ">=", "flipped": True}
    return None


def parse_rules(text, session=None):
    """Разбор без LLM: ключевые слова и фразы из YAML-реестра."""
    t = text.lower()
    cons, covered, ignored, hits = [], [], [], []
    for cid, spec in registry.public_chars(session).items():
        for phr, c in (spec.get("phrases") or {}).items():
            m = re.search(phr, t)
            if m:
                covered.append(m.span())
                mk = qsem.negation(t, m.span())
                if mk:  # «не нужен вид на море»: условия нет, но мы это запомнили; «не у моря»: условие наоборот
                    fc = _flip(spec, c) if qsem.polar(mk) else None
                    if fc:
                        cons.append({"char": cid, **fc, "must": True, "phrase": phr})
                    else:
                        ignored.append(qsem.ignored_entry(t, m.span(), cid))
                    continue
                cons.append({"char": cid, **c, "must": True, "phrase": phr})
                hits.append({"cid": cid, "span": m.span()})
                if cid == "beach_walk" and c.get("field") == "minutes_there" and c.get("value") == 15:
                    # число гостя из собственной фразы условия («пляж 5 минут», «10 минут до моря»), не из первых «мин» запроса
                    n = re.search(r"(\d+)\s*мин", t[max(0, m.start() - 8):m.end()])
                    if n:
                        cons[-1]["value"] = int(n.group(1))
        for kw in spec.get("keywords", []):
            i = t.find(kw.lower())
            if i >= 0:
                sp = (i, i + len(kw))
                covered.append(sp)
                mk = qsem.negation(t, sp)
                if mk:
                    fc = _flip(spec, spec["default_constraint"]) if qsem.polar(mk) and spec.get("default_constraint") else None
                    if fc:
                        if not any(c["char"] == cid and c.get("flipped") for c in cons):
                            cons.append({"char": cid, **fc, "must": True, "phrase": kw})
                    elif not any(g["char"] == cid for g in ignored):
                        ignored.append(qsem.ignored_entry(t, sp, cid))
                    continue
                hits.append({"cid": cid, "span": sp})
                if spec.get("default_constraint") and not any(c["char"] == cid for c in cons):
                    cons.append({"char": cid, **spec["default_constraint"], "must": True, "phrase": kw})
    pets = registry.public_chars(session).get("pets")
    pb = qsem.pet_hit(t) if pets and not any(c["char"] == "pets" for c in cons) else None
    if pb and not qsem.negation(t, pb[0]):  # «овчарка» без слова «собака»: это тоже поездка с питомцем
        cons.append({"char": "pets", **pets["default_constraint"], "must": True, "phrase": pb[1]})
        hits.append({"cid": "pets", "span": pb[0]})
        covered.append(pb[0])
    seen_c = {}
    for c in cons:  # два условия на одно поле («рядом с пляжем» и «5 минут до моря»): остаётся строже
        k = (c["char"], c["field"], c["op"])
        if k in seen_c and c["op"] == "<=" and isinstance(c["value"], (int, float)):
            seen_c[k]["value"] = min(seen_c[k]["value"], c["value"])
            c["_dup"] = True
        else:
            seen_c.setdefault(k, c)
    cons = [c for c in cons if not c.pop("_dup", False)]
    ignored = [g for g in ignored if not any(c["char"] == g["char"] for c in cons)]
    base = {"max_price": None, "min_stars": None, "min_rating": None}
    m = re.search(r"до\s*(\d[\d\s]{2,})\s*(?:₽|руб|р\b)", t)
    if m:
        base["max_price"] = float(m.group(1).replace(" ", ""))
        covered.append(m.span())
    m = re.search(r"(\d)\s*(?:\*|зв[её]зд)", t)
    if m:
        base["min_stars"] = int(m.group(1))
        covered.append(m.span())
    for w in MONTH_WORDS:
        m = re.search(w, t)
        if m:
            covered.append(m.span())
    missing, seen = [], set()
    for pat, name, proposal in MISSING_SEEDS:
        m = re.search(pat, t)
        if m and name not in seen and not any(a < m.end() and m.start() < b for a, b in covered):
            seen.add(name)
            if qsem.negation(t, m.span()):
                ignored.append(qsem.ignored_entry(t, m.span(), None))
                covered.append(m.span())
                continue
            missing.append({"phrase": name, "proposal": proposal})
            covered.append(m.span())
    from app import compiler  # шаблоны компилятора, которых нет в реестре (и в черновиках сессии): тоже кандидаты в missing
    known = {c["char"] for c in cons} | set(registry.public_chars(session))
    for c in compiler.candidates(text):
        i = t.find(c["phrase"])
        if {c["id"], c["id"] + "_custom"} & known or any(a < i + len(c["phrase"]) and i < b for a, b in covered):
            continue
        covered.append((i, i + len(c["phrase"])))
        if i >= 0 and qsem.negation(t, (i, i + len(c["phrase"]))):
            ignored.append(qsem.ignored_entry(t, (i, i + len(c["phrase"])), None))
            continue
        missing.append({"phrase": c["phrase"], "proposal": c["proposal"]})
    for q in qsem.qualifiers(t, hits):  # уточнения («веганский», «12 кг»), которых реестр не проверяет: условие остаётся, но не закрыто
        if not any(q["phrase"].lower() in x["phrase"].lower() or x["phrase"].lower() in q["phrase"].lower() for x in missing):
            missing.append(q)
    if not (off := qsem.off_region(text)):  # части фразы, где ничего не распознано: честно в missing, а не молча теряем
        for a, b in qsem.leftover(t, covered + [h["span"] for h in hits]):
            ph = text[a:b].strip()
            if not any(ph.lower() in x["phrase"].lower() or x["phrase"].lower() in ph.lower() for x in missing):
                missing.append({"phrase": ph, "proposal": f"{ph}: такого условия в реестре пока нет"})
    if not cons and not missing and not any(base.values()) and not ignored:
        # слова есть, а понять нечего: честно говорим «этого мы пока не знаем», вместо пустой выдачи без объяснения
        q = " ".join(text.split())
        if q:
            missing.append({"phrase": q[:80], "proposal": q})
    out = {"intent": text, "month": _month(text), "constraints": cons, "base": base, "missing": missing,
           "ignored": ignored, "parser": "rules"}
    if off:
        out["off_region"] = off
    return out


def _guard(parsed, text, session=None):
    """Те же защиты от смысла, что у правил, для разбора LLM и агента: снять условия, которые гость отменил («не нужен
    вид на море»), добавить в missing уточнения без поля в реестре и пометить другой город. Работает на тексте запроса."""
    parsed = copy.deepcopy(parsed)
    r = parse_rules(text, session)
    gone = {g["char"] for g in r["ignored"] if g.get("char")}
    keep = {c["char"] for c in r["constraints"]}
    parsed["ignored"] = list(parsed.get("ignored") or [])
    for c in list(parsed.get("constraints") or []):
        ph = (c.get("phrase") or "").lower()
        i = text.lower().find(ph) if ph else -1
        mk = qsem.negation(text.lower(), (i, i + len(ph))) if i >= 0 else None
        by_phrase = bool(mk)
        fc = _flip(registry.get(c.get("char")) or {}, c) if qsem.polar(mk) else None
        if fc:  # «не у моря» в разборе LLM: условие наоборот, а не требование
            parsed["constraints"][parsed["constraints"].index(c)] = fc
            continue
        if (c.get("char") in gone and c.get("char") not in keep) or by_phrase:
            parsed["constraints"].remove(c)
            e = next((g for g in r["ignored"] if g.get("char") == c.get("char")), None) or \
                qsem.ignored_entry(text.lower(), (i, i + len(ph)), c.get("char"))
            parsed["ignored"].append(e)
    for g in r["ignored"]:
        if g not in parsed["ignored"] and not any(x.get("char") == g.get("char") and g.get("char") for x in parsed["ignored"]):
            parsed["ignored"].append(g)
    t = text.lower()
    cons = parsed.get("constraints") or []
    # LLM иногда кладёт в missing ту же фразу, что уже стала условием («не у моря»): гостю это читается как «не учли»
    miss = [m for m in parsed.get("missing") or []
            if not any(c.get("phrase") and str(c["phrase"]).lower() in str(m.get("phrase", "")).lower() for c in cons)]
    for q in qsem.qualifiers(t, [{"cid": c["char"], "span": _find(t, c)} for c in parsed.get("constraints") or []]):
        if not any(q["phrase"].lower() in x["phrase"].lower() or x["phrase"].lower() in q["phrase"].lower() for x in miss):
            miss.append(q)
    for x in r["missing"]:  # части фразы без распознанного условия (правила их видят, LLM мог пропустить)
        a = t.find(x["phrase"].lower())
        if x["proposal"].endswith("реестре пока нет") and a >= 0 and not any(
                _find(t, c)[0] < a + len(x["phrase"]) and a < _find(t, c)[1] for c in parsed.get("constraints") or []) \
                and not any(x["phrase"].lower() in m["phrase"].lower() for m in miss):
            miss.append(x)
    parsed["missing"] = miss
    off = qsem.off_region(text)
    if off:
        parsed["off_region"] = off
    return parsed


def _find(t, c):
    """Где в запросе условие LLM: по его phrase, иначе по ключевым словам характеристики; (0, 0) — не нашли."""
    ph = (c.get("phrase") or "").lower()
    if ph and ph in t:
        i = t.find(ph)
        return (i, i + len(ph))
    spec = registry.get(c.get("char")) or {}
    for kw in spec.get("keywords", []):
        i = t.find(kw.lower())
        if i >= 0:
            return (i, i + len(kw))
    return (0, 0)


def _parse_key(text, session, system):
    """Ключ кэша разбора: текст без регистра и лишних пробелов, отпечаток реестра (публичные характеристики вместе
    с черновиками сессии: id, ключевые слова, поля), промпт, модель и сессия."""
    chars = {cid: [s.get("keywords"), s["fields"], s["description"].strip().splitlines()[0]]
             for cid, s in registry.public_chars(session).items()}
    fp = json.dumps([chars, system, llm.MODEL, llm.PROVIDER, session or ""], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256((" ".join(text.lower().split()) + "\x00" + fp).encode()).hexdigest()


def parse(text, session=None):
    if llm.available():
        try:
            system = SYSTEM.format(chars=registry.describe_for_llm(session), label_in=region.META["label_in"])
            key = None
            try:
                key = _parse_key(text, session, system)
                hit = store.parse_cache_get(key)
                if hit is not None:
                    return _guard(hit, text, session)
            except Exception:  # кэш не должен ломать разбор
                key = None
            out = llm.json_call(system, text, _schema(session), effort="low")
            out["parser"] = "llm"
            if out.get("month") is None:
                out["month"] = _month(text)
            if key:
                try:
                    store.parse_cache_put(key, text, out)
                except Exception:
                    pass
            return _guard(out, text, session)
        except Exception as e:  # LLM недоступна — работаем на правилах, но честно говорим об этом
            r = parse_rules(text, session)
            r["parser"] = f"rules (LLM: {type(e).__name__})"
            return r
    return parse_rules(text, session)


def _coerce(f, op, v):
    """Значение условия под тип поля реестра или ValueError."""
    t = f.get("type")
    if t == "bool":
        if isinstance(v, str) and v.lower() in ("true", "false"):
            v = v.lower() == "true"
        if not isinstance(v, bool) or op not in ("==", "!="):
            raise ValueError("bool: нужны ==/!= и true/false")
    elif t == "number":
        if isinstance(v, str):
            v = float(v.replace(",", "."))
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("number: нужно число")
    else:
        if not isinstance(v, str) or op not in ("==", "!=") or (f.get("values") and v not in f["values"]):
            raise ValueError("enum/text: нужно значение из списка и ==/!=")
    return v


WISH_RX = re.compile(r"хорошо бы|желательн|по возможности|если (?:можно|получится|будет)|не обязательн|было бы (?:неплохо|хорошо|здорово)|в идеале|по желанию|бонусом", re.I)


def parse_agent(text, constraints, month=None, base=None, missing=None, session=None):
    """Условия, которые агент уже разобрал сам (та же форма, что у разбора LLM). Каждое проверяется по реестру
    (характеристика видна сессии, поле есть, оператор и значение подходят типу). Возвращает (parsed, отклонённые);
    при любом отклонённом или пустом списке parsed = None, поиск вернётся к обычному разбору."""
    pub = registry.public_chars(session)
    good, bad = [], []
    for i, c in enumerate(constraints or []):
        try:
            spec = pub.get(c.get("char"))
            if spec is None:
                raise ValueError(f"нет характеристики {c.get('char')}")
            f = spec["fields"].get(c.get("field"))
            if f is None:
                raise ValueError(f"нет поля {c.get('char')}.{c.get('field')}")
            op = c.get("op", "==")
            if op not in OPS:
                raise ValueError(f"оператор {op}")
            good.append({"char": c["char"], "field": c["field"], "op": op, "value": _coerce(f, op, c.get("value", True)),
                         "must": bool(c.get("must", True)), "phrase": str(c.get("phrase") or "")})
        except (ValueError, TypeError, AttributeError) as e:
            bad.append({"idx": i, "item": c, "why": str(e)})
    if bad or not good:
        return None, bad
    # то же правило, что у разбора LLM: пожелание только там, где гость сам смягчил («хорошо бы», «желательно»)
    if not WISH_RX.search(text):
        for c in good:
            if not c["must"]:
                c["must"], c["guard"] = True, "no_wish_words"
    # страховка: явные требования, которые правила видят по словам гостя, агент не может потерять или смягчить
    # если гость сам что-то смягчил, правила не знают, что именно: тогда они только добавляют забытое, и как пожелание
    wishes = bool(WISH_RX.search(text))
    rules = parse_rules(text, session)
    for rc in rules["constraints"]:
        mine = [c for c in good if c["char"] == rc["char"]]
        if not mine:
            good.append(rc | {"guard": "rules"} | ({"must": False} if wishes else {}))
        elif not wishes and rc.get("must", True) and not any(c["must"] for c in mine):
            for c in mine:
                c["must"], c["guard"] = True, "rules"
    b = {k: v for k, v in (rules["base"] or {}).items() if v is not None} | {k: v for k, v in (base or {}).items() if v}
    try:
        nb = {"max_price": float(b["max_price"]) if b.get("max_price") else None,
              "min_stars": int(b["min_stars"]) if b.get("min_stars") else None,
              "min_rating": float(b["min_rating"]) if b.get("min_rating") else None}
        m = int(month) if month else None
    except (ValueError, TypeError, KeyError):
        return None, [{"idx": None, "item": {"month": month, "base": base}, "why": "month/base не числа"}]
    if m is not None and not 1 <= m <= 12:
        return None, [{"idx": None, "item": {"month": month}, "why": "month вне 1-12"}]
    miss = [{"phrase": str(x.get("phrase", "")), "proposal": str(x.get("proposal", ""))}
            for x in missing or [] if isinstance(x, dict) and x.get("phrase")] or parse_rules(text, session)["missing"]
    return _guard({"intent": text, "month": m or _month(text), "constraints": good, "base": nb, "missing": miss,
                   "parser": "agent"}, text, session), []


def _field_value(spec, value, field, month):
    f = spec["fields"].get(field, {})
    if f.get("per_month"):
        bym = (value or {}).get(f.get("path", "by_month")) or {}
        if month:
            return (bym.get(str(month)) or {}).get(field)
        vals = [m.get(field) for m in bym.values() if m.get(field) is not None]
        if f["type"] == "bool":
            return any(vals) if vals else None
        return min(vals) if vals and f.get("better") == "lower" else (max(vals) if vals else None)
    return (value or {}).get(field)


def check(hotel_id, c, month, cache):
    spec = registry.get(c["char"])
    if spec is None or c["field"] not in spec["fields"]:
        return {"status": "unknown", "why": f"нет поля {c['char']}.{c['field']}", **c}
    if c["char"] not in cache:
        cache[c["char"]] = store.resolve(hotel_id, spec)
    r = cache[c["char"]]
    c = {**c, "label": c.get("label") or constraint_label(c)}
    if r["status"] == "unknown":
        return {**c, "status": "unknown", "name": spec["name"], "why": "данных нет",
                "confidence": 0.0}
    v = _field_value(spec, r["value"], c["field"], month)
    if v is None:
        return {**c, "status": "unknown", "name": spec["name"], "why": r.get("summary"),
                "source": r.get("source_label"), "confidence": r["confidence"]}
    try:
        ok = OPS[c["op"]](v, c["value"])
    except TypeError:
        ok = None
    conf = spec["fields"][c["field"]].get("confirm_any")
    if ok and conf and c["op"] == "==" and c["value"] is True and not any((r["value"] or {}).get(k) is True for k in conf):
        # низкое здание без лифта: «подходит» только по этажности, а вход без ступенек знает один отельер
        return {**c, "status": "unknown", "name": spec["name"], "source": r.get("source_label"), "confidence": r["confidence"],
                "why": (r.get("summary") or "") + ": лифт и вход без ступенек не подтверждены, это знает отельер"}
    weak = r["confidence"] < 0.5 or r["status"] == "conflict"
    return {**c, "status": "unknown" if ok is None else ("pass" if ok else "fail"), "weak": weak, "actual": v,
            "name": spec["name"], "why": r.get("summary"), "source": r.get("source_label"),
            "confidence": r["confidence"], "conflict": r["status"] == "conflict", "observed_at": r.get("observed_at")}


def _price_txt(h):
    return f"{int(h['price_nov1']):,}".replace(",", " ") + f" ₽ на {qsem.PRICE_DAY_RU}"


def _base_ok(h, base, month=None):
    """Жёсткие отказы по базовым условиям. Цена в карточке на одну дату (1 ноября): если гость назвал другой месяц,
    превышение бюджета не отказ, а «уточните» (см. _base_soft)."""
    why = []
    if base.get("max_price") and (month in (None, qsem.PRICE_MONTH)):
        if h["price_nov1"] is None:
            why.append("нет цены на даты")
        elif h["price_nov1"] > base["max_price"]:
            why.append(f"дороже бюджета ({_price_txt(h)})")
    if base.get("min_stars") and (h["stars"] or 0) < base["min_stars"]:
        why.append("меньше звёзд")
    if base.get("min_rating") and (h["rating"]["total"] or 0) < base["min_rating"]:
        why.append("рейтинг ниже")
    return why


def _base_soft(h, base, month):
    """Бюджет при месяце не 1 ноября: цену на даты гостя мы не знаем."""
    if not base.get("max_price") or month in (None, qsem.PRICE_MONTH):
        return []
    if h["price_nov1"] is None:
        return ["цены на ваши даты нет, уточните на Островке"]
    over = " выше бюджета" if h["price_nov1"] > base["max_price"] else " в бюджете"
    return [f"{_price_txt(h)}{over}, на ваши даты уточните"]


def _caveats(parsed, price_note=None):
    """Чего мы не проверили: пока список не пуст, нельзя говорить «все условия выполнены»."""
    out = []
    off = parsed.get("off_region")
    if off:
        out.append(f"вы спросили про «{off['asked']}», а отели у нас в регионе «{off['active']}»")
    out += [f"не умеем проверить: {m['phrase']}" for m in parsed.get("missing") or []]
    if price_note:
        out.append(price_note)
    return out


def search(text, limit=10, parsed=None, drop=None, loosen=None, session=None):
    """drop — номера (idx) или имена характеристик условий, которые не учитывать; loosen — {idx: новый порог}.
    parsed можно передать готовый, чтобы не разбирать запрос заново. session — сессия, видящая свои черновики."""
    parsed, dropped, loosened = relax.prepare(parsed or parse(text, session), drop, loosen)
    parsed = _annotate(parsed)
    parsed.setdefault("ignored", [])
    if "off_region" not in parsed and (off := qsem.off_region(text)):
        parsed["off_region"] = off
    month = parsed.get("month")
    geo = gd.load()
    base = parsed.get("base") or {}
    price_note = qsem.price_info(base, month)
    if price_note:
        base["price_date"] = qsem.PRICE_DATE
    common = {"ignored": parsed["ignored"], "price_note": price_note, "off_region": parsed.get("off_region"),
              "caveats": _caveats(parsed, price_note)}
    if parsed.get("off_region"):
        # другой город: отели Сочи не выдаём за ответ, пустая выдача и объяснение
        off = parsed["off_region"]
        store.log_query(text, {"constraints": [], "month": month}, parsed.get("missing"))
        return {"query": text, "parsed": parsed, "month": month, "month_name": MONTHS_RU.get(month),
                "counts": {"match": 0, "maybe": 0, "fail": 0, "unchecked": len(geo.hotels)},
                "results": [], "near_misses": [], "nothing_to_check": True, "dropped": dropped, "loosened": loosened,
                "message": (f"{off['asked']} мы уже собрали отдельно, но в поиск этот район пока не включён. Сейчас в поиске "
                            f"«{off['active']}», и эти отели мы не покажем как ответ про «{off['asked']}»." if off.get("region") else
                            f"Вы спросили про «{off['asked']}», а у нас отели только в регионе «{off['active']}». "
                            "Показывать их как ответ про другой город не будем."), **common}
    if not parsed["constraints"] and not any(base.get(k) for k in ("max_price", "min_stars", "min_rating")):
        # проверять нечем: не раскладываем все отели по корзинам «подходит»
        counts = {"match": 0, "maybe": 0, "fail": 0, "unchecked": len(geo.hotels)}
        _log(text, parsed, [], month)
        return {"query": text, "parsed": parsed, "month": month, "month_name": MONTHS_RU.get(month), "counts": counts,
                "results": [], "near_misses": [], "nothing_to_check": True,
                "dropped": dropped, "loosened": loosened, **common}
    rows = []
    cw = {c["char"]: _city_factor(c["char"]) for c in parsed["constraints"]}
    for h in geo.hotels:
        cache = {}
        checks = [check(h["id"], c, month, cache) for c in parsed["constraints"]]
        base_fail = _base_ok(h, parsed.get("base") or {}, month)
        base_soft = _base_soft(h, parsed.get("base") or {}, month)
        must = [x for x in checks if x.get("must", True)]
        fails = [x for x in must if x["status"] == "fail"] + [{"status": "fail", "why": w} for w in base_fail]
        unknown = [x for x in must if x["status"] == "unknown"] + [{"status": "unknown", "why": w} for w in base_soft]
        bucket = "fail" if fails else ("maybe" if unknown else "match")
        score = sum((x.get("confidence") or 0.3) * (1.0 if x["status"] == "pass" else 0.0) * cw.get(x["char"], 1.0)
                    for x in checks)
        # среди подходящих выше те, у кого запас по числовому условию больше (5 минут до пляжа лучше 14)
        for x in checks:
            if x["status"] == "pass" and isinstance(x.get("actual"), (int, float)) and not isinstance(x["actual"], bool) \
                    and isinstance(x.get("value"), (int, float)) and x["value"]:
                if x["op"] in ("<=", "<"):
                    score += 0.3 * max(0.0, 1 - x["actual"] / x["value"])
                elif x["op"] in (">=", ">"):
                    score += 0.3 * min(1.0, x["actual"] / x["value"] - 1)
        score += 0.05 * (h["rating"]["total"] or 0) / 10
        rows.append({"hotel": _brief(h), "bucket": bucket, "score": round(score, 3), "checks": checks,
                     "base_fail": base_fail, "base_soft": base_soft, "n_fail": len(fails),
                     "_over": any("выше бюджета" in w for w in base_soft)})
    order = {"match": 0, "maybe": 1, "fail": 2}
    rows.sort(key=lambda r: (order[r["bucket"]], r["n_fail"], r["_over"], -r["score"]))
    counts = {b: sum(1 for r in rows if r["bucket"] == b) for b in order}
    _log(text, parsed, parsed["constraints"], month)
    out = {"query": text, "parsed": parsed, "month": month, "month_name": MONTHS_RU.get(month), "counts": counts,
           "results": rows[:limit], "near_misses": [r for r in rows if r["bucket"] == "fail"][:3] if counts["match"] == 0 else [],
           "dropped": dropped, "loosened": loosened, "nothing_to_check": False, **common}
    if counts["match"] < relax.FEW:
        out["relaxations"] = relax.compute(rows, parsed)
        out["pareto"] = relax.pareto(rows, month)
    return out


def _city_factor(char_id):
    """Вклад условия в порядок внутри корзины: 0,25 + 0,75 × вес в профиле города; без профиля 1."""
    w = city.weight(char_id)
    return 1.0 if w is None else 0.25 + 0.75 * w


def _covered(text, constraints):
    """Куски запроса, ставшие условиями (phrase бывает regex из реестра): их слова профиль города не считает пробелом."""
    out = []
    for c in constraints:
        ph = c.get("phrase")
        if not ph:
            continue
        try:
            m = re.search(ph, text.lower())
        except re.error:
            m = None
        out.append(m.group(0) if m else ph)
    return out


def _log(text, parsed, constraints, month):
    """Журнал запросов и профиль города: недостающее копится в кандидатах, пометки спроса уходят в parsed.missing."""
    try:
        parsed["missing"] = city.note_missing(text, parsed.get("missing"), covered=_covered(text, constraints))
    except Exception:  # профиль города не должен ломать поиск
        pass
    store.log_query(text, {"constraints": constraints, "month": month}, parsed.get("missing"))


def _brief(h):
    return {"id": h["id"], "name": h["name"], "kind": h["kind"], "stars": h["stars"], "address": h["address"],
            "lat": h["lat"], "lon": h["lon"], "rating": h["rating"]["total"], "reviews": h["rating"]["count"],
            "price_nov1": h["price_nov1"], "photo": (h["photos"] or [None])[0], "url": h["url"]}


def explain(row):
    """Человеческие строки «почему подходит / в чём не дотягивает / что неизвестно» и те же факты короткими чипами."""
    good, bad, unk, chips = [], [], [], []
    for c in row["checks"]:
        # источник и уверенность в строку не пишем: они есть полями чипа (source, confidence) для подсказок
        line = ru_text(f"{c.get('name', c['char'])}: {c.get('why') or c.get('label')}")
        st = c["status"]
        if st == "pass":
            weak = c.get("weak")
            (unk if weak else good).append(line + (" ⚠ источники расходятся" if c.get("conflict") else ""))
            st = "unknown" if weak else "pass"
        elif st == "fail":
            bad.append(line)
        else:
            unk.append(line)
        chips.append({"status": st, "text": c.get("label") or c.get("name"), "full": line,
                      "confidence": c.get("confidence") or 0.0, "char": c.get("char"), "field": c.get("field"),
                      "op": c.get("op"), "value": c.get("value"), "must": c.get("must", True), "actual": c.get("actual"),
                      "weak": bool(c.get("weak")), "conflict": bool(c.get("conflict")), "source": c.get("source")})
    for w in row.get("base_fail", []):
        bad.append(w)
        chips.append({"status": "fail", "text": w, "full": w, "confidence": 1.0})
    for w in row.get("base_soft", []):
        unk.append(w)
        chips.append({"status": "unknown", "text": w, "full": w, "confidence": 0.0})
    return {"good": good, "bad": bad, "unknown": unk, "chips": chips}


def compare(hotel_ids, char_ids=None, month=None):
    chars = char_ids or list(registry.public_chars())
    out = {"hotels": [], "rows": []}
    geo = gd.load()
    for hid in hotel_ids:
        out["hotels"].append(_brief(geo.hotel_by_id[hid]))
    for cid in chars:
        spec = registry.get(cid)
        cells = []
        for hid in hotel_ids:
            r = store.resolve(hid, spec)
            cells.append({"summary": r.get("summary") or "нет данных", "status": r["status"],
                          "confidence": r["confidence"], "source": r.get("source_label")})
        out["rows"].append({"char": cid, "name": spec["name"], "cells": cells})
    return out
