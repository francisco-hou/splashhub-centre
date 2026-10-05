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

/* The top bar: who you are, top right. "User" for anybody; "Admin" once the
   admin password has been entered (SSO will put a real name here later). Its
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
  var here = function (p) { return path === p ? ' active' : ''; };
  var bar = document.createElement('header');
  bar.className = 'topbar';
  bar.innerHTML =
    '<div class="tb-right">' +
      '<button type="button" class="tb-user" id="userBtn" aria-haspopup="menu" aria-expanded="false" aria-controls="userMenu">' +
        '<span class="tb-av" id="userAv">' + SV(I.user) + '</span><span class="tb-name" id="userName">User</span>' + SV(I.caret) +
      '</button>' +
      '<div class="tb-menu" id="userMenu" role="menu" hidden>' +
        '<div class="tb-who"><span class="tb-av tb-av-lg" id="userAv2">' + SV(I.user) + '</span>' +
          '<span><b id="userName2">User</b><small id="userSub">Everyone on the team</small></span></div>' +
        '<div class="tb-sep"></div>' +
        '<div class="tb-group">Admin</div>' +
        '<a class="tb-item' + here('/logs') + '" href="/logs" role="menuitem">' + SV(I.logs) + 'Logs<span class="tb-lock" title="Needs the admin password">' + SV(I.lock) + '</span></a>' +
        '<a class="tb-item' + here('/settings') + '" href="/settings" role="menuitem">' + SV(I.gear) + 'Settings<span class="tb-lock" title="Needs the admin password">' + SV(I.lock) + '</span></a>' +
        '<div class="tb-sep"></div>' +
        '<a class="tb-item" id="adminIn" href="/logs?next=' + encodeURIComponent(path) + '" role="menuitem">' + SV(I.key) + 'Admin sign-in</a>' +
        '<button type="button" class="tb-item" id="signOut" role="menuitem" hidden>' + SV(I.out) + 'Sign out</button>' +
      '</div>' +
    '</div>';
  var nav = document.getElementById('snav');
  nav.parentNode.insertBefore(bar, nav.nextSibling);

  var btn = document.getElementById('userBtn'), menu = document.getElementById('userMenu');
  function open(on) { menu.hidden = !on; btn.setAttribute('aria-expanded', on); btn.classList.toggle('open', on); }
  btn.addEventListener('click', function (e) { e.stopPropagation(); open(menu.hidden); });
  document.addEventListener('click', function (e) { if (!menu.hidden && !menu.contains(e.target)) open(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !menu.hidden) { open(false); btn.focus(); } });

  // Who: Admin when the admin password is set and was entered here; else User.
  fetch('/api/session', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (s) {
    var admin = !!(s.required && s.authed);
    var name = admin ? 'Admin' : 'User';
    ['userName', 'userName2'].forEach(function (id) { document.getElementById(id).textContent = name; });
    ['userAv', 'userAv2'].forEach(function (id) { document.getElementById(id).innerHTML = SV(admin ? I.admin : I.user); });
    bar.classList.toggle('is-admin', admin);
    document.getElementById('userSub').textContent = admin ? 'Signed in with the admin password'
      : (s.required ? 'Logs and Settings need the admin password' : 'No admin password is set yet');
    // the locks only mean something when there is a password to ask for
    Array.prototype.forEach.call(menu.querySelectorAll('.tb-lock'), function (l) { l.hidden = admin || !s.required; });
    document.getElementById('adminIn').hidden = admin || !s.required;
    document.getElementById('signOut').hidden = !admin;
  }).catch(function () {});
})();
