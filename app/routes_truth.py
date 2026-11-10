"""Движок правды по HTTP: аудит заявлений, репутация отельера, оценённая надёжность источников."""
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import audit, registry, store, truth
from app import geodata as gd

router = APIRouter()
WEB = Path(__file__).resolve().parent / "web"
SIDE = {"geo": "расчёт", "osm": "карта", "open-meteo": "метеоданные", "photos": "фото", "reviews": "отзывы",
        "card": "карточка", "hotelier": "отельер"}
SAYS = {"hotelier": "Отельер пишет", "card": "Карточка заявляет", "reviews": "Гости пишут", "geo": "Расчёт показывает",
        "osm": "Карта показывает", "open-meteo": "Метеоданные показывают", "photos": "Фото показывают"}
PLURAL = {"reviews", "photos", "open-meteo"}
TRUSTED = {"geo": "расчёту", "osm": "карте", "open-meteo": "метеоданным", "photos": "фото", "reviews": "отзывам",
           "card": "карточке", "hotelier": "отельеру"}


def _says(fact):
    """Что сказал источник: цитата в «ёлочках» из сводки факта, иначе да/нет."""
    m = re.search(r"«([^»]+)»", fact["summary"] or "")
    return m.group(1).rstrip(".") if m else None


def plain_sentence(r, spec):
    """Одна фраза для гостя: кто что сказал, что показывают остальные и кому мы поверили."""
    if r["status"] != "conflict" or not r.get("conflicts"):
        return None
    val = r["value"].get(spec["key"])
    votes = [v for v in r["trust"]["votes"] if abs(v["contrib"]) >= 0.05]
    by_src = {f["source"]: f for f in r["facts"]}
    lose = [v["source"] for v in votes if v["vote"] != val]
    win = sorted((v for v in votes if v["vote"] == val), key=lambda v: -abs(v["contrib"]))
    if not lose or not win:
        return None
    who = lose[0]
    if spec["id"] in audit.MIN_COMPLAINTS and val is False and audit._complaints(r["facts"]) < audit.MIN_COMPLAINTS[spec["id"]]:
        return None   # одна жалоба ещё не спор
    said = _says(by_src[who]) if who in by_src else None
    said = f"«{said}»" if said else f"«{spec['name']}: {'да' if not val else 'нет'}»"
    names = [SIDE.get(v["source"], v["source"]) for v in win[:2]]
    top = audit.plain(by_src[win[0]["source"]]["summary"]) if win[0]["source"] in by_src else ""
    return (f"{SAYS.get(who, 'Источник сообщает')} {said}, но {' и '.join(names)} {'говорят' if len(names) > 1 or win[0]['source'] in PLURAL else 'говорит'} иное"
            f"{': ' + top if top else ''}. Мы верим {TRUSTED.get(win[0]['source'], 'расчёту')}.")


def _known(hotel_id):
    if hotel_id not in gd.load().hotel_by_id:
        raise HTTPException(404, "нет такого отеля")


@router.get("/truth.js")
def truth_js():
    return FileResponse(WEB / "truth.js", media_type="application/javascript")


@router.get("/api/truth/audit")
def audit_overview(limit: int = 30):
    return audit.audit_all(limit)


@router.get("/api/truth/audit/{hotel_id}")
def audit_one(hotel_id: str):
    _known(hotel_id)
    return audit.audit_hotel(hotel_id)


@router.get("/api/truth/hotel/{hotel_id}")
def hotel_trust(hotel_id: str):
    """Репутация отельера и по каждой булевой характеристике: кому поверили и почему."""
    _known(hotel_id)
    rows = []
    for cid, spec in registry.all_chars().items():
        if not truth.is_bool_key(spec):
            continue
        r = store.resolve(hotel_id, spec)
        if r.get("trust"):
            rows.append({"char": cid, "name": spec["name"], "class": r["class"], "value": r["value"].get(spec["key"]),
                         "confidence": r["confidence"], "status": r["status"], "sentence": plain_sentence(r, spec),
                         **r["trust"]})
    return {"reputation": truth.hotelier_reputation(hotel_id), "chars": rows}


class Suggest(BaseModel):
    char_id: str


@router.post("/api/truth/suggest/{hotel_id}")
def suggest_to_card(hotel_id: str, s: Suggest):
    """Гость или админ предлагает дописать в карточку то, что расчёт уверенно видит, а карточка молчит."""
    _known(hotel_id)
    if s.char_id not in registry.all_chars():
        raise HTTPException(404, "нет такой характеристики")
    store.log_event("card_suggestion", hotel_id, s.char_id, {"text": "предложено дописать в карточку"})
    return {"logged": True}


@router.get("/api/truth/reliability")
def reliability():
    return {c: truth.reliability(s) for c, s in registry.all_chars().items() if truth.is_bool_key(s)}
