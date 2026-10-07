// SplashHub Centre -- Ad filter (adfilter.py): the tickets Spark thinks are
// marketing or spam, held here to be checked. Open tasks first (not solved or
// closed), then Solved / closed and the ones marked wrong. Right / Wrong per
// ticket; a click on the subject shows what the sender wrote. Nothing here
// changes Zendesk (silently closing them comes later, once it's reliable).
(function () {
  'use strict';

  var S = { view: 'open', q: '', page: 0, rows: [], openRow: null };
  var ST = null, ZD = '';
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
  function ticketLink(id) { return ZD ? '<a href="' + esc(ZD) + '/agent/tickets/' + id + '" target="_blank" rel="noopener">#' + id + '</a>' : '#' + id; }

  function loadStatus() {
    return api('/api/adfilter').then(function (s) {
      ST = s;
      var n = $('note');
      if (!s.on) { n.hidden = false; n.innerHTML = 'The Ad filter is <b>off</b>. An admin can switch it on in <b>Settings &rsaquo; AutoTag</b>.'; }
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
        tile('Checked by the team', checked ? Math.round(100 * s.right / checked) + '% right' : '—', int(s.right) + ' right · ' + int(s.wrong) + ' wrong');
      [].forEach.call($('adview').children, function (c) {
        var k = c.getAttribute('data-v'), n = k === 'open' ? s.open_ads : k === 'done' ? s.done_ads : s.wrong;
        var lbl = c.textContent.replace(/\s*\d+$/, '');
        c.innerHTML = esc(lbl) + ' <span class="chip-n">' + int(n) + '</span>';
      });
    }).catch(function (e) { $('note').hidden = false; $('note').textContent = 'Could not load the Ad filter: ' + e.message; });
  }

  function checkCell(r) {
    return '<div class="ad-chk"><button type="button" class="btn btn-sm' + (r.verdict === 'right' ? ' on-ok' : '') + '" data-v="right" data-id="' + r.ticket_id + '" title="Yes, it is an ad / spam">✓ Right</button>' +
      '<button type="button" class="btn btn-sm' + (r.verdict === 'wrong' ? ' on-bad' : '') + '" data-v="wrong" data-id="' + r.ticket_id + '" title="No, it is a real request">✗ Wrong</button>' +
      (r.verdict ? '<button type="button" class="btn btn-sm btn-link" data-v="" data-id="' + r.ticket_id + '">Undo</button>' : '') + '</div>';
  }
  function row(r) {
    var open = S.openRow === r.ticket_id;
    return '<tr class="ad-row' + (open ? ' open' : '') + '" data-id="' + r.ticket_id + '"><td class="when">' + esc(when(r.created_ms)) + '</td>' +
      '<td>' + ticketLink(r.ticket_id) + '</td><td>' + tstatus(r.status) + '</td>' +
      '<td class="ad-subj"><button type="button" class="link-btn ad-open" aria-expanded="' + open + '">' + esc(r.subject || '(no subject)') + '</button>' +
        '<div class="muted">' + esc(r.requester || '') + '</div></td>' +
      '<td><span class="at-b ad-b">Ad / spam</span>' + (r.confidence && r.confidence !== 'high' ? ' <span class="at-conf at-' + esc(r.confidence) + '">' + esc(r.confidence) + '</span>' : '') +
        (r.why ? '<div class="muted">' + esc(r.why) + '</div>' : '') + '</td>' +
      '<td>' + checkCell(r) + '</td></tr>' +
      (open ? '<tr class="ad-more"><td colspan="6"><div class="at-k">What they wrote</div><div class="at-sample">' + esc(r.sample || '(no text)') + '</div>' +
        '<div class="muted"><a href="/settings#sparklog-' + r.ticket_id + '">See what Spark read and answered</a> (admins)</div></td></tr>' : '');
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

  $('rows').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-v]');
    if (b) {
      b.disabled = true;
      post('/api/adfilter/verdict', { ticket_id: +b.getAttribute('data-id'), verdict: b.getAttribute('data-v') })
        .then(function () { loadStatus(); load(); })
        .catch(function (e) { b.disabled = false; $('note').hidden = false; $('note').textContent = 'Could not save: ' + e.message; });
      return;
    }
    if (ev.target.closest('.ad-open')) {
      var id = +ev.target.closest('.ad-row').getAttribute('data-id');
      S.openRow = S.openRow === id ? null : id;
      $('rows').innerHTML = S.rows.map(row).join('');
    }
  });
  $('adview').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-v]'); if (!b) return;
    S.view = b.getAttribute('data-v'); S.page = 0; S.openRow = null;
    [].forEach.call(this.children, function (c) { c.classList.toggle('active', c === b); });
    load();
  });
  var qT = 0;
  $('q').addEventListener('input', function () { clearTimeout(qT); qT = setTimeout(function () { S.q = $('q').value.trim(); S.page = 0; load(); }, 250); });
  $('prev').addEventListener('click', function () { if (S.page > 0) { S.page--; load(); } });
  $('next').addEventListener('click', function () { S.page++; load(); });
  $('refresh').addEventListener('click', function () { loadStatus(); load(); });

  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (x) { ZD = x.zendesk_url || ''; if (S.rows.length) $('rows').innerHTML = S.rows.map(row).join(''); }).catch(function () {});
  loadStatus().then(load);
  setInterval(function () { if (document.visibilityState === 'visible') { loadStatus(); load(); } }, 60000);
})();
