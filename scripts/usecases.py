"""Прогон пользовательских сценариев через чат-агента (как если бы писал гость) → docs/usecases_run.md.
Каждый сценарий — диалог из 1–2 реплик. Пишет в отдельную копию базы, демо-база не меняется.
  python scripts/usecases.py            # все
  python scripts/usecases.py 3 5        # выбранные по номерам
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
shutil.copy(ROOT / "data" / "facts.sqlite", tmp / "facts.sqlite")
os.environ.update(FACTS_DB=str(tmp / "facts.sqlite"), CUSTOM_DIR=str(tmp / "custom"), SIM_FILE=str(tmp / "sim.json"))

from app import agent, llm  # noqa: E402

CASES = [
    ("Флагманский запрос из ТЗ", ["Тихий номер с видом на закат недалеко от моря, едем в июле"]),
    ("Пожилой человек", ["Еду с мамой, ей тяжело ходить в гору. Нужно близко к пляжу и чтобы из окна было видно море"]),
    ("Семья с собакой", ["Мы с ребёнком 3 лет и собакой 12 кг. Нужна детская площадка рядом и чтобы пускали с собакой"]),
    ("Удалёнщик", ["Работаю удалённо две недели в ноябре: нужно тихо днём, хороший интернет и чтобы рядом можно было поесть"]),
    ("Ночной прилёт", ["Прилетаем в 2 ночи. Важно, чтобы рядом была круглосуточная аптека и где-то поесть"]),
    ("Вопрос про конкретный отель", ["В Cosmos Сочи Отель будет слышно поезда ночью? И далеко ли там до моря?"]),
    ("Закат зимой с этажа", ["Хочу смотреть, как солнце садится в море, в конце декабря. Какие отели и с какого этажа?"]),
    ("Сравнение", ["Сравни AZIMUT Парк Отель Виноградная и Отель Грейс Горизонт по виду на море, тишине и пути до пляжа"]),
    ("Нет характеристики → собрать", ["Нужен отель рядом с аквапарком", "Да, собери эту характеристику и поищи ещё раз"]),
    ("Погода", ["Можно ли ещё купаться в Сочи в начале ноября?"]),
    ("Негатив: чтобы НЕ было", ["Чтобы рядом не было стройки и баров под окнами, и не надо было переходить железную дорогу к морю"]),
    ("Только отельер знает", ["Есть ли в Отель Лофт плотные шторы блэкаут? Мне важно спать днём"]),
]


def main():
    pick = {int(x) for x in sys.argv[1:]}
    out = [f"# Прогон пользовательских сценариев\n\nПровайдер: {llm.PROVIDER} ({llm.MODEL}), {time.strftime('%Y-%m-%d %H:%M')}\n"]
    for i, (title, turns) in enumerate(CASES, 1):
        if pick and i not in pick:
            continue
        msgs, t0 = [], time.time()
        out.append(f"\n## {i}. {title}\n")
        for u in turns:
            msgs.append({"role": "user", "content": u})
            try:
                r = agent.chat(msgs)
            except Exception as e:
                r = {"text": f"ОШИБКА: {e}", "trace": [], "mode": "error"}
            msgs.append({"role": "assistant", "content": r["text"]})
            tools = " → ".join(t["tool"] + (f"({json.dumps(t['input'], ensure_ascii=False)[:120]})" if t.get("input") else "") for t in r["trace"])
            out.append(f"**Гость:** {u}\n\n*инструменты:* {tools or '—'}\n\n**Ответ** ({r['mode']}):\n\n{r['text']}\n")
        out.append(f"*{time.time() - t0:.0f} с*\n")
        print(f"{i}. {title}: {time.time() - t0:.0f} с", flush=True)
        (ROOT / "docs" / "usecases_run.md").write_text("\n".join(out), encoding="utf-8")
    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
