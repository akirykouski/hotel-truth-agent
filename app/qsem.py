"""Смысл запроса, который не ловят ключевые слова: отрицание («не нужен вид на море»), уточнения без поля в реестре
(«веганский завтрак», «собака 12 кг»), другой город и дата цен. Правила работают на тексте, поэтому одни и те же
проверки применяются к разбору правилами, LLM и агента."""
import json
import re

from app import region
from app.tools.sun import MONTHS_RU

PRICE_DATE = "2026-11-01"   # цены в карточках скрапнуты на одну дату (hotels.json: price_nov1)
PRICE_MONTH = 11
PRICE_DAY_RU = "1 ноября"
IGNORED_REASON = "вы сказали, что не нужно"

_SPLIT = re.compile(r"[,;.!?\n()]|\s(?:но|а|зато|однако|только)\s")
# условие снимается целиком, если в той же части фразы сказано «не нужно / не важно / необязательно»
_NEG = re.compile(r"\bне\s+(?:очень\s+|так\s+)?(?:нуж\w+|важ\w*|обязател\w*|надо|требу\w*|хоч\w+|интересу\w*|принципиальн\w*|нравит\w*)"
                  r"|\bне(?:важ|обязател|принципиальн)\w*|\bбез\s+разниц\w*|\bнеактуальн\w*|\bкроме\b")
_WITHOUT = re.compile(r"\bбез\b")
# «против»: гость хочет обратное, а не просто снял условие («не у моря», «подальше от моря», «не на первой линии»)
_POLAR = re.compile(r"(?<![а-яё])(?:не(?:\s+(?:на|в|у|к|с|от|до|рядом|возле|около|близко|вблизи|совсем|очень|слишком)){0,2}"
                    r"|подальше\s+от|далеко\s+от|вдали\s+от|в\s+стороне\s+от)\s+$")
_POLAR_MARK = re.compile(r"не(?:\s+(?:на|в|у|к|с|от|до|рядом|возле|около|близко|вблизи|совсем|очень|слишком))*|подальше\s+от|"
                         r"далеко\s+от|вдали\s+от|в\s+стороне\s+от")
# части фразы без требования: кто едет и связки; из них не делаем «не умеем проверить»
_LEAD = re.compile(r"^(?:хоч\w*|хот\w*|нуж\w*|ищ\w*|отел\w*|гостиниц\w*|номер\w*|мне|нам|я|мы|работа\w*|подбер\w*|найд\w*|покаж\w*|"
                   r"пожалуйста|можно|надо|бы|же|и|а|но)$")
_FILLER = re.compile(r"^(?:хоч\w*|хот\w*|нуж\w*|ищ\w*|отел\w*|гостиниц\w*|номер\w*|мне|нам|я|мы|в|во|на|и|с|со|для|по|за|из|к|у|от|до|а|но|же|"
                     r"бы|пожалуйста|работа\w*|сем\w+|вдво\w+|пар\w*|друз\w*|компани\w*|жен\w*|муж\w*|бабушк\w*|дедушк\w*|мам\w*|"
                     r"пап\w*|реб[её]н\w*|взросл\w*|человек\w*|приед\w*|едем|еду|поездк\w*|отпуск\w*|отдых\w*|отдохн\w*|сочи|"
                     r"подбер\w*|найд\w*|покаж\w*|можно|надо|очень|просто|только|вариант\w*|что-нибудь|что-то|\d+)$")

_FOOD = re.compile(r"завтрак\w*|обед\w*|ужин\w*|еда\b|еду\b|еды\b|еде\b|питани\w*|меню|кухн\w*|блюд\w*")
_DIET = re.compile(r"веган\w*|вегетариан\w*|халяль\w*|халял\w*|халал\w*|кошерн\w*|постн\w*|безглютен\w*|без\s+глютен\w*|безлактоз\w*|"
                   r"без\s+лактоз\w*|диетическ\w*|диетическ\w+|детск\w+\s+меню|аллерг\w*|сыроед\w*|органическ\w*|фермерск\w*")
_QTY = re.compile(r"(\d+(?:[.,]\d+)?)\s*(кг\b|килограмм\w*|кило\b|см\b|сантиметр\w*|кв\.?\s*м\b|м²|квадрат\w*)")
_PET = re.compile(r"собак\w*|пёс\w*|пес\b|песик\w*|щен\w+|питомц\w*|кошк\w*|кот\b|котом|кошеч\w*|животн\w*")
_BREED = re.compile(r"овчарк\w*|лабрадор\w*|хаски|доберман\w*|ротвейлер\w*|алабай\w*|бульдог\w*|корги|такс[аыуе]\b|йорк\w*|"
                    r"чихуахуа|спаниел\w*|пудел\w+|мопс\w*|дог\b|доги\b|мастиф\w*|кане-?корсо|бигл\w*|шпиц\w*")
_PET_SIZE = re.compile(r"крупн\w+|больш\w+|средн\w+|маленьк\w+|мелк\w+|гигантск\w+|породист\w+|порода|породы|породой|вес\w*")
_ADJ = re.compile(r"^[а-яё]{4,}(?:ый|ий|ой|ая|яя|ое|ее|ые|ие|ую|юю|ого|его|ым|им|ом|ем|ых|их|ыми|ими)$")
# оценочные слова, которые не меняют условие и не требуют отдельной характеристики
_STOP_ADJ = re.compile(r"^(?:хорош|отличн|прекрасн|великолепн|замечательн|красив|вкусн|приятн|шикарн|удобн|уютн|нормальн|чист|нов|свеж|"
                       r"настоящ|люб|как|сам|этот|эти|наш|ваш|свой|своё|сво[ейю]|собственн|тих|спокойн|небольш|ближайш|"
                       r"хотел|нужн|важн|главн|основн|идеальн|лучш|достойн|комфортн|качествен|классн|крутой|топов|"
                       r"пятизвёздоч|четырёхзвёздоч|трёхзвёздоч|пятизвездоч|четырехзвездоч|трехзвездоч|общ|один|друг|каждый|весь|"
                       r"какой|такой|данн|обычн|стандартн|простой|хороший|дешев|недорог|бюджетн|доступн|рабоч|"
                       r"подходящ|желательн|возможн|любимый|тот|тем|всем|вашем|нашем|любом|одном|разн)")


def _clauses(t):
    out, a = [], 0
    for m in _SPLIT.finditer(t):
        out.append((a, m.start()))
        a = m.end()
    out.append((a, len(t)))
    return [c for c in out if c[1] > c[0]]


def clause_of(t, span):
    for a, b in _clauses(t):
        if a <= span[0] < b or a < span[1] <= b:
            return a, b
    return 0, len(t)


def negation(t, span):
    """Маркер отрицания в той же части фразы, что и найденное условие (сам маркер вне найденного куска), либо None."""
    a, b = clause_of(t, span)
    for m in _NEG.finditer(t, a, b):
        if m.end() <= span[0] or m.start() >= span[1]:
            return m.group(0)
    m = _POLAR.search(t, a, span[0])
    if m:
        return m.group(0).strip()
    for m in _WITHOUT.finditer(t, a, span[0]):  # «без» действует на ближайшее: «без вида на море», «без бассейна и спа»
        gap = t[m.end():span[0]]  # «без лестниц и у моря»: «без» не перескакивает через «и» к следующему условию
        if m.end() <= span[0] and len(gap) <= 30 and " но " not in gap and not re.search(r"(?<![а-яё])и(?![а-яё])", gap):
            return m.group(0)
    return None


def polar(marker):
    """Отрицание «против» («не у моря», «подальше от моря»): гость хочет обратное, а не снял условие («не нужно»)."""
    return bool(marker and _POLAR_MARK.fullmatch(marker))


def leftover(t, handled):
    """Части фразы, в которых ничего не распознано (нет ни условия, ни пропуска, ни missing): [(a, b)]. Связки вроде
    «работаю удалённо», «хочу», «семья» не требования и сюда не попадают."""
    out = []
    for a, b in _clauses(t):
        if any(x < b and a < y for x, y in handled):
            continue
        ws = list(re.finditer(r"[a-zа-яё0-9-]+", t[a:b]))
        if not ws or all(_FILLER.match(m.group(0)) for m in ws):
            continue
        while _LEAD.match(ws[0].group(0)):  # без глаголов-связок по краям: «хочу отель в горах» → «в горах»
            ws.pop(0)
        while _LEAD.match(ws[-1].group(0)):
            ws.pop()
        out.append((a + ws[0].start(), a + ws[-1].end()))
    return out


def ignored_entry(t, span, cid=None):
    return {"phrase": t[span[0]:span[1]], "char": cid, "reason": IGNORED_REASON}


def qualifiers(t, hits):
    """Уточнения, которые реестр не проверяет: диета у еды, вес и размер питомца, прилагательное или число при найденном
    условии. hits — [{span, cid, label}] действующих условий. Возвращает missing-записи; условия остаются как есть."""
    out, seen = [], set()

    def add(phrase, proposal):
        k = phrase.lower()
        if not any(k in s or s in k for s in seen):
            seen.add(k)
            out.append({"phrase": phrase, "proposal": proposal})

    spans = [h["span"] for h in hits]
    for a, b in _clauses(t):
        part = t[a:b]
        d, f = _DIET.search(part), _FOOD.search(part)
        if d and f:
            lo, hi = min(d.start(), f.start()), max(d.end(), f.end())
            phr = part[lo:hi]
            add(phr, f"{phr}: отдельное меню под такое питание, подтверждает отельер")
        elif d and any(h["cid"] in ("breakfast", "meal_plan") and a <= h["span"][0] < b for h in hits):
            add(d.group(0), f"в отеле есть питание: {d.group(0)}")
        has_pet = _PET.search(part) or any(h["cid"] == "pets" and a <= h["span"][0] < b for h in hits)
        for q in _QTY.finditer(part):
            near = [h for h in hits if a <= h["span"][0] < b]
            if not near and not has_pet:
                continue
            h0 = next((h for h in near if h["cid"] == "pets"), None) or (near[0] if near else None)
            pm = _PET.search(part)
            sp0 = (h0["span"][0] - a, h0["span"][1] - a) if h0 else (pm.start(), pm.end())
            phr = re.sub(r"^(?:с|со|и|для)\s+", "", part[min(sp0[0], q.start()):max(q.end(), sp0[1])])
            if (h0 and h0["cid"] == "pets") or (not h0 and pm):
                add(phr, f"отель принимает животных такого веса ({q.group(0)}): вес питомца называет только отельер")
            else:
                add(phr, f"{phr}: числовое уточнение, поля для него в реестре нет")
        if has_pet:
            s = _PET_SIZE.search(part)
            br = _BREED.search(part)
            m = br or s
            if m:
                add(m.group(0) if not (br and s) else part[min(br.start(), s.start()):max(br.end(), s.end())],
                    "отель принимает такое животное: размер, порода и вес зависят от правил отеля, их называет отельер")
        elif _BREED.search(part):
            m = _BREED.search(part)
            add(m.group(0), "отель принимает такую породу: порода и вес зависят от правил отеля, их называет отельер")
    # прилагательное прямо перед найденным условием, которого нет среди известных слов: «панорамный вид», «веганский завтрак»
    for h in hits:
        a, b = clause_of(t, h["span"])
        w = re.search(r"([а-яё]+)\s+$", t[a:h["span"][0]])
        if not w:
            continue
        word = w.group(1)
        wspan = (a + w.start(1), a + w.end(1))
        if not _ADJ.match(word) or _STOP_ADJ.match(word) or _DIET.fullmatch(word) or \
                any(s[0] < wspan[1] and wspan[0] < s[1] for s in spans) or negation(t, h["span"]):
            continue
        phr = f"{word} {t[h['span'][0]:h['span'][1]]}"
        add(phr, f"{phr}: уточнение «{word}» реестр пока не проверяет")
    return out


def pet_hit(t):
    """Питомец названием без «с собакой» («собака 25 кг», «овчарка», «хаски»): тоже поездка с животным: (span, текст)."""
    m = _PET.search(t) or _BREED.search(t)
    return (m.span(), m.group(0)) if m else None


_PLACES = None


def _places():
    global _PLACES
    if _PLACES is None:
        f = region.ROOT / "data" / "off_region.json"
        _PLACES = json.loads(f.read_text(encoding="utf-8"))["places"] if f.exists() else []
    return _PLACES


def off_region(text):
    """Если гость назвал город или район, которого нет в активном регионе: {asked, active, region?}. «Из Москвы» (откуда
    едут) не считается. Падежи ловит основа слова в данных."""
    t = text.lower()
    here = (region.META.get("label", "") + " " + (region.NAME or "") + " " + region.META.get("label_of", "")).lower()
    for p in _places():
        m = re.search(r"(?<![а-яё])(?:" + p["rx"] + r")(?![а-яё])", t)
        if not m:
            continue
        if re.search(r"(?:\bиз|\bот|\bчерез|\bпосле)\s+$", t[:m.start()]):
            continue
        if re.search(p["rx"], here) or (p.get("region") and p["region"] == region.NAME):
            continue
        out = {"asked": p["name"], "active": region.META["label"]}
        if p.get("region") and (region.ROOT / "data" / "regions" / p["region"]).exists():
            out["region"] = p["region"]
            try:
                out["region_label"] = json.loads((region.ROOT / "data" / "regions" / p["region"] / "region.json").read_text(encoding="utf-8"))["label"]
            except (OSError, ValueError, KeyError):
                out["region_label"] = p["name"]
        return out
    return None


def price_info(base, month):
    """Подпись к бюджету: цены в карточках на одну дату, а не на даты гостя."""
    if not (base or {}).get("max_price"):
        return None
    note = f"цена на {PRICE_DAY_RU}, на ваши даты проверьте на Островке"
    if month and month != PRICE_MONTH:
        note += f": вы спросили про {MONTHS_RU[month].lower()}, а в другой месяц цена может сильно отличаться"
    return note
