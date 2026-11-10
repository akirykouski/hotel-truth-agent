"""Смысл запроса: отрицание, уточнения без поля в реестре, другой город, дата цен. Проверяем и условия, и подписи выдачи.
Запуск: make semantic-test  (или LLM_PROVIDER=none python tests/semantic_queries.py)"""
import os
import sys
from pathlib import Path

os.environ["LLM_PROVIDER"] = "none"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FACTS_DB", str(ROOT / "data" / "cache" / "facts.semantic.sqlite"))
from app import actions, agent, search  # noqa: E402

shutil_src = ROOT / "data" / "facts.sqlite"
if not Path(os.environ["FACTS_DB"]).exists():
    import shutil
    Path(os.environ["FACTS_DB"]).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(shutil_src, os.environ["FACTS_DB"])


def chars(r):
    return {c["char"] for c in r["parsed"]["constraints"]}


def ign(r):
    return {g["char"] for g in r["parsed"]["ignored"] if g.get("char")}


def miss(r, *words):
    txt = " ".join(m["phrase"].lower() for m in r["parsed"]["missing"])
    return all(w in txt for w in words)


def cons(r, char):
    return [c for c in r["parsed"]["constraints"] if c["char"] == char]


def flipped(r, char, op, value):
    c = cons(r, char)
    return len(c) == 1 and c[0]["op"] == op and c[0]["value"] == value


def beach_far(r):
    """Условие «подальше от моря» работает в обратную сторону: среди подходящих нет отелей у воды."""
    return all(x["actual"] > 15 for row in r["results"] if row["bucket"] == "match" for x in row["checks"] if x["char"] == "beach_walk")


def open_(r):
    """Ответ не вправе называть запрос выполненным."""
    return bool(r["caveats"]) or bool(r.get("off_region"))


CASES = [
    # (запрос, проверка, что проверяем)
    ("Не нужен вид на море, нужен хороший интернет", lambda r: "sea_view" not in chars(r) and "wifi" in chars(r) and "sea_view" in ign(r)
     and r["parsed"]["ignored"][0]["reason"] == "вы сказали, что не нужно", "отрицание снимает море, интернет остаётся"),
    ("Тихий отель с веганским завтраком", lambda r: {"night_quiet", "breakfast"} <= chars(r) and miss(r, "веган") and open_(r),
     "веганский завтрак в missing"),
    ("С собакой 12 кг", lambda r: "pets" in chars(r) and miss(r, "12 кг") and open_(r), "вес собаки в missing"),
    ("Вид на море в Казани", lambda r: r["parsed"]["off_region"]["asked"] == "Казань" and not r["results"] and r["message"]
     and r["counts"]["match"] == 0, "другой город: пусто и объяснение"),
    ("вид на море не обязателен", lambda r: "sea_view" not in chars(r) and "sea_view" in ign(r), "постфиксное «не обязателен»"),
    ("Без моря, главное wifi", lambda r: "sea_view" not in chars(r) and "wifi" in chars(r), "«без моря»"),
    ("Хочу тихий отель, вид на море неважно", lambda r: "night_quiet" in chars(r) and "sea_view" not in chars(r), "«неважно» в своей части фразы"),
    ("Нужен бассейн, кроме вида на море ничего не важно", lambda r: "sea_view" not in chars(r), "«кроме»"),
    ("С собакой, без подъёма до пляжа", lambda r: {"pets", "beach_walk"} <= chars(r) and not r["parsed"]["ignored"],
     "«без подъёма» это условие, а не отрицание"),
    ("Тихо и с видом на море, без собак", lambda r: {"night_quiet", "sea_view"} <= chars(r) and "pets" not in chars(r), "отрицание локально"),
    ("собака 25 кг", lambda r: "pets" in chars(r) and miss(r, "25 кг") and open_(r), "другой вес"),
    ("овчарка", lambda r: "pets" in chars(r) and miss(r, "овчарка") and open_(r), "порода без слова «собака»"),
    ("С большой собакой", lambda r: "pets" in chars(r) and miss(r, "больш") and open_(r), "размер питомца"),
    ("халяльная еда", lambda r: miss(r, "халял") and open_(r), "диета без завтрака"),
    ("завтрак без глютена", lambda r: "breakfast" in chars(r) and miss(r, "глютен") and open_(r), "без глютена"),
    ("вегетарианский ужин и тишина", lambda r: "night_quiet" in chars(r) and miss(r, "вегетариан") and open_(r), "вегетарианский ужин"),
    ("панорамный вид на море", lambda r: "sea_view" in chars(r) and miss(r, "панорамн") and open_(r), "прилагательное без поля"),
    ("отель в Москве с видом", lambda r: r["parsed"]["off_region"]["asked"] == "Москва" and not r["results"], "в Москве"),
    ("в Питере у моря", lambda r: r["parsed"]["off_region"]["asked"] == "Санкт-Петербург" and not r["results"], "Питер"),
    ("тихий отель в Анапе", lambda r: r["parsed"]["off_region"]["asked"] == "Анапа", "Анапе"),
    ("отель в Адлере с видом на море", lambda r: r["parsed"]["off_region"]["asked"] == "Адлер" and r["parsed"]["off_region"].get("region") == "adler",
     "район Сочи, есть отдельный регион"),
    ("Из Москвы приеду, нужен вид на море", lambda r: "off_region" not in r["parsed"] and r["counts"]["match"] > 0, "«из Москвы» это откуда едут"),
    ("тихий отель в Сочи", lambda r: "off_region" not in r["parsed"] and r["results"], "Сочи это наш регион"),
    ("до 4000 ₽ в августе", lambda r: r["parsed"]["base"]["price_date"] == "2026-11-01" and "1 ноября" in r["price_note"]
     and "август" in r["price_note"] and r["counts"]["fail"] == 0 and open_(r), "бюджет не отказ при другом месяце"),
    ("тихий отель до 5000 ₽", lambda r: "1 ноября" in r["price_note"] and r["parsed"]["base"]["price_date"] and open_(r),
     "бюджет с подписью даты"),
    ("тихий отель с видом на море", lambda r: {"night_quiet", "sea_view"} <= chars(r) and not r["parsed"]["missing"] and not r["parsed"]["ignored"]
     and not open_(r) and r["counts"]["match"] > 0, "обычный запрос без оговорок"),
    # --- раунд жюри: отрицание «против», потерянные части фразы, регион собран, но не включён, «без лестниц» ---
    ("не у моря, в горах, тихо", lambda r: flipped(r, "beach_walk", ">", 15) and "night_quiet" in chars(r) and miss(r, "в горах")
     and not r["parsed"]["ignored"] and beach_far(r) and r["counts"]["match"] < 120 and open_(r), "«не у моря» переворачивает условие, «в горах» в missing"),
    ("без лестниц и у моря", lambda r: {"accessibility", "beach_walk"} <= {c["char"] for c in r["parsed"]["constraints"]} and not r["parsed"].get("ignored"),
     "«без» не перескакивает через «и» к следующему условию"),
    ("без ступенек и чтобы рядом море", lambda r: {"accessibility", "beach_walk"} <= {c["char"] for c in r["parsed"]["constraints"]} and not r["parsed"]["missing"],
     "«ступенек» и «рядом море» распознаны"),
    ("не слишком далеко от моря, тихо", lambda r: flipped(r, "beach_walk", "<=", 15) and not r["parsed"].get("ignored"), "«не слишком далеко» значит близко"),
    ("подальше от моря", lambda r: flipped(r, "beach_walk", ">", 15) and not r["parsed"]["missing"] and beach_far(r), "«подальше от моря»"),
    ("не на первой линии", lambda r: flipped(r, "beach_walk", ">", 6) and not r["parsed"]["missing"], "«не на первой линии»"),
    ("вдали от пляжа", lambda r: flipped(r, "beach_walk", ">", 15), "«вдали от пляжа»"),
    ("не у моря", lambda r: not [c for c in cons(r, "beach_walk") if c["op"] == "<="] and r["counts"]["match"] > 0, "не требование «у моря»"),
    ("без вида на море", lambda r: "sea_view" not in chars(r) and "sea_view" in ign(r) and not r["parsed"]["missing"], "«без вида на море» один: не создаёт sea_view"),
    ("вид на море не нужен", lambda r: "sea_view" not in chars(r) and "sea_view" in ign(r) and not r["parsed"]["missing"], "«не нужен» после слова"),
    ("работаю удалённо, быстрый wifi, не у дороги", lambda r: {"wifi", "night_quiet"} <= chars(r) and miss(r, "быстрый")
     and not miss(r, "работаю") and not miss(r, "дороги"), "«не у дороги» это тишина; «работаю удалённо» не missing"),
    ("не возле трассы", lambda r: chars(r) == {"night_quiet"} and not r["parsed"]["missing"], "«не возле трассы»"),
    ("подальше от дороги и с видом на море", lambda r: {"night_quiet", "sea_view"} <= chars(r), "«подальше от дороги»"),
    ("хочу отель в горах, тихо", lambda r: "night_quiet" in chars(r) and miss(r, "в горах") and not miss(r, "хочу"), "лишняя часть фразы в missing, «хочу» нет"),
    ("в Адлере с видом", lambda r: r["parsed"]["off_region"]["region"] == "adler" and not r["results"] and "собрали отдельно" in r["message"]
     and "отдельно" in r["message"] and "только в регионе" not in r["message"], "Адлер собран: сообщение про команду Островка"),
    ("в Хосте у моря", lambda r: r["parsed"]["off_region"]["region"] == "hosta" and "собрали отдельно" in r["message"],
     "Хоста собран: сообщение про команду Островка"),
    ("тихий отель в Анапе", lambda r: "region" not in r["parsed"]["off_region"] and "только в регионе" in r["message"] and "собрали отдельно" not in r["message"],
     "Анапа не собрана: прежнее сообщение"),
    ("без лестниц, бабушке 80", lambda r: chars(r) == {"accessibility"} and not r["parsed"]["missing"] and r["counts"]["maybe"] > 0
     and r["counts"]["match"] == 100 and  # 99 с лифтом + 1 с пандусом в карточке
      all(x["status"] == "pass" and x["actual"] is True and x["confidence"] for row in r["results"]
                                            if row["bucket"] == "match" for x in row["checks"]), "низкое здание без лифта это «возможно»"),
    ("тихо и без лестниц", lambda r: {"night_quiet", "accessibility"} <= chars(r) and r["counts"]["maybe"] > 0, "тишина плюс лестницы: есть «возможно»"),
    ("хороший интернет и красивый вид на море", lambda r: {"wifi", "sea_view"} <= chars(r) and not r["parsed"]["missing"], "оценочные слова не уточнения"),
]

fails = 0
for q, ok, why in CASES:
    r = search.search(q)
    try:
        good = bool(ok(r))
    except Exception as e:  # noqa: BLE001
        good = False
        why += f" [{type(e).__name__}: {e}]"
    fails += not good
    print("OK  " if good else "FAIL", q, "->", sorted(chars(r)), "missing=" + str([m["phrase"] for m in r["parsed"]["missing"]]),
          "ignored=" + str([g["phrase"] for g in r["parsed"]["ignored"]]), r["counts"], "" if good else "| " + why)

# текст ответа: нельзя ставить «подходит» там, где остались непроверенные уточнения или чужой город
d = actions.search_hotels("Тихий отель с веганским завтраком", limit=3)
txt = agent._template_answer(d)
chk = [("all_checked=false при missing", d["all_checked"] is False), ("в тексте «не закрыто»", "не закрыто" in txt and "веган" in txt),
       ("«по проверенным условиям»", "по проверенным условиям" in txt)]
d = actions.search_hotels("Вид на море в Казани")
txt = agent._template_answer(d)
chk += [("Казань: нет «Подходит»", "Подходит" not in txt and "Подходят" not in txt and "Казан" in txt)]
d = actions.search_hotels("тихий отель с видом на море", limit=3)
chk += [("чистый запрос: all_checked", d["all_checked"] is True and "не закрыто" not in agent._template_answer(d))]
# разбор LLM/агента: те же защиты поверх его вывода
def llm_like(*cons):
    return {"intent": "", "month": None, "base": {"max_price": None, "min_stars": None, "min_rating": None}, "missing": [],
            "constraints": [{"char": c, "field": f, "op": "==", "value": True, "must": True, "phrase": p} for c, f, p in cons]}


g = search._guard(llm_like(("sea_view", "has", "вид на море"), ("wifi", "good", "интернет")), "Не нужен вид на море, нужен хороший интернет")
chk += [("LLM: отрицание снимает море", {c["char"] for c in g["constraints"]} == {"wifi"} and g["ignored"][0]["phrase"] == "вид на море")]
g = search._guard(llm_like(("breakfast", "has", "завтраком")), "Тихий отель с веганским завтраком")
chk += [("LLM: веган в missing", any("веган" in m["phrase"] for m in g["missing"]))]
g = search._guard(llm_like(("sea_view", "has", "вид на море")), "Вид на море в Казани")
chk += [("LLM: off_region", g["off_region"]["asked"] == "Казань")]
pa, _ = search.parse_agent("С собакой 12 кг", [{"char": "pets", "field": "allowed", "op": "==", "value": True}])
chk += [("агент: вес в missing", pa is not None and any("12 кг" in m["phrase"] for m in pa["missing"]))]
for name, ok in chk:
    fails += not ok
    print("OK  " if ok else "FAIL", "answer:", name)

print(f"\n{len(CASES) + len(chk) - fails}/{len(CASES) + len(chk)}")
sys.exit(1 if fails else 0)
