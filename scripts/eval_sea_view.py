"""Оценка «вид на море» против независимой разметки (data/eval/sea_view_gold.json).

Детерминирована, фото не нужны: читает gold json и seed-факты (data/facts.sqlite, только чтение).
Сравнивает: расчёт (geo), итог движка правды (resolved: geo+карточка+фото+отзывы), baseline «до берега ≤ X м»,
baseline «карточка заявляет вид на море». Метки «unknown» из оценки точности исключены (считаются отдельно).
  python scripts/eval_sea_view.py [--json data/eval/sea_view_results.json]
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import shutil, tempfile  # noqa: E401
_TMP = Path(tempfile.mkdtemp()) / "facts.sqlite"   # store.conn включает WAL и пишет схему: seed не трогаем, читаем копию
shutil.copy(ROOT / "data" / "facts.sqlite", _TMP)
os.environ["FACTS_DB"] = str(_TMP)
os.environ["LLM_PROVIDER"] = "none"

from app import registry, store  # noqa: E402

GOLD = ROOT / "data" / "eval" / "sea_view_gold.json"
ABSTAIN_BELOW = 0.5          # уверенность ниже: система воздерживается
BAND_ROWS = ("расчёт (geo, только геометрия)", "baseline: до берега ≤ 300 м", "baseline: карточка заявляет «вид на море»")
COAST_X = (150, 300, 500)    # 300 выбран заранее как основной; 150 и 500 для чувствительности


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def fmt(k, n):
    if n == 0:
        return "н/д (n=0)"
    lo, hi = wilson(k, n)
    return f"{k / n:.2f} [{lo:.2f}–{hi:.2f}] ({k}/{n})"


def metrics(items, pred):
    """items: размеченные yes/no; pred(item) -> (bool|None). None = воздержался."""
    tp = fp = fn = tn = ab = 0
    errs = []
    for it in items:
        p = pred(it)
        y = it["label"] == "yes"
        if p is None:
            ab += 1
            continue
        if p and y:
            tp += 1
        elif p and not y:
            fp += 1
            errs.append(("FP", it))
        elif not p and y:
            fn += 1
            errs.append(("FN", it))
        else:
            tn += 1
    n = tp + fp + fn + tn
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if tp and prec + rec else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "n": n, "abstain": ab, "n_items": len(items),
            "precision": fmt(tp, tp + fp), "recall": fmt(tp, tp + fn), "accuracy": fmt(tp + tn, n),
            "specificity": fmt(tn, tn + fp), "f1": round(f1, 2), "abstain_rate": fmt(ab, len(items))}, errs


def load():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    char = registry.get("sea_view")
    for it in gold["items"]:
        fs = {f["source"]: f for f in store.facts(it["id"], "sea_view")}
        g = fs["geo"]
        it["geo_has"] = bool(g["value"]["has"])
        it["geo_conf"] = float(g["confidence"])
        it["geo_from_floor"] = g["value"].get("from_floor")
        it["geo_facade"] = g["value"].get("facade")
        ev = json.loads(g["evidence"]) if isinstance(g["evidence"], str) else (g["evidence"] or {})
        fac = ev.get("facades", [])
        it["geo_max_deg"] = max([f.get("sea_deg_top_floor", 0) for f in fac] or [0])
        bld = ev.get("building", {})
        it["geo_match"] = bld.get("match")
        it["geo_levels_src"] = bld.get("levels_source")
        it["card_claim"] = "card" in fs
        res = store.resolve(it["id"], char)
        it["res_has"] = bool((res.get("value") or {}).get("has"))
        it["res_conf"] = float(res.get("confidence") or 0)
        it["res_source"] = res.get("source_label")
    return gold


def why(kind, it):
    """Короткая причина по заметке разметки и расчёта (для списка ошибок)."""
    g = f"расчёт: {'видно' if it['geo_has'] else 'нет'} (ув. {it['geo_conf']:.2f}" + (
        f", сторона {it['geo_facade']} с {it['geo_from_floor']} эт." if it["geo_has"] else "") + ")"
    if not it["geo_has"]:
        g += ("; море закрыто полностью" if it["geo_max_deg"] == 0 else
              f"; макс. {it['geo_max_deg']}° моря с верхнего этажа" + (" (ниже порога 10°)" if it["geo_max_deg"] < 10 else ""))
    g += f"; здание: {it['geo_match']}, " + ("этажность в OSM не указана" if "не указана" in (it["geo_levels_src"] or "") else "этажность из OSM")
    return f"{g}; берег {it['coast_dist_m']} м; метка {it['label']} ({it['label_confidence']}): {it['note']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    gold = load()
    allit = gold["items"]
    lab = [i for i in allit if i["label"] in ("yes", "no")]
    unk = [i for i in allit if i["label"] == "unknown"]
    print(f"Выборка: {len(allit)} отелей; размечено yes/no: {len(lab)} (yes {sum(i['label']=='yes' for i in lab)}, "
          f"no {sum(i['label']=='no' for i in lab)}); unknown: {len(unk)}")

    methods = {
        "расчёт (geo, только геометрия)": lambda i: None if i["geo_conf"] < ABSTAIN_BELOW else i["geo_has"],
        "итог движка (geo+карточка+фото+отзывы)": lambda i: None if i["res_conf"] < ABSTAIN_BELOW else i["res_has"],
    }
    for x in COAST_X:
        methods[f"baseline: до берега ≤ {x} м"] = (lambda x: lambda i: i["coast_dist_m"] <= x)(x)
    methods["baseline: карточка заявляет «вид на море»"] = lambda i: i["card_claim"]
    methods["baseline: всегда «видно»"] = lambda i: True

    out = {"n_sample": len(allit), "n_labelled": len(lab), "n_unknown": len(unk), "methods": {}}
    errs_by = {}

    def table(title, items, only=None):
        print(f"\n### {title} (n={len(items)})\n")
        print("| метод | precision | recall | accuracy | specificity | F1 | воздержался |")
        print("|---|---|---|---|---|---|---|")
        res = {}
        for name, fn in methods.items():
            m, errs = metrics(items, fn)
            res[name] = m
            errs_by.setdefault(title, {})[name] = errs
            if only and name not in only:
                continue
            print(f"| {name} | {m['precision']} | {m['recall']} | {m['accuracy']} | {m['specificity']} | {m['f1']} | {m['abstain_rate']} |")
        return res

    out["methods"]["all"] = table("Все размеченные", lab)
    cells = [i for i in lab if i["sample_from"] == "ячейка"]
    out["methods"]["cells_only"] = table("Только отели, выбранные по ячейкам страт (без «спорных» из отбора по расхождению)", cells)
    for band, nm in (("near", "<300 м"), ("mid", "300–800 м"), ("far", ">800 м")):
        sub = [i for i in lab if i["band"] == band]
        if sub:
            out["methods"][band] = table(f"Берег {nm}", sub, only=BAND_ROWS)

    # воздержание и порог уверенности (расчёт)
    print("\n### Расчёт: точность по порогу уверенности (selective prediction)\n")
    print("| порог | покрытие | accuracy на отвеченных |")
    print("|---|---|---|")
    sel = {}
    for th in (0.0, 0.5, 0.7, 0.9, 1.0):
        ans = [i for i in lab if i["geo_conf"] >= th]
        ok = sum(i["geo_has"] == (i["label"] == "yes") for i in ans)
        sel[th] = {"answered": len(ans), "correct": ok}
        print(f"| ≥{th} | {fmt(len(ans), len(lab))} | {fmt(ok, len(ans))} |")
    out["selective"] = sel
    print("\nUnknown-метки (разметчик не смог решить): по предсказанию расчёта")
    print(f"  расчёт «видно»: {sum(i['geo_has'] for i in unk)}, «нет»: {sum(not i['geo_has'] for i in unk)}; "
          f"воздержаний расчёта (ув.<{ABSTAIN_BELOW}): {sum(i['geo_conf'] < ABSTAIN_BELOW for i in allit)} из {len(allit)}")

    key = "Все размеченные"
    for name in ("расчёт (geo, только геометрия)", "baseline: до берега ≤ 300 м"):
        print(f"\n### Ошибки: {name}\n")
        for kind, it in errs_by[key][name]:
            print(f"- {kind} {it['id']} {it['name']}: {why(kind, it)}")
    out["errors"] = {n: [{"kind": k, "id": i["id"], "name": i["name"], "why": why(k, i)} for k, i in errs_by[key][n]]
                     for n in errs_by[key]}
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
