"""LLM track: the 12 guest scenarios through the real chat agent, scored by an independent oracle.

The oracle does not trust the agent or any grounding code inside the repo. It replays every tool call from the
trace through app.actions (deterministic), collects every number the tools returned, then checks every number
with a unit in the final answer against that pool. It also checks constraint coverage: each characteristic the
rules parser finds in the guest's message should show up in some tool output.

    python bench/llm_track.py --repo ../ostrovok-agent-grounding --out bench/results/grounding.llm.json [--cases 1 4 12]
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
ap.add_argument("--out")
ap.add_argument("--cases", nargs="*", type=int)
ap.add_argument("--workers", type=int, default=4)
args = ap.parse_args()
REPO = Path(args.repo).resolve()

tmp = Path(tempfile.mkdtemp(prefix="bench-llm-"))
shutil.copy(REPO / "data" / "facts.sqlite", tmp / "facts.sqlite")
os.environ.update(FACTS_DB=str(tmp / "facts.sqlite"), CUSTOM_DIR=str(tmp / "custom"), SIM_FILE=str(tmp / "sim.json"),
                  LLM_PROVIDER=os.getenv("BENCH_LLM_PROVIDER", "claude-cli"))
os.environ.pop("REGION", None)
sys.path.insert(0, str(REPO))

from app import actions, agent, llm, search  # noqa: E402

_LAST = {}  # thread id -> tool outputs the agent actually saw (from the Claude Code stream)


def _cli_agent_capture(system, messages, timeout=600, session=None):
    """Same as llm.cli_agent, but also keeps every tool_result so the oracle checks what the agent really saw
    instead of replaying calls (a replay re-parses the query and can return different hotels)."""
    import subprocess
    import threading
    cfg = {"mcpServers": {"hotels": {"command": sys.executable, "args": ["-m", "app.mcp_server"], "cwd": str(REPO),
                                      "env": {k: v for k, v in os.environ.items() if k in ("FACTS_DB", "CUSTOM_DIR", "SIM_FILE", "REGION")}
                                      | ({"OSTROVOK_SESSION": session} if session else {})}}}
    convo = "\n\n".join(f"{'Гость' if m['role'] == 'user' else 'Ты'}: {m['content']}" for m in messages)
    args = llm.CLI_BASE + ["--mcp-config", json.dumps(cfg), "--tools", "", "--allowedTools", "mcp__hotels",
                           "--output-format", "stream-json", "--verbose", "--system-prompt", system, convo]
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=REPO)
    trace, text, outs = [], "", []
    for line in r.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for b in ev["message"].get("content", []):
                if b.get("type") == "tool_use":
                    trace.append({"tool": b["name"].replace("mcp__hotels__", ""), "input": b.get("input", {})})
        elif ev.get("type") == "user":
            for b in (ev.get("message") or {}).get("content", []) or []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    outs.append(b.get("content"))
        elif ev.get("type") == "result":
            text = ev.get("result") or ""
    _LAST.setdefault(threading.get_ident(), []).extend(outs)
    if not text:
        raise llm.LLMUnavailable(f"claude -p ничего не ответил: {r.stderr.strip()[:300]}")
    return text, trace


if llm.PROVIDER == "claude-cli":
    llm.cli_agent = _cli_agent_capture

CASES = [
    ["Тихий номер с видом на закат недалеко от моря, едем в июле"],
    ["Еду с мамой, ей тяжело ходить в гору. Нужно близко к пляжу и чтобы из окна было видно море"],
    ["Мы с ребёнком 3 лет и собакой 12 кг. Нужна детская площадка рядом и чтобы пускали с собакой"],
    ["Работаю удалённо две недели в ноябре: нужно тихо днём, хороший интернет и чтобы рядом можно было поесть"],
    ["Прилетаем в 2 ночи. Важно, чтобы рядом была круглосуточная аптека и где-то поесть"],
    ["В Cosmos Сочи Отель будет слышно поезда ночью? И далеко ли там до моря?"],
    ["Хочу смотреть, как солнце садится в море, в конце декабря. Какие отели и с какого этажа?"],
    ["Сравни AZIMUT Парк Отель Виноградная и Отель Грейс Горизонт по виду на море, тишине и пути до пляжа"],
    ["Нужен отель рядом с аквапарком", "Да, собери эту характеристику и поищи ещё раз"],
    ["Можно ли ещё купаться в Сочи в начале ноября?"],
    ["Чтобы рядом не было стройки и баров под окнами, и не надо было переходить железную дорогу к морю"],
    ["Есть ли в Отель Лофт плотные шторы блэкаут? Мне важно спать днём"],
]

UNIT = r"(?:дБ|db|м\b|метр\w*|км|мин\w*|этаж\w*|°\s?C?|градус\w*|%|руб\w*|₽|ч\b|час\w*|отел\w*)"
CLAIM = re.compile(r"(?<![\w.,])(\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+(?:[.,]\d+)?)\s*(?:-?(?:й|го|м|ти|ми))?\s*" + UNIT, re.I)
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def numbers_in(obj):
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return {float(x) for x in NUM.findall(s)}


def supported(v, pool):
    tol = max(1.0, 0.05 * abs(v))
    return any(abs(v - p) <= tol for p in pool)


def replay(trace):
    outs = []
    for t in trace:
        fn = getattr(actions, t["tool"], None)
        if fn is None:
            continue
        try:
            outs.append(fn(**(t.get("input") or {})))
        except Exception as e:
            outs.append({"error": str(e)})
    return outs


JUDGE = """Ты строгий фактчекер ответов ассистента по подбору отелей. Тебе дают: реплики гостя, ответ ассистента,
результаты всех инструментов, которые он вызывал (единственный источник правды об отелях), и описание того, что
умеет считать система. Найди в ответе утверждения, которые НЕ следуют из результатов инструментов: выдуманные
факты об отелях, неверные цифры, а также ложные утверждения о возможностях системы (например «расчёт не учитывает
деревья», «шум днём не считали», если в описании системы это есть). Общие советы и оговорки не считай.
Ответь только JSON: {"claims_checked": int, "unsupported": [строки], "false_capability": [строки]}"""


def capability_card():
    from app import registry
    from app.tools import catalog
    tools = "\n".join(f"- инструмент {n}: {t.get('description', '')}" for n, t in catalog.TOOLS.items())
    acts = "\n".join(f"- действие {n}: {' '.join((getattr(actions, n).__doc__ or '').split())}"
                      for n in dir(actions) if not n.startswith("_") and callable(getattr(actions, n))
                      and getattr(getattr(actions, n), "__module__", "") == "app.actions")
    return tools + "\n" + acts + "\n" + "\n".join(f"- {s['name']} ({cid}): {' '.join(s['description'].split())} Методы: "
                     + "; ".join(m.get("method", "") for m in s.get("methods", []))
                     for cid, s in registry.all_chars().items())


def fact_check(turns, text, outs):
    prompt = ("Реплики гостя:\n" + "\n".join(turns) + "\n\nОтвет ассистента:\n" + text +
              "\n\nЧто умеет система:\n" + capability_card() +
              "\n\nРезультаты инструментов (JSON):\n" + json.dumps(outs, ensure_ascii=False, default=str)[:90000])
    try:
        import subprocess
        r = subprocess.run(["claude", "-p", "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands",
                            "--no-session-persistence", "--tools", "", "--output-format", "json",
                            "--system-prompt", JUDGE, prompt], capture_output=True, text=True, timeout=400)
        out = json.loads(r.stdout)
        if isinstance(out, list):  # newer Claude Code prints the event list in json mode
            out = next((e for e in reversed(out) if isinstance(e, dict) and e.get("type") == "result"), {})
        raw = out.get("result") or ""
        return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception as e:
        return {"error": str(e)[:200]}


def run_case(i):
    import threading
    _LAST[threading.get_ident()] = []
    turns = CASES[i - 1]
    msgs, trace_all, t0 = [], [], time.time()
    text, mode = "", ""
    for u in turns:
        msgs.append({"role": "user", "content": u})
        try:
            r = agent.chat(msgs)
        except Exception as e:
            r = {"text": f"ERROR {e}", "trace": [], "mode": "error"}
        msgs.append({"role": "assistant", "content": r["text"]})
        trace_all += r["trace"]
        text, mode = r["text"], r.get("mode")
    seen = _LAST.get(threading.get_ident()) or []
    # what the agent saw in the stream, plus outputs the app itself attached to its trace (e.g. facts a grounding
    # step fetched after the model finished); fall back to replay only when the stream had nothing
    outs = (seen + [t["output"] for t in trace_all if t.get("output") is not None]) if seen else replay(trace_all)
    pool = set()
    for o in outs:
        pool |= numbers_in(o)
    for u in turns:
        pool |= {float(x) for x in NUM.findall(u)}
    claims = []
    for m in CLAIM.finditer(text):
        v = float(re.sub(r"[ \u00a0\u202f]", "", m.group(1)).replace(",", "."))
        claims.append({"claim": text[max(0, m.start() - 30):m.end() + 5].replace("\n", " "), "value": v,
                       "supported": supported(v, pool)})
    want = {c["char"] for u in turns for c in search.parse_rules(u)["constraints"]}
    blob = json.dumps(outs, ensure_ascii=False, default=str)
    covered = {c for c in want if c in blob}
    sec = round(time.time() - t0)
    fc = fact_check(turns, text, outs)
    return {"case": i, "q": turns[0], "sec": sec, "mode": mode, "fact_check": fc,
            "tools": [t["tool"] for t in trace_all], "trace": trace_all, "outputs_from": "stream" if seen else "replay",
            "claims": len(claims),
            "unsupported": [c for c in claims if not c["supported"]],
            "constraints": sorted(want), "covered": sorted(covered), "answer": text}


def main():
    if not llm.available():
        sys.exit("LLM unavailable")
    ids = args.cases or list(range(1, len(CASES) + 1))
    # case 9 adds a characteristic to the shared DB; run it alone after the rest so it can't leak into them
    mutating = [i for i in ids if i == 9]
    with ThreadPoolExecutor(args.workers) as ex:
        rows = list(ex.map(run_case, [i for i in ids if i not in mutating]))
    rows += [run_case(i) for i in mutating]
    for r in rows:
        print(f"{r['case']:2d} {r['sec']:4d}s claims={r['claims']:3d} unsupported={len(r['unsupported'])} "
              f"coverage={len(r['covered'])}/{len(r['constraints'])} tools={len(r['tools'])} "
              f"judge_unsupported={len(r['fact_check'].get('unsupported', []))} "
              f"false_capability={len(r['fact_check'].get('false_capability', []))}", flush=True)
    tot = sum(r["claims"] for r in rows)
    uns = sum(len(r["unsupported"]) for r in rows)
    want = sum(len(r["constraints"]) for r in rows)
    cov = sum(len(r["covered"]) for r in rows)
    summary = {"cases": len(rows), "numeric_claims": tot, "unsupported": uns,
               "grounded_rate": round(1 - uns / max(1, tot), 3), "constraint_coverage": round(cov / max(1, want), 3),
               "median_sec": sorted(r["sec"] for r in rows)[len(rows) // 2],
               "errors": sum(1 for r in rows if r["mode"] in ("error", "rules") or r["answer"].startswith("ERROR")),
               "judge_unsupported": sum(len(r["fact_check"].get("unsupported", [])) for r in rows),
               "judge_false_capability": sum(len(r["fact_check"].get("false_capability", [])) for r in rows),
               "judge_errors": sum(1 for r in rows if "error" in r["fact_check"])}
    # case 9 builds a characteristic: the oracle cannot replay that side effect faithfully, so comparisons
    # across builds use the 11 other cases; case 9 is reported but kept out of the headline numbers
    core = [r for r in rows if r["case"] != 9]
    summary["core11"] = {"judge_unsupported": sum(len(r["fact_check"].get("unsupported", [])) for r in core),
                         "judge_false_capability": sum(len(r["fact_check"].get("false_capability", [])) for r in core),
                         "numeric_unsupported": sum(len(r["unsupported"]) for r in core),
                         "constraint_coverage": round(sum(len(r["covered"]) for r in core) / max(1, sum(len(r["constraints"]) for r in core)), 3)}
    print(json.dumps(summary, ensure_ascii=False))
    if args.out:
        Path(args.out).write_text(json.dumps({"repo": str(REPO), "provider": f"{llm.PROVIDER}:{llm.MODEL}",
                                              "at": time.strftime("%Y-%m-%d %H:%M"), "summary": summary, "rows": rows},
                                             ensure_ascii=False, indent=1))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
