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
      if (r.status === 401) { location.href = '/?next=/settings'; throw new Error('login'); }
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function post(path, body) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  }

  fetch('/api/session', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (s) {
    if (s.required && !s.authed) { location.href = '/?next=/settings'; return; }
    $('signOut').hidden = !s.required;
    $('page').hidden = false;
    setup(); settings(); pollImport();
  });
  $('signOut').addEventListener('click', function () {
    fetch('/logout', { method: 'POST', credentials: 'same-origin' }).then(function () { location.href = '/'; });
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

  // ---- scan a ticket now ---------------------------------------------------------------
  $('scanForm').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var tid = $('tid').value.trim().replace(/^#/, '');
    if (!/^\d+$/.test(tid)) { $('scanMsg').textContent = 'Enter a ticket number.'; return; }
    $('scanBtn').disabled = true; $('scanMsg').textContent = '';
    post('/api/scans', { ticket_id: tid, force: $('force').checked })
      .then(function (r) {
        $('scanMsg').innerHTML = 'Queued #' + esc(tid) + '. <a href="/scans#' + r.id + '">Open it on SOS Scans</a>';
        $('tid').value = '';
      })
      .catch(function (e) { if (e.message !== 'login') $('scanMsg').textContent = e.message; })
      .then(function () { $('scanBtn').disabled = false; });
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
  $('impStop').addEventListener('click', function () {
    this.disabled = true; $('impMsg').textContent = 'Stopping after the current ticket…';
    api('/api/import-past/stop', { method: 'POST' }).then(function () { setTimeout(pollImport, 800); });
  });
})();
