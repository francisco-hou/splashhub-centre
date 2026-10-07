// SplashHub Centre -- Ad/Spam Filter (adfilter.py): the tickets Spark thinks
// are marketing or spam, held here to be checked. Open tasks first (not solved
// or closed), then Solved / closed and the ones marked wrong. A row opens the
// preview: the ticket's whole first message (fresh from Zendesk), Spark's call,
// Right / Wrong, and Silent close -- confirmed twice; one Zendesk update adds a
// private note "Silent-Close" and the silent_close tag (nothing to the customer).
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
  function row(r) {
    return '<tr class="ad-row" tabindex="0" data-id="' + r.ticket_id + '"><td class="when">' + esc(when(r.created_ms)) + '</td>' +
      '<td>' + ticketLink(r.ticket_id) + '</td><td>' + tstatus(r.status) + '</td>' +
      '<td class="ad-subj"><div class="ad-s">' + esc(r.subject || '(no subject)') + '</div><div class="muted">' + esc(r.requester || '') + '</div></td>' +
      '<td><span class="at-b ad-b">Ad / spam</span>' + (r.confidence && r.confidence !== 'high' ? ' <span class="at-conf at-' + esc(r.confidence) + '">' + esc(r.confidence) + '</span>' : '') +
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
    var silent = r.silent_ms ? '<div class="ad-done">Silently closed from SplashHub Centre ' + esc(when(r.silent_ms)) +
      ' &mdash; private note &ldquo;Silent-Close&rdquo; and the <code>silent_close</code> tag added.</div>' : '';
    var close = r.silent_ms ? '' :
      '<div class="at-k">Silent close</div>' +
      (p.confirm ? '<div class="ad-confirm">' +
          '<div>Adds a <b>private note &ldquo;Silent-Close&rdquo;</b> and the tag <code>silent_close</code> to ticket <b>#' + r.ticket_id + '</b> in Zendesk. Nothing is sent to the customer.</div>' +
          '<label class="ad-sure"><input type="checkbox" id="adSure"> I checked it: this ticket is spam / marketing</label>' +
          '<div class="frow ad-act"><button type="button" class="btn btn-sm ad-danger" id="adGo" disabled>Yes, silent close #' + r.ticket_id + '</button>' +
          '<button type="button" class="btn btn-sm" id="adCancel">Cancel</button></div></div>'
        : '<div class="frow ad-act"><button type="button" class="btn btn-sm ad-danger-o" id="adClose">Silent close…</button>' +
          '<span class="muted">Private note + <code>silent_close</code> tag; asks twice.</span></div>');
    return '<div class="at-d">' +
      '<div class="at-dh"><div class="at-dt">' + ticketLink(r.ticket_id) + ' · ' + esc(r.subject || '(no subject)') + '</div>' +
        '<div class="muted">' + esc(when(r.created_ms)) + (r.requester ? ' · ' + esc(r.requester) : '') + (r.channel ? ' · ' + esc(r.channel) : '') + ' · ' + tstatus(z.status || r.status) + '</div></div>' +
      silent +
      '<div class="at-grid"><div class="at-box"><div class="at-k">Spark says</div><div><span class="at-b ad-b">Ad / spam</span> ' + esc(r.confidence || '') + ' confidence</div>' +
        (r.why ? '<div>' + esc(r.why) + '</div>' : '') + '<div class="muted"><a href="/settings#sparklog-' + r.ticket_id + '">What Spark read and answered</a> (admins)</div></div>' +
      '<div class="at-box"><div class="at-k">In Zendesk now</div><div>' + tstatus(z.status || r.status) + '</div>' +
        '<div class="muted ad-tags">' + (z.tags && z.tags.length ? z.tags.map(function (t) { return '<code>' + esc(t) + '</code>'; }).join(' ') : 'no tags') + '</div></div></div>' +
      '<div class="at-k">What they wrote' + (z.live ? '' : ' <span class="muted">(kept copy — Zendesk didn’t answer)</span>') + '</div>' +
      '<div class="at-sample ad-full">' + esc(z.description || r.sample || '(no text)') + '</div>' +
      '<div class="at-k">Is Spark right?</div>' +
      '<div class="frow ad-act"><button type="button" class="btn btn-sm' + (r.verdict === 'right' ? ' on-ok' : '') + '" data-v="right">✓ Right, it’s spam</button>' +
        '<button type="button" class="btn btn-sm' + (r.verdict === 'wrong' ? ' on-bad' : '') + '" data-v="wrong">✗ Wrong, it’s real</button>' +
        (r.verdict && !r.silent_ms ? '<button type="button" class="btn btn-sm btn-link" data-v="">Undo</button>' : '') + '</div>' +
      close +
      '<div class="sc-msg" id="adMsg" aria-live="polite"></div>' +
      '<div class="frow"><a class="btn btn-sm" href="' + esc(zdUrl(r.ticket_id)) + '" target="_blank" rel="noopener">Open in Zendesk</a></div></div>';
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
      P.zd = { description: t.description, tags: t.tags, status: t.status, live: t.live };
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
    if (ev.target.id === 'adClose') { P.confirm = true; draw(); return; }            // first confirmation: the box
    if (ev.target.id === 'adCancel') { P.confirm = false; draw(); return; }
    if (ev.target.id === 'adGo') {                                                   // second: ticked, then this button
      if (!$('adSure').checked) return;
      var go = ev.target; go.disabled = true; go.textContent = 'Closing…';
      post('/api/adfilter/silent-close', { ticket_id: id }).then(function (r) {
        refreshRow(r); P.confirm = false; draw(); loadStatus();
        $('adMsg').textContent = 'Done — #' + id + ' has the private note “Silent-Close” and the silent_close tag.';
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

  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (x) { ZD = x.zendesk_url || ''; if (S.rows.length) $('rows').innerHTML = S.rows.map(row).join(''); }).catch(function () {});
  loadStatus().then(load);
  setInterval(function () { if (document.visibilityState === 'visible' && $('pnWrap').hidden) { loadStatus(); load(); } }, 60000);
})();
