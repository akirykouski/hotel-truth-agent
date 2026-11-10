"""Скриншоты интерфейса для docs/shots: /ui/classic (прежняя страница гостя), /hotelier, /backoffice на десктопе (1440) и телефоне (390).

Снимает с запущенного сервера и ужимает до 256 цветов, чтобы репозиторий не пух. Выдача строится через /api/search,
то есть тем же поиском, что и в чате, но без LLM: так скриншоты одинаковые при каждом запуске, а пузыря с ответом
помощника на них нет.

    uvicorn app.api:app --port 8000
    uv run --no-project --with playwright --with pillow python scripts/shots.py [--base http://localhost:8000] [--only ui-home]
"""
import argparse
import asyncio
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
SEARCH = "тихий номер с видом на закат недалеко от моря, июль"
RELAX = "бассейн, с собакой, тихо ночью, до пляжа без подъёма, вид на закат, июль"
HOTEL = "7861043"      # Отель Империя: вид с запада с 3-го этажа, шумная сторона на восток
CABINET = "8307772"    # Гостевой Дом Просперус: отельер уже ответил про вид на море
COMPARE = ["7861043", "10003527", "9742403"]
SIZES = {"desktop": (1440, 900), "mobile": (390, 844)}


async def search(pg, query):
    await pg.evaluate("""async q => { oPlace(true); document.getElementById('q').value = q;
        history.push({role: 'user', content: q}); renderResults(await api('/api/search', {query: q, limit: 6})) }""", query)
    await pg.wait_for_timeout(3000)


async def hotel(pg, hid, wait=7000):
    await pg.evaluate("id => openHotel(id)", hid)
    await pg.wait_for_timeout(wait)


async def window_floor(pg, floor):
    """Вид из окна Империи: сторона З, заданный этаж; снимаем только блок."""
    await pg.click("#wv-fac button[data-d='З']")
    await pg.wait_for_timeout(800)
    await pg.evaluate("f => { const r = document.getElementById('wv-floor'); r.value = f; r.dispatchEvent(new Event('input')) }", floor)
    await pg.wait_for_timeout(1500)
    return pg.locator(".wv")


async def shot_window(pg, floor):
    await hotel(pg, HOTEL)
    return await window_floor(pg, floor)


async def shot_nightline(pg):
    await hotel(pg, HOTEL)
    return pg.locator(".nl")


# имя → (путь, действие, во весь рост). Действие может вернуть элемент: тогда снимается только он.
SHOTS = {
    "ui-home": ("/ui/classic", None, False),
    "ui-search": ("/ui/classic", lambda pg: search(pg, SEARCH), False),
    "ui-relax": ("/ui/classic", lambda pg: search(pg, RELAX), True),
    "ui-hotel-top": ("/ui/classic", lambda pg: hotel(pg, HOTEL), False),
    "ui-hotel": ("/ui/classic", lambda pg: hotel(pg, HOTEL), True),
    "ui-compare": ("/ui/classic", lambda pg: pg.evaluate("ids => { compareIds = ids; show('compare') }", COMPARE), True),
    "ui-criterion": ("/ui/classic", lambda pg: pg.evaluate("show('chars')"), False),
    "hotelier-pick": ("/hotelier", lambda pg: pg.evaluate("oChange()"), False),
    "hotelier-cabinet": ("/hotelier", lambda pg: pg.evaluate("id => openCabinet(id)", CABINET), True),
    "hotelier-audit": ("/hotelier", lambda pg: pg.evaluate("id => { openCabinet(id); show('audit') }", CABINET), True),
    "admin-overview": ("/backoffice", None, False),
    "admin-chars": ("/backoffice", lambda pg: pg.evaluate("show('chars')"), True),
    "admin-metrics": ("/backoffice", lambda pg: pg.evaluate("show('metrics')"), True),
    "admin-audit": ("/backoffice", lambda pg: pg.evaluate("show('audit')"), True),
    "admin-questions": ("/backoffice", lambda pg: pg.evaluate("show('hotelier')"), False),
    "admin-log": ("/backoffice", lambda pg: pg.evaluate("show('log')"), True),
    "admin-regions": ("/backoffice", lambda pg: pg.evaluate("show('regions')"), True),
    "window-low": ("/ui/classic", lambda pg: shot_window(pg, 1), False),
    "window-high": ("/ui/classic", lambda pg: shot_window(pg, 8), False),
    "nightline-imperia": ("/ui/classic", shot_nightline, False),
}


def shrink(path):
    # MEDIANCUT, а не FASTOCTREE: тот сливает фон #F4F4F4 с белыми карточками
    Image.open(path).convert("RGB").quantize(256, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--out", default=str(ROOT / "docs" / "shots"))
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for kind, (w, h) in SIZES.items():
            ctx = await browser.new_context(viewport={"width": w, "height": h}, locale="ru-RU", color_scheme="light")
            await ctx.add_init_script("try { localStorage.clear() } catch (e) {}")
            for name, (path, act, full) in SHOTS.items():
                if a.only and name not in a.only:
                    continue
                pg = await ctx.new_page()
                errors = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                await pg.goto(a.base + path)
                await pg.wait_for_timeout(2000)
                target = await act(pg) if act else None
                await pg.wait_for_timeout(1500)
                file = out / f"{name}-{kind}.png"
                if target is not None:
                    await target.screenshot(path=file)
                else:
                    await pg.evaluate("window.scrollTo(0, 0)")
                    await pg.screenshot(path=file, full_page=full)
                shrink(file)
                print(f"{file.relative_to(ROOT)}" + (f"  ошибки: {errors}" if errors else ""))
                await pg.close()
            await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
