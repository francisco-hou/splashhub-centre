// SplashHub Centre -- Customers page.
//
// A search first: a domain, an address or a company name, with matches as you
// type and the customers looked at lately. Picking one opens their summary,
// from what SplashHub Centre already holds (customers.py): the status at a
// glance, Spark's summary, the open tickets, and one timeline of tickets,
// orders, Custom SOS packages and SSO requests. A ticket opens in a preview
// (the whole conversation, read from Zendesk now) -- only the customer's own.
// The open customer is in the address (#domain:datamaas.com) to share or reload.
(function () {
  'use strict';

  var ZD = '', CUR = null, FILTER = 'all', ALL = false, FIRST = 10;
  var VERDICT = { normal: 'Verified', needs_review: 'Needs review', suspicious: 'High risk' };
  var SSO = { needs_details: 'Needs details', pending: 'Not checked', not_found: 'Not found yet', verified: 'Verified', enabled: 'Enabled', error: 'Check failed' };
  var TST = { new: 'New', open: 'Open', pending: 'Pending', hold: 'On-hold', solved: 'Solved', closed: 'Closed' };
  var OPEN = { new: 1, open: 1, pending: 1, hold: 1 };
  var RECENT_KEY = 'shcCustRecent';
  var SPARK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/></svg>';
  var OUT = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>';
  var ICON = {
    tk: '<path d="M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4z"/>',
    po: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
    sos: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/>',
    sso: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2"/><path d="M16 7l3 3"/>'
  };
  function ico(k) { return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICON[k] + '</svg>'; }

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function int(n) { return (n || 0).toLocaleString('en-US'); }
  function day(ms) { return ms ? new Date(ms).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : ''; }
  function short(ms) { return ms ? new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : ''; }
  function ago(ms) {
    if (!ms) return '';
    var d = (Date.now() - ms) / 86400000;
    return d < 1 / 24 ? 'just now' : d < 1 ? Math.round(d * 24) + ' h ago' : d < 2 ? 'yesterday' : d < 60 ? Math.round(d) + ' days ago' : Math.round(d / 30) + ' months ago';
  }
  function api(path) {
    return fetch(path, { credentials: 'same-origin' }).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function plural(n, one, many) { return int(n) + ' ' + (n === 1 ? one : (many || one + 's')); }
  function initials(s) { var w = String(s || '?').replace(/[^A-Za-z0-9 .@-]/g, '').split(/[\s.@-]+/).filter(Boolean); return ((w[0] || '?')[0] + ((w[1] || '')[0] || '')).toUpperCase(); }

  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (x) { ZD = x.zendesk_url || ''; route(); }).catch(function () { route(); });
  $('page').hidden = false;

  // ---- the address decides what shows: the search, or one customer ------------------------
  function route() {
    var m = /^#((domain|email):.+)$/.exec(decodeURIComponent(location.hash || ''));
    if (m) open(m[1]); else showSearch();
  }
  window.addEventListener('hashchange', route);

  // ---- search: matches as you type, recent customers -------------------------------------------
  function recent() { try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); } catch (e) { return []; } }
  function remember(c) {
    var r = recent().filter(function (x) { return x.key !== c.key; });
    r.unshift({ key: c.key, label: c.label, org: (c.orgs || [])[0] || '' });
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(r.slice(0, 6))); } catch (e) { /* private window */ }
  }
  function showSearch() {
    CUR = null;
    $('searchView').hidden = false; $('view').hidden = true; $('view').innerHTML = '';
    $('q').value = ''; $('sugg').hidden = true; $('err').textContent = '';
    var r = recent();
    $('recent').innerHTML = r.length ? 'Recent: ' + r.map(function (x) { return '<a href="#' + esc(x.key) + '">' + esc(x.org || x.label) + '</a>'; }).join(' · ') : '';
    setTimeout(function () { $('q').focus(); }, 0);
  }
  function suggRow(c) {
    var bits = [c.label];
    if (c.tickets) bits.push(plural(c.tickets, 'ticket') + (c.open ? ' (' + int(c.open) + ' open)' : ''));
    if (c.provisioning) bits.push(plural(c.provisioning, 'order'));
    if (c.sos) bits.push(plural(c.sos, 'SOS package'));
    if (c.sso) bits.push(plural(c.sso, 'SSO request'));
    return '<a class="cs-sug" href="#' + esc(c.key) + '"><span class="cs-sav">' + esc(initials((c.orgs || [])[0] || c.label)) + '</span><span class="cs-st">' +
      '<b>' + esc((c.orgs || [])[0] || c.label) + '</b><span class="muted">' + esc(bits.join(' · ')) + '</span></span>' +
      (c.last_ms ? '<span class="muted cs-when">' + esc(ago(c.last_ms)) + '</span>' : '') + '</a>';
  }
  var sT = 0, sSeq = 0, last = [];
  function suggest(now) {
    clearTimeout(sT);
    var q = $('q').value.trim();
    $('err').textContent = '';
    if (q.length < 2) { $('sugg').hidden = true; last = []; return; }
    sT = setTimeout(function () {
      var my = ++sSeq;
      $('sugg').hidden = false;
      $('sugg').innerHTML = '<div class="cs-none">Looking…</div>';
      api('/api/customers/find?q=' + encodeURIComponent(q)).then(function (d) {
        if (my !== sSeq) return;
        last = d.matches;
        $('sugg').innerHTML = d.matches.length ? d.matches.map(suggRow).join('') : '<div class="cs-none">' + esc(d.note || 'No customer matches “' + q + '”.') + '</div>';
      }).catch(function (e) { if (my === sSeq) $('sugg').innerHTML = '<div class="cs-none">' + esc(e.message) + '</div>'; });
    }, now ? 0 : 250);
  }
  $('q').addEventListener('input', function () { suggest(false); });
  $('form').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var q = $('q').value.trim();
    if (q.length < 2) { $('err').textContent = 'Type at least 2 letters.'; return; }
    if (last.length) { location.hash = last[0].key; return; }        // Enter: the first match
    suggest(true);
  });

  // ---- one customer -----------------------------------------------------------------------------
  function open(key) {
    $('searchView').hidden = true; $('view').hidden = false;
    $('view').innerHTML = '<div class="pn-loading">Loading…</div>';
    api('/api/customers/profile?key=' + encodeURIComponent(key)).then(function (c) {
      CUR = c; FILTER = 'all'; ALL = false;
      remember(c);
      $('view').innerHTML = render(c);
      drawTimeline();
      loadSummary(c.key);
      window.scrollTo(0, 0);
    }).catch(function (e) {
      $('view').innerHTML = '<button type="button" class="btn btn-sm" data-back="1">&larr; New search</button><div class="cu-empty">' + esc(e.message) + '</div>';
    });
  }
  function chip(text, tone, title) { return '<span class="cs-chip' + (tone ? ' t-' + tone : '') + '"' + (title ? ' title="' + esc(title) + '"' : '') + '>' + text + '</span>'; }
  function chips(c) {
    var out = [];
    if (c.provisioning) out.push(chip('Paying', 'ok', 'Has provisioning orders'));
    else if (c.trial) out.push(chip('Trial', 'warn', 'Only trial SOS packages so far'));
    var plan = (c.provisioning_requests || [])[0];
    if (plan && plan.product) out.push(chip(esc(plan.product) + (plan.quantity ? ' &times; ' + int(plan.quantity) : '') + (plan.more ? ' +' + plan.more : ''), '', 'The latest order'));
    if (c.ends) {
      var d = Math.round((new Date(c.ends + 'T00:00:00') - Date.now()) / 86400000);
      out.push(d < 0 ? chip('Ended ' + esc(day(new Date(c.ends + 'T00:00:00').getTime())), 'bad', 'The latest provision end date')
        : d <= 60 ? chip('Renews in ' + plural(d, 'day'), 'warn', 'Provision end date ' + c.ends)
        : chip('Until ' + esc(day(new Date(c.ends + 'T00:00:00').getTime())), '', 'Provision end date'));
    }
    if (c.open) out.push(chip(plural(c.open, 'open ticket'), 'info'));
    if (c.flagged) out.push(chip(plural(c.flagged, 'SOS package') + ' to check', 'bad', 'Needs review or high risk'));
    var s = (c.sso_requests || [])[0];
    if (s) out.push(chip('SSO ' + esc((SSO[s.status] || s.status || '').toLowerCase()), s.status === 'verified' || s.status === 'enabled' ? 'ok' : 'warn', s.domain || ''));
    return out.join('');
  }
  function render(c) {
    var title = c.orgs.length ? c.orgs[0] : c.label;
    var links = [];
    if (ZD) links.push('<a class="btn btn-sm" href="' + esc(ZD) + '/agent/search/1?type=ticket&q=' + encodeURIComponent(c.kind === 'email' ? 'requester:' + c.label : c.domain) +
      '" target="_blank" rel="noopener">Tickets in Zendesk ' + OUT + '</a>');
    var NAMES = { 'team info': 'View team on ACP', 'manage': 'Manage SOS PKG on ACP', 'download package': 'Download package' };
    (c.links || []).slice(0, 2).forEach(function (l) {
      links.push('<a class="btn btn-sm" href="' + esc(l.url) + '" target="_blank" rel="noopener">' + esc(NAMES[String(l.label).toLowerCase()] || l.label) + ' ' + OUT + '</a>');
    });
    var sub = [c.label !== title ? esc(c.label) : '', c.countries.length ? esc(c.countries.join(', ')) : '',
      c.first_ms ? 'first seen ' + esc(day(c.first_ms)) : '', c.last_ms ? 'last contact ' + esc(ago(c.last_ms)) : ''].filter(Boolean).join(' · ');
    var h = '<button type="button" class="btn btn-sm cs-back" data-back="1">&larr; New search</button>' +
      '<section class="cs-head"><div class="cs-av">' + esc(initials(title)) + '</div><div class="cs-hl"><h2 class="cs-title">' + esc(title) + '</h2>' +
        '<div class="muted cs-sub">' + sub + '</div></div><div class="cs-links">' + links.join('') + '</div></section>' +
      (c.generic ? '<div class="cu-generic">Free e-mail provider: only this one address is shown, not everyone at ' + esc(c.domain) + '.</div>' : '') +
      '<div class="cs-chips">' + chips(c) + '</div>';
    // Spark's summary (written in the background: loadSummary fills it in)
    h += '<section class="card cu-ai" id="cuAi"><div class="cu-ai-h"><span class="cu-ai-t">' + SPARK + 'Summary</span><span class="snav-ai">Spark</span>' +
      '<span class="cu-ai-when" id="cuAiWhen"></span><button type="button" class="btn btn-sm" id="cuAiAgain" title="Write it again">Refresh</button></div>' +
      '<div class="cu-ai-body" id="cuAiBody"><span class="cu-ai-wait">Spark is reading this customer’s records…</span></div></section>';
    // open tickets first
    var ot = c.open_tickets || [];
    h += '<section class="card cs-card"><div class="card-head"><h2 class="card-title">Needs attention</h2><span class="count">' +
      (ot.length ? plural(ot.length, 'open ticket') : 'nothing open') + '</span></div><div class="cs-pad">' +
      (ot.length ? ot.map(function (t) {
        return row('tk', '#' + t.ticket_id + ' ' + (t.subject || '(no subject)'), 'updated ' + ago(t.updated_ms || t.created_ms), '', 'data-tid="' + t.ticket_id + '"', t.status);
      }).join('') : '<div class="cs-none">No open tickets from ' + (c.kind === 'email' ? 'this address' : 'this customer') + '.</div>') + '</div></section>';
    // everything, newest first
    h += '<section class="card cs-card"><div class="card-head"><h2 class="card-title">Timeline</h2><div class="chips cs-filters" id="tlf">' +
      [['all', 'All'], ['tk', 'Tickets'], ['po', 'Orders'], ['sos', 'SOS'], ['sso', 'SSO']].map(function (f) {
        return '<button type="button" class="chip' + (f[0] === 'all' ? ' active' : '') + '" data-f="' + f[0] + '">' + f[1] + '</button>';
      }).join('') + '</div></div><div class="cs-pad" id="tl"></div>' +
      (c.tickets > (c.recent_tickets || []).length ? '<div class="cu-more">Tickets: the latest ' + (c.recent_tickets || []).length + ' of ' + int(c.tickets) + ' (2026).</div>' : '') + '</section>';
    // who writes in, what about
    var people = (c.people || []).slice(0, 8), topics = c.topics || [];
    if (people.length || topics.length) {
      h += '<section class="card cs-card"><div class="cs-pad cs-more">' +
        (people.length ? '<div><div class="cu-h">People</div><div class="cs-people">' + people.map(function (p, i) {
          return '<a href="#email:' + esc(p.email) + '" title="Only this address"><span class="cs-pav">' + esc(initials(p.email)) + '</span>' + esc(p.email) + ' <i>' + p.n + '</i>' + (i === 0 && people.length > 1 ? ' <span class="cs-most">most active</span>' : '') + '</a>';
        }).join('') + '</div></div>' : '') +
        (topics.length ? '<div><div class="cu-h">Topics</div><div class="cu-tags">' + topics.map(function (t) { return '<span>' + esc(t) + '</span>'; }).join('') + '</div></div>' : '') +
        '</div></section>';
    }
    return h;
  }
  function row(kind, title, sub, when, attrs, st) {
    return '<div class="cs-row' + (attrs ? ' cs-click' : '') + '" ' + (attrs || '') + ' tabindex="' + (attrs ? 0 : -1) + '"><span class="cs-ic k-' + kind + '">' + ico(kind) + '</span>' +
      '<span class="cs-rt"><span class="cs-rtt">' + esc(title) + '</span><span class="muted cs-rts">' + esc(sub) + '</span></span>' +
      (st ? '<span class="tst tst-' + esc(st) + '">' + esc(TST[st] || st) + '</span>' : '') +
      (when ? '<span class="muted cs-when">' + esc(when) + '</span>' : '') + '</div>';
  }
  function drawTimeline() {
    var c = CUR, items = [];
    (c.recent_tickets || []).forEach(function (t) {
      items.push({ k: 'tk', ms: t.created_ms, html: row('tk', '#' + t.ticket_id + ' ' + (t.subject || '(no subject)'), c.kind === 'domain' && t.requester_email ? t.requester_email : '', short(t.created_ms), 'data-tid="' + t.ticket_id + '"', t.status) });
    });
    (c.provisioning_requests || []).forEach(function (p) {
      items.push({ k: 'po', ms: p.created_ms, html: row('po', 'Order: ' + (p.product || p.subject || 'provisioning request') + (p.quantity ? ' × ' + p.quantity : '') + (p.more ? ' +' + p.more + ' more' : ''),
        [p.order_type, p.expected ? 'provision ' + p.expected : '', p.ends ? 'until ' + p.ends : ''].filter(Boolean).join(' · '), short(p.created_ms), 'data-tid="' + p.ticket_id + '"', p.status) });
    });
    (c.packages || []).forEach(function (p) {
      items.push({ k: 'sos', ms: p.requested_ms, html: row('sos', 'Custom SOS package' + (p.name ? ' “' + p.name + '”' : ''),
        [VERDICT[p.verdict] || 'not reviewed', p.type, c.kind === 'domain' ? p.creator : ''].filter(Boolean).join(' · '), short(p.requested_ms), 'data-href="/scans#' + p.id + '"') });
    });
    (c.sso_requests || []).forEach(function (s) {
      items.push({ k: 'sso', ms: s.requested_ms, html: row('sso', 'SSO for ' + (s.domain || '(no domain yet)'), SSO[s.status] || s.status || '', short(s.requested_ms), 'data-href="/sso#' + s.id + '"') });
    });
    items.sort(function (a, b) { return (b.ms || 0) - (a.ms || 0); });
    var shown = items.filter(function (x) { return FILTER === 'all' || x.k === FILTER; });
    $('tl').innerHTML = shown.length ? shown.slice(0, ALL ? shown.length : FIRST).map(function (x) { return x.html; }).join('') +
      (!ALL && shown.length > FIRST ? '<button type="button" class="btn btn-sm cs-all" data-all="1">Show all ' + int(shown.length) + '</button>' : '')
      : '<div class="cs-none">Nothing of this kind yet.</div>';
  }

  // ---- the ticket preview: the whole conversation, read from Zendesk now --------------------------
  var pSeq = 0;
  function preview(tid) {
    var my = ++pSeq;
    $('pnWrap').hidden = false; document.body.classList.add('pn-lock');
    $('detail').innerHTML = '<div class="pn-loading">Loading ticket #' + tid + '…</div>';
    $('panel').focus();
    api('/api/customers/ticket?key=' + encodeURIComponent(CUR.key) + '&id=' + tid).then(function (d) {
      if (my !== pSeq) return;
      var LBL = { customer: 'Customer', agent: 'Agent', note: 'Internal note' }, c = d.conversation || [];
      $('detail').innerHTML = '<div class="at-d"><div class="at-dh"><div class="at-dt">' + (ZD ? '<a href="' + esc(ZD) + '/agent/tickets/' + tid + '" target="_blank" rel="noopener">#' + tid + '</a>' : '#' + tid) +
        ' · ' + esc(d.ticket.subject || '(no subject)') + '</div><div class="muted">' + (d.ticket.status ? '<span class="tst tst-' + esc(d.ticket.status) + '">' + esc(TST[d.ticket.status] || d.ticket.status) + '</span> · ' : '') +
        plural(c.length, 'message') + ', oldest first</div></div>' +
        '<div class="ad-convo cs-convo">' + c.map(function (m) {
          return '<div class="ad-msg ad-' + esc(m.kind) + '"><div class="ad-mh"><b>' + esc(LBL[m.kind] || m.kind) + '</b>' + (m.who ? ' · ' + esc(m.who) : '') +
            (m.ms ? ' <span class="muted">· ' + esc(day(m.ms)) + '</span>' : '') + '</div><div class="ad-mb">' + esc(m.text || '') + '</div></div>';
        }).join('') + '</div>' +
        (ZD ? '<div class="frow"><a class="btn btn-sm" href="' + esc(ZD) + '/agent/tickets/' + tid + '" target="_blank" rel="noopener">Open in Zendesk ' + OUT + '</a></div>' : '') + '</div>';
      var box = $('detail').querySelector('.cs-convo'); if (box) box.scrollTop = box.scrollHeight;
    }).catch(function (e) { if (my === pSeq) $('detail').innerHTML = '<div class="cu-empty">' + esc(e.message) + '</div>'; });
  }
  function closePreview() { pSeq++; $('pnWrap').hidden = true; document.body.classList.remove('pn-lock'); }
  $('pnClose').addEventListener('click', closePreview);
  $('pnWrap').addEventListener('mousedown', function (ev) { if (ev.target === this) closePreview(); });
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && !$('pnWrap').hidden) closePreview();
    if (ev.key === 'Enter' && ev.target.classList && ev.target.classList.contains('cs-click')) ev.target.click();
  });

  // ---- clicks ---------------------------------------------------------------------------------------
  document.addEventListener('click', function (ev) {
    if (ev.target.closest('[data-back]')) { location.hash = ''; if (!location.hash) showSearch(); return; }
    var f = ev.target.closest('#tlf [data-f]');
    if (f) {
      FILTER = f.getAttribute('data-f'); ALL = false;
      [].forEach.call($('tlf').children, function (b) { b.classList.toggle('active', b === f); });
      drawTimeline(); return;
    }
    if (ev.target.closest('[data-all]')) { ALL = true; drawTimeline(); return; }
    if (ev.target.closest('a')) return;
    var r = ev.target.closest('.cs-click');
    if (r && CUR) {
      if (r.getAttribute('data-tid')) preview(+r.getAttribute('data-tid'));
      else if (r.getAttribute('data-href')) location.href = r.getAttribute('data-href');
      return;
    }
    if (ev.target.closest('#cuAiAgain') && sumKey) {
      $('cuAiBody').innerHTML = '<span class="cu-ai-wait">Spark is writing it again…</span>';
      $('cuAiWhen').textContent = '';
      loadSummary(sumKey, true);
    }
  });

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
})();
