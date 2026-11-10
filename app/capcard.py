"""Карточка возможностей для системного промпта агента: что считает каждая характеристика и каждый инструмент.
Собирается из реестра YAML и catalog.TOOLS, поэтому не расходится с кодом (деревья, шум днём, закат по месяцам и т.д.)."""
from app import registry
from app.tools import catalog


def _first(s, n=170):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def build():
    lines = ["Что система умеет считать (если характеристика есть здесь, она считается; не говори «не считается»,"
             " не проверив её через hotel_facts):"]
    for cid, s in registry.all_chars().items():
        fields = ", ".join(f"{k}" + (f" ({v['label']})" if v.get("label") else "") for k, v in s["fields"].items())
        method = "; ".join(_first(m.get("method", ""), 140) for m in s.get("methods", []) if m.get("method"))
        lines.append(f"- {cid} «{s['name']}»: поля {fields}. Метод: {method}")
    lines.append("Инструменты-примитивы (compute_tool):")
    for n, t in catalog.TOOLS.items():
        lines.append(f"- {n}: {_first(t['description'])}")
    return "\n".join(lines)


def constraints_schema(session=None):
    """Компактная схема для аргумента constraints инструмента search_hotels: характеристики, поля, типы, единицы
    (из реестра, поэтому не расходится с кодом)."""
    from app import search
    lines = []
    for cid, s in registry.public_chars(session).items():
        fs = []
        for k, v in s["fields"].items():
            t = {"bool": "bool", "number": "num", "enum": "enum", "text": "text"}.get(v["type"], v["type"])
            if v.get("values"):
                t += "=" + "|".join(v["values"])
            fs.append(f"{k}:{t} «{v.get('label', k)}»" + (" [по месяцам]" if v.get("per_month") else ""))
        lines.append(f"{cid}: " + "; ".join(fs))
    return ("\n\nСтруктурные условия. Если разобрал запрос гостя сам, передай constraints: список "
            "{char, field, op, value, must, phrase}; op из == != <= >= < >; must=true для требований, false для пожеланий; "
            "phrase кусок запроса гостя; month 1-12 если понятен; base {max_price, min_stars, min_rating} для бюджета, звёзд, "
            "рейтинга; missing [{phrase, proposal}] для нужд, которых нет в списке. " + search.THRESHOLDS +
            " Отрицание: bool-поле с value=false. Неизвестная характеристика или поле: условие отклоняется, поиск "
            "разбирает запрос заново. query передавай всегда, слова гостя без изменений. Характеристики и поля:\n" + "\n".join(lines))
