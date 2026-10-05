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
