/* Sense: как человек обращается с устройством. Собираем только тайминги и геометрию касаний, никакого текста.
   Сигналы приходят из двух мест: пассивно со всего интерфейса и прицельно из мини-игр (ctx.sense.*).
   Профиль считается здесь, политика рекомендаций по профилю — на сервере (app/sense.py). */
(function () {
  const KEY = 'o-sense-v1', MAX = 120;
  const now = () => performance.now();
  const med = a => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2 };
  const clamp = (x, a = 0, b = 100) => Math.max(a, Math.min(b, x));
  const lin = (x, good, bad) => x == null ? null : clamp(100 * (bad - x) / (bad - good));
  const store = { get() { try { return JSON.parse(localStorage.getItem(KEY) || 'null') } catch (e) { return null } }, set(v) { try { localStorage.setItem(KEY, JSON.stringify(v)) } catch (e) { } } };

  const blank = () => ({ reaction: [], tapErr: [], tapHit: [], swipeV: [], swipeStraight: [], dragStraight: [], dragMs: [], holdErr: [], rhythmErr: [], trackErr: [],
    choiceMs: [], choiceOk: [], keyMs: [], iki: [], backspace: 0, keys: 0, nearMiss: [], rage: 0, dead: 0, clicks: 0, scrollV: [],
    pointer: {}, firstActionMs: null, games: {}, waits: [], hiddenDuringWait: 0, sessions: 0, optOut: false });
  let S = Object.assign(blank(), store.get() || {});
  S.sessions++;
  const push = (k, v) => { if (v == null || Number.isNaN(v)) return; const a = S[k]; a.push(+(+v).toFixed(2)); if (a.length > MAX) a.shift() };
  const t0 = now(); let lastSave = 0, subs = [];

  function changed() {
    const t = now(); if (t - lastSave > 400) { lastSave = t; store.set(S) }
    subs.forEach(f => { try { f() } catch (e) { } });
    clearTimeout(changed.timer); changed.timer = setTimeout(sync, 1500);
  }

  // ---------- прицельные сигналы из игр ----------
  const sig = {
    reaction(ms, o = {}) { if (ms > 80 && ms < 3000) push('reaction', ms); if (o.ok === false) push('choiceOk', 0); changed() },
    tap({ x, y, target, hit }) {
      if (target) { const cx = target.x + target.w / 2, cy = target.y + target.h / 2, r = Math.max(8, Math.min(target.w, target.h) / 2);
        push('tapErr', Math.hypot(x - cx, y - cy) / r) }
      push('tapHit', hit ? 1 : 0); changed() },
    swipe({ dx, dy, ms, straightness }) { if (ms > 0) push('swipeV', Math.hypot(dx, dy) / ms); if (straightness != null) push('swipeStraight', straightness); changed() },
    drag({ path, ms }) { if (path && path.length > 2) { let L = 0; for (let i = 1; i < path.length; i++) L += Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]);
        const D = Math.hypot(path.at(-1)[0] - path[0][0], path.at(-1)[1] - path[0][1]); if (L > 20) push('dragStraight', D / L);
        push('dragMs', ms ?? (path.at(-1)[2] - path[0][2])) } changed() },
    hold({ wantMs, gotMs }) { push('holdErr', Math.abs(gotMs - wantMs) / wantMs); changed() },
    rhythm({ wantMs, gotMs }) { push('rhythmErr', Math.abs(gotMs - wantMs) / wantMs); changed() },
    track({ errPx, sizePx }) { push('trackErr', errPx / Math.max(8, sizePx)); changed() },
    choice({ ms, ok }) { push('choiceMs', ms); push('choiceOk', ok ? 1 : 0); changed() },
    key({ ms, ok }) { push('keyMs', ms); if (ok != null) push('choiceOk', ok ? 1 : 0); changed() },
    game(id, r) { const g = S.games[id] || (S.games[id] = { played: 0, won: 0, best: 0 }); g.played++; if (r.won) g.won++; g.best = Math.max(g.best, r.score || 0); changed() },
    wait(ms, hidden) { push('waits', ms); if (hidden) S.hiddenDuringWait++; changed() },
  };

  // ---------- пассивные сигналы со всего интерфейса ----------
  const INTERACTIVE = 'button,a,input,textarea,select,summary,label,[onclick],[role=button],.chip,.leaflet-interactive';
  let clicksWin = [];
  addEventListener('pointerdown', e => {
    if (S.optOut) return;
    S.pointer[e.pointerType] = (S.pointer[e.pointerType] || 0) + 1;
    if (S.firstActionMs == null) S.firstActionMs = Math.round(now() - t0);
    if (e.target.closest && e.target.closest('.arc-stage')) return;      // внутри игры сигналы шлёт сама игра
    S.clicks++;
    const hitEl = e.target.closest && e.target.closest(INTERACTIVE);
    if (!hitEl) {                                                         // промах: насколько рядом была ближайшая кнопка
      let best = Infinity;
      document.querySelectorAll('button,.chip,a.g').forEach(b => { const r = b.getBoundingClientRect(); if (!r.width) return;
        const dx = Math.max(r.left - e.clientX, 0, e.clientX - r.right), dy = Math.max(r.top - e.clientY, 0, e.clientY - r.bottom); best = Math.min(best, Math.hypot(dx, dy)) });
      if (best < 24) push('nearMiss', best); else S.dead++;
    }
    const t = now(); clicksWin = clicksWin.filter(c => t - c.t < 700 && Math.hypot(c.x - e.clientX, c.y - e.clientY) < 30); clicksWin.push({ t, x: e.clientX, y: e.clientY });
    if (clicksWin.length === 3) S.rage++;
    changed();
  }, { capture: true, passive: true });

  let lastKey = 0;
  addEventListener('keydown', e => {
    if (S.optOut || !e.target.matches || !e.target.matches('textarea,input')) return;
    const t = now(); if (t - lastKey < 1500 && lastKey) push('iki', t - lastKey); lastKey = t;
    S.keys++; if (e.key === 'Backspace') S.backspace++;
    if (S.keys % 10 === 0) changed();
  }, { capture: true, passive: true });

  let sy = scrollY, st = now();
  addEventListener('scroll', () => { const t = now(), dt = t - st; if (dt > 60) { const v = Math.abs(scrollY - sy) / dt; if (v > 0.05) push('scrollV', v); sy = scrollY; st = t } }, { passive: true });

  // ---------- профиль ----------
  function device() {
    const touch = matchMedia('(pointer:coarse)').matches, w = Math.min(screen.width, screen.height);
    const kind = touch ? (w < 600 ? 'телефон' : 'планшет') : 'компьютер';
    const p = S.pointer, input = Object.keys(p).sort((a, b) => p[b] - p[a])[0] || (touch ? 'touch' : 'mouse');
    return { kind, input, hover: matchMedia('(hover:hover)').matches, dpr: devicePixelRatio, viewport: [innerWidth, innerHeight],
      reducedMotion: matchMedia('(prefers-reduced-motion:reduce)').matches, lang: navigator.language };
  }
  function profile() {
    const dev = device();
    const parts = {
      'реакция': lin(med(S.reaction), 280, 750),
      'точность касаний': S.tapErr.length ? clamp(0.6 * lin(med(S.tapErr), 0.25, 1.4) + 0.4 * 100 * (S.tapHit.reduce((a, b) => a + b, 0) / Math.max(1, S.tapHit.length))) : null,
      'уверенность жестов': (S.swipeV.length || S.dragStraight.length) ? avg([lin(med(S.swipeV), 1.6, 0.3), S.swipeStraight.length ? 100 * med(S.swipeStraight) : null, S.dragStraight.length ? lin(1 - med(S.dragStraight), 0.05, 0.5) : null]) : null,
      'чувство ритма': (S.holdErr.length || S.rhythmErr.length) ? lin(med([...S.holdErr, ...S.rhythmErr]), 0.08, 0.6) : null,
      'слежение за целью': lin(med(S.trackErr), 0.3, 2.5),
      'скорость решений': S.choiceMs.length ? clamp(0.7 * lin(med(S.choiceMs), 600, 2500) + 30 * (avg(S.choiceOk) ?? 1)) : null,
      'набор текста': S.iki.length > 8 ? clamp(lin(med(S.iki), 130, 450) - 120 * (S.backspace / Math.max(1, S.keys))) : null,
      'промахи в интерфейсе': S.clicks > 6 ? clamp(100 - 400 * S.nearMiss.length / S.clicks - 15 * S.rage) : null,
    };
    const w = { 'реакция': 1, 'точность касаний': 1.4, 'уверенность жестов': 1, 'чувство ритма': .6, 'слежение за целью': .8, 'скорость решений': 1, 'набор текста': 1, 'промахи в интерфейсе': 1.2 };
    let sw = 0, sv = 0; for (const [k, v] of Object.entries(parts)) if (v != null) { sw += w[k]; sv += w[k] * v }
    const n = S.reaction.length + S.tapErr.length + S.swipeV.length + S.dragStraight.length + S.holdErr.length + S.rhythmErr.length + S.trackErr.length + S.choiceMs.length + (S.iki.length > 8 ? 5 : 0) + (S.clicks > 6 ? 3 : 0);
    const kinds = Object.values(parts).filter(v => v != null).length;   // одна игра не даёт полной картины
    const score = sw ? Math.round(sv / sw) : null, confidence = +(Math.min(1, n / 40) * Math.min(1, kinds / 4)).toFixed(2);
    const segment = score == null ? 'unknown' : score >= 68 ? 'confident' : score >= 42 ? 'regular' : 'careful';
    return { score, confidence, segment, parts: Object.fromEntries(Object.entries(parts).map(([k, v]) => [k, v == null ? null : Math.round(v)])),
      device: dev, hand: thumb(), patience: { firstActionMs: S.firstActionMs, medianWaitMs: med(S.waits), leftDuringWait: S.hiddenDuringWait },
      games: S.games, signals: n, optOut: S.optOut };
  }
  function avg(a) { a = a.filter(x => x != null); return a.length ? a.reduce((x, y) => x + y, 0) / a.length : null }

  // большой палец: игры сообщают нормированный x касаний в нижней трети экрана
  const thumbX = [];
  addEventListener('pointerdown', e => { if (e.pointerType === 'touch' && e.clientY > innerHeight * .55) { thumbX.push(e.clientX / innerWidth); if (thumbX.length > 60) thumbX.shift() } }, { capture: true, passive: true });
  function thumb() { if (thumbX.length < 8) return null; const m = med(thumbX); return m > .56 ? 'правая' : m < .44 ? 'левая' : 'обе' }

  // ---------- синхронизация с сервером: только агрегаты ----------
  let sid; try { sid = sessionStorage.getItem('o-sid') || (sessionStorage.setItem('o-sid', crypto.randomUUID()), sessionStorage.getItem('o-sid')) } catch (e) { sid = 'anon-' + Math.random().toString(36).slice(2) }
  let policy = null;
  // посетитель: тот же ключ, что у главной (app/web/front/app.js, SID) — по нему копятся события и кластер вкуса
  let vid; try { vid = localStorage.getItem('osess'); if (!vid) { vid = 's' + Math.random().toString(36).slice(2, 12); localStorage.setItem('osess', vid) } } catch (e) { vid = sid }
  function context() {   // контекст браузера без отпечатков: ничего, что однозначно опознаёт устройство
    const c = navigator.connection || {}, d = new Date(), ref = document.referrer;
    const u = new URLSearchParams(location.search), utm = {};
    ['utm_source', 'utm_medium', 'utm_campaign'].forEach(k => { if (u.get(k)) utm[k] = u.get(k).slice(0, 60) });
    return { tz: Intl.DateTimeFormat().resolvedOptions().timeZone, tzOffset: -d.getTimezoneOffset(), langs: (navigator.languages || []).slice(0, 4),
      screen: [screen.width, screen.height], viewport: [innerWidth, innerHeight], dpr: devicePixelRatio,
      colorScheme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light', reducedMotion: matchMedia('(prefers-reduced-motion:reduce)').matches,
      effectiveType: c.effectiveType, saveData: c.saveData, deviceMemory: navigator.deviceMemory, cores: navigator.hardwareConcurrency,
      touchPoints: navigator.maxTouchPoints, hour: d.getHours(), weekday: d.getDay(), referrer: ref || null, utm: Object.keys(utm).length ? utm : null,
      pointer: matchMedia('(pointer:coarse)').matches ? 'coarse' : 'fine' };
  }
  // согласие: до ответа посетителя контекст и события не отправляются вовсе
  const CK = 'o-consent';
  const consent = () => { try { return localStorage.getItem(CK) } catch (e) { return null } };
  const allowed = () => consent() === 'yes' && !S.optOut;
  function setConsent(v) { try { localStorage.setItem(CK, v) } catch (e) { } const b = document.getElementById('oConsent'); if (b) b.remove(); if (v === 'yes') visit(); subs.forEach(f => { try { f() } catch (e) { } }) }
  function askConsent() {
    if (location.pathname !== '/') return;  // спрашиваем только гостя на главной; в кабинетах подстройки выдачи нет
    if (consent() || S.optOut || document.getElementById('oConsent') || !document.body) return;
    const b = document.createElement('div');
    b.id = 'oConsent'; b.className = 'o-consent'; b.setAttribute('role', 'region'); b.setAttribute('aria-label', 'Подстройка выдачи');
    b.innerHTML = '<p>Чтобы поднять выше отели, которые чаще открывают похожие на вас посетители, учитываем устройство, регион и тип сети по IP, время поиска и какие отели вы открываете. Сам IP не храним. Стереть всё можно внизу страницы.</p>' +
      '<div><button type="button" data-c="yes">Учитывать</button><button type="button" data-c="no">Не надо</button></div>';
    b.addEventListener('click', e => { const c = e.target.closest('[data-c]'); if (c) setConsent(c.dataset.c) });
    document.body.appendChild(b);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', askConsent); else askConsent();
  async function visit() {
    if (!allowed()) return;
    try { await fetch('/api/visit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ vid, client: context() }) }) } catch (e) { }
  }
  visit();
  // события выдачи: копим и отправляем пачкой; при уходе со страницы — sendBeacon
  let queue = [], qt;
  function flush(beacon) {
    if (!queue.length || !allowed()) { queue = []; return }
    const body = JSON.stringify({ vid, events: queue.splice(0, 50) });
    try { if (beacon && navigator.sendBeacon) navigator.sendBeacon('/api/events', new Blob([body], { type: 'application/json' }));
      else fetch('/api/events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => { }) } catch (e) { }
  }
  function track(type, data = {}, hotel_id) {
    if (!allowed()) return;
    queue.push({ type, data, hotel_id: hotel_id == null ? undefined : String(hotel_id), at: Date.now() / 1000 });
    clearTimeout(qt); qt = setTimeout(flush, 1200);
  }
  addEventListener('pagehide', () => flush(true));
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flush(true) });
  async function sync() {
    if (S.optOut) return;
    try { const r = await fetch('/api/sense/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sid, vid: allowed() ? vid : '', profile: profile() }) });
      if (r.ok) { policy = await r.json(); subs.forEach(f => { try { f() } catch (e) { } }) } } catch (e) { }
  }
  setTimeout(sync, 800);

  window.Sense = {
    sig, profile, sid: () => sid, policy: () => policy, sync,
    onChange(f) { subs.push(f) },
    vid: () => vid, track, context, consent, setConsent,
    optOut(v) { S.optOut = !!v; store.set(S); if (v) { policy = null; queue = []; try { localStorage.removeItem(CK) } catch (e) { } fetch('/api/visit/forget', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ vid }) }).catch(() => { }) } else setConsent('yes'); subs.forEach(f => f()) },
    reset() { const o = S.optOut; S = blank(); S.optOut = o; store.set(S); policy = null; thumbX.length = 0; sync() },
  };
})();
