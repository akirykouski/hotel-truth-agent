"""API черновиков: список с авто-отчётом, одобрить/отклонить, асинхронная сборка и её шаги."""
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import compiler, registry, store
from app.auth import Principal, require_admin

router = APIRouter()
WEB = Path(__file__).resolve().parent / "web"


@router.get("/drafts.js")
def script():
    return FileResponse(WEB / "drafts.js", media_type="text/javascript")


class Decision(BaseModel):
    reason: str = ""   # «кто» в журнале берётся из токена, не из тела


class Build(BaseModel):
    description: str


def _card(spec):
    return {"id": spec["id"], "name": spec["name"], "description": spec["description"].strip(), "status": registry.status(spec),
            "origin": spec.get("origin"), "key": spec.get("key"), "keywords": spec.get("keywords", []),
            "drafted_at": spec.get("drafted_at"), "approved_by": spec.get("approved_by"),
            "rejected_reason": spec.get("rejected_reason"), "eval": spec.get("eval")}


@router.get("/api/drafts")
def drafts(status: str = "draft"):
    return {"drafts": [_card(s) for s in registry.drafts(status)]}


def _decide(char_id, fn, *args):
    spec = registry.get(char_id)
    if spec is None or spec.get("origin") not in ("compiled", "template"):
        raise HTTPException(404, "нет такого черновика")
    return _card(fn(char_id, *args))


@router.post("/api/drafts/{char_id}/approve")
def approve(char_id: str, d: Decision = Decision(), who: Principal = Depends(require_admin)):
    return _decide(char_id, registry.approve, who.sub)


@router.post("/api/drafts/{char_id}/reject")
def reject(char_id: str, d: Decision = Decision(), who: Principal = Depends(require_admin)):
    return _decide(char_id, registry.reject, d.reason, who.sub)


@router.post("/api/drafts/build")
def build(b: Build, x_session: str | None = Header(None), who: Principal = Depends(require_admin)):
    return {"job": compiler.build_async(b.description, x_session)}


@router.get("/api/drafts/jobs")
def jobs():
    return {"jobs": [compiler.public_job(j) for j in sorted(compiler.JOBS.values(), key=lambda j: -j["started"])]}


@router.get("/api/drafts/jobs/{job_id}")
def job(job_id: str):
    j = compiler.JOBS.get(job_id)
    if j is None:
        raise HTTPException(404, "нет такой задачи")
    out = compiler.public_job(j)
    if j["status"] == "done" and j["char_id"]:
        spec = registry.get(j["char_id"])
        out["result"] = _card(spec) if spec else None
    return out
