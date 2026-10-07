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

/* Holiday theme (Settings > Look > Theme). Only the top bar and the menu's
   shade change, so text and numbers read as always:
   - a garland hanging under the top bar (lights, lanterns, bunting, diyas...)
     whose ornaments twinkle, sway or flicker (Decorations on/off)
   - a greeting with a bobbing emoji
   Shown at once from this browser's last copy, then checked with SplashHub
   Centre. window.shcTheme.apply() is used by Settings. No motion for anyone
   whose computer asks for less (app.css). */
(function () {
  var root = document.documentElement, KEY = 'shcThemeNow';
  var NS = 'http://www.w3.org/2000/svg';

  var T = {
    christmas:      { g: 'bulb',    c: ['#e5383b', '#2a9d4b', '#f4c430', '#3a86ff'] },
    halloween:      { g: 'flag',    c: ['#f07a1a', '#6b3fa0', '#2f2f2f'], bats: true },
    thanksgiving:   { g: 'leaf',    c: ['#c4622d', '#e09a3e', '#8a5a2b', '#b5452b'] },
    new_year:       { g: 'star',    c: ['#c9a227', '#e6c656', '#a9b1c2'] },
    lunar_new_year: { g: 'lantern', c: ['#d7263d'], trim: '#f2b705' },
    valentines:     { g: 'heart',   c: ['#e0457b', '#f7a8c4', '#c9184a'] },
    st_patricks:    { g: 'shamrock', c: ['#1e9e5a', '#4fb276', '#f2c94c'] },
    sakura:         { g: 'blossom', c: ['#f4a6c0', '#e98aab', '#fbd3e0'] },
    easter:         { g: 'egg',     c: ['#c7b2f0', '#f4d35e', '#9fdcc0', '#f7b2c8'] },
    july_4:         { g: 'pennant', c: ['#c8102e', '#f4f4f4', '#1f4e9c'] },
    mid_autumn:     { g: 'lantern', c: ['#e8902f', '#d9a441'], trim: '#6b4fa0' },
    diwali:         { g: 'diya',    c: ['#f2a516'] }
  };

  // ---- the garland under the top bar -------------------------------------------------------------
  function el(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  var ORN = {
    bulb: function (g, x, y, c, i) {
      el('rect', { x: x - 2.5, y: y - 3, width: 5, height: 4, rx: 1, fill: '#56605a' }, g);
      el('ellipse', { cx: x, cy: y + 5, rx: 4.2, ry: 6, fill: c, 'class': 'th-tw', style: 'animation-delay:' + (-(i * 0.37) % 2.4).toFixed(2) + 's;color:' + c }, g);
    },
    flag: function (g, x, y, c) { el('path', { d: 'M' + (x - 8) + ' ' + (y - 2) + ' L' + (x + 8) + ' ' + (y - 2) + ' L' + x + ' ' + (y + 15) + 'z', fill: c, 'class': 'th-sway' }, g); },
    pennant: function (g, x, y, c, i) {
      el('path', { d: 'M' + (x - 9) + ' ' + (y - 2) + ' L' + (x + 9) + ' ' + (y - 2) + ' L' + x + ' ' + (y + 16) + 'z', fill: c, stroke: c === '#f4f4f4' ? '#d6dbe1' : 'none', 'class': 'th-sway' }, g);
      if (c === '#1f4e9c') el('path', { d: star(x, y + 4, 3.4, 1.4), fill: '#fff' }, g);
    },
    lantern: function (g, x, y, c, i, t) {
      var s = el('g', { 'class': 'th-sway', style: 'transform-box:view-box;transform-origin:' + x + 'px ' + (y - 3) + 'px;animation-delay:' + (-(i * 0.5) % 3).toFixed(2) + 's' }, g);
      el('line', { x1: x, y1: y - 3, x2: x, y2: y + 1, stroke: '#7a5c2e', 'stroke-width': 1 }, s);
      el('rect', { x: x - 6, y: y + 1, width: 12, height: 3, rx: 1, fill: t || '#f2b705' }, s);
      el('rect', { x: x - 8, y: y + 3, width: 16, height: 14, rx: 6, fill: c, 'class': 'th-glow', style: 'color:' + c }, s);
      el('rect', { x: x - 6, y: y + 16, width: 12, height: 3, rx: 1, fill: t || '#f2b705' }, s);
      el('line', { x1: x, y1: y + 19, x2: x, y2: y + 25, stroke: t || '#f2b705', 'stroke-width': 1.4 }, s);
    },
    heart: function (g, x, y, c, i) {
      var s = el('g', { 'class': 'th-sway', style: 'transform-box:view-box;transform-origin:' + x + 'px ' + (y - 2) + 'px;animation-delay:' + (-(i * 0.6) % 3).toFixed(2) + 's' }, g);
      el('line', { x1: x, y1: y - 2, x2: x, y2: y + 3, stroke: '#c9a0b0', 'stroke-width': 1 }, s);
      el('path', { d: heart(x, y + 3, 8), fill: c }, s);
    },
    leaf: function (g, x, y, c, i) {
      el('path', { d: 'M' + x + ' ' + (y - 1) + ' C' + (x + 9) + ' ' + (y + 2) + ' ' + (x + 7) + ' ' + (y + 13) + ' ' + x + ' ' + (y + 17) + ' C' + (x - 7) + ' ' + (y + 13) + ' ' + (x - 9) + ' ' + (y + 2) + ' ' + x + ' ' + (y - 1) + 'z',
        fill: c, 'class': 'th-sway', transform: 'rotate(' + ((i % 2 ? 1 : -1) * 18) + ' ' + x + ' ' + y + ')' }, g);
    },
    star: function (g, x, y, c, i) { el('path', { d: star(x, y + 6, 7, 3), fill: c, 'class': 'th-tw', style: 'animation-delay:' + (-(i * 0.41) % 2.4).toFixed(2) + 's;color:' + c }, g); },
    diya: function (g, x, y, c, i) {
      el('path', { d: 'M' + (x - 8) + ' ' + (y + 8) + ' Q' + x + ' ' + (y + 17) + ' ' + (x + 8) + ' ' + (y + 8) + 'z', fill: '#b5541c' }, g);
      el('ellipse', { cx: x, cy: y + 3, rx: 2.6, ry: 5, fill: '#ffcf4a', 'class': 'th-flick', style: 'transform-origin:' + x + 'px ' + (y + 7) + 'px;animation-delay:' + (-(i * 0.3) % 1.2).toFixed(2) + 's;color:#ffb020' }, g);
    },
    egg: function (g, x, y, c, i) {
      el('ellipse', { cx: x, cy: y + 7, rx: 6, ry: 8, fill: c, 'class': 'th-sway' }, g);
      el('path', { d: 'M' + (x - 5.5) + ' ' + (y + 7) + ' q2.75 -2 5.5 0 t5.5 0', stroke: '#fff', 'stroke-width': 1.6, fill: 'none' }, g);
    },
    shamrock: function (g, x, y, c) {
      [[0, 2], [-4, 7], [4, 7]].forEach(function (d) { el('circle', { cx: x + d[0], cy: y + d[1], r: 4, fill: c }, g); });
      el('path', { d: 'M' + x + ' ' + (y + 8) + ' q2 5 1 9', stroke: c, 'stroke-width': 1.5, fill: 'none' }, g);
    },
    blossom: function (g, x, y, c) {
      for (var k = 0; k < 5; k++) { var a = k * 1.2566; el('circle', { cx: x + Math.cos(a) * 4, cy: y + 6 + Math.sin(a) * 4, r: 3.4, fill: c }, g); }
      el('circle', { cx: x, cy: y + 6, r: 1.8, fill: '#f6d36b' }, g);
    }
  };
  function star(cx, cy, R, r) {
    var p = '';
    for (var k = 0; k < 10; k++) { var a = Math.PI / 5 * k - Math.PI / 2, rr = k % 2 ? r : R; p += (k ? 'L' : 'M') + (cx + Math.cos(a) * rr).toFixed(1) + ' ' + (cy + Math.sin(a) * rr).toFixed(1); }
    return p + 'z';
  }
  function heart(x, y, s) {
    return 'M' + x + ' ' + (y + s * 0.9) + ' C' + (x - s * 1.2) + ' ' + (y + s * 0.2) + ' ' + (x - s * 0.7) + ' ' + (y - s * 0.6) + ' ' + x + ' ' + (y - s * 0.1) +
      ' C' + (x + s * 0.7) + ' ' + (y - s * 0.6) + ' ' + (x + s * 1.2) + ' ' + (y + s * 0.2) + ' ' + x + ' ' + (y + s * 0.9) + 'z';
  }
  function bat(g, x, y) {
    el('path', { d: 'M' + x + ' ' + y + ' q-4 -4 -9 -2 q3 1 2 4 q-3 -1 -5 1 q5 0 7 3 q3 -2 5 -1 q2 -1 5 1 q2 -3 7 -3 q-2 -2 -5 -1 q-1 -3 2 -4 q-5 -2 -9 2z',
      fill: '#2f2f2f', 'class': 'th-sway' }, g);
  }
  var garland = null, gTheme = null;
  function drawGarland(key) {
    var bar = document.querySelector('.topbar');
    if (garland) { garland.remove(); garland = null; }
    var t = T[key]; if (!t || !bar) return;
    var W = bar.clientWidth, L = 118, n = Math.ceil(W / L) + 1, H = 46;
    garland = document.createElement('div'); garland.className = 'th-garland'; garland.setAttribute('aria-hidden', 'true');
    var svg = el('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H }, garland);
    var d = '';
    for (var i = 0; i < n; i++) d += (i ? '' : 'M0 1') + ' Q' + (i * L + L / 2) + ' 17 ' + ((i + 1) * L) + ' 1';
    el('path', { d: d, stroke: key === 'christmas' ? '#3c4a3f' : '#8a7a62', 'stroke-width': 1.2, fill: 'none', opacity: 0.7 }, svg);
    var k = 0, per = t.g === 'bulb' || t.g === 'star' ? [0.18, 0.5, 0.82] : t.g === 'flag' || t.g === 'pennant' || t.g === 'blossom' || t.g === 'leaf' ? [0.25, 0.5, 0.75] : [0.5];
    for (var s = 0; s < n; s++) {
      per.forEach(function (f) {
        var x = s * L + f * L, y = 1 + 16 * (1 - Math.pow(2 * f - 1, 2));          // on the swag
        if (x > W + 10) return;
        ORN[t.g](svg, x, y, t.c[k % t.c.length], k, t.trim);
        k++;
      });
      if (t.bats && s % 3 === 1) bat(svg, s * L + L * 0.5, 30);
    }
    bar.appendChild(garland);
    gTheme = key;
  }

  // ---- applying a theme ---------------------------------------------------------------------------
  function apply(t) {
    var a = t && t.active;
    if (a) root.setAttribute('data-theme', a.key); else root.removeAttribute('data-theme');
    var bar = document.querySelector('.topbar'), pill = document.getElementById('thGreet');
    if (bar && a) {
      if (!pill) { pill = document.createElement('span'); pill.id = 'thGreet'; pill.className = 'th-greet'; bar.insertBefore(pill, bar.firstChild); }
      pill.innerHTML = '<span class="th-emoji" aria-hidden="true"></span><span></span>';
      pill.firstChild.textContent = a.emoji; pill.lastChild.textContent = a.greet;
    } else if (pill) pill.remove();
    if (a && T[a.key] && t.fx !== false) { if (gTheme !== a.key || !garland) drawGarland(a.key); }
    else { if (garland) { garland.remove(); garland = null; } gTheme = null; }
    try { localStorage.setItem(KEY, JSON.stringify({ active: a || null, fx: t ? t.fx : true })); } catch (e) {}
  }
  window.shcTheme = { apply: apply };
  var rT = 0;
  window.addEventListener('resize', function () { clearTimeout(rT); rT = setTimeout(function () { if (gTheme) drawGarland(gTheme); }, 200); });

  var saved = null;
  try { saved = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) {}
  function go() {
    if (saved) apply(saved);
    fetch('/api/theme', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (t) { if (t) apply(t); }).catch(function () {});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go); else go();   // the top bar comes after this script
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


/* Arrivals: when new items come into a list you're looking at (SOS Scans, SSO
   Requests, the PO menus, AutoTag, the Ad/Spam Filter), they slide in at the
   top with a blue glow that fades and a small "New" tag, and a notice in the
   corner says how many (click: go to the first). Only real arrivals: a filter,
   a search or another page never counts, nor a big change at once. */
(function () {
 function start() {
  var rows = document.getElementById('rows');
  if (!rows || !window.MutationObserver) return;
  var p = location.pathname.replace(/\/+$/, '');
  var WHAT = { '/scans': ['SOS request', 'SOS requests'], '/sso': ['SSO request', 'SSO requests'], '/po': ['PO request', 'PO requests'],
    '/autotag': ['ticket', 'tickets'], '/adfilter': ['ad / spam ticket', 'ad / spam tickets'] }[p];
  if (!WHAT) return;
  var known = null, act = Date.now(), still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  ['pointerdown', 'keydown', 'input', 'change'].forEach(function (e) { addEventListener(e, function () { act = Date.now(); }, true); });
  function ids() { return [].map.call(rows.querySelectorAll('tr[data-id]'), function (tr) { return tr.getAttribute('data-id'); }); }

  var toast = null, tT = 0;
  function notice(n, first) {
    if (!toast) {
      toast = document.createElement('button');
      toast.type = 'button';
      toast.className = 'arrive-toast';
      toast.addEventListener('click', function () {
        var tr = rows.querySelector('tr[data-id="' + toast.getAttribute('data-first') + '"]');
        if (tr) { tr.scrollIntoView({ block: 'center', behavior: still ? 'auto' : 'smooth' }); tr.focus({ preventScroll: true }); }
        toast.hidden = true;
      });
      document.body.appendChild(toast);
    }
    toast.innerHTML = '<span class="arrive-dot" aria-hidden="true"></span>' + n + ' new ' + (n === 1 ? WHAT[0] : WHAT[1]);
    toast.setAttribute('data-first', first);
    toast.hidden = false;
    toast.classList.remove('arrive-in'); void toast.offsetWidth; toast.classList.add('arrive-in');
    clearTimeout(tT); tT = setTimeout(function () { toast.hidden = true; }, 6000);
  }

  new MutationObserver(function () {
    var now = ids();
    if (!now.length) return;
    var before = known;
    known = now;
    if (!before || !before.length || Date.now() - act < 1500) return;      // first view, or a filter / page change
    var was = {}; before.forEach(function (i) { was[i] = 1; });
    var firstOld = -1;
    for (var i = 0; i < now.length; i++) if (was[now[i]]) { firstOld = i; break; }
    if (firstOld <= 0) return;                                             // nothing kept from before, or nothing above it
    var fresh = now.slice(0, firstOld);
    if (fresh.length > 10) return;                                         // a big change at once is not an arrival
    fresh.forEach(function (id) {
      var tr = rows.querySelector('tr[data-id="' + id + '"]'); if (!tr) return;
      tr.classList.add('row-arrive');
      var td = tr.querySelector('td');
      if (td && !td.querySelector('.row-new-tag')) td.insertAdjacentHTML('beforeend', ' <span class="row-new-tag">New</span>');
    });
    notice(fresh.length, fresh[0]);
  }).observe(rows, { childList: true });
 }
 if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();   // the list comes after this script
})();
