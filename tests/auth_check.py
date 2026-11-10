"""Роли на сервере: гость, отельер своего отеля, админ. Журнал берёт «кто» из токена. Временная база, без LLM."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp()) / "facts.sqlite"
shutil.copy(ROOT / "data" / "facts.sqlite", tmp)
os.environ.update(FACTS_DB=str(tmp), CUSTOM_DIR=str(tmp.parent / "custom"), SIM_FILE=str(tmp.parent / "sim.json"),
                  AUTH_SECRET="auth-check-secret", LLM_PROVIDER="none", ADMIN_PASSWORD="demo", HOTELIER_DEMO_CODE="demo")
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, store  # noqa: E402
from app.api import app  # noqa: E402

c = TestClient(app)
fails = 0


def check(name, cond, info=""):
    global fails
    print(("OK  " if cond else "FAIL"), name, info)
    fails += 0 if cond else 1


def bearer(t):
    return {"Authorization": "Bearer " + t}


# ───── вход ─────
check("админ: неверный пароль 401", c.post("/api/auth/admin", json={"password": "x"}).status_code == 401)
ra = c.post("/api/auth/admin", json={"password": "demo"})
check("админ: демо-пароль даёт токен", ra.status_code == 200 and ra.json()["role"] == "admin")
ADM = bearer(ra.json()["token"])
qs = c.get("/api/questions").json()
qA = next(q for q in qs if q["char_id"] == "pets")
qB = next(q for q in qs if q["hotel_id"] != qA["hotel_id"] and q["char_id"] == "pets")
hA, hB = qA["hotel_id"], qB["hotel_id"]
check("отельер: неверный код 401, нет отеля 404", c.post("/api/auth/hotelier", json={"hotel_id": hA, "code": "no"}).status_code == 401
      and c.post("/api/auth/hotelier", json={"hotel_id": "nope", "code": "demo"}).status_code == 404)
HA = bearer(c.post("/api/auth/hotelier", json={"hotel_id": hA, "code": "demo"}).json()["token"])
check("/api/auth/me различает роли", c.get("/api/auth/me", headers=HA).json()["sub"] == f"hotelier:{hA}" and c.get("/api/auth/me").json()["role"] == "guest")

# ───── токен ─────
good = auth.issue("admin")
body = good.split(".")[1]
check("подделанный токен отвергнут", auth.verify(good[:-2] + "xx") is None and auth.verify(f"v1.{body}.") is None and auth.verify("мусор") is None)
check("просроченный токен отвергнут", auth.verify(auth.issue("admin", ttl=-5)) is None)
check("битый токен в заголовке даёт 401, не гостя", c.post("/api/drafts/x/approve", headers=bearer("bad")).status_code == 401)

# ───── черновики ─────
SID = {"X-Session": "auth-check"}
new = c.post("/api/characteristics", json={"description": "рядом остановка автобуса"}, headers=SID).json()
check("гость создаёт личный черновик (открыто по замыслу)", new.get("ok") and new["id"])
did = new["id"]
check("гость: approve 401", c.post(f"/api/drafts/{did}/approve").status_code == 401)
check("гость: reject 401, build 401", c.post(f"/api/drafts/{did}/reject").status_code == 401 and c.post("/api/drafts/build", json={"description": "x"}).status_code == 401)
check("отельер: approve 403", c.post(f"/api/drafts/{did}/approve", headers=HA).status_code == 403)
ap = c.post(f"/api/drafts/{did}/approve", json={"by": "Злоумышленник"}, headers=ADM)
check("админ: approve проходит", ap.status_code == 200 and ap.json()["status"] == "approved")
ev = next(e for e in store.events(50) if e["kind"] == "characteristic_approved" and e["char_id"] == did)
check("журнал: «кто» из токена, не из тела", ev["payload"]["by"] == "admin" and ap.json()["approved_by"] == "admin", ev["payload"])

# ───── ответы отельеров ─────
ans = {"answer": "Да, пускаем собак до 8 кг, 1000 руб в сутки"}
check("гость: ответ 401", c.post(f"/api/questions/{qA['id']}/answer", json=ans).status_code == 401)
check("отельер A: чужой вопрос (отель B) 403", c.post(f"/api/questions/{qB['id']}/answer", json=ans, headers=HA).status_code == 403)
check("вопрос B остался открытым", next(q for q in store.questions() if q["id"] == qB["id"])["status"] == "open")
check("несуществующий вопрос 404", c.post("/api/questions/99999999/answer", json=ans, headers=HA).status_code == 404)
ok = c.post(f"/api/questions/{qA['id']}/answer", json=ans, headers=HA)
check("отельер A: свой вопрос проходит", ok.status_code == 200 and ok.json()["after"]["source_label"] == "ответ отельера")
ev = next(e for e in store.events(50) if e["kind"] == "hotelier_answer" and e["hotel_id"] == hA)
check("журнал ответа: «кто» из токена", ev["payload"]["by"] == f"hotelier:{hA}", ev["payload"].get("by"))
okb = c.post(f"/api/questions/{qB['id']}/answer", json=ans, headers=ADM)
check("админ отвечает за любой отель", okb.status_code == 200)

# ───── эхо ответа: тот же доступ, что у ответа ─────
qC = next(q for q in c.get("/api/questions").json() if q["char_id"] == "pets" and q["hotel_id"] not in (hA, hB))
echo = {"answer": "Да, пускаем собак до 8 кг", "echo": True}
check("эхо и confirm: гость 401, отельер чужого отеля 403",
      all(getattr(c, "post")(u, json=b).status_code == 401 and c.post(u, json=b, headers=HA).status_code == 403
          for u, b in ((f"/api/questions/{qC['id']}/answer", echo), (f"/api/questions/{qC['id']}/confirm", {"ok": True}))))
c.post(f"/api/questions/{qC['id']}/answer", json=echo, headers=ADM)
cf = c.post(f"/api/questions/{qC['id']}/confirm", json={"ok": True}, headers=ADM)
ev = next(e for e in store.events(50) if e["kind"] == "hotelier_answer" and e["hotel_id"] == qC["hotel_id"])
check("confirm: «кто» из токена", cf.status_code == 200 and ev["payload"]["by"] == "admin", ev["payload"].get("by"))

# ───── прочие изменяющие действия ─────
closed = [("post", "/api/radar/apply", {}), ("post", "/api/regions/build", {"source": "s", "bbox": [1, 1, 2, 2], "name": "abc"}),
          ("post", "/api/regions/switch", {"name": "default"}), ("post", "/api/regions/jobs/x/cancel", {}),
          ("post", "/api/simulate/building", {"lat": 43.58, "lon": 39.72}), ("post", "/api/refresh/stale", None),
          ("post", "/api/taste/refit", None), ("post", "/api/taste/seed", {}), ("delete", "/api/taste/seed", None),
          ("post", "/api/city/recompute", {}), ("post", "/api/city/chars/sea_view", {"weight": 0.5}),
          ("post", "/api/city/requests", {"phrase": "тест"}), ("post", "/api/city/requests/x/build", {}),
          ("post", "/api/city/requests/x", {"status": "off"})]
for m, u, b in closed:
    kw = {"json": b} if b is not None else {}
    check(f"{m.upper()} {u}: гость 401, отельер 403", getattr(c, m)(u, **kw).status_code == 401 and getattr(c, m)(u, headers=HA, **kw).status_code == 403)

# ───── чтение и гостевые действия остаются открытыми ─────
check("чтение открыто", all(c.get(u).status_code == 200 for u in ("/api/status", "/api/hotels", "/api/questions", "/api/radar", "/api/drafts")))
check("гость может спросить отельера", c.post(f"/api/hotels/{hA}/ask", json={"char_id": "kids"}).status_code == 200)
sys.exit(1 if fails else 0)
