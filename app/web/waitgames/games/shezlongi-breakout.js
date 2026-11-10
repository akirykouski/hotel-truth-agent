/* Шезлонги: пробей волны (Breakout). */
(function () {
  Arcade.register({
    id: 'shezlongi-breakout', title: 'Шезлонги: пробей волны', era: 'world', icon: '🏖️', duration: 30,
    rules: 'Води шезлонг пальцем или мышью и отбивай гальку. Пробей волны.',
    win: 'Волны пробиты. Море открыто для вас.',
    lose: 'Галька улетела в море. Шезлонг ни при чём.',
    primitives: ['track', 'drag'],
    start(stage, ctx) {
      const { canvas, g } = ctx.canvas(), W = ctx.w, H = ctx.h, P = ctx.pal;
      const COLS = 6, ROWS = 3, M = 14, GAP = 5, BW = (W - 2 * M - GAP * (COLS - 1)) / COLS, BH = 22, TOP = 56;
      const PWD = Math.max(80, W * .22), PH = 14, PY = H - 52, R = 7, SPD = Math.max(400, H * .78);
      const INK = '#20291d', LCD = '#cdeeb0', LIME = '#acef81', BLUE = P.blue, dpr = devicePixelRatio || 1;
      const tex = document.createElement('canvas'); tex.width = Math.max(1, W * dpr); tex.height = Math.max(1, H * dpr);
      { const t = tex.getContext('2d'); t.fillStyle = 'rgba(32,41,29,.06)'; const st = Math.round(3 * dpr); for (let i = 0; i < tex.height; i += st) t.fillRect(0, i, tex.width, Math.max(1, dpr * .6)); for (let i = 0; i < tex.width; i += st) t.fillRect(i, 0, Math.max(1, dpr * .6), tex.height) }
      const bricks = []; for (let r = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++)
        bricks.push({ x: M + c * (BW + GAP), y: TOP + r * (BH + GAP) + Math.sin(c * .9 + r) * 4, col: (r + c) % 2 ? P.lime : P.blue, alive: true });
      let px = W / 2, tx = W / 2, lives = 3, broke = 0, serve = performance.now() + 700, trail = [];
      const ball = { x: W / 2, y: PY - R - 2, vx: 0, vy: 0, on: true };
      const setT = e => { tx = Math.max(PWD / 2, Math.min(W - PWD / 2, ctx.pt(e).x)) };
      ctx.on(stage, 'pointermove', e => { setT(e); sampleDrag(e) });
      ctx.on(stage, 'pointerdown', e => { setT(e); seg = null });
      let keys = 0;
      ctx.onKey((k, e) => { if (k === 'ArrowLeft') keys = -1; if (k === 'ArrowRight') keys = 1 });
      ctx.on(window, 'keyup', e => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') keys = 0 });
      // drag: непрерывный отрезок движения в одну сторону, отправляем при развороте (не чаще раза в 0,7 с)
      let seg = null, lastD = 0;
      function sampleDrag(e) {
        const p = ctx.pt(e), t = performance.now();
        if (!seg) return void (seg = { path: [[p.x, p.y, t]], dir: 0 });
        const a = seg.path[seg.path.length - 1], dx = p.x - a[0]; if (Math.abs(dx) < 2) return;
        const d = Math.sign(dx); if (seg.dir && d !== seg.dir && Math.abs(a[0] - seg.path[0][0]) > 40) { flush(); seg = { path: [[a[0], a[1], a[2]]], dir: d } }
        else if (seg.dir && d !== seg.dir) seg.dir = d; else seg.dir = d;
        if (t - a[2] > 30) seg.path.push([p.x, p.y, t]);
      }
      function flush() { const t = performance.now(); if (seg && seg.path.length > 4 && t - lastD > 700) { lastD = t; ctx.sense.drag({ path: seg.path }) } }
      ctx.every(250, () => { if (!ball.on && ball.vy > 0 && ball.y > H * 2 / 3) ctx.sense.track({ errPx: Math.abs(px - ball.x), sizePx: PWD }) });
      const launch = () => { const a = (Math.random() - .5) * .9; ball.vx = SPD * Math.sin(a); ball.vy = -SPD * Math.cos(a); ball.on = false };
      ctx.score(0);
      const finishIf = () => { if (broke === bricks.length) ctx.end({ won: true, score: broke }) };
      ctx.raf(dt => {
        dt /= 1000; const now = performance.now();
        px += (tx - px) * Math.min(1, dt * 30); if (keys) { tx = Math.max(PWD / 2, Math.min(W - PWD / 2, tx + keys * W * 1.1 * dt)) }
        if (ball.on) { ball.x = px; ball.y = PY - R - 2; if (now > serve) launch() }
        else for (let s = 0; s < 3; s++) {
          const d = dt / 3; ball.x += ball.vx * d; ball.y += ball.vy * d;
          if (ball.x < R) { ball.x = R; ball.vx = Math.abs(ball.vx) } if (ball.x > W - R) { ball.x = W - R; ball.vx = -Math.abs(ball.vx) }
          if (ball.y < R) { ball.y = R; ball.vy = Math.abs(ball.vy) }
          if (ball.vy > 0 && ball.y + R >= PY && ball.y + R <= PY + PH + 8 && Math.abs(ball.x - px) <= PWD / 2 + R) {       // шезлонг: угол зависит от точки удара
            const k = Math.max(-1, Math.min(1, (ball.x - px) / (PWD / 2))), a = k * 1.0; ball.vx = SPD * Math.sin(a); ball.vy = -SPD * Math.cos(a); ball.y = PY - R }
          for (const b of bricks) if (b.alive && ball.x + R > b.x && ball.x - R < b.x + BW && ball.y + R > b.y && ball.y - R < b.y + BH) {
            b.alive = false; broke++; ctx.score(broke);
            const ox = Math.min(ball.x + R - b.x, b.x + BW - (ball.x - R)), oy = Math.min(ball.y + R - b.y, b.y + BH - (ball.y - R));
            if (ox < oy) ball.vx = -ball.vx; else ball.vy = -ball.vy; break;
          }
          if (ball.y > H + R) { lives--; trail = []; if (lives <= 0) return ctx.end({ won: false, score: broke }); ball.on = true; ball.vx = ball.vy = 0; serve = now + 900; break }
        }
        if (!ball.on) { trail.push([ball.x, ball.y]); if (trail.length > 14) trail.shift() }
        finishIf();
        // ---- рисование ----
        g.fillStyle = LCD; g.fillRect(0, 0, W, H);
        g.fillStyle = INK; g.globalAlpha = .08; g.beginPath(); for (let i = 0; i < ROWS * COLS; i++) { const c = i % COLS, r = (i / COLS) | 0; g.roundRect(M + c * (BW + GAP), TOP + r * (BH + GAP) + Math.sin(c * .9 + r) * 4, BW, BH, 4) } g.fill(); g.globalAlpha = 1;   // призрачные сегменты
        g.globalAlpha = .12; g.strokeStyle = INK; g.lineWidth = 2; g.beginPath(); for (let x = 0; x <= W; x += 6) g.lineTo(x, H - 16 + Math.sin(x / 14 + now / 600) * 3); g.stroke(); g.globalAlpha = 1;
        bricks.forEach((b, i) => { if (!b.alive) return; const x = b.x, y = b.y;
          if (((i / COLS | 0) + i % COLS) % 2) {                                                  // зонтик: купол с дольками + ручка
            g.fillStyle = INK; g.beginPath(); g.moveTo(x, y + BH - 5); g.quadraticCurveTo(x + BW / 2, y - BH * .75, x + BW, y + BH - 5); g.closePath(); g.fill();
            g.fillStyle = LIME; for (let k = 0; k < 3; k++) { const x0 = x + BW * (k * 2 + .5) / 6; g.beginPath(); g.moveTo(x0, y + BH - 5); g.quadraticCurveTo(x0 + BW / 12, y + 3, x0 + BW / 6 + 2, y + BH - 5); g.fill() }
            g.fillStyle = INK; g.fillRect(x + BW / 2 - 1, y + BH - 6, 2.4, 7) }
          else {                                                                                  // пляжное полотенце: полоски и бахрома
            g.fillStyle = BLUE; g.beginPath(); g.roundRect(x, y + 2, BW, BH - 4, 2); g.fill();
            g.fillStyle = LIME; g.fillRect(x, y + BH * .3, BW, 3); g.fillRect(x, y + BH * .6, BW, 3);
            g.fillStyle = INK; for (let fx = x + 2; fx < x + BW; fx += 4) { g.fillRect(fx, y, 1.4, 3); g.fillRect(fx, y + BH - 3, 1.4, 3) } } });
        g.strokeStyle = INK; g.globalAlpha = .28; g.lineWidth = 2; g.setLineDash([2, 5]); g.beginPath(); trail.forEach((p, i) => i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
        // шезлонг: каркас + синий холст сиденья + наклонная спинка + ножки
        g.lineCap = 'round'; g.lineJoin = 'round'; g.strokeStyle = INK; g.lineWidth = 3;
        g.beginPath(); g.moveTo(px - PWD / 2 + 8, PY + PH); g.lineTo(px - PWD / 2 + 14, PY + PH + 9); g.moveTo(px + PWD / 2 - 8, PY + PH); g.lineTo(px + PWD / 2 - 14, PY + PH + 9); g.stroke();
        g.fillStyle = BLUE; g.beginPath(); g.roundRect(px - PWD / 2, PY, PWD, PH, 4); g.fill(); g.lineWidth = 2; g.stroke();
        g.fillStyle = LIME; for (let k = 1; k < 5; k++) g.fillRect(px - PWD / 2 + PWD * k / 5 - 2, PY + 2, 4, PH - 4);
        g.lineWidth = 6; g.strokeStyle = INK; g.beginPath(); g.moveTo(px - PWD / 2 + 3, PY + 3); g.lineTo(px - PWD / 2 + 20, PY - 13); g.stroke();
        g.lineWidth = 3; g.strokeStyle = BLUE; g.beginPath(); g.moveTo(px - PWD / 2 + 3, PY + 3); g.lineTo(px - PWD / 2 + 20, PY - 13); g.stroke(); g.lineCap = 'butt';
        // мяч-пляжный: 4 дольки
        g.save(); g.translate(ball.x, ball.y); g.rotate(now / 260); [BLUE, '#eef9e0', LIME, '#eef9e0'].forEach((c, k) => { g.fillStyle = c; g.beginPath(); g.moveTo(0, 0); g.arc(0, 0, R, k * Math.PI / 2, (k + 1) * Math.PI / 2); g.fill() });
        g.fillStyle = INK; g.beginPath(); g.arc(0, 0, 1.6, 0, 7); g.fill(); g.restore(); g.strokeStyle = INK; g.lineWidth = 1.8; g.beginPath(); g.arc(ball.x, ball.y, R, 0, 7); g.stroke();
        for (let i = 0; i < 3; i++) { g.globalAlpha = i < lives ? 1 : .1; g.fillStyle = INK; g.beginPath(); g.arc(W - 20 - i * 18, 28, 6, 0, 7); g.fill() } g.globalAlpha = 1;
        g.fillStyle = INK; g.font = '700 14px system-ui,sans-serif'; g.textAlign = 'left'; g.fillText(`Волны: ${broke}/${bricks.length}`, M, 32);
        g.drawImage(tex, 0, 0, W, H);
      });
      return { stop() { flush() }, timeUp() { return { won: broke / bricks.length >= .7, score: broke } } };
    }
  });
})();
