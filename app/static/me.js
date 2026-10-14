// SplashHub Centre -- My Dashboard (mydash.py): the signed-in person's own queue,
// the same cards as SplashHub's Dashboard in Zendesk. Ticket numbers open the
// ticket in Zendesk; a stat tile opens that search there.
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  var D = null, page = 0, PER = 10;

  function age(ms) {
    if (!ms) return '';
    var m = Math.max(1, Math.round((Date.now() - ms) / 60000));
    if (m < 60) return m + 'm';
    var h = Math.round(m / 60);
    return h < 48 ? h + 'h' : Math.round(h / 24) + 'd';
  }
  function tURL(id) { return D.zendesk + '/agent/tickets/' + id; }
  function sURL(q) { return D.zendesk + '/agent/search/1?' + new URLSearchParams({ q: q, type: 'ticket' }).toString(); }
  function pill(st) { return '<span class="md-pill md-' + esc(st || 'none') + '">' + esc(st || '') + '</span>'; }
  function row(t, right, extra) {
    return '<a class="md-row" href="' + tURL(t.id) + '" target="_blank" rel="noopener">' +
      '<span class="md-id">#' + t.id + '</span><span class="md-subj">' + esc(t.subject) + (extra || '') + '</span>' +
      pill(t.status) + '<span class="md-age">' + esc(right) + '</span></a>';
  }
  function empty(msg) { return '<div class="md-empty">' + msg + '</div>'; }
  function err(k) { return D.errors && D.errors[k] ? empty('Couldn&rsquo;t load: ' + esc(D.errors[k])) : null; }

  function stats() {
    var s = D.stats, q = D.queries;
    var tiles = [['Assigned by RR', s.rr, 'new or open', q.rr], ['Open', s.open, 'assigned to you', q.open],
                 ['Pending', s.pending, 'waiting on the customer', q.pending], ['On hold', s.hold, 'waiting on support', q.hold],
                 ['Solved / Closed', s.solved, s.month + ' so far', q.solved]];
    $('mdStats').innerHTML = tiles.map(function (t, i) {
      return '<a class="md-stat" href="' + sURL(t[3]) + '" target="_blank" rel="noopener" style="animation-delay:' + (i * 0.04).toFixed(2) + 's">' +
        '<span class="md-stat-l">' + t[0] + '</span><span class="md-stat-n">' + (t[1] == null ? '—' : Number(t[1]).toLocaleString()) + '</span>' +
        '<span class="md-stat-s">' + esc(t[2]) + '</span></a>';
    }).join('');
  }
  function rr() {
    $('mdRrCount').textContent = D.stats.rr ? D.stats.rr + (D.rr.length < D.stats.rr ? ' · showing ' + D.rr.length : '') : '';
    $('mdRrList').innerHTML = err('rr') || (D.rr.length ? D.rr.map(function (t) { return row(t, age(t.created)); }).join('')
      : empty('No round-robin tickets waiting on you.'));
  }
  function open() {
    var list = D.open, pages = Math.max(1, Math.ceil(list.length / PER));
    page = Math.min(page, pages - 1);
    $('mdOpenCount').textContent = D.stats.open ? D.stats.open + ' open' + (list.length < D.stats.open ? ' · first ' + list.length + ' loaded' : '') : '';
    $('mdOpenList').innerHTML = err('open') || (list.length ? list.slice(page * PER, page * PER + PER).map(function (t) { return row(t, age(t.updated)); }).join('')
      : empty('No open tickets assigned to you.'));
    $('mdOpenPager').hidden = pages < 2;
    $('mdPage').textContent = (page + 1) + ' / ' + pages;
    $('mdPrev').disabled = page === 0; $('mdNext').disabled = page >= pages - 1;
  }
  function pins() {
    var p = D.pins;
    if (err('pins')) { $('mdPinsList').innerHTML = err('pins'); $('mdPinsCount').textContent = ''; return; }
    $('mdPinsCount').textContent = p && p.waiting.length ? p.waiting.length + ' waiting' : '';
    $('mdPinsList').innerHTML = !p || !p.pinned ? empty('No pinned tickets. Pin a ticket from SplashHub&rsquo;s sidebar in Zendesk.')
      : !p.waiting.length ? empty('Nobody&rsquo;s waiting on your ' + p.pinned + ' pinned ticket' + (p.pinned === 1 ? '' : 's') + '.')
      : p.waiting.slice(0, 8).map(function (t) {
          return row(t, age(t.since), t.waiting > 1 ? ' <span class="md-n">' + t.waiting + ' replies</span>' : '');
        }).join('');
  }
  function langs() {
    var l = D.langs, card = $('mdLang');
    if (err('langs')) { card.hidden = false; $('mdLangList').innerHTML = err('langs'); return; }
    card.hidden = !l;
    if (!l) return;
    $('mdLangCount').textContent = l.tickets.length + ' in ' + l.langs.join(', ');
    $('mdLangList').innerHTML = l.tickets.length ? l.tickets.slice(0, 12).map(function (t) {
      return row(t, age(t.created), ' <span class="md-n">' + esc(t.lang.toUpperCase()) + (t.mine ? ' · yours' : t.assigned ? '' : ' · unassigned') + '</span>');
    }).join('') + (l.tickets.length > 12 ? empty('…and ' + (l.tickets.length - 12) + ' more') : '')
      : empty('No ' + esc(l.langs.join(' / ')) + ' RR tickets in the last 7 days (' + l.scanned + ' scanned).');
  }

  function draw() {
    var first = (D.me.name || '').split(' ')[0];
    $('mdSub').textContent = 'Your queue at a glance' + (first ? ', ' + first : '') + '.';
    $('mdStamp').textContent = 'Updated ' + new Date(D.ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    stats(); rr(); open(); pins(); langs();
  }
  function note(msg) { $('mdNote').hidden = !msg; $('mdNote').innerHTML = msg || ''; }

  function load(fresh) {
    var b = $('mdRefresh'); b.classList.add('spin'); b.disabled = true;
    fetch('/api/me/dashboard' + (fresh ? '?fresh=1' : ''), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.signin) { note(esc(d.error) + ' <a href="/auth/login?next=%2Fme">Sign in</a>'); return; }
        if (d.error) { note('Couldn&rsquo;t load your dashboard: ' + esc(d.error)); return; }
        note(''); D = d; draw();
      })
      .catch(function () { note('Couldn&rsquo;t reach SplashHub Centre. Try Refresh in a moment.'); })
      .then(function () { b.classList.remove('spin'); b.disabled = false; });
  }
  $('mdRefresh').addEventListener('click', function () { load(true); });
  $('mdPrev').addEventListener('click', function () { page--; open(); });
  $('mdNext').addEventListener('click', function () { page++; open(); });
  // Back on the tab after a while: quietly refresh (the server keeps a minute's copy).
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && D && Date.now() - D.ms > 120000) load(false);
  });
  load(false);
})();
