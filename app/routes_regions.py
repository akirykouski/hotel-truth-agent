"""API регионов: список, источники отелей и их точки, проверка рамки, сборка по этапам, отмена, переключение."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from app import regions
from app.auth import require_admin

router = APIRouter()
WEB = Path(__file__).resolve().parent / "web"


class Box(BaseModel):
    source: str
    bbox: list[float]

    @field_validator("bbox")
    @classmethod
    def _bbox(cls, b):
        if len(b) != 4 or b[0] >= b[2] or b[1] >= b[3]:
            raise ValueError("нужно [юг, запад, север, восток]")
        return [round(x, 5) for x in b]


class Build(Box):
    name: str
    label: str | None = None
    label_in: str | None = None
    label_of: str | None = None
    reuse: bool = False
    overwrite: bool = False


class Switch(BaseModel):
    name: str


def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except regions.RegionError as e:
        raise HTTPException(e.code, str(e)) from e


@router.get("/regions.js", include_in_schema=False)
def script():
    return FileResponse(WEB / "regions.js", media_type="text/javascript")


@router.get("/api/regions")
def listing():
    return {"regions": regions.listing(), "sources": regions.sources(), "running": regions.running()}


@router.get("/api/regions/sources/{source}/points")
def points(source: str):
    return _call(regions.points, source)


@router.post("/api/regions/check")
def check(b: Box):
    return _call(regions.check, b.source, b.bbox)


@router.post("/api/regions/build", dependencies=[Depends(require_admin)])
def build(b: Build):
    return _call(regions.start, b.name.strip().lower(), b.source, b.bbox, b.label, b.label_in, b.label_of,
                 b.reuse, b.overwrite)


@router.get("/api/regions/jobs")
def jobs():
    return {"jobs": regions.jobs()}


@router.get("/api/regions/jobs/{job_id}")
def job(job_id: str, log: bool = False):
    return _call(regions.job, job_id, log)


@router.post("/api/regions/jobs/{job_id}/cancel", dependencies=[Depends(require_admin)])
def cancel(job_id: str):
    return _call(regions.cancel, job_id)


@router.post("/api/regions/switch", dependencies=[Depends(require_admin)])
def switch(s: Switch):
    return _call(regions.switch, s.name)
