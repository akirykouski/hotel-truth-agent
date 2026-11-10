"""Засеять синтетических посетителей и обучить кластеры вкуса. Синтетика помечена и в порог включения не идёт.

  python scripts/seed_synthetic.py                 # 600 посетителей, 5 персон, signal 0.8
  python scripts/seed_synthetic.py --n 1000 --signal 0.5
  python scripts/seed_synthetic.py --wipe          # убрать всю синтетику
  python scripts/seed_synthetic.py --replay        # плюс честный офлайн-повтор на синтетике (MRR до/после)

После засева запустите `make taste-demo` (TASTE_DEMO=1) и откройте главную с ?cluster=1: выдача переставляется
демо-моделью, над списком штамп «Демо: синтетические посетители» и причина.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import taste, taste_synth, visitors  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=600)
ap.add_argument("--signal", type=float, default=0.8, help="доля посетителей с контекстом своей персоны (0 = контроль)")
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--wipe", action="store_true")
ap.add_argument("--replay", action="store_true")
a = ap.parse_args()

if a.wipe:
    print("удалено синтетических:", taste_synth.wipe())
    taste.refit(evaluate_gate=False)
    sys.exit(0)
truth = taste_synth.generate(n=a.n, signal=a.signal, seed=a.seed)
print("засеяно:", len(truth), "→", visitors.DB_PATH)
taste.refit(evaluate_gate=False)
st = taste.status()
print("демо-модель: k =", st["demo"]["k"], "силуэт", st["demo"]["silhouette"], "размеры", st["demo"]["size"])
for c in st["clusters"]:
    print(f"  кластер {c['cluster']}: {c['size']} посетителей, любят: {', '.join(c['likes'])}")
if a.replay:
    for cold in (True, False):
        print("офлайн-повтор" + (" (холодный старт)" if cold else ""), json.dumps(taste.replay(include_synthetic=True, cold_only=cold), ensure_ascii=False))
