/* Вход по ролям (ДЕМО). Токен лежит в sessionStorage, fetch к /api/ сам подставляет Authorization: Bearer.
   Сервер проверяет токен сам (app/auth.py); здесь только форма входа и понятные сообщения о 401/403.
   В продакшене вместо демо-формы токен приносит партнёрский вход Островка. */
(function () {
  const KEY = 'ostrovok_auth';
  const store = {
    get() { try { return JSON.parse(sessionStorage.getItem(KEY) || 'null') } catch (e) { return null } },
    set(v) { try { v ? sessionStorage.setItem(KEY, JSON.stringify(v)) : sessionStorage.removeItem(KEY) } catch (e) { } },
  };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const same = u => { try { const x = new URL(u, location.href); return x.origin === location.origin && x.pathname.startsWith('/api/') && !x.pathname.startsWith('/api/auth/') } catch (e) { return false } };

  const css = document.createElement('style');
  css.textContent = `.au-bg{position:fixed;inset:0;background:rgba(10,15,30,.45);z-index:3000;display:flex;align-items:center;justify-content:center;padding:16px}
.au-box{background:var(--card,#fff);color:var(--ink,#16181d);border-radius:16px;padding:22px;max-width:400px;width:100%;box-shadow:0 12px 40px rgba(0,0,0,.25);font:14px/1.45 inherit}
.au-box h2{margin:0 0 6px;font-size:19px}.au-box .au-hint{color:var(--muted,#667085);font-size:13px;margin:0 0 12px}
.au-box input{width:100%;padding:11px 12px;border:1px solid var(--line,#e4e7ec);border-radius:10px;font:inherit;background:var(--bg,#fff);color:inherit;min-height:44px}
.au-row{display:flex;gap:8px;margin-top:12px}.au-row button{flex:1;min-height:44px;border-radius:10px;border:0;font:inherit;font-weight:600;cursor:pointer}
.au-ok{background:var(--acc,#0b63f6);color:#fff}.au-no{background:var(--acc-soft,#e8f0ff);color:var(--acc,#0b63f6)}
.au-err{color:var(--bad,#c01048);font-size:13px;margin-top:8px;min-height:1em}
.au-toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:#16181d;color:#fff;padding:10px 16px;border-radius:12px;z-index:3100;max-width:92vw;font-size:14px}
.au-chip{display:inline-flex;align-items:center;gap:8px;font-size:13px;margin-left:auto;white-space:nowrap}
.au-chip button{border:0;border-radius:10px;padding:7px 12px;min-height:36px;cursor:pointer;font:inherit;background:var(--acc-soft,#e8f0ff);color:var(--acc,#0b63f6)}
.au-chip button.au-demo{background:var(--acc,#0b63f6);color:#fff;font-weight:600}`;
  document.head.appendChild(css);

  function toast(msg) {
    const t = document.createElement('div'); t.className = 'au-toast'; t.textContent = msg; document.body.appendChild(t);
    setTimeout(() => t.remove(), 4500);
  }

  async function post(url, body) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    let d = null; try { d = await r.json() } catch (e) { }
    if (!r.ok) throw new Error((d && d.detail) || 'Не получилось войти');
    return d;
  }

  const A = window.Auth = {
    get: () => store.get(),
    role: () => (store.get() || {}).role || 'guest',
    ok(role, hotel) { const a = store.get(); return !!a && (a.role === 'admin' || (role === 'hotelier' && a.role === 'hotelier' && (!hotel || a.hotel_id === hotel))); },
    logout() { store.set(null); chip(); },
    async loginAdmin(password) { const d = await post('/api/auth/admin', { password }); store.set({ token: d.token, role: 'admin', hotel_id: null }); chip(); return d; },
    async loginHotelier(hotel_id, code) { const d = await post('/api/auth/hotelier', { hotel_id, code }); store.set({ token: d.token, role: 'hotelier', hotel_id }); chip(); return d; },
    /* Показать форму входа. role: 'admin' | 'hotelier'. Промис: true после входа, false при отмене. */
    need(role, hotel) {
      if (A.ok(role, hotel)) return Promise.resolve(true);
      return new Promise(res => {
        const bg = document.createElement('div'); bg.className = 'au-bg';
        const adm = role === 'admin';
        bg.innerHTML = `<form class="au-box" autocomplete="off"><h2>${adm ? 'Вход для команды Островка' : 'Вход отельера'}</h2>
          <p class="au-hint">Демо-вход для жюри: ${adm ? 'пароль <b>demo</b>' : 'код <b>demo</b>'}. В продакшене здесь партнёрский вход Островка.</p>
          <input name="s" type="password" value="demo" aria-label="${adm ? 'Пароль' : 'Код доступа'}" placeholder="${adm ? 'Пароль' : 'Код доступа'}">
          <div class="au-err" role="alert"></div>
          <div class="au-row"><button type="button" class="au-no">Не сейчас</button><button class="au-ok">Войти</button></div></form>`;
        document.body.appendChild(bg);
        const f = bg.firstChild, inp = f.s, err = f.querySelector('.au-err');
        inp.focus(); inp.select();
        const done = v => { bg.remove(); res(v); };
        f.querySelector('.au-no').onclick = () => done(false);
        f.onsubmit = async e => {
          e.preventDefault(); err.textContent = '';
          try { adm ? await A.loginAdmin(inp.value) : await A.loginHotelier(hotel, inp.value); done(true); }
          catch (x) { err.textContent = x.message; }
        };
      });
    },
  };

  /* fetch: подставляем токен, на 401/403 даём короткое сообщение, а на 401 ещё и форму входа (не для чтения) */
  const f0 = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url);
    const a = store.get();
    if (a && same(url)) { init = Object.assign({}, init); init.headers = Object.assign({}, init.headers, { Authorization: 'Bearer ' + a.token }); }
    const r = await f0(input, init);
    if ((r.status === 401 || r.status === 403) && same(url)) {
      let d = ''; try { d = (await r.clone().json()).detail } catch (e) { }
      if (r.status === 401 && a) { store.set(null); chip(); }
      toast(d || (r.status === 401 ? 'Нужен вход' : 'Нет доступа'));
      const write = ((init && init.method) || 'GET').toUpperCase() !== 'GET';
      if (r.status === 401 && write) { const d = document.documentElement.dataset; d.role === 'hotelier' && d.hotel ? A.need('hotelier', d.hotel) : A.need('admin'); }
    }
    return r;
  };

  /* чип в шапке: кто вошёл, выход; на /backoffice (все вкладки) кнопка входа командой Островка одним кликом */
  function chip() {
    const h = document.querySelector('header'); if (!h) return;
    let c = document.getElementById('au-chip');
    if (!c) { c = document.createElement('div'); c.id = 'au-chip'; c.className = 'au-chip'; h.appendChild(c); }
    const a = store.get();
    if (a) {
      c.innerHTML = `<span>${a.role === 'admin' ? 'Команда Островка' : 'Отельер ' + esc(a.hotel_id)}</span><button type="button">Выйти</button>`;
      c.querySelector('button').onclick = () => A.logout();
    } else {
      const jury = !document.documentElement.dataset.role || document.documentElement.dataset.role === 'admin';  // бэк-офис: вход демо одним кликом
      if (document.documentElement.dataset.role === 'hotelier') { c.innerHTML = ''; return; }  // отельер входит, выбирая отель
      c.innerHTML = jury ? '<button type="button" class="au-demo">Войти как команда Островка (демо)</button>' : '<button type="button">Войти</button>';
      c.querySelector('button').onclick = async () => {
        if (jury) { try { await A.loginAdmin('demo'); return } catch (e) { } }
        A.need('admin');
      };
    }
  }
  const boot = () => {
    chip();
    if (location.pathname.replace(/\/+$/, '') === '/admin' && !A.ok('admin')) A.need('admin');  // /admin просит пароль, /backoffice входит одним кликом
  };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', boot) : boot();
})();
