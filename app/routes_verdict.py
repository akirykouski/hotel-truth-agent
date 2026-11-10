"""Вердикт в карточке отеля: отдаём скрипт, данные берёт из уже существующих эндпоинтов."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()
JS = Path(__file__).resolve().parent / "web" / "verdict.js"


@router.get("/web/verdict.js")
def script():
    return FileResponse(JS, media_type="text/javascript")
