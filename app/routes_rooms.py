"""Эндпоинты подбора номера: категории отеля с просьбой для брони и короткие подсказки для выдачи поиска."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app import actions
from app import geodata as gd

WEB = Path(__file__).resolve().parent / "web"

router = APIRouter()


def _wants(w):
    return [x for x in (w or "").split(",") if x in ("sea", "sunset", "quiet")] or None


@router.get("/rooms.js")
def rooms_js():
    return FileResponse(WEB / "rooms.js", media_type="text/javascript")


@router.get("/api/rooms/{hotel_id}")
def room_advice(hotel_id: str, wants: str = "", month: int | None = None):
    if hotel_id not in gd.load().hotel_by_id:
        raise HTTPException(404, "нет такого отеля")
    return actions.room_advice(hotel_id, _wants(wants), month)


@router.get("/api/rooms")
def room_picks(ids: str, wants: str = "", month: int | None = None):
    """Одна строка «брать / попросить» на отель для карточек выдачи."""
    out = {}
    for hid in [i for i in ids.split(",") if i][:20]:
        if hid not in gd.load().hotel_by_id:
            continue
        a = actions.room_advice(hid, _wants(wants), month)
        b = a["best"]
        if b and b["special_request"]:
            out[hid] = {"room": b["room"], "ask": b["ask"], "sea_view_p": b["sea_view_p"], "hidden_view": b["hidden_view"],
                        "special_request": b["special_request"]}
    return out
