/* О!ркада: мини-игры на время ожидания поиска. Игры регистрируются через Arcade.register (файлы games/*.js).
   Контракт игры:
     Arcade.register({ id, title, era:'ussr'|'world', icon, duration (≤30 c), rules, win, lose, primitives:[...],
       start(stage, ctx) -> { stop(), timeUp?() -> {won, score} } })
   ctx: w, h, pal, canvas(w,h), score(n), end({won, score}), on(el, ev, fn, opts), raf(fn), after(ms, fn),
        rect(el) (координаты относительно stage), pt(e) (точка события относительно stage),
        onSwipe(fn(dir, info)), onKey(fn(key, e)), sense.{tap,reaction,swipe,drag,hold,rhythm,track,choice,key} */
(function () {
  const PAL = { blue: '#0b4ec2', lime: '#acef81', grey: '#f2f1f0', ink: '#292f37', purple: '#855ca6', red: '#cb1b00', white: '#ffffff', sea: '#3d7be0' };
  const SLOW = ['/api/chat', '/api/search', '/api/characteristics', '/api/simulate/building', '/answer'];
  // Страница может выключить автозапуск (window.ARCADE_AUTO = false): тогда игра открывается только по кнопке.
  const AUTO = window.ARCADE_AUTO !== false;
  const cover = (g, cls = '') => `<div class="arc-cover ${cls}"><img src="/waitgames/covers/${g.id}.webp" alt="" onerror="this.parentNode.classList.add('noimg')"><span>${g.icon || ICON.pad}</span></div>`;
  const games = [], esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  let readyMsg = null, root, cur = null, waitingFor = null, lastId = null, pending = 0, ready = false, played = false, waitStart = 0, hiddenInWait = false;
  const PIN = '<svg viewBox="0 0 15 19" aria-hidden="true"><path fill="currentColor" d="M7.5 0C3.4 0 0 3.3 0 7.4c0 5 6.3 10.8 6.6 11.1.5.4 1.3.4 1.8 0 .3-.3 6.6-6.1 6.6-11.1C15 3.3 11.6 0 7.5 0zm0 10.6a3.2 3.2 0 1 1 0-6.4 3.2 3.2 0 0 1 0 6.4z"/></svg>';

  // ---------- нарисованные иконки (один штрих 1.75, круглые окончания) ----------
  const IC = d => `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
  const ICON = {
    pad: IC('<rect x="2.5" y="7" width="19" height="11" rx="4.5"/><path d="M7.5 10.5v4M5.5 12.5h4M15.5 11.5h.01M18 13.5h.01"/>'),
    user: IC('<circle cx="12" cy="8" r="3.6"/><path d="M4.8 20c.6-3.8 3.6-6 7.2-6s6.6 2.2 7.2 6"/>'),
    grid: IC('<rect x="4" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.6"/>'),
    swap: IC('<path d="M4 12a8 8 0 0 1 13.7-5.6L20 8.5M20 4v4.5h-4.5M20 12a8 8 0 0 1-13.7 5.6L4 15.5M4 20v-4.5h4.5"/>'),
    star: IC('<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>'),
    x: IC('<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>'),
  };

  // ---------- семисегментные цифры: тусклые (погашенные) сегменты рисуются всегда ----------
  const SEGP = { a: '3,1.5 4.5,0 15.5,0 17,1.5 15.5,3 4.5,3', g: '3,17 4.5,15.5 15.5,15.5 17,17 15.5,18.5 4.5,18.5', d: '3,32.5 4.5,31 15.5,31 17,32.5 15.5,34 4.5,34',
    f: '1.5,3.6 3,5.1 3,13.4 1.5,14.9 0,13.4 0,5.1', b: '18.5,3.6 20,5.1 20,13.4 18.5,14.9 17,13.4 17,5.1', e: '1.5,19.4 3,20.9 3,28.9 1.5,30.4 0,28.9 0,20.9', c: '18.5,19.4 20,20.9 20,28.9 18.5,30.4 17,28.9 17,20.9' };
  const DIG = { 0: 'abcdef', 1: 'bc', 2: 'abdeg', 3: 'abcdg', 4: 'bcfg', 5: 'acdfg', 6: 'acdefg', 7: 'abc', 8: 'abcdefg', 9: 'abcdfg', '-': 'g' };
  const seg = (v, n, cls = '') => {
    const raw = v == null ? '' : String(typeof v === 'number' ? Math.round(v) : v), t = raw.replace('—', '-').slice(-n).padStart(n, ' ');
    return `<span class="arc-seg ${cls}" role="img" aria-label="${esc(raw)}">${[...t].map(ch => { const on = DIG[ch] || '';
      return '<svg viewBox="0 0 20 34" aria-hidden="true">' + 'abcdefg'.split('').map(k => `<polygon class="${on.includes(k) ? 'on' : ''}" points="${SEGP[k]}"/>`).join('') + '</svg>' }).join('')}</span>`;
  };
  // ---------- штемпель: кольцо с текстом по окружности и словом по центру ----------
  let pmN = 0;
  const postmark = (word, cls = '') => { const id = 'arcpm' + (++pmN);
    return `<svg class="arc-pm ${cls}" viewBox="0 0 120 120" aria-hidden="true"><defs><path id="${id}" d="M60 60m-45 0a45 45 0 1 1 90 0a45 45 0 1 1-90 0"/></defs><circle cx="60" cy="60" r="56" class="r1"/><circle cx="60" cy="60" r="35" class="r2"/><text class="rt"><textPath href="#${id}" textLength="276">ОСТРОВОК · СОЧИ · ОСТРОВОК · СОЧИ ·</textPath></text><rect x="5" y="47" width="110" height="26" rx="2" class="band"/><text x="60" y="66.5" text-anchor="middle" class="w">${word}</text></svg>` };

  // ---------- шапка в стиле ostrovok.ru ----------
  function brandHeader() {
    const h1 = document.querySelector('header h1'), nav = document.getElementById('nav'); if (!h1 || !nav || h1.dataset.o) return; h1.dataset.o = 1;
    h1.innerHTML = `<a class="o-mark" href="https://ostrovok.ru/" target="_blank" rel="noopener" aria-label="Ostrovok.ru">OSTR${PIN}VOK.RU</a><span class="o-sub">О!Правда об отеле</span>`;
    const b = document.createElement('div'); b.className = 'arc-hbtns';
    b.innerHTML = `<button class="arc-hbtn" data-a="play" title="Мини-игры" aria-label="О!ркада">${ICON.pad}<i>О!ркада</i></button><button class="arc-hbtn" data-a="me" title="Что мы поняли о вас" aria-label="Профиль">${ICON.user}<i>Профиль</i></button>`;
    b.onclick = e => { const a = e.target.closest('button')?.dataset.a; if (a === 'play') open({ manual: true }); if (a === 'me') open({ profile: true }) };
    nav.after(b);
  }

  // ---------- оверлей ----------
  function mount() {
    if (root) return root;
    root = document.createElement('div'); root.className = 'arc'; root.hidden = true;
    const key = (a, ic, label, cls = '') => `<span class="arc-k ${cls}"><button class="arc-key ${a === 'close' ? 'arc-x' : ''}" data-a="${a}" aria-label="${label}" title="${label}">${ICON[ic]}</button><span class="arc-kl">${label}</span></span>`;
    root.innerHTML = `<div class="arc-unit"><div class="arc-tab" hidden></div><div class="arc-panel" role="dialog" aria-modal="true" aria-label="О!ркада">
      <div class="arc-head"><div class="arc-brand"><span class="arc-logo"><b>О!</b>ркада</span><span class="arc-plate">Электроника · Островок</span></div>
        <span class="arc-grille" aria-hidden="true">${'<i></i>'.repeat(9)}</span></div>
      <div class="arc-frame"><span class="arc-cap">Игры на время поиска</span><div class="arc-screen"><div class="arc-lcd">
        <div class="arc-top"><span class="arc-title"></span><span class="arc-readout"><span class="arc-lab">очки</span><span class="arc-score"></span></span><span class="arc-readout"><span class="arc-lab">сек</span><span class="arc-clock"></span></span></div>
        <div class="arc-time"><i></i></div>
        <div class="arc-body"></div></div></div></div>
      <div class="arc-wait" aria-live="polite" hidden><span class="arc-lamps"><i></i><i></i><i></i><i></i></span><span class="arc-wait-t"></span><button class="arc-go" hidden>Показать</button></div>
      <div class="arc-keys">${key('other', 'swap', 'Другая игра', 'dsk')}${key('all', 'grid', 'Все игры')}${key('me', 'user', 'Профиль')}${key('close', 'x', 'Закрыть')}</div></div></div>`;
    document.body.appendChild(root);
    root.querySelector('.arc-x').onclick = close;
    root.querySelector('.arc-keys').onclick = e => { const a = e.target.closest('button')?.dataset.a; if (a === 'all') { stopGame(); list() } if (a === 'me') showProfile(); if (a === 'other') { stopGame(); lobby() } };
    setScore(null); setClock(null);
    root.addEventListener('click', e => { if (e.target === root) close() });
    addEventListener('keydown', e => { if (!root.hidden && e.key === 'Escape') close() });
    return root;
  }
  const $ = s => root.querySelector(s);
  const setScore = n => { $('.arc-score').innerHTML = seg(n == null ? null : Math.min(9999, n), 4) };
  const setClock = n => { $('.arc-clock').innerHTML = seg(n, 2) };
  function setTab(g, mode) {
    const t = $('.arc-tab'); root.dataset.tab = g && mode ? mode : '';
    if (!g || !mode) { t.hidden = true; t.innerHTML = ''; return }
    t.hidden = false; t.innerHTML = cover(g, mode === 'lobby' ? 'in' : mode) + (mode === 'win' ? postmark('ПРИНЯТО', 'ok') : mode === 'lose' ? postmark('ВОЗВРАТ', 'ret') : '');
  }
  // названия стадий общие со страницей (window.WAIT_STAGES); страница же отдаёт живую стадию агента (waitStageNow)
  const PH = () => window.WAIT_STAGES || ['Разбираем запрос', 'Проверяем вид и путь', 'Сверяем цифры', 'Пишем ответ'];
  let waitTimer = 0;
  const phaseNow = () => { const live = window.waitStageNow && window.waitStageNow(); if (live != null) return Math.min(live, PH().length - 1); const s = (performance.now() - waitStart) / 1000; return s < 2.5 ? 0 : s < 5 ? 1 : 2 };
  function paintPhase(i) { const w = $('.arc-wait'); w.dataset.ph = i; w.querySelectorAll('.arc-lamps i').forEach((l, k) => { l.className = k < i || (ready && k <= i) ? 'done' : k === i ? 'cur' : '' }); }
  function setWait() {
    const w = $('.arc-wait'); w.hidden = !pending && !ready; w.classList.toggle('on', ready); clearInterval(waitTimer);
    const g = $('.arc-go'); g.hidden = !ready;
    if (ready) { paintPhase(3); $('.arc-wait-t').innerHTML = `<b>${esc(readyMsg || 'Готово: результаты обновлены.')}</b>${cur ? '<span class="arc-cont">Игра не прервётся: доиграйте или откройте выдачу.</span>' : ''}`; g.onclick = close }
    else if (pending) { const t = () => { const i = phaseNow(); paintPhase(i); $('.arc-wait-t').textContent = PH()[i] }; t(); waitTimer = setInterval(() => (pending && !ready) ? t() : clearInterval(waitTimer), 500) }
  }

  function open(o = {}) {
    mount(); root.hidden = false; document.body.classList.add('arc-lock'); setWait();
    if (o.profile) return showProfile();
    if (cur) return;
    lobby(o.id);
  }
  function close() { stopGame(); clearInterval(waitTimer); if (root) root.hidden = true; document.body.classList.remove('arc-lock'); ready = false; Sense.sync() }

  function pick(id) {
    if (id) return games.find(g => g.id === id);
    const pool = games.filter(g => g.id !== lastId); return pool[Math.floor(Math.random() * pool.length)] || games[0];
  }
  function lobby(id) {
    const g = pick(id); if (!g || (id && !games.some(x => x.id === id) && document.readyState !== 'complete')) { waitingFor = id || '*'; $('.arc-body').innerHTML = '<div class="arc-card">Игры загружаются…</div>'; return }
    waitingFor = null;
    $('.arc-title').textContent = g.title; setScore(null); setClock(g.duration); $('.arc-time i').style.width = '0';
    const shown = performance.now();
    $('.arc-body').innerHTML = `<div class="arc-card arc-start"><h3>${esc(g.title)}</h3>
      <div class="arc-era">${g.era === 'ussr' ? 'Из детства на «Электронике»' : 'Классика со всего мира'} · ${g.duration} с</div>
      <p>${esc(g.rules)}</p><button class="arc-play">Играть</button>
      <div class="arc-more"><button data-a="other">Другая игра</button><button data-a="all">Все игры</button><button data-a="me">Что мы поняли о вас</button></div></div>`;
    setTab(g, 'lobby');
    $('.arc-play').onclick = () => { Sense.sig.choice({ ms: performance.now() - shown, ok: true }); run(g) };
    $('.arc-more').onclick = e => { const a = e.target.dataset.a; if (a === 'other') { lastId = g.id; lobby() } if (a === 'all') list(); if (a === 'me') showProfile() };
  }
  function list() {
    setTab(null); $('.arc-title').textContent = 'Все игры'; setScore(null); setClock(null); $('.arc-time i').style.width = '0';
    $('.arc-body').innerHTML = `<div class="arc-grid">${games.map(g => `<button data-id="${g.id}" style="--d:${games.indexOf(g) * 40}ms"><span class="arc-st">${cover(g, 'sm')}</span><span class="arc-gt">${esc(g.title)}</span><small>${g.era === 'ussr' ? 'СССР' : 'мир'} · ${g.duration} с</small></button>`).join('')}</div>`;
    $('.arc-grid').onclick = e => { const b = e.target.closest('button'); if (b) lobby(b.dataset.id) };
  }

  // ---------- запуск игры ----------
  function run(g) {
    stopGame(); lastId = g.id; played = true; setTab(null);
    const body = $('.arc-body'); body.innerHTML = '<div class="arc-stage" tabindex="0"></div>';
    const stage = body.firstChild; stage.focus({ preventScroll: true });
    const W = stage.clientWidth, H = stage.clientHeight, offs = [], timers = [], rafs = [];
    let score = 0, done = false, inst = null;
    const T0 = performance.now(), dur = Math.min(30, g.duration || 25) * 1000;
    const bar = $('.arc-time i'); let lastLeft = -1; setScore(0); setClock(Math.round(dur / 1000));
    const sr = () => stage.getBoundingClientRect();
    const ctx = {
      w: W, h: H, pal: PAL,
      canvas(w = W, h = H) { const c = document.createElement('canvas'), d = devicePixelRatio || 1; c.width = w * d; c.height = h * d; c.style.width = w + 'px'; c.style.height = h + 'px';
        const x = c.getContext('2d'); x.scale(d, d); stage.appendChild(c); return { canvas: c, g: x } },
      score(n) { score = n; setScore(n) },
      end(r = {}) { if (done) return; done = true; finish(g, { won: !!r.won, score: r.score ?? score, ms: performance.now() - T0 }) },
      on(el, ev, fn, opt) { el.addEventListener(ev, fn, opt); offs.push(() => el.removeEventListener(ev, fn, opt)) },
      after(ms, fn) { const t = setTimeout(() => !done && fn(), ms); timers.push(t); return t },
      every(ms, fn) { const t = setInterval(() => !done && fn(), ms); timers.push(t); return t },
      raf(fn) { let last = performance.now(); const loop = t => { if (done) return; fn(Math.min(50, t - last), t); last = t; rafs[0] = requestAnimationFrame(loop) }; rafs[0] = requestAnimationFrame(loop) },
      rect(el) { const a = el.getBoundingClientRect(), s = sr(); return { x: a.left - s.left, y: a.top - s.top, w: a.width, h: a.height } },
      pt(e) { const s = sr(); return { x: e.clientX - s.left, y: e.clientY - s.top } },
      onSwipe(fn) {
        let st = null, path = [];
        ctx.on(stage, 'pointerdown', e => { st = { ...ctx.pt(e), t: performance.now() }; path = [[st.x, st.y]] });
        ctx.on(stage, 'pointermove', e => { if (st) { const p = ctx.pt(e); path.push([p.x, p.y]) } });
        ctx.on(stage, 'pointerup', e => {
          if (!st) return; const p = ctx.pt(e), dx = p.x - st.x, dy = p.y - st.y, ms = performance.now() - st.t; st = null;
          if (Math.hypot(dx, dy) < 18) return fn('tap', { x: p.x, y: p.y, ms });
          let L = 0; for (let i = 1; i < path.length; i++) L += Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]);
          const info = { dx, dy, ms, straightness: L ? Math.hypot(dx, dy) / L : 1 }; Sense.sig.swipe(info);
          fn(Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'down' : 'up'), info);
        });
      },
      onKey(fn) { ctx.on(window, 'keydown', e => { if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', ' '].includes(e.key)) e.preventDefault(); fn(e.key, e) }) },
      sense: Sense.sig,
    };
    stage.style.touchAction = 'none';
    ctx.raf(() => { const k = Math.min(1, (performance.now() - T0) / dur); bar.style.width = (k * 100) + '%'; const left = Math.max(0, Math.ceil((dur - (performance.now() - T0)) / 1000)); if (left !== lastLeft) { lastLeft = left; setClock(left) }
      if (k >= 1 && !done) { const r = inst?.timeUp ? inst.timeUp() : { won: false, score }; ctx.end(r) } });
    cur = { stop() { done = true; offs.forEach(f => f()); timers.forEach(t => { clearTimeout(t); clearInterval(t) }); cancelAnimationFrame(rafs[0]); try { inst?.stop?.() } catch (e) { } } };
    try { inst = g.start(stage, ctx) } catch (e) { console.error('[arcade]', g.id, e); ctx.end({ won: false, score: 0 }) }
  }
  function stopGame() { if (cur) { cur.stop(); cur = null } }
  function finish(g, r) {
    stopGame(); Sense.sig.game(g.id, r);
    const p = Sense.profile();
    $('.arc-body').innerHTML = `<div class="arc-card arc-end ${r.won ? 'won' : 'lost'}">${r.won ? '<div class="arc-confetti" aria-hidden="true">' + '<i></i>'.repeat(14) + '</div>' : ''}
      <h3>${esc(r.won ? g.win : g.lose)}</h3><div class="arc-era">Очки: <b>${r.score}</b> · ${(r.ms / 1000).toFixed(1)} с</div>
      ${p.score != null && p.confidence >= 0.15 ? `<div class="arc-mini">Ловкость с устройством: <b>${p.score}</b>/100 <span>· ${SEG[p.segment]}</span></div>` : ''}
      ${p.segment !== 'unknown' && p.confidence >= 0.4 ? '<div class="arc-mini arc-enough">Профиль собран: выдача уже подстроена. Играть дальше не обязательно.</div>' : ''}
      <div class="arc-row"><button class="arc-play" data-a="again">Ещё раз</button><button class="arc-sec" data-a="other">Другая игра</button></div>
      <div class="arc-more"><button data-a="me">Что мы поняли о вас</button>${ready || !pending ? '<button data-a="close">К результатам</button>' : ''}</div></div>`;
    setTab(g, r.won ? 'win' : 'lose');
    $('.arc-end').onclick = e => { const a = e.target.dataset.a; if (a === 'again') run(g); if (a === 'other') lobby(); if (a === 'me') showProfile(); if (a === 'close') close() };
  }

  // ---------- что мы поняли о пользователе ----------
  const SEG = { confident: 'уверенный пользователь', regular: 'обычный темп', careful: 'бережный темп', unknown: 'пока мало данных' };
  function showProfile() {
    stopGame(); setTab(null); $('.arc-title').textContent = ''; setScore(null); setClock(null); $('.arc-time i').style.width = '0';
    const p = Sense.profile(), pol = Sense.policy(), d = p.device, low = p.confidence < 0.15;
    const ent = Object.entries(p.parts), have = ent.filter(([, v]) => v != null), none = ent.filter(([, v]) => v == null).map(([k]) => k);
    const bars = low ? '' : have.map(([k, v]) => `<div class="arc-bar"><span>${esc(k)}</span><i><b style="width:${v}%"></b></i><em>${v}</em></div>`).join('') + (none.length ? `<div class="arc-empty">Нет данных: ${esc(none.join(', '))}.</div>` : '');
    $('.arc-body').innerHTML = `<div class="arc-card arc-prof">
      <h3>Что мы о вас узнали</h3>
      ${pol ? `<h4>Что это меняет в выдаче</h4><ul>${pol.reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul>` : '<p class="arc-note">Сыграйте одну-две игры, и мы подстроим выдачу.</p>'}
      <h4>Паспорт устройства</h4>
      <div class="arc-big">${seg(low ? null : p.score, 3, 'lg')}${low ? '' : '<small>/100</small>'}</div>
      <div class="arc-era">${low ? `Мало данных: сыграйте ещё одну игру · сигналов ${p.signals}` : `${SEG[p.segment]} · уверенность вывода ${Math.round(p.confidence * 100)}% · сигналов ${p.signals}`}</div>
      ${bars}
      <div class="arc-facts">${d.kind} · ввод: ${esc(d.input)}${p.hand ? ' · большой палец: ' + p.hand : ''} · экран ${d.viewport.join('×')} · DPR ${d.dpr}${d.reducedMotion ? ' · без анимаций' : ''}</div>
      <p class="arc-note">Из игр храним тайминги и точность касаний, без текста запросов. ${Sense.consent && Sense.consent() === 'yes' ? 'Вы разрешили учитывать устройство, регион и тип сети по IP, время поиска и какие отели вы открываете: это хранится, пока вы не сотрёте данные. Сам IP не храним.' : 'Устройство, регион и открытые отели не учитываем: вы этого не разрешали.'}</p>
      <label class="arc-opt"><input type="checkbox" ${p.optOut ? 'checked' : ''}> Не подстраивать выдачу и стереть мои данные</label>
      <div class="arc-row"><button class="arc-play" data-a="play">Сыграть</button><button class="arc-sec" data-a="reset">Сбросить</button></div></div>`;
    $('.arc-opt input').onchange = e => { Sense.optOut(e.target.checked); showProfile() };
    $('.arc-prof .arc-row').onclick = e => { const a = e.target.dataset.a; if (a === 'play') lobby(); if (a === 'reset') { Sense.reset(); showProfile() } };
  }

  // ---------- перехват долгих запросов ----------
  const qs = new URLSearchParams(location.search), demoDelay = qs.get('arcade') === 'slow' ? 7000 : 0;
  const _fetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : input.url, post = init && init.method === 'POST';
    if (!post || !SLOW.some(s => url.includes(s))) return _fetch(input, init);
    pending++; waitStart = performance.now(); hiddenInWait = false; ready = false; readyMsg = null; played = !!cur;
    const show = setTimeout(() => { if (pending && AUTO) open({}) }, 1200);
    const p = _fetch(input, init).then(r => demoDelay && url.includes('/api/chat') ? new Promise(ok => setTimeout(() => ok(r), demoDelay)) : r);
    const done = () => { clearTimeout(show); pending = Math.max(0, pending - 1); const ms = performance.now() - waitStart; Sense.sig.wait(ms, hiddenInWait);
      if (!AUTO) { if (root && !root.hidden) setWait(); return }  // готовность объявляет страница через notify()
      if (root && !root.hidden) { if (cur) { ready = true; setWait() } else if (ms > 1200) { ready = true; setWait(); setTimeout(() => { if (!cur && ready) close() }, 2600) } else close() } };
    p.then(done, done); return p;
  };
  document.addEventListener('visibilitychange', () => { if (document.hidden && pending) hiddenInWait = true });

  // ---------- выдача под профиль: порядок внутри корзины и плотность ----------
  function hookResults() {
    if (typeof window.renderResults !== 'function' || window.renderResults.o) return;
    const orig = window.renderResults;
    window.renderResults = async function (s) {
      lastResults = s; const pol = Sense.policy(); appliedSeg = pol?.segment;
      if (pol && pol.segment !== 'unknown' && s?.results?.length) {
        try {
          const r = await _fetch('/api/sense/rerank', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sid: Sense.sid(), profile: Sense.profile(), results: s.results.map(x => ({ id: x.hotel.id, bucket: x.bucket, rating: x.hotel.rating, reviews: x.hotel.reviews, good: (x.good || []).length, bad: (x.bad || []).length, unknown: (x.unknown || []).length })) }) });
          if (r.ok) { const o = await r.json(), by = Object.fromEntries(s.results.map(x => [x.hotel.id, x]));
            s = { ...s, results: o.order.map(id => by[id]).filter(Boolean) }; document.body.dataset.oDensity = o.density;
            orig(s); const c = document.getElementById('counts');
            if (c && o.note) c.insertAdjacentHTML('beforeend', `<div class="arc-tuned">${ICON.star} ${esc(o.note)} <button onclick="Arcade.open({profile:true})">почему</button></div>`); return }
        } catch (e) { }
      }
      return orig(s);
    };
    window.renderResults.o = 1;
  }
  let lastResults = null, appliedSeg;
  Sense.onChange(() => {   // профиль уточнился после игры: пересобираем уже показанную выдачу
    const pol = Sense.policy(); document.body.classList.toggle('o-comfy', pol?.density === 'comfy');
    if (lastResults && pol?.segment !== appliedSeg && !cur) window.renderResults(lastResults);
  });

  // для внешних интерфейсов: переставить выдачу /api/search под профиль. Возвращает {s, note, density, policy}
  // кластеры вкуса работают и без игр (по контексту), поэтому сервер спрашиваем всегда, если есть выдача; ?cluster=1 — демо
  const demo = /[?&]cluster=1\b/.test(location.search);
  async function tune(s) {
    const pol = Sense.policy(), prof = Sense.profile();
    if (!s?.results?.length || prof.optOut) return { s, note: null, density: 'normal', policy: pol };
    try {
      const r = await _fetch('/api/sense/rerank', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sid: Sense.sid(), vid: Sense.vid && Sense.vid(), demo, profile: pol ? prof : { ...prof, segment: 'unknown', confidence: 0 },
          results: s.results.map(x => ({ id: x.hotel.id, bucket: x.bucket, rating: x.hotel.rating, reviews: x.hotel.reviews, good: (x.good || []).length, bad: (x.bad || []).length, unknown: (x.unknown || []).length })) }) });
      const o = await r.json(), by = Object.fromEntries(s.results.map(x => [x.hotel.id, x]));
      return { s: { ...s, results: o.order.map(id => by[id]).filter(Boolean) }, note: o.note, rub: o.rub, density: o.density, policy: o.policy, taste: o.taste };
    } catch (e) { return { s, note: null, density: 'normal', policy: pol } }
  }
  window.Arcade = { tune, register(g) { if (!games.some(x => x.id === g.id)) games.push(g); if (waitingFor && root && !root.hidden && !cur && (waitingFor === '*' || waitingFor === g.id)) lobby(waitingFor === '*' ? undefined : g.id) }, open, close, games, PAL,
    // Страница сообщает, что именно готово; если игра идёт, она не прерывается (как динозавр в Chrome).
    notify(msg) { readyMsg = msg; ready = true; if (root && !root.hidden) setWait() }, isOpen: () => !!(root && !root.hidden) };
  const init = () => { brandHeader(); hookResults(); if (qs.get('arcade') === 'open') open({ manual: true, id: qs.get('game') }) };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', init) : init();
})();
