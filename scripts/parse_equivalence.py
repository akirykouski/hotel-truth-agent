"""Эквивалентность разбора: условия, которые агент передаёт в search_hotels(constraints=...), против вложенного
разбора LLM (search.parse) на тех же словах гостя. Агент настоящий (claude-cli + MCP), условия берутся из его
вызова в trace. Для каждого запроса: same / agent stricter / agent looser / different и число подходящих отелей.

    python scripts/parse_equivalence.py --out docs/parse_equivalence.md [--workers 4] [--only 1 5 7]
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--out", default=str(ROOT / "docs" / "parse_equivalence.md"))
ap.add_argument("--workers", type=int, default=4)
ap.add_argument("--only", nargs="*", type=int)
args = ap.parse_args()

tmp = Path(tempfile.mkdtemp(prefix="parse-eq-"))
shutil.copy(ROOT / "data" / "facts.sqlite", tmp / "facts.sqlite")
os.environ.update(FACTS_DB=str(tmp / "facts.sqlite"), CUSTOM_DIR=str(tmp / "custom"), SIM_FILE=str(tmp / "sim.json"),
                  LLM_PROVIDER="claude-cli")
sys.path.insert(0, str(ROOT))

from app import actions, agent, llm, region, search  # noqa: E402

# 12 запросов из bench/llm_track.py CASES (первая реплика) + 20 разных
QUERIES = [
    "Тихий номер с видом на закат недалеко от моря, едем в июле",
    "Еду с мамой, ей тяжело ходить в гору. Нужно близко к пляжу и чтобы из окна было видно море",
    "Мы с ребёнком 3 лет и собакой 12 кг. Нужна детская площадка рядом и чтобы пускали с собакой",
    "Работаю удалённо две недели в ноябре: нужно тихо днём, хороший интернет и чтобы рядом можно было поесть",
    "Прилетаем в 2 ночи. Важно, чтобы рядом была круглосуточная аптека и где-то поесть",
    "В Cosmos Сочи Отель будет слышно поезда ночью? И далеко ли там до моря?",
    "Хочу смотреть, как солнце садится в море, в конце декабря. Какие отели и с какого этажа?",
    "Сравни AZIMUT Парк Отель Виноградная и Отель Грейс Горизонт по виду на море, тишине и пути до пляжа",
    "Нужен отель рядом с аквапарком",
    "Можно ли ещё купаться в Сочи в начале ноября?",
    "Чтобы рядом не было стройки и баров под окнами, и не надо было переходить железную дорогу к морю",
    "Есть ли в Отель Лофт плотные шторы блэкаут? Мне важно спать днём",
    # отрицания, числа, месяцы, бюджеты, питомцы, вне реестра
    "Не хочу номер на шумной улице, нужен отель без стройки рядом",
    "До пляжа не больше 10 минут пешком, и чтобы не надо было переходить железную дорогу",
    "Отель до 6000 рублей за ночь, чтобы море было видно из окна",
    "Едем в августе, нужен закат над морем из номера и тишина ночью",
    "Нужна собака 12 кг разрешена, и парк рядом погулять",
    "Хочу отель с бассейном и спа, недалеко от пляжа",
    "Не меньше 4 звёзд, тихо ночью, рейтинг от 8",
    "В марте хочу искупаться, насколько тёплое море в апреле и в какой отель ехать",
    "Хорошо бы с видом на море, но главное, чтобы без подъёма до пляжа",
    "Нужен отель с лифтом, рядом с морем, мама в инвалидном кресле",
    "С двумя детьми 5 и 8 лет, площадка не дальше 200 м, и чтобы кафе было рядом",
    "Ищу тихий отель, где хорошая шумоизоляция и шторы блэкаут, дети спят днём",
    "Нужна парковка у отеля и зарядка для электромобиля рядом",
    "Только не первая линия и не рядом с вокзалом, хочу спокойно спать",
    "Отель с завтраком и трансфером из аэропорта, до 8000 в сутки",
    "Чтобы до моря было максимум 5 минут и закат виден в сентябре",
    "Едем в январе, нужен хороший вайфай и рабочий стол, тихо днём",
    "Хочу видеть море с самого низкого этажа, не выше 3-го",
    "Работаю ночью, сплю днём: нужны блэкаут-шторы, круглосуточная еда рядом и тишина днём",
    "Кошка и собака 25 кг, пляж рядом, шумные улицы не страшны",
]

_OPS_STRICT = {"<=": -1, "<": -1, ">=": 1, ">": 1}


def key(c):
    return (c["char"], c["field"])


def norm(p):
    cons = {}
    for c in p.get("constraints") or []:
        cons[key(c)] = (c["op"], c["value"], bool(c.get("must", True)))
    b = p.get("base") or {}
    return {"cons": cons, "month": p.get("month"), "base": {k: b.get(k) for k in ("max_price", "min_stars", "min_rating") if b.get(k)}}


def fmt(c):
    return f"{c[0][0]}.{c[0][1]} {c[1][0]} {c[1][1]}{'' if c[1][2] else ' (желание)'}"


def compare(nested, agent_p):
    """Список различий (agent_vs_nested): каждое помечено stricter / looser / other."""
    a, n = norm(agent_p), norm(nested)
    diffs = []
    for k in sorted(set(a["cons"]) | set(n["cons"])):
        ca, cn = a["cons"].get(k), n["cons"].get(k)
        if ca == cn:
            continue
        if cn is None:
            diffs.append(("stricter" if ca[2] else "looser", f"агент добавил {fmt((k, ca))}"))
        elif ca is None:
            diffs.append(("looser" if cn[2] else "stricter", f"агент не взял {fmt((k, cn))}"))
        else:
            kind = "other"
            if ca[0] == cn[0] and ca[0] in _OPS_STRICT and ca[2] == cn[2] and isinstance(ca[1], (int, float)) \
                    and isinstance(cn[1], (int, float)):
                d = (ca[1] - cn[1]) * _OPS_STRICT[ca[0]]
                kind = "stricter" if d > 0 else "looser" if d < 0 else "same"
            elif ca[:2] == cn[:2]:
                kind = "stricter" if ca[2] and not cn[2] else "looser"
            diffs.append((kind, f"{fmt((k, cn))} -> {fmt((k, ca))}"))
    if a["month"] != n["month"]:
        diffs.append(("other", f"месяц {n['month']} -> {a['month']}"))
    if a["base"] != n["base"]:
        diffs.append(("other", f"бюджет/звёзды {n['base']} -> {a['base']}"))
    kinds = {d[0] for d in diffs} - {"same"}
    if not kinds:
        return "same", []
    if kinds == {"stricter"}:
        return "agent stricter", diffs
    if kinds == {"looser"}:
        return "agent looser", diffs
    return "different", diffs


def show(p):
    cs = "; ".join(f"{c['char']}.{c['field']} {c['op']} {c['value']}{'' if c.get('must', True) else '~'}" for c in p.get("constraints") or [])
    b = {k: v for k, v in (p.get("base") or {}).items() if v}
    return f"{cs or 'нет условий'} | мес {p.get('month')}" + (f" | {b}" if b else "")


def run(i):
    q = QUERIES[i - 1]
    t0 = time.time()
    row = {"n": i, "query": q}
    try:
        nested = search.parse(q)
    except Exception as e:
        row.update(verdict="error", note=f"nested: {e}")
        return row
    row["nested"] = nested
    try:
        _, trace = llm.cli_agent(agent._system().replace("{label_in}", region.META["label_in"]), [{"role": "user", "content": q}])
    except Exception as e:
        row.update(verdict="error", note=f"agent: {str(e)[:120]}")
        return row
    calls = [t for t in trace if t["tool"] == "search_hotels"]
    row["calls"] = len(calls)
    if not calls:
        row.update(verdict="no search", note="агент не вызывал search_hotels (вопрос про конкретный отель или без подбора)")
        return row
    withc = next((t for t in calls if t["input"].get("constraints")), None)
    if withc is None:
        row.update(verdict="no constraints", note="агент вызвал search_hotels без constraints (поиск разобрал сам)")
        return row
    inp = withc["input"]
    agent_p, rejected = search.parse_agent(q, inp["constraints"], inp.get("month"), inp.get("base"), inp.get("missing"))
    row["agent_input"] = inp
    if agent_p is None:
        row.update(verdict="rejected", note=f"условия отклонены реестром: {rejected}")
        return row
    row["agent"] = agent_p
    row["verdict"], row["diffs"] = compare(nested, agent_p)
    ra = search.search(q, limit=3, parsed=agent_p)
    rn = search.search(q, limit=3, parsed=nested)
    row["counts"] = {"nested": rn["counts"], "agent": ra["counts"]}
    row["top3"] = {"nested": [r["hotel"]["name"] for r in rn["results"]], "agent": [r["hotel"]["name"] for r in ra["results"]]}
    row["sec"] = round(time.time() - t0)
    return row


ids = args.only or list(range(1, len(QUERIES) + 1))
with ThreadPoolExecutor(args.workers) as ex:
    rows = list(ex.map(run, ids))

order = ["same", "agent stricter", "agent looser", "different", "no constraints", "no search", "rejected", "error"]
summary = {k: sum(1 for r in rows if r["verdict"] == k) for k in order}
out = ["# Эквивалентность разбора: агент против вложенного LLM", "",
       "Сгенерировано `scripts/parse_equivalence.py`. Настоящий агент (claude-cli + MCP) получает слова гостя; из его "
       "вызова `search_hotels` берётся `constraints` (+ month, base), сравнивается с `search.parse` (вложенный разбор LLM) "
       "на тех же словах. Первые 12 запросов из `bench/llm_track.py`, остальные 20 написаны под отрицания, числа, "
       "месяцы, бюджеты, питомцев и нужды вне реестра. «Строже» и «мягче» относятся к условиям агента относительно "
       "вложенного разбора; отельные вопросы без подбора попадают в «no search».", "",
       "## Итого", "", "| Вердикт | Запросов |", "|---|---|"] + [f"| {k} | {v} |" for k, v in summary.items() if v] + \
      ["", "## По запросам", "",
       "| # | Запрос | Вердикт | Подходят (вложенный / агент) | Топ-3 совпал |", "|---|---|---|---|---|"]
for r in rows:
    c = r.get("counts")
    cc = f"{c['nested']['match']}+{c['nested']['maybe']}м / {c['agent']['match']}+{c['agent']['maybe']}м" if c else "-"
    t3 = ("да" if r["top3"]["nested"] == r["top3"]["agent"] else f"{len(set(r['top3']['nested']) & set(r['top3']['agent']))}/3") if c else "-"
    out.append(f"| {r['n']} | {r['query'][:70]} | {r['verdict']} | {cc} | {t3} |")
out += ["", "(«N+Mм»: подходят + возможно, по числу отелей.)", "", "## Расхождения", ""]
for r in rows:
    if r["verdict"] == "same":
        continue
    out += [f"### {r['n']}. {r['query']}", "", f"Вердикт: **{r['verdict']}**" + (f". {r['note']}" if r.get("note") else ""), ""]
    if r.get("nested"):
        out.append(f"- вложенный разбор: `{show(r['nested'])}`")
    if r.get("agent"):
        out.append(f"- условия агента: `{show(r['agent'])}`")
    for kind, d in r.get("diffs", []):
        out.append(f"  - {kind}: {d}")
    if r.get("counts"):
        out.append(f"- подходят: {r['counts']['nested']} против {r['counts']['agent']}")
        out.append(f"- топ-3 вложенный: {r['top3']['nested']}; агент: {r['top3']['agent']}")
    out.append("")
Path(args.out).write_text("\n".join(out), encoding="utf-8")
(tmp / "rows.json").write_text(json.dumps(rows, ensure_ascii=False, default=str, indent=1))
print(json.dumps(summary, ensure_ascii=False), "raw:", tmp / "rows.json")
