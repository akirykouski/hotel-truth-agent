// Значок сверки под ответом чата: «Все цифры сверены с расчётами» или «Не подтвердилось и убрано: N утверждений».
(function () {
  const css = document.createElement('style');
  css.textContent = `
.gnd{margin-top:8px;font-size:12px}
.gnd>summary{list-style:none;display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:99px;cursor:pointer;min-height:28px;max-width:100%;line-height:1.3}
.gnd>summary::-webkit-details-marker{display:none}
.gnd.ok>summary{background:var(--ok-soft);color:var(--ok)}
.gnd.fix>summary{background:var(--warn-soft);color:var(--warn)}
.gnd .gb{margin-top:6px;padding:8px 10px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);white-space:normal}
.gnd .gb ul{margin:4px 0 8px;padding-left:18px}.gnd .gb li{margin:2px 0;overflow-wrap:anywhere}
.gnd .gb .g-no{color:var(--bad)}.gnd .gb .g-yes{color:var(--ok)}.gnd .gb h4{margin:8px 0 2px;font-size:12px;color:var(--muted);font-weight:600}
`;
  document.head.appendChild(css);
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const pending = [];

  const origFetch = window.fetch;
  window.fetch = async function (url, opts) {
    const resp = await origFetch.apply(this, arguments);
    if (String(url).includes('/api/chat')) {
      pending.push(resp.clone().json().then(j => j.grounding || null).catch(() => null));
    }
    return resp;
  };

  function plural(n, a, b, c) {
    const m = n % 100, d = n % 10;
    return m > 10 && m < 20 ? c : d === 1 ? a : d > 1 && d < 5 ? b : c;
  }

  // источник подтверждения без служебных имён: «search_hotels#0: 12 мин пешком» -> «12 мин пешком», «search_hotels#0.walk_min» -> «расчёт»
  function evText(e) {
    const m = /^\w+#\d+(?:[:.]\s*)?(.*)$/.exec(e || '');
    if (!m) return e || '';
    return /\s/.test(m[1]) ? '«' + m[1].replace(/^[-*\s]+/, '') + '»' : 'расчёт';
  }

  function badge(g) {
    const removed = (g.removed || []).length;
    const bad = removed || g.before.unsupported;  // число берём из показанного списка
    const ok = bad === 0 && !(g.fetched || []).length;
    let label;
    if (g.error) return '';
    if (ok) label = 'Все цифры сверены с расчётами';
    else if (!bad) label = 'Цифры сверены, недостающее дополнено из расчётов';
    else label = `Не подтвердилось и ${removed ? 'убрано' : 'исправлено'}: ${bad} ${plural(bad, 'утверждение', 'утверждения', 'утверждений')}`;
    const checked = (g.after.claims || []).filter(c => c.supported);
    const rows = checked.slice(0, 40).map(c => `<li><span class="g-yes">✓</span> ${esc(c.text)} <span class="muted">· ${esc(evText(c.evidence))}</span></li>`).join('');
    const gone = (g.removed || []).map(t => `<li class="g-no">${esc(String(t).replace(/^[-*•\s]+/, ''))}</li>`).join('');
    const cov = (g.missing || []).length ? `<h4>Добрано по запросу гостя</h4><ul><li>${g.missing.map(esc).join(', ')}</li></ul>` : '';
    return `<details class="gnd ${ok ? 'ok' : 'fix'}"><summary>${ok ? '✓' : '⚠'} ${label}</summary><div class="gb">`
      + (gone ? `<h4>Убрано из ответа</h4><ul>${gone}</ul>` : '')
      + (g.repaired ? '<div class="muted">Ответ переписан один раз по сверенным данным.</div>' : '')
      + cov + `<h4>Подтверждено (${checked.length} из ${g.after.total})</h4><ul>${rows || '<li class="muted">числовых утверждений нет</li>'}</ul></div></details>`;
  }

  function attach(node) {
    if (!node.classList || !node.classList.contains('a') || node.dataset.gnd) return;
    if (!node.querySelector('.trace')) return;
    node.dataset.gnd = '1';
    const p = pending.shift();
    if (p) p.then(g => { if (g) node.insertAdjacentHTML('beforeend', badge(g)); });
  }

  const start = () => {
    const box = document.getElementById('msgs');
    if (!box) return;
    new MutationObserver(() => box.querySelectorAll('.m.a').forEach(attach)).observe(box, {childList: true, subtree: true});
  };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', start) : start();
})();
