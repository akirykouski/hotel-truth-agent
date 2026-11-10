/* Чайка над набережной (Flappy-style). Выжить 25 с между зонтиками. */
(function () {
  Arcade.register({
    id: 'chaika-flappy', title: 'Чайка над набережной', era: 'world', icon: '🕊️', duration: 25,
    rules: 'Тапай в своём ритме: чайка летит между зонтиками. Не задень.',
    win: 'Пролетела над всеми. Чайка довольна.',
    lose: 'Зонтик оказался ближе. Попробуем ещё?',
    primitives: ['rhythm'],
    start(stage, ctx) {
      const { canvas, g } = ctx.canvas(), W = ctx.w, H = ctx.h, P = ctx.pal;
      const SEA = 54, GRAV = H * 1.5, FLAP = -H * .5, SPEED = 125, GAP = Math.max(215, H * .37), PW = 58, DOME = 26, POLE = 12, R = 13, BX = W * .3, SPACE = 235;
      let y = H * .4, vy = 0, started = false, dead = false, passed = 0, dist = 0, lastFlap = 0, gapY = H * .45;
      const pipes = [], ints = [], clouds = [[W * .2, H * .15, 1], [W * .7, H * .3, .7], [W * .45, H * .08, .5]];
      const med = a => { const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2 };
      function spawn(x) {
        gapY = Math.max(GAP / 2 + 50, Math.min(H - SEA - GAP / 2 - 50, gapY + (Math.random() - .5) * 220));
        pipes.push({ x, gy: gapY, c: pipes.length % 2 ? P.lime : P.purple, ok: false });
      }
      function flap() {
        if (dead) return; const t = performance.now();
        if (!started) { started = true; spawn(W + 40) }
        else if (lastFlap) { const d = t - lastFlap; if (ints.length >= 3) ctx.sense.rhythm({ wantMs: med(ints), gotMs: d }); ints.push(d); if (ints.length > 8) ints.shift() }
        lastFlap = t; vy = FLAP;
      }
      ctx.on(stage, 'pointerdown', e => { e.preventDefault(); flap() });
      ctx.onKey((k, e) => { if (k === ' ' || k === 'ArrowUp') { e.preventDefault(); flap() } });
      const hitRect = (x, y0, w, h) => { const cx = Math.max(x, Math.min(BX, x + w)), cy = Math.max(y0, Math.min(y, y0 + h)); return Math.hypot(BX - cx, y - cy) < R };
      const INK = '#20291d', LCD = '#cdeeb0', LIME = '#acef81', BLUE = P.blue, dpr = devicePixelRatio || 1;
      const tex = document.createElement('canvas'); tex.width = Math.max(1, W * dpr); tex.height = Math.max(1, H * dpr);
      { const t = tex.getContext('2d'); t.fillStyle = 'rgba(32,41,29,.06)'; const st = Math.round(3 * dpr); for (let i = 0; i < tex.height; i += st) t.fillRect(0, i, tex.width, Math.max(1, dpr * .6)); for (let i = 0; i < tex.width; i += st) t.fillRect(i, 0, Math.max(1, dpr * .6), tex.height) }
      const skyline = [[0, 34], [26, 58], [52, 40], [74, 70], [100, 46], [128, 62], [150, 36], [176, 54]], SKW = 200;
      function pin(cx, cy, k = 1) { g.save(); g.translate(cx, cy); g.scale(k, k); g.fillStyle = LIME; g.strokeStyle = INK; g.lineWidth = 1.5; g.beginPath(); g.moveTo(0, 0); g.bezierCurveTo(-8, -7, -5, -15, 0, -15); g.bezierCurveTo(5, -15, 8, -7, 0, 0); g.fill(); g.stroke(); g.fillStyle = INK; g.beginPath(); g.arc(0, -9, 1.8, 0, 7); g.fill(); g.restore() }
      // верхнее препятствие: мачта + блок отеля с окнами (cap = зона DOME, cy = верх блока)
      function tower(cx, cy) { const r = PW / 2 - 3; g.fillStyle = INK; g.fillRect(cx - r, cy, r * 2, DOME);
        g.fillStyle = LCD; for (let i = 0; i < 4; i++) { g.fillRect(cx - r + 5 + i * (r * 2 - 8) / 4, cy + 5, 6, 7); g.fillRect(cx - r + 5 + i * (r * 2 - 8) / 4, cy + 15, 6, 5) }
        g.fillStyle = LIME; g.fillRect(cx - r + 5 + (r * 2 - 8) / 4 * 2, cy + 5, 6, 7); g.fillStyle = INK; g.fillRect(cx - r - 3, cy + DOME - 4, r * 2 + 6, 4); pin(cx, cy - 12, .9) }
      // нижнее препятствие: пальма (ствол-сегменты + крона)
      function palm(cx, cy) { const r = PW / 2; g.strokeStyle = INK; g.lineCap = 'round'; g.lineWidth = 3.5;
        for (let i = -1; i <= 1; i += 2) { g.beginPath(); g.moveTo(cx, cy + DOME * .4); g.quadraticCurveTo(cx + i * r * .55, cy - 2, cx + i * (r - 3), cy + DOME * .8); g.stroke() }
        g.beginPath(); g.moveTo(cx, cy + DOME * .4); g.quadraticCurveTo(cx, cy, cx, cy - 1); g.stroke();
        for (let i = -1; i <= 1; i += 2) { g.beginPath(); g.moveTo(cx, cy + DOME * .5); g.quadraticCurveTo(cx + i * r * .3, cy + 1, cx + i * r * .85, cy + DOME * .35); g.stroke() }
        g.fillStyle = INK; g.beginPath(); g.arc(cx, cy + DOME * .5, 4, 0, 7); g.fill(); g.fillStyle = LCD; g.fillRect(cx - POLE / 2 + 3, cy + DOME + 6, POLE - 6, 2); g.lineCap = 'butt' }
      function gull(flapT) { // чайка: туловище, хвост, голова с клювом, крыло машет
        const w = Math.sin(flapT * 22) * 9;
        g.fillStyle = BLUE; g.strokeStyle = INK; g.lineWidth = 2; g.lineJoin = 'round';
        g.beginPath(); g.moveTo(-4, -1); g.lineTo(-14 + w * .3, -12 - w); g.lineTo(5, -3); g.closePath(); g.fill(); g.stroke();          // дальнее крыло
        g.fillStyle = '#eef9e0'; g.beginPath(); g.moveTo(-17, 2); g.lineTo(-10, -3); g.quadraticCurveTo(2, -7, 11, -2); g.quadraticCurveTo(12, 5, 0, 7); g.quadraticCurveTo(-10, 7, -17, 2); g.fill(); g.stroke();   // тело
        g.beginPath(); g.arc(12, -3, 5, 0, 7); g.fill(); g.stroke();                                                                      // голова
        g.fillStyle = INK; g.beginPath(); g.moveTo(16, -4); g.lineTo(22, -2); g.lineTo(16, -1); g.fill(); g.beginPath(); g.arc(13, -4, 1.2, 0, 7); g.fill();
        g.fillStyle = BLUE; g.beginPath(); g.moveTo(-6, 0); g.lineTo(-12 + w * .3, 12 + w * .8); g.lineTo(6, 2); g.closePath(); g.fill(); g.stroke();   // ближнее крыло
      }
      ctx.raf(dt => {
        dt /= 1000; const t = performance.now() / 1000;
        if (started && !dead) {
          vy += GRAV * dt; y += vy * dt; if (y < R) { y = R; vy = Math.max(vy, 0) }
          pipes.forEach(p => p.x -= SPEED * dt); dist += SPEED * dt;
          if (pipes.length && pipes[0].x < -PW) pipes.shift();
          const L = pipes[pipes.length - 1]; if (!L || L.x < W - SPACE) spawn(W + PW);
          for (const p of pipes) {
            const x0 = p.x - PW / 2, top = p.gy - GAP / 2, bot = p.gy + GAP / 2;
            if (hitRect(x0, 0, PW, top) && (hitRect(p.x - POLE / 2, 0, POLE, top - DOME) || hitRect(x0 + 3, top - DOME, PW - 6, DOME)) ||
                hitRect(p.x - POLE / 2, bot + DOME, POLE, H) || hitRect(x0 + 3, bot, PW - 6, DOME)) { dead = true; break }
            if (!p.ok && p.x < BX) { p.ok = true; ctx.score(++passed) }
          }
          if (y > H - SEA - R) dead = true;
          if (dead) ctx.after(250, () => ctx.end({ won: false, score: passed }));
        } else if (!started) y = H * .4 + Math.sin(t * 4) * 8;
        // ---- рисование ----
        g.fillStyle = LCD; g.fillRect(0, 0, W, H);
        g.fillStyle = 'rgba(32,41,29,.08)';                                                                                      // призрачный город (параллакс)
        const off = (dist * .25) % SKW; for (let x0 = -off; x0 < W; x0 += SKW) skyline.forEach(([sx, sh]) => g.fillRect(x0 + sx, H - SEA - sh, 22, sh));
        clouds.forEach(c => { c[0] -= 12 * c[2] * dt; if (c[0] < -70) c[0] = W + 70; const r = 16 * c[2] + 10;
          g.beginPath(); g.arc(c[0], c[1], r, 0, 7); g.arc(c[0] + r, c[1] + 4, r * .8, 0, 7); g.arc(c[0] - r, c[1] + 6, r * .7, 0, 7); g.fill() });
        pipes.forEach(p => { const top = p.gy - GAP / 2, bot = p.gy + GAP / 2;
          g.fillStyle = INK; g.fillRect(p.x - POLE / 2, 0, POLE, top - DOME); g.fillRect(p.x - POLE / 2, bot + DOME, POLE, H);
          tower(p.x, top - DOME); palm(p.x, bot) });
        g.fillStyle = BLUE; g.fillRect(0, H - SEA, W, SEA);
        g.strokeStyle = LIME; g.lineWidth = 2; g.beginPath();
        for (let x = 0; x <= W; x += 6) g.lineTo(x, H - SEA + 8 + Math.sin((x + dist) / 14) * 3); g.stroke();
        g.strokeStyle = INK; g.lineWidth = 2; g.beginPath(); g.moveTo(0, H - SEA); g.lineTo(W, H - SEA); g.stroke();
        g.save(); g.translate(BX, y); g.rotate(Math.max(-.5, Math.min(.9, vy / (H * .9)))); gull(vy < 0 ? performance.now() / 1000 : 0.04); g.restore();
        g.drawImage(tex, 0, 0, W, H);
        if (!started) { g.fillStyle = INK; g.font = '600 18px system-ui,sans-serif'; g.textAlign = 'center'; g.fillText('Тап или пробел: взмах', W / 2, H * .62) }
      });
      ctx.score(0);
      return { stop() { }, timeUp() { return { won: !dead, score: passed } } };
    }
  });
})();
