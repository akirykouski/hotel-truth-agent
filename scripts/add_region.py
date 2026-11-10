"""Новый регион одной командой: отели, OSM, карта высот, климат, предрасчёт всех фактов → data/regions/<имя>/.

  python scripts/add_region.py --name adler --bbox 43.39,39.87,43.50,39.99 \\
      --hotels-src data/sources/sochi/hotels.jsonl.xz --label Адлер
  REGION=adler make run

Этапы: проверка рамки → загрузка (отели, OSM, рельеф, климат идут параллельно, Overpass получает по одному запросу
на слой) → предрасчёт → демо-ответы отельеров → проверка результата. С --status FILE ход сборки по этапам пишется
в JSON (его читает вкладка «Регионы»), с --reuse уже скачанные слои не качаются заново. Без аргументов --label*
подпись берётся из --label.
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _region import check_plan, parse_bbox, write_meta  # noqa: E402

PY = sys.executable
OSM_LAYERS = ("buildings", "ways", "water", "pois")
STEPS = [  # id, название, вес в общем прогрессе (примерно доля времени)
    ("check", "Проверка рамки и отелей", 1),
    ("hotels", "Отели из скрапа Островка", 2),
    ("osm", "OpenStreetMap: здания, дороги, вода, места", 45),
    ("dem", "Карта высот Copernicus GLO-30", 10),
    ("climate", "Климат и море, Open-Meteo", 4),
    ("precompute", "Предрасчёт характеристик", 32),
    ("seed", "Демо-ответы отельеров", 3),
    ("verify", "Проверка результата", 3),
]


class Progress:
    """Состояние сборки в JSON-файле. Пишется атомарно: файл читает веб-сервер, пока шаги идут параллельно."""

    def __init__(self, path, **head):
        self.path, self.lock = Path(path) if path else None, threading.Lock()
        self.s = {"state": "running", "pid": os.getpid(), "started_at": time.time(), "finished_at": None, "error": None,
                  **head, "steps": [{"id": i, "title": t, "weight": w, "state": "pending", "started_at": None,
                                     "seconds": None, "done": None, "total": None, "note": "", "log": []}
                                    for i, t, w in STEPS], "result": None}
        self.save()

    def step(self, sid):
        return next(x for x in self.s["steps"] if x["id"] == sid)

    def update(self, sid=None, **kv):
        with self.lock:
            (self.step(sid) if sid else self.s).update(kv)
            self.save()

    def line(self, sid, text):
        with self.lock:
            st = self.step(sid)
            st["log"] = (st["log"] + [text])[-40:]
            self.save()

    def save(self):
        if self.path:
            tmp = self.path.with_suffix(f".{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(self.s, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)


def parser(sid, prog):
    """Разбор вывода скрипта шага в счётчик «сделано из» и короткую заметку."""
    def osm(t):
        if m := re.match(r"(\w+): (\d+) объектов", t):
            st = prog.step(sid)
            prog.update(sid, done=(st["done"] or 0) + 1, note=f"слой {m[1]}: {int(m[2]):,} объектов".replace(",", " "))
        elif m := re.match(r"\s*https?://([^/\s]+)\S*: (\S+)", t):
            prog.update(sid, note=f"зеркало {m[1]} ответило {m[2]}, пробую следующее")

    def dem(t):
        if m := re.match(r"тайл (\d+)/(\d+)", t):
            prog.update(sid, done=int(m[1]), total=int(m[2]), note=t)

    def climate(t):
        if t.startswith("морская точка"):
            prog.update(sid, note=t)

    def hotels(t):
        if m := re.match(r"(\d+) отелей", t):
            prog.update(sid, done=1, note=f"{m[1]} отелей в рамке")

    def precompute(t):
        if m := re.match(r"характеристик: (\d+), отелей: (\d+)", t):
            prog.update(sid, done=0, total=int(m[1]), note=f"{m[1]} характеристик × {m[2]} отелей")
        elif m := re.match(r"[\d:]+ (\w+): посчитано для", t):
            prog.update(sid, done=(prog.step(sid)["done"] or 0) + 1, note=f"готово: {m[1]}")
        elif m := re.match(r"готово за .*вопросов отельерам (\d+)", t):
            prog.update(sid, note=f"вопросов отельерам: {m[1]}")

    return {"osm": osm, "dem": dem, "climate": climate, "hotels": hotels, "precompute": precompute}.get(sid, lambda t: None)


def run(prog, sid, cmd, env=None):
    t = time.time()
    prog.update(sid, state="running", started_at=t)
    p = subprocess.Popen([PY, *cmd], cwd=ROOT, env={**os.environ, "PYTHONUNBUFFERED": "1", **(env or {})},
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    parse, tail = parser(sid, prog), []
    for raw in p.stdout:
        text = raw.rstrip()
        if not text:
            continue
        tail = (tail + [text])[-30:]
        prog.line(sid, text)
        try:
            parse(text)
        except Exception:  # noqa: BLE001 — разбор вывода только для прогресса, сборку он не роняет
            pass
    rc = p.wait()
    dt = time.time() - t
    prog.update(sid, state="ok" if rc == 0 else "fail", seconds=round(dt, 1),
                **({} if rc == 0 else {"note": next((x for x in reversed(tail) if x.strip()), f"код выхода {rc}")}))
    print(f"{'OK  ' if rc == 0 else 'FAIL'} {sid:<16}{dt:6.0f} с", flush=True)
    if rc:
        print("\n".join(tail[-15:]), file=sys.stderr)
    return rc


def have(out, sid):
    """Есть ли уже результат шага загрузки (для --reuse)."""
    return {"hotels": (out / "hotels.json").exists(), "dem": (out / "dem.npz").exists(),
            "climate": (out / "climate.json").exists(),
            "osm": all((out / "osm" / f"{x}.json.gz").exists() for x in OSM_LAYERS)}[sid]


def verify(out):
    """Сводка по готовой базе фактов: сколько отелей и характеристик посчитано и какая доля известна."""
    db = sqlite3.connect(out / "facts.sqlite")
    facts, hotels = db.execute("SELECT count(*), count(DISTINCT hotel_id) FROM facts WHERE active=1").fetchone()
    by_char = db.execute("SELECT char_id, count(DISTINCT hotel_id) FROM facts WHERE active=1 GROUP BY char_id").fetchall()
    questions = db.execute("SELECT count(*) FROM questions WHERE status='open'").fetchone()[0]
    db.close()
    total = json.loads((out / "hotels.json").read_text(encoding="utf-8"))["hotels"]
    return {"facts": facts, "hotels_with_facts": hotels, "hotels": len(total), "characteristics": len(by_char),
            "open_questions": questions, "coverage": {c: round(n / max(1, len(total)), 2) for c, n in by_char}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="короткое имя папки: adler")
    ap.add_argument("--bbox", required=True, type=parse_bbox, help="зона отелей s,w,n,e")
    ap.add_argument("--hotels-src", required=True, help="hotels.jsonl или .jsonl.xz из data/sources/<город>/")
    ap.add_argument("--label", help="подпись зоны в интерфейсе, по умолчанию имя")
    ap.add_argument("--label-in", help="«в Адлере» для подсказок LLM, по умолчанию «в <label>»")
    ap.add_argument("--label-of", help="«Адлера», по умолчанию label")
    ap.add_argument("--status", help="JSON-файл с ходом сборки по этапам (для веб-интерфейса)")
    ap.add_argument("--reuse", action="store_true", help="не качать заново отели, OSM, рельеф и климат, если они уже есть")
    a = ap.parse_args()
    label = a.label or a.name
    out = ROOT / "data" / "regions" / a.name
    prog = Progress(a.status, name=a.name, label=label, label_in=a.label_in, label_of=a.label_of, bbox=list(a.bbox),
                    source=a.hotels_src, reuse=a.reuse)
    t0 = time.time()

    def fail(msg):
        for st in prog.s["steps"]:
            if st["state"] == "pending":
                st["state"] = "skipped"
        prog.update(state="failed", error=msg, finished_at=time.time())
        raise SystemExit(msg)

    prog.update("check", state="running", started_at=time.time())
    plan = check_plan(a.hotels_src, a.bbox)
    prog.update("check", state="ok" if plan["ok"] else "fail", seconds=round(time.time() - t0, 1), done=1, total=1,
                note=(f"{plan['hotels']} отелей, {plan['area_km2']} км²" if plan["ok"] else "; ".join(plan["errors"])))
    prog.update(plan=plan)
    for w in plan["warnings"]:
        prog.line("check", "внимание: " + w)
    if not plan["ok"]:
        fail("; ".join(plan["errors"]))

    out.mkdir(parents=True, exist_ok=True)
    s, w, n, e = a.bbox
    write_meta(out, name=a.name, label=label, label_in=a.label_in or f"в {label}", label_of=a.label_of or label,
               place_in=a.label_in or f"в {label}", center=[round((s + n) / 2, 4), round((w + e) / 2, 4)],
               sun_lat=round((s + n) / 2, 2), bbox=list(a.bbox), complete=False)
    reg = ["--region", a.name, "--bbox", ",".join(map(str, a.bbox))]
    prog.update("osm", total=len(OSM_LAYERS), done=0)
    loads = {"osm": ["scripts/fetch_osm.py", *reg], "dem": ["scripts/fetch_dem.py", *reg],
             "climate": ["scripts/fetch_climate.py", *reg],
             "hotels": ["scripts/prepare_hotels.py", a.hotels_src, *reg]}
    with ThreadPoolExecutor(4) as ex:
        futs = []
        for sid, cmd in loads.items():
            if a.reuse and have(out, sid):
                prog.update(sid, state="skipped", note="уже скачано, беру готовое", seconds=0)
                print(f"SKIP {sid:<16} уже скачано", flush=True)
                continue
            futs.append(ex.submit(run, prog, sid, cmd))
        failed = [f.result() for f in futs]
    if any(failed):
        bad = [st["title"] for st in prog.s["steps"] if st["state"] == "fail"]
        fail("не прошла загрузка: " + ", ".join(bad) + ". Повторите с --reuse: готовые слои не будут качаться заново")
    if a.reuse:  # hotels.json мог остаться от прошлой рамки: число отелей в метаданных берём из файла
        write_meta(out, hotels=len(json.loads((out / "hotels.json").read_text(encoding="utf-8"))["hotels"]))

    env = {"REGION": a.name, "LLM_PROVIDER": "none"}
    if run(prog, "precompute", ["scripts/precompute.py"], env) or run(prog, "seed", ["scripts/seed_demo.py"], env):
        fail("предрасчёт не прошёл, подробности в журнале этапа")

    prog.update("verify", state="running", started_at=time.time())
    try:
        res = verify(out)
    except Exception as ex:  # noqa: BLE001
        prog.update("verify", state="fail", note=str(ex))
        fail(f"база фактов не читается: {ex}")
    if not res["facts"]:
        prog.update("verify", state="fail", note="в базе нет ни одного факта")
        fail("предрасчёт не дал фактов")
    prog.update("verify", state="ok", seconds=0.1, done=1, total=1,
                note=f"{res['facts']} фактов у {res['hotels_with_facts']} из {res['hotels']} отелей")

    total = time.time() - t0
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file() and "cache" not in f.parts)
    write_meta(out, built_at=time.strftime("%Y-%m-%d"), build_seconds=round(total), size_mb=round(size / 1e6, 1),
               complete=True)
    prog.update(state="done", finished_at=time.time(), result=res | {"seconds": round(total), "size_mb": round(size / 1e6, 1)})
    print(f"\nрегион {a.name}: {res['hotels']} отелей, {res['facts']} фактов, {size / 1e6:.1f} МБ, "
          f"всего {total:.0f} с ({total / 60:.1f} мин)")
    print(f"запуск: REGION={a.name} make run")


if __name__ == "__main__":
    main()
