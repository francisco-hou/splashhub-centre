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

/* Holiday theme (Settings > Look > Theme). Everything stays in the frame and
   behind the boxes, so text and numbers read as always:
   - a garland hanging under the top bar (lights, lanterns, bunting, diyas...)
     whose ornaments twinkle, sway or flicker
   - a small scene at the bottom of the left menu
   - a greeting with a bobbing emoji
   - decorations drifting behind the boxes (snow, tumbling leaves, flipping
     confetti, petals, rising sparks) and, for some, fireworks now and then
   Shown at once from this browser's last copy, then checked with SplashHub
   Centre. window.shcTheme.apply() is used by Settings. No motion for anyone
   whose computer asks for less. */
(function () {
  var root = document.documentElement, KEY = 'shcThemeNow';
  var still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var NS = 'http://www.w3.org/2000/svg';

  var T = {
    christmas:      { g: 'bulb',    c: ['#e5383b', '#2a9d4b', '#f4c430', '#3a86ff'], scene: 'village', fx: 'snow' },
    halloween:      { g: 'flag',    c: ['#f07a1a', '#6b3fa0', '#2f2f2f'], bats: true, scene: 'pumpkins', fx: 'leaves', fxc: ['#f07a1a', '#a0522d', '#6b3fa0'] },
    thanksgiving:   { g: 'leaf',    c: ['#c4622d', '#e09a3e', '#8a5a2b', '#b5452b'], scene: 'harvest', fx: 'leaves', fxc: ['#c4622d', '#e09a3e', '#b5452b', '#d9a441'] },
    new_year:       { g: 'star',    c: ['#c9a227', '#e6c656', '#a9b1c2'], scene: 'skyline', fx: 'confetti', fxc: ['#c9a227', '#e0457b', '#0071ce', '#1e9e5a', '#f07a1a'], fireworks: ['#e6c656', '#e0457b', '#5aa9e6', '#f07a1a'] },
    lunar_new_year: { g: 'lantern', c: ['#d7263d'], trim: '#f2b705', scene: 'lanterns', fx: 'confetti', fxc: ['#d7263d', '#f2b705'], fireworks: ['#f2b705', '#ff5a5f'] },
    valentines:     { g: 'heart',   c: ['#e0457b', '#f7a8c4', '#c9184a'], scene: 'hearts', fx: 'hearts', fxc: ['#f29bbb', '#e0457b'] },
    st_patricks:    { g: 'shamrock', c: ['#1e9e5a', '#4fb276', '#f2c94c'], scene: 'hills', fx: 'shamrocks', fxc: ['#4fb276', '#7fcf98'] },
    sakura:         { g: 'blossom', c: ['#f4a6c0', '#e98aab', '#fbd3e0'], scene: 'branch', fx: 'petals', fxc: ['#f4a6c0', '#f9c9d8', '#e98aab'] },
    easter:         { g: 'egg',     c: ['#c7b2f0', '#f4d35e', '#9fdcc0', '#f7b2c8'], scene: 'meadow', fx: 'confetti', fxc: ['#c7b2f0', '#f4d35e', '#9fdcc0', '#f7b2c8'] },
    july_4:         { g: 'pennant', c: ['#c8102e', '#f4f4f4', '#1f4e9c'], scene: 'flag', fx: 'stars', fxc: ['#c8102e', '#1f4e9c', '#9aa6b2'], fireworks: ['#e63946', '#f1faee', '#457b9d'] },
    mid_autumn:     { g: 'lantern', c: ['#e8902f', '#d9a441'], trim: '#6b4fa0', scene: 'moon', fx: 'sparks', fxc: ['#e8c25a', '#d9a441'] },
    diwali:         { g: 'diya',    c: ['#f2a516'], scene: 'rangoli', fx: 'sparks', fxc: ['#f2a516', '#e8c25a', '#f07a1a'], fireworks: ['#f2a516', '#e0457b', '#f7d046'] }
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

  // ---- a scene at the bottom of the left menu -----------------------------------------------------
  var SCENES = {
    village: '<path d="M0 70 Q60 56 120 66 T240 62 V96 H0z" fill="#eef4fa"/><path d="M0 80 Q80 70 160 78 T240 76 V96 H0z" fill="#fff"/>' +
      tree(26, 74, 22) + tree(214, 70, 26) + tree(196, 76, 16) + house(70, 58, '#c94f3d') + house(118, 62, '#5a7d9a') + house(160, 58, '#7a5c3e'),
    pumpkins: '<circle cx="200" cy="24" r="14" fill="#fbe7b2"/><path d="M0 74 Q120 60 240 74 V96 H0z" fill="#e9dfd2"/>' + pumpkin(60, 70, 18) + pumpkin(108, 74, 13) + pumpkin(150, 72, 16) +
      '<path d="M190 40 q-3 -3 -7 -1 q2 1 1 3 q-2 -1 -4 1 q4 0 6 2 q2 -1 4 -1 q2 -1 4 1 q2 -2 6 -2 q-2 -2 -4 -1 q-1 -2 2 -3 q-4 -2 -8 1z" fill="#3a3a3a"/>',
    harvest: '<path d="M0 76 Q120 64 240 76 V96 H0z" fill="#f3e2c7"/>' + pumpkin(70, 72, 16) + pumpkin(170, 74, 12) +
      '<path d="M112 80 l-6 -34 M118 80 l0 -36 M124 80 l6 -34" stroke="#c99a3e" stroke-width="3" stroke-linecap="round"/>' + '<path d="M106 46 l-4 -8 M118 44 l0 -9 M130 46 l4 -8" stroke="#e0b452" stroke-width="5" stroke-linecap="round"/>',
    skyline: '<rect x="0" y="62" width="240" height="34" fill="#e8ebf2"/>' + [[10, 40], [34, 52], [52, 30], [80, 46], [100, 24], [126, 50], [148, 36], [172, 54], [190, 28], [214, 44]].map(function (b, i) {
      return '<rect x="' + b[0] + '" y="' + b[1] + '" width="' + (16 + i % 3 * 4) + '" height="' + (96 - b[1]) + '" fill="#c3cad8"/>'; }).join('') +
      burst(60, 16, '#e6c656') + burst(170, 12, '#e0457b') + burst(120, 8, '#5aa9e6'),
    lanterns: '<path d="M10 0 Q120 26 230 0" stroke="#8a5a2b" stroke-width="1.4" fill="none"/>' + lantern(50, 10) + lantern(120, 22) + lantern(190, 10) +
      '<path d="M0 86 Q120 74 240 86 V96 H0z" fill="#fbe3e3"/>',
    hearts: heartSvg(60, 52, 16, '#f7a8c4') + heartSvg(118, 40, 24, '#e0457b') + heartSvg(178, 54, 14, '#f29bbb') + heartSvg(150, 74, 9, '#c9184a') + heartSvg(88, 78, 8, '#e0457b'),
    hills: '<path d="M20 70 A100 100 0 0 1 220 70" stroke="#e05a5a" stroke-width="5" fill="none" opacity=".55"/><path d="M28 70 A92 92 0 0 1 212 70" stroke="#f2c94c" stroke-width="5" fill="none" opacity=".55"/>' +
      '<path d="M36 70 A84 84 0 0 1 204 70" stroke="#4fb276" stroke-width="5" fill="none" opacity=".55"/><path d="M0 74 Q70 58 140 72 T240 66 V96 H0z" fill="#9fd8a9"/><path d="M0 84 Q90 72 240 84 V96 H0z" fill="#6cc283"/>' +
      '<ellipse cx="196" cy="72" rx="12" ry="7" fill="#3a3a3a"/><circle cx="190" cy="66" r="3" fill="#f2c94c"/><circle cx="197" cy="64" r="3" fill="#f2c94c"/><circle cx="203" cy="67" r="3" fill="#f2c94c"/>',
    branch: '<path d="M240 10 C180 22 150 40 90 46 C60 49 30 60 6 74" stroke="#7a5446" stroke-width="4" fill="none" stroke-linecap="round"/><path d="M150 36 C140 50 130 58 116 64" stroke="#7a5446" stroke-width="2.5" fill="none"/>' +
      [[210, 16], [176, 28], [140, 40], [100, 44], [66, 52], [30, 64], [124, 60], [190, 20]].map(function (p, i) { return blossomSvg(p[0], p[1], i % 2 ? '#f4a6c0' : '#fbd3e0'); }).join(''),
    meadow: '<path d="M0 72 Q120 60 240 72 V96 H0z" fill="#cfeccf"/>' + egg(70, 70, '#c7b2f0') + egg(104, 74, '#f4d35e') + egg(140, 70, '#9fdcc0') + egg(172, 74, '#f7b2c8') +
      [30, 48, 196, 214].map(function (x) { return blossomSvg(x, 66, '#fff'); }).join(''),
    flag: '<g transform="translate(70 18)"><rect width="100" height="56" fill="#fff" stroke="#d6dbe1"/>' + [0, 2, 4, 6].map(function (i) { return '<rect y="' + (i * 8) + '" width="100" height="8" fill="#c8102e"/>'; }).join('') +
      '<rect width="42" height="30" fill="#1f4e9c"/>' + [[8, 7], [20, 7], [32, 7], [14, 15], [26, 15], [8, 23], [20, 23], [32, 23]].map(function (p) { return '<path d="' + star(p[0], p[1], 3, 1.2) + '" fill="#fff"/>'; }).join('') +
      '</g><line x1="70" y1="12" x2="70" y2="94" stroke="#8a8f99" stroke-width="2"/>',
    moon: '<circle cx="168" cy="38" r="26" fill="#fbe7b2"/><circle cx="160" cy="32" r="4" fill="#f2d48a" opacity=".6"/><circle cx="176" cy="46" r="3" fill="#f2d48a" opacity=".6"/>' +
      lantern(50, 12, '#e8902f') + lantern(96, 26, '#d9a441') + '<path d="M0 84 Q120 72 240 84 V96 H0z" fill="#efe4d0"/>',
    rangoli: [36, 30, 22, 14].map(function (r, i) { return '<circle cx="120" cy="56" r="' + r + '" fill="' + ['#f7d046', '#e0457b', '#f2a516', '#c2185b'][i] + '" opacity=".75"/>'; }).join('') +
      [0, 1, 2, 3, 4, 5, 6, 7].map(function (k) { var a = k * Math.PI / 4; return '<circle cx="' + (120 + Math.cos(a) * 30).toFixed(1) + '" cy="' + (56 + Math.sin(a) * 30).toFixed(1) + '" r="4" fill="#fff"/>'; }).join('') +
      [46, 194].map(function (x) { return '<path d="M' + (x - 10) + ' 84 Q' + x + ' 94 ' + (x + 10) + ' 84z" fill="#b5541c"/><ellipse cx="' + x + '" cy="78" rx="3" ry="6" fill="#ffcf4a" class="th-flick" style="transform-origin:' + x + 'px 84px"/>'; }).join('')
  };
  function tree(x, y, h) { return '<path d="M' + x + ' ' + (y - h) + ' L' + (x + h * 0.45) + ' ' + y + ' H' + (x - h * 0.45) + 'z" fill="#2f6b4a"/><path d="M' + x + ' ' + (y - h) + ' L' + (x + h * 0.2) + ' ' + (y - h * 0.55) + ' H' + (x - h * 0.2) + 'z" fill="#fff"/>'; }
  function house(x, y, c) { return '<rect x="' + x + '" y="' + y + '" width="26" height="18" fill="' + c + '"/><path d="M' + (x - 3) + ' ' + y + ' L' + (x + 13) + ' ' + (y - 12) + ' L' + (x + 29) + ' ' + y + 'z" fill="#fff"/><rect x="' + (x + 9) + '" y="' + (y + 6) + '" width="8" height="7" fill="#ffd36b" class="th-glow" style="color:#ffd36b"/>'; }
  function pumpkin(x, y, r) { return '<ellipse cx="' + x + '" cy="' + y + '" rx="' + r + '" ry="' + (r * 0.8) + '" fill="#f07a1a"/><ellipse cx="' + x + '" cy="' + y + '" rx="' + (r * 0.45) + '" ry="' + (r * 0.8) + '" fill="#e06a0e"/><rect x="' + (x - 1.5) + '" y="' + (y - r * 0.8 - 5) + '" width="3" height="6" fill="#4a7a3a"/>' +
      '<path d="M' + (x - r * 0.45) + ' ' + (y - 2) + ' l3 -4 l3 4z M' + (x + r * 0.15) + ' ' + (y - 2) + ' l3 -4 l3 4z M' + (x - r * 0.4) + ' ' + (y + 4) + ' q' + (r * 0.4) + ' 5 ' + (r * 0.8) + ' 0" fill="#ffd36b" stroke="#ffd36b" stroke-width="1" class="th-glow" style="color:#ffb020"/>'; }
  function burst(x, y, c) { var s = ''; for (var k = 0; k < 10; k++) { var a = k * Math.PI / 5; s += '<line x1="' + x + '" y1="' + y + '" x2="' + (x + Math.cos(a) * 12).toFixed(1) + '" y2="' + (y + Math.sin(a) * 12).toFixed(1) + '" stroke="' + c + '" stroke-width="2" stroke-linecap="round" class="th-tw" style="animation-delay:' + (-k * 0.2) + 's;color:' + c + '"/>'; } return s; }
  function lantern(x, y, c) { c = c || '#d7263d'; return '<line x1="' + x + '" y1="' + (y - 10) + '" x2="' + x + '" y2="' + y + '" stroke="#8a5a2b"/><g class="th-sway" style="transform-box:view-box;transform-origin:' + x + 'px ' + (y - 10) + 'px"><rect x="' + (x - 11) + '" y="' + y + '" width="22" height="24" rx="9" fill="' + c + '" class="th-glow" style="color:' + c + '"/><rect x="' + (x - 7) + '" y="' + (y - 2) + '" width="14" height="4" rx="1" fill="#f2b705"/><rect x="' + (x - 7) + '" y="' + (y + 22) + '" width="14" height="4" rx="1" fill="#f2b705"/><line x1="' + x + '" y1="' + (y + 26) + '" x2="' + x + '" y2="' + (y + 34) + '" stroke="#f2b705" stroke-width="2"/></g>'; }
  function heartSvg(x, y, s, c) { return '<path d="' + heart(x, y, s) + '" fill="' + c + '" class="th-sway" style="transform-box:view-box;transform-origin:' + x + 'px ' + y + 'px"/>'; }
  function blossomSvg(x, y, c) { var s = ''; for (var k = 0; k < 5; k++) { var a = k * 1.2566; s += '<circle cx="' + (x + Math.cos(a) * 4).toFixed(1) + '" cy="' + (y + Math.sin(a) * 4).toFixed(1) + '" r="3.6" fill="' + c + '"/>'; } return s + '<circle cx="' + x + '" cy="' + y + '" r="1.8" fill="#f6d36b"/>'; }
  function egg(x, y, c) { return '<ellipse cx="' + x + '" cy="' + y + '" rx="10" ry="13" fill="' + c + '"/><path d="M' + (x - 9) + ' ' + y + ' q4.5 -4 9 0 t9 0" stroke="#fff" stroke-width="2" fill="none"/>'; }
  var scene = null;
  function drawScene(key) {
    if (scene) { scene.remove(); scene = null; }
    var t = T[key], foot = document.querySelector('.snav-foot'); if (!t || !foot || !SCENES[t.scene]) return;
    scene = document.createElement('div'); scene.className = 'th-scene'; scene.setAttribute('aria-hidden', 'true');
    scene.innerHTML = '<svg viewBox="0 0 240 96" preserveAspectRatio="xMidYMax meet" xmlns="' + NS + '">' + SCENES[t.scene] + '</svg>';
    foot.insertBefore(scene, foot.firstChild);
  }

  // ---- drifting decorations and fireworks, behind the boxes --------------------------------------
  var canvas = null, raf = 0, onResize = null;
  function stopFx() {
    cancelAnimationFrame(raf); raf = 0;
    if (onResize) { window.removeEventListener('resize', onResize); onResize = null; }
    if (canvas) { canvas.remove(); canvas = null; }
  }
  function startFx(key) {
    stopFx();
    var t = T[key]; if (!t || still) return;
    canvas = document.createElement('canvas'); canvas.className = 'th-fx'; canvas.setAttribute('aria-hidden', 'true');
    document.body.insertBefore(canvas, document.body.firstChild);
    var cv = canvas, ctx = cv.getContext('2d'), W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2), parts = [], sparks = [], nextBurst = 0;
    function size() { W = innerWidth; H = innerHeight; cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); }
    size(); onResize = size; window.addEventListener('resize', size);
    var cols = t.fxc || t.c, up = t.fx === 'sparks';
    function pick(a) { return a[Math.floor(Math.random() * a.length)]; }
    function make(anyY) {
      var z = 0.45 + Math.random() * 0.75;                    // depth: nearer = bigger, faster, clearer
      return { x: Math.random() * W, y: anyY ? Math.random() * H : (up ? H + 20 : -20), z: z, s: (t.fx === 'snow' ? 2.4 : 7) * z + 1,
        v: (up ? -1 : 1) * (0.35 + 0.55 * z), sw: Math.random() * 6.28, sws: 0.008 + Math.random() * 0.012, r: Math.random() * 6.28,
        vr: (Math.random() - 0.5) * 0.05, f: Math.random() * 6.28, c: pick(cols), a: 0.35 + 0.45 * z };
    }
    var N = Math.min(46, Math.round(W * H / 38000) + 10);
    for (var i = 0; i < N; i++) parts.push(make(true));
    function shape(p) {
      var s = p.s;
      switch (t.fx) {
        case 'snow':
          var gr = ctx.createRadialGradient(0, 0, 0, 0, 0, s); gr.addColorStop(0, '#ffffff'); gr.addColorStop(1, 'rgba(176,201,228,.85)');
          ctx.fillStyle = gr; ctx.beginPath(); ctx.arc(0, 0, s, 0, 6.283); ctx.fill(); break;
        case 'leaves':
          ctx.scale(Math.cos(p.f), 1); ctx.fillStyle = p.c; ctx.beginPath(); ctx.moveTo(0, -s); ctx.quadraticCurveTo(s, 0, 0, s); ctx.quadraticCurveTo(-s, 0, 0, -s); ctx.fill();
          ctx.strokeStyle = 'rgba(0,0,0,.18)'; ctx.lineWidth = 0.8; ctx.beginPath(); ctx.moveTo(0, -s); ctx.lineTo(0, s); ctx.stroke(); break;
        case 'petals':
          ctx.scale(1, 0.55 + 0.45 * Math.abs(Math.cos(p.f))); ctx.fillStyle = p.c; ctx.beginPath(); ctx.ellipse(0, 0, s * 0.8, s * 0.5, 0, 0, 6.283); ctx.fill(); break;
        case 'confetti':
          ctx.scale(1, Math.cos(p.f)); ctx.fillStyle = p.c; ctx.fillRect(-s * 0.5, -s * 0.22, s, s * 0.44); break;
        case 'hearts':
          ctx.fillStyle = p.c; ctx.beginPath(); ctx.moveTo(0, s * 0.6); ctx.bezierCurveTo(-s, 0, -s * 0.5, -s * 0.8, 0, -s * 0.2); ctx.bezierCurveTo(s * 0.5, -s * 0.8, s, 0, 0, s * 0.6); ctx.fill(); break;
        case 'shamrocks':
          ctx.fillStyle = p.c; [[0, -s * 0.4], [-s * 0.4, s * 0.15], [s * 0.4, s * 0.15]].forEach(function (d) { ctx.beginPath(); ctx.arc(d[0], d[1], s * 0.42, 0, 6.283); ctx.fill(); }); break;
        case 'stars':
          ctx.globalAlpha *= 0.55 + 0.45 * Math.abs(Math.sin(p.f)); ctx.fillStyle = p.c; ctx.beginPath();
          for (var k = 0; k < 10; k++) { var a = Math.PI / 5 * k - Math.PI / 2, rr = k % 2 ? s * 0.4 : s; ctx.lineTo(Math.cos(a) * rr, Math.sin(a) * rr); } ctx.fill(); break;
        case 'sparks':
          ctx.globalAlpha *= 0.5 + 0.5 * Math.abs(Math.sin(p.f)); var g2 = ctx.createRadialGradient(0, 0, 0, 0, 0, s * 0.6);
          g2.addColorStop(0, '#fff6d6'); g2.addColorStop(0.4, p.c); g2.addColorStop(1, 'rgba(242,165,22,0)'); ctx.fillStyle = g2; ctx.beginPath(); ctx.arc(0, 0, s * 0.6, 0, 6.283); ctx.fill(); break;
      }
    }
    function burst(now) {
      var x = W * (0.15 + Math.random() * 0.7), y = H * (0.12 + Math.random() * 0.3), c = pick(t.fireworks), n = 46;
      for (var k = 0; k < n; k++) { var a = k / n * 6.283, sp = 1.6 + Math.random() * 1.8; sparks.push({ x: x, y: y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, c: Math.random() < 0.25 ? '#ffffff' : c, born: now }); }
    }
    var last = 0;
    function frame(now) {
      raf = requestAnimationFrame(frame);
      if (document.hidden || now - last < 30) return;           // about 30 frames a second, nothing while hidden
      last = now; ctx.clearRect(0, 0, W, H);
      parts.forEach(function (p, i) {
        p.y += p.v; p.sw += p.sws; p.x += Math.sin(p.sw) * (0.4 + p.z * 0.5); p.r += p.vr; p.f += 0.06;
        if (p.y > H + 30 || p.y < -30 || p.x < -40 || p.x > W + 40) parts[i] = p = make(false);
        ctx.save(); ctx.globalAlpha = p.a; ctx.translate(p.x, p.y); if (t.fx !== 'snow' && t.fx !== 'sparks') ctx.rotate(p.r); shape(p); ctx.restore();
      });
      if (t.fireworks) {
        if (!nextBurst) nextBurst = now + 2500;
        if (now > nextBurst) { burst(now); nextBurst = now + 7000 + Math.random() * 7000; }
        sparks = sparks.filter(function (s) { return now - s.born < 1700; });
        sparks.forEach(function (s) {
          var age = (now - s.born) / 1700;
          s.x += s.vx; s.y += s.vy; s.vx *= 0.97; s.vy = s.vy * 0.97 + 0.045;
          ctx.globalAlpha = Math.max(0, 1 - age) * 0.9; ctx.fillStyle = s.c; ctx.beginPath(); ctx.arc(s.x, s.y, 2.1 * (1 - age * 0.5), 0, 6.283); ctx.fill();
        });
        ctx.globalAlpha = 1;
      }
    }
    raf = requestAnimationFrame(frame);
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
    if (a && T[a.key]) { if (gTheme !== a.key || !garland) drawGarland(a.key); drawScene(a.key); }
    else { if (garland) { garland.remove(); garland = null; } gTheme = null; if (scene) { scene.remove(); scene = null; } }
    if (a && t.fx !== false) { if (!canvas || canvas.getAttribute('data-k') !== a.key) { startFx(a.key); if (canvas) canvas.setAttribute('data-k', a.key); } }
    else stopFx();
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
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go); else go();   // the menu's foot comes after this script
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
