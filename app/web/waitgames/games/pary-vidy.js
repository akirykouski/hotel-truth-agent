/* Пары: вид из окна (Memory). 12 карточек-окон, 6 пар видов. */
(function () {
  Arcade.register({
    id: 'pary-vidy', title: 'Пары: вид из окна', era: 'world', icon: '🪟', duration: 30,
    rules: 'Открывай окна и ищи пары одинаковых видов. Двенадцать окон, тридцать секунд.',
    win: 'Все виды найдены. Окно с морем нашлось первым.',
    lose: 'Не все пары сошлись. Вид из окна ещё загадка.',
    primitives: ['choice', 'tap'],
    start(stage, ctx) {
      const P = ctx.pal, INK = '#20291d', LCD = '#cdeeb0', PAPER = '#e6f6d6', LIME = '#acef81', BLUE = P.blue;
      const S = (b) => `<svg viewBox="0 0 60 60" aria-hidden="true" fill="none" stroke="${INK}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${b}</svg>`;
      const ICONS = [
        S(`<circle cx="44" cy="15" r="6" fill="${LIME}"/><path d="M6 32h48" /><path d="M6 40q6-5 12 0t12 0 12 0 12 0M6 48q6-5 12 0t12 0 12 0 12 0M6 56q6-5 12 0t12 0 12 0 12 0" stroke="${BLUE}"/>`),                       // море
        S(`<path d="M4 50L22 18l10 17 7-10 17 25z" fill="${INK}"/><path d="M17 27l5-9 5 9-5-3zM36 30l3-5 3 5-3-2z" fill="${LIME}" stroke="none"/><path d="M4 50h52"/>`),                                      // горы
        S(`<path d="M12 36a18 18 0 0 1 36 0z" fill="${LIME}"/><path d="M4 36h52M10 43h40M16 50h28" /><path d="M30 10v5M12 17l3 3M48 17l-3 3"/>`),                                                 // закат
        S(`<path d="M10 54V24a20 20 0 0 1 40 0v30" fill="${PAPER}"/><path d="M20 54V28a10 10 0 0 1 20 0v26"/><path d="M30 54V30M6 54h48"/><path d="M30 18q-6-8-14-6M30 18q6-8 14-6M30 18q-2-9 0-13" stroke="${BLUE}"/>`),         // двор с аркой и пальмой
        S(`<path d="M6 54V26h12v28M20 54V12h14v42M36 54V30h10v24M48 54V22h8v32M4 54h52" fill="${PAPER}"/><path d="M24 20h2M28 20h2M24 28h2M28 28h2M24 36h2M28 36h2M24 44h2M28 44h2M10 33h2M10 41h2M40 38h2M52 30h2" stroke="${INK}"/><path d="M27 12V6" stroke="${BLUE}"/><circle cx="27" cy="5" r="2.2" fill="${LIME}"/>`), // город
        S(`<rect x="6" y="26" width="48" height="26" rx="3" fill="${BLUE}" stroke="${INK}"/><path d="M12 34q4-4 8 0t8 0 8 0 8 0M12 43q4-4 8 0t8 0 8 0 8 0" stroke="${LIME}"/><path d="M42 26V12q0-5 6-5M48 26V12q0-4 6-4" stroke="${INK}"/>`)  // бассейн
      ];
      const VIEWS = ICONS.map(i => [i]);
      const deck = VIEWS.concat(VIEWS).map((v, i) => ({ v, k: i % 6 })).sort(() => Math.random() - .5);
      const st = document.createElement('style');
      st.textContent = `.pv{position:absolute;inset:0;padding:12px;display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(4,1fr);gap:10px;background:${LCD}}
.pv::after{content:'';position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,rgba(32,41,29,.05) 0 1px,transparent 1px 3px)}
.pv-c{position:relative;perspective:600px;cursor:pointer;-webkit-tap-highlight-color:transparent;min-height:44px}
.pv-i{position:absolute;inset:0;transform-style:preserve-3d;transition:transform .32s}
.pv-c.on .pv-i{transform:rotateY(180deg)}
.pv-f,.pv-b{position:absolute;inset:0;border-radius:6px;backface-visibility:hidden;-webkit-backface-visibility:hidden;display:flex;align-items:center;justify-content:center;overflow:hidden;border:2px solid ${INK};background:${PAPER}}
.pv-b i{position:absolute;display:block}
.pv-st{right:8%;top:10%;width:26%;aspect-ratio:4/5;background:${LIME};border:2px dashed ${INK};box-sizing:border-box}
.pv-st::after{content:'';position:absolute;left:28%;top:22%;width:44%;height:44%;border-radius:50% 50% 50% 0;transform:rotate(-45deg);background:${INK}}
.pv-pm{right:26%;top:20%;width:30%;aspect-ratio:1;border:2px solid ${BLUE};border-radius:50%;opacity:.75;transform:rotate(-12deg);box-sizing:border-box}
.pv-pm::after{content:'';position:absolute;left:14%;right:14%;top:42%;height:2px;background:${BLUE};box-shadow:0 5px 0 ${BLUE},0 -5px 0 ${BLUE}}
.pv-ln{left:10%;width:42%;height:2px;background:${INK};opacity:.3}
.pv-f{transform:rotateY(180deg)}
.pv-f svg{width:78%;height:78%;max-height:100%}
.pv-c.ok .pv-f{opacity:.5}
.pv-c.ok .pv-f::after{content:'✓';position:absolute;right:5px;top:4px;font-size:18px;font-weight:700;color:${INK};background:${LIME};border:2px solid ${INK};border-radius:50%;width:26px;height:26px;line-height:22px;text-align:center;box-sizing:border-box}
.pv-c.bad .pv-f{border-color:#cb1b00}`;
      stage.appendChild(st);
      const g = document.createElement('div'); g.className = 'pv'; stage.appendChild(g);
      const cards = deck.map(d => {
        const c = document.createElement('div'); c.className = 'pv-c';
        c.innerHTML = `<div class="pv-i"><div class="pv-b"><i class="pv-ln" style="top:58%"></i><i class="pv-ln" style="top:70%"></i><i class="pv-ln" style="top:82%;width:28%"></i><i class="pv-pm"></i><i class="pv-st"></i></div><div class="pv-f">${d.v[0]}</div></div>`;
        g.appendChild(c); return Object.assign(d, { el: c, open: false, done: false });
      });
      let first = null, lock = false, pairs = 0, prev = performance.now();
      cards.forEach(c => ctx.on(c.el, 'pointerdown', e => {
        e.preventDefault();
        const p = ctx.pt(e); ctx.sense.tap({ x: p.x, y: p.y, target: ctx.rect(c.el), hit: true });
        if (lock || c.open || c.done) return;
        const now = performance.now(), ms = now - prev; prev = now;
        c.open = true; c.el.classList.add('on');
        if (!first) { first = c; return }
        const ok = first.k === c.k; ctx.sense.choice({ ms, ok });
        const a = first; first = null; lock = true;
        if (ok) {
          ctx.after(380, () => { a.done = c.done = true; a.el.classList.add('ok'); c.el.classList.add('ok'); lock = false; ctx.score(++pairs);
            if (pairs === 6) ctx.end({ won: true, score: pairs }) });
        } else {
          a.el.classList.add('bad'); c.el.classList.add('bad');
          ctx.after(750, () => { [a, c].forEach(x => { x.open = false; x.el.classList.remove('on', 'bad') }); lock = false });
        }
      }));
      ctx.score(0);
      return { stop() { }, timeUp() { return { won: pairs === 6, score: pairs } } };
    }
  });
})();
