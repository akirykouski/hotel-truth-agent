"""API радара изменений: сигналы и отправка вопросов отельерам."""
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import geodata as gd
from app import radar
from app.auth import require_admin

router = APIRouter()
WEB = Path(__file__).resolve().parent / "web"


class Apply(BaseModel):
    alerts: list[dict] | None = None
    ids: list[str] | None = None


def _scan(now=None):
    alerts = radar.scan(now=now)
    st = radar.states(alerts)
    geo = gd.load()
    for a in alerts:
        a["state"] = st[a["id"]]
        a["url"] = geo.hotel_by_id[a["hotel_id"]]["url"]
    return alerts


@router.get("/api/radar")
def get_radar(now: str | None = None):
    alerts = _scan(now)
    return {"osm_base": str(gd.load().osm_meta["osm_base"])[:10], "window_days": radar.WINDOW_DAYS,
            "summary": radar.summary(alerts), "alerts": alerts}


@router.post("/api/radar/apply", dependencies=[Depends(require_admin)])
def apply_radar(a: Apply, now: str | None = None):
    """Без тела: применить все сигналы. Со списком ids или alerts: только их."""
    alerts = a.alerts
    if not alerts:
        alerts = _scan(now)
        if a.ids:
            alerts = [x for x in alerts if x["id"] in set(a.ids)]
    res = radar.apply(alerts, now)
    return {"applied": len(res), "queued": sum(r["state"] == "queued" for r in res), "results": res}


@router.get("/radar.js")
def radar_js():
    return FileResponse(WEB / "radar.js", media_type="application/javascript")
