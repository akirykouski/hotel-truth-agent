// Фото как независимый датчик: миниатюры с метками в карточке отеля и блок «сверка с фото» в метриках.
(function(){
const st=document.createElement('style');
st.textContent=`.ph{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:6px}
.ph figure{margin:0;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--card)}
.ph img{width:100%;height:96px;object-fit:cover;display:block;background:var(--line)}
.ph figcaption{padding:6px 8px;font-size:12px;line-height:1.35}.ph .k{color:var(--muted);font-size:11px}
.ph .sea{border-color:var(--ok)}.ph .sea figcaption{background:var(--ok-soft)}
@media(max-width:600px){.ph{grid-template-columns:repeat(2,1fr)}.ph img{height:84px}}`;
document.head.appendChild(st);
if(typeof SRC!=='undefined')SRC['фото отеля']='📷';
const KIND={room:'номер',balcony:'балкон',view_from_window:'вид из окна',facade:'фасад',lobby:'лобби',pool:'бассейн',restaurant:'ресторан',beach:'пляж',bathroom:'санузел',territory:'территория',other:'другое'};
const caption=e=>e.sea_from_room?'на фото из номера видно море':e.sea?'на фото видно море (не из номера)':(e.note||'');

const openHotel0=window.openHotel;
window.openHotel=async function(id){
  await openHotel0(id);
  try{
    const d=await api('/api/hotels/'+id),seen=new Set(),ev=[];
    d.facts.forEach(f=>f.facts.filter(x=>x.source==='фото отеля').forEach(x=>(x.evidence.photos||[]).forEach(p=>{if(!seen.has(p.url)){seen.add(p.url);ev.push(p)}})));
    if(!ev.length)return;
    ev.sort((a,b)=>(b.sea_from_room-a.sea_from_room)||(b.sea-a.sea));
    const box=document.createElement('div');
    box.innerHTML=`<h3>Что видно на фото</h3><div class="small muted">Метки поставила модель по кадрам из карточки Островка. Отели снимают лучшие номера, поэтому если моря на фото нет, это слабый довод; если есть, сильный.</div><div class="ph">${ev.map(p=>`<figure class="${p.sea_from_room?'sea':''}"><a href="${esc(p.url)}" target="_blank"><img src="${esc(p.url)}" loading="lazy" alt=""></a><figcaption><span class="k">${esc(KIND[p.kind]||p.kind)} · ${(+p.confidence||0).toFixed(2)}</span><br>${esc(caption(p))}</figcaption></figure>`).join('')}</div>`;
    $('hotel').appendChild(box);
  }catch(e){}
};

const loadMetrics0=window.loadMetrics;
window.loadMetrics=async function(){
  await loadMetrics0();
  try{
    const p=(await api('/api/metrics')).photos,pc=v=>v==null?'нет данных':Math.round(v*100)+'%';
    const box=document.createElement('div');
    box.innerHTML=`<h3>Сверка с фото (независимый датчик)</h3><div class="kpi">
 <div><b>${Math.round((p.recall_geo_vs_photos||0)*p.photo_sea_from_room)} из ${p.photo_sea_from_room}</b>отелей, где на фото из номера видно море, расчёт тоже видит море. Для сравнения: расчёт говорит «море» у ${pc(p.geo_sea_base_rate)} отелей с фото, так что полное совпадение при такой выборке впечатляет меньше, чем кажется</div>
 <div><b>${pc(p.geo_agrees_no_sea)}</b>из ${p.photo_no_sea} отелей, где на фото номеров моря нет, расчёт тоже говорит «нет». Это около случайного уровня (${pc(p.geo_no_sea_chance)}), а не точность: отели снимают лучшие номера, поэтому «моря на фото нет» мало что доказывает</div>
 <div><b>${p.geo_sea_but_not_on_photos}</b>отелей: расчёт видит море, а на фото номеров его нет. Часто это номера на верхних этажах, которые не снимали</div>
 <div><b>${p.hotels_with_room_photos}</b>отелей с фото номеров или балконов из ${status.hotels||229}</div></div>
 <div class="small muted" style="margin-top:6px">${esc(p.note)}</div>`;
    const h=document.querySelector('#metrics h3');
    h?$('metrics').insertBefore(box,h):$('metrics').appendChild(box);
  }catch(e){}
};
})();
