/* Интерфейсы по ролям на общем index.html: /ui/classic — прежняя страница гостя, /hotelier — отельер, /backoffice —
   команда Островка. Роль ставит строчка в <head> index.html (data-role на <html>), стиль — skin.css и
   front/postcard-roles.css. Здесь: шапка с кнопкой «Сменить роль», вкладки роли, поиск для гостя по образцу ostrovok.ru,
   «мой отель» и карточка глазами гостя для отельера, обзор для команды. Подключается последним, поверх модулей. */
(function () {
  const ROLE = document.documentElement.dataset.role;
  if (!ROLE) return;

  const ROLES = {
    guest: { path: '/ui/classic', link: 'Гостям', short: 'Гость', sub: 'для гостей', title: 'О!Правда: подбор отеля',
      tabs: [['search', 'Поиск'], ['hotel', 'Отель'], ['compare', 'Сравнение'], ['chars', 'Свой критерий']] },
    hotelier: { path: '/hotelier', link: 'Отельерам', short: 'Отельер', sub: 'для отельеров', title: 'О!Правда: кабинет отельера',
      tabs: [['hotelier', 'Вопросы и профиль'], ['audit', 'Проверка обещаний'], ['hotel', 'Как видят гости']] },
    admin: { path: '/backoffice', link: 'Команде Островка', short: 'Островок', sub: 'для команды', title: 'О!Правда: бэк-офис',
      tabs: [['overview', 'Обзор'], ['city', 'Профиль города'], ['search', 'Поиск'], ['hotel', 'Отель'], ['compare', 'Сравнение'],
        ['chars', 'Характеристики'], ['metrics', 'Метрики'], ['audit', 'Обещания'], ['hotelier', 'Вопросы отельерам'],
        ['log', 'Актуализация'], ['regions', 'Регионы']] },
  };
  const R = ROLES[ROLE];
  const E = s => esc(s);
  const nf = n => Math.round(n).toLocaleString('ru-RU');
  const cap = s => s ? s[0].toUpperCase() + s.slice(1) : '';
  const store = { get: k => { try { return localStorage.getItem(k) } catch (e) { return null } }, set: (k, v) => { try { localStorage.setItem(k, v) } catch (e) { } } };
  const body = document.body;
  document.title = R.title;

  /* шапка: словесный знак, вкладки роли, переключатель ролей */
  const header = document.querySelector('header'), nav = $('nav');
  // отельер и команда — в мире витрины «Открытка из Сочи» (front/postcard-roles.css): словесный знак как на /
  const MARK = '<span class="o-mark">OSTR<svg viewBox="0 0 15 19" aria-hidden="true"><path fill="currentColor" d="M7.5 0C3.4 0 0 3.3 0 7.4c0 5 6.3 10.8 6.6 11.1.5.4 1.3.4 1.8 0 .3-.3 6.6-6.1 6.6-11.1C15 3.3 11.6 0 7.5 0zm0 10.6a3.2 3.2 0 1 1 0-6.4 3.2 3.2 0 0 1 0 6.4z"/></svg>VOK.RU</span>';
  header.insertAdjacentHTML('afterbegin', ROLE === 'guest' ? `<a class="o-logo" href="${R.path}"><b>О!Правда</b><small>${E(R.sub)}</small></a>`
    : `<a class="pc-logo" href="${R.path}">${MARK}<span class="logo-sub">О!Правда<small>${E(R.sub)}</small></span></a>`);
  // роли меняются на /choose-role, как на витрине: одна кнопка вместо трёх ссылок
  header.insertAdjacentHTML('beforeend', `<a class="o-switch" href="/choose-role" aria-label="Сменить роль: гость, отельер или команда Островка"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7h12l-3-3M17 17H5l3 3"/></svg><span>Сменить роль</span></a>`);
  const badge = $('rg-badge'); if (badge && ROLE !== 'admin') badge.remove();

  /* вкладки: только свои и в своём порядке, секции чужих ролей остаются в DOM, но кнопок к ним нет */
  if (ROLE === 'admin') document.querySelector('main').insertAdjacentHTML('afterbegin', '<section class="tab" id="t-overview"><div class="o-ov" id="ov">Собираю…</div></section>');
  const tabs = R.tabs.filter(([k]) => $('t-' + k));
  nav.innerHTML = tabs.map(([k, v]) => `<button data-t="${k}">${E(v)}</button>`).join('');

  const show0 = window.show;
  let inner = false;
  window.show = function (t) {
    body.dataset.tab = t;
    if (inner) return show0(t);
    if (ROLE === 'hotelier' && t === 'audit' && my()) $('aout').innerHTML = '<div class="muted" style="margin-top:10px">Считаю…</div>';
    show0(t);
    if (ROLE === 'admin' && t === 'overview') overview();
    if (ROLE === 'admin' && t === 'hotelier' && !$('cab').innerHTML) openQueue();
    if (ROLE === 'hotelier' && my()) {
      inner = true;
      try {
        if (t === 'audit') openAudit(my());
        if (t === 'hotel') guestView(my());
      } finally { inner = false; }
    }
  };

  /* страница отеля как на Островке: «‹ Все варианты», шапка с ценой, мозаика фото */
  let shownHotel = null;
  const openHotel0 = window.openHotel;
  window.openHotel = async function (id) {
    shownHotel = id;
    const [r, d] = await Promise.all([openHotel0(id), api('/api/hotels/' + id).catch(() => null)]);
    const host = $('hotel'), head = host.querySelector('.vd-head');
    if (d && head && shownHotel === id) {
      const h = d.hotel, ph = d.card.photos || [];
      const back = (ROLE === 'guest' && body.classList.contains('o-searched') ? '<button onclick="show(\'search\')">‹ Все варианты</button>' : '')
        + (ROLE === 'guest' ? '<button onclick="oHome()">⌕ Новый поиск</button>' : '');
      head.className = 'vd-head o-hhead';
      head.innerHTML = `<div><h2>${E(h.name)}</h2><div class="o-haddr">${E(h.address || '')} · <a href="#" onclick="document.getElementById('hmap').scrollIntoView({behavior:'smooth',block:'center'});return false">Показать на карте</a></div>
        ${h.rating ? `<div class="o-rate o-rate-l"><i class="${rc(h.rating)}">${dc(h.rating)}</i><div><b>${word(h.rating)}</b><span>${h.reviews} ${pl(h.reviews, 'отзыв', 'отзыва', 'отзывов')}</span></div></div>` : ''}</div>
        <div class="o-hbuy">${h.price_nov1 ? `<span>от <b>${nf(h.price_nov1)} ₽</b></span>` : '<span class="muted">нет мест на 1 ноября</span>'}<a class="o-btn" href="${E(h.url)}" target="_blank" rel="noopener">Посмотреть цены</a></div>`;
      if (back) head.insertAdjacentHTML('beforebegin', `<div class="o-crumbs">${back}</div>`);
      if (ph.length) {
        const big = ph[0].replace('/t/640x400/', '/t/1024x768/');
        head.insertAdjacentHTML('afterend', `<div class="o-mosaic n${Math.min(ph.length, 4)}"><img src="${E(big)}" onerror="this.onerror=null;this.src='${E(ph[0])}'" alt="">${ph.slice(1, 4).map(p => `<img src="${E(p)}" alt="" loading="lazy">`).join('')}</div>`);
      }
    }
    return r;
  };

  document.body.insertAdjacentHTML('beforeend', `<footer class="o-foot"><span>Факты из OpenStreetMap, Copernicus GLO-30, Open-Meteo, карточек и отзывов Островка, ответов отельеров. У каждого факта есть источник, уверенность и срок годности.</span>
    <span><a href="/choose-role">Сменить роль</a></span></footer>`);

  /* оценка как на Островке: слово, число отзывов и зелёная «закладка», чем выше, тем насыщеннее */
  function word(r) { return r >= 9 ? 'Превосходно' : r >= 8.5 ? 'Отлично' : r >= 8 ? 'Очень хорошо' : r >= 7 ? 'Хорошо' : 'Неплохо' }
  function rc(r) { return r >= 9 ? 'r9' : r >= 8 ? 'r8' : r >= 7 ? 'r7' : 'r6' }

  /* ───── гость ───── */
  if (ROLE === 'guest') {
    const sec = $('t-search'), grid = sec.querySelector('.grid'), chat = grid.querySelector('.chat'), col = grid.children[1];

    /* главная: зелёная шапка во всю ширину, поля с подписями, синяя «Найти» */
    const hero = document.createElement('div');
    hero.className = 'o-hero';
    hero.innerHTML = `<div class="o-in"><h1>Оооочень честно про&nbsp;каждый отель!</h1>
      <p class="o-lead">Опишите словами, что важно в поездке. Проверим по карте, высотам, шуму и отзывам и скажем, где не уверены.</p><div class="o-slot"></div>
      <div class="o-where" id="o-where"></div></div>`;
    document.querySelector('main').before(hero);
    const form = $('askf'), q = $('q'), go = form.querySelector('button');
    q.rows = 1;
    q.placeholder = 'тихий номер с видом на закат, до моря пешком, июль';
    form.innerHTML = '';
    form.insertAdjacentHTML('beforeend', `<label class="o-field o-what"><span>Что важно в поездке</span></label>`);
    form.querySelector('.o-what').appendChild(q);
    go.textContent = 'Найти'; go.className = 'b o-go'; form.appendChild(go);
    hero.querySelector('.o-slot').append(form, $('examples'));

    const sheet = document.createElement('div');
    sheet.className = 'o-sheet';
    sheet.innerHTML = `<h2 class="o-big">Как мы проверяем отели</h2><p class="o-sub">Не верим на слово ни описанию, ни рекламе: считаем сами и сверяем источники</p>
      <div class="o-empty">
      <div><i>🛰</i><b>Считаем сами</b><span>Вид на море по этажам, шум ночью по сторонам здания, путь до пляжа с подъёмами.</span></div>
      <div><i>✓</i><b>Сверяем каждую цифру</b><span>Ответ помощника проверяется по расчётам: что не подтвердилось, убираем.</span></div>
      <div><i>🏨</i><b>Спрашиваем отель</b><span>Если данных мало, вопрос уходит отельеру, а вы видите, насколько мы уверены.</span></div></div>`;
    sec.insertBefore(sheet, grid);

    /* выдача: слева запрос и что проверили, в центре ответ и отели, справа карта во всю высоту */
    grid.className = 'o-serp';
    const side = document.createElement('aside');
    side.className = 'o-side';
    side.innerHTML = '<div class="o-box o-qbox" id="o-qbox"><div class="o-qhead">Ваш запрос</div></div><div class="o-box"><div class="o-qhead">Что проверили</div><div id="o-counts-slot"></div></div>';
    side.querySelector('#o-counts-slot').appendChild($('counts'));
    grid.insertBefore(side, grid.firstChild);
    col.className = 'o-list';
    col.insertAdjacentHTML('afterbegin', '<div class="o-found" id="o-found"></div>');
    $('o-found').after(chat);
    const rowc = col.querySelector('.row'); if (rowc) rowc.remove();
    const mc = document.createElement('div'); mc.className = 'o-mapcol'; mc.appendChild($('map')); grid.appendChild(mc);

    let zone = '';
    api('/api/status').then(s => { zone = s.zone; $('o-where').textContent = `${cap(s.zone)} · ${s.hotels} ${pl(s.hotels, 'отель', 'отеля', 'отелей')} проверено`; });

    function place(searched) {
      body.classList.toggle('o-searched', searched);
      const slot = searched ? $('o-qbox') : hero.querySelector('.o-slot');
      slot.appendChild(form);
      if (!searched) slot.appendChild($('examples'));
      setTimeout(() => map.invalidateSize(), 80);
    }
    window.oPlace = place;
    window.oHome = function () { place(false); show('search'); window.scrollTo(0, 0); q.focus(); };
    const send0 = window.send;
    window.send = function () {
      if (q.value.trim()) { place(true); show('search'); window.scrollTo(0, 0); }
      return send0();
    };

    let n = 0;
    const render0 = window.renderResults;
    window.renderResults = function (s) {
      n = 0;
      const c = s.counts, shown = s.results.length || s.near_misses.length;
      $('o-found').innerHTML = s.nothing_to_check ? `Ищем варианты ${zone ? 'в зоне «' + E(zone) + '»' : ''}`
        : s.results.length ? `Подходят ${c.match}${c.maybe ? `, ещё ${c.maybe} уточняем` : ''} · показаны ${shown}` : 'Точных совпадений нет, вот ближайшие';
      return render0(s);
    };
    const TAG = { match: ['✓ Подходит', 'ok'], maybe: ['? Уточняем', 'mb'], fail: ['✕ Не подходит', 'no'] };
    const MK = { pass: '✓', fail: '✕', unknown: '?' };
    window.card = function (r) {
      const h = r.hotel, [tl, tc] = TAG[r.bucket] || ['не определено', 'mb'];
      n += 1;
      const perks = (r.chips || []).map(x => `<li class="o-${x.status}" title="${E(x.full)}"><i>${MK[x.status] || '?'}</i>${E(x.text)}${x.status === 'unknown' ? ' — уточняем' : ''}</li>`).join('');
      return `<div class="card h o-card">
        <div class="o-ph" onclick="openHotel('${h.id}')"><img src="${E(h.photo || '')}" alt="" loading="lazy" onerror="this.style.visibility='hidden'"><span class="o-tag ${tc}">${tl}</span><span class="o-num">${n}</span></div>
        <div class="o-main">
          <div class="o-top"><div class="o-tl"><div class="o-name" onclick="openHotel('${h.id}')">${E(h.name)}</div>
            ${h.stars ? `<div class="o-stars" title="${h.stars} ${pl(h.stars, 'звезда', 'звезды', 'звёзд')}">${'★'.repeat(h.stars)}</div>` : ''}<div class="o-addr">${E(h.address || '')}</div></div>
            ${h.rating ? `<div class="o-rate"><div><b>${word(h.rating)}</b><span>${h.reviews} ${pl(h.reviews, 'отзыв', 'отзыва', 'отзывов')}</span></div><i class="${rc(h.rating)}">${dc(h.rating)}</i></div>` : ''}</div>
          <div class="o-offer"><div class="o-ol"><ul class="lines o-perks">${perks}</ul></div>
            <div class="o-price">${h.price_nov1 ? `<b>${nf(h.price_nov1)} ₽</b><span>за ночь, 1 ноября</span>` : '<span>нет мест на 1 ноября</span>'}</div></div>
          <div class="o-acts"><button class="g" onclick="addCmp('${h.id}')">В сравнение</button><a class="g" href="${E(h.url)}" target="_blank" rel="noopener">На Островке ↗</a>
            <button class="b" onclick="openHotel('${h.id}')">Все факты об отеле</button></div></div></div>`;
    };

    /* «Свой критерий»: гостю только форма, без реестра и черновиков админа */
    const ch = $('t-chars');
    ch.querySelector('.grid').style.gridTemplateColumns = '1fr';
    const reg = $('chars').closest('.card'); if (reg) reg.style.display = 'none';
    const st = document.createElement('style');
    st.textContent = '#t-chars #drafts{display:none}#t-chars .grid{max-width:760px}';
    document.head.appendChild(st);
    ch.querySelector('h2').textContent = 'Не нашли нужное условие? Опишите его';
    ch.querySelector('.muted.small').textContent = 'Помощник сам выберет источники, проверит на нескольких отелях и посчитает для всех. Новый критерий сразу работает в вашем поиске, остальным гостям он станет доступен после проверки командой Островка.';
    place(false);
  }

  /* ───── отельер ───── */
  function my() { return store.get('myHotel') }
  /* «Как видят гости»: карточка отеля с витрины /ui (?embed=1 — только карточка, без шапки и выдачи), ровно как у гостя */
  function guestView(id) {
    const host = $('t-hotel');
    if (host.dataset.gv === id) return;
    host.dataset.gv = id;
    host.innerHTML = `<div class="card pc-gv"><h2>Как видят гости</h2><div class="muted small">Карточка вашего отеля на витрине Островка: вердикт, какой номер брать, вид из окна, ночь по часам и источники фактов. Это ровно то, что видит гость.</div>
      <iframe class="pc-gv-frame" src="/ui?hotel=${encodeURIComponent(id)}&embed=1" title="Карточка отеля глазами гостя" loading="lazy"></iframe>
      <a class="g" href="/ui?hotel=${encodeURIComponent(id)}" target="_blank" rel="noopener">Открыть на витрине ↗</a></div>`;
  }
  if (ROLE === 'hotelier') {
    const box = $('t-hotelier').querySelector('.card');
    box.querySelector('h2').remove();
    [...box.querySelectorAll('button')].find(b => b.textContent.includes('Все открытые'))?.remove();
    box.insertAdjacentHTML('afterbegin', '<div id="o-me"></div>');
    const row = box.querySelector('.row'); row.style.display = 'none';

    const cab0 = window.openCabinet;
    window.openCabinet = async function (id) {
      store.set('myHotel', id); shownHotel = null;
      document.documentElement.dataset.hotel = id;
      if (window.Auth) Auth.need('hotelier', id);   // демо-вход; кабинет открывается сразу, отвечать можно после входа
      $('klist').innerHTML = ''; row.style.display = 'none';
      me(id);
      return cab0(id);
    };
    window.oChange = function () {
      $('o-me').innerHTML = '<h2>Какой отель вы представляете?</h2><div class="muted small">Демо без входа: выберите отель из списка или найдите по названию. Сначала отели, где у гостей больше всего вопросов.</div>';
      row.style.display = ''; $('cab').innerHTML = '';
      pickList();
    };
    async function me(id) {
      const hs = await api('/api/hotels'), h = hs.find(x => x.id === id);
      $('o-me').innerHTML = `<div class="o-me">${h && h.photo ? `<img src="${E(h.photo)}" alt="">` : ''}<div><div class="muted">Ваш отель</div><b>${E(h ? h.name : id)}</b>
        <div class="muted">${h && h.address ? E(h.address) : ''}</div></div>
        ${h && h.rating ? `<div class="o-rate"><div><b>${word(h.rating)}</b><span>${h.reviews} ${pl(h.reviews, 'отзыв', 'отзыва', 'отзывов')}</span></div><i class="${rc(h.rating)}">${dc(h.rating)}</i></div>` : ''}
        <button class="g" onclick="oChange()">Сменить отель</button></div>`;
    }
    async function pickList() {
      const [qs, hs] = await Promise.all([api('/api/questions'), api('/api/hotels')]);
      const cnt = {}; qs.forEach(q => { cnt[q.hotel_id] = (cnt[q.hotel_id] || 0) + 1 });
      const top = hs.map(h => [h, cnt[h.id] || 0]).sort((a, b) => b[1] - a[1]).slice(0, 12);
      $('klist').innerHTML = `<div class="o-pick">${top.map(([h, c]) => `<button onclick="openCabinet('${h.id}')">${h.photo ? `<img src="${E(h.photo)}" alt="" loading="lazy">` : ''}<span><b>${E(h.name)}</b><span>${c ? `<em>${c} ${pl(c, 'вопрос', 'вопроса', 'вопросов')}</em> ждут ответа` : 'вопросов нет'}</span></span></button>`).join('')}</div>`;
    }
    window.openHotel = () => show('hotel');  // любая «Карточка» у отельера — его отель глазами гостя
    if (my()) { document.documentElement.dataset.hotel = my(); me(my()); cab0(my()); if (window.Auth) Auth.need('hotelier', my()); } else oChange();
  }

  /* ───── админ: обзор ───── */
  async function overview() {
    const ov = $('ov');
    const [s, dr, rg, ev, N, ct] = await Promise.all([api('/api/status'), api('/api/drafts?status=all'), api('/api/regions').catch(() => ({})), api('/api/events?limit=8'), names(), api('/api/city').catch(() => null)]);
    const wait = dr.drafts.filter(d => d.status === 'draft'), run = rg.running;
    const ready = ct ? ct.requests.filter(r => r.state === 'ready').length : 0, top = ct ? ct.chars.slice(0, 2).map(c => c.name.toLowerCase()).join(', ') : '';
    const tile = (v, label, tab, hot) => `<button data-go="${tab}"${hot ? ' class="o-hot"' : ''}><b>${v}</b><span>${label}</span></button>`;
    ov.innerHTML = `<div class="o-tiles">
      ${tile(E(cap(s.zone)), `${s.hotels} ${pl(s.hotels, 'отель', 'отеля', 'отелей')} · OSM на ${ruDate(s.osm_base)}`, 'regions')}
      ${tile(s.characteristics, pl(s.characteristics, 'характеристика в поиске', 'характеристики в поиске', 'характеристик в поиске'), 'chars')}
      ${ct ? tile(ready || ct.requests.filter(r => r.state === 'candidate').length, ready ? `${pl(ready, 'параметр гости просят', 'параметра гости просят', 'параметров гости просят')} чаще ${ct.threshold} раз` : `${pl(ct.requests.filter(r => r.state === 'candidate').length, 'кандидат', 'кандидата', 'кандидатов')} в профиль города · важнее всего: ${E(top)}`, 'city', ready) : ''}
      ${tile(wait.length, pl(wait.length, 'черновик ждёт решения', 'черновика ждут решения', 'черновиков ждут решения'), 'chars', wait.length)}
      ${tile(nf(s.open_questions), 'вопросов отельерам без ответа', 'hotelier', s.open_questions)}
      ${tile(s.llm ? 'LLM' : 'правила', s.llm ? `разбор запросов: ${E(s.model || s.provider)}` : 'разбор запросов по ключевым словам', 'metrics')}
      ${run ? tile(`${Math.round((run.progress || 0) * 100)}%`, `сборка региона «${E(run.label || run.name)}»`, 'regions', 1) : ''}</div>
      <div class="o-two"><div class="card"><h2>Ждут решения</h2>${wait.map(d => `<div class="o-dr"><div><b>${E(d.name)}</b><div class="muted small">${E(d.eval?.verdict || '')} · ${E(ruDate(d.drafted_at))}</div></div><button class="g" data-go="chars">Разобрать</button></div>`).join('') || '<div class="muted">Новых черновиков нет.</div>'}</div>
      <div class="card"><h2>Последние события</h2>${ev.map(e => `<div class="ev"><div class="when">${E(ruDate(e.at))} ${E(e.at.slice(11, 16))}</div><div>${evLine(e, N)}</div></div>`).join('') || '<div class="muted">Пока пусто.</div>'}
        <button class="g" data-go="log" style="margin-top:8px">Весь журнал</button></div></div>`;
    ov.onclick = e => { const t = e.target.closest('[data-go]'); if (t) show(t.dataset.go) };
  }

  show(tabs[0][0]);
})();
