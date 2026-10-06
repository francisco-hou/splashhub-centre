// SplashHub Centre -- Customers page.
//
// One customer (an e-mail domain, or one address on a free e-mail provider) on
// one page, from what SplashHub Centre already holds (customers.py): their 2026
// Zendesk tickets, Custom SOS packages and SSO requests, the people who wrote
// in, and quick links. No search: the most active customers of the last 30 days.
// The open customer is in the address (#domain:datamaas.com) to share or reload.
(function () {
  'use strict';

  var ZD = '';
  var VERDICT = { normal: 'Verified', needs_review: 'Needs review', suspicious: 'High risk' };
  var SSO = { needs_details: 'Needs details', pending: 'Not checked', not_found: 'Not found yet', verified: 'Verified', error: 'Check failed' };
  var OPEN = { new: 1, open: 1, pending: 1, hold: 1 };
  var SPARK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/></svg>';
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var OUT = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>';

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function int(n) { return (n || 0).toLocaleString('en-US'); }
  function day(ms) { return ms ? new Date(ms).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : ''; }
  function ago(ms) {
    if (!ms) return '';
    var d = (Date.now() - ms) / 86400000;
    return d < 1 ? 'today' : d < 2 ? 'yesterday' : d < 60 ? Math.round(d) + ' days ago' : Math.round(d / 30) + ' months ago';
  }
  function api(path) {
    return fetch(path, { credentials: 'same-origin' }).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function zdTicket(id) {
    return ZD ? '<a href="' + esc(ZD) + '/agent/tickets/' + id + '" target="_blank" rel="noopener">#' + id + '</a>' : '#' + id;
  }
  function plural(n, one, many) { return int(n) + ' ' + (n === 1 ? one : (many || one + 's')); }

  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (x) { ZD = x.zendesk_url || ''; route(); }).catch(function () { route(); });
  $('page').hidden = false;

  // ---- the address decides what shows ---------------------------------------------------
  function route() {
    var m = /^#((domain|email):.+)$/.exec(decodeURIComponent(location.hash || ''));
    if (m) open(m[1]); else showTop();
  }
  window.addEventListener('hashchange', route);

  function card(c) {
    var bits = [];
    if (c.tickets) bits.push('<span class="cu-chip">' + plural(c.tickets, 'ticket') + (c.open ? ' &middot; <b>' + int(c.open) + ' open</b>' : '') + '</span>');
    if (c.sos) bits.push('<span class="cu-chip' + (c.flagged ? ' warn' : '') + '">' + plural(c.sos, 'SOS package') + (c.flagged ? ' &middot; ' + int(c.flagged) + ' flagged' : '') + '</span>');
    if (c.sso) bits.push('<span class="cu-chip">' + plural(c.sso, 'SSO request') + '</span>');
    return '<a class="cu-card" href="#' + esc(c.key) + '"><div class="cu-card-h"><b>' + esc(c.label) + '</b>' +
      (c.last_ms ? '<span class="muted">' + esc(ago(c.last_ms)) + '</span>' : '') + '</div>' +
      (c.orgs && c.orgs.length ? '<div class="cu-orgs">' + esc(c.orgs.join(' · ')) + '</div>' : '') +
      '<div class="cu-chips">' + bits.join('') + '</div></a>';
  }

  function showTop() {
    $('matches').innerHTML = '';
    $('msg').textContent = '';
    $('view').innerHTML = '<div class="pn-loading">Loading…</div>';
    api('/api/customers/top').then(function (d) {
      $('view').innerHTML = '<section class="card cu-section"><div class="card-head"><h2 class="card-title">Most active customers</h2>' +
        '<span class="count">last ' + d.days + ' days &middot; tickets, SOS and SSO requests</span></div>' +
        (d.customers.length ? '<div class="cu-grid">' + d.customers.map(card).join('') + '</div>'
                            : '<div class="cu-empty">Nothing yet. Customers appear as tickets, SOS and SSO requests come in.</div>') + '</section>';
    }).catch(function (e) { $('view').innerHTML = '<div class="cu-empty">Could not load: ' + esc(e.message) + '</div>'; });
  }

  // ---- search ----------------------------------------------------------------------------
  $('form').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var q = $('q').value.trim();
    if (!q) { location.hash = ''; showTop(); return; }
    $('msg').textContent = 'Looking…';
    $('matches').innerHTML = '';
    api('/api/customers/find?q=' + encodeURIComponent(q)).then(function (d) {
      if (d.matches.length === 1) { $('msg').textContent = ''; location.hash = d.matches[0].key; return; }
      if (!d.matches.length) { $('msg').textContent = d.note || 'No customer found for “' + q + '”.'; return; }
      $('msg').textContent = d.matches.length + ' customers match — pick one:';
      $('matches').innerHTML = '<div class="cu-grid">' + d.matches.map(card).join('') + '</div>';
    }).catch(function (e) { $('msg').textContent = e.message; });
  });

  // ---- one customer ----------------------------------------------------------------------
  function open(key) {
    $('matches').innerHTML = '';
    $('msg').textContent = '';
    $('view').innerHTML = '<div class="pn-loading">Loading…</div>';
    api('/api/customers/profile?key=' + encodeURIComponent(key)).then(function (c) {
      $('q').value = c.label;
      $('view').innerHTML = profile(c);
      loadSummary(c.key);
    }).catch(function (e) { $('view').innerHTML = '<div class="cu-empty">' + esc(e.message) + '</div>'; });
  }

  function stat(label, value, sub, cls) {
    return '<div class="stat"><div class="stat-label">' + label + '</div><div class="stat-value ' + (cls || '') + '">' + value + '</div><div class="stat-sub">' + sub + '</div></div>';
  }
  function months(list) {
    if (!list.length) return '';
    var max = Math.max.apply(null, list.map(function (m) { return m.n; }));
    return '<div class="kb-months cu-months">' + list.map(function (m) {
      return '<div class="kb-month" title="' + esc(m.month) + ': ' + m.n + '"><i style="height:' + Math.max(6, Math.round(100 * m.n / max)) + '%"></i><span>' +
        esc(MON[+m.month.slice(5) - 1] || m.month) + '</span></div>';
    }).join('') + '</div>';
  }
  function tstatus(st) { return st ? '<span class="tst tst-' + esc(st) + '">' + esc(st.charAt(0).toUpperCase() + st.slice(1)) + '</span>' : ''; }

  function profile(c) {
    var links = [];
    if (ZD) links.push('<a class="btn btn-sm" href="' + esc(ZD) + '/agent/search/1?type=ticket&q=' + encodeURIComponent(c.kind === 'email' ? 'requester:' + c.label : c.domain) +
      '" target="_blank" rel="noopener">Tickets in Zendesk ' + OUT + '</a>');
    // the SOS request's links, named as on SOS Scans
    var NAMES = { 'team info': 'View team on ACP', 'manage': 'Manage SOS PKG on ACP', 'download package': 'Download package' };
    (c.links || []).forEach(function (l) {
      links.push('<a class="btn btn-sm" href="' + esc(l.url) + '" target="_blank" rel="noopener">' + esc(NAMES[String(l.label).toLowerCase()] || l.label) + ' ' + OUT + '</a>');
    });

    var h = '<section class="card cu-head"><div class="cu-head-l"><h2 class="cu-title">' + esc(c.label) + '</h2>' +
      '<div class="cu-sub">' + [c.orgs.length ? esc(c.orgs.join(' · ')) : '', c.countries.length ? esc(c.countries.join(', ')) + ' <span class="muted">(guess)</span>' : '',
        c.first_ms ? 'first seen ' + esc(day(c.first_ms)) : ''].filter(Boolean).join(' &nbsp;&middot;&nbsp; ') + '</div>' +
      (c.generic ? '<div class="cu-generic">Free e-mail provider: only this one address is shown, not everyone at ' + esc(c.domain) + '.</div>' : '') +
      (c.people.length ? '<div class="cu-people">' + c.people.slice(0, 8).map(function (p) {
        return '<a href="#email:' + esc(p.email) + '" title="Only this address">' + esc(p.email) + ' <i>' + p.n + '</i></a>';
      }).join('') + '</div>' : '') +
      '</div><div class="cu-links">' + links.join('') + '</div></section>';

    // the AI summary: filled in by loadSummary() when Spark has written it
    h += '<section class="card cu-ai" id="cuAi"><div class="cu-ai-h"><span class="cu-ai-t">' + SPARK + 'Summary</span><span class="snav-ai">Spark</span>' +
      '<span class="cu-ai-when" id="cuAiWhen"></span><button type="button" class="btn btn-sm" id="cuAiAgain" title="Write it again">Refresh</button></div>' +
      '<div class="cu-ai-body" id="cuAiBody"><span class="cu-ai-wait">Spark is reading this customer’s records…</span></div></section>';

    var verified = (c.sso_requests || []).filter(function (s) { return s.status === 'verified'; }).length;
    var nextProv = (c.provisioning_requests || []).filter(function (p) { return OPEN[p.status]; }).length;
    h += '<div class="stats">' +
      stat('Tickets, 2026', int(c.tickets), c.open ? '<b>' + int(c.open) + '</b> still open' : (c.tickets ? 'none open' : '&nbsp;')) +
      stat('Provisioning', int(c.provisioning), c.provisioning ? (nextProv ? int(nextProv) + ' pending' : 'none pending') : 'no requests') +
      stat('Custom SOS packages', int(c.sos), c.flagged ? int(c.flagged) + ' needs review / high risk' : (c.sos ? 'none flagged' : 'none'), c.flagged ? 'cu-warn' : '') +
      stat('SSO requests', int(c.sso), c.sso ? int(verified) + ' verified' : 'none') + '</div>';

    // 1) their tickets
    var T = '<section class="card cu-section"><div class="card-head"><h2 class="card-title">Tickets</h2><span class="count">2026' +
      (c.provisioning ? ' &middot; provisioning requests are in their own box below' : '') + '</span></div><div class="cu-pad">';
    if (!c.tickets) {
      T += '<div class="cu-empty">No 2026 tickets from ' + (c.kind === 'email' ? 'this address' : 'this domain') + ' (or Zendesk Tickets aren&rsquo;t downloaded yet).</div>';
    } else {
      T += '<div class="cu-tix"><div class="cu-tix-l">' + months(c.per_month) +
        (c.topics.length ? '<div class="cu-h">Topics</div><div class="cu-tags">' + c.topics.map(function (t) { return '<span>' + esc(t) + '</span>'; }).join('') + '</div>' : '') +
        (c.tags.length ? '<div class="cu-h">Tags</div><div class="cu-tags">' + c.tags.map(function (t) { return '<span>' + esc(t.tag) + ' <i>' + t.n + '</i></span>'; }).join('') + '</div>' : '') +
        '</div><div class="cu-tix-r"><table class="runs cu-table"><tbody>' + c.recent_tickets.map(function (t) {
          return '<tr><td class="when">' + esc(day(t.created_ms)) + '</td><td>' + zdTicket(t.ticket_id) + '</td><td class="cu-subj" title="' + esc(t.subject) + '">' + esc(t.subject || '') +
            (c.kind === 'domain' && t.requester_email ? '<span class="muted"> &middot; ' + esc(t.requester_email) + '</span>' : '') + '</td><td>' + tstatus(t.status) + '</td></tr>';
        }).join('') + '</tbody></table>' + (c.tickets > c.recent_tickets.length ? '<div class="cu-more">Latest ' + c.recent_tickets.length + ' of ' + int(c.tickets) + '.</div>' : '') +
        '</div></div>';
    }
    T += '</div></section>';

    // 2) the rest, each in its own box -- only when there are any
    var boxes = [];
    if (c.provisioning_requests && c.provisioning_requests.length) {
      boxes.push(box('Provisioning requests', c.provisioning, c.provisioning_requests.map(function (p) {
        var due = p.expected ? 'expected ' + esc(p.expected) : '';
        return '<div class="cu-row"><span class="cu-row-t"><b>' + esc(p.product || p.subject || 'Provisioning request') + (p.quantity ? ' <span class="cu-qty">&times; ' + int(p.quantity) + '</span>' : '') + '</b>' +
          '<span class="muted cu-row-s">' + [p.order_type ? esc(p.order_type) : '', due, zdTicket(p.ticket_id) + ' &middot; ' + esc(day(p.created_ms))].filter(Boolean).join(' &middot; ') + '</span></span>' +
          tstatus(p.status) + '</div>';
      })));
    }
    if (c.packages && c.packages.length) {
      boxes.push(box('Custom SOS packages', c.sos, c.packages.map(function (p) {
        return '<a class="cu-row" href="/scans#' + p.id + '"><span class="cu-row-t"><b>' + esc(p.name || 'Package') +
          (p.type ? ' <span class="' + (String(p.type).toLowerCase() === 'trial' ? 'cu-trial' : 'cu-type') + '">' + esc(p.type) + '</span>' : '') + '</b>' +
          '<span class="muted cu-row-s">' + esc(day(p.requested_ms)) + ' &middot; #' + p.ticket + (p.creator && c.kind === 'domain' ? ' &middot; ' + esc(p.creator) : '') + '</span></span>' +
          (p.verdict ? '<span class="vpill v-' + esc(p.verdict) + '">' + esc(VERDICT[p.verdict] || p.verdict) + '</span>' : '<span class="muted">not reviewed</span>') + '</a>';
      })));
    }
    if (c.sso_requests && c.sso_requests.length) {
      boxes.push(box('SSO requests', c.sso, c.sso_requests.map(function (s) {
        return '<a class="cu-row" href="/sso#' + s.id + '"><span class="cu-row-t"><b>' + esc(s.domain || '(no domain yet)') + '</b><span class="muted cu-row-s">' +
          esc(day(s.requested_ms)) + ' &middot; #' + s.ticket_id + '</span></span><span class="vpill s-' + esc(s.status) + '">' + esc(SSO[s.status] || s.status) + '</span></a>';
      })));
    }
    var none = [!c.provisioning ? 'provisioning requests' : '', !c.sos ? 'Custom SOS packages' : '', !c.sso ? 'SSO requests' : ''].filter(Boolean);
    return h + T + (boxes.length ? '<div class="cu-boxes">' + boxes.join('') + '</div>' : '') +
      (none.length ? '<div class="cu-none">No ' + none.join(', ').replace(/, ([^,]*)$/, ' or $1') + '.</div>' : '');
  }
  function box(title, n, rows) {
    return '<section class="card cu-section"><div class="card-head"><h2 class="card-title">' + esc(title) + '</h2><span class="count">' + int(n) + '</span></div>' +
      '<div class="cu-pad">' + rows.join('') + '</div></section>';
  }

  // ---- the AI summary (Spark writes it in the background; ask again until it's there) ----
  var sumT = null, sumKey = null;
  function loadSummary(key, fresh, tries) {
    clearTimeout(sumT);
    sumKey = key;
    api('/api/customers/summary?key=' + encodeURIComponent(key) + (fresh ? '&fresh=1' : '')).then(function (s) {
      if (sumKey !== key || !$('cuAiBody')) return;
      var body = $('cuAiBody');
      if (s.off) { $('cuAi').hidden = true; return; }
      if (s.pending) {
        if (s.old && s.old.points) drawPoints(s.old, true);
        else body.innerHTML = '<span class="cu-ai-wait">Spark is reading this customer’s records…</span>';
        if ((tries || 0) < 30) sumT = setTimeout(function () { loadSummary(key, false, (tries || 0) + 1); }, 2500);
        return;
      }
      if (s.error) { body.innerHTML = '<span class="muted">Spark couldn’t write the summary: ' + esc(s.error) + '</span>'; return; }
      drawPoints(s, false);
    }).catch(function () {});
  }
  function drawPoints(s, updating) {
    $('cuAiBody').innerHTML = '<ul>' + s.points.map(function (p) {
      return '<li>' + esc(p).replace(/#(\d{3,9})\b/g, function (m, n) { return ZD ? '<a href="' + esc(ZD) + '/agent/tickets/' + n + '" target="_blank" rel="noopener">#' + n + '</a>' : m; }) + '</li>';
    }).join('') + '</ul>';
    $('cuAiWhen').textContent = updating ? 'updating…' : (s.ms ? 'written ' + ago(s.ms) : '');
  }
  document.addEventListener('click', function (ev) {
    if (ev.target.closest('#cuAiAgain') && sumKey) {
      $('cuAiBody').innerHTML = '<span class="cu-ai-wait">Spark is writing it again…</span>';
      $('cuAiWhen').textContent = '';
      loadSummary(sumKey, true);
    }
  });
})();
