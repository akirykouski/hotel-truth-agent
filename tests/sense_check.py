"""Проверка политики выдачи по профилю устройства. Запуск: python tests/sense_check.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402
from app import sense  # noqa: E402
from app.api import app  # noqa: E402

fails = 0


def check(name, cond, info=""):
    global fails
    print(("OK  " if cond else "FAIL"), name, info)
    fails += 0 if cond else 1


R = [{"id": "a", "bucket": "maybe", "rating": 9.5, "reviews": 900, "good": 1, "bad": 0, "unknown": 2},
     {"id": "b", "bucket": "match", "rating": 7.0, "reviews": 5, "good": 3, "bad": 0, "unknown": 0},
     {"id": "c", "bucket": "match", "rating": 9.2, "reviews": 800, "good": 2, "bad": 0, "unknown": 1}]
careful = {"segment": "careful", "confidence": 0.6, "device": {"kind": "телефон"}, "hand": "левая"}
confident = {"segment": "confident", "confidence": 0.6}

o = sense.rerank(careful, R)["order"]
check("бережный: внутри «подходит» сначала проверенный отель", o[:2] == ["c", "b"], o)
check("корзины не смешиваются", o.index("a") > o.index("b"), o)
o = sense.rerank(confident, R)["order"]
check("уверенный: выше отель с большим числом подтверждённых условий", o[0] == "b", o)
check("мало данных: выдача без изменений",
      sense.rerank({"segment": "careful", "confidence": 0.05}, R)["order"] == ["b", "c", "a"])
check("отказ от подстройки уважается", sense.policy({**careful, "optOut": True})["segment"] == "unknown")
check("рука попадает в объяснение", any("левая" in r for r in sense.policy(careful)["reasons"]))

c = TestClient(app)
check("статика игр отдаётся", c.get("/waitgames/arcade.js").status_code == 200)
check("выход из папки игр закрыт", c.get("/waitgames/..%2F..%2Fapi.py").status_code == 404)
check("API профиля", c.post("/api/sense/profile", json={"sid": "t", "profile": careful}).json()["density"] == "comfy")
sys.exit(1 if fails else 0)
