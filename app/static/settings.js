// SplashHub Centre -- Settings page.
//
// The SOS Scans controls that change how the team works: the AI review
// switch, "Auto add internal note", Scan a ticket, and the
// past-request import. Every switch is team-wide and stored on the server.
(function () {
  'use strict';

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function api(path, opts) {
    return fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {})).then(function (r) {
      if (r.status === 401) { location.href = '/logs?next=/settings'; throw new Error('login'); }
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function post(path, body) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  }

  fetch('/api/session', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (s) {
    if (s.required && !s.authed) { location.href = '/logs?next=/settings'; return; }
    $('signOut').hidden = !s.required;
    $('page').hidden = false;
    setup(); settings(); pollImport(); pollCases(); pollKb(); pollPo(); loadNotify(); loadAsk();
    // The Price Book's feed settings: SplashHub's own pbsettings.js.
    if (window.PricebookSettingsPage) PricebookSettingsPage.boot(window.CentrePriceClient);
    showSect();
    if (location.hash === '#pricebook') { var u = document.getElementById('pbsUrl'); if (u) u.focus(); }
  });
  // One section at a time, picked on the left (the link's #hash, so it can be shared and survives a reload).
  function showSect() {
    var want = (location.hash || '').slice(1).split('-')[0], items = document.querySelectorAll('.set-nav-item');   // #sparklog-12345: the section, then a ticket
    if (!document.getElementById('setSect-' + want)) want = items[0].getAttribute('data-sect');
    Array.prototype.forEach.call(items, function (a) { a.classList.toggle('active', a.getAttribute('data-sect') === want); });
    Array.prototype.forEach.call(document.querySelectorAll('.set-sect'), function (s) { s.classList.toggle('active', s.id === 'setSect-' + want); });
  }
  window.addEventListener('hashchange', showSect);

  $('signOut').addEventListener('click', function () {
    fetch('/logout', { method: 'POST', credentials: 'same-origin' }).then(function () { location.href = '/scans'; });
  });

  // What is still missing on Spluki, if anything.
  function setup() {
    api('/api/scan-setup').then(function (s) {
      var el = $('setup');
      if (s.ai_review !== 'on') s.missing = s.missing.filter(function (m) { return !/^AI_/.test(m); });
      if (!s.missing.length) { el.hidden = true; return; }
      el.hidden = false;
      el.innerHTML = '<b>Not fully set up.</b> Missing: ' + s.missing.map(function (m) { return '<code>' + esc(m) + '</code>'; }).join(', ') + '. ' +
        (s.can_scan ? 'Scanning works; Zendesk&rsquo;s trigger can&rsquo;t be verified until the webhook secret is set.'
                    : 'Requests from Zendesk still appear with their details and images; the AI review waits until these are in place.');
    }).catch(function () {});
  }

  // ---- switches ---------------------------------------------------------------------
  function drawSwitch(box, input, state, on) {
    $(input).checked = on;
    $(state).textContent = on ? 'On' : 'Off';
    $(box).classList.toggle('on', on);
  }
  function settings() {
    api('/api/settings').then(function (s) {
      drawSwitch('aiSwitch', 'aiToggle', 'aiState', s.ai_review === 'on');
      drawSwitch('noteSwitch', 'noteToggle', 'noteState', s.auto_note === 'on');
      drawEngine(s.translate_engine);
      drawSpark(s);
      $('sparkState').innerHTML = s.spark ? '<span class="set-ok">&#10003; Spark is connected.</span>'
        : 'Spark isn&rsquo;t connected to SplashHub Centre yet; until it is, translations with Spark will say so.';
    }).catch(function () {});
  }

  $('aiToggle').addEventListener('change', function () {
    var on = this.checked;
    var ask = on
      ? 'Turn on the AI review?\n\nOnly SOS requests that arrive from now on are reviewed by Claude. Requests already on the list, and past requests, stay as they are.'
      : 'Turn off the AI review?\n\nNew SOS requests will be listed with their details and images only.';
    if (!confirm(ask)) { drawSwitch('aiSwitch', 'aiToggle', 'aiState', !on); return; }
    post('/api/ai-review', { on: on })
      .then(function (r) { drawSwitch('aiSwitch', 'aiToggle', 'aiState', r.ai_review === 'on'); setup(); })
      .catch(function () { drawSwitch('aiSwitch', 'aiToggle', 'aiState', !on); });
  });

  // Writing to every reviewed ticket is a bigger step than a button press, so
  // turning it ON asks first.
  $('noteToggle').addEventListener('change', function () {
    var on = this.checked;
    if (on && !confirm('Turn on automatic internal notes?\n\nFrom now on, every finished AI review is added to its Zendesk ticket as an internal note (agents only).')) {
      drawSwitch('noteSwitch', 'noteToggle', 'noteState', false); return;
    }
    post('/api/settings', { auto_note: on })
      .then(function (r) { drawSwitch('noteSwitch', 'noteToggle', 'noteState', r.auto_note === 'on'); })
      .catch(function () { drawSwitch('noteSwitch', 'noteToggle', 'noteState', !on); });
  });

  function drawEngine(e) {
    [].forEach.call($('trEngine').querySelectorAll('button'), function (b) {
      var on = b.getAttribute('data-engine') === e;
      b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
    });
  }
  $('trEngine').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-engine]'); if (!b) return;
    drawEngine(b.getAttribute('data-engine'));
    post('/api/settings', { translate_engine: b.getAttribute('data-engine') })
      .then(function (r) { drawEngine(r.translate_engine); }).catch(settings);
  });

  // ---- Spark: model, thinking, speed test -------------------------------------------
  function drawSpark(s) {
    var sel = $('spModel');
    if (!s.spark || s.spark_error) {
      $('spState').textContent = s.spark_error ? 'Spark answered with a problem: ' + s.spark_error : 'Spark isn’t connected to SplashHub Centre yet.';
      sel.disabled = true; $('spTest').disabled = true; $('thinkToggle').disabled = true;
      return;
    }
    $('spState').innerHTML = '<span class="set-ok">&#10003; Connected.</span> Spark offers ' + s.spark_models.length + ' model' + (s.spark_models.length === 1 ? '' : 's') + ' to SplashHub Centre.';
    sel.innerHTML = s.spark_models.map(function (m) {
      return '<option value="' + esc(m) + '"' + (m === s.spark_model ? ' selected' : '') + '>' + esc(m) + '</option>';
    }).join('');
    drawSwitch('thinkSwitch', 'thinkToggle', 'thinkState', s.spark_thinking === 'on');
  }
  $('spModel').addEventListener('change', function () {
    var m = this.value;
    $('spTestMsg').textContent = '';
    post('/api/settings', { spark_model: m }).catch(function (e) { $('spTestMsg').textContent = e.message; settings(); });
  });
  $('thinkToggle').addEventListener('change', function () {
    var on = this.checked;
    post('/api/settings', { spark_thinking: on })
      .then(function (r) { drawSwitch('thinkSwitch', 'thinkToggle', 'thinkState', r.spark_thinking === 'on'); })
      .catch(function () { drawSwitch('thinkSwitch', 'thinkToggle', 'thinkState', !on); });
  });
  $('spTest').addEventListener('click', function () {
    var b = this, m = $('spModel').value;
    b.disabled = true; $('spTestMsg').textContent = 'Asking ' + m + '…';
    post('/api/spark/test', { model: m })
      .then(function (r) { $('spTestMsg').innerHTML = '<b>' + esc(r.model) + '</b>: ' + r.seconds + ' s' + (r.answer ? ' — “' + esc(r.answer) + '”' : ''); })
      .catch(function (e) { if (e.message !== 'login') $('spTestMsg').textContent = e.message; })
      .then(function () { b.disabled = false; });
  });

  // ---- import past requests (runs on the server; this starts and watches it) -----------
  var impPoll = null;
  function drawImport(st) {
    var msg = $('impMsg');
    $('impBtn').disabled = !!st.running;
    $('impStop').hidden = !st.running;
    $('impStop').disabled = !!st.stop;
    if (st.running) {
      msg.textContent = st.done ? 'Importing… ' + st.done.toLocaleString() + ' checked, ' + st.added.toLocaleString() + ' added' +
        (st.resumed ? ' (carried on after a restart)' : '') : 'Searching Zendesk…';
      clearTimeout(impPoll); impPoll = setTimeout(pollImport, 2000);
    } else if (st.error) {
      msg.textContent = 'Stopped: ' + st.error;
    } else if (st.stopped) {
      msg.textContent = 'Stopped — ' + st.added + ' added so far. Press Import again to carry on from there.';
    } else if (st.finished_ms) {
      msg.textContent = 'Done — ' + st.added.toLocaleString() + ' added, ' + st.skipped.toLocaleString() + ' already listed' +
        (st.failed ? ', ' + st.failed + ' could not be read' : '') + ' (' + st.found.toLocaleString() + ' found).';
    } else {
      msg.textContent = '';
    }
  }
  function pollImport() { api('/api/import-past').then(drawImport).catch(function () {}); }
  $('impBtn').addEventListener('click', function () {
    if (!confirm('Import past SOS requests?\n\nSplashHub Centre searches Zendesk for every past “New SOS package created by…” ticket and lists it on SOS Scans; its images show from Zendesk. No AI review. Tickets already listed are skipped.')) return;
    api('/api/import-past', { method: 'POST' }).then(drawImport).catch(function (e) {
      if (e.message !== 'login') $('impMsg').textContent = e.message;
    });
  });
  // ---- Cases: 2026's tickets for the AI (cases.py; reads Zendesk only) ----------------
  var casePoll = null;
  function day(s) { return s ? new Date(s.length > 10 ? s : s + 'T00:00:00Z').toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : ''; }
  function drawCases(st) {
    var n = (st.count || 0).toLocaleString();
    $('caseState').innerHTML = st.count
      ? '<b>' + n + '</b> cases kept, ' + esc(day(st.first)) + ' &ndash; ' + esc(day(st.last)) + ', ' +
        '<b>' + (st.with_replies || 0).toLocaleString() + '</b> with their conversation.' +
        (st.downloaded ? (st.updated ? ' Last updated ' + esc(new Date(st.updated).toLocaleString()) + '.' : '') : ' Download not finished yet (next: the week of ' + esc(day(st.next_week)) + ').')
      : 'Nothing downloaded yet.';
    $('caseDl').hidden = !!st.downloaded;
    $('caseDl').textContent = st.count && !st.downloaded ? 'Carry on downloading' : 'Download 2026 tickets';
    $('caseUp').hidden = !st.downloaded;
    $('caseDl').disabled = $('caseUp').disabled = !!st.running;
    $('caseStop').hidden = !st.running;
    $('caseStop').disabled = !!st.stop;
    var msg = $('caseMsg');
    if (st.running) {
      msg.textContent = (st.phase === 'replies' ? 'Reading conversations… ' + (st.replies || 0).toLocaleString() + ' read so far.' :
        st.phase === 'tickets' && st.week ? 'Downloading the week of ' + day(st.week) + '… ' + (st.saved ? st.saved.toLocaleString() + ' saved so far.' : '') :
        st.phase === 'updates' ? 'Updating… ' : 'Starting… ') + (st.skipped ? ' ' + st.skipped + ' skipped (unreadable).' : '');
      clearTimeout(casePoll); casePoll = setTimeout(pollCases, 2500);
    } else if (st.error) {
      msg.textContent = 'Stopped: ' + st.error;
    } else if (st.stopped) {
      msg.textContent = 'Stopped. Press the button again to carry on from the same week.';
    } else if (st.finished_ms) {
      msg.textContent = 'Done: ' + (st.saved || 0).toLocaleString() + ' tickets, ' + (st.replies || 0).toLocaleString() + ' conversations' +
        (st.skipped ? ', ' + st.skipped + ' skipped (unreadable)' : '') + '.';
    } else {
      msg.textContent = '';
    }
  }
  function pollCases() { api('/api/cases').then(drawCases).catch(function () {}); }
  $('caseDl').addEventListener('click', function () {
    var b = this;
    b.disabled = true; $('caseMsg').textContent = 'Asking Zendesk how many there are…';
    api('/api/cases?zendesk=1').then(function (st) {
      b.disabled = false;
      var many = st.zendesk_count != null ? 'Zendesk has about ' + st.zendesk_count.toLocaleString() + ' tickets from 2026.\n\n' : '';
      if (!confirm('Download 2026 tickets?\n\n' + many + 'SplashHub Centre reads them from Zendesk: first the tickets a week at a time, then each one\'s conversation (a few hours for the year). It keeps the subject, tags, status, dates, the requester\'s e-mail and organization, and the conversation, with support agents\' names, addresses and signatures taken out. Nothing is written to Zendesk. You can leave this page.')) {
        $('caseMsg').textContent = ''; return;
      }
      post('/api/cases/download').then(drawCases).catch(function (e) { if (e.message !== 'login') $('caseMsg').textContent = e.message; });
    }).catch(function (e) { b.disabled = false; if (e.message !== 'login') $('caseMsg').textContent = e.message; });
  });
  $('caseUp').addEventListener('click', function () {
    post('/api/cases/update').then(drawCases).catch(function (e) { if (e.message !== 'login') $('caseMsg').textContent = e.message; });
  });
  $('caseStop').addEventListener('click', function () {
    this.disabled = true; $('caseMsg').textContent = 'Stopping after the current week…';
    post('/api/cases/stop').then(function () { setTimeout(pollCases, 800); });
  });

  // ---- Notifications: Teams cards (notify.py) ----------------------------------------------
  function drawNotify(n) {
    var last = n.last;
    $('ntState').innerHTML = (n.configured
      ? '<span class="set-ok">&#10003; A Teams workflow link is set.</span>'
      : 'Not connected yet: <code>TEAMS_WEBHOOK_URL</code> isn&rsquo;t set on Spluki.') +
      (last ? ' Last ' + esc(last.what) + ' ' + esc(new Date(last.ms).toLocaleString()) + ': ' + (last.error ? '<span class="sc-err-i">' + esc(last.error) + '</span>' : 'posted.') : '');
    $('ntTest').disabled = !n.configured;
    $('ntKinds').innerHTML = n.kinds.map(function (k) {
      return '<div class="set-row"><div class="set-txt"><div class="set-t">' + esc(k.label) + '</div>' +
        '<div class="frow set-form"><button type="button" class="btn btn-sm" data-run="' + esc(k.key) + '"' + (n.configured ? '' : ' disabled') +
        ' title="Post this alert to Teams now, from the current data, marked as a test">Run now</button><span class="sc-msg" data-runmsg="' + esc(k.key) + '"></span></div></div>' +
        '<label class="aisw"><span class="aisw-sw"><input type="checkbox" data-kind="' + esc(k.key) + '"' + (k.on ? ' checked' : '') +
        ' aria-label="' + esc(k.label) + '"><span class="aisw-track"></span></span><span class="aisw-state">' + (k.on ? 'On' : 'Off') + '</span></label></div>';
    }).join('');
    if (n.languages && !LANG_DIRTY) drawLangs(n.languages);
  }
  // ---- Language routing table
  var LANG_DIRTY = false;
  function langRow(r) {
    return '<tr><td><input type="checkbox" class="nt-on"' + (r.on ? ' checked' : '') + ' aria-label="On"></td>' +
      '<td><input type="text" class="sc-input nt-l" value="' + esc(r.lang || '') + '" aria-label="Language"></td>' +
      '<td><input type="text" class="sc-input nt-t" value="' + esc((r.tags || []).join(', ')) + '" spellcheck="false" aria-label="Tags"></td>' +
      '<td><input type="text" class="sc-input nt-p" value="' + esc((r.people || []).map(function (p) { return p.email; }).join(', ')) + '" spellcheck="false" placeholder="name@splashtop.com, \u2026" aria-label="People"></td>' +
      '<td><button type="button" class="btn btn-icon btn-sm nt-del" title="Remove" aria-label="Remove">&times;</button></td></tr>';
  }
  function drawLangs(cfg) {
    $('ntQuery').value = cfg.query || '';
    $('ntSpark').checked = cfg.spark !== false;
    $('ntRows').innerHTML = (cfg.rows || []).map(langRow).join('');
  }
  function readLangs() {
    var rows = Array.prototype.map.call($('ntRows').querySelectorAll('tr'), function (tr) {
      var split = function (sel) { return tr.querySelector(sel).value.split(/[,;\s]+/).map(function (x) { return x.trim(); }).filter(Boolean); };
      return { on: tr.querySelector('.nt-on').checked, lang: tr.querySelector('.nt-l').value.trim(), tags: split('.nt-t'),
               people: split('.nt-p').map(function (e) { return { email: e }; }) };
    });
    return { query: $('ntQuery').value.trim(), spark: $('ntSpark').checked, rows: rows.filter(function (r) { return r.lang; }) };
  }
  $('ntRows').addEventListener('input', function () { LANG_DIRTY = true; $('ntLangMsg').textContent = 'Not saved yet.'; });
  $('ntRows').addEventListener('change', function () { LANG_DIRTY = true; $('ntLangMsg').textContent = 'Not saved yet.'; });
  $('ntQuery').addEventListener('input', function () { LANG_DIRTY = true; $('ntLangMsg').textContent = 'Not saved yet.'; });
  $('ntSpark').addEventListener('change', function () { LANG_DIRTY = true; $('ntLangMsg').textContent = 'Not saved yet.'; });
  $('ntRows').addEventListener('click', function (ev) {
    var d = ev.target.closest('.nt-del'); if (!d) return;
    d.closest('tr').remove(); LANG_DIRTY = true; $('ntLangMsg').textContent = 'Not saved yet.';
  });
  $('ntAdd').addEventListener('click', function () {
    $('ntRows').insertAdjacentHTML('beforeend', langRow({ on: false, lang: '', tags: [], people: [] }));
    LANG_DIRTY = true;
  });
  $('ntSave').addEventListener('click', function () {
    var b = this; b.disabled = true; $('ntLangMsg').textContent = 'Saving\u2026';
    var sent = readLangs();
    post('/api/notify/languages', sent).then(function (n) {
      b.disabled = false; LANG_DIRTY = false; drawNotify(n);
      var dropped = sent.rows.reduce(function (t, r) { return t + r.people.length; }, 0) -
        n.languages.rows.reduce(function (t, r) { return t + r.people.length; }, 0);
      $('ntLangMsg').textContent = 'Saved.' + (dropped > 0 ? ' ' + dropped + ' address' + (dropped === 1 ? '' : 'es') + ' left out: only @splashtop.com people can be mentioned.' : '');
    }).catch(function (e) { b.disabled = false; if (e.message !== 'login') $('ntLangMsg').textContent = e.message; });
  });
  $('ntKinds').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-run]'); if (!b) return;
    var k = b.getAttribute('data-run'), m = document.querySelector('[data-runmsg="' + k + '"]');
    b.disabled = true; m.textContent = 'Posting\u2026';
    post('/api/notify/run', { kind: k }).then(function (r) {
      b.disabled = false; m.textContent = (r.posted ? 'Posted' : 'Nothing posted') + (r.note ? ' \u2014 ' + r.note : '') + '.';
    }).catch(function (e) { b.disabled = false; if (e.message !== 'login') m.textContent = e.message; });
  });
  function loadNotify() { api('/api/notify').then(drawNotify).catch(function () {}); }
  $('ntKinds').addEventListener('change', function (ev) {
    var c = ev.target.closest('[data-kind]'); if (!c) return;
    c.disabled = true;
    post('/api/notify', { kind: c.getAttribute('data-kind'), on: c.checked }).then(drawNotify)
      .catch(function (e) { c.checked = !c.checked; c.disabled = false; if (e.message !== 'login') $('ntMsg').textContent = e.message; });
  });
  $('ntTest').addEventListener('click', function () {
    var b = this; b.disabled = true; $('ntMsg').textContent = 'Sending\u2026';
    post('/api/notify/test').then(function (r) { b.disabled = false; $('ntMsg').textContent = 'Sent \u2014 check the channel.'; drawNotify(r.settings); })
      .catch(function (e) { b.disabled = false; if (e.message !== 'login') $('ntMsg').textContent = e.message; });
  });

  // ---- Ask from Teams (teamsask.py) ---------------------------------------------------------------
  function drawAsk(a) {
    $('taOn').checked = !!a.on; $('taState').textContent = a.on ? 'On' : 'Off';
    if (document.activeElement !== $('taWord')) $('taWord').value = a.word || 'centre';
    var f = a.flow || {};
    $('taFlow').innerHTML = '<div class="ta-h">The flow&rsquo;s HTTP step</div><dl class="po-dl">' +
      '<dt>Method</dt><dd><code>POST</code></dd>' +
      '<dt>URI</dt><dd>' + (f.url ? '<code class="ta-copy">' + esc(f.url) + '</code>' : '<span class="muted">this release has no webhook intake</span>') + '</dd>' +
      '<dt>Headers</dt><dd><code>Content-Type</code>: <code>application/json</code><br><code>X-Centre-Key</code>: ' +
        (a.key ? '<code class="ta-copy ta-key">' + esc(a.key) + '</code> <span class="sc-err-i">copy it now \u2014 it isn&rsquo;t shown again</span>'
               : (a.has_key ? '<span class="muted">the key you created (press Create a key for a new one; the old one stops working)</span>' : '<span class="muted">press Create a key</span>')) + '</dd>' +
      '<dt>Body</dt><dd><code>' + esc(f.body || '@{triggerBody()}') + '</code> <span class="muted">(Expression tab)</span></dd></dl>';
  }
  function loadAsk() { api('/api/teams-ask').then(drawAsk).catch(function () {}); }
  $('taOn').addEventListener('change', function () {
    post('/api/teams-ask', { on: this.checked }).then(drawAsk).catch(function (e) { if (e.message !== 'login') $('taMsg').textContent = e.message; });
  });
  $('taSave').addEventListener('click', function () {
    post('/api/teams-ask', { word: $('taWord').value }).then(function (a) { drawAsk(a); $('taMsg').textContent = 'Saved.'; })
      .catch(function (e) { if (e.message !== 'login') $('taMsg').textContent = e.message; });
  });
  $('taKey').addEventListener('click', function () {
    if (!confirm('Create a new key? The flow must then use the new one; an older key stops working.')) return;
    post('/api/teams-ask/key').then(function (a) { drawAsk(a); $('taMsg').textContent = 'New key created: copy it into the flow now.'; })
      .catch(function (e) { if (e.message !== 'login') $('taMsg').textContent = e.message; });
  });

  // ---- PO Requests: every "Provision Details" ticket, all years (po.py; reads Zendesk only) ----
  var poPoll = null;
  function drawPo(st) {
    $('poState').innerHTML = st.count
      ? '<b>' + st.count.toLocaleString() + '</b> PO requests (' + (st.with_convo || 0).toLocaleString() + ' with their conversation), ' + esc(day(st.first_ms ? new Date(st.first_ms).toISOString().slice(0, 10) : '')) + ' &ndash; ' +
        esc(day(st.last_ms ? new Date(st.last_ms).toISOString().slice(0, 10) : '')) + '.' + (st.synced_ms ? ' Last updated ' + esc(new Date(st.synced_ms).toLocaleString()) + '.' : '')
      : 'Nothing imported yet.';
    $('poImport').hidden = !!st.synced_ms;
    $('poUpdate').hidden = !st.synced_ms;
    $('poImport').disabled = $('poUpdate').disabled = !!st.running;
    $('poStop').hidden = !st.running;
    var msg = $('poMsg');
    if (st.running) {
      msg.textContent = st.phase === 'conversations'
        ? 'Reading each PO ticket\u2019s conversation\u2026 ' + (st.replies || 0).toLocaleString() + ' read so far (a few a second; you can leave this page).'
        : (st.kind === 'update' ? 'Updating' : 'Importing') + '\u2026 ' + (st.seen || 0).toLocaleString() + ' tickets read, ' + (st.saved || 0).toLocaleString() + ' PO requests saved.';
      clearTimeout(poPoll); poPoll = setTimeout(pollPo, 2000);
    } else if (st.error) {
      msg.textContent = 'Stopped: ' + st.error;
    } else if (st.finished_ms) {
      msg.textContent = 'Done: ' + (st.saved || 0).toLocaleString() + ' PO requests saved.';
    } else {
      msg.textContent = '';
    }
  }
  function pollPo() { api('/api/po').then(drawPo).catch(function () {}); }
  $('poImport').addEventListener('click', function () {
    this.disabled = true; $('poMsg').textContent = 'Starting\u2026';
    post('/api/po/import').then(drawPo).catch(function (e) { $('poImport').disabled = false; if (e.message !== 'login') $('poMsg').textContent = e.message; });
  });
  $('poUpdate').addEventListener('click', function () {
    post('/api/po/update').then(drawPo).catch(function (e) { if (e.message !== 'login') $('poMsg').textContent = e.message; });
  });
  $('poStop').addEventListener('click', function () {
    this.disabled = true;
    post('/api/po/stop').then(function () { setTimeout(pollPo, 800); });
  });

  // ---- Zendesk Knowledge Base: the Help Center's articles (kb.py; reads Zendesk only) ----
  var kbPoll = null;
  function drawKb(st) {
    $('kbState').innerHTML = st.articles
      ? '<b>' + st.articles.toLocaleString() + '</b> articles in <b>' + st.languages + '</b> language' + (st.languages === 1 ? '' : 's') +
        (st.rows > st.articles ? ' (' + st.rows.toLocaleString() + ' counting translations).' : '.') + (st.synced_ms ? ' Last synced ' + esc(new Date(st.synced_ms).toLocaleString()) + '.' : '')
      : 'Nothing downloaded yet.';
    $('kbSync').textContent = st.synced_ms ? 'Sync now' : 'Download the Knowledge Base';
    $('kbSync').disabled = !!st.running;
    $('kbStop').hidden = !st.running;
    var msg = $('kbMsg');
    if (st.running) {
      msg.textContent = 'Downloading' + (st.locale ? ' ' + st.locale : '') + '\u2026 ' + (st.saved || 0).toLocaleString() + ' saved so far.';
      clearTimeout(kbPoll); kbPoll = setTimeout(pollKb, 2000);
    } else if (st.error) {
      msg.textContent = 'Stopped: ' + st.error;
    } else if (st.finished_ms) {
      msg.textContent = 'Done: ' + (st.saved || 0).toLocaleString() + ' articles and translations.';
    } else {
      msg.textContent = '';
    }
  }
  function pollKb() { api('/api/kb').then(drawKb).catch(function () {}); }
  $('kbSync').addEventListener('click', function () {
    this.disabled = true; $('kbMsg').textContent = 'Starting\u2026';
    post('/api/kb/sync').then(drawKb).catch(function (e) { $('kbSync').disabled = false; if (e.message !== 'login') $('kbMsg').textContent = e.message; });
  });
  $('kbStop').addEventListener('click', function () {
    this.disabled = true; $('kbMsg').textContent = 'Stopping after the current page\u2026';
    post('/api/kb/stop').then(function () { setTimeout(pollKb, 800); });
  });

  $('impStop').addEventListener('click', function () {
    this.disabled = true; $('impMsg').textContent = 'Stopping after the current ticket…';
    api('/api/import-past/stop', { method: 'POST' }).then(function () { setTimeout(pollImport, 800); });
  });
})();

/* Settings > Look > Theme: Automatic, Off, or one holiday kept on. A choice
   is saved for everyone and shown on this page at once. */
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  if (!$('thGrid')) return;
  var T = null;
  function fmt(d) { var x = new Date(d + 'T12:00:00'); return x.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }); }
  function send(body) {
    $('thMsg').textContent = 'Saving…';
    fetch('/api/theme', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; }); })
      .then(function (t) { draw(t); if (window.shcTheme) window.shcTheme.apply(t); $('thMsg').textContent = 'Saved — everyone sees it on their next page.'; })
      .catch(function (e) { $('thMsg').textContent = 'Could not save: ' + e.message; });
  }
  function draw(t) {
    T = t;
    var opts = [{ key: 'auto', label: 'Automatic', emoji: '📅' }, { key: 'off', label: 'Off', emoji: '⬜' }].concat(t.themes);
    $('thGrid').innerHTML = opts.map(function (o) {
      return '<button type="button" class="th-opt' + (o.key === t.choice ? ' on' : '') + '" data-k="' + o.key + '" aria-pressed="' + (o.key === t.choice) + '">' +
        '<span class="th-e">' + o.emoji + '</span>' + o.label + '</button>';
    }).join('');
    var now = t.active ? 'Showing now: <b>' + t.active.emoji + ' ' + t.active.label + '</b>.' : 'No theme showing now.';
    var next = t.choice === 'auto' && t.upcoming.length ? ' Next: ' + t.upcoming.filter(function (u) { return !t.active || u.key !== t.active.key; }).slice(0, 3)
      .map(function (u) { return u.emoji + ' ' + u.label + ' (' + fmt(u.from) + ')'; }).join(', ') + '.' : '';
    $('thNext').innerHTML = now + next;
    [].forEach.call($('thFx').querySelectorAll('button'), function (b) {
      var on = (b.getAttribute('data-fx') === '1') === t.fx;
      b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
    });
  }
  $('thGrid').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-k]'); if (b && T && b.getAttribute('data-k') !== T.choice) send({ choice: b.getAttribute('data-k') });
  });
  $('thFx').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-fx]'); if (b) send({ fx: b.getAttribute('data-fx') === '1' });
  });
  fetch('/api/theme', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(draw).catch(function () {});
})();

/* Settings > AutoTag: on / off, skip phrases, always-Japanese requesters,
   and a check for new tickets now. Writing to Zendesk by itself stays off. */
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  if (!$('atOn')) return;
  function call(path, body) {
    return fetch(path, { method: body ? 'POST' : 'GET', credentials: 'same-origin', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; }); });
  }
  function draw(s) {
    [].forEach.call($('atOn').querySelectorAll('button'), function (b) {
      var on = (b.getAttribute('data-on') === '1') === s.on;
      b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
    });
    $('atState').textContent = (s.on ? 'On' : 'Off') + ' · tickets created from ' + s.since + ' on, read every 2 minutes · ' +
      s.total.toLocaleString() + ' read so far' + (s.error ? ' · last round: ' + s.error : '') + '. Spark is free.';
    if (document.activeElement !== $('atSkip')) $('atSkip').value = s.skip.join('\n');
    if (document.activeElement !== $('atJp')) $('atJp').value = s.jp_emails.join('\n');
  }
  function save(body, msg) {
    $('atMsg').textContent = 'Saving…';
    call('/api/autotag/settings', body).then(function (s) { draw(s); $('atMsg').textContent = msg; })
      .catch(function (e) { $('atMsg').textContent = 'Could not save: ' + e.message; });
  }
  $('atOn').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-on]'); if (b) save({ on: b.getAttribute('data-on') === '1' }, 'Saved.');
  });
  $('atSave').addEventListener('click', function () { save({ skip: $('atSkip').value, jp_emails: $('atJp').value }, 'Saved — used from the next round.'); });
  $('atRun').addEventListener('click', function () {
    call('/api/autotag/run', {}).then(function () { $('atMsg').textContent = 'Checking now — new tickets show on the AutoTag page in a minute.'; })
      .catch(function (e) { $('atMsg').textContent = 'Could not start: ' + e.message; });
  });
  call('/api/autotag').then(draw).catch(function () {});
})();


/* Settings > AI > Spark activity: every Spark decision (sparklog.py), newest
   first; a row opens what Spark was given, its answer, its reasoning and what
   Centre did. #sparklog-12345 opens it on that ticket. */
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  if (!$('slRows')) return;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  var S = { area: '', changed: '', ticket: '', page: 0 }, ZD = '', OPEN = null, seq = 0;
  function when(ms) { var d = new Date(ms); return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }
  function get(p) { return fetch(p, { credentials: 'same-origin' }).then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; }); }); }
  function tlinks(ts) {
    return ts.length ? ts.slice(0, 2).map(function (t) { return ZD ? '<a href="' + esc(ZD) + '/agent/tickets/' + t + '" target="_blank" rel="noopener">#' + t + '</a>' : '#' + t; }).join(' ') +
      (ts.length > 2 ? ' <span class="muted">+' + (ts.length - 2) + '</span>' : '') : '<span class="muted">—</span>';
  }
  function fromHash() {
    var m = /^#sparklog-(\d+)/.exec(location.hash || '');
    if (m && m[1] !== S.ticket) { S.ticket = m[1]; $('slTicket').value = m[1]; S.page = 0; load(); }
  }
  function load() {
    var my = ++seq, q = ['page=' + S.page];
    ['area', 'changed', 'ticket'].forEach(function (k) { if (S[k]) q.push(k + '=' + encodeURIComponent(S[k])); });
    get('/api/spark-log?' + q.join('&')).then(function (d) {
      if (my !== seq) return;
      var sel = $('slArea');
      if (sel.options.length <= 1) {
        sel.innerHTML = '<option value="">Every area</option>' + Object.keys(d.areas).map(function (k) {
          return '<option value="' + esc(k) + '">' + esc(d.areas[k]) + (d.counts[k] ? ' (' + d.counts[k] + ')' : '') + '</option>';
        }).join('');
        sel.value = S.area;
      }
      if (d.stats) drawStats(d.stats);
      $('slCount').textContent = d.total ? d.total.toLocaleString() + (d.total === 1 ? ' decision' : ' decisions') : '';
      $('slRows').innerHTML = d.rows.length ? d.rows.map(function (r) {
        return '<tr class="sl-row' + (r.error ? ' sl-err' : '') + '" data-id="' + r.id + '" tabindex="0"><td class="when">' + esc(when(r.ts_ms)) + '</td>' +
          '<td>' + esc(r.area_label) + '</td><td>' + tlinks(r.tickets) + '</td>' +
          '<td class="sl-dec">' + (r.error ? '<span class="at-bad">Failed: ' + esc(r.error) + '</span>' : r.decision ? (r.changed ? '<b>' + esc(r.decision) + '</b>' : esc(r.decision)) : '<span class="muted">—</span>') + '</td>' +
          '<td class="r muted">' + secs(r.ms) + '</td></tr>' +
          (OPEN === r.id ? '<tr class="sl-open"><td colspan="5" id="slDetail"><div class="pn-loading">Loading…</div></td></tr>' : '');
      }).join('') : '<tr class="empty-row"><td colspan="5">' + (S.area || S.changed || S.ticket ? 'Nothing matches.' : 'No Spark decisions yet.') + '</td></tr>';
      var pages = Math.ceil(d.total / d.per_page);
      $('slPager').hidden = pages <= 1;
      $('slPagerTxt').textContent = 'Page ' + (d.page + 1) + ' of ' + pages;
      $('slPrev').disabled = d.page <= 0; $('slNext').disabled = d.page + 1 >= pages;
      if (OPEN) detail(OPEN);
    }).catch(function (e) { $('slRows').innerHTML = '<tr class="empty-row"><td colspan="5">Could not load: ' + esc(e.message) + '</td></tr>'; });
  }
  function secs(ms) { return ms == null ? '—' : ms < 1000 ? ms + ' ms' : (ms / 1000).toFixed(1) + ' s'; }
  function drawStats(st) {
    var t = function (label, value, sub, cls) {
      return '<div class="stat"><div class="stat-label">' + label + '</div><div class="stat-value ' + (cls || '') + '">' + value + '</div><div class="stat-sub">' + sub + '</div></div>';
    };
    var d = st.day;
    $('slStats').innerHTML = t('Decisions · 24 h', d.n.toLocaleString(), d.tickets.toLocaleString() + ' tickets read · ' + d.changed + ' changed something') +
      t('Average answer', secs(d.avg_ms), 'from asking to answer') + t('Slowest', secs(d.max_ms), 'in the last 24 h') +
      t('Failed', d.failed, d.failed ? 'retried on the next round' : 'none', d.failed ? 'ov-o' : '');
    var tb = $('slAreas');
    tb.hidden = !st.areas.length;
    tb.tBodies[0].innerHTML = st.areas.map(function (a) {
      return '<tr><td>' + esc(a.label) + '</td><td class="n">' + a.n + '</td><td class="n">' + secs(a.avg_ms) + '</td><td class="n">' + (a.per_ticket_ms != null ? secs(a.per_ticket_ms) : '—') +
        '</td><td class="n">' + secs(a.max_ms) + '</td><td class="n">' + a.changed + '</td><td class="n">' + (a.failed ? '<span class="at-bad">' + a.failed + '</span>' : '0') + '</td></tr>';
    }).join('');
  }
  function block(title, body, open) {
    return '<details class="sl-part"' + (open ? ' open' : '') + '><summary>' + title + '</summary><pre class="sl-pre">' + esc(body || '') + '</pre></details>';
  }
  function detail(id) {
    get('/api/spark-log/' + id).then(function (r) {
      var el = $('slDetail'); if (!el || OPEN !== id) return;
      el.innerHTML = '<div class="sl-d">' +
        '<div class="muted">' + esc(r.area_label) + ' · ' + esc(r.model || '') + ' · took ' + secs(r.ms) +
          (r.n_tickets > 1 ? ' for ' + r.n_tickets + ' tickets (' + secs(Math.round(r.ms / r.n_tickets)) + ' each)' : '') +
          (r.tokens_in ? ' · read ' + r.tokens_in.toLocaleString() + ' tokens, wrote ' + (r.tokens_out || 0).toLocaleString() : '') + '</div>' +
        (r.decision ? '<div><span class="pn-k">What Centre did</span> ' + esc(r.decision) + '</div>' : '') +
        (r.error ? '<div class="at-bad">' + esc(r.error) + '</div>' : '') +
        block('Spark&rsquo;s answer', r.answer, true) +
        (r.thinking ? block('How it was thinking', r.thinking, true)
          : '<div class="sl-note">No reasoning kept &mdash; thinking is off in <a href="#spark">Settings &rsaquo; Spark</a>. The short reason inside the answer is what it gave.</div>') +
        block('What it read', r.input, false) + block('The question it was asked', r.question, false) + '</div>';
    }).catch(function (e) { var el = $('slDetail'); if (el) el.textContent = 'Could not load: ' + e.message; });
  }
  $('slRows').addEventListener('click', function (ev) {
    if (ev.target.closest('a')) return;
    var tr = ev.target.closest('.sl-row'); if (!tr) return;
    var id = +tr.getAttribute('data-id');
    OPEN = OPEN === id ? null : id; load();
  });
  $('slArea').addEventListener('change', function () { S.area = this.value; S.page = 0; OPEN = null; load(); });
  $('slChanged').addEventListener('change', function () { S.changed = this.value; S.page = 0; OPEN = null; load(); });
  var tT = 0;
  $('slTicket').addEventListener('input', function () { clearTimeout(tT); var v = this.value.replace(/\D/g, ''); tT = setTimeout(function () { S.ticket = v; S.page = 0; OPEN = null; load(); }, 300); });
  $('slPrev').addEventListener('click', function () { if (S.page > 0) { S.page--; OPEN = null; load(); } });
  $('slNext').addEventListener('click', function () { S.page++; OPEN = null; load(); });
  window.addEventListener('hashchange', fromHash);
  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; }).then(function (x) { ZD = x.zendesk_url || ''; }).catch(function () {});
  fromHash();
  if (!S.ticket) load();
})();
