// Блок «Ночь по часам» в карточке отеля: уровень шума по сторонам здания с 20:00 до 09:00.
(function () {
    const HOURS = [20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
  const st = { id: null, win: null, data: null, pick: null };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const css = `
.nl{margin-top:18px}.nl h3{margin:0 0 4px}
.nl .nl-bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0}
.nl .seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.nl .seg button{border:0;background:var(--card);color:var(--muted);padding:9px 14px;cursor:pointer;font:inherit;font-size:13px;min-height:40px}
.nl .seg button.on{background:var(--acc-soft);color:var(--acc);font-weight:600}
.nl .nl-advice{font-size:14px;font-weight:600;margin:6px 0}
.nl svg{display:block;width:100%;height:auto;overflow:visible}
.nl .ax{stroke:var(--line);stroke-width:1}.nl .tx{fill:var(--muted);font-size:11px}.nl .tl{font-size:12px;font-weight:600}
.nl .night{fill:var(--unk-soft)}.nl .thr{stroke:var(--bad);stroke-width:1.5;stroke-dasharray:5 4}.nl .thr-t{fill:var(--bad);font-size:11px}
.nl .fl{display:grid;grid-template-columns:1fr;gap:4px;margin:8px 0;padding:0;list-style:none;font-size:12.5px}
.nl .fl li{display:flex;gap:8px;align-items:baseline}.nl .dot{width:10px;height:10px;border-radius:50%;flex:none;transform:translateY(1px)}
.nl .note{font-size:12px;color:var(--muted);margin-top:6px}.nl .halo{stroke:var(--acc-soft)}`;
  const style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);
  const COLORS = ['#7a5af8', '#0b63f6', '#b54708', '#c01048', '#0e9384', '#667085', '#dd2590', '#a15c07'];

  function cssv(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim() || '#888'; }

  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  const dirName = f => f.dir_name || f.dir;
  const dB = v => Math.round(v);

  // ваша сторона: window.bestPick {hotel_id, side, floor} или событие rooms:best на document
  function readPick(p) {
    if (p && p.side && (!p.hotel_id || p.hotel_id === st.id)) return { side: String(p.side).toLowerCase(), floor: p.floor };
    return null;
  }
  function isPick(f) {
    return !!st.pick && (f.dir.toLowerCase() === st.pick.side || dirName(f).toLowerCase() === st.pick.side);
  }

  // стороны с одинаковой кривой рисуем одной линией с общей подписью
  function groups() {
    const m = new Map();
    st.data.facades.forEach((f, i) => {
      const v = series(f), k = v.map(x => x.toFixed(1)).join('|');
      if (!m.has(k)) m.set(k, { v, items: [] });
      m.get(k).items.push({ f, i });
    });
    return [...m.values()].map(g => ({
      v: g.v, items: g.items, i: g.items[0].i,
      quietest: g.items.some(x => x.f.quietest), pick: g.items.some(x => isPick(x.f)),
      name: g.items.length === st.data.facades.length && g.items.length > 2 ? 'Все стороны' : g.items.map(x => cap(dirName(x.f))).join(', '),
    }));
  }

  function series(f) {
    const key = st.win === 'open' ? 'indoor_open' : 'indoor_closed';
    return HOURS.map(h => f[key][h] != null ? f[key][h] : f[key][String(h)]);
  }

  function chart(box) {
    const d = st.data, W = Math.max(300, box.clientWidth || 340), H = W < 460 ? 250 : 290;
    const gs = groups(), lab = g => g.name + (g.pick ? ' (ваша)' : '');
    const m = { l: 40, r: Math.min(130, Math.max(...gs.map(g => lab(g).length)) * 6.8 + 10), t: 14, b: 44 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
    const all = d.facades.flatMap(series);
    const lo = Math.floor((Math.min(...all, d.threshold.indoor_db) - 2) / 5) * 5, hi = Math.ceil((Math.max(...all, d.threshold.indoor_db + 4) + 1) / 5) * 5;
    const x = i => m.l + iw * i / (HOURS.length - 1), y = v => m.t + ih * (1 - (v - lo) / (hi - lo));
    const ok = cssv('--ok');
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Шум внутри номера по часам, по сторонам здания">`;
    // ночное окно 23:00-07:00
    s += `<rect class="night" x="${x(3)}" y="${m.t}" width="${x(11) - x(3)}" height="${ih}"/>`;
    s += `<text class="tx" x="${(x(3) + x(11)) / 2}" y="${m.t + 11}" text-anchor="middle">ночь для сна</text>`;
    for (let v = lo; v <= hi; v += 5) {
      s += `<line class="ax" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text class="tx" x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
    }
    HOURS.forEach((h, i) => {
      if (i % (W < 400 ? 3 : W < 560 ? 2 : 1) === 0) s += `<text class="tx" x="${x(i)}" y="${H - m.b + 16}" text-anchor="middle">${String(h).padStart(2, '0')}:00</text>`;
    });
    s += `<text class="tx" x="${m.l + iw / 2}" y="${H - 6}" text-anchor="middle">время суток</text>`;
    s += `<text class="tx" transform="translate(11 ${m.t + ih / 2}) rotate(-90)" text-anchor="middle">дБ(A) внутри номера</text>`;
    const thr = d.threshold.indoor_db;
    s += `<line class="thr" x1="${m.l}" x2="${W - m.r}" y1="${y(thr)}" y2="${y(thr)}"/><text class="thr-t" x="${m.l + 4}" y="${y(thr) + 13}">порог сна ВОЗ ${thr} дБ</text>`;
    // линии: тихая сторона сверху, подпись в конце линии с разведением
    const order = gs.slice().sort((a, b) => (a.quietest ? 1 : 0) - (b.quietest ? 1 : 0) || (a.pick ? 1 : 0) - (b.pick ? 1 : 0));
    const ends = order.map(o => ({ o, y: y(o.v[o.v.length - 1]) })).sort((a, b) => a.y - b.y);
    for (let k = 1; k < ends.length; k++) if (ends[k].y - ends[k - 1].y < 14) ends[k].y = ends[k - 1].y + 14;
    order.forEach(o => {
      const c = o.quietest ? ok : COLORS[o.i % COLORS.length], w = o.quietest || o.pick ? 3.5 : 1.8, op = o.quietest || o.pick ? 1 : .8;
      const pts = o.v.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
      if (o.pick) s += `<polyline class="halo" points="${pts}" fill="none" stroke-width="10" stroke-linejoin="round" stroke-linecap="round"/>`;
      s += `<polyline points="${pts}" fill="none" stroke="${c}" stroke-width="${w}" stroke-linejoin="round" opacity="${op}"><title>${esc(o.name)}</title></polyline>`;
    });
    ends.forEach(e => {
      const c = e.o.quietest ? ok : COLORS[e.o.i % COLORS.length];
      s += `<text class="tl" x="${W - m.r + 5}" y="${e.y + 4}" fill="${c}">${esc(lab(e.o))}</text>`;
    });
    return s + '</svg>';
  }

  function paint() {
    const box = document.getElementById('nl-body');
    if (!box || !st.data) return;
    const d = st.data, w = st.win;
    st.pick = st.pick || readPick(window.bestPick);
    const ac = d.air_conditioning;
    const advice = d.advice_by_window[w];
    box.innerHTML = `<div class="nl-advice">${esc(advice)}</div><div id="nl-chart">${''}</div>
<ul class="fl">${groups().map(g => {
      const sl = g.items[0].f.sleep[w], c = g.quietest ? cssv('--ok') : COLORS[g.i % COLORS.length];
      const t = sl.hours_above === 0 ? 'тихо всю ночь' : sl.hours_above >= d.night_window.length ? `шумно всю ночь${sl.cause ? ', из-за ' + esc(sl.cause) : ''}`
        : `шумно ${sl.hours_above} из ${d.night_window.length} ночных часов${sl.cause ? ', из-за ' + esc(sl.cause) : ''}`;
      const lvl = sl.at_floor ? '≤20 дБ (фон)' : `в среднем ${dB(sl.night_mean_indoor)} дБ`;
      return `<li><span class="dot" style="background:${c}"></span><span><b>${esc(g.name)}</b>${g.quietest ? ' (самая тихая)' : ''}${g.pick ? ' (ваша сторона)' : ''}: ${t}, ${lvl}</span></li>`;
    }).join('')}</ul>
<div class="note">В поиске «тихо» значит ночью снаружи тише 55 дБ; здесь видно, что будет в комнате.</div>
<div class="note">${ac.has ? 'В карточке есть кондиционер, поэтому по умолчанию окно закрыто.' : 'Кондиционера в карточке нет, поэтому по умолчанию окно открыто.'} ${esc(d.threshold.why)}.</div>
<details><summary>что неточно</summary>${d.uncertainty.map(u => `<div class="note">${esc(u)}</div>`).join('')}</details>`;
    document.getElementById('nl-chart').innerHTML = chart(document.getElementById('nl-chart'));
    document.querySelectorAll('.nl .seg button').forEach(b => b.classList.toggle('on', b.dataset.w === w));
  }

  async function load() {
    const body = document.getElementById('nl-body');
    if (body) body.innerHTML = '<div class="muted">Считаю ночь по часам…</div>';
    try {
      const r = await fetch(`/api/hotels/${st.id}/night`);
      if (!r.ok) throw new Error(r.status);
      st.data = await r.json();
      if (!st.win) st.win = st.data.window_assumed;
      paint();
    } catch (e) {
      if (body) body.innerHTML = '<div class="muted">Не удалось посчитать ночь по часам.</div>';
    }
  }

  function mount(id) {
    const host = document.getElementById('hotel');
    if (!host) return;
    st.id = id; st.win = null; st.data = null; st.pick = readPick(window.bestPick);
    const el = document.createElement('div');
    el.className = 'nl';
    el.innerHTML = `<h3>Ночь по часам</h3><div class="muted small">Удастся ли выспаться: шум с каждой стороны здания с 20:00 до 09:00 по дорогам, железной дороге и барам.</div>
<div class="nl-bar"><div class="seg" role="group" aria-label="Окно"><button data-w="open">окно открыто</button><button data-w="closed">окно закрыто</button></div></div>
<div id="nl-body"></div>`;
    const anchor = host.querySelector(':scope > h3');
    host.insertBefore(el, anchor);  // перед таблицей фактов
    el.querySelectorAll('.seg button').forEach(b => b.onclick = () => { st.win = b.dataset.w; paint(); });
    load();
  }

  const orig = window.openHotel;
  window.openHotel = async function openHotel(id) {
    const r = await orig(id);
    mount(id);
    return r;
  };
  document.addEventListener('rooms:best', e => { st.pick = readPick(e.detail); paint(); });
  let t; window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(paint, 150); });
})();
