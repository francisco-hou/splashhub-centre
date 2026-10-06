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
    setup(); settings(); pollImport(); pollCases();
    // The Price Book's feed settings: SplashHub's own pbsettings.js.
    if (window.PricebookSettingsPage) PricebookSettingsPage.boot(window.CentrePriceClient);
    showSect();
    if (location.hash === '#pricebook') { var u = document.getElementById('pbsUrl'); if (u) u.focus(); }
  });
  // One section at a time, picked on the left (the link's #hash, so it can be shared and survives a reload).
  function showSect() {
    var want = (location.hash || '').slice(1), items = document.querySelectorAll('.set-nav-item');
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

  $('impStop').addEventListener('click', function () {
    this.disabled = true; $('impMsg').textContent = 'Stopping after the current ticket…';
    api('/api/import-past/stop', { method: 'POST' }).then(function () { setTimeout(pollImport, 800); });
  });
})();
