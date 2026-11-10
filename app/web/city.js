/* Профиль города: что важно гостям в активном регионе. Веса характеристик (авто по описаниям, отзывам, разбросу и
   спросу, ручная правка, выключение) и параметры, которых нет в реестре, но их просят гости (спрос, сборка, одобрение).
   Подключается одной строкой в index.html до roles.js, стили вставляет сам. Работает поверх глобалов ($, esc, api, show, pl, dc, ruDate). */
(function () {
  const css = `
.ct-meta{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0 4px;font-size:13px;color:var(--muted)}
.ct-meta .g{margin-left:auto}
.ct-row{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(150px,1fr) 150px;gap:6px 16px;align-items:center;padding:10px 0;border-top:1px solid var(--line)}
.ct-row.off{opacity:.55}.ct-row b{font-size:14.5px}
.ct-desc{font-size:12px;color:var(--muted);margin-top:2px}
.ct-sig{grid-column:1/4;font-size:12px;color:var(--muted);display:flex;gap:4px 12px;flex-wrap:wrap}
.ct-w{display:flex;flex-direction:column;gap:4px}
.ct-w input{width:100%;accent-color:var(--acc)}
.ct-wv{font-size:12.5px;font-variant-numeric:tabular-nums}.ct-wv b{font-size:15px}
.ct-wv button{border:0;background:none;color:var(--acc);cursor:pointer;padding:0 0 0 4px;font-size:12px}
.ct-on{display:flex;gap:6px;align-items:center;font-size:13px;justify-self:end;cursor:pointer}
.ct-na{display:inline-block;font-size:11.5px;border-radius:6px;padding:1px 7px;background:var(--unk-soft);color:var(--muted);margin-left:6px}
.ct-add{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 4px}.ct-add input{flex:1;min-width:220px}
.ct-req{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 14px;padding:10px 0;border-top:1px solid var(--line);align-items:center}
.ct-req .ct-acts{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.ct-ex{font-size:12px;color:var(--muted);grid-column:1/3}
.ct-err{grid-column:1/3;font-size:12px;color:var(--bad)}
.ct-st{font-size:11.5px;border-radius:6px;padding:1px 7px;margin-left:6px;white-space:nowrap}
.ct-st.ready{background:var(--bad-soft);color:var(--bad)}.ct-st.candidate,.ct-st.off,.ct-st.rejected{background:var(--unk-soft);color:var(--muted)}
.ct-st.building,.ct-st.draft{background:var(--acc-soft);color:var(--acc)}.ct-st.live{background:var(--ok-soft,var(--acc-soft));color:var(--ok)}
.ct-spin{display:inline-block;width:10px;height:10px;border:2px solid var(--acc);border-right-color:transparent;border-radius:50%;animation:cts .8s linear infinite;vertical-align:-1px}
@keyframes cts{to{transform:rotate(360deg)}}
@media(max-width:700px){.ct-row{grid-template-columns:minmax(0,1fr) 120px}.ct-row .ct-w{grid-column:1/3;grid-row:2}.ct-sig{grid-column:1/3}
  .ct-req{grid-template-columns:1fr}.ct-req .ct-acts{justify-content:flex-start}}`;
  document.head.insertAdjacentHTML('beforeend', `<style>${css}</style>`);

  const nav = $('nav'), main = document.querySelector('main');
  nav.insertAdjacentHTML('beforeend', '<button data-t="city">Профиль города</button>');
  main.insertAdjacentHTML('beforeend', `<section class="tab" id="t-city">
  <div class="card"><h2 id="ct-title">Профиль города</h2>
    <div class="muted small">Что важно гостям именно здесь. Вес от 0 до 1 считается сам по данным региона: о чём говорят
      гости в отзывах и чем отели продают себя в описаниях (половина веса), насколько по характеристике различаются
      отели (30%) и сколько раз её уже искали (20%). Вес решает порядок отелей внутри корзины «подходит» и очередь
      вопросов отельерам. Ручной вес главнее авто; выключенная характеристика остаётся в поиске, если гость попросит
      её прямо, но не влияет на порядок и вопросы.</div>
    <div class="ct-meta" id="ct-meta"></div><div id="ct-chars">Считаю…</div></div>
  <div class="card" style="margin-top:16px"><h2>Чего не хватает: просят гости</h2>
    <div class="muted small" id="ct-reqnote">Условия из запросов, которых нет в реестре. Похожие формулировки склеиваются,
      каждый новый запрос с этими словами добавляет спрос.</div>
    <form class="ct-add" id="ct-add"><input id="ct-phrase" placeholder="Параметр для города, например: паркет в номере" maxlength="200">
      <button class="g" type="submit">Добавить</button><button class="b" type="button" id="ct-addb">Добавить и собрать</button></form>
    <div id="ct-reqs"></div></div></section>`);

  const _show = window.show;
  window.show = function (t) { _show(t); if (t == 'city') load(); };

  const STATE = {ready: 'пора добавлять', candidate: 'кандидат', building: 'собирается', draft: 'черновик ждёт одобрения',
    live: 'в поиске', rejected: 'отклонён', off: 'скрыт'};
  const f2 = x => dc((+x || 0).toFixed(2)), pct = x => Math.round((+x || 0) * 100) + '%';
  const err = e => { try { return JSON.parse(e.message).detail || e.message; } catch (_) { return e.message; } };
  let P = null, poll = null;

  async function load() {
    try { P = await api('/api/city'); } catch (e) { $('ct-chars').innerHTML = `<div class="bad">${esc(err(e))}</div>`; return; }
    $('ct-title').textContent = `Профиль города: что важно гостям ${P.label_in}`;
    $('ct-meta').innerHTML = `<span>${P.hotels} ${pl(P.hotels, 'отель', 'отеля', 'отелей')} · ${P.queries} ${pl(P.queries, 'запрос', 'запроса', 'запросов')} гостей в журнале${P.computed_at ? ' · пересчитано ' + esc(ruDate(P.computed_at)) + ' ' + esc(P.computed_at.slice(11, 16)) : ''}</span>
      <button class="g" id="ct-re">Пересчитать по данным</button>`;
    $('ct-re').onclick = async e => { e.target.disabled = true; e.target.textContent = 'Считаю…'; await api('/api/city/recompute', {}); load(); };
    $('ct-reqnote').innerHTML = `Условия из запросов, которых нет в реестре. Похожие формулировки склеиваются, каждый новый запрос с этими словами добавляет спрос.
      С <b>${P.threshold}</b> ${pl(P.threshold, 'запроса', 'запросов', 'запросов')} параметр помечается «пора добавлять». Собранная характеристика после одобрения попадает в профиль и в поиск этого города.`;
    renderChars(); renderReqs();
    clearTimeout(poll);
    if (P.requests.some(r => r.state == 'building')) poll = setTimeout(() => { if (document.body.dataset.tab == 'city' || $('t-city').classList.contains('on')) load(); }, 3000);
  }

  function renderChars() {
    $('ct-chars').innerHTML = P.chars.map(c => {
      const s = c.signals || {}, manual = c.manual_weight != null, off = c.status == 'off';
      const w = off ? 0 : c.weight || 0;
      return `<div class="ct-row ${off ? 'off' : ''}" data-id="${esc(c.id)}">
        <div><b>${esc(c.name)}</b>${s.reason == 'no_data' ? '<span class="ct-na" title="у характеристики нет посчитанных фактов в базе региона: посчитайте её (scripts/precompute.py) или удалите рабочую базу data/cache/facts.runtime.sqlite">нет фактов</span>' : s.reason == 'absent' ? '<span class="ct-na" title="признак не встречается ни у одного отеля региона, например моря нет">не встречается здесь</span>' : ''}${c.custom ? '<span class="ct-na">добавлена словами</span>' : ''}
          <div class="ct-desc">${esc(c.description)}</div></div>
        <div class="ct-w"><input type="range" min="0" max="100" step="5" value="${Math.round(w * 100)}" ${off ? 'disabled' : ''} aria-label="вес ${esc(c.name)}">
          <div class="ct-wv"><b>${f2(w)}</b> ${off ? 'выключена' : manual ? `вручную, авто ${f2(c.auto_weight)}<button data-reset>сбросить</button>` : 'авто'}</div></div>
        <label class="ct-on"><input type="checkbox" ${off ? '' : 'checked'}> учитывать</label>
        <div class="ct-sig"><span>в отзывах ${pct(s.review_share)}</span><span>в описаниях ${pct(s.card_share)} отелей</span>
          <span>различает отели ${f2(s.entropy)}${s.known_share < 1 ? `, известно у ${pct(s.known_share)}` : ''}</span><span>${s.demand || 0} ${pl(s.demand || 0, 'запрос', 'запроса', 'запросов')}</span></div></div>`;
    }).join('') || '<div class="muted">Характеристик нет.</div>';
  }

  $('ct-chars').addEventListener('input', e => {
    if (e.target.type != 'range') return;
    e.target.nextElementSibling.innerHTML = `<b>${f2(e.target.value / 100)}</b> вручную`;
  });
  $('ct-chars').addEventListener('change', async e => {
    const row = e.target.closest('.ct-row'); if (!row) return;
    const id = encodeURIComponent(row.dataset.id);
    if (e.target.type == 'range') await api(`/api/city/chars/${id}`, {weight: e.target.value / 100});
    if (e.target.type == 'checkbox') await api(`/api/city/chars/${id}`, {status: e.target.checked ? 'active' : 'off'});
    load();
  });
  $('ct-chars').addEventListener('click', async e => {
    if (!e.target.matches('[data-reset]')) return;
    await api(`/api/city/chars/${encodeURIComponent(e.target.closest('.ct-row').dataset.id)}`, {reset: true});
    load();
  });

  function acts(r) {
    const b = (a, label, cls = 'g') => `<button class="${cls}" data-a="${a}">${label}</button>`;
    if (r.state == 'building') return '<span class="small muted"><span class="ct-spin"></span> собирается, это до пары минут</span>';
    if (r.state == 'draft') return b('approve', 'Одобрить для поиска', 'b') + b('report', 'Отчёт черновика');
    if (r.state == 'live') return `<span class="small muted">в поиске как «${esc(r.char_name)}»</span>`;
    if (r.state == 'off') return b('on', 'Вернуть');
    return b('build', r.state == 'rejected' ? 'Собрать заново' : 'Собрать характеристику', r.state == 'ready' ? 'b' : 'g') + b('off', 'Не нужно');
  }

  function renderReqs() {
    $('ct-reqs').innerHTML = P.requests.map(r => `<div class="ct-req" data-id="${esc(r.id)}" data-char="${esc(r.char_id || '')}">
      <div><b>${esc(r.phrase)}</b><span class="ct-st ${r.state}">${STATE[r.state] || r.state}</span>
        <div class="small muted">${r.demand ? `${r.demand} ${pl(r.demand, 'запрос', 'запроса', 'запросов')}` : 'добавлен вручную'}${r.last_asked ? ' · последний ' + esc(ruDate(r.last_asked)) : ''}${r.proposal && r.proposal != r.phrase ? ' · что считать: ' + esc(r.proposal) : ''}</div></div>
      <div class="ct-acts">${acts(r)}</div>
      ${(r.examples || []).length ? `<div class="ct-ex">Запросы: ${r.examples.map(x => '«' + esc(x) + '»').join(', ')}</div>` : ''}
      ${r.note ? `<div class="ct-err">Сборка не удалась: ${esc(r.note)}</div>` : ''}</div>`).join('')
      || '<div class="muted" style="margin-top:8px">Пока все запросы гостей покрыты реестром.</div>';
  }

  $('ct-reqs').addEventListener('click', async e => {
    const a = e.target.dataset.a, row = e.target.closest('.ct-req'); if (!a || !row) return;
    const id = encodeURIComponent(row.dataset.id);
    e.target.disabled = true;
    try {
      if (a == 'build') await api(`/api/city/requests/${id}/build`, {});
      if (a == 'off' || a == 'on') await api(`/api/city/requests/${id}`, {status: a == 'off' ? 'off' : 'active'});
      if (a == 'approve') { await api(`/api/drafts/${encodeURIComponent(row.dataset.char)}/approve`, {}); await api('/api/city/recompute', {}); }
      if (a == 'report') { show('chars'); return; }
    } catch (x) { alert(err(x)); }
    load();
  });

  async function add(build) {
    const v = $('ct-phrase').value.trim(); if (!v) return;
    try { await api('/api/city/requests', {phrase: v, build}); $('ct-phrase').value = ''; } catch (x) { alert(err(x)); }
    load();
  }
  $('ct-add').onsubmit = e => { e.preventDefault(); add(false); };
  $('ct-addb').onclick = () => add(true);
})();
