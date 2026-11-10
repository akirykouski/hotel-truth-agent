/* Что, если ослабить условия: чипы с выгодой, убранные условия и фронтир компромиссов под выдачей поиска. */
(function () {
  const css = `
#relax{margin-top:12px}#relax:empty{display:none}
#relax h3{margin:0 0 6px}
#relax .rx{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0}
#relax .rx button{min-height:44px;display:flex;flex-direction:column;justify-content:center;align-items:flex-start;text-align:left;border:1px solid var(--line);
 background:var(--acc-soft);color:var(--acc);border-radius:12px;padding:6px 12px;font:inherit;cursor:pointer;max-width:100%}
#relax .rx button b{font-size:13px}#relax .rx button span{font-size:11.5px;color:var(--muted)}
#relax .rx button.off{background:var(--warn-soft);color:var(--warn);border-color:transparent;flex-direction:row;align-items:center;gap:8px}
#relax .rx button.off span{color:inherit}
#relax .fr{overflow-x:auto}#relax .fr table{min-width:420px}
#relax .fr td.n{font-weight:600}#relax .fr a{color:var(--ink);text-decoration:none;cursor:pointer}
#relax .tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:99px;background:var(--ok-soft);color:var(--ok);margin:2px 4px 0 0}
@media(max-width:600px){#relax .rx button{flex:1 1 100%}}`;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  const res = document.getElementById('results');
  const box = document.createElement('div'); box.id = 'relax'; box.className = 'card';
  res.parentNode.insertBefore(box, res.nextSibling);

  let base = null;            // {query, parsed} исходной выдачи: от него считаются все пересчёты
  let drop = [], loosen = {}; // что сейчас убрано и смягчено
  const e = s => esc(s);
  const orig = window.renderResults;

  function lastQuery() {
    try { return [...history].reverse().find(m => m.role == 'user').content } catch (_) { return '' }
  }

  window.renderResults = function (s) {
    if (!s.__relax) { base = { query: lastQuery(), parsed: s.parsed }; drop = []; loosen = {}; }
    orig(s);
    draw(s);
  };

  async function rerun() {
    box.style.opacity = .6;
    try {
      const s = await api('/api/relax', { query: base.query, parsed: base.parsed, drop, loosen, limit: 5 });
      s.__relax = true; window.renderResults(s);
    } finally { box.style.opacity = 1; }
  }

  function draw(s) {
    const rel = s.relaxations || [], off = s.dropped || [], lo = s.loosened || [], fr = s.pareto || [];
    if (!rel.length && !off.length && !lo.length) { box.innerHTML = ''; return; }
    const name = i => (rel.find(r => r.idxs.includes(i)) || {}).text;
    let h = '<h3>Что, если ослабить условия</h3>';
    if (off.length || lo.length) {
      h += '<div class="rx">' + off.map(d => `<button class="off" data-un="${d.idx}" title="вернуть условие">без «${e(d.label)}» <span>✕</span></button>`).join('') +
        lo.map(l => `<button class="off" data-unl="${l.idx}" title="вернуть порог">${e(l.label)} (было ${e(String(l.from).replace('.', ','))}) <span>✕</span></button>`).join('') + '</div>';
    }
    if (rel.length) {
      h += `<div class="muted small">Подходят ${s.counts.match}, возможно ${s.counts.maybe}. Нажмите, чтобы пересчитать без условия:</div><div class="rx">` +
        rel.filter(r => r.gain > 0).slice(0, 6).map((r, i) => {
          const lab = r.kind == 'loosen' ? r.chip : `без «${r.text.match(/«(.+)»:/)[1]}»`;
          return `<button data-rx="${i}" title="${e(r.text)}"><b>${e(lab)} +${r.gain}</b><span>лучший: ${e(r.best)}</span></button>`;
        }).join('') + '</div>';
    }
    if (fr.length > 1) {
      h += `<h3>Компромиссы</h3><div class="fr"><table><tr><th>Отель</th><th>Цена на 1 ноября</th><th>До пляжа</th><th>Ночью</th></tr>` +
        fr.map(f => `<tr><td class="n"><a data-h="${e(f.id)}">${e(f.name)}</a><div>${(f.tags || []).map(t => `<span class="tag">${e(t)}</span>`).join('')}${f.bucket == 'maybe' ? '<span class="badge bq">уточняем</span>' : ''}</div></td>
          <td>${Math.round(f.price_nov1)} ₽</td><td>${f.minutes == null ? 'нет данных' : f.minutes + ' мин'}</td><td>${f.db == null ? 'нет данных' : f.db + ' дБ'}</td></tr>`).join('') + '</table></div>';
    }
    box.innerHTML = h;
    const shown = rel.filter(r => r.gain > 0).slice(0, 6);
    box.onclick = ev => {
      const t = ev.target.closest('[data-rx],[data-un],[data-unl],[data-h]');
      if (!t) return;
      if (t.dataset.h) return openHotel(t.dataset.h);
      if (t.dataset.rx != null) {
        const r = shown[+t.dataset.rx];
        if (r.kind == 'loosen') loosen[r.idxs[0]] = r.to; else r.idxs.forEach(i => drop.includes(i) || drop.push(i));
      } else if (t.dataset.un != null) drop = drop.filter(i => i != t.dataset.un);
      else delete loosen[t.dataset.unl];
      rerun();
    };
  }
})();
