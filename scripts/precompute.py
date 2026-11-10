"""Предрасчёт фактов по всем характеристикам реестра для всех отелей демо-зоны → data/facts.sqlite.

Жюри не нужно это запускать: база лежит в репозитории. Запускать после изменения данных или рецептов.
  python scripts/precompute.py            # всё с нуля
  python scripts/precompute.py sea_view   # только одна характеристика
  python scripts/precompute.py --region adler   # то же для региона из data/regions/adler/ (или REGION=adler)
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    args = sys.argv[1:]
    if "--region" in args:  # до импорта app: регион читается при загрузке модулей
        i = args.index("--region")
        os.environ["REGION"] = args[i + 1]
        del args[i:i + 2]
    only = args
    from app import geodata as gd, registry, store  # noqa: E402
    store.DB_PATH = store.SEED_PATH  # пишем предрасчёт в файл репозитория
    if not only and store.SEED_PATH.exists():
        store.SEED_PATH.unlink()
    runtime = store.SEED_PATH.parent / "cache" / "facts.runtime.sqlite"
    if runtime.exists():
        runtime.unlink()  # рабочая копия пересоздастся из нового предрасчёта
    t = time.time()
    print(f"характеристик: {len(only or registry.all_chars())}, отелей: {len(gd.load().hotels)}", flush=True)
    errors = registry.compute_all(only or None, log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
    n = 0
    if not only:
        for h in gd.load().hotels:
            n += len(registry.plan_questions(h["id"]))
    store.log_event("precompute", payload={"chars": only or "all", "errors": errors, "questions": n})
    print(f"готово за {time.time() - t:.0f} с, ошибок {errors}, вопросов отельерам {n}")


if __name__ == "__main__":
    main()
