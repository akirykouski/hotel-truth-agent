// Радар изменений: панель на вкладке «Актуализация и журнал». Стили вставляются отсюда.
(function(){
const css=`
#radar .rh{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
#radar .rh h2{margin:0}
#radar .rf{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
#radar .rf .chip.off{background:var(--unk-soft);color:var(--unk)}
#radar .ra{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:8px 0;border-left-width:4px}
#radar .ra.high{border-left-color:var(--bad)}#radar .ra.medium{border-left-color:var(--warn)}#radar .ra.low{border-left-color:var(--unk)}
#radar .rt{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
#radar .rt a{font-weight:600;color:var(--acc);cursor:pointer;text-decoration:none}
#radar .rk{font-size:11px;padding:1px 8px;border-radius:99px;background:var(--acc-soft);color:var(--acc)}
#radar blockquote{margin:6px 0 0;padding:4px 10px;border-left:3px solid var(--line);color:var(--ink);font-size:12.5px;overflow-wrap:anywhere}
#radar blockquote span{color:var(--muted);margin-right:6px;white-space:nowrap}
#radar .rknown{margin-top:12px}#radar .rknown summary{cursor:pointer;font-weight:600;min-height:36px;display:flex;align-items:center}
#radar .rb{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px}
#radar .rb button{min-height:36px}
@media(max-width:600px){#radar .rb button{width:100%;min-height:44px}#radar .rb{align-items:stretch}}
`;
const st=document.createElement('style');st.textContent=css;document.head.appendChild(st);
const sec=document.getElementById('t-log');
const card=document.createElement('div');card.className='card';card.id='radar';card.style.marginBottom='16px';
card.innerHTML='<div class="rh"><h2>Радар изменений</h2><span class="muted small" id="rsub"></span></div>'+
 '<div class="muted small">Радар следит, что поменялось вокруг отеля: всплеск жалоб в свежих отзывах, просевшая оценка, стройка рядом на снимке OSM, истёкший срок факта. У каждого сигнала есть даты и цитаты.</div>'+
 '<div class="rf" id="rfilter"></div><div id="rlist"><div class="muted">Сканирую…</div></div>';
sec.insertBefore(card,sec.firstChild);

const KIND={review_spike:'всплеск жалоб',rating_drift:'падение оценки',osm_construction:'стройка рядом',stale_fact:'факт устарел'};
const SEV={high:['высокая','bf'],medium:['средняя','bq'],low:['низкая','bu']};
let data=null,off=new Set(),more=false;const LIM=6;
const e=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const dt=d=>String(d||'').split('-').reverse().join('.');
const pl=(n,a,b,c)=>{n=Math.abs(n);const m=n%10,h=n%100;return m==1&&h!=11?a:(m>=2&&m<=4&&(h<12||h>14)?b:c)};

function view(){
  const s=data.summary;
  document.getElementById('rsub').textContent=`${s.alerts} ${pl(s.alerts,'сигнал изменений','сигнала изменений','сигналов изменений')} в ${s.hotels_with_alerts} из ${s.hotels_total} ${pl(s.hotels_total,'отеля','отелей','отелей')} · окно ${data.window_days} дней`;
  document.getElementById('rfilter').innerHTML=Object.entries(s.by_kind).map(([k,n])=>`<button class="chip${off.has(k)?' off':''}" data-k="${k}">${e(KIND[k]||k)} ${n}</button>`).join('')||'<span class="muted small">Сигналов нет.</span>';
  const list=data.alerts.filter(a=>!a.known&&!off.has(a.kind));
  const known=data.alerts.filter(a=>a.known);
  const shown=more?list:list.slice(0,LIM);
  document.getElementById('rlist').innerHTML=(shown.map(card_).join('')||'<div class="muted">Ничего не показано.</div>')+
   (list.length>LIM?`<div class="rb"><button class="g" data-more="1">${more?'Свернуть':'Показать ещё '+(list.length-LIM)}</button></div>`:'')+
   (known.length?`<details class="rknown"><summary>Стройки на снимке OSM от ${dt(data.osm_base)}: ${known.length}</summary><div class="muted small">Эти стройки уже учтены в фактах отелей, это не новые изменения.</div>${known.map(card_).join('')}</details>`:'');
}
function btn(a){
  if(a.state=='queued')return '<span class="ok small">Вопрос в очереди у отельера</span>';
  if(a.state=='answered')return '<span class="ok small">Отельер ответил</span>';
  if(a.state=='event_only')return '<span class="muted small">Записано в журнал</span>';
  return `<button class="b" data-id="${e(a.id)}">${a.char_id?'Отправить вопрос отельеру':'Записать в журнал'}</button>`;
}
function card_(a){
  const [sl,sc]=SEV[a.severity]||SEV.low,ev=a.evidence;
  return `<div class="ra ${a.severity}"><div class="rt"><span class="badge ${sc}">${sl}</span><span class="rk">${e(KIND[a.kind]||a.kind)}</span>
   <a data-h="${e(a.hotel_id)}">${e(a.hotel_name)}</a></div>
   <div class="small" style="margin-top:4px"><b>${e(a.title)}</b>. ${e(ev.text)}</div>
   ${(ev.quotes||[]).map(q=>`<blockquote><span>${dt(q.date)}</span>${e(q.quote)}</blockquote>`).join('')}
   <div class="rb" id="rb-${e(a.id)}">${btn(a)}</div></div>`;
}
async function load(){
  try{data=await api('/api/radar');view()}catch(x){document.getElementById('rlist').innerHTML='<div class="bad">Ошибка: '+e(x.message)+'</div>'}
}
card.addEventListener('click',async ev=>{
  const t=ev.target,k=t.dataset&&t.dataset.k,h=t.dataset&&t.dataset.h,id=t.dataset&&t.dataset.id;
  if(t.dataset&&t.dataset.more){more=!more;view()}
  else if(k){off.has(k)?off.delete(k):off.add(k);view()}
  else if(h){openHotel(h)}
  else if(id){
    const box=t.parentNode;t.disabled=true;t.textContent='Отправляю…';
    try{
      const r=await api('/api/radar/apply',{ids:[id]}),x=r.results[0],a=data.alerts.find(a=>a.id==id);
      a.state=x.state=='queued'||x.state=='already_queued'?'queued':'event_only';
      box.innerHTML=x.state=='queued'?'<span class="ok small">Вопрос в очереди у отельера'+(x.marked_facts?`, на перепроверку отправлено ${x.marked_facts} ${pl(x.marked_facts,'факт','факта','фактов')}`:'')+'</span>'
        :x.state=='already_queued'?'<span class="ok small">Такой вопрос уже в очереди у отельера</span>'
        :x.state=='budget_full'?'<span class="bad small">У отеля уже 3 важных вопроса, этот не вошёл</span>'
        :'<span class="muted small">Записано в журнал, вопрос не нужен: сигнал без характеристики</span>';
    }catch(x){t.disabled=false;t.textContent='Повторить';box.insertAdjacentHTML('beforeend','<span class="bad small">Ошибка: '+e(x.message)+'</span>')}
  }
});
document.getElementById('nav').addEventListener('click',ev=>{if(ev.target.dataset.t=='log')load()});
if(sec.classList.contains('on'))load();
})();
