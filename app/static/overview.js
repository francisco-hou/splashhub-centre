// SplashHub Centre -- Admin > Dashboard: the whole support picture on one page
// (overview.py). Team-wide numbers only. Zendesk's live counts are read in the
// background at most every 5 minutes; while they refresh the page shows the
// last ones and asks again a few seconds later.
(function () {
  'use strict';

  var ZD = '';
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function int(n) { return (n || 0).toLocaleString('en-US'); }
  function usd(n) { return '$' + (n || 0).toFixed(2); }
  function ago(ms) {
    if (!ms) return '';
    var m = (Date.now() - ms) / 60000;
    return m < 1 ? 'just now' : m < 60 ? Math.round(m) + ' min ago' : m < 1440 ? Math.round(m / 60) + ' h ago' : Math.round(m / 1440) + ' d ago';
  }
  function trend(now, before, goodWhenDown) {
    if (!before) return now ? '<span class="muted">new this week</span>' : '<span class="muted">&nbsp;</span>';
    var pct = Math.round(100 * (now - before) / before);
    if (!pct) return '<span class="muted">same as last week</span>';
    var up = pct > 0, bad = goodWhenDown ? up : false;
    return '<span class="' + (bad ? 'd-up' : 'ov-neutral') + '">' + (up ? '▲ ' : '▼ ') + Math.abs(pct) + '% vs last week</span>';
  }
  function api(path) {
    return fetch(path, { credentials: 'same-origin' }).then(function (r) {
      if (r.status === 401) { location.href = '/logs?next=/overview'; throw new Error('login'); }
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }

  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (x) { ZD = x.zendesk_url || ''; }).catch(function () {});
  $('page').hidden = false;

  var again = null, tries = 0, AGENT = '';
  function load(fresh) {
    clearTimeout(again);
    var q = [fresh ? 'fresh=1' : '', AGENT ? 'agent=' + encodeURIComponent(AGENT) : ''].filter(Boolean).join('&');
    api('/api/overview' + (q ? '?' + q : '')).then(function (d) {
      $('ov').innerHTML = draw(d);
      var l = d.live || {};
      $('stamp').textContent = l.updating ? 'Reading Zendesk…' : (l.ms ? 'Zendesk ' + ago(l.ms) : '');
      if (l.updating && tries++ < 20) again = setTimeout(function () { load(false); }, 3000);
      else tries = 0;
    }).catch(function (e) { if (e.message !== 'login') $('ov').innerHTML = '<div class="cu-empty">Could not load: ' + esc(e.message) + '</div>'; });
  }
  load(false);
  $('refresh').addEventListener('click', function () { tries = 0; load(true); });
  $('ov').addEventListener('change', function (ev) {
    if (ev.target.id === 'ovAgent') { AGENT = ev.target.value; load(false); }
  });
  $('ov').addEventListener('click', function (ev) {
    var p = ev.target.closest('[data-agent]'); if (!p) return;
    ev.preventDefault(); AGENT = p.getAttribute('data-agent'); load(false);
  });
  setInterval(function () { if (document.visibilityState === 'visible') load(false); }, 5 * 60000);

  function tile(label, value, sub, cls, href) {
    var inner = '<div class="stat-label">' + label + '</div><div class="stat-value ' + (cls || '') + '">' + value + '</div><div class="stat-sub">' + (sub || '&nbsp;') + '</div>';
    return href ? '<a class="stat ov-tile" href="' + esc(href) + '">' + inner + '</a>' : '<div class="stat">' + inner + '</div>';
  }
  function card(title, sub, body, cls) {
    return '<section class="card ov-card ' + (cls || '') + '"><div class="card-head"><h2 class="card-title">' + title + '</h2>' +
      (sub ? '<span class="count">' + sub + '</span>' : '') + '</div><div class="ov-pad">' + body + '</div></section>';
  }
  function zdSearch(q) { return ZD ? ZD + '/agent/search/1?type=ticket&q=' + encodeURIComponent(q) : null; }

  function draw(d) {
    var L = d.live || {}, z = L.data;
    var h = '';
    // ---- Zendesk now
    if (z) {
      h += '<div class="ov-section">Zendesk now</div><div class="stats ov-6">' +
        tile('New', int(z.new), 'not picked up yet', z.new ? 'cu-warn' : '', zdSearch('status:new')) +
        tile('Open', int(z.open), 'being worked on', '', zdSearch('status:open')) +
        tile('RR queue', int(z.rr), 'open round-robin tickets', '', null) +
        tile('Pending', int(z.pending), 'waiting on the customer', '', zdSearch('status:pending')) +
        tile('On hold', int(z.hold), 'parked', '', zdSearch('status:hold')) +
        tile('Today', int(z.created_today) + ' / ' + int(z.solved_today), 'created / solved', '', null) + '</div>';
    } else {
      h += '<div class="note">' + (L.error ? 'Zendesk counts: ' + esc(L.error) : 'Reading Zendesk… the live numbers appear in a few seconds.') + '</div>';
    }
    // ---- Tickets + attention
    var t = d.tickets, max = Math.max.apply(null, [1].concat(t.days.map(function (x) { return x.n; })));
    var bars = '<div class="ov-bars">' + t.days.map(function (x, i) {
      var dt = new Date(x.day_ms + 12 * 3600000);
      return '<div class="ov-bar' + (i >= 7 ? ' this' : '') + '" title="' + esc(WD[dt.getUTCDay()] + ' ' + MON[dt.getUTCMonth()] + ' ' + dt.getUTCDate()) + ': ' + x.n + '">' +
        '<i style="height:' + Math.max(3, Math.round(100 * x.n / max)) + '%"></i><span>' + (i % 2 ? '' : dt.getUTCDate()) + '</span></div>';
    }).join('') + '</div>';
    var tix = '<div class="ov-big"><b>' + int(t.week) + '</b> tickets in the last 7 days ' + trend(t.week, t.prev_week, true) + '</div>' + bars +
      (t.tags.length ? '<div class="cu-h">Top tags this week</div><div class="cu-tags">' + t.tags.map(function (g) { return '<span>' + esc(g.tag) + ' <i>' + g.n + '</i></span>'; }).join('') + '</div>' : '') +
      (t.rising.length ? '<div class="cu-h">Rising in the last 30 days</div><div class="cu-tags ov-rise">' + t.rising.map(function (w) { return '<span>' + esc(w.word) + ' <i>×' + w.times_more_common + '</i></span>'; }).join('') + '</div>' : '') +
      (!t.total_2026 ? '<div class="cu-empty">Zendesk Tickets aren&rsquo;t downloaded yet (Settings &rsaquo; Database).</div>' : '');
    var att = d.attention.length ? d.attention.map(function (a) {
      return '<a class="cu-row" href="' + esc(a.link) + '"><span class="cu-row-t"><b><span class="ov-kind ' + a.tone + '">' + esc(a.kind) + '</span> ' + esc(a.what) + '</b>' +
        '<span class="muted cu-row-s">#' + a.ticket + (a.note ? ' &middot; ' + esc(a.note) : '') + (a.ms ? ' &middot; ' + esc(ago(a.ms)) : '') + '</span></span></a>';
    }).join('') : '<div class="cu-empty">Nothing waiting. 🎉</div>';
    h += '<div class="ov-row2">' + card('Tickets', '2026 &middot; daily, last 14 days', tix) + card('Needs attention', 'oldest first', att, 'ov-att') + '</div>';
    // ---- SOS / SSO / PO / languages
    var s = d.sos, o = d.sso, p = d.po;
    var langs = z && z.languages && z.languages.length ? z.languages.map(function (l) {
      return '<div class="dhb"><span>' + esc(l.lang) + '</span><div class="dhbt"><i style="width:' + Math.round(100 * l.n / Math.max.apply(null, z.languages.map(function (x) { return x.n; }))) + '%"></i></div><span>' + int(l.n) + '</span></div>';
    }).join('') : '<div class="cu-empty">' + (z ? 'No routed-language tickets in the RR queue.' : 'Waiting for Zendesk…') + '</div>';
    h += '<div class="ov-row4">' +
      card('<a href="/scans">Custom SOS packages</a>', '', '<div class="ov-kv"><span>Last 24 h</span><b>' + int(s.day) + '</b><span>Last 7 days</span><b>' + int(s.week) + '</b>' +
        '<span>Needs review, open</span><b class="' + (s.needs_review ? 'ov-o' : '') + '">' + int(s.needs_review) + '</b><span>High risk, open</span><b class="' + (s.high_risk ? 'ov-r' : '') + '">' + int(s.high_risk) + '</b></div>') +
      card('<a href="/sso">SSO requests</a>', '', '<div class="ov-kv"><span>Waiting for DNS</span><b>' + int(o.waiting) + '</b><span>Needs details</span><b class="' + (o.needs_details ? 'ov-o' : '') + '">' + int(o.needs_details) + '</b>' +
        '<span>Verified, 7 days</span><b class="ov-g">' + int(o.verified_week) + '</b><span>All</span><b>' + int(o.total) + '</b></div>') +
      card('<a href="/po">PO requests</a>', '', '<div class="ov-kv"><span>Open</span><b>' + int(p.open) + '</b><span>Due in 7 days</span><b>' + int(p.due_week) + '</b>' +
        '<span>Overdue</span><b class="' + (p.overdue ? 'ov-r' : '') + '">' + int(p.overdue) + '</b><span>Last 30 days</span><b>' + int(p.last_30d) + '</b></div>') +
      card('RR queue by language', 'tagged', langs) + '</div>';
    // ---- AI usage, Knowledge Base, customers
    var ai = d.ai;
    var sel = '<select class="sel ov-agent" id="ovAgent" aria-label="Member"><option value="">Everyone</option>' + (ai.people || []).map(function (p) {
      return '<option value="' + esc(p.agent) + '"' + (p.agent === ai.agent ? ' selected' : '') + '>' + esc(p.agent) + '</option>';
    }).join('') + '</select>';
    var aiBody = sel + '<div class="ov-big"><b>' + int(ai.runs) + '</b> AI runs &middot; <b>' + usd(ai.cost) + '</b> in 7 days ' + trend(ai.runs, ai.prev_runs, false) + '</div>' +
      (ai.tools.length ? ai.tools.map(function (x) {
        return '<div class="dhb"><span>' + esc(x.tool) + '</span><div class="dhbt"><i style="width:' + Math.round(100 * x.runs / Math.max(1, ai.tools[0].runs)) + '%"></i></div><span>' + int(x.runs) + ' &middot; ' + usd(x.cost) + '</span></div>';
      }).join('') : '<div class="cu-empty">No runs this week.</div>') +
      (!ai.agent && ai.people && ai.people.length ? '<div class="cu-h">By member (30 days)</div>' + ai.people.slice(0, 8).map(function (p) {
        return '<a class="dhb ov-person" href="#" data-agent="' + esc(p.agent) + '"><span title="' + esc(p.agent) + '">' + esc(p.agent) + '</span><div class="dhbt"><i style="width:' +
          Math.round(100 * p.runs / Math.max(1, ai.people[0].runs)) + '%"></i></div><span>' + int(p.runs) + ' &middot; ' + usd(p.cost) + '</span></a>';
      }).join('') : '') +
      '<div class="ov-more"><a href="/logs' + (ai.agent ? '?agent=' + encodeURIComponent(ai.agent) : '') + '">Open Logs' + (ai.agent ? ' for ' + esc(ai.agent) : '') + '</a></div>';
    var kb = d.kb;
    var kbBody = '<div class="ov-kv"><span>Articles</span><b>' + int(kb.articles) + '</b><span>Outdated translations</span><b class="' + (kb.outdated ? 'ov-o' : '') + '">' + int(kb.outdated) + '</b></div>' +
      (kb.least_helpful.length ? '<div class="cu-h">Least helpful (10+ votes)</div>' + kb.least_helpful.map(function (a) {
        return '<a class="cu-row" href="/kb#' + a.id + '"><span class="cu-row-t"><b>' + esc(a.title) + '</b></span><span class="' + (a.helpful < 50 ? 'ov-r' : '') + '"><b>' + a.helpful + '%</b> <span class="muted">' + a.votes + ' votes</span></span></a>';
      }).join('') : (kb.articles ? '' : '<div class="cu-empty">Not downloaded yet (Settings &rsaquo; Database).</div>'));
    var cuBody = d.customers.length ? d.customers.map(function (c) {
      return '<a class="cu-row" href="/customers#' + esc(c.key) + '"><span class="cu-row-t"><b>' + esc(c.label) + '</b><span class="muted cu-row-s">' +
        [c.tickets ? c.tickets + ' tickets' + (c.open ? ' (' + c.open + ' open)' : '') : '', c.sos ? c.sos + ' SOS' : '', c.sso ? c.sso + ' SSO' : ''].filter(Boolean).join(' &middot; ') + '</span></span></a>';
    }).join('') : '<div class="cu-empty">Nothing yet.</div>';
    h += '<div class="ov-row3">' + card('AI usage', 'vs last week', aiBody) + card('<a href="/kb">Knowledge Base</a>', '', kbBody) +
      card('<a href="/customers">Most active customers</a>', '30 days', cuBody) + '</div>';
    return h;
  }
})();
