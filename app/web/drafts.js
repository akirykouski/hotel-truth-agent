/* Черновики характеристик: авто-отчёт для админа, Одобрить / Отклонить, ход сборки.
   Подключается одной строкой в index.html, стили вставляет сам. Работает поверх глобалов index.html ($, esc, api, show). */
(function () {
  const css = `
#drafts{margin-bottom:16px}
.dr-head{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:4px}
.dr-card{border:1px solid var(--line);border-radius:12px;padding:12px;margin-top:10px;background:var(--card)}
.dr-card.approved{border-color:var(--ok);background:var(--ok-soft)}.dr-card.rejected{border-color:var(--bad);background:var(--bad-soft);opacity:.85}
.dr-title{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.dr-title b{font-size:15px}
.dr-warn{background:var(--warn-soft);color:var(--warn);border-radius:8px;padding:8px 10px;margin:8px 0;font-size:13px}
.dr-ok{background:var(--ok-soft);color:var(--ok);border-radius:8px;padding:8px 10px;margin:8px 0;font-size:13px}
.dr-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:8px 0}
.dr-box{border:1px solid var(--line);border-radius:10px;padding:9px 10px;font-size:13px}
.dr-box h4{margin:0 0 6px;font-size:12px;color:var(--muted);font-weight:500}
.dr-bar{display:flex;height:10px;border-radius:5px;overflow:hidden;background:var(--line);margin:4px 0}
.dr-bar i{display:block;height:10px}.dr-k{background:var(--ok)}.dr-u{background:var(--unk)}.dr-c{background:var(--bad)}.dr-y{background:var(--acc)}.dr-n{background:var(--warn)}
.dr-s{display:grid;grid-template-columns:1fr;gap:6px;margin:6px 0;padding:0;list-style:none}
.dr-s li{border:1px solid var(--line);border-radius:8px;padding:7px 9px;font-size:13px}
.dr-act{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;align-items:center}
.dr-act button{min-height:40px;padding:8px 16px}.dr-act input{flex:1;min-width:140px;min-height:40px}
button.dr-no{background:none;border:1px solid var(--bad);color:var(--bad);border-radius:8px;cursor:pointer;font-weight:600}
button.dr-yes{background:var(--ok);color:#fff;border:0;border-radius:8px;cursor:pointer;font-weight:600}
button[disabled]{opacity:.5;cursor:default}
.dr-state{font-weight:600;margin-top:10px}
.dr-job{border:1px dashed var(--acc);border-radius:10px;padding:8px 10px;margin-top:10px;font-size:13px;background:var(--acc-soft)}
.dr-job ol{margin:6px 0 0;padding-left:0;list-style:none;font-size:12.5px}.dr-job li{margin:2px 0}.dr-job .t{color:var(--muted);display:inline-block;min-width:44px}
.dr-spin{display:inline-block;width:10px;height:10px;border:2px solid var(--acc);border-right-color:transparent;border-radius:50%;animation:drs 1s linear infinite;vertical-align:-1px;margin-right:6px}
@keyframes drs{to{transform:rotate(360deg)}}
.dr-ev{font-size:11.5px;color:var(--muted);word-break:break-word}
@media(max-width:600px){.dr-card{padding:10px}.dr-act button{flex:1}.dr-act input{flex:1 1 100%;order:3}}`;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  /* id сессии: черновик, который собрал этот посетитель, виден только ему, пока админ не одобрит */
  let sid = null;
  try { sid = localStorage.getItem('osess'); if (!sid) { sid = 's' + Math.random().toString(36).slice(2, 12); localStorage.setItem('osess', sid); } }
  catch (e) { sid = 's' + Math.random().toString(36).slice(2, 12); }
  const f0 = window.fetch.bind(window);
  window.fetch = (u, o) => {
    if (typeof u === 'string' && u.startsWith('/api/')) { o = Object.assign({}, o); o.headers = Object.assign({}, o.headers, { 'X-Session': sid }); }
    return f0(u, o);
  };

  const E = s => (window.esc ? window.esc(s) : String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])));
  const pct = (a, b) => b ? Math.round(a / b * 100) : 0;
  const clock = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  const pl = (n, a, b, c) => { const m = n % 100, k = n % 10; return `${n} ${m > 10 && m < 15 ? c : k === 1 ? a : k >= 2 && k <= 4 ? b : c}`; };
  const dec = x => String(x).replace('.', ',');
  const SRC = { 'OpenStreetMap': '🗺', 'карточка Островка': '📋', 'отзывы гостей': '💬' };

  function evalHtml(e) {
    if (!e) return '<div class="muted small">Отчёт собирается.</div>';
    const c = e.coverage, d = e.distribution, g = e.signal, r = e.recipe;
    const warn = e.warnings.length
      ? e.warnings.map(w => `<div class="dr-warn">⚠ ${E(w)}</div>`).join('')
      : '<div class="dr-ok">Проверки пройдены: покрытие и разброс значений выглядят нормально.</div>';
    const note = e.degenerate && e.degenerate.note ? `<div class="small muted">${E(e.degenerate.note)}</div>` : '';
    const cov = `<div class="dr-box"><h4>Покрытие: ${pl(c.total, 'отель', 'отеля', 'отелей')}</h4>
      <div class="dr-bar"><i class="dr-k" style="width:${pct(c.known, c.total)}%"></i><i class="dr-c" style="width:${pct(c.conflict, c.total)}%"></i><i class="dr-u" style="width:${pct(c.unknown + c.stale, c.total)}%"></i></div>
      известно ${c.known}, спорно ${c.conflict}, нет данных ${c.unknown}${c.stale ? `, устарело ${c.stale}` : ''}</div>`;
    let dist;
    if (d.kind === 'bool') dist = `<div class="dr-bar"><i class="dr-y" style="width:${pct(d.true, d.n)}%"></i><i class="dr-n" style="width:${pct(d.false, d.n)}%"></i></div>«да» ${d.true}, «нет» ${d.false} из ${d.n} известных`;
    else if (d.kind === 'number') dist = `от ${dec(d.min)} до ${dec(d.max)}, медиана ${dec(d.median)} (${pl(d.n, 'отель', 'отеля', 'отелей')})`;
    else if (d.kind === 'enum') dist = Object.entries(d.counts).map(([k, v]) => `${E(k)}: ${v}`).join(', ');
    else dist = 'значений нет';
    const dbox = `<div class="dr-box"><h4>Разброс главного поля «${E(e.key)}»</h4>${dist}<div class="muted small">разнообразие значений ${dec(d.entropy)} из 1${e.degenerate.flag ? ' · <b class="bad">подозрительно однородно</b>' : ''}</div></div>`;
    let sbox;
    if (g.available) sbox = `<div class="dr-box"><h4>Независимый сигнал: слова «${E(g.terms.join('», «'))}» в ${g.via.map(v => v === 'card' ? 'карточке' : 'отзывах').join(' и ')}</h4>
      слова нашлись у ${pl(g.signal_hits, 'отеля', 'отелей', 'отелей')}, расчёт подтвердил ${g.of_signal_with_true == null ? 'н/д' : Math.round(g.of_signal_with_true * 100)}%.<br>
      Из ${pl(g.computed_true, 'отеля', 'отелей', 'отелей')} с «да» слова есть у ${g.both} (${g.of_true_with_signal == null ? 'н/д' : Math.round(g.of_true_with_signal * 100)}%).</div>`;
    else sbox = `<div class="dr-box"><h4>Независимый сигнал</h4><span class="muted">${E(g.note)}</span></div>`;
    const rbox = `<div class="dr-box"><h4>Рецепт</h4>способ: ${r.mode === 'llm' ? 'собрано нейросетью' : 'готовый шаблон'} · источники: ${E(r.sources.map(x => ({ card: 'карточка', reviews: 'отзывы', osm: 'карта OSM', geo: 'расчёт по карте' }[x] || x)).join(', '))}<br>попыток: ${r.attempts} · сборка ${dec(r.wall_s)} с</div>`;
    const samples = e.samples.map(s => `<li><b>${E(s.hotel)}</b>
      <span class="badge ${s.value === true ? 'bm' : s.value === false ? 'bq' : 'bu'}">${s.value === true ? 'да' : s.value === false ? 'нет' : s.value == null ? 'нет данных' : E(s.value)}</span>
      <div>${E(s.summary)}</div>${s.source ? `<div class="muted small">${SRC[s.source] || ''} ${E(s.source)}${s.status !== 'unknown' ? ' · уверенность ' + dec(s.confidence) : ''}</div>` : ''}
      ${s.evidence ? `<details><summary>доказательство</summary><div class="dr-ev">${E(s.evidence)}</div></details>` : ''}</li>`).join('');
    return `${warn}${note}<div class="dr-grid">${cov}${dbox}${sbox}${rbox}</div>
      <h3>Пять примеров</h3><ul class="dr-s">${samples}</ul>`;
  }

  function cardHtml(d) {
    const v = d.eval ? d.eval.verdict : 'без отчёта';
    const open = d.status === 'draft';
    const badge = d.status === 'approved' ? '<span class="badge bm">одобрено</span>' : d.status === 'rejected' ? '<span class="badge bf">отклонено</span>'
      : `<span class="badge ${v === 'можно одобрять' ? 'bm' : 'bq'}">${d.eval ? E(v) : 'считается'}</span>`;
    return `<div class="dr-card ${d.status}" id="dr-${E(d.id)}">
      <div class="dr-title"><b>${E(d.name)}</b>${badge}<span class="muted small">${E(d.id)} · ${E((d.drafted_at || '').slice(0, 16).replace('T', ' '))}</span></div>
      <div class="small">${E(d.description)}</div>
      <details ${open && d.eval ? 'open' : ''}><summary>Отчёт проверки</summary>${evalHtml(d.eval)}</details>
      ${open && !d.eval ? '<div class="dr-state muted"><span class="dr-spin"></span>Отчёт ещё собирается, решение появится следом.</div>' : open ? `<div class="dr-act"><button class="dr-yes" onclick="draftDecide('${E(d.id)}','approve')">Одобрить</button>
        <input id="drr-${E(d.id)}" placeholder="причина отказа (по желанию)"><button class="dr-no" onclick="draftDecide('${E(d.id)}','reject')">Отклонить</button></div>`
        : `<div class="dr-state ${d.status === 'approved' ? 'ok' : 'bad'}">${d.status === 'approved' ? `Одобрено (${E(d.approved_by || 'админ')}): характеристику понимает публичный поиск.` : `Отклонено${d.rejected_reason ? ': ' + E(d.rejected_reason) : ''}. В поиске её никто не увидит.`}</div>`}
    </div>`;
  }

  window.draftDecide = async function (id, what) {
    const box = document.getElementById('dr-' + id);
    box.querySelectorAll('button').forEach(b => b.disabled = true);
    const reason = (document.getElementById('drr-' + id) || {}).value || '';
    try {
      const r = await fetch(`/api/drafts/${encodeURIComponent(id)}/${what}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason }) });
      if (!r.ok) { let t = await r.text(); try { t = JSON.parse(t).detail || t } catch (_) { } throw new Error(t) }
      const d = await r.json();
      const old = box.querySelector('details');
      const wasOpen = old && old.open;
      box.outerHTML = cardHtml(d);
      const nb = document.getElementById('dr-' + id);
      nb.querySelector('details').open = !!wasOpen;
      if (typeof window.loadChars === 'function') loadCharsOnly();
    } catch (e) {
      box.querySelectorAll('button').forEach(b => b.disabled = false);
      alert('Не получилось: ' + e.message);
    }
  };

  let timer = null;
  function jobsHtml(jobs) {
    return jobs.map(j => `<div class="dr-job"><div>${j.status === 'running' ? '<span class="dr-spin"></span>' : j.status === 'done' ? '✔ ' : '✖ '}<b>${E(j.text)}</b>
      <span class="muted">· ${clock(j.elapsed_s)} · ${j.status === 'running' ? 'идёт сборка' : j.status === 'done' ? 'готово' : 'не получилось'}</span></div>
      <ol>${j.steps.map(s => `<li><span class="t">${clock(s.t)}</span>${E(s.msg)}</li>`).join('')}</ol></div>`).join('');
  }

  async function loadDrafts() {
    const host = document.getElementById('drafts');
    if (!host) return;
    const [dr, jb] = await Promise.all([fetch('/api/drafts?status=all').then(r => r.json()), fetch('/api/drafts/jobs').then(r => r.json())]);
    const open = dr.drafts.filter(d => d.status === 'draft'), done = dr.drafts.filter(d => d.status !== 'draft');
    const live = jb.jobs.filter(j => j.status === 'running');
    const keepOpen = new Set([...host.querySelectorAll('details[open]')].map(x => x.closest('.dr-card')?.id));
    host.innerHTML = `<div class="card"><div class="dr-head"><h2 style="margin:0">Черновики</h2><span class="muted small">Характеристики, собранные агентом, не попадают в поиск, пока админ не одобрит. ${open.length ? `Ждут решения: ${open.length}.` : 'Ждущих решения нет.'}</span></div>
      <div id="drjobs">${jobsHtml(live)}</div>
      ${open.map(cardHtml).join('') || '<div class="muted small" style="margin-top:8px">Пока пусто. Соберите характеристику словами слева, она появится здесь с отчётом.</div>'}
      ${done.length ? `<details style="margin-top:10px"><summary>Решённые (${done.length})</summary>${done.map(cardHtml).join('')}</details>` : ''}</div>`;
    host.querySelectorAll('.dr-card').forEach(c => { const dt = c.querySelector('details'); if (dt && keepOpen.has(c.id)) dt.open = true; });
    clearTimeout(timer);
    if (live.length) timer = setTimeout(loadDrafts, 2000);
  }
  window.loadDrafts = loadDrafts;

  function mount() {
    const tab = document.getElementById('t-chars');
    if (!tab || document.getElementById('drafts')) return;
    const host = document.createElement('div'); host.id = 'drafts'; tab.insertBefore(host, tab.firstChild);
    const orig = window.loadChars;
    window.loadCharsOnly = orig;
    window.loadChars = async function () { await orig.apply(this, arguments); loadDrafts(); };
    /* сборка идёт в фоне, ход виден шагами: шаблонная секунды, LLM минуты */
    window.addChar = async function () {
      const t = document.getElementById('newc').value.trim(); if (!t) return;
      const out = document.getElementById('newres');
      out.innerHTML = '<div class="dr-job"><span class="dr-spin"></span>Запускаю сборку…</div>';
      let job;
      try {
        const r = await fetch('/api/drafts/build', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ description: t }) });
        if (!r.ok) throw new Error(await r.text());
        job = (await r.json()).job;
      } catch (e) { out.innerHTML = `<div class="bad">Ошибка: ${E(e.message)}</div>`; return; }
      loadDrafts();
      for (;;) {
        const j = await fetch('/api/drafts/jobs/' + job).then(r => r.json());
        out.innerHTML = jobsHtml([j]);
        if (j.status === 'running') { await new Promise(r => setTimeout(r, 1500)); continue; }
        if (j.status === 'failed') { out.innerHTML += `<div class="bad" style="margin-top:6px">${E(j.steps.length ? j.steps[j.steps.length - 1].msg : 'не получилось')}</div>`; break; }
        const d = j.result;
        out.innerHTML += `<div class="small" style="margin-top:8px">Черновик <b>${E(d.name)}</b> готов. Вы уже видите его в поиске, остальным он станет доступен после одобрения админом (раздел «Черновики» выше).</div>`;
        break;
      }
      loadDrafts(); loadCharsOnly();
    };
    loadDrafts();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
})();
