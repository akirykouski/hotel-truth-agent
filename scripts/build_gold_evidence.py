"""Пакеты улик для слепой разметки «вид на море» (data/cache/eval_evidence/, в git не идёт).

На вход только id из data/eval/sea_view_sample.json. В пакет НЕ попадают результаты расчёта, уверенность,
страта и расстояние до берега: размечающий видит название, адрес, фото, категории номеров и фразы отзывов.
  python scripts/build_gold_evidence.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.label_photos import download  # noqa: E402

OUT = ROOT / "data" / "cache" / "eval_evidence"
KW = re.compile(r"вид[аеуо]?\b|видн|видел|мор[еяюь] (из|с |вид|за )|окн|окон|балкон|во двор|на двор|стен[уаы]|панорам|на этаж|\d[- ]?(й|м|го)? ?этаж|лоджи|террас", re.I)


def snippets(text, limit=3):
    out = []
    for s in re.split(r"(?<=[.!?\n])\s+", text or ""):
        if KW.search(s):
            out.append(s.strip()[:220])
        if len(out) >= limit:
            break
    return out


def main():
    ids = [s["id"] for s in json.loads((ROOT / "data/eval/sea_view_sample.json").read_text())["sample"]]
    hotels = {h["id"]: h for h in json.loads((ROOT / "data/hotels.json").read_text())["hotels"]}
    OUT.mkdir(parents=True, exist_ok=True)
    for hid in ids:
        h = hotels[hid]
        paths = [p for p in (download(u) for u in h["photos"]) if p]
        sheet = None
        if paths:
            sheet = OUT / f"{hid}.jpg"
            cmd = ["ffmpeg", "-y", "-loglevel", "error"]
            for p in paths:
                cmd += ["-i", str(p)]
            fc = "".join(f"[{i}:v]scale=640:400:force_original_aspect_ratio=decrease,pad=640:400:(ow-iw)/2:(oh-ih)/2[s{i}];"
                         for i in range(len(paths)))
            n = len(paths)
            if n == 1:
                fc += "[s0]copy[o]"
            elif n == 2:
                fc += "[s0][s1]hstack[o]"
            elif n == 3:
                fc += "[s0][s1]hstack[t];[s2]pad=1280:400:0:0[b];[t][b]vstack[o]"
            else:
                fc += "[s0][s1]hstack[t];[s2][s3]hstack[b];[t][b]vstack[o]"
            subprocess.run(cmd + ["-filter_complex", fc, "-map", "[o]", "-frames:v", "1", str(sheet)], check=True)
        L = [f"# {hid} {h['name']}", f"адрес: {h['address']}  звёзд: {h.get('stars')}", f"фото: {len(paths)} (лист: {sheet}); порядок слева-направо, сверху-вниз: " + ", ".join(p.name for p in paths)]
        L.append("описание: " + " | ".join(snippets(h.get("description"), 4)))
        L.append("категории номеров (с признаком вида):")
        names = sorted({r["name"] for r in h["rooms"]})
        view = [n for n in names if re.search(r"вид|мор|окн|балкон|террас|двор", n, re.I)]
        L.append(f"  всего {len(names)}; с видом/балконом: " + "; ".join(view[:14]))
        L.append("отзывы (id, номер, фрагменты про вид/окна/этаж):")
        k = 0
        for r in h["reviews"]:
            sn = snippets(r.get("plus"), 2) + [("(минус) " + s) for s in snippets(r.get("minus"), 2)]
            if sn:
                k += 1
                L.append(f"  [{r['id']}] {r.get('date')} номер «{r.get('room')}»: " + " / ".join(sn))
            if k >= 9:
                break
        L.append(f"отзывов всего {len(h['reviews'])}, с упоминаниями {k}")
        (OUT / f"{hid}.txt").write_text("\n".join(L), encoding="utf-8")
    print(len(ids), "packets ->", OUT)


if __name__ == "__main__":
    main()
