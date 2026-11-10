"""Правила «ответа с развилками»: показываем развилки только при настоящем компромиссе.
Запуск: LLM_PROVIDER=none python tests/answer_check.py"""
import os
import sys
from pathlib import Path

os.environ.setdefault("LLM_PROVIDER", "none")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import actions, answer  # noqa: E402

fails = 0


def check(name, ok, info=""):
    global fails
    print(("OK  " if ok else "FAIL"), name, info)
    fails += not ok


def run(q, prio=None):
    r = actions.search_hotels(q, 300)
    m = [x["hotel"] for x in r["results"] if x["bucket"] == "match"]
    return answer.build(m, r["parsed"], q, prio, r["parsed"].get("month")), m


# разбор намерения
it = answer.intent("главное тишина, цена не важна", {"constraints": []})
check("«цена не важна»: цена не ось и не развилка", "price" not in it["dims"] and "price" not in it["fork_dims"], it)
check("«главное тишина»: тишина главная", it["priorities"][:1] == ["quiet"], it["priorities"])
it = answer.intent("вид на море", {"constraints": [{"char": "sea_view", "field": "has"}]})
check("«вид на море» — про вид, не про дорогу до пляжа", "sea" in it["dims"] and "beach" not in it["dims"], it["dims"])
check("отзывы не развилка, если о них не спрашивали", "rating" not in it["fork_dims"], it["fork_dims"])

# один подходящий — развилок нет
a = answer.build([{"id": "x", "price_nov1": 1000, "rating": 9}], {"constraints": []}, "что-то")
check("один отель: без развилок", not a["show"] and a["reason"] == "single")

# настоящий компромисс
a, m = run("тихий номер с видом на закат недалеко от моря, июль")
check("закат у моря: есть развилки", a["show"] and a["forks"], [f["title"] for f in a.get("forks", [])])
for f in a.get("forks", []):
    check(f"  развилка «{f['title']}» с выигрышем и потерей", bool(f["gain"]) and bool(f["loss"]), f["loss"])
check("  победитель и развилки — разные отели", len({a["winner"]["id"], *[f["hotel"]["id"] for f in a["forks"]]}) == 1 + len(a["forks"]))

# при названном главном развилки им не жертвуют
a, _ = run("главное тишина, недалеко от моря")
for f in a.get("forks", []):
    check(f"  «главное тишина»: развилка «{f['title']}» не ухудшает тишину", not any("дБ" in x for x in f["loss"]), f["loss"])
check("«главное тишина»: нет развилки «если важнее тишина»", all(f["dim"] != "quiet" for f in a.get("forks", [])))

# цена не важна — нет развилки по цене
a, _ = run("вид на море, цена не важна")
check("«цена не важна»: нет развилки по цене", all(f["dim"] != "price" for f in a.get("forks", [])))

print("\nвсе проверки прошли" if not fails else f"\nпровалено: {fails}")
sys.exit(1 if fails else 0)
