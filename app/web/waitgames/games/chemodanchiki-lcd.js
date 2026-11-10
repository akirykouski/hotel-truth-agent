/* Чемоданчики: LCD-ловец. Чемоданы ползут от ресепшна по 4 жёлобам в углы, ловим тапом в нужный угол (или Q A P L). */
(function () {
  Arcade.register({
    id: 'chemodanchiki-lcd', title: 'Чемоданчики', era: 'ussr', icon: '🧳', duration: 25,
    rules: 'Лови чемоданы корзиной: тап в угол или Q A P L. Три потери и конец.',
    win: 'Чемоданы у портье. Номер ждёт.', lose: 'Чемодан уехал в Тулу. Бывает.',
    primitives: ['reaction', 'choice', 'tap', 'key'],
    start(stage, ctx) {
      const { w: W, h: H, pal } = ctx, M = 12, SEGS = 6, OPEN = 4, LIVES = 3;
      const { canvas, g } = ctx.canvas();
      const cx = W / 2, cy = H / 2 + 4;
      // зоны: 0 Q (лев-верх), 1 A (лев-низ), 2 P (прав-верх), 3 L (прав-низ)
      const keys = ['q', 'a', 'p', 'l'], sx = [-1, -1, 1, 1], sy = [-1, 1, -1, 1];
      const ex = zi => cx + sx[zi] * (W / 2 - M - 50), ey = zi => cy + sy[zi] * (H / 2 - M - 62);
      const pos = (zi, k) => { const f = .2 + .58 * k / (SEGS - 1); return [cx + (ex(zi) - cx) * f, cy + (ey(zi) - cy) * f] };
      const quad = zi => ({ x: sx[zi] < 0 ? 0 : cx, y: sy[zi] < 0 ? 0 : cy, w: sx[zi] < 0 ? cx : W - cx, h: sy[zi] < 0 ? cy : H - cy });
      const T0 = performance.now(), lanes = [[], [], [], []], flash = [0, 0, 0, 0], flashOk = [1, 1, 1, 1];
      let misses = 0, caught = 0, nextSpawn = T0 + 700, lastZ = -1, over = false;
      const lerp = (a, b, k) => a + (b - a) * k;

      function lose() { if (over) return; over = true; ctx.after(450, () => ctx.end({ won: false, score: caught })) }
      function miss(zi) { misses++; flash[zi] = performance.now(); flashOk[zi] = 0; if (misses >= LIVES) lose() }
      function press(zi, how, e) {
        if (over) return; const now = performance.now(), L = lanes[zi], s = L[0];
        const ok = !!(s && now >= s.openAt);
        if (ok) { L.shift(); caught++; ctx.score(caught); flash[zi] = now; flashOk[zi] = 1; ctx.sense.reaction(now - s.openAt, { ok: true }) }
        else if (s && now >= s.t0 + 2 * s.step) { flash[zi] = now; flashOk[zi] = 0 }   // рано: без штрафа
        else miss(zi);
        const ms = s ? Math.max(0, now - s.openAt) : 0;
        if (how === 'key') ctx.sense.key({ ms, ok });
        else { const q = quad(zi); ctx.sense.tap({ x: e.x, y: e.y, target: q, hit: ok }); ctx.sense.choice({ ms, ok }) }
      }
      ctx.on(stage, 'pointerdown', e => { const p = ctx.pt(e); press((p.x < cx ? 0 : 2) + (p.y < cy ? 0 : 1), 'tap', p) });
      ctx.onKey(k => { const zi = keys.indexOf(String(k).toLowerCase()); if (zi >= 0) press(zi, 'key') });

      // ---------- LCD: чернила, призрачные сегменты 8%, лайм-метка ----------
      const INK = '#20291d', GH = 'rgba(32,41,29,.08)', BLUE = pal.blue, RED = pal.red, LIME = pal.lime;
      const PIN = new Path2D('M7.5 0C3.4 0 0 3.3 0 7.4c0 5 6.3 10.8 6.6 11.1.5.4 1.3.4 1.8 0 .3-.3 6.6-6.1 6.6-11.1C15 3.3 11.6 0 7.5 0zm0 10.6a3.2 3.2 0 1 1 0-6.4 3.2 3.2 0 0 1 0 6.4z');
      const sc = Math.max(.85, Math.min(1.45, Math.min(W, H) / 400));
      const scan = (() => { const d = devicePixelRatio || 1, c = document.createElement('canvas'); c.width = W * d; c.height = H * d; const x = c.getContext('2d'); x.scale(d, d); x.fillStyle = 'rgba(32,41,29,.05)'; for (let y = 0; y < H; y += 3) x.fillRect(0, y, W, 1); return c })();
      function suitcase(x, y, lit, tilt) {                 // чемодан: корпус из трёх сегментов, ручка, колёсики, бирка
        g.save(); g.translate(x, y); g.scale(sc, sc); if (tilt) g.rotate(tilt);
        const col = lit ? INK : GH; g.fillStyle = col; g.strokeStyle = col;
        g.fillRect(-15, -10, 6, 22); g.fillRect(-7.5, -10, 15, 22); g.fillRect(9, -10, 6, 22);
        g.lineWidth = 2.6; g.lineJoin = 'round'; g.beginPath(); g.moveTo(-6, -10.5); g.lineTo(-6, -15.5); g.lineTo(6, -15.5); g.lineTo(6, -10.5); g.stroke();
        g.beginPath(); g.arc(-9, 14.5, 2.6, 0, 7); g.arc(9, 14.5, 2.6, 0, 7); g.fill();
        if (lit) { g.fillStyle = LIME; g.strokeStyle = INK; g.lineWidth = 1.4; g.beginPath(); g.roundRect(13, -3, 8, 12, 2); g.fill(); g.stroke();
          g.beginPath(); g.moveTo(15, -3); g.lineTo(15, -9); g.lineWidth = 1; g.stroke(); g.fillStyle = INK; g.beginPath(); g.arc(17, 0, 1, 0, 7); g.fill() }
        else { g.strokeStyle = GH; g.lineWidth = 1.4; g.beginPath(); g.roundRect(13, -3, 8, 12, 2); g.stroke() }
        g.restore();
      }
      function cart(x, y, state, open) {                   // тележка портье: платформа, стойка с ручкой, колёса
        g.save(); g.translate(x, y); g.scale(Math.max(.9, sc * .95), Math.max(.9, sc * .95));
        const fill = state === 2 ? RED : state === 1 ? LIME : open ? LIME : BLUE, line = state === 1 || open ? INK : (state === 2 ? INK : INK);
        g.fillStyle = fill; g.strokeStyle = INK; g.lineWidth = 2.2; g.lineJoin = 'round';
        g.beginPath(); g.roundRect(-30, 2, 60, 12, 4); g.fill(); g.stroke();                       // платформа
        g.beginPath(); g.moveTo(-24, 2); g.lineTo(-24, -18); g.lineTo(-14, -18); g.stroke();       // стойка и ручка
        g.beginPath(); g.moveTo(-24, -6); g.lineTo(18, -6); g.lineWidth = 1.6; g.stroke();
        g.fillStyle = INK; g.beginPath(); g.arc(-18, 18, 3.6, 0, 7); g.arc(18, 18, 3.6, 0, 7); g.fill();
        g.fillStyle = state === 2 ? INK : LCDM; g.fillRect(-10, 7, 20, 2);                         // сегментный зазор
        if (open) { g.fillStyle = INK; for (let i = -1; i <= 1; i++) { g.beginPath(); g.moveTo(i * 12 - 4, -12); g.lineTo(i * 12 + 4, -12); g.lineTo(i * 12, -6.5); g.fill() } }  // «ловим»
        g.restore();
      }
      const LCDM = '#cdeeb0';
      const pinI = (x, y, col) => { g.save(); g.translate(x - 7.5 * .9, y - 9); g.scale(.9, .9); g.fillStyle = col; g.fill(PIN); g.restore() };
      ctx.raf(() => {
        const now = performance.now(), el = now - T0, pr = Math.min(1, el / 25000);
        if (!over && el < 21500 && now >= nextSpawn) {
          const free = [0, 1, 2, 3].filter(i => lanes[i].every(s => now - s.t0 > 2 * s.step * 2 + 200) && i !== lastZ);
          if (free.length) { const zi = free[Math.random() * free.length | 0], step = lerp(470, 340, pr); lastZ = zi;
            lanes[zi].push({ t0: now, step, openAt: now + OPEN * step, missAt: now + SEGS * step }) }
          nextSpawn = now + lerp(1250, 880, pr) + Math.random() * 280;
        }
        for (let zi = 0; zi < 4; zi++) while (lanes[zi][0] && now >= lanes[zi][0].missAt) { lanes[zi].shift(); if (!over) miss(zi) }
        // отрисовка: LCD-окно на лаймовой подложке
        g.clearRect(0, 0, W, H);
        g.strokeStyle = 'rgba(32,41,29,.28)'; g.lineWidth = 1.5; g.beginPath(); g.roundRect(M, M, W - 2 * M, H - 2 * M, 14); g.stroke();
        for (let zi = 0; zi < 4; zi++) {                                  // жёлоб: призрачные чемоданы, ближние к углу чуть ярче
          for (let k = 0; k < SEGS; k++) { const [x, y] = pos(zi, k); suitcase(x, y, false) }
          g.strokeStyle = GH; g.lineWidth = 2; g.setLineDash([2, 6]); g.beginPath(); g.moveTo(cx, cy); g.lineTo(ex(zi), ey(zi)); g.stroke(); g.setLineDash([]);
        }
        for (let zi = 0; zi < 4; zi++) {
          const s = lanes[zi][0], fl = now - flash[zi] < 220, open = s && now >= s.openAt;
          cart(ex(zi), ey(zi), fl ? (flashOk[zi] ? 1 : 2) : 0, open);
          for (const c of lanes[zi]) { const k = Math.min(SEGS - 1, Math.floor((now - c.t0) / c.step)), [x, y] = pos(zi, k); suitcase(x, y, true, (k % 2 ? .06 : -.06)) }
        }
        g.fillStyle = INK; g.strokeStyle = INK; g.lineWidth = 2;                       // ресепшн: звонок
        g.beginPath(); g.arc(cx, cy + 2, 11 * sc, Math.PI, 0); g.fill(); g.fillRect(cx - 14 * sc, cy + 3, 28 * sc, 4); g.fillRect(cx - 1.5, cy - 12 * sc - 4, 3, 4);
        pinI(cx, cy - 22 * sc - 6, BLUE);
        for (let i = 0; i < LIVES; i++) {                                              // потери: метки-пины, потерянная краснеет с крестом
          const x = cx + (i - 1) * 26, y = M + 24;
          if (i < misses) { pinI(x, y, GH); g.strokeStyle = RED; g.lineWidth = 3; g.beginPath(); g.moveTo(x - 6, y - 6); g.lineTo(x + 6, y + 6); g.moveTo(x + 6, y - 6); g.lineTo(x - 6, y + 6); g.stroke() }
          else pinI(x, y, BLUE);
        }
        g.drawImage(scan, 0, 0, W, H);
      });
      return { stop() { }, timeUp() { return { won: misses < LIVES, score: caught } } };
    },
  });
})();
