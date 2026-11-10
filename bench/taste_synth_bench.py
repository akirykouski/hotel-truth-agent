"""Кластеры вкуса на синтетике: сила сигнала × число посетителей × зерно, контроль signal=0, задержка, восстановление персон.

Каждая конфигурация в своей временной базе. Метрика: офлайн-повтор холодного старта (taste.replay, k-fold по
посетителям, вкус только из контекста и моторики), MRR открытого отеля до/после и 95% ДИ бутстрепом.
Восстановление персон: ARI между кластерами и скрытой персоной. Задержка: taste.apply на 30 отелях.
Запуск: python bench/taste_synth_bench.py [--out bench/results/taste_synth.json]
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "taste_synth.json"))
ap.add_argument("--signals", default="0,0.3,0.6,0.9")
ap.add_argument("--ns", default="100,300,1000")
ap.add_argument("--seeds", default="11,12,13")
a = ap.parse_args()
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ.setdefault("TASTE_DEMO", "1")   # задержка демо-пути (в результатах до этой строки мерился путь «on» с записью serp_base)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np  # noqa: E402
from app import taste, taste_synth, visitors  # noqa: E402


def ari(a_, b_):
    from collections import Counter
    n = len(a_)
    comb = lambda x: x * (x - 1) / 2
    ct = Counter(zip(a_, b_))
    sa, sb = Counter(a_), Counter(b_)
    idx = sum(comb(v) for v in ct.values())
    ea, eb = sum(comb(v) for v in sa.values()), sum(comb(v) for v in sb.values())
    exp = ea * eb / comb(n)
    mx = (ea + eb) / 2
    return (idx - exp) / (mx - exp) if mx != exp else 0.0


rows = []
taste.hotels()
for sig in [float(x) for x in a.signals.split(",")]:
    for n in [int(x) for x in a.ns.split(",")]:
        for seed in [int(x) for x in a.seeds.split(",")]:
            db = Path(tempfile.mkdtemp()) / "v.sqlite"
            truth = taste_synth.generate(n=n, signal=sig, seed=seed, db=db)
            t = time.time()
            model = taste.fit(include_synthetic=True, db=db)
            fit_s = time.time() - t
            if model is None:
                rows.append({"signal": sig, "n": n, "seed": seed, "model": None})
                continue
            vs = {v["vid"]: v for v in visitors.all_visitors(db)}
            lab = [taste.assign(model, vs[v]) for v in truth]
            ev = taste.replay(include_synthetic=True, db=db, cold_only=True)
            # задержка: модель в состоянии модуля, как в проде
            taste._state.update({"demo": model, "prod": model, "gate": {"passed": True}})
            H = taste.hotels()
            items = [{"id": h, "bucket": "match" if i < 10 else "maybe"} for i, h in enumerate(H["ids"][:30])]
            lat = []
            for v in list(truth)[:100]:
                t = time.perf_counter()
                taste.apply(v, items, demo=True, db=db)
                lat.append((time.perf_counter() - t) * 1000)
            rows.append({"signal": sig, "n": n, "seed": seed, "k": model["k"], "silhouette": model["silhouette"],
                         "ari_persona": round(ari(lab, list(truth.values())), 3), "fit_s": round(fit_s, 2),
                         "replay_cold": ev, "apply_ms_p50": round(float(np.percentile(lat, 50)), 2),
                         "apply_ms_p95": round(float(np.percentile(lat, 95)), 2)})
            visitors.reset_connections()
            print(json.dumps(rows[-1], ensure_ascii=False), file=sys.stderr)
# сводка по (signal, n): среднее по зёрнам
summary = []
for sig in sorted({r["signal"] for r in rows}):
    for n in sorted({r["n"] for r in rows}):
        rs = [r for r in rows if r["signal"] == sig and r["n"] == n and r.get("replay_cold")]
        if not rs:
            continue
        summary.append({"signal": sig, "n": n, "seeds": len(rs),
                        "mrr_base": round(np.mean([r["replay_cold"]["mrr_base"] for r in rs]), 4),
                        "gain_best_tried": round(np.mean([r["replay_cold"]["gain"] for r in rs]), 4),
                        # λ выбирается повтором; если ни одна сила не значима, λ = 0 и фактический сдвиг 0
                        "gain_effective": round(np.mean([r["replay_cold"]["gain"] if r["replay_cold"]["lmax"] > 0 else 0.0
                                                         for r in rs]), 4),
                        "lmax_chosen": [r["replay_cold"]["lmax"] for r in rs],
                        "ci_low_min": min(r["replay_cold"]["ci_low"] for r in rs),
                        "ci_high_max": max(r["replay_cold"]["ci_high"] for r in rs),
                        "seeds_significant": sum(r["replay_cold"]["ci_low"] > 0 for r in rs),
                        "ari": round(np.mean([r["ari_persona"] for r in rs]), 3),
                        "silhouette": round(np.mean([r["silhouette"] for r in rs]), 3),
                        "apply_ms_p95": max(r["apply_ms_p95"] for r in rs), "fit_s_max": max(r["fit_s"] for r in rs)})
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
Path(a.out).write_text(json.dumps({"summary": summary, "runs": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
for s in summary:
    print(json.dumps(s, ensure_ascii=False))
