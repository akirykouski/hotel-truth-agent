"""Benchmark: one frozen yardstick for every feature branch.

Runs against any checkout of the repo (main, a feature worktree, the integration branch) on a throwaway copy
of that checkout's facts.sqlite. Deterministic, no LLM (LLM_PROVIDER=none). The LLM track is bench/llm_track.py.

    python bench/run.py --repo ../ostrovok-agent-truth --out bench/results/truth.json

Every probe either measures something that exists in the baseline (so the delta is honest) or checks a feature
contract from bench/CONTRACTS.md; a missing contract scores "absent", never an error.
"""
import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
ap.add_argument("--out")
ap.add_argument("--only", nargs="*")
args = ap.parse_args()
REPO = Path(args.repo).resolve()

tmp = Path(tempfile.mkdtemp(prefix="bench-"))
shutil.copy(REPO / "data" / "facts.sqlite", tmp / "facts.sqlite")
os.environ.update(FACTS_DB=str(tmp / "facts.sqlite"), CUSTOM_DIR=str(tmp / "custom"), SIM_FILE=str(tmp / "sim.json"),
                  LLM_PROVIDER="none")
os.environ.pop("REGION", None)
sys.path.insert(0, str(REPO))

from app import geodata as gd  # noqa: E402
from app import registry, search, store  # noqa: E402

GEO = gd.load()
HOTELS = GEO.hotels
PHYSICAL = ["sea_view", "night_quiet", "beach_walk", "sunset"]
POLICY = ["pets", "night_checkin"]

SCENARIOS = [
    "Тихий номер с видом на закат недалеко от моря, едем в июле",
    "Еду с мамой, ей тяжело ходить в гору. Нужно близко к пляжу и чтобы из окна было видно море",
    "Мы с ребёнком 3 лет и собакой 12 кг. Нужна детская площадка рядом и чтобы пускали с собакой",
    "Работаю удалённо две недели в ноябре: нужно тихо днём, хороший интернет и чтобы рядом можно было поесть",
    "Прилетаем в 2 ночи. Важно, чтобы рядом была круглосуточная аптека и где-то поесть",
    "Хочу смотреть, как солнце садится в море, в конце декабря",
    "Чтобы рядом не было стройки и баров под окнами, и не надо было переходить железную дорогу к морю",
    "Есть ли плотные шторы блэкаут? Мне важно спать днём",
]
STRICT = [  # deliberately over-constrained: relaxation should have something to say
    "Тихий номер с видом на море и закатом, без подъёма до пляжа, с собакой, рядом детская площадка, июль",
    "Вид на море, тихо, круглосуточная аптека рядом, пускают с собакой, плотные шторы, без подъёма, парковка",
    "Закат над морем в декабре, тихо ночью, без подъёма, парковка, с собакой, детская площадка",
]


def key_of(cid):
    return (registry.get(cid) or {}).get("key")


def geo_fact(hid, cid):
    return next((f for f in store.facts(hid, cid) if f["source"] == "geo"), None)


def timed(fn):
    t0 = time.time()
    try:
        out = fn()
        return out, round(time.time() - t0, 2), None
    except Exception as e:
        return None, round(time.time() - t0, 2), f"{type(e).__name__}: {e}\n{traceback.format_exc()[-600:]}"


# ---------------------------------------------------------------- T1: baseline quality metrics (app/metrics.py)

def t1_metrics():
    from app import metrics
    r = metrics.report()
    sv, nz = r["sea_view"], r["noise"]["by_loudest_side"]
    cov = r["coverage"]
    return {
        "sea_recall_vs_card": sv["recall_vs_card"], "sea_recall_vs_reviews": sv["recall_vs_reviews"],
        "sea_recall_vs_strong": sv["recall_vs_strong"], "sea_agrees_no_view": sv["geo_agrees_no_view"],
        "sea_geo_yes_not_advertised": sv["geo_yes_not_advertised"],
        "noise_complaints_per100_by_band": [b["complaints_per_100_reviews"] for b in nz],
        "noise_monotonic": all(a <= b for a, b in zip([b["complaints_per_100_reviews"] for b in nz],
                                                      [b["complaints_per_100_reviews"] for b in nz][1:])),
        "claims_overstated": r["claims"]["overstated"],
        "coverage_mean": round(sum(c["coverage"] for c in cov) / len(cov), 3),
        "conflicts_total": sum(c["conflict"] for c in cov),
        "characteristics": len(cov),
        "questions_total": r["questions"]["total"], "facts_total": r["questions"]["facts_total"],
    }


# ---------------------------------------------------------------- T2: fraud robustness (adversarial hotelier)

def _inject(hid, cid, value, conf=0.9):
    return store.put_fact(hid, cid, "hotelier", value, conf, "ответ отельера (синтетическая проверка)",
                          "bench: injected hotelier claim", 365)


def t2_fraud():
    """Hotelier contradicts confident physics on physical characteristics → physics should survive and the
    conflict must be flagged. On policy characteristics the hotelier is the authority → hotelier should win."""
    out = {}
    for cid in PHYSICAL + POLICY:
        spec, key = registry.get(cid), key_of(cid)
        if not spec or not key:
            continue
        cases = []
        for h in HOTELS:
            base = store.resolve(h["id"], spec)
            v = (base.get("value") or {}).get(key)
            if not isinstance(v, bool) or base["status"] == "unknown" or base["confidence"] < 0.5:
                continue
            if cid in PHYSICAL and base.get("source") not in ("geo", "osm", "open-meteo"):
                continue
            cases.append((h["id"], v))
        cases = cases[:40]
        held, flagged = 0, 0
        for hid, v in cases:
            before = copy.deepcopy(store.resolve(hid, spec)["value"])
            fid = _inject(hid, cid, dict(before) | {key: (not v)})
            r = store.resolve(hid, spec)
            held += (r["value"] or {}).get(key) == v
            flagged += r["status"] == "conflict" or bool(r.get("conflicts"))
            store.conn().execute("DELETE FROM facts WHERE id=?", (fid,))
            store.conn().execute("UPDATE facts SET active=1, superseded_by=NULL WHERE superseded_by=?", (fid,))
            store.conn().commit()
        n = len(cases)
        r3 = (lambda x: round(x / n, 3) if n else None)
        if cid in PHYSICAL:
            out[cid] = {"n": n, "physics_holds": r3(held), "conflict_flagged": r3(flagged)}
        else:
            out[cid] = {"n": n, "hotelier_wins": r3(n - held), "conflict_flagged": r3(flagged)}
    phys = [v["physics_holds"] for k, v in out.items() if k in PHYSICAL and v["n"]]
    pol = [v["hotelier_wins"] for k, v in out.items() if k in POLICY and v["n"]]
    # also count how often a hotelier claim agreeing with strong guest reviews already matches the resolved value
    out["_score"] = {"physics_holds_mean": round(sum(phys) / max(1, len(phys)), 3),
                     "policy_hotelier_wins_mean": round(sum(pol) / max(1, len(pol)), 3)}
    return out


def t2_correction():
    """The other side of fraud resistance: where strong guest reviews already disagree with the computation, a
    hotelier claim that AGREES with the guests is an honest correction and should be accepted (value follows
    hotelier + guests). A system that blocks every hotelier claim on physics scores 0 here."""
    out = {}
    for cid in PHYSICAL:
        spec, key = registry.get(cid), key_of(cid)
        if not spec or not key:
            continue
        cases = []
        for h in HOTELS:
            fs = store.facts(h["id"], cid)
            g = next((f for f in fs if f["source"] == "geo"), None)
            rv = next((f for f in fs if f["source"] == "reviews" and (f["confidence"] or 0) >= 0.5), None)
            if not g or not rv:
                continue
            gv, rvv = (g["value"] or {}).get(key), (rv["value"] or {}).get(key)
            if isinstance(gv, bool) and isinstance(rvv, bool) and gv != rvv:
                before = (store.resolve(h["id"], spec)["value"] or {}).get(key)
                if before != rvv:  # only cases the hotelier's claim would actually have to change
                    cases.append((h["id"], rvv, g["value"]))
        accepted = 0
        for hid, want, gval in cases:
            fid = _inject(hid, cid, dict(gval) | {key: want})
            accepted += (store.resolve(hid, spec)["value"] or {}).get(key) == want
            store.conn().execute("DELETE FROM facts WHERE id=?", (fid,))
            store.conn().execute("UPDATE facts SET active=1, superseded_by=NULL WHERE superseded_by=?", (fid,))
            store.conn().commit()
        out[cid] = {"n": len(cases), "correction_accepted": round(accepted / len(cases), 3) if cases else None}
    n = sum(v["n"] for v in out.values())
    out["_score"] = {"n": n, "correction_accepted": round(sum(v["n"] * v["correction_accepted"] for v in out.values()
                                                              if v["correction_accepted"] is not None) / n, 3) if n else None,
                     "note": None if n else "не измеримо: система уже согласна с гостями до ответа отельера"}
    return out


# ---------------------------------------------------------------- T3: held-out agreement + calibration

def _ece(pairs, bins=5):
    if not pairs:
        return None
    tot, err = len(pairs), 0.0
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        b = [(c, y) for c, y in pairs if lo <= c < hi or (i == bins - 1 and c == 1.0)]
        if b:
            err += len(b) / tot * abs(sum(c for c, _ in b) / len(b) - sum(y for _, y in b) / len(b))
    return round(err, 3)


def t3_heldout():
    """Leave-one-source-out: hide the reviews fact, resolve from the rest, compare with what guests said.
    Only reviews facts with confidence ≥ 0.5 count as labels (strong guest signal). ECE = calibration error of
    the resolved confidence against that agreement. Reviews are never the label for their own prediction."""
    out, allpairs = {}, []
    for cid in registry.all_chars():
        spec, key = registry.get(cid), key_of(cid)
        if not key:
            continue
        pairs, agree, n = [], 0, 0
        for h in HOTELS:
            fs = store.facts(h["id"], cid)
            lab = next((f for f in fs if f["source"] == "reviews" and (f["confidence"] or 0) >= 0.5), None)
            if not lab or not isinstance((lab["value"] or {}).get(key), bool):
                continue
            rest = [dict(f) for f in fs if f["source"] != "reviews"]
            if not rest:
                continue
            r = store.resolve(h["id"], spec, fs=rest)
            pv = (r.get("value") or {}).get(key)
            if not isinstance(pv, bool):
                continue
            ok = pv == lab["value"][key]
            agree += ok
            n += 1
            pairs.append((float(r["confidence"]), 1.0 if ok else 0.0))
        if n:
            out[cid] = {"n": n, "agree": round(agree / n, 3), "ece": _ece(pairs),
                        "mean_conf": round(sum(c for c, _ in pairs) / n, 3)}
            allpairs += pairs
    out["_score"] = {"n": len(allpairs), "agree": round(sum(y for _, y in allpairs) / max(1, len(allpairs)), 3),
                     "ece": _ece(allpairs)}
    # overconfidence (report problem: sea view at 1.0 behind trees)
    sv = registry.get("sea_view")
    confs = [store.resolve(h["id"], sv)["confidence"] for h in HOTELS]
    out["_overconfidence"] = {"sea_view_conf_eq_1": sum(1 for c in confs if c >= 0.999),
                              "sea_view_conf_ge_095": sum(1 for c in confs if c >= 0.95)}
    return out


# ---------------------------------------------------------------- T4: search scenarios (rules parser)

def t4_search():
    out = []
    for q in SCENARIOS:
        r = search.search(q, limit=5)
        out.append({"q": q[:60], "constraints": len(r["parsed"]["constraints"]), "counts": r["counts"],
                    "top": [x["hotel"]["id"] for x in r["results"][:5]]})
    return {"scenarios": out,
            "constraints_parsed_total": sum(x["constraints"] for x in out),
            "scenarios_with_match": sum(1 for x in out if x["counts"]["match"] > 0)}


# ---------------------------------------------------------------- feature probes (contracts)

def f2_window():
    from app.tools import window  # noqa
    sv = registry.get("sea_view")
    consistent, n, t0 = 0, 0, time.time()
    for h in HOTELS[:60]:
        g = geo_fact(h["id"], "sea_view")
        if not g or g["confidence"] < 0.8:
            continue
        v = g["value"]
        levels = v.get("levels") or 5
        if v.get("has"):
            w = window.render(h["id"], facade=v.get("facade"), floor=int(v.get("from_floor") or levels), month=7)
            ok = w["sea_fraction"] > 0
        else:
            w = window.render(h["id"], floor=int(levels), month=7)
            ok = w["sea_fraction"] == 0 or w.get("sea_p", 0) < 0.5
        has_svg = isinstance(w.get("svg"), str) and w["svg"].lstrip().startswith("<svg")
        has_sun = isinstance(w.get("sun"), dict) and "az" in w["sun"]
        consistent += ok and has_svg and has_sun
        n += 1
    return {"n": n, "consistent_with_sea_view": round(consistent / max(1, n), 3),
            "ms_per_render": round(1000 * (time.time() - t0) / max(1, n))}


def f3_rooms():
    from app import rooms  # noqa
    named, named_ok, req, hidden, guest_ok, guest_n, total = 0, 0, 0, 0, 0, 0, 0
    from app.metrics import SEA_POS
    import re
    pos = re.compile("|".join(SEA_POS), re.I)
    for h in HOTELS:
        g = geo_fact(h["id"], "sea_view")
        rr = rooms.resolve_rooms(h["id"])
        by = {x["room"]: x for x in rr}
        total += len(rr)
        for x in rr:
            if x.get("special_request"):
                req += 1
            hidden += bool(x.get("hidden_view"))
            if x.get("claims_sea_view") and g and g["value"].get("has") and g["confidence"] >= 0.8:
                named += 1
                named_ok += x["sea_view_p"] >= 0.5 and bool((x.get("ask") or {}).get("min_floor"))
        for rv in h["reviews"]:
            x = by.get(rv.get("room"))
            if x and pos.search(rv.get("plus") or ""):
                guest_n += 1
                guest_ok += x["sea_view_p"] >= 0.5
    return {"categories": total, "named_sea_view_consistent": round(named_ok / max(1, named), 3), "named_n": named,
            "agree_with_guests_who_stayed": round(guest_ok / max(1, guest_n), 3), "guest_n": guest_n,
            "with_special_request": req, "hidden_view_categories": hidden}


FABRICATED = [  # (answer, trace) — every one contains a number the tools never returned
    ("Шум ночью около 31 дБ на стороне З.", [{"tool": "hotel_facts", "input": {"hotel_id": "__H__", "chars": ["night_quiet"]}}]),
    ("До пляжа 2 минуты пешком, подъёма нет.", [{"tool": "hotel_facts", "input": {"hotel_id": "__H__", "chars": ["beach_walk"]}}]),
    ("Море видно с 1-го этажа со всех сторон.", [{"tool": "hotel_facts", "input": {"hotel_id": "__H__", "chars": ["sea_view"]}}]),
    ("Вода в ноябре 27 °C, можно купаться.", [{"tool": "hotel_facts", "input": {"hotel_id": "__H__", "chars": ["sea_season"]}}]),
    ("Аквапарк в 50 м от отеля.", []),
]


def f4_grounding():
    from app import grounding  # noqa
    from app import actions
    hid = HOTELS[0]["id"]
    caught = 0
    for txt, tr in FABRICATED:
        tr = json.loads(json.dumps(tr).replace("__H__", hid))
        for t in tr:
            t["output"] = getattr(actions, t["tool"])(**t["input"])
        v = grounding.verify(txt, tr)
        caught += v["unsupported"] > 0
    # a true answer must pass: quote the real fact summary
    real = actions.hotel_facts(hid, ["beach_walk"])["facts"][0]["summary"]
    tr = [{"tool": "hotel_facts", "input": {"hotel_id": hid, "chars": ["beach_walk"]}}]
    tr[0]["output"] = actions.hotel_facts(hid, ["beach_walk"])
    fp = grounding.verify(real, tr)["unsupported"] > 0
    return {"fabricated_caught": f"{caught}/{len(FABRICATED)}", "caught_rate": round(caught / len(FABRICATED), 3),
            "false_positive_on_true_answer": fp}


def f5_draft():
    from app import compiler
    r = compiler.add("рядом есть бассейн")
    cid = r.get("id") or r.get("char_id")
    spec = registry.get(cid) or {}
    status = spec.get("status") or r.get("status")
    parsed_public = search.parse_rules("отель где есть бассейн")
    public_sees = any(c["char"] == cid for c in parsed_public["constraints"])
    has_eval = isinstance(r.get("eval"), dict) and bool(r["eval"])
    approved_sees = None
    if hasattr(registry, "approve"):
        registry.approve(cid)
        approved_sees = any(c["char"] == cid for c in search.parse_rules("отель где есть бассейн")["constraints"])
    gate = status == "draft" and not public_sees and approved_sees is True
    return {"status_after_add": status, "public_sees_draft": public_sees, "has_eval_report": has_eval,
            "public_sees_after_approve": approved_sees, "gate_works": gate}


def f6_photos():
    n = store.conn().execute("SELECT COUNT(*) FROM facts WHERE source='photos' AND active=1").fetchone()[0]
    labels = REPO / "data" / "photo_labels.json"
    if not labels.exists() and n == 0:
        raise ImportError("no photo labels")
    agree, tot = 0, 0
    for h in HOTELS:
        p = next((f for f in store.facts(h["id"], "sea_view") if f["source"] == "photos"), None)
        g = geo_fact(h["id"], "sea_view")
        if p and g and isinstance((p["value"] or {}).get("has"), bool):
            tot += 1
            agree += p["value"]["has"] == g["value"]["has"]
    return {"photo_facts": n, "hotels_labeled": len(json.loads(labels.read_text())) if labels.exists() else 0,
            "sea_view_agree_with_geo": round(agree / max(1, tot), 3), "n": tot}


def f7_relax():
    got, useful = 0, 0
    detail = []
    for q in STRICT:
        r = search.search(q, limit=5)
        rel = r.get("relaxations")
        if r["counts"]["match"] < 10:
            ok = isinstance(rel, list) and len(rel) > 0 and all("drop" in x and "gain" in x for x in rel)
            got += ok
            useful += ok and any(x["gain"] > 0 for x in rel)
            detail.append({"q": q[:50], "match": r["counts"]["match"], "relaxations": (rel or [])[:3]})
    n = len(detail) or 1
    return {"strict_queries": len(detail), "with_relaxations": round(got / n, 3), "with_positive_gain": round(useful / n, 3),
            "detail": detail}


def f8_timeline():
    from app.tools import noise
    ok, n = 0, 0
    for h in HOTELS[:40]:
        g = geo_fact(h["id"], "night_quiet")
        t = noise.timeline(h["id"], month=7)
        fac = t["facades"]
        full = all(len(f["hours"]) == 24 for f in fac)
        if g:
            q = min(fac, key=lambda f: sum(float(f["hours"][str(k)] if str(k) in f["hours"] else f["hours"][k]) for k in (0, 1, 2, 3, 4)))
            night = sum(float(q["hours"][str(k)] if str(k) in q["hours"] else q["hours"][k]) for k in (23, 0, 1, 2, 3, 4, 5, 6)) / 8
            ok += full and abs(night - g["value"]["night_db_quiet"]) <= 4
            n += 1
    return {"n": n, "consistent_with_night_db": round(ok / max(1, n), 3)}


def f9_radar():
    from app import radar
    base = radar.scan()
    h = copy.deepcopy(HOTELS[0])
    today = date.today()
    for i in range(6):
        h["reviews"].append({"date": (today - timedelta(days=5 + i * 7)).isoformat(), "plus": "",
                             "minus": "Под окнами стройка, с 8 утра шумно, отбойный молоток.", "rating": 5,
                             "room": h["rooms"][0]["name"] if h["rooms"] else "", "id": 900000 + i})
    inj = radar.scan(hotels=[h])
    caught = any(a["hotel_id"] == h["id"] for a in inj)
    clean = copy.deepcopy(HOTELS[1])
    clean["reviews"] = [r for r in clean["reviews"] if "строй" not in ((r.get("minus") or "") + (r.get("plus") or ""))]
    return {"alerts_on_real_data": len(base), "alert_rate": round(len({a["hotel_id"] for a in base}) / len(HOTELS), 3),
            "synthetic_spike_caught": caught}


def f10_region():
    regions = REPO / "data" / "regions"
    names = [p.name for p in regions.iterdir() if p.is_dir()] if regions.exists() else []
    if not names:
        raise ImportError("no regions")
    res = {}
    for name in names:
        code = ("import json,sys; sys.path.insert(0,'.'); from app import geodata as gd, registry, store; "
                "g=gd.load(); sv=registry.get('sea_view'); "
                "k=sum(1 for h in g.hotels if store.resolve(h['id'],sv)['status']!='unknown'); "
                "print(json.dumps({'hotels':len(g.hotels),'sea_view_known':k}))")
        env = dict(os.environ, REGION=name)
        env.pop("FACTS_DB", None)
        p = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True, timeout=600)
        try:
            res[name] = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:
            res[name] = {"error": (p.stderr or p.stdout)[-400:]}
    return res


TRACKS = {"t1_metrics": t1_metrics, "t2_fraud": t2_fraud, "t2_correction": t2_correction, "t3_heldout": t3_heldout, "t4_search": t4_search,
          "f2_window": f2_window, "f3_rooms": f3_rooms, "f4_grounding": f4_grounding, "f5_draft": f5_draft,
          "f6_photos": f6_photos, "f7_relax": f7_relax, "f8_timeline": f8_timeline, "f9_radar": f9_radar,
          "f10_region": f10_region}


def main():
    git = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    res = {"repo": str(REPO), "branch": git, "sha": sha, "at": time.strftime("%Y-%m-%d %H:%M"), "tracks": {}}
    for name, fn in TRACKS.items():
        if args.only and name not in args.only:
            continue
        out, sec, err = timed(fn)
        absent = err is not None and (err.startswith("ImportError") or err.startswith("ModuleNotFoundError")
                                      or err.startswith("AttributeError: module"))
        res["tracks"][name] = {"status": "absent" if absent else ("error" if err else "ok"), "sec": sec,
                               "result": out, **({"error": err} if err and not absent else {})}
        print(f"{name:14s} {res['tracks'][name]['status']:7s} {sec:6.1f}s  "
              f"{json.dumps(out, ensure_ascii=False)[:160] if out else (err or '')[:160]}", flush=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
