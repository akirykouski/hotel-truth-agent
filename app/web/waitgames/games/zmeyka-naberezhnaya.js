/* Змейка по набережной: цепочка лаймовых секций собирает ключ-карты. Свайп или стрелки. */
(function () {
  Arcade.register({
    id: 'zmeyka-naberezhnaya', title: 'Змейка по набережной', era: 'world', icon: '🐍', duration: 25,
    rules: 'Свайпай или жми стрелки: собери 8 ключ-карт и не врежься в бордюр.',
    win: '8 ключ-карт собрано. Заселяйтесь.', lose: 'Бордюр был твёрже. Ещё круг?',
    primitives: ['swipe', 'key'],
    start(stage, ctx) {
      const { w: W, h: H, pal } = ctx, N = 12, GOAL = 8, STEP = 250;
      const { g } = ctx.canvas();
      const C = Math.floor(Math.min(W - 24, H - 70) / N), ox = Math.round((W - C * N) / 2), oy = Math.round((H - C * N) / 2);
      const DIR = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] }, KEY = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', w: 'up', s: 'down', a: 'left', d: 'right' };
      let snake = [[6, 6], [5, 6], [4, 6]], dir = 'right', queue = [], card, got = 0, acc = 0, over = false, lastKeyT = 0, lastEmit = 0, go = false;
      const free = (x, y) => !snake.some(s => s[0] === x && s[1] === y);
      function spawn() { let x, y; do { x = Math.random() * N | 0; y = Math.random() * N | 0 } while (!free(x, y)); card = [x, y] }
      spawn();
      const opp = (a, b) => DIR[a][0] + DIR[b][0] === 0 && DIR[a][1] + DIR[b][1] === 0;
      function turn(d) { go = true; const last = queue.length ? queue[queue.length - 1] : dir; if (d === last || opp(d, last) || queue.length > 1) return false; queue.push(d); return true }
      ctx.onSwipe(d => { if (d !== 'tap') turn(d) });
      ctx.onKey((k, e) => {
        const d = KEY[k]; if (!d) return; const now = performance.now(), ok = turn(d);
        if (now - lastEmit > 400) { lastEmit = now; ctx.sense.key({ ms: lastKeyT ? Math.min(3000, now - lastKeyT) : 600, ok }) } lastKeyT = now;
      });
      function finish(won) { over = true; draw(); ctx.after(350, () => ctx.end({ won, score: got })) }
      function tick() {
        if (queue.length) dir = queue.shift();
        const h = snake[0], n = [h[0] + DIR[dir][0], h[1] + DIR[dir][1]];
        const eat = n[0] === card[0] && n[1] === card[1];
        if (n[0] < 0 || n[1] < 0 || n[0] >= N || n[1] >= N || snake.slice(0, eat ? snake.length : -1).some(s => s[0] === n[0] && s[1] === n[1])) return finish(false);
        snake.unshift(n);
        if (eat) { got++; ctx.score(got); if (got >= GOAL) return finish(true); spawn() } else snake.pop();
      }
      // ---------- LCD: статичный слой (набережная, галька, море, пальмы, растр) рисуется один раз ----------
      const INK = '#20291d', GH = 'rgba(32,41,29,.08)', BLUE = pal.blue, LIME = pal.lime, d = devicePixelRatio || 1;
      const PIN = new Path2D('M7.5 0C3.4 0 0 3.3 0 7.4c0 5 6.3 10.8 6.6 11.1.5.4 1.3.4 1.8 0 .3-.3 6.6-6.1 6.6-11.1C15 3.3 11.6 0 7.5 0zm0 10.6a3.2 3.2 0 1 1 0-6.4 3.2 3.2 0 0 1 0 6.4z');
      const bgc = document.createElement('canvas'); bgc.width = W * d; bgc.height = H * d;
      (function () {
        const x = bgc.getContext('2d'); x.scale(d, d); const S = C * N; let sd = 7; const rnd = () => (sd = (sd * 16807) % 2147483647) / 2147483647;
        // плитка набережной: шахматка призраков и сетка
        x.fillStyle = 'rgba(32,41,29,.045)'; for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) if ((r + c) & 1) x.fillRect(ox + c * C, oy + r * C, C, C);
        x.strokeStyle = GH; x.lineWidth = 1; x.beginPath();
        for (let i = 0; i <= N; i++) { x.moveTo(ox + i * C + .5, oy); x.lineTo(ox + i * C + .5, oy + S); x.moveTo(ox, oy + i * C + .5); x.lineTo(ox + S, oy + i * C + .5) }
        x.stroke();
        // бордюр и галечный пляж по краю
        x.strokeStyle = INK; x.lineWidth = 2.5; x.strokeRect(ox - 1, oy - 1, S + 2, S + 2);
        x.fillStyle = 'rgba(32,41,29,.4)';
        const peb = (px, py) => { x.beginPath(); x.ellipse(px, py, 1.6 + rnd() * 2.6, 1.3 + rnd() * 1.6, rnd() * 3, 0, 7); x.fill() };
        for (let i = 0; i < N * 7; i++) { const t = (i + rnd()) / (N * 7) * S; peb(ox + t, oy - 4 - rnd() * 4); peb(ox + t, oy + S + 4 + rnd() * 4); peb(ox - 4 - rnd() * 4, oy + t); peb(ox + S + 4 + rnd() * 4, oy + t) }
        // море внизу: волновая штриховка
        const sy = oy + S + 14; x.strokeStyle = 'rgba(32,41,29,.22)'; x.lineWidth = 1.2;
        for (let r = 0, y = sy; y < H - 4; r++, y += 9) for (let px = (r % 2) * 9 + 2; px < W - 6; px += 18) { x.beginPath(); x.moveTo(px, y); x.quadraticCurveTo(px + 4.5, y - 4, px + 9, y); x.stroke() }
        // пальмы: в боковых полях или над полем, если есть место
        const palm = (bx, by, h, lean) => {
          x.strokeStyle = 'rgba(32,41,29,.55)'; x.lineWidth = Math.max(3, h * .06); x.lineCap = 'round'; x.beginPath(); x.moveTo(bx, by); x.quadraticCurveTo(bx + lean * h * .1, by - h * .5, bx + lean * h * .22, by - h); x.stroke();
          const tx = bx + lean * h * .22, ty = by - h; x.lineWidth = Math.max(2, h * .035);
          for (let k = 0; k < 6; k++) { const a = -Math.PI + (k + .5) * Math.PI / 6 * 1.0, L = h * .55; x.beginPath(); x.moveTo(tx, ty); x.quadraticCurveTo(tx + Math.cos(a) * L * .6, ty + Math.sin(a) * L * .6 - L * .25, tx + Math.cos(a) * L, ty + Math.sin(a) * L * .55 + L * .25); x.stroke() }
        };
        const side = ox - 12, topS = oy - 46;
        if (side >= 44) { const h = Math.min(120, side * 1.7); palm(ox - side / 2 - 4, oy + S - 6, h, 1); palm(ox + S + side / 2 + 4, oy + S - 6, h, -1) }
        else if (topS >= 44) { const h = Math.min(80, topS + 10); palm(ox + 14, oy - 12, h, 1); palm(ox + S - 14, oy - 12, h, -1) }
        x.lineCap = 'butt';
        x.fillStyle = 'rgba(32,41,29,.05)'; for (let y = 0; y < H; y += 3) x.fillRect(0, y, W, 1);   // растр
      })();
      const towel = (x, y, horiz, col, hd) => {            // секция-полотенце: сегмент с лаймовыми полосами
        g.fillStyle = col; g.beginPath(); g.roundRect(x + 1.5, y + 1.5, C - 3, C - 3, 4); g.fill();
        if (!hd) { g.fillStyle = LIME; const o = C * .3, w = Math.max(2, C * .09);
          if (horiz) { g.fillRect(x + o, y + 3, w, C - 6); g.fillRect(x + C - o - w, y + 3, w, C - 6) } else { g.fillRect(x + 3, y + o, C - 6, w); g.fillRect(x + 3, y + C - o - w, C - 6, w) } }
      };
      function draw() {
        g.clearRect(0, 0, W, H); g.drawImage(bgc, 0, 0, W, H);
        // счётчик: 8 ключ-карт, пойманные горят
        const cw = 16, ch = 11, gap = 5, tx = W / 2 - (GOAL * (cw + gap) - gap) / 2, ty = Math.max(8, oy - 28);
        for (let i = 0; i < GOAL; i++) { const lit = i < got; g.fillStyle = lit ? INK : GH; g.beginPath(); g.roundRect(tx + i * (cw + gap), ty, cw, ch, 2); g.fill(); if (lit) { g.fillStyle = LIME; g.fillRect(tx + i * (cw + gap) + 2, ty + 3, cw - 4, 2) } }
        // ключ-карта: лаймовая карточка с магнитной полосой и пином
        const cxp = ox + card[0] * C, cyp = oy + card[1] * C, kw = C - 6, kh = Math.round((C - 6) * .7);
        g.fillStyle = LIME; g.strokeStyle = INK; g.lineWidth = 2; g.beginPath(); g.roundRect(cxp + 3, cyp + (C - kh) / 2, kw, kh, 3); g.fill(); g.stroke();
        g.fillStyle = INK; g.fillRect(cxp + 3, cyp + (C - kh) / 2 + kh * .22, kw, kh * .2);
        g.save(); g.translate(cxp + C * .5 - 4, cyp + C * .5 + kh * .02); g.scale(.5, .5); g.fillStyle = BLUE; g.fill(PIN); g.restore();
        // змейка из пляжных полотенец
        for (let i = snake.length - 1; i >= 0; i--) {
          const s = snake[i], x = ox + s[0] * C, y = oy + s[1] * C, nb = snake[i ? i - 1 : 1] || s;
          const horiz = i ? nb[1] === s[1] : DIR[dir][1] === 0;
          if (i) towel(x, y, horiz, INK, false);
          else { towel(x, y, horiz, BLUE, true); const dd = DIR[dir], ex = dd[1] ? C * .22 : 0, ey = dd[0] ? C * .22 : 0, ecx = x + C / 2 + dd[0] * C * .14, ecy = y + C / 2 + dd[1] * C * .14;
            g.fillStyle = LIME; g.beginPath(); g.arc(ecx - ex, ecy - ey, C * .13, 0, 7); g.arc(ecx + ex, ecy + ey, C * .13, 0, 7); g.fill();
            g.fillStyle = INK; g.beginPath(); g.arc(ecx - ex + dd[0] * 1.5, ecy - ey + dd[1] * 1.5, C * .06, 0, 7); g.arc(ecx + ex + dd[0] * 1.5, ecy + ey + dd[1] * 1.5, C * .06, 0, 7); g.fill() }
        }
      }
      ctx.raf(dt => { if (over) return; if (!go) { draw(); return } acc += dt; while (acc >= STEP && !over) { acc -= STEP; tick() } draw() });
      return { stop() { }, timeUp() { return { won: got >= GOAL, score: got } } };
    },
  });
})();
