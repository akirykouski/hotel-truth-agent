"""Кластеры вкуса на реальных данных Expedia: помогает ли кластер по контексту угадать выбор лучше популярности.

Данные: Kaggle «Expedia Hotel Recommendations» (бронирования 2013–2014, цель = один из 100 кластеров отелей),
разбивка по времени из зеркала huggingface.co/datasets/anhvanhyx9/expedia-train-val-test (train/valid/test.csv).

Без персонализации (база): популярность кластеров отелей в направлении поиска (аналог нашего запроса).
С кластерами вкуса: та же формула, что в app/taste.py, s = (1 − позиция/n) + λ·τc[отель], где τc — вектор
подъёма P(отель | кластер посетителя) / P(отель) − 1, нормированный. Кластер посетителя — k-means по контексту
без истории: страна, регион, мобильность, канал, сайт, состав группы, пакет, срок до заезда, длительность, месяц.
Направление поиска в кластеры не входит: оно уже в базе.

k и λ выбираются на valid, отчёт на test. Контроль: те же кластеры, но перемешанные между событиями test.
Запуск: python bench/taste_expedia.py --data <папка с csv> [--out bench/results/taste_expedia.json]
"""
import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True)
ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "taste_expedia.json"))
ap.add_argument("--sample-fit", type=int, default=120_000)
ap.add_argument("--ks", default="8,16,32,64")
ap.add_argument("--lams", default="0,0.1,0.2,0.4,0.6,0.8,1.2,1.6")
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
rng = np.random.default_rng(a.seed)
t0 = time.time()

COLS = ["user_id", "item_id", "is_cold", "ctx_dest_id", "ctx_is_mobile", "ctx_channel", "ctx_site_name",
        "ctx_posa_continent", "ctx_user_country", "ctx_user_region", "ctx_party_type", "ctx_is_package",
        "ctx_adults", "ctx_children", "ctx_lead_days", "ctx_stay_nights", "ctx_checkin_month"]


def load(name):
    out = {c: [] for c in COLS}
    with open(Path(a.data) / f"{name}.csv", newline="") as f:
        for r in csv.DictReader(f):
            for c in COLS:
                out[c].append(r[c])
    return out


def num(xs, default=0.0):
    o = np.empty(len(xs))
    for i, x in enumerate(xs):
        try:
            o[i] = float(x)
        except ValueError:
            o[i] = default
    return o


D = {n: load(n) for n in ("train", "valid", "test")}
print(f"загружено за {time.time() - t0:.0f} с:", {n: len(d["item_id"]) for n, d in D.items()}, file=sys.stderr)


def vocab(col, top):
    vals, cnt = np.unique(np.array(D["train"][col]), return_counts=True)
    return list(vals[np.argsort(-cnt)][:top])


VOC = {"ctx_user_country": vocab("ctx_user_country", 15), "ctx_user_region": vocab("ctx_user_region", 30),
       "ctx_channel": vocab("ctx_channel", 11), "ctx_site_name": vocab("ctx_site_name", 12),
       "ctx_posa_continent": vocab("ctx_posa_continent", 5), "ctx_party_type": vocab("ctx_party_type", 8)}


def features(d):
    blocks = []
    for col, voc in VOC.items():
        idx = {v: i for i, v in enumerate(voc)}
        oh = np.zeros((len(d[col]), len(voc) + 1))
        oh[np.arange(len(d[col])), [idx.get(x, len(voc)) for x in d[col]]] = 1
        blocks.append(oh)
    mob = num(d["ctx_is_mobile"])[:, None]
    pkg = num(d["ctx_is_package"])[:, None]
    lead = np.log1p(np.clip(num(d["ctx_lead_days"]), 0, 400))[:, None] / 6
    stay = np.log1p(np.clip(num(d["ctx_stay_nights"]), 0, 30))[:, None] / 3.4
    mon = num(d["ctx_checkin_month"], 6)
    season = np.stack([np.sin(2 * np.pi * mon / 12), np.cos(2 * np.pi * mon / 12)], 1)
    ad = np.clip(num(d["ctx_adults"], 2), 0, 6)[:, None] / 3
    ch = np.clip(num(d["ctx_children"]), 0, 4)[:, None] / 2
    return np.hstack(blocks + [mob, pkg, lead, stay, season, ad, ch]).astype(np.float32)


X = {n: features(d) for n, d in D.items()}
Y = {n: np.array(d["item_id"], int) for n, d in D.items()}
DEST = {n: np.array(d["ctx_dest_id"]) for n, d in D.items()}
COLD = {n: np.array(d["is_cold"]) == "True" for n, d in D.items()}
NI = 100

# база: популярность в направлении, затем общая
glob = np.bincount(Y["train"], minlength=NI).astype(float) + 1
glob /= glob.sum()
dest_cnt = {}
for dst, y in zip(DEST["train"], Y["train"]):
    v = dest_cnt.get(dst)
    if v is None:
        v = dest_cnt[dst] = np.zeros(NI)
    v[y] += 1


def base_scores(split):
    S = np.empty((len(Y[split]), NI))
    for i, dst in enumerate(DEST[split]):
        v = dest_cnt.get(dst)
        S[i] = (v if v is not None else 0) + 1e-3 * glob   # общая популярность разбивает ничьи
    return S


BASE = {n: base_scores(n) for n in ("valid", "test")}


def kmeans(Xs, k, iters=40):
    C = Xs[rng.choice(len(Xs), k, replace=False)]
    for _ in range(iters):
        lab = assign(Xs, C)
        newC = np.array([Xs[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
        if np.allclose(newC, C, atol=1e-5):
            break
        C = newC
    return C


def assign(Xa, C, chunk=50_000):
    out = np.empty(len(Xa), int)
    c2 = (C ** 2).sum(1)
    for s in range(0, len(Xa), chunk):
        B = Xa[s:s + chunk]
        out[s:s + chunk] = (c2[None] - 2 * B @ C.T).argmin(1)
    return out


def taste_vectors(lab_train, k):
    T = np.zeros((k, NI))
    for j in range(k):
        p = np.bincount(Y["train"][lab_train == j], minlength=NI).astype(float) + 1
        lift = (p / p.sum()) / glob - 1
        T[j] = lift / max(np.linalg.norm(lift), 1e-9)
    return T


def rerank_rank(S, T_rows, lam):
    """Ранг (1..100) правильного отеля: база → позиция → s = (1 − pos/n) + λ·τ."""
    order = np.argsort(-S, 1, kind="stable")
    pos = np.empty_like(order)
    pos[np.arange(len(S))[:, None], order] = np.arange(NI)[None]
    s = (1 - pos / NI) + lam * T_rows
    return s


def ranks(scores, y):
    tgt = scores[np.arange(len(y)), y]
    return 1 + (scores > tgt[:, None]).sum(1)


def metrics(rk, mask=None):
    rk = rk if mask is None else rk[mask]
    rr = 1 / rk
    return {"n": int(len(rk)), "mrr": round(float(rr.mean()), 4), "map5": round(float(np.where(rk <= 5, rr, 0).mean()), 4),
            "hit5": round(float((rk <= 5).mean()), 4)}


def boot_gain(rb, rt, n=300):
    d = 1 / rt - 1 / rb
    bs = [d[rng.integers(len(d), size=len(d))].mean() for _ in range(n)]
    return round(float(d.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)


fit_idx = rng.choice(len(X["train"]), min(a.sample_fit, len(X["train"])), replace=False)
rank_base = {n: ranks(rerank_rank(BASE[n], np.zeros((len(Y[n]), NI)), 0), Y[n]) for n in ("valid", "test")}
grid = []
best = None
models = {}
for k in [int(x) for x in a.ks.split(",")]:
    C = kmeans(X["train"][fit_idx], k)
    lab_tr = assign(X["train"], C)
    T = taste_vectors(lab_tr, k)
    lab_va = assign(X["valid"], C)
    models[k] = (C, T)
    for lam in [float(x) for x in a.lams.split(",")]:
        rk = ranks(rerank_rank(BASE["valid"], T[lab_va], lam), Y["valid"])
        m = metrics(rk)
        grid.append({"k": k, "lambda": lam, **m})
        if best is None or m["mrr"] > best[0]:
            best = (m["mrr"], k, lam)
    print(f"k={k} готово, {time.time() - t0:.0f} с", file=sys.stderr)
_, K, LAM = best
C, T = models[K]
lab_te = assign(X["test"], C)
res = {}
for name, lam in (("tuned", LAM), ("app_default_0.6", 0.6)):
    rk = ranks(rerank_rank(BASE["test"], T[lab_te], lam), Y["test"])
    res[name] = {"lambda": lam, "all": metrics(rk), "cold": metrics(rk, COLD["test"]), "warm": metrics(rk, ~COLD["test"]),
                 "gain_all": boot_gain(rank_base["test"], rk), "gain_cold": boot_gain(rank_base["test"][COLD["test"]], rk[COLD["test"]])}
# вариант «вероятности»: s = log P(отель | направление) + β · log(P(отель | кластер) / P(отель)).
# В отличие от сдвига по позиции, сила базы сохраняется: сильный сигнал запроса кластер не перебивает.
def nb_scores(split, lab, k, beta):
    P = BASE[split] / BASE[split].sum(1, keepdims=True)
    L = np.zeros((k, NI))
    for j in range(k):
        p = np.bincount(Y["train"][lab_tr_by_k[k] == j], minlength=NI).astype(float) + 1
        L[j] = np.log((p / p.sum()) / glob)
    return np.log(P + 1e-6) + beta * L[lab]


lab_tr_by_k = {}
nb_grid, nb_best = [], None
for k, (Ck, Tk) in models.items():
    lab_tr_by_k[k] = assign(X["train"], Ck)
    lab_va = assign(X["valid"], Ck)
    for beta in (0.0, 0.1, 0.25, 0.5, 0.75, 1.0):
        m = metrics(ranks(nb_scores("valid", lab_va, k, beta), Y["valid"]))
        nb_grid.append({"k": k, "beta": beta, **m})
        if nb_best is None or m["mrr"] > nb_best[0]:
            nb_best = (m["mrr"], k, beta)
_, KB, BETA = nb_best
lab_te_b = assign(X["test"], models[KB][0])
rk_nb0 = ranks(nb_scores("test", lab_te_b, KB, 0.0), Y["test"])
rk_nb = ranks(nb_scores("test", lab_te_b, KB, BETA), Y["test"])
rk_nbc = ranks(nb_scores("test", rng.permutation(lab_te_b), KB, BETA), Y["test"])
res["prob_blend"] = {"k": KB, "beta": BETA, "base_same_scoring": metrics(rk_nb0),
                     "all": metrics(rk_nb), "cold": metrics(rk_nb, COLD["test"]), "warm": metrics(rk_nb, ~COLD["test"]),
                     "gain_all": boot_gain(rk_nb0, rk_nb), "gain_cold": boot_gain(rk_nb0[COLD["test"]], rk_nb[COLD["test"]]),
                     "control_shuffled": {"all": metrics(rk_nbc), "gain_all": boot_gain(rk_nb0, rk_nbc)}}
perm = rng.permutation(lab_te)
rk = ranks(rerank_rank(BASE["test"], T[perm], LAM), Y["test"])
res["control_shuffled_clusters"] = {"lambda": LAM, "all": metrics(rk), "gain_all": boot_gain(rank_base["test"], rk)}
out = {"data": "Expedia Hotel Recommendations (Kaggle), time split from HF anhvanhyx9/expedia-train-val-test",
       "rows": {n: len(Y[n]) for n in Y}, "items": NI, "chosen": {"k": K, "lambda": LAM, "by": "valid MRR"},
       "base_test": {"all": metrics(rank_base["test"]), "cold": metrics(rank_base["test"], COLD["test"]),
                     "warm": metrics(rank_base["test"], ~COLD["test"])},
       "taste_test": res, "valid_grid": grid, "valid_grid_prob": nb_grid, "seconds": round(time.time() - t0)}
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in out.items() if k != "valid_grid"}, ensure_ascii=False, indent=1))
