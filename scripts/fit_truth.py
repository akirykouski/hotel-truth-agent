"""Оценка надёжности источников по каждой характеристике (EM в духе Dawid–Skene) → data/truth_reliability.json.

  python scripts/fit_truth.py                  # по всем источникам, пишет data/truth_reliability.json
  python scripts/fit_truth.py --exclude reviews --out /tmp/rel.json   # без отзывов: проверка утечки в held-out
Запускать после precompute. Файл лежит в репозитории; если его нет, рантайм досчитает сам.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LLM_PROVIDER", "none")

from app import store, truth  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--out")
    a = ap.parse_args()
    store.conn(store.SEED_PATH)   # считаем по предрасчёту из репозитория, не по рабочей копии
    fit = truth.fit_all(tuple(a.exclude))
    truth.save(fit, a.out)
    for cid, f in fit.items():
        src = ", ".join(f"{s} {p['sens']:.2f}/{p['spec']:.2f} ({p['votes']})" for s, p in f["sources"].items())
        print(f"{cid:15} {f['class']:12} pi={f['pi']:.2f} отелей {f['hotels']:3} (сверяемых {f['multi_source_hotels']:3})  {src}")
    print("записано в", a.out or truth.FILE)


if __name__ == "__main__":
    main()
