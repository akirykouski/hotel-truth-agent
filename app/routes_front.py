"""Витрина: правка разобранного запроса без повторного разбора текста.

Гость убирает плашку-условие, добавляет новое или делает его «желательным». Фронт присылает
исправленный разбор, мы ищем по нему. Новое условие разбираем правилами по короткой фразе.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from app import actions, answer, registry, search, store
from app import geodata as gd

router = APIRouter()


class Parsed(BaseModel):
    query: str
    parsed: dict
    limit: int = 300


class Phrase(BaseModel):
    text: str


def _clean(parsed: dict) -> dict:
    """Оставляем только условия по известным характеристикам и полям."""
    cons = []
    for c in parsed.get("constraints") or []:
        spec = registry.get(c.get("char"))
        if spec and c.get("field") in spec["fields"] and c.get("op") in search.OPS:
            cons.append({**c, "must": c.get("must", True) is not False})
    base = parsed.get("base") or {}
    return {**parsed, "constraints": cons, "missing": parsed.get("missing") or [],
            "base": {k: base.get(k) for k in ("max_price", "min_stars", "min_rating")}}


@router.post("/api/search/parsed")
def search_parsed(p: Parsed):
    # тот же ответ, что у /api/search (корзины, смягчения, «нечего проверять»), только по готовому разбору
    return actions.search_hotels(p.query, p.limit, parsed=_clean(p.parsed))


class Fit(BaseModel):
    hotel_ids: list[str]
    constraints: list[dict]
    month: int | None = None


# Чем мерить «насколько хорошо» выполнено условие: поле значения, что лучше (lo/hi), допуск, при котором
# разница не в счёт, и подпись. Галочка «да» у двух отелей не значит «одинаково»: 4 минуты до пляжа лучше 9.
MEASURE = {
    "beach_walk": ("minutes_there", "lo", 1, lambda v: f"{v:.0f} мин до пляжа"),
    "sea_view": ("from_floor", "lo", 0, lambda v: f"море видно с {v:.0f}-го этажа"),
    "sunset": ("from_floor", "lo", 0, lambda v: f"закат видно с {v:.0f}-го этажа"),
    "night_quiet": ("night_db_quiet", "lo", 1, lambda v: f"ночью {v:.0f} дБ на тихой стороне"),
    "food_near": ("count", "hi", 3, lambda v: f"{v:.0f} мест поесть в 300 м"),
    "car": ("parking_m", "lo", 30, lambda v: f"парковка в {v:.0f} м"),
    "kids": ("playground_m", "lo", 40, lambda v: f"площадка в {v:.0f} м"),
    "blackout": ("share", "hi", .05, lambda v: f"блэкаут в {v * 100:.0f}% категорий номеров"),
    "wifi": ("good_share", "hi", .05, lambda v: f"Wi-Fi «отлично» у {v * 100:.0f}% гостей"),
    "breakfast": ("meal_score", "hi", .3, lambda v: f"еду гости оценивают на {v:.1f} из 10"),
    "kitchen": ("share", "hi", .1, lambda v: f"кухня в {v * 100:.0f}% категорий номеров"),
    "balcony": ("share", "hi", .1, lambda v: f"балкон в {v * 100:.0f}% категорий номеров"),
    "adults_only": ("families_share", "lo", .05, lambda v: f"семей с детьми {v * 100:.0f}% среди гостей"),
    "family": ("families_share", "hi", .05, lambda v: f"семей с детьми {v * 100:.0f}% среди гостей"),
}


def _measure(hid, char, month):
    m = MEASURE.get(char)
    spec = registry.get(char)
    if not m or not spec:
        return None
    r = store.resolve(hid, spec)
    v = r.get("value") or {}
    if isinstance(v, dict) and "by_month" in v:  # закат зависит от месяца поездки
        v = (v["by_month"] or {}).get(str(month or 7)) or {}
    x = v.get(m[0]) if isinstance(v, dict) else None
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return None
    return {"value": x, "better": m[1], "tol": m[2], "text": m[3](x)}


@router.post("/api/compare/fit")
def compare_fit(f: Fit):
    """Сравнение под выбор гостя: выполняет ли каждый отель то, что гость назвал важным, и насколько хорошо."""
    cons = _clean({"constraints": f.constraints})["constraints"]
    out = []
    for hid in f.hotel_ids:
        cache = {}
        out.append({"hotel_id": hid, "checks": [{"char": c["char"], "field": c["field"],
                                                 "status": search.check(hid, c, f.month, cache)["status"],
                                                 "measure": _measure(hid, c["char"], f.month)} for c in cons]})
    return {"hotels": out}


@router.post("/api/parse/rules")
def parse_phrase(p: Phrase):
    """Разбор короткой фразы правилами (без LLM): для кнопки «+ условие»."""
    r = search.parse_rules(p.text)
    return {"constraints": r["constraints"], "month": r["month"]}


class Ask(BaseModel):
    query: str = ""
    hotel_ids: list[str]           # подходящие отели в порядке выдачи
    parsed: dict | None = None
    priorities: list[str] = []     # характеристики из «Что важнее?», по порядку
    month: int | None = None


@router.post("/api/answer")
def answer_forks(a: Ask):
    """Один отель-ответ и развилки «если важнее …», только если среди подходящих есть настоящий компромисс."""
    by = gd.load().hotel_by_id
    hotels = [search._brief(by[i]) for i in a.hotel_ids if i in by]
    return answer.build(hotels, a.parsed, a.query, a.priorities, a.month or (a.parsed or {}).get("month"))
