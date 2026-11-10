/* Вид из окна: панорама из выбранной стороны здания и этажа, закат месяца. Встраивается в карточку отеля. */
(function () {
  const MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];
  const e = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  const css = document.createElement('style');
  css.textContent = `
.wv{margin:14px 0 4px;padding:14px;border:1px solid var(--line);border-radius:12px;background:var(--card)}
.wv h3{margin:0 0 2px;font-size:15px}
.wv .sub{color:var(--muted);font-size:12px;margin-bottom:10px}
.wv .ctl{display:grid;grid-template-columns:auto 1fr auto;gap:10px 16px;align-items:center;margin-bottom:10px}
.wv .lab{font-size:12px;color:var(--muted);white-space:nowrap}
.wv .fac{display:flex;gap:6px;flex-wrap:wrap}
.wv .fac button{min-height:44px;min-width:44px;padding:4px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink);font:inherit;font-size:13px;cursor:pointer;line-height:1.15}
.wv .fac button small{display:block;font-size:10.5px;color:var(--muted)}
.wv .fac button.on{background:var(--acc-soft);border-color:var(--acc);color:var(--acc);font-weight:600}
.wv .fac button.on small{color:var(--acc)}
.wv .fl{display:flex;align-items:center;gap:10px;min-width:0}
.wv input[type=range]{flex:1;min-width:0;height:44px;margin:0;accent-color:var(--acc);background:none;border:0;padding:0;cursor:pointer}
.wv .fn{font-weight:700;font-size:16px;min-width:2.2em;text-align:right}
.wv select{min-height:44px;font-size:14px}
.wv .pic{position:relative;min-height:90px;transition:opacity .12s}
.wv .pic.busy{opacity:.6}
.wv .pic svg{max-width:900px}
.wv .cap,.wv .note,.wv .legend{max-width:900px}
.wv .chips{display:none;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.wv .chips span{padding:5px 12px;border-radius:999px;background:#0b1026;color:#fff;font-size:13px;font-weight:600;line-height:1.25}
.wv .legend{margin:-4px 0 10px;font-size:12px;color:var(--muted)}
.wv .pick{margin-top:6px;font-size:13px;font-weight:600;color:var(--acc)}
.wv .ctl{max-width:900px}
.wv .cap{margin-top:10px;font-size:15px;font-weight:600;line-height:1.35}
.wv .note{margin-top:4px;font-size:12px;color:var(--muted)}
@media(max-width:700px){.wv .ctl{grid-template-columns:1fr}.wv .lab{margin-bottom:-4px}}
@media(max-width:600px){.wv svg.wsvg{width:100%!important;height:200px!important}.wv svg .pill{display:none}.wv .chips{display:flex}.wv svg .cp{font-size:30px}.wv svg .sm{font-size:22px}}
`;
  document.head.appendChild(css);

  let current = null;
  document.addEventListener('rooms:best', ev => { if (current) current(ev.detail); else window.bestPick = ev.detail; });
  // сторона из вердикта, когда движок номеров не назвал структурную: window.verdictPick {hotel_id, side, floor}
  document.addEventListener('verdict:side', ev => { if (current) current(ev.detail); });

  function mount(hotelId) {
    const anchor = document.querySelector('#hotel .grid');
    if (!anchor) return;
    const old = document.getElementById('wv');
    if (old) old.remove();
    const box = document.createElement('div');
    box.id = 'wv';
    box.className = 'wv';
    box.innerHTML = '<h3>Вид из окна</h3><div class="sub">Считаем по карте высот и зданиям OSM: выберите сторону, этаж и месяц.</div><div class="pic busy" id="wv-pic">Считаю…</div>';
    anchor.insertAdjacentElement('afterend', box);

    const st = { facade: null, floor: null, month: 7, levels: 1, token: 0, timer: null, pick: null };
    const takePick = d => {
      if (d && String(d.hotel_id) === String(hotelId) && (d.side || d.facade)) st.pick = { side: d.side || d.facade, floor: +d.floor || null };
    };
    takePick(window.bestPick);
    if (!st.pick) takePick(window.verdictPick);
    if (st.pick) { st.facade = st.pick.side; st.floor = st.pick.floor; }
    current = d => { takePick(d); if (st.pick) { st.facade = st.pick.side; st.floor = st.pick.floor; get(); } };
    const get = async () => {
      const my = ++st.token;
      const q = new URLSearchParams({ month: st.month });
      if (st.facade) q.set('facade', st.facade);
      if (st.floor) q.set('floor', st.floor);
      const pic = document.getElementById('wv-pic');
      if (pic) pic.classList.add('busy');
      let w;
      try {
        const r = await fetch(`/api/hotels/${hotelId}/window?${q}`);
        if (!r.ok) throw new Error(await r.text());
        w = await r.json();
      } catch (err) {
        if (st.pick && my === st.token) { st.pick = null; st.facade = null; st.floor = null; return get(); }   // совет не подошёл к этому зданию
        if (my === st.token && pic) pic.textContent = 'Не удалось посчитать вид из окна.';
        return;
      }
      if (my !== st.token) return;       // пришёл устаревший ответ
      st.facade = w.facade; st.floor = w.floor; st.levels = w.levels;
      draw(w);
    };

    const draw = w => {
      const sea = w.facades.find(f => f.dir === w.facade);
      const first = document.getElementById('wv-ctl');
      if (!first) {
        box.querySelector('.sub').insertAdjacentHTML('afterend', `<div class="ctl" id="wv-ctl">
          <span class="lab">Сторона</span>
          <div class="fac" id="wv-fac"></div><span></span>
          <span class="lab">Этаж</span>
          <div class="fl"><input type="range" id="wv-floor" min="1" max="${w.levels}" step="1" aria-label="Этаж"><span class="fn" id="wv-fn"></span></div><span></span>
          <span class="lab">Месяц</span>
          <div><select id="wv-month" aria-label="Месяц">${MONTHS.map((m, i) => `<option value="${i + 1}"${i + 1 === st.month ? ' selected' : ''}>${m}</option>`).join('')}</select></div><span></span>
        </div>`);
        const fl = document.getElementById('wv-floor');
        fl.addEventListener('input', () => {
          st.floor = +fl.value;
          document.getElementById('wv-fn').textContent = st.floor;
          clearTimeout(st.timer);
          st.timer = setTimeout(get, 50);
        });
        document.getElementById('wv-month').addEventListener('change', ev => { st.month = +ev.target.value; get(); });
      }
      const fac = document.getElementById('wv-fac');
      fac.innerHTML = w.facades.map(f => `<button type="button" data-d="${e(f.dir)}" class="${f.dir === w.facade ? 'on' : ''}">${e(f.name)}<small>${f.sea_from_floor ? 'море с ' + f.sea_from_floor + '-го этажа' : 'моря нет'}</small></button>`).join('');
      fac.querySelectorAll('button').forEach(b => b.addEventListener('click', () => { st.facade = b.dataset.d; get(); }));
      let lg = document.getElementById('wv-legend');
      if (!lg) { lg = document.createElement('div'); lg.id = 'wv-legend'; lg.className = 'legend'; document.getElementById('wv-ctl').insertAdjacentElement('afterend', lg); }
      lg.textContent = 'Под названием стороны: с какого этажа море видно при расчёте по лучшим оценкам высот. Внизу показано, в какой доле вариантов расчёта оно видно именно с выбранного этажа.';
      const fl = document.getElementById('wv-floor');
      fl.max = w.levels; fl.value = w.floor;
      document.getElementById('wv-fn').textContent = w.floor;
      const picked = st.pick && st.pick.side === w.facade && (!st.pick.floor || st.pick.floor === w.floor);
      if (!picked) st.pick = null;
      const note = sea && sea.sea_from_floor
        ? `Расчёт ${sea.confidence >= 0.8 ? 'устойчив' : 'зависит от неточных высот соседних зданий'}: уверенность по стороне ${Math.round(sea.confidence * 100)}%.`
        : 'Мягкая светлая полоса показывает разброс по неточным высотам соседних зданий.';
      document.getElementById('wv-pic').className = 'pic';
      document.getElementById('wv-pic').innerHTML = `<div class="chips">${w.chips.map(c => `<span>${e(c)}</span>`).join('')}</div>` + w.svg +
        (picked ? '<div class="pick">Это вид из номера, который мы советуем</div>' : '') +
        `<div class="cap">${e(w.verdict)}</div><div class="note">Море видно в ${Math.round(w.sea_p * 100)}% вариантов расчёта: высоты соседних домов известны неточно, поэтому считаем много раз. ${w.note ? e(w.note) + ' ' : ''}${e(note)} Этажность взята из OSM, размер солнца на рисунке условный.</div>`;
    };

    get();
  }

  const orig = window.openHotel;
  if (typeof orig === 'function') {
    window.openHotel = async function openHotel(id) {
      await orig(id);
      mount(id);
    };
  }
})();
