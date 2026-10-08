// SplashHub Centre -- Ad/Spam Filter (adfilter.py): the tickets Spark thinks
// are marketing or spam, held here to be checked. Open tasks first (not solved
// or closed), then Solved / closed and the ones marked wrong. A row opens the
// preview: the ticket's whole first message (fresh from Zendesk), Spark's call,
// Right / Wrong, and Silent close -- confirmed twice: the silent_close tag, a
// private note "Silent-Close" (nothing to the customer), Product = Don't Know,
// Issue Type = Other and Solved; then what stuck. It can be pressed again.
(function () {
  'use strict';

  var S = { view: 'open', q: '', page: 0, rows: [] };
  var ST = null, ZD = '', CUR = null, P = null;
  var TSTATUS = { new: 'New', open: 'Open', pending: 'Pending', hold: 'On-hold', solved: 'Solved', closed: 'Closed' };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function int(n) { return (n || 0).toLocaleString('en-US'); }
  function api(path, opts) {
    return fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {})).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function post(path, body) { return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }
  function when(ms) {
    if (!ms) return '';
    var d = new Date(ms), now = new Date();
    var t = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    return d.toDateString() === now.toDateString() ? 'Today ' + t : (d.getMonth() + 1) + '/' + d.getDate() + ' ' + t;
  }
  function tstatus(st) { return st ? '<span class="tst tst-' + esc(st) + '">' + esc(TSTATUS[st] || st) + '</span>' : '<span class="muted">—</span>'; }
  function zdUrl(id) { return ZD ? ZD + '/agent/tickets/' + id : ''; }
  function ticketLink(id) { return ZD ? '<a href="' + esc(zdUrl(id)) + '" target="_blank" rel="noopener">#' + id + '</a>' : '#' + id; }

  // ---- top --------------------------------------------------------------------------------------
  function loadStatus() {
    return api('/api/adfilter').then(function (s) {
      ST = s;
      var n = $('note');
      if (!s.on) { n.hidden = false; n.innerHTML = 'The Ad/Spam Filter is <b>off</b>. An admin can switch it on in <b>Settings &rsaquo; AutoTag</b>.'; }
      else if (s.error) { n.hidden = false; n.textContent = 'Last round: ' + s.error; }
      else n.hidden = true;
      $('stamp').textContent = s.last_ms ? 'Checked ' + when(s.last_ms) + ' · every 2 min' : (s.on ? 'Starting…' : '');
      var checked = s.right + s.wrong;
      var tile = function (label, value, sub, cls) {
        return '<div class="stat"><div class="stat-label">' + label + '</div><div class="stat-value ' + (cls || '') + '">' + value + '</div><div class="stat-sub">' + sub + '</div></div>';
      };
      $('stats').innerHTML =
        tile('Ads in open tasks', int(s.open_ads), int(s.done_ads) + ' more already solved / closed', s.open_ads ? 'ov-o' : '') +
        tile('Tickets scanned', int(s.checked), 'created since ' + esc(s.since) + ' · ' + int(s.ads) + ' were ads') +
        tile('Checked by the team', checked ? Math.round(100 * s.right / checked) + '% right' : '—',
          int(s.right) + ' right · ' + int(s.wrong) + ' wrong · ' + int(s.silent) + ' silently closed');
      [].forEach.call($('adview').children, function (c) {
        var k = c.getAttribute('data-v'), n = k === 'open' ? s.open_ads : k === 'done' ? s.done_ads : s.wrong;
        var lbl = c.textContent.replace(/\s*[\d,]+$/, '');
        c.innerHTML = esc(lbl) + ' <span class="chip-n">' + int(n) + '</span>';
      });
    }).catch(function (e) { $('note').hidden = false; $('note').textContent = 'Could not load the Ad/Spam Filter: ' + e.message; });
  }

  // ---- the list ---------------------------------------------------------------------------------
  function checkTxt(r) {
    if (r.silent_ms) return '<span class="ad-silent" title="Silently closed from SplashHub Centre ' + esc(when(r.silent_ms)) + '">Silent-closed</span>';
    if (r.verdict === 'right') return '<span class="at-ok">✓ Right</span>';
    if (r.verdict === 'wrong') return '<span class="at-bad">✗ Wrong</span>';
    return '<span class="muted">Not checked</span>';
  }
  // Spark's call (it may have changed when scanned again: then what it was before)
  function said(r) {
    var b = r.spam ? '<span class="at-b ad-b">Ad / spam</span>' : '<span class="at-b at-none">Not an ad</span>';
    if (r.rescan_ms && r.prev_spam != null && +r.prev_spam !== +r.spam)
      b += ' <span class="at-conf at-was" title="Spark changed its call when scanned again ' + esc(when(r.rescan_ms)) + '">was ' + (r.prev_spam ? 'ad / spam' : 'not an ad') + '</span>';
    return b;
  }
  function row(r) {
    return '<tr class="ad-row" tabindex="0" data-id="' + r.ticket_id + '"><td class="when">' + esc(when(r.created_ms)) + '</td>' +
      '<td>' + ticketLink(r.ticket_id) + '</td><td>' + tstatus(r.status) + '</td>' +
      '<td class="ad-subj"><div class="ad-s">' + esc(r.subject || '(no subject)') + '</div><div class="muted">' + esc(r.requester || '') + '</div></td>' +
      '<td>' + said(r) + (r.confidence && r.confidence !== 'high' ? ' <span class="at-conf at-' + esc(r.confidence) + '">' + esc(r.confidence) + '</span>' : '') +
        (r.why ? '<div class="muted">' + esc(r.why) + '</div>' : '') + '</td>' +
      '<td>' + checkTxt(r) + '</td></tr>';
  }
  var seq = 0;
  function load() {
    var my = ++seq, q = ['page=' + S.page, 'view=' + S.view];
    if (S.q) q.push('q=' + encodeURIComponent(S.q));
    return api('/api/adfilter/list?' + q.join('&')).then(function (d) {
      if (my !== seq) return;
      S.rows = d.rows;
      $('count').textContent = d.total ? 'newest first · ' + int(d.total) + (d.total === 1 ? ' ticket' : ' tickets') : '';
      $('rows').innerHTML = d.rows.length ? d.rows.map(row).join('') : '<tr class="empty-row"><td colspan="6">' +
        (S.q ? 'No tickets match.' : S.view === 'open' ? 'No ads among the open tickets.' : S.view === 'done' ? 'No solved or closed ads.' : 'Nothing marked wrong.') + '</td></tr>';
      var pages = Math.ceil(d.total / d.per_page);
      $('pager').hidden = pages <= 1;
      $('pagerTxt').textContent = 'Page ' + (d.page + 1) + ' of ' + pages;
      $('prev').disabled = d.page <= 0; $('next').disabled = d.page + 1 >= pages;
    }).catch(function (e) { $('rows').innerHTML = '<tr class="empty-row"><td colspan="6">Could not load: ' + esc(e.message) + '</td></tr>'; });
  }

  // ---- the preview ------------------------------------------------------------------------------
  function detail(p) {
    var r = p.row, z = p.zd;
    var silent = r.silent_ms ? '<div class="ad-done">Silently closed from SplashHub Centre ' + esc(when(r.silent_ms)) + '.' + checkLine(p.check) + '</div>' : '';
    var close =
      '<div class="at-k">Silent close</div>' +
      (p.confirm ? '<div class="ad-confirm">' +
          '<div>On ticket <b>#' + r.ticket_id + '</b> in Zendesk: adds the tag <code>silent_close</code>, a <b>private note &ldquo;Silent-Close&rdquo;</b>, sets <b>Product = Don&rsquo;t Know</b> and <b>Issue Type = Other</b>, and marks it <b>Solved</b>. Nothing is sent to the customer.</div>' +
          '<label class="ad-sure"><input type="checkbox" id="adSure"> I checked it: this ticket is spam / marketing</label>' +
          '<div class="frow ad-act"><button type="button" class="btn btn-sm ad-danger" id="adGo" disabled>Yes, silent close #' + r.ticket_id + '</button>' +
          '<button type="button" class="btn btn-sm" id="adCancel">Cancel</button></div></div>'
        : '<div class="frow ad-act"><button type="button" class="btn btn-sm ad-danger-o" id="adClose">' + (r.silent_ms ? 'Silent close again…' : 'Silent close…') + '</button>' +
          '<span class="muted">Tag, private note, Product / Issue Type, Solved; asks twice.</span></div>');
    return '<div class="at-d">' +
      '<div class="at-dh"><div class="at-dt">' + ticketLink(r.ticket_id) + ' · ' + esc(r.subject || '(no subject)') + '</div>' +
        '<div class="muted">' + esc(when(r.created_ms)) + (r.requester ? ' · ' + esc(r.requester) : '') + (r.channel ? ' · ' + esc(r.channel) : '') + ' · ' + tstatus(z.status || r.status) + '</div></div>' +
      silent +
      '<div class="at-grid"><div class="at-box"><div class="at-k">Spark says</div><div>' + said(r) + ' ' + esc(r.confidence ? r.confidence + ' confidence' : '') + '</div>' +
        (r.why ? '<div>' + esc(r.why) + '</div>' : '') + '<div class="muted"><a href="/sparklog#t-' + r.ticket_id + '">What Spark read and answered</a> (admins)</div>' +
        (r.rescan_ms ? '<div class="rs-line">Scanned again ' + esc(when(r.rescan_ms)) + ': ' + (r.prev_spam != null && +r.prev_spam !== +r.spam ? 'Spark changed its call' : 'same call') + '</div>' : '') +
        '<div class="frow rs-act"><button type="button" class="btn btn-sm" id="adRescan" title="Read this ticket again and ask Spark again, with today\u2019s rules. Nothing is written to Zendesk.">Scan again with Spark</button></div></div>' +
      '<div class="at-box"><div class="at-k">In Zendesk now</div><div>' + tstatus(z.status || r.status) + '</div>' +
        '<div class="muted ad-tags">' + (z.tags && z.tags.length ? z.tags.map(function (t) { return '<code>' + esc(t) + '</code>'; }).join(' ') : 'no tags') + '</div></div></div>' +
      convo(z, r) +
      '<div class="at-k">Is Spark right?</div>' +
      '<div class="frow ad-act"><button type="button" class="btn btn-sm' + (r.verdict === 'right' ? ' on-ok' : '') + '" data-v="right">✓ Right, it’s spam</button>' +
        '<button type="button" class="btn btn-sm' + (r.verdict === 'wrong' ? ' on-bad' : '') + '" data-v="wrong">✗ Wrong, it’s real</button>' +
        (r.verdict && !r.silent_ms ? '<button type="button" class="btn btn-sm btn-link" data-v="">Undo</button>' : '') + '</div>' +
      close +
      '<div class="sc-msg" id="adMsg" aria-live="polite"></div>' +
      '<div class="frow"><a class="btn btn-sm" href="' + esc(zdUrl(r.ticket_id)) + '" target="_blank" rel="noopener">Open in Zendesk</a></div></div>';
  }
  // what Zendesk shows after a silent close: each part ✓ or ✗
  function checkLine(c) {
    if (!c) return '';
    var part = function (ok, label) { return '<span class="' + (ok ? 'at-ok' : 'at-bad') + '">' + (ok ? '✓' : '✗') + ' ' + esc(label) + '</span>'; };
    return '<div class="ad-check">' + part(c.tag, 'silent_close tag') + ' ' +
      Object.keys(c.fields || {}).map(function (k) { return part(c.fields[k], k); }).join(' ') + ' ' +
      part(c.status === 'solved' || c.status === 'closed', 'Solved' + (c.status && c.status !== 'solved' && c.status !== 'closed' ? ' (it is ' + c.status + ')' : '')) + '</div>';
  }
  // the whole ticket, oldest first: customer / agent / internal note, each with who and when
  function convo(z, r) {
    var c = z.conversation || [];
    if (!c.length) {
      return '<div class="at-k">What they wrote' + (z.live ? '' : ' <span class="muted">(kept copy — Zendesk didn’t answer)</span>') + '</div>' +
        '<div class="at-sample ad-full">' + esc(z.description || r.sample || '(no text)') + '</div>';
    }
    var LBL = { customer: 'Customer', agent: 'Agent', note: 'Internal note' };
    return '<div class="at-k">The whole ticket <span class="muted">(' + c.length + (c.length === 1 ? ' message' : ' messages') + ', oldest first)</span></div>' +
      '<div class="ad-convo">' + c.map(function (m) {
        return '<div class="ad-msg ad-' + esc(m.kind) + '"><div class="ad-mh"><b>' + esc(LBL[m.kind] || m.kind) + '</b>' +
          (m.who ? ' · ' + esc(m.who) : '') + (m.ms ? ' <span class="muted">· ' + esc(when(m.ms)) + '</span>' : '') + '</div>' +
          '<div class="ad-mb">' + esc(m.text || '') + '</div></div>';
      }).join('') + '</div>';
  }
  function draw() { if (P && CUR === P.row.ticket_id) $('detail').innerHTML = detail(P); }
  function openPanel(id) {
    var r = S.rows.filter(function (x) { return x.ticket_id === id; })[0]; if (!r) return;
    CUR = id; P = { row: r, zd: { description: '', tags: [], live: true }, confirm: false };
    $('pnWrap').hidden = false;
    document.body.classList.add('pn-lock');
    $('pnPos').textContent = (S.rows.indexOf(r) + 1) + ' of ' + S.rows.length + ' on this page';
    $('detail').innerHTML = '<div class="pn-loading">Loading the ticket…</div>';
    $('panel').focus();
    api('/api/adfilter/ticket/' + id).then(function (t) {
      if (CUR !== id) return;
      P.zd = { description: t.description, tags: t.tags, status: t.status, live: t.live, conversation: t.conversation };
      draw();
    }).catch(function (e) { if (CUR !== id) return; P.zd = { description: r.sample, tags: [], live: false }; draw(); $('adMsg').textContent = e.message; });
  }
  function closePanel() { CUR = null; P = null; $('pnWrap').hidden = true; document.body.classList.remove('pn-lock'); }
  function step(d) {
    var i = S.rows.map(function (x) { return x.ticket_id; }).indexOf(CUR), n = S.rows[i + d];
    if (n) openPanel(n.ticket_id);
  }
  function refreshRow(r) {
    S.rows = S.rows.map(function (x) { return x.ticket_id === r.ticket_id ? r : x; });
    var tr = document.querySelector('.ad-row[data-id="' + r.ticket_id + '"]'); if (tr) tr.outerHTML = row(r);
    if (P && P.row.ticket_id === r.ticket_id) { P.row = r; if (r.status) P.zd.status = r.status; }
  }

  $('detail').addEventListener('change', function (ev) { if (ev.target.id === 'adSure') $('adGo').disabled = !ev.target.checked; });
  $('detail').addEventListener('click', function (ev) {
    if (!P) return;
    var id = P.row.ticket_id, b = ev.target.closest('[data-v]');
    if (b) {
      post('/api/adfilter/verdict', { ticket_id: id, verdict: b.getAttribute('data-v') })
        .then(function (r) { refreshRow(r); draw(); loadStatus(); })
        .catch(function (e) { $('adMsg').textContent = 'Could not save: ' + e.message; });
      return;
    }
    if (ev.target.id === 'adRescan') {
      var rb = ev.target; rb.disabled = true; rb.textContent = 'Asking Spark…';
      post('/api/adfilter/rescan', { ids: [id] }).then(function (d) {
        if (d.row) { refreshRow(d.row); draw(); }
        loadStatus();
        var c = (d.rescan.changed || [])[0];
        if (CUR === id) $('adMsg').textContent = c ? 'Spark changed its call: ' + c.was + ' → ' + c.now + '.' : 'Spark made the same call as before.';
      }).catch(function (e) { rb.disabled = false; rb.textContent = 'Scan again with Spark'; $('adMsg').textContent = 'Could not scan again: ' + e.message; });
      return;
    }
    if (ev.target.id === 'adClose') { P.confirm = true; draw(); return; }            // first confirmation: the box
    if (ev.target.id === 'adCancel') { P.confirm = false; draw(); return; }
    if (ev.target.id === 'adGo') {                                                   // second: ticked, then this button
      if (!$('adSure').checked) return;
      var go = ev.target; go.disabled = true; go.textContent = 'Closing…';
      post('/api/adfilter/silent-close', { ticket_id: id }).then(function (r) {
        P.check = r.check; refreshRow(r); P.confirm = false; draw(); loadStatus();
        var c = r.check || {}, all = c.tag && (c.status === 'solved' || c.status === 'closed') && Object.keys(c.fields || {}).every(function (k) { return c.fields[k]; });
        var msg = all ? 'Done — #' + id + ' is silently closed.' : 'Not everything stuck on #' + id + ' — see above; you can press Silent close again.';
        $('adMsg').textContent = msg;
        api('/api/adfilter/ticket/' + id).then(function (t) {          // the ticket again: the new note in the conversation
          if (!P || CUR !== id) return;
          P.zd = { description: t.description, tags: t.tags, status: t.status, live: t.live, conversation: t.conversation };
          draw(); $('adMsg').textContent = msg;
        }).catch(function () {});
      }).catch(function (e) { go.disabled = false; go.textContent = 'Yes, silent close #' + id; $('adMsg').textContent = 'Could not silent close: ' + e.message; });
    }
  });

  // ---- controls ---------------------------------------------------------------------------------
  $('rows').addEventListener('click', function (ev) {
    if (ev.target.closest('a')) return;
    var tr = ev.target.closest('.ad-row'); if (tr) openPanel(+tr.getAttribute('data-id'));
  });
  $('rows').addEventListener('keydown', function (ev) { var tr = ev.target.closest('.ad-row'); if (tr && ev.key === 'Enter') openPanel(+tr.getAttribute('data-id')); });
  $('adview').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-v]'); if (!b) return;
    S.view = b.getAttribute('data-v'); S.page = 0;
    [].forEach.call(this.children, function (c) { c.classList.toggle('active', c === b); });
    load();
  });
  var qT = 0;
  $('q').addEventListener('input', function () { clearTimeout(qT); qT = setTimeout(function () { S.q = $('q').value.trim(); S.page = 0; load(); }, 250); });
  $('prev').addEventListener('click', function () { if (S.page > 0) { S.page--; load(); } });
  $('next').addEventListener('click', function () { S.page++; load(); });
  $('refresh').addEventListener('click', function () { loadStatus(); load(); });
  $('pnClose').addEventListener('click', closePanel);
  $('pnPrev').addEventListener('click', function () { step(-1); });
  $('pnNext').addEventListener('click', function () { step(1); });
  $('pnWrap').addEventListener('click', function (ev) { if (ev.target === this) closePanel(); });
  document.addEventListener('keydown', function (ev) {
    if ($('pnWrap').hidden || /^(INPUT|SELECT)$/.test((ev.target || {}).tagName || '')) return;
    if (ev.key === 'Escape') closePanel();
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); step(-1); }
    else if (ev.key === 'ArrowDown') { ev.preventDefault(); step(1); }
  });

  var RS_URL = '/api/adfilter/rescan';
  // ---- Scan again: the tickets on this page (or one, from the preview) read and asked again ----------
  //      with today's rules, to see whether a fix changed Spark's answers. Nothing goes to Zendesk.
  var rsT = 0;
  function rsDraw(rs, openable) {
    var el = $('rsBox');
    if (!rs || (!rs.running && !rs.finished_ms)) { el.hidden = true; return; }
    el.hidden = false;
    if (rs.running) { el.innerHTML = '<span class="at-spin"></span> Spark is reading ' + rs.total + ' ticket' + (rs.total === 1 ? '' : 's') + ' again… ' + rs.done + ' of ' + rs.total; return; }
    var ch = rs.changed || [];
    el.innerHTML = '<div class="rs-head"><b>Scanned again:</b> ' + (rs.total - rs.failed) + ' of ' + rs.total + ' read · ' +
      (ch.length ? '<b>' + ch.length + ' changed</b>' : 'no answer changed') +
      (rs.failed ? ' · <span class="muted">' + rs.failed + ' kept their old answer' + (rs.why_text ? ': ' + esc(rs.why_text) : '') + '</span>' : '') +
      (rs.error ? ' · <span class="at-bad">' + esc(rs.error) + '</span>' : '') +
      ' <button type="button" class="btn btn-sm btn-link" id="rsHide">Hide</button></div>' +
      (ch.length ? '<ul class="rs-list">' + ch.map(function (c) {
        return '<li><button type="button" class="btn-link rs-open" data-open="' + c.ticket_id + '">#' + c.ticket_id + '</button> ' +
          '<span class="rs-was">' + esc(c.was) + '</span> → <b>' + esc(c.now) + '</b>' + (c.why ? ' <span class="muted">· ' + esc(c.why) + '</span>' : '') + '</li>';
      }).join('') + '</ul>' : '');
  }
  function rsWatch() {
    clearTimeout(rsT);
    loadStatus().then(function () {
      var rs = ST && ST.rescan;
      rsDraw(rs);
      if (rs && rs.running) { rsT = setTimeout(rsWatch, 1500); return; }
      $('rescanPage').disabled = false;
      load();
    });
  }
  $('rescanPage').addEventListener('click', function () {
    var ids = S.rows.map(function (r) { return r.ticket_id; });
    if (!ids.length) return;
    var b = this; b.disabled = true;
    post(RS_URL, { ids: ids }).then(function (d) { rsDraw(d.rescan); rsWatch(); })
      .catch(function (e) { b.disabled = false; $('rsBox').hidden = false; $('rsBox').textContent = 'Could not scan again: ' + e.message; });
  });
  $('rsBox').addEventListener('click', function (ev) {
    if (ev.target.id === 'rsHide') { $('rsBox').hidden = true; return; }
    var o = ev.target.closest('[data-open]'); if (!o) return;
    var id = +o.getAttribute('data-open');
    if (S.rows.some(function (r) { return r.ticket_id === id; })) openPanel(id);
    else { S.q = String(id); $('q').value = S.q; S.page = 0; load().then(function () { openPanel(id); }); }
  });

  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (x) { ZD = x.zendesk_url || ''; if (S.rows.length) $('rows').innerHTML = S.rows.map(row).join(''); }).catch(function () {});
  loadStatus().then(function () { if (ST && ST.rescan && ST.rescan.running) rsWatch(); return load(); });
  setInterval(function () { if (document.visibilityState === 'visible' && $('pnWrap').hidden) { loadStatus(); load(); } }, 60000);
})();
