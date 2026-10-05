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
