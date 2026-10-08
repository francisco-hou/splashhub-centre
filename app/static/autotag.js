// SplashHub Centre -- AutoTag (autotag.py): Spark's language for each new
// ticket, held here to be checked. The list compares it with the ticket's
// language tag in Zendesk now; a ticket opens in a panel with what Spark read,
// Right / Wrong, and the Add tag / Change tag button -- the only thing here that
// writes to Zendesk (that one ticket's tags; no status change).
(function () {
  'use strict';

  var S = { q: '', lang: '', state: '', verdict: '', match: '', page: 0, rows: [], sel: {} };
  var ST = null, ZD = '', CUR = null;

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
  function tagOf(lang) { return lang ? 'language_' + ({ Japanese: 'ja', Korean: 'ko', 'Chinese (Simplified)': 'zh-cn', 'Chinese (Traditional)': 'zh-tw', English: 'en', French: 'fr', German: 'de', Spanish: 'es', Italian: 'it', Portuguese: 'pt', Other: 'other' }[lang] || '') : ''; }
  function ticketLink(id) { return ZD ? '<a href="' + esc(ZD) + '/agent/tickets/' + id + '" target="_blank" rel="noopener">#' + id + '</a>' : '#' + id; }

  // ---- top: state and numbers ----------------------------------------------------------------
  function loadStatus() {
    return api('/api/autotag').then(function (s) {
      ST = s;
      var n = $('note');
      if (!s.on) { n.hidden = false; n.innerHTML = 'AutoTag is <b>off</b>. An admin can switch it on in <b>Settings &rsaquo; AutoTag</b>.'; }
      else if (s.error) { n.hidden = false; n.textContent = 'Last round: ' + s.error; }
      else n.hidden = true;
      $('stamp').textContent = s.last_ms ? 'Checked ' + when(s.last_ms) + ' · every 2 min' : (s.on ? 'Starting…' : '');
      var sel = $('lang');
      if (sel.options.length <= 1) {
        sel.innerHTML = '<option value="">All languages</option>' + s.choices.map(function (c) { return '<option>' + esc(c) + '</option>'; }).join('') + '<option value="None">No text (no tag)</option>';
        sel.value = S.lang;
      }
      var checked = s.right + s.wrong, compared = s.same + s.differs;
      var tile = function (label, value, sub, cls) {
        return '<div class="stat"><div class="stat-label">' + label + '</div><div class="stat-value ' + (cls || '') + '">' + value + '</div><div class="stat-sub">' + sub + '</div></div>';
      };
      $('stats').innerHTML =
        tile('Tickets read', int(s.total), int(s.last_24h) + ' in the last 24 h' + (s.skipped ? ' · ' + int(s.skipped) + ' skipped (provisioning, calls)' : '')) +
        tile('Would tag', int(s.held), s.languages.slice(0, 3).map(function (l) { return esc(l.lang) + ' ' + l.n; }).join(' · ') || 'none yet') +
        tile('Same as Zendesk', compared ? Math.round(100 * s.same / compared) + '%' : '—', int(s.same) + ' of ' + int(compared) + ' that have a language tag') +
        tile('Differs', int(s.differs), int(s.no_tag) + ' more have no language tag', s.differs ? 'ov-o' : '') +
        tile('Checked by the team', checked ? Math.round(100 * s.right / checked) + '% right' : '—', int(s.right) + ' right · ' + int(s.wrong) + ' wrong');
    }).catch(function (e) { $('note').hidden = false; $('note').textContent = 'Could not load AutoTag: ' + e.message; });
  }

  // ---- the list ---------------------------------------------------------------------------------
  function sparkCell(r) {
    if (r.state === 'skipped') return '<span class="at-b at-skip" title="' + esc(r.reason) + '">Skipped</span>' + was(r);
    if (r.state === 'waiting') return '<span class="at-b at-wait">Waiting</span>' + was(r);
    if (r.state === 'none') return '<span class="at-b at-none" title="No real customer text: no tag">No text</span>' + was(r);
    return '<span class="at-b">' + esc(r.lang) + '</span>' + (r.confidence && r.confidence !== 'high' ? ' <span class="at-conf at-' + esc(r.confidence) + '">' + esc(r.confidence) + '</span>' : '') +
      (r.method === 'requester' ? ' <span class="at-conf" title="' + esc(r.reason) + '">by requester</span>' : '') + was(r);
  }
  // scanned again and Spark changed its answer: what it said before
  function was(r) { return r.prev_lang ? ' <span class="at-conf at-was" title="Spark changed its answer when scanned again ' + esc(when(r.rescan_ms)) + '">was ' + esc(r.prev_lang) + '</span>' : ''; }
  function zdCell(r) {
    var z = r.zd_lang ? esc(r.zd_lang) : '<span class="muted">—</span>';
    if (r.match === 'differs') z = '<span class="at-diff">' + z + '</span>';
    if (r.applied_ms) z += r.applied_tag ? ' <span class="at-conf at-applied" title="Tag added from SplashHub Centre ' + esc(when(r.applied_ms)) + '">from Centre</span>'
      : ' <span class="at-conf" title="Language tag cleared from SplashHub Centre ' + esc(when(r.applied_ms)) + '">cleared</span>';
    return z;
  }
  function checkCell(r) {
    if (r.verdict === 'right') return '<span class="at-ok">✓ Right</span>';
    if (r.verdict === 'wrong') return '<span class="at-bad">✗ Wrong' + (r.correct_lang ? ' · ' + esc(r.correct_lang) : '') + '</span>';
    return '<span class="muted">—</span>';
  }
  // the language a mass Add tags would give: the team's correction, else Spark's (as autotag._target)
  function target(r) {
    if (r.applied_ms && !r.applied_tag) return null;        // someone cleared its tag on purpose: not put back by a mass add
    var lang = r.verdict === 'wrong' && r.correct_lang ? r.correct_lang : (r.state === 'held' ? r.lang : null);
    return lang && lang !== 'None' && lang !== r.zd_lang ? lang : null;
  }
  function row(r) {
    var can = !!target(r);
    return '<tr class="at-row" tabindex="0" data-id="' + r.ticket_id + '"><td class="at-ck"><input type="checkbox" data-ck="' + r.ticket_id + '"' +
      (can ? '' : ' disabled title="Nothing to add: no language, or Zendesk already has it"') + (can && S.sel[r.ticket_id] ? ' checked' : '') +
      ' aria-label="Select ticket ' + r.ticket_id + '"></td><td class="when">' + esc(when(r.created_ms)) + '</td>' +
      '<td>#' + r.ticket_id + '</td><td class="at-subj" title="' + esc(r.subject) + '">' + esc(r.subject || '(no subject)') + '</td>' +
      '<td>' + sparkCell(r) + '</td><td>' + zdCell(r) + '</td><td>' + checkCell(r) + '</td></tr>';
  }
  var seq = 0;
  function load() {
    var my = ++seq;
    var q = ['page=' + S.page];
    ['q', 'lang', 'state', 'verdict', 'match'].forEach(function (k) { if (S[k]) q.push(k + '=' + encodeURIComponent(S[k])); });
    return api('/api/autotag/list?' + q.join('&')).then(function (d) {
      if (my !== seq) return;
      S.rows = d.rows;
      $('count').textContent = d.total ? 'newest first · ' + int(d.total) + (d.total === 1 ? ' ticket' : ' tickets') : '';
      $('rows').innerHTML = d.rows.length ? d.rows.map(row).join('') :
        '<tr class="empty-row"><td colspan="7">' + (S.q || S.lang || S.state || S.verdict || S.match ? 'No tickets match.' : 'No tickets read yet — new ones appear within 2 minutes.') + '</td></tr>';
      var pages = Math.ceil(d.total / d.per_page);
      $('pager').hidden = pages <= 1;
      $('pagerTxt').textContent = 'Page ' + (d.page + 1) + ' of ' + pages;
      $('prev').disabled = d.page <= 0; $('next').disabled = d.page + 1 >= pages;
      if (CUR) { var r = find(CUR); if (r) $('detail').innerHTML = detail(r); }
      drawBulk();
    }).catch(function (e) { $('rows').innerHTML = '<tr class="empty-row"><td colspan="7">Could not load: ' + esc(e.message) + '</td></tr>'; });
  }
  function find(id) { return S.rows.filter(function (r) { return r.ticket_id === id; })[0]; }
  function swap(r) {
    S.rows = S.rows.map(function (x) { return x.ticket_id === r.ticket_id ? r : x; });
    var tr = document.querySelector('.at-row[data-id="' + r.ticket_id + '"]');
    if (tr) tr.outerHTML = row(r);
    if (CUR === r.ticket_id) $('detail').innerHTML = detail(r);
  }

  // ---- one ticket -------------------------------------------------------------------------------
  function options(sel) {
    return (ST ? ST.choices : []).map(function (c) { return '<option' + (c === sel ? ' selected' : '') + '>' + esc(c) + '</option>'; }).join('');
  }
  function detail(r) {
    var want = r.verdict === 'wrong' && r.correct_lang && r.correct_lang !== 'None' ? r.correct_lang : (r.state === 'held' ? r.lang : (r.zd_lang || ''));
    var said = r.state === 'held' ? '<b>' + esc(r.lang) + '</b> · ' + esc(r.confidence || '') + ' confidence' + (r.reason ? ' · ' + esc(r.reason) : '') :
      r.state === 'none' ? '<b>No text</b> — no real customer text, so no tag' + (r.reason ? ' · ' + esc(r.reason) : '') :
      r.state === 'skipped' ? '<b>Skipped</b> — ' + esc(r.reason) : '<b>Waiting</b> for Spark';
    var applied = !r.applied_ms ? '' : r.applied_tag ? '<div class="at-note">Tag <code>' + esc(r.applied_tag) + '</code> added from SplashHub Centre ' + esc(when(r.applied_ms)) +
      (r.applied_from ? ' (took off <code>' + esc(r.applied_from) + '</code>)' : '') + '.</div>'
      : '<div class="at-note">Language tag <code>' + esc(r.applied_from || '') + '</code> cleared from SplashHub Centre ' + esc(when(r.applied_ms)) + '.</div>';
    return '<div class="at-d">' +
      '<div class="at-dh"><div class="at-dt">' + ticketLink(r.ticket_id) + ' · ' + esc(r.subject || '(no subject)') + '</div>' +
      '<div class="muted">' + esc(when(r.created_ms)) + (r.channel ? ' · ' + esc(r.channel) : '') + (r.requester ? ' · ' + esc(r.requester) : '') + (r.status ? ' · ' + esc(r.status) : '') + '</div></div>' +
      '<div class="at-grid"><div class="at-box"><div class="at-k">Spark says</div><div>' + said + '</div>' +
        (r.tag ? '<div class="muted">Would add <code>' + esc(r.tag) + '</code></div>' : '') +
        (r.method === 'spark' ? '<div class="muted"><a href="/sparklog#t-' + r.ticket_id + '">See what Spark read and answered</a> (admins)</div>' : '') +
        (r.rescan_ms ? '<div class="rs-line">Scanned again ' + esc(when(r.rescan_ms)) + ': ' + (r.prev_lang ? 'changed from <b>' + esc(r.prev_lang) + '</b>' : 'same answer') + '</div>' : '') +
        '<div class="frow rs-act"><button type="button" class="btn btn-sm" id="atRescan" title="Read this ticket again and ask Spark again, with today\u2019s rules. Nothing is written to Zendesk.">Scan again with Spark</button></div></div>' +
      '<div class="at-box"><div class="at-k">In Zendesk now</div><div>' + (r.zd_lang ? '<b>' + esc(r.zd_lang) + '</b> <code>' + esc(tagOf(r.zd_lang)) + '</code>' : 'No language tag') + '</div>' +
        (r.match === 'differs' ? '<div class="at-diff">Differs from Spark</div>' : r.match === 'same' ? '<div class="at-ok">Same as Spark</div>' : '') + '</div></div>' +
      '<div class="at-k">What Spark read <span class="muted">(subject + the customer&rsquo;s first message)</span></div>' +
      '<div class="at-sample">' + esc(r.sample || '(no customer text)') + '</div>' +
      '<div class="at-k">Is Spark right?</div>' +
      '<div class="frow at-act"><button type="button" class="btn btn-sm' + (r.verdict === 'right' ? ' on-ok' : '') + '" data-v="right">✓ Right</button>' +
        '<button type="button" class="btn btn-sm' + (r.verdict === 'wrong' ? ' on-bad' : '') + '" data-v="wrong">✗ Wrong</button>' +
        (r.verdict === 'wrong' ? '<label class="at-lbl">It is <select class="sel" id="atCorrect"><option value="">choose…</option>' + options(r.correct_lang) +
          '<option value="None"' + (r.correct_lang === 'None' ? ' selected' : '') + '>No text (no tag)</option></select></label>' : '') +
        (r.verdict ? '<button type="button" class="btn btn-sm btn-link" data-v="">Undo</button>' : '') + '</div>' +
      '<div class="at-k">Tag in Zendesk</div>' +
      '<div class="frow at-act"><select class="sel" id="atLang"><option value="">Language…</option>' + options(want) + '</select>' +
        '<button type="button" class="btn btn-primary btn-sm" id="atApply" disabled>Add tag</button>' +
        (r.zd_lang ? '<button type="button" class="btn btn-sm" id="atClear" title="Take the language tag off this ticket in Zendesk">Clear tag</button>' : '') + '</div>' +
      '<div class="at-hint" id="atHint"></div><div class="sc-msg" id="atMsg" aria-live="polite"></div>' + applied +
      '</div>';
  }
  function hint() {
    var r = find(CUR), b = $('atApply'); if (!r || !b) return;
    var lang = $('atLang').value, tag = tagOf(lang), cur = r.zd_lang ? tagOf(r.zd_lang) : '';
    b.disabled = !lang || lang === r.zd_lang;
    b.textContent = cur && lang && lang !== r.zd_lang ? 'Change tag' : 'Add tag';
    $('atHint').innerHTML = !lang ? '' : lang === r.zd_lang ? 'The ticket already has <code>' + esc(tag) + '</code>.' :
      (cur ? 'Takes off <code>' + esc(cur) + '</code> and adds <code>' + esc(tag) + '</code>' : 'Adds <code>' + esc(tag) + '</code>') +
      ' on ticket #' + r.ticket_id + ' in Zendesk &mdash; tags only: the status stays as it is and nobody needs to submit.';
  }
  function openPanel(id) {
    var r = find(id); if (!r) return;
    CUR = id;
    $('pnWrap').hidden = false;
    document.body.classList.add('pn-lock');
    var i = S.rows.indexOf(r);
    $('pnPos').textContent = (i + 1) + ' of ' + S.rows.length + ' on this page';
    $('detail').innerHTML = detail(r);
    hint();
    $('panel').focus();
  }
  function closePanel() { CUR = null; $('pnWrap').hidden = true; document.body.classList.remove('pn-lock'); }
  function step(d) { var i = S.rows.indexOf(find(CUR)), n = S.rows[i + d]; if (n) openPanel(n.ticket_id); }

  $('detail').addEventListener('change', function (ev) {
    if (ev.target.id === 'atLang') hint();
    if (ev.target.id === 'atCorrect') {
      var lang = ev.target.value;
      post('/api/autotag/verdict', { ticket_id: CUR, verdict: 'wrong', correct_lang: lang }).then(function (r) { swap(r); hint(); loadStatus(); });
    }
  });
  $('detail').addEventListener('click', function (ev) {
    var v = ev.target.closest('[data-v]');
    if (v) {
      post('/api/autotag/verdict', { ticket_id: CUR, verdict: v.getAttribute('data-v') }).then(function (r) { swap(r); hint(); loadStatus(); })
        .catch(function (e) { $('atMsg').textContent = 'Could not save: ' + e.message; });
      return;
    }
    if (ev.target.id === 'atRescan') {
      var rb = ev.target, rid = CUR;
      rb.disabled = true; rb.textContent = 'Asking Spark…';
      post('/api/autotag/rescan', { ids: [rid] }).then(function (d) {
        if (d.row) swap(d.row);
        loadStatus();
        var c = (d.rescan.changed || [])[0];
        if (CUR === rid) $('atMsg').textContent = c ? 'Spark changed its answer: ' + c.was + ' → ' + c.now + '.' : 'Spark gave the same answer as before.';
      }).catch(function (e) { rb.disabled = false; rb.textContent = 'Scan again with Spark'; $('atMsg').textContent = 'Could not scan again: ' + e.message; });
      return;
    }
    if (ev.target.id === 'atClear') {
      var cb = ev.target, cid = CUR, cr = find(cid);
      if (!cb.getAttribute('data-sure')) {
        cb.setAttribute('data-sure', '1'); cb.classList.add('on-bad');
        cb.textContent = 'Yes, clear ' + tagOf(cr && cr.zd_lang);
        $('atHint').innerHTML = 'Takes <code>' + esc(tagOf(cr && cr.zd_lang)) + '</code> off ticket #' + cid + ' in Zendesk &mdash; tags only: the status stays as it is.';
        return;
      }
      cb.disabled = true; $('atMsg').textContent = 'Clearing the tag in Zendesk…';
      post('/api/autotag/clear', { ticket_id: cid }).then(function (r) {
        swap(r); hint(); loadStatus();
        if (CUR === cid) $('atMsg').textContent = 'Done — ticket #' + cid + ' has no language tag now.';
      }).catch(function (e) { $('atMsg').textContent = 'Could not clear: ' + e.message; cb.disabled = false; });
      return;
    }
    if (ev.target.id === 'atApply') {
      var b = ev.target, lang = $('atLang').value, id = CUR;
      b.disabled = true; $('atMsg').textContent = 'Writing the tag to Zendesk…';
      post('/api/autotag/apply', { ticket_id: id, lang: lang }).then(function (r) {
        swap(r); hint(); loadStatus();
        if (CUR === id) $('atMsg').textContent = 'Done — ticket #' + id + ' now has ' + tagOf(lang) + '.';
      }).catch(function (e) { $('atMsg').textContent = 'Could not tag: ' + e.message; b.disabled = false; });
    }
  });

  // ---- controls ---------------------------------------------------------------------------------
  var qT = 0;
  $('q').addEventListener('input', function () { clearTimeout(qT); qT = setTimeout(function () { S.q = $('q').value.trim(); S.page = 0; load(); }, 250); });
  ['lang', 'state', 'verdict'].forEach(function (k) { $(k).addEventListener('change', function () { S[k] = this.value; S.page = 0; load(); }); });
  $('match').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-m]'); if (!b) return;
    S.match = b.getAttribute('data-m'); S.page = 0;
    Array.prototype.forEach.call(this.children, function (c) { c.classList.toggle('active', c === b); });
    load();
  });
  $('prev').addEventListener('click', function () { if (S.page > 0) { S.page--; load(); } });
  $('next').addEventListener('click', function () { S.page++; load(); });
  $('refresh').addEventListener('click', function () { loadStatus(); load(); });
  $('rows').addEventListener('click', function (ev) { if (ev.target.closest('a, .at-ck')) return; var r = ev.target.closest('.at-row'); if (r) openPanel(+r.getAttribute('data-id')); });
  $('rows').addEventListener('keydown', function (ev) { var r = ev.target.closest('.at-row'); if (r && ev.key === 'Enter') openPanel(+r.getAttribute('data-id')); });
  $('pnClose').addEventListener('click', closePanel);
  $('pnPrev').addEventListener('click', function () { step(-1); });
  $('pnNext').addEventListener('click', function () { step(1); });
  $('pnWrap').addEventListener('click', function (ev) { if (ev.target === this) closePanel(); });
  document.addEventListener('keydown', function (ev) {
    if ($('pnWrap').hidden || /^(SELECT|INPUT)$/.test((ev.target || {}).tagName || '')) return;
    if (ev.key === 'Escape') closePanel();
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); step(-1); }
    else if (ev.key === 'ArrowDown') { ev.preventDefault(); step(1); }
  });


  // ---- for the checking phase (to be removed once AutoTag writes tags by itself):
  //      Scan new tickets, and Add tags to the ticked tickets -------------------------------------
  var confirming = false, bulkT = 0;
  function chosen() { return S.rows.filter(function (r) { return S.sel[r.ticket_id] && target(r); }); }
  function drawBulk() {
    var b = ST && ST.bulk, el = $('bulk'), n = chosen().length;
    var all = S.rows.filter(target);
    $('ckAll').checked = all.length > 0 && all.every(function (r) { return S.sel[r.ticket_id]; });
    $('ckAll').disabled = !all.length;
    if (b && b.running) {
      el.hidden = false;
      el.innerHTML = '<span class="at-spin"></span> Adding tags in Zendesk… ' + b.done + ' of ' + b.total;
      return;
    }
    if (!n) {
      confirming = false;
      el.hidden = !all.length;
      if (all.length) el.innerHTML = '<button type="button" class="btn btn-sm" id="bulkAll">Add tags to all on this page (' + all.length + ')</button>';
      return;
    }
    el.hidden = false;
    if (confirming) {
      var by = {};
      chosen().forEach(function (r) { var l = target(r); by[l] = (by[l] || 0) + 1; });
      el.innerHTML = 'Add the language tag to <b>' + n + '</b> ticket' + (n === 1 ? '' : 's') + ' in Zendesk? <span class="muted">(' +
        Object.keys(by).map(function (l) { return esc(l) + ' ' + by[l]; }).join(', ') + ' · tags only, the status stays)</span> ' +
        '<button type="button" class="btn btn-primary btn-sm" id="bulkYes">Yes, add tags</button> <button type="button" class="btn btn-sm" id="bulkNo">Cancel</button>';
    } else {
      el.innerHTML = '<b>' + n + '</b> selected <button type="button" class="btn btn-primary btn-sm" id="bulkGo">Add tags</button> <button type="button" class="btn btn-sm" id="bulkClear">Clear</button>';
    }
  }
  function watchBulk() {
    clearTimeout(bulkT);
    loadStatus().then(function () {
      drawBulk();
      if (ST.bulk && ST.bulk.running) { bulkT = setTimeout(watchBulk, 1500); return; }
      var b = ST.bulk || {};
      S.sel = {};
      load().then(function () {
        $('bulk').hidden = false;
        $('bulk').innerHTML = 'Done: ' + b.tagged + ' tagged' + (b.skipped ? ', ' + b.skipped + ' had nothing to add' : '') +
          (b.failed ? ', <span class="at-bad">' + b.failed + ' failed</span> (' + esc(b.error || '') + ')' : '') + '.';
        setTimeout(drawBulk, 6000);
      });
    });
  }
  $('rows').addEventListener('change', function (ev) {
    var id = ev.target.getAttribute('data-ck'); if (!id) return;
    if (ev.target.checked) S.sel[id] = true; else delete S.sel[id];
    confirming = false; drawBulk();
  });
  $('ckAll').addEventListener('change', function () {
    var on = this.checked;
    S.rows.filter(target).forEach(function (r) { if (on) S.sel[r.ticket_id] = true; else delete S.sel[r.ticket_id]; });
    [].forEach.call(document.querySelectorAll('[data-ck]:not([disabled])'), function (c) { c.checked = on; });
    confirming = false; drawBulk();
  });
  $('bulk').addEventListener('click', function (ev) {
    var id = ev.target.id;
    if (id === 'bulkGo') { confirming = true; drawBulk(); }
    else if (id === 'bulkAll') {                         // every ticket on this page that can be tagged, then the usual confirm
      S.rows.filter(target).forEach(function (r) { S.sel[r.ticket_id] = true; });
      [].forEach.call(document.querySelectorAll('[data-ck]:not([disabled])'), function (c) { c.checked = true; });
      confirming = true; drawBulk();
    }
    else if (id === 'bulkNo') { confirming = false; drawBulk(); }
    else if (id === 'bulkClear') { S.sel = {}; confirming = false; load(); }
    else if (id === 'bulkYes') {
      confirming = false;
      post('/api/autotag/apply-many', { ids: chosen().map(function (r) { return r.ticket_id; }) })
        .then(function () { watchBulk(); })
        .catch(function (e) { $('bulk').innerHTML = 'Could not start: ' + esc(e.message); });
    }
  });
  $('scanNow').addEventListener('click', function () {
    var b = this; b.disabled = true; b.textContent = 'Scanning…';
    post('/api/autotag/scan', {}).then(function () {
      var tries = 0;
      (function wait() {
        loadStatus().then(function () {
          if (ST.busy && tries++ < 120) return setTimeout(wait, 2000);
          load(); b.disabled = false; b.textContent = 'Scan new tickets';
        });
      })();
    }).catch(function (e) { b.disabled = false; b.textContent = 'Scan new tickets'; $('note').hidden = false; $('note').textContent = 'Could not scan: ' + e.message; });
  });

  var RS_URL = '/api/autotag/rescan';
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
      (rs.failed ? ' · <span class="muted">' + rs.failed + ' kept their old answer (no answer from Spark, or a chat still going)</span>' : '') +
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
    .then(function (x) { ZD = x.zendesk_url || ''; }).catch(function () {});
  loadStatus().then(function () { if (ST && ST.rescan && ST.rescan.running) rsWatch(); return load(); });
  setInterval(function () { if (document.visibilityState === 'visible' && $('pnWrap').hidden) { loadStatus(); load(); } }, 60000);
})();
