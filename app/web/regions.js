/* Регионы: список собранных, новый регион рамкой на карте, ход сборки по этапам, переключение.
   Подключается одной строкой в index.html, стили вставляет сам. Работает поверх глобалов index.html ($, esc, api, show, pl, dc). */
(function () {
  const css = `
.rg-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
.rg-reg{border:1px solid var(--line);border-radius:12px;padding:11px 12px;display:flex;flex-direction:column;gap:4px}
.rg-reg.on{border-color:var(--acc);background:var(--acc-soft)}.rg-reg b{font-size:15px}
.rg-reg .rg-act{margin-top:auto;padding-top:6px}
.rg-new{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:16px;margin-top:12px}
@media(max-width:900px){.rg-new{grid-template-columns:1fr}}
#rg-map{height:440px;border-radius:12px;border:1px solid var(--line)}
.rg-form label{display:block;font-size:12px;color:var(--muted);margin:10px 0 3px}
.rg-form input,.rg-form select{width:100%}
.rg-two{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.rg-check{border-radius:10px;padding:9px 11px;margin-top:10px;font-size:13px;background:var(--unk-soft)}
.rg-check.err{background:var(--bad-soft);color:var(--bad)}.rg-check .w{color:var(--warn)}
.rg-check b{font-size:18px}
.rg-hint{font-size:12px;color:var(--muted);margin-top:6px}
.rg-job{border:1px solid var(--acc);border-radius:12px;padding:12px 14px;margin-top:12px}
.rg-job.done{border-color:var(--ok)}.rg-job.failed,.rg-job.interrupted{border-color:var(--bad)}.rg-job.cancelled{border-color:var(--line)}
.rg-head{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.rg-head b{font-size:15px}
.rg-bar{height:8px;border-radius:4px;background:var(--line);overflow:hidden;margin:8px 0 4px}
.rg-bar i{display:block;height:8px;background:var(--acc);transition:width .4s}
.rg-job.done .rg-bar i{background:var(--ok)}.rg-job.failed .rg-bar i,.rg-job.interrupted .rg-bar i{background:var(--bad)}
.rg-steps{list-style:none;margin:8px 0 0;padding:0}
.rg-steps li{display:grid;grid-template-columns:22px minmax(0,1fr) auto;gap:2px 8px;padding:7px 0;border-top:1px solid var(--line);font-size:13px}
.rg-ic{font-weight:700;text-align:center}.rg-steps .running .rg-ic{color:var(--acc)}.rg-steps .ok .rg-ic{color:var(--ok)}
.rg-steps .fail .rg-ic{color:var(--bad)}.rg-steps .pending,.rg-steps .skipped,.rg-steps .cancelled{color:var(--muted)}
.rg-note{grid-column:2/4;font-size:12px;color:var(--muted);overflow-wrap:anywhere}.rg-steps .fail .rg-note{color:var(--bad)}
.rg-sub{grid-column:2/4;height:4px;border-radius:2px;background:var(--line);overflow:hidden}.rg-sub i{display:block;height:4px;background:var(--acc)}
.rg-steps details{grid-column:2/4}.rg-t{font-variant-numeric:tabular-nums;color:var(--muted);font-size:12px}
.rg-spin{display:inline-block;width:11px;height:11px;border:2px solid var(--acc);border-right-color:transparent;border-radius:50%;animation:rgs 0.8s linear infinite;vertical-align:-1px}
@keyframes rgs{to{transform:rotate(360deg)}}
.rg-res{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-top:10px}
.rg-res div{border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:12px;color:var(--muted)}.rg-res b{display:block;font-size:18px;color:var(--ink)}
.rg-err{background:var(--bad-soft);color:var(--bad);border-radius:8px;padding:8px 10px;margin-top:8px;font-size:13px}
.rg-hist{font-size:12.5px;margin-top:10px}.rg-hist div{padding:4px 0;border-top:1px solid var(--line);cursor:pointer}
#rg-badge{cursor:pointer}
.rg-over{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:3000;display:flex;align-items:center;justify-content:center}
.rg-over div{background:var(--card);border-radius:12px;padding:18px 22px;max-width:360px;font-size:14px}
button.b[disabled]{opacity:.5;cursor:default}
@media(max-width:600px){#rg-map{height:300px}.rg-steps li{grid-template-columns:20px minmax(0,1fr) auto}}`;
  document.head.insertAdjacentHTML('beforeend', `<style>${css}</style>`);

  const nav = $('nav'), main = document.querySelector('main');
  nav.insertAdjacentHTML('beforeend', '<button data-t="regions">Регионы</button>');
  main.insertAdjacentHTML('beforeend', `<section class="tab" id="t-regions">
  <div class="card"><h2>Регионы</h2><div class="muted small">Каждый регион: свои отели, вырезка OSM, карта высот, климат и база фактов.
    Сервер работает с одним регионом; переключение перезапускает его с другими данными, около секунды.</div>
    <div class="rg-list" id="rg-list" style="margin-top:10px"></div><div id="rg-job"></div><div id="rg-hist" class="rg-hist"></div></div>
  <div class="card" style="margin-top:16px"><h2>Новый регион</h2>
    <div class="muted small">Выберите город из скрапа Островка и обведите на карте плотное ядро отелей: два клика по углам рамки.
      Дальше всё делает тот же конвейер, что и <code>scripts/add_region.py</code>: отели, OSM, рельеф, климат, предрасчёт, проверка.</div>
    <div class="rg-new"><div><div id="rg-map"></div>
      <div class="row" style="margin-top:8px"><button class="g" id="rg-draw">Нарисовать рамку заново</button>
        <span class="small muted" id="rg-mode"></span></div></div>
      <div class="rg-form">
        <label for="rg-src">Город из скрапа</label><select id="rg-src"></select><div class="rg-hint" id="rg-srcnote"></div>
        <label for="rg-bbox">Рамка: юг, запад, север, восток</label><input id="rg-bbox" placeholder="43.50,39.85,43.53,39.89" inputmode="decimal">
        <div id="rg-check"></div>
        <label for="rg-label">Название в интерфейсе</label><input id="rg-label" placeholder="Хоста">
        <div class="rg-two"><div><label for="rg-in">«где»</label><input id="rg-in" placeholder="в Хосте"></div>
          <div><label for="rg-of">«чего»</label><input id="rg-of" placeholder="Хосты"></div></div>
        <label for="rg-name">Имя папки (латиница)</label><input id="rg-name" placeholder="hosta" autocapitalize="off" spellcheck="false">
        <div id="rg-exists" class="rg-hint"></div>
        <div style="margin-top:12px"><button class="b" id="rg-go" disabled>Собрать регион</button></div>
        <div id="rg-goerr"></div></div></div></div></section>`);

  const _show = window.show;
  window.show = function (t) { _show(t); if (t == 'regions') open(); };

  let R = {regions: [], sources: [], running: null}, mp, ptsLayer, regLayer, rect, corner, preview, bbox = null,
    plan = null, curJob = null, polling = null, fetchedAt = 0, nameTouched = false, checkSeq = 0;
  const fmtT = s => { s = Math.max(0, Math.round(s)); return s < 60 ? s + ' с' : Math.floor(s / 60) + ' мин ' + String(s % 60).padStart(2, '0') + ' с'; };
  const err = e => { try { return JSON.parse(e.message).detail || e.message; } catch (_) { return e.message; } };
  const STATE = {running: ['идёт сборка', 'bu'], done: ['готово', 'bm'], failed: ['ошибка', 'bf'], interrupted: ['прервано', 'bf'], cancelled: ['отменено', 'bn']};
  const ICON = {pending: '○', ok: '✓', fail: '✕', skipped: '✓', cancelled: '–'};
  const TR = {а:'a',б:'b',в:'v',г:'g',д:'d',е:'e',ё:'e',ж:'zh',з:'z',и:'i',й:'y',к:'k',л:'l',м:'m',н:'n',о:'o',п:'p',р:'r',с:'s',т:'t',у:'u',ф:'f',х:'kh',ц:'ts',ч:'ch',ш:'sh',щ:'sch',ъ:'',ы:'y',ь:'',э:'e',ю:'yu',я:'ya'};
  const slug = s => s.toLowerCase().split('').map(c => TR[c] ?? c).join('').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 30);

  async function open() {
    await load();
    setTimeout(initMap, 30);
  }

  async function load() {
    try { R = await api('/api/regions'); } catch (e) { $('rg-list').innerHTML = `<div class="bad">${esc(err(e))}</div>`; return; }
    renderList();
    const src = $('rg-src'), was = src.value;
    src.innerHTML = R.sources.map(s => `<option value="${esc(s.id)}" ${s.ready ? '' : 'disabled'}>${esc(s.label)}${s.hotels ? ' · ' + s.hotels + ' объектов' : ' · не скачан'}</option>`).join('')
      || '<option value="">нет источников</option>';
    if (was) src.value = was;
    $('rg-srcnote').textContent = R.sources.length ? (R.sources.find(s => !s.ready)?.note || '') : 'Нет файлов отелей в data/sources/<город>/ (или в папке из HOTELS_SRC_DIR).';
    const jobs = (await api('/api/regions/jobs')).jobs;
    const j = R.running || (curJob && jobs.find(x => x.id == curJob.id)) || jobs[0];
    if (j) curJob = j;
    renderHist(jobs);
    if (j) { fetchedAt = Date.now() / 1000; renderJob(j); if (j.state == 'running') poll(); }
    nameCheck();
  }

  function renderList() {
    const building = R.running && R.running.name;
    $('rg-list').innerHTML = R.regions.map(r => `<div class="rg-reg ${r.active ? 'on' : ''}"><div><b>${esc(r.label || r.name)}</b> ${r.active ? '<span class="badge bm">активный</span>' : ''}${r.complete ? '' : r.name == building ? '<span class="badge bu">собирается</span>' : '<span class="badge bf">не собран</span>'}</div>
      <div class="small">${r.hotels ?? '?'} ${pl(r.hotels || 0, 'отель', 'отеля', 'отелей')}${r.built_at ? ' · собран ' + esc(ruDate(r.built_at)) : ''}</div>
      <div class="small muted">${[r.build_seconds ? 'сборка ' + fmtT(r.build_seconds) : r.name == 'default' ? 'демо-зона из репозитория' : '', r.size_mb ? dc(r.size_mb) + ' МБ' : '', `<code>${esc(r.name)}</code>`].filter(Boolean).join(' · ')}</div>
      <div class="rg-act">${r.active ? '<span class="small muted">сейчас открыт</span>' : r.complete ? `<button class="g" data-sw="${esc(r.name)}">Переключиться</button>` : ''}</div></div>`).join('');
  }

  function renderHist(jobs) {
    const old = jobs.filter(j => !curJob || j.id != curJob.id).slice(0, 5);
    $('rg-hist').innerHTML = old.length ? '<div class="muted" style="border:0">Прошлые сборки</div>' + old.map(j => {
      const [l, c] = STATE[j.state] || [j.state, 'bu'];
      return `<div data-job="${esc(j.id)}"><span class="badge ${c}">${l}</span>${esc(j.label || j.name)} · ${esc(new Date(j.started_at * 1000).toLocaleString('ru-RU', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}))}${j.finished_at ? ' · ' + fmtT(j.finished_at - j.started_at) : ''}</div>`;
    }).join('') : '';
  }

  // ---------- ход сборки ----------
  function elapsed(j, from) { return (j.finished_at || (j.now + Date.now() / 1000 - fetchedAt)) - (from ?? j.started_at); }

  function renderJob(j) {
    const [l, c] = STATE[j.state] || [j.state, 'bu'], pct = Math.round((j.state == 'done' ? 1 : j.progress) * 100);
    const parallel = j.steps.filter(s => s.state == 'running').length;
    const steps = j.steps.map(s => {
      const ic = s.state == 'running' ? '<span class="rg-spin"></span>' : ICON[s.state] || '?';
      const t = s.state == 'running' && s.started_at ? fmtT(elapsed({...j, finished_at: null}, s.started_at)) : s.seconds != null && s.state != 'skipped' ? fmtT(s.seconds) : '';
      const cnt = s.total && s.state == 'running' ? `${s.done || 0}/${s.total} · ` : '';
      const sub = s.total && s.state == 'running' ? `<div class="rg-sub"><i style="width:${Math.round(100 * (s.done || 0) / s.total)}%"></i></div>` : '';
      const note = s.note || (s.state == 'skipped' ? 'пропущено' : '');
      return `<li class="${s.state}"><span class="rg-ic">${ic}</span><span>${esc(s.title)}</span><span class="rg-t">${cnt}${t}</span>${sub}
        ${note ? `<span class="rg-note">${esc(note)}</span>` : ''}${s.log && s.log.length ? `<details><summary>вывод этапа</summary><pre>${esc(s.log.join('\n'))}</pre></details>` : ''}</li>`;
    }).join('');
    const r = j.result, p = j.plan;
    const res = r ? `<div class="rg-res"><div><b>${r.hotels}</b>отелей</div><div><b>${r.facts}</b>фактов с источником</div><div><b>${r.characteristics}</b>характеристик</div>
      <div><b>${r.open_questions}</b>вопросов отельерам</div><div><b>${dc(r.size_mb)} МБ</b>на диске</div><div><b>${fmtT(r.seconds)}</b>вся сборка</div></div>` : '';
    const acts = [];
    if (j.state == 'running') acts.push(`<button class="g" data-cancel="${esc(j.id)}">Отменить</button>`);
    if (j.state == 'done' && !R.regions.find(x => x.name == j.name)?.active) acts.push(`<button class="b" data-sw="${esc(j.name)}">Переключиться на «${esc(j.label)}»</button>`);
    if (['failed', 'interrupted', 'cancelled'].includes(j.state)) acts.push(`<button class="b" data-retry="${esc(j.id)}">Повторить, взяв уже скачанное</button>`);
    acts.push(`<button class="g" data-log="${esc(j.id)}">Полный журнал</button>`);
    $('rg-job').innerHTML = `<div class="rg-job ${j.state}"><div class="rg-head"><b>Сборка «${esc(j.label || j.name)}»</b><span class="badge ${c}">${l}</span>
      <span class="rg-t" id="rg-el">${fmtT(elapsed(j))}</span>${p ? `<span class="small muted">${p.hotels} отелей · ${dc(p.area_km2)} км²${j.reuse ? ' · с уже скачанным' : ''}</span>` : ''}</div>
      <div class="rg-bar"><i style="width:${pct}%"></i></div><div class="small muted">${pct}%${parallel > 1 ? ` · ${parallel} ${pl(parallel, 'этап идёт', 'этапа идут', 'этапов идут')} параллельно` : ''}${j.state == 'running' && j.steps.find(s => s.id == 'osm' && s.state == 'running') ? ' · OSM обычно 2–25 мин, зависит от загрузки Overpass' : ''}</div>
      ${j.error ? `<div class="rg-err">${esc(j.error)}</div>` : ''}${res}<ul class="rg-steps">${steps}</ul>
      <div class="row" style="margin-top:10px">${acts.join('')}</div><div id="rg-log"></div></div>`;
    badge(j);
  }

  function poll() {
    clearTimeout(polling);
    polling = setTimeout(async () => {
      if (!curJob) return;
      try { curJob = await api('/api/regions/jobs/' + encodeURIComponent(curJob.id)); fetchedAt = Date.now() / 1000; } catch (_) { poll(); return; }
      const opened = [...document.querySelectorAll('#rg-job details')].map(d => d.open), logOpen = $('rg-log')?.innerHTML;
      if ($('t-regions').classList.contains('on')) {
        renderJob(curJob);
        document.querySelectorAll('#rg-job details').forEach((d, i) => { d.open = !!opened[i]; });
        if (logOpen) $('rg-log').innerHTML = logOpen;
      } else badge(curJob);
      if (curJob.state == 'running') poll(); else load();
    }, 1500);
  }
  setInterval(() => { const e = $('rg-el'); if (e && curJob && curJob.state == 'running') e.textContent = fmtT(elapsed(curJob)); }, 1000);

  function badge(j) {
    let b = $('rg-badge');
    if (!b) { $('status').insertAdjacentHTML('afterend', '<span class="badge bu" id="rg-badge" title="Открыть вкладку «Регионы»"></span>'); b = $('rg-badge'); b.onclick = () => show('regions'); }
    b.style.display = j.state == 'running' ? '' : 'none';
    b.textContent = `сборка «${j.label || j.name}»: ${Math.round(j.progress * 100)}%`;
  }

  // ---------- карта и рамка ----------
  function initMap() {
    if (mp) { mp.invalidateSize(); return; }
    mp = L.map('rg-map', {preferCanvas: true}).setView(status.center || [43.59, 39.73], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '© OpenStreetMap'}).addTo(mp);
    ptsLayer = L.layerGroup().addTo(mp); regLayer = L.layerGroup().addTo(mp);
    mp.on('click', e => {
      if (!corner) { corner = e.latlng; setMode(); return; }
      const a = corner; corner = null; if (preview) { preview.remove(); preview = null; }
      setBbox([Math.min(a.lat, e.latlng.lat), Math.min(a.lng, e.latlng.lng), Math.max(a.lat, e.latlng.lat), Math.max(a.lng, e.latlng.lng)]);
    });
    mp.on('mousemove', e => {
      if (!corner) return;
      const b = [[corner.lat, corner.lng], [e.latlng.lat, e.latlng.lng]];
      if (preview) preview.setBounds(b); else preview = L.rectangle(b, {color: '#0b63f6', weight: 1, dashArray: '4', fill: false, interactive: false}).addTo(mp);
    });
    drawRegions(); loadPoints(); setMode();
  }

  function setMode() { $('rg-mode').textContent = corner ? 'Теперь второй угол рамки' : bbox ? 'Клик по карте начнёт новую рамку' : 'Кликните первый угол рамки'; }

  function drawRegions() {
    regLayer.clearLayers();
    R.regions.filter(r => r.bbox).forEach(r => L.rectangle([[r.bbox[0], r.bbox[1]], [r.bbox[2], r.bbox[3]]], {color: '#667085', weight: 1, dashArray: '3', fillOpacity: .05, interactive: false})
      .bindTooltip(r.label || r.name, {permanent: true, direction: 'center', className: 'small'}).addTo(regLayer));
  }

  async function loadPoints() {
    const src = $('rg-src').value; ptsLayer.clearLayers(); if (!src) return;
    let d; try { d = await api('/api/regions/sources/' + encodeURIComponent(src) + '/points'); } catch (e) { $('rg-srcnote').textContent = err(e); return; }
    d.points.forEach(([la, lo, ok]) => L.circleMarker([la, lo], {radius: ok ? 2.5 : 1.5, weight: 0, fillOpacity: ok ? .75 : .35, fillColor: ok ? '#0b63f6' : '#98a2b3', interactive: false}).addTo(ptsLayer));
    const hs = d.points.filter(p => p[2]);
    if (hs.length && !bbox) mp.fitBounds(hs.map(p => [p[0], p[1]]), {padding: [20, 20], maxZoom: 13});
    $('rg-srcnote').textContent = `${hs.length} отелей на карте (синие), серые: квартиры, их не берём`;
    if (bbox) runCheck();
  }

  function setBbox(b, fromInput) {
    bbox = b.map(x => Math.round(x * 1e4) / 1e4);
    if (!fromInput) $('rg-bbox').value = bbox.join(',');
    if (rect) rect.remove();
    rect = L.rectangle([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], {color: '#0b63f6', weight: 2, fillOpacity: .08, interactive: false}).addTo(mp);
    if (fromInput) mp.fitBounds(rect.getBounds(), {padding: [30, 30]});
    setMode(); runCheck();
  }

  async function runCheck() {
    const src = $('rg-src').value, seq = ++checkSeq;
    if (!bbox || !src) { plan = null; nameCheck(); return; }
    $('rg-check').innerHTML = '<div class="rg-check muted">Считаю отели в рамке…</div>';
    try { plan = await api('/api/regions/check', {source: src, bbox}); } catch (e) { plan = null; $('rg-check').innerHTML = `<div class="rg-check err">${esc(err(e))}</div>`; nameCheck(); return; }
    if (seq != checkSeq) return;
    const est = plan.estimate_s;
    $('rg-check').innerHTML = `<div class="rg-check ${plan.ok ? '' : 'err'}"><b>${plan.hotels}</b> ${pl(plan.hotels, 'отель', 'отеля', 'отелей')} в рамке · ${dc(plan.area_km2)} км²${plan.apartments_skipped ? `<div class="small muted">квартир пропущено: ${plan.apartments_skipped}</div>` : ''}
      ${plan.ok ? `<div class="small">Расчёт около ${fmtT(est.compute)} плюс OSM ${Math.round(est.osm[0] / 60)}–${Math.round(est.osm[1] / 60)} мин</div>` : ''}
      ${plan.errors.map(x => `<div class="small">✕ ${esc(x)}</div>`).join('')}${plan.warnings.map(x => `<div class="small w">⚠ ${esc(x)}</div>`).join('')}</div>`;
    nameCheck();
  }

  function nameCheck() {
    const name = $('rg-name').value.trim().toLowerCase(), ex = R.regions.find(r => r.name == name);
    const valid = /^[a-z][a-z0-9_-]{1,30}$/.test(name) && name != 'default';
    $('rg-exists').innerHTML = !name ? '' : !valid ? '<span class="bad">латиница, цифры, - и _, от 2 знаков</span>'
      : ex?.active ? '<span class="bad">это активный регион: переключитесь на другой, чтобы его пересобрать</span>'
      : ex ? `Регион <code>${esc(name)}</code> уже есть.<br><label style="display:inline;color:var(--ink)"><input type="checkbox" id="rg-reuse" checked style="width:auto"> взять уже скачанное (OSM, рельеф, климат)</label><br>
        <label style="display:inline;color:var(--ink)"><input type="checkbox" id="rg-over" style="width:auto"> пересобрать с нуля</label>` : 'Новая папка data/regions/' + esc(name);
    $('rg-go').disabled = !(plan && plan.ok && valid && !ex?.active && !R.running);
    $('rg-go').title = R.running ? 'уже идёт другая сборка' : '';
    if (!$('rg-goerr').querySelector('.rg-err')) $('rg-goerr').innerHTML = R.running ? `<div class="rg-hint">Сейчас собирается «${esc(R.running.label || R.running.name)}»: следующую можно запустить, когда она закончится.</div>` : '';
  }

  async function startBuild(body) {
    $('rg-goerr').innerHTML = '';
    try { curJob = await api('/api/regions/build', body); } catch (e) { $('rg-goerr').innerHTML = `<div class="rg-err">${esc(err(e))}</div>`; return; }
    fetchedAt = Date.now() / 1000; R.running = curJob; renderJob(curJob); nameCheck(); poll();
    $('rg-job').scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  async function switchTo(name) {
    const r = R.regions.find(x => x.name == name);
    document.body.insertAdjacentHTML('beforeend', `<div class="rg-over" id="rg-over"><div>Перезапускаю сервер с регионом «${esc(r?.label || name)}»…</div></div>`);
    try { await api('/api/regions/switch', {name}); } catch (e) { $('rg-over').firstChild.innerHTML = `<span class="bad">${esc(err(e))}</span>`; setTimeout(() => $('rg-over')?.remove(), 3000); return; }
    const t0 = Date.now();
    (async function wait() {
      await new Promise(ok => setTimeout(ok, 700));
      try { const s = await api('/api/status'); if (s.region == name) { localStorage.setItem('cmp', '[]'); location.reload(); return; } } catch (_) { /* сервер ещё поднимается */ }
      if (Date.now() - t0 < 30000) wait(); else $('rg-over').firstChild.innerHTML = 'Сервер не поднялся за 30 с. Проверьте консоль, где он запущен.';
    })();
  }

  // ---------- события ----------
  $('rg-src').onchange = () => { bbox = null; if (rect) rect.remove(); $('rg-bbox').value = ''; $('rg-check').innerHTML = ''; plan = null; loadPoints(); setMode(); nameCheck(); };
  $('rg-bbox').onchange = () => {
    const b = $('rg-bbox').value.split(/[,;\s]+/).filter(Boolean).map(Number);
    if (b.length == 4 && b.every(isFinite) && b[0] < b[2] && b[1] < b[3]) setBbox(b, true);
    else $('rg-check').innerHTML = '<div class="rg-check err">нужно четыре числа: юг, запад, север, восток</div>';
  };
  $('rg-draw').onclick = () => { bbox = null; corner = null; if (rect) rect.remove(); plan = null; $('rg-check').innerHTML = ''; setMode(); nameCheck(); };
  $('rg-label').oninput = () => {
    const v = $('rg-label').value.trim();
    $('rg-in').placeholder = v ? 'в ' + v : 'в Хосте'; $('rg-of').placeholder = v || 'Хосты';
    if (!nameTouched) { $('rg-name').value = slug(v); nameCheck(); }
  };
  $('rg-name').oninput = () => { nameTouched = true; nameCheck(); };
  $('rg-go').onclick = () => {
    const name = $('rg-name').value.trim().toLowerCase(), label = $('rg-label').value.trim() || name;
    startBuild({name, source: $('rg-src').value, bbox, label, label_in: $('rg-in').value.trim() || null, label_of: $('rg-of').value.trim() || null,
      reuse: !!$('rg-reuse')?.checked && !$('rg-over')?.checked, overwrite: !!$('rg-over')?.checked || !!$('rg-reuse')?.checked});
  };
  $('t-regions').addEventListener('click', async e => {
    const d = e.target.dataset || {};
    if (d.sw) switchTo(d.sw);
    if (d.cancel) { try { curJob = await api(`/api/regions/jobs/${encodeURIComponent(d.cancel)}/cancel`, {}); fetchedAt = Date.now() / 1000; renderJob(curJob); load(); } catch (x) { alert(err(x)); } }
    if (d.retry && curJob) {
      const src = R.sources.find(s => s.path == curJob.source)?.id || $('rg-src').value;
      startBuild({name: curJob.name, source: src, bbox: curJob.bbox, label: curJob.label, label_in: curJob.label_in, label_of: curJob.label_of, reuse: true, overwrite: true});
    }
    if (d.log) {
      const j = await api(`/api/regions/jobs/${encodeURIComponent(d.log)}?log=true`);
      $('rg-log').innerHTML = `<pre>${esc(j.log_tail || 'журнал пуст')}</pre>`;
    }
    if (d.job) { curJob = await api('/api/regions/jobs/' + encodeURIComponent(d.job)); fetchedAt = Date.now() / 1000; renderJob(curJob); load(); }
  });

  // идущая сборка видна в шапке на любой вкладке
  api('/api/regions').then(d => { R = d; if (d.running) { curJob = d.running; fetchedAt = Date.now() / 1000; badge(curJob); poll(); } }).catch(() => {});
})();
