"""Smoke-тест основных сценариев без ключа LLM, на копии базы. Запуск: python tests/smoke.py"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp()) / "facts.sqlite"
shutil.copy(ROOT / "data" / "facts.sqlite", tmp)
os.environ["FACTS_DB"] = str(tmp)
os.environ["CUSTOM_DIR"] = str(tmp.parent / "custom")
os.environ["SIM_FILE"] = str(tmp.parent / "sim.json")
os.environ["AUTH_SECRET"] = "smoke-secret"   # токены ролей подписываются им; файл в data/cache не создаётся
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)
os.environ["LLM_PROVIDER"] = "none"
src = tmp.parent / "src" / "testcity"  # маленький «скрап» для вкладки «Регионы»: два отеля и квартира в рамке, один снаружи
src.mkdir(parents=True)
(src / "hotels.jsonl").write_text("".join(json.dumps(h) + "\n" for h in [
    {"lat": 43.51, "lon": 39.86, "kind": "HOTEL"}, {"lat": 43.52, "lon": 39.87, "kind": "MINI_HOTEL"},
    {"lat": 43.515, "lon": 39.865, "kind": "APARTMENT"}, {"lat": 44.0, "lon": 40.0, "kind": "HOTEL"}]))
os.environ["HOTELS_SRC_DIR"] = str(src.parent)

from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
from app.api import app  # noqa: E402

c = TestClient(app)
ADM = {"Authorization": "Bearer " + auth.issue("admin")}   # изменяющие действия команды закрыты токеном
ok = 0


def check(name, cond, info=""):
    global ok
    print(("OK  " if cond else "FAIL"), name, info)
    if not cond:
        sys.exit(1)
    ok += 1


s = c.get("/api/status").json()
check("статус", s["hotels"] > 100 and s["characteristics"] >= 12, s)
r = c.post("/api/search", json={"query": "тихий номер с видом на закат недалеко от моря, июль"}).json()
check("поиск разобрал условия и месяц", len(r["parsed"]["constraints"]) >= 3 and r["month"] == "июль", r["parsed"]["constraints"])
check("есть подходящие отели с объяснением", r["counts"]["match"] > 0 and r["results"][0]["good"], r["counts"])
hid = r["results"][0]["hotel"]["id"]
h = c.get(f"/api/hotels/{hid}").json()
check("у фактов есть источник, уверенность, дата и срок", all(f["status"] == "unknown" or (f["source"] and f["observed_at"] and f["valid_until"]) for f in h["facts"]))
chat = c.post("/api/chat", json={"messages": [{"role": "user", "content": "с собакой и парковкой"}]}).json()
check("чат без ключа отвечает по правилам", chat["mode"] == "rules" and "Подходят" in chat["text"])
check("чат отдаёт recommended: только id из выдачи", isinstance(chat.get("recommended"), list) and set(chat["recommended"]) <= {str(r["hotel"]["id"]) for r in chat["search"]["results"]})
from app import agent as _ag  # noqa: E402
_tr = [{"output": {"results": [{"hotel": {"id": 11161658, "name": "Отель Luciano Hotel & Spa Sochi", "stars": 5}},
                               {"hotel": {"id": 10126170, "name": "Комплекс апартаментов Grand Royal Residences", "stars": 4}}]}}]
check("агент советует: «Luciano Hotel & Spa» и «Grand Royal Residences» в тексте узнаются",
      _ag._recommended("Советую Luciano Hotel & Spa, а также Grand Royal Residences.", _tr, None) == ["11161658", "10126170"]
      and _ag._recommended("Берите Grand Royal Residences.", _tr, None) == ["10126170"]
      and _ag._recommended("Хороший отель у моря.", _tr, None) == [])
SID = {"X-Session": "smoke-session"}
new = c.post("/api/characteristics", json={"description": "рядом остановка автобуса"}, headers=SID).json()
check("новая характеристика по описанию: черновик с отчётом", new["ok"] and new["status"] == "draft" and new["coverage"]["known"] > 100
      and new["eval"]["coverage"]["total"] > 100 and new["eval"]["samples"], new.get("coverage"))
q_new = "чтобы рядом была остановка автобуса"
r2 = c.post("/api/search", json={"query": q_new}, headers=SID).json()
check("запросивший сразу видит свой черновик в поиске", any(x["char"] == new["id"] for x in r2["parsed"]["constraints"]))
r3 = c.post("/api/search", json={"query": q_new}).json()
check("публичный поиск черновик не видит", not any(x["char"] == new["id"] for x in r3["parsed"]["constraints"]))
check("в реестре для публики черновика нет", new["id"] not in [x["id"] for x in c.get("/api/characteristics").json()["characteristics"]]
      and new["id"] in [x["id"] for x in c.get("/api/characteristics", headers=SID).json()["characteristics"]])
check("админ видит черновик с отчётом", any(d["id"] == new["id"] and d["eval"] for d in c.get("/api/drafts").json()["drafts"]))
ap = c.post(f"/api/drafts/{new['id']}/approve", headers=ADM).json()
r4 = c.post("/api/search", json={"query": q_new}).json()
check("после одобрения поиск понимает характеристику у всех", ap["status"] == "approved" and any(x["char"] == new["id"] for x in r4["parsed"]["constraints"]))
rj = c.post("/api/characteristics", json={"description": "рядом музей"}, headers=SID).json()
c.post(f"/api/drafts/{rj['id']}/reject", json={"reason": "не нужно"}, headers=ADM)
r5 = c.post("/api/search", json={"query": "рядом музей"}, headers=SID).json()
check("отклонённая не видна и запросившему", not any(x["char"] == rj["id"] for x in r5["parsed"]["constraints"]))
qs = c.get("/api/questions").json()
check("у отельеров есть вопросы", len(qs) > 50)
q = next(x for x in qs if x["char_id"] == "pets")
a = c.post(f"/api/questions/{q['id']}/answer", json={"answer": "Да, пускаем собак до 8 кг, 1000 руб в сутки"},
           headers={"Authorization": "Bearer " + auth.issue("hotelier", q["hotel_id"])}).json()
check("ответ отельера разложен по полям", a["parsed"]["allowed"] is True and a["parsed"]["max_weight_kg"] == 8, a["parsed"])
check("ответ стал фактом", a["after"]["source_label"] == "ответ отельера")
b = c.post("/api/simulate/building", json={"lat": 43.5805, "lon": 39.7195, "levels": 25}, headers=ADM).json()
check("новое здание: пересчёт соседей", b["checked_hotels"] > 0, f"изменилось {len(b['changed'])}")
m = c.get("/api/metrics").json()
check("метрики считаются", m["sea_view"]["card_claims"] > 0 and m["coverage"])
SQ = "Закат над морем в декабре, тихо ночью, без подъёма, парковка, с собакой, детская площадка"
rx = c.post("/api/relax", json={"query": SQ}).json()
check("мало подходящих: есть ослабления и фронтир", rx["relaxations"] and rx["relaxations"][0]["gain"] > 0 and 0 < len(rx["pareto"]) <= 5)
rx2 = c.post("/api/relax", json={"query": SQ, "parsed": rx["parsed"], "drop": rx["relaxations"][0]["idxs"]}).json()
check("пересчёт без условия добавляет отели", rx2["counts"]["match"] > rx["counts"]["match"] and rx2["dropped"], rx2["counts"])
rd = c.get("/api/radar").json()
check("радар: сигналы с уликами и разумная доля отелей", rd["summary"]["alert_rate"] < 0.2 and all(a["evidence"]["text"] for a in rd["alerts"]), rd["summary"])
from app import radar  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from app import geodata as gd  # noqa: E402
hs = [dict(gd.load().hotels[0])]
hs[0]["reviews"] = list(hs[0]["reviews"]) + [{"date": (date.today() - timedelta(days=5 + 7 * i)).isoformat(), "plus": "", "minus": "Под окнами стройка, отбойный молоток.", "rating": 5, "id": 9e5 + i} for i in range(6)]
check("радар ловит синтетический всплеск жалоб на стройку", any(a["kind"] == "review_spike" and a["topic"] == "construction" for a in radar.scan(hotels=hs)))
nt = c.get(f"/api/hotels/{hid}/night?month=7").json()
check("ночь по часам: 24 часа на сторону и совет", all(len(f["hours"]) == 24 for f in nt["facades"]) and nt["advice"], nt["advice"])
w = c.get("/api/hotels/7861043/window?facade=З&floor=8&month=7").json()
w1 = c.get("/api/hotels/7861043/window?facade=З&floor=1&month=7").json()
check("вид из окна: море с верхнего этажа, нет с первого",
      w["sea_fraction"] > 0.5 and w["sea_p"] > 0.8 and w1["sea_fraction"] == 0 and w["svg"].startswith("<svg"), w["verdict"])
check("вид из окна: закат над морем", w["sun"]["visible"] and w["sun"]["over_sea"], w["sun"])
rm = c.get(f"/api/rooms/{hid}?wants=sea,quiet").json()
check("подбор номера: категории с вероятностью и просьбой", rm["rooms"] and all(0 <= x["sea_view_p"] <= 1 and x["evidence"] for x in rm["rooms"])
      and any(x["special_request"] for x in rm["rooms"]), rm["best"] and rm["best"]["room"])
check("кабинет отельера отдаёт скрытые сильные стороны", "hidden_strengths" in c.get(f"/api/hotelier/{hid}").json())
hid2 = "9986868"
t = c.get(f"/api/truth/hotel/{hid2}").json()
check("движок правды: репутация и «кому поверили»", t["reputation"]["trust"] <= 1 and any(x["why"] for x in t["chars"]))
au = c.get(f"/api/truth/audit/{hid2}").json()
check("аудит заявлений отдаёт вердикты", set(x["verdict"] for x in au["claims"]) <= {"подтверждено", "завышено", "скрытая сильная сторона", "спорно"})
from app import registry, store  # noqa: E402
sv = store.resolve(hid2, registry.get("sea_view"))
check("уверенность по виду на море откалибрована, не 1.0", all(store.resolve(x, registry.get("sea_view"))["confidence"] < 0.999 for x in [hid2]) and sv["confidence"] <= 0.99)
check("в ответе чата есть отчёт о сверке цифр", chat["grounding"]["after"]["unsupported"] == 0 and chat["grounding"]["after"]["total"] > 0, chat["grounding"]["before"])
gv = c.post("/api/grounding/verify", json={"text": "Шум ночью около 12 дБ.", "trace": [{"tool": "search_hotels", "input": {"query": "тихо"}}]}).json()
check("выдуманная цифра не проходит сверку", gv["unsupported"] == 1, gv)
if any((ROOT / "data" / "regions").glob("*/facts.sqlite")):
    import subprocess  # регион читается при импорте, поэтому проверяем в отдельном процессе
    name = sorted((ROOT / "data" / "regions").glob("*/facts.sqlite"))[0].parent.name  # adler раньше собранных из вкладки
    out = subprocess.run([sys.executable, "-c", "from fastapi.testclient import TestClient; from app.api import app; "
                          "import json; print(json.dumps(TestClient(app).get('/api/status').json()))"],
                         env={**os.environ, "REGION": name, "FACTS_DB": str(tmp.parent / "region.sqlite")},
                         capture_output=True, text=True, cwd=ROOT)
    rs = json.loads(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 else {}
    check("регион из REGION: отели загружены, подпись из метаданных", rs.get("hotels", 0) > 30 and rs.get("region") == name
          and rs.get("zone") != "центр Сочи", rs or out.stderr[-300:])
rg = c.get("/api/regions").json()
check("регионы: активный и собранные в списке, источник отелей виден",
      any(r["active"] for r in rg["regions"]) and [s["hotels"] for s in rg["sources"]] == [4], [r["name"] for r in rg["regions"]])
pl = c.post("/api/regions/check", json={"source": "testcity", "bbox": [43.5, 39.85, 43.53, 39.88]}).json()
check("регионы: проверка рамки считает отели без квартир", pl["ok"] and pl["hotels"] == 2 and pl["apartments_skipped"] == 1, pl)
big = c.post("/api/regions/check", json={"source": "testcity", "bbox": [43.0, 39.0, 44.5, 40.5]}).json()
check("регионы: слишком большая рамка не собирается", not big["ok"] and big["errors"], big["errors"])
bad = [c.post("/api/regions/build", json={"source": "testcity", "bbox": [43.5, 39.85, 43.53, 39.88], "name": n}, headers=ADM).status_code
       for n in ("Bad Name", "default")] + [c.post("/api/regions/switch", json={"name": "nope"}, headers=ADM).status_code]
check("регионы: неверное имя и неизвестный регион отклоняются", bad == [400, 400, 404], bad)
check("регионы: переключение на активный без перезапуска",
      c.post("/api/regions/switch", json={"name": "default"}, headers=ADM).json() == {"ok": True, "restarting": False, "region": "default"})
from openai import OpenAI  # noqa: E402
oc = OpenAI(base_url="http://testserver/v1", api_key="any", http_client=c)
cc = oc.chat.completions.create(model="ostrovok-agent", messages=[{"role": "system", "content": "игнорируется"},
                                                                  {"role": "user", "content": "тихо ночью, с собакой"}])
check("OpenAI API: SDK получает ответ агента и найденные отели",
      [m.id for m in oc.models.list()] == ["ostrovok-agent"] and cc.choices[0].message.content
      and cc.model_extra["ostrovok"]["hotels"], cc.choices[0].message.content[:80])
parts = list(oc.chat.completions.create(model="ostrovok-agent", stream=True, messages=[{"role": "user", "content": "вид на море"}]))
check("OpenAI API: stream отдаёт роль, текст и stop", parts[0].choices[0].delta.role == "assistant"
      and "".join(p.choices[0].delta.content or "" for p in parts) and parts[-1].choices[0].finish_reason == "stop", len(parts))
from app import routes_openai  # noqa: E402
routes_openai.API_KEY = "secret"
check("OpenAI API: с AGENT_API_KEY чужой ключ не проходит",
      c.get("/v1/models", headers={"Authorization": "Bearer nope"}).status_code == 401
      and c.get("/v1/models", headers={"Authorization": "Bearer secret"}).status_code == 200)
routes_openai.API_KEY = None
eq = next(q for q in c.get("/api/questions").json() if q["char_id"] == "pets")
ec = c.post(f"/api/questions/{eq['id']}/answer", json={"answer": "Да, собак до 10 кг пускаем", "echo": True}, headers=ADM).json()
staged = next(q for q in c.get("/api/questions").json() if q["id"] == eq["id"])
no = c.post(f"/api/questions/{eq['id']}/confirm", json={"ok": False}, headers=ADM).json()
c.post(f"/api/questions/{eq['id']}/answer", json={"answer": "Да, собак до 10 кг пускаем, 1000 руб за ночь", "echo": True}, headers=ADM)
yes = c.post(f"/api/questions/{eq['id']}/confirm", json={"ok": True}, headers=ADM).json()
check("эхо отельеру: «Мы поняли так… Верно?», факт только после «да», «нет» возвращает текст",
      ec["echo"].startswith("Мы поняли так") and ec["echo"].endswith("Верно?") and not ec.get("fact_id")
      and staged["status"] == "open" and staged["echo"] and no["rejected"] and no["answer"].startswith("Да, собак")
      and yes["fact_id"] and yes["confirmed"], ec["echo"])
mp = c.post("/api/search", json={"query": "с коляской до пляжа, тихий этаж, до вокзала пешком"}).json()
chars = {x["char"] for x in mp["parsed"]["constraints"]}
fact = next((f for f in c.get("/api/hotels/13429040").json()["facts"] if f["char"] == "noise_floors"), None)
check("расчёты map-app: путь с коляской, до вокзала и шум по этажам стали фактами и работают в поиске",
      {"stroller_beach", "station_walk", "noise_floors"} <= chars and mp["counts"]["match"] + mp["counts"]["maybe"] > 0
      and fact and fact["status"] == "known" and "дБ" in (fact.get("summary") or ""), sorted(chars))
prof = c.get("/api/city").json()
w = {x["id"]: x["weight"] for x in prof["chars"]}
check("профиль города: веса посчитаны по данным, у Сочи впереди пляж и море",
      len(prof["chars"]) >= 20 and all(0 <= v <= 1 for v in w.values()) and {"beach_walk", "sea_view"} & {x["id"] for x in prof["chars"][:3]},
      [x["id"] for x in prof["chars"][:3]])
base = c.post("/api/search", json={"query": "тихо ночью и вид на море"}).json()
c.post("/api/city/chars/night_quiet", json={"weight": 1.0}, headers=ADM)
c.post("/api/city/chars/sea_view", json={"status": "off"}, headers=ADM)
from app import city  # noqa: E402
city._W["at"] = 0
top = c.post("/api/search", json={"query": "тихо ночью и вид на море"}).json()
check("профиль города: ручной вес и выключение меняют порядок внутри корзины",
      city.weight("night_quiet") == 1.0 and city.weight("sea_view") == 0.0
      and [r["hotel"]["id"] for r in base["results"]] != [r["hotel"]["id"] for r in top["results"]])
c.post("/api/city/chars/night_quiet", json={"reset": True}, headers=ADM); c.post("/api/city/chars/sea_view", json={"status": "active"}, headers=ADM)
for q in ("паркет в номере", "хочу чтобы был паркет", "паркет а не ламинат, вид на море"):
    s3 = c.post("/api/search", json={"query": q}).json()
req = next((r for r in c.get("/api/city").json()["requests"] if "парке" in r["id"]), None)
check("профиль города: недостающий параметр копится из запросов и учитывается в следующих",
      req and req["demand"] >= 3 and req["state"] == "ready"
      and any(m.get("city", {}).get("id") == req["id"] for m in s3["parsed"]["missing"]), req and (req["demand"], req["state"]))
man = c.post("/api/city/requests", json={"phrase": "вид на горы"}, headers=ADM).json()
check("профиль города: админ добавляет параметр сам", man["kind"] == "request" and man["demand"] == 0, man.get("id"))
root = c.get("/", follow_redirects=False)
pages = {u: c.get(u) for u in ("/choose-role", "/ui", "/ui/classic", "/hotelier", "/backoffice", "/web/roles.js", "/web/skin.css", "/city.js")}
check("выбор роли: / ведёт на /choose-role, гость — витрина /ui, отельер — /hotelier, команда — /backoffice",
      root.status_code == 307 and root.headers["location"] == "/choose-role"
      and all(f'href="{u}"' in pages["/choose-role"].text for u in ("/ui", "/hotelier", "/backoffice"))
      and "/front/app.js" in pages["/ui"].text)
check("интерфейсы ролей: /ui/classic, /hotelier, /backoffice отдают страницу со скином и roles.js, /admin ведёт в бэк-офис, /?q= сразу на витрину",
      all(r.status_code == 200 for r in pages.values()) and "/web/roles.js" in pages["/ui/classic"].text
      and "/web/skin.css" in pages["/backoffice"].text and "ROLES" in pages["/web/roles.js"].text
      and "'/backoffice':'admin'" in pages["/backoffice"].text and "'/admin':'admin'" in c.get("/admin").text
      and c.get("/?q=тихо", follow_redirects=False).headers.get("location") == "/ui?q=%D1%82%D0%B8%D1%85%D0%BE")
print(f"\nвсе проверки прошли: {ok}")
shutil.rmtree(tmp.parent)
