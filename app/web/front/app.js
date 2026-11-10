/* О!Правда об отеле: витрина. Vanilla JS, Leaflet для карты. Данные только из /api/*. */
(() => {
'use strict';

/* ================= утилиты ================= */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : '';
/* «с 6-го этажа», но «со 2-го этажа» */
const fromFl = n => `${n === 2 ? 'со' : 'с'} ${n}-го этажа`;
/* верхний этаж здания называем «последним», а не «с N-го»: выше подниматься некуда */
const atFl = (n, L) => L > 1 && n >= L ? `на последнем (${L}-м) этаже` : fromFl(n);
const nomFl = (n, L) => L > 1 && n >= L ? `последний (${L}-й) этаж` : `${n}-й этаж`;
const DIR_ADJ = { 'С': 'северной', 'СВ': 'северо-восточной', 'В': 'восточной', 'ЮВ': 'юго-восточной', 'Ю': 'южной', 'ЮЗ': 'юго-западной', 'З': 'западной', 'СЗ': 'северо-западной' };
const DIR_GEN = { 'С': 'севера', 'СВ': 'северо-востока', 'В': 'востока', 'ЮВ': 'юго-востока', 'Ю': 'юга', 'ЮЗ': 'юго-запада', 'З': 'запада', 'СЗ': 'северо-запада' };
const DIR_CODE = 'СВ|СЗ|ЮВ|ЮЗ|С|В|Ю|З';
/* коды сторон света в тексте фактов раскрываем словами, «5-го этажа» не разрываем переносом */
const tidy = t => String(t ?? '')
  .replace(/(\d+) раз(?![а-яё])/g, (m, n) => { const k = +n % 100, d = k % 10; return n + (d >= 2 && d <= 4 && (k < 12 || k > 14) ? ' раза' : ' раз') })  // факты в базе пишут «2 раз»
  .replace(new RegExp(`на стороне (${DIR_CODE})(?![А-Яа-яЁё])`, 'g'), (m, c) => `на ${DIR_ADJ[c]} стороне`)
  .replace(new RegExp(`со стороны (${DIR_CODE})(?![А-Яа-яЁё])`, 'g'), (m, c) => `со стороны ${DIR_GEN[c]}`)
  .replace(new RegExp(`(шумнее всего|громче всего|тише всего) (${DIR_CODE})(?![А-Яа-яЁё])`, 'g'), (m, w, c) => `${w} со стороны ${DIR_GEN[c]}`)
  .replace(/(\d+-(?:го|й|м|е)) (этаж\w*)/g, '$1\u00a0$2');
/* уровни шума снаружи подписываем «у фасада», внутри номера «в номере»: два числа про одну сторону никогда не стоят без подписи */
const outDb = t => String(t ?? '').replace(/~(\d+)\s?дБ(?! у фасада)( ночью)?/g, (m, n, ni) => `~${n} дБ у фасада${ni || ''}`);
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const isDesk = () => matchMedia('(min-width:980px)').matches;
const vib = (n = 8) => { try { navigator.vibrate && navigator.vibrate(n) } catch (e) { } };
const plural = (n, a, b, c) => { const m = Math.abs(n) % 100, d = m % 10; return m > 10 && m < 20 ? c : d > 1 && d < 5 ? b : d === 1 ? a : c };
const money = n => Math.round(n).toLocaleString('ru-RU').replace(/ /g, ' ') + ' ₽';
const fdate = iso => { try { return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }) } catch (e) { return '' } };
/* id сессии (тот же ключ, что в /drafts.js): характеристика, собранная из выдачи, видна этому посетителю до одобрения админом */
const SID = (() => { try { let v = localStorage.getItem('osess'); if (!v) { v = 's' + Math.random().toString(36).slice(2, 12); localStorage.setItem('osess', v) } return v } catch (e) { return 's' + Math.random().toString(36).slice(2, 12) } })();
const j = async (url, body) => {
  const r = await fetch(url, body === undefined ? { headers: { 'X-Session': SID } } : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Session': SID }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(url + ' ' + r.status);
  return r.json();
};
function vt(fn) {
  if (!document.startViewTransition || reduced) { fn(); return { finished: Promise.resolve() } }
  try { return document.startViewTransition(fn) } catch (e) { fn(); return { finished: Promise.resolve() } }
}
/* события выдачи для кластеров вкуса (app/taste.py): поиск, показанный порядок, открытие, время просмотра */
const EMBED = document.documentElement.classList.contains('embed');  // карточка внутри кабинета отельера: это не гость, не трекаем
const track = (type, data, hid) => { if (EMBED) return; try { window.Sense && Sense.track && Sense.track(type, data, hid) } catch (e) { } };
const trackedRaw = new WeakSet();
let openedAt = null;
function trackDwell() { if (openedAt) { track('dwell', { ms: Math.round(performance.now() - openedAt.t) }, openedAt.id); openedAt = null } }
let toastT;
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('on'), 2600) }

/* битые картинки: плитка-заглушка вместо иконки, лайм вместо фото */
function imgFail(img) {
  const p = img.parentElement;
  if (p && p.classList.contains('ico')) p.classList.add('fb');
  else if (p && p.classList.contains('ico-big')) p.classList.add('fb');
  else if (p && p.classList.contains('pc-pic')) { img.hidden = true; document.querySelector('.pc')?.classList.add('noart') }
  else { img.style.display = 'none'; if (p) p.classList.add('noimg') }
}
document.addEventListener('error', e => { if (e.target && e.target.tagName === 'IMG') imgFail(e.target) }, true);
const recheckImgs = () => $$('img').forEach(i => { if (i.complete && i.naturalWidth === 0 && i.getAttribute('src')) imgFail(i) });

/* ================= характеристики: иконки, группы ================= */
const CH = {
  sea_view: { n: 'Вид на море', i: 'sea', e: '🌊' }, sea_view_quiet: { n: 'Море с тихой стороны', i: 'sea', e: '🌊' },
  sea_season: { n: 'Море в сезон', i: 'sea', e: '🌊' },
  sunset: { n: 'Закат из окна', i: 'sunset', e: '🌅' }, sunset_quiet: { n: 'Закат с тихой стороны', i: 'sunset', e: '🌅' },
  beach_walk: { n: 'Путь до пляжа', i: 'beach', e: '🏖' },
  night_quiet: { n: 'Тишина', i: 'quiet', e: '🤫' }, soundproofing: { n: 'Шумоизоляция', i: 'quiet', e: '🤫' },
  blackout: { n: 'Плотные шторы', i: 'quiet', e: '🌙' }, construction: { n: 'Стройка рядом', e: '🚧' },
  kids: { n: 'Для детей рядом', i: 'kids', e: '🧸' }, pets: { n: 'С питомцем', i: 'pets', e: '🐾' },
  accessibility: { n: 'Без лестниц', i: 'stairs', e: '🛗' }, car: { n: 'На машине', e: '🚗' }, wifi: { n: 'Интернет для работы', e: '📶' },
  night_checkin: { n: 'Заселение ночью', i: 'night', e: '🌃' }, night_open: { n: 'Что открыто ночью', i: 'night', e: '🌃' },
  food_near: { n: 'Где поесть рядом', e: '🍽' },
  breakfast: { n: 'Завтрак', e: '🥐' }, meal_plan: { n: 'Пансион и «всё включено»', e: '🍽' },
  pool: { n: 'Бассейн', e: '🏊' }, private_beach: { n: 'Свой пляж', i: 'beach', e: '🏖' }, spa: { n: 'СПА и сауна', e: '🧖' },
  fitness: { n: 'Тренажёрный зал', e: '🏋' }, adults_only: { n: 'Для взрослых', i: 'quiet', e: '🍸' },
  family: { n: 'Для семей с детьми', i: 'kids', e: '🧸' }, transfer: { n: 'Трансфер из аэропорта', e: '🚐' },
  kitchen: { n: 'Кухня в номере', e: '🍳' }, balcony: { n: 'Балкон или терраса', i: 'sea', e: '🌿' },
};
const GROUPS = [
  ['Море, вид и закат', 'sea_view', ['sea_view', 'sea_view_quiet', 'sunset', 'sunset_quiet', 'sea_season']],
  ['Дорога до пляжа', 'beach_walk', ['beach_walk']],
  ['Тишина и сон', 'night_quiet', ['night_quiet', 'soundproofing', 'blackout', 'construction']],
  ['Питание', 'breakfast', ['breakfast', 'meal_plan']],
  ['Бассейн, пляж и СПА', 'pool', ['pool', 'private_beach', 'spa', 'fitness']],
  ['С детьми, без детей, с питомцем', 'kids', ['family', 'kids', 'adults_only', 'pets']],
  ['Номер', 'balcony', ['balcony', 'kitchen']],
  ['Удобства', 'accessibility', ['accessibility', 'car', 'transfer', 'wifi']],
  ['Ночью и рядом', 'night_open', ['night_open', 'night_checkin', 'food_near']],
];
const ico = (cid, cls = '') => {
  const m = CH[cid] || { e: '•' };
  return `<span class="ico ${cls}" data-e="${m.e || '•'}">${m.i ? `<img src="/front/assets/icon-${m.i}.webp" alt="" loading="lazy">` : ''}</span>`;
};
const icoByName = (name, e, cls = '') => `<span class="ico ${cls}" data-e="${e}"><img src="/front/assets/icon-${name}.webp" alt="" loading="lazy"></span>`;
const KIND = { HOTEL: 'Отель', GUESTHOUSE: 'Гостевой дом', APART_HOTEL: 'Апарт-отель', LODGING_HOUSES: 'Дом для гостей', HOSTEL: 'Хостел', RESORT: 'Курорт', BOUTIQUE: 'Бутик-отель', MINI_HOTEL: 'Мини-отель', SANATORIUM: 'Санаторий' };
const MONTH_PREP = ['', 'январе', 'феврале', 'марте', 'апреле', 'мае', 'июне', 'июле', 'августе', 'сентябре', 'октябре', 'ноябре', 'декабре'];

const EXAMPLES = [
  { t: 'тихий номер с видом на закат недалеко от моря, июль', i: 'sunset', e: '🌅' },
  { t: 'вид на море, без подъёма в гору на обратном пути', i: 'sea', e: '🌊' },
  { t: 'с собакой', i: 'pets', e: '🐾' },
  { t: 'с детьми, детская площадка рядом', i: 'kids', e: '🧸' },
  { t: 'без лестниц, есть лифт', i: 'stairs', e: '🛗' },
  { t: 'заселиться ночью', i: 'night', e: '🌃' },
];
const TILES = [
  { n: 'Вид на море', d: 'Видно ли море из окна и с какого этажа.', q: 'вид на море', i: 'sea', e: '🌊' },
  { n: 'Закат', d: 'Смотрят ли окна на закат в нужный месяц.', q: 'вид на закат, июль', i: 'sunset', e: '🌅' },
  { n: 'Дорога до пляжа', d: 'Минуты пешком, подъём на обратном пути, переходы.', q: 'пляж не дальше 10 минут пешком', i: 'beach', e: '🏖' },
  { n: 'Тишина ночью', d: 'С какой стороны здания шумно: дорога, рельсы.', q: 'тихий номер и плотные шторы', i: 'quiet', e: '🤫' },
  { n: 'С детьми', d: 'Площадки, парки и больница поблизости.', q: 'с детьми, детская площадка рядом', i: 'kids', e: '🧸' },
  { n: 'С питомцем', d: 'Принимают ли с животными, где гулять.', q: 'с собакой', i: 'pets', e: '🐾' },
  { n: 'Без лестниц', d: 'Лифт, этажность, вход без ступеней.', q: 'без лестниц, есть лифт', i: 'stairs', e: '🛗' },
  { n: 'Ночью', d: 'Заселение после полуночи, что открыто рядом.', q: 'заселиться ночью', i: 'night', e: '🌃' },
];

/* условие из разбора запроса -> человеческая фраза */
/* Имена характеристик из реестра, включая собранные из выдачи («Ванна в номере»). */
const NAMES = {};
const loadNames = () => j('/api/characteristics').then(d => d.characteristics.forEach(c => { NAMES[c.id] = c.name })).catch(() => { });
loadNames();
function human(c, monthNum) {
  const v = c.value, k = c.char + '.' + c.field, lt = c.op === '<=' || c.op === '<', yes = v === true;
  const B = (a, b) => yes ? a : b;
  const map = {
    'beach_walk.minutes_there': () => `Пляж ${lt ? 'до' : 'от'} ${v} мин пешком`,
    'beach_walk.minutes_back': () => `Назад от пляжа ${lt ? 'до' : 'от'} ${v} мин`,
    'beach_walk.climb_back_m': () => `Подъём на обратном пути ${lt ? 'до' : 'от'} ${v} м`,
    'beach_walk.crosses_rail': () => B('С переходом через ж/д', 'Без перехода через ж/д'),
    'beach_walk.crosses_road': () => B('С переходом дороги', 'Без перехода дороги'),
    'night_quiet.quiet': () => B('Тихо ночью', 'Шумно ночью'),
    'night_quiet.day_quiet': () => B('Тихо днём', 'Шумно днём'),
    'sea_view.has': () => B('Вид на море', 'Без вида на море'),
    'sea_view_quiet.has': () => B('Море с тихой стороны', 'Море только с шумной стороны'),
    'sunset.visible': () => B('Закат из окна', 'Без заката из окна'),
    'sunset.over_sea': () => B('Закат над морем', 'Закат не над морем'),
    'sunset_quiet.visible_quiet': () => B('Закат с тихой стороны', 'Закат только с шумной стороны'),
    'kids.playground_near': () => B('Детская площадка рядом', 'Без площадки рядом'),
    'kids.playground_m': () => `Площадка ${lt ? 'в пределах' : 'дальше'} ${v} м`,
    'pets.allowed': () => B('Можно с питомцем', 'Без питомцев'),
    'accessibility.easy': () => B('Без лестниц', 'С лестницами'),
    'accessibility.lift': () => B('Есть лифт', 'Без лифта'),
    'accessibility.step_free_entrance': () => B('Вход без ступеней', 'Вход со ступенями'),
    'night_checkin.allowed': () => B('Заселение ночью', 'Без ночного заселения'),
    'night_checkin.desk_24h': () => B('Ресепшн круглосуточно', 'Ресепшн не круглосуточно'),
    'night_open.pharmacy_24h': () => B('Аптека круглосуточно', 'Без ночной аптеки'),
    'night_open.food_late': () => B('Еда поздно вечером', 'Без еды поздно вечером'),
    'night_open.shop_late': () => B('Магазин поздно вечером', 'Без магазина поздно вечером'),
    'sea_season.swim': () => B(monthNum ? `Купаться в ${MONTH_PREP[monthNum]}` : 'Можно купаться', 'Купаться нельзя'),
    'wifi.good': () => B('Хороший интернет', 'Слабый интернет'),
    'wifi.desk': () => B('Рабочий стол в номере', 'Без рабочего стола'),
    'construction.none_near': () => B('Без стройки рядом', 'Стройка рядом'),
    'soundproofing.good': () => B('Хорошая шумоизоляция', 'Слабая шумоизоляция'),
    'blackout.has': () => B('Плотные шторы', 'Без плотных штор'),
    'car.parking': () => B('Парковка', 'Без парковки'),
    'food_near.plenty': () => B('Есть где поесть рядом', 'Мало мест поесть рядом'),
    'breakfast.has': () => B('Завтрак', 'Без завтрака'), 'breakfast.buffet': () => B('Завтрак «шведский стол»', 'Завтрак не шведский стол'),
    'breakfast.in_room': () => B('Завтрак в номер', 'Без завтрака в номер'),
    'meal_plan.any_board': () => B('Пансион', 'Без пансиона'), 'meal_plan.half_board': () => B('Полупансион', 'Без полупансиона'),
    'meal_plan.full_board': () => B('Полный пансион', 'Без полного пансиона'), 'meal_plan.all_inclusive': () => B('Всё включено', 'Не «всё включено»'),
    'pool.has': () => B('Бассейн', 'Без бассейна'), 'pool.heated': () => B('Бассейн с подогревом', 'Бассейн без подогрева'),
    'pool.indoor': () => B('Крытый бассейн', 'Без крытого бассейна'), 'pool.outdoor': () => B('Открытый бассейн', 'Без открытого бассейна'),
    'private_beach.has': () => B('Свой пляж', 'Без своего пляжа'), 'spa.has': () => B('СПА или сауна', 'Без СПА'),
    'spa.sauna': () => B('Сауна или хаммам', 'Без сауны'), 'spa.massage': () => B('Массаж', 'Без массажа'),
    'fitness.has': () => B('Тренажёрный зал', 'Без тренажёрного зала'), 'adults_only.adult': () => B('Для взрослых', 'Много семей с детьми'),
    'adults_only.adults_only': () => B('Только для взрослых', 'Можно с детьми'), 'family.friendly': () => B('Для семей с детьми', 'Не для семей'),
    'family.kids_club': () => B('Детская комната или анимация', 'Без детской комнаты'), 'family.family_rooms': () => B('Семейные номера', 'Без семейных номеров'),
    'transfer.has': () => B('Трансфер', 'Без трансфера'), 'kitchen.has': () => B('Кухня в номере', 'Без кухни'), 'balcony.has': () => B('Балкон или терраса', 'Без балкона'),
    'stroller_beach.minutes_there': () => `С коляской до пляжа ${lt ? 'до' : 'от'} ${v} мин`,
    'stroller_beach.possible': () => B('С коляской до пляжа без лестниц', 'До пляжа только по лестницам'),
    'station_walk.minutes_there': () => `До станции ${lt ? 'до' : 'от'} ${v} мин пешком`,
    'center_walk.minutes_there': () => `До центра ${lt ? 'до' : 'от'} ${v} мин пешком`,
    'noise_floors.quiet': () => B('Есть тихая сторона и этаж ночью', 'Ночью шумно со всех сторон'),
  };
  if (map[k]) return map[k]();
  if (NAMES[c.char] && c.value === true) return NAMES[c.char];  // характеристики, добавленные словами
  const ph = String(c.phrase || '');
  if (ph && !/[\\[\]()|?*+^$]/.test(ph)) return cap(ph);
  return (CH[c.char]?.n || c.char) + (c.label ? `: ${c.label}` : '');
}

/* ================= почтовая символика: штемпели, марки, отметки ================= */
const I = {
  ok: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.500 4.500 4.500L19 7.500"/></svg>',
  no: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6.500 6.500 11 11m0-11-11 11"/></svg>',
  q: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.200 9.300a2.900 2.900 0 1 1 4.200 2.600c-.9.500-1.400 1-1.400 2M12 17.400v.1"/></svg>',
  flip: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h13l-3-3m6 11H7l3 3"/></svg>',
  arrow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6"/></svg>',
  plus: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
  star: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3.500 2.600 5.400 5.900.8-4.300 4.100 1 5.800L12 16.800l-5.200 2.800 1-5.800L3.500 9.700l5.900-.8z"/></svg>',
};
let pmN = 0;
/* штемпель: текст по кругу + код в центре. ring: что написано по кругу, code: центр */
function pmCenter(code) {
  const L = Array.isArray(code) ? code : [code], n = L.length, mx = Math.max(...L.map(x => x.length));
  const fs = Math.min(n > 1 ? 11 : 13.5, 78 / mx);
  return L.map((t, i) => `<text class="pm-c" style="font-size:${fs.toFixed(1)}px" x="50" y="${(n > 1 ? 50 + (i ? 12 : -1) : 50 + fs * .36).toFixed(1)}" text-anchor="middle">${esc(t)}</text>`).join('');
}
function pm(ring, code, cls = '', size = 64) {
  const id = 'pmp' + (++pmN); let t = String(ring).toUpperCase();
  const base = t; while (t.length < 30) t += '  ·  ' + base;
  return `<svg class="pmk ${cls}" viewBox="0 0 100 100" width="${size}" height="${size}" aria-hidden="true"><defs><path id="${id}" d="M13 50a37 37 0 1 1 74 0a37 37 0 1 1-74 0"/></defs><circle class="pm-o" cx="50" cy="50" r="47"/><circle class="pm-i" cx="50" cy="50" r="27"/><text class="pm-r"><textPath href="#${id}" textLength="228" lengthAdjust="spacing">${esc(t)}</textPath></text>${pmCenter(code)}</svg>`;
}
const dshort = iso => { try { const d = new Date(iso); return String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0') + '.' + d.getFullYear() } catch (e) { return '' } };
/* Источники факта берём из данных API: source + method. Центр штемпеля: короткие метки. */
const LBL = { osm: ['OSM', 'OSM'], dem: ['РЕЛЬЕФ', 'РЕЛЬЕФ'], meteo: ['OPEN-METEO', 'METEO'], card: ['ОСТРОВОК', 'ОСТРОВОК'], rev: ['ОТЗЫВЫ', 'ОТЗЫВЫ'], host: ['ОТЕЛЬЕР', 'ОТЕЛЬЕР'] };
const DEM_FACTS = new Set(['Вид на море', 'Море с тихой стороны', 'Закат из окна', 'Закат с тихой стороны', 'Путь до пляжа']);
const DATES = { osm: '' };
function srcInfo(src, iso, factName, method) {
  const s = String(src || ''), m = String(method || ''), k = [];
  if (/геоданн|openstreet|osm|расч[её]т/i.test(s)) { k.push('osm'); if (DEM_FACTS.has(factName) || /DEM|Copernicus|рельеф/i.test(m)) k.push('dem') }
  else if (/meteo|климат|погод/i.test(s)) k.push('meteo');
  else if (/отзыв/i.test(s)) k.push('rev');
  else if (/отельер/i.test(s)) k.push('host');
  else if (/карточк|островк/i.test(s)) { k.push('card'); if (/OSM/.test(m)) k.push('osm') }
  if (!k.length) k.push('card');
  const L = k.map(x => LBL[x]);
  const date = iso ? dshort(iso) : (k.includes('osm') && DATES.osm ? DATES.osm : '');
  return { code: L.map(x => x[1]), ring: L.map(x => x[0]).join(' + ') + (date ? '  ·  ' + date : ''), date, labels: L.map(x => x[0]).join(' + ') };
}
const confCls = c => c >= .7 ? 'hi' : c >= .5 ? 'mid' : 'lo';
/* уверенность словами: гостю проценты не нужны, точное число остаётся в подсказке. o.cls/o.label — для заявлений отеля */
const CONF_W = { hi: 'Устойчивый расчёт', mid: 'Скорее всего', lo: 'Примерно' };
const cst = (c, o = {}) => c == null ? '' : `<span class="cw ${o.cls || confCls(c)}" title="${o.label || 'Уверенность вывода'} ${Math.round(c * 100)}%">${CONF_W[confCls(c)]}</span>`;
/* числа с единицами жирнее, с табличными цифрами */
/* текст с раскрытыми сторонами света, «6-го этажа» без разрыва строки */
const esct = t => esc(tidy(t)).replace(/(\d+-(?:го|й|м|е)(?:\u00a0[а-яё.]+)?)/g, '<span class="nw">$1</span>');
const numify = t => esc(tidy(outDb(t))).replace(/(~?\d+(?:[.,]\d+)?(?:\s?(?:мин|дБ|км|эт\.|м|%)|-го эт\.|-(?:го|й|м|е)(?![а-яё]))?)/g, '<span class="num">$1</span>');

/* строка улики из API: «Название: суть — источник, уверенность 0.85 ⚠ …» */
function parseEv(line) {
  line = String(line); const warn = line.includes('⚠'); line = line.replace(/\s*⚠.*$/, '');
  let name = '', body = line, src = '', conf = null;
  const ci = line.indexOf(': ');
  if (ci > 0 && ci < 44) { name = line.slice(0, ci); body = line.slice(ci + 2) }
  const si = body.lastIndexOf(' — ');
  if (si > 0) { const tail = body.slice(si + 3); const m = tail.match(/уверенность\s*([\d.,]+)\s*$/); if (m) conf = parseFloat(m[1].replace(',', '.')); src = tail.replace(/,\s*уверенность\s*[\d.,]+\s*$/, ''); body = body.slice(0, si) }
  else { const p = body.match(/\s*\(([^()]+?),\s*уверенность\s*([\d.,]+)\)\s*$/); if (p) { src = p[1]; conf = parseFloat(p[2].replace(',', '.')); body = body.slice(0, p.index) } }  // поиск пишет «(источник, уверенность 0,79)»
  return { name, body, src, warn, conf };
}
function evList(row, max) {
  const mk = (arr, t) => (arr || []).map(l => ({ t, ...parseEv(l) }));
  const g = mk(row.good, 'good'), b = mk(row.bad, 'bad'), u = mk(row.unknown, 'unk');
  const order = row.bucket === 'match' ? [g, u, b] : row.bucket === 'maybe' ? [u, b, g] : [b, g, u];
  const all = order.flat(), shown = max ? all.slice(0, max) : all;
  return { all, shown, rest: all.length - shown.length };
}
const SYM = { good: [I.ok, 'Подходит'], bad: [I.no, 'Не подходит'], unk: [I.q, 'Пока не знаем'] };
const mark = t => `<i class="mk mk-${t}" role="img" aria-label="${SYM[t][1]}">${SYM[t][0]}</i>`;
/* строка на обороте: отметка, факт, уверенность словом. Источник скрыт, открывается кнопкой «Источник». */
function lineHTML(e, k) {
  const si = e.src ? srcInfo(e.src, null, e.name) : null;
  const src = si ? `<span class="ln-s">${pm(si.ring, si.code, 'pmk-s', 44)}<span>${esc(cap(e.src))}: ${esc(si.labels)}${si.date ? ', ' + si.date : ''}</span></span>` : '';
  return `<li class="ln ln-${e.t}" style="--k:${k}">${mark(e.t)}<div class="ln-b"><span class="ln-t">${e.name ? `<b>${esc(e.name)}.</b> ` : ''}${numify(cap(e.body))}</span>${e.warn ? '<span class="ln-w">Источники расходятся</span>' : ''}${src}</div><div class="ln-r">${cst(e.conf)}${si ? '<button type="button" class="ln-src js-src" aria-expanded="false">Источник</button>' : ''}</div></li>`;
}
/* короткая отметка на лицевой стороне */
/* из чего вывод: расчёт по открытым данным / карточка / отзывы / отельер */
const EV_KIND = { OSM: 'calc', 'РЕЛЬЕФ': 'calc', METEO: 'calc', 'ОСТРОВОК': 'card', 'ОТЗЫВЫ': 'rev', 'ОТЕЛЬЕР': 'host' };
const EV_LBL = { calc: 'Рассчитано', card: 'По карточке', rev: 'Из отзывов', host: 'Слово отельера' };
const evKinds = list => { const k = new Set(); list.forEach(e => { if (e.src) srcInfo(e.src, null, e.name).code.forEach(c => k.add(EV_KIND[c] || 'card')) }); return ['calc', 'card', 'rev', 'host'].filter(x => k.has(x)) };  // источник неизвестен: метку не выдумываем
/* верхняя тройка: главный плюс, главный минус именно для этого гостя, чем подтверждено */
function decideHTML(ev) {
  const miss = ((state.data && state.data.parsed && state.data.parsed.missing) || [])[0];  // часть запроса не проверена: не пишем «минусов нет»
  const pro = ev.all.find(e => e.t === 'good'), con = ev.all.find(e => e.t === 'bad'), unk = ev.all.find(e => e.t === 'unk');
  const one = e => `<b>${esc(e.name || cap(e.body).slice(0, 40))}</b>${e.name ? `<small>${numify(cap(e.body))}</small>` : ''}`;
  const kinds = evKinds(ev.all.filter(e => e.t !== 'unk'));
  const more = ev.all.filter(e => e.t === 'good' && e !== pro && e.name).map(e => e.name.toLowerCase());  // остальные выполненные условия одной строкой
  return `<ul class="qks dcd">
    <li class="qk qk-good">${mark('good')}<div>${pro ? one(pro) : '<b>Явных плюсов по запросу нет</b>'}${more.length ? `<small class="also">Ещё выполнено: ${esc(more.join(', '))}</small>` : ''}</div></li>
    ${con ? `<li class="qk qk-bad">${mark('bad')}<div><small class="for-you">для вас:</small>${one(con)}</div></li>` : unk ? `<li class="qk qk-unk">${mark('unk')}<div><small class="for-you">для вас, пока не знаем:</small>${one(unk)}</div></li>` : miss ? `<li class="qk qk-unk">${mark('unk')}<div><small class="for-you">для вас, пока не знаем:</small><b>${esc(miss.phrase)}</b></div></li>` : `<li class="qk qk-good">${mark('good')}<div><b>Минусов по вашим условиям не нашли</b></div></li>`}
  </ul>${kinds.length ? `<p class="evk" aria-label="Чем подтверждено">${kinds.map(k => `<span class="evk-${k}">${EV_LBL[k]}</span>`).join('')}</p>` : ''}`;
}
const quickHTML = e => `<li class="qk qk-${e.t}">${mark(e.t)}<div><b>${esc(e.name || cap(e.body).slice(0, 40))}</b>${e.name ? `<small>${numify(cap(e.body))}</small>` : ''}</div></li>`;
/* «Почему подходит вам» в карточке отеля: одна строка на условие, источник там же, где у всех фактов */
const evHTML = e => `<li class="ev ev-${e.t}">${mark(e.t)}<div><span class="ev-t">${e.name ? `<b>${esc(e.name)}.</b> ` : ''}${numify(cap(e.body))}</span>${e.warn ? '<span class="ev-s w">Источники расходятся</span>' : ''}</div>${cst(e.conf)}</li>`;

/* ================= состояние ================= */
/* организаторы просили 3-5 вариантов: сначала три сильнейших, остальное за «Показать ещё» */
const TOP_N = 3;
const state = {
  q: '', raw: null, data: null, rows: [], near: [], byId: new Map(), tab: 'match', shown: TOP_N, seq: 0,
  compare: [], sel: null, openId: null, hotelCache: new Map(), mapOn: false, constraintChars: new Set(), tuned: null,
  edited: false,  // условия правили плашками: ищем по разбору, а не по тексту
  agentIds: new Set(), llm: true,  // id отелей, которые назвал агент; есть ли ключ LLM
  answer: null, priorities: [],  // ответ с развилками; что гость назвал главным в «Что важнее?»
};
const relax = { query: '', parsed: null, drop: [], loosen: {} };  /* база для пересчёта без условий: разбор исходного запроса */
const slowM = /[?&]slow=(\d+)/.exec(location.search), slow = slowM ? slowM[1] : null, slowMs = slow > 1 ? slow * 1000 : 6000;

/* ================= шапка, герой ================= */
const hdr = $('#hdr');
new ResizeObserver(() => document.documentElement.style.setProperty('--hh', hdr.offsetHeight + 'px')).observe(hdr);

function setCompact() {
  const heroGone = (() => { const r = $('#hs').getBoundingClientRect(); return r.bottom < 0 })();
  hdr.classList.toggle('compact', document.body.classList.contains('has-results') || heroGone);
}
addEventListener('scroll', () => requestAnimationFrame(setCompact), { passive: true });

/* бегущий плейсхолдер */
(() => {
  const ph = $('#hsph1'), wrap = $('#hsph'), ta = $('#hsi'), field = ta.closest('.hs-field');
  let i = 0, t;
  const show = () => { ph.textContent = EXAMPLES[i % EXAMPLES.length].t };
  show();
  const next = () => {
    if (document.hidden || document.activeElement === ta && ta.value) return;
    wrap.classList.add('out');
    setTimeout(() => { i++; show(); wrap.classList.remove('out'); wrap.classList.add('in'); requestAnimationFrame(() => requestAnimationFrame(() => wrap.classList.remove('in'))) }, 220);
  };
  t = setInterval(next, reduced ? 6000 : 3600);
  const sync = () => field.classList.toggle('has', !!ta.value);
  ta.addEventListener('input', sync);
  ta.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#hs').requestSubmit() } });
  window.__phIndex = () => i % EXAMPLES.length;
})();

/* чипы-примеры и плитки */
$('#ex').innerHTML = EXAMPLES.map(x => `<button type="button" class="exc" data-q="${esc(x.t)}">${icoByName(x.i, x.e)}<span>${esc(cap(x.t))}</span></button>`).join('');
$('#tiles').innerHTML = TILES.map(x => `<button type="button" class="chk-i" data-q="${esc(x.q)}">${icoByName(x.i, x.e)}<span class="chk-t"><b>${esc(x.n)}</b><small>${esc(x.d)}</small></span><span class="chk-a">${I.arrow}</span></button>`).join('');
const SRC_CARDS = [
  { ring: 'OpenStreetMap  ·  24.07.2026', code: 'OSM', n: 'OpenStreetMap', d: 'здания, дороги, ж/д, пешие пути. Снимок 24.07.2026' },
  { ring: 'Copernicus GLO-30  ·  рельеф', code: 'DEM', n: 'Рельеф Copernicus', d: 'высоты: что закрывает море и закат, подъём на пути' },
  { ring: 'Open-Meteo  ·  2022-2025', code: 'ПОГ', n: 'Open-Meteo', d: 'море и погода в месяц поездки по данным 2022-2025' },
  { ring: 'Карточки и отзывы Островка  ·  2026', code: 'ОСТР', n: 'Карточки и отзывы Островка', d: 'удобства, категории номеров, что пишут гости' },
];
$('#srcs').innerHTML = SRC_CARDS.map((x, i) => `<div class="src" style="--r:${[-6, 4, -3, 7][i]}deg">${pm(x.ring, x.code, 'pmk-l', 92)}<span><b>${esc(x.n)}</b><small>${esc(x.d)}</small></span></div>`).join('');
const heroPM = n => { $('#pmHero').innerHTML = pm(`Сочи  ·  ${n} отелей  ·  2026`, 'СОЧИ', 'pmk-h', 150) };
heroPM(229);
document.addEventListener('click', e => {
  const h = e.target.closest('.js-here');  // «Искать то же здесь»: тот же запрос без названия чужого города
  if (h && state.data && state.data.off_region) {
    const stem = state.data.off_region.asked.toLowerCase().slice(0, Math.max(4, state.data.off_region.asked.length - 2));
    const q = state.q.replace(new RegExp('\\s*(?:во?\\s+)?' + stem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '[а-яё]*', 'i'), '').replace(/\s{2,}/g, ' ').trim();
    $('#hsi').value = q; runSearch(q); return;
  }
  const b = e.target.closest('[data-q]'); if (!b) return;
  vib(); $('#hsi').value = b.dataset.q; $('#hsi').closest('.hs-field').classList.add('has'); runSearch(b.dataset.q);
});

/* параллакс плавающих плиток (мышь) */
(() => {
  if (reduced || !matchMedia('(pointer:fine)').matches) return;
  const card = $('#pc'), fls = $$('.fl'); let raf;
  card.addEventListener('pointermove', e => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      const r = card.getBoundingClientRect(), dx = (e.clientX - r.left) / r.width - .5, dy = (e.clientY - r.top) / r.height - .5;
      fls.forEach(f => { const d = +f.dataset.depth || 20; f.style.transform = `translate(${(dx * d).toFixed(1)}px,${(dy * d).toFixed(1)}px)` });
    });
  });
  card.addEventListener('pointerleave', () => fls.forEach(f => f.style.transform = ''));
})();

/* форма: герой и шапка */
$('#hs').addEventListener('submit', e => { e.preventDefault(); runSearch($('#hsi').value) });
$('#hq').addEventListener('submit', e => { e.preventDefault(); $('#hqi').blur(); runSearch($('#hqi').value) });
$('#logo').addEventListener('click', e => { e.preventDefault(); goHome() });
$('#btnPlay').addEventListener('click', () => { vib(); window.Arcade && Arcade.open({ manual: true }) });
$('#btnMe').addEventListener('click', () => { vib(); window.Arcade && Arcade.open({ profile: true }) });

/* залипающий штамп отправки на мобильном: пока поле в фокусе или штамп ушёл за экран */
const dock = $('#dock');
function updateDock() {
  const mob = !matchMedia('(min-width:860px)').matches, has = document.body.classList.contains('has-results');
  if (!mob || has) { dock.hidden = true; return }
  const r = $('#hsgo').getBoundingClientRect(), out = r.bottom < 0 || r.top > innerHeight;
  dock.hidden = !(document.activeElement === $('#hsi') || out);
}
addEventListener('scroll', () => requestAnimationFrame(updateDock), { passive: true });
addEventListener('resize', updateDock);
$('#hsi').addEventListener('focus', updateDock); $('#hsi').addEventListener('blur', () => setTimeout(updateDock, 120));

function goHome() {
  state.seq++;
  closeHotelNow(); setMapOn(false);
  vt(() => { document.body.classList.remove('has-results'); $('#results').hidden = true; $('#mapfab').hidden = true; window.scrollTo(0, 0); setCompact() });
  history.replaceState(null, '', location.pathname + (slow ? '?slow=' + slow : ''));
}

/* ================= поиск ================= */
/* одни и те же названия стадий на карточке ожидания, в ответе агента и на ленте О!ркады (arcade.js читает window.WAIT_STAGES) */
const STAGES = window.WAIT_STAGES = ['Разбираем запрос', 'Проверяем вид и путь', 'Сверяем цифры', 'Пишем ответ'];
const WAIT_GAME = 'chemodanchiki-lcd';  // «Сыграть, пока ждём» открывает именно её
const PHASES = STAGES.slice(0, 3);  // быстрый поиск ответ не пишет
let phaseT = null;
function phasesHTML() {
  const li = PHASES.map((p, i) => `<li data-i="${i}" class="${i ? '' : 'now'}"><i class="mk"></i><span>${p}</span><span class="pms"></span></li>`).join('');
  return `<div class="transit" role="status" aria-label="Идёт поиск"><div class="tc u2" aria-hidden="true"><span class="stampbox"></span></div><div class="tc u1" aria-hidden="true"><span class="stampbox"></span></div><div class="tc top"><span class="stampbox" aria-hidden="true"><img src="/front/assets/icon-sea.webp" alt=""></span><h3>Ищем отели</h3><ol class="phases">${li}</ol><p>Каждый отель проверяем по картам, рельефу и карточке Островка.</p>${playOffer('Пока ищем, можно сыграть.')}</div></div>`;
}
function skeleton() { return phasesHTML() }
/* Игра только по желанию: кнопка появляется, если ожидание дольше 1,2 с. */
const playOffer = t => window.Arcade ? `<p class="play-offer" hidden><span>${t}</span><button type="button" class="btn btn-lime js-play" data-game="${WAIT_GAME}">Сыграть, пока ждём</button></p>` : '';
function revealPlay(get) { setTimeout(() => { const r = get(), o = r && r.isConnected && r.querySelector('.play-offer'); if (o) o.hidden = false }, 1200) }  // get(): узел ищем позже, vt() рисует асинхронно
document.addEventListener('click', e => { const b = e.target.closest('.js-play'); if (b) { vib(); Arcade.open({ manual: true, id: b.dataset.game || WAIT_GAME }) } });
function setPhase(k) {
  $$('#list .transit .phases li').forEach((el, i) => {
    el.classList.toggle('done', i < k); el.classList.toggle('now', i === k);
    const mk = el.querySelector('.mk'), slot = el.querySelector('.pms');
    if (i < k && !slot.firstChild) { mk.innerHTML = I.ok; slot.innerHTML = pm(PHASES[i], String(i + 1), 'pmk-p', 58) }
  });
}
function stopPhases() { clearInterval(phaseT); phaseT = null; document.body.classList.remove('waiting') }
function startPhases() {
  stopPhases(); let k = 0; document.body.classList.add('waiting');
  phaseT = setInterval(() => { if (!$('#list .transit')) { stopPhases(); return } k = Math.min(PHASES.length - 1, k + 1); setPhase(k) }, slow ? slowMs / 3 : 1100);
}
/* parsed: поиск по исправленному плашками разбору (текст запроса тот же, условия другие) */
async function runSearch(q, parsed) {
  q = (q || '').trim(); if (!q) { $('#hsi').focus(); return }
  const seq = ++state.seq; state.q = q; state.edited = !!parsed;
  if (!parsed) state.priorities = [];  // новый запрос словами: прежний выбор «что важнее» не переносим
  $('#hsi').value = q; $('#hqi').value = q; $('#hsi').closest('.hs-field').classList.add('has');
  history.replaceState(null, '', '?' + new URLSearchParams({ q, ...(slow ? { slow } : {}) }));
  if (!EMBED) { ag.seq++; if (ag.ctrl) ag.ctrl.abort(); ag.asked = ''; ag.busy = false; ag.minH = 0; agentTimer(false); agentPoll(false); agentRender() }  // прошлый ответ агента к новому поиску не относится
  closeHotelNow(); setMapOn(false);
  const first = !document.body.classList.contains('has-results');
  /* без view transition: её колбэк запускается на следующем кадре и может отработать уже после ответа API,
     затёрев выдачу заглушкой (так «Ищем отели» висело по 15-25 с, пока API отвечал за миллисекунды) */
  document.body.classList.add('has-results'); $('#results').hidden = false;
  if (!parsed) $('#und').innerHTML = '';  // при правке плашек запрос и плашки остаются на месте
  $('#tabs').innerHTML = ''; $('#tabsNote').textContent = '';
  $('#list').innerHTML = skeleton();
  $('#mapfab').hidden = true;
  if (!parsed) window.scrollTo(0, 0);
  setCompact(); updateDock();
  startPhases(); revealPlay(() => $('#list .transit'));
  try {
    const raw = parsed ? await j('/api/search/parsed', { query: q, parsed, limit: 300 }) : await j('/api/search', { query: q, limit: 300 });
    if (seq !== state.seq) return;
    state.raw = raw;
    if (!EMBED) {  // настоящий агент стартует, как только пришёл быстрый разбор; карточки его не ждут
      const ed = parsed && (parsed.constraints || []).map(c => c.label).filter(Boolean);  // условия поправлены плашками: агент получает их явно
      agentStart(ed && ed.length ? `${q}. Условия после правки: ${ed.join('; ')}` : q, raw);
    }
    relax.query = q; relax.parsed = raw.parsed; relax.drop = []; relax.loosen = {};
    let t = { s: raw, note: null, density: 'normal' };
    try { if (window.Arcade) t = await Arcade.tune(raw) } catch (e) { }
    if (seq !== state.seq) return;
    stopPhases();
    applyResults(t, first);
  } catch (err) {
    if (seq !== state.seq) return;
    stopPhases();
    if (window.Arcade && Arcade.isOpen()) Arcade.notify('Поиск не ответил, попробуйте ещё раз');
    $('#und').innerHTML = '';
    $('#list').innerHTML = `<div class="near"><div class="ico-big"><img src="/front/assets/empty-search.webp" alt=""></div><h3>Не удалось найти</h3><p>Сервер не ответил. Проверьте соединение и попробуйте ещё раз. Ваш текст сохранён.</p><button class="btn btn-blue" type="button" id="retry">Найти ещё раз</button></div>`;
    $('#retry').onclick = () => runSearch(q);
  }
}

function applyResults(t, animate) {
  const s = t.s;
  state.tuned = t;
  if (t.density === 'comfy' || t.density === 'dense') document.body.dataset.density = t.density; else delete document.body.dataset.density;
  state.data = s; state.dataSeq = state.seq;
  state.rows = s.results.map(r => ({ ...r }));
  state.near = (s.near_misses || []).map(r => ({ ...r, bucket: 'fail', near: true }));
  state.byId = new Map([...state.near, ...state.rows].map(r => [r.hotel.id, r]));
  state.constraintChars = new Set((s.parsed?.constraints || []).map(c => c.char));
  if (state.raw && !trackedRaw.has(state.raw)) { trackedRaw.add(state.raw); track('search', { chars: [...state.constraintChars], n: (s.results || []).length }) }
  if (state.rows.length) track('serp', { rows: state.rows.slice(0, 30).map(r => ({ id: String(r.hotel.id), bucket: r.bucket })), tuned: !!t.note });
  state.tab = s.counts.match ? 'match' : s.counts.maybe ? 'maybe' : state.near.length ? 'match' : 'fail';
  state.shown = TOP_N;
  $('#split').classList.toggle('empty', !!s.nothing_to_check);
  if (!String(state.answerKey || '').startsWith(state.seq + '|')) state.answer = null;  // ответ прошлого поиска не показываем
  renderUnderstood(); renderTabs(); renderList(true);
  loadAnswer(); agentRender();
  $('#mapfab').hidden = !!s.nothing_to_check; $('#mapfab').classList.toggle('away', !state.mapOn && scrollY < 240);
  ensureMap(); renderMap(true);
  document.title = `${cap(state.q)}: О!Правда об отеле`;
  const c = s.counts, n = (c.match || 0) + (c.maybe || 0);
  if (window.Arcade && Arcade.isOpen()) Arcade.notify(t.learned || (s.nothing_to_check ? 'В запросе пока нечего проверять' : c.match ? `Нашли ${c.match} ${plural(c.match, 'отель', 'отеля', 'отелей')}` : `Готово: ${n} ${plural(n, 'отель', 'отеля', 'отелей')} под вопросом`));
}

/* ================= ответ с развилками =================
   Бэкенд (app/answer.py) решает, есть ли среди подходящих настоящий компромисс по тому, что важно гостю.
   Есть — над списком «Наш ответ» и 1–3 «если важнее …». Нет — лучший отель просто встаёт первым с пометкой. */
/* Порядок state.rows не трогаем: подстройка под устройство (Sense) сравнивает его с ответом поиска, и любая
   перестановка здесь запускала бы её снова — выдача мигала между двумя первыми отелями. Лучшего поднимаем
   только при отрисовке (listRows), а ответ кэшируем по набору отелей, чтобы повторная отрисовка его не перезапрашивала. */
async function loadAnswer() {
  const seq = state.seq, s = state.data;
  const ids = state.rows.filter(r => r.bucket === 'match').map(r => r.hotel.id);
  if (s.nothing_to_check || ids.length < 2) { state.answer = null; state.answerKey = null; return }
  const key = [seq, JSON.stringify(s.parsed?.constraints || []), state.priorities.join(), [...ids].sort().join()].join('|');
  if (key === state.answerKey) return;  // тот же поиск, просто перерисовка
  state.answerKey = key; state.answer = null;
  let a;
  try { a = await j('/api/answer', { query: state.q, hotel_ids: ids.slice(0, 80), parsed: s.parsed, priorities: state.priorities, month: s.parsed?.month || null }) } catch (e) { return }
  if (seq !== state.seq || key !== state.answerKey || !a.winner) return;
  state.answer = a;
  if (state.tab === 'match') renderList(false);
}
/* строки текущей вкладки для показа: если компромисса нет, лучший по пунктам гостя идёт первым */
function listRows() {
  let rows = tabRows(); const a = state.answer;
  if (state.agentIds && state.agentIds.size) {  // отели, которые советует агент, идут первыми (в его порядке), остальные как были
    const ord = [...state.agentIds], pin = rows.filter(r => state.agentIds.has(String(r.hotel.id))).sort((x, y) => ord.indexOf(String(x.hotel.id)) - ord.indexOf(String(y.hotel.id)));
    if (pin.length) return [...pin, ...rows.filter(r => !pin.includes(r))];  // выбор агента важнее «лучшего по правилам»
  }
  if (state.tab !== 'match' || !a || a.show) return rows;
  const i = rows.findIndex(r => r.hotel.id === a.winner.id);
  return i > 0 ? [rows[i], ...rows.slice(0, i), ...rows.slice(i + 1)] : rows;
}
function answerHTML(a) {
  const w = a.winner, ids = [w.id, ...a.forks.map(f => f.hotel.id)];
  const pic = h => h.photo ? `<img src="${esc(h.photo)}" alt="" loading="lazy">` : '<span class="ans-noimg"></span>';
  const ttl = 'Развилки: если важнее другое';  // одно название всегда, с агентом и без
  const am = id => state.agentIds.has(String(id)) ? `<span class="agt-mark ans-agt">${I.star}Агент советует</span>` : '';
  return `<section class="ans" aria-label="${ttl}">
    <div class="ans-h"><span class="ans-k">${ttl}</span><small>из ${a.considered} ${plural(a.considered, 'подходящего', 'подходящих', 'подходящих')} отелей</small></div>
    <button type="button" class="ans-win js-ans" data-id="${esc(w.id)}">${pic(w)}<span class="ans-b"><b>${esc(w.name)}</b>${am(w.id)}${w.strengths.length ? `<span class="ans-why">${esc(cap(w.strengths.join(', ')))}</span>` : ''}<small>${esc(w.facts.join(' · '))}</small></span>${I.arrow}</button>
    <ul class="tr" style="--n:${a.forks.length}" aria-label="Другие варианты, если для вас важнее другое">${a.forks.map(f => `<li class="tr-c"><span class="tr-lab">${esc(f.title)}</span><button type="button" class="tr-card js-ans" data-id="${esc(f.hotel.id)}"><span class="tr-top">${pic(f.hotel)}<b>${esc(f.hotel.name)}</b></span>${am(f.hotel.id)}<span class="tr-g">↑ ${esc(cap(f.gain))}</span>${f.loss.map(l => `<span class="tr-l">↓ ${esc(l)}</span>`).join('')}</button></li>`).join('')}</ul>
    <div class="ans-acts"><button type="button" class="btn btn-line js-ans-cmp" data-ids="${esc(ids.join(','))}">${I.flip}<span>Сравнить эти ${ids.length}</span></button></div>
  </section>`;
}

/* Чего реестр не знает (parsed.missing): предлагаем собрать проверку прямо из выдачи, без отдельной вкладки. */
function learnHTML(m, i, total) {
  return `<div class="learn" data-i="${i}"><div class="learn-t"><b>Пока не умеем проверить: «${esc(m.phrase)}»</b><span>Можем проверить ${total === 1 ? 'отель' : `все ${total} ${plural(total, 'отель', 'отеля', 'отелей')}`} по карточкам и отзывам Островка и обновить выдачу.</span></div><button type="button" class="btn btn-blue js-learn">Проверить</button></div>`;
}
/* Оговорки к разбору: что сняли по просьбе гостя (parsed.ignored), другой город (off_region), на какую дату цены. */
function notesHTML(s) {
  const p = s.parsed || {}, n = [];
  // другой город объясняет пустое состояние в списке, здесь не повторяем
  if ((p.ignored || []).length) n.push(`Как вы просили, не учитываем: ${p.ignored.map(g => '«' + esc(g.phrase) + '»').join(', ')}.`);
  if (s.price_note) n.push(`Бюджет: ${esc(s.price_note)}.`);
  return n.map(x => `<div class="notice">${x}</div>`).join('');
}
const LEARN_PH = ['Собираем проверку', 'Пробуем на 5 отелях', 'Проверяем все отели'];
$('#und').addEventListener('click', e => {
  const b = e.target.closest('.js-learn'); if (!b) return;
  const box = b.closest('.learn'), m = (state.data?.parsed?.missing || [])[+box.dataset.i];
  if (m) { vib(); learn(box, m) }
});
async function learn(box, m) {
  const seq = state.seq;
  box.classList.add('busy');
  box.innerHTML = `<div class="learn-t" role="status"><b>Проверяем «${esc(m.phrase)}»</b><ol class="learn-ph">${LEARN_PH.map((x, i) => `<li class="${i ? '' : 'now'}">${x}</li>`).join('')}</ol>${playOffer('Это может занять время. Пока считаем, можно сыграть.')}</div>`;
  revealPlay(() => box);
  let k = 0;
  const tick = setInterval(() => { k = Math.min(LEARN_PH.length - 1, k + 1); box.querySelectorAll('.learn-ph li').forEach((li, i) => { li.classList.toggle('done', i < k); li.classList.toggle('now', i === k) }) }, slow ? (slowMs + 2000) / 3 : 1400);
  const fail = msg => { clearInterval(tick); if (window.Arcade && Arcade.isOpen()) Arcade.notify(`Не получилось проверить «${m.phrase}»`); box.classList.remove('busy'); box.innerHTML = `<div class="learn-t"><b>Не получилось проверить «${esc(m.phrase)}»</b><span>${esc(msg)}</span></div>` };
  try {
    const r = await j('/api/characteristics', { description: m.proposal });
    if (!r.ok) return fail('Сформулируйте иначе или спросите про это отель напрямую.');
    await loadNames();
    const raw = await j('/api/search', { query: state.q, limit: 300 });
    clearInterval(tick);
    if (seq !== state.seq) return;
    state.raw = raw;
    let t = { s: raw, note: null, density: 'normal' };
    try { if (window.Arcade) t = await Arcade.tune(raw) } catch (e) { }
    const cv = r.coverage || {};
    t.learned = `«${cap(m.phrase)}» проверили: есть в ${cv.key_true} из ${cv.total} отелей`;
    applyResults(t, false);
    if (!(window.Arcade && Arcade.isOpen())) toast(t.learned);
  } catch (e) { fail('Сервер не ответил. Попробуйте ещё раз.') }
}

/* Плашки — это условия, в которые мы перевели запрос. Их можно убрать (×), сделать желательными
   (клик по плашке) или добавить новые (+ условие). Тогда ищем по исправленному разбору. */
/* Готовые условия задаём полем реестра напрямую: разбор правилами путает «ночью» в разных фразах. */
const COND = {
  sea: { t: 'вид на море', i: 'sea_view', c: ['sea_view', 'has'], n: 'Вид на море', d: 'Море видно из окна номера' },
  sunset: { t: 'закат из окна', i: 'sunset', c: ['sunset', 'visible'], n: 'Закат из окна', d: 'Окна смотрят на закат' },
  quiet: { t: 'тихо ночью', i: 'night_quiet', c: ['night_quiet', 'quiet'], n: 'Тишина ночью', d: 'Под окнами нет шумной дороги и рельсов' },
  beach: { t: 'пляж до 10 минут пешком', i: 'beach_walk', c: ['beach_walk', 'minutes_there', '<=', 10], n: 'Ближе к морю', d: 'До пляжа не больше 10 минут пешком' },
  kids: { t: 'детская площадка рядом', i: 'kids', c: ['kids', 'playground_near'], n: 'Площадка для детей', d: 'Детская площадка в паре минут' },
  pets: { t: 'с собакой', i: 'pets', c: ['pets', 'allowed'], n: 'С питомцем', d: 'Можно с собакой или кошкой' },
  stairs: { t: 'без лестниц', i: 'accessibility', c: ['accessibility', 'easy'], n: 'Без лестниц', d: 'Лифт и вход без ступеней' },
  blackout: { t: 'плотные шторы', i: 'blackout', c: ['blackout', 'has'], n: 'Плотные шторы', d: 'Чтобы выспаться утром' },
  car: { t: 'парковка', i: 'car', c: ['car', 'parking'], n: 'Парковка', d: 'Есть где оставить машину' },
  wifi: { t: 'хороший интернет', i: 'wifi', c: ['wifi', 'good'], n: 'Интернет для работы', d: 'Стабильный Wi-Fi и рабочий стол' },
  checkin: { t: 'заселение ночью', i: 'night_checkin', c: ['night_checkin', 'allowed'], n: 'Заселение ночью', d: 'Заселят, даже если приедете в 2 часа ночи' },
  food: { t: 'поесть рядом', i: 'food_near', c: ['food_near', 'plenty'], n: 'Кафе рядом', d: 'Есть где поесть в шаге от отеля' },
  breakfast: { t: 'завтрак', i: 'breakfast', c: ['breakfast', 'has'], n: 'Завтрак в отеле', d: 'Не надо искать, где поесть утром' },
  allinc: { t: 'пансион', i: 'meal_plan', c: ['meal_plan', 'any_board'], n: 'Пансион или «всё включено»', d: 'Еда включена, думать о ней не надо' },
  pool: { t: 'бассейн', i: 'pool', c: ['pool', 'has'], n: 'Бассейн', d: 'Можно плавать, даже когда море холодное' },
  privbeach: { t: 'свой пляж', i: 'private_beach', c: ['private_beach', 'has'], n: 'Свой пляж', d: 'Лежаки отеля, без толпы городского пляжа' },
  spa: { t: 'спа', i: 'spa', c: ['spa', 'has'], n: 'СПА и сауна', d: 'Сауна, хаммам или массаж в отеле' },
  adults: { t: 'для взрослых', i: 'adults_only', c: ['adults_only', 'adult'], n: 'Тихо, без детей', d: 'Семьи с детьми здесь почти не живут' },
  familyk: { t: 'для семей', i: 'family', c: ['family', 'friendly'], n: 'Удобно с детьми', d: 'Семейные номера, детская комната' },
  kitchen: { t: 'кухня в номере', i: 'kitchen', c: ['kitchen', 'has'], n: 'Кухня в номере', d: 'Можно готовить самому' },
  balcony: { t: 'балкон', i: 'balcony', c: ['balcony', 'has'], n: 'Балкон или терраса', d: 'Утренний кофе на свежем воздухе' },
  transfer: { t: 'трансфер', i: 'transfer', c: ['transfer', 'has'], n: 'Трансфер из аэропорта', d: 'Встретят и довезут до отеля' },
};
const ADD = ['sea', 'sunset', 'quiet', 'beach', 'breakfast', 'allinc', 'pool', 'privbeach', 'spa', 'familyk', 'adults', 'kids', 'pets',
  'balcony', 'kitchen', 'stairs', 'blackout', 'car', 'transfer', 'wifi', 'checkin', 'food'];
const mkCond = (a, must = true) => ({ char: a.c[0], field: a.c[1], op: a.c[2] || '==', value: a.c.length > 3 ? a.c[3] : true, must, phrase: a.t });
const editParsed = () => JSON.parse(JSON.stringify(state.data?.parsed || {}));
function chip(i, key, inner, cls = '', title = '') {
  return `<span class="qc ${cls}" style="--i:${i}" data-k="${key}" ${title ? `title="${esc(title)}"` : ''}>${inner}<button type="button" class="qc-x" aria-label="Убрать условие">${I.no}</button></span>`;
}
function renderUnderstood() {
  const s = state.data, p = s.parsed || {}, cs = p.constraints || [], base = p.base || {}, mn = p.month;
  const chips = [];
  cs.forEach((c, i) => {
    const soft = c.must === false;
    const inner = `${CH[c.char] ? ico(c.char) : ''}<button type="button" class="qc-t">${esc(human(c, mn))}${soft ? ' <small>желательно</small>' : ''}</button>`;
    chips.push(chip(chips.length, 'c' + i, inner, `${soft ? 'soft' : ''} ${CH[c.char] ? '' : 'plain'}`, soft ? 'Желательно. Нажмите, чтобы сделать обязательным' : 'Обязательно. Нажмите, чтобы сделать желательным'));
  });
  if (mn) chips.push(chip(chips.length, 'month', `<span class="qc-t">${esc(cap(s.month || ''))}</span>`, 'plain'));
  if (base.max_price) chips.push(chip(chips.length, 'max_price', `<span class="qc-t">До ${esc(money(base.max_price))}</span>`, 'plain'));
  if (base.min_stars) chips.push(chip(chips.length, 'min_stars', `<span class="qc-t">От ${base.min_stars} <span class="stars-i">${I.star}</span></span>`, 'plain'));
  if (base.min_rating) chips.push(chip(chips.length, 'min_rating', `<span class="qc-t">Рейтинг от ${base.min_rating}</span>`, 'plain'));
  const have = new Set(cs.map(c => c.char));
  const opts = ADD.filter(k => !have.has(COND[k].c[0])).map(k => `<button type="button" class="add-o" data-add="${k}">${ico(COND[k].i)}<span>${esc(COND[k].n)}</span></button>`).join('');
  chips.push(`<span class="qc-addw"><button type="button" class="qc qc-add" id="qcAdd" aria-expanded="false" style="--i:${chips.length}">${I.plus}<span>Добавить условие</span></button>
    <div class="add-pop" id="addPop" hidden><div class="add-l">${opts}</div><form class="add-f" id="addF"><input id="addI" placeholder="Своё условие словами" aria-label="Своё условие"><button type="submit" class="btn btn-blue">Добавить</button></form></div></span>`);
  chips.push(`<button type="button" class="qc qc-duel js-duel" style="--i:${chips.length + 1}">${I.flip}<span>Что важнее? Уточнить за 30 секунд</span></button>`);

  const nothing = !!s.nothing_to_check;
  const total = nothing ? (s.counts.unchecked || 0) : (s.counts.match || 0) + (s.counts.maybe || 0) + (s.counts.fail || 0);
  const hasMissing = (p.missing || []).length > 0;
  const emptyMsg = nothing
    ? (hasMissing || s.off_region ? '' : `<div class="notice">В запросе нет условий, которые мы умеем проверять. Добавьте условие кнопкой выше или напишите про вид, закат, пляж, тишину, бассейн, завтрак, детей или питомца.</div>`) : '';
  const lead = nothing ? `<div class="und-l"><span>Проверить пока нечего</span></div>`
    : `<div class="und-l"><span>Проверяем для вас:</span><span>${total} ${plural(total, 'отель', 'отеля', 'отелей')}</span></div>`;
  $('#und').innerHTML = `<div class="qbox" id="qbox"><span class="qbox-l">Ваш запрос</span><div class="qbox-v"><q>${esc(state.q)}</q>${state.edited ? '<small>условия изменены вручную</small>' : ''}</div><button type="button" class="btn btn-line qbox-e" id="qEdit">Изменить</button></div>
    ${lead}${chips.join('')}
    <p class="und-h">Нажмите на условие, чтобы сделать его желательным. Крестик убирает условие.</p>${notesHTML(s)}${emptyMsg}${relaxHTML(s)}${(p.missing || []).map((m, i) => learnHTML(m, i, total)).join('')}`;
}
function editQuery() {
  const box = $('#qbox'); if (!box || box.classList.contains('on')) return;
  box.classList.add('on');
  box.innerHTML = `<span class="qbox-l">Ваш запрос</span><form class="qbox-f" id="qboxF"><textarea id="qboxI" rows="2" aria-label="Запрос">${esc(state.q)}</textarea><button type="submit" class="btn btn-blue">Найти</button><button type="button" class="btn btn-line" id="qboxX">Отмена</button></form>`;
  const ta = $('#qboxI'); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
  ta.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#qboxF').requestSubmit() } if (e.key === 'Escape') renderUnderstood() });
}
function addKnown(k) {
  const p = editParsed(), a = COND[k];
  if (!(p.constraints || []).some(c => c.char === a.c[0] && c.field === a.c[1])) p.constraints = [...(p.constraints || []), mkCond(a)];
  runSearch(state.q, p);
}
async function addCondition(text) {
  text = (text || '').trim(); if (!text) return;
  let r = null; try { r = await j('/api/parse/rules', { text }) } catch (e) { }
  const p = editParsed(), have = new Set((p.constraints || []).map(c => c.char + '.' + c.field));
  const add = (r?.constraints || []).filter(c => !have.has(c.char + '.' + c.field));
  const newMonth = r?.month && r.month !== p.month;
  if (!add.length && !newMonth) {
    // правила такого условия не знают: дописываем его в запрос, поиск предложит собрать проверку
    runSearch(state.q + ', ' + text); return;
  }
  if (newMonth) p.month = r.month;
  p.constraints = [...(p.constraints || []), ...add];
  runSearch(state.q, p);
}
$('#und').addEventListener('click', e => {
  if (e.target.closest('#qEdit')) { vib(); editQuery(); return }
  if (e.target.closest('#qboxX')) { renderUnderstood(); return }
  if (e.target.closest('#qcAdd')) {
    const pop = $('#addPop'), on = pop.hidden; pop.hidden = !on; $('#qcAdd').setAttribute('aria-expanded', on);
    if (on) setTimeout(() => $('#addI')?.focus({ preventScroll: true }), 30); return;
  }
  const o = e.target.closest('[data-add]'); if (o) { vib(); addKnown(o.dataset.add); return }
  if (e.target.closest('.js-duel')) { vib(); openDuel((p, keys) => { state.priorities = keys.map(k => COND[k].c[0]); runSearch(state.q, p) }); return }
  const qc = e.target.closest('.qc[data-k]'); if (!qc) return;
  const k = qc.dataset.k, p = editParsed();
  if (e.target.closest('.qc-x')) {
    vib();
    if (k[0] === 'c') p.constraints.splice(+k.slice(1), 1);
    else if (k === 'month') p.month = null;
    else p.base[k] = null;
    runSearch(state.q, p); return;
  }
  if (k[0] === 'c' && e.target.closest('.qc-t')) {
    vib(); const c = p.constraints[+k.slice(1)]; c.must = c.must === false;
    runSearch(state.q, p);
  }
});
$('#und').addEventListener('submit', e => {
  e.preventDefault();
  if (e.target.id === 'qboxF') { const v = $('#qboxI').value.trim(); if (v) runSearch(v); return }
  if (e.target.id === 'addF') addCondition($('#addI').value);
});
document.addEventListener('click', e => { const pop = $('#addPop'); if (pop && !pop.hidden && !e.target.closest('.qc-addw')) { pop.hidden = true; $('#qcAdd')?.setAttribute('aria-expanded', 'false') } });

/* Ослабление условий: чипы «Без «…»: +N отелей» и возврат убранного. Пересчёт идёт через /api/relax с исходным разбором. */
function relaxList(s) { return (s.relaxations || []).filter(r => r.gain > 0).slice(0, 6) }
/* человеческая подпись условия, как в чипах запроса; два моря (вид и вид с тихой стороны) сливаем в одно */
function conLabel(idx) {
  const cs = (relax.parsed && relax.parsed.constraints) || [], mn = relax.parsed && relax.parsed.month;
  const c = cs.find(x => x.idx === idx) || cs[idx];
  return c ? human(c, mn) : null;
}
/* смягчённое условие словами: «Пляж до 30 мин пешком» (порог из ответа API, подпись как в чипах запроса) */
function loosLabel(l) {
  const cs = (relax.parsed && relax.parsed.constraints) || [], c = cs.find(x => x.idx === l.idx) || cs[l.idx];
  return c ? human({ ...c, value: l.to }, relax.parsed.month) : l.label;
}
function relaxLabels(r) {
  const cs = (relax.parsed && relax.parsed.constraints) || [];
  const list = r.idxs.map(i => cs.find(x => x.idx === i) || cs[i]).filter(Boolean);
  const base = c => c.char.replace(/_quiet$/, '');
  const uniq = [];
  list.forEach(c => { const k = base(c), at = uniq.findIndex(u => base(u) === k); if (at < 0) uniq.push(c); else if (/_quiet$/.test(uniq[at].char)) uniq[at] = c });
  const mn = relax.parsed && relax.parsed.month;
  const labs = uniq.map(c => human(c, mn));
  return labs.length ? labs.join(' и ') : (r.drop || r.text);
}
function relaxHTML(s) {
  const off = s.dropped || [], lo = s.loosened || [], rl = relaxList(s);
  if (!off.length && !lo.length && !rl.length) return '';
  const undo = off.map(d => `<button type="button" class="qc ghost rx-undo" data-un="${esc(d.idx)}" title="Вернуть условие">Без «${esc(conLabel(d.idx) || d.label)}»<i aria-hidden="true">✕</i></button>`).join('')
    + lo.map(l => `<button type="button" class="qc ghost rx-undo" data-unl="${esc(l.idx)}" title="Вернуть порог">${esc(loosLabel(l))}, было ${esc(String(l.from).replace('.', ','))}<i aria-hidden="true">✕</i></button>`).join('');
  const loosened = r => {   /* «Пляж до 6 мин пешком: +4 отеля»: подпись условия уже с новым порогом */
    const cs = (relax.parsed && relax.parsed.constraints) || [], c = cs.find(x => x.idx === r.idxs[0]) || cs[r.idxs[0]];
    return c ? human({ ...c, value: r.to }, relax.parsed.month) : relaxLabels(r);
  };
  const chips = rl.map((r, i) => r.kind === 'loosen'
    ? `<button type="button" class="qc rx" data-rx="${i}" title="${esc(r.text || '')}">${esc(loosened(r))}: <b>+${r.gain} ${plural(r.gain, 'отель', 'отеля', 'отелей')}</b></button>`
    : `<button type="button" class="qc rx" data-rx="${i}" title="${esc(r.text || '')}">Без «${esc(relaxLabels(r))}»: <b>+${r.gain} ${plural(r.gain, 'отель', 'отеля', 'отелей')}</b></button>`).join('');
  return `<div class="rlx" id="rlx">${rl.length ? `<span class="rlx-l">Подходящих мало. Уберите условие, и вариантов станет больше:</span>` : ''}${chips}${undo}</div>`;
}
async function relaxRun() {
  const seq = ++state.seq, box = $('#rlx'); box && box.classList.add('busy');
  try {
    const raw = await j('/api/relax', { query: relax.query, parsed: relax.parsed, drop: relax.drop, loosen: relax.loosen, limit: 300 });
    if (seq !== state.seq) return;
    state.raw = raw;
    let t = { s: raw, note: null, density: 'normal' };
    try { if (window.Arcade) t = await Arcade.tune(raw) } catch (e) { }
    if (seq !== state.seq) return;
    closeHotelNow(); applyResults(t, false);
  } catch (e) { if (seq === state.seq) { box && box.classList.remove('busy'); toast('Не удалось пересчитать, попробуйте ещё раз') } }
}
$('#und').addEventListener('click', e => {
  const b = e.target.closest('[data-rx],[data-un],[data-unl]'); if (!b || !state.data) return;
  vib();
  if (b.dataset.rx != null) {
    const r = relaxList(state.data)[+b.dataset.rx]; if (!r) return;
    if (r.kind === 'loosen') relax.loosen = { ...relax.loosen, [r.idxs[0]]: r.to };
    else r.idxs.forEach(i => relax.drop.includes(i) || relax.drop.push(i));
  } else if (b.dataset.un != null) relax.drop = relax.drop.filter(i => String(i) !== b.dataset.un);
  else { const l = { ...relax.loosen }; delete l[b.dataset.unl]; relax.loosen = l }
  relaxRun();
});

const TAB_NOTE = {
  match: 'Все ваши условия выполнены.',
  maybe: 'Часть условий пока не подтверждена. Мы спрашиваем отели.',
  fail: 'Хотя бы одно обязательное условие не выполняется.',
};
function renderTabs() {
  const c = state.data.counts;
  if (state.data.nothing_to_check) { $('#tabs').innerHTML = ''; $('#tabsNote').innerHTML = ''; $('#tabsbar').hidden = true; return }
  $('#tabsbar').hidden = false;
  const defs = [['match', 'Подходит'], ['maybe', 'Возможно'], ['fail', 'Не подходит']];
  $('#tabs').innerHTML = defs.map(([b, l]) => `<button class="tab tab-${b}" role="tab" data-b="${b}" aria-selected="${state.tab === b}" aria-controls="list"><b>${c[b] || 0}</b><span>${l}</span></button>`).join('');
  const tn = $('#tabsNote'), t = state.tuned;
  const dr = state.data.dropped || [], lz = state.data.loosened || [];
  const relaxed = dr.length || lz.length ? [
    dr.length ? `Подходят без ${dr.length > 1 ? 'условий' : 'условия'} ${dr.map(d => `«${conLabel(d.idx) || d.label}»`).join(' и ')}.` : '',
    lz.length ? `Подходят, если смягчить ${lz.map(l => `«${loosLabel(l)}»`).join(' и ')}.` : '',
    `Вернуть ${dr.length + lz.length > 1 ? 'их' : 'его'} можно кнопкой выше.`].filter(Boolean).join(' ') : null;
  const open = state.data.all_checked === false || (state.data.parsed && (state.data.parsed.missing || []).length);
  const mNote = open ? 'Всё, что мы умеем проверять, выполнено. Остального пока не знаем, подробности выше.' : TAB_NOTE.match;  // не обещаем «всё выполнено», если часть запроса не проверена
  tn.innerHTML = `<span class="tn-t">${state.tab === 'match' && !c.match ? 'Ни один отель не выполняет всё сразу.' : state.tab === 'match' && relaxed ? esc(relaxed) : state.tab === 'match' ? mNote : TAB_NOTE[state.tab]}</span>`;
  const why = t && t.note ? t.note.replace(/^Подобрано под ваш темп:?\s*/, '') : '';  // заголовок уже на штампе, не повторяем
  if (t && t.note) tn.innerHTML += `<div class="tune"><span class="rub">${esc(t.rub || 'Подобрано под ваш темп')}</span><span class="why">${esc(cap(why))}</span><button type="button" id="undoTune">Отменить и стереть данные</button><button type="button" id="whyTune" class="lnk">Почему так</button></div>`;
  const w = $('#whyTune');
  if (w) w.onclick = () => {
    const ts = t && t.taste;
    if (ts && ts.applied) toast(ts.mode === 'demo' ? 'Демо: порядок внутри вкладок сдвинут по выбору синтетических посетителей. Факты и цены те же.'
      : ts.w_own >= 0.5 ? 'Порядок внутри вкладок сдвинут к отелям, похожим на те, что вы уже открывали. Факты и цены те же.'
      : `Порядок внутри вкладок сдвинут к отелям, которые открывали посетители с похожим устройством, регионом и временем поиска (их ${ts.cluster_size}). Факты и цены те же.`);
    else if (window.Arcade) Arcade.open({ profile: true });
  };
  const u = $('#undoTune'); if (u) u.onclick = () => { track('undo', {}); if (window.Sense && Sense.optOut) { Sense.optOut(true); toast('Подстройка отключена, данные о вас стёрты. Порядок вернётся к исходному.') } };
}
$('#tabs').addEventListener('click', e => {
  const b = e.target.closest('.tab'); if (!b || b.dataset.b === state.tab) return;
  vib(); state.tab = b.dataset.b; state.shown = TOP_N;
  vt(() => { renderTabs(); renderList(true); renderMap(true); window.scrollTo({ top: Math.min(scrollY, $('#tabsbar').offsetTop - 80), behavior: 'instant' in window ? 'instant' : 'auto' }) });
});

function priceHTML(h) {
  return h.price_nov1 ? `<div class="price"><b>${money(h.price_nov1)}</b><small>цена на 1 ноября</small></div>` : `<div class="price na"><b>Цены на даты нет</b></div>`;
}
const PLATES = ['sea', 'sunset', 'beach', 'quiet'];
const BKT = { match: 'Подходит', maybe: 'Возможно', fail: 'Не подходит' };
function cardHTML(r, i, top) {
  const h = r.hotel, ev = evList(r), q3 = ev.all.slice(0, 3), stars = h.stars || 0;
  const inCmp = state.compare.includes(h.id), plate = PLATES[(parseInt(h.id, 10) || 0) % 4];
  const bk = r.near ? 'near' : r.bucket, bl = r.near ? 'Почти подходит' : BKT[r.bucket];
  const lines = ev.all.map((e, k) => lineHTML(e, k)).join('');
  return `<article class="card b-${bk}" data-id="${esc(h.id)}" style="--i:${i}" aria-label="${esc(h.name)}">
  <div class="flip">
    <div class="face front">
      <div class="ph ${h.photo ? '' : 'noimg'}" style="--pl:url(/front/assets/icon-${plate}.webp)">${h.photo ? `<img src="${esc(h.photo)}" alt="" loading="${i < 3 ? 'eager' : 'lazy'}" decoding="async">` : ''}
        <span class="bkt bkt-${bk}">${bl}</span>
        <button class="cmp" type="button" aria-pressed="${inCmp}" aria-label="${inCmp ? 'Убрать из сравнения' : 'Добавить в сравнение'}">${I.plus}</button>
      </div>
      <div class="cb">
        <div class="t1"><h3>${esc(h.name)}</h3></div>
        ${state.agentIds.has(String(h.id)) ? `<p class="best-mark agt-mark">${I.star}<span>Агент советует</span></p>` : ''}
        ${state.answer && !state.answer.show && state.answer.winner.id === h.id && r.bucket === 'match' ? `<p class="best-mark">${I.star}<span>Лучший по вашим пунктам${state.answer.winner.strengths.length ? ': ' + esc(state.answer.winner.strengths.join(', ')) : ''}</span></p>` : ''}
        <div class="meta">${stars ? `<span class="stars" role="img" aria-label="${stars} ${plural(stars, 'звезда', 'звезды', 'звёзд')}">${Array.from({ length: stars }, () => I.star).join('')}</span>` : ''}${h.rating ? `<span class="rate">${h.rating.toFixed(1)}${h.reviews ? `<small>${h.reviews} ${plural(h.reviews, 'отзыв', 'отзыва', 'отзывов')}</small>` : ''}</span>` : ''}</div>
        <p class="addr">${KIND[h.kind] ? `<span class="k">${KIND[h.kind]}</span>` : ''}<span>${esc(h.address || '')}</span></p>
        ${top ? decideHTML(ev) : `<ul class="qks">${q3.map(quickHTML).join('')}</ul>`}
        <div class="cf">${priceHTML(h)}<div class="acts"><button type="button" class="btn btn-line js-flip" aria-label="Что проверили: ${esc(h.name)}">${I.flip}<span>Что проверили</span></button><button type="button" class="btn btn-blue js-open">Подробнее</button></div></div>
      </div>
    </div>
    <div class="face back" inert aria-hidden="true">
      <div class="bh"><div><h4>${esc(h.name)}</h4><p>Что мы проверили для вашего запроса</p></div><span class="stampbox sb-${bk}">${bl}</span></div>
      <ul class="lns">${lines || '<li class="ln-empty">В запросе нет условий, которые мы умеем проверять.</li>'}</ul>
      <div class="bf"><button type="button" class="btn btn-line js-flip" aria-label="Назад к фото">${I.flip}<span>Назад</span></button><button type="button" class="btn btn-blue js-open">Подробнее</button></div>
    </div>
  </div>
</article>`;
}
function flipCard(card, viaBtn) {
  const on = card.classList.toggle('flipped');
  const f = card.querySelector('.front'), b = card.querySelector('.back');
  f.inert = on; b.inert = !on; f.setAttribute('aria-hidden', on); b.setAttribute('aria-hidden', !on);
  vib(6);
  if (viaBtn) setTimeout(() => (on ? b : f).querySelector('.js-flip')?.focus({ preventScroll: true }), 60);
}

/* сдача из стопки: первые карточки стартуют друг на друге с наклоном ±2° */
function dealStack(list) {
  const cards = $$('.card', list).slice(0, 5); if (cards.length < 2) return;
  const y0 = cards[0].offsetTop;
  cards.forEach((c, i) => {
    const dy = Math.min(c.offsetTop - y0, 440);
    c.style.setProperty('--sy', (-dy + i * 6) + 'px');
    c.style.setProperty('--tilt', (i % 2 ? 2 : -2) + 'deg');
    c.style.zIndex = 10 - i; setTimeout(() => { c.style.zIndex = '' }, 900 + i * 40);
  });
}
function tabRows() { return state.rows.filter(r => r.bucket === state.tab) }
function renderList(reset) {
  const list = $('#list'), rows = listRows(), c = state.data.counts;
  let html = '';
  if (state.data.off_region) {
    html += `<div class="near"><div class="ico-big"><img src="/front/assets/empty-search.webp" alt=""></div><h3>Это не ${esc(state.data.off_region.asked)}</h3><p>${esc(state.data.message || '')}</p>${state.data.parsed && (state.data.parsed.constraints || []).length ? `<div class="near-ex"><button type="button" class="btn btn-blue js-here">Искать то же в регионе «${esc(state.data.off_region.active)}»</button></div>` : ''}</div>`;
  } else if (state.data.nothing_to_check) {
    html += `<div class="near"><div class="ico-big"><img src="/front/assets/empty-search.webp" alt=""></div><h3>Пока нечего проверять</h3><p>В запросе нет условий, которые мы умеем проверять по карте, рельефу и карточкам, поэтому отели не разложены по подходящим. Спросите про вид, закат, пляж, тишину, детей или питомца.</p><div class="near-ex">${EXAMPLES.slice(0, 3).map(x => `<button type="button" class="exc" data-q="${esc(x.t)}">${icoByName(x.i, x.e)}<span>${esc(cap(x.t))}</span></button>`).join('')}</div></div>`;
  } else if (state.tab === 'match' && !c.match) {
    html += `<div class="near"><div class="ico-big"><img src="/front/assets/empty-search.webp" alt=""></div><h3>Точного совпадения нет</h3><p>Ни один отель не выполняет все условия сразу. ${state.near.length ? 'Вот ближайшие и то, что именно не сходится.' : 'Попробуйте убрать одно условие.'}</p></div>`;
    if (state.near.length) { html += `<h3 class="sub-h">Ближе всего к запросу</h3>` + state.near.map((r, i) => cardHTML(r, i, i < TOP_N)).join('') }
  } else if (!rows.length) {
    html += `<div class="near"><div class="ico-big"><img src="/front/assets/empty-search.webp" alt=""></div><h3>Здесь пусто</h3><p>В этой корзине нет отелей.</p></div>`;
  } else {
    const n = Math.min(state.shown, rows.length), a = state.answer;
    if (a && a.show && state.tab === 'match') html += answerHTML(a) + `<h3 class="sub-h">Все подходящие: ${rows.length}</h3>`;
    html += rows.slice(0, n).map((r, i) => cardHTML(r, i % 12, i < TOP_N)).join('');
    if (n < rows.length) html += `<button type="button" class="btn btn-line more-btn" id="moreBtn">Показать ещё ${Math.min(12, rows.length - n)} из ${rows.length - n}</button>`;
  }
  list.innerHTML = html;
  recheckImgs();
  if (reset) dealStack(list);
}
$('#list').addEventListener('click', e => {
  const ab = e.target.closest('.js-ans'); if (ab) { vib(); openHotel(ab.dataset.id); return }
  const ac = e.target.closest('.js-ans-cmp');
  if (ac) { vib(); state.compare = ac.dataset.ids.split(',').slice(0, 4); syncCompareUI(); openCompare(); return }
  const card = e.target.closest('.card'); if (!card) { if (e.target.closest('#moreBtn')) { vib(4); state.shown += 12; renderList(); renderMap(true) } return }
  if (e.target.closest('.cmp')) { e.stopPropagation(); toggleCompare(card.dataset.id); return }
  if (e.target.closest('.js-open')) { vib(); openHotel(card.dataset.id, card); return }
  const sb = e.target.closest('.js-src');
  if (sb) { vib(4); const on = sb.closest('.ln').classList.toggle('src-on'); sb.setAttribute('aria-expanded', on); sb.textContent = on ? 'Скрыть' : 'Источник'; return }
  if (e.target.closest('.js-flip')) { flipCard(card, true); return }
  if (e.target.closest('a,button')) return;
  flipCard(card, false);
});
$('#list').addEventListener('pointerover', e => { if (e.pointerType === 'touch' || !matchMedia('(hover:hover)').matches) return; const c = e.target.closest('.card'); if (c) { c.classList.add('hl'); pinState(c.dataset.id, true) } });
$('#list').addEventListener('pointerout', e => { if (e.pointerType === 'touch' || !matchMedia('(hover:hover)').matches) return; const c = e.target.closest('.card'); if (c && !c.contains(e.relatedTarget)) { c.classList.remove('hl'); pinState(c.dataset.id, false) } });

/* ================= карта ================= */
const map = { m: null, layer: null, markers: new Map(), hover: null };
const PIN = '<div class="pin"><i></i><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.500a5.600 5.600 0 0 0-5.600 5.600c0 4.300 5.600 10.400 5.600 10.400s5.600-6.100 5.600-10.400A5.600 5.600 0 0 0 12 3.500zm0 7.800a2.200 2.200 0 1 1 0-4.400 2.200 2.200 0 0 1 0 4.400z"/></svg></div>';
function ensureMap() {
  if (map.m || !window.L) return;
  map.m = L.map('map', { zoomControl: false, zoomSnap: .5, scrollWheelZoom: true }).setView([43.585, 39.72], 13);
  L.control.zoom({ position: 'bottomright' }).addTo(map.m);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' }).addTo(map.m);
  map.layer = L.layerGroup().addTo(map.m);
}
function pinEl(id) { return map.markers.get(id)?.getElement()?.querySelector('.pin') }
function pinState(id, on) {
  if (!id) return;
  if (on) { if (map.hover && map.hover !== id) pinState(map.hover, false); map.hover = id }
  else if (map.hover === id) map.hover = null;
  const m = map.markers.get(id); if (!m) return;
  const sel = on || state.sel === id;
  pinEl(id)?.classList.toggle('sel', sel); m.setZIndexOffset(sel ? 1000 : 0);
}
function renderMap(fit) {
  if (!map.m) return;
  map.layer.clearLayers(); map.markers.clear();
  const rows = (state.tab === 'match' && !state.data.counts.match) ? state.near : tabRows().slice(0, state.shown);  // карта следует за списком: сначала тройка
  const pts = [];
  rows.forEach(r => {
    const h = r.hotel; if (h.lat == null || h.lon == null) return;
    const m = L.marker([h.lat, h.lon], { icon: L.divIcon({ className: 'pinw', html: PIN, iconSize: [28, 34], iconAnchor: [14, 32] }), keyboard: false, riseOnHover: true, title: '' });
    m.bindTooltip(esc(h.name), { direction: 'top', offset: [0, -30], className: 'ptip', opacity: 1 });
    m.on('click', () => selectHotel(h.id, true));
    m.addTo(map.layer); map.markers.set(h.id, m); pts.push([h.lat, h.lon]);
  });
  if (state.sel && map.markers.has(state.sel)) pinState(state.sel, false);
  if (fit && pts.length) { map.m.invalidateSize(); map.m.fitBounds(pts, { padding: [44, 44], maxZoom: 15, animate: false }) }
}
function selectHotel(id, fromMap) {
  const prev = state.sel; state.sel = id;
  if (prev && prev !== id) pinState(prev, false);
  pinState(id, false); vib(6);
  const r = state.byId.get(id); if (!r) return;
  if (isDesk()) {
    let card = $(`.card[data-id="${CSS.escape(id)}"]`);
    if (!card && fromMap) { const rows = tabRows(); const ix = rows.findIndex(x => x.hotel.id === id); if (ix >= state.shown) { state.shown = ix + 1; renderList(); renderMap(false); card = $(`.card[data-id="${CSS.escape(id)}"]`) } }
    if (card) { card.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' }); card.classList.add('hl'); setTimeout(() => card.classList.remove('hl'), 1800) }
  } else {
    const h = r.hotel, mc = $('#mapcard');
    mc.hidden = false; mc.dataset.id = id;
    mc.innerHTML = `${h.photo ? `<img src="${esc(h.photo)}" alt="">` : '<span class="ico ico-lg" data-e="🏨"></span>'}<div><b>${esc(h.name)}</b><small>${h.rating ? h.rating.toFixed(1) + ' · ' : ''}${h.price_nov1 ? money(h.price_nov1) : 'цены на даты нет'}</small></div>`;
    mc.onclick = () => openHotel(id);
  }
}
function setMapOn(on) {
  state.mapOn = on && !isDesk();
  $('#split').classList.toggle('map-on', state.mapOn);
  document.body.classList.toggle('map-open', state.mapOn);
  const f = $('#mapfab'); f.setAttribute('aria-pressed', state.mapOn);
  $('#mapfabT').textContent = state.mapOn ? 'Список' : 'Карта';
  $('#mapcard').hidden = true;
  if (state.mapOn && map.m) setTimeout(() => { map.m.invalidateSize(); renderMap(true) }, 60);
}
(() => { let y = scrollY; addEventListener('scroll', () => { const d = scrollY - y; if (Math.abs(d) < 8) return; $('#mapfab').classList.toggle('away', !state.mapOn && (scrollY < 240 || d > 0)); y = scrollY }, { passive: true }) })();
$('#mapfab').addEventListener('click', () => { vib(); setMapOn(!state.mapOn) });
addEventListener('resize', () => { if (isDesk() && state.mapOn) setMapOn(false); map.m && map.m.invalidateSize() });

/* ================= карточка отеля ================= */
const sheet = $('#sheet'), scrim = $('#scrim');
let sheetOpen = false;

function galleryHTML(photos) {
  return `<div class="gal"><div class="gal-t" id="galT">${photos.map((p, i) => `<img src="${esc(p)}" alt="" ${i ? 'loading="lazy"' : ''} decoding="async">`).join('')}</div><span class="gal-n" id="galN">${photos.length > 1 ? `1 / ${photos.length}` : ''}</span></div>`;
}
function metaHTML(h) {
  const st = h.stars || 0;
  return `<div class="sb"><h2>${esc(h.name)}</h2><div class="meta">${h.rating ? `<span class="rate">${h.rating.toFixed(1)}${h.reviews ? `<small>${h.reviews} ${plural(h.reviews, 'отзыв', 'отзыва', 'отзывов')}</small>` : ''}</span>` : ''}${st ? `<span class="stars" role="img" aria-label="${st} ${plural(st, 'звезда', 'звезды', 'звёзд')}">${Array.from({ length: st }, () => I.star).join('')}</span>` : ''}${KIND[h.kind] ? `<span class="k">${KIND[h.kind]}</span>` : ''}</div><p class="adr">${esc(h.address || '')}</p></div>`;
}
function ctaHTML(h) {
  const on = state.compare.includes(h.id);
  return `<button type="button" class="btn btn-line" id="shCmp" aria-pressed="${on}">${on ? 'В сравнении' : 'Сравнить'}</button><a class="btn btn-blue" href="${esc(h.url)}" target="_blank" rel="noopener">Открыть на Островке</a>`;
}

function openHotel(id, from) {
  const row = state.byId.get(id); if (!row) return;
  trackDwell(); openedAt = { id: String(id), t: performance.now() };
  track('open', { pos: state.rows.findIndex(r => r.hotel.id === id), bucket: row.bucket, tab: state.tab }, id);
  const h = row.hotel; state.openId = id; state.sel = id;
  const photos = h.photo ? [h.photo] : [];
  $('#shScroll').innerHTML = (photos.length ? galleryHTML(photos) : '<div class="gal noimg"></div>') + metaHTML(h) + wireShell() + `<div id="shBody"><div class="sk-sheet"><i style="width:70%"></i><i></i><i style="width:85%"></i><i style="height:90px"></i><i style="height:90px"></i></div></div>`;
  $('#shCta').innerHTML = ctaHTML(h);
  $('#shScroll').scrollTop = 0; sheet.classList.remove('scrolled');
  const cardImg = from && from.querySelector('.ph img');
  const hero = $('#galT img');
  const apply = () => {
    if (cardImg) cardImg.style.viewTransitionName = '';
    if (hero && document.startViewTransition && !reduced) hero.style.viewTransitionName = 'hotel';
    sheet.hidden = false; scrim.hidden = false; sheet.classList.add('nt');
    void sheet.offsetWidth; sheet.classList.add('open'); scrim.classList.add('open');
    document.body.classList.add('lock'); sheetOpen = true;
  };
  history.pushState({ ui: 'sheet' }, '');
  if (cardImg && document.startViewTransition && !reduced) {
    cardImg.style.viewTransitionName = 'hotel';
    vt(apply).finished.finally(() => { sheet.classList.remove('nt'); if (hero) hero.style.viewTransitionName = '' });
  } else {
    sheet.hidden = false; scrim.hidden = false; void sheet.offsetWidth; sheet.classList.add('open'); scrim.classList.add('open');
    document.body.classList.add('lock'); sheetOpen = true;
  }
  loadHotelBody(id, row);
  loadWire(id);
  setTimeout(() => $('#shX').focus({ preventScroll: true }), 80);
}

async function getHotel(id) {
  if (!state.hotelCache.has(id)) state.hotelCache.set(id, j('/api/hotels/' + encodeURIComponent(id)).catch(e => { state.hotelCache.delete(id); throw e }));
  return state.hotelCache.get(id);
}
async function loadHotelBody(id, row) {
  let d;
  try { d = await getHotel(id) } catch (e) {
    if (state.openId === id) $('#shBody').innerHTML = `<div class="grp"><div class="notice">Не удалось загрузить факты. Попробуйте открыть отель ещё раз.</div></div>`;
    return;
  }
  if (state.openId !== id) return;
  const photos = (d.card?.photos || []).filter(Boolean);
  const gt = $('#galT');
  if (photos.length > 1) {
    const have = gt ? gt.children.length : 0;
    if (!gt) { $('.gal.noimg')?.remove(); $('#shScroll').insertAdjacentHTML('afterbegin', galleryHTML(photos)) }
    else { photos.slice(have ? 1 : 0).forEach(p => gt.insertAdjacentHTML('beforeend', `<img src="${esc(p)}" alt="" loading="lazy" decoding="async">`)) }
    bindGallery(photos.length);
  }
  $('#shBody').innerHTML = factsHTML(d, row);
  recheckImgs();
}
function bindGallery(total) {
  const gt = $('#galT'), n = $('#galN'); if (!gt || !n || gt.dataset.b) return; gt.dataset.b = 1;
  n.textContent = `1 / ${total}`;
  gt.addEventListener('scroll', () => { const i = Math.round(gt.scrollLeft / gt.clientWidth); n.textContent = `${i + 1} / ${total}` }, { passive: true });
}

function factHTML(f, q) {
  const known = f.status !== 'unknown', conf = f.confidence || 0;
  const list = f.facts?.length ? f.facts : [{ source: f.source, observed_at: f.observed_at, confidence: f.confidence }];
  const seen = new Set(), pms = list.filter(x => x.source).map(x => ({ x, si: srcInfo(x.source, x.observed_at, f.name, x.method) })).filter(({ si }) => { const k = si.ring; return !seen.has(k) && seen.add(k) }).map(({ x, si }) => { return `<span class="fp-i">${pm(si.ring, si.code, 'pmk-m', 64)}<small>${esc(si.labels)}${si.date ? '<br>' + si.date : ''}</small></span>` }).join('');
  const cfl = (f.conflicts || []).map(c => `<div class="cfl"><b>${esc(cap(c.kind || 'Источники расходятся'))}</b>${esc(cap(c.winner || ''))}: «${esc(c.winner_says || '')}». ${esc(cap(c.other || ''))}: «${esc(c.other_says || '')}». Верим: ${esc(c.winner || 'расчёту')}.</div>`).join('');
  // источник и способ расчёта скрыты, открываются по нажатию
  const rows = f.facts?.length ? f.facts.map(x => `<div class="src-row"><b>${esc(cap(x.source))}</b><span>${esc(cap(x.summary || ''))}</span><br><span>Метод: ${esc(x.method || 'не указан')}. Проверено ${esc(fdate(x.observed_at))}${x.stale ? ', данные устарели' : ''}.</span></div>`).join('') : '';
  const det = known && (pms || rows) ? `<details class="det"><summary>Источник</summary>${pms ? `<div class="fp">${pms}</div>` : ''}${rows}</details>` : '';
  const st = f.status === 'conflict' ? '<span class="st conflict">Расхождение</span>' : known ? cst(conf) : '<span class="st unknown">Пока не знаем</span>';
  return `<div class="fact ${q ? 'q' : ''} ${known ? '' : 'unk'}" data-c="${esc(f.char)}"><div class="fh">${ico(f.char)}<b>${esc(f.name)}</b>${st}</div>
    <div class="fs">${numify(cap(f.summary))}</div>
    ${cfl}${det}
    ${known ? '' : `<button type="button" class="ask" data-ask="${esc(f.char)}">Спросить у отеля</button>`}</div>`;
}
function factsHTML(d, row) {
  const facts = d.facts || [], by = Object.fromEntries(facts.map(f => [f.char, f]));
  const qset = state.constraintChars;
  let out = '';
  const ev = evList(row);
  if (ev.all.length) out += `<section class="fordemand"><h3>${row.bucket === 'match' ? 'Почему подходит вам' : 'Что по вашему запросу'}</h3><ul class="evs">${ev.all.map(evHTML).join('')}</ul></section>`;
  // всё остальное свёрнуто: гость пробегает глазами заголовки и открывает нужное
  const fold = (head, n, body, cls = 'grp') => `<details class="${cls} fold"><summary><h3>${head}</h3><span class="fold-n">${n}</span></summary>${body}</details>`;
  const nf = n => `${n} ${plural(n, 'факт', 'факта', 'фактов')}`;
  if (facts.length) out += `<h3 class="more-h">Подробнее об отеле</h3>`;
  const used = new Set();
  GROUPS.forEach(([title, icon, ids]) => {
    const fs = ids.map(i => by[i]).filter(f => f && f.status !== 'unknown');
    ids.forEach(i => used.add(i));
    if (!fs.length) return;
    fs.sort((a, b) => (qset.has(b.char) ? 1 : 0) - (qset.has(a.char) ? 1 : 0));
    out += fold(`${ico(icon, 'ico-md')}${esc(title)}`, nf(fs.length), fs.map(f => factHTML(f, qset.has(f.char))).join(''));
  });
  const others = facts.filter(f => !used.has(f.char) && f.status !== 'unknown');
  if (others.length) out += fold(`${ico('x', 'ico-md')}Ещё`, nf(others.length), others.map(f => factHTML(f, qset.has(f.char))).join(''));
  const unk = facts.filter(f => f.status === 'unknown');
  if (unk.length) out += fold(`<span class="ico ico-md" data-e="?"></span>Пока не знаем`, `${unk.length}`, unk.map(f => factHTML(f, qset.has(f.char))).join(''));
  if (d.card?.description) out += fold('Описание от отеля', '', `<p>${esc(d.card.description)}${d.card.description.length >= 1190 ? '…' : ''}</p><small>Описание написал отель. Факты выше мы проверяем отдельно.</small>`, 'desc');
  return out;
}
$('#shScroll').addEventListener('click', async e => {
  const b = e.target.closest('[data-ask]'); if (!b || b.disabled) return;
  vib(); b.disabled = true; b.textContent = 'Отправляем…';
  try { await j(`/api/hotels/${encodeURIComponent(state.openId)}/ask`, { char_id: b.dataset.ask }); b.textContent = 'Вопрос отправлен отелю'; toast('Вопрос ушёл отелю. Ответ появится в карточке.') }
  catch (err) { b.disabled = false; b.textContent = 'Спросить у отеля'; toast('Не получилось отправить вопрос') }
});
$('#shCta').addEventListener('click', e => { if (e.target.closest('#shCmp')) { vib(); toggleCompare(state.openId) } });

function doClose() {
  if (!sheetOpen) return; sheetOpen = false;
  const id = state.openId, cardImg = $(`.card[data-id="${CSS.escape(id || '')}"] .ph img`), hero = $('#galT img');
  const fin = () => { sheet.hidden = true; scrim.hidden = true; sheet.classList.remove('nt'); sheet.style.transform = ''; sheet.classList.remove('drag'); document.body.classList.remove('lock'); if (cardImg) cardImg.style.viewTransitionName = '' };
  if (cardImg && hero && document.startViewTransition && !reduced && isInView(cardImg)) {
    hero.style.viewTransitionName = 'hotel'; sheet.classList.add('nt');
    vt(() => { hero.style.viewTransitionName = ''; cardImg.style.viewTransitionName = 'hotel'; sheet.classList.remove('open'); scrim.classList.remove('open'); sheet.style.transition = 'none' }).finished.finally(() => { sheet.style.transition = ''; fin() });
  } else {
    sheet.style.transform = ''; sheet.classList.remove('open'); scrim.classList.remove('open');
    setTimeout(() => { if (!sheetOpen) fin() }, 460);
  }
  trackDwell();
  state.openId = null;
}
function isInView(el) { const r = el.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight }
function closeHotelNow() { if (sheetOpen) { sheetOpen = false; sheet.classList.remove('open'); sheet.hidden = true; scrim.hidden = true; document.body.classList.remove('lock'); state.openId = null } }
function closeHotel() { if (!sheetOpen) return; if (history.state && history.state.ui === 'sheet') history.back(); else doClose() }
$('#shX').addEventListener('click', closeHotel);
$('#shScroll').addEventListener('scroll', e => sheet.classList.toggle('scrolled', e.target.scrollTop > 6), { passive: true });
scrim.addEventListener('click', closeHotel);
addEventListener('keydown', e => { if (e.key === 'Escape') { if (!$('#cmpModal').hidden) closeCompare(); else closeHotel() } });
addEventListener('popstate', () => { if (!$('#cmpModal').hidden) { hideCompare(); return } if (sheetOpen) doClose() });

/* свайп вниз за ручку (мобильная шторка) */
(() => {
  const g = $('#shGrab'); let y0 = null, dy = 0;
  g.addEventListener('pointerdown', e => { y0 = e.clientY; dy = 0; g.setPointerCapture(e.pointerId); sheet.classList.add('drag') });
  g.addEventListener('pointermove', e => { if (y0 == null) return; dy = Math.max(0, e.clientY - y0); sheet.style.transform = `translateY(${dy}px)` });
  const end = () => { if (y0 == null) return; y0 = null; sheet.classList.remove('drag'); if (dy > 110) { vib(); closeHotel() } else sheet.style.transform = ''; dy = 0 };
  g.addEventListener('pointerup', end); g.addEventListener('pointercancel', end);
})();

/* ================= «Что важнее?»: пять пар, карточку смахивают в сторону того, что важнее ================= */
/* Не «да/нет» по одному отелю, а выбор между двумя удобствами: так мы узнаём приоритеты, не задавая вопросов-анкет.
   Выбранное становится условием (желательным, если его не было; обязательным, если было), отвергнутое — желательным. */
const DUELS = [['quiet', 'beach'], ['sea', 'sunset'], ['pool', 'privbeach'], ['breakfast', 'kitchen'], ['adults', 'familyk'], ['balcony', 'spa']];
function openDuel(done) {
  if (!state.data || $('.duel')) return;
  const picks = []; let k = 0;
  const el = document.createElement('div');
  el.className = 'duel'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true'); el.setAttribute('aria-label', 'Что для вас важнее');
  el.innerHTML = `<div class="duel-in"><div class="duel-top"><h2>Что для вас важнее?</h2><span class="duel-n" id="duelN"></span><button type="button" class="sh-x static" id="duelX" aria-label="Закрыть">${I.no}</button></div>
    <p class="duel-sub">Смахните карточку в сторону того, что важнее, или нажмите на него.</p>
    <div class="duel-stack" id="duelStack"></div>
    <div class="duel-btns"><button type="button" class="btn btn-line" data-pick="0">${I.arrow}<span>Это</span></button><button type="button" class="btn btn-line duel-skip" data-pick="-1">Всё равно</button><button type="button" class="btn btn-line" data-pick="1"><span>Это</span>${I.arrow}</button></div></div>`;
  document.body.append(el); document.body.classList.add('lock');
  const half = (key, side) => { const a = COND[key]; return `<button type="button" class="dc-h dc-h${side}" data-pick="${side}">${ico(a.i, 'ico-lg')}<b>${esc(a.n)}</b><small>${esc(a.d)}</small><span class="dc-st">Важнее</span></button>` };
  const cardHTML = (i, back) => `<div class="dc ${back ? 'dc-back' : ''}" data-i="${i}">${half(DUELS[i][0], 0)}<span class="dc-or">или</span>${half(DUELS[i][1], 1)}</div>`;
  const draw = () => {
    $('#duelN').textContent = `${Math.min(k + 1, DUELS.length)} из ${DUELS.length}`;
    $('#duelStack').innerHTML = (k + 1 < DUELS.length ? cardHTML(k + 1, true) : '') + cardHTML(k, false);
    bindDrag($('.dc:not(.dc-back)', el));
  };
  const close = () => { el.remove(); removeEventListener('keydown', onKey, true); if (!sheetOpen && $('#cmpModal').hidden) document.body.classList.remove('lock') };
  const finish = () => {
    close();
    const p = editParsed(); p.constraints = p.constraints || [];
    const find = a => p.constraints.find(c => c.char === a.c[0] && c.field === a.c[1]);
    const won = [];
    picks.forEach(([w, l]) => {
      const a = COND[w], had = find(a); won.push(a.n);
      if (had) had.must = true; else p.constraints.push(mkCond(a, false));
      const lc = find(COND[l]); if (lc) lc.must = false;
    });
    if (!won.length) return;
    toast(`Учли: ${won.join(', ')}`);
    done(p, picks.map(([w]) => w));
  };
  const pick = side => {
    const card = $('.dc:not(.dc-back)', el); if (!card || card.classList.contains('out')) return;
    vib(10);
    if (side >= 0) picks.push([DUELS[k][side], DUELS[k][1 - side]]);
    card.classList.add('out', side === 0 ? 'out-l' : side === 1 ? 'out-r' : 'out-d');
    card.style.transform = '';
    setTimeout(() => { k++; if (k >= DUELS.length) finish(); else draw() }, reduced ? 0 : 260);
  };
  /* Нажатие на половину выбирает её, протяжка смахивает. Указатель захватываем только когда пошла протяжка:
     иначе клик уходит на всю карточку и половина его не получает. Выбор по нажатию решаем сами, на pointerup. */
  function bindDrag(card) {
    let x0 = null, dx = 0, moved = false, side = null, pid = null;
    card.addEventListener('pointerdown', e => { x0 = e.clientX; dx = 0; moved = false; pid = e.pointerId; side = e.target.closest('[data-pick]')?.dataset.pick ?? null });
    card.addEventListener('pointermove', e => {
      if (x0 == null) return; dx = e.clientX - x0;
      if (!moved && Math.abs(dx) > 8) { moved = true; card.classList.add('drag'); try { card.setPointerCapture(pid) } catch (err) { } }
      if (!moved) return;
      card.style.transform = `translateX(${dx}px) rotate(${(dx / 22).toFixed(1)}deg)`;
      card.classList.toggle('lean-0', dx < -40); card.classList.toggle('lean-1', dx > 40);
    });
    const end = () => {
      if (x0 == null) return; x0 = null; card.classList.remove('drag');
      if (!moved) { if (side != null) pick(+side); return }
      if (dx < -90) pick(0); else if (dx > 90) pick(1);
      else { card.style.transform = ''; card.classList.remove('lean-0', 'lean-1') }
    };
    card.addEventListener('pointerup', end); card.addEventListener('pointercancel', () => { moved = true; dx = 0; end() });
    card.addEventListener('click', e => {  // мышью и пальцем выбор уже сделан на pointerup; с клавиатуры (detail 0) выбираем здесь
      e.stopPropagation();
      const h = e.detail === 0 && e.target.closest('[data-pick]'); if (h) pick(+h.dataset.pick);
    });
  }
  const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close() } if (e.key === 'ArrowLeft') pick(0); if (e.key === 'ArrowRight') pick(1); if (e.key === 'ArrowDown') pick(-1) };
  addEventListener('keydown', onKey, true);
  el.addEventListener('click', e => {
    if (e.target.closest('#duelX') || e.target === el) { close(); return }
    const b = e.target.closest('.duel-btns [data-pick]'); if (b) pick(+b.dataset.pick);
  });
  draw();
}

/* ================= сравнение ================= */
function toggleCompare(id) {
  const i = state.compare.indexOf(id);
  if (i >= 0) state.compare.splice(i, 1);
  else { if (state.compare.length >= 4) { toast('В сравнении может быть до 4 отелей'); return } state.compare.push(id); }
  vib();
  syncCompareUI();
}
function syncCompareUI() {
  $$('.card .cmp').forEach(b => { const on = state.compare.includes(b.closest('.card').dataset.id); b.setAttribute('aria-pressed', on); b.setAttribute('aria-label', on ? 'Убрать из сравнения' : 'Добавить в сравнение') });
  const sc = $('#shCmp'); if (sc && state.openId) { const on = state.compare.includes(state.openId); sc.setAttribute('aria-pressed', on); sc.textContent = on ? 'В сравнении' : 'Сравнить' }
  const n = state.compare.length, tray = $('#tray');
  tray.hidden = !n;
  document.documentElement.style.setProperty('--tray', n ? (isDesk() ? '84px' : '76px') : '0px');
  if (!n) return;
  $('#traySlots').innerHTML = Array.from({ length: Math.min(4, n + 1) }, (_, i) => {
    const id = state.compare[i], h = id && state.byId.get(id)?.hotel;
    return h ? `<button type="button" class="slot" data-rm="${esc(id)}" aria-label="Убрать ${esc(h.name)}">${h.photo ? `<img src="${esc(h.photo)}" alt="">` : ''}<span class="x">${I.no}</span></button>` : `<span class="slot empty" aria-hidden="true">${I.plus}</span>`;
  }).join('');
  const go = $('#trayGo'); go.disabled = n < 2; go.textContent = n < 2 ? 'Выберите ещё' : `Сравнить (${n})`;
}
$('#traySlots').addEventListener('click', e => { const b = e.target.closest('[data-rm]'); if (b) toggleCompare(b.dataset.rm) });
$('#trayClear').addEventListener('click', () => { state.compare = []; syncCompareUI() });
$('#trayGo').addEventListener('click', openCompare);

let cmpData = null;
async function openCompare() {
  if (state.compare.length < 2) return; vib();
  const modal = $('#cmpModal');
  history.pushState({ ui: 'cmp' }, '');
  // vt() рисует заглушку отложенно (в фоновой вкладке — когда угодно позже); если сравнение уже готово, заглушку не рисуем
  let ready = false;
  vt(() => { modal.hidden = false; document.body.classList.add('lock'); if (!ready) $('#cmpBody').innerHTML = `<div class="cmp-empty"><div class="wait"><ol class="phases"><li class="now"><i class="mk"></i><span>Собираем факты двух открыток</span></li></ol></div></div>` });
  try {
    cmpData = await j('/api/compare', { hotel_ids: state.compare.slice() });
    ready = true; modal.hidden = false; document.body.classList.add('lock');
    renderCompare();
  } catch (e) { $('#cmpBody').innerHTML = `<div class="cmp-empty"><img src="/front/assets/empty-search.webp" alt=""><p>Не удалось загрузить сравнение. Закройте окно и откройте сравнение ещё раз.</p></div>` }
}
function renderCompare() {
  const d = cmpData; if (!d) return;
  const only = $('#cmpDiff').checked, qset = state.constraintChars, n = d.hotels.length;
  let rows = d.rows.slice().sort((a, b) => (qset.has(b.char) ? 1 : 0) - (qset.has(a.char) ? 1 : 0));
  if (only) rows = rows.filter(r => new Set(r.cells.map(c => c.summary)).size > 1);
  const cols = Array.from({ length: n }, () => 'minmax(140px,1fr)').join(' var(--hg) ');
  const sc = c => c.status === 'unknown' ? -1 : (c.confidence || 0);
  const head = d.hotels.map((h, i) => `<div class="vh"><div class="vh-p">${h.photo ? `<img src="${esc(h.photo)}" alt="" onerror="this.style.visibility='hidden'">` : ''}</div><b>${esc(h.name)}</b><small>${h.rating ? h.rating.toFixed(1) + ' · ' : ''}${h.price_nov1 ? money(h.price_nov1) : 'цены на даты нет'}</small><a href="${esc(h.url)}" target="_blank" rel="noopener">Открыть на Островке</a></div>${i < n - 1 ? `<div class="hinge hinge-h"><span>VS</span></div>` : ''}`).join('');
  const body = rows.map(r => {
    const sco = r.cells.map(sc), mx = Math.max(...sco), mn = Math.min(...sco), dec = mx > mn;
    const cells = r.cells.map((c, i) => {
      const si = c.source ? srcInfo(c.source, null, r.name) : null;
      const win = dec && sco[i] === mx, lose = dec && sco[i] < mx;
      return `<div class="vc ${c.status} ${win ? 'win' : ''} ${lose ? 'lose' : ''} ${qset.has(r.char) ? 'q' : ''}"><small class="vl">${esc(r.name)}</small><span class="vv">${numify(cap(c.summary))}</span>${si ? `<span class="vs-s">${esc(si.labels)}${c.status !== 'unknown' ? cst(c.confidence) : ''}</span>` : ''}</div>${i < n - 1 ? `<div class="hinge">${ico(r.char)}</div>` : ''}`;
    }).join('');
    return cells;
  }).join('');
  $('#cmpBody').innerHTML = fitHTML() + `<div class="vs" style="--cols:${cols};--n:${n}"><div class="vs-g">${head}${body}</div></div>${rows.length ? '<p class="vs-note">Жирным выделен факт, в котором мы увереннее. Если уверенность равна, строка не размечена.</p>' : '<div class="cmp-empty">Все характеристики у этих отелей совпадают.</div>'}`;
}
$('#cmpDiff').addEventListener('change', () => { vib(4); renderCompare() });
/* «Сравнить за 30 секунд»: пары «это или то», затем говорим, какой из отелей в сравнении выполняет больше выбранного */
async function cmpDuel() {
  openDuel(async (p, keys) => {
    const ids = state.compare.slice();
    try {
      const r = await j('/api/compare/fit', { hotel_ids: ids, constraints: keys.map(k => mkCond(COND[k])), month: p.month });
      state.fit = { ids: ids.join(), keys, hotels: r.hotels };
    } catch (e) { toast('Не получилось сравнить по вашему выбору') }
    renderCompare();
    state.afterCmp = p;  // выдачу пересчитаем, когда закроют сравнение: анимация поиска не должна мигать сквозь окно
  });
}
function fitHTML() {
  const f = state.fit, d = cmpData;
  if (!f || f.ids !== d.hotels.map(h => h.id).join()) {
    return `<div class="fit fit-promo"><div class="fit-t"><b>Сложно выбрать?</b><span>Шесть вопросов «это или то», и мы покажем, какой из отелей подходит именно вам.</span></div><button type="button" class="btn btn-blue js-cmpduel">${I.flip}<span>Сравнить за 30 секунд</span></button></div>`;
  }
  const ST = { pass: 'good', fail: 'bad', unknown: 'unk' }, H = f.hotels, n = H.length;
  const info = id => d.hotels.find(h => h.id === id) || {};
  const nm = i => `«${esc(info(H[i].hotel_id).name || '')}»`;
  // 1) сколько выбранного выполнено; 2) по каждому выбранному — у кого число лучше (минуты, этаж, дБ…), с допуском;
  // 3) если всё равно поровну — дешевле; 4) выше рейтинг. Ничьей не объявляем: всегда называем, чем один лучше.
  const pass = H.map(h => h.checks.filter(c => c.status === 'pass').length);
  const edge = H.map(() => []);  // по каким условиям отель заметно лучше остальных
  f.keys.forEach((key, k) => {
    const ms = H.map(h => h.checks[k].status !== 'fail' ? h.checks[k].measure : null);
    const vals = ms.filter(Boolean); if (vals.length < 2) return;
    const m0 = vals[0], hi = m0.better === 'hi';
    const best = hi ? Math.max(...vals.map(m => m.value)) : Math.min(...vals.map(m => m.value));
    const near = m => m && Math.abs(m.value - best) <= m0.tol;
    if (ms.every(near)) return;  // у всех есть и разница в пределах допуска
    ms.forEach((m, i) => { if (near(m)) edge[i].push(k) });
  });
  const price = H.map(h => info(h.hotel_id).price_nov1 || Infinity), rate = H.map(h => info(h.hotel_id).rating || 0);
  const order = H.map((_, i) => i).sort((a, b) => pass[b] - pass[a] || edge[b].length - edge[a].length || price[a] - price[b] || rate[b] - rate[a]);
  const w = order[0], r = order[1];
  let why;
  if (!pass[w] && !edge[w].length) why = 'Ни один отель не выполняет то, что вы выбрали, этот ближе других по цене и оценкам';
  else if (pass[w] > pass[r]) why = `Выполняет ${pass[w]} из ${f.keys.length} условий, остальные меньше`;
  else if (edge[w].length > edge[r].length) why = `При равных галочках сильнее в: ${edge[w].map(k => COND[f.keys[k]].n.toLowerCase()).join(', ')}`;
  else if (price[w] < price[r] && price[r] !== Infinity) {
    const pl = i => edge[i].map(k => COND[f.keys[k]].n.toLowerCase()).join(', ');
    why = edge[w].length ? `У каждого свой плюс: у этого — ${pl(w)}, у другого — ${pl(r)}. Решает цена: этот дешевле на ${money(price[r] - price[w])}`
      : `По вашему выбору отели почти равны, а этот дешевле на ${money(price[r] - price[w])}`;
  }
  else if (rate[w] > rate[r]) why = `По вашему выбору и цене отели почти равны, а у этого выше оценка гостей: ${rate[w].toFixed(1)} против ${rate[r].toFixed(1)}`;
  else why = 'Отели почти не отличаются по вашему выбору, посмотрите таблицу ниже';
  const cols = H.map((h, i) => `<div class="fit-h ${i === w ? 'win' : ''}">${i === w ? '<span class="fit-best">Лучше для вас</span>' : ''}<b>${esc(info(h.hotel_id).name || '')}</b><small>${pass[i]} из ${f.keys.length}${price[i] !== Infinity ? ' · ' + money(price[i]) : ''}</small><ul>${h.checks.map((c, k) => `<li class="${edge[i].includes(k) ? 'edge' : ''}">${mark(ST[c.status])}<span><b>${esc(COND[f.keys[k]].n)}</b>${c.measure ? `<small>${esc(c.measure.text)}</small>` : ''}</span>${edge[i].includes(k) ? '<em>лучше</em>' : ''}</li>`).join('')}</ul></div>`).join('');
  return `<div class="fit"><div class="fit-t"><b>Вам больше подходит ${nm(w)}</b><span>${why}.</span></div><button type="button" class="btn btn-line js-cmpduel">Пройти ещё раз</button><div class="fit-g" style="--n:${n}">${cols}</div></div>`;
}
$('#cmpBody').addEventListener('click', e => { if (e.target.closest('.js-cmpduel')) { vib(); cmpDuel() } });
function hideCompare() {
  vt(() => { $('#cmpModal').hidden = true; if (!sheetOpen) document.body.classList.remove('lock') });
  if (state.afterCmp) { const p = state.afterCmp; state.afterCmp = null; setTimeout(() => runSearch(state.q, p), 350) }
}
function closeCompare() { if (history.state && history.state.ui === 'cmp') history.back(); else hideCompare() }
$('#cmpX').addEventListener('click', closeCompare);
$('#cmpModal').addEventListener('click', e => { if (e.target.id === 'cmpModal') closeCompare() });

/* ================= правда об отеле: блоки из бэкенда ================= */
/* Вердикт, номер, вид из окна, ночь по часам, заявления карточки. Каждый блок грузится сам, со своим ожиданием и своей ошибкой.
   Все числа приходят из API и только форматируются здесь (округление, склонение). */
const DIRN = { 'С': 'север', 'СВ': 'северо-восток', 'В': 'восток', 'ЮВ': 'юго-восток', 'Ю': 'юг', 'ЮЗ': 'юго-запад', 'З': 'запад', 'СЗ': 'северо-запад' };
const DIRREV = Object.fromEntries(Object.entries(DIRN).map(([k, v]) => [v, k]));
const dirn = c => DIRN[c] || c;
const MONTHS_NOM = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];
const TW_SECS = [['twRooms', 'Какой номер брать', 70], ['twWin', 'Вид из окна', 150], ['twNight', 'Ночь по часам', 110], ['twClaims', 'Проверка карточки', 60]];
const TW_NIGHT_HOURS = [21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8];
const enc = encodeURIComponent;
let tw = null;

const twSkel = (h = 70) => `<div class="sk-sheet"><i style="width:60%"></i><i style="height:${h}px"></i></div>`;
function wireShell() {
  return `<div id="shWire" class="tw-wire"><div class="tw-vd wait" id="twVd" aria-live="polite"><div class="tw-vd-l">Подбираем номер</div><div class="sk-sheet"><i style="width:80%"></i></div></div>`
    + TW_SECS.map(([id, t, h]) => `<section class="tw" id="${id}"><h3>${t}</h3><div class="tw-b">${twSkel(h)}</div></section>`).join('') + `</div>`;
}
const twBody = id => $(`#${id} .tw-b`);
function twErr(ctx, id, retry) {
  if (tw !== ctx) return;
  ctx.retry[id] = retry;
  twBody(id).innerHTML = `<div class="tw-err"><p>Этот раздел не загрузился. Остальное на месте.</p><button type="button" class="btn btn-line" data-retry="${id}">Повторить</button></div>`;
}
function twRetry(ctx, id, h) { if (tw === ctx) twBody(id).innerHTML = twSkel(h) }

function twCopy(btn, text) {
  const label = btn.dataset.label || btn.textContent; btn.dataset.label = label;
  const done = () => { btn.textContent = 'Скопировано'; btn.classList.add('done'); toast('Текст скопирован. Вставьте его в поле «Пожелания» при бронировании.'); setTimeout(() => { btn.textContent = label; btn.classList.remove('done') }, 2200) };
  const fb = () => { const ta = document.createElement('textarea'); ta.value = text; ta.style.cssText = 'position:fixed;opacity:0'; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); done() } catch (e) { toast('Выделите текст и скопируйте вручную') } ta.remove() };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fb); else fb();
}

function loadWire(id) {
  const ctx = tw = { id, wants: queryWants(), row: state.byId.get(id) || null, rooms: null, roomsErr: false, pick: null, night: null, nightErr: false, nightWin: null, win: null, winV: null, winErr: false, ws: { month: 7, facade: null, floor: null, token: 0 }, touched: false, pickAsked: false, truth: null, hotel: null, audit: null, retry: {} };
  twRooms(ctx); twWinLoad(ctx, {}, { verdict: true, first: true }); twNight(ctx); twClaims(ctx);
  j(`/api/truth/hotel/${enc(id)}`).then(t => { if (tw === ctx) { ctx.truth = t; drawVerdict(ctx) } }).catch(() => { });
  getHotel(id).then(d => { if (tw === ctx) { ctx.hotel = d; drawVerdict(ctx) } }).catch(() => { });
}

/* ---------- какой номер брать ---------- */
function pickOf(d) {
  const b = d && d.best, req = b && b.special_request; if (!req) return null;
  const m = req.match(/окнами на ([а-яё-]+)/i);
  const side = (b.ask && b.ask.side) || (m && DIRREV[m[1].toLowerCase()]) || null;
  if (!side) return null;
  return { side, floor: (b.ask && b.ask.min_floor) || null, room: b.room, request: req };
}
/* Что гость просил про вид, закат и тишину: из разбора активного поиска. Без запроса оцениваем вид и тишину. */
function queryWants() {
  const p = state.data && state.data.parsed, cs = (p && p.constraints) || [], w = { sea: false, sunset: false, quiet: false, chars: new Set(cs.map(c => c.char)), month: (p && p.month) || null };
  cs.forEach(c => {
    if (c.char === 'sea_view' || c.char === 'sea_view_quiet') w.sea = true;
    if (c.char === 'sunset' || c.char === 'sunset_quiet') w.sunset = true;
    if (c.char === 'night_quiet' || /_quiet$/.test(c.char)) w.quiet = true;
  });
  w.none = !cs.length;               // запроса нет (открыли по ссылке) или в нём нечего проверять
  w.geo = w.sea || w.sunset || w.quiet;
  return w;
}
const apiWants = w => (w.geo ? [w.sea && 'sea', w.sunset && 'sunset', w.quiet && 'quiet'].filter(Boolean) : ['sea', 'quiet']).join(',');
async function twRooms(ctx) {
  try { ctx.rooms = await j(`/api/rooms/${enc(ctx.id)}?wants=${apiWants(ctx.wants)}${ctx.wants.sunset && ctx.wants.month ? '&month=' + ctx.wants.month : ''}`); ctx.roomsErr = false }
  catch (e) { if (tw !== ctx) return; ctx.roomsErr = true; twErr(ctx, 'twRooms', () => { twRetry(ctx, 'twRooms', 70); twRooms(ctx) }); drawVerdict(ctx); return }
  if (tw !== ctx) return;
  ctx.pick = pickOf(ctx.rooms);
  drawRooms(ctx); drawVerdict(ctx); twWinForPick(ctx);
}
function askText(a) { return a && a.side ? `окна на ${dirn(a.side)}${a.min_floor > 1 ? ', ' + atFl(a.min_floor, a.levels) : ''}` : 'окна на тихую сторону' }
const OTHER_ACC = { 'город': 'город', 'горы': 'горы', 'двор': 'двор', 'сад': 'сад', 'парк': 'парк', 'бассейн': 'бассейн', 'терраса': 'террасу', 'река': 'реку', 'набережная': 'набережную', 'порт': 'порт' };
/* что категория обещает про вид (без процентов: цифра шанса одна на панель) */
const viewTag = r => r.windowless ? 'без окна' : r.claims_sea_view ? 'вид на море в названии' : r.other_view ? (OTHER_ACC[r.other_view] ? `вид на ${OTHER_ACC[r.other_view]}` : 'вид не на море') : 'вид не указан';
function drawRooms(ctx) {
  const d = ctx.rooms, b = d.best, box = twBody('twRooms');
  const generic = !!d.note || !!d.tie || (d.same_p && d.rooms.length > 1);
  if (!b) { box.innerHTML = `<p class="tw-note">${esc(d.note || 'Подходящих категорий нет.')}</p>${d.honesty ? `<p class="tw-hon">${esc(d.honesty)}</p>` : ''}`; return }
  const rp = Math.round((b.random_p || 0) * 100), ap = b.ask && b.ask.side && b.ask.p != null ? Math.round(b.ask.p * 100) : null;
  const askHelps = ap != null && ap > rp + 2, askLower = ap != null && ap < rp - 2, askSame = ap != null && !askHelps && !askLower;
  const quietAsk = /тихо/.test(b.special_request || '');
  const tags = [b.windowless ? ['без окна', 'bad'] : null, b.claims_sea_view ? ['вид на море в названии'] : null, b.hidden_view ? ['море видно, хоть не в названии', 'ok'] : null, b.other_view ? [viewTag(b)] : null, b.balcony ? ['балкон'] : null, b.size_m2 ? [`${b.size_m2} м²`] : null,
    b.guests && b.guests.praise_sea ? [`гости хвалят вид: ${b.guests.praise_sea}`, 'ok'] : null, b.guests && b.guests.deny_sea ? [`жалобы на вид: ${b.guests.deny_sea}`, 'bad'] : null].filter(Boolean);
  const others = d.rooms.filter(r => r.room !== b.room);
  const hotel = (state.byId.get(ctx.id) || {}).hotel, link = hotel && hotel.url ? `<a class="btn btn-line" href="${esc(hotel.url)}" target="_blank" rel="noopener">Открыть на Островке</a>` : '';
  const tie = d.tie, anyName = tie && tie.claims_n >= 2 ? `Любая из ${tie.claims_n} категорий «с видом на море»` : 'Любая категория';
  const seaTalk = ctx.wants.sea || ctx.wants.sunset || ctx.wants.none, showBars = !generic && ap != null && seaTalk;
  box.innerHTML = `${generic ? `<p class="tw-note">${d.note ? esc(d.note) : (seaTalk ? 'Шанс увидеть море у категорий одинаковый: важны сторона здания и этаж, а не название.' : 'У категорий одинаковые стороны здания: важны сторона и этаж, а не название.')}</p>` : ''}
    <div class="tw-room">
      <small class="tw-k">${generic ? 'Подойдёт' : 'Лучшая категория'}</small>
      <b class="tw-rn">${generic ? esc(anyName) : esc(b.room)}</b>
      ${!generic && tags.length ? `<div class="tw-tags">${tags.map(t => `<span class="tw-tag ${t[1] || ''}">${esc(t[0])}</span>`).join('')}</div>` : ''}
      ${!generic && seaTalk ? `<div class="tw-ph">Шанс, что из окна будет видно море</div><div class="tw-p"><span>Если отель выберет сторону наугад</span><span class="tw-bar"><i style="width:${rp}%"></i></span><b>${rp}%</b></div>` : ''}
      ${showBars && (askHelps || askLower) ? `<div class="tw-p"><span>Если попросить ${esc(askText(b.ask))}</span><span class="tw-bar"><i style="width:${ap}%"></i></span><b>${ap}%</b></div>` : ''}
      ${showBars && askLower ? `<p class="tw-note">Ради тишины шанс увидеть море ниже.</p>` : ''}
      ${showBars && askSame ? `<p class="tw-note">${quietAsk ? 'Просьба нужна ради тишины, шансы на море она не меняет' : 'Просьба шансы на море не меняет'}</p>` : ''}
      ${b.claim_note ? `<p class="tw-note">${esc(b.claim_note)}</p>` : ''}
      ${b.special_request ? `<div class="tw-ask"><small class="tw-k">Что написать в пожеланиях к брони</small><p>${esc(b.special_request)}</p><div class="tw-acts"><button type="button" class="btn btn-blue" data-copy="${esc(b.special_request)}">Скопировать текст</button>${link}</div></div>`
        : `<div class="tw-ask"><small class="tw-k">Просить нечего</small><p>${b.windowless ? 'В номере нет настоящего окна, море не видно.' : 'Сторону и этаж по расчёту выбирать незачем.'}</p></div>`}
      ${b.evidence && b.evidence.length ? `<details class="det"><summary>Откуда это</summary><ul class="tw-ev">${b.evidence.map(x => `<li>${esct(x)}</li>`).join('')}</ul></details>` : ''}
    </div>
    ${others.length ? `<details class="det"><summary>Другие категории: ${others.length}</summary><ul class="tw-alt">${others.map(r => `<li><span>${esc(r.room)}</span><b>${esc(viewTag(r))}</b></li>`).join('')}</ul></details>` : ''}
    ${d.honesty && seaTalk ? `<p class="tw-hon">${esc(d.honesty)}</p>` : ''}`;
}

/* ---------- вердикт ---------- */
const GEO_CHARS = new Set(['sea_view', 'sea_view_quiet', 'sunset', 'sunset_quiet', 'night_quiet', 'beach_walk']);
const geoKey = ch => /^(sea_view|sunset)/.test(ch) ? 'sea' : ch === 'night_quiet' ? 'night' : ch === 'beach_walk' ? 'beach' : null;
const anyCat = d => d.tie && d.tie.claims_n >= 2 ? `любая из ${d.tie.claims_n} категорий «с видом на море»` : 'любая категория';
function twChips(ctx) {
  const p = ctx.pick, W = ctx.wants, row = ctx.row, L = ctx.rooms ? ctx.rooms.levels : 0, mn = state.data && state.data.parsed ? state.data.parsed.month : null;
  const conflict = c => { const x = ((ctx.truth && ctx.truth.chars) || []).find(y => y.char === c && y.status === 'conflict' && y.sentence); return x ? x.sentence : null };
  const w = ctx.winV, by = {};
  /* море: только если гость просил море или закат (или запроса нет) */
  if (W.sunset && !W.sea && !W.none) {
    /* гость просил закат, не море: чип про закат из расчёта окна */
    if (w && w.sun && p && w.facade === p.side) {
      const ov = w.sun.over_sea, vis = w.sun.visible;
      by.sea = { k: 'sea', cls: vis ? 'ok' : 'warn', text: `закат в ${MONTH_PREP[w.month] || 'выбранном месяце'}: ${vis ? (ov ? 'виден над морем' : 'виден над городом') : 'из окна не виден'}`,
        tip: `Источник: вид из окна, окна на ${dirn(w.facade)}, ${nomFl(w.floor, w.levels)}. Солнце за последние 90 минут до заката против высот зданий и рельефа. Это расчёт, на месте может отличаться.` };
    } else if (!ctx.winErr) by.sea = { k: 'w', cls: 'wait', text: 'проверяем закат из окна' };
  } else if (W.sea || W.sunset || W.none) {
    if (w && typeof w.sea_p === 'number') {
      const pc = Math.round(w.sea_p * 100);
      by.sea = { k: 'sea', cls: pc > 50 ? 'ok' : 'warn', text: (w.chips && w.chips[1]) || `море из окна: шанс ${pc}%`,
        tip: `Источник: вид из окна, окна на ${dirn(w.facade)}, ${nomFl(w.floor, w.levels)}. Считаем по карте высот и зданиям OpenStreetMap много раз со сдвигом позиции. Это расчёт, на месте может отличаться.` };
    } else if (!ctx.winErr) by.sea = { k: 'w', cls: 'wait', text: 'проверяем вид из окна' };
  }
  const n = ctx.night;
  if (W.quiet || W.none) {
    if (n && p && p.side) {
      const f = (n.facades || []).find(x => x.dir === p.side), ws = n.window_assumed || 'closed', sl = f && f.sleep && f.sleep[ws];
      if (sl) {
        const thr = n.threshold ? n.threshold.indoor_db : null, db = Math.ceil(sl.night_mean_indoor), quiet = thr != null ? db <= thr : sl.at_floor;
        by.night = { k: 'night', cls: quiet ? 'ok' : 'warn',
          text: `ночью ${quiet ? 'тихо' : 'шумновато'}: ${db} дБ в номере при ${ws === 'closed' ? 'закрытом' : 'открытом'} окне`,
          tip: `Источник: ночь по часам, окна на ${dirn(p.side)}, окно ${ws === 'closed' ? 'закрыто' : 'открыто'}${n.air_conditioning ? (n.air_conditioning.has ? ', в карточке есть кондиционер' : ', кондиционера в карточке нет') : ''}. ${n.threshold ? n.threshold.why + '.' : ''} Не учтены дома, которые закрывают от шума.` };
      }
    } else if (!n && !ctx.nightErr && p && p.side) by.night = { k: 'n', cls: 'wait', text: 'проверяем шум ночью' };
  }
  const f = ctx.hotel && (ctx.hotel.facts || []).find(x => x.char === 'beach_walk' && x.status !== 'unknown');
  if ((W.chars.has('beach_walk') || W.none) && f && f.value && typeof f.value.minutes_there === 'number') {
    const v = f.value, mm = Math.max(1, Math.round(v.minutes_there));
    const meth = String((f.facts && f.facts[0] && f.facts[0].method) || 'пешие маршруты OpenStreetMap и рельеф').replace(/пеший граф OSM/g, 'пешие маршруты OpenStreetMap');
    by.beach = { k: 'beach', cls: mm <= 10 && v.climb_back_m < 30 ? 'ok' : 'warn', text: `пляж ${mm} мин` + (v.climb_back_m >= 3 ? `, подъём ${Math.round(v.climb_back_m)} м` : ''),
      tip: `Источник: ${f.source || 'расчёт по геоданным'}, ${meth}. ${tidy(f.summary || '')}` };
  }
  const CF = { sea: 'sea_view', night: 'night_quiet', beach: 'beach_walk' };
  Object.values(by).forEach(c => {
    if (c.k === 'sea' && W.sunset && !W.sea && !W.none) return;
    const sn = CF[c.k] && conflict(CF[c.k]); if (!sn) return;
    const m = sn.match(/(\d+) из (\d+)/), calcYes = sn.startsWith('Расчёт показывает');
    if (c.k === 'night') c.text = calcYes ? (m ? `ночью тихо по расчёту, но ${m[1]} из ${m[2]} гостей жалуются на шум` : 'ночью тихо по расчёту, но гости жалуются на шум') : 'гости хвалят тишину, но по расчёту шумно';
    else if (c.k === 'sea') c.text = calcYes ? 'море по расчёту видно, но гости пишут иное' : 'гости пишут про вид на море, а расчёт его не находит';
    else c.text += ', но отзывы говорят иное';
    c.cls = 'warn'; c.tip = sn + ' ' + c.tip;
  });
  /* остальные выполненные условия запроса: питомцы, шторы, ночное заселение и так далее */
  const cs = (row && row.chips) || [];
  cs.forEach((c, i) => {
    if (GEO_CHARS.has(c.char) || c.status !== 'pass' || c.must === false) return;
    by['c' + i] = { k: 'c' + i, cls: c.weak || c.conflict ? 'warn' : 'ok', text: human(c, mn).toLowerCase(),
      tip: `Источник: ${c.source || 'карточка Островка'}${c.confidence != null ? `, уверенность ${Math.round(c.confidence * 100)}%` : ''}. ${tidy(c.full || '')}` };
  });
  /* порядок: как гость назвал условия, потом остальные */
  const order = [];
  ((state.data && state.data.parsed && state.data.parsed.constraints) || []).forEach((c, i) => { const k = geoKey(c.char) || (GEO_CHARS.has(c.char) ? null : 'c' + cs.findIndex(x => x.char === c.char && x.field === c.field)); if (k && !order.includes(k)) order.push(k) });
  ['sea', 'night', 'beach'].forEach(k => order.includes(k) || order.push(k));
  return order.map(k => by[k]).filter(Boolean);
}
function failLine(c, mn) {
  const k = c.char + '.' + c.field, v = c.value, a = c.actual, r = x => String(Math.round(x));
  if (k === 'beach_walk.climb_back_m' && typeof a === 'number') return `Подъём от пляжа ${r(a)} м, а вы просили ${v <= 25 ? 'без подъёма' : `не больше ${r(v)} м`}`;
  if (k === 'beach_walk.minutes_there' && typeof a === 'number') return `До пляжа ${r(a)} мин пешком, а вы просили до ${r(v)}`;
  if (k === 'beach_walk.minutes_back' && typeof a === 'number') return `Обратно от пляжа ${r(a)} мин, а вы просили до ${r(v)}`;
  if (k === 'beach_walk.crosses_rail') return 'К пляжу надо переходить железную дорогу, а вы просили без перехода';
  if ((k === 'sea_view.has' || k === 'sea_view_quiet.has') && v === true) return 'По расчёту моря из окон нет, а вы просили вид на море';
  if (k === 'sunset.visible' && v === true) return 'Закат из окон не виден, а вы просили вид на закат';
  if (k === 'night_quiet.quiet' && v === true) return 'Тихой стороны по расчёту нет, а вы просили тихий номер';
  if (k === 'pets.allowed' && v === true) return 'С питомцами здесь не принимают, а вы просили отель для поездки с питомцем';
  return `Не выполняется условие «${human(c, mn)}»`;
}
function drawVerdict(ctx) {
  const el = $('#twVd'); if (!el || tw !== ctx) return;
  if (!ctx.rooms && !ctx.roomsErr) return;
  const W = ctx.wants, row = ctx.row, mn = state.data && state.data.parsed ? state.data.parsed.month : null;
  let line, cls = '', pre = '', after = '';
  if (ctx.roomsErr) { line = 'Подбор номера недоступен. Вид и ночь смотрите ниже.'; cls = 'none' }
  else {
    const d = ctx.rooms, b = d.best, p = ctx.pick, generic = !!d.note || !!d.tie || (d.same_p && d.rooms.length > 1), L = d.levels || 0;
    const fl = p && p.floor > 1 ? `, <b>${esc(atFl(p.floor, L))}</b>` : '';
    const sea = b && b.ask && b.ask.p != null ? b.ask.p : b ? b.best_side_p : 0;
    const cond = row && !W.none ? (row.chips || []).filter(c => c.char && c.must !== false) : [];
    const failed = row && !W.none && row.bucket === 'fail' ? (cond.find(c => c.status === 'fail') || null) : null;
    const bf = row && !W.none && row.bucket === 'fail' && !failed ? (row.chips || []).find(c => !c.char && c.status === 'fail') : null, baseFail = bf ? bf.text : null;
    const askLine = p ? (generic ? `Просите <b>окна на ${esc(dirn(p.side))}</b>${fl}.` : `Просите в номере «${esc(p.room)}» <b>окна на ${esc(dirn(p.side))}</b>${fl}.`) : '';
    if (failed || baseFail) {
      /* отель не прошёл обязательное условие: начинаем с него, зелёного «Берите» нет */
      line = esc(failed ? failLine(failed, mn) : cap(baseFail)) + '.'; cls = 'warn';
      if (p && (W.geo || W.none)) after = `<div class="tw-vd-2">Если отель всё же подходит: ${askLine.charAt(0).toLowerCase() + askLine.slice(1)}</div>`;
    } else if (W.none) {
      pre = '<div class="tw-vd-pre">Без запроса: оцениваем вид и тишину.</div>';
      if (!b) { line = esc(d.note || 'Категорий номеров в карточке нет. Смотрите вид и ночь ниже.'); cls = 'none' }
      else if (!p) { line = 'Просить нечего: по расчёту стороны не отличаются'; cls = 'none' }
      else line = sea > 0.5 ? (generic ? `Подойдёт ${anyCat(d)}. ${askLine}` : `Берите номер «${esc(p.room)}» и просите <b>окна на ${esc(dirn(p.side))}</b>${fl}.`) : sea === 0.5 ? `Море видно или нет: 50 на 50. ${askLine}` : `Моря, скорее всего, не будет. Лучший шанс: <b>окна на ${esc(dirn(p.side))}</b>${fl}.`;
      if (p && sea <= 0.5) cls = 'none';
    } else if (!W.geo) {
      /* гость просил не про вид и тишину: итог по его условиям, подбор номера ниже */
      const okc = cond.filter(c => c.status === 'pass' && !c.weak), list = okc.map(c => human(c, mn).toLowerCase()).join(', ');
      if (okc.length && okc.length === cond.length) line = `Подходит по ${okc.length} ${plural(okc.length, 'условию', 'условиям', 'условиям')}: ${esc(list)}.`;
      else if (okc.length) { line = `Подтверждено ${okc.length} из ${cond.length}: ${esc(list)}. Остальное пока не знаем.`; cls = 'none' }
      else { line = `Пока не подтверждено ни одно из ${cond.length} ${plural(cond.length, 'условия', 'условий', 'условий')}.`; cls = 'none' }
    } else if (!b) { line = esc(d.note || 'Категорий номеров в карточке нет. Смотрите вид и ночь ниже.'); cls = 'none' }
    else if (!p) { line = 'Просить нечего: по расчёту стороны не отличаются'; cls = 'none' }
    else if (W.sunset && !W.sea) {
      const wv = ctx.winV, sun = wv && wv.sun && wv.facade === p.side ? wv.sun : null;
      if (!sun) line = `Просите <b>окна на ${esc(dirn(p.side))}</b>${fl}.`;
      else if (sun.visible) line = `Просите <b>окна на ${esc(dirn(p.side))}</b>${fl}: закат в ${esc(MONTH_PREP[wv.month] || 'этом месяце')} ${sun.over_sea ? 'виден над морем' : 'виден над городом'}.`;
      else { line = `Закат в ${esc(MONTH_PREP[wv.month] || 'этом месяце')} из окон на ${esc(dirn(p.side))} не виден. Лучший шанс: <b>окна на ${esc(dirn(p.side))}</b>${fl}.`; cls = 'none' }
    } else if (W.sea || W.sunset) {
      if (sea > 0.5) line = generic ? `Подойдёт ${anyCat(d)}. ${askLine}` : `Берите номер «${esc(p.room)}» и просите <b>окна на ${esc(dirn(p.side))}</b>${fl}.`;
      else if (sea === 0.5) { line = `Море видно или нет: 50 на 50. ${askLine}`; cls = 'none' }
      else { line = `Моря, скорее всего, не будет. Лучший шанс: <b>окна на ${esc(dirn(p.side))}</b>${fl}.`; cls = 'none' }
    } else line = `${generic ? '' : `В номере «${esc(p.room)}» `}${generic ? 'Просите' : 'просите'} <b>окна на ${esc(dirn(p.side))}</b>${fl}: ночью там тише всего.`;
  }
  const cs = twChips(ctx); ctx.chips = cs;
  const open = el.querySelector('.tw-chip.on'), oi = open ? +open.dataset.chip : -1;
  el.className = 'tw-vd ' + cls;
  el.innerHTML = `${pre}<div class="tw-vd-l">${line}</div>${after}${cs.length ? `<div class="tw-chips">${cs.map((c, i) => c.cls === 'wait' ? `<span class="tw-chip wait">${esc(c.text)}</span>` : `<button type="button" class="tw-chip ${c.cls} ${i === oi ? 'on' : ''}" data-chip="${i}" aria-expanded="${i === oi}">${esc(c.text)}</button>`).join('')}</div><div class="tw-src" ${oi >= 0 && cs[oi] ? '' : 'hidden'}>${oi >= 0 && cs[oi] ? esc(cs[oi].tip) : ''}</div>` : ''}`;
}

/* ---------- вид из окна ---------- */
async function twWinLoad(ctx, params, opts) {
  const ws = ctx.ws, my = ++ws.token, q = new URLSearchParams({ month: ws.month });
  if (params.facade) q.set('facade', params.facade);
  if (params.floor) q.set('floor', params.floor);
  const pic = $('#twWin .tw-pic'); pic && pic.classList.add('busy');
  let w;
  try { w = await j(`/api/hotels/${enc(ctx.id)}/window?${q}`) }
  catch (e) {
    if (tw !== ctx || my !== ws.token) return;
    pic && pic.classList.remove('busy');
    if (opts.fromPick || ctx.win) { if (ctx.win) toast('Не удалось посчитать этот вид'); return }
    ctx.winErr = true; twErr(ctx, 'twWin', () => { ctx.winErr = false; twRetry(ctx, 'twWin', 150); twWinLoad(ctx, {}, { verdict: true, first: true }) }); drawVerdict(ctx); return;
  }
  if (tw !== ctx || my !== ws.token) return;
  ws.facade = w.facade; ws.floor = w.floor; if (w.month) ws.month = w.month;
  ctx.win = w; ctx.winErr = false;
  if (opts.verdict) ctx.winV = w;
  drawWin(ctx);
  if (opts.verdict) drawVerdict(ctx);
  if (opts.first) twWinForPick(ctx);
}
/* рекомендованная сторона известна, а на экране другая: один раз показываем вид из рекомендованного номера */
function twWinForPick(ctx) {
  const p = ctx.pick, w = ctx.win; if (!p || !w || ctx.touched || ctx.pickAsked) return;
  ctx.pickAsked = true;
  if (w.facade === p.side && (!p.floor || w.floor === p.floor)) return;
  twWinLoad(ctx, { facade: p.side, floor: p.floor }, { verdict: true, fromPick: true });
}
function drawWin(ctx) {
  const w = ctx.win, box = twBody('twWin'), ws = ctx.ws;
  if (!box.querySelector('.tw-wc')) {
    box.innerHTML = `<p class="tw-sub">Считаем по карте высот и зданиям OpenStreetMap. Выберите сторону, этаж и месяц.</p>
      <div class="tw-wc">
        <div class="tw-row"><span class="tw-lab" id="twFacL">Сторона</span><div class="tw-fac" id="twFac" role="group" aria-labelledby="twFacL"></div></div>
        <div class="tw-row" id="twFloorRow"><label class="tw-lab" for="twFloor">Этаж</label><div class="tw-fl"><input id="twFloor" type="range" min="1" step="1" value="1"><output id="twFn" for="twFloor"></output></div></div>
        <div class="tw-row"><label class="tw-lab" for="twMonth">Месяц</label><select id="twMonth">${MONTHS_NOM.map((m, i) => `<option value="${i + 1}">${cap(m)}</option>`).join('')}</select></div>
      </div><div class="tw-pic"></div>`;
  }
  $('#twFac').innerHTML = w.facades.map(f => `<button type="button" data-fac="${esc(f.dir)}" aria-pressed="${f.dir === w.facade}"><span>${esc(cap(f.name))}</span><small>${f.sea_from_floor ? `море ${atFl(f.sea_from_floor, w.levels)}` : 'моря нет'}</small></button>`).join('');
  const fl = $('#twFloor'); fl.max = w.levels; fl.value = w.floor; $('#twFn').textContent = w.floor;
  $('#twFloorRow').hidden = !(w.levels > 1);
  $('#twMonth').value = String(w.month || ws.month);
  const p = ctx.pick, picked = p && p.side === w.facade && (!p.floor || p.floor === w.floor);
  const sea = w.facades.find(f => f.dir === w.facade);
  const pic = $('#twWin .tw-pic'); pic.classList.remove('busy');
  pic.innerHTML = `<div class="tw-wchips">${(w.chips || []).slice(1).map(c => `<span>${esc(c)}</span>`).join('')}</div>${w.svg}
    ${picked ? '<div class="tw-pick">Это вид из номера, который мы советуем</div>' : ''}
    <p class="tw-cap">${esc(w.verdict || '')}</p>
    <p class="tw-note">Высоты соседних домов известны неточно, поэтому считаем много раз. ${w.note ? esc(w.note) + ' ' : ''}${sea && sea.sea_from_floor ? `Этаж, с которого видно море, оценён по 24 вариантам высот соседних домов, уверенность ${Math.round(sea.confidence * 100)}%. Ошибка возможна на несколько этажей. ` : ''}Это расчёт, на месте может отличаться.</p>`;
}

/* ---------- ночь по часам ---------- */
async function twNight(ctx) {
  try { ctx.night = await j(`/api/hotels/${enc(ctx.id)}/night`); ctx.nightErr = false }
  catch (e) { if (tw !== ctx) return; ctx.nightErr = true; twErr(ctx, 'twNight', () => { ctx.nightErr = false; twRetry(ctx, 'twNight', 110); twNight(ctx) }); drawVerdict(ctx); return }
  if (tw !== ctx) return;
  drawNight(ctx); drawVerdict(ctx);
}
function drawNight(ctx) {
  const n = ctx.night, ws = ctx.nightWin || n.window_assumed || 'closed', key = ws === 'open' ? 'indoor_open' : 'indoor_closed', box = twBody('twNight');
  const thr = n.threshold ? n.threshold.indoor_db : null, fs = n.facades || [];
  if (!fs.length) { box.innerHTML = '<p class="tw-note">Для этого здания ночной расчёт недоступен.</p>'; return }
  const mx = Math.max(...fs.flatMap(f => TW_NIGHT_HOURS.map(h => f[key][h])), thr || 0) || 1;
  const rows = fs.map(f => {
    const sl = f.sleep && f.sleep[ws], q = f.dir === n.quietest, l = f.dir === n.loudest && !q;
    const bars = TW_NIGHT_HOURS.map(h => { const v = f[key][h]; return `<i class="${thr != null && Math.ceil(v) > thr ? 'hi' : ''}" style="height:${Math.max(4, Math.round(v / mx * 100))}%" title="${h}:00, ${Math.ceil(v)} дБ в номере"></i>` }).join('');
    return `<div class="tw-nr ${q ? 'q' : ''}"><span class="tw-nd">${esc(cap(f.dir_name))}${q ? '<small>тише всего</small>' : l ? '<small>громче всего</small>' : ''}</span><span class="tw-bars" ${thr != null ? `style="--thr:${(thr / mx * 100).toFixed(1)}%"` : ''} role="img" aria-label="Шум по часам, сторона ${esc(f.dir_name)}">${bars}</span><span class="tw-nv">${sl ? (sl.at_floor && !(thr != null && Math.ceil(sl.night_mean_indoor) > thr) ? 'тихо' : Math.ceil(sl.night_mean_indoor) + ' дБ') : ''}</span></div>`;
  }).join('');
  const adv = (n.advice_by_window && n.advice_by_window[ws]) || n.advice || '';
  box.innerHTML = `<p class="tw-adv">${esc(adv)}</p>
    <div class="tw-seg" role="group" aria-label="Окно ночью"><button type="button" data-nw="closed" aria-pressed="${ws === 'closed'}">Окно закрыто</button><button type="button" data-nw="open" aria-pressed="${ws === 'open'}">Окно открыто</button></div>
    <div class="tw-nt"><div class="tw-ticks" aria-hidden="true"><span></span><span class="tw-tk">${TW_NIGHT_HOURS.map(h => `<i>${h % 3 === 0 ? h : ''}</i>`).join('')}</span><span class="tw-tkl">в номере</span></div>${rows}</div>
    <p class="tw-hon">Средний уровень в номере ночью, дБ. Светлые столбики: не громче ${thr != null ? thr : 30} дБ, тёмные: громче.${n.threshold ? ` ${esc(n.threshold.why)}.` : ''}</p>
    ${(n.uncertainty && n.uncertainty.length) || n.method ? `<details class="det"><summary>На что опирается расчёт</summary><ul class="tw-ev">${(n.uncertainty || []).map(x => `<li>${esc(x)}</li>`).join('')}${n.method ? `<li>${esc(cap(n.method))}</li>` : ''}</ul></details>` : ''}`;
}

/* ---------- заявления карточки против расчёта ---------- */
async function twClaims(ctx) {
  try { ctx.audit = await j(`/api/truth/audit/${enc(ctx.id)}`) }
  catch (e) { if (tw !== ctx) return; twErr(ctx, 'twClaims', () => { twRetry(ctx, 'twClaims', 60); twClaims(ctx) }); return }
  if (tw !== ctx) return;
  const a = ctx.audit, ORD = ['завышено', 'спорно', 'скрытая сильная сторона', 'подтверждено'], cls = { 'завышено': 'bad', 'спорно': 'conflict', 'скрытая сильная сторона': 'known', 'подтверждено': 'known' };
  const all = a.claims.slice().sort((x, y) => ORD.indexOf(x.verdict) - ORD.indexOf(y.verdict));
  const flagged = all.filter(c => c.verdict !== 'подтверждено');
  const ok = (a.counts && a.counts['подтверждено']) || 0, r = a.reputation;
  const head = !a.claims.length ? '<p class="tw-note">В карточке нет заявлений, которые можно проверить расчётом.</p>'
    : !flagged.length ? `<p class="tw-note">Расчёт подтвердил всё, что заявляет карточка (${a.claims.length} из ${a.claims.length}).</p>`
    : `<p class="tw-note">Расчёт подтвердил ${ok} из ${a.claims.length}. Под вопросом: ${flagged.length}.</p>`;
  const stamp = c => cst(c.confidence, { label: 'Устойчивость расчёта', cls: { 'спорно': 'amber', 'завышено': 'red' }[c.verdict] });
  twBody('twClaims').innerHTML = head + all.map(c => `<div class="tw-cl"><div class="tw-clh"><span class="st ${cls[c.verdict] || 'known'}">${esc(c.verdict)}</span><small>${esc(cap(c.kind))}</small>${c.confidence != null ? `<span class="cst-l">устойчивость расчёта</span>` : ''}${stamp(c)}</div>
      <p class="tw-clc">${esct(cap(c.who))}: ${esct(c.claim)}</p>${c.evidence && c.evidence.length ? `<ul class="tw-ev">${c.evidence.map(x => `<li>${esct(cap(outDb(x)))}</li>`).join('')}</ul>` : ''}</div>`).join('')
    + (r && r.checks > 0 ? `<p class="tw-hon">Отзывы совпали с расчётом в ${r.agree} из ${r.checks} проверок.</p>` : '');
}

/* ---------- события блоков ---------- */
(() => {
  const root = $('#shScroll'); let ft;
  root.addEventListener('click', e => {
    if (!tw) return;
    const t = e.target, b = t.closest('[data-copy],[data-chip],[data-fac],[data-nw],[data-retry]'); if (!b) return;
    if (b.dataset.copy != null) { vib(); twCopy(b, b.dataset.copy) }
    else if (b.dataset.chip != null) {
      const el = $('#twVd'), src = $('.tw-src', el), i = +b.dataset.chip, was = b.classList.contains('on');
      $$('.tw-chip', el).forEach(x => { x.classList.remove('on'); x.setAttribute('aria-expanded', 'false') });
      if (was || !tw.chips[i]) { src.hidden = true; return }
      b.classList.add('on'); b.setAttribute('aria-expanded', 'true'); src.textContent = tw.chips[i].tip; src.hidden = false;
    } else if (b.dataset.fac) { vib(); tw.touched = true; twWinLoad(tw, { facade: b.dataset.fac, floor: tw.ws.floor }, {}) }
    else if (b.dataset.nw) { tw.nightWin = b.dataset.nw; if (tw.night) drawNight(tw) }
    else if (b.dataset.retry) { const f = tw.retry[b.dataset.retry]; f && f() }
  });
  root.addEventListener('input', e => {
    if (!tw || e.target.id !== 'twFloor') return;
    tw.touched = true; tw.ws.floor = +e.target.value; $('#twFn').textContent = e.target.value;
    clearTimeout(ft); const c = tw; ft = setTimeout(() => { if (tw === c) twWinLoad(c, { facade: c.ws.facade, floor: c.ws.floor }, {}) }, 140);
  });
  root.addEventListener('change', e => {
    if (!tw || e.target.id !== 'twMonth') return;
    tw.touched = true; tw.ws.month = +e.target.value; twWinLoad(tw, { facade: tw.ws.facade, floor: tw.ws.floor }, {});
  });
})();

/* ================= профиль устройства: плотность и перестановка ================= */
(() => {
  let dirty = false;
  const run = async () => {
    dirty = false;
    if (!state.raw || !window.Arcade || document.body.classList.contains('arc-lock')) { dirty = !!state.raw; return }
    try {
      const t = await Arcade.tune(state.raw);
      const was = state.rows.map(r => r.hotel.id).join(), now = t.s.results.map(r => r.hotel.id).join();
      if (was !== now || t.density !== (state.tuned && state.tuned.density) || t.note !== (state.tuned && state.tuned.note)) applyResultsKeep(t);
    } catch (e) { }
  };
  const applyResultsKeep = t => { const tab = state.tab; applyResults(t, false); if (state.data.counts[tab]) { state.tab = tab; renderTabs(); renderList(true); renderMap(false) } };
  if (window.Sense && Sense.onChange) { let tm; Sense.onChange(() => { clearTimeout(tm); tm = setTimeout(run, 500) }) }
  new MutationObserver(() => { if (dirty && !document.body.classList.contains('arc-lock')) run() }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
})();

/* ================= ответ агента =================
   Быстрый поиск (/api/search) рисует карточки за секунды. Параллельно идёт настоящий агент (POST /api/chat: инструменты,
   сверка цифр, один ремонт), обычно 30-60 с. Ответ приходит отдельным блоком над выдачей; карточки его не ждут. */
const AGENT_TIMEOUT = 120000;
const ag = { seq: 0, ctrl: null, msgs: [], turns: [], busy: false, t0: 0, tick: null, err: '', asked: '', parsed: null, stage: 0, rid: '', poll: null, minH: 0 };
/* безопасный текст: экранируем всё, затем только **жирный**, абзацы и списки; «Минус:», «Попросите:» выделяем и без маркера */
const AGT_LBL = /^(Минус|Попросите|Какой номер брать):/;
function mdSafe(t) {
  const inl = x => esc(x).replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(AGT_LBL, '<b>$1:</b>');
  const out = []; let list = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null } };
  for (const raw of String(t || '').replace(/\r/g, '').split('\n')) {
    const ln = raw.trim();
    if (!ln) { close(); continue }
    let m;
    if ((m = /^(?:[-*•]|—)\s+(.*)$/.exec(ln))) { if (list !== 'ul') { close(); out.push('<ul>'); list = 'ul' } out.push(`<li>${inl(m[1])}</li>`) }
    else if ((m = /^\d+[.)]\s+(.*)$/.exec(ln))) { if (list !== 'ol') { close(); out.push('<ol>'); list = 'ol' } out.push(`<li>${inl(m[1])}</li>`) }
    else if ((m = /^#{1,4}\s+(.*)$/.exec(ln))) { close(); out.push(`<p><b>${inl(m[1].replace(/\*\*/g, ''))}</b></p>`) }
    else { close(); out.push(`<p>${inl(ln)}</p>`) }
  }
  close(); return out.join('');
}
/* одна строка о главном: первая содержательная строка без разметки */
function agentGist(t) {
  const ln = String(t || '').split('\n').map(x => x.replace(/^\s*(?:[-*•—]|\d+[.)]|#{1,4})\s*/, '').replace(/\*\*/g, '').trim()).find(x => x.length > 12) || '';
  return ln.length > 150 ? ln.slice(0, 150).replace(/\s+\S*$/, '') + '…' : ln;
}
/* короткое имя отеля для чипа: без типа заведения */
const KIND_RX = /^(?:(?:бутик|мини|апарт)[- ]?отель|отель|гостиница|гостиничный комплекс|комплекс апартаментов|апартаменты|санаторно-курортный комплекс|санаторий|пансионат)\s+/i;
const shortName = n => { let s = String(n || ''); for (let k = 0; k < 3 && KIND_RX.test(s); k++) s = s.replace(KIND_RX, ''); s = s.replace(/^[«"]|[»"]$/g, '').replace(/\s+(?:Sochi|Сочи)$/i, '').trim(); return s.length >= 3 ? s : String(n || '') };
function agentBadge(g) {
  if (!g || g.error || !g.before || !g.after) return '';
  const removed = (g.removed || []).length, bad = removed || g.before.unsupported, filled = (g.fetched || []).length;
  const ok = !removed;  // исправлено без потерь: спокойный вид, жёлтый только если что-то пришлось убрать
  const label = !bad ? (filled ? 'Цифры сверены, недостающие агент взял из расчётов' : 'Все цифры сверены с расчётами')
    : removed ? `Убрано после сверки: ${bad} ${plural(bad, 'утверждение', 'утверждения', 'утверждений')}`
      : `Сверено с расчётами · исправлено: ${bad}`;
  const gone = (g.removed || []).map(t => `<li class="g-no">${esc(String(t).replace(/^[-*•\s]+/, ''))}</li>`).join('');
  const checked = (g.after.claims || []).filter(c => c.supported).slice(0, 40);
  const rows = checked.map(c => `<li><span class="g-yes gi">${I.ok}</span> ${esc(c.text)}</li>`).join('');
  return `<details class="gnd ${ok ? 'ok' : 'fix'}"><summary>${ok ? `<span class="gi">${I.ok}</span>` : '<span class="gi" aria-hidden="true">⚠</span>'} ${label}</summary><div class="gb">`
    + (gone ? `<h4>Убрано из ответа</h4><ul>${gone}</ul>` : '')
    + (g.repaired ? '<p class="muted">Агент переписал ответ по сверенным данным.</p>' : '')
    + `<h4>Подтверждено (${checked.length} из ${g.after.total})</h4><ul>${rows || '<li class="muted">в ответе нет цифр для сверки</li>'}</ul></div></details>`;
}
const curData = () => state.dataSeq === state.seq ? state.data : null;  // выдача именно этого поиска, не прошлого
/* стадия для ленты О!ркады: пока агент работает, лента показывает его живую стадию */
window.waitStageNow = () => ag.busy ? ag.stage : null;
const stagesHTML = () => `<ol class="agt-st" aria-label="Что делает агент">${STAGES.map((s, i) => `<li class="${i < ag.stage ? 'done' : i === ag.stage ? 'now' : ''}"><i class="mk">${i < ag.stage ? I.ok : ''}</i><span>${s}</span></li>`).join('')}</ol>`;
function agentStage(k) {
  if (k <= ag.stage) return;
  ag.stage = k;
  $$('#agent .agt-st li').forEach((li, i) => { li.className = i < k ? 'done' : i === k ? 'now' : ''; li.firstChild.innerHTML = i < k ? I.ok : '' });
  const w = $('#agent .agt-wst'); if (w) w.textContent = STAGES[k];
}
/* живая стадия с сервера (по id запуска); не ответил — стоим на последней известной */
function agentPoll(on) {
  clearInterval(ag.poll); ag.poll = null; if (!on) return;
  const rid = ag.rid, seq = ag.seq;
  ag.poll = setInterval(async () => {
    if (!ag.busy || seq !== ag.seq || rid !== ag.rid) { agentPoll(false); return }
    try { const d = await j('/api/chat/progress?run=' + encodeURIComponent(rid)); if (ag.busy && rid === ag.rid && typeof d.stage === 'number') agentStage(Math.min(d.stage, STAGES.length - 1)) } catch (e) { }
  }, 1000);
}
/* карточка выбора агента: фото, имя, почему (из данных карточки), цена на дату */
function pickHTML(id) {
  const r = state.byId.get(id), h = r.hotel, ev = evList(r);
  const pro = ev.all.find(e => e.t === 'good'), con = ev.all.find(e => e.t === 'bad');
  const nm = e => e.name || cap(e.body).slice(0, 40);
  const why = pro ? `${cap(nm(pro))}${con ? ` · минус: ${nm(con).toLowerCase()}` : ''}` : con ? `Минус: ${nm(con).toLowerCase()}` : 'Подробности внутри';
  const price = h.price_nov1 ? `<span class="agt-pp"><b>${money(h.price_nov1)}</b><small>цена на 1 ноября</small></span>` : '<span class="agt-pp na">Цены на даты нет</span>';
  return `<button type="button" class="agt-pick" data-id="${esc(id)}"><span class="agt-pph ${h.photo ? '' : 'noimg'}">${h.photo ? `<img src="${esc(h.photo)}" alt="" loading="lazy" decoding="async">` : ''}</span><span class="agt-pb"><b>${esc(shortName(h.name))}</b><span class="agt-pw">${esc(why)}</span>${price}</span></button>`;
}
/* "Отели, которые агент проверял: N" и состояние страницы вокруг героя: агент ведёт, пока работает или ответил */
function agentLead() {
  const cur = curData(), lead = !!ag.asked && state.llm && !cur?.off_region && (ag.busy || ag.turns.some(t => t.role === 'agent'));
  const work = lead && ag.busy && !ag.turns.some(t => t.role === 'agent');
  document.body.classList.toggle('agt-lead', lead); document.body.classList.toggle('agt-work', work);
  const h = $('#agtSecH'), n = cur?.counts?.match || 0;
  if (h) { h.hidden = !(lead && n); h.textContent = `Отели, которые агент проверял: ${n}` }
}
function agentRender() {
  const box = $('#agent'); if (!box) return;
  if (!ag.asked || curData()?.off_region) { box.innerHTML = ''; agentLead(); return }
  if (!state.llm) { box.innerHTML = '<section class="agt agt-off"><span class="agt-k">Ответ агента</span><p>Агент сейчас выключен. Карточки ниже подобраны по вашим условиям.</p></section>'; agentLead(); return }
  const last = ag.turns.map(t => t.role).lastIndexOf('agent'), hasA = last >= 0;
  const prev = box.firstElementChild, wasWork = prev && prev.classList.contains('is-work');
  if (wasWork && prev.offsetHeight) ag.minH = prev.offsetHeight;  // ответ не ниже ожидания: страница под ним не прыгает
  const turns = ag.turns.map((t, i) => {
    if (t.role === 'user') return `<p class="agt-q">${esc(t.text)}</p>`;
    const recs = (t.rec || []).filter(id => state.byId.has(id));
    const latest = i === last, open = !!t.full;
    const body = !latest && !open ? `<p class="agt-sum">${esc(agentGist(t.text))}</p>` : `<div class="agt-t${latest && !open ? ' cap' : ''}">${mdSafe(t.text)}</div>`;
    const more = `<button type="button" class="agt-more" data-i="${i}" aria-expanded="${open}"${latest && !open ? ' hidden' : ''}>${open ? 'Свернуть' : 'Весь ответ'}</button>`;
    const picks = latest && recs.length ? `<div class="agt-picks"><span class="agt-pk">Агент советует</span><div class="agt-pg" style="--n:${Math.min(3, recs.length)}">${recs.slice(0, 3).map(pickHTML).join('')}</div></div>` : '';
    const chips = !latest && open && recs.length ? `<div class="agt-recs"><span>Агент советует:</span>${recs.map(id => `<button type="button" class="agt-rec" data-id="${esc(id)}">${esc(shortName(state.byId.get(id).hotel.name))}</button>`).join('')}</div>` : '';
    return `<div class="agt-a${picks ? ' agt-a2' : ''}" data-i="${i}">${body}${more}${picks}${chips}${latest || open ? agentBadge(t.g) : ''}</div>`;
  }).join('');
  const secs = () => Math.round((Date.now() - ag.t0) / 1000);
  /* первое ожидание: стадии, секунды, игра и контур будущего ответа; повторный вопрос: короткая строка */
  const work = !ag.busy ? '' : hasA ? `<div class="agt-w"><span class="agt-spin" aria-hidden="true"></span><p><b class="agt-wst">${STAGES[ag.stage]}</b><span class="agt-sec"> · прошло ${secs()} с</span></p></div>`
    : `<div class="agt-wk"><div><div class="agt-prog">${stagesHTML()}<p class="agt-wl">Агент сверяет факты по карте, рельефу и отзывам. Обычно 10–30 секунд<span class="agt-sec"> · прошло ${secs()} с</span></p>${window.Arcade ? `<button type="button" class="btn btn-lime js-play" data-game="${WAIT_GAME}">Сыграть, пока ждём</button>` : ''}</div>
      <div class="agt-gh" aria-hidden="true"><i></i><i></i><i></i><i class="s"></i><i></i><i></i><i></i><i class="s"></i><i></i><i></i><i class="s"></i></div></div><div class="agt-gp" aria-hidden="true"><i></i><i></i><i></i></div></div>`;
  const err = ag.err ? `<p class="agt-err">${esc(ag.err)}</p>` : '';
  const form = hasA ? `<form class="agt-f" id="agtF"><input id="agtI" type="text" enterkeyhint="send" autocomplete="off" placeholder="Например: какой номер там брать?" aria-label="Уточнить у агента" maxlength="500"${ag.busy ? ' disabled' : ''}><button type="submit" class="btn btn-blue"${ag.busy ? ' disabled' : ''}>Спросить</button></form>` : '';
  const keep = $('#agtI') ? $('#agtI').value : '';
  const lone = !hasA && !ag.busy;  // ответа нет и не будет (ошибка): тихая плашка, карточки впереди
  const mh = hasA && ag.minH ? ` style="min-height:${ag.minH}px"` : '';
  box.innerHTML = `<section class="agt agt-hero ${ag.busy && !hasA ? 'is-work' : lone ? 'is-fb' : 'is-done'}"${mh}><div class="agt-h"><h2 class="agt-k">Ответ агента</h2><small>проверяет каждую цифру по расчётам</small></div>${turns}${work}${err}${form}</section>`;
  if ($('#agtI') && keep) $('#agtI').value = keep;
  agentLead();
  /* «Весь ответ» только на узком экране и только если текст реально длиннее лимита (на широком ответ раскрыт целиком) */
  box.querySelectorAll('.agt-t.cap').forEach(el => { if (el.scrollHeight <= el.clientHeight + 4) el.classList.remove('cap'); else el.parentElement.querySelector('.agt-more').hidden = false });
}
function agentTimer(on) {
  clearInterval(ag.tick); ag.tick = null;
  if (on) ag.tick = setInterval(() => { const e = $('.agt-sec'); if (e) e.textContent = ` · прошло ${Math.round((Date.now() - ag.t0) / 1000)} с`; else if (!ag.busy) agentTimer(false) }, 1000);
}
async function agentAsk(msgs, seq, parsed) {
  if (ag.ctrl) ag.ctrl.abort();
  const ctrl = ag.ctrl = new AbortController(); let timedOut = false;
  const to = setTimeout(() => { timedOut = true; ctrl.abort() }, AGENT_TIMEOUT);
  ag.busy = true; ag.err = ''; ag.t0 = Date.now(); ag.stage = 0; ag.rid = SID + Math.random().toString(36).slice(2, 8); agentRender(); agentTimer(true); agentPoll(true);
  const t0 = performance.now();
  try {
    const r = await fetch('/api/chat', { method: 'POST', signal: ctrl.signal, headers: { 'Content-Type': 'application/json', 'X-Session': SID }, body: JSON.stringify({ messages: msgs.slice(-12), run: ag.rid, ...(parsed ? { parsed } : {}) }) });
    if (!r.ok) throw new Error('chat ' + r.status);
    const d = await r.json();
    if (seq !== ag.seq) return;
    if (d.mode === 'rules') { ag.err = 'Агент сейчас недоступен. Карточки ниже подобраны по вашим условиям.'; return }
    const rec = (d.recommended || []).map(String);
    ag.msgs = [...msgs, { role: 'assistant', content: d.text || '' }];
    ag.turns.forEach(t => { t.full = false });
    ag.turns.push({ role: 'agent', text: d.text || '', g: d.grounding || null, rec, full: false });
    rec.forEach(id => state.agentIds.add(id));
    track('agent', { ms: Math.round(performance.now() - t0), rec: rec.length });
    if (state.data) renderList(false);  // пометки «Агент советует», выбранные отели первыми
  } catch (e) {
    if (seq !== ag.seq) return;
    ag.err = timedOut ? 'Агент не успел ответить за 2 минуты. Карточки ниже подобраны по вашим условиям. Чтобы спросить агента снова, повторите поиск.' : 'Не удалось получить ответ агента. Карточки ниже на месте.';
    if (ag.turns.length && ag.turns[ag.turns.length - 1].role === 'user') ag.turns.pop();
  } finally {
    clearTimeout(to);
    if (seq === ag.seq) { ag.busy = false; agentTimer(false); agentPoll(false); agentRender() }
  }
}
/* raw: ответ быстрого поиска. Агент ищет по тому же разбору (parsed), чтобы число и набор отелей совпадали с карточками;
   другой город (off_region) — агент не нужен, LLM не тратим */
function agentStart(q, raw) {
  if (ag.ctrl) ag.ctrl.abort();
  const seq = ++ag.seq;
  Object.assign(ag, { msgs: [], turns: [], err: '', busy: false, asked: q, parsed: raw?.parsed || null, stage: 0, minH: 0 });
  state.agentIds = new Set();
  if (raw?.off_region) { agentTimer(false); ag.asked = ''; agentRender(); return }
  if (!state.llm) { agentTimer(false); agentRender(); return }
  agentAsk([{ role: 'user', content: q }], seq, ag.parsed);
  if (!isDesk()) requestAnimationFrame(() => { const h = $('#agent section'); if (h && h.getBoundingClientRect().top > innerHeight * .6) h.scrollIntoView({ block: 'start', behavior: reduced ? 'auto' : 'smooth' }) });  // на телефоне агент первым в кадре
}
if ('IntersectionObserver' in window) new IntersectionObserver(es => $('#mapfab').classList.toggle('over-agent', es[0].isIntersecting && !!$('#agent').firstChild)).observe($('#agent'));  /* D5 */
$('#agent').addEventListener('submit', e => {
  e.preventDefault();
  const i = $('#agtI'), v = i && i.value.trim(); if (!v || ag.busy) return;
  i.value = '';
  ag.turns.push({ role: 'user', text: v });
  agentAsk([...ag.msgs, { role: 'user', content: v }], ag.seq);
});
$('#agent').addEventListener('click', e => {
  const b = e.target.closest('.agt-rec,.agt-pick'); if (b) { vib(); openHotel(b.dataset.id); return }
  const m = e.target.closest('.agt-more'); if (m) { const t = ag.turns[+m.dataset.i]; if (t) { t.full = !t.full; agentRender() } }
});

/* ================= запуск ================= */
(async () => {
  recheckImgs(); setCompact(); updateDock();
  try {
    const st = await j('/api/status'); state.llm = st.llm !== false;
    heroPM(st.hotels); if (st.osm_base) DATES.osm = dshort(st.osm_base);
    $('#footMeta').textContent = `Прототип хакатона Островка. ${cap(st.zone || 'Центр Сочи')}: ${st.hotels} ${plural(st.hotels, 'отель', 'отеля', 'отелей')}, ${st.characteristics} ${plural(st.characteristics, 'характеристика', 'характеристики', 'характеристик')}. Факты считаются по картам OpenStreetMap, рельефу Copernicus, данным Open-Meteo, карточкам и отзывам Островка.`;
  } catch (e) { }
  const qp = new URLSearchParams(location.search), q = qp.get('q');
  const hid = qp.get('hotel') || (/[#&]hotel=(\d+)/.exec(location.hash) || [])[1];
  if (q) await runSearch(q);
  if (hid) openById(hid);
})();

/* Ссылка на отель: ?hotel=ID или #hotel=ID открывает карточку; если отеля нет в выдаче, строка собирается из списка отелей. */
async function openById(id) {
  if (!state.byId.has(id)) {
    try {
      const h = (await j('/api/hotels')).find(x => String(x.id) === String(id)); if (!h) return;
      state.byId.set(h.id, { hotel: h, bucket: 'maybe', good: [], bad: [], unknown: [] });
    } catch (e) { return }
  }
  openHotel(String(id));
}
/* «Стереть мои данные» в подвале: подстройка выключается, всё о посетителе удаляется на сервере */
{ const b = $('#footForget'); if (b) b.onclick = () => { if (window.Sense && Sense.optOut) { Sense.optOut(true); toast('Данные о вас стёрты, выдача больше не подстраивается.') } } }
})();
