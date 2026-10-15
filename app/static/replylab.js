// SplashHub Centre -- Reply Lab (replylab.py). Three tabs:
//  Draft: put a ticket number in (by hand), pick one to three models (Spark,
//    Haiku 5.5) and compare the drafts side by side with how long each took and
//    its tokens. Read only: nothing is written to Zendesk; a draft is there to
//    read and copy. Drafts use the text in the Prompt tab, saved or not.
//  Prompt: the reply prompt -- save (used from the next draft, here and in the
//    ticket sidebar), compare with the default or an earlier version, History,
//    and the sidebar's Spark model.
//  Templates: the team's reply templates -- edit, add, delete (Recently
//    deleted), and which templates a customer's words would get.
(function () {
  'use strict';

  var MAX_MODELS = 3;
  var S = { info: null, ticket: null, picked: {}, runs: [], tab: 'draft', pBase: '', compare: null, histOpen: false, tId: null, tBase: null };

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
  // the prompt on the Draft tab: which one the drafts use; it is edited on the Prompt tab
  function drawPSum() {
    var I = S.info, dirty = pDirty();
    $('pSum').innerHTML = '<span class="rl-psn">' + (dirty ? '<span class="pt-dirty"><i></i>Your unsaved edit</span>' :
      I.is_default ? '<b>The default prompt</b>' : '<b>The saved prompt</b> <span class="muted">· ' + esc(when(I.updated_ms)) + (I.updated_by ? ' · ' + esc(who(I.updated_by)) : '') + '</span>') +
      '</span><button type="button" class="btn btn-sm" id="pSumEdit">' + (dirty ? 'Back to the edit' : 'Edit prompt') + '</button>';
    $('pTabDot').hidden = !dirty;
  }
  document.addEventListener('click', function (ev) { if (ev.target.closest('#pSumEdit')) setTab('prompt'); });
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
    $('draft').disabled = !S.ticket || !Object.keys(S.picked).length || !$('pText').value.trim();
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
      (d.template_used ? '<div class="rl-used' + (d.similarity >= 90 ? ' ok' : '') + '">Template: <b>' + esc(d.template_used) + '</b> · ' + d.similarity + '% the same</div>'
        : d.templates && d.templates.length ? '<div class="rl-meta">Given: ' + d.templates.map(esc).join(' · ') + ' — none used</div>' : '') +
      '<div class="rl-reply">' + esc(d.text) + '</div>' +
      '<div class="frow rl-cact"><button type="button" class="btn btn-sm" data-copy="' + run.n + ':' + d.i + '">Copy</button></div></div>';
  }
  function drawRuns() {
    $('runsCard').hidden = !S.runs.length;
    $('runs').innerHTML = S.runs.map(function (run) {
      return '<div class="rl-run"><div class="rl-rh"><b>Draft ' + run.n + '</b> · ticket #' + run.ticket + ' · ' + esc(run.at) +
        ' · ' + (run.template === 'auto' ? 'closest templates' : run.template === 'none' ? 'no template' : 'template: ' + esc(run.templateLabel)) +
        (run.custom ? ' · <span class="rl-tagp">unsaved prompt</span>' : '') + (run.notes ? ' · notes: <span class="muted">' + esc(run.notes.slice(0, 120)) + '</span>' : '') +
        (run.include_notes ? '' : ' · <span class="muted">internal notes left out</span>') +
        (run.custom ? ' <button type="button" class="btn-link rl-useprompt" data-prompt="' + run.n + '">Use this prompt again</button>' : '') + '</div>' +
        '<div class="rl-cards">' + run.drafts.map(function (d) { return card(run, d); }).join('') + '</div></div>';
    }).join('');
  }
  setInterval(function () {
    [].forEach.call(document.querySelectorAll('[data-tick]'), function (el) { el.textContent = Math.round((Date.now() - +el.getAttribute('data-tick')) / 1000) + ' s'; });
  }, 1000);
  $('draft').addEventListener('click', function () {
    var ids = Object.keys(S.picked), prompt = $('pText').value.trim(), notes = $('notes').value.trim();
    var tsel = $('tpl'), run = { n: S.runs.length + 1, ticket: S.ticket.ticket.id, at: clock(), prompt: prompt, custom: prompt !== S.info.prompt.trim(),
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
      if (r) { $('pText').value = r.prompt; pSync(); setTab('prompt'); toast('That draft’s prompt is in the editor — Save prompt keeps it for everyone.'); }
    }
  });

  // ---- controls ----------------------------------------------------------------------------------
  $('models').addEventListener('change', function (ev) {
    var id = ev.target.getAttribute('data-m'); if (!id) return;
    if (ev.target.checked) S.picked[id] = true; else delete S.picked[id];
    try { localStorage.setItem('shcReplyLabModels', JSON.stringify(Object.keys(S.picked))); } catch (e) {}
    drawModels();
  });
  // ---- helpers for the Prompt and Templates tabs ----------------------------------------------
  function who(by) { return by ? String(by).split('@')[0].replace(/[._]/g, ' ') : ''; }

  var toastT = null;
  function toast(msg, bad) {
    var t = $('toast');
    t.textContent = msg; t.hidden = false; t.classList.toggle('bad', !!bad);
    t.classList.remove('pt-pop'); void t.offsetWidth; t.classList.add('pt-pop');
    clearTimeout(toastT); toastT = setTimeout(function () { t.hidden = true; }, 3200);
  }
  function busy(btn, on, label) {
    if (on) { btn.dataset.label = btn.textContent; btn.textContent = label || 'Saving…'; btn.disabled = true; }
    else { btn.textContent = btn.dataset.label || btn.textContent; }
  }

  // ---- a word diff: what changed between two texts ------------------------------------------------
  function diff(a, b) {
    var A = a.split(/(\s+)/), B = b.split(/(\s+)/), pre = 0, suf = 0;
    while (pre < A.length && pre < B.length && A[pre] === B[pre]) pre++;
    while (suf < A.length - pre && suf < B.length - pre && A[A.length - 1 - suf] === B[B.length - 1 - suf]) suf++;
    var a2 = A.slice(pre, A.length - suf), b2 = B.slice(pre, B.length - suf), n = a2.length, m = b2.length, out = [];
    if (n * m > 6e6) {                                   // very different: show it as one change
      out.push(['d', a2.join('')], ['i', b2.join('')]);
    } else {
      var L = new Uint16Array((n + 1) * (m + 1)), i, j;
      for (i = n - 1; i >= 0; i--) for (j = m - 1; j >= 0; j--)
        L[i * (m + 1) + j] = a2[i] === b2[j] ? L[(i + 1) * (m + 1) + j + 1] + 1 : Math.max(L[(i + 1) * (m + 1) + j], L[i * (m + 1) + j + 1]);
      i = 0; j = 0;
      while (i < n || j < m) {
        if (i < n && j < m && a2[i] === b2[j]) { out.push(['s', a2[i]]); i++; j++; }
        else if (j < m && (i === n || L[i * (m + 1) + j + 1] >= L[(i + 1) * (m + 1) + j])) { out.push(['i', b2[j]]); j++; }
        else { out.push(['d', a2[i]]); i++; }
      }
    }
    var html = esc(A.slice(0, pre).join('')), cur = null, buf = '', adds = 0, dels = 0;
    function flush() {
      if (!buf) return;
      html += cur === 's' ? esc(buf) : '<' + (cur === 'i' ? 'ins' : 'del') + '>' + esc(buf) + '</' + (cur === 'i' ? 'ins' : 'del') + '>';
      buf = '';
    }
    out.forEach(function (o) {
      if (o[0] !== cur) { flush(); cur = o[0]; }
      buf += o[1];
      if (o[0] === 'i' && /\S/.test(o[1])) adds++;
      if (o[0] === 'd' && /\S/.test(o[1])) dels++;
    });
    flush();
    return { html: html + esc(A.slice(A.length - suf).join('')), adds: adds, dels: dels };
  }

  // ---- the Prompt tab -----------------------------------------------------------------------
  var PROMPT = { name: 'The reply prompt', engine: 'Spark · Claude', where: 'Reply Lab drafts and the ticket sidebar’s Reply Lab tile',
    about: 'How a reply is written: the tone, when to use a team template word for word, what never to promise. Saved, it is used from the next draft.',
    fixed: 'After this the model gets the ticket’s conversation, the closest team templates and the agent’s notes. The first line it writes (TEMPLATE: ...) is how Reply Lab shows which template was used, so keep that rule in.',
    placeholders: [] };
  function P() {
    var I = S.info;
    return { name: PROMPT.name, engine: PROMPT.engine, where: PROMPT.where, about: PROMPT.about, fixed: PROMPT.fixed, placeholders: [],
             text: I.prompt, 'default': I.default_prompt, is_default: I.is_default, updated_ms: I.updated_ms, updated_by: I.updated_by, history: I.history };
  }
  function pDirty() { return !!S.info && $('pText').value !== S.pBase; }
  function openPrompt() {
    var p = P();
    S.pBase = p.text; S.compare = null; S.histOpen = false;
    $('pName').textContent = p.name;
    $('pWhere').innerHTML = '<span class="pt-eng">' + esc(p.engine) + '</span> Used in ' + esc(p.where);
    $('pAbout').textContent = p.about;
    $('pText').value = p.text; $('pNote').value = '';
    $('pFixedT').textContent = p.fixed;
    $('pPh').innerHTML = p.placeholders.length ? '<span class="muted">Fills in:</span>' + p.placeholders.map(function (ph) {
      return '<button type="button" class="pt-chip" data-ph="' + esc(ph.name) + '" title="Insert at the cursor: ' + esc(ph.about) + '">' + esc(ph.name) + '</button>';
    }).join('') : '';
    drawPState(); drawHist(); drawCompare(); pSync();
  }
  function drawPState() {
    var p = P();
    $('pState').innerHTML = p.is_default
      ? '<span class="pt-badge">Default text</span>'
      : '<span class="pt-badge pt-badge-ed">Edited</span><span class="muted">' + esc(when(p.updated_ms)) + (p.updated_by ? ' · ' + esc(who(p.updated_by)) : '') + '</span>';
    $('pReset').disabled = p.is_default;
    $('pCompare').hidden = p.is_default && !pDirty();
    $('pHistN').textContent = p.history.length || '';
    $('pHistBtn').disabled = !p.history.length;
  }
  function pSync() {
    var d = pDirty(), v = $('pText').value;
    $('pDirty').hidden = !d; $('pSave').disabled = !d || !v.trim(); $('pDiscard').disabled = !d;
    $('pCount').textContent = int(v.length) + ' characters';
    var p = P();
    $('pCompare').hidden = p.is_default && v === p.default;
    var miss = p.placeholders.filter(function (ph) { return v.indexOf(ph.name) < 0; });
    [].forEach.call($('pPh').querySelectorAll('[data-ph]'), function (b) {
      b.classList.toggle('missing', miss.some(function (ph) { return ph.name === b.getAttribute('data-ph'); }));
    });
    if (S.compare !== null) drawCompare();
  }
  $('pText').addEventListener('input', function () { pSync(); drawPSum(); });
  $('pTry').addEventListener('click', function () {
    setTab('draft');
    if (!S.ticket) $('tkId').focus(); else if (!$('draft').disabled) $('draft').focus();
  });
  $('pPh').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-ph]'); if (!b) return;
    var ta = $('pText'), s = ta.selectionStart, e = ta.selectionEnd, ph = b.getAttribute('data-ph');
    ta.value = ta.value.slice(0, s) + ph + ta.value.slice(e);
    ta.focus(); ta.selectionStart = ta.selectionEnd = s + ph.length; pSync();
  });

  // compare: the text in the editor against the default or an earlier version
  function drawCompare() {
    var on = S.compare !== null, p = P();
    $('pText').hidden = on; $('pDiff').hidden = !on;
    $('pCompare').classList.toggle('on', on); $('pCompare').setAttribute('aria-pressed', on);
    $('pCompare').textContent = on ? 'Back to editing' : 'Compare with default';
    if (!on) return;
    var base = S.compare === 'default' ? p.default : (p.history[S.compare] || {}).text || '';
    var label = S.compare === 'default' ? 'the default' : 'the version from ' + when(p.history[S.compare].ms);
    var d = diff(base, $('pText').value);
    $('pDiff').innerHTML = '<div class="pt-dhead"><span>Changes from <b>' + esc(label) + '</b> to the text in the editor</span>' +
      (d.adds || d.dels ? '<span class="pt-dn"><ins>+' + d.adds + ' words</ins> <del>−' + d.dels + ' words</del></span>' : '<span class="muted">No differences</span>') + '</div>' +
      '<div class="pt-dbody">' + d.html + '</div>';
  }
  $('pCompare').addEventListener('click', function () { S.compare = S.compare === null ? 'default' : null; drawCompare(); });

  // history: the versions a save replaced
  function drawHist() {
    var p = P();
    $('pHist').hidden = !S.histOpen; $('pHistBtn').setAttribute('aria-expanded', S.histOpen);
    $('pHistBtn').classList.toggle('on', S.histOpen);
    if (!S.histOpen) return;
    var cur = '<li class="pt-hv pt-hv-cur"><span class="pt-hdot"></span><div><b>In use now</b> · ' +
      (p.is_default ? 'the default text' : 'saved ' + esc(when(p.updated_ms)) + (p.updated_by ? ' by ' + esc(who(p.updated_by)) : '')) + '</div></li>';
    $('pHist').innerHTML = '<div class="pt-hhead"><b>Earlier versions</b><span class="muted">The last ' + p.history.length + ' kept · newest first</span></div><ol class="pt-hl">' + cur +
      p.history.map(function (h, i) {
        var what = h['default'] ? 'The default text' : 'Saved ' + esc(when(h.ms)) + (h.by ? ' by ' + esc(who(h.by)) : '');
        return '<li class="pt-hv"><span class="pt-hdot"></span><div class="pt-hmain"><div><b>' + what + '</b></div>' +
          '<div class="muted">Replaced ' + esc(when(h.replaced_ms)) + (h.replaced_by ? ' by ' + esc(who(h.replaced_by)) : '') +
          (h.note ? ' — “' + esc(h.note) + '”' : '') + '</div></div>' +
          '<div class="pt-hact"><button type="button" class="btn btn-sm" data-hc="' + i + '">Compare</button>' +
          '<button type="button" class="btn btn-sm" data-hu="' + i + '">Use this version</button></div></li>';
      }).join('') + '</ol>';
  }
  $('pHistBtn').addEventListener('click', function () { S.histOpen = !S.histOpen; drawHist(); });
  $('pHist').addEventListener('click', function (ev) {
    var c = ev.target.closest('[data-hc]'), u = ev.target.closest('[data-hu]'), p = P();
    if (c) { S.compare = +c.getAttribute('data-hc'); drawCompare(); $('pDiff').scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
    if (u) {
      var h = p.history[+u.getAttribute('data-hu')];
      $('pText').value = h.text; $('pNote').value = 'Back to the version from ' + when(h.ms);
      S.compare = null; drawCompare(); pSync();
      toast('That version is in the editor — press Save prompt to use it.');
    }
  });

  $('pDiscard').addEventListener('click', function () { $('pText').value = S.pBase; $('pNote').value = ''; pSync(); });
  $('pSave').addEventListener('click', function () {
    var b = $('pSave'); busy(b, true);
    post('/api/replylab/prompt', { prompt: $('pText').value, note: $('pNote').value }).then(function (r) {
      replaceP(r); toast('Saved — the prompt is used from the next draft, here and in the ticket sidebar.');
    }).catch(function (e) { toast(e.message, true); }).then(function () { busy(b, false); pSync(); });
  });
  $('pReset').addEventListener('click', function () {
    var p = P();
    if (!confirm('Put the prompt back to the default text? The text in use now stays in History.')) return;
    post('/api/replylab/prompt', { prompt: '', note: 'Back to the default' }).then(function (r) { replaceP(r); toast('The prompt is back to the default.'); })
      .catch(function (e) { toast(e.message, true); });
  });
  function replaceP(r) {
    ['prompt', 'default_prompt', 'is_default', 'updated_ms', 'updated_by', 'history'].forEach(function (k) { S.info[k] = r[k]; });
    S.pBase = r.prompt; $('pText').value = r.prompt; $('pNote').value = '';
    S.compare = null; drawCompare(); drawPState(); drawHist(); pSync(); drawPSum();
  }

  function drawSideModel() {
    var d = S.info, spark = d.models.filter(function (m) { return m.provider === 'Spark'; }).map(function (m) { return m.label; }), list = spark.slice();
    if (list.indexOf(d.sidebar_model) < 0) list.unshift(d.sidebar_model);
    $('sideModel').innerHTML = list.map(function (m) {
      return '<option value="' + esc(m) + '"' + (m === d.sidebar_model ? ' selected' : '') + '>' + esc(m) + (m === d.sidebar_default ? ' (default)' : '') + '</option>';
    }).join('');
    $('sideModel').disabled = !spark.length;
    if (!spark.length) $('sideMsg').textContent = 'Spark isn’t connected — can’t change it now';
  }
  $('sideModel').addEventListener('change', function () {
    var m = this.value;
    post('/api/replylab/sidebar-model', { model: m }).then(function (r) {
      S.info.sidebar_model = r.sidebar_model; toast('The ticket sidebar drafts with ' + r.sidebar_model + ' from now on.');
    }).catch(function (e) { toast(e.message, true); drawSideModel(); });
  });

  // ---- the Templates tab: the list -----------------------------------------------------------------------
  function tpl(id) { return S.info.templates.filter(function (t) { return t.id === id; })[0]; }
  function drawTList() {
    var q = $('tQ').value.trim().toLowerCase(), tag = $('tTag').value, groups = {};
    var tags = {};
    S.info.templates.forEach(function (t) { tags[t.tag] = (tags[t.tag] || 0) + 1; });
    var names = Object.keys(tags).sort();
    $('tTag').innerHTML = '<option value="">All tags (' + S.info.templates.length + ')</option>' + names.map(function (n) {
      return '<option value="' + esc(n) + '"' + (n === tag ? ' selected' : '') + '>' + esc(n) + ' (' + tags[n] + ')</option>';
    }).join('');
    $('tTags').innerHTML = names.map(function (n) { return '<option value="' + esc(n) + '">'; }).join('');
    S.info.templates.forEach(function (t) {
      if (tag && t.tag !== tag) return;
      if (q && (t.title + ' ' + t.tag + ' ' + t.text).toLowerCase().indexOf(q) < 0) return;
      (groups[t.tag] = groups[t.tag] || []).push(t);
    });
    var keys = Object.keys(groups).sort();
    var html = S.tId === '' ? '<div class="pt-tgrp"><button type="button" class="pt-titem active"><b>New template</b><span>Not saved yet</span></button></div>' : '';
    html += keys.map(function (k) {
      return '<div class="pt-tgrp"><div class="pt-tgh">' + esc(k) + ' <span>' + groups[k].length + '</span></div>' +
        groups[k].sort(function (a, b) { return a.title.localeCompare(b.title); }).map(function (t) {
          var first = t.text.replace(/^(hello|hi|dear)[^\n]*\n+/i, '').replace(/^thank you[^\n]*\n+/i, '').split('\n')[0];
          return '<button type="button" class="pt-titem' + (t.id === S.tId ? ' active' : '') + '" data-id="' + esc(t.id) + '"><b>' + esc(t.title) +
            (t.updated_ms ? '<i class="pt-eddot" title="Edited ' + esc(when(t.updated_ms)) + '"></i>' : '') + '</b><span>' + esc(first) + '</span></button>';
        }).join('') + '</div>';
    }).join('');
    $('tList').innerHTML = html || '<div class="pt-none">No template matches “' + esc(q) + '”.</div>';
    $('tResetAll').hidden = !S.info.templates_edited;
  }
  $('tQ').addEventListener('input', drawTList);
  $('tTag').addEventListener('change', drawTList);
  $('tList').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-id]'); if (!b) return;
    var id = b.getAttribute('data-id'); if (id === S.tId) return;
    if (tDirty() && !confirm('You have unsaved changes to this template. Leave them?')) return;
    openTemplate(id);
  });
  $('tNew').addEventListener('click', function () {
    if (tDirty() && !confirm('You have unsaved changes to this template. Leave them?')) return;
    openTemplate('');
    $('tTitle').focus();
  });

  // ---- templates: the editor ---------------------------------------------------------------------
  function drawLangs() {
    $('tLang').innerHTML = S.info.languages.map(function (l) { return '<option>' + esc(l) + '</option>'; }).join('');
  }
  function tVals() { return { title: $('tTitle').value.trim(), tag: $('tTagIn').value.trim(), language: $('tLang').value, text: $('tText').value.replace(/\s+$/, '') }; }
  function tDirty() {
    if (S.tId === null || !S.tBase) return false;
    var v = tVals(), b = S.tBase;
    return v.title !== b.title || v.tag !== b.tag || v.language !== b.language || v.text !== b.text;
  }
  function openTemplate(id, quiet) {
    var t = id ? tpl(id) : null;
    if (id && !t) return;
    S.tId = id;
    S.tBase = t ? { title: t.title, tag: t.tag, language: t.language, text: t.text } : { title: '', tag: $('tTag').value || '', language: 'English', text: '' };
    $('tTitle').value = S.tBase.title; $('tTagIn').value = S.tBase.tag; $('tLang').value = S.tBase.language; $('tText').value = S.tBase.text;
    $('tHead').textContent = t ? t.title : 'New template';
    $('tMeta').textContent = t ? (t.updated_ms ? 'Edited ' + when(t.updated_ms) + (t.updated_by ? ' by ' + who(t.updated_by) : '') : 'From the team’s Notion page') : 'Fill in a title, a tag and the text, then save.';
    $('tState').innerHTML = t ? '<span class="pt-badge">' + esc(t.language) + '</span>' : '<span class="pt-badge pt-badge-ed">New</span>';
    $('tDel').hidden = !t;
    tSync(); drawTList();
    if (!quiet && t) $('tText').focus({ preventScroll: true });
  }
  function tSync() {
    var d = tDirty(), v = tVals();
    $('tDirty').hidden = !d; $('tDiscard').disabled = !d;
    $('tSave').disabled = !(d || S.tId === '') || !v.title || !v.text;
    $('tCount').textContent = int(v.text.length) + ' characters' + (/XXX/.test(v.text) ? ' · ' + (v.text.match(/XXX/g) || []).length + '× XXX' : '');
  }
  ['tTitle', 'tTagIn', 'tLang', 'tText'].forEach(function (id) { $(id).addEventListener('input', tSync); $(id).addEventListener('change', tSync); });
  $('tDiscard').addEventListener('click', function () {
    if (S.tId === '') { openTemplate((S.info.templates[0] || {}).id || ''); return; }
    openTemplate(S.tId, true);
  });
  $('tSave').addEventListener('click', function () {
    var v = tVals(); v.id = S.tId || '';
    if (!v.tag) v.tag = 'Other';
    var b = $('tSave'); busy(b, true);
    post('/api/replylab/template', v).then(function (t) {
      S.tId = t.id;
      return load(true).then(function () { openTemplate(t.id, true); toast(v.id ? 'Template saved — Reply Lab uses it from the next draft.' : 'Template added — Reply Lab can use it from the next draft.'); });
    }).catch(function (e) { toast(e.message, true); }).then(function () { busy(b, false); tSync(); });
  });
  $('tDel').addEventListener('click', function () {
    var t = tpl(S.tId); if (!t) return;
    if (!confirm('Delete “' + t.title + '”?\n\nIt goes to Recently deleted, where it can be put back.')) return;
    post('/api/replylab/template/delete', { id: t.id }).then(function () {
      S.tId = null;
      return load(true).then(function () { openTemplate((S.info.templates[0] || {}).id || '', true); toast('“' + t.title + '” deleted — it’s in Recently deleted.'); });
    }).catch(function (e) { toast(e.message, true); });
  });

  // recently deleted, and back to the original set
  function drawTrash() {
    var tr = S.info.trash || [];
    $('tTrashN').textContent = tr.length || '';
    $('tTrashBtn').disabled = !tr.length;
    if (!tr.length) $('tTrash').hidden = true;
    $('tTrash').innerHTML = tr.map(function (x) {
      return '<div class="pt-trow"><div><b>' + esc(x.template.title) + '</b><span class="muted">' + esc(when(x.deleted_ms)) + (x.deleted_by ? ' · ' + esc(who(x.deleted_by)) : '') + '</span></div>' +
        '<button type="button" class="btn btn-sm" data-restore="' + esc(x.template.id) + '">Put back</button></div>';
    }).join('');
  }
  $('tTrashBtn').addEventListener('click', function () {
    var open = $('tTrash').hidden; $('tTrash').hidden = !open; this.setAttribute('aria-expanded', open);
  });
  $('tTrash').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-restore]'); if (!b) return;
    post('/api/replylab/template/restore', { id: b.getAttribute('data-restore') }).then(function (t) {
      return load(true).then(function () { openTemplate(t.id, true); toast('“' + t.title + '” is back.'); });
    }).catch(function (e) { toast(e.message, true); });
  });
  $('tResetAll').addEventListener('click', function () {
    if (!confirm('Put back the original ' + 'templates from the team’s Notion page?\n\nTemplates added or changed here go to Recently deleted, so nothing is lost.')) return;
    post('/api/replylab/templates/reset').then(function (r) {
      S.tId = null;
      return load(true).then(function () { openTemplate((S.info.templates[0] || {}).id || '', true); toast('The original templates are back' + (r.moved ? ' — ' + r.moved + ' moved to Recently deleted.' : '.')); });
    }).catch(function (e) { toast(e.message, true); });
  });

  // which templates would a ticket get
  $('mBtn').addEventListener('click', function () {
    var text = $('mText').value.trim(); if (!text) { $('mText').focus(); return; }
    $('mMsg').textContent = 'Matching…';
    post('/api/replylab/match', { text: text }).then(function (r) {
      $('mMsg').textContent = r.matches.length ? '' : 'No template matches these words well enough — Reply Lab would write without one.';
      $('mOut').innerHTML = r.matches.length ? '<ol class="pt-ml">' + r.matches.map(function (m, i) {
        return '<li><button type="button" class="pt-mi' + (i < 3 ? ' top' : '') + '" data-id="' + esc(m.id) + '"><span class="pt-mn">' + (i + 1) + '</span><span class="pt-mt"><b>' + esc(m.title) + '</b>' +
          '<span class="muted">' + esc(m.tag) + (i < 3 ? ' · offered to the model' : ' · not offered (only the top 3 are)') + '</span>' +
          (m.words.length ? '<span class="pt-mw">' + m.words.map(function (w) { return '<i>' + esc(w) + '</i>'; }).join('') + '</span>' : '') + '</span></button></li>';
      }).join('') + '</ol>' : '';
    }).catch(function (e) { $('mMsg').textContent = ''; toast(e.message, true); });
  });
  $('mOut').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-id]'); if (!b) return;
    if (tDirty() && !confirm('You have unsaved changes to this template. Leave them?')) return;
    openTemplate(b.getAttribute('data-id'));
    $('tEd').scrollIntoView({ block: 'start', behavior: 'smooth' });
  });



  // ---- tabs, leaving with unsaved changes ----------------------------------------------------------
  function setTab(t) {
    S.tab = t;
    [].forEach.call(document.querySelectorAll('.pt-tabs [data-tab]'), function (b) {
      var on = b.getAttribute('data-tab') === t; b.classList.toggle('on', on); b.setAttribute('aria-selected', on);
    });
    $('vDraft').hidden = t !== 'draft'; $('vPrompt').hidden = t !== 'prompt'; $('vTemplates').hidden = t !== 'templates';
    if (t === 'draft' && S.info) { drawPSum(); canDraft(); }
    if (location.hash !== '#' + t) history.replaceState(null, '', t === 'draft' ? location.pathname : '#' + t);
  }
  document.querySelector('.pt-tabs').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-tab]'); if (b) setTab(b.getAttribute('data-tab'));
  });
  window.addEventListener('beforeunload', function (e) { if (pDirty() || tDirty()) { e.preventDefault(); e.returnValue = ''; } });
  document.addEventListener('keydown', function (e) {           // Ctrl+S saves what is being edited
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && S.tab !== 'draft') {
      var b = S.tab === 'prompt' ? $('pSave') : $('tSave');
      e.preventDefault(); if (!b.disabled) b.click();
    }
  });

  function load(keep) {
    return api('/api/replylab').then(function (info) {
      S.info = info; $('err').hidden = true;
      $('nTemplates').textContent = info.templates.length;
      if (!keep) {
        var last = [];
        try { last = JSON.parse(localStorage.getItem('shcReplyLabModels') || '[]'); } catch (e) {}
        last.forEach(function (id) { if (info.models.some(function (m) { return m.id === id; })) S.picked[id] = true; });
        if (!Object.keys(S.picked).length && info.models.length) S.picked[info.models[0].id] = true;
        drawModels(); openPrompt();
      }
      drawTemplates(); drawPSum(); canDraft();
      drawTList(); drawTrash(); drawLangs(); drawSideModel();
      if (S.tId === null) openTemplate((info.templates[0] || {}).id || '', true);
    }).catch(function (e) {
      $('err').hidden = false; $('err').textContent = 'Could not load Reply Lab: ' + e.message;
      $('models').innerHTML = '';
    });
  }
  setTab(/^#(prompt|templates)$/.test(location.hash) ? location.hash.slice(1) : 'draft');
  load();
  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (x) { S.zd = x.zendesk_url || ''; if (S.ticket) drawTicket(); }).catch(function () {});
})();
