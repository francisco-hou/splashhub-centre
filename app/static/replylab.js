// SplashHub Centre -- Reply Lab (replylab.py): put a ticket number in (by hand),
// pick one to three models (Spark, Haiku 5.5), adjust the prompt, press Draft and
// compare the drafts side by side with
// how long each took and its tokens. Read only: nothing is written to Zendesk;
// a draft is there to read and copy. The prompt can be saved for everyone.
(function () {
  'use strict';

  var MAX_MODELS = 3;
  var S = { info: null, ticket: null, picked: {}, runs: [], savedPrompt: '' };

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
  function clock(ms) { var d = ms ? new Date(ms) : new Date(); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }
  function when(ms) {
    if (!ms) return '';
    var d = new Date(ms), now = new Date();
    return d.toDateString() === now.toDateString() ? 'Today ' + clock(ms) : (d.getMonth() + 1) + '/' + d.getDate() + ' ' + clock(ms);
  }
  var TSTATUS = { new: 'New', open: 'Open', pending: 'Pending', hold: 'On-hold', solved: 'Solved', closed: 'Closed' };

  // ---- the setup: models and the prompt ----------------------------------------------------------
  function drawModels() {
    var ms = S.info.models, n = Object.keys(S.picked).length;
    if (!ms.length) { $('models').innerHTML = '<div class="muted">No model available. ' + esc(S.info.notes.join(' · ')) + '</div>'; return; }
    var groups = {};
    ms.forEach(function (m) { (groups[m.provider] = groups[m.provider] || []).push(m); });
    $('models').innerHTML = Object.keys(groups).map(function (p) {
      return '<div class="rl-mgroup"><div class="rl-mprov">' + esc(p) + '</div>' + groups[p].map(function (m) {
        var on = !!S.picked[m.id];
        return '<label class="rl-model' + (on ? ' on' : '') + '"><input type="checkbox" data-m="' + esc(m.id) + '"' + (on ? ' checked' : '') +
          (!on && n >= MAX_MODELS ? ' disabled' : '') + '> ' + esc(m.label) + '</label>';
      }).join('') + '</div>';
    }).join('') + (S.info.notes.length ? '<div class="muted rl-mnote">' + esc(S.info.notes.join(' · ')) + '</div>' : '');
    canDraft();
  }
  function promptState() {
    var v = $('prompt').value.trim(), def = S.info.default_prompt.trim();
    $('promptState').textContent = v === S.savedPrompt.trim() ? (v === def ? 'The default prompt' : 'The saved prompt') : 'Edited — not saved (this draft uses it anyway)';
    $('promptSave').disabled = v === S.savedPrompt.trim() || !v;
    $('promptReset').disabled = v === def;
  }
  // the team's templates: Closest 3 (by the ticket's words), none, or one picked by hand
  function drawTemplates() {
    var by = {};
    (S.info.templates || []).forEach(function (t) { (by[t.tag] = by[t.tag] || []).push(t); });
    $('tpl').innerHTML = '<option value="auto">Closest 3 to the ticket (picked by its words)</option><option value="none">No template</option>' +
      Object.keys(by).sort().map(function (g) {
        return '<optgroup label="' + esc(g) + '">' + by[g].map(function (t) { return '<option value="' + esc(t.id) + '">' + esc(t.title) + '</option>'; }).join('') + '</optgroup>';
      }).join('');
    tplInfo();
  }
  function tplInfo() {
    var v = $('tpl').value, el = $('tplInfo');
    if (v === 'none') { el.innerHTML = '<span class="muted">The model writes from the prompt alone.</span>'; return; }
    if (v === 'auto') {
      el.innerHTML = S.closest ? (S.closest.length ? 'For this ticket: ' + S.closest.map(function (t) { return '<b>' + esc(t) + '</b>'; }).join(', ') : '<span class="muted">No template shares words with this ticket — the prompt alone.</span>')
        : '<span class="muted">' + (S.ticket ? 'Finding the closest…' : 'Load a ticket to see which.') + '</span>';
      return;
    }
    var t = (S.info.templates || []).filter(function (x) { return x.id === v; })[0];
    el.innerHTML = t ? '<details class="rl-tprev"><summary>Show the template</summary><div class="rl-reply rl-treply">' + esc(t.text) + '</div></details>' : '';
  }
  $('tpl').addEventListener('change', tplInfo);
  function loadClosest(id) {
    S.closest = null; tplInfo();
    api('/api/replylab/closest/' + id).then(function (d) { if (S.ticket && S.ticket.ticket.id === +id) { S.closest = d.titles; tplInfo(); } }).catch(function () {});
  }

  function canDraft() {
    $('draft').disabled = !S.ticket || !Object.keys(S.picked).length || !$('prompt').value.trim();
    $('draftHint').textContent = !S.ticket ? 'Load a ticket first.' : !Object.keys(S.picked).length ? 'Pick at least one model.' : '';
  }

  // ---- the ticket --------------------------------------------------------------------------------
  function drawTicket() {
    var d = S.ticket, t = d.ticket, c = d.conversation || [];
    var LBL = { customer: 'Customer', agent: 'Agent', note: 'Internal note' };
    $('tk').innerHTML = '<div class="rl-th"><div class="rl-tt"><a href="' + esc(S.zd) + '/agent/tickets/' + t.id + '" target="_blank" rel="noopener">#' + t.id + '</a> · ' + esc(t.subject || '(no subject)') + '</div>' +
      '<div class="muted">' + (t.status ? '<span class="tst tst-' + esc(t.status) + '">' + esc(TSTATUS[t.status] || t.status) + '</span> · ' : '') + esc(t.channel || '') +
      ' · ' + c.length + (c.length === 1 ? ' message' : ' messages') + '</div></div>' +
      '<div class="ad-convo rl-convo">' + c.map(function (m) {
        return '<div class="ad-msg ad-' + esc(m.kind) + '"><div class="ad-mh"><b>' + esc(LBL[m.kind] || m.kind) + '</b>' + (m.who ? ' · ' + esc(m.who) : '') +
          (m.ms ? ' <span class="muted">· ' + esc(when(m.ms)) + '</span>' : '') + '</div><div class="ad-mb">' + esc(m.text || '') + '</div></div>';
      }).join('') + '</div>';
    var box = $('tk').querySelector('.rl-convo'); if (box) box.scrollTop = box.scrollHeight;     // the latest message in view
  }
  $('tkForm').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var id = $('tkId').value.replace(/[^\d]/g, '');
    if (!id) return;
    $('tkBtn').disabled = true;
    $('tk').innerHTML = '<div class="pn-loading">Loading ticket #' + esc(id) + ' from Zendesk…</div>';
    api('/api/replylab/ticket/' + id).then(function (d) {
      S.ticket = d; drawTicket(); canDraft(); loadClosest(id);
    }).catch(function (e) { S.ticket = null; canDraft(); $('tk').innerHTML = '<div class="note">Could not load ticket #' + esc(id) + ': ' + esc(e.message) + '</div>'; })
      .then(function () { $('tkBtn').disabled = false; });
  });

  // ---- drafts ------------------------------------------------------------------------------------
  function card(run, d) {
    var head = '<div class="rl-ch"><span class="rl-prov rl-' + esc(d.provider.toLowerCase()) + '">' + esc(d.provider) + '</span> <b>' + esc(d.label) + '</b></div>';
    if (d.busy) return '<div class="rl-card">' + head + '<div class="rl-wait"><span class="at-spin"></span> Writing… <span class="muted" data-tick="' + d.t0 + '"></span></div></div>';
    if (d.error) return '<div class="rl-card rl-err">' + head + '<div class="at-bad">' + esc(d.error) + '</div></div>';
    return '<div class="rl-card">' + head +
      '<div class="rl-meta">' + (d.ms / 1000).toFixed(1) + ' s' + (d.tokens_in != null ? ' · ' + int(d.tokens_in) + ' in / ' + int(d.tokens_out) + ' out tokens' : '') +
        ' · ' + int(d.text.length) + ' characters</div>' +
      (d.templates && d.templates.length ? '<div class="rl-meta">Given: ' + d.templates.map(esc).join(' · ') + '</div>' : '') +
      '<div class="rl-reply">' + esc(d.text) + '</div>' +
      '<div class="frow rl-cact"><button type="button" class="btn btn-sm" data-copy="' + run.n + ':' + d.i + '">Copy</button></div></div>';
  }
  function drawRuns() {
    $('runsCard').hidden = !S.runs.length;
    $('runs').innerHTML = S.runs.map(function (run) {
      return '<div class="rl-run"><div class="rl-rh"><b>Draft ' + run.n + '</b> · ticket #' + run.ticket + ' · ' + esc(run.at) +
        ' · ' + (run.template === 'auto' ? 'closest templates' : run.template === 'none' ? 'no template' : 'template: ' + esc(run.templateLabel)) +
        (run.custom ? ' · <span class="rl-tagp">edited prompt</span>' : '') + (run.notes ? ' · notes: <span class="muted">' + esc(run.notes.slice(0, 120)) + '</span>' : '') +
        (run.include_notes ? '' : ' · <span class="muted">internal notes left out</span>') +
        (run.custom ? ' <button type="button" class="btn-link rl-useprompt" data-prompt="' + run.n + '">Use this prompt again</button>' : '') + '</div>' +
        '<div class="rl-cards">' + run.drafts.map(function (d) { return card(run, d); }).join('') + '</div></div>';
    }).join('');
  }
  setInterval(function () {
    [].forEach.call(document.querySelectorAll('[data-tick]'), function (el) { el.textContent = Math.round((Date.now() - +el.getAttribute('data-tick')) / 1000) + ' s'; });
  }, 1000);
  $('draft').addEventListener('click', function () {
    var ids = Object.keys(S.picked), prompt = $('prompt').value.trim(), notes = $('notes').value.trim();
    var tsel = $('tpl'), run = { n: S.runs.length + 1, ticket: S.ticket.ticket.id, at: clock(), prompt: prompt, custom: prompt !== S.info.default_prompt.trim(),
                notes: notes, include_notes: $('incNotes').checked, template: tsel.value, templateLabel: tsel.options[tsel.selectedIndex].text, drafts: [] };
    run.drafts = ids.map(function (id, i) {
      var m = S.info.models.filter(function (x) { return x.id === id; })[0];
      return { i: i, id: id, label: m.label, provider: m.provider, busy: true, t0: Date.now() };
    });
    S.runs.unshift(run); drawRuns();
    run.drafts.forEach(function (d) {          // each model at once; each card fills in as it answers
      post('/api/replylab/draft', { ticket_id: run.ticket, model: d.id, prompt: prompt, notes: notes, include_notes: run.include_notes, template: run.template })
        .then(function (r) { Object.assign(d, r, { busy: false }); })
        .catch(function (e) { d.busy = false; d.error = e.message; })
        .then(drawRuns);
    });
    $('runsCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  $('runs').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-copy]');
    if (b) {
      var k = b.getAttribute('data-copy').split(':'), run = S.runs.filter(function (r) { return r.n === +k[0]; })[0], d = run && run.drafts[+k[1]];
      if (d && navigator.clipboard) navigator.clipboard.writeText(d.text).then(function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1300); });
      return;
    }
    var p = ev.target.closest('[data-prompt]');
    if (p) {
      var r = S.runs.filter(function (x) { return x.n === +p.getAttribute('data-prompt'); })[0];
      if (r) { $('prompt').value = r.prompt; promptState(); canDraft(); $('prompt').scrollIntoView({ behavior: 'smooth', block: 'center' }); }
    }
  });

  // ---- controls ----------------------------------------------------------------------------------
  $('models').addEventListener('change', function (ev) {
    var id = ev.target.getAttribute('data-m'); if (!id) return;
    if (ev.target.checked) S.picked[id] = true; else delete S.picked[id];
    try { localStorage.setItem('shcReplyLabModels', JSON.stringify(Object.keys(S.picked))); } catch (e) {}
    drawModels();
  });
  $('prompt').addEventListener('input', function () { promptState(); canDraft(); });
  $('promptSave').addEventListener('click', function () {
    var b = this; b.disabled = true;
    post('/api/replylab/prompt', { prompt: $('prompt').value }).then(function (r) {
      S.savedPrompt = r.prompt; $('prompt').value = r.prompt; promptState(); $('promptMsg').textContent = 'Saved — everyone using Reply Lab gets this prompt.';
    }).catch(function (e) { b.disabled = false; $('promptMsg').textContent = 'Could not save: ' + e.message; });
  });
  $('promptReset').addEventListener('click', function () {
    $('prompt').value = S.info.default_prompt; promptState(); canDraft();
    $('promptMsg').textContent = S.savedPrompt.trim() === S.info.default_prompt.trim() ? '' : 'Back to the default — press Save to keep it for everyone.';
  });

  api('/api/replylab').then(function (info) {
    S.info = info; S.savedPrompt = info.prompt; $('prompt').value = info.prompt;
    var last = [];
    try { last = JSON.parse(localStorage.getItem('shcReplyLabModels') || '[]'); } catch (e) {}
    last.forEach(function (id) { if (info.models.some(function (m) { return m.id === id; })) S.picked[id] = true; });
    if (!Object.keys(S.picked).length && info.models.length) S.picked[info.models[0].id] = true;
    drawModels(); drawTemplates(); promptState(); canDraft();
  }).catch(function (e) { $('models').innerHTML = '<div class="note">Could not load Reply Lab: ' + esc(e.message) + '</div>'; });
  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (x) { S.zd = x.zendesk_url || ''; if (S.ticket) drawTicket(); }).catch(function () {});
})();
