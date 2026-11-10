/* Подбор номера: блок «Какой номер брать» в карточке отеля, строка «Брать / попросить» в выдаче поиска,
   скрытые сильные стороны в кабинете отельера. Подключается одной строкой в index.html, свои стили вносит сам. */
(function () {
  const css = `
.rm{margin-top:14px}.rm h2{margin-bottom:4px}.rm .sub{color:var(--muted);font-size:12.5px;margin-bottom:8px}
.rm .wants{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:8px 0}
.rm .wants button{border:1px solid var(--line);background:none;color:var(--ink);border-radius:99px;padding:6px 12px;font-size:12.5px;cursor:pointer;min-height:34px}
.rm .wants button.on{background:var(--acc-soft);color:var(--acc);border-color:var(--acc);font-weight:600}
.rm .wants select{padding:5px 8px;min-height:34px}
.rm-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:10px}
.rm-c{border:1px solid var(--line);border-radius:12px;padding:12px;background:var(--card);display:flex;flex-direction:column;gap:7px;min-width:0}
.rm-c.best{border-color:var(--ok);box-shadow:0 0 0 1px var(--ok) inset}
.rm-c .nm{font-weight:600;overflow-wrap:anywhere}.rm-c .tags{display:flex;gap:4px;flex-wrap:wrap}
.rm-p{display:flex;align-items:center;gap:8px;font-size:12.5px}.rm-p .bar{flex:1;height:8px;background:var(--line);border-radius:4px;overflow:hidden}
.rm-p .bar i{display:block;height:8px;border-radius:4px;background:var(--ok)}.rm-p .bar i.mid{background:var(--muted)}.rm-p .bar i.low{background:var(--warn)}
.rm-p b{min-width:38px;text-align:right}.rm-p{flex-wrap:wrap}.rm-p>span:first-child{flex-basis:100%}.rm-p .bar{min-width:80px}
.rm-ask{font-size:13px;background:var(--bg);border-radius:8px;padding:8px 10px}
.rm-ask .lbl{color:var(--muted);font-size:11.5px;display:block}
.rm-copy{border:0;background:var(--acc);color:#fff;border-radius:8px;padding:9px 12px;font-weight:600;cursor:pointer;min-height:40px;font-size:13px}
.rm-copy.done{background:var(--ok)}
.rm-c details{font-size:12px}.rm-c details ul{margin:6px 0 0;padding-left:16px;color:var(--muted)}.rm-c details li{margin:3px 0}
.rm-copy.ghost{background:none;color:var(--acc);border:1px solid var(--acc);min-height:34px;padding:5px 10px;font-weight:500;white-space:nowrap}
.rm-copy.ghost.done{background:var(--ok);color:#fff;border-color:var(--ok)}
.rm-rows{display:flex;flex-direction:column;gap:6px;margin-top:10px}
.rm-r{border:1px solid var(--line);border-radius:10px;background:var(--card);min-width:0}
.rm-r>summary{color:var(--ink);display:flex;align-items:center;gap:10px;padding:8px 10px;cursor:pointer;list-style:none;font-size:13px}
.rm-r>summary::-webkit-details-marker{display:none}
.rm-r .nm{flex:1;min-width:0;overflow-wrap:anywhere;font-weight:500}.rm-r .pp{color:var(--muted);font-size:12.5px;white-space:nowrap}
.rm-r .pp.low{color:var(--warn)}.rm-r .body{padding:0 10px 10px;display:flex;flex-direction:column;gap:7px}
.rm-r ul{margin:0;padding-left:16px;color:var(--muted);font-size:12px}.rm-r li{margin:3px 0}
.rm-more{margin-top:10px}.rm-note{color:var(--muted);font-size:12px;margin-top:10px}
.rm-line{font-size:12.5px;margin-top:6px;padding:6px 9px;border-radius:8px;background:var(--ok-soft);color:var(--ink)}
.rm-line b{color:var(--ok)}
@media(max-width:600px){#hotel table{display:block;overflow-x:auto}.rm-cards{grid-template-columns:1fr}.rm-c .rm-copy{width:100%}.rm-r>summary{flex-wrap:wrap}.rm-r .nm{flex-basis:100%}}`;
  const st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);

  const E = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const MONTHS = ['янв', 'фев', 'мар', 'апр', 'ма', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  const WANTS = [['sea', 'Море'], ['quiet', 'Тишина ночью'], ['sunset', 'Закат']];
  const state = { wants: ['sea', 'quiet'], month: new Date().getMonth() + 1 };

  const DIR = { 'С': 'север', 'СВ': 'северо-восток', 'В': 'восток', 'ЮВ': 'юго-восток', 'Ю': 'юг', 'ЮЗ': 'юго-запад', 'З': 'запад', 'СЗ': 'северо-запад' };
  const floorText = a => !a || !a.min_floor || a.min_floor <= 1 ? 'любой этаж'
    : a.levels && a.min_floor >= a.levels ? `на последнем (${a.levels}-м) этаже` : `не ниже ${a.min_floor}-го этажа`;
  const askText = a => a && a.side ? `окна на ${DIR[a.side] || a.side}, ${floorText(a)}` : '';
  const askFrom = a => a && a.side ? `окна на ${DIR[a.side] || a.side}` + (a.min_floor && a.min_floor > 1 ? (a.levels && a.min_floor >= a.levels ? ', на последнем этаже' : `, от ${a.min_floor}-го этажа`) : '') : '';
  const barCls = p => p >= 0.6 ? '' : p >= 0.3 ? 'mid' : 'low';
  const plural = (n, one, few, many) => { const m = n % 100, d = n % 10; return n + ' ' + (m > 10 && m < 20 ? many : d === 1 ? one : d >= 2 && d <= 4 ? few : many); };
  const TIP = 'Оценка по геометрии здания и отзывам гостей этой категории, не измерение. Этаж считаем подходящим, когда вероятность моря не ниже 0,8 (если таких этажей нет, берём первый с 0,5).';

  function copy(btn, text) {
    const ok = () => { const t = btn.textContent; btn.textContent = 'Скопировано'; btn.classList.add('done'); setTimeout(() => { btn.textContent = t; btn.classList.remove('done'); }, 2000); };
    const fb = () => { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); ok(); } catch (e) { btn.textContent = 'Выделите текст вручную'; } ta.remove(); };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(ok, fb); else fb();
  }

  const tagsOf = r => [r.claims_sea_view ? '<span class="badge bm">море в названии</span>' : '',
    r.windowless ? '<span class="badge bf">без окна</span>' : '',
    r.hidden_view ? '<span class="badge bq">скрытый вид</span>' : '',
    r.other_view ? `<span class="badge bu">вид: ${E(r.other_view)}</span>` : '',
    r.balcony ? '<span class="badge bu">балкон</span>' : '',
    r.size_m2 ? `<span class="badge bu">${r.size_m2} м²</span>` : '',
    r.guests && r.guests.praise_sea ? `<span class="badge bm">гости хвалят вид: ${r.guests.praise_sea}</span>` : '',
    r.guests && r.guests.deny_sea ? `<span class="badge bf">жалобы на вид: ${r.guests.deny_sea}</span>` : ''].join('');
  const askBlock = r => r.special_request
    ? `<div class="rm-ask"><span class="lbl">Что написать в бронь (${E(askText(r.ask) || 'окна на тихую сторону')})</span>${E(r.special_request)}</div>
       <button class="rm-copy" type="button" data-req="${E(r.special_request)}">Скопировать просьбу</button>`
    : `<div class="rm-ask"><span class="lbl">Просить нечего</span>${r.windowless ? 'В номере нет настоящего окна, море не видно.' : 'Сторону и этаж по расчёту выбирать незачем.'}</div>`;
  const evid = r => `<details><summary>откуда это</summary><ul>${r.evidence.map(x => `<li>${E(x)}</li>`).join('')}</ul></details>`;

  function heroCard(r, generic) {
    if (generic) return `<div class="rm-c best"><div class="nm">Любая категория</div>${askBlock(r)}</div>`;
    const p = Math.round(r.sea_view_p * 100);
    const ap = r.ask && r.ask.side && r.ask.p != null ? Math.round(r.ask.p * 100) : null;
    return `<div class="rm-c best"><div class="nm">★ ${E(r.room)}</div><div class="tags">${tagsOf(r)}</div>
      <div class="rm-p" title="${E(TIP)}"><span>море в случайном номере категории</span><span class="bar"><i class="${barCls(r.sea_view_p)}" style="width:${p}%"></i></span><b>${p}%</b></div>
      ${ap != null ? `<div style="font-size:12.5px">с просьбой (${E(askFrom(r.ask))}): <b>${ap}%</b></div>` : ''}
      ${askBlock(r)}${evid(r)}</div>`;
  }

  function row(r) {
    const p = Math.round(r.sea_view_p * 100);
    return `<details class="rm-r"><summary><span class="nm">${E(r.room)}</span>
      <span class="pp ${barCls(r.sea_view_p) === 'low' ? 'low' : ''}" title="${E(TIP)}">море в случайном номере категории: ${p}%</span>
      ${r.special_request ? `<button class="rm-copy ghost" type="button" data-req="${E(r.special_request)}">Скопировать</button>` : ''}</summary>
      <div class="body"><div class="tags">${tagsOf(r)}</div>${askBlock(r)}${evid(r)}</div></details>`;
  }

  function publish(hid, d) {
    const b = d.best;
    const pick = b && b.ask && b.ask.side ? { hotel_id: hid, side: b.ask.side, floor: b.ask.min_floor, room: b.room } : null;
    window.bestPick = pick;
    document.dispatchEvent(new CustomEvent('rooms:best', { detail: pick }));
  }

  function draw(box, d, hid) {
    const rooms = d.rooms;
    const best = d.best;
    const rest0 = rooms.filter(r => !best || r.room !== best.room);
    const shown = rest0.filter(r => r.sea_view_p >= 0.3 || r.hidden_view).slice(0, 6);
    const rest = rest0.filter(r => !shown.includes(r));
    const same = d.same_p && rooms.length > 1;
    const sameP = d.same_p_value != null ? Math.round(d.same_p_value * 100) : 0;
    const generic = same || !!d.note;
    box.innerHTML = `<h2>Какой номер брать</h2>
      <div class="sub">Номер назначают при заселении. Здесь видно, какая категория и какая сторона здания дают то, что вы хотите, и что написать в бронь.</div>
      <div class="wants" role="group" aria-label="Что важно">${WANTS.map(([k, v]) => `<button type="button" data-w="${k}" class="${state.wants.includes(k) ? 'on' : ''}">${v}</button>`).join('')}
      ${state.wants.includes('sunset') ? `<select aria-label="Месяц">${MONTHS.map((m, i) => `<option value="${i + 1}" ${state.month == i + 1 ? 'selected' : ''}>${['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'][i]}</option>`).join('')}</select>` : ''}</div>
      ${d.note ? `<div class="rm-note">${E(d.note)}</div>` : ''}
      ${same ? `<div class="rm-note">У всех категорий одна оценка моря (${sameP}%): категория не важна, важны сторона и этаж.</div>` : ''}
      ${best ? `<div class="rm-cards">${heroCard(best, generic)}</div>` : '<div class="muted">Подходящих категорий нет.</div>'}
      ${!same && shown.length ? `<div class="rm-rows">${shown.map(row).join('')}</div>` : ''}
      ${!same && rest.length ? `<details class="rm-more"><summary>ещё ${plural(rest.length, 'категория', 'категории', 'категорий')}</summary><div class="rm-rows">${rest.map(row).join('')}</div></details>` : ''}
      <div class="rm-note">${E(d.honesty)}</div>`;
    box.querySelectorAll('.wants button').forEach(b => b.onclick = () => {
      const w = b.dataset.w, i = state.wants.indexOf(w);
      if (i >= 0) { if (state.wants.length > 1) state.wants.splice(i, 1); } else state.wants.push(w);
      load(box, hid);
    });
    const sel = box.querySelector('.wants select');
    if (sel) sel.onchange = () => { state.month = +sel.value; load(box, hid); };
    box.querySelectorAll('.rm-copy').forEach(b => b.onclick = e => { e.preventDefault(); e.stopPropagation(); copy(b, b.dataset.req); });
    publish(hid, d);
  }

  async function load(box, hid) {
    const q = `wants=${state.wants.join(',')}` + (state.wants.includes('sunset') ? `&month=${state.month}` : '');
    try { draw(box, await api(`/api/rooms/${hid}?${q}`), hid); } catch (e) { box.innerHTML = `<div class="muted">Подбор номера недоступен: ${E(e.message)}</div>`; }
  }

  const openHotel0 = window.openHotel;
  window.openHotel = async function (id) {
    const r = await openHotel0(id);
    const host = document.getElementById('hotel');
    const grid = host && host.querySelector('.grid');
    if (grid) {
      const box = document.createElement('div');
      box.className = 'card rm';
      box.textContent = 'Считаю…';
      grid.insertAdjacentElement('afterend', box);
      load(box, id);
    }
    return r;
  };

  const render0 = window.renderResults;
  window.renderResults = function (s) {
    render0(s);
    const wants = ['sea_view', 'night_quiet', 'sunset'].filter(c => (s.parsed.constraints || []).some(x => x.char === c))
      .map(c => ({ sea_view: 'sea', night_quiet: 'quiet', sunset: 'sunset' }[c]));
    if (!wants.length) return;
    const cards = [...document.querySelectorAll('#results .card.h')];
    const ids = cards.map(c => (c.innerHTML.match(/openHotel\('([^']+)'\)/) || [])[1]);
    const mi = s.month ? MONTHS.findIndex(m => String(s.month).toLowerCase().startsWith(m)) + 1 : 0;
    fetch(`/api/rooms?ids=${ids.filter(Boolean).join(',')}&wants=${wants.join(',')}` + (mi ? `&month=${mi}` : ''))
      .then(r => r.json()).then(m => cards.forEach((c, i) => {
        const x = m[ids[i]];
        const lines = c.querySelector('.lines');
        if (!x || !lines) return;
        lines.insertAdjacentHTML('afterend', `<div class="rm-line">Брать: <b>${E(x.room)}</b>; попросить: ${E(askText(x.ask) || 'окна на тихую сторону')}${x.hidden_view ? ' (море, вероятно, видно, хотя в карточке это не сказано)' : ''}</div>`);
      })).catch(() => { });
  };

  const cab0 = window.openCabinet;
  window.openCabinet = async function (id) {
    const r = await cab0(id);
    try {
      const d = await api('/api/hotelier/' + id);
      if (d.hidden_strengths && d.hidden_strengths.length) {
        document.getElementById('cab').insertAdjacentHTML('beforeend', `<h3>Скрытые сильные стороны</h3><ul class="lines">${d.hidden_strengths.map(x => `<li class="ok">✅ ${E(x.text)}</li>`).join('')}</ul>`);
      }
    } catch (e) { }
    return r;
  };
})();
