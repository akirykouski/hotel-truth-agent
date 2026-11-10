"""Пеший маршрут по реальным дорожкам OSM с учётом рельефа и переходов.

Граф: все пешеходные и автомобильные линии OSM, кроме магистралей без тротуаров. Узлы склеиваются по
координатам. Высота узла берётся из карты высот. Время по функции Тоблера: 6·e^(−3,5·|уклон + 0,05|) км/ч;
лестницы ещё в 1,5 раза медленнее. Поэтому путь туда и обратно занимает разное время.

Переходы на пути: через железную дорогу (по уровню, тоннелем, мостом) и через крупные дороги (primary,
secondary, trunk), где маршрут пересекает её, а не идёт вдоль.
"""
import heapq
import math
from functools import lru_cache

import networkx as nx
import numpy as np
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from app import geodata as gd

WALKABLE = {"footway", "path", "pedestrian", "steps", "residential", "living_street", "service", "unclassified",
            "tertiary", "tertiary_link", "secondary", "secondary_link", "primary", "primary_link", "track",
            "cycleway", "platform", "corridor"}
MAJOR = {"primary", "primary_link", "secondary", "secondary_link", "trunk", "trunk_link"}


def _key(lat, lon):
    return (round(lat, 7), round(lon, 7))


def tobler_kmh(slope):
    return 6.0 * math.exp(-3.5 * abs(slope + 0.05))


@lru_cache(maxsize=1)
def graph():
    geo = gd.load()
    G = nx.DiGraph()
    major_nodes, rail_lines, rail_nodes = {}, [], set()
    for e in geo.ways:
        t = e["tags"]
        g = e.get("geometry") or []
        if t.get("railway") in ("rail", "light_rail", "funicular") and len(g) > 1:
            x, y = gd.to_xy([p["lat"] for p in g], [p["lon"] for p in g])
            rail_lines.append(LineString(np.column_stack([x, y])))
            rail_nodes.update(_key(p["lat"], p["lon"]) for p in g)
        hw = t.get("highway")
        if hw in MAJOR:
            for p in g:
                major_nodes[_key(p["lat"], p["lon"])] = t.get("name") or hw
    for e in geo.ways:
        t = e["tags"]
        hw = t.get("highway")
        g = e.get("geometry") or []
        if hw not in WALKABLE or len(g) < 2 or t.get("foot") == "no" or t.get("access") == "private":
            continue
        keys = [_key(p["lat"], p["lon"]) for p in g]
        lats = np.array([p["lat"] for p in g])
        lons = np.array([p["lon"] for p in g])
        x, y = gd.to_xy(lats, lons)
        z = gd.ground(geo, lats, lons)
        for i in range(len(keys) - 1):
            a, b = keys[i], keys[i + 1]
            d = float(math.hypot(x[i + 1] - x[i], y[i + 1] - y[i]))
            if d < 0.5:
                continue
            for u, v, dz in ((a, b, float(z[i + 1] - z[i])), (b, a, float(z[i] - z[i + 1]))):
                slope = max(-0.5, min(0.5, dz / d))
                kmh = tobler_kmh(slope) / (1.5 if hw == "steps" else 1.0)
                G.add_edge(u, v, length=d, dz=dz, sec=d / (kmh / 3.6), hw=hw, name=t.get("name"),
                           tunnel=t.get("tunnel") not in (None, "no"), bridge=t.get("bridge") not in (None, "no"),
                           way=e["id"])
            G.nodes[a]["xy"] = (float(x[i]), float(y[i]))
            G.nodes[b]["xy"] = (float(x[i + 1]), float(y[i + 1]))
    # крупнейшая связная компонента
    comp = max(nx.weakly_connected_components(G), key=len)
    G = G.subgraph(comp).copy()
    nodes = list(G.nodes)
    xy = np.array([G.nodes[n]["xy"] for n in nodes])
    return G, nodes, xy, major_nodes, STRtree(rail_lines), rail_lines, rail_nodes


def nearest_node(x, y):
    G, nodes, xy, *_ = graph()
    i = int(np.argmin((xy[:, 0] - x) ** 2 + (xy[:, 1] - y) ** 2))
    return nodes[i], float(math.hypot(xy[i, 0] - x, xy[i, 1] - y))


@lru_cache(maxsize=64)
def _targets_for(kind):
    """Узлы графа у цели: у пляжей — в 30 м от контура пляжа."""
    geo = gd.load()
    G, nodes, xy, *_ = graph()
    out = {}
    if kind == "beach":
        for b in geo.beaches:
            poly = b["xy"]
            for i in range(len(poly) - 1):
                px, py = poly[i]
                d2 = (xy[:, 0] - px) ** 2 + (xy[:, 1] - py) ** 2
                for j in np.where(d2 < 30 ** 2)[0]:
                    out[nodes[j]] = b["name"] or "пляж"
    return out


def _dijkstra(G, src, targets, weight):
    dist, prev, seen = {src: 0.0}, {}, set()
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u in seen:
            continue
        seen.add(u)
        if u in targets:
            path = [u]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            return d, path[::-1]
        for v, attrs in G[u].items():
            nd = d + attrs[weight]
            if nd < dist.get(v, float("inf")):
                dist[v], prev[v] = nd, u
                heapq.heappush(pq, (nd, v))
    return None, None


def _crossings(G, path):
    _, _, _, major_nodes, rail_tree, rail_lines, rail_nodes = graph()
    out = []
    for i in range(1, len(path)):
        u, v = path[i - 1], path[i]
        e = G[u][v]
        if e["tunnel"] or e["bridge"]:
            seg = LineString([G.nodes[u]["xy"], G.nodes[v]["xy"]])
            if any(seg.intersects(rail_lines[j]) for j in rail_tree.query(seg)):
                out.append({"what": "железная дорога", "how": "тоннель" if e["tunnel"] else "мост"})
        if v in rail_nodes and i + 1 < len(path):
            out.append({"what": "железная дорога", "how": "переезд по уровню"})
        if v in major_nodes and i + 1 < len(path):
            nxt = G[v][path[i + 1]]
            if e["hw"] not in MAJOR and nxt["hw"] not in MAJOR:
                out.append({"what": f"дорога {major_nodes[v]}", "how": "наземный переход"})
    uniq = []
    for c in out:
        if not uniq or uniq[-1] != c:
            uniq.append(c)
    return uniq


def _climb(z, step=4.0):
    """Набор и сброс высоты с гистерезисом 4 м: мелкий шум карты высот не копится в «подъём»."""
    up = down = 0.0
    ref = z[0]
    for v in z[1:]:
        if v - ref >= step:
            up += v - ref
            ref = v
        elif ref - v >= step:
            down += ref - v
            ref = v
    return up, down


@lru_cache(maxsize=1024)
def route_to(hotel_id, kind="beach"):
    geo = gd.load()
    h = geo.hotel_by_id[hotel_id]
    G = graph()[0]
    src, snap = nearest_node(h["x"], h["y"])
    targets = _targets_for(kind)
    if not targets:
        return None
    sec, path = _dijkstra(G, src, set(targets), "sec")
    if path is None:
        return None
    return _summary(G, h, path, sec, snap, targets[path[-1]])


def _summary(G, h, path, sec, snap, target_name):
    length = sum(G[path[i]][path[i + 1]]["length"] for i in range(len(path) - 1))
    z = np.cumsum([0.0] + [G[path[i]][path[i + 1]]["dz"] for i in range(len(path) - 1)])
    up, down = _climb(z)
    back = sum(G[path[i + 1]][path[i]]["sec"] for i in range(len(path) - 1))
    steps = sum(G[path[i]][path[i + 1]]["length"] for i in range(len(path) - 1) if G[path[i]][path[i + 1]]["hw"] == "steps")
    straight = math.dist((h["x"], h["y"]), G.nodes[path[-1]]["xy"])
    pts = [gd.to_latlon(*G.nodes[n]["xy"]) for n in path[:: max(1, len(path) // 60)]] + [gd.to_latlon(*G.nodes[path[-1]]["xy"])]
    return {
        "target": target_name, "distance_m": round(length + snap), "straight_m": round(straight),
        "minutes_there": round((sec + snap / 1.3) / 60, 1), "minutes_back": round((back + snap / 1.3) / 60, 1),
        "climb_back_m": round(down), "climb_there_m": round(up), "steps_m": round(steps),
        "crossings": _crossings(G, path), "snap_m": round(snap),
        # во сколько раз путь длиннее прямой: > 3 — вероятно, закрытая территория или обрыв, путь сомнителен
        "detour": round((length + snap) / max(straight, 50), 1),
        "polyline": [[round(float(a), 6), round(float(b), 6)] for a, b in pts],
    }


@lru_cache(maxsize=256)
def _targets_tags(tags_items):
    """Узлы графа в 40 м от объектов OSM с нужными тегами."""
    from app.tools.places import match_tags
    geo = gd.load()
    G, nodes, xy, *_ = graph()
    want = dict(tags_items)
    out = {}
    for p in geo.pois:
        if not match_tags(p["tags"], want):
            continue
        d2 = (xy[:, 0] - p["x"]) ** 2 + (xy[:, 1] - p["y"]) ** 2
        j = int(np.argmin(d2))
        if d2[j] < 40 ** 2:
            out[nodes[j]] = p["tags"].get("name") or "/".join(f"{k}={v}" for k, v in want.items())
    return out


@lru_cache(maxsize=2048)
def route_to_tags(hotel_id, tags_items):
    geo = gd.load()
    h = geo.hotel_by_id[hotel_id]
    G = graph()[0]
    src, snap = nearest_node(h["x"], h["y"])
    targets = _targets_tags(tags_items)
    if not targets:
        return None
    sec, path = _dijkstra(G, src, set(targets), "sec")
    if path is None:
        return None
    return _summary(G, h, path, sec, snap, targets[path[-1]])
