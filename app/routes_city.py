"""API профиля города: веса характеристик активного региона, ручная правка, кандидаты из запросов гостей и их сборка."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import city
from app.auth import Principal, require_admin

router = APIRouter()
WEB = Path(__file__).resolve().parent / "web"


class CharEdit(BaseModel):
    weight: float | None = None
    reset: bool = False
    status: str | None = None


class Request(BaseModel):
    phrase: str
    proposal: str | None = None
    build: bool = False


class RequestEdit(BaseModel):
    status: str


def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except KeyError as e:
        raise HTTPException(404, f"нет такого параметра: {e}") from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/city.js", include_in_schema=False)
def script():
    return FileResponse(WEB / "city.js", media_type="text/javascript")


@router.get("/api/city")
def profile():
    return city.profile()


@router.post("/api/city/recompute")
def recompute(who: Principal = Depends(require_admin)):
    return {"recomputed": city.recompute()}


@router.post("/api/city/chars/{char_id}")
def edit_char(char_id: str, e: CharEdit, who: Principal = Depends(require_admin)):
    return _call(city.set_char, char_id, e.weight, e.reset, e.status)


@router.post("/api/city/requests")
def add_request(r: Request, who: Principal = Depends(require_admin)):
    row = _call(city.add_request, r.phrase.strip(), r.proposal)
    return row | ({"job": city.build_request(row["id"])} if r.build else {})


@router.post("/api/city/requests/{rid}/build")
def build(rid: str, who: Principal = Depends(require_admin)):
    return {"job": _call(city.build_request, rid)}


@router.post("/api/city/requests/{rid}")
def edit_request(rid: str, e: RequestEdit, who: Principal = Depends(require_admin)):
    _call(city.set_request, rid, e.status)
    return {"ok": True}
