"""Записывает демо-ролик (~3 мин) прототипа «О!Правда об отеле»: Playwright + запись видео, затем ffmpeg в H.264 MP4.

Сценарий (то, о чём просило жюри): запрос путешественника, три варианта, одна неожиданная деталь с доказательством,
одно спорное заявление, уточнение отельера, новая характеристика, одобренная админом.

    # сервер на ОДНОРАЗОВОЙ копии базы: ролик пишет в неё ответы отельера и одобряет черновик
    cp data/facts.sqlite /tmp/v.sqlite
    mkdir -p /tmp/custom && cp registry/custom/*.yaml /tmp/custom/   # одобренный черновик пишется в CUSTOM_DIR, не в репозиторий
    LLM_PROVIDER=none FACTS_DB=/tmp/v.sqlite CUSTOM_DIR=/tmp/custom .venv/bin/uvicorn app.api:app --port 8050
    python scripts/record_demo.py --base http://localhost:8050 --out docs/demo.mp4

Нужны playwright (chromium) и ffmpeg. Подписи внизу экрана рисуются DOM-оверлеем и переживают переходы между страницами.
Запускайте на свежей копии базы: повторный прогон на той же копии увидит уже одобренную характеристику.
"""
import argparse
import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
QUERY = "тихий номер с видом на закат недалеко от моря, июль"
ANSWER = "делюксы смотрят на море с 5 по 9 этаж, стандарты во двор"
HOTELIER_HOTEL = "Гостевой Дом Акс"   # в «Проверке обещаний» он обещает «3 категории с видом на море», а расчёт моря не видит
NEW_CHAR = "в отеле есть бассейн"
W, H = 1440, 900

CAPTION_JS = """
(() => {
  const mk = () => {
    if (document.getElementById('__cap')) return;
    const d = document.createElement('div'); d.id = '__cap';
    d.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;padding:16px 32px;background:rgba(8,12,24,.82);' +
      'color:#fff;font:600 22px/1.3 -apple-system,"Segoe UI",Roboto,Arial,sans-serif;text-align:center;pointer-events:none;letter-spacing:.1px';
    let t = ''; try { t = sessionStorage.getItem('__cap') || '' } catch (e) {}
    d.textContent = t; d.style.display = t ? 'block' : 'none';
    (document.body || document.documentElement).appendChild(d);
  };
  if (document.body) mk(); else document.addEventListener('DOMContentLoaded', mk);
  window.__setCap = t => { try { sessionStorage.setItem('__cap', t) } catch (e) {}
    mk(); const d = document.getElementById('__cap'); d.textContent = t; d.style.display = t ? 'block' : 'none'; };
})();
"""

SCROLL_JS = """([sel, y, ms]) => new Promise(res => {
  const el = sel ? document.querySelector(sel) : null;
  const get = () => el ? el.scrollTop : window.scrollY;
  const set = v => el ? (el.scrollTop = v) : window.scrollTo(0, v);
  const root = el || document.documentElement; root.style.scrollBehavior = 'auto'; document.body.style.scrollBehavior = 'auto';
  const a = get(), t0 = performance.now();
  const ease = p => p < .5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  const step = now => { const p = Math.min(1, (now - t0) / ms); set(a + (y - a) * ease(p)); p < 1 ? requestAnimationFrame(step) : res(); };
  requestAnimationFrame(step);
})"""


async def cap(pg, text):
    await pg.evaluate("t => window.__setCap(t)", text)


async def hold(pg, sec):
    await pg.wait_for_timeout(int(sec * 1000))


async def scroll(pg, y, ms=1400, sel=None):
    """Плавная прокрутка окна (или элемента sel) к y."""
    await pg.evaluate(SCROLL_JS, [sel, y, ms])


async def scroll_to_el(pg, selector, offset=90, ms=1400, sel=None, nth=0):
    y = await pg.evaluate("""([s, off, host, n]) => { const e = document.querySelectorAll(s)[n]; if (!e) return null;
        const h = host ? document.querySelector(host) : null;
        const top = e.getBoundingClientRect().top - (h ? h.getBoundingClientRect().top : 0) + (h ? h.scrollTop : window.scrollY);
        return Math.max(0, top - off) }""", [selector, offset, sel, nth])
    if y is not None:
        await scroll(pg, y, ms, sel)


async def dismiss_consent(pg):
    try:
        await pg.get_by_role("button", name="Не надо").first.click(timeout=2500)
    except Exception:
        pass


async def search(pg, text, delay=70):
    await pg.click("#hsi")
    await pg.keyboard.type(text, delay=delay)
    await hold(pg, 0.6)
    await pg.keyboard.press("Enter")
    await pg.wait_for_selector("#results:not([hidden])", timeout=20000)
    await hold(pg, 1.5)


async def fresh_home(pg, base):
    await pg.goto(base + "/")
    await pg.wait_for_selector("#hsi")
    await hold(pg, 1.0)
    await dismiss_consent(pg)


async def login_modal(pg, secs=2.5):
    """Показываем форму входа (демо-значение подставлено), жмём «Войти»."""
    btn = pg.locator("button:visible", has_text="Войти").last
    await btn.wait_for(timeout=10000)
    await hold(pg, secs)
    await btn.click()
    await hold(pg, 1.2)


async def step1_search(pg, base):
    await cap(pg, "1. Запрос словами: путешественник пишет, как ему нужно")
    await fresh_home(pg, base)
    await hold(pg, 2.5)
    await search(pg, QUERY)
    await cap(pg, "1. Три лучших варианта, и сколько отелей подходит, возможно подходит, не подходит")
    await hold(pg, 4.5)
    await scroll_to_el(pg, "#list .card", 150, 1600, nth=0)
    await cap(pg, "1. Плюс по условиям запроса: путь до пляжа, закат, тишина. Рядом то, что «для вас» минус")
    await hold(pg, 5.5)
    await scroll_to_el(pg, "#list .card", 150, 1500, nth=1)
    await hold(pg, 4.0)
    await scroll_to_el(pg, "#list .card", 150, 1500, nth=2)
    await cap(pg, "1. У каждого условия есть источник и пометка уверенности: расчёт, карта, отзывы")
    await hold(pg, 5.0)
    # раскрываем «Что мы проверили» на третьей карточке: чипы-доказательства
    try:
        await pg.locator("#list .card").nth(2).get_by_text("Что проверили").click(timeout=3000)
        await hold(pg, 4.5)
    except Exception:
        pass


async def step2_hotel(pg):
    await cap(pg, "2. Открываем один отель")
    await scroll(pg, 0, 900)
    await scroll_to_el(pg, "#list .card", 150, 1000, nth=0)
    await hold(pg, 1.0)
    await pg.locator("#list .card").first.get_by_role("button", name="Подробнее").click()
    await pg.wait_for_selector("#shScroll .tw-ask, #shScroll h2", timeout=15000)
    await cap(pg, "2. Неожиданная деталь: «просите окна на запад», с доводами и источником")
    await hold(pg, 5.5)
    await cap(pg, "2. «Какой номер брать»: какую сторону и этаж попросить, текст просьбы копируется одной кнопкой")
    await scroll_to_el(pg, "#shScroll h3", 20, 1600, sel="#shScroll", nth=0)
    await hold(pg, 3.0)
    try:
        await pg.locator("#shScroll button[data-copy]").first.click(timeout=3000)
    except Exception:
        pass
    await hold(pg, 3.5)
    await cap(pg, "2. Вид из окна: что увидите с этого этажа, с этой стороны, в июле. Закат считается по рельефу и домам")
    await scroll_to_el(pg, "#shScroll h3", 20, 1800, sel="#shScroll", nth=1)
    await hold(pg, 6.0)
    await cap(pg, "2. Ночь по часам: когда шумно и с какой стороны, чтобы выбрать тихий номер")
    await scroll_to_el(pg, "#shScroll h3", 20, 1800, sel="#shScroll", nth=2)
    await hold(pg, 6.0)


async def step3_honesty(pg, base):
    await cap(pg, "3. Честность: чего не знаем, говорим прямо")
    await fresh_home(pg, base)
    await search(pg, "Тихий отель с веганским завтраком", delay=45)
    await cap(pg, "3. «Про веганский завтрак мы пока не знаем»: не придумываем, предлагаем проверить")
    await hold(pg, 6.0)
    await cap(pg, "3. Другой город: «Это не Казань». Чужой регион не выдаём за ответ")
    await fresh_home(pg, base)
    await search(pg, "Вид на море в Казани", delay=45)
    await hold(pg, 6.0)


async def step4_conflict(pg, base):
    await cap(pg, "4. Спорное заявление: админ команды Островка проверяет обещания отелей")
    await pg.goto(base + "/admin")
    await hold(pg, 1.2)
    await dismiss_consent(pg)
    await login_modal(pg, 3.0)
    await pg.locator("button[data-t=audit]").click()
    await cap(pg, "4. «Проверка обещаний»: что отель пишет о себе против расчёта по карте и отзывам")
    await hold(pg, 5.0)
    await pg.fill("#t-audit input", "Акс")
    await hold(pg, 0.8)
    await pg.locator("#t-audit button:has-text('Найти')").click()
    await hold(pg, 1.5)
    await pg.locator("#alist button", has_text=HOTELIER_HOTEL).first.click()
    await hold(pg, 1.5)
    await pg.evaluate("document.querySelectorAll('#aout details').forEach(d => d.open = true)")
    await cap(pg, "4. Гостевой Дом Акс: «3 категории с видом на море», а расчёт моря из окон не видит. Помечено «спорно»")
    await hold(pg, 7.0)


async def step5_hotelier(pg, base):
    await cap(pg, "5. Уточнение отельера: ему приходит вопрос по спорному месту")
    await pg.goto(base + "/hotelier")
    await pg.evaluate("sessionStorage.removeItem('__cap_x'); Object.keys(sessionStorage).filter(k => k !== '__cap').forEach(k => sessionStorage.removeItem(k))")
    await pg.goto(base + "/hotelier")
    await hold(pg, 1.2)
    await dismiss_consent(pg)
    await pg.fill("#kfind", "Акс")
    await hold(pg, 0.6)
    await pg.locator("#kfind").locator("xpath=following-sibling::button[1]").click()
    await hold(pg, 1.5)
    await pg.locator("#klist button", has_text=HOTELIER_HOTEL).first.click()
    await login_modal(pg, 3.0)
    await cap(pg, "5. Вопрос от системы: «Какие категории номеров выходят на эту сторону и с какого этажа?»")
    await pg.locator("textarea:visible").first.wait_for(timeout=15000)
    ta_id = await pg.evaluate("""() => { const t = [...document.querySelectorAll('textarea')].filter(t => t.offsetParent).find(t => /море/i.test(t.closest('div').parentElement.innerText) && /категории/i.test(t.closest('div').parentElement.innerText)); return t ? t.id : null }""")
    ta = pg.locator("#" + ta_id) if ta_id else pg.locator("textarea:visible").first
    await ta.scroll_into_view_if_needed()
    await hold(pg, 4.0)
    await ta.click()
    await pg.keyboard.type(ANSWER, delay=65)
    await hold(pg, 1.2)
    await cap(pg, "5. Ответ свободным текстом, без форм. Система разбирает его в поля: этаж, категории, уверенность")
    await ta.locator("xpath=following-sibling::button[1] | ../button").first.click()
    await hold(pg, 2.5)
    await cap(pg, "5. «Было → стало» и сверка: слова отельера против расчёта и карточки. На веру не принимаем")
    await hold(pg, 8.0)


async def step6_admin(pg, base):
    await cap(pg, "6. Новая характеристика: админ собирает её из текста и одобряет")
    await pg.goto(base + "/admin")
    await pg.evaluate("Object.keys(sessionStorage).filter(k => k !== '__cap').forEach(k => sessionStorage.removeItem(k))")
    await pg.goto(base + "/admin")
    await hold(pg, 1.2)
    await dismiss_consent(pg)
    await login_modal(pg, 2.0)
    await pg.locator("button[data-t=chars]").click()
    await hold(pg, 1.5)
    await scroll_to_el(pg, "#newc", 140, 1600)
    await hold(pg, 1.5)
    await pg.click("#newc")
    await pg.keyboard.type(NEW_CHAR, delay=70)
    await cap(pg, "6. «В отеле есть бассейн»: агент берёт готовый шаблон, считает по 229 отелям и показывает отчёт проверки")
    await hold(pg, 1.5)
    await pg.get_by_role("button", name="Собрать и посчитать").click()
    await hold(pg, 6.0)
    # ждём готовности черновика: появляется кнопка «Одобрить» у нового черновика
    new_id = None
    for _ in range(60):
        new_id = await pg.evaluate("""() => { const b = [...document.querySelectorAll('button[onclick^="draftDecide"]')]
            .filter(b => b.textContent.trim() === 'Одобрить' && !b.disabled && /бассейн/i.test(b.closest('[id^="dr-"]')?.innerText || ''))[0];
            return b ? b.closest('[id^="dr-"]').id : null }""")
        if new_id:
            break
        await hold(pg, 0.5)
    if not new_id:
        raise RuntimeError("черновик «бассейн» не собрался")
    await scroll_to_el(pg, "#" + new_id, 80, 1500)
    await cap(pg, "6. Черновик готов: покрытие, разброс значений, пять примеров с доказательствами")
    await hold(pg, 5.0)
    await pg.evaluate("id => { const d = document.querySelector('#' + id + ' details'); if (d) d.open = true }", new_id)
    await hold(pg, 3.0)
    await cap(pg, "6. Админ одобряет, и характеристика становится публичной")
    await pg.locator(f"#{new_id} button.dr-yes").click()
    await hold(pg, 3.0)
    await scroll_to_el(pg, "#" + new_id, 80, 800)
    await hold(pg, 4.0)
    # публичность: гость видит новую характеристику в поиске
    await cap(pg, "6. Гость уже ищет по ней: «бассейн» появился среди условий поиска")
    await fresh_home(pg, base)
    await search(pg, "отель с бассейном", delay=60)
    await hold(pg, 6.0)
    await cap(pg, "О!Правда об отеле: запрос словами, вывод с доказательствами, уточнение отельера, одобрение админа")
    await hold(pg, 4.0)


async def record(base, tmp):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp),
                                  record_video_size={"width": W, "height": H}, locale="ru-RU")
        await ctx.add_init_script(CAPTION_JS)
        pg = await ctx.new_page()
        pg.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
        try:
            await step1_search(pg, base)
            await step2_hotel(pg)
            await step3_honesty(pg, base)
            await step4_conflict(pg, base)
            await step5_hotelier(pg, base)
            await step6_admin(pg, base)
        finally:
            video = pg.video
            await ctx.close()
            path = await video.path()
            await b.close()
    return Path(path)


def convert(webm, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    subprocess.run([ff, "-y", "-i", str(webm), "-c:v", "libx264", "-preset", "slow", "-crf", "28", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-vf", "scale=1280:-2", str(out)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8050")
    ap.add_argument("--out", default=str(ROOT / "docs" / "demo.mp4"))
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="demo_rec_"))
    webm = asyncio.run(record(a.base.rstrip("/"), tmp))
    out = Path(a.out)
    convert(webm, out)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"{out}: {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
