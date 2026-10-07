// SplashHub Centre -- SSO Requests page.
//
// Requests to validate an SSO method (ssocheck.py): the ticket gives the
// domain and the DNS TXT record the customer must add. A row opens the request
// in a pop-up: the record on the left (correctable when the ticket didn't say
// it plainly), and on the right the DNS check -- "Check DNS now" -- and, after
// a check, "Add as internal note". Everything here is manual.
(function () {
  'use strict';

  var S = { status: '', q: '', page: 0, open: null, tview: 'open' };   // opens on the tickets that need action
  var LABEL = { needs_details: 'Needs details', pending: 'Not checked', not_found: 'Not found yet', verified: 'Verified', error: 'Check failed' };
  var CHIPS = [['', 'All'], ['waiting', 'Waiting'], ['verified', 'Verified'], ['not_found', 'Not found yet'],
               ['pending', 'Not checked'], ['needs_details', 'Needs details'], ['error', 'Check failed']];
  var ICON_OUT = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>';
  var ZD = '';
  var CUR = null;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function whenTxt(ms) {
    if (!ms) return '';
    var d = new Date(ms), p = function (n) { return String(n).padStart(2, '0'); };
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }
  function fullWhen(ms) {
    return ms ? new Date(ms).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
  }
  function pill(st) { return '<span class="vpill s-' + esc(st) + '">' + esc(LABEL[st] || st) + '</span>'; }
  // the Zendesk ticket's own status, as on SOS Scans (read with the ticket, refreshed when it changes)
  var TSTATUS = { new: 'New', open: 'Open', pending: 'Pending', hold: 'On-hold', solved: 'Solved', closed: 'Closed' };
  function tstatus(st) {
    return st ? '<span class="tst tst-' + esc(st) + '">' + esc(TSTATUS[st] || st) + '</span>' : '<span class="muted">—</span>';
  }
  // where it stands (ssocheck._stage): rules for the facts; the customer's latest reply read by Spark
  var STAGE = { enabled: 'Verified & enabled', no_records: 'Records not sent yet', sent: 'Waiting for the customer',
    says_done: 'Customer says it’s added', stuck: 'Customer has a question', waiting: 'Customer waiting on their side', replied: 'Customer replied' };
  var BY_SPARK = { says_done: 1, stuck: 1, waiting: 1, replied: 1 };
  function stageTxt(r) {
    if (!r.stage) return '';
    var t = STAGE[r.stage] || r.stage;
    if (r.stage === 'says_done' && r.status !== 'verified' && r.last_checked_ms) t += ' — not in DNS yet';
    return t;
  }
  function stageLine(r) {
    var t = stageTxt(r); if (!t) return '';
    var warn = r.stage === 'stuck' || (r.stage === 'says_done' && r.status !== 'verified');
    return '<div class="sso-stage' + (warn ? ' warn' : r.stage === 'enabled' || r.stage === 'says_done' ? ' ok' : '') + '" title="' +
      esc((r.stage_note || '') + (BY_SPARK[r.stage] ? ' (read by Spark)' : '')) + '">' + esc(t) + '</div>';
  }
  function api(path, opts) {
    return fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {})).then(function (r) {
      if (r.status === 401) { location.href = '/logs?next=' + encodeURIComponent('/sso' + location.hash); throw new Error('login'); }
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function post(path, body) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  }

  // ---- boot: same session as the Logs page ----------------------------------------
  fetch('/api/session', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (s) {
    $('signOut').hidden = !(s.required && s.authed);
    $('page').hidden = false;
    var m = /^#(\d+)$/.exec(location.hash);
    if (m) S.open = +m[1];
    load(); pollJob('import'); pollJob('all');
  });
  $('signOut').addEventListener('click', function () {
    fetch('/logout', { method: 'POST', credentials: 'same-origin' }).then(function () { location.reload(); });
  });

  // ---- background jobs: the import and "Check all waiting" --------------------------
  var JOBS = {
    import: { url: '/api/sso-import', btn: 'impBtn', stop: 'impStop', msg: 'impMsg', timer: null,
              text: function (st) {
                if (st.running) return st.done ? 'Importing… ' + st.done.toLocaleString() + ' checked, ' + st.added.toLocaleString() + ' added' +
                  (st.resumed ? ' (carried on after a restart)' : '') : 'Searching Zendesk…';
                if (st.error) return 'Stopped: ' + st.error;
                if (st.stopped) return 'Stopped — ' + st.added + ' added so far. Press Import again to carry on.';
                return st.finished_ms ? 'Done — ' + st.added + ' added, ' + st.skipped + ' already listed (' + st.found + ' found).' : '';
              } },
    all: { url: '/api/sso-check-all', btn: 'allBtn', stop: 'allStop', msg: 'allMsg', timer: null,
           text: function (st) {
             if (st.running) return 'Checking… ' + st.done + ' of ' + st.found + ' (' + st.verified + ' verified)';
             if (st.error) return 'Stopped: ' + st.error;
             return st.finished_ms ? 'Checked ' + st.done + ' — ' + st.verified + ' verified now.' : '';
           } }
  };
  function drawJob(k, st) {
    var j = JOBS[k];
    $(j.btn).disabled = !!st.running;
    $(j.stop).hidden = !st.running;
    $(j.msg).textContent = j.text(st);
    clearTimeout(j.timer);
    if (st.running) j.timer = setTimeout(function () { pollJob(k); }, 2000);
  }
  function pollJob(k) {
    var j = JOBS[k];
    api(j.url).then(function (st) {
      var was = $(j.btn).disabled;
      drawJob(k, st);
      if (was && !st.running) { lastSig = ''; load(); }
    }).catch(function () {});
  }
  Object.keys(JOBS).forEach(function (k) {
    var j = JOBS[k];
    $(j.btn).addEventListener('click', function () {
      if (k === 'import' && !confirm('Import past SSO requests?\n\nSplashHub Centre searches Zendesk for every 2026 SSO ticket (tagged single_sign-on__sso_, or with a splashtop-sso-challenge record), reads each conversation and lists it here. Tickets already listed are skipped.')) return;
      post(j.url).then(function (st) { drawJob(k, st); }).catch(function (e) { if (e.message !== 'login') $(j.msg).textContent = e.message; });
    });
    $(j.stop).addEventListener('click', function () {
      this.disabled = true; $(j.msg).textContent = 'Stopping…';
      post(j.url + '/stop').then(function () { setTimeout(function () { pollJob(k); }, 800); });
    });
  });

  // ---- add a ticket ----------------------------------------------------------------
  $('addForm').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var tid = $('tid').value.trim().replace(/^#/, '');
    if (!/^\d+$/.test(tid)) { $('addMsg').textContent = 'Enter a ticket number.'; return; }
    $('addBtn').disabled = true;
    post('/api/sso', { ticket_id: tid }).then(function (r) {
      $('addMsg').textContent = 'Added #' + tid + '.'; $('tid').value = ''; S.open = r.id; S.status = ''; S.page = 0; lastSig = ''; load();
    }).catch(function (e) { if (e.message !== 'login') $('addMsg').textContent = e.message; })
      .then(function () { $('addBtn').disabled = false; });
  });

  $('tview').addEventListener('change', function () { S.tview = this.value; S.page = 0; lastSig = ''; load(); });

  // ---- list --------------------------------------------------------------------------
  var seq = 0, lastSig = '';
  // The refresh icon (top right) turns while the list is being checked: on a
  // click, on the automatic check every minute, and while a request is being
  // processed. At least a moment, so a quick check is still visible. The
  // list itself never dims or flashes -- it only changes when there is news.
  var spinAt = 0;
  function spinOn() { spinAt = Date.now(); $('refresh').classList.add('spin'); }
  function spinOff() {
    setTimeout(function () { $('refresh').classList.remove('spin'); }, Math.max(0, 700 - (Date.now() - spinAt)));
  }
  setInterval(function () { if (document.visibilityState === 'visible' && !$('page').hidden) load(); }, 60000);

  function load() {
    var my = ++seq;
    spinOn();
    var p = 'page=' + S.page + '&tview=' + S.tview + (S.status ? '&status=' + encodeURIComponent(S.status) : '') + (S.q ? '&q=' + encodeURIComponent(S.q) : '');
    api('/api/sso?' + p).then(function (res) {
      spinOff();
      if (my !== seq) return;
      var sig = JSON.stringify([p, res.total, res.counts, res.rows.map(function (r) { return [r.id, r.status, r.domain, r.last_checked_ms, r.note_json, r.ticket_status, r.stage, r.stage_note]; })]);
      if (sig !== lastSig) { lastSig = sig; drawChips(res.counts); drawRows(res); }
      var d = new Date();
      $('stamp').textContent = 'Updated ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    }).catch(function (e) { spinOff(); if (e.message !== 'login') $('stamp').textContent = 'Could not load: ' + e.message; });
  }
  function drawChips(counts) {
    var n = function (k) { return counts[k] || 0; };
    var total = Object.keys(counts).reduce(function (a, k) { return a + counts[k]; }, 0);
    var num = { '': total, waiting: n('pending') + n('not_found') + n('error'), verified: n('verified'), not_found: n('not_found'),
                pending: n('pending'), needs_details: n('needs_details'), error: n('error') };
    $('chips').innerHTML = CHIPS.map(function (c) {
      return '<button type="button" class="chip' + (S.status === c[0] ? ' active' : '') + (num[c[0]] ? '' : ' empty') +
        '" data-v="' + c[0] + '">' + esc(c[1]) + ' <span class="chip-n">' + num[c[0]] + '</span></button>';
    }).join('');
  }
  function drawRows(res) {
    $('count').textContent = res.total ? 'newest first · ' + res.total + (res.total === 1 ? ' request' : ' requests') : '';
    if (!res.rows.length) {
      $('rows').innerHTML = '<tr class="empty-row"><td colspan="7">' + (S.status || S.q ? 'No requests match.' :
        S.tview === 'open' ? 'Nothing needs action right now. Solved and closed tickets are under the ticket-status filter.' :
        S.tview === 'done' ? 'No solved or closed SSO tickets yet.' :
        'No SSO requests yet. SplashHub Centre looks for them every 15 minutes (tickets tagged single_sign-on__sso_ or with a splashtop-sso-challenge record); Import past SSO requests finds the ones from 2026.') + '</td></tr>';
    } else {
      $('rows').innerHTML = res.rows.map(function (r) {
        return '<tr class="sc-row" data-id="' + r.id + '" tabindex="0">' +
          '<td class="when">' + esc(whenTxt(r.requested_ms)) + '</td>' +
          '<td><a href="' + esc(ZD) + '/agent/tickets/' + r.ticket_id + '" target="_blank" rel="noopener" class="tlink">#' + r.ticket_id + '</a></td>' +
          '<td>' + tstatus(r.ticket_status) + '</td>' +
          '<td>' + pill(r.status) + (r.note_json ? ' <span class="noted" title="An internal note was added">&#10003; note</span>' : '') + stageLine(r) + '</td>' +
          '<td class="topic">' + (r.domain ? esc(r.domain) + more(r) : '<span class="muted">—</span>') + '</td>' +
          '<td>' + (r.requester_email ? esc(r.requester_email) : '<span class="muted">—</span>') + '</td>' +
          '<td class="when">' + (r.last_checked_ms ? esc(whenTxt(r.last_checked_ms)) : '<span class="muted">never</span>') + '</td></tr>';
      }).join('');
    }
    if (S.open) openPanel(S.open); else markOpen();
    var pages = Math.ceil(res.total / res.per_page);
    $('pager').hidden = pages <= 1;
    $('prev').disabled = res.page <= 0;
    $('next').disabled = res.page >= pages - 1;
    $('pagerTxt').textContent = res.total ? (res.page * res.per_page + 1) + '–' + (res.page * res.per_page + res.rows.length) + ' of ' + res.total : '';
  }
  $('chips').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-v]'); if (!b) return;
    S.status = b.getAttribute('data-v'); S.page = 0; load();
  });
  var typing = null;
  $('q').addEventListener('input', function () {
    var v = this.value.trim(); clearTimeout(typing);
    typing = setTimeout(function () { S.q = v; S.page = 0; load(); }, 250);
  });
  $('refresh').addEventListener('click', function () { lastSig = ''; load(); });
  $('prev').addEventListener('click', function () { if (S.page > 0) { S.page--; load(); } });
  $('next').addEventListener('click', function () { S.page++; load(); });

  // ---- the pop-up ----------------------------------------------------------------------
  function kv(k, v, cls) {
    return '<div><span class="pn-k">' + esc(k) + '</span><span class="pn-v' + (cls ? ' ' + cls : '') + '">' + v + '</span></div>';
  }
  function copyBtn(v) {
    return v ? ' <button type="button" class="link-btn copy-btn" data-copy="' + esc(v) + '" title="Copy">Copy</button>' : '';
  }

  // a ticket with several challenge records: "+2" after the first domain
  function recsOf(x) { try { return (typeof x.records_json === 'string' ? JSON.parse(x.records_json || '[]') : x.records) || []; } catch (e) { return []; } }
  function more(r) {
    var n = recsOf(r).length;
    return n > 1 ? ' <span class="muted" title="' + esc(recsOf(r).map(function (x) { return x.domain; }).join(', ')) + '">+' + (n - 1) + '</span>' : '';
  }

  function render(s) {
    var r = s.last_result || null;
    var title = s.domain || 'No domain yet';
    var h = '<div class="pn-cols"><div class="pn-main">';
    // header
    h += '<header class="pn-head"><div class="pn-meta">' + pill(s.status) + '<span>' + esc(whenTxt(s.requested_ms)) + '</span>' +
      (s.source === 'import' ? '<span>· imported</span>' : s.source === 'search' ? '<span>· found in Zendesk</span>' : s.source === 'webhook' ? '<span>· from Zendesk trigger</span>' : '<span>· added by hand</span>') +
      '</div>' +
      '<h2 class="pn-title">' + esc(title) + '</h2>' +
      '<div class="pn-facts">' +
        kv('Requested', esc(fullWhen(s.requested_ms))) +
        kv('Requester', s.requester_email ? esc(s.requester_email) : '<span class="muted">—</span>') +
        '<div><span class="pn-k">Ticket</span><a class="pn-v" href="' + esc(s.zendesk_url) + '/agent/tickets/' + s.ticket_id + '" target="_blank" rel="noopener">#' + s.ticket_id + '</a></div>' +
        kv('Ticket status', tstatus(s.ticket_status)) +
        (s.stage ? kv('Where it stands', esc(stageTxt(s)) + (s.stage_note ? '<div class="muted">' + esc(s.stage_note) + (BY_SPARK[s.stage] ? ' · read by Spark' : '') + '</div>' : '')) : '') +
        (s.organization ? kv('Organization', esc(s.organization)) : '') +
      '</div></header>';
    // the record, correctable
    h += '<section class="pn-sec"><div class="pn-h">DNS record to look for</div>' +
      (s.parse && s.status === 'needs_details' ? '<div class="pn-ai-warn">' + esc(s.parse) + '</div>' : '') +
      '<form class="sso-rec" id="recForm">' +
        '<label><span class="pn-k">Domain</span><input class="sc-input" name="domain" value="' + esc(s.domain || '') + '" placeholder="example.com" autocomplete="off" spellcheck="false"></label>' +
        '<label><span class="pn-k">TXT record on</span><input class="sc-input" name="txt_name" value="' + esc(s.txt_name || '') + '" placeholder="the domain itself, or e.g. _splashtop.example.com" autocomplete="off" spellcheck="false"></label>' +
        '<label class="wide"><span class="pn-k">Expected TXT value' + copyBtn(s.txt_value) + '</span><input class="sc-input" name="txt_value" value="' + esc(s.txt_value || '') + '" placeholder="the value the customer was asked to add" autocomplete="off" spellcheck="false"></label>' +
        '<div class="sso-rec-act"><button type="submit" class="btn btn-sm">Save</button><span class="sc-msg" id="recMsg"></span></div>' +
      '</form></section>';
    // every challenge record in the ticket (more than one domain)
    var all = recsOf(s);
    if (all.length > 1) {
      var lastAll = (r && r.all) || [];
      h += '<section class="pn-sec"><div class="pn-h">All records in the ticket (' + all.length + ')</div><ul class="sso-all">' +
        all.map(function (x) {
          var c = lastAll.filter(function (a) { return a.host === x.host; })[0] || x;
          var st = c.error ? ['s-error', 'couldn’t check'] : c.found ? ['s-verified', 'in place'] : c.exists === undefined && !c.checked_ms && !lastAll.length ? ['', 'not checked'] :
            !x.value ? ['s-needs_details', 'no value in the ticket'] : ['s-not_found', 'not there yet'];
          return '<li><b>' + esc(x.domain) + '</b> <span class="sso-st ' + st[0] + '">' + st[1] + '</span><div class="muted">TXT on ' + esc(x.host) +
            (x.value ? ' · ' + esc(x.value) + copyBtn(x.value) : '') + '</div></li>';
        }).join('') + '</ul></section>';
    }
    // what the ticket said
    var fields = (s.fields || []).filter(function (f) { return f.value; });
    if (fields.length) {
      h += '<section class="pn-sec"><div class="pn-h">From the ticket</div><div class="pn-stack">' +
        fields.map(function (f) { return kv(f.label, esc(f.value)); }).join('') + '</div></section>';
    }
    if (s.description) {
      h += '<section class="pn-sec"><button type="button" class="link-btn rq-raw-btn" data-raw="1" aria-expanded="false">Show original text</button>' +
        '<pre class="rq-raw" hidden>' + esc(s.description) + '</pre></section>';
    }
    h += '<div class="pn-foot">Request ' + s.id + (s.checks ? ' · checked ' + s.checks + (s.checks === 1 ? ' time' : ' times') : '') + '</div>';
    // right: the DNS check card
    h += '</div><div class="pn-side"><div class="pn-side-in">' +
      '<a class="btn" href="' + esc(s.zendesk_url) + '/agent/tickets/' + s.ticket_id + '" target="_blank" rel="noopener" style="width:100%;justify-content:center">Open ticket #' + s.ticket_id + ' in Zendesk ' + ICON_OUT + '</a>' +
      '<section class="pn-sec pn-ai"><div class="pn-h">DNS check' +
        '<button type="button" class="btn btn-sm pn-ai-btn" data-check="1"' + (s.domain ? '' : ' disabled title="Add the domain first"') + '>' + (r ? 'Check again' : 'Check DNS now') + '</button></div>';
    if (!r) {
      h += '<div class="pn-why">' + (s.domain ? 'Not checked yet. Check DNS looks the TXT record up now.' : 'Add the domain (and the expected value) on the left first.') + '</div>';
    } else {
      var okN = (r.all || []).filter(function (a) { return a.found; }).length;
      var head = r.error ? ['s-error', 'Couldn’t check: ' + esc(r.error)]
        : r.all && r.found ? ['s-verified', 'Verified — all ' + r.all.length + ' TXT records are in place']
        : r.all ? ['s-not_found', okN + ' of ' + r.all.length + ' records in place — see All records']
        : r.found ? ['s-verified', 'Verified — the TXT record is in place']
        : !r.exists ? ['s-not_found', esc(r.name) + ' does not exist in DNS']
        : !r.expected ? ['s-needs_details', 'Add the expected value to compare']
        : ['s-not_found', 'Not found yet — the expected TXT record isn’t there'];
      h += '<div class="sso-result ' + head[0] + '">' + head[1] + '</div>';
      if (!r.error) {
        // The matching record first; when verified, the rest fold away.
        var want = (r.expected || '').replace(/\s+/g, '').toLowerCase();
        var isHit = function (x) { return want && x.replace(/\s+/g, '').toLowerCase().indexOf(want) >= 0; };
        var recs = r.records || [], hits = recs.filter(isHit), rest = recs.filter(function (x) { return !isHit(x); });
        var li = function (x, hit) { return '<li' + (hit ? ' class="hit"' : '') + '>' + esc(x) + '</li>'; };
        h += '<div class="pn-k">TXT records on ' + esc(r.name) + '</div>';
        if (!recs.length) h += '<div class="pn-why">None.</div>';
        else if (hits.length && rest.length) {
          h += '<ul class="sso-recs">' + hits.map(function (x) { return li(x, true); }).join('') + '</ul>' +
            '<details class="sso-hist"><summary>' + rest.length + (rest.length === 1 ? ' other record' : ' other records') + '</summary>' +
            '<ul class="sso-recs">' + rest.map(function (x) { return li(x, false); }).join('') + '</ul></details>';
        } else h += '<ul class="sso-recs">' + recs.map(function (x) { return li(x, isHit(x)); }).join('') + '</ul>';
      }
      h += '<div class="pn-ai-by">Checked ' + esc(fullWhen(r.ms)) + (s.verified_ms ? ' · first verified ' + esc(fullWhen(s.verified_ms)) : '') + '</div>';
      var hist = (s.history || []).slice(1, 6);
      if (hist.length) {
        h += '<details class="sso-hist"><summary>Earlier checks</summary><ul>' + hist.map(function (x) {
          return '<li>' + esc(fullWhen(x.ms)) + ' — ' + (x.error ? 'couldn’t check' : x.found ? 'verified' : 'not found') + '</li>';
        }).join('') + '</ul></details>';
      }
      h += noteBlock(s);
    }
    h += '<div class="pn-ai-msg" aria-live="polite"></div></section></div></div></div>';
    return h;
  }

  // "Add as internal note": preview, then add to the ticket. Manual only.
  var NOTE = { open: null, text: '', busy: false };
  function noteBlock(s) {
    var h = '<div class="pn-note">';
    if (s.note && s.note.ms) h += '<div class="pn-note-done">&#10003; Added to Zendesk as an internal note · ' + esc(fullWhen(s.note.ms)) + '</div>';
    if (NOTE.open !== s.id) {
      return h + '<button type="button" class="btn pn-note-btn" data-note="1">' + (s.note ? 'Add another internal note' : 'Add as internal note') + '</button></div>';
    }
    return h + '<div class="pn-note-box"><div class="pn-note-top"><span class="pn-note-lbl">Internal note on #' + s.ticket_id + '</span></div>' +
      '<pre class="pn-note-pre">' + (NOTE.text ? esc(NOTE.text) : 'Loading&hellip;') + '</pre>' +
      '<div class="pn-note-hint">Only agents see internal notes; the customer is not notified.</div>' +
      '<div class="pn-note-act"><button type="button" class="btn btn-primary btn-sm" data-notepost="1"' + (NOTE.busy || !NOTE.text ? ' disabled' : '') + '>' +
        (NOTE.busy ? 'Adding&hellip;' : 'Add to Zendesk') + '</button><button type="button" class="btn btn-sm" data-notecancel="1">Cancel</button></div></div></div>';
  }
  function redraw() { if (CUR) $('detail').innerHTML = render(CUR); }
  function msg(t) { var m = $('detail').querySelector('.pn-ai-msg'); if (m) m.textContent = t; }

  var dseq = 0;
  function loadDetail(id) {
    var my = ++dseq;
    api('/api/sso/' + id).then(function (s) {
      if (my !== dseq || S.open !== id) return;
      ZD = s.zendesk_url;
      var rawOpen = CUR && CUR.id === s.id && $('detail').querySelector('.rq-raw:not([hidden])');
      CUR = s; redraw();
      if (rawOpen) $('detail').querySelector('[data-raw]').click();
    }).catch(function (e) { if (my === dseq && e.message !== 'login') $('detail').innerHTML = '<div class="pn-loading"><div class="sc-err">Could not load this request.</div></div>'; });
  }

  function rowEls() { return [].slice.call($('rows').querySelectorAll('.sc-row')); }
  function markOpen() {
    var list = rowEls(), at = -1;
    list.forEach(function (tr, i) { var on = +tr.getAttribute('data-id') === S.open; tr.classList.toggle('open', on); if (on) at = i; });
    $('pnPos').textContent = at >= 0 ? (at + 1) + ' of ' + list.length + ' on this page' : '';
    $('pnPrev').disabled = at <= 0;
    $('pnNext').disabled = at < 0 || at >= list.length - 1;
  }
  var back = null;
  function openPanel(id) {
    var same = S.open === id && !$('pnWrap').hidden;
    if ($('pnWrap').hidden) back = document.activeElement;
    S.open = id;
    if (location.hash !== '#' + id) history.replaceState(null, '', '#' + id);
    $('pnWrap').hidden = false;
    document.body.classList.add('pn-lock');
    markOpen();
    if (!same) {
      CUR = null; NOTE.open = null;
      $('detail').innerHTML = '<div class="pn-loading">Loading&hellip;</div>';
      $('panel').scrollTop = 0; $('panel').focus();
    }
    loadDetail(id);
  }
  function closePanel() {
    S.open = null; CUR = null;
    if (location.hash) history.replaceState(null, '', location.pathname);
    $('pnWrap').hidden = true;
    document.body.classList.remove('pn-lock');
    markOpen();
    if (back && document.contains(back)) back.focus();
    back = null;
  }
  function step(d) {
    var list = rowEls(), at = list.findIndex(function (tr) { return +tr.getAttribute('data-id') === S.open; });
    var next = list[at + d];
    if (at < 0 || !next) return;
    openPanel(+next.getAttribute('data-id'));
    next.scrollIntoView({ block: 'nearest' });
    back = next;
  }
  $('pnClose').addEventListener('click', closePanel);
  $('pnWrap').addEventListener('mousedown', function (ev) { if (ev.target === this) closePanel(); });
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
  document.addEventListener('keydown', function (ev) {
    if (ev.defaultPrevented || $('pnWrap').hidden || /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName || '')) return;
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') { ev.preventDefault(); step(ev.key === 'ArrowDown' ? 1 : -1); }
    else if (ev.key === 'Escape') closePanel();
  });

  // pop-up actions
  $('detail').addEventListener('submit', function (ev) {
    if (ev.target.id !== 'recForm' || !CUR) return;
    ev.preventDefault();
    var f = ev.target, s = CUR;
    post('/api/sso/' + s.id + '/details', { domain: f.domain.value, txt_name: f.txt_name.value, txt_value: f.txt_value.value })
      .then(function () { $('recMsg').textContent = 'Saved.'; lastSig = ''; load(); loadDetail(s.id); })
      .catch(function (e) { if (e.message !== 'login') $('recMsg').textContent = e.message; });
  });
  $('detail').addEventListener('click', function (ev) {
    if (!CUR) return;
    var s = CUR, b;
    if ((b = ev.target.closest('[data-check]'))) {
      b.disabled = true; b.textContent = 'Checking…';
      post('/api/sso/' + s.id + '/check').then(function () { lastSig = ''; load(); loadDetail(s.id); })
        .catch(function (e) { b.disabled = false; b.textContent = 'Check DNS now'; if (e.message !== 'login') msg(e.message); });
      return;
    }
    if ((b = ev.target.closest('[data-copy]'))) {
      ev.preventDefault();
      navigator.clipboard && navigator.clipboard.writeText(b.getAttribute('data-copy')).then(function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1200); });
      return;
    }
    if (ev.target.closest('[data-note]')) {
      NOTE.open = s.id; NOTE.text = ''; NOTE.busy = false; redraw();
      api('/api/sso/' + s.id + '/note').then(function (r) { if (NOTE.open === s.id) { NOTE.text = r.text; redraw(); } })
        .catch(function (e) { if (e.message !== 'login') msg(e.message); });
      return;
    }
    if (ev.target.closest('[data-notecancel]')) { NOTE.open = null; redraw(); return; }
    if (ev.target.closest('[data-notepost]')) {
      NOTE.busy = true; redraw();
      post('/api/sso/' + s.id + '/note').then(function (r) { s.note = r.note; NOTE.open = null; NOTE.busy = false; lastSig = ''; load(); if (CUR === s) redraw(); })
        .catch(function (e) { NOTE.busy = false; redraw(); if (e.message !== 'login') msg(e.message); });
      return;
    }
    var raw = ev.target.closest('[data-raw]');
    if (raw) {
      var pre = raw.nextElementSibling, open = pre.hidden;
      pre.hidden = !open; raw.setAttribute('aria-expanded', open); raw.textContent = open ? 'Hide original text' : 'Show original text';
    }
  });
})();
