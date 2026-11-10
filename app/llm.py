"""Клиент LLM. LLM здесь только разбирает текст (запрос, ответ отельера), пишет рецепты и объясняет;
ничего не считает и фактов не придумывает.

По умолчанию Claude через официальный SDK anthropic (ANTHROPIC_API_KEY, модель claude-opus-5-5).
Если у проверяющего другой провайдер, OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL (любой OpenAI-совместимый API,
локальному серверу хватает адреса). Без ключа система работает: поиск разбирает запрос по ключевым словам
из реестра, ответы отельера — простыми правилами.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# .env из .env.example задаёт переменные пустыми; SDK читают их сами и пустую строку берут как значение
# (адрес API "" или заголовок "Bearer "), поэтому пустые убираем до создания клиентов
for _v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
    if os.environ.get(_v, None) == "":
        del os.environ[_v]

def _openai_configured():
    """Ключ или адрес OpenAI-совместимого API. Локальным серверам (Ollama, vLLM, LM Studio) хватает адреса."""
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_BASE_URL"))


def _pick_provider():
    """Явный LLM_PROVIDER; иначе ключ Anthropic → SDK; иначе ключ или адрес OpenAI-совместимого API;
    иначе установленный Claude Code (подписка) → claude-cli. Явная настройка API важнее установленной программы."""
    p = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if p:
        return "openai" if p in ("openai-compatible", "openai_compatible", "oai") else p
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    if _openai_configured():
        return "openai"
    if shutil.which("claude"):
        return "claude-cli"
    return "anthropic"


PROVIDER = _pick_provider()
DEFAULT_MODEL = {"anthropic": "claude-opus-5-5", "openai": "gpt-4.1", "claude-cli": "claude-opus-5-5"}
MODEL = os.getenv("LLM_MODEL") or DEFAULT_MODEL.get(PROVIDER, "claude-opus-5-5")
ROOT = Path(__file__).resolve().parent.parent


class LLMUnavailable(RuntimeError):
    pass


def available():
    if PROVIDER == "none":  # принудительно без LLM (тесты, демо правил)
        return False
    if PROVIDER == "claude-cli":
        return bool(shutil.which("claude"))
    if PROVIDER == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    return _openai_configured()


_client = None


def _anthropic():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def _openai():
    global _client
    if _client is None:
        from openai import OpenAI
        # локальные серверы ключ не проверяют, а SDK без ключа не создаётся
        _client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None, api_key=os.getenv("OPENAI_API_KEY") or "none")
    return _client


def _loads(text):
    """JSON из ответа модели: слабые модели заворачивают его в ```json или пишут фразу до и после."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < i:
        raise LLMUnavailable(f"модель не вернула JSON: {text[:200]}")
    return json.loads(text[i:j + 1])


def _check(resp):
    if resp.stop_reason == "refusal":
        raise LLMUnavailable("модель отказалась отвечать на этот запрос")
    return resp


def _create(**kw):
    """Запрос к Claude с серверным фолбэком: если классификатор безопасности откажет, запрос сам уйдёт на
    рекомендованную модель (fallbacks="default")."""
    c = _anthropic()
    return _check(c.beta.messages.create(model=MODEL, betas=["server-side-fallback-2026-07-01"],
                                         fallbacks="default", **kw))


def json_call(system, user, schema, effort="low", max_tokens=4000):
    """Один запрос, ответ строго по JSON-схеме."""
    if not available():
        raise LLMUnavailable("нет ключа LLM")
    if PROVIDER == "claude-cli":
        out = _cli(["--json-schema", json.dumps(schema, ensure_ascii=False), "--tools", ""], system, user)
        if out.get("structured_output") is None:
            raise LLMUnavailable(f"claude -p не вернул JSON: {str(out.get('result'))[:200]}")
        return out["structured_output"]
    if PROVIDER == "anthropic":
        resp = _create(max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}],
                       output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}})
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    hint = msgs + [{"role": "user", "content": "Ответь только JSON по схеме: " + json.dumps(schema, ensure_ascii=False)}]
    # не все OpenAI-совместимые провайдеры умеют strict-схемы или response_format: от строгого к простому
    tries = [(msgs, {"type": "json_schema", "json_schema": {"name": "out", "schema": schema, "strict": True}}),
             (hint, {"type": "json_object"}), (hint, None)]
    import openai
    for i, (m, fmt) in enumerate(tries):
        try:
            resp = _openai().chat.completions.create(model=MODEL, messages=m, **({"response_format": fmt} if fmt else {}))
            return _loads(resp.choices[0].message.content)
        except (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError, openai.APIConnectionError):
            raise  # ключ, модель или адрес неверны: другой формат не поможет
        except Exception:
            if i == len(tries) - 1:
                raise


# ---------- Claude Code в режиме -p: работает на подписке, без ключа API ----------

CLI_BASE = ["claude", "-p", "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands",
            "--no-session-persistence"]


def _cli(extra, system, prompt, timeout=300):
    args = CLI_BASE + (["--model", MODEL] if os.getenv("LLM_MODEL") else []) + extra + \
        ["--output-format", "json", "--system-prompt", system, prompt]
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    if r.returncode != 0 and not r.stdout.strip():
        raise LLMUnavailable(f"claude -p: {r.stderr.strip()[:300]}")
    out = json.loads(r.stdout)
    if isinstance(out, list):  # новые версии Claude Code в режиме json печатают список событий, итог — последнее result
        out = next((e for e in reversed(out) if isinstance(e, dict) and e.get("type") == "result"),
                   {"is_error": True, "result": "нет итога"})
    if out.get("is_error"):
        raise LLMUnavailable(f"claude -p: {str(out.get('result'))[:300]}")
    return out


def _tool_output(content):
    """Результат MCP-инструмента из stream-json: текстовые блоки с JSON. Один блок — его значение, несколько —
    список значений (так FastMCP отдаёт список). Не JSON — None, тогда grounding переиграет вызов."""
    if isinstance(content, str):
        blocks = [content]
    else:
        blocks = [x.get("text") for x in content or [] if isinstance(x, dict) and x.get("type") == "text"]
    vals = []
    for t in blocks:
        try:
            vals.append(json.loads(t))
        except (TypeError, ValueError):
            return None
    return vals[0] if len(vals) == 1 else (vals or None)


def cli_agent(system, messages, timeout=600, session=None):
    """Агент = Claude Code с нашим MCP-сервером: инструменты те же, что у веб-чата и внешних агентов."""
    cfg = {"mcpServers": {"hotels": {"command": sys.executable, "args": ["-m", "app.mcp_server"], "cwd": str(ROOT),
                                      "env": {**{k: v for k, v in os.environ.items() if k in ("FACTS_DB", "CUSTOM_DIR", "SIM_FILE")},
                                              **({"OSTROVOK_SESSION": session} if session else {})}}}}
    convo = "\n\n".join(f"{'Гость' if m['role'] == 'user' else 'Ты'}: {m['content']}" for m in messages)
    args = CLI_BASE + (["--model", MODEL] if os.getenv("LLM_MODEL") else []) + [
        "--mcp-config", json.dumps(cfg), "--tools", "", "--allowedTools", "mcp__hotels",
        "--output-format", "stream-json", "--verbose", "--system-prompt", system, convo]
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    trace, text, by_id = [], "", {}
    for line in r.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for b in ev["message"].get("content", []):
                if b.get("type") == "tool_use":
                    trace.append({"tool": b["name"].replace("mcp__hotels__", ""), "input": b.get("input", {})})
                    by_id[b.get("id")] = trace[-1]
        elif ev.get("type") == "user":  # результаты инструментов: то, что агент реально видел, переигрывать не нужно
            for b in (ev.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in by_id:
                    out = _tool_output(b.get("content"))
                    if out is not None:
                        by_id[b["tool_use_id"]]["output"] = {"error": str(out)[:300]} if b.get("is_error") else out
        elif ev.get("type") == "result":
            text = ev.get("result") or ""
            if ev.get("is_error"):
                raise LLMUnavailable(f"claude -p: {text[:300]}")
    if not text:
        raise LLMUnavailable(f"claude -p ничего не ответил: {r.stderr.strip()[:300]}")
    return text, trace


def agent(system, messages, tools, execute, effort="medium", max_steps=8, on_step=None, session=None):
    """Цикл агента с инструментами. tools: [{name, description, input_schema}]; execute(name, input) -> dict.
    Возвращает (финальный текст, журнал вызовов)."""
    if not available():
        raise LLMUnavailable("нет ключа LLM")
    if PROVIDER == "claude-cli":
        return cli_agent(system, messages, session=session)
    trace = []
    if PROVIDER == "anthropic":
        msgs = list(messages)
        for _ in range(max_steps):
            resp = _create(max_tokens=16000, system=system, tools=tools, messages=msgs,
                           output_config={"effort": effort})
            uses = [b for b in resp.content if b.type == "tool_use"]
            msgs.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use" or not uses:
                return "".join(b.text for b in resp.content if b.type == "text"), trace
            results = []
            for u in uses:
                try:
                    out, err = execute(u.name, u.input), False
                except Exception as e:  # ошибка инструмента уходит модели, а не роняет диалог
                    out, err = {"error": str(e)}, True
                trace.append({"tool": u.name, "input": u.input, "error": err, "output": out})
                if on_step:
                    on_step(trace[-1])
                results.append({"type": "tool_result", "tool_use_id": u.id, "is_error": err,
                                "content": json.dumps(out, ensure_ascii=False, default=str)[:20000]})
            msgs.append({"role": "user", "content": results})
        return "Остановился после нескольких шагов, посмотрите результаты выше.", trace
    # OpenAI-совместимый провайдер
    oa_tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["input_schema"]}} for t in tools]
    msgs = [{"role": "system", "content": system}] + list(messages)
    for _ in range(max_steps):
        r = _openai().chat.completions.create(model=MODEL, messages=msgs, tools=oa_tools)
        m = r.choices[0].message
        if not m.tool_calls:
            return m.content or "", trace
        # в историю только стандартные поля: refusal, annotations, reasoning_content и т. п. ломают часть провайдеров
        msgs.append({"role": "assistant", "content": m.content or "",
                     "tool_calls": [{"id": tc.id, "type": "function",
                                     "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                                    for tc in m.tool_calls]})
        for tc in m.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except ValueError as e:  # модель прислала битый JSON аргументов: пусть исправится сама
                args, out, err = {}, {"error": f"аргументы не JSON: {e}"}, True
            else:
                try:
                    out, err = execute(tc.function.name, args), False
                except Exception as e:
                    out, err = {"error": str(e)}, True
            trace.append({"tool": tc.function.name, "input": args, "error": err, "output": out})
            if on_step:
                on_step(trace[-1])
            msgs.append({"role": "tool", "tool_call_id": tc.id,
                         "content": json.dumps(out, ensure_ascii=False, default=str)[:20000]})
    return "Остановился после нескольких шагов.", trace
