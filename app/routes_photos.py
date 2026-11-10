"""Отдаёт app/web/photos.js (UI фото-датчика: миниатюры в карточке отеля и блок сверки в метриках)."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()
WEB = Path(__file__).resolve().parent / "web"


@router.get("/photos.js", include_in_schema=False)
def photos_js():
    return FileResponse(WEB / "photos.js", media_type="application/javascript")
