// SplashHub Centre -- Spark activity (Admin): every Spark decision (sparklog.py),
// newest first, with a 24-hour summary and a per-area table. A row opens a
// pop-up: the ticket on the left (fresh from Zendesk: status, tags and the whole
// conversation; a switcher when Spark read several tickets at once) and Spark's
// judgement on the right (what Centre did, its answer, its reasoning, what it
// read, the question). /sparklog#t-12345 opens on that ticket's decisions.
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  var S = { area: '', changed: '', ticket: '', page: 0, rows: [] }, ZD = '', seq = 0;
  var POP = { id: null, rec: null, tickets: [], cur: null, cache: {} };
  var TSTATUS = { new: 'New', open: 'Open', pending: 'Pending', hold: 'On-hold', solved: 'Solved', closed: 'Closed' };

  function when(ms) { var d = new Date(ms); return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }
  function secs(ms) { return ms == null ? '—' : ms < 1000 ? ms + ' ms' : (ms / 1000).toFixed(1) + ' s'; }
  function get(p) {
    return fetch(p, { credentials: 'same-origin' }).then(function (r) {
      if (r.status === 401) { location.href = '/logs?next=' + encodeURIComponent('/sparklog' + location.hash); throw new Error('login'); }
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function tstatus(st) { return st ? '<span class="tst tst-' + esc(st) + '">' + esc(TSTATUS[st] || st) + '</span>' : ''; }
  function tlinks(ts) {
    return ts.length ? ts.slice(0, 2).map(function (t) { return ZD ? '<a href="' + esc(ZD) + '/agent/tickets/' + t + '" target="_blank" rel="noopener">#' + t + '</a>' : '#' + t; }).join(' ') +
      (ts.length > 2 ? ' <span class="muted">+' + (ts.length - 2) + '</span>' : '') : '<span class="muted">—</span>';
  }

  // ---- the summary and the list -----------------------------------------------------------------
  function drawStats(st) {
    var t = function (label, value, sub, cls) {
      return '<div class="stat"><div class="stat-label">' + label + '</div><div class="stat-value ' + (cls || '') + '">' + value + '</div><div class="stat-sub">' + sub + '</div></div>';
    };
    var d = st.day;
    $('slStats').innerHTML = t('Decisions · 24 h', d.n.toLocaleString(), d.tickets.toLocaleString() + ' tickets read · ' + d.changed + ' changed something') +
      t('Average answer', secs(d.avg_ms), 'from asking to answer') + t('Slowest', secs(d.max_ms), 'in the last 24 h') +
      t('Failed', d.failed, d.failed ? 'retried on the next round' : 'none', d.failed ? 'ov-o' : '');
    $('slAreasCard').hidden = !st.areas.length;
    $('slAreas').tBodies[0].innerHTML = st.areas.map(function (a) {
      return '<tr><td>' + esc(a.label) + '</td><td class="n">' + a.n + '</td><td class="n">' + secs(a.avg_ms) + '</td><td class="n">' + (a.per_ticket_ms != null ? secs(a.per_ticket_ms) : '—') +
        '</td><td class="n">' + secs(a.max_ms) + '</td><td class="n">' + a.changed + '</td><td class="n">' + (a.failed ? '<span class="at-bad">' + a.failed + '</span>' : '0') + '</td></tr>';
    }).join('');
  }
  function load() {
    var my = ++seq, q = ['page=' + S.page];
    ['area', 'changed', 'ticket'].forEach(function (k) { if (S[k]) q.push(k + '=' + encodeURIComponent(S[k])); });
    return get('/api/spark-log?' + q.join('&')).then(function (d) {
      if (my !== seq) return;
      $('page').hidden = false;
      S.rows = d.rows;
      if (d.stats) drawStats(d.stats);
      var sel = $('slArea');
      if (sel.options.length <= 1) {
        sel.innerHTML = '<option value="">Every area</option>' + Object.keys(d.areas).map(function (k) {
          return '<option value="' + esc(k) + '">' + esc(d.areas[k]) + (d.counts[k] ? ' (' + d.counts[k] + ')' : '') + '</option>';
        }).join('');
        sel.value = S.area;
      }
      $('slCount').textContent = d.total ? d.total.toLocaleString() + (d.total === 1 ? ' decision' : ' decisions') + ' · newest first' : '';
      $('slRows').innerHTML = d.rows.length ? d.rows.map(function (r) {
        return '<tr class="sl-row' + (r.error ? ' sl-err' : '') + '" data-id="' + r.id + '" tabindex="0"><td class="when">' + esc(when(r.ts_ms)) + '</td>' +
          '<td>' + esc(r.area_label) + '</td><td>' + tlinks(r.tickets) + '</td>' +
          '<td class="sl-dec">' + (r.error ? '<span class="at-bad">Failed: ' + esc(r.error) + '</span>' : r.decision ? (r.changed ? '<b>' + esc(r.decision) + '</b>' : esc(r.decision)) : '<span class="muted">—</span>') + '</td>' +
          '<td class="r muted">' + secs(r.ms) + '</td></tr>';
      }).join('') : '<tr class="empty-row"><td colspan="5">' + (S.area || S.changed || S.ticket ? 'Nothing matches.' : 'No Spark decisions yet.') + '</td></tr>';
      var pages = Math.ceil(d.total / d.per_page);
      $('slPager').hidden = pages <= 1;
      $('slPagerTxt').textContent = 'Page ' + (d.page + 1) + ' of ' + pages;
      $('slPrev').disabled = d.page <= 0; $('slNext').disabled = d.page + 1 >= pages;
      var t = new Date(); $('stamp').textContent = 'Updated ' + String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0');
    }).catch(function (e) { if (e.message !== 'login') { $('page').hidden = false; $('slRows').innerHTML = '<tr class="empty-row"><td colspan="5">Could not load: ' + esc(e.message) + '</td></tr>'; } });
  }

  // ---- the pop-up: the ticket (left), Spark's judgement (right) ---------------------------------------
  function block(title, body, open) {
    return '<details class="sl-part"' + (open ? ' open' : '') + '><summary>' + title + '</summary><pre class="sl-pre">' + esc(body || '') + '</pre></details>';
  }
  function right(r) {
    return '<div class="sl-rh"><div class="sl-k">Spark&rsquo;s judgement</div><div class="muted">' + esc(r.area_label) + ' · ' + esc(when(r.ts_ms)) + '</div></div>' +
      (r.error ? '<div class="sl-verdict bad">Failed: ' + esc(r.error) + '</div>' : r.decision ? '<div class="sl-verdict' + (r.changed ? ' changed' : '') + '"><div class="sl-k">What Centre did</div>' + esc(r.decision) + '</div>' : '') +
      '<div class="sl-facts"><span>took <b>' + secs(r.ms) + '</b></span>' +
        (r.n_tickets > 1 ? '<span>' + r.n_tickets + ' tickets · ' + secs(Math.round(r.ms / r.n_tickets)) + ' each</span>' : '') +
        (r.tokens_in ? '<span>read ' + r.tokens_in.toLocaleString() + ' tokens · wrote ' + (r.tokens_out || 0).toLocaleString() + '</span>' : '') +
        (r.model ? '<span>' + esc(r.model) + '</span>' : '') + '</div>' +
      block('Spark&rsquo;s answer', r.answer, true) +
      (r.thinking ? block('How it was thinking', r.thinking, true)
        : '<div class="sl-note">No reasoning kept &mdash; thinking is off in <a href="/settings#spark">Settings &rsaquo; Spark</a>. The short reason inside the answer is what it gave.</div>') +
      block('What it read', r.input, false) + block('The question it was asked', r.question, false);
  }
  function msgs(c) {
    var LBL = { customer: 'Customer', agent: 'Agent', note: 'Internal note' };
    return '<div class="ad-convo sl-convo">' + c.map(function (m) {
      return '<div class="ad-msg ad-' + esc(m.kind) + '"><div class="ad-mh"><b>' + esc(LBL[m.kind] || m.kind) + '</b>' + (m.who ? ' · ' + esc(m.who) : '') +
        (m.ms ? ' <span class="muted">· ' + esc(when(m.ms)) + '</span>' : '') + '</div><div class="ad-mb">' + esc(m.text || '') + '</div></div>';
    }).join('') + '</div>';
  }
  function left() {
    var r = POP.rec, ts = POP.tickets;
    if (!ts.length) {
      return '<div class="sl-k">No ticket</div><div class="muted">This decision isn&rsquo;t about one ticket (' + esc(r.area_label) + '). What Spark read:</div>' +
        '<pre class="sl-pre sl-tall">' + esc(r.input || '') + '</pre>';
    }
    var sw = ts.length > 1 ? '<div class="chips sl-sw" role="group" aria-label="Tickets in this decision">' + ts.map(function (t) {
      return '<button type="button" class="chip' + (t === POP.cur ? ' active' : '') + '" data-t="' + t + '">#' + t + '</button>';
    }).join('') + '</div>' : '';
    var t = POP.cache[POP.cur];
    var body = !t ? '<div class="pn-loading">Loading ticket #' + POP.cur + '…</div>'
      : t.error ? '<div class="sl-note">Couldn&rsquo;t read ticket #' + POP.cur + ' from Zendesk: ' + esc(t.error) + '</div>'
      : '<div class="sl-th"><div class="sl-tt">' + (ZD ? '<a href="' + esc(ZD) + '/agent/tickets/' + t.id + '" target="_blank" rel="noopener">#' + t.id + '</a>' : '#' + t.id) +
          ' · ' + esc(t.subject || '(no subject)') + '</div>' +
          '<div class="muted">' + tstatus(t.status) + (t.requester ? ' ' + esc(t.requester) : '') + '</div>' +
          (t.tags && t.tags.length ? '<div class="ad-tags muted">' + t.tags.map(function (g) { return '<code>' + esc(g) + '</code>'; }).join(' ') + '</div>' : '') + '</div>' +
        '<div class="sl-k">The whole ticket <span class="muted">(' + t.conversation.length + (t.conversation.length === 1 ? ' message' : ' messages') + ', oldest first)</span></div>' +
        msgs(t.conversation);
    return sw + body;
  }
  function showTicket(id) {
    POP.cur = id; $('slLeft').innerHTML = left();
    if (POP.cache[id]) return;
    get('/api/ticket-preview/' + id).then(function (t) { POP.cache[id] = t; if (t.zendesk_url) ZD = t.zendesk_url; })
      .catch(function (e) { POP.cache[id] = { error: e.message }; })
      .then(function () { if (POP.cur === id && !$('slOv').hidden) $('slLeft').innerHTML = left(); });
  }
  function openPop(id) {
    var i = S.rows.map(function (x) { return x.id; }).indexOf(id);
    POP.id = id; POP.rec = null;
    $('slOv').hidden = false; document.body.classList.add('pn-lock');
    $('slPos').textContent = i >= 0 ? (i + 1) + ' of ' + S.rows.length + ' on this page' : '';
    $('slLeft').innerHTML = '<div class="pn-loading">Loading…</div>'; $('slRight').innerHTML = '';
    $('slPop').focus();
    get('/api/spark-log/' + id).then(function (r) {
      if (POP.id !== id) return;
      POP.rec = r;
      POP.tickets = (r.tickets || []).map(Number);
      var want = Number(S.ticket) || 0;
      $('slRight').innerHTML = right(r);
      if (POP.tickets.length) showTicket(POP.tickets.indexOf(want) >= 0 ? want : POP.tickets[0]);
      else $('slLeft').innerHTML = left();
    }).catch(function (e) { if (e.message !== 'login') $('slRight').innerHTML = '<div class="sl-note">Could not load: ' + esc(e.message) + '</div>'; });
  }
  function closePop() { POP.id = null; $('slOv').hidden = true; document.body.classList.remove('pn-lock'); }
  function step(d) {
    var ids = S.rows.map(function (x) { return x.id; }), i = ids.indexOf(POP.id);
    if (ids[i + d] != null) openPop(ids[i + d]);
  }

  // ---- controls --------------------------------------------------------------------------------------
  $('slRows').addEventListener('click', function (ev) {
    if (ev.target.closest('a')) return;
    var tr = ev.target.closest('.sl-row'); if (tr) openPop(+tr.getAttribute('data-id'));
  });
  $('slRows').addEventListener('keydown', function (ev) { var tr = ev.target.closest('.sl-row'); if (tr && ev.key === 'Enter') openPop(+tr.getAttribute('data-id')); });
  $('slLeft').addEventListener('click', function (ev) { var b = ev.target.closest('[data-t]'); if (b) showTicket(+b.getAttribute('data-t')); });
  $('slX').addEventListener('click', closePop);
  $('slUp').addEventListener('click', function () { step(-1); });
  $('slDown').addEventListener('click', function () { step(1); });
  $('slOv').addEventListener('click', function (ev) { if (ev.target === this) closePop(); });
  document.addEventListener('keydown', function (ev) {
    if ($('slOv').hidden) return;
    if (ev.key === 'Escape') closePop();
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); step(-1); }
    else if (ev.key === 'ArrowDown') { ev.preventDefault(); step(1); }
  });
  $('slArea').addEventListener('change', function () { S.area = this.value; S.page = 0; load(); });
  $('slChanged').addEventListener('change', function () { S.changed = this.value; S.page = 0; load(); });
  var tT = 0;
  $('slTicket').addEventListener('input', function () { clearTimeout(tT); var v = this.value.replace(/\D/g, ''); tT = setTimeout(function () { S.ticket = v; S.page = 0; load(); }, 300); });
  $('slPrev').addEventListener('click', function () { if (S.page > 0) { S.page--; load(); } });
  $('slNext').addEventListener('click', function () { S.page++; load(); });
  $('refresh').addEventListener('click', load);
  function fromHash() {
    var m = /^#t-(\d+)/.exec(location.hash || '');
    S.ticket = m ? m[1] : ''; $('slTicket').value = S.ticket; S.page = 0;
  }
  window.addEventListener('hashchange', function () { fromHash(); load(); });

  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; }).then(function (x) { ZD = x.zendesk_url || ZD; }).catch(function () {});
  fromHash();
  load();
  setInterval(function () { if (document.visibilityState === 'visible' && $('slOv').hidden) load(); }, 60000);
})();
