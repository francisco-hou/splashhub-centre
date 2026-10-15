// SplashHub Centre -- Prompts & Templates (admins): edit the AI prompts and the
// team's reply templates (aiprompts.py, replylab.py). A save is used from the
// next AI call: no release. Every prompt keeps its earlier versions (History),
// a deleted template waits in Recently deleted, and the reply prompt can be
// tried on a real ticket before it is saved (a draft only -- nothing is sent).
(function () {
  'use strict';

  var S = { data: null, tab: 'prompts', pKey: null, pBase: '', compare: null, histOpen: false,
            tId: null, tBase: null, models: null };

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
  function post(path, body) { return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }); }
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function clock(d) { return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }
  function when(ms) {
    if (!ms) return '';
    var d = new Date(ms), now = new Date(), y = new Date(now.getTime() - 864e5);
    if (d.toDateString() === now.toDateString()) return 'today ' + clock(d);
    if (d.toDateString() === y.toDateString()) return 'yesterday ' + clock(d);
    return d.getDate() + ' ' + MON[d.getMonth()] + (d.getFullYear() !== now.getFullYear() ? ' ' + d.getFullYear() : '') + ', ' + clock(d);
  }
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

  var ICONS = {
    reply: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 9h8"/><path d="M8 13h5"/>',
    filter: '<path d="M22 3H2l8 9.46V19l4 2v-8.54z"/>',
    tag: '<path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8z"/><circle cx="7" cy="7" r="1.5"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    spark: '<path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z"/>'
  };
  function icon(k) { return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[k] || ICONS.spark) + '</svg>'; }

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

  // ---- loading -------------------------------------------------------------------------------------
  function load(keep) {
    return api('/api/prompts').then(function (d) {
      S.data = d; $('err').hidden = true;
      $('nPrompts').textContent = d.prompts.length;
      $('nTemplates').textContent = d.templates.length;
      drawPList();
      if (!keep || !S.pKey) openPrompt(S.pKey || d.prompts[0].key, true);
      drawTList(); drawTrash(); drawLangs();
      if (S.tId === null && !keep) openTemplate((d.templates[0] || {}).id || '', true);
      drawSideModel();
    }).catch(function (e) {
      $('err').hidden = false;
      $('err').textContent = /login/.test(e.message) ? 'Prompts & Templates is for admins. Sign in with an Admin account.' : 'Could not load: ' + e.message;
    });
  }
  function prompt(key) { return S.data.prompts.filter(function (p) { return p.key === key; })[0]; }

  // ---- prompts: the list -------------------------------------------------------------------------
  function drawPList() {
    $('pList').innerHTML = '<div class="pt-lhead">AI prompts</div>' + S.data.prompts.map(function (p) {
      var st = p.is_default ? '' : '<span class="pt-badge pt-badge-ed" title="Edited ' + esc(when(p.updated_ms)) + '">Edited</span>';
      return '<button type="button" class="pt-item' + (p.key === S.pKey ? ' active' : '') + '" data-key="' + esc(p.key) + '">' +
        '<span class="pt-ic">' + icon(p.icon) + '</span><span class="pt-it"><b>' + esc(p.name) + '</b><span>' + esc(p.engine) + '</span></span>' + st + '</button>';
    }).join('');
  }
  $('pList').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-key]'); if (!b || b.getAttribute('data-key') === S.pKey) return;
    if (pDirty() && !confirm('You have unsaved changes to “' + prompt(S.pKey).name + '”. Leave them?')) return;
    openPrompt(b.getAttribute('data-key'));
  });

  // ---- prompts: the editor -----------------------------------------------------------------------
  function pDirty() { return S.pKey && $('pText').value !== S.pBase; }
  function openPrompt(key, quiet) {
    var p = prompt(key); if (!p) return;
    S.pKey = key; S.pBase = p.text; S.compare = null; S.histOpen = false;
    $('pName').textContent = p.name;
    $('pWhere').innerHTML = '<span class="pt-eng">' + esc(p.engine) + '</span> Used in ' + esc(p.where);
    $('pAbout').textContent = p.about;
    $('pText').value = p.text; $('pNote').value = '';
    $('pFixedT').textContent = p.fixed;
    $('pPh').innerHTML = p.placeholders.length ? '<span class="muted">Fills in:</span>' + p.placeholders.map(function (ph) {
      return '<button type="button" class="pt-chip" data-ph="' + esc(ph.name) + '" title="Insert at the cursor: ' + esc(ph.about) + '">' + esc(ph.name) + '</button>';
    }).join('') : '';
    $('pTry').hidden = p.test !== 'reply';
    if (p.test === 'reply') loadModels();
    drawPState(); drawHist(); drawCompare(); pSync();
    drawPList();
    if (!quiet) $('pText').focus({ preventScroll: true });
  }
  function drawPState() {
    var p = prompt(S.pKey);
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
    var p = prompt(S.pKey);
    $('pCompare').hidden = p.is_default && v === p.default;
    var miss = p.placeholders.filter(function (ph) { return v.indexOf(ph.name) < 0; });
    [].forEach.call($('pPh').querySelectorAll('[data-ph]'), function (b) {
      b.classList.toggle('missing', miss.some(function (ph) { return ph.name === b.getAttribute('data-ph'); }));
    });
    if (S.compare !== null) drawCompare();
  }
  $('pText').addEventListener('input', pSync);
  $('pPh').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-ph]'); if (!b) return;
    var ta = $('pText'), s = ta.selectionStart, e = ta.selectionEnd, ph = b.getAttribute('data-ph');
    ta.value = ta.value.slice(0, s) + ph + ta.value.slice(e);
    ta.focus(); ta.selectionStart = ta.selectionEnd = s + ph.length; pSync();
  });

  // compare: the text in the editor against the default or an earlier version
  function drawCompare() {
    var on = S.compare !== null, p = prompt(S.pKey);
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
    var p = prompt(S.pKey);
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
    var c = ev.target.closest('[data-hc]'), u = ev.target.closest('[data-hu]'), p = prompt(S.pKey);
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
    post('/api/prompts/save', { key: S.pKey, text: $('pText').value, note: $('pNote').value }).then(function (p) {
      replaceP(p); toast('Saved — “' + p.name + '” is used from the next AI call.');
    }).catch(function (e) { toast(e.message, true); }).then(function () { busy(b, false); pSync(); });
  });
  $('pReset').addEventListener('click', function () {
    var p = prompt(S.pKey);
    if (!confirm('Put “' + p.name + '” back to the default text? The text in use now stays in History.')) return;
    post('/api/prompts/reset', { key: S.pKey }).then(function (np) { replaceP(np); toast('“' + np.name + '” is back to the default.'); })
      .catch(function (e) { toast(e.message, true); });
  });
  function replaceP(np) {
    S.data.prompts = S.data.prompts.map(function (p) { return p.key === np.key ? np : p; });
    S.pBase = np.text; $('pText').value = np.text; $('pNote').value = '';
    S.compare = null; drawCompare(); drawPState(); drawHist(); drawPList(); pSync();
  }

  // ---- try the reply prompt on a ticket, and the sidebar's model -----------------------------------
  function loadModels() {
    if (S.models) return;
    S.models = [];
    api('/api/replylab').then(function (d) {
      S.models = d.models;
      $('tryModel').innerHTML = d.models.length ? d.models.map(function (m) {
        return '<option value="' + esc(m.id) + '">' + esc(m.provider + ' · ' + m.label) + '</option>';
      }).join('') : '<option value="">No model available</option>';
      var haiku = d.models.filter(function (m) { return /haiku/.test(m.id); })[0];
      if (haiku) $('tryModel').value = haiku.id;
    }).catch(function () { $('tryModel').innerHTML = '<option value="">Models unavailable</option>'; });
  }
  $('tryForm').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var tk = parseInt(String($('tryTk').value).replace(/\D/g, ''), 10);
    if (!tk) { $('tryTk').focus(); return; }
    if (!$('tryModel').value) return;
    var b = $('tryBtn'); busy(b, true, 'Drafting…');
    $('tryMsg').textContent = 'Reading #' + tk + ' and writing a draft — this takes a few seconds';
    post('/api/replylab/draft', { ticket_id: tk, model: $('tryModel').value, prompt: $('pText').value, template: 'auto', include_notes: true })
      .then(function (r) {
        $('tryMsg').textContent = '';
        var tpl = r.template_used ? '<span class="pt-tpl">Template: <b>' + esc(r.template_used) + '</b>' + (r.similarity != null ? ' · ' + r.similarity + '% the same' : '') + '</span>'
          : '<span class="pt-tpl pt-tpl-none">No template used</span>';
        $('tryOut').innerHTML = '<div class="pt-draft"><div class="pt-dmeta"><b>#' + tk + '</b><span>' + esc(r.provider + ' · ' + r.model) + '</span><span>' +
          (r.ms / 1000).toFixed(1) + ' s</span>' + tpl + (pDirty() ? '<span class="pt-unsaved">with your unsaved text</span>' : '') +
          '<button type="button" class="btn btn-sm pt-copy">Copy</button></div><div class="pt-dtext"></div></div>';
        $('tryOut').querySelector('.pt-dtext').textContent = r.text;
        $('tryOut').querySelector('.pt-copy').addEventListener('click', function () {
          navigator.clipboard.writeText(r.text).then(function () { toast('Draft copied.'); });
        });
      }).catch(function (e) { $('tryMsg').textContent = ''; toast(e.message, true); })
      .then(function () { busy(b, false); b.disabled = false; });
  });
  function drawSideModel() {
    var d = S.data, list = d.spark_models.slice();
    if (list.indexOf(d.sidebar_model) < 0) list.unshift(d.sidebar_model);
    $('sideModel').innerHTML = list.map(function (m) {
      return '<option value="' + esc(m) + '"' + (m === d.sidebar_model ? ' selected' : '') + '>' + esc(m) + (m === d.sidebar_default ? ' (default)' : '') + '</option>';
    }).join('');
    $('sideModel').disabled = !d.spark_models.length;
    if (!d.spark_models.length) $('sideMsg').textContent = 'Spark isn’t connected — can’t change it now';
  }
  $('sideModel').addEventListener('change', function () {
    var m = this.value;
    post('/api/prompts/sidebar-model', { model: m }).then(function (r) {
      S.data.sidebar_model = r.sidebar_model; toast('The ticket sidebar drafts with ' + r.sidebar_model + ' from now on.');
    }).catch(function (e) { toast(e.message, true); drawSideModel(); });
  });

  // ---- templates: the list -----------------------------------------------------------------------
  function tpl(id) { return S.data.templates.filter(function (t) { return t.id === id; })[0]; }
  function drawTList() {
    var q = $('tQ').value.trim().toLowerCase(), tag = $('tTag').value, groups = {};
    var tags = {};
    S.data.templates.forEach(function (t) { tags[t.tag] = (tags[t.tag] || 0) + 1; });
    var names = Object.keys(tags).sort();
    $('tTag').innerHTML = '<option value="">All tags (' + S.data.templates.length + ')</option>' + names.map(function (n) {
      return '<option value="' + esc(n) + '"' + (n === tag ? ' selected' : '') + '>' + esc(n) + ' (' + tags[n] + ')</option>';
    }).join('');
    $('tTags').innerHTML = names.map(function (n) { return '<option value="' + esc(n) + '">'; }).join('');
    S.data.templates.forEach(function (t) {
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
    $('tResetAll').hidden = !S.data.templates_edited;
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
    $('tLang').innerHTML = S.data.languages.map(function (l) { return '<option>' + esc(l) + '</option>'; }).join('');
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
    if (S.tId === '') { openTemplate((S.data.templates[0] || {}).id || ''); return; }
    openTemplate(S.tId, true);
  });
  $('tSave').addEventListener('click', function () {
    var v = tVals(); v.id = S.tId || '';
    if (!v.tag) v.tag = 'Other';
    var b = $('tSave'); busy(b, true);
    post('/api/prompts/template', v).then(function (t) {
      S.tId = t.id;
      return load(true).then(function () { openTemplate(t.id, true); toast(v.id ? 'Template saved — Reply Lab uses it from the next draft.' : 'Template added — Reply Lab can use it from the next draft.'); });
    }).catch(function (e) { toast(e.message, true); }).then(function () { busy(b, false); tSync(); });
  });
  $('tDel').addEventListener('click', function () {
    var t = tpl(S.tId); if (!t) return;
    if (!confirm('Delete “' + t.title + '”?\n\nIt goes to Recently deleted, where it can be put back.')) return;
    post('/api/prompts/template/delete', { id: t.id }).then(function () {
      S.tId = null;
      return load(true).then(function () { openTemplate((S.data.templates[0] || {}).id || '', true); toast('“' + t.title + '” deleted — it’s in Recently deleted.'); });
    }).catch(function (e) { toast(e.message, true); });
  });

  // recently deleted, and back to the original set
  function drawTrash() {
    var tr = S.data.trash || [];
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
    post('/api/prompts/template/restore', { id: b.getAttribute('data-restore') }).then(function (t) {
      return load(true).then(function () { openTemplate(t.id, true); toast('“' + t.title + '” is back.'); });
    }).catch(function (e) { toast(e.message, true); });
  });
  $('tResetAll').addEventListener('click', function () {
    if (!confirm('Put back the original ' + 'templates from the team’s Notion page?\n\nTemplates added or changed here go to Recently deleted, so nothing is lost.')) return;
    post('/api/prompts/templates/reset').then(function (r) {
      S.tId = null;
      return load(true).then(function () { openTemplate((S.data.templates[0] || {}).id || '', true); toast('The original templates are back' + (r.moved ? ' — ' + r.moved + ' moved to Recently deleted.' : '.')); });
    }).catch(function (e) { toast(e.message, true); });
  });

  // which templates would a ticket get
  $('mBtn').addEventListener('click', function () {
    var text = $('mText').value.trim(); if (!text) { $('mText').focus(); return; }
    $('mMsg').textContent = 'Matching…';
    post('/api/prompts/match', { text: text }).then(function (r) {
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
    $('vPrompts').hidden = t !== 'prompts'; $('vTemplates').hidden = t !== 'templates';
    if (location.hash !== '#' + t) history.replaceState(null, '', t === 'prompts' ? location.pathname : '#' + t);
  }
  document.querySelector('.pt-tabs').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-tab]'); if (b) setTab(b.getAttribute('data-tab'));
  });
  window.addEventListener('beforeunload', function (e) { if (pDirty() || tDirty()) { e.preventDefault(); e.returnValue = ''; } });
  document.addEventListener('keydown', function (e) {           // Ctrl+S saves what is being edited
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      var b = S.tab === 'prompts' ? $('pSave') : $('tSave');
      e.preventDefault(); if (!b.disabled) b.click();
    }
  });

  setTab(location.hash === '#templates' ? 'templates' : 'prompts');
  load();
})();
