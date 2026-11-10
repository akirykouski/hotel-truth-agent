"""Ночь по часам: данные для карточки отеля и сам скрипт блока."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app import geodata as gd
from app.tools import noise

router = APIRouter()
JS = Path(__file__).resolve().parent / "web" / "nightline.js"


@router.get("/api/hotels/{hotel_id}/night")
def night(hotel_id: str, month: int = 7, weekday: int = 5):
    if hotel_id not in gd.load().hotel_by_id:
        raise HTTPException(404, "нет такого отеля")
    return noise.timeline(hotel_id, month, weekday)


@router.get("/web/nightline.js")
def script():
    return FileResponse(JS, media_type="text/javascript")
