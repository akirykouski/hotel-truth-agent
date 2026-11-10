"""Маршруты заземления: скрипт значка сверки и проверка произвольного текста против вызовов инструментов."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import grounding

router = APIRouter()
WEB = Path(__file__).resolve().parent / "web"


class Check(BaseModel):
    text: str
    trace: list[dict]
    user_texts: list[str] = []


@router.get("/web/grounding.js")
def script():
    return FileResponse(WEB / "grounding.js", media_type="application/javascript")


@router.post("/api/grounding/verify")
def verify(c: Check):
    v = grounding.verify(c.text, c.trace, c.user_texts)
    return {k: (v[k] if k != "claims" else [{x: y for x, y in cl.items() if x != "span"} for cl in v[k]]) for k in v}
