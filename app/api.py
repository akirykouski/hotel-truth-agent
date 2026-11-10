"""HTTP API и веб-интерфейс. Запуск: uvicorn app.api:app --port 8000"""
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from app import actions, agent, city, demo_draft, hotelier, llm, region, registry, routes_drafts, routes_grounding, routes_truth, search, store
from app import geodata as gd
from app.auth import Principal, authorize_hotel, current, require_admin
from app.routes_relax import router as relax_router

WEB = Path(__file__).resolve().parent / "web"
app = FastAPI(title="Островок: факты об отелях")
app.include_router(relax_router)
app.include_router(routes_drafts.router)
app.add_event_handler("startup", demo_draft.ensure)
app.add_event_handler("startup", lambda: threading.Thread(target=city.ensure, daemon=True).start())  # профиль города, ~2 с

from app import routes_nightline  # noqa: E402
app.include_router(routes_nightline.router)
app.include_router(routes_truth.router)
from app.routes_photos import router as photos_router  # noqa: E402
app.include_router(photos_router)
app.include_router(routes_grounding.router)
from app.routes_waitgames import router as _arcade_router; app.include_router(_arcade_router)  # noqa: E402,E702
from app.routes_front import router as _front_router; app.include_router(_front_router)  # noqa: E402,E702


class Chat(BaseModel):
    messages: list[dict]
    parsed: dict | None = None  # разбор быстрого поиска: агент ищет по тем же условиям, что видит гость
    run: str | None = None  # id запуска от страницы: по нему /api/chat/progress отдаёт живую стадию


class Query(BaseModel):
    query: str
    limit: int = 10


class Compare(BaseModel):
    hotel_ids: list[str]
    chars: list[str] | None = None


class NewChar(BaseModel):
    description: str


class Answer(BaseModel):
    answer: str
    echo: bool = False  # кабинет: сначала эхо «Мы поняли так… Верно?», факт после /confirm


class Confirm(BaseModel):
    ok: bool = True


class Ask(BaseModel):
    char_id: str
    question: str | None = None


class Building(BaseModel):
    lat: float
    lon: float
    levels: int = 16
    radius_m: float = 25


@app.get("/")
def index(request: Request):
    # сначала выбор роли: гость /ui, отельер /hotelier, команда /backoffice; ссылка с запросом (/?q=...) ведёт сразу к гостю
    q = request.url.query
    return RedirectResponse("/ui?" + q if q else "/choose-role", status_code=307)


@app.get("/health")
def health():
    # для healthcheck в docker compose: процесс жив и база фактов открывается
    store.conn().execute("SELECT 1").fetchone()
    return {"status": "ok", "region": region.NAME or "default"}


@app.get("/api/status")
def status():
    geo = gd.load()
    return {"llm": llm.available(), "provider": llm.PROVIDER, "model": llm.MODEL if llm.available() else None,
            "hotels": len(geo.hotels), "characteristics": len(registry.public_chars()),
            "region": region.NAME or "default", "zone": region.META["label"], "center": region.META["center"],
            "osm_base": geo.osm_meta["osm_base"],
            "open_questions": len(store.questions(status="open"))}


@app.post("/api/chat")
def chat(c: Chat, x_session: str | None = Header(None)):
    return agent.chat(c.messages[-12:], session=x_session, parsed_in=c.parsed, run=c.run)


@app.get("/api/chat/progress")
def chat_progress(run: str):
    return {"stage": agent.progress(run)}


@app.post("/api/search")
def do_search(q: Query, x_session: str | None = Header(None)):
    return actions.search_hotels(q.query, q.limit, session=x_session)


@app.get("/api/hotels")
def hotels(q: str = ""):
    if q:
        return actions.find_hotel(q)
    return [search._brief(h) for h in gd.load().hotels]


@app.get("/api/hotels/{hotel_id}")
def hotel(hotel_id: str, x_session: str | None = Header(None)):
    geo = gd.load()
    if hotel_id not in geo.hotel_by_id:
        raise HTTPException(404, "нет такого отеля")
    h = geo.hotel_by_id[hotel_id]
    out = actions.hotel_facts(hotel_id, full=True, session=x_session)
    out["card"] = {"rooms": [r["name"] for r in h["rooms"]], "photos": h["photos"], "description": h["description"][:1200],
                   "url": h["url"]}
    return out


@app.post("/api/compare")
def compare(c: Compare):
    return actions.compare_hotels(c.hotel_ids, c.chars)


@app.get("/api/characteristics")
def chars(x_session: str | None = Header(None)):
    return actions.list_characteristics(session=x_session)


@app.post("/api/characteristics")
def add_char(n: NewChar, x_session: str | None = Header(None)):
    return actions.add_characteristic(n.description, session=x_session)


@app.get("/api/hotelier/{hotel_id}")
def inbox(hotel_id: str):
    return actions.hotelier_inbox(hotel_id)


@app.get("/api/questions")
def questions(status: str | None = "open"):
    geo = gd.load()
    return [q | {"hotel_name": geo.hotel_by_id[q["hotel_id"]]["name"]} for q in actions.question_views(store.questions(status=status))]


def _own_question(qid: int, who: Principal) -> dict:
    """Вопрос по id; отвечает отельер этого отеля или админ, чужой отель закрыт."""
    q = next((x for x in store.questions() if x["id"] == qid), None)
    if q is None:
        raise HTTPException(404, "нет такого вопроса")
    authorize_hotel(who, q["hotel_id"])
    return q


@app.post("/api/questions/{qid}/answer")
def answer(qid: int, a: Answer, who: Principal = Depends(current)):
    _own_question(qid, who)
    try:   # «кто» в журнале из токена
        return hotelier.preview(qid, a.answer) if a.echo else hotelier.answer(qid, a.answer, by=who.sub)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/questions/{qid}/confirm")
def confirm(qid: int, c: Confirm = Confirm(), who: Principal = Depends(current)):
    _own_question(qid, who)
    try:
        return hotelier.confirm(qid, c.ok, by=who.sub)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/hotels/{hotel_id}/ask")
def ask(hotel_id: str, a: Ask):
    return actions.ask_hotelier(hotel_id, a.char_id, a.question)


@app.get("/api/events")
def events(limit: int = 50):
    return store.events(limit)


@app.get("/api/metrics")
def metrics():
    from app import metrics as m
    return m.report()


@app.post("/api/simulate/building")
def new_building(b: Building, who: Principal = Depends(require_admin)):
    from app import refresh
    return refresh.add_building(b.lat, b.lon, b.levels, b.radius_m)


@app.post("/api/refresh/stale")
def refresh_stale(before: str | None = None, who: Principal = Depends(require_admin)):
    from app import refresh
    return refresh.recheck_stale(before)


app.include_router(__import__("app.routes_radar", fromlist=["router"]).router)
from app.routes_window import router as _window_router; app.include_router(_window_router)  # noqa: E402
from app.routes_rooms import router as rooms_router; app.include_router(rooms_router)  # noqa: E402,E702
from app.routes_verdict import router as verdict_router; app.include_router(verdict_router)  # noqa: E402,E702
from app.routes_regions import router as regions_router; app.include_router(regions_router)  # noqa: E402,E702
from app.routes_city import router as city_router; app.include_router(city_router)  # noqa: E402,E702
from app.routes_openai import router as openai_router; app.include_router(openai_router)  # noqa: E402,E702
from app.routes_roles import router as roles_router; app.include_router(roles_router)  # noqa: E402,E702
from app.auth import router as auth_router; app.include_router(auth_router)  # noqa: E402,E702
