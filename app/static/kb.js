// SplashHub Centre -- Knowledge Base page.
//
// The Zendesk Help Center's articles as SplashHub Centre keeps them (kb.py):
// search, filter by language / category / flags, sort by how they're doing,
// and a pop-up per article with its stats -- helpful votes, languages (and
// which translations are outdated), the 2026 tickets that link it, by month --
// and its text, with a link to the article in the Help Center.
(function () {
  'use strict';

  var S = { q: '', locale: '', category: '', sort: '', flag: '', page: 0, rows: [], open: null };
  var ZD = '';
  var ICON_OUT = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>';
  var UP = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 10v12"/><path d="M15 5.9 14 10h5.8a2 2 0 0 1 2 2.3l-1.4 8a2 2 0 0 1-2 1.7H7V10l4-8a3 3 0 0 1 4 3.9z"/></svg>';
  var DOWN = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 14V2"/><path d="M9 18.1 10 14H4.2a2 2 0 0 1-2-2.3l1.4-8A2 2 0 0 1 5.6 2H17v12l-4 8a3 3 0 0 1-4-3.9z"/></svg>';

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
    return d < 1 ? 'today' : d < 2 ? 'yesterday' : d < 60 ? Math.round(d) + ' days ago' : d < 730 ? Math.round(d / 30) + ' months ago' : Math.round(d / 365) + ' years ago';
  }
  function api(path) {
    return fetch(path, { credentials: 'same-origin' }).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }

  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (x) { ZD = x.zendesk_url || ''; }).catch(function () {});

  // ---- boot ----------------------------------------------------------------------------
  $('page').hidden = false;
  var m = /^#(\d+)$/.exec(location.hash);
  if (m) S.open = +m[1];
  loadMeta(true);

  // ---- languages, categories and the headline numbers ---------------------------------
  function loadMeta(first) {
    return api('/api/kb/meta' + (S.locale ? '?locale=' + encodeURIComponent(S.locale) : '')).then(function (d) {
      $('empty').hidden = !!d.kpis.articles || d.languages.length > 0;
      S.locale = d.locale;
      $('locale').innerHTML = d.languages.length
        ? d.languages.map(function (l) { return '<option value="' + esc(l.locale) + '"' + (l.locale === d.locale ? ' selected' : '') + '>' + esc(l.locale) + ' (' + int(l.n) + ')</option>'; }).join('')
        : '<option value="">No languages yet</option>';
      var cur = S.category;
      $('category').innerHTML = '<option value="">All categories</option>' + d.categories.map(function (c) {
        return '<option value="' + esc(c.name) + '"' + (c.name === cur ? ' selected' : '') + '>' + esc(c.name || '(none)') + ' (' + int(c.n) + ')</option>';
      }).join('');
      drawStats(d);
      $('stamp').textContent = d.synced_ms ? 'Synced ' + ago(d.synced_ms) : '';
      load();
    }).catch(function (e) { $('stamp').textContent = 'Could not load: ' + e.message; });
  }

  function drawStats(d) {
    var k = d.kpis;
    var stat = function (label, value, sub) {
      return '<div class="stat"><div class="stat-label">' + label + '</div><div class="stat-value">' + value + '</div><div class="stat-sub">' + sub + '</div></div>';
    };
    $('stats').innerHTML =
      stat('Articles', int(k.articles), esc(d.locale) + ' &middot; ' + int(k.drafts) + ' draft' + (k.drafts === 1 ? '' : 's') + ', ' + int(k.agents_only) + ' agents only') +
      stat('Updated, 30 days', int(k.updated_30d), k.articles ? Math.round(100 * k.updated_30d / k.articles) + '% of them' : '&nbsp;') +
      stat('Linked in tickets', int(k.linked_articles), d.tickets_ready ? int(k.ticket_links) + ' ticket link' + (k.ticket_links === 1 ? '' : 's') + ' in 2026' : 'once Zendesk Tickets are downloaded') +
      stat('Outdated translations', int(k.outdated), k.outdated ? 'in ' + int(k.outdated_articles) + ' article' + (k.outdated_articles === 1 ? '' : 's') + ', all languages' : 'all languages up to date');
  }

  // ---- the list -----------------------------------------------------------------------
  var seq = 0;
  function load() {
    var my = ++seq;
    var p = ['locale=' + encodeURIComponent(S.locale || ''), 'page=' + S.page];
    if (S.q) p.push('q=' + encodeURIComponent(S.q));
    if (S.category) p.push('category=' + encodeURIComponent(S.category));
    if (S.sort) p.push('sort=' + encodeURIComponent(S.sort));
    if (S.flag) p.push('flag=' + encodeURIComponent(S.flag));
    api('/api/kb/search?' + p.join('&')).then(function (d) {
      if (my !== seq) return;
      S.rows = d.rows;
      $('count').textContent = int(d.total) + (d.total === 1 ? ' article' : ' articles');
      $('rows').innerHTML = d.rows.length ? d.rows.map(row).join('')
        : '<tr class="empty-row"><td colspan="4">' + (S.q || S.category || S.flag ? 'No articles match.' : 'No articles yet.') + '</td></tr>';
      var pages = Math.ceil(d.total / d.per_page);
      $('pager').hidden = pages <= 1;
      $('pagerTxt').textContent = 'Page ' + (d.page + 1) + ' of ' + pages;
      $('prev').disabled = d.page <= 0;
      $('next').disabled = d.page + 1 >= pages;
      if (S.open) { var id = S.open; S.open = null; openPanel(id); }
    }).catch(function (e) { $('rows').innerHTML = '<tr class="empty-row"><td colspan="4">Could not load: ' + esc(e.message) + '</td></tr>'; });
  }

  function flags(r) {
    return (r.promoted ? '<span class="kb-flag kb-promoted">Promoted</span>' : '') +
      (r.outdated ? '<span class="kb-flag kb-outdated">Outdated</span>' : '') +
      (r.internal ? '<span class="kb-flag kb-internal">Agents only</span>' : '') +
      (r.draft ? '<span class="kb-flag kb-draft">Draft</span>' : '');
  }
  function helpful(r) {
    if (!r.up && !r.down) return '<span class="muted">no votes</span>';
    return '<span class="kb-votes"><span class="kb-up">' + UP + int(r.up) + '</span><span class="kb-down">' + DOWN + int(r.down) + '</span>' +
      (r.helpful != null ? '<b class="' + (r.helpful < 50 ? 'kb-low' : '') + '">' + r.helpful + '%</b>' : '') + '</span>';
  }
  function row(r) {
    return '<tr class="kb-row" data-id="' + r.id + '" tabindex="0">' +
      '<td class="kb-title"><span class="kb-t">' + esc(r.title) + '</span>' + flags(r) +
        '<span class="kb-where">' + esc([r.category, r.section].filter(Boolean).join(' › ')) + '</span></td>' +
      '<td class="n">' + helpful(r) + '</td>' +
      '<td class="n">' + (r.linked ? '<b>' + int(r.linked) + '</b>' : '<span class="muted">0</span>') + '</td>' +
      '<td class="when" title="' + esc(day(r.updated_ms)) + '">' + esc(ago(r.updated_ms)) + '</td></tr>';
  }

  // ---- one article ----------------------------------------------------------------------
  var CUR = null;
  function openPanel(id) {
    CUR = id;
    $('pnWrap').hidden = false;
    document.body.classList.add('pn-lock');
    history.replaceState(null, '', '#' + id);
    var i = S.rows.findIndex(function (r) { return r.id === id; });
    $('pnPos').textContent = i >= 0 ? (i + 1) + ' of ' + S.rows.length + ' on this page' : '';
    $('detail').innerHTML = '<div class="pn-loading">Loading…</div>';
    $('panel').focus();
    api('/api/kb/article/' + id + '?locale=' + encodeURIComponent(S.locale || '')).then(function (a) {
      if (CUR !== id) return;
      $('detail').innerHTML = detail(a);
    }).catch(function (e) { $('detail').innerHTML = '<div class="pn-loading"><div class="sc-err">Could not load this article: ' + esc(e.message) + '</div></div>'; });
  }
  function closePanel() {
    CUR = null;
    $('pnWrap').hidden = true;
    document.body.classList.remove('pn-lock');
    history.replaceState(null, '', location.pathname);
  }
  function step(d) {
    var i = S.rows.findIndex(function (r) { return r.id === CUR; });
    var n = S.rows[i + d];
    if (n) openPanel(n.id);
  }

  function bars(months) {
    if (!months.length) return '';
    var max = Math.max.apply(null, months.map(function (m) { return m.n; }));
    return '<div class="kb-months">' + months.map(function (m) {
      return '<div class="kb-month" title="' + esc(m.month) + ': ' + m.n + '"><i style="height:' + Math.max(6, Math.round(100 * m.n / max)) + '%"></i><span>' + esc(m.month.slice(5)) + '</span></div>';
    }).join('') + '</div>';
  }
  function body(text) {
    // the article text as kb.py keeps it: '#' headings, '- ' list items, paragraphs
    return String(text || '').split(/\n{2,}/).map(function (para) {
      var lines = para.split('\n');
      if (lines.every(function (l) { return /^- /.test(l); })) return '<ul>' + lines.map(function (l) { return '<li>' + esc(l.slice(2)) + '</li>'; }).join('') + '</ul>';
      var h = /^(#{1,4}) (.*)$/.exec(lines[0]);
      if (h && lines.length === 1) return '<h4>' + esc(h[2]) + '</h4>';
      return '<p>' + lines.map(function (l) { return /^- /.test(l) ? '• ' + esc(l.slice(2)) : esc(l.replace(/^#{1,4} /, '')); }).join('<br>') + '</p>';
    }).join('');
  }
  function detail(a) {
    var stat = function (label, value, sub) {
      return '<div class="kb-stat"><span>' + label + '</span><b>' + value + '</b>' + (sub ? '<small>' + sub + '</small>' : '') + '</div>';
    };
    var h = '<div class="kb-head"><div class="kb-crumb">' + esc([a.category, a.section].filter(Boolean).join(' › ')) + '</div>' +
      '<h2 class="kb-h">' + esc(a.title) + '</h2><div class="kb-flags">' + flags(a) + '</div>' +
      (a.url ? '<a class="btn btn-primary kb-open" href="' + esc(a.url) + '" target="_blank" rel="noopener">Open in the Help Center ' + ICON_OUT + '</a>' : '') + '</div>';
    h += '<div class="kb-stats-row">' +
      stat('Helpful', a.helpful != null ? a.helpful + '%' : '&mdash;', int(a.up) + ' yes &middot; ' + int(a.down) + ' no') +
      stat('Linked in tickets', int(a.linked), '2026 tickets whose replies link it') +
      stat('Updated', esc(ago(a.updated_ms)), esc(day(a.updated_ms))) +
      stat('Created', esc(day(a.created_ms)), 'article ' + a.id) + '</div>';
    if (a.linked_by_month && a.linked_by_month.length) {
      h += '<section class="pn-sec"><div class="pn-h">Linked in tickets, by month</div>' + bars(a.linked_by_month) + '</section>';
    }
    if (a.tickets && a.tickets.length) {
      h += '<section class="pn-sec"><div class="pn-h">Latest tickets that link it</div><div class="kb-tickets">' + a.tickets.map(function (t) {
        return ZD ? '<a href="' + esc(ZD) + '/agent/tickets/' + t.ticket + '" target="_blank" rel="noopener">#' + t.ticket + '</a>' : '<span>#' + t.ticket + '</span>';
      }).join('') + '</div></section>';
    }
    if (a.languages && a.languages.length) {
      h += '<section class="pn-sec"><div class="pn-h">Languages <span class="count">' + a.languages.length + '</span></div><div class="kb-langs">' + a.languages.map(function (l) {
        return '<a class="kb-lang' + (l.outdated ? ' out' : '') + '" href="' + esc(l.url || '#') + '" target="_blank" rel="noopener" title="' + esc(l.title) + (l.outdated ? ' -- outdated' : '') + '">' +
          esc(l.locale) + (l.locale === a.source_locale ? ' <i>source</i>' : '') + (l.outdated ? ' <i>outdated</i>' : '') + '</a>';
      }).join('') + '</div></section>';
    }
    if (a.labels) h += '<section class="pn-sec"><div class="pn-h">Labels</div><div class="kb-labels">' + a.labels.split(/\s*,\s*/).filter(Boolean).map(function (l) { return '<span>' + esc(l) + '</span>'; }).join('') + '</div></section>';
    h += '<section class="pn-sec"><div class="pn-h">Article</div><div class="kb-body">' + (body(a.body) || '<span class="muted">No text.</span>') + '</div></section>';
    return '<div class="pn-main kb-pop">' + h + '</div>';
  }

  // ---- events -------------------------------------------------------------------------
  var qT = null;
  $('q').addEventListener('input', function () {
    clearTimeout(qT);
    qT = setTimeout(function () { S.q = $('q').value.trim(); S.page = 0; load(); }, 250);
  });
  $('locale').addEventListener('change', function () { S.locale = this.value; S.category = ''; S.page = 0; loadMeta(); });
  $('category').addEventListener('change', function () { S.category = this.value; S.page = 0; load(); });
  $('sort').addEventListener('change', function () { S.sort = this.value; S.page = 0; load(); });
  $('flags').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-flag]'); if (!b) return;
    S.flag = b.getAttribute('data-flag'); S.page = 0;
    Array.prototype.forEach.call(this.children, function (c) { c.classList.toggle('active', c === b); });
    load();
  });
  $('prev').addEventListener('click', function () { if (S.page > 0) { S.page--; load(); } });
  $('next').addEventListener('click', function () { S.page++; load(); });
  $('refresh').addEventListener('click', function () { loadMeta(); });
  $('rows').addEventListener('click', function (ev) { var r = ev.target.closest('.kb-row'); if (r) openPanel(+r.getAttribute('data-id')); });
  $('rows').addEventListener('keydown', function (ev) { var r = ev.target.closest('.kb-row'); if (r && ev.key === 'Enter') openPanel(+r.getAttribute('data-id')); });
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
