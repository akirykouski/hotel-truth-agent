"""Интерфейсы по ролям. / ведёт на выбор роли /choose-role: гость — витрина /ui (app/web/front), отельер — /hotelier,
команда Островка — /backoffice (он же /admin). /ui/classic — прежняя страница гостя.

/hotelier, /backoffice и /ui/classic отдают общий index.html: роль определяется по адресу, roles.js оставляет её вкладки
и перекладывает страницу, skin.css и front/postcard-roles.css дают стиль. Модули работают без изменений.
"""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

WEB = Path(__file__).resolve().parent / "web"
router = APIRouter()


def _page():
    return FileResponse(WEB / "index.html")


def _front():
    return FileResponse(WEB / "front" / "index.html")


def _choose():
    return FileResponse(WEB / "front" / "choose-role.html")


for _path, _fn in (("/ui", _front), ("/choose-role", _choose), ("/ui/classic", _page), ("/hotelier", _page), ("/backoffice", _page), ("/admin", _page)):
    router.add_api_route(_path, _fn, methods=["GET"], include_in_schema=False)
    router.add_api_route(_path + "/", _fn, methods=["GET"], include_in_schema=False)


@router.get("/web/roles.js", include_in_schema=False)
def roles_js():
    return FileResponse(WEB / "roles.js", media_type="application/javascript")


@router.get("/web/auth.js", include_in_schema=False)
def auth_js():
    return FileResponse(WEB / "auth.js", media_type="application/javascript")


@router.get("/web/skin.css", include_in_schema=False)
def skin_css():
    return FileResponse(WEB / "skin.css", media_type="text/css")


@router.get("/favicon.svg", include_in_schema=False)
def favicon():
    return FileResponse(WEB / "favicon.svg", media_type="image/svg+xml")


@router.get("/favicon.ico", include_in_schema=False)
def favicon_ico():  # браузеры спрашивают .ico сами, отдаём тот же SVG
    return RedirectResponse("/favicon.svg", status_code=308)
