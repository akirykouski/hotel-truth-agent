"""О!ркада и профиль устройства: статика игр и API профиля."""
from pathlib import Path

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import sense, taste, taste_synth, visitors
from app.auth import require_admin

WEB = Path(__file__).resolve().parent / "web"
DIRS = {"waitgames": WEB / "waitgames", "front": WEB / "front"}
TYPES = {".js": "text/javascript", ".css": "text/css", ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml"}
router = APIRouter()


class ProfileIn(BaseModel):
    sid: str
    profile: dict
    vid: str = ""


class RerankIn(BaseModel):
    sid: str = ""
    profile: dict
    results: list[dict]
    vid: str = ""
    demo: bool = False


class VisitIn(BaseModel):
    vid: str
    client: dict = {}


class EventsIn(BaseModel):
    vid: str
    events: list[dict]


class SeedIn(BaseModel):
    n: int = 300
    signal: float = 0.8
    seed: int = 7


def _serve(root: Path, path: str):
    p = (root / path).resolve()
    if not p.is_relative_to(root) or p.suffix not in TYPES or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type=TYPES[p.suffix], headers={"Cache-Control": "no-cache"})


@router.get("/waitgames/{path:path}")
def waitgames_asset(path: str):
    return _serve(DIRS["waitgames"], path)


@router.get("/front/{path:path}")
def front_asset(path: str):
    return _serve(DIRS["front"], path)


@router.post("/api/sense/profile")
def profile(b: ProfileIn):
    return sense.record(b.sid[:64], b.profile, b.vid[:64])


@router.post("/api/sense/rerank")
def rerank(b: RerankIn):
    return sense.rerank(b.profile, b.results, b.vid[:64], b.demo)


# ---------- посетитель: контекст, события, кластеры вкуса ----------

@router.post("/api/visit")
def visit(b: VisitIn, request: Request):
    if not b.vid:
        raise HTTPException(400, "нет vid")
    ip = visitors.client_ip(request.headers, request.client.host if request.client else None)
    return visitors.upsert_visit(b.vid, ip, {k.lower(): v for k, v in request.headers.items()}, b.client)


@router.post("/api/visit/forget")
def forget(b: VisitIn):
    visitors.forget(b.vid[:64])
    return {"ok": True}


@router.post("/api/events")
def events(b: EventsIn):
    if not b.vid:
        raise HTTPException(400, "нет vid")
    return {"stored": visitors.log_events(b.vid, b.events)}


@router.get("/api/taste/status")
def taste_status():
    return taste.status()


@router.post("/api/taste/refit", dependencies=[Depends(require_admin)])
def taste_refit(request: Request):
    _demo_allowed(request)
    return taste.refit()


def _demo_allowed(request: Request | None = None):
    """Засев синтетики и переобучение: только в демо (TASTE_DEMO=1) или с ключом TASTE_ADMIN_KEY."""
    key = os.getenv("TASTE_ADMIN_KEY")
    if key and request is not None and request.headers.get("x-admin-key") == key:
        return
    if os.getenv("TASTE_DEMO", "0") != "1":
        raise HTTPException(403, "демо выключено: TASTE_DEMO=1 или заголовок X-Admin-Key")


@router.post("/api/taste/seed", dependencies=[Depends(require_admin)])
def taste_seed(b: SeedIn, request: Request):
    """Демо: засеять синтетических посетителей (помечены, в порог не идут) и переобучить кластеры."""
    _demo_allowed(request)
    truth = taste_synth.generate(n=max(20, min(b.n, 3000)), signal=b.signal, seed=b.seed)
    gate = taste.refit(evaluate_gate=False)
    return {"seeded": len(truth), "status": taste.status(), "gate_real": gate["passed"]}


@router.delete("/api/taste/seed", dependencies=[Depends(require_admin)])
def taste_unseed(request: Request):
    _demo_allowed(request)
    n = taste_synth.wipe()
    taste.refit(evaluate_gate=False)
    return {"removed": n}


@router.get("/api/sense/summary")
def summary():
    return sense.summary()
