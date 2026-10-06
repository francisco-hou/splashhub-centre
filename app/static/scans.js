// SplashHub Centre -- SOS Scans page.
//
// Every Custom SOS package request a Zendesk trigger sends here (or that an
// admin starts with "Scan a ticket") is listed here, brand-reviewed by the
// server (sosscan.py) when the AI review applies. A row opens the request in
// a pop-up, where its AI review can also be run by hand. While any scan
// is queued or running the list refreshes itself every few seconds.
(function () {
  'use strict';

  var S = { verdict: '', q: '', page: 0, open: null };
  var ZD = '';
  // The same three words as the internal note: Verified / Needs review / High risk.
  var LABEL = { suspicious: 'High risk', needs_review: 'Needs review', normal: 'Verified',
                queued: 'Queued', running: 'Scanning…', waiting: 'Waiting', held: 'AI off', past: 'Past request', skipped: 'Skipped', error: 'Error', not_applicable: 'Not applicable' };
  var REF = { none: 'No Splashtop reference', powered_by_attribution: '“Powered by Splashtop” credit',
              unmodified_default: 'Splashtop default UI visible', other_reference: 'Misleading “by Splashtop” text' };
  var CHIPS = [['', 'All'], ['flagged', 'Flagged'], ['suspicious', 'High risk'], ['needs_review', 'Needs review'],
               ['normal', 'Verified'], ['held', 'Not reviewed'], ['waiting', 'Waiting'], ['skipped', 'Skipped'], ['error', 'Errors']];

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function formatUsd(n) { if (!n) return '$0.00'; return n < 0.01 ? '<$0.01' : '$' + n.toFixed(n < 1 ? 3 : 2); }
  function whenTxt(ms) {
    if (!ms) return '—';
    var d = new Date(ms);
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  // An imported past request is 'held' too, but reads as what it is.
  function state(r) { return r.verdict || (r.status === 'held' && r.source === 'import' ? 'past' : r.status); }
  // The Zendesk ticket's own status, in Zendesk's colours.
  var TSTATUS = { new: 'New', open: 'Open', pending: 'Pending', hold: 'On-hold', solved: 'Solved', closed: 'Closed' };
  function tstatus(st) {
    return st ? '<span class="tst tst-' + esc(st) + '">' + esc(TSTATUS[st] || st) + '</span>' : '<span class="muted">—</span>';
  }
  function pill(st) { return '<span class="vpill v-' + esc(st) + '">' + esc(LABEL[st] || st) + '</span>'; }
  function api(path, opts) {
    return fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {})).then(function (r) {
      if (r.status === 401) { location.href = '/logs?next=/scans'; throw new Error('login'); }
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }

  // ---- boot: same session as the Logs page (sign in there) -------------------
  fetch('/api/session', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (s) {
    $('signOut').hidden = !(s.required && s.authed);
    $('page').hidden = false;
    var m = /^#(\d+)$/.exec(location.hash);       // /scans#123 opens that request (on View Scans)
    if (m) S.open = +m[1];
    setup();
    var pref = 'dash';
    try { pref = localStorage.getItem('sosView') || 'dash'; } catch (e) { /* fine */ }
    // the dashboard is the main view; #list, or a link to one request, opens the list
    setView(m || location.hash === '#list' ? 'list' : pref, true);
  });
  $('signOut').addEventListener('click', function () {
    fetch('/logout', { method: 'POST', credentials: 'same-origin' }).then(function () { location.reload(); });
  });

  // The Zendesk address for the ticket links. (The AI review switch, Scan a
  // ticket and the import are on the Settings page.)
  function setup() {
    api('/api/scan-setup').then(function (s) { ZD = s.zendesk_url; }).catch(function () {});
  }


  // ---- views: Dashboard (the main one) and View Scans (the list) -------------------------
  var VIEW = 'dash';
  function setView(v, keepHash) {
    VIEW = v === 'list' ? 'list' : 'dash';
    $('dashView').hidden = VIEW !== 'dash';
    $('listView').hidden = VIEW !== 'list';
    $('tabDash').setAttribute('aria-selected', VIEW === 'dash');
    $('tabList').setAttribute('aria-selected', VIEW === 'list');
    if (!keepHash && !S.open) history.replaceState(null, '', VIEW === 'list' ? '#list' : location.pathname);
    try { localStorage.setItem('sosView', VIEW); } catch (e) { /* private window: fine */ }
    if (VIEW === 'dash') loadDash(); else load();
  }
  $('tabDash').addEventListener('click', function () { setView('dash'); });
  $('tabList').addEventListener('click', function () { setView('list'); });
  function showList(verdict) { S.verdict = verdict || ''; S.page = 0; lastSig = ''; setView('list'); }

  // ---- the dashboard ------------------------------------------------------------------------
  var DCOL = { verified: '#7cc79a', needs_review: '#f2a65a', high_risk: '#e05a4f', not_reviewed: '#cfd8e2' };
  var dseqD = 0, dSparkT = null, dSparkTries = 0;
  function loadDash(fresh) {
    var my = ++dseqD;
    spinOn();
    api('/api/scans/dashboard?tz=' + new Date().getTimezoneOffset() + (fresh ? '&fresh=1' : '')).then(function (d) {
      spinOff();
      if (my !== dseqD) return;
      drawKpis(d.kpis); drawChart(d.days); drawSpike(d.spikes); drawAttention(d.attention); drawWho(d.who); drawMix(d.mix, d.spend, d.lookalikes);
      // Spark answers in the background: ask again shortly for its part
      var waiting = [d.spikes.spark, d.lookalikes].some(function (x) { return x && (x.pending || x.updating); });
      clearTimeout(dSparkT);
      if (waiting && dSparkTries++ < 12) dSparkT = setTimeout(function () { if (VIEW === 'dash') loadDash(); }, 5000);
      if (!waiting) dSparkTries = 0;
      var t = new Date();
      $('stamp').textContent = 'Updated ' + String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0');
    }).catch(function (e) { spinOff(); if (e.message !== 'login') $('stamp').textContent = 'Could not load: ' + e.message; });
  }
  function ago(ms) {
    if (!ms) return '';
    var h = (Date.now() - ms) / 3600000;
    return h < 24 ? Math.max(1, Math.round(h)) + ' h' : Math.round(h / 24) + ' d';
  }
  function trend(up, txt) { return '<span class="' + (up ? 'd-up' : 'd-dn') + '">' + (up ? '▲ ' : '▼ ') + esc(txt) + '</span>'; }

  function drawKpis(k) {
    var card = function (label, value, sub, cls, go) {
      return '<button type="button" class="card dk" ' + (go != null ? 'data-go="' + go + '"' : '') + '>' +
        '<span class="dk-l">' + label + '</span><span class="dk-v ' + (cls || '') + '">' + value + '</span><span class="dk-s">' + sub + '</span></button>';
    };
    var day = k.day, week = k.week, g = k.generic;
    $('dKpis').innerHTML =
      card('Last 24 h', day.n, day.ratio != null ? trend(day.ratio >= 1, '×' + day.ratio) + ' vs usual ~' + Math.round(day.usual) : 'no history yet', '', '') +
      card('Last 7 days', week.n, week.pct != null ? trend(week.pct >= 0, Math.abs(week.pct) + '%') + ' vs ~' + Math.round(week.usual) : 'no history yet', '', '') +
      card('Needs review · open', k.needs_review_open.n, k.needs_review_open.n ? 'oldest waiting ' + ago(k.needs_review_open.oldest_ms) : 'nothing waiting', 'dk-o', 'needs_review') +
      card('High risk · open', k.high_risk_open.n, k.high_risk_open.first ? '#' + esc(k.high_risk_open.first) : 'none open', 'dk-r', 'suspicious') +
      card('Generic emails · 7 d', g.pct != null ? g.pct + '%' : '—', g.before != null && g.pct != null ? trend(g.pct >= g.before, 'from ' + g.before + '%') + ' the 30 days before' : '', '', '');
  }
  $('dKpis').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-go]'); if (b) showList(b.getAttribute('data-go'));
  });

  // Stacked bars by verdict, and a dashed line for the usual on that weekday.
  function drawChart(days) {
    var W = 1000, H = 300, padL = 34, padB = 26, padT = 12, n = days.length, bw = (W - padL) / n;
    var max = Math.max(4, Math.max.apply(null, days.map(function (d) { return Math.max(d.total, d.usual); })));
    var y = function (v) { return H - padB - (v / max) * (H - padB - padT); };
    var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="dchart" role="img" aria-label="Requests per day for the last ' + n + ' days">';
    [0, 0.5, 1].forEach(function (f) {
      var v = Math.round(max * f), yy = y(v);
      svg += '<line x1="' + padL + '" x2="' + W + '" y1="' + yy + '" y2="' + yy + '" class="dgrid"/><text x="' + (padL - 6) + '" y="' + (yy + 4) + '" class="dax" text-anchor="end">' + v + '</text>';
    });
    days.forEach(function (d, i) {
      var x = padL + i * bw + bw * 0.18, w = bw * 0.64, base = H - padB;
      var date = new Date(d.day_ms), lab = (date.getMonth() + 1) + '/' + date.getDate();
      svg += '<g><title>' + lab + ': ' + d.total + ' requests (' + d.verified + ' verified, ' + d.needs_review + ' needs review, ' +
        d.high_risk + ' high risk, ' + d.not_reviewed + ' not reviewed) · usual ~' + d.usual + '</title>';
      ['verified', 'needs_review', 'high_risk', 'not_reviewed'].forEach(function (c) {
        if (!d[c]) return;
        var h = (d[c] / max) * (H - padB - padT);
        base -= h;
        svg += '<rect x="' + x + '" y="' + base + '" width="' + w + '" height="' + Math.max(h - 1, 1) + '" rx="2" fill="' + DCOL[c] + '"/>';
      });
      svg += '</g>';
      if (i % 3 === (n - 1) % 3) svg += '<text x="' + (x + w / 2) + '" y="' + (H - 8) + '" class="dax" text-anchor="middle">' + lab + '</text>';
    });
    svg += '<polyline class="dusual" points="' + days.map(function (d, i) { return (padL + i * bw + bw / 2) + ',' + y(d.usual); }).join(' ') + '"/>';
    $('dChart').innerHTML = svg + '</svg>';
  }

  function drawSpike(sp) {
    var any = sp.day.alert || sp.week.alert;
    var row = function (label, s) {
      var pct = s.usual ? Math.min(100, Math.round(100 * s.n / Math.max(s.n, s.usual * 2))) : (s.n ? 100 : 0);
      return '<span>' + label + '</span><div class="dmeter' + (s.alert ? ' hot' : '') + '"><i style="width:' + pct + '%"></i></div>' +
        '<b class="' + (s.alert ? 'd-red' : '') + '">' + s.n + ' vs ~' + Math.round(s.usual) + '</b>';
    };
    var h = '<div class="dct ' + (any ? 'd-alert' : '') + '">' + (any ? '⚡ Spike alert' : 'Spike alert') + '<span>' +
      (any ? 'more requests than usual' : 'nothing unusual') + '</span></div>' +
      '<div class="dcmp">' + row('Last 24 h', sp.day) + row('Last 7 days', sp.week) + '</div>';
    var s = sp.spark;
    h += '<div class="dspark"><div class="dspark-h">Spark · what stands out</div>';
    if (!any) h += '<div class="dmuted">When there is a spike, Spark says what the requests have in common.</div>';
    else if (!s || s.off) h += '<div class="dmuted">Spark isn’t connected yet. Once it is, it explains spikes here.</div>';
    else if (s.pending) h += '<div class="dmuted dthink">Spark is looking at these requests…</div>';
    else if (s.error) h += '<div class="dmuted">Spark couldn’t answer: ' + esc(s.error) + '</div>';
    else h += '<ul>' + s.points.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join('') + '</ul>';
    $('dSpike').classList.toggle('dcard-alert', any);
    $('dSpike').innerHTML = h + '</div>';
  }

  function drawAttention(list) {
    var h = '<div class="dct">Needs attention <span>flagged or not reviewed · ticket open</span></div>';
    if (!list.length) h += '<div class="dmuted">Nothing waiting. 🎉</div>';
    list.forEach(function (a) {
      h += '<button type="button" class="drow" data-open="' + a.id + '"><span class="drow-t"><b>#' + a.ticket_id + '</b> ' + esc(a.why) +
        ' <span class="dmuted">· ' + ago(a.requested_ms) + '</span></span>' + pill(state(a)) + '</button>';
    });
    $('dAttention').innerHTML = h;
  }
  $('dAttention').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-open]'); if (b) openPanel(+b.getAttribute('data-open'));
  });

  function bars(items, max) {
    return items.map(function (it) {
      return '<div class="dhb"><span title="' + esc(it.label) + '">' + esc(it.label) + '</span><div class="dhbt"><i class="' + (it.warn ? 'o' : '') +
        '" style="width:' + Math.round(100 * it.n / Math.max(max, 1)) + '%"></i></div><span>' + esc(it.value != null ? it.value : it.n) + '</span></div>';
    }).join('');
  }
  function drawWho(w) {
    var max = Math.max.apply(null, [1].concat(w.domains.map(function (d) { return d.n; })));
    $('dWho').innerHTML = '<div class="dct">Who’s asking <span>7 days · creator domains</span></div>' +
      (w.domains.length ? bars(w.domains.map(function (d) { return { label: d.domain, n: d.n, warn: d.generic }; }), max) : '<div class="dmuted">No requests in the last 7 days.</div>') +
      '<div class="dtags"><span class="dtag dtag-n">' + w.new + ' new ' + (w.new === 1 ? 'team' : 'teams') + '</span><span class="dtag">' + w.returning + ' returning</span>' +
      (w.flagged_before ? '<span class="dtag dtag-r">' + w.flagged_before + ' flagged before</span>' : '') + '</div>';
  }
  function drawMix(mix, spend, look) {
    var total = mix.reduce(function (t, m) { return t + m.n; }, 0);
    var h = '<div class="dct">Package mix <span>7 days</span></div>' +
      (total ? bars(mix.map(function (m) { return { label: m.type.charAt(0).toUpperCase() + m.type.slice(1), n: m.n, warn: m.type === 'trial', value: Math.round(100 * m.n / total) + '%' }; }), total)
             : '<div class="dmuted">No requests in the last 7 days.</div>');
    h += '<div class="dct dct-sub">Lookalike names <span>Spark</span></div>';
    if (!look || look.off) h += '<div class="dmuted">Spark isn’t connected yet. Once it is, it lists package names that imitate a known brand.</div>';
    else if (look.pending) h += '<div class="dmuted dthink">Spark is reading this week’s package names…</div>';
    else if (look.error) h += '<div class="dmuted">Spark couldn’t answer: ' + esc(look.error) + '</div>';
    else if (!look.items.length) h += '<div class="dmuted">None this week.</div>';
    else h += look.items.map(function (x) { return '<div class="drow drow-s"><span>“' + esc(x.name) + '”</span><span class="dmuted">' + esc(x.brand) + '</span></div>'; }).join('');
    h += '<div class="dspend">AI spend 7 d: <b>' + formatUsd(spend.total) + '</b> · ' + spend.reviews + (spend.reviews === 1 ? ' review' : ' reviews') +
      (spend.reviews ? ' · avg ' + formatUsd(spend.avg) : '') + '</div>';
    $('dMix').innerHTML = h;
  }

  // ---- list ----------------------------------------------------------------------
  // The list updates in place: no dimming, and nothing is redrawn when nothing
  // changed -- an automatic check while a request is processing should be
  // invisible unless it has news.
  var seq = 0, poll = null, lastSig = '';
  // The refresh icon (top right) turns while the list is being checked: on a
  // click, on the automatic check every minute, and while a request is being
  // processed. At least a moment, so a quick check is still visible. The
  // list itself never dims or flashes -- it only changes when there is news.
  var spinAt = 0;
  function spinOn() { spinAt = Date.now(); $('refresh').classList.add('spin'); }
  function spinOff() {
    setTimeout(function () { $('refresh').classList.remove('spin'); }, Math.max(0, 700 - (Date.now() - spinAt)));
  }
  setInterval(function () {
    if (document.visibilityState === 'visible' && !$('page').hidden) { if (VIEW === 'dash') loadDash(); else load(); }
  }, 60000);

  function load(fresh) {
    var my = ++seq;
    spinOn();
    var p = 'page=' + S.page + (S.verdict ? '&verdict=' + encodeURIComponent(S.verdict) : '') + (S.q ? '&q=' + encodeURIComponent(S.q) : '');
    // fresh: the refresh button -- the server reads every ticket status on screen from Zendesk first
    api('/api/scans?' + p + (fresh ? '&fresh=1' : '')).then(function (res) {
      spinOff();
      if (my !== seq) return;
      var sig = JSON.stringify([p, res.total, res.counts, res.rows.map(function (r) { return [r.id, r.status, r.verdict, r.subject, r.creator_email, r.cost, r.ticket_status]; })]);
      if (sig !== lastSig) {
        lastSig = sig;
        drawChips(res.counts);
        drawRows(res);
      }
      var d = new Date();
      $('stamp').textContent = 'Updated ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
      clearTimeout(poll);
      if (res.rows.some(function (r) { return r.status === 'queued' || r.status === 'running'; })) poll = setTimeout(load, 4000);
    }).catch(function (e) { spinOff(); if (e.message !== 'login') $('stamp').textContent = 'Could not load: ' + e.message; });
  }

  function drawChips(counts) {
    var n = function (k) { return counts[k] || 0; };
    var total = Object.keys(counts).reduce(function (a, k) { return a + counts[k]; }, 0);
    var num = { '': total, flagged: n('suspicious') + n('needs_review'), suspicious: n('suspicious'),
                needs_review: n('needs_review'), normal: n('normal'), held: n('held'), waiting: n('waiting'), skipped: n('skipped'), error: n('error') };
    $('verdicts').innerHTML = CHIPS.map(function (c) {
      return '<button type="button" class="chip' + (S.verdict === c[0] ? ' active' : '') + (num[c[0]] ? '' : ' empty') +
        '" data-v="' + c[0] + '">' + esc(c[1]) + ' <span class="chip-n">' + num[c[0]] + '</span></button>';
    }).join('');
  }

  function drawRows(res) {
    $('count').textContent = res.total ? 'newest first · ' + res.total + (res.total === 1 ? ' scan' : ' scans') : '';
    if (!res.rows.length) {
      $('rows').innerHTML = '<tr class="empty-row"><td colspan="7">' +
        (S.verdict || S.q ? 'No scans match.' : 'No scans yet. They appear here when Zendesk sends a Custom SOS package request, or when you scan a ticket above.') +
        '</td></tr>';
    } else {
      $('rows').innerHTML = res.rows.map(function (r) {
        var who = r.creator_email ? esc(r.creator_email) : '<span class="muted">—</span>';
        return '<tr class="sc-row' + (S.open === r.id ? ' open' : '') + '" data-id="' + r.id + '" tabindex="0">' +
          '<td class="when">' + esc(whenTxt(r.requested_ms)) + '</td>' +
          '<td><a href="' + esc(ZD) + '/agent/tickets/' + r.ticket_id + '" target="_blank" rel="noopener" class="tlink">#' + r.ticket_id + '</a></td>' +
          '<td>' + tstatus(r.ticket_status) + '</td>' +
          '<td>' + pill(state(r)) + '</td>' +
          '<td class="topic" title="' + esc(r.subject || '') + '">' + esc(r.subject || (r.error && !r.subject ? r.error : '—')) + '</td>' +
          '<td>' + who + '</td>' +
          '<td class="n">' + esc(formatUsd(r.cost)) + '</td></tr>';
      }).join('');
    }
    if (S.open) openPanel(S.open); else markOpen();
    var pages = Math.ceil(res.total / res.per_page);
    $('pager').hidden = pages <= 1;
    $('prev').disabled = res.page <= 0;
    $('next').disabled = res.page >= pages - 1;
    $('pagerTxt').textContent = res.total ? (res.page * res.per_page + 1) + '–' + (res.page * res.per_page + res.rows.length) + ' of ' + res.total : '';
  }

  // ---- the pop-up: one request, in full ---------------------------------------------
  // Reading order: what was asked for (package, key facts, links), the AI
  // review -- or the button to run one -- then what end users will see, every
  // image, and the ticket's original text. Text from the ticket is untrusted:
  // everything goes through esc(), and links are only ever the http(s) URLs
  // the server parsed. Empty fields are left out rather than shown as dashes.
  var KNOWN = { 'package name': 1, 'caption': 1, 'type': 1, 'subscription': 1, 'technician count': 1,
                'date of creation': 1, 'creator': 1, 'instruction text': 1, 'disclaimer': 1, 'screenshot': 1 };
  var LINK_NAMES = { 'download package': 'Download package', 'manage': 'Manage SOS PKG on ACP', 'team info': 'View team on ACP' };
  var ICON_OUT = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>';
  var ICON_TR = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/></svg>';
  var COST_HINT = 'about $0.10–$0.30';
  var LB = { items: [], i: 0 };     // the lightbox's images
  var CUR = null;                   // the request shown in the panel

  function fieldMap(req) {
    var m = {};
    ((req && req.fields) || []).forEach(function (f) { m[f.label.toLowerCase()] = f.value; });
    return m;
  }
  // The Translate button's English, shown under the original when on.
  var FOREIGN = /[^\x00-\x7f]/;
  var SHOW_EN = true;
  function en(s, key, v) {
    var t = SHOW_EN && s.translation && s.translation[key];
    return t && t !== v ? '<span class="pn-en"><span class="pn-en-tag">EN</span>' + esc(t) + '</span>' : '';
  }
  function hasForeign(s, req) {
    return FOREIGN.test(s.subject || '') || (req.fields || []).some(function (x) { return x.value && FOREIGN.test(x.value); });
  }
  // Always there on an SOS request: languages like German or Spanish look
  // like English to a quick check, so the agent decides.
  function translateBtn(s, req) {
    if (!s.translation) return '<button type="button" class="btn btn-sm pn-tr-btn" data-translate="1">' + ICON_TR + 'Translate to English</button>';
    var differs = Object.keys(s.translation).some(function (k) {
      var orig = k === 'subject' ? s.subject : ((req.fields || []).filter(function (f) { return f.label.toLowerCase() === k; })[0] || {}).value;
      return s.translation[k] && s.translation[k] !== orig;
    });
    if (!differs) return '<span class="pn-tr-done">' + ICON_TR + 'Already in English</span>';
    return '<button type="button" class="btn btn-sm pn-tr-btn" data-entoggle="1">' + ICON_TR + (SHOW_EN ? 'Hide English' : 'Show English') + '</button>';
  }
  function kvEn(s, k, v, key) {
    return '<div><span class="pn-k">' + esc(k) + '</span><span class="pn-v">' + esc(v) + '</span>' + en(s, key, v) + '</div>';
  }

  function kv(k, v, sub, wide, cls) {
    return '<div' + (wide ? ' class="pn-wide"' : '') + '><span class="pn-k">' + esc(k) + '</span><span class="pn-v' + (cls ? ' ' + cls : '') + '">' + esc(v) + '</span>' +
      (sub ? '<span class="pn-sub">' + esc(sub) + '</span>' : '') + '</div>';
  }
  function fullWhen(ms) {
    if (!ms) return '';
    return new Date(ms).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  function header(s, req, f) {
    var title = f['package name'] || s.subject || ('Ticket #' + s.ticket_id);
    // First row: when, who and which ticket; then what the package is.
    var facts = [];
    if (f['date of creation']) facts.push(kv('Created', f['date of creation']));
    var who = f['creator'] || s.creator_email;
    if (who) facts.push(kv('Creator', who, s.creator_domain && who.indexOf(s.creator_domain) < 0 ? s.creator_domain : '', 1));
    facts.push('<div><span class="pn-k">Ticket</span><a class="pn-v" href="' + esc(s.zendesk_url) + '/agent/tickets/' + s.ticket_id +
               '" target="_blank" rel="noopener">#' + s.ticket_id + '</a></div>');
    [['Type', f['type']], ['Subscription', f['subscription'], 1], ['Technicians', f['technician count']]].forEach(function (x) {
      // a trial package stands out: worth a closer look before it goes to customers
      if (x[1]) facts.push(kv(x[0], x[1], '', x[2], x[0] === 'Type' && /trial/i.test(x[1]) ? 'pn-trial' : ''));
    });
    if (s.organization) facts.push(kv('Organization', s.organization, '', 1));
    return '<header class="pn-head">' +
      '<div class="pn-meta">' + pill(state(s)) + '<span>' + esc(whenTxt(s.requested_ms)) + '</span>' +
        (s.source === 'import' ? '<span>· imported</span>' : s.source === 'webhook' ? '<span>· from Zendesk trigger</span>' : '') +
        translateBtn(s, req) + '</div>' +
      '<h2 class="pn-title">' + esc(title) + '</h2>' + en(s, f['package name'] ? 'package name' : 'subject', title) +
      (f['caption'] ? '<div class="pn-cap">' + esc(f['caption']) + '</div>' : '') +
      (facts.length ? '<div class="pn-facts">' + facts.join('') + '</div>' : '') +
      '</header>';
  }

  // The package's links as buttons: the ACP pages (download=false) or the
  // download (download=true).
  // Who pressed Scan in SplashHub's sidebar for this request (newest first).
  var PRESS = { viewed: 'saw this review', started: 'started the AI review', again: 'pressed Review again' };
  function sidebarBlock(s) {
    var hist = [];
    try { hist = JSON.parse(s.sidebar_json || '[]'); } catch (e) {}
    if (!hist.length) return '';
    hist = hist.slice().reverse();
    var row = function (p) {
      var d = new Date(p.ms);
      return '<li><b>' + esc(p.by) + '</b> ' + esc(PRESS[p.action] || p.action) + ' <span class="sb-when">' +
        esc(d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })) + '</span></li>';
    };
    return '<section class="pn-sec sb-press"><div class="pn-h">Scan in SplashHub</div><ul>' + hist.slice(0, 5).map(row).join('') + '</ul>' +
      (hist.length > 5 ? '<details><summary>' + (hist.length - 5) + ' earlier</summary><ul>' + hist.slice(5).map(row).join('') + '</ul></details>' : '') +
      '</section>';
  }

  function linkBtns(req, download) {
    return (req.links || []).filter(function (l) {
      return /^https?:\/\//i.test(l.url) && (l.label.toLowerCase() === 'download package') === download;
    }).map(function (l) {
      return '<a class="btn btn-sm" href="' + esc(l.url) + '" target="_blank" rel="noopener noreferrer" title="' + esc(l.url) + '">' +
        esc(LINK_NAMES[l.label.toLowerCase()] || l.label) + ICON_OUT + '</a>';
    });
  }

  // The AI review: the result when there is one, else the button. The button
  // works whatever the switch says -- it is someone deciding, for this one.
  function aiBlock(s, items) {
    var busy = (s.status === 'queued' || s.status === 'running') && s.ai_review === 'manual';
    var h = '<section class="pn-sec pn-ai"><div class="pn-h">AI review';
    if (s.result && !busy) {
      h += '<button type="button" class="btn btn-sm pn-ai-btn" data-review="1">Re-review</button>';
    }
    h += '</div>';
    if (busy) {
      return h + '<div class="pn-ai-run"><span class="spin-dot" aria-hidden="true"></span>Reviewing&hellip; this usually takes under a minute.</div></section>';
    }
    var note = s.error && (s.status === 'held' || s.status === 'done') ? s.error : '';
    var failed = /^The AI review didn/.test(note);
    if (failed) h += '<div class="pn-ai-warn">' + esc(note) + '</div>';
    if (!s.result) {
      // Only images that failed to download -- older requests show theirs
      // from Zendesk on purpose, and the review fetches what it needs.
      var noCopies = (s.gallery || []).some(function (g) { return !g.key && g.error; });
      h += (note && !failed ? '<div class="pn-why">' + esc(note.replace(/ -- /g, ' — ')) + '</div>' : '') +
        '<div class="pn-ai-cta"><button type="button" class="btn btn-primary" data-review="1">Run AI review</button>' +
        '<span class="pn-ai-hint">Checks the images and package details for brand impersonation, ' + COST_HINT + '. The result is saved here.</span></div>' +
        (noCopies ? '<div class="pn-ai-warn">Images can&rsquo;t be downloaded by SplashHub Centre yet, so the AI would only check the text details.</div>' : '');
      return h + '<div class="pn-ai-msg" aria-live="polite"></div></section>';
    }
    var res = s.result;
    // The same layout as SplashHub's sidebar scan (scan.js renderResults):
    // the generic-email warning, then ONE card -- the overall verdict with the
    // average confidence, the Splashtop-credit lines, one summary (package
    // details first, then each image) and one list of everything flagged.
    // Each image's own verdict is under its thumbnail in Images.
    // Team rule (stricter than the sidebar): a generic email is not accepted
    // unless the customer gives a reason -- never green, at most "Needs review".
    var generic = !!(s.creator_is_free_email || res.creator_domain_is_generic_email || res.generic_email);
    if (generic) {
      h += '<div class="sh-generic">Generic email detected' + (s.creator_email ? ' (' + esc(s.creator_email) + ')' : '') +
        '<span class="sh-generic-sub">Not accepted unless the customer gives a reason.</span></div>';
    }
    if (res.text_only) {
      h += '<div class="pn-ai-warn">Text-only review: ' + res.text_only + (res.text_only === 1 ? ' image' : ' images') +
        ' couldn&rsquo;t be downloaded, so the AI didn&rsquo;t see ' + (res.text_only === 1 ? 'it' : 'them') + '.</div>';
    }
    var tr = res.ticket_review && res.ticket_review.verdict !== 'not_applicable' ? res.ticket_review : null;
    var fs = res.findings || [];
    var SEV = { normal: 0, needs_review: 1, suspicious: 2 };
    var worst = fs.map(function (f) { return f.verdict; }).concat(tr ? [tr.verdict] : [])
      .reduce(function (w, v) { return SEV[v] > SEV[w] ? v : w; }, 'normal');
    if (generic && worst === 'normal') worst = 'needs_review';
    var conf = fs.length ? Math.round(fs.reduce(function (t, f) { return t + (f.confidence || 0); }, 0) / fs.length * 100) : null;
    h += '<div class="sh-card"><span class="vpill v-' + esc(worst) + '">' + esc(LABEL[worst] || worst) +
      (conf != null ? ' (' + conf + '%)' : '') + '</span>';
    var shown = {};
    fs.forEach(function (f) {
      var r = f.splashtop_reference;
      if (shown[r] || (r !== 'powered_by_attribution' && r !== 'other_reference')) return;
      shown[r] = 1;
      h += r === 'other_reference'
        ? '<div class="sh-warn">Contains a Splashtop name/logo/attribution beyond &ldquo;Powered by&rdquo; &mdash; not acceptable for a white-label build.</div>'
        : '<div class="sh-sum">Contains a &ldquo;Powered by Splashtop&rdquo; attribution &mdash; acceptable for a white-label build.</div>';
    });
    var parts = (tr ? [tr.summary] : []).concat(fs.map(function (f) { return f.summary; })).filter(Boolean);
    if (!fs.length && !tr && res.overall_summary) parts = [res.overall_summary];
    if (parts.length) h += '<div class="sh-sum">' + esc(parts.join(' ')) + '</div>';
    var flags = [].concat.apply(tr ? (tr.flagged_fields || []).slice() : [], fs.map(function (f) { return f.flagged_elements || []; }));
    if (flags.length) h += '<ul class="sh-flags">' + flags.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>';
    h += '</div>';
    h += '<div class="pn-ai-by">' + (s.ai_review === 'manual' ? 'Reviewed with the AI review button' : 'Reviewed automatically on arrival') +
      (s.reviewed_ms || s.finished_ms ? ' · ' + esc(fullWhen(s.reviewed_ms || s.finished_ms)) : '') +
      (s.model ? ' · ' + esc(s.model) + ' · ' + esc(formatUsd(s.cost)) : '') + '</div>';
    return h + noteBlock(s) + '<div class="pn-ai-msg" aria-live="polite"></div></section>';
  }

  // "Add as internal note": preview the note (summary or full details), then
  // add it to the Zendesk ticket. Manual: nothing is added without the press.
  var NOTE = { open: null, text: '', busy: false };
  function noteBlock(s) {
    var h = '<div class="pn-note">';
    if (s.note && s.note.error) {
      h += '<div class="pn-ai-warn">The automatic internal note failed: ' + esc(s.note.error) + '</div>';
    } else if (s.note && s.note.ms) {
      h += '<div class="pn-note-done">&#10003; Added to Zendesk as an internal note' + (s.note.auto ? ' automatically' : '') +
        ' · ' + esc(fullWhen(s.note.ms)) + '</div>';
    }
    if (NOTE.open !== s.id) {
      return h + '<button type="button" class="btn pn-note-btn" data-note="1">' + (s.note ? 'Add another internal note' : 'Add as internal note') + '</button></div>';
    }
    return h + '<div class="pn-note-box">' +
      '<div class="pn-note-top"><span class="pn-note-lbl">Internal note on #' + s.ticket_id + '</span></div>' +
      // The server builds the note's HTML and escapes everything in it from the ticket or the AI.
      '<div class="pn-note-pre zd-note">' + (NOTE.text || 'Loading&hellip;') + '</div>' +
      '<div class="pn-note-hint">Only agents see internal notes; the customer is not notified.</div>' +
      '<div class="pn-note-act"><button type="button" class="btn btn-primary btn-sm" data-notepost="1"' + (NOTE.busy || !NOTE.text ? ' disabled' : '') + '>' +
        (NOTE.busy ? 'Adding&hellip;' : 'Add to Zendesk') + '</button>' +
        '<button type="button" class="btn btn-sm" data-notecancel="1">Cancel</button></div>' +
      '</div></div>';
  }
  function notePreview(s) {
    NOTE.text = '';

    api('/api/scans/' + s.id + '/note').then(function (r) {
      if (NOTE.open === s.id) { NOTE.text = r.html; redraw(); }
    }).catch(function (e) { if (e.message !== 'login') { NOTE.text = ''; noteMsg(e.message); } });
  }
  function redraw() { if (CUR) $('detail').innerHTML = render(CUR); }
  function noteMsg(t) { var m = $('detail').querySelector('.pn-ai-msg'); if (m) m.textContent = t; }

  function endUserBlock(s, req, f) {
    var shown = [['Caption', f['caption']], ['Instruction text', f['instruction text']], ['Disclaimer', f['disclaimer']],
                 ['Screenshot', f['screenshot']]].filter(function (x) { return x[1]; });
    var other = (req.fields || []).filter(function (x) { return !KNOWN[x.label.toLowerCase()] && x.value; });
    var h = '';
    if (shown.length) {
      h += '<section class="pn-sec"><div class="pn-h">What end users see</div><div class="pn-stack">' +
        shown.map(function (x) { return kvEn(s, x[0], x[1], x[0].toLowerCase()); }).join('') + '</div></section>';
    }
    if (other.length) {
      h += '<section class="pn-sec"><div class="pn-h">Other details</div><div class="pn-stack">' +
        other.map(function (x) { return kvEn(s, x.label, x.value, x.label.toLowerCase()); }).join('') + '</div></section>';
    }
    return h;
  }

  // Every image on the ticket, from Zendesk's own link (it loads for anyone
  // signed in to Zendesk in this browser). Requests from before copies were
  // dropped may still have a stored copy, which is used when present.
  function galleryItems(s) {
    if (s.gallery && s.gallery.length) {
      return s.gallery.map(function (g) {
        var link = /^https:\/\/[^\/]+\.(zendesk\.com|zdusercontent\.com)\//i.test(g.url || '') ||
                   (s.zendesk_url && (g.url || '').indexOf(s.zendesk_url + '/') === 0) ? g.url : '';
        return { src: g.key ? '/api/scans/' + s.id + '/image/' + g.id : link, name: g.filename, error: g.error,
                 bytes: g.bytes, reviewed: g.reviewed_index, linked: !g.key && !!link };
      });
    }
    return (s.images || []).map(function (im, i) { return { src: im.content_url, name: im.filename, reviewed: i }; });
  }
  function kb(n) { return n ? (n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB') : ''; }

  function gallery(s, items) {
    if (!items.length) return '';
    var res = s.result || {};
    var linked = items.some(function (it) { return it.linked; });
    return '<section class="pn-sec"><div class="pn-h">Images <span class="count">' + items.length + '</span>' +
      '<span class="gal-note">' + (linked ? 'Shown from Zendesk &mdash; sign in to Zendesk in this browser if they don&rsquo;t load.'
                                         : (s.result ? 'Outlined images are the ones the AI reviewed.' : '')) + '</span></div><div class="gal-grid">' +
      items.map(function (it, i) {
        var f = it.reviewed != null ? (res.findings || []).filter(function (x) { return x.image_index === it.reviewed; })[0] : null;
        return '<figure class="gal-item' + (it.reviewed != null && s.result ? ' reviewed' : '') + '">' +
          (it.src
            ? '<button type="button" class="gal-img" data-lb="' + i + '" title="Open ' + esc(it.name) + '">' +
                '<img src="' + esc(it.src) + '" alt="' + esc(it.name) + '" loading="lazy" referrerpolicy="no-referrer"></button>'
            : '<div class="gal-img gal-missing" title="' + esc(it.error || '') + '">Couldn&rsquo;t download</div>') +
          '<figcaption><span class="gal-name" title="' + esc(it.name) + '">' + esc(it.name) + '</span>' +
            '<span class="gal-meta">' + (f ? pill(f.verdict) : '') +
            (it.bytes ? ' <span class="muted">' + kb(it.bytes) + '</span>' : '') + '</span></figcaption></figure>';
      }).join('') + '</div></section>';
  }

  function render(s) {
    var req = s.request || { fields: [], links: [] }, f = fieldMap(req);
    var items = galleryItems(s);
    LB.items = items.filter(function (it) { return it.src; });
    // Two columns, top to bottom: the request on the left, its AI review the
    // whole right side (stacked, AI review first, when the pop-up is narrow).
    var h = '<div class="pn-cols"><div class="pn-main">' + header(s, req, f);
    // Problems with the request itself; the AI block explains its own state.
    if (s.error && s.status !== 'held' && s.status !== 'done' && !(s.status === 'queued' || s.status === 'running')) {
      h += '<div class="' + (s.status === 'waiting' || s.status === 'skipped' ? 'sc-info' : 'sc-err') + '">' + esc(s.error) + '</div>';
    }
    h += endUserBlock(s, req, f) + gallery(s, items);
    if (s.description) {
      h += '<section class="pn-sec"><button type="button" class="link-btn rq-raw-btn" data-raw="1" aria-expanded="false">Show original text</button>' +
        '<pre class="rq-raw" hidden>' + esc(s.description) + '</pre></section>';
    }
    h += sidebarBlock(s);
    h += '<div class="pn-foot">' + ['Scan ' + s.id, s.creator_source ? 'Creator from ' + esc(s.creator_source) : '',
                                     s.requested_by ? 'Started by ' + esc(s.requested_by) : ''].filter(Boolean).join(' · ') + '</div>';
    // Right: the ACP pages, then the download, as full-width buttons; then the AI review card.
    var acp = linkBtns(req, false).concat(linkBtns(req, true));
    h += '</div><div class="pn-side"><div class="pn-side-in">' +
      (acp.length ? '<div class="pn-acp">' + acp.join('') + '</div>' : '') + aiBlock(s, items) + '</div></div></div>';
    return h;
  }

  var dseq = 0;
  function loadDetail(id) {
    var my = ++dseq;
    api('/api/scans/' + id).then(function (s) {
      if (my !== dseq || S.open !== id) return;
      var box = $('detail');
      // The original text stays open across refreshes of the same request.
      var rawOpen = CUR && CUR.id === s.id && box.querySelector('.rq-raw:not([hidden])');
      CUR = s;
      box.innerHTML = render(s);
      if (rawOpen) box.querySelector('[data-raw]').click();
      if (s.status === 'queued' || s.status === 'running') { clearTimeout(dpoll); dpoll = setTimeout(function () { if (S.open === id) { loadDetail(id); load(); } }, 3000); }
    }).catch(function (e) { if (my === dseq && e.message !== 'login') $('detail').innerHTML = '<div class="pn-loading"><div class="sc-err">Could not load this request.</div></div>'; });
  }
  var dpoll = null;

  // ---- opening, closing, stepping ---------------------------------------------------
  function rowEls() { return [].slice.call($('rows').querySelectorAll('.sc-row')); }
  function markOpen() {
    var list = rowEls(), at = -1;
    list.forEach(function (tr, i) {
      var on = +tr.getAttribute('data-id') === S.open;
      tr.classList.toggle('open', on);
      if (on) at = i;
    });
    $('pnPos').textContent = at >= 0 ? (at + 1) + ' of ' + list.length + ' on this page' : '';
    $('pnPrev').disabled = at <= 0;
    $('pnNext').disabled = at < 0 || at >= list.length - 1;
  }
  function openPanel(id) {
    var same = S.open === id && !$('pnWrap').hidden;
    if ($('pnWrap').hidden) back = document.activeElement;     // focus goes back there on close
    S.open = id;
    if (location.hash !== '#' + id) history.replaceState(null, '', '#' + id);
    $('pnWrap').hidden = false;
    document.body.classList.add('pn-lock');
    markOpen();
    if (!same) $('panel').focus();
    if (!same) {
      CUR = null; NOTE.open = null;
      $('detail').innerHTML = '<div class="pn-loading">Loading&hellip;</div>';
      $('panel').scrollTop = 0;
    }
    loadDetail(id);
  }
  function closePanel() {
    S.open = null; CUR = null; clearTimeout(dpoll);
    if (location.hash) history.replaceState(null, '', VIEW === 'list' ? '#list' : location.pathname);
    $('pnWrap').hidden = true;
    document.body.classList.remove('pn-lock');
    markOpen();
    if (back && document.contains(back)) back.focus();
    back = null;
  }
  var back = null;
  function step(d) {
    var list = rowEls(), at = list.findIndex(function (tr) { return +tr.getAttribute('data-id') === S.open; });
    var next = list[at + d];
    if (at < 0 || !next) return;
    openPanel(+next.getAttribute('data-id'));
    next.scrollIntoView({ block: 'nearest' });   // the list behind follows along
    back = next;
  }
  $('pnClose').addEventListener('click', closePanel);
  $('pnWrap').addEventListener('mousedown', function (ev) { if (ev.target === this) closePanel(); });   // click outside
  $('pnPrev').addEventListener('click', function () { step(-1); });
  $('pnNext').addEventListener('click', function () { step(1); });

  $('rows').addEventListener('click', function (ev) {
    if (ev.target.closest('a')) return;
    var tr = ev.target.closest('.sc-row'); if (!tr) return;
    var id = +tr.getAttribute('data-id');
    if (S.open === id) closePanel(); else openPanel(id);
  });
  $('rows').addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' && ev.target.classList.contains('sc-row')) ev.target.click();
  });
  // ↑ / ↓ step to the next request without closing, Esc closes -- not while
  // typing, and not while the lightbox has the keys.
  document.addEventListener('keydown', function (ev) {
    if (ev.defaultPrevented || $('pnWrap').hidden || /^(INPUT|TEXTAREA|SELECT)$/.test((ev.target.tagName || ''))) return;
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') { ev.preventDefault(); step(ev.key === 'ArrowDown' ? 1 : -1); }
    else if (ev.key === 'Escape') closePanel();
  });
  // Tab stays inside the pop-up while it is open.
  $('pnWrap').addEventListener('keydown', function (ev) {
    if (ev.key !== 'Tab') return;
    var f = [].slice.call($('panel').querySelectorAll('a[href], button:not([disabled])')).filter(function (x) { return x.offsetParent; });
    if (!f.length) return;
    if (ev.shiftKey && (document.activeElement === f[0] || document.activeElement === $('panel'))) { ev.preventDefault(); f[f.length - 1].focus(); }
    else if (!ev.shiftKey && document.activeElement === f[f.length - 1]) { ev.preventDefault(); f[0].focus(); }
  });

  // Panel interactions: the AI review button, the original text, the lightbox.
  $('detail').addEventListener('click', function (ev) {
    var rv = ev.target.closest('[data-review]');
    if (rv && CUR) {
      var s = CUR;     // no confirm: the button is the decision (its hint gives the cost)
      rv.disabled = true;
      var msg = $('detail').querySelector('.pn-ai-msg');
      api('/api/scans/' + s.id + '/review', { method: 'POST' })
        .then(function () { loadDetail(s.id); load(); })
        .catch(function (e) { rv.disabled = false; if (msg && e.message !== 'login') msg.textContent = e.message; });
      return;
    }
    if (CUR && ev.target.closest('[data-note]')) {
      NOTE.open = CUR.id; NOTE.busy = false; redraw(); notePreview(CUR);
      return;
    }
    if (CUR && ev.target.closest('[data-notecancel]')) { NOTE.open = null; redraw(); return; }
    if (CUR && ev.target.closest('[data-notepost]')) {
      var ns_s = CUR;
      NOTE.busy = true; redraw();
      api('/api/scans/' + ns_s.id + '/note', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        .then(function (r) { ns_s.note = r.note; NOTE.open = null; NOTE.busy = false; if (CUR === ns_s) redraw(); })
        .catch(function (e) { NOTE.busy = false; redraw(); if (e.message !== 'login') noteMsg(e.message); });
      return;
    }
    var trb = ev.target.closest('[data-translate]');
    if (trb && CUR) {
      var cur = CUR;
      trb.disabled = true; trb.lastChild.textContent = 'Translating…';
      api('/api/scans/' + cur.id + '/translate', { method: 'POST' })
        .then(function (r) { if (CUR === cur) { cur.translation = r.translation; SHOW_EN = true; $('detail').innerHTML = render(cur); } })
        .catch(function (e) { trb.disabled = false; trb.lastChild.textContent = e.message === 'login' ? 'Translate to English' : e.message; });
      return;
    }
    if (ev.target.closest('[data-entoggle]') && CUR) {
      SHOW_EN = !SHOW_EN; $('detail').innerHTML = render(CUR);
      return;
    }
    var raw = ev.target.closest('[data-raw]');
    if (raw) {
      var pre = raw.nextElementSibling, open = pre.hidden;
      pre.hidden = !open; raw.setAttribute('aria-expanded', open); raw.textContent = open ? 'Hide original text' : 'Show original text';
      return;
    }
    var g = ev.target.closest('[data-lb], [data-lbsrc]');
    if (g) {
      var src = g.getAttribute('data-lbsrc') || g.querySelector('img').getAttribute('src');
      LB.i = Math.max(0, LB.items.findIndex(function (x) { return x.src === src; }));
      showLb();
    }
  });

  var lb = document.createElement('div');
  lb.className = 'lb'; lb.hidden = true; lb.setAttribute('role', 'dialog'); lb.setAttribute('aria-modal', 'true');
  lb.innerHTML = '<button type="button" class="lb-x" aria-label="Close">&times;</button>' +
    '<button type="button" class="lb-nav lb-prev" aria-label="Previous image">&#8249;</button>' +
    '<figure class="lb-fig"><img alt=""><figcaption></figcaption></figure>' +
    '<button type="button" class="lb-nav lb-next" aria-label="Next image">&#8250;</button>';
  document.body.appendChild(lb);
  function showLb() {
    var it = LB.items[LB.i]; if (!it) return;
    lb.querySelector('img').src = it.src; lb.querySelector('img').alt = it.name;
    lb.querySelector('figcaption').textContent = it.name + '  ·  ' + (LB.i + 1) + ' of ' + LB.items.length;
    lb.querySelector('.lb-prev').hidden = lb.querySelector('.lb-next').hidden = LB.items.length < 2;
    lb.hidden = false; lb.querySelector('.lb-x').focus();
  }
  function lbStep(d) { LB.i = (LB.i + d + LB.items.length) % LB.items.length; showLb(); }
  lb.addEventListener('click', function (ev) {
    if (ev.target.closest('.lb-prev')) lbStep(-1);
    else if (ev.target.closest('.lb-next')) lbStep(1);
    else if (ev.target === lb || ev.target.closest('.lb-x')) lb.hidden = true;
  });
  // Capture phase, so it runs before the panel's keys: it marks the keys it
  // uses (preventDefault) and the panel leaves those alone.
  document.addEventListener('keydown', function (ev) {
    if (lb.hidden) return;
    if (ev.key === 'Escape') { lb.hidden = true; ev.preventDefault(); }
    else if (ev.key === 'ArrowLeft') { lbStep(-1); ev.preventDefault(); }
    else if (ev.key === 'ArrowRight') { lbStep(1); ev.preventDefault(); }
    else if (ev.key === 'ArrowUp' || ev.key === 'ArrowDown') ev.preventDefault();
  }, true);

  $('verdicts').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-v]'); if (!b) return;
    S.verdict = b.getAttribute('data-v'); S.page = 0; load();
  });
  var typing = null;
  $('q').addEventListener('input', function () {
    var v = this.value.trim(); clearTimeout(typing);
    typing = setTimeout(function () { S.q = v; S.page = 0; load(); }, 250);
  });
  $('refresh').addEventListener('click', function () { setup(); if (VIEW === 'dash') loadDash(true); else load(true); });
  $('prev').addEventListener('click', function () { if (S.page > 0) { S.page--; load(); } });
  $('next').addEventListener('click', function () { S.page++; load(); });

})();
