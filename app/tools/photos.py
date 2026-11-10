"""Фото отеля как независимый датчик: замороженные метки зрения Claude (scripts/label_photos.py).

Метки лежат в data/photo_labels.json: {hotel_id: [{url, labels}]}. Инструмент только агрегирует их по отелю,
фактов не придумывает. Главная оговорка: отели снимают лучшие номера, поэтому «моря на фото нет» значит
меньше, чем «море на фото есть».
"""
import json
from functools import lru_cache
from pathlib import Path

LABELS = Path(__file__).resolve().parent.parent.parent / "data" / "photo_labels.json"
MIN_CONF = 0.6   # кадры с меньшей уверенностью разметки не считаем
ROOMISH = ("room", "balcony", "view_from_window")


@lru_cache(maxsize=1)
def _load():
    return json.loads(LABELS.read_text(encoding="utf-8")) if LABELS.exists() else {}


def _yn(items, key):
    """Есть ли хоть один кадр с yes / с no по полю; кадры с низкой уверенностью пропускаем."""
    vals = [i["labels"][key] for i in items if i["labels"].get(key) in ("yes", "no")]
    return {"yes": vals.count("yes"), "no": vals.count("no")}


def photo_labels(hotel_id):
    items = [i for i in _load().get(hotel_id, []) if (i["labels"].get("confidence") or 0) >= MIN_CONF]
    roomish = [i for i in items if i["labels"]["kind"] in ROOMISH]
    sea_room = [i for i in roomish if i["labels"].get("sea_from_room")]
    sea_any = [i for i in items if i["labels"].get("sea_visible")]
    ev = lambda i: {"url": i["url"], "kind": i["labels"]["kind"], "note": i["labels"].get("note"),   # noqa: E731
                    "sea": bool(i["labels"].get("sea_visible")), "sea_from_room": bool(i["labels"].get("sea_from_room")),
                    "confidence": i["labels"].get("confidence")}
    return {"photos": len(items), "room_photos": len(roomish), "sea_from_room": len(sea_room),
            "sea_any": len(sea_any), "best_conf": max([i["labels"]["confidence"] for i in sea_room], default=0.0),
            "views": sorted({i["labels"]["view"] for i in roomish} - {"unknown", "none"}),
            "blackout": _yn(roomish, "blackout_curtains"), "steps": _yn(items, "entrance_steps"),
            "elevator": _yn(items, "elevator"),
            "evidence": [ev(i) for i in items if i["labels"]["kind"] in ROOMISH or i["labels"].get("sea_visible")
                         or i["labels"].get("entrance_steps") == "yes" or i["labels"].get("elevator") == "yes"
                         or i["labels"].get("blackout_curtains") == "yes"]}
