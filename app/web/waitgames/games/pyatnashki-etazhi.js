/* Пятнашки «Этажи»: 3x3, плитки 1-8 по порядку. Перетащить плитку в пустую клетку или тапнуть. */
(function () {
  Arcade.register({
    id: 'pyatnashki-etazhi', title: 'Пятнашки «Этажи»', era: 'ussr', icon: '🏢', duration: 30,
    rules: 'Перетащи плитки на свои места: от 1 этажа до 8. Пустая клетка не мешает.',
    win: 'Этажи на месте. Лифт довольно.', lose: 'Время вышло. Лифт застрял между этажами.',
    primitives: ['drag', 'tap'],
    start(stage, ctx) {
      const { w: W, h: H, pal } = ctx, N = 3, GAP = 6;
      const S = Math.min(W - 28, H - 150, 360), CS = (S - GAP * (N + 1)) / N, P = CS + GAP;
      // состав: b[i] = номер плитки в клетке i (0 = пусто); решённое: 1..8, пусто в конце
      let b = [1, 2, 3, 4, 5, 6, 7, 8, 0], moves = 0, over = false, last = -1;
      const nb = i => { const r = i / N | 0, c = i % N, o = []; if (r) o.push(i - N); if (r < N - 1) o.push(i + N); if (c) o.push(i - 1); if (c < N - 1) o.push(i + 1); return o };
      const dist = () => b.reduce((s, v, i) => v ? s + Math.abs(((v - 1) / N | 0) - (i / N | 0)) + Math.abs((v - 1) % N - i % N) : s, 0);
      do { b = [1, 2, 3, 4, 5, 6, 7, 8, 0]; last = -1;
        const k = 9 + (Math.random() * 4 | 0);                                    // 9-12 ходов от решённого: решаемо за время
        for (let n = 0; n < k; n++) { const e = b.indexOf(0), o = nb(e).filter(x => x !== last); const m = o[Math.random() * o.length | 0]; b[e] = b[m]; b[m] = 0; last = e }
      } while (dist() < 5);

      // ---------- LCD: лаймовая подложка шелла, чернила, призрачные окна ----------
      const INK = '#20291d', GH = 'rgba(32,41,29,.08)';
      const st = document.createElement('style');
      st.textContent = `.pe-t{position:absolute;left:0;top:0;box-sizing:border-box;border-radius:8px;background:#b7dd96;color:${INK};border:2px solid ${INK};cursor:grab;touch-action:none;overflow:hidden;
  transition:transform .14s ease-out;font-variant-numeric:tabular-nums;font-family:"Spoof","PT Root UI",system-ui,sans-serif}
.pe-t svg{position:absolute;left:0;right:0;bottom:0;width:100%;height:62%;display:block}
.pe-t svg *{stroke:${INK}}
.pe-t b{position:absolute;left:8%;top:5%;font:800 var(--pe-n)/1 "Spoof","PT Root UI",system-ui,sans-serif;font-variant-numeric:tabular-nums;letter-spacing:.02em}
.pe-t i{position:absolute;right:9%;top:9%;font:700 10px/1 "PT Root UI",system-ui,sans-serif;font-style:normal;letter-spacing:.08em;opacity:.55}
.pe-t.ok{background:${pal.blue};color:${pal.lime};border-color:${INK}}.pe-t.ok svg *{stroke:${pal.lime}}
.pe-t.dr{background:${pal.lime};z-index:5;border-color:${INK};filter:none}
.pe-slot{position:absolute;box-sizing:border-box;border-radius:8px;background:${GH}}
.pe-slot.e{border:2px dashed rgba(32,41,29,.28);background:none}
.pe-board{position:absolute;box-sizing:border-box;border-radius:12px;border:2px solid ${INK};background:rgba(32,41,29,.05);touch-action:none}
.pe-hud{position:absolute;left:0;right:0;text-align:center;color:${INK};font:700 15px/1 "PT Root UI",system-ui,sans-serif;font-variant-numeric:tabular-nums;letter-spacing:.02em}
.pe-roof{position:absolute;pointer-events:none}
.pe-scan{position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,rgba(32,41,29,.05) 0 1px,transparent 1px 3px)}`;
      stage.appendChild(st);
      const bg = document.createElement('div');                                     // призрачный фасад: окна 8%
      bg.style.cssText = `position:absolute;left:50%;bottom:0;width:${Math.min(W - 10, S + 40)}px;height:${H * .78}px;transform:translateX(-50%);border-radius:10px 10px 0 0;background-image:linear-gradient(90deg,transparent 0 6px,${GH} 6px 18px,transparent 18px),linear-gradient(transparent 0 8px,${GH} 8px 24px,transparent 24px);background-size:28px 34px;pointer-events:none`;
      stage.appendChild(bg);
      const hud = document.createElement('div'); hud.className = 'pe-hud'; hud.style.top = '14px';
      stage.appendChild(hud);
      const board = document.createElement('div'); board.className = 'pe-board';
      const bTop = Math.max(48, (H - S) / 2 - 10);
      board.style.cssText = `left:${(W - S) / 2}px;top:${bTop}px;width:${S}px;height:${S}px`;
      stage.appendChild(board);
      // крыша отеля над доской: скат, антенна и пин
      const roof = document.createElement('div'); roof.className = 'pe-roof';
      roof.innerHTML = `<svg viewBox="0 0 100 14" width="${S}" height="${Math.min(30, S * .08)}" preserveAspectRatio="none"><path d="M0 14L8 3H92L100 14Z" fill="${INK}"/><rect x="47" y="0" width="1.4" height="3" fill="${INK}"/></svg>`;
      roof.style.cssText = `left:${(W - S) / 2}px;top:${bTop - Math.min(30, S * .08) + 1}px;width:${S}px;height:${Math.min(30, S * .08)}px`;
      if (bTop >= 64) stage.appendChild(roof);
      for (let i = 0; i < 9; i++) { const s = document.createElement('div'); s.className = 'pe-slot' + (i === 8 ? ' e' : ''); s.style.cssText = `left:${GAP + (i % N) * P}px;top:${GAP + (i / N | 0) * P}px;width:${CS}px;height:${CS}px`; board.appendChild(s) }
      const WIN = `<svg viewBox="0 0 100 62" preserveAspectRatio="none" aria-hidden="true"><g fill="none" stroke-width="2.6"><rect x="9" y="6" width="20" height="26" rx="2"/><rect x="40" y="6" width="20" height="26" rx="2"/><rect x="71" y="6" width="20" height="26" rx="2"/><path d="M19 6V32M50 6V32M81 6V32M9 19H29M40 19H60M71 19H91"/></g><path d="M5 40H95M5 40V56M95 40V56M5 56H95M18 40V56M31 40V56M44 40V56M57 40V56M70 40V56M83 40V56" fill="none" stroke-width="2"/></svg>`;
      const tiles = {};
      for (let v = 1; v <= 8; v++) {
        const t = document.createElement('div'); t.dataset.v = v; t.className = 'pe-t';
        t.style.cssText = `width:${CS}px;height:${CS}px;--pe-n:${CS * .34 | 0}px`;
        t.innerHTML = `<b>${v}</b><i>ЭТАЖ</i>${WIN}`; board.appendChild(t); tiles[v] = t;
      }
      const scanL = document.createElement('div'); scanL.className = 'pe-scan'; stage.appendChild(scanL);
      const xy = i => [GAP + (i % N) * P, GAP + (i / N | 0) * P];
      function place(v, dx = 0, dy = 0) { const i = b.indexOf(v), [x, y] = xy(i); tiles[v].style.transform = `translate(${x + dx}px,${y + dy}px)` }
      function paint() {
        let ok = 0; for (let v = 1; v <= 8; v++) { const here = b.indexOf(v) === v - 1; if (here) ok++; place(v); tiles[v].classList.toggle('ok', here) }
        ctx.score(ok); hud.textContent = `на месте ${ok} из 8 · ходов ${moves}`;
        if (ok === 8 && !over) { over = true; ctx.after(600, () => ctx.end({ won: true, score: 100 + Math.max(0, 40 - moves)  })) }
      }
      function slide(i) {                                                         // двигает клетку i и цепочку к пустой, если в одной линии
        const e = b.indexOf(0), r = i / N | 0, c = i % N, er = e / N | 0, ec = e % N;
        if (r !== er && c !== ec) return false;
        const st = r === er ? (c < ec ? 1 : -1) : (r < er ? N : -N);
        for (let p = e; p !== i; p -= st) b[p] = b[p - st]; b[i] = 0; moves++; return true;
      }
      let drag = null;
      ctx.on(board, 'pointerdown', e => {
        const t = e.target.closest('[data-v]'); if (!t || over) return;
        const v = +t.dataset.v, i = b.indexOf(v), p = ctx.pt(e), adj = nb(i).includes(b.indexOf(0));
        drag = { v, i, t, adj, x0: p.x, y0: p.y, path: [[p.x, p.y, performance.now()]], t0: performance.now(), moved: 0, id: e.pointerId };
        try { t.setPointerCapture(e.pointerId) } catch (x) { }
      });
      ctx.on(board, 'pointermove', e => {
        if (!drag || e.pointerId !== drag.id) return; const p = ctx.pt(e), d = drag; d.path.push([p.x, p.y, performance.now()]);
        if (!d.adj) return;
        const em = b.indexOf(0), lim = P, ax = (em % N) - (d.i % N), ay = (em / N | 0) - (d.i / N | 0);
        const dx = ax ? Math.max(0, Math.min(lim, (p.x - d.x0) * ax)) * ax : 0, dy = ay ? Math.max(0, Math.min(lim, (p.y - d.y0) * ay)) * ay : 0;
        d.moved = Math.max(Math.abs(p.x - d.x0), Math.abs(p.y - d.y0));
        d.t.style.transition = 'none'; d.t.classList.add('dr'); place(d.v, dx, dy); d.f = Math.hypot(dx, dy) / lim;
      });
      const up = e => {
        if (!drag || e.pointerId !== drag.id) return; const d = drag, p = ctx.pt(e), now = performance.now(); drag = null;
        const t = d.t; t.style.transition = ''; t.classList.remove('dr');
        const em = b.indexOf(0), tr = ctx.rect(board);
        const cell = (k) => { const [x, y] = xy(k); return { x: tr.x + x, y: tr.y + y, w: CS, h: CS } };
        if (d.moved < 8) {                                                      // тап: сдвинуть (в т.ч. цепочку)
          const moved = slide(b.indexOf(d.v)); ctx.sense.tap({ x: p.x, y: p.y, target: cell(d.i), hit: moved });
        } else {
          if (d.path.length > 2) ctx.sense.drag({ path: d.path, ms: now - d.t0 });
          if (d.adj && d.f > .4) { const ec = cell(em); ctx.sense.tap({ x: p.x, y: p.y, target: ec, hit: p.x >= ec.x && p.x <= ec.x + CS && p.y >= ec.y && p.y <= ec.y + CS }); slide(d.i) }
        }
        paint();
      };
      ctx.on(board, 'pointerup', up); ctx.on(board, 'pointercancel', up);
      paint();
      return { stop() { }, timeUp() { let ok = 0; for (let v = 1; v <= 8; v++) if (b.indexOf(v) === v - 1) ok++; return { won: false, score: ok } } };
    },
  });
})();
