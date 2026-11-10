"""Окно с видом: панорама из выбранной стороны здания и этажа, закат выбранного месяца.

Те же лучи, что в view.py (карта высот Copernicus + здания OSM + деревья из DSM + Монте-Карло по неточным
высотам), но с шагом 1° внутри веера ±70° от нормали стены и из точки на стене: центр здания сдвинут к стене на
половину глубины корпуса. Для каждого азимута считаем самый высокий угол препятствия отдельно для зданий,
деревьев и рельефа, видно ли море и какой полосой. Из этого рисуется панорама 140° × 30° с угловыми осями,
солнцем на дуге последних 90 минут до заката и мягкой полосой разброса по Монте-Карло.

`sea_p` берётся из расчёта по фасаду (view.compute, p_sea_by_floor): одно число и для кнопок сторон, и для подписи.
Панорама остаётся иллюстрацией номинального прогона; если она расходится с этим числом, под ней стоит пояснение.
"""
import math
import zlib
from functools import lru_cache

import numpy as np

from app import geodata as gd
from app.tools import view
from app.tools.sun import MONTHS_RU, sun_path, sunset_azimuth

REL = np.arange(-view.FAN, view.FAN + 1, 1.0)     # азимут луча относительно нормали стены, шаг 1°
OFFK = 0.5                                        # доля половины глубины корпуса: глаз у стены, но не дальше, чем считает sea_view
MAX_OFFSET_M = 40                                 # дальше 40 м от центра к стене глаз не двигаем (сложные контуры)
SUN_SPAN_MIN = 90
V_TOP, V_BOT = 20.0, -10.0                        # вертикальный диапазон панорамы, градусы над горизонтом
MONTH_IN = {1: "январе", 2: "феврале", 3: "марте", 4: "апреле", 5: "мае", 6: "июне", 7: "июле", 8: "августе",
            9: "сентябре", 10: "октябре", 11: "ноябре", 12: "декабре"}
BLOCK = {"building": "закрывают здания", "tree": "закрывают деревья", "terrain": "закрывает рельеф"}
DIR_WORD = {"С": "север", "СВ": "северо-восток", "В": "восток", "ЮВ": "юго-восток", "Ю": "юг", "ЮЗ": "юго-запад",
            "З": "запад", "СЗ": "северо-запад"}   # куда смотрят окна: «окна на юго-восток»
NEG = np.float32(-np.inf)
SHOW_MAX = 0.99   # 100% наружу не отдаём: расчёт вероятностный


def _shown(p):
    return min(SHOW_MAX, float(p))


def floor_label(floor, levels):
    """«5-й этаж», на верхнем этаже здания «последний (9-й) этаж»."""
    return f"последний ({levels}-й) этаж" if levels and floor >= levels and levels > 1 else f"{floor}-й этаж"


def floor_at(floor, levels):
    """«на 5-м этаже», на верхнем: «на последнем (9-м) этаже»."""
    return f"на последнем ({levels}-м) этаже" if levels and floor >= levels and levels > 1 else f"на {floor}-м этаже"


def _angdiff(a, b):
    return abs((a - b + 540) % 360 - 180)


def _facade_list(hotel_id):
    """Стороны здания по порядку: сначала с морем (раньше этаж), потом по размеру видимого моря сверху."""
    v = view.compute(hotel_id)
    sun_az = sunset_azimuth(7)

    def key(f):
        if f["sea_from_floor"]:
            return (0, f["sea_from_floor"], -f["confidence"], 0)
        return (1, -f["sea_deg_top_floor"], _angdiff(f["az"], sun_az), 0)
    return v, sorted(v["facades"], key=key)


@lru_cache(maxsize=96)
def _rays(hotel_id, dir_):
    """Лучи веера одной стороны из точки на стене: рельеф, здания, деревья, море по каждому лучу."""
    geo = gd.load()
    b, how, g0, *_ = view._profile(hotel_id)
    bid, _ = gd.hotel_building(hotel_id)
    facs = view._facades(b)
    i = next(k for k, f in enumerate(facs) if f["dir"] == dir_)
    az0 = float(facs[i]["az"])
    h = geo.hotel_by_id[hotel_id]
    cx, cy = (float(b.xy[:, 0].mean()), float(b.xy[:, 1].mean())) if b is not None else (h["x"], h["y"])
    off = 0.0
    if b is not None and "length_m" in facs[i]:
        off = min(OFFK * facs[(i + 1) % 4]["length_m"] / 2, MAX_OFFSET_M)   # половина глубины корпуса вдоль нормали
        cx += off * math.sin(math.radians(az0))
        cy += off * math.cos(math.radians(az0))
    az = (az0 + REL) % 360
    rad = np.radians(az)[:, None]
    X = cx + view.DIST[None, :] * np.sin(rad)
    Y = cy + view.DIST[None, :] * np.cos(rad)
    lat, lon = gd.to_latlon(X, Y)
    r, c, ok = gd.dem_index(geo, lat, lon)
    ground = np.where(ok, geo.dem_dtm[r, c], 0.0).astype(np.float32)
    extra = np.where(ok, geo.dem_extra[r, c], 0.0).astype(np.float32)
    extra[:, view.DIST < 30] = 0.0
    sea = np.where(ok, geo.dem_sea[r, c], False)
    gr = ((Y - geo.grid_y0) // gd.CELL).astype(int)
    gc = ((X - geo.grid_x0) // gd.CELL).astype(int)
    inside = (gr >= 0) & (gr < geo.grid_bid.shape[0]) & (gc >= 0) & (gc < geo.grid_bid.shape[1])
    bids = np.where(inside, geo.grid_bid[np.clip(gr, 0, geo.grid_bid.shape[0] - 1),
                                         np.clip(gc, 0, geo.grid_bid.shape[1] - 1)], -1)
    if bid >= 0:
        bids[bids == bid] = -1
    sea &= bids < 0
    extra[bids >= 0] = 0.0
    extra[sea] = 0.0
    return {"az0": az0, "az": az, "ground": ground, "sea": sea, "bids": bids, "extra": extra, "g0": float(g0),
            "offset_m": round(off)}


def _trace(R, heights, veg, eye, detail=False):
    """Один прогон: видно ли море по каждому лучу и угол препятствия перед морем. С detail ещё углы по видам."""
    ground, sea, bids, extra = R["ground"], R["sea"], R["bids"], R["extra"]
    dist = view.DIST[None, :]
    isb = bids >= 0
    bh = np.where(isb, heights[np.clip(bids, 0, None)], 0.0)
    base = ground - view.CURV[None, :] - eye
    t_b = (base + bh) / dist
    t_t = (base + extra * veg) / dist
    t = np.maximum(t_b, t_t)
    prev = np.maximum.accumulate(t, axis=1)
    prev = np.concatenate([np.full((t.shape[0], 1), -np.inf, dtype=np.float32), prev[:, :-1]], axis=1)
    tsea = (-view.CURV[None, :] - eye) / dist
    vis = sea & (tsea > prev)
    seen = vis.any(axis=1)
    top = t.max(axis=1)
    has = sea.any(axis=1)
    fs = sea.argmax(axis=1)
    rows = np.arange(len(t))
    pre = prev[rows, fs]
    block = np.where(has, np.where(np.isfinite(pre), pre, tsea[0, fs]), top)
    out = {"sea": seen, "block": np.degrees(np.arctan(block)), "top": np.degrees(np.arctan(top))}
    if detail:
        ang = np.degrees(np.arctan(tsea[0]))
        out["lo"] = np.where(vis, ang[None, :], np.inf).min(axis=1)
        out["hi"] = np.where(vis, ang[None, :], -np.inf).max(axis=1)
        deg = lambda a: np.degrees(np.arctan(a))     # noqa: E731
        out["building"] = deg(np.where(isb, t_b, NEG).max(axis=1))
        out["tree"] = deg(np.where(extra > 0, t_t, NEG).max(axis=1))
        out["terrain"] = deg((base / dist).max(axis=1))
    return out


def _mc(hotel_id, R, eye, runs=view.MC_RUNS):
    """Прогоны Монте-Карло с теми же случайными высотами, что в view.compute (одно зерно на отель)."""
    geo = gd.load()
    rng = np.random.default_rng(int(hotel_id) % 2**32)
    res = []
    for k in range(runs):
        if k == 0:
            hts, veg = geo.b_heights, view.VEG_NOMINAL
        else:
            hts = np.maximum(geo.b_heights + geo.b_sigma * rng.standard_normal(len(geo.b_heights)).astype(np.float32), 2.0)
            veg = float(rng.uniform(0.4, 1.0))
        res.append(_trace(R, hts, veg, eye, detail=(k == 0)))
    return res


def _kind(d):
    names = ("building", "tree", "terrain")
    vals = np.stack([d[n] for n in names])
    return [names[i] for i in vals.argmax(axis=0)]


def _sun(az0, az_arr, obst, month, sea_ray):
    """Солнце в последние 90 минут до заката: где его видно из окна и садится ли оно над морем."""
    pts = []
    for mins, saz, salt in sun_path(month, SUN_SPAN_MIN, 5):
        rel = (saz - az0 + 540) % 360 - 180
        inside = abs(rel) <= view.FAN
        vis = bool(inside and salt > float(np.interp(rel, REL, obst)) and salt > -0.01)
        pts.append({"min": mins, "az": saz, "alt": salt, "rel": rel, "inside": inside, "visible": vis})
    seen = [p for p in pts if p["visible"]]
    ref = seen[-1] if seen else pts[-1]
    rel_set = ref["rel"]
    j = int(np.clip(round(rel_set + view.FAN), 0, len(REL) - 1))
    over_sea = bool(seen and sea_ray[max(0, j - 2): j + 3].any())
    return pts, ref, {"az": round(ref["az"]), "alt": round(ref["alt"], 1), "visible": bool(seen),
                      "over_sea": over_sea, "visible_min": 5 * len(seen) if seen else 0,
                      "sunset_az": round(pts[-1]["az"]), "month": month}


# ---------------------------------------------------------------- рисунок

K = 1000 / (2 * view.FAN)         # пикселей на градус (по обеим осям)
W = 1000
H = (V_TOP - V_BOT) * K
AXIS = 52


def _x(rel):
    return (rel + view.FAN) * K


def _y(a):
    return min(max((V_TOP - a) * K, 0), H)


def _f(v):
    return f"{v:.1f}"


def _layer(rel, top, floor_, step):
    """Заливка между верхним и нижним краем по подряд идущим азимутам; step=True даёт ступеньки, как у домов."""
    parts, i, n = [], 0, len(rel)
    draw = floor_ < top - 0.05
    while i < n:
        if not draw[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and draw[j + 1]:
            j += 1
        up, dn = [], []
        for k in range(i, j + 1):
            x0, x1 = _x(rel[k] - 0.5), _x(rel[k] + 0.5)
            if step:
                up += [(x0, _y(top[k])), (x1, _y(top[k]))]
                dn += [(x1, _y(floor_[k])), (x0, _y(floor_[k]))]
            else:
                up.append(((x0 + x1) / 2, _y(top[k])))
                dn.append(((x0 + x1) / 2, _y(floor_[k])))
        pts = up + dn[::-1]
        parts.append("M" + " L".join(f"{_f(max(0, min(W, x)))},{_f(y)}" for x, y in pts) + "Z")
        i = j + 1
    return " ".join(parts)


def _sea_label(rel, sea, lo, hi):
    """Подпись «море» на самой широкой полосе видимого моря; если моря меньше 3% ширины, рамка и стрелка к нему."""
    n = len(rel)
    best, i = None, 0
    while i < n:
        if not sea[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and sea[j + 1]:
            j += 1
        if best is None or j - i > best[1] - best[0]:
            best = (i, j)
        i = j + 1
    if best is None:
        return ""
    a, b = best
    cx = (_x(rel[a] - 0.5) + _x(rel[b] + 0.5)) / 2
    wpx = _x(rel[b] + 0.5) - _x(rel[a] - 0.5)
    ymid = _y((float(np.mean(lo[a:b + 1])) + float(np.mean(hi[a:b + 1]))) / 2)
    area = float(np.sum((hi - lo)[sea])) / (n * (V_TOP - V_BOT))     # доля кадра, занятая видимым морем
    tiny = sea.sum() / n < 0.03 or area < 0.02
    if wpx >= 90 and not tiny:
        lx = min(max(cx, 50), W - 50)
        return f'<text x="{_f(lx)}" y="{_f(ymid + 12)}" class="lb sh" style="font-size:34px" text-anchor="middle">море</text>'
    # узкая полоса: рамка вокруг неё и подпись со стрелкой сверху
    pad = 16
    x0, x1 = _x(rel[a] - 0.5) - pad, _x(rel[b] + 0.5) + pad
    ry0, ry1 = ymid - 22, ymid + 22
    lx = min(max(cx, 40), W - 40)
    ty = max(44, ry0 - 50)
    return (f'<rect x="{_f(x0)}" y="{_f(ry0)}" width="{_f(x1 - x0)}" height="{_f(ry1 - ry0)}" rx="10" fill="none" '
            f'stroke="#fff" stroke-width="3" stroke-dasharray="6 4"/>'
            f'<path d="M{_f(lx)},{_f(ty + 8)} L{_f(cx)},{_f(ry0 - 3)}" stroke="#fff" stroke-width="3" fill="none"/>'
            f'<text x="{_f(lx)}" y="{_f(ty)}" class="lb sh" style="font-size:34px" text-anchor="middle">море</text>')


def _svg(R, pan, band, floor, dir_, month, sea_p, sun_pts, ref, sun, levels=None):
    """Возвращает (заголовок, вердикт-плашка, svg): плашки на узком экране рисуем HTML над картинкой."""
    uid = "w%x" % zlib.crc32(f"{dir_}{floor}{month}{R['az0']}{R['g0']}".encode())
    rel = REL
    top_b, top_t, top_g = (np.array([p[k] for p in pan]) for k in ("building_deg", "tree_deg", "terrain_deg"))
    sea = np.array([p["sea"] for p in pan])
    lo = np.array([p["sea_lo"] if p["sea"] else 0.0 for p in pan])
    hi = np.array([p["sea_hi"] if p["sea"] else 0.0 for p in pan])
    bottom = np.full(len(rel), V_BOT - 1)

    def floor_for(top):
        # слой выше моря (дальний берег, горы) рисуем только над полосой моря, ближний слой ниже неё — до низа кадра
        return np.where(sea & (top > lo), hi, bottom)

    sea_poly = _layer(rel, np.where(sea, hi, -99), np.where(sea, lo, -99), False)
    shore = _layer(rel, np.where(sea, lo, -99), bottom, True)
    mount = _layer(rel, top_g, floor_for(top_g), False)
    trees = _layer(rel, top_t, floor_for(top_t), True)
    houses = _layer(rel, top_b, floor_for(top_b), True)

    # мягкая полоса разброса: между 10-м и 90-м процентилем препятствия перед морем по прогонам
    bl, bh = band
    wide = (bh - bl > 0.4) & (bh < V_TOP - 2) & (bh - bl < 6)
    band_poly = _layer(rel, np.where(wide, bh, -99), np.where(wide, bl, -99), False)

    hx = _x(0)  # центр кадра = нормаль стены
    sx = [(_x(p["rel"]), _y(max(p["alt"], 0))) for p in sun_pts if p["inside"]]
    path = "M" + " L".join(f"{_f(x)},{_f(y)}" for x, y in sx) if len(sx) > 1 else ""
    rx, ry = _x(ref["rel"]), _y(max(ref["alt"], 0))
    ghosts, ghost_lb = "", ""
    for p in sun_pts:
        if p["min"] in (60, 30) and p["inside"]:
            gx, gy = _x(p["rel"]), _y(max(p["alt"], 0))
            left = gx > W / 2         # подпись со стороны, где в кадре больше места
            ghosts += (f'<circle cx="{_f(gx)}" cy="{_f(gy)}" r="13" fill="none" stroke="#fff3cf" stroke-opacity=".8" '
                       f'stroke-dasharray="3 3"/>')
            # подпись рисуем поверх домов и деревьев, иначе слой препятствий оставляет от неё один символ
            ghost_lb += (f'<text x="{_f(gx - 18 if left else gx + 18)}" y="{_f(gy + 6)}" '
                         f'class="lb sm sh gl" style="font-size:21px" text-anchor="{"end" if left else "start"}">за {p["min"]} мин до заката</text>')
    glow_x = _x((sun_pts[-1]["rel"])) if sun_pts[-1]["inside"] else None
    glow = (f'<circle cx="{_f(glow_x)}" cy="{_f(_y(0))}" r="300" fill="url(#{uid}g)"/>' if glow_x is not None else "")
    sun_svg = ""
    if sun["visible"] or ref["inside"]:
        sun_svg = (f'<circle cx="{_f(rx)}" cy="{_f(ry)}" r="34" fill="#ffd27a" opacity=".28"/>'
                   f'<circle cx="{_f(rx)}" cy="{_f(ry)}" r="17" fill="url(#{uid}s)"/>')

    # блики солнца на море
    glitter = ""
    if glow_x is not None and sea.any():
        for k in range(9):
            gy = _y(-0.6 - k * 0.9)
            gw = 18 + k * 12
            glitter += (f'<rect x="{_f(glow_x - gw / 2)}" y="{_f(gy)}" width="{gw}" height="2.2" rx="1.1" '
                        f'fill="#ffe9b0" opacity="{0.75 - k * 0.07:.2f}"/>')

    # окна в силуэтах домов: детерминированно, чтобы картинка не прыгала между запросами
    lights = ""
    for i, a in enumerate(top_b):
        if a > V_BOT + 1.5 and (not sea[i] or a > hi[i]) and a > -4 and ((i * 2654435761 + floor) >> 3) % 3 == 0:
            y0 = _y(a) + 12 + ((i * 7) % 4) * 11
            if y0 < H - 8:
                lights += f'<rect x="{_f(_x(rel[i]) + 1.8)}" y="{_f(y0)}" width="3.2" height="4.6" fill="#ffd98a" opacity=".75"/>'

    # компас
    ticks = ""
    a0 = R["az0"]
    # подписей сторон света не больше трёх, ближайших к центру кадра: на телефоне больше не помещается читаемо
    big_az = sorted((az for az in range(int(math.ceil(a0 - view.FAN)), int(math.floor(a0 + view.FAN)) + 1) if az % 45 == 0),
                    key=lambda az: abs(az - a0))[:3]
    for az in range(int(math.ceil(a0 - view.FAN)), int(math.floor(a0 + view.FAN)) + 1):
        if az % 5:
            continue
        x = _x(az - a0)
        big = az % 45 == 0
        mid = az % 15 == 0
        ticks += f'<line x1="{_f(x)}" y1="{_f(H)}" x2="{_f(x)}" y2="{_f(H + (26 if big else 14 if mid else 8))}" stroke="#aeb7d6" stroke-width="{2 if big else 1}"/>'
        if big and az in big_az:
            anc = "start" if x < 40 else "end" if x > W - 40 else "middle"
            ticks += f'<text x="{_f(min(max(x, 4), W - 4))}" y="{_f(H + 46)}" class="cp" text-anchor="{anc}">{DIR_WORD[gd.dir_name(az % 360)]}</text>'

    sea_lb = _sea_label(rel, sea, lo, hi)
    pct = round(_shown(sea_p) * 100)
    where = f"окна на {DIR_WORD[dir_]}, {floor_label(floor, levels)}"
    verdict = f"море из окна: шанс {pct}% ({where})" if pct else f"моря из окна не видно ({where})"
    short = f"море из окна: шанс {pct}%" if pct else "моря из окна не видно"
    pill = lambda x, y, w, text: (   # noqa: E731
        f'<g class="pill"><rect x="{x}" y="{y}" width="{w}" height="34" rx="17" fill="#0b1026" opacity=".55"/>'
        f'<text x="{x + w / 2}" y="{y + 23}" class="lb sm" text-anchor="middle">{text}</text></g>')
    head = f"{floor_label(floor, levels)} · окна на {DIR_WORD[dir_]} · {MONTHS_RU[month]}"
    pw1 = 17 * len(head) * 0.6 + 36
    pw2 = 17 * len(short) * 0.6 + 36

    return head, verdict, (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="wsvg" viewBox="0 0 {W} {_f(H + AXIS)}" preserveAspectRatio="xMidYMid slice" role="img" '
        f'aria-label="Вид из окна: {head}, {verdict}" style="width:100%;height:auto;display:block;border-radius:12px">'
        f'<defs><linearGradient id="{uid}k" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="{_f(_y(0))}">'
        '<stop offset="0" stop-color="#17214a"/><stop offset=".38" stop-color="#4a3a7e"/><stop offset=".66" stop-color="#c25a7c"/>'
        '<stop offset=".88" stop-color="#f79b58"/><stop offset="1" stop-color="#ffd48c"/></linearGradient>'
        f'<linearGradient id="{uid}m" gradientUnits="userSpaceOnUse" x1="0" y1="{_f(_y(0))}" x2="0" y2="{_f(H)}">'
        '<stop offset="0" stop-color="#4a8be0"/><stop offset=".35" stop-color="#3f7fd6"/>'
        '<stop offset="1" stop-color="#2d63b4"/></linearGradient>'
        f'<radialGradient id="{uid}g"><stop offset="0" stop-color="#fff0c4" stop-opacity=".85"/>'
        '<stop offset=".35" stop-color="#ffb26b" stop-opacity=".45"/><stop offset="1" stop-color="#ff8a5c" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="{uid}t" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="{_f(H)}">'
        '<stop offset="0" stop-color="#37604a"/><stop offset=".5" stop-color="#27483d"/><stop offset="1" stop-color="#1b3430"/></linearGradient>'
        f'<radialGradient id="{uid}s"><stop offset="0" stop-color="#fffbe8"/><stop offset="1" stop-color="#ffb347"/></radialGradient>'
        f'<filter id="{uid}b" x="-5%" y="-30%" width="110%" height="160%"><feGaussianBlur stdDeviation="5"/></filter>'
        f'<clipPath id="{uid}c"><rect width="{W}" height="{_f(H)}" rx="12"/></clipPath></defs>'
        '<style>.sh{paint-order:stroke;stroke:#2b2150;stroke-width:4px;stroke-opacity:.55}.lb{font:600 22px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;fill:#fff}.sm{font-size:17px;font-weight:500}'
        '.cp{font:700 27px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;fill:#e9edff}</style>'
        f'<rect width="{W}" height="{_f(H + AXIS)}" rx="12" fill="#0f1530"/>'
        f'<g clip-path="url(#{uid}c)">'
        f'<rect width="{W}" height="{_f(H)}" fill="#2a2740"/>'
        f'<rect width="{W}" height="{_f(_y(0))}" fill="url(#{uid}k)"/>'
        f'{glow}'
        f'<path d="{path}" fill="none" stroke="#fff3cf" stroke-opacity=".6" stroke-width="2" stroke-dasharray="4 5"/>{ghosts}{sun_svg}'
        f'<path d="{sea_poly}" fill="url(#{uid}m)" stroke="#2b66c0" stroke-width="1.5"/>{glitter}'
        f'<path d="{shore}" fill="#2a2740"/>'
        f'<path d="{mount}" fill="#6a5a8c" opacity=".92"/>'
        f'<path d="{trees}" fill="url(#{uid}t)"/>'
        f'<path d="{houses}" fill="#1c1f33" stroke="#3b4066" stroke-width="1"/>{lights}'
        f'<path d="{band_poly}" fill="#fff6dc" opacity=".42" filter="url(#{uid}b)"/>'
        f'{ghost_lb}{sea_lb}'
        f'{pill(14, 14, pw1, head)}{pill(W - 14 - pw2, 14, pw2, short)}'
        '</g>'
        f'<line x1="0" y1="{_f(H)}" x2="{W}" y2="{_f(H)}" stroke="#aeb7d6" stroke-opacity=".5"/>{ticks}'
        '</svg>')


# ---------------------------------------------------------------- расчёт

def _verdict(floor, dir_, month, sea_p, sun, pan, az0, levels=None):
    fl = floor_label(floor, levels)
    head = f"{fl[0].upper() + fl[1:]}, окна на {DIR_WORD[dir_]}:"
    pct = round(_shown(sea_p) * 100)
    parts = []
    if sea_p >= 0.75:
        parts.append(f"море, скорее всего, видно (шанс {pct}%)")
    elif round(sea_p, 2) == 0.5:
        parts.append("море видно или нет: 50 на 50")
    elif sea_p > 0.5:
        parts.append(f"море скорее видно (шанс {pct}%)")
    elif sea_p > 0:
        parts.append(f"море скорее не видно, только краешек (шанс {pct}%)")
    else:
        mid = [p for p in pan if abs(p["az"] - az0) <= 35 or abs(p["az"] - az0) >= 325]
        kinds = [p["kind"] for p in mid]
        main = max(set(kinds), key=kinds.count) if kinds else "building"
        parts.append(f"моря не видно, {BLOCK[main]}")
    if sun["visible"] and sun["over_sea"]:
        parts.append(f"закат над морем в {MONTH_IN[month]}")
    elif sun["visible"]:
        parts.append(f"закат в {MONTH_IN[month]} виден над городом")
    else:
        # чем закрыт закат: вид препятствия на азимуте солнца
        rel = (sun["sunset_az"] - az0 + 540) % 360 - 180
        if abs(rel) > view.FAN:
            parts.append(f"закат в {MONTH_IN[month]} не попадает в окно этой стороны")
        else:
            k = pan[int(np.clip(round(rel + view.FAN), 0, len(pan) - 1))]["kind"]
            parts.append(f"закат в {MONTH_IN[month]} {BLOCK[k]}")
    return f"{head} " + "; ".join(parts) + "."


@lru_cache(maxsize=512)
def _render(hotel_id, dir_, floor, month):
    geo = gd.load()
    levels = view.compute(hotel_id)["building"]["levels"]
    R = _rays(hotel_id, dir_)
    eye = R["g0"] + (floor - 1) * gd.FLOOR_M + 1.5
    runs = _mc(hotel_id, R, eye)
    nom = runs[0]
    kinds = _kind(nom)
    sea_runs = np.array([r["sea"] for r in runs])
    ok = sea_runs.sum(axis=1) >= view.SEA_MIN_DEG
    pan_nominal = bool(ok[0])          # что показывает рисунок
    fac = next(f for f in view.compute(hotel_id)["facades"] if f["dir"] == dir_)
    sea_p = float(fac["p_sea_by_floor"][floor])     # то же число, что в расчёте по фасаду и в факте sea_view
    mismatch = pan_nominal != (sea_p >= 0.5)
    note = (f"Рисунок схематичный: по расчёту для этой стороны и этажа море видно с вероятностью {round(_shown(sea_p) * 100)}%."
            if mismatch else None)
    sea_fraction = float(nom["sea"].mean())
    blocks = np.array([r["block"] for r in runs])
    band = (np.percentile(blocks, 10, axis=0), np.percentile(blocks, 90, axis=0))

    pan = []
    for i, a in enumerate(R["az"]):
        s = bool(nom["sea"][i])
        pan.append({"az": round(float(a), 1), "obstruction_deg": round(float(nom["top"][i]), 2), "kind": kinds[i],
                    "sea": s, "sea_lo": round(float(nom["lo"][i]), 2) if s else None,
                    "sea_hi": round(float(nom["hi"][i]), 2) if s else None,
                    "building_deg": round(float(nom["building"][i]), 2), "tree_deg": round(float(nom["tree"][i]), 2),
                    "terrain_deg": round(float(nom["terrain"][i]), 2),
                    "sea_p": round(_shown(sea_runs[:, i].mean()), 2)})
    obst = np.array([p["obstruction_deg"] for p in pan])
    sun_pts, ref, sun = _sun(R["az0"], R["az"], obst, month, nom["sea"])
    head, chip, svg = _svg(R, pan, band, floor, dir_, month, sea_p, sun_pts, ref, sun, levels)
    return {"facade": dir_, "floor": floor, "month": month, "az": round(R["az0"]), "eye_height_m": round((floor - 1) * gd.FLOOR_M + 1.5, 1),
            "sea_fraction": round(sea_fraction, 3), "sea_p": round(_shown(sea_p), 2), "sea_pan_nominal": pan_nominal,
            "sun": sun, "panorama": pan, "svg": svg, "chips": [head, chip], "note": note,
            "verdict": _verdict(floor, dir_, month, sea_p, sun, pan, R["az0"], levels),
            "eye_offset_m": R["offset_m"]}


def render(hotel_id, facade=None, floor=None, month=7):
    """Вид из окна: {facade, floor, sea_fraction, sea_p, sun{az, alt, visible, over_sea}, panorama[], svg, verdict, ...}."""
    v, facs = _facade_list(hotel_id)
    month = int(month)
    if month not in MONTHS_RU:
        raise ValueError("месяц от 1 до 12")
    dirs = [f["dir"] for f in facs]
    if facade is None:
        facade = dirs[0]
    elif facade not in dirs:
        raise ValueError(f"нет стороны {facade}, есть: {', '.join(dirs)}")
    levels = v["building"]["levels"]
    floor = levels if floor is None else int(min(max(int(floor), 1), levels))
    out = dict(_render(hotel_id, facade, floor, month))
    out["levels"] = levels
    out["facades"] = [{"dir": f["dir"], "name": DIR_WORD[f["dir"]], "az": f["az"], "sea_from_floor": f["sea_from_floor"],
                       "confidence": round(_shown(f["confidence"]), 2)} for f in facs]
    return out
