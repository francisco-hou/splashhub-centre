// SplashHub Centre -- Logs page.
//
// Every filter (period, tool, agent, model, search) scopes everything below it:
// stats, both charts and the table re-render from the same slice, so the
// numbers always agree. Aggregates come from the server (/api/summary); rows
// arrive a page at a time (/api/runs). Days are the viewer's calendar days --
// the page sends its UTC offset and the server buckets on it.
(function () {
  'use strict';

  var DAY = 86400000;
  var TZ = new Date().getTimezoneOffset();      // minutes behind UTC (Taipei = -480)
  var S = { days: 30, from: '', to: '', tool: '', agent: '', model: '', q: '', page: 0, measure: 'runs' };   // days -1: the custom range
  var META = null, SUM = null;
  try { var m0 = localStorage.getItem('shc.measure'); if (m0 === 'cost' || m0 === 'runs') S.measure = m0; } catch (e) {}

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ---- formatting (formatUsd is SplashHub's, so costs read the same) --------
  function formatUsd(n) {
    if (!n) return '$0.00';
    return n < 0.01 ? '<$0.01' : '$' + n.toFixed(n < 1 ? 3 : 2);
  }
  function usdShort(n) {               // axis ticks and bar labels
    if (!n) return '$0';
    if (n >= 1000) return '$' + (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'K';
    if (n >= 100) return '$' + Math.round(n);
    if (n >= 1) return '$' + n.toFixed(n % 1 ? 2 : 0);
    return '$' + n.toFixed(2);
  }
  function int(n) { return (n || 0).toLocaleString('en-US'); }
  function compact(n) {
    n = n || 0;
    if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
    if (n >= 1e4) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'K';
    return int(n);
  }
  // 'claude-opus-4-8' -> 'Opus 4.8', as SplashHub's shortModel() does.
  function shortModel(m) {
    m = String(m || '');
    if (!m || m === '—') return '';
    var c = m.match(/^claude-(\w+)-([\d-]+)$/);
    if (c) return c[1].charAt(0).toUpperCase() + c[1].slice(1) + ' ' + c[2].replace(/-/g, '.');
    // 'spark:qwen3.6-35b-a3b' -> 'Spark Qwen 3.6'; 'gpt-5.6-sol' -> 'GPT-5.6 Sol' (full name on hover)
    var sp = m.match(/^spark:([a-z]+)([\d.]+)/i);
    if (sp) return 'Spark ' + sp[1].charAt(0).toUpperCase() + sp[1].slice(1) + ' ' + sp[2];
    var g = m.match(/^gpt-([\d.]+)(?:-(\w+))?/i);
    if (g) return 'GPT-' + g[1] + (g[2] ? ' ' + g[2].charAt(0).toUpperCase() + g[2].slice(1) : '');
    return m;
  }
  function dayIdx(ms) { return Math.floor((ms - TZ * 60000) / DAY); }
  function dayStart(idx) { return idx * DAY + TZ * 60000; }
  var WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  function dayLabel(idx, long) {
    var d = new Date(dayStart(idx) + 12 * 3600000);
    return (long ? WD[d.getDay()] + ' ' : '') + (d.getMonth() + 1) + '/' + d.getDate();
  }
  function whenTxt(ms) {
    var d = new Date(ms), now = new Date();
    var t = (d.getMonth() + 1) + '/' + d.getDate() + (d.getFullYear() !== now.getFullYear() ? '/' + String(d.getFullYear()).slice(2) : '');
    return t + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }

  // ---- requests -------------------------------------------------------------
  function api(path) {
    return fetch(path, { credentials: 'same-origin' }).then(function (r) {
      if (r.status === 401) { showLogin(); throw new Error('login'); }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }
  function ymdIdx(ymd) { var p = String(ymd).split('-'); return dayIdx(new Date(+p[0], +p[1] - 1, +p[2], 12).getTime()); }
  function idxYmd(idx) { var d = new Date(dayStart(idx) + 12 * 3600000); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
  // the days shown: [first, last] as day indexes (the viewer's calendar days)
  function span() {
    var today = dayIdx(Date.now());
    if (S.days === -1 && S.from && S.to) return [Math.min(ymdIdx(S.from), ymdIdx(S.to)), Math.max(ymdIdx(S.from), ymdIdx(S.to))];
    if (S.days > 0) return [today - S.days + 1, today];
    return [META && META.first ? dayIdx(META.first) : today, today];
  }
  function range() {
    if (!S.days) return {};
    var s = span();
    return S.days === -1 ? { since: dayStart(s[0]), until: dayStart(s[1] + 1) } : { since: dayStart(s[0]) };
  }
  function params(extra) {
    var p = range();
    if (S.tool) p.tool = S.tool;
    if (S.agent) p.agent = S.agent;
    if (S.model) p.model = S.model;
    if (S.q) p.q = S.q;
    Object.keys(extra || {}).forEach(function (k) { p[k] = extra[k]; });
    return Object.keys(p).map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(p[k]); }).join('&');
  }

  // ---- sign-in ----------------------------------------------------------------
  // Not an admin: Logs and Settings are for the Admin role (Settings > People); there is no password.
  function showLogin(msg) {
    $('page').hidden = true;
    $('login').hidden = false;
    if (msg) { $('loginErr').textContent = msg; $('loginErr').hidden = false; }
  }
  $('signOut').addEventListener('click', function () {
    fetch('/logout', { method: 'POST', credentials: 'same-origin' }).then(function () { location.href = '/scans'; });
  });

  // ---- boot -----------------------------------------------------------------
  function boot() {
    fetch('/api/session', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (s) {
      if (s.required && !s.authed) {
        showLogin(s.user ? '' : 'Sign in with your Splashtop Microsoft account first.');
        return;
      }
      var nx = new URLSearchParams(location.search).get('next');
      if (/^\/(settings)(#[a-z]+)?$/.test(nx || '')) { location.href = nx; return; }
      start();
    }).catch(function () { showLogin('Could not reach the server.'); });
  }

  function start() {
    api('/api/meta').then(function (m) {
      applyMeta(m);
      $('page').hidden = false;
      syncControls();
      load();
    }).catch(function (e) { if (e.message !== 'login') $('stamp').textContent = 'Could not load: ' + e.message; });
  }
  function applyMeta(m) {
    META = m;
    $('sampleNote').hidden = !m.sample;
    fillSelect($('agent'), m.agents, 'All agents', S.agent);
    fillSelect($('model'), m.models, 'All models', S.model, shortModel);
    drawFeed(m.feed, m.sample);
  }
  function ago(ms) {
    if (!ms) return 'never';
    var s = Math.max(0, Math.round((Date.now() - ms) / 1000));
    if (s < 60) return 'just now';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (s < 86400) return Math.round(s / 3600) + ' h ago';
    return Math.round(s / 86400) + ' d ago';
  }
  // The live feed from SplashHub (webhook pickup), in one chip.
  function drawFeed(f, sample) {
    var el = $('feed');
    if (!f || sample) { el.hidden = true; return; }
    el.hidden = false;
    el.className = 'feed' + (f.enabled && !f.last_error ? ' live' : f.enabled ? ' warn' : '');
    if (f.enabled && !f.last_error) {
      $('feedTxt').textContent = 'Live';
      el.title = 'Receiving runs from SplashHub. Last run received ' + ago(f.last_event_ms) + '.' +
        (f.rejected ? '\n' + f.rejected + ' post(s) discarded since the app started' +
          (f.last_reject ? ' — last because ' + f.last_reject : '') + '.' : '');
      // Posts arriving but none kept: say so in the chip itself, not only on hover.
      if (f.rejected && !f.runs) { el.className = 'feed warn'; $('feedTxt').textContent = 'Posts rejected'; }
    } else if (f.enabled) {
      $('feedTxt').textContent = 'Feed problem';
      el.title = f.last_error;
    } else {
      $('feedTxt').textContent = 'Feed off';
      el.title = f.reason || 'Not receiving runs.';
    }
  }
  function fillSelect(sel, values, allLabel, cur, label) {
    sel.innerHTML = '<option value="">' + esc(allLabel) + '</option>' + values.map(function (v) {
      return '<option value="' + esc(v) + '"' + (v === cur ? ' selected' : '') + '>' + esc((label && label(v)) || v) + '</option>';
    }).join('');
  }

  // ---- load: summary + first page together ------------------------------------
  var loadSeq = 0;
  function load(rowsOnly) {
    var my = ++loadSeq;
    document.body.classList.add('loading');
    $('refresh').classList.add('spin');
    var jobs = [api('/api/runs?' + params({ page: S.page }))];
    // a full refresh also re-reads meta: new agents/models and the feed's state
    if (!rowsOnly) jobs.push(api('/api/summary?' + params({ tz: TZ })), api('/api/meta'));
    Promise.all(jobs).then(function (res) {
      if (my !== loadSeq) return;                // a newer filter won
      if (!rowsOnly) { applyMeta(res[2]); SUM = res[1]; drawStats(); drawChips(); drawDays(); drawTools(); }
      drawRows(res[0]);
      $('csv').href = '/api/runs.csv?' + params();
      var d = new Date();
      $('stamp').textContent = 'Updated ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    }).catch(function (e) {
      if (e.message !== 'login') $('stamp').textContent = 'Could not load: ' + e.message;
    }).then(function () {
      if (my !== loadSeq) return;
      document.body.classList.remove('loading');
      $('refresh').classList.remove('spin');
    });
  }
  function refilter() { S.page = 0; syncControls(); load(); }

  // ---- controls -------------------------------------------------------------------
  function syncControls() {
    [].forEach.call($('period').children, function (b) { b.classList.toggle('active', +b.getAttribute('data-days') === S.days); });
    $('range').hidden = S.days !== -1;
    [].forEach.call($('measure').children, function (b) { b.classList.toggle('active', b.getAttribute('data-m') === S.measure); });
    $('tool').classList.toggle('on', !!S.tool);
    $('agent').classList.toggle('on', !!S.agent);
    $('model').classList.toggle('on', !!S.model);
    $('clearFilters').hidden = !(S.tool || S.agent || S.model || S.q);
    $('dayTitle').textContent = S.measure === 'cost' ? 'Estimated cost per day' : 'Runs per day';
  }
  $('period').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-days]'); if (!b) return;
    var d = +b.getAttribute('data-days');
    if (d === -1 && !(S.from && S.to)) {                 // Custom: start from the period shown now
      var s = span(); S.from = idxYmd(s[0]); S.to = idxYmd(s[1]);
      $('from').value = S.from; $('to').value = S.to;
    }
    S.days = d; refilter();
  });
  ['from', 'to'].forEach(function (k) {
    $(k).addEventListener('change', function () {
      if (!this.value) return;
      S[k] = this.value;
      if (S.from && S.to && S.from > S.to) { var t = S.from; S.from = S.to; S.to = t; $('from').value = S.from; $('to').value = S.to; }
      refilter();
    });
  });
  $('measure').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-m]'); if (!b) return;
    S.measure = b.getAttribute('data-m');
    try { localStorage.setItem('shc.measure', S.measure); } catch (e) {}
    syncControls(); drawDays(); drawTools();
  });
  $('agent').addEventListener('change', function () { S.agent = this.value; refilter(); });
  $('model').addEventListener('change', function () { S.model = this.value; refilter(); });
  var typing = null;
  $('q').addEventListener('input', function () {
    var v = this.value.trim();
    clearTimeout(typing);
    typing = setTimeout(function () { if (v !== S.q) { S.q = v; refilter(); } }, 250);
  });
  $('tool').addEventListener('change', function () { S.tool = this.value; refilter(); });
  $('clearFilters').addEventListener('click', function () {
    S.tool = S.agent = S.model = S.q = '';
    $('q').value = ''; $('tool').value = ''; $('agent').value = ''; $('model').value = '';
    refilter();
  });
  $('refresh').addEventListener('click', function () { load(); });
  $('prev').addEventListener('click', function () { if (S.page > 0) { S.page--; load(true); } });
  $('next').addEventListener('click', function () { S.page++; load(true); });

  // ---- stats ----------------------------------------------------------------------
  function periodDays() { var s = span(); return Math.max(1, s[1] - s[0] + 1); }
  function drawStats() {
    var s = SUM, n = periodDays();
    $('sRuns').textContent = int(s.runs);
    $('sRunsSub').textContent = s.runs ? (s.runs / n).toFixed(1).replace(/\.0$/, '') + ' a day on average' : 'No runs in this view';
    $('sCost').textContent = formatUsd(s.cost);
    $('sCostSub').textContent = s.runs ? formatUsd(s.cost / s.runs) + ' a run on average' : '—';
    $('sTok').textContent = compact(s.input_tokens + s.output_tokens);
    $('sTokSub').textContent = compact(s.input_tokens) + ' in · ' + compact(s.output_tokens) + ' out';
    $('sAgents').textContent = int(s.agents);
    $('sAgentsSub').textContent = s.top_agent ? 'Most active: ' + s.top_agent + ' · ' + int(s.top_agent_runs) + ' runs' : '—';
    $('sAgentsSub').title = $('sAgentsSub').textContent;
  }

  // ---- the tool filter: a dropdown, busiest tool first, with its runs (counts follow every filter but the tool itself) ----
  function drawChips() {
    var total = SUM.by_tool.reduce(function (a, t) { return a + t.runs; }, 0);
    var html = '<option value="">All tools (' + int(total) + ')</option>';
    SUM.by_tool.slice().sort(function (a, b) { return b.runs - a.runs; }).forEach(function (t) {
      if (t.key === 'other' && !t.runs && S.tool !== 'other') return;
      html += '<option value="' + esc(t.key) + '"' + (S.tool === t.key ? ' selected' : '') + '>' + esc(t.label) + ' (' + int(t.runs) + ')</option>';
    });
    $('tool').innerHTML = html;
    $('tool').value = S.tool || '';
  }

  // ---- runs / cost per day: one series, columns, hover per column ----------------
  function niceTicks(max) {
    if (max <= 0) return { top: 1, step: 1 };
    var raw = max / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))), step = mag;
    [1, 2, 2.5, 5, 10].some(function (k) { step = k * mag; return k * mag >= raw; });
    return { top: Math.ceil(max / step) * step, step: step };
  }
  function topRounded(x, y, w, h, r) {     // 4px rounded data-end, square at the baseline
    r = Math.min(r, w / 2, h);
    return 'M' + x + ',' + (y + h) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y +
      'H' + (x + w - r) + 'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + 'V' + (y + h) + 'Z';
  }
  function drawDays() {
    var box = $('dayChart');
    if (!SUM) return;
    var sp = span(), first = sp[0], lastDay = sp[1];
    var byDay = {};
    SUM.by_day.forEach(function (d) { byDay[d.day] = d; });
    var days = [];
    for (var i = first; i <= lastDay; i++) days.push({ day: i, runs: (byDay[i] || {}).runs || 0, cost: (byDay[i] || {}).cost || 0 });
    var cost = S.measure === 'cost';
    var val = function (d) { return cost ? d.cost : d.runs; };
    var fmt = cost ? usdShort : int;

    var W = Math.max(280, box.clientWidth - 24), H = 200, m = { l: 44, r: 6, t: 10, b: 24 };
    var pw = W - m.l - m.r, ph = H - m.t - m.b;
    var max = Math.max.apply(null, days.map(val));
    var t = niceTicks(max);
    var y = function (v) { return m.t + ph - (v / t.top) * ph; };
    var band = pw / days.length, bw = Math.max(2, Math.min(24, band - 2));

    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="' +
      esc($('dayTitle').textContent) + '">';
    for (var v = 0; v <= t.top + 1e-9; v += t.step) {
      var yy = Math.round(y(v)) + 0.5;
      s += '<line class="' + (v === 0 ? 'base' : 'grid') + '" x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + yy + '" y2="' + yy + '"/>';
      s += '<text class="axis" x="' + (m.l - 8) + '" y="' + (yy + 3.5) + '" text-anchor="end">' + esc(fmt(v)) + '</text>';
    }
    var every = Math.max(1, Math.ceil(days.length / 7));
    days.forEach(function (d, i) {
      var cx = m.l + band * i + band / 2, h = Math.max(0, y(0) - y(val(d)));
      // hit area first (full column, wider than the bar), bar after it
      s += '<rect class="hit" data-i="' + i + '" tabindex="0" x="' + (m.l + band * i) + '" y="' + m.t + '" width="' + band + '" height="' + ph + '"' +
        ' aria-label="' + esc(dayLabel(d.day, true) + ': ' + int(d.runs) + ' runs, ' + formatUsd(d.cost)) + '"/>';
      if (h > 0) s += '<path class="bar" data-b="' + i + '" d="' + topRounded(cx - bw / 2, y(val(d)), bw, h, 4) + '"/>';
      if ((days.length - 1 - i) % every === 0) {
        // labels near either edge anchor inward so they are never clipped
        var lx = cx, anchor = 'middle';
        if (cx + 16 > W - m.r) { lx = W - m.r; anchor = 'end'; }
        else if (cx - 16 < m.l) { lx = m.l; anchor = 'start'; }
        s += '<text class="axis" x="' + lx + '" y="' + (H - 6) + '" text-anchor="' + anchor + '">' + esc(dayLabel(d.day)) + '</text>';
      }
    });
    s += '</svg>';
    box.innerHTML = s;

    var tip = $('tip');
    function show(ev, el) {
      var i = +el.getAttribute('data-i'), d = days[i];
      [].forEach.call(box.querySelectorAll('.bar.hot'), function (b) { b.classList.remove('hot'); });
      var bar = box.querySelector('[data-b="' + i + '"]'); if (bar) bar.classList.add('hot');
      tip.innerHTML = '';
      var v = document.createElement('div'); v.className = 'tip-val';
      v.textContent = cost ? formatUsd(d.cost) : int(d.runs) + (d.runs === 1 ? ' run' : ' runs');
      var row = document.createElement('div'); row.className = 'tip-row';
      var key = document.createElement('span'); key.className = 'tip-key';
      var lbl = document.createElement('span'); lbl.textContent = dayLabel(d.day, true);
      row.appendChild(key); row.appendChild(lbl);
      var sub = document.createElement('div'); sub.className = 'tip-sub';
      sub.textContent = cost ? int(d.runs) + (d.runs === 1 ? ' run' : ' runs') : formatUsd(d.cost) + ' estimated';
      tip.appendChild(v); tip.appendChild(row); tip.appendChild(sub);
      tip.hidden = false;
      var r = el.getBoundingClientRect(), tw = tip.offsetWidth;
      var x = ev && ev.clientX != null ? ev.clientX : r.left + r.width / 2;
      tip.style.left = Math.max(8, Math.min(window.innerWidth - tw - 8, x - tw / 2)) + 'px';
      tip.style.top = Math.max(8, r.top - tip.offsetHeight + 4) + 'px';
    }
    function hide() {
      tip.hidden = true;
      [].forEach.call(box.querySelectorAll('.bar.hot'), function (b) { b.classList.remove('hot'); });
    }
    [].forEach.call(box.querySelectorAll('.hit'), function (el) {
      el.addEventListener('pointermove', function (ev) { show(ev, el); });
      el.addEventListener('focus', function () { show(null, el); });
      el.addEventListener('pointerleave', hide);
      el.addEventListener('blur', hide);
    });
  }

  // ---- by tool: horizontal bars, value at the tip; a row filters to it -------------
  function drawTools() {
    var box = $('toolChart');
    if (!SUM || !box) return;                    // the tool cards above show runs per tool now
    var cost = S.measure === 'cost';
    var rows = SUM.by_tool.filter(function (t) { return t.runs > 0; })
      .sort(function (a, b) { return (cost ? b.cost - a.cost : b.runs - a.runs) || a.label.localeCompare(b.label); });
    box.classList.toggle('has-sel', !!S.tool);
    if (!rows.length) { box.innerHTML = '<div class="tb-empty">No runs in this view.</div>'; return; }
    var max = Math.max.apply(null, rows.map(function (t) { return cost ? t.cost : t.runs; })) || 1;
    box.innerHTML = rows.map(function (t) {
      var v = cost ? t.cost : t.runs;
      var pct = Math.max(0.5, v / max * 100);
      return '<button type="button" class="tb-row' + (S.tool === t.key ? ' sel' : '') + '" data-tool="' + esc(t.key) +
        '" title="' + esc(t.label + ': ' + int(t.runs) + ' runs, ' + formatUsd(t.cost) + (S.tool === t.key ? ' — click to show all tools' : ' — click to filter')) + '">' +
        '<span class="tb-label">' + esc(t.label) + '</span>' +
        '<span class="tb-track"><span class="tb-bar" style="width:' + pct.toFixed(2) + '%"></span>' +
        '<span class="tb-val">' + esc(cost ? usdShort(t.cost) : int(t.runs)) + '</span></span></button>';
    }).join('');
  }
  if ($('toolChart')) $('toolChart').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-tool]'); if (!b) return;
    var k = b.getAttribute('data-tool');
    S.tool = S.tool === k ? '' : k; refilter();
  });

  // ---- table ------------------------------------------------------------------------
  function drawRows(res) {
    var tb = $('rows');
    var from = res.page * res.per_page;
    $('count').textContent = res.total ? 'newest first · ' + int(res.total) + (res.total === 1 ? ' run' : ' runs') : '';
    if (!res.rows.length) {
      tb.innerHTML = '<tr class="empty-row"><td colspan="8">' +
        (S.tool || S.agent || S.model || S.q ? 'No runs match these filters.' : 'No runs in this period.') + '</td></tr>';
    } else {
      var byDay = {}, today = dayIdx(Date.now()), lastD = null;
      ((SUM && SUM.by_day) || []).forEach(function (d) { byDay[d.day] = d; });
      tb.innerHTML = res.rows.map(function (r) {
        var di = dayIdx(r.ts_ms), head = '';
        if (di !== lastD) {
          lastD = di;
          var dd = byDay[di] || {}, name = di === today ? 'Today' : di === today - 1 ? 'Yesterday' : '';
          head = '<tr class="lg-day"><td colspan="8"><b>' + esc(name ? name + ' · ' + dayLabel(di, true) : dayLabel(di, true)) + '</b>' +
            (dd.runs != null ? '<span class="muted"> · ' + int(dd.runs) + (dd.runs === 1 ? ' run' : ' runs') + ' · ' + esc(formatUsd(dd.cost)) + '</span>' : '') + '</td></tr>';
        }
        var model = shortModel(r.model);
        var zero = function (n) { return n ? int(n) : '<span class="muted">0</span>'; };
        return head + '<tr>' +
          '<td class="when">' + esc(String(new Date(r.ts_ms).getHours()).padStart(2, '0') + ':' + String(new Date(r.ts_ms).getMinutes()).padStart(2, '0')) + '</td>' +
          '<td>' + esc(r.agent || '—') + '</td>' +
          '<td>' + esc(r.kind) + '</td>' +
          '<td' + (model ? ' title="' + esc(r.model) + '"' : ' class="muted"') + '>' + esc(model || '—') + '</td>' +
          '<td class="topic" title="' + esc(r.topic || '') + '">' + esc(r.topic || '—') + '</td>' +
          '<td class="n">' + int(r.tickets) + '</td>' +
          '<td class="n" title="' + int(r.input_tokens || 0) + ' in, ' + int(r.output_tokens || 0) + ' out">' +
            (r.input_tokens || r.output_tokens ? compact(r.input_tokens || 0) + ' <span class="muted">/</span> ' + compact(r.output_tokens || 0)
                                                : '<span class="muted">0</span>') + '</td>' +
          '<td class="n">' + esc(formatUsd(r.cost)) + '</td>' +
          '</tr>';
      }).join('');
    }
    var pages = Math.ceil(res.total / res.per_page);
    $('pager').hidden = pages <= 1;
    $('prev').disabled = res.page <= 0;
    $('next').disabled = res.page >= pages - 1;
    $('pagerTxt').textContent = res.total ? int(from + 1) + '–' + int(from + res.rows.length) + ' of ' + int(res.total) : '';
  }

  var resizing = null;
  window.addEventListener('resize', function () { clearTimeout(resizing); resizing = setTimeout(drawDays, 120); });

  boot();
})();
