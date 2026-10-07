// SplashHub Centre -- Wiki: every part of the app, one section at a time. The
// contents list (left) picks the section; /wiki#sso opens that one (shareable);
// links in the text and the Previous / Next links below each section move the
// same way. The search box looks through the whole wiki and lists every
// section that mentions the words, highlighted; clearing it goes back.
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  var parts = [].slice.call(document.querySelectorAll('.wiki-part'));
  var secs = [].slice.call(document.querySelectorAll('.wiki-sec'));
  var ids = secs.map(function (s) { return s.id; });
  function title(s) { return s.querySelector('h3').childNodes[0].textContent.trim(); }
  var cur = null, searching = false;

  // contents: one group per part, one link per section
  $('toc').innerHTML = parts.map(function (p) {
    return '<div class="toc-grp"><div class="toc-part">' + p.getAttribute('data-part') + '</div>' +
      [].map.call(p.querySelectorAll('.wiki-sec'), function (s) {
        return '<a href="#' + s.id + '" data-s="' + s.id + '">' + title(s) + '</a>';
      }).join('') + '</div>';
  }).join('');

  // Previous / Next, under the section shown
  var pager = document.createElement('nav');
  pager.className = 'wiki-pager';
  pager.setAttribute('aria-label', 'Previous and next section');
  $('doc').appendChild(pager);

  function show(id) {
    if (ids.indexOf(id) < 0) id = ids[0];
    cur = id;
    if (searching) return;
    var sec = $(id);
    secs.forEach(function (s) { s.hidden = s !== sec; });
    parts.forEach(function (p) { p.hidden = !p.contains(sec); });
    [].forEach.call($('toc').querySelectorAll('a'), function (a) { a.hidden = false; a.classList.toggle('on', a.getAttribute('data-s') === id); });
    [].forEach.call($('toc').querySelectorAll('.toc-grp'), function (g) { g.hidden = false; });
    var i = ids.indexOf(id), prev = secs[i - 1], next = secs[i + 1];
    pager.innerHTML = (prev ? '<a class="wp-prev" href="#' + prev.id + '"><span>&larr; Previous</span><b>' + title(prev) + '</b></a>' : '<span></span>') +
      (next ? '<a class="wp-next" href="#' + next.id + '"><span>Next &rarr;</span><b>' + title(next) + '</b></a>' : '<span></span>');
    pager.hidden = false;
    document.title = title(sec) + ' · Wiki · SplashHub Centre';
    window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', function () { show((location.hash || '').slice(1)); });

  // search: every section that mentions every word, highlighted
  var orig = {};
  secs.forEach(function (s) { orig[s.id] = s.innerHTML; });
  function hilite(node, re) {
    if (node.nodeType === 3) {
      if (!re.test(node.nodeValue)) return;
      var span = document.createElement('span');
      span.innerHTML = node.nodeValue.replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; })
        .replace(re, function (m) { return '<mark class="wiki-hit">' + m + '</mark>'; });
      node.parentNode.replaceChild(span, node);
      return;
    }
    if (node.nodeType === 1 && !/^(SCRIPT|STYLE|MARK|svg)$/i.test(node.tagName)) [].slice.call(node.childNodes).forEach(function (c) { hilite(c, re); });
  }
  var t = 0;
  $('wq').addEventListener('input', function () {
    clearTimeout(t);
    var q = this.value.trim().toLowerCase();
    t = setTimeout(function () {
      var words = q.split(/\s+/).filter(Boolean), shown = 0;
      secs.forEach(function (s) { s.innerHTML = orig[s.id]; });
      var none = $('wnone');
      if (!words.length) {                                   // back to the section you were on
        searching = false;
        if (none) none.hidden = true;
        show(cur);
        return;
      }
      searching = true;
      pager.hidden = true;
      var re = new RegExp('(' + words.map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }).join('|') + ')', 'gi');
      secs.forEach(function (s) {
        var hit = words.every(function (w) { return s.textContent.toLowerCase().indexOf(w) >= 0; });
        s.hidden = !hit;
        if (hit) { shown++; hilite(s, re); }
      });
      parts.forEach(function (p) { p.hidden = ![].some.call(p.querySelectorAll('.wiki-sec'), function (s) { return !s.hidden; }); });
      [].forEach.call($('toc').querySelectorAll('a'), function (a) { a.hidden = $(a.getAttribute('data-s')).hidden; a.classList.remove('on'); });
      [].forEach.call($('toc').querySelectorAll('.toc-grp'), function (g) { g.hidden = ![].some.call(g.querySelectorAll('a'), function (a) { return !a.hidden; }); });
      if (!shown && !none) { none = document.createElement('div'); none.id = 'wnone'; none.className = 'wiki-none'; $('doc').appendChild(none); }
      if (none) { none.hidden = !!shown; none.textContent = shown ? '' : 'Nothing in the wiki mentions “' + q + '”.'; }
    }, 150);
  });
  // a contents link while searching: leave the search and open that section
  $('toc').addEventListener('click', function (ev) {
    var a = ev.target.closest('a[data-s]'); if (!a || !searching) return;
    ev.preventDefault();
    $('wq').value = ''; searching = false;
    secs.forEach(function (s) { s.innerHTML = orig[s.id]; });
    var none = $('wnone'); if (none) none.hidden = true;
    if (location.hash === '#' + a.getAttribute('data-s')) show(a.getAttribute('data-s'));
    else location.hash = a.getAttribute('data-s');
  });

  // open at the top of the page, not where the browser would jump for #section
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  show((location.hash || '').slice(1));
  window.addEventListener('load', function () { setTimeout(function () { window.scrollTo(0, 0); }, 0); });
})();
