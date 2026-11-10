"""Кластеры вкуса: ограничения, режимы и API на временной базе. Запуск: python tests/taste_check.py"""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="taste-"))
os.environ["VISITORS_DB"] = str(TMP / "v.sqlite")
os.environ["TASTE_MODEL"] = str(TMP / "m.json")
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ["TASTE_DEMO"] = "1"
os.environ["AUTH_SECRET"] = "taste-secret"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402
from app import taste, taste_synth, visitors  # noqa: E402
from app import auth  # noqa: E402
from app.api import app  # noqa: E402

fails = 0


def check(name, cond, info=""):
    global fails
    print(("OK  " if cond else "FAIL"), name, info)
    fails += 0 if cond else 1


H = taste.hotels()
ci = H["cols"].index("construction")
hid = next(h for h in H["ids"] if (taste.store.conn().execute(
    "SELECT value FROM facts WHERE hotel_id=? AND char_id='construction' AND active=1 LIMIT 1", (h,)).fetchone() or [""])[0].find('"none_near": true') >= 0)
check("полярность: «без стройки рядом» = 1, где none_near истинно", H["raw"][H["index"][hid], ci] == 1.0, hid)
base_chars = {p.stem for p in (Path(__file__).resolve().parent.parent / "registry").glob("*.yaml")}
check("каждый базовый признак есть в словаре причин", all(c in taste.REASON for c in H["cols"] if c in base_chars),
      [c for c in H["cols"] if c in base_chars and c not in taste.REASON])
check("признаки отелей собраны", len(H["ids"]) > 50 and len(H["cols"]) >= 10, (len(H["ids"]), len(H["cols"])))
check("UA: iPhone → телефон iOS Safari", visitors.parse_ua("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile/15E148 Safari/604.1")
      == {"browser": "Safari", "os": "iOS", "device": "phone", "model": None})
check("сеть: МТС мобильная, Hetzner хостинг", visitors.net_type("MTS PJSC") == "mobile" and visitors.net_type("Hetzner Online GmbH") == "hosting")
check("частный IP не уходит в гео", visitors.geo("192.168.1.5")["net"] == "local")

c = TestClient(app)
ADM = {"Authorization": "Bearer " + auth.issue("admin")}
r = c.post("/api/visit", json={"vid": "u1", "client": {"hour": 22, "referrer": "https://yandex.ru/search?text=секрет", "canvas": "x"}},
           headers={"user-agent": "Mozilla/5.0 (Linux; Android 14) Mobile Chrome/130", "x-forwarded-for": "8.8.8.8"})
v = visitors.visitor("u1")
check("визит сохранён", r.status_code == 200 and v and v["device"] == "phone" and v["os"] == "Android", r.json())
check("IP не хранится ни сырым, ни хэшем", "8.8.8.8" not in str(v) and "ip_hash" not in v)
check("из referrer только домен", v["client"].get("referrer") == "yandex.ru", v["client"])
check("лишние поля клиента отброшены", "canvas" not in v["client"])
c.post("/api/sense/profile", json={"sid": "s", "vid": "declined", "profile": {"segment": "careful", "confidence": 0.6}})
check("профиль игр без согласия к vid не привязывается", visitors.visitor("declined") is None and not visitors.conn().execute(
    "SELECT 1 FROM profiles WHERE vid='declined'").fetchone())
check("события без визита (нет согласия) не пишутся", visitors.log_events("nobody", [{"type": "open", "hotel_id": "1"}]) == 0)
check("клиент не может записать базу повтора", c.post("/api/events", json={"vid": "u1", "events": [
    {"type": "serp_base", "data": {"rows": []}}, {"type": "shadow", "data": {}}]}).json()["stored"] == 0)
check("события: чужие типы отбрасываются", c.post("/api/events", json={"vid": "u1", "events": [
    {"type": "open", "hotel_id": H["ids"][0]}, {"type": "drop table", "data": {}}]}).json()["stored"] == 1)

rows = [{"id": h, "bucket": b} for h, b in zip(H["ids"][:40], ["match"] * 15 + ["maybe"] * 25)]
os.environ["TASTE_MODE"] = "auto"
out = taste.apply("u1", rows)
check("без модели и данных: порядок не меняется", out["order"] == [r["id"] for r in rows] and not out["applied"], out.get("mode"))

taste_synth.generate(n=300, signal=0.8, seed=3)
gate = taste.refit()
check("синтетика не открывает порог", gate["passed"] is False and gate["real_with_open"] <= 1, gate["real_with_open"])
check("auto без порога = тень", taste.mode() == "shadow")
syn = "syn-3-1"
out = taste.apply(syn, rows)
check("тень: показанный порядок не меняется", out["order"] == [r["id"] for r in rows] and out["mode"] == "shadow")
check("тень без модели на реальных данных ничего не делает", out.get("cluster") is None and not out["applied"])

out = taste.apply(syn, rows, demo=True)
o = out["order"]
check("демо переставляет", out["mode"] == "demo" and out["applied"], out.get("note"))
check("корзины не смешиваются", set(o[:15]) == {r["id"] for r in rows[:15]})
check("состав выдачи тот же", sorted(o) == sorted(r["id"] for r in rows))
check("причина видна", bool(out.get("note")) and out["note"].startswith("Выше отели ") and "похожие посетители" in out["note"], out.get("note"))
check("отказ от подстройки уважается", taste.apply(syn, rows, demo=True, opt_out=True)["order"] == [r["id"] for r in rows])
os.environ["TASTE_MODE"] = "off"
check("TASTE_MODE=off выключает всё", taste.apply(syn, rows, demo=True)["order"] == [r["id"] for r in rows])
os.environ["TASTE_MODE"] = "auto"

res = [{"id": r["id"], "bucket": r["bucket"], "rating": 9, "reviews": 10, "good": 1, "bad": 0, "unknown": 0} for r in rows]
j = c.post("/api/sense/rerank", json={"vid": syn, "demo": True, "profile": {"segment": "unknown", "confidence": 0}, "results": res}).json()
check("API rerank: демо помечено на штампе", j["taste"]["mode"] == "demo" and j["rub"] == "Демо: синтетические посетители", j.get("rub"))
j = c.post("/api/sense/rerank", json={"vid": "nobody", "profile": {"segment": "unknown"}, "results": res}).json()
check("API rerank: незнакомый посетитель не ломает выдачу", j["order"] == [r["id"] for r in rows])
st = c.get("/api/taste/status").json()
check("статус: режим, счётчики, кластеры", st["mode"] == "shadow" and st["counts"]["visitors_synthetic"] == 300 and st["clusters"], st["mode"])
c.post("/api/visit/forget", json={"vid": "u1", "client": {}})
check("забыть посетителя", visitors.visitor("u1") is None and not visitors.events_of("u1"))
check("стереть синтетику", c.delete("/api/taste/seed", headers=ADM).json()["removed"] == 300 and visitors.counts()["visitors_synthetic"] == 0)


def as_real(n, signal, seed):
    """Синтетика, переписанная как «реальная», только во временной базе теста: проверяем сам порог."""
    db = TMP / f"gate-{signal}.sqlite"
    taste_synth.generate(n=n, signal=signal, seed=seed, db=db)
    visitors.conn(db).execute("UPDATE visitors SET synthetic=0")
    return db


db0 = as_real(400, 0.0, 21)
g0 = taste.refit(db=db0)
check("контроль: без сигнала в контексте кластер не помогает новичкам, λ_cold = 0", g0["lmax_cold"] == 0.0,
      {k: g0["replay_cold"].get(k) for k in ("gain", "ci_low", "best_tried_lmax")})
check("повтор для посетителей с историей посчитан отдельно", g0["replay"] is not None and "lmax" in g0["replay"],
      {k: g0["replay"].get(k) for k in ("lmax", "gain", "ci_low")})
db9 = as_real(400, 0.9, 22)
g9 = taste.refit(db=db9)
check("порог: с сигналом включается, λ_cold из повтора", g9["passed"] and g9["lmax_cold"] > 0 and taste.mode() == "on",
      {k: g9["replay_cold"].get(k) for k in ("lmax", "gain", "ci_low")})
treated = next(f"syn-22-{i}" for i in range(400) if taste._fold(f"syn-22-{i}", taste.HOLDOUT_K) != 0)
held = next(f"syn-22-{i}" for i in range(400) if taste._fold(f"syn-22-{i}", taste.HOLDOUT_K) == 0)
o9 = taste.apply(treated, rows, db=db9)
check("после порога перестановка идёт без demo", o9["mode"] == "on" and o9["applied"], o9.get("lambda"))
check("после порога пишется исходный порядок для повтора", any(e["type"] == "serp_base" for e in visitors.events_of(treated, db=db9)))
oh = taste.apply(held, rows, db=db9)
check("контрольная группа без буста", oh["mode"] == "holdout" and oh["order"] == [r["id"] for r in rows])
q = [e for e in visitors.events_of(treated, ("search",), db=db9)][-1]["data"]["chars"]
names = [taste.REASON[c] for c in q if c in taste.REASON]
check("причина не повторяет запрос", o9.get("note") is None or not any(n in o9["note"] for n in names), (q, o9.get("note")))
os.environ["TASTE_DEMO"] = "0"
check("без токена переобучение и засев закрыты (401)", c.post("/api/taste/refit").status_code == 401 and c.post("/api/taste/seed", json={}).status_code == 401
      and c.delete("/api/taste/seed").status_code == 401)
check("без демо и с админом переобучение и засев закрыты", c.post("/api/taste/refit", headers=ADM).status_code == 403 and c.post("/api/taste/seed", json={}, headers=ADM).status_code == 403)
check("без демо ?cluster=1 ничего не делает", not taste.apply(treated, rows, demo=True, db=db9).get("mode") == "demo")
os.environ["TASTE_DEMO"] = "1"
os.environ["TASTE_MODE"] = "shadow"
o9 = taste.apply("syn-22-7", rows, db=db9)
check("тень на реальных данных: показан исходный порядок, в лог пишутся оба", o9["order"] == [r["id"] for r in rows] and any(
    e["type"] == "shadow" and e["data"]["shown"] != e["data"]["taste"] for e in visitors.events_of("syn-22-7", db=db9)))
os.environ["TASTE_MODE"] = "auto"
sys.exit(1 if fails else 0)
