"""Посетители и их события: контекст устройства и сети, действия в выдаче, моторный профиль из игр.

Одна база SQLite (data/cache/visitors.sqlite, путь меняется переменной VISITORS_DB):
  visitors  — по одному на посетителя (vid из localStorage фронта): гео и сеть по IP, браузер, контекст браузера;
  events    — поиск, показ выдачи, открытие карточки, время просмотра, снятые условия, теневая перестановка;
  profiles  — снимки профиля из мини-игр (app/web/waitgames/sense.js).

Сырой IP не храним, даже в виде хэша: только то, что из него следует (страна, регион, город, тип сети).
Пишем только после согласия посетителя (sense.js), «Стереть мои данные» удаляет всё (forget).
Гео по IP: офлайн-базы db-ip lite (CC BY 4.0), скачиваются scripts/fetch_geoip.py; без них гео пустое.
Отпечатки браузера (canvas, WebGL, аудио) не собираем.
"""
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
DB_PATH = Path(os.getenv("VISITORS_DB") or CACHE / "visitors.sqlite")
GEO_DIR = Path(os.getenv("GEOIP_DIR") or CACHE / "geoip")
LEGACY_JSONL = CACHE / "sense.jsonl"

SCHEMA = """
CREATE TABLE IF NOT EXISTS visitors (
  vid TEXT PRIMARY KEY, first_seen REAL, last_seen REAL, visits INTEGER DEFAULT 1, synthetic INTEGER DEFAULT 0,
  country TEXT, region TEXT, city TEXT, tz_ip TEXT, asn INTEGER, asn_org TEXT, net TEXT,
  browser TEXT, os TEXT, device TEXT, model TEXT, lang TEXT, client TEXT);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, vid TEXT, at REAL, type TEXT, hotel_id TEXT, payload TEXT);
CREATE INDEX IF NOT EXISTS events_vid ON events(vid, type);
CREATE INDEX IF NOT EXISTS events_type ON events(type, at);
CREATE TABLE IF NOT EXISTS profiles (
  vid TEXT PRIMARY KEY, at REAL, profile TEXT);
"""
EVENT_TYPES = {"search", "serp", "open", "dwell", "relax", "verdict", "tab", "undo", "book"}
SERVER_TYPES = {"shadow", "serp_base"}   # пишет только сервер (app/taste.py): клиент не может подделать базу повтора
MAX_PAYLOAD = 4000

_lock = threading.Lock()
_conns: dict[str, sqlite3.Connection] = {}


def conn(path: Path | None = None) -> sqlite3.Connection:
    p = str(path or DB_PATH)
    c = _conns.get(p)
    if c is None:
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(p, check_same_thread=False, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=3000")
        c.executescript(SCHEMA)
        # базы первой версии хранили хэш IP: стираем его и соль
        if any(r[1] == "ip_hash" for r in c.execute("PRAGMA table_info(visitors)")):
            c.execute("UPDATE visitors SET ip_hash=NULL WHERE ip_hash IS NOT NULL")
        try:
            (CACHE / "visitors.salt").unlink()
        except OSError:
            pass
        c.row_factory = sqlite3.Row
        _conns[p] = c
    return c


def reset_connections():
    """Для тестов: следующий conn() откроет базу по текущему DB_PATH."""
    for c in _conns.values():
        c.close()
    _conns.clear()


# ---------- IP → гео и тип сети ----------

_readers: dict[str, object] = {}


def _reader(name: str):
    if name not in _readers:
        try:
            import maxminddb
            f = GEO_DIR / f"{name}.mmdb"
            _readers[name] = maxminddb.open_database(str(f)) if f.exists() else None
        except Exception:
            _readers[name] = None
    return _readers[name]


MOBILE_ASN = re.compile(r"mts|mobile telesystems|vimpelcom|beeline|megafon|tele2|t2 mobile|yota|scartel|"
                        r"\bmobile\b|wireless|cellular|vodafone|t-mobile|orange|kcell|beltelecom mobile|a1 ", re.I)
HOSTING_ASN = re.compile(r"hosting|cloud|data ?cent|datacenter|amazon|google|microsoft|digitalocean|hetzner|ovh|"
                         r"selectel|timeweb|linode|akamai|vultr|leaseweb|contabo|m247|choopa|yandex\.cloud|"
                         r"server|vpn|proxy|colo|yandex llc", re.I)
CORP_ASN = re.compile(r"bank|university|institute|government|ministry|corporat|gazprom|rzd|sber", re.I)


def net_type(org: str | None) -> str:
    """Грубый тип сети по владельцу ASN: мобильная, хостинг/VPN, организация или домашняя."""
    if not org:
        return "unknown"
    if HOSTING_ASN.search(org):
        return "hosting"
    if MOBILE_ASN.search(org):
        return "mobile"
    if CORP_ASN.search(org):
        return "corp"
    return "home"


def _private(ip: str) -> bool:
    return ip.startswith(("10.", "127.", "192.168.", "::1", "fc", "fd", "169.254.")) or \
        bool(re.match(r"172\.(1[6-9]|2\d|3[01])\.", ip))


def geo(ip: str | None) -> dict:
    out = {"country": None, "region": None, "city": None, "tz_ip": None, "asn": None, "asn_org": None, "net": "unknown"}
    if not ip or _private(ip):
        out["net"] = "local" if ip else "unknown"
        return out
    city = _reader("city")
    if city:
        try:
            r = city.get(ip) or {}
            out["country"] = (r.get("country") or {}).get("iso_code")
            subs = r.get("subdivisions") or []
            out["region"] = ((subs[0].get("names") or {}).get("en")) if subs else None
            out["city"] = ((r.get("city") or {}).get("names") or {}).get("en")
            out["tz_ip"] = (r.get("location") or {}).get("time_zone")
        except Exception:
            pass
    asn = _reader("asn")
    if asn:
        try:
            r = asn.get(ip) or {}
            out["asn"] = r.get("autonomous_system_number")
            out["asn_org"] = r.get("autonomous_system_organization")
            out["net"] = net_type(out["asn_org"])
        except Exception:
            pass
    return out


def client_ip(headers, peer: str | None) -> str | None:
    """Первый адрес из X-Forwarded-For (если за прокси), иначе адрес соединения."""
    xff = headers.get("x-forwarded-for") or headers.get("x-real-ip")
    if xff:
        return xff.split(",")[0].strip()
    return peer


# ---------- User-Agent и Client Hints ----------

def parse_ua(ua: str | None, hints: dict | None = None) -> dict:
    ua = ua or ""
    hints = hints or {}
    if re.search(r"YaBrowser", ua):
        browser = "Yandex"
    elif re.search(r"Edg/", ua):
        browser = "Edge"
    elif re.search(r"OPR/|Opera", ua):
        browser = "Opera"
    elif re.search(r"SamsungBrowser", ua):
        browser = "Samsung"
    elif re.search(r"Firefox/|FxiOS", ua):
        browser = "Firefox"
    elif re.search(r"Chrome/|CriOS", ua):
        browser = "Chrome"
    elif re.search(r"Safari/", ua):
        browser = "Safari"
    else:
        browser = "other"
    if re.search(r"iPhone|iPad|iPod", ua):
        os_ = "iOS"
    elif "Android" in ua:
        os_ = "Android"
    elif "Windows" in ua:
        os_ = "Windows"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        os_ = "macOS"
    elif "Linux" in ua:
        os_ = "Linux"
    else:
        os_ = "other"
    plat = (hints.get("sec-ch-ua-platform") or "").strip('"')
    if plat:
        os_ = {"macOS": "macOS", "Windows": "Windows", "Android": "Android", "iOS": "iOS", "Linux": "Linux"}.get(plat, os_)
    mobile_hint = hints.get("sec-ch-ua-mobile")
    if re.search(r"iPad|Tablet", ua) or ("Android" in ua and "Mobile" not in ua):
        device = "tablet"
    elif re.search(r"Mobi|iPhone|iPod", ua) or mobile_hint == "?1":
        device = "phone"
    elif re.search(r"bot|crawl|spider|HeadlessChrome", ua, re.I):
        device = "bot"
    else:
        device = "desktop"
    model = (hints.get("sec-ch-ua-model") or "").strip('"') or None
    return {"browser": browser, "os": os_, "device": device, "model": model}


# ---------- запись ----------

CLIENT_KEYS = ("tz", "tzOffset", "langs", "screen", "viewport", "dpr", "colorScheme", "reducedMotion", "effectiveType",
               "saveData", "deviceMemory", "cores", "touchPoints", "hour", "weekday", "referrer", "utm", "pointer")


def _clean_client(client: dict | None) -> dict:
    out = {}
    for k in CLIENT_KEYS:
        v = (client or {}).get(k)
        if v is None:
            continue
        if isinstance(v, str):
            v = v[:200]
        elif isinstance(v, (list, dict)):
            v = json.loads(json.dumps(v, ensure_ascii=False)[:400]) if len(json.dumps(v)) <= 400 else None
        if v is not None:
            out[k] = v
    if out.get("referrer"):   # только домен: путь может содержать личное
        m = re.match(r"https?://([^/]+)", str(out["referrer"]))
        out["referrer"] = m.group(1) if m else None
    return out


def upsert_visit(vid: str, ip: str | None, headers: dict, client: dict | None = None, synthetic: bool = False,
                 db: Path | None = None) -> dict:
    vid = (vid or "")[:64]
    if not vid:
        raise ValueError("нет vid")
    g = geo(ip)
    ua = parse_ua(headers.get("user-agent"), headers)
    lang = (headers.get("accept-language") or "").split(",")[0][:16] or None
    cl = _clean_client(client)
    t = time.time()
    row = {"vid": vid, **g, **ua, "lang": lang, "client": json.dumps(cl, ensure_ascii=False)}
    with _lock:
        c = conn(db)
        c.execute("""INSERT INTO visitors (vid, first_seen, last_seen, visits, synthetic, country, region, city, tz_ip,
                       asn, asn_org, net, browser, os, device, model, lang, client)
                     VALUES (:vid, :t, :t, 1, :syn, :country, :region, :city, :tz_ip, :asn, :asn_org, :net,
                       :browser, :os, :device, :model, :lang, :client)
                     ON CONFLICT(vid) DO UPDATE SET last_seen=:t, visits=visits+1,
                       country=COALESCE(:country, country), region=COALESCE(:region, region),
                       city=COALESCE(:city, city), tz_ip=COALESCE(:tz_ip, tz_ip), asn=COALESCE(:asn, asn),
                       asn_org=COALESCE(:asn_org, asn_org), net=:net, browser=:browser, os=:os, device=:device,
                       model=COALESCE(:model, model), lang=:lang, client=:client""",
                  {**row, "t": t, "syn": 1 if synthetic else 0})
    return {k: row[k] for k in ("country", "region", "city", "net", "browser", "os", "device")}


def log_events(vid: str, events: list[dict], db: Path | None = None, server: bool = False) -> int:
    """Пишет события только известного посетителя: без визита (нет согласия или он стёр данные) ничего не храним,
    в том числе запоздавшие события, отправленные до «Стереть мои данные»."""
    vid = (vid or "")[:64]
    if not conn(db).execute("SELECT 1 FROM visitors WHERE vid=?", (vid,)).fetchone():
        return 0
    rows = []
    for e in events[:50]:
        typ = str(e.get("type") or "")
        if typ not in EVENT_TYPES and not (server and typ in SERVER_TYPES):
            continue
        payload = json.dumps(e.get("data") or {}, ensure_ascii=False)
        if len(payload) > MAX_PAYLOAD:
            continue
        hid = e.get("hotel_id")
        rows.append((vid, float(e.get("at") or time.time()), typ, str(hid)[:64] if hid is not None else None, payload))
    if rows:
        with _lock:
            conn(db).executemany("INSERT INTO events (vid, at, type, hotel_id, payload) VALUES (?, ?, ?, ?, ?)", rows)
    return len(rows)


def save_profile(vid: str, profile: dict, db: Path | None = None):
    """Только для известного посетителя (дал согласие): без визита профиль игр к vid не привязываем."""
    if not conn(db).execute("SELECT 1 FROM visitors WHERE vid=?", ((vid or "")[:64],)).fetchone():
        return
    slim = {k: profile.get(k) for k in ("score", "confidence", "segment", "parts", "device", "hand", "patience", "signals")}
    with _lock:
        conn(db).execute("INSERT INTO profiles (vid, at, profile) VALUES (?, ?, ?) "
                         "ON CONFLICT(vid) DO UPDATE SET at=excluded.at, profile=excluded.profile",
                         ((vid or "")[:64], time.time(), json.dumps(slim, ensure_ascii=False)))


def forget(vid: str, db: Path | None = None):
    """Отказ от сбора: стираем всё о посетителе."""
    with _lock:
        c = conn(db)
        for t in ("visitors", "events", "profiles"):
            c.execute(f"DELETE FROM {t} WHERE vid=?", (vid,))


# ---------- чтение ----------

def visitor(vid: str, db: Path | None = None) -> dict | None:
    r = conn(db).execute("SELECT * FROM visitors WHERE vid=?", (vid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["client"] = json.loads(d["client"] or "{}")
    p = conn(db).execute("SELECT profile FROM profiles WHERE vid=?", (vid,)).fetchone()
    d["profile"] = json.loads(p["profile"]) if p else {}
    return d


def all_visitors(db: Path | None = None) -> list[dict]:
    c = conn(db)
    profs = {r["vid"]: json.loads(r["profile"]) for r in c.execute("SELECT vid, profile FROM profiles")}
    out = []
    for r in c.execute("SELECT * FROM visitors"):
        d = dict(r)
        d["client"] = json.loads(d["client"] or "{}")
        d["profile"] = profs.get(d["vid"], {})
        out.append(d)
    return out


def events_of(vid: str | None = None, types=None, db: Path | None = None) -> list[dict]:
    q, a = "SELECT * FROM events WHERE 1=1", []
    if vid:
        q += " AND vid=?"
        a.append(vid)
    if types:
        q += f" AND type IN ({','.join('?' * len(types))})"
        a += list(types)
    q += " ORDER BY at, id"
    return [{**dict(r), "data": json.loads(r["payload"] or "{}")} for r in conn(db).execute(q, a)]


def counts(db: Path | None = None) -> dict:
    c = conn(db)
    real = c.execute("SELECT COUNT(*) FROM visitors WHERE synthetic=0 AND device!='bot'").fetchone()[0]
    syn = c.execute("SELECT COUNT(*) FROM visitors WHERE synthetic=1").fetchone()[0]
    with_open = c.execute("""SELECT COUNT(DISTINCT e.vid) FROM events e JOIN visitors v ON v.vid=e.vid
                             WHERE e.type='open' AND v.synthetic=0 AND v.device!='bot'""").fetchone()[0]
    ev = {r[0]: r[1] for r in c.execute("SELECT type, COUNT(*) FROM events GROUP BY type")}
    return {"visitors_real": real, "visitors_synthetic": syn, "real_with_open": with_open, "events": ev}


def import_legacy_jsonl(path: Path = LEGACY_JSONL, db: Path | None = None) -> int:
    """Разовый перенос старого sense.jsonl: последний профиль на sid. Тестовый sid «t» пропускаем."""
    if not path.exists():
        return 0
    last = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("sid") and r["sid"] != "t":
            last[r["sid"]] = r
    for sid, r in last.items():
        save_profile("legacy-" + sid, r, db)
    return len(last)
