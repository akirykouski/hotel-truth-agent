// Движок правды в интерфейсе: вкладка «Проверка обещаний», репутация отельера и «кому поверили» на карточке отеля.
// Подключается одной строкой в index.html, стили добавляет сам.
(function(){
const css=`
.tr-v{display:inline-block;font-size:11px;padding:1px 8px;border-radius:99px;font-weight:600;white-space:nowrap}
.tr-ok{background:var(--ok-soft);color:var(--ok)}.tr-hid{background:var(--ok-soft);color:var(--ok);box-shadow:inset 0 0 0 1px var(--ok)}.tr-over{background:var(--bad-soft);color:var(--bad)}.tr-dis{background:var(--warn-soft);color:var(--warn)}
.tr-claim{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:8px 0;display:grid;grid-template-columns:minmax(120px,max-content) 1fr;gap:4px 16px}
.tr-claim .ev{font-size:12px;color:var(--muted);margin-top:4px}.tr-claim .ev div{margin:2px 0}
.tr-rep{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:10px 0;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.tr-rep b{font-size:20px}.tr-bar{width:90px;height:7px;background:var(--line);border-radius:4px}.tr-bar i{display:block;height:7px;border-radius:4px}
.tr-why{font-size:12px;margin-top:4px;color:var(--muted)}.tr-why b{color:var(--ink)}
.tr-row{display:grid;grid-template-columns:1fr auto;gap:6px 12px;padding:8px 0;border-bottom:1px solid var(--line)}
.tr-row:last-child{border-bottom:0}
.tr-sum{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:10px 0}.tr-sum div{border:1px solid var(--line);border-radius:12px;padding:10px 12px}.tr-sum b{font-size:22px;display:block}
.tr-pairs{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center}.tr-pairs span{white-space:nowrap}
.tr-claim.tr-o{border-left:4px solid var(--bad)}.tr-claim.tr-h{border-left:4px solid var(--ok)}
.tr-claim .tr-q{overflow-wrap:anywhere}
.tr-sec{margin:16px 0 4px;font-weight:600}.tr-sec small{font-weight:400;color:var(--muted)}
details.tr-fold{margin:12px 0}details.tr-fold summary{cursor:pointer;font-weight:600;padding:6px 0}
.tr-say{font-size:13px;margin-top:4px}
.tr-act{margin-top:8px}.tr-act button{min-height:36px}.tr-sent{font-weight:600;color:var(--ok);font-size:13px}.tr-sum small{display:block;font-size:12px;color:var(--muted);margin-top:2px}.tr-sum .tr-zero{color:var(--muted)}
@media(max-width:600px){.tr-claim{grid-template-columns:1fr}.tr-sum{grid-template-columns:1fr 1fr}.tr-sum b{font-size:18px}}
`;
const st=document.createElement('style');st.textContent=css;document.head.appendChild(st);

const VC={'подтверждено':'tr-ok','завышено':'tr-over','скрытая сильная сторона':'tr-hid','спорно':'tr-dis'};
const VS=['завышено','скрытая сильная сторона','подтверждено','спорно'];
const cm=x=>String(x).replace(/(\d)\.(\d)/g,'$1,$2');
const pair=(v,n)=>`<span>${verdict(v)} ${n||0}</span>`;
const pairs=c=>`<div class="tr-pairs small">${VS.filter(v=>c[v]).map(v=>pair(v,c[v])).join('')||'<span class="muted">заявлений для проверки нет</span>'}</div>`;
const verdict=v=>`<span style="white-space:nowrap" class="tr-v ${VC[v]||'tr-dis'}">${esc(v)}</span>`;
const CLS={physical:'измеряется',policy:'решает отель',experiential:'мнение гостей'};
const trustColor=t=>t>=0.8?'var(--ok)':t>=0.5?'var(--warn)':'var(--bad)';
const repBox=r=>{
  const t=r.trust,n=r.checks;
  return `<div class="tr-rep"><div><div class="muted small">Доверие к отельеру</div><b style="color:${n?trustColor(t):'var(--muted)'}">${n?cm(t.toFixed(2)):'—'}</b></div>
  <div class="tr-bar"><i style="width:${Math.round((n?t:1)*100)}%;background:${n?trustColor(t):'var(--line)'}"></i></div>
  <div class="small" style="flex:1;min-width:200px">${esc(r.label)}.${n&&t<1?' Каждое расхождение с надёжным расчётом снижает вес всех ответов этого отельера.':''}
  ${(r.details||[]).filter(d=>!d.agree).map(d=>`<div class="bad">${esc(d.name)}: отельер сказал «${d.claim?'да':'нет'}», расчёт «${d.physics?'да':'нет'}» (${cm(d.physics_conf.toFixed(2))})</div>`).join('')}</div></div>`};

// вкладка и секция
const nav=document.getElementById('nav'),main=document.querySelector('main');
nav.insertAdjacentHTML('beforeend','<button data-t="audit">Проверка обещаний</button>');
main.insertAdjacentHTML('beforeend',`<section class="tab" id="t-audit"><div class="card"><h2>Проверка обещаний</h2>
  <div class="muted small">Что отель пишет о себе (описание, категории номеров, ответы отельера) и что подтверждается расчётом, картой и отзывами. Само заявление в оценку не засчитываем: сверяем его только с другими источниками.</div>
  <div class="row" style="margin-top:10px"><input id="afind" placeholder="название отеля"><button class="g" onclick="findHotel('afind','alist',openAudit)">Найти</button>
  <button class="g" onclick="auditOverview()">Где больше всего спорного</button></div><div id="alist"></div><div id="aout"></div></div></section>`);
const _show=window.show;
let direct=false;
window.show=function(t){_show(t);if(t=='audit'&&!direct&&!document.getElementById('aout').innerHTML)auditOverview()};

window.auditOverview=async function(){
  const o=document.getElementById('aout');o.innerHTML='<div class="muted" style="margin-top:10px">Проверяю все отели…</div>';
  const d=await api('/api/truth/audit?limit=25'),t=d.totals;
  const tile=(v,label,cls,note)=>`<div><b class="${cls}">${v}</b>${label}${note?`<small>${note}</small>`:''}</div>`;
  const over=t['завышено'];
  o.innerHTML=`<div class="tr-sum">${tile(t['спорно'],'спорно','',"проверить нечем или данные слабые").replace('<b class="">','<b style="color:var(--warn)">')}
  ${tile(t['скрытая сильная сторона'],'карточка молчит, расчёт уверенно видит море','ok')}${tile(t['подтверждено'],'подтверждено','ok')}
  ${tile(over,'завышено',over?'bad':'tr-zero',over?'':'ни одно заявление не опровергнуто надёжным расчётом')}</div>
  <div class="small muted">Проверено отелей: ${d.hotels}, с замечаниями: ${d.hotels_with_issues}. Сначала те, где заявления дальше всего от расчёта.</div>
  ${d.worst.map(r=>`<div class="tr-row"><div><b>${esc(r.hotel.name)}</b>${r.top?`<div class="small muted">${esc(r.top.claim)}</div><div class="small">${esc(r.top.evidence[0]||'')}</div>`:''}</div>
   <div style="text-align:right">${r.counts['завышено']?pair('завышено',r.counts['завышено']):''} ${r.counts['спорно']?pair('спорно',r.counts['спорно']):''}<br><button class="g" style="margin-top:4px" onclick="openAudit('${r.hotel.id}')">Разбор</button></div></div>`).join('')}`};

window.openAudit=async function openAudit(id){
  direct=true;show('audit');direct=false;const o=document.getElementById('aout');o.innerHTML='<div class="muted" style="margin-top:10px">Считаю…</div>';
  const d=await api('/api/truth/audit/'+id),c=d.counts;
  const sec=(v,title,note,open)=>{const xs=d.claims.filter(x=>x.verdict==v);if(!xs.length)return '';
    const body=xs.map(x=>claimBox(x,d.hotel.id)).join('');
    return open?`<div class="tr-sec">${esc(title)} <small>${esc(note)}</small></div>${body}`
      :`<details class="tr-fold"><summary>${esc(title)}: ${xs.length}</summary>${body}</details>`};
  o.innerHTML=`<h3 style="margin-top:14px">${esc(d.hotel.name)} <button class="g" onclick="openHotel('${d.hotel.id}')">Карточка</button> <button class="g" onclick="auditOverview()">Назад к списку</button></h3>
  ${pairs(c)}
  ${d.reputation.checks?repBox(d.reputation):''}
  ${d.claims.length?sec('завышено','Завышено','заявлено больше, чем показывает расчёт',true)+sec('скрытая сильная сторона','Скрытые сильные стороны','карточка молчит, а расчёт уверенно видит море',true)
    +sec('подтверждено','Подтверждено','',false)+sec('спорно','Спорно','проверить нечем или данные слабые',false)
   :'<div class="muted" style="margin-top:10px">Проверяемых заявлений нет: нечем сверить слова отеля.</div>'}`};
const claimBox=(x,hid)=>`<div class="tr-claim ${x.verdict=='завышено'?'tr-o':x.verdict=='скрытая сильная сторона'?'tr-h':''}"><div class="small muted">${esc(x.kind)}</div>
   <div><b class="tr-q">${esc(x.claim)}</b> <span class="muted small">(${esc(x.who)})</span><div class="ev">${x.evidence.map(e=>`<div>${esc(e)}</div>`).join('')}</div>${actBtn(x,hid)}</div></div>`;
const actBtn=(x,hid)=>{
  if(x.verdict=='спорно'||x.verdict=='завышено')return `<div class="tr-act"><button class="g" onclick="trAct(this,'ask','${hid}','${x.char}')">Спросить отельера</button></div>`;
  if(x.verdict=='скрытая сильная сторона')return `<div class="tr-act"><button class="g" onclick="trAct(this,'suggest','${hid}','${x.char}')">Предложить дописать в карточку</button></div>`;
  return ''};
window.trAct=async function(btn,kind,hid,cid){
  btn.disabled=true;
  try{
    const r=await fetch(kind=='ask'?`/api/hotels/${hid}/ask`:`/api/truth/suggest/${hid}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({char_id:cid})});
    if(!r.ok)throw 0;
    btn.parentNode.innerHTML=`<span class="tr-sent">${kind=='ask'?'Вопрос отправлен отельеру: ответ появится в его кабинете':'Предложение записано: отелю передадим, что дописать в карточку'}</span>`;
  }catch(e){btn.disabled=false;btn.parentNode.insertAdjacentHTML('beforeend',' <span class="bad small">Не получилось отправить, попробуйте ещё раз</span>')}
};

// карточка отеля: репутация отельера и «кому поверили» по каждой характеристике
const _open=window.openHotel;
window.openHotel=async function openHotel(id){
  await _open(id);
  try{
    const [t,a]=await Promise.all([api('/api/truth/hotel/'+id),api('/api/truth/audit/'+id)]);
    const box=document.getElementById('hotel');if(!box)return;
    const rows=t.chars.filter(c=>c.status=='conflict'||c.hotelier);
    const html=(t.reputation.checks?repBox(t.reputation):'')+
     (rows.length?`<h3>Кому мы поверили</h3>${rows.map(c=>`<div class="tr-row"><div><b>${esc(c.name)}</b> <span class="muted small">${esc(CLS[c.class]||c.class)}</span>${c.sentence?`<div class="tr-say">${esc(c.sentence)}</div>`:''}<div class="tr-why">${esc(c.why)}</div></div><div style="white-space:nowrap">${c.sentence?'<span class="badge bf">спорно</span>':''} ${cm(conf(c.confidence))}</div></div>`).join('')}`:'')+
     `<div class="small" style="margin-top:8px"><div style="margin-bottom:6px">Проверка обещаний:</div>${pairs(a.counts)} <button class="g" style="margin-top:6px" onclick="openAudit('${id}')">Разбор</button></div>`;
    const h3=[...box.querySelectorAll('h3')].find(e=>e.textContent.startsWith('Что мы знаем'));
    if(h3)h3.insertAdjacentHTML('beforebegin',html);
  }catch(e){}
};

// кабинет отельера: репутация
const _cab=window.openCabinet;
window.openCabinet=async function openCabinet(id){
  await _cab(id);
  try{const d=await api('/api/hotelier/'+id);const cab=document.getElementById('cab');const k=cab.querySelector('.kpi');
    if(k)k.insertAdjacentHTML('afterend',repBox(d.reputation));}catch(e){}
};
})();
