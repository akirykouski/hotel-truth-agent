"""Разметка фото отелей зрением Claude (Claude Code CLI на подписке) → data/photo_labels.json.

Фото берём из карточек (data/hotels.json, 4 штуки на отель, 640×400), качаем в data/cache/photos/ (в git не идёт),
размечаем пачками по ~10 кадров, 3 вызова параллельно. Результат кэшируется по кадрам в data/cache/photo_labels.part.json,
повторный запуск продолжает с места остановки. Метки замораживаются в data/photo_labels.json (в git).
  python scripts/label_photos.py            # всё
  python scripts/label_photos.py --limit 5  # пробный прогон на 5 отелях, в замороженный файл не пишет
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.llm import CLI_BASE  # noqa: E402

PHOTOS = ROOT / "data" / "cache" / "photos"
PART = ROOT / "data" / "cache" / "photo_labels.part.json"
FROZEN = ROOT / "data" / "photo_labels.json"
BATCH, WORKERS, RETRIES = 10, 3, 3
MODEL = os.getenv("LABEL_MODEL", "claude-opus-5-5")

KINDS = ["room", "balcony", "view_from_window", "facade", "lobby", "pool", "restaurant", "beach", "bathroom",
         "territory", "other"]
VIEWS = ["sea", "city", "mountains", "greenery", "courtyard", "none", "unknown"]
YNU = ["yes", "no", "unknown"]
ITEM = {"type": "object", "additionalProperties": False,
        "required": ["n", "kind", "sea_visible", "sea_from_room", "view", "blackout_curtains", "entrance_steps",
                     "elevator", "confidence", "note"],
        "properties": {"n": {"type": "integer"}, "kind": {"enum": KINDS}, "sea_visible": {"type": "boolean"},
                       "sea_from_room": {"type": "boolean"}, "view": {"enum": VIEWS},
                       "blackout_curtains": {"enum": YNU}, "entrance_steps": {"enum": YNU}, "elevator": {"enum": YNU},
                       "confidence": {"type": "number"}, "note": {"type": "string"}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"],
          "properties": {"items": {"type": "array", "items": ITEM}}}

SYSTEM = """Ты размечаешь фотографии отелей для сервиса проверки фактов. Смотри только на то, что видно на кадре, ничего не домысливай.
Для каждого файла верни объект с полями:
n: номер файла из списка.
kind: что на кадре: room (жилая комната), balcony (балкон или терраса номера), view_from_window (кадр сделан ради вида из окна или с балкона), facade (здание снаружи), lobby, pool, restaurant, beach, bathroom, territory (двор, сад, парковка), other.
sea_visible: на кадре видно море (любое: с пляжа, с территории, из окна).
sea_from_room: море видно ИЗ номера, то есть через окно или с балкона номера. С пляжа, бассейна или территории это false.
view: что за окном или на открытом пространстве: sea, city, mountains, greenery, courtyard, none (окна нет или вида нет), unknown.
blackout_curtains: yes только если на кадре явно видны плотные затемняющие шторы или жалюзи, no если видны окна без них или с тюлем, unknown если окон не видно.
entrance_steps: yes если на кадре видны ступеньки или лестница у входа в здание, no если вход виден и ступеней нет (пандус, ровный вход), unknown в остальных случаях.
elevator: yes если на кадре виден лифт, no только если кадр явно показывает лестничный холл без лифта, иначе unknown.
confidence: 0..1, насколько ты уверен в разметке кадра.
note: одна короткая фраза по-русски, что видно (до 80 символов).
Если сомневаешься, выбирай unknown или false и снижай confidence."""


def photo_path(url):
    return PHOTOS / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg")


def download(url):
    p = photo_path(url)
    if p.exists() and p.stat().st_size > 1000:
        return p
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            p.write_bytes(urllib.request.urlopen(req, timeout=30).read())
            return p
        except Exception:
            time.sleep(1 + i)
    return None


def label_batch(items):
    """items: [(hotel_id, url, path)] → {url: labels}. Один вызов claude -p с Read по путям."""
    lines = "\n".join(f"{i + 1}. {p}" for i, (_, _, p) in enumerate(items))
    prompt = f"Прочитай инструментом Read каждый из файлов и разметь его.\n{lines}"
    args = CLI_BASE + ["--model", MODEL, "--tools", "Read", "--allowedTools", "Read", "--json-schema", json.dumps(SCHEMA),
                       "--output-format", "json", "--system-prompt", SYSTEM, prompt]
    last = None
    for attempt in range(RETRIES):
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=600, cwd=ROOT)
            out = json.loads(r.stdout)
            if isinstance(out, list):  # с инструментами CLI отдаёт ленту событий, итог в последнем result
                out = next(e for e in reversed(out) if e.get("type") == "result")
            got = (out.get("structured_output") or {}).get("items")
            if not got or out.get("is_error"):
                raise RuntimeError(str(out.get("result"))[:200])
            by_n = {g["n"]: {k: v for k, v in g.items() if k != "n"} for g in got}
            if len(by_n) < len(items):
                raise RuntimeError(f"вернул {len(by_n)} из {len(items)}")
            return {items[n - 1][1]: lab for n, lab in by_n.items() if 1 <= n <= len(items)}
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    print("пачка не разметилась:", last, file=sys.stderr)
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    hotels = json.loads((ROOT / "data" / "hotels.json").read_text(encoding="utf-8"))["hotels"]
    if a.limit:
        hotels = hotels[:a.limit]
    PHOTOS.mkdir(parents=True, exist_ok=True)
    todo = [(h["id"], u) for h in hotels for u in (h.get("photos") or [])]
    t0 = time.time()
    with ThreadPoolExecutor(16) as ex:
        paths = dict(zip([u for _, u in todo], ex.map(download, [u for _, u in todo])))
    print(f"скачано {sum(1 for p in paths.values() if p)} из {len(todo)} фото за {time.time() - t0:.0f} с")
    part = json.loads(PART.read_text()) if PART.exists() else {}
    rest = [(hid, u, str(paths[u])) for hid, u in todo if paths[u] and u not in part]
    batches = [rest[i:i + BATCH] for i in range(0, len(rest), BATCH)]
    print(f"к разметке {len(rest)} кадров, {len(batches)} вызовов, уже готово {len(part)}")
    t1, calls = time.time(), 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for res in ex.map(label_batch, batches):
            calls += 1
            part.update(res)
            PART.write_text(json.dumps(part, ensure_ascii=False))
            print(f"{time.strftime('%H:%M:%S')} вызовов {calls}/{len(batches)}, кадров {len(part)}", flush=True)
    print(f"разметка: {calls} вызовов за {(time.time() - t1) / 60:.1f} мин")
    if a.limit:
        return
    out = {h["id"]: [{"url": u, "labels": part[u]} for u in (h.get("photos") or []) if u in part] for h in hotels}
    out = {k: v for k, v in out.items() if v}
    FROZEN.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    missing = len(todo) - sum(len(v) for v in out.values())
    print(f"записано {FROZEN.name}: {len(out)} отелей, {sum(len(v) for v in out.values())} кадров, без разметки {missing}")


if __name__ == "__main__":
    main()
