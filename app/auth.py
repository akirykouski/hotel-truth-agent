"""Роли и доступ на сервере: гость (без токена), отельер (один отель) и админ (команда Островка).

Токен: подписанный HMAC-SHA256 bearer вида `v1.<payload>.<подпись>`, в payload роль, отель, срок.
Секрет: AUTH_SECRET из окружения; если не задан, один раз генерируется и хранится в data/cache/auth_secret
(общий том app и mcp, чтобы токен, выданный одним контейнером, понимал другой).

ДЕМО-ВХОД. /api/auth/admin (пароль ADMIN_PASSWORD, по умолчанию `demo`) и /api/auth/hotelier (отель + код
HOTELIER_DEMO_CODE, по умолчанию `demo`) нужны только чтобы жюри могло пройти по ролям. В продакшене токен выдаёт
партнёрский вход Островка (SSO/ЛК отельера), остальной код не меняется: он проверяет только токен.
Кто совершил действие, берётся из токена (`Principal.sub`), никогда из тела запроса.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

TTL_S = int(os.getenv("AUTH_TTL_S") or 12 * 3600)
SECRET_FILE = Path(os.getenv("AUTH_SECRET_FILE") or Path(__file__).resolve().parent.parent / "data" / "cache" / "auth_secret")


@dataclass(frozen=True)
class Principal:
    role: str = "guest"          # guest | hotelier | admin
    hotel_id: str | None = None
    sub: str = "guest"           # кто это в журнале: admin, hotelier:<hotel_id>


GUEST = Principal()
_secret_cache: bytes | None = None


def _secret() -> bytes:
    global _secret_cache
    if _secret_cache is None:
        env = os.getenv("AUTH_SECRET")
        if env:
            _secret_cache = env.encode()
        else:
            if not SECRET_FILE.exists():
                SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
                try:  # O_EXCL: два контейнера на старте не затрут секрет друг друга
                    fd = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "w") as f:
                        f.write(os.urandom(32).hex())
                except FileExistsError:
                    pass
            for _ in range(20):  # другой процесс мог создать файл, но ещё не дописать
                _secret_cache = SECRET_FILE.read_text().strip().encode()
                if _secret_cache:
                    break
                time.sleep(0.05)
    return _secret_cache


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sig(body: str) -> str:
    return _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())


def issue(role: str, hotel_id: str | None = None, ttl: int | None = None) -> str:
    sub = "admin" if role == "admin" else f"hotelier:{hotel_id}"
    body = _b64(json.dumps({"r": role, "h": hotel_id, "s": sub, "exp": int(time.time()) + (ttl or TTL_S)}).encode())
    return f"v1.{body}.{_sig(body)}"


def verify(token: str | None) -> Principal | None:
    try:
        ver, body, sig = (token or "").split(".")
        if ver != "v1" or not hmac.compare_digest(sig, _sig(body)):
            return None
        p = json.loads(_unb64(body))
        if p["exp"] < time.time() or p["r"] not in ("admin", "hotelier"):
            return None
        return Principal(p["r"], p.get("h"), p["s"])
    except Exception:
        return None


def current(authorization: str | None = Header(None)) -> Principal:
    """Кто пришёл. Без заголовка гость; заголовок есть, но токен битый или просрочен: 401, а не тихий гость."""
    if not authorization:
        return GUEST
    scheme, _, tok = authorization.partition(" ")
    p = verify(tok.strip()) if scheme.lower() == "bearer" else None
    if p is None:
        raise HTTPException(401, "Вход устарел или не распознан: войдите заново")
    return p


def require_admin(p: Principal = Depends(current)) -> Principal:
    if p.role == "admin":
        return p
    raise HTTPException(403 if p.role != "guest" else 401,
                        "Нужен вход команды Островка" if p.role == "guest" else "Это действие только для команды Островка")


def authorize_hotel(p: Principal, hotel_id: str) -> Principal:
    """Админ проходит всегда, отельер только к своему отелю."""
    if p.role == "admin" or (p.role == "hotelier" and p.hotel_id == hotel_id):
        return p
    if p.role == "guest":
        raise HTTPException(401, "Нужен вход отельера")
    raise HTTPException(403, "Это вопрос другого отеля: отвечать может только его отельер")


def require_hotelier(hotel_id: str, p: Principal = Depends(current)) -> Principal:
    """Зависимость для маршрутов с {hotel_id} в пути."""
    return authorize_hotel(p, hotel_id)


# ───── демо-вход ─────
router = APIRouter()


class AdminLogin(BaseModel):
    password: str = ""


class HotelierLogin(BaseModel):
    hotel_id: str
    code: str = ""


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _out(role, hotel_id=None):
    return {"token": issue(role, hotel_id), "role": role, "hotel_id": hotel_id, "expires_in": TTL_S,
            "demo": True, "note": "демо-вход; в продакшене токен выдаёт партнёрский вход Островка"}


@router.post("/api/auth/admin")
def login_admin(b: AdminLogin):
    if not _eq(b.password, os.getenv("ADMIN_PASSWORD") or "demo"):
        raise HTTPException(401, "Неверный пароль")
    return _out("admin")


@router.post("/api/auth/hotelier")
def login_hotelier(b: HotelierLogin):
    from app import geodata as gd
    if b.hotel_id not in gd.load().hotel_by_id:
        raise HTTPException(404, "нет такого отеля")
    if not _eq(b.code, os.getenv("HOTELIER_DEMO_CODE") or "demo"):
        raise HTTPException(401, "Неверный код")
    return _out("hotelier", b.hotel_id)


@router.get("/api/auth/me")
def me(p: Principal = Depends(current)):
    return {"role": p.role, "hotel_id": p.hotel_id, "sub": p.sub}
