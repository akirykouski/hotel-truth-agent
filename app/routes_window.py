"""Вид из окна: панорама и вердикт по стороне здания, этажу и месяцу."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app import geodata as gd
from app.tools import window

router = APIRouter()
WEB = Path(__file__).resolve().parent / "web"


@router.get("/api/hotels/{hotel_id}/window")
def hotel_window(hotel_id: str, facade: str | None = None, floor: int | None = None, month: int = 7):
    if hotel_id not in gd.load().hotel_by_id:
        raise HTTPException(404, "нет такого отеля")
    try:
        return window.render(hotel_id, facade or None, floor, month)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/web/window.js")
def window_js():
    return FileResponse(WEB / "window.js", media_type="application/javascript")
