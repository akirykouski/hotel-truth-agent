"""Активный регион: имя из переменной REGION, папка данных и метаданные (подпись, центр, рамка).

Без REGION работает демо-зона: центр Сочи, данные лежат прямо в data/. Регион из scripts/add_region.py живёт в
data/regions/<имя>/ со своими отелями, OSM, картой высот, климатом и facts.sqlite.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = (os.getenv("REGION") or "").strip() or None

DEFAULT_META = {
    "name": "default", "label": "центр Сочи", "label_in": "в центре Сочи", "label_of": "центра Сочи", "place_in": "в Сочи",
    "center": [43.595, 39.735], "sun_lat": 43.6,
}


def data_dir(name=NAME) -> Path:
    return ROOT / "data" / "regions" / name if name else ROOT / "data"


def load_meta(name=NAME) -> dict:
    if not name:
        return dict(DEFAULT_META)
    f = data_dir(name) / "region.json"
    if not f.exists():
        raise SystemExit(f"регион {name!r} не найден: нет {f}. Создайте его: python scripts/add_region.py --name {name} ...")
    return DEFAULT_META | json.loads(f.read_text(encoding="utf-8"))


META = load_meta()
DATA = data_dir()
