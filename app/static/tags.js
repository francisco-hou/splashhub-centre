// SplashHub Centre -- Tags page (tags.py): tickets per Zendesk tag, from the
// Zendesk Tickets data. Sets: Topics (SplashHub's list, with its groups),
// Languages, All tags (the most used, found by themselves). Period: today / 7 /
// 30 days. Views: Share (donut) and Heatmap (8 weeks). The table sorts by any
// column; every count opens the matching Zendesk search. The chosen topics and
// the last set / period / view are remembered in this browser.
(function () {
  'use strict';

  var COLORS = ['#0071ce', '#7cc79a', '#f2a65a', '#e05a4f', '#8e6bd6', '#36a3b8', '#d4a72c', '#c06c9a', '#5b8c3a', '#9aa6b2'];
  var KEY = 'shcTags';
  var S = load() || { kind: 'topics', win: 'd7', view: 'share', sort: 'd7', dir: -1, select: null };
  var DATA = null, ZD = '';

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function int(n) { return (n || 0).toLocaleString('en-US'); }
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { return null; } }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) {} }
  function api(path) {
    return fetch(path, { credentials: 'same-origin' }).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function seg(id, key) {
    Array.prototype.forEach.call($(id).children, function (b) { b.classList.toggle('on', b.getAttribute('data-v') === S[key]); });
  }
  function days(win) { return win === 'today' ? 0 : win === 'd7' ? 7 : 30; }
  function zdLink(r, n) {
    if (!ZD || !n) return int(n);
    var d = new Date(Date.now() - days(S.win) * 86400000).toISOString().slice(0, 10);
    var q = 'type:ticket tags:' + r.tags.join(',') + ' created>=' + d;
    return '<a href="' + esc(ZD) + '/agent/search/1?type=ticket&q=' + encodeURIComponent(q) + '" target="_blank" rel="noopener">' + int(n) + '</a>';
  }
  function change(r) {
    var now = S.win === 'd30' ? r.d30 : r.d7, before = S.win === 'd30' ? r.prev30 : r.prev7;
    if (S.win === 'today') return null;
    if (!before) return now ? 100 : 0;
    return Math.round(100 * (now - before) / before);
  }

  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (x) { ZD = x.zendesk_url || ''; if (DATA) draw(); }).catch(function () {});
  seg('kind', 'kind'); seg('win', 'win'); seg('vw', 'view');
  fetchData();

  function fetchData() {
    $('pick').hidden = S.kind !== 'topics';
    var q = 'kind=' + S.kind + '&tz=' + new Date().getTimezoneOffset();     // all rows; the chosen topics are picked here
    api('/api/tags?' + q).then(function (d) {
      DATA = d;
      $('empty').hidden = d.ready;
      $('stamp').textContent = int(d.total.d7) + ' tickets in 7 days';
      if (d.choices && !S.select) {           // first visit: the groups plus the busiest topics
        S.select = d.rows.slice().sort(function (a, b) { return b.d30 - a.d30; }).filter(function (r) { return r.d30; })
          .slice(0, 10).map(function (r) { return r.label; });
        save();
      }
      draw();
    }).catch(function (e) { $('rows').innerHTML = '<tr class="empty-row"><td colspan="5">Could not load: ' + esc(e.message) + '</td></tr>'; });
  }

  function rows() {
    var rs = DATA.rows.slice();
    if (S.kind === 'topics' && S.select) rs = rs.filter(function (r) { return S.select.indexOf(r.label) >= 0; });
    rs.forEach(function (r) { r.change = change(r); });
    var k = S.sort;
    rs.sort(function (a, b) {
      var x = a[k], y = b[k];
      if (k === 'label') return S.dir * String(x).localeCompare(String(y));
      return S.dir * (((x == null) ? -1e9 : x) - ((y == null) ? -1e9 : y));
    });
    return rs;
  }

  function draw() {
    var rs = rows();
    $('count').textContent = rs.length + (rs.length === 1 ? ' tag' : ' tags');
    $('rows').innerHTML = rs.length ? rs.map(function (r, i) {
      var c = r.change;
      return '<tr><td><span class="tg-dot" style="background:' + COLORS[i % COLORS.length] + '"></span>' + esc(r.label) +
        (r.group ? ' <span class="tg-grp" title="' + esc(r.tags.join(', ')) + '">group</span>' : '') + '</td>' +
        '<td class="n">' + zdLink(r, r.today) + '</td><td class="n">' + zdLink(r, r.d7) + '</td><td class="n">' + zdLink(r, r.d30) + '</td>' +
        '<td class="n">' + (c == null ? '<span class="muted">&mdash;</span>' : '<span class="' + (c > 0 ? 'd-up' : c < 0 ? 'd-dn' : 'muted') + '">' +
          (c > 0 ? '▲ ' : c < 0 ? '▼ ' : '') + Math.abs(c) + '%</span>') + '</td></tr>';
    }).join('') : '<tr class="empty-row"><td colspan="5">Nothing to show.</td></tr>';
    Array.prototype.forEach.call(document.querySelectorAll('.tg-table th[data-sort]'), function (th) {
      th.classList.toggle('sorted', th.getAttribute('data-sort') === S.sort);
      th.setAttribute('data-dir', S.dir > 0 ? 'asc' : 'desc');
    });
    if (S.view === 'heat') heat(rs); else donut(rs);
  }

  function donut(rs) {
    var key = S.win, total = rs.reduce(function (t, r) { return t + (r[key] || 0); }, 0);
    $('chartTitle').textContent = 'Share';
    $('chartSub').textContent = (S.win === 'today' ? 'today' : S.win === 'd7' ? 'last 7 days' : 'last 30 days') + ' · ' + int(total) + ' tag uses';
    if (!total) { $('chart').innerHTML = '<div class="cu-empty">No tickets with these tags in this period.</div>'; return; }
    var R = 70, C = 2 * Math.PI * R, off = 0, segs = '', legend = '';
    rs.forEach(function (r, i) {
      var v = r[key] || 0; if (!v) return;
      var len = C * v / total, col = COLORS[i % COLORS.length];
      segs += '<circle r="' + R + '" cx="100" cy="100" fill="none" stroke="' + col + '" stroke-width="26" stroke-dasharray="' + len.toFixed(2) + ' ' + (C - len).toFixed(2) +
        '" stroke-dashoffset="' + (-off).toFixed(2) + '"><title>' + esc(r.label) + ': ' + v + '</title></circle>';
      off += len;
      legend += '<div class="tg-leg"><span class="tg-dot" style="background:' + col + '"></span><span class="tg-leg-l">' + esc(r.label) + '</span><b>' + Math.round(100 * v / total) + '%</b></div>';
    });
    $('chart').innerHTML = '<div class="tg-donut"><svg viewBox="0 0 200 200" width="200" height="200" aria-hidden="true"><g transform="rotate(-90 100 100)">' + segs + '</g>' +
      '<text x="100" y="96" text-anchor="middle" class="tg-tot">' + int(total) + '</text><text x="100" y="116" text-anchor="middle" class="tg-tot-s">tag uses</text></svg>' +
      '<div class="tg-legend">' + legend + '</div></div>';
  }

  function heat(rs) {
    $('chartTitle').textContent = 'Heatmap';
    $('chartSub').textContent = 'tickets per week · last 8 weeks';
    var max = Math.max.apply(null, [1].concat(rs.map(function (r) { return Math.max.apply(null, r.weeks); })));
    var head = '<tr><th></th>' + DATA.weeks.map(function (w) { var d = new Date(w); return '<th>' + (d.getMonth() + 1) + '/' + d.getDate() + '</th>'; }).join('') + '</tr>';
    var body = rs.map(function (r) {
      return '<tr><th title="' + esc(r.label) + '">' + esc(r.label) + '</th>' + r.weeks.map(function (n) {
        var a = n ? 0.12 + 0.88 * n / max : 0;
        return '<td style="background:rgba(0,113,206,' + a.toFixed(2) + ');color:' + (a > 0.55 ? '#fff' : '#3d4650') + '">' + (n || '') + '</td>';
      }).join('') + '</tr>';
    }).join('');
    $('chart').innerHTML = '<div class="tg-heat-wrap"><table class="tg-heat">' + head + body + '</table></div>';
  }

  // ---- controls -------------------------------------------------------------------------------
  function onSeg(id, key, refetch) {
    $(id).addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-v]'); if (!b) return;
      S[key] = b.getAttribute('data-v'); seg(id, key); save();
      if (key === 'win' && S.sort !== 'label' && S.sort !== 'change') S.sort = S.win;
      if (refetch) fetchData(); else draw();
    });
  }
  onSeg('kind', 'kind', true); onSeg('win', 'win', false); onSeg('vw', 'view', false);
  document.querySelector('.tg-table thead').addEventListener('click', function (ev) {
    var th = ev.target.closest('[data-sort]'); if (!th) return;
    var k = th.getAttribute('data-sort');
    S.dir = S.sort === k ? -S.dir : (k === 'label' ? 1 : -1); S.sort = k; save(); draw();
  });
  // Choose topics (up to 15 on screen at once)
  $('pick').addEventListener('click', function () {
    var p = $('picker'); p.hidden = !p.hidden;
    if (!p.hidden) drawChoices();
  });
  function drawChoices() {
    var q = $('pickQ').value.trim().toLowerCase(), sel = S.select || [];
    $('choices').innerHTML = (DATA.choices || []).filter(function (c) { return !q || c.toLowerCase().indexOf(q) >= 0; }).map(function (c) {
      return '<label class="tg-choice"><input type="checkbox" value="' + esc(c) + '"' + (sel.indexOf(c) >= 0 ? ' checked' : '') + '> ' + esc(c) + '</label>';
    }).join('');
  }
  $('pickQ').addEventListener('input', drawChoices);
  $('choices').addEventListener('change', function (ev) {
    var c = ev.target; if (!c.value) return;
    var sel = (S.select || []).slice(), i = sel.indexOf(c.value);
    if (c.checked && i < 0) {
      if (sel.length >= 15) { c.checked = false; $('pickMsg').textContent = 'Up to 15 at once.'; return; }
      sel.push(c.value);
    } else if (!c.checked && i >= 0) sel.splice(i, 1);
    S.select = sel; $('pickMsg').textContent = sel.length + ' chosen';
  });
  $('pickApply').addEventListener('click', function () { save(); $('picker').hidden = true; draw(); });
})();
