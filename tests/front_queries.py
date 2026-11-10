"""Каждая плитка и каждый пример на главной обязаны разбираться хотя бы в одно условие (или попасть в missing).
Запуск: make front-test  (или LLM_PROVIDER=none python tests/front_queries.py)"""
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("LLM_PROVIDER", "none")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import search  # noqa: E402

js = (ROOT / "app/web/front/app.js").read_text(encoding="utf-8")
queries = []
for name, key in (("EXAMPLES", "t"), ("TILES", "q")):
    block = re.search(r"const " + name + r" = \[(.*?)\n\];", js, re.S)
    assert block, f"нет блока {name} в app.js"
    queries += re.findall(r"\b" + key + r": '([^']+)'", block.group(1))

# описания плиток тоже уходят в поиск, если гость скопирует их в поле, плюс живые формулировки и тарабарщина
tile_block = re.search(r"const TILES = \[(.*?)\n\];", js, re.S).group(1)
queries += re.findall(r"\bd: '([^']+)'", tile_block)
queries += ["заселение ночью", "заселение после полуночи", "хочу тишину и бассейн с подогревом", "фывапролдж",
            "в 10 минутах от центра, пляж 5 минут"]

fails = 0
for q in queries:
    p = search.parse_rules(q)
    n = len(p["constraints"]) + len(p["missing"])
    print("OK  " if n else "FAIL", q, "->", [f"{c['char']}.{c['field']}" for c in p["constraints"]], [m["phrase"] for m in p["missing"]])
    fails += 0 if n else 1
if len(queries) < 27:
    print("FAIL: нашли только", len(queries), "запросов, ждали 27 (6 примеров, 8 плиток, 8 описаний, 5 вариантов)")
    fails += 1
# число минут до пляжа берётся из собственной фразы, а не из первых «мин» запроса
beach = [c["value"] for c in search.parse_rules("в 10 минутах от центра, пляж 5 минут")["constraints"] if c["char"] == "beach_walk"]
if beach != [5]:
    print("FAIL: «пляж 5 минут» должен дать порог 5, получили", beach)
    fails += 1
sys.exit(1 if fails else 0)
