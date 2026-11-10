/* Морской бой: номера. Сетка 7x7 в тетрадную клетку, 3 спрятанных номера, 10 промахов. Сигналы: tap (точный тап по мелкой клетке), choice (колебание перед первым выстрелом). */
(function () {
  const N = 7, CELL = 34, SHOTS = 10, COLS = 'АБВГДЕЖ';
  const rnd = n => Math.floor(Math.random() * n);
  function place() {                                                  // 3 номера по 2 клетки, не касаются друг друга
    for (;;) {
      const rooms = [], occ = new Set(); let ok = true;
      for (let i = 0; i < 3 && ok; i++) {
        for (let t = 0; ; t++) {
          if (t > 200) { ok = false; break }
          const hz = rnd(2), r = rnd(hz ? N : N - 1), c = rnd(hz ? N - 1 : N), cells = [[r, c], hz ? [r, c + 1] : [r + 1, c]];
          const bad = cells.some(([a, b]) => { for (let da = -1; da <= 1; da++) for (let db = -1; db <= 1; db++) if (occ.has((a + da) + ',' + (b + db))) return true; return false });
          if (!bad) { rooms.push(cells); cells.forEach(([a, b]) => occ.add(a + ',' + b)); break }
        }
      }
      if (ok) return rooms;
    }
  }
  Arcade.register({
    id: 'morskoy-boy-nomera', title: 'Морской бой: номера', era: 'ussr', icon: '🔑', duration: 30,
    rules: 'Найди 3 номера на плане этажа за 10 промахов. Тапай точно.',
    win: 'Все три номера найдены. Бронь подтверждена.', lose: 'Выстрелы кончились. Номера целы и спрятаны.',
    primitives: ['precise-tap'],
    start(stage, ctx) {
      const { pal } = ctx, rooms = place(), found = new Set(), shot = new Set(), cells = {};
      let left = SHOTS, nfound = 0, first = true, locked = false;
      const t0 = performance.now(), L = 22;                          // L: ширина подписей
      const st = document.createElement('style');
      const INK = '#20291d', WAVE = "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 34 34'%3E%3Cpath d='M5 13q3-4 6 0t6 0 6 0M11 23q3-4 6 0t6 0' fill='none' stroke='%2320291d' stroke-opacity='.16' stroke-width='1.4' stroke-linecap='round'/%3E%3C/svg%3E\")";
      const SPLASH = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><circle cx="12" cy="13" r="3.2" fill="none" stroke="#20291d" stroke-width="2"/><circle cx="12" cy="13" r="7.6" fill="none" stroke="#20291d" stroke-opacity=".45" stroke-width="1.6" stroke-dasharray="3 3"/><path d="M12 3v3M4.5 6l2 2M19.5 6l-2 2" stroke="#20291d" stroke-width="1.6" stroke-linecap="round"/></svg>';
      const ROOM = '<svg viewBox="0 0 28 28" width="28" height="28" aria-hidden="true"><rect x="2.5" y="2.5" width="23" height="23" rx="3" fill="#20291d"/><rect x="6" y="5.5" width="16" height="10.5" rx="1" fill="#acef81"/><path d="M5 19.5H23M5 19.5V25M23 19.5V25M10.5 19.5V25M14 19.5V25M17.5 19.5V25" stroke="#acef81" stroke-width="1.5" fill="none"/></svg>';
      st.textContent = `.mb{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:${INK};font-family:"PT Root UI",system-ui,sans-serif;font-variant-numeric:tabular-nums}
.mb::after{content:"";position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,rgba(32,41,29,.05) 0 1px,transparent 1px 3px)}
.mb-top{display:flex;gap:14px;font:700 12px "PT Root UI",system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;width:${N * CELL + L}px;justify-content:space-between;align-items:baseline}
.mb-top b{font:800 22px "PT Root UI",system-ui,sans-serif;letter-spacing:0;margin-left:4px}
.mb-board{position:relative;width:${N * CELL + L}px;height:${N * CELL + L}px;background:rgba(32,41,29,.04);border-radius:6px}
.mb-grid{position:absolute;left:${L}px;top:${L}px;width:${N * CELL}px;height:${N * CELL}px;display:grid;grid-template-columns:repeat(${N},${CELL}px);grid-template-rows:repeat(${N},${CELL}px);outline:2px solid ${INK};outline-offset:1px;border-radius:2px}
.mb-c{width:${CELL}px;height:${CELL}px;box-sizing:border-box;border:1px solid rgba(32,41,29,.14);background:${WAVE};display:flex;align-items:center;justify-content:center;font:800 16px "Spoof","PT Root UI",system-ui,sans-serif;cursor:crosshair;position:relative}
.mb-c.s{cursor:default;background-image:none}.mb-c.pop{animation:mbp .25s}@keyframes mbp{40%{transform:scale(1.3)}}
.mb-c .k{display:flex}
.mb-c b{position:relative;z-index:1}
.mb-c.w{background-color:rgba(11,78,194,.22)}.mb-c.w2{background-color:rgba(11,78,194,.1)}
.mb-lab{position:absolute;font:700 12px "PT Root UI",system-ui,sans-serif;color:${INK};width:${CELL}px;text-align:center;line-height:${L}px;opacity:.7}
.mb-lab.r{width:${L}px;line-height:${CELL}px;left:0}.mb-lab.c{top:0}
.mb-hint{min-height:44px;font:600 15px/1.3 "PT Root UI",system-ui,sans-serif;text-align:center;padding:0 24px;max-width:340px}
.mb-sub{font-size:12px;opacity:.6;text-align:center}`;
      stage.appendChild(st);
      const root = document.createElement('div'); root.className = 'mb';
      root.innerHTML = `<div class="mb-top"><span>Выстрелы<b class="L">${SHOTS}</b></span><span>Номера<b class="F">0</b>/3</span></div><div class="mb-board"><div class="mb-grid"></div></div><div class="mb-hint">Выбери клетку. Подсказка: цифра показывает, сколько клеток до ближайшего номера.</div><div class="mb-sub">Попадание не тратит выстрел</div>`;
      stage.appendChild(root);
      const board = root.querySelector('.mb-board'), grid = root.querySelector('.mb-grid'), hint = root.querySelector('.mb-hint');
      for (let i = 0; i < N; i++) {
        board.insertAdjacentHTML('beforeend', `<div class="mb-lab c" style="left:${L + i * CELL}px">${COLS[i]}</div><div class="mb-lab r" style="top:${L + i * CELL}px">${i + 1}</div>`);
      }
      for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) { const d = document.createElement('div'); d.className = 'mb-c'; d.dataset.r = r; d.dataset.c = c; grid.appendChild(d); cells[r + ',' + c] = d }
      const roomAt = (r, c) => rooms.findIndex(rm => rm.some(([a, b]) => a === r && b === c));
      const dist = (r, c) => { let m = 99; rooms.forEach((rm, i) => { if (found.has(i)) return; rm.forEach(([a, b]) => m = Math.min(m, Math.max(Math.abs(a - r), Math.abs(b - c)))) }); return m };
      const hud = () => { root.querySelector('.L').textContent = left; root.querySelector('.F').textContent = nfound; ctx.score(nfound) };

      ctx.on(grid, 'pointerdown', e => {
        const el = e.target.closest('.mb-c'); if (!el || locked || el.classList.contains('s')) return; e.preventDefault();
        const r = +el.dataset.r, c = +el.dataset.c, p = ctx.pt(e), idx = roomAt(r, c), hit = idx >= 0;
        ctx.sense.tap({ x: p.x, y: p.y, target: ctx.rect(el), hit });
        if (first) { first = false; ctx.sense.choice({ ms: performance.now() - t0, ok: true }) }
        el.classList.add('s', 'pop');
        if (hit) {
          found.add(idx); nfound++;
          rooms[idx].forEach(([a, b]) => { const ce = cells[a + ',' + b]; ce.classList.add('s', 'pop'); ce.className = 'mb-c s'; ce.innerHTML = '<span class="k">' + ROOM + '</span>'; ce.style.backgroundColor = '#acef81' });
          hint.textContent = nfound === 3 ? 'Все три номера найдены.' : 'Есть номер. Выстрел не потрачен.';
        } else {
          left--; const d = dist(r, c);
          el.innerHTML = d <= 2 ? `<b>${d}</b>` : SPLASH; if (d === 1) el.classList.add('w'); else if (d === 2) el.classList.add('w2');
          hint.textContent = d === 1 ? 'Тепло: номер совсем рядом.' : d === 2 ? 'Близко: ближайший номер через клетку.' : `Холодно: ближайший номер в ${d} клетках.`;
        }
        hud();
        if (nfound === 3) { locked = true; ctx.after(900, () => ctx.end({ won: true, score: 3 })) }
        else if (left === 0) { locked = true; ctx.after(900, () => { rooms.forEach((rm, i) => found.has(i) || rm.forEach(([a, b]) => { cells[a + ',' + b].style.backgroundColor = 'rgba(203,27,0,.28)' })); ctx.after(700, () => ctx.end({ won: false, score: nfound })) }) }
      });
      hud();
      return { stop() { }, timeUp() { return { won: nfound === 3, score: nfound } } };
    }
  });
})();
