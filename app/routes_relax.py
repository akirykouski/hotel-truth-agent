"""Ослабление условий поиска: пересчёт с убранным или смягчённым условием и скрипт интерфейса."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import actions

router = APIRouter()
WEB = Path(__file__).resolve().parent / "web"


class Relax(BaseModel):
    query: str
    parsed: dict | None = None      # исходный разбор запроса (из первой выдачи), чтобы не разбирать заново
    drop: list[int | str] = []      # номера условий (idx) или имена характеристик
    loosen: dict[str, float] = {}   # {idx: новый порог}
    limit: int = 5


@router.post("/api/relax")
def relax(r: Relax):
    return actions.search_hotels(r.query, r.limit, parsed=r.parsed, drop=r.drop, loosen=r.loosen)


@router.get("/relax.js")
def script():
    return FileResponse(WEB / "relax.js", media_type="application/javascript")
