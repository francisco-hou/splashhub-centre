// SplashHub Centre -- PO Requests page.
//
// Every Zendesk ticket with a "Provision Details" order, all years (po.py):
// the headline numbers (open, due this week, overdue), a filterable list, and
// a pop-up per order with its products, every order field, and links to the
// ticket and to the customer's page.
(function () {
  'use strict';

  var S = { q: '', status: '', region: '', when: '', year: '', page: 0, rows: [], open: null };
  var seq = 0;           // the newest list request; an older answer is dropped
  var ZD = '';
  var OPEN = { new: 1, open: 1, pending: 1, hold: 1 };
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
    return d < 1 ? 'today' : d < 2 ? 'yesterday' : Math.round(d) + ' days ago';
  }
  function today() { return new Date().toISOString().slice(0, 10); }
  function api(path) {
    return fetch(path, { credentials: 'same-origin' }).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function tstatus(st) { return st ? '<span class="tst tst-' + esc(st) + '">' + esc(st.charAt(0).toUpperCase() + st.slice(1)) + '</span>' : ''; }
  function zd(id) { return ZD ? '<a href="' + esc(ZD) + '/agent/tickets/' + id + '" target="_blank" rel="noopener">#' + id + '</a>' : '#' + id; }
  function overdue(r) { return r.expected && r.expected < today() && OPEN[r.status]; }
  function expected(r) {
    if (!r.expected) return '<span class="muted">&mdash;</span>';
    return '<span class="' + (overdue(r) ? 'po-over' : r.expected >= today() && OPEN[r.status] ? 'po-soon' : '') + '">' + esc(r.expected) + '</span>';
  }

  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (x) { ZD = x.zendesk_url || ''; }).catch(function () {});
  $('page').hidden = false;
  var m = /^#(\d+)$/.exec(location.hash);
  if (m) S.open = +m[1];
  overview();
  load();

  function overview() {
    api('/api/po/overview').then(function (o) {
      $('empty').hidden = o.total > 0;
      var stat = function (label, value, sub, cls) {
        return '<div class="stat"><div class="stat-label">' + label + '</div><div class="stat-value ' + (cls || '') + '">' + value + '</div><div class="stat-sub">' + sub + '</div></div>';
      };
      $('stats').innerHTML =
        stat('Open', int(o.open), int(o.total) + ' in all') +
        stat('Due in 7 days', int(o.due_week), 'expected provision date, still open') +
        stat('Overdue', int(o.overdue), 'date passed, ticket still open', o.overdue ? 'cu-warn' : '') +
        stat('Last 30 days', int(o.last_30d), o.regions.map(function (r) { return esc(r.region) + ' ' + int(r.n); }).join(' &middot; ') || '&nbsp;');
      var cur = S.year;
      $('year').innerHTML = '<option value="">All years</option>' + o.years.map(function (y) {
        return '<option value="' + esc(y.year) + '"' + (y.year === cur ? ' selected' : '') + '>' + esc(y.year) + ' (' + int(y.n) + ')</option>';
      }).join('');
      $('stamp').textContent = o.synced_ms ? 'Updated ' + ago(o.synced_ms) : '';
    }).catch(function (e) { $('stamp').textContent = 'Could not load: ' + e.message; });
  }

  function load() {
    var my = ++seq;
    var p = ['page=' + S.page];
    ['q', 'status', 'region', 'when', 'year'].forEach(function (k) { if (S[k]) p.push(k + '=' + encodeURIComponent(S[k])); });
    api('/api/po/search?' + p.join('&')).then(function (d) {
      if (my !== seq) return;
      S.rows = d.rows;
      $('count').textContent = int(d.total) + (d.total === 1 ? ' order' : ' orders');
      $('rows').innerHTML = d.rows.length ? d.rows.map(row).join('')
        : '<tr class="empty-row"><td colspan="8">' + (S.q || S.status || S.region || S.when || S.year ? 'No orders match.' : 'No PO requests yet.') + '</td></tr>';
      var pages = Math.ceil(d.total / d.per_page);
      $('pager').hidden = pages <= 1;
      $('pagerTxt').textContent = 'Page ' + (d.page + 1) + ' of ' + pages;
      $('prev').disabled = d.page <= 0;
      $('next').disabled = d.page + 1 >= pages;
      if (S.open) { var id = S.open; S.open = null; openPanel(id); }
    }).catch(function (e) { $('rows').innerHTML = '<tr class="empty-row"><td colspan="8">Could not load: ' + esc(e.message) + '</td></tr>'; });
  }

  function who(r) {
    var main = r.company || r.spid || r.customer_domain || '';
    var sub = r.company && r.spid ? r.spid : '';
    return '<span class="po-who"><b>' + esc(main || '—') + '</b>' + (sub ? '<span class="muted">' + esc(sub) + '</span>' : '') + '</span>';
  }
  function prods(r) {
    if (!r.products.length) return '<span class="muted">&mdash;</span>';
    var p = r.products[0];
    return '<span class="po-prod" title="' + esc(r.products.map(function (x) { return x.name + (x.qty ? ' × ' + x.qty : ''); }).join('\n')) + '">' +
      esc(p.name) + (p.qty ? ' <b>&times; ' + esc(p.qty) + '</b>' : '') + (r.products.length > 1 ? ' <span class="muted">+' + (r.products.length - 1) + '</span>' : '') + '</span>';
  }
  function row(r) {
    return '<tr class="po-row' + (overdue(r) ? ' po-row-over' : '') + '" data-id="' + r.ticket_id + '" tabindex="0">' +
      '<td class="when">' + esc(day(r.created_ms)) + '</td><td>#' + r.ticket_id + '</td><td>' + who(r) + '</td>' +
      '<td class="po-prod-c">' + prods(r) + '</td><td>' + esc(r.order_type || '') + '</td><td>' + expected(r) + '</td>' +
      '<td><span class="po-reg po-reg-' + esc((r.region || '').toLowerCase().replace(/[^a-z]/g, '')) + '">' + esc(r.region || '') + '</span></td><td>' + tstatus(r.status) + '</td></tr>';
  }

  // ---- one order ---------------------------------------------------------------------------
  var CUR = null;
  function openPanel(id) {
    CUR = id;
    $('pnWrap').hidden = false;
    document.body.classList.add('pn-lock');
    history.replaceState(null, '', '#' + id);
    var i = S.rows.findIndex(function (r) { return r.ticket_id === id; });
    $('pnPos').textContent = i >= 0 ? (i + 1) + ' of ' + S.rows.length + ' on this page' : '';
    $('detail').innerHTML = '<div class="pn-loading">Loading…</div>';
    $('panel').focus();
    api('/api/po/' + id).then(function (r) { if (CUR === id) $('detail').innerHTML = detail(r); })
      .catch(function (e) { $('detail').innerHTML = '<div class="pn-loading"><div class="sc-err">Could not load: ' + esc(e.message) + '</div></div>'; });
  }
  function closePanel() {
    CUR = null; $('pnWrap').hidden = true; document.body.classList.remove('pn-lock');
    history.replaceState(null, '', location.pathname);
  }
  function step(d) {
    var i = S.rows.findIndex(function (r) { return r.ticket_id === CUR; });
    var n = S.rows[i + d];
    if (n) openPanel(n.ticket_id);
  }
  function detail(r) {
    var links = [];
    if (ZD) links.push('<a class="btn btn-primary btn-sm" href="' + esc(ZD) + '/agent/tickets/' + r.ticket_id + '" target="_blank" rel="noopener">Open ticket #' + r.ticket_id + ' ' + OUT + '</a>');
    if (r.customer_domain) links.push('<a class="btn btn-sm" href="/customers#domain:' + encodeURIComponent(r.customer_domain) + '">Customer page: ' + esc(r.customer_domain) + '</a>');
    var fact = function (label, value) { return '<div class="kb-stat"><span>' + label + '</span><b class="po-fact">' + (value || '&mdash;') + '</b></div>'; };
    var h = '<div class="kb-head"><div class="kb-crumb">PO request &middot; ' + tstatus(r.status) + '</div>' +
      '<h2 class="kb-h">' + esc(r.company || r.spid || r.subject || ('#' + r.ticket_id)) + '</h2>' +
      (r.company && r.spid ? '<div class="kb-crumb">' + esc(r.spid) + '</div>' : '') +
      '<div class="cu-links">' + links.join('') + '</div></div>';
    h += '<div class="kb-stats-row">' + fact('Order type', esc(r.order_type)) + fact('Expected provision', expected(r)) +
      fact('Region', esc(r.region)) + fact('Created', esc(day(r.created_ms))) + '</div>';
    h += '<section class="pn-sec"><div class="pn-h">Products <span class="count">' + r.products.length + '</span></div>' +
      (r.products.length ? '<table class="runs po-prods"><thead><tr><th>Product</th><th class="r">Quantity</th><th class="r">Additional</th><th>Start</th><th>End</th></tr></thead><tbody>' +
        r.products.map(function (p) {
          return '<tr><td>' + esc(p['Product Name']) + '</td><td class="n">' + esc(p['Quantity'] || '') + '</td><td class="n">' + esc(p['Additional Quantity'] || '') + '</td>' +
            '<td>' + esc(p['Provision Start Date'] || '') + '</td><td>' + esc(p['Provision End Date'] || '') + '</td></tr>';
        }).join('') + '</tbody></table>' : '<div class="muted">No products listed.</div>') + '</section>';
    var keys = Object.keys(r.order || {});
    if (keys.length) {
      h += '<section class="pn-sec"><div class="pn-h">Order details</div><dl class="po-dl">' + keys.map(function (k) {
        return '<dt>' + esc(k) + '</dt><dd>' + esc(r.order[k]).replace(/\n/g, '<br>') + '</dd>';
      }).join('') + '</dl></section>';
    }
    h += '<div class="pn-foot">Ticket #' + r.ticket_id + ' &middot; ' + esc(r.subject || '') + ' &middot; updated ' + esc(day(r.updated_ms)) + '</div>';
    return '<div class="pn-main kb-pop">' + h + '</div>';
  }

  // ---- events -------------------------------------------------------------------------------
  var qT = null;
  $('q').addEventListener('input', function () { clearTimeout(qT); qT = setTimeout(function () { S.q = $('q').value.trim(); S.page = 0; load(); }, 250); });
  $('region').addEventListener('change', function () { S.region = this.value; S.page = 0; load(); });
  $('year').addEventListener('change', function () { S.year = this.value; S.page = 0; load(); });
  function chips(id, key) {
    $(id).addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-v]'); if (!b) return;
      S[key] = b.getAttribute('data-v'); S.page = 0;
      Array.prototype.forEach.call(this.children, function (c) { c.classList.toggle('active', c === b); });
      load();
    });
  }
  chips('statusChips', 'status');
  chips('whenChips', 'when');
  $('prev').addEventListener('click', function () { if (S.page > 0) { S.page--; load(); } });
  $('next').addEventListener('click', function () { S.page++; load(); });
  $('refresh').addEventListener('click', function () { overview(); load(); });
  $('rows').addEventListener('click', function (ev) { var r = ev.target.closest('.po-row'); if (r) openPanel(+r.getAttribute('data-id')); });
  $('rows').addEventListener('keydown', function (ev) { var r = ev.target.closest('.po-row'); if (r && ev.key === 'Enter') openPanel(+r.getAttribute('data-id')); });
  $('pnClose').addEventListener('click', closePanel);
  $('pnPrev').addEventListener('click', function () { step(-1); });
  $('pnNext').addEventListener('click', function () { step(1); });
  $('pnWrap').addEventListener('click', function (ev) { if (ev.target === this) closePanel(); });
  document.addEventListener('keydown', function (ev) {
    if ($('pnWrap').hidden) return;
    if (ev.key === 'Escape') closePanel();
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); step(-1); }
    else if (ev.key === 'ArrowDown') { ev.preventDefault(); step(1); }
  });
})();
