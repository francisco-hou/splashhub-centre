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

/* Admin (above Sign out): opens Logs and Settings, the two pages that need the
   admin password. Open on those pages; elsewhere as last left, per browser. */
(function () {
  var btn = document.getElementById('adminBtn'), menu = document.getElementById('adminMenu'), KEY = 'shcAdminOpen';
  if (!btn || !menu) return;
  var here = !!menu.querySelector('.snav-item.active');
  function show(open) {
    menu.hidden = !open;
    btn.setAttribute('aria-expanded', open);
    btn.classList.toggle('open', open);
    btn.classList.toggle('here', here && !open);
  }
  var kept = false;
  try { kept = localStorage.getItem(KEY) === '1'; } catch (e) {}
  show(here || kept);
  btn.addEventListener('click', function () {
    var open = menu.hidden;
    show(open);
    try { localStorage.setItem(KEY, open ? '1' : '0'); } catch (e) {}
  });
})();
