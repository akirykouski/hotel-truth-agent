/* Вердикт наверху карточки отеля: какой номер брать, что попросить и чем это подтверждается.
   Три факта берём из уже посчитанного: вид из окна, ночь по часам, путь до пляжа. Подключается одной строкой в index.html. */
(function () {
  const css = `
.vd-head{margin-bottom:10px}.vd-head h2{margin-bottom:2px}
.vd{margin:0 0 14px;padding:14px 16px;border:1px solid var(--line);border-left:5px solid var(--ok);border-radius:12px;background:var(--card);min-width:0}
.vd.none{border-left-color:var(--muted)}
.vd-line{font-size:20px;line-height:1.3;overflow-wrap:anywhere}.vd-line b{color:var(--ok)}.vd.none .vd-line b{color:var(--ink)}
.vd-line.wait{color:var(--muted);font-size:15px}
.vd-chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.vd-chip{display:inline-flex;align-items:center;gap:6px;min-height:36px;padding:5px 12px;border:1px solid var(--line);border-radius:99px;background:var(--bg);color:var(--ink);font:inherit;font-size:13px;line-height:1.25;cursor:pointer;text-align:left}
.vd-chip.ok{border-color:var(--ok);background:var(--ok-soft)}.vd-chip.warn{border-color:var(--warn);background:var(--warn-soft)}
.vd-chip.on{box-shadow:0 0 0 2px var(--acc-soft)}
.vd-src{margin-top:8px;font-size:12.5px;color:var(--muted);overflow-wrap:anywhere}
.vd-act{margin-top:12px}
.vd-copy{border:0;background:var(--acc);color:#fff;border-radius:8px;padding:10px 16px;font-weight:600;cursor:pointer;min-height:44px;font-size:14px}
.vd-copy.done{background:var(--ok)}
.vd-req{margin-top:8px;font-size:12.5px;color:var(--muted)}
details.vd-rooms{margin:8px 0}details.vd-rooms summary{cursor:pointer;font-size:13px;color:var(--muted)}details.vd-rooms div{margin-top:6px}
.vd-wait{margin-top:20px}
@media(max-width:600px){.vd{padding:12px}.vd-chips{flex-direction:column;align-items:stretch}.vd-chip{width:100%;min-height:44px}.vd-copy{width:100%}}`;
  const st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);

  const E = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const DIR = { 'С': 'север', 'СВ': 'северо-восток', 'В': 'восток', 'ЮВ': 'юго-восток', 'Ю': 'юг', 'ЮЗ': 'юго-запад', 'З': 'запад', 'СЗ': 'северо-запад' };
  const dir = c => DIR[c] || c;
  const jget = async u => { const r = await fetch(u); if (!r.ok) throw new Error(r.status); return r.json(); };
  const ok = async u => { try { return await jget(u); } catch (e) { return null; } };
  const CONF = { sea: 'sea_view', night: 'night_quiet', beach: 'beach_walk' };

  function copy(btn, text) {
    const label = btn.textContent;
    const done = () => { btn.textContent = 'Скопировано'; btn.classList.add('done'); setTimeout(() => { btn.textContent = label; btn.classList.remove('done'); }, 2000); };
    const fb = () => { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); done(); } catch (e) { btn.textContent = 'Выделите текст вручную'; } ta.remove(); };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fb); else fb();
  }

  // Факты и тексты чипов; pick = {side, floor, room, request} или null
  function chips(ctx, pick) {
    const out = [];
    const conflict = k => { const c = (ctx.truth && ctx.truth.chars || []).find(x => x.char === CONF[k] && x.status === 'conflict' && x.sentence); return c ? c.sentence : null; };
    const w = ctx.win;
    if (w && typeof w.sea_p === 'number') {
      const p = Math.round(w.sea_p * 100);
      const fl = pick && pick.floor ? `${pick.floor}-й этаж` : 'верхний этаж';
      out.push({
        k: 'sea', cls: p >= 50 ? 'ok' : 'warn',
        text: p >= 15 ? `море видно в ${p}% вариантов расчёта (окна на ${dir(w.facade)}, ${fl})` : p > 0 ? `моря почти не видно (${p}%)` : 'моря из этих окон не видно',
        tip: `Источник: симулятор «Вид из окна», окна на ${dir(w.facade)}, ${fl}. Считаем по карте высот и зданиям OSM много раз со сдвигом позиции, это оценка, не измерение.`,
      });
    }
    const n = ctx.night;
    if (n && pick && pick.side) {
      const f = (n.facades || []).find(x => x.dir === pick.side);
      const wst = n.window_assumed || 'closed';
      const sl = f && f.sleep && f.sleep[wst];
      if (sl) {
        const lvl = sl.at_floor ? '≤20 дБ' : `около ${Math.round(sl.night_mean_indoor)} дБ`;
        const thr = n.threshold ? n.threshold.indoor_db : 30;
        const why = n.air_conditioning && n.air_conditioning.has ? 'в карточке есть кондиционер' : 'кондиционера в карточке нет';
        out.push({
          k: 'night', cls: sl.night_mean_indoor <= thr || sl.at_floor ? 'ok' : 'warn',
          text: `ночью ${lvl} в комнате, окно ${wst === 'closed' ? 'закрыто' : 'открыто'}`,
          tip: `Источник: график «Ночь по часам», сторона ${dir(pick.side)}, окно ${wst === 'closed' ? 'закрыто' : 'открыто'} (${why}). Порог для сна: ${String(thr).replace('.', ',')} дБ в спальне (ВОЗ). Не учтены дома, которые закрывают от шума.`,
        });
      }
    }
    const b = ctx.beach;
    if (b && b.value && typeof b.value.minutes_there === 'number') {
      const v = b.value, m = Math.max(1, Math.round(v.minutes_there));
      out.push({
        k: 'beach', cls: m <= 10 && v.climb_back_m < 30 ? 'ok' : 'warn',
        text: `пляж ${m} мин` + (v.climb_back_m >= 3 ? `, подъём ${Math.round(v.climb_back_m)} м` : ''),
        tip: `Источник: ${b.source || 'расчёт по геоданным'}, ${(b.facts && b.facts[0] && b.facts[0].method) || 'пеший граф OSM и рельеф'}. ${b.summary}.`,
      });
    }
    out.forEach(c => {
      const s = conflict(c.k);
      if (!s) return;
      const m = s.match(/(\d+) из (\d+)/);
      const calcYes = s.startsWith('Расчёт показывает');
      if (c.k === 'night') c.text = calcYes ? (m ? `ночью тихо по расчёту, но ${m[1]} из ${m[2]} гостей жалуются на шум` : 'ночью тихо по расчёту, но гости жалуются на шум') : 'гости хвалят тишину, а расчёт показывает шум';
      else if (c.k === 'sea') c.text = calcYes ? 'море по расчёту видно, но гости пишут иное' : 'гости пишут про вид на море, а расчёт его не находит';
      else c.text += ', но отзывы говорят иное';
      c.cls = 'warn'; c.tip = s + ' ' + c.tip;
    });
    return out;
  }

  function lineOf(ctx, pick) {
    if (!pick || !pick.side) return { cls: 'none', html: 'Просить нечего: по расчёту стороны не отличаются' };
    const sea = ctx.win && typeof ctx.win.sea_p === 'number' ? ctx.win.sea_p : null;
    const fl = pick.floor > 1 ? `, <b>от ${pick.floor}-го этажа</b>` : '';
    if (pick.room && sea !== null && sea >= 0.5) return { cls: '', html: `Берите <b>${E(pick.room)}</b> · просите <b>окна на ${E(dir(pick.side))}${fl}</b>` };
    return { cls: 'none', html: `Моря из окон не обещаем · просите <b>окна на ${E(dir(pick.side))}${fl}</b>` };
  }

  function draw(band, ctx, pick) {
    const ln = lineOf(ctx, pick);
    const cs = chips(ctx, pick);
    const req = pick && pick.request ? pick.request : '';
    band.className = 'vd ' + ln.cls;
    band.innerHTML = `<div class="vd-line">${ln.html}</div>
      ${cs.length ? `<div class="vd-chips">${cs.map((c, i) => `<button type="button" class="vd-chip ${c.cls}" data-i="${i}" title="${E(c.tip)}" aria-label="${E(c.text + '. ' + c.tip)}">${E(c.text)}</button>`).join('')}</div><div class="vd-src" hidden></div>` : ''}
      ${req ? `<div class="vd-act"><button type="button" class="vd-copy">Скопировать просьбу</button></div><div class="vd-req">${E(req)}</div>` : ''}`;
    const src = band.querySelector('.vd-src');
    band.querySelectorAll('.vd-chip').forEach(b => b.onclick = () => {
      const was = b.classList.contains('on');
      band.querySelectorAll('.vd-chip').forEach(x => x.classList.remove('on'));
      if (was) { src.hidden = true; return; }
      b.classList.add('on'); src.textContent = cs[+b.dataset.i].tip; src.hidden = false;
    });
    const cb = band.querySelector('.vd-copy');
    if (cb) cb.onclick = () => copy(cb, req);
  }

  const REV = Object.fromEntries(Object.entries(DIR).map(([k, v]) => [v, k]));
  // Рекомендация движка номеров: сторону берём из структуры или из текста его же просьбы; без просьбы просить нечего
  function pickOf(advice) {
    const b = advice && advice.best;
    const request = b && b.special_request;
    if (!request) return null;
    const m = request.match(/окнами на ([а-яё-]+)/i);
    const side = (b.ask && b.ask.side) || (m && REV[m[1]]) || null;
    if (!side) return null;
    return { side, floor: (b.ask && b.ask.min_floor) || null, room: b.room, request, own: !(b.ask && b.ask.side) };
  }

  const dispatchSide = (id, pick) => {
    window.verdictPick = pick && pick.own ? { hotel_id: id, side: pick.side, floor: pick.floor } : null;
    if (window.verdictPick) document.dispatchEvent(new CustomEvent('verdict:side', { detail: window.verdictPick }));
  };

  async function apply(band, base, pick) {
    const id = band.dataset.hid;
    const ctx = Object.assign({}, base);
    ctx.win = await ok(`/api/hotels/${id}/window` + (pick && pick.side ? `?facade=${encodeURIComponent(pick.side)}` + (pick.floor ? `&floor=${pick.floor}` : '') : ''));
    if (!band.isConnected || band.dataset.hid !== id) return;
    dispatchSide(id, pick);
    draw(band, ctx, pick);
  }

  async function build(id, band) {
    const [rooms, night, truth, hotel] = await Promise.all([ok(`/api/rooms/${id}?wants=sea,quiet`), ok(`/api/hotels/${id}/night`), ok(`/api/truth/hotel/${id}`), ok(`/api/hotels/${id}`)]);
    const beach = hotel && (hotel.facts || []).find(f => f.char === 'beach_walk' && f.status !== 'unknown');
    band._ctx = { night, truth, beach, win: null };
    const pick = pickOf(rooms);
    band._key = JSON.stringify(pick);
    await apply(band, band._ctx, pick);
  }

  // Блок «Какой номер брать» меняет выбор: подстраиваем вердикт под него
  document.addEventListener('rooms:best', async ev => {
    const band = document.getElementById('vd');
    const d = ev.detail;
    if (!band || !band._ctx) return;
    let pick;
    if (d) {
      if (String(d.hotel_id) !== band.dataset.hid) return;
      const req = document.querySelector('#hotel .rm .rm-copy[data-req]');
      pick = { side: d.side, floor: +d.floor || null, room: d.room, request: req ? req.dataset.req : '' };
    } else {
      // рекомендации нет (например, снят «Море»): спрашиваем движок номеров с теми же пожеланиями
      const w = [...document.querySelectorAll('#hotel .rm .wants button.on')].map(b => b.dataset.w).join(',') || 'sea,quiet';
      pick = pickOf(await ok(`/api/rooms/${band.dataset.hid}?wants=${w}`));
    }
    const key = JSON.stringify(pick);
    if (band._key === key) return;
    band._key = key;
    apply(band, band._ctx, pick);
  });

  const openHotel0 = window.openHotel;
  window.openHotel = async function openHotel(id) {
    const r = await openHotel0(id);
    const host = document.getElementById('hotel');
    const grid = host && host.querySelector('.grid');
    if (!grid) return r;
    const old = document.getElementById('vd'); if (old) old.remove();
    const oldh = host.querySelector('.vd-head'); if (oldh) oldh.remove();
    const left = grid.firstElementChild;
    const head = document.createElement('div');
    head.className = 'vd-head';
    const h2 = left.querySelector('h2'); if (h2) head.appendChild(h2);
    const addr = left.querySelector('.muted'); if (addr) head.appendChild(addr);
    const band = document.createElement('div');
    band.id = 'vd'; band.className = 'vd none'; band.dataset.hid = String(id);
    band.innerHTML = '<div class="vd-line wait">Считаю, какой номер брать…</div>';
    grid.insertAdjacentElement('beforebegin', head);
    head.insertAdjacentElement('afterend', band);

    const rooms = [...left.querySelectorAll('.small.muted')].find(e => e.textContent.trim().startsWith('Номера:'));
    if (rooms) {
      const d = document.createElement('details');
      d.className = 'vd-rooms';
      d.innerHTML = '<summary>Все категории номеров</summary>';
      rooms.insertAdjacentElement('beforebegin', d);
      d.appendChild(rooms);
    }
    const wait = [...left.querySelectorAll('h3')].find(e => e.textContent.startsWith('Ждём ответа'));
    const table = host.querySelector('table.ft');
    if (wait && table) {
      const box = document.createElement('div');
      box.className = 'vd-wait';
      for (let n = wait; n;) { const nx = n.nextElementSibling; box.appendChild(n); n = nx && nx.classList.contains('q') ? nx : null; }
      table.insertAdjacentElement('afterend', box);
    }
    build(id, band).catch(() => { band.innerHTML = '<div class="vd-line wait">Вердикт недоступен, факты ниже.</div>'; });
    return r;
  };
})();
