// SplashHub Centre -- Wiki: every part of the app in one organized page. The
// contents list (left) is built from the sections and follows the scroll; the
// search box keeps only the sections that mention the words, highlighted.
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  var parts = [].slice.call(document.querySelectorAll('.wiki-part'));
  var secs = [].slice.call(document.querySelectorAll('.wiki-sec'));

  // contents: one heading per part, one link per section
  $('toc').innerHTML = parts.map(function (p) {
    return '<div class="toc-grp"><div class="toc-part">' + p.getAttribute('data-part') + '</div>' +
      [].map.call(p.querySelectorAll('.wiki-sec'), function (s) {
        return '<a href="#' + s.id + '" data-s="' + s.id + '">' + s.querySelector('h3').childNodes[0].textContent.trim() + '</a>';
      }).join('') + '</div>';
  }).join('');

  // the section in view is lit in the contents
  function mark(id) {
    [].forEach.call($('toc').querySelectorAll('a'), function (a) { a.classList.toggle('on', a.getAttribute('data-s') === id); });
  }
  if (window.IntersectionObserver) {
    var seen = {};
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { seen[e.target.id] = e.isIntersecting ? e.boundingClientRect.top : null; });
      var best = null, top = 1e9;
      Object.keys(seen).forEach(function (k) { if (seen[k] != null && seen[k] < top) { top = seen[k]; best = k; } });
      if (best) mark(best);
    }, { rootMargin: '-70px 0px -55% 0px' });
    secs.forEach(function (s) { io.observe(s); });
  }

  // search: keep the sections that mention every word; highlight them
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
    if (node.nodeType === 1 && !/^(SCRIPT|STYLE|MARK)$/.test(node.tagName)) [].slice.call(node.childNodes).forEach(function (c) { hilite(c, re); });
  }
  var t = 0;
  $('wq').addEventListener('input', function () {
    clearTimeout(t);
    var q = this.value.trim().toLowerCase();
    t = setTimeout(function () {
      var words = q.split(/\s+/).filter(Boolean), shown = 0;
      secs.forEach(function (s) {
        s.innerHTML = orig[s.id];
        var hit = !words.length || words.every(function (w) { return s.textContent.toLowerCase().indexOf(w) >= 0; });
        s.hidden = !hit;
        if (hit) shown++;
        if (hit && words.length) {
          var re = new RegExp('(' + words.map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }).join('|') + ')', 'gi');
          hilite(s, re);
        }
      });
      parts.forEach(function (p) { p.hidden = ![].some.call(p.querySelectorAll('.wiki-sec'), function (s) { return !s.hidden; }); });
      [].forEach.call($('toc').querySelectorAll('a'), function (a) { a.hidden = $(a.getAttribute('data-s')).hidden; });
      [].forEach.call($('toc').querySelectorAll('.toc-grp'), function (g) { g.hidden = ![].some.call(g.querySelectorAll('a'), function (a) { return !a.hidden; }); });
      var none = $('wnone');
      if (!shown && !none) { none = document.createElement('div'); none.id = 'wnone'; none.className = 'wiki-none'; $('doc').appendChild(none); }
      if (none) { none.hidden = !!shown; none.textContent = shown ? '' : 'Nothing in the wiki mentions “' + q + '”.'; }
    }, 150);
  });
})();
