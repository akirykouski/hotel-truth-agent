/* Этажи сверху: падающие блоки 6x8. Тап по колонке двигает, двойной тап (<=300 мс) поворачивает, свайп вниз сбрасывает. Сигналы: tap (колонка как цель), rhythm (двойной тап, в т.ч. неудачный 300-500 мс). */
(function () {
  const COLS = 6, ROWS = 8, GOAL = 3, STEP = 560;
  const SHAPES = [{ c: [[0, 0], [0, 1]], k: 'lime', w: 3 }, { c: [[0, 0], [0, 1], [0, 2]], k: 'blue', w: 2 }, { c: [[0, 0], [1, 0], [1, 1]], k: 'purple', w: 3 }, { c: [[0, 0], [0, 1], [1, 0], [1, 1]], k: 'sea', w: 1 }];
  const norm = cs => { const r = Math.min(...cs.map(a => a[0])), c = Math.min(...cs.map(a => a[1])); return cs.map(([a, b]) => [a - r, b - c]) };
  const rot = cs => norm(cs.map(([r, c]) => [c, -r]));
  const wid = cs => Math.max(...cs.map(a => a[1])) + 1;
  Arcade.register({
    id: 'etazhi-blocks', title: 'Этажи сверху', era: 'world', icon: '🏗️', duration: 30,
    rules: 'Тап по колонке двигает блок, двойной тап поворачивает. Собери 3 ряда.',
    win: 'Три этажа собраны. Прораб улыбается.', lose: 'Шахта полна. Стройка закрыта на обед.',
    primitives: ['double-tap', 'tap'],
    start(stage, ctx) {
      const { w, h, pal } = ctx, { canvas, g } = ctx.canvas();
      const cell = Math.floor(Math.min((w - 24 - 112) / COLS, (h - 110) / ROWS)), bw = cell * COLS, bh = cell * ROWS, bx = 12, by = Math.floor((h - bh) / 2) - 14;
      const col = { blue: pal.blue, lime: pal.lime, purple: pal.purple, sea: '#d9d8d6' };
      const grid = Array.from({ length: ROWS }, () => Array(COLS).fill(null));
      const pick = () => { let t = Math.random() * SHAPES.reduce((s, x) => s + x.w, 0); for (const s of SHAPES) if ((t -= s.w) < 0) return { c: s.c.map(a => [...a]), k: s.k }; return SHAPES[0] };
      const hasHover = matchMedia('(hover:hover)').matches;
      let cur = null, next = pick(), acc = 0, rows = 0, clearing = null, lastTap = 0, lastCol = -9, done = false;

      const hit = (cs, x, y) => cs.some(([r, c]) => { const R = y + r, C = x + c; return C < 0 || C >= COLS || R >= ROWS || (R >= 0 && grid[R][C]) });
      function spawn() {
        const p = next; next = pick(); const x = Math.floor((COLS - wid(p.c)) / 2);
        cur = { c: p.c, k: p.k, x, y: 0 }; acc = 0;
        if (hit(cur.c, cur.x, cur.y)) { cur = null; done = true; ctx.after(500, () => ctx.end({ won: false, score: rows })) }
      }
      const move = dx => { if (cur && !clearing && !hit(cur.c, cur.x + dx, cur.y)) { cur.x += dx; return true } return false };
      function toCol(c) { if (!cur || clearing) return; const tgt = Math.max(0, Math.min(COLS - wid(cur.c), c - Math.floor(wid(cur.c) / 2))); while (cur.x !== tgt && move(Math.sign(tgt - cur.x))); }
      function rotate() { if (!cur || clearing) return; const n = rot(cur.c); for (const k of [0, -1, 1, -2, 2]) if (!hit(n, cur.x + k, cur.y)) { cur.c = n; cur.x += k; return } }
      const ghostY = () => { let y = cur.y; while (!hit(cur.c, cur.x, y + 1)) y++; return y };
      function lock() {
        cur.c.forEach(([r, c]) => { grid[cur.y + r][cur.x + c] = cur.k }); cur = null;
        const full = grid.map((row, i) => row.every(Boolean) ? i : -1).filter(i => i >= 0);
        if (full.length) { clearing = { rows: full, t: 0 }; ctx.score(rows + full.length) } else spawn();
      }
      const drop = () => { if (!cur || clearing) return; cur.y = ghostY(); lock() };

      ctx.onSwipe((dir, info) => {
        if (dir === 'down' && info.dy > 36) return drop();
        if (dir !== 'tap') return;
        const now = performance.now(), c = Math.max(0, Math.min(COLS - 1, Math.floor((info.x - bx) / cell)));
        ctx.sense.tap({ x: info.x, y: info.y, target: { x: bx + c * cell, y: by, w: cell, h: bh }, hit: info.x >= bx && info.x <= bx + bw });
        const dt = now - lastTap;
        if (lastTap && dt <= 300 && Math.abs(c - lastCol) <= 1) { rotate(); ctx.sense.rhythm({ wantMs: 300, gotMs: dt }); lastTap = 0; return }
        if (lastTap && dt > 300 && dt <= 500) ctx.sense.rhythm({ wantMs: 300, gotMs: dt });       // неудавшийся двойной тап
        lastTap = now; lastCol = c; toCol(c);
      });
      ctx.onKey(k => { if (k === 'ArrowLeft') move(-1); else if (k === 'ArrowRight') move(1); else if (k === 'ArrowUp') rotate(); else if (k === 'ArrowDown') { if (cur && !clearing && !hit(cur.c, cur.x, cur.y + 1)) cur.y++; acc = 0 } else if (k === ' ') drop() });

      const INK = '#20291d', LCD = '#cdeeb0', LIME = '#acef81', RED = '#cb1b00';
      const dpr = devicePixelRatio || 1, tex = document.createElement('canvas'); tex.width = Math.max(1, w * dpr); tex.height = Math.max(1, h * dpr);
      { const t = tex.getContext('2d'); t.fillStyle = 'rgba(32,41,29,.06)'; const st = Math.round(3 * dpr); for (let i = 0; i < tex.height; i += st) t.fillRect(0, i, tex.width, Math.max(1, dpr * .6)); for (let i = 0; i < tex.width; i += st) t.fillRect(i, 0, Math.max(1, dpr * .6), tex.height) }
      const win = (x, y, ww, hh, c) => { g.fillStyle = c; g.fillRect(x, y, ww, hh) };
      // этаж отеля: корпус + окно + балкон. k задаёт тип окна, m: ink | blue | lit (вспышка собранного ряда)
      function sq(x, y, s, k, m) {
        const body = m === 'blue' ? pal.blue : m === 'lit' ? LIME : INK, glass = m === 'lit' ? INK : (m === 'blue' ? LIME : LCD), lit = m !== 'lit';
        g.fillStyle = body; g.beginPath(); g.roundRect(x + 1, y + 1, s - 2, s - 2, 2); g.fill();
        const u = s / 10;
        if (k === 'lime') { win(x + 2.5 * u, y + 2 * u, 5 * u, 3.6 * u, glass); win(x + 1.8 * u, y + 6.6 * u, 6.4 * u, 1.1 * u, glass) }          // окно + балкон
        else if (k === 'blue') { g.fillStyle = glass; g.beginPath(); g.moveTo(x + 3 * u, y + 6 * u); g.lineTo(x + 3 * u, y + 3.6 * u); g.arc(x + 5 * u, y + 3.6 * u, 2 * u, Math.PI, 0); g.lineTo(x + 7 * u, y + 6 * u); g.fill(); win(x + 2 * u, y + 6.9 * u, 6 * u, u, glass) }  // арочное окно
        else if (k === 'purple') { win(x + 1.8 * u, y + 2.6 * u, 2.6 * u, 3.4 * u, glass); win(x + 5.6 * u, y + 2.6 * u, 2.6 * u, 3.4 * u, glass); win(x + 1.5 * u, y + 7 * u, 7 * u, u, glass) }
        else { win(x + 2 * u, y + 2 * u, 6 * u, 4.4 * u, glass); g.fillStyle = body; g.fillRect(x + 4.9 * u, y + 2 * u, .25 * u + .6, 4.4 * u); g.fillRect(x + 2 * u, y + 4.1 * u, 6 * u, .25 * u + .6); win(x + 1.5 * u, y + 7.2 * u, 7 * u, .9 * u, glass) }
        if (lit && m === 'ink' && ((x * 7 + y * 13) | 0) % 3 === 0) { g.fillStyle = LIME; g.fillRect(x + 3.2 * u, y + 3 * u, 1.2 * u, 1.2 * u) } // «горящее» окно
      }
      const seg = (x, y, s, a) => { g.globalAlpha = a; g.fillStyle = INK; g.beginPath(); g.roundRect(x + 1, y + 1, s - 2, s - 2, 2); g.fill(); g.globalAlpha = 1 };
      function pin(cx, cy) { g.fillStyle = LIME; g.strokeStyle = INK; g.lineWidth = 1.5; g.beginPath(); g.moveTo(cx, cy); g.bezierCurveTo(cx - 8, cy - 7, cx - 5, cy - 15, cx, cy - 15); g.bezierCurveTo(cx + 5, cy - 15, cx + 8, cy - 7, cx, cy); g.fill(); g.stroke(); g.fillStyle = INK; g.beginPath(); g.arc(cx, cy - 9, 1.8, 0, 7); g.fill() }
      spawn(); ctx.score(0);
      ctx.raf((dt) => {
        if (!done && cur) { acc += dt; while (acc >= STEP && cur) { acc -= STEP; if (hit(cur.c, cur.x, cur.y + 1)) { lock(); break } cur.y++ } }
        if (clearing) { clearing.t += dt; if (clearing.t > 450) {
          const keep = grid.filter((_, i) => !clearing.rows.includes(i)); while (keep.length < ROWS) keep.unshift(Array(COLS).fill(null));
          keep.forEach((r, i) => grid[i] = r); rows += clearing.rows.length; clearing = null; ctx.score(rows);
          if (rows >= GOAL) { done = true; ctx.after(500, () => ctx.end({ won: true, score: rows })) } else spawn() } }
        g.fillStyle = LCD; g.fillRect(0, 0, w, h);
        for (let r = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++) seg(bx + c * cell, by + r * cell, cell, .08);          // призрачные сегменты
        g.strokeStyle = INK; g.lineWidth = 2; g.strokeRect(bx - 2, by - 2, bw + 4, bh + 4);
        const fl = clearing && Math.floor(clearing.t / 90) % 2 === 0; let top = -1;
        for (let r = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++) if (grid[r][c]) { if (top < 0) top = r; const on = clearing && clearing.rows.includes(r); sq(bx + c * cell, by + r * cell, cell, grid[r][c], on ? (fl ? 'lit' : 'blue') : 'ink') }
        if (top > 0) { const c0 = grid[top].findIndex(Boolean); pin(bx + c0 * cell + cell / 2, by + top * cell + 1) }              // пин Ostrovok на крыше
        if (cur) { const gy = ghostY(); g.strokeStyle = INK; g.globalAlpha = .3; g.lineWidth = 1.5; cur.c.forEach(([r, c]) => g.strokeRect(bx + (cur.x + c) * cell + 2, by + (gy + r) * cell + 2, cell - 4, cell - 4)); g.globalAlpha = 1; cur.c.forEach(([r, c]) => sq(bx + (cur.x + c) * cell, by + (cur.y + r) * cell, cell, cur.k, 'blue')) }
        // правая панель
        const px = bx + bw + 14, pw = w - px - 12;
        g.fillStyle = INK; g.font = '600 13px sans-serif'; g.textAlign = 'left'; g.fillText('Дальше', px, by + 12);
        const ms = Math.min(18, Math.floor(pw / 4)); g.globalAlpha = .08; g.fillStyle = INK; g.beginPath(); g.roundRect(px, by + 20, pw, ms * 3 + 12, 6); g.fill(); g.globalAlpha = 1;
        const nw = wid(next.c), nh = Math.max(...next.c.map(a => a[0])) + 1;
        next.c.forEach(([r, c]) => sq(px + (pw - nw * ms) / 2 + c * ms, by + 26 + (ms * 3 - nh * ms) / 2 + r * ms, ms, next.k, 'ink'));
        g.fillStyle = INK; g.font = '700 26px sans-serif'; g.fillText(`${rows}/${GOAL}`, px, by + 124); g.font = '13px sans-serif'; g.fillText('рядов', px, by + 142);
        g.globalAlpha = .75; g.font = '11.5px sans-serif';
        const tips = hasHover ? ['← → двигать', '↑ повернуть', '↓ ниже', 'Пробел сброс', 'или тап и свайп'] : ['Тап: колонка', '2 тапа: поворот', 'Свайп ↓: сброс'];
        tips.forEach((t, i) => g.fillText(t, px, by + 176 + i * 18)); g.globalAlpha = 1;
        g.drawImage(tex, 0, 0, w, h);
      });
      return { stop() { }, timeUp() { return { won: rows >= GOAL, score: rows } } };
    }
  });
})();
