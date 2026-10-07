/* The left menu (same look as SplashHub's dashboard in Zendesk): collapses to
   an icon rail with the button by the logo, remembered per browser, and
   always a rail on narrow windows. */
(function () {
  var root = document.documentElement, KEY = 'shcNavMini';
  var narrow = window.matchMedia('(max-width: 900px)');
  function picked() { try { return localStorage.getItem(KEY) === '1'; } catch (e) { return false; } }
  function apply() {
    var mini = narrow.matches || picked();
    root.classList.toggle('nav-mini', mini);
    var t = document.getElementById('navToggle');
    if (t) { t.title = mini ? 'Expand the menu' : 'Collapse the menu'; t.setAttribute('aria-label', t.title); t.hidden = narrow.matches; }
  }
  apply();
  if (narrow.addEventListener) narrow.addEventListener('change', apply);
  document.getElementById('navToggle').addEventListener('click', function () {
    try { localStorage.setItem(KEY, picked() ? '0' : '1'); } catch (e) {}
    root.classList.add('nav-anim');
    apply();
  });
})();

/* The top bar: who you are, top right. "Splashtop Support" for now (SSO will
   put a real name here later), with the role under it: Member for anybody,
   Admin once the admin password has been entered. Its menu: Admin login (the
   password, right there) or Log out. An admin also gets Logs and Settings in
   the left menu, under AI. Its
   menu holds the two admin pages (Logs, Settings) and Admin sign-in / Sign out.
   Each page's own script handles the Sign out button (#signOut). */
(function () {
  var SV = function (d) { return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>'; };
  var I = {
    user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    admin: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    caret: '<polyline points="6 9 12 15 18 9"/>',
    logs: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    key: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2"/><path d="M16 7l3 3"/>',
    out: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>'
  };
  var path = location.pathname.replace(/\/+$/, '') || '/';
    var bar = document.createElement('header');
  bar.className = 'topbar';
  bar.innerHTML =
    '<div class="tb-right">' +
      '<button type="button" class="tb-user" id="userBtn" aria-haspopup="menu" aria-expanded="false" aria-controls="userMenu">' +
        '<span class="tb-av" id="userAv">' + SV(I.user) + '</span>' +
        '<span class="tb-id"><span class="tb-name">Splashtop Support</span><span class="tb-role" id="userRole">Member</span></span>' + SV(I.caret) +
      '</button>' +
      '<div class="tb-menu" id="userMenu" role="menu" hidden>' +
        '<div class="tb-who"><span class="tb-av tb-av-lg" id="userAv2">' + SV(I.user) + '</span>' +
          '<span><b>Splashtop Support</b><span class="tb-role" id="userRole2">Member</span><small id="userSub">Everyone on the team</small></span></div>' +
        '<div class="tb-sep"></div>' +
        '<button type="button" class="tb-item" id="adminIn" role="menuitem" hidden>' + SV(I.key) + 'Admin login</button>' +
        '<form class="tb-login" id="adminForm" hidden>' +
          '<input type="password" id="adminPw" placeholder="Admin password" autocomplete="current-password" aria-label="Admin password">' +
          '<button type="submit" class="btn btn-primary btn-sm">Log in</button>' +
          '<div class="tb-err" id="adminErr" aria-live="polite"></div>' +
        '</form>' +
        '<button type="button" class="tb-item" id="signOut" role="menuitem" hidden>' + SV(I.out) + 'Log out</button>' +
      '</div>' +
    '</div>';
  var nav = document.getElementById('snav');
  nav.parentNode.insertBefore(bar, nav.nextSibling);

  var btn = document.getElementById('userBtn'), menu = document.getElementById('userMenu');
  function open(on) { menu.hidden = !on; btn.setAttribute('aria-expanded', on); btn.classList.toggle('open', on); }
  btn.addEventListener('click', function (e) { e.stopPropagation(); open(menu.hidden); });
  document.addEventListener('click', function (e) { if (!menu.hidden && !menu.contains(e.target)) open(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !menu.hidden) { open(false); btn.focus(); } });

  // Admin login, right here in the menu: the password goes to /login, then the page reloads as Admin.
  var form = document.getElementById('adminForm'), pw = document.getElementById('adminPw'), err = document.getElementById('adminErr');
  document.getElementById('adminIn').addEventListener('click', function () {
    form.hidden = !form.hidden; err.textContent = '';
    if (!form.hidden) pw.focus();
  });
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (!pw.value) { pw.focus(); return; }
    var b = form.querySelector('button'); b.disabled = true; err.textContent = '';
    fetch('/login', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ password: pw.value }) })
      .then(function (r) {
        if (r.ok) { location.reload(); return; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          b.disabled = false; pw.value = ''; pw.focus();
          err.textContent = r.status === 401 || r.status === 403 ? 'That password isn’t right.' : (j.error || 'Could not log in (HTTP ' + r.status + ').');
        });
      })
      .catch(function () { b.disabled = false; err.textContent = 'Could not reach SplashHub Centre.'; });
  });

  // Who: Admin when the admin password is set and was entered here; else User.
  fetch('/api/session', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (s) {
    var admin = !!(s.required && s.authed);
    var role = admin ? 'Admin' : 'Member';
    ['userRole', 'userRole2'].forEach(function (id) { document.getElementById(id).textContent = role; });
    ['userAv', 'userAv2'].forEach(function (id) { document.getElementById(id).innerHTML = SV(admin ? I.admin : I.user); });
    bar.classList.toggle('is-admin', admin);
    document.getElementById('userSub').textContent = admin ? 'Signed in with the admin password'
      : (s.required ? 'Logs and Settings need the admin password' : 'No admin password is set yet');
    // Logs and Settings (left menu, under AI): for an admin only -- or for
    // everyone while no admin password is set, as the server allows then.
    Array.prototype.forEach.call(document.querySelectorAll('.snav-adm, .snav-adm-h'), function (el) {
      if (!el.classList.contains('active')) el.hidden = !(admin || !s.required);
    });
    var h = document.querySelector('.snav-adm-h'); if (h) h.hidden = !(admin || !s.required);
    document.getElementById('adminIn').hidden = admin || !s.required;
    document.getElementById('signOut').hidden = !admin;
  }).catch(function () {});
})();

/* Arriving on a page: the header, cards and tiles rise in one after another.
   Only for what appears in the first moments after the page opens -- a later
   refresh of the same boxes (the Dashboard reloads its numbers) stays still. */
(function () {
  if (!window.MutationObserver || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var PICK = 'main.page .hdr, main.page .card, main.page .stat, main.page .me-wrap';
  function stagger() {
    var i = 0;
    Array.prototype.forEach.call(document.querySelectorAll(PICK), function (el) {
      if (el.hasAttribute('data-in') || (el.parentElement && el.parentElement.closest('[data-in]'))) return;
      el.setAttribute('data-in', '');
      el.style.setProperty('--in', Math.min(i++, 9));
    });
  }
  var mo = new MutationObserver(stagger);
  mo.observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener('DOMContentLoaded', stagger);
  setTimeout(function () { mo.disconnect(); }, 1500);
})();

/* Holiday theme (Settings > Look > Theme): a tinted top bar and menu, a thin
   festive stripe, a greeting, and a few decorations drifting behind the boxes
   (never over the text). Shown at once from this browser's last copy, then
   checked with SplashHub Centre. window.shcTheme.apply() is used by Settings. */
(function () {
  var root = document.documentElement, KEY = 'shcThemeNow';
  var still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var FX = {
    christmas: { g: ['❄', '❅', '❆'], c: ['#9db8d6', '#b9cde3'], n: 22 },
    thanksgiving: { g: ['🍂', '🍁'], n: 12 },
    halloween: { g: ['🍂', '🦇'], n: 10 },
    sakura: { g: ['🌸'], n: 14 },
    valentines: { g: ['💗', '♥'], c: ['#f29bbb'], n: 12 },
    st_patricks: { g: ['☘'], c: ['#4fb276', '#7fcf98'], n: 14 },
    new_year: { conf: ['#c9a227', '#e0457b', '#0071ce', '#1e9e5a', '#f07a1a'], n: 26 },
    lunar_new_year: { conf: ['#d7263d', '#f2b705'], n: 20 },
    july_4: { g: ['✦', '★'], c: ['#c8102e', '#1f4e9c', '#9aa6b2'], n: 18 },
    easter: { conf: ['#c7b2f0', '#f4d35e', '#9fdcc0', '#f7b2c8'], n: 18 },
    diwali: { g: ['✦', '✧'], c: ['#f2a516', '#e8c25a', '#f07a1a'], n: 18, up: true },
    mid_autumn: { g: ['✦', '·'], c: ['#d9a441', '#e8c25a'], n: 16, up: true }
  };
  var canvas = null, raf = 0, parts = [], onResize = null;

  function stopFx() {
    cancelAnimationFrame(raf); raf = 0; parts = [];
    if (onResize) { window.removeEventListener('resize', onResize); onResize = null; }
    if (canvas) { canvas.remove(); canvas = null; }
  }
  function startFx(key) {
    stopFx();
    var f = FX[key]; if (!f || still) return;
    canvas = document.createElement('canvas'); canvas.className = 'th-fx'; canvas.setAttribute('aria-hidden', 'true');
    document.body.insertBefore(canvas, document.body.firstChild);
    var cv = canvas, ctx = cv.getContext('2d'), W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
    function size() { W = innerWidth; H = innerHeight; cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); }
    size(); onResize = size; window.addEventListener('resize', size);
    function pick(a) { return a[Math.floor(Math.random() * a.length)]; }
    function make(anyY) {
      return { x: Math.random() * W, y: anyY ? Math.random() * H : (f.up ? H + 20 : -20), s: 10 + Math.random() * 10,
        v: (f.up ? -1 : 1) * (0.25 + Math.random() * 0.45), sw: Math.random() * Math.PI * 2, r: Math.random() * 6.28, vr: (Math.random() - 0.5) * 0.02,
        g: f.g ? pick(f.g) : null, c: pick(f.c || f.conf || ['#999']), a: 0.35 + Math.random() * 0.3 };
    }
    for (var i = 0; i < f.n; i++) parts.push(make(true));
    var last = 0;
    function frame(t) {
      raf = requestAnimationFrame(frame);
      if (document.hidden || t - last < 33) return;              // about 30 frames a second, nothing while hidden
      last = t; ctx.clearRect(0, 0, W, H);
      parts.forEach(function (p, i) {
        p.y += p.v; p.sw += 0.012; p.x += Math.sin(p.sw) * 0.35; p.r += p.vr;
        if (p.y > H + 30 || p.y < -30) parts[i] = p = make(false);
        ctx.save(); ctx.globalAlpha = p.a; ctx.translate(p.x, p.y); ctx.rotate(p.r);
        if (p.g) { ctx.fillStyle = p.c; ctx.font = p.s + 'px "Segoe UI Emoji","Apple Color Emoji",sans-serif'; ctx.textAlign = 'center'; ctx.fillText(p.g, 0, 0); }
        else { ctx.fillStyle = p.c; ctx.fillRect(-p.s / 4, -p.s / 8, p.s / 2, p.s / 4); }
        ctx.restore();
      });
    }
    raf = requestAnimationFrame(frame);
  }

  function apply(t) {
    var a = t && t.active;
    if (a) root.setAttribute('data-theme', a.key); else root.removeAttribute('data-theme');
    var bar = document.querySelector('.topbar'), pill = document.getElementById('thGreet');
    if (bar && a) {
      if (!pill) { pill = document.createElement('span'); pill.id = 'thGreet'; pill.className = 'th-greet'; bar.insertBefore(pill, bar.firstChild); }
      pill.textContent = a.emoji + ' ' + a.greet;
    } else if (pill) pill.remove();
    if (a && t.fx !== false) { if (!canvas || canvas.getAttribute('data-k') !== a.key) { startFx(a.key); if (canvas) canvas.setAttribute('data-k', a.key); } }
    else stopFx();
    try { localStorage.setItem(KEY, JSON.stringify({ active: a || null, fx: t ? t.fx : true })); } catch (e) {}
  }
  window.shcTheme = { apply: apply };

  var saved = null;
  try { saved = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) {}
  function go() {
    if (saved) apply(saved);
    fetch('/api/theme', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (t) { if (t) apply(t); }).catch(function () {});
  }
  if (document.body) go(); else document.addEventListener('DOMContentLoaded', go);
})();

/* Loading, so nothing just pops or sits empty:
   - the last view: each page's boxes are kept in this browser when you leave
     it and shown straight away next time (a little faded) until the fresh
     data replaces them
   - placeholders: shimmering rows and boxes the very first time (app.css)
   - a thin bar under the top bar while a page waits on SplashHub Centre after
     you open it or click / type / filter (not for background refreshes, nor
     the AI's own streamed answer)
   - a soft fade when content arrives in a box that was waiting */
(function () {
  var root = document.documentElement, f0 = window.fetch;
  var SK = '#stats, #dKpis, #dChart, .dcard, #dayChart, #toolChart, #chart, #verdicts, #chips, #tools, #ntKinds, #thGrid';
  // the boxes kept per page: their data only (filters, forms and open panels are left alone)
  var KEEP = '#stats, #dKpis, #dChart, #dAttention, #dSpike, #dWho, #dMix, #dayChart, #toolChart, #chart, #chartSub, #verdicts, #chips, #tools, ' +
    '#rows, #count, #pagerTxt, #stamp, #ov';
  var SNAP = 'shcView:' + location.pathname.replace(/\/+$/, '').replace(/\.html$/, ''), NOPE = /^\/(customers|ask|settings|me)\b/;
  var host = document.querySelector('.topbar') || document.body;
  var bar = document.createElement('div'); bar.className = 'ld-bar'; bar.setAttribute('aria-hidden', 'true');
  host.appendChild(bar);
  var busy = 0, act = Date.now(), showT = 0, settled = false, restored = false;
  ['pointerdown', 'keydown', 'input', 'change'].forEach(function (e) { addEventListener(e, function () { act = Date.now(); }, true); });

  function initial(el) {         // still as the page was written: empty, or only placeholders
    return !el.children.length ? !el.textContent.trim() : [].every.call(el.children, function (c) { return /\b(sk-tr|sk-ov|pn-loading)\b/.test(c.className); });
  }
  function restore() {
    if (restored || NOPE.test(location.pathname) || !document.querySelector('main.page')) return;
    restored = true;
    var snap = null;
    try { snap = JSON.parse(localStorage.getItem(SNAP) || 'null'); } catch (e) {}
    if (!snap || Date.now() - snap.ms > 7 * 86400000) return;
    [].forEach.call(document.querySelectorAll(KEEP), function (el) {
      var k = el.id || ''; if (!k || snap.box[k] == null || !initial(el)) return;
      el.innerHTML = snap.box[k];
      [].forEach.call(el.childNodes, function (n) { n._snap = true; });
      el.setAttribute('data-stale', '');
    });
  }
  function keep() {
    if (NOPE.test(location.pathname) || !document.querySelector('main.page')) return;
    var old = null, box = {}, size = 0;
    try { old = JSON.parse(localStorage.getItem(SNAP) || 'null'); } catch (e) {}
    [].forEach.call(document.querySelectorAll(KEEP), function (el) {
      var k = el.id; if (!k) return;
      if (el.hasAttribute('data-stale') || initial(el) || el.querySelector('.sk-tr, .pn-loading')) {   // never saved: keep the last good one
        if (old && old.box[k] != null) box[k] = old.box[k];
        return;
      }
      box[k] = el.innerHTML; size += box[k].length;
    });
    if (!Object.keys(box).length || size > 400000) return;
    try { localStorage.setItem(SNAP, JSON.stringify({ ms: Date.now(), box: box })); }
    catch (e) {           // full: make room by dropping the other pages' views
      try { Object.keys(localStorage).forEach(function (k) { if (k.indexOf('shcView:') === 0 && k !== SNAP) localStorage.removeItem(k); });
        localStorage.setItem(SNAP, JSON.stringify({ ms: Date.now(), box: box })); } catch (e2) {}
    }
  }
  addEventListener('pagehide', keep);
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'hidden') keep(); });
  document.addEventListener('DOMContentLoaded', restore);

  function unstale() { [].forEach.call(document.querySelectorAll('[data-stale]'), function (el) { el.removeAttribute('data-stale'); }); }
  function start() { if (busy++ === 0) { clearTimeout(showT); bar.classList.remove('end'); showT = setTimeout(function () { bar.classList.add('on'); }, 150); } }
  function done() {
    if (--busy > 0) return;
    busy = 0; clearTimeout(showT);
    if (bar.classList.contains('on')) { bar.classList.add('end'); setTimeout(function () { if (!busy) bar.classList.remove('on', 'end'); }, 380); }
    if (!settled) { settled = true; setTimeout(function () { root.classList.add('sk-off'); unstale(); }, 1500); }
  }
  if (f0) window.fetch = function (u, o) {
    var url = typeof u === 'string' ? u : (u && u.url) || '';
    if (url.indexOf('/api/') >= 0) restore();               // the page is built and asking for its data: show the last view now
    var p = f0.apply(this, arguments);
    if (url.indexOf('/api/') >= 0 && url.indexOf('/api/ask') < 0 && url.indexOf('/api/theme') < 0 && Date.now() - act < 1500) {
      start(); p.then(done, done);
    }
    return p;
  };
  setTimeout(function () { root.classList.add('sk-off'); unstale(); }, 12000);     // never shimmer or stay faded for ever

  if (!window.MutationObserver) return;
  new MutationObserver(function (ms) {
    ms.forEach(function (m) {
      var t = m.target; if (t.nodeType !== 1 || !m.addedNodes.length) return;
      var mine = [].every.call(m.addedNodes, function (n) { return n._snap; });
      if (t.hasAttribute('data-stale') && !mine) { t.removeAttribute('data-stale'); return; }   // fresh data over the last view: no fade, it just updates
      var waited = [].some.call(m.removedNodes, function (n) { return n.nodeType === 1 && /\b(sk-tr|sk-ov|pn-loading)\b/.test(n.className || ''); }) ||
        (!m.removedNodes.length && t.matches && t.matches(SK) && t.childNodes.length === m.addedNodes.length);
      if (!waited) return;
      t.removeAttribute('data-arrived'); void t.offsetWidth; t.setAttribute('data-arrived', '');
      clearTimeout(t._arr); t._arr = setTimeout(function () { t.removeAttribute('data-arrived'); }, 700);
    });
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
