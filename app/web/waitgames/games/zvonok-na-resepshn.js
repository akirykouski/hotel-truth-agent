/* Звонок на ресепшн (whack-a-mole, go/no-go). */
(function () {
  Arcade.register({
    id: 'zvonok-na-resepshn', title: 'Звонок на ресепшн', era: 'world', icon: '🔔', duration: 20,
    rules: 'Жми на звонок, пока он не спрятался. Табличку «не беспокоить» не трогай.',
    win: 'Все гости обслужены. Ресепшн сияет.',
    lose: 'Разбудил тех, кого не надо. Тише.',
    primitives: ['reaction', 'tap'],
    start(stage, ctx) {
      const P = ctx.pal, NEED = 10;
      const BELL = '<svg viewBox="0 0 60 60" fill="none" stroke="#20291d" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="30" cy="50" rx="24" ry="5" fill="#20291d"/><path d="M10 46a20 20 0 0 1 40 0z" fill="#acef81"/><path d="M18 36a13 13 0 0 1 8-9" stroke-width="2"/><g class="zv-btn"><rect x="28" y="19" width="4" height="7" fill="#0b4ec2"/><ellipse cx="30" cy="18" rx="6" ry="3.4" fill="#0b4ec2"/></g><g class="zv-tk"><path d="M12 14l-5-4M48 14l5-4M6 24H1M54 24h5"/></g></svg>';
      const st = document.createElement('style');
      const INK = '#20291d', LCD = '#cdeeb0', LIME = '#acef81';
      st.textContent = `.zv{position:absolute;inset:0;background:${LCD};padding:44px 14px 14px;display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,1fr);gap:12px}
.zv::after{content:'';position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,rgba(32,41,29,.05) 0 1px,transparent 1px 3px);z-index:4}
.zv-h{position:absolute;left:14px;right:14px;top:10px;display:flex;justify-content:space-between;font:700 15px system-ui,sans-serif;color:${INK};font-variant-numeric:tabular-nums}
.zv-w{position:relative;min-height:44px;border:3px solid ${INK};border-radius:6px 6px 3px 3px;background:rgba(32,41,29,.08);overflow:hidden;cursor:pointer;-webkit-tap-highlight-color:transparent}
.zv-w::before{content:'';position:absolute;left:0;right:0;bottom:0;height:7px;background:${INK};opacity:.85}
.zv-w::after{content:'';position:absolute;left:50%;top:0;bottom:0;width:3px;margin-left:-1.5px;background:${INK};opacity:.12}
.zv-s{position:absolute;inset:0 0 7px;display:flex;align-items:center;justify-content:center;z-index:1;animation:zvp .16s ease-out}
@keyframes zvp{from{transform:scale(.3);opacity:0}to{transform:scale(1);opacity:1}}
.zv-bell{width:78%;max-height:92%;aspect-ratio:1}
.zv-bell svg{width:100%;height:100%;overflow:visible}
.zv-btn{transition:transform .08s}
.zv-s.press .zv-btn{transform:translateY(5px)}
.zv-s.press .zv-bell{animation:zvk .22s ease-out}
@keyframes zvk{0%{transform:translateX(0)}30%{transform:translateX(-2px) rotate(-3deg)}60%{transform:translateX(2px) rotate(3deg)}100%{transform:none}}
.zv-tk{opacity:0}
.zv-s.press .zv-tk{opacity:1}
.zv-no{position:relative;width:80%;padding:12px 2px 8px;margin-top:6px;background:${INK};color:${LIME};border-radius:5px;font:700 11px/1.25 system-ui,sans-serif;text-align:center;letter-spacing:.02em}
.zv-no::before{content:'';position:absolute;left:50%;top:-9px;width:14px;height:14px;margin-left:-7px;border:3px solid ${INK};border-radius:50%;background:${LCD};box-sizing:border-box}
.zv-ring{position:absolute;left:50%;top:50%;width:30px;height:30px;margin:-15px;border:3px solid #0b4ec2;border-radius:50%;z-index:2;pointer-events:none;animation:zvr .45s ease-out forwards}
.zv-ring::after{content:'';position:absolute;inset:-9px;border:2px solid #0b4ec2;border-radius:50%;opacity:.6}
@keyframes zvr{to{transform:scale(3.6);opacity:0}}
.zv-w.bad{background:rgba(203,27,0,.25);border-color:#cb1b00}`;
      stage.appendChild(st);
      const root = document.createElement('div'); root.className = 'zv';
      root.innerHTML = '<div class="zv-h"><span class="zv-a">Звонки: 0/' + NEED + '</span><span class="zv-m">Ошибки: 0/2</span></div>';
      stage.appendChild(root);
      const wins = [...Array(9)].map(() => { const w = document.createElement('div'); w.className = 'zv-w'; root.appendChild(w); return w });
      let bells = 0, mist = 0, cur = null, bag = [], last = -1;
      const hud = () => { root.querySelector('.zv-a').textContent = `Звонки: ${bells}/${NEED}`; root.querySelector('.zv-m').textContent = `Ошибки: ${mist}/2`; ctx.score(bells) };
      function clear(keep) { if (cur) { const e = cur.w.querySelector('.zv-s'); if (keep && e) { e.classList.add('press'); ctx.after(260, () => e.remove()) } else e?.remove(); cur = null } }
      function spawn() {
        if (!bag.length) bag = [1, 1, 1, 1, 1, 1, 0, 0].sort(() => Math.random() - .5);   // 25% табличек, без длинных серий
        const go = bag.pop(); let i; do i = Math.floor(Math.random() * 9); while (i === last); last = i;
        const w = wins[i], s = document.createElement('div'); s.className = 'zv-s';
        s.innerHTML = go ? '<div class="zv-bell">' + BELL + '</div>' : '<div class="zv-no">НЕ<br>БЕСПОКОИТЬ</div>';
        w.appendChild(s); cur = { w, go, t: performance.now() };
        const me = cur; ctx.after(930, () => { if (cur === me) { clear(); ctx.after(160, spawn) } });
      }
      wins.forEach(w => ctx.on(w, 'pointerdown', e => {
        e.preventDefault(); const p = ctx.pt(e), now = performance.now(), hasCur = cur && cur.w === w;
        ctx.sense.tap({ x: p.x, y: p.y, target: ctx.rect(w), hit: !!hasCur });
        if (!hasCur) return;
        const c = cur, ms = now - c.t; clear(c.go);
        if (c.go) {
          ctx.sense.reaction(ms, { ok: true }); bells++;
          const r = document.createElement('i'); r.className = 'zv-ring'; w.appendChild(r); ctx.after(450, () => r.remove());
          hud(); if (bells >= NEED) return ctx.end({ won: true, score: bells });
        } else {
          ctx.sense.reaction(ms, { ok: false }); mist++; w.classList.add('bad'); ctx.after(400, () => w.classList.remove('bad'));
          hud(); if (mist >= 2) return ctx.end({ won: false, score: bells });
        }
        ctx.after(200, spawn);
      }));
      hud(); ctx.after(600, spawn);
      return { stop() { }, timeUp() { return { won: bells >= NEED && mist <= 1, score: bells } } };
    }
  });
})();
