"""Демо-состояние для жюри: два отельера уже ответили на вопросы (разбор правилами, без LLM), чтобы в кабинете и
в карточке отеля сразу было видно, как ответ становится фактом и как он спорит с расчётом и отзывами.
  python scripts/seed_demo.py   # после precompute.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import hotelier, registry, store  # noqa: E402

store.DB_PATH = store.SEED_PATH

ANSWERS = {
    "sea_view": "Делюксы с балконом смотрят на море, с 3-го по 9-й этаж. Стандарты выходят во двор, моря оттуда не видно.",
    "pets": "Да, принимаем собак и кошек до 10 кг, 1500 руб за ночь, нужен ветпаспорт.",
    "soundproofing": "Да, во всех номерах шумоизоляция и стеклопакеты, кроме стандартов на первом этаже.",
}


def main():
    done = set()
    for q in store.questions(status="open"):
        if q["char_id"] in ANSWERS and q["char_id"] not in done:
            r = hotelier.answer(q["id"], ANSWERS[q["char_id"]])
            print(q["hotel_id"], q["char_id"], "→", r["after"]["summary"] if r.get("after") else r["parsed"])
            done.add(q["char_id"])
    store.log_event("demo_seeded", payload={"answered": sorted(done)})


if __name__ == "__main__":
    main()
