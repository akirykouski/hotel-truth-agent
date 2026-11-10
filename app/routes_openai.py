"""Агент как OpenAI-совместимый API: GET /v1/models и POST /v1/chat/completions (обычный ответ и stream).

Подходит любой клиент OpenAI (SDK, Open WebUI, LibreChat): base_url = http://localhost:8080/v1. Внутри тот же
agent.chat, что и у веб-чата: инструменты, сверка цифр, факты региона. Системные сообщения клиента не передаются,
у агента свой промпт. Журнал инструментов, сверка цифр и найденные отели лежат в поле ответа `ostrovok`.
Если задан AGENT_API_KEY, нужен заголовок Authorization: Bearer <ключ>, иначе доступ открыт (локальное демо).
"""
import json
import os
import time
import uuid

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import agent, region

router = APIRouter()
MODEL_ID = "ostrovok-agent"
API_KEY = os.getenv("AGENT_API_KEY") or None


def _error(status, message, kind="invalid_request_error"):
    return JSONResponse({"error": {"message": message, "type": kind, "param": None, "code": None}}, status_code=status)


def _authorized(authorization):
    return not API_KEY or (authorization or "").removeprefix("Bearer ").strip() == API_KEY


def _text(content):
    """content в формате OpenAI: строка или список частей [{type: text, text}]; картинки агент не читает."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _messages(raw):
    out = [{"role": m.get("role"), "content": _text(m.get("content"))} for m in raw if isinstance(m, dict)]
    return [m for m in out if m["role"] in ("user", "assistant") and m["content"].strip()][-12:]


def _extra(res):
    s = res.get("search") or {}
    hotels = [{"id": r["hotel"]["id"], "name": r["hotel"]["name"], "bucket": r["bucket"]} for r in (s.get("results") or [])[:5]]
    return {"region": region.NAME or "default", "mode": res.get("mode"), "grounding": res.get("grounding"),
            "trace": res.get("trace"), "hotels": hotels,
            "all_checked": s.get("all_checked"), "caveats": s.get("caveats") or [], "off_region": s.get("off_region")}


@router.get("/v1/models")
def models(authorization: str | None = Header(None)):
    if not _authorized(authorization):
        return _error(401, "неверный API-ключ", "authentication_error")
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "created": 1793145600, "owned_by": "ostrovok",
                                        "description": f"агент фактов об отелях {region.META['label_of']}"}]}


@router.post("/v1/chat/completions")
async def completions(request: Request, authorization: str | None = Header(None), x_session: str | None = Header(None)):
    if not _authorized(authorization):
        return _error(401, "неверный API-ключ", "authentication_error")
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "тело запроса должно быть JSON")
    messages = _messages(body.get("messages") or [])
    if not messages or messages[-1]["role"] != "user":
        return _error(400, "нужно хотя бы одно сообщение user с текстом, последним")
    session = x_session or body.get("user")
    cid, created, model = f"chatcmpl-{uuid.uuid4().hex[:24]}", int(time.time()), MODEL_ID

    if not body.get("stream"):
        from starlette.concurrency import run_in_threadpool
        res = await run_in_threadpool(agent.chat, messages, session)
        return {"id": cid, "object": "chat.completion", "created": created, "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": res["text"]}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, "ostrovok": _extra(res)}

    def chunk(delta, finish=None, **extra):
        return "data: " + json.dumps({"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                                      "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **extra},
                                     ensure_ascii=False) + "\n\n"

    def stream():  # агент отвечает целиком после проверки цифр, поэтому роль уходит сразу, а текст частями после
        yield chunk({"role": "assistant", "content": ""})
        res = agent.chat(messages, session)
        text = res["text"]
        for i in range(0, len(text), 200):
            yield chunk({"content": text[i:i + 200]})
        yield chunk({}, "stop", ostrovok=_extra(res))
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
