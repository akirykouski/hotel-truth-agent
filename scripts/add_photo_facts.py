"""Дописывает в seed data/facts.sqlite факты источника photos (sea_view, blackout, accessibility) из
data/photo_labels.json. Факты других источников не трогает: исполняются только методы с source: photos.
  python scripts/add_photo_facts.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import geodata as gd, registry, store  # noqa: E402

CHARS = ("sea_view", "blackout", "accessibility")


def main():
    store.DB_PATH = store.SEED_PATH
    c = store.conn()
    c.execute("DELETE FROM facts WHERE source='photos'")
    c.commit()
    n = {}
    for cid in CHARS:
        spec = registry.get(cid)
        for m in (m for m in spec["methods"] if m["source"] == "photos"):
            for h in gd.load().hotels:
                r = registry.run_method(spec, m, h["id"])
                if r is None:
                    continue
                store.put_fact(h["id"], cid, "photos", r["value"], r["confidence"], r["summary"], m["method"],
                               spec.get("ttl_days", 180), r["evidence"], r["scope"], str(spec.get("version", 1)))
                n[cid] = n.get(cid, 0) + 1
    c.execute("VACUUM")
    print("фактов photos:", n)


if __name__ == "__main__":
    main()
