/* Городки на гальке: зажать, отпустить в зелёной зоне шкалы, сбить башенку из 5 камешков за 3 броска. Сигнал: hold. */
(function () {
  Arcade.register({
    id: 'gorodki-galka', title: 'Городки на гальке', era: 'ussr', icon: '🪨', duration: 20,
    rules: 'Зажми, пока шкала не позеленеет, и отпусти. Собьёшь башенку из гальки?',
    win: 'Башенка разлетелась. Меткий глаз.', lose: 'Мимо. Галька катится дальше, море ждёт.',
    primitives: ['hold'],
    start(stage, ctx) {
      const { w, h, pal } = ctx, { canvas, g } = ctx.canvas();
      const GY = h * .56, SX = w * .76, BX = w * .15, SH = 28, SW = Math.min(52, w * .13);
      const C = .62, HALF = .11, SWEEP = 1300;                       // центр и полуширина зелёной зоны, мс на проход шкалы
      const bar = { x: 24, y: h * .8, w: w - 48, h: 32 };
      const pebbles = Array.from({ length: 46 }, () => ({ x: Math.random() * w, y: GY + 14 + Math.random() * (h * .2), r: 2 + Math.random() * 5, a: Math.random() * 3 }));
      let st = 'idle', t0 = 0, pos = 0, throws = 3, left = 5, ball = null, bits = [], flash = null, down = false, done = false;
      const calc = now => { const ph = ((now - t0) / SWEEP) % 2; return ph < 1 ? ph : 2 - ph };

      function press() { if (st !== 'idle' || down) return; down = true; st = 'charge'; t0 = performance.now() }
      function release() {
        if (!down) return; down = false; if (st !== 'charge') return;
        const got = performance.now() - t0, p = calc(performance.now());
        // ближайший момент прохождения центра зоны: C*SWEEP + 2k*SWEEP или (2-C)*SWEEP + 2k*SWEEP
        let want = Infinity; for (let k = 0; k < 4; k++) for (const b of [C * SWEEP, (2 - C) * SWEEP]) { const v = b + 2 * k * SWEEP; if (Math.abs(v - got) < Math.abs(want - got)) want = v }
        ctx.sense.hold({ wantMs: want, gotMs: got });
        const d = Math.abs(p - C), q = d <= HALF ? 1 - d / HALF : 0;
        const k = d <= HALF ? (q >= .4 ? 3 : 2) : d <= HALF + .12 ? 1 : 0;
        const tx = k ? SX - SW / 2 - 8 : p < C ? BX + (SX - BX) * (.3 + .45 * p / C) : w + 40;
        ball = { u: 0, tx, k, p }; st = 'fly'; throws--; pos = p;
      }
      function land() {
        const k = Math.min(ball.k, left);
        for (let i = left - k; i < left; i++) bits.push({ x: SX, y: GY - (i + 1) * SH, vx: 120 + Math.random() * 220, vy: -180 - Math.random() * 220, r: 0, vr: 4 + Math.random() * 6, i });
        left -= k; ctx.score(5 - left);
        flash = { t: 0, s: k ? '+' + k : 'мимо' }; ball = null;
        if (left === 0) { st = 'over'; ctx.after(1000, () => ctx.end({ won: true, score: 5 })) }
        else if (throws === 0) { st = 'over'; ctx.after(1000, () => ctx.end({ won: false, score: 5 - left })) }
        else ctx.after(600, () => { st = 'idle' });
      }

      ctx.on(stage, 'pointerdown', e => { e.preventDefault(); press() });
      ctx.on(window, 'pointerup', release); ctx.on(window, 'pointercancel', release);
      ctx.onKey((k, e) => { if (k === ' ' && !e.repeat) press() });
      ctx.on(window, 'keyup', e => { if (e.key === ' ') release() });

      // ---------- LCD: статичный слой (море-штриховка, галечный пляж, растр) рисуется один раз ----------
      const INK = '#20291d', GH = 'rgba(32,41,29,.08)', BLUE = pal.blue, LIME = pal.lime, RED = pal.red, FONT = '"PT Root UI",system-ui,sans-serif';
      const PIN = new Path2D('M7.5 0C3.4 0 0 3.3 0 7.4c0 5 6.3 10.8 6.6 11.1.5.4 1.3.4 1.8 0 .3-.3 6.6-6.1 6.6-11.1C15 3.3 11.6 0 7.5 0zm0 10.6a3.2 3.2 0 1 1 0-6.4 3.2 3.2 0 0 1 0 6.4z');
      const dpr = devicePixelRatio || 1, bgc = document.createElement('canvas'); bgc.width = w * dpr; bgc.height = h * dpr;
      (function () {
        const x = bgc.getContext('2d'); x.scale(dpr, dpr);
        x.strokeStyle = 'rgba(32,41,29,.2)'; x.lineWidth = 1.2;                                      // море: волновая штриховка
        for (let r = 0, y = 70; y < GY - 74; r++, y += 12) for (let px = (r % 2) * 11 + 2; px < w - 8; px += 22) { x.beginPath(); x.moveTo(px, y); x.quadraticCurveTo(px + 5.5, y - 5, px + 11, y); x.quadraticCurveTo(px + 16.5, y + 4, px + 22, y); x.stroke() }
        x.fillStyle = 'rgba(32,41,29,.12)'; x.fillRect(0, GY - 70, w, 3); x.fillStyle = INK; x.fillRect(0, GY - 62, w, 2);         // кромка воды и горизонт
        x.fillStyle = 'rgba(32,41,29,.34)'; pebbles.forEach(b => { x.beginPath(); x.ellipse(b.x, b.y, b.r * 1.4, b.r, b.a, 0, 7); x.fill() });       // галька
        x.fillStyle = INK; x.fillRect(0, GY, w, 2.5);                                                 // земля
        x.strokeStyle = 'rgba(32,41,29,.3)'; x.lineWidth = 2; x.setLineDash([4, 4]); x.strokeRect(SX - SW * 1.15, GY - SH * 5 - 8, SW * 2.3, SH * 5 + 8); x.setLineDash([]);   // «город»
        x.fillStyle = INK; x.fillRect(BX + 42, GY - 14, 3, 14); x.fillRect(BX + 42, GY + 6, 3, 8);   // линия кона
        x.fillStyle = 'rgba(32,41,29,.05)'; for (let y = 0; y < h; y += 3) x.fillRect(0, y, w, 1);   // растр
      })();
      function stone(x, y, i, col) {                    // фигура «города»: чурка с лаймовым пояском
        const c = col || INK; g.fillStyle = c; g.beginPath(); g.roundRect(x - SW / 2, y + 1, SW, SH - 4, 6); g.fill();
        if (!col) { g.fillStyle = i % 2 ? LIME : BLUE; g.fillRect(x - SW / 2 + 3, y + SH / 2 - 3, SW - 6, 4) }
      }
      function bat(x, y, a, col, k) {                      // бита: тонкая рукоять и утолщённый бой
        g.save(); g.translate(x, y); g.rotate(a); if (k) g.scale(k, k); g.fillStyle = col;
        g.beginPath(); g.roundRect(-28, -3, 42, 6, 3); g.fill(); g.beginPath(); g.roundRect(8, -5, 22, 10, 5); g.fill();
        g.fillStyle = LIME; g.fillRect(-12, -3, 4, 6); g.restore();
      }
      function gull(x, y, f) {                          // чайка: силуэт-галочка с махом крыльев
        g.fillStyle = INK; g.strokeStyle = INK; g.lineWidth = 3; g.lineCap = 'round'; g.beginPath();
        g.moveTo(x - 18, y - 4 + f * 7); g.quadraticCurveTo(x - 9, y - 12 - f * 4, x, y); g.quadraticCurveTo(x + 9, y - 12 - f * 4, x + 18, y - 4 + f * 7); g.stroke(); g.lineCap = 'butt';
        g.beginPath(); g.ellipse(x, y + 1, 4, 2.6, 0, 0, 7); g.fill();
      }
      ctx.raf((dt, now) => {
        g.clearRect(0, 0, w, h); g.drawImage(bgc, 0, 0, w, h);
        gull(((now * .035) % (w + 100)) - 50, 78 + Math.sin(now / 900) * 8, Math.sin(now / 130));
        for (let i = 5; i > left; i--) { g.fillStyle = GH; g.beginPath(); g.roundRect(SX - SW / 2, GY - i * SH + 1, SW, SH - 4, 6); g.fill() }   // призраки сбитых
        for (let i = 0; i < left; i++) stone(SX, GY - (i + 1) * SH, i);
        g.save(); g.translate(SX - 7.5, GY - left * SH - 32); g.fillStyle = BLUE; g.fill(PIN); g.restore();      // пин: цель
        bits = bits.filter(b => b.y < h + 30); bits.forEach(b => { const s = dt / 1000; b.vy += 900 * s; b.x += b.vx * s; b.y += b.vy * s; b.r += b.vr * s;
          if (b.y > GY - SH + 3 && b.vy > 0) { b.y = GY - SH + 3; b.vy *= -.35; b.vx *= .8 }
          g.save(); g.translate(b.x, b.y + SH / 2); g.rotate(b.r); g.translate(-b.x, -b.y - SH / 2); stone(b.x, b.y, b.i); g.restore() });
        const bx0 = BX, by0 = GY - 14;
        if (ball) { ball.u = Math.min(1, ball.u + dt / 520); const u = ball.u, bx = bx0 + (ball.tx - bx0) * u, by = by0 - 110 * Math.sin(Math.PI * u) * (ball.k ? 1 : .8);
          bat(bx, by, u * 9, BLUE); if (u >= 1) land() }
        else if (st !== 'over') bat(bx0 + 8, by0 + 2, -.55, BLUE);
        // шкала: сегментный индикатор, зелёная зона обведена
        if (st === 'charge') pos = calc(now);
        const NS = Math.max(18, Math.floor(bar.w / 13)), sw = bar.w / NS, lit = Math.round(pos * (NS - 1));
        g.strokeStyle = INK; g.lineWidth = 2; g.beginPath(); g.roundRect(bar.x - 4, bar.y - 4, bar.w + 8, bar.h + 8, 8); g.stroke();
        for (let i = 0; i < NS; i++) {
          const f = (i + .5) / NS, zone = Math.abs(f - C) <= HALF, x = bar.x + i * sw + 1;
          if (zone) { g.fillStyle = LIME; g.fillRect(x, bar.y, sw - 2, bar.h); g.strokeStyle = INK; g.lineWidth = 1.2; g.strokeRect(x + .6, bar.y + .6, sw - 3.2, bar.h - 1.2) }
          const on = st === 'charge' ? i <= lit : i === lit;
          if (on) { g.fillStyle = INK; g.fillRect(x, bar.y + (zone ? 6 : 0), sw - 2, zone ? bar.h - 12 : bar.h) }
          else if (!zone) { g.fillStyle = GH; g.fillRect(x, bar.y, sw - 2, bar.h) }
        }
        const rx = bar.x + bar.w * pos; g.fillStyle = BLUE; g.beginPath(); g.moveTo(rx - 7, bar.y - 12); g.lineTo(rx + 7, bar.y - 12); g.lineTo(rx, bar.y - 3); g.fill();
        g.fillStyle = INK; g.font = '700 14px ' + FONT; g.textAlign = 'center';
        g.fillText(st === 'charge' ? 'Отпусти в зелёной зоне' : 'Зажми экран или Пробел', w / 2, bar.y + bar.h + 28);
        g.textAlign = 'left'; g.font = '700 13px ' + FONT; g.fillText('БРОСКИ', 16, 28);
        for (let i = 0; i < 3; i++) bat(118 + i * 34, 24, -.35, i < throws ? INK : GH, .5);
        g.textAlign = 'right'; g.fillText('ГАЛЬКА', w - 24 - 5 * 15, 28);
        for (let i = 0; i < 5; i++) { g.fillStyle = i < left ? INK : GH; g.beginPath(); g.roundRect(w - 16 - (5 - i) * 15 + 2, 17, 11, 14, 3); g.fill() }
        if (flash) { flash.t += dt; if (flash.t > 900) flash = null; else { g.globalAlpha = 1 - flash.t / 900; g.textAlign = 'center'; g.font = '800 34px ' + FONT; g.fillStyle = flash.s === 'мимо' ? RED : BLUE;
          g.fillText(flash.s, w / 2, GY - 150 - flash.t * .03); g.globalAlpha = 1 } }
      });
      return { stop() { }, timeUp() { return { won: left === 0, score: 5 - left } } };
    }
  });
})();
