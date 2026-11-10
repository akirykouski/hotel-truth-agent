"""Регионы из интерфейса: список собранных, источники отелей, сборка нового в фоне и переключение.

Сборку делает тот же scripts/add_region.py, что и из консоли: сервер запускает его отдельным процессом с --status и
читает ход по этапам из JSON в data/cache/region_jobs/. Сборка переживает перезапуск сервера. Переключение региона
перезапускает процесс сервера с другим REGION (данные региона читаются при импорте модулей), это около секунды.
"""
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path

from app import region

ROOT = region.ROOT
sys.path.insert(0, str(ROOT / "scripts"))
from _region import check_plan, is_lfs_pointer, iter_hotels, read_meta  # noqa: E402

JOBS_DIR = ROOT / "data" / "cache" / "region_jobs"
SRC_DIR = Path(os.getenv("HOTELS_SRC_DIR") or ROOT / "data" / "sources")   # <город>/hotels.jsonl[.xz], скрап Островка
CITY_LABEL = {"sochi": "Сочи", "spb": "Санкт-Петербург"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")
_procs = {}  # job_id → Popen, чтобы забрать код выхода и не оставлять зомби


class RegionError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


# ---------- собранные регионы ----------

def _entry(name, meta, data):
    return {"name": name, "label": meta.get("label"), "hotels": meta.get("hotels"), "center": meta.get("center"),
            "bbox": meta.get("bbox"), "built_at": meta.get("built_at"), "build_seconds": meta.get("build_seconds"),
            "size_mb": meta.get("size_mb"), "active": name == (region.NAME or "default"),
            "complete": meta.get("complete", True) and (data / "facts.sqlite").exists()}


def listing():
    hotels = json.loads((ROOT / "data" / "hotels.json").read_text(encoding="utf-8"))
    out = [_entry("default", region.DEFAULT_META | {"hotels": len(hotels["hotels"]), "bbox": hotels.get("zone")},
                  ROOT / "data")]
    for f in sorted((ROOT / "data" / "regions").glob("*/region.json")):
        out.append(_entry(f.parent.name, read_meta(f.parent), f.parent))
    return out


# ---------- источники отелей (скрап Островка) ----------

def _src_file(d):
    """Файл отелей города: несжатый, если есть, иначе .xz из репозитория."""
    return next((f for f in (d / "hotels.jsonl", d / "hotels.jsonl.xz") if f.exists()), None)


def sources():
    out = []
    dirs = sorted(d for d in SRC_DIR.iterdir() if d.is_dir()) if SRC_DIR.exists() else []
    for f in filter(None, map(_src_file, dirs)):
        lfs = is_lfs_pointer(f)
        out.append({"id": f.parent.name, "label": CITY_LABEL.get(f.parent.name, f.parent.name), "path": str(f),
                    "ready": not lfs, "hotels": None if lfs else len(_points(str(f), f.stat().st_mtime)),
                    "note": "файл — заглушка Git LFS: выполните git lfs pull там, где он лежит" if lfs else ""})
    return out


def _source(src_id):
    f = None if "/" in src_id or ".." in src_id else _src_file(SRC_DIR / src_id)
    if f is None:
        raise RegionError(f"нет источника отелей {src_id!r} в {SRC_DIR}", 404)
    if is_lfs_pointer(f):
        raise RegionError("файл отелей — заглушка Git LFS: выполните git lfs pull там, где он лежит", 409)
    return f


@lru_cache(maxsize=8)
def _points(path, mtime):  # mtime в ключе кэша: перескачанный файл читается заново
    return tuple(iter_hotels(path))


def points(src_id):
    f = _source(src_id)
    pts = _points(str(f), f.stat().st_mtime)
    return {"source": src_id, "points": [[round(la, 5), round(lo, 5), int(k not in ("APARTMENT", "LIVING_QUARTERS"))]
                                         for la, lo, k in pts]}


def check(src_id, bbox):
    f = _source(src_id)
    return check_plan(f, bbox, points=_points(str(f), f.stat().st_mtime))


# ---------- сборка ----------

def _alive(pid, job_id=None):
    p = _procs.get(job_id)
    if p is not None:
        return p.poll() is None
    try:  # процесс от прошлого запуска сервера (после переключения региона): забираем код выхода, если он наш
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _read(job_dir):
    try:
        s = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    s["id"] = job_dir.name
    if s.get("state") == "running" and not _alive(s.get("pid", 0), job_dir.name):
        s["state"] = "interrupted"
        s["error"] = s.get("error") or "процесс сборки завершился без итога: смотрите журнал этапа"
        for st in s["steps"]:
            if st["state"] == "running":
                st["state"] = "fail"
    done = sum(st["weight"] * (1 if st["state"] in ("ok", "skipped") else
                               (st["done"] or 0) / st["total"] if st["state"] == "running" and st.get("total") else 0)
               for st in s["steps"])
    s["progress"] = round(done / sum(st["weight"] for st in s["steps"]), 3)
    s["now"] = time.time()
    return s


def jobs(limit=10):
    if not JOBS_DIR.exists():
        return []
    dirs = sorted((d for d in JOBS_DIR.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)[:limit]
    return [j for j in (_read(d) for d in dirs) if j]


def job(job_id, log=False):
    d = JOBS_DIR / job_id
    if "/" in job_id or not d.is_dir() or (s := _read(d)) is None:
        raise RegionError("нет такой сборки", 404)
    if log and (d / "build.log").exists():
        s["log_tail"] = (d / "build.log").read_text(encoding="utf-8", errors="replace")[-6000:]
    return s


def running():
    return next((j for j in jobs() if j["state"] == "running"), None)


def start(name, source, bbox, label=None, label_in=None, label_of=None, reuse=False, overwrite=False):
    if not NAME_RE.match(name or "") or name == "default":
        raise RegionError("имя папки: латиница, цифры, - и _, от 2 до 31 знака, например hosta")
    if name == region.NAME:
        raise RegionError("это активный регион: сначала переключитесь на другой, потом пересобирайте", 409)
    if (j := running()) is not None:
        raise RegionError(f"уже идёт сборка «{j.get('label')}»: Overpass не любит параллельные загрузки", 409)
    out = ROOT / "data" / "regions" / name
    if (out / "region.json").exists() and not (overwrite or reuse):
        raise RegionError(f"регион {name} уже есть: отметьте «пересобрать» или выберите другое имя", 409)
    f = _source(source)
    plan = check_plan(f, bbox, points=_points(str(f), f.stat().st_mtime))
    if not plan["ok"]:
        raise RegionError("; ".join(plan["errors"]))
    job_id = time.strftime("%Y%m%d-%H%M%S-") + name
    d = JOBS_DIR / job_id
    d.mkdir(parents=True)
    cmd = [sys.executable, str(ROOT / "scripts" / "add_region.py"), "--name", name, "--bbox", ",".join(map(str, bbox)),
           "--hotels-src", str(f), "--status", str(d / "status.json")]
    for flag, v in (("--label", label), ("--label-in", label_in), ("--label-of", label_of)):
        if v and v.strip():
            cmd += [flag, v.strip()]
    if reuse:
        cmd.append("--reuse")
    with open(d / "build.log", "w", encoding="utf-8") as log:
        _procs[job_id] = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                          env={**os.environ, "PYTHONUNBUFFERED": "1"})
    for _ in range(50):  # status.json пишет сам скрипт: ждём его, чтобы интерфейс сразу увидел этапы
        if (d / "status.json").exists():
            break
        time.sleep(0.05)
    return job(job_id)


def cancel(job_id):
    s = job(job_id)
    if s["state"] != "running":
        raise RegionError("сборка уже не идёт", 409)
    try:
        os.killpg(s["pid"], signal.SIGTERM)  # группа процессов: add_region и его шаги
    except ProcessLookupError:
        pass
    f = JOBS_DIR / job_id / "status.json"
    raw = json.loads(f.read_text(encoding="utf-8"))
    for st in raw["steps"]:
        if st["state"] in ("running", "pending"):
            st["state"] = "cancelled"
    raw.update(state="cancelled", finished_at=time.time(), error="сборка отменена")
    f.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return job(job_id)


# ---------- переключение ----------

def _restart():
    time.sleep(0.5)  # ответ на запрос успевает уйти
    os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])


def switch(name, restart=_restart):
    reg = next((r for r in listing() if r["name"] == name), None)
    if reg is None:
        raise RegionError("нет такого региона", 404)
    if not reg["complete"]:
        raise RegionError("регион собран не до конца: дождитесь сборки или пересоберите", 409)
    if reg["active"]:
        return {"ok": True, "restarting": False, "region": name}
    if name == "default":
        os.environ.pop("REGION", None)
    else:
        os.environ["REGION"] = name
    threading.Thread(target=restart, daemon=True).start()
    return {"ok": True, "restarting": True, "region": name}
