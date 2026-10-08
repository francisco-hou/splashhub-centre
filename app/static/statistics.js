// SplashHub Centre -- Statistics (stats.py, admin): how often the Wrap Up note is
// on the tickets the team solves. Chats and tickets (calls aren't counted),
// counts only: totals, per week, per agent. Read only.
(function () {
  'use strict';

  var S = { period: '30', data: null, table: false };
  var C_WRAP = '#0b5cad', C_REST = '#6fb1ea';     // validated pair (dataviz validator: all checks pass)

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function int(n) { return (n || 0).toLocaleString('en-US'); }
  function pct(a, b) { return b ? Math.round(100 * a / b) + '%' : '—'; }
  function api(path, opts) {
    return fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {})).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function day(ymd) { var d = new Date(ymd + 'T00:00:00Z'); return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }); }
  function when(ms) { if (!ms) return ''; var d = new Date(ms); return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }

  // ---- totals -----------------------------------------------------------------------------------
  function tiles(d) {
    var c = d.total.chat, t = d.total.ticket, solved = c.solved + t.solved, wrapped = c.wrapped + t.wrapped;
    var tile = function (label, value, sub) {
      return '<div class="stat"><div class="stat-label">' + label + '</div><div class="stat-value">' + value + '</div><div class="stat-sub">' + sub + '</div></div>';
    };
    $('stats').innerHTML =
      tile('Solved', int(solved), int(c.solved) + ' chats · ' + int(t.solved) + ' tickets') +
      tile('With a Wrap Up note', int(wrapped), int(c.wrapped) + ' chats · ' + int(t.wrapped) + ' tickets') +
      tile('Wrapped up', pct(wrapped, solved), 'of solved chats and tickets') +
      tile('Chats', pct(c.wrapped, c.solved), int(c.wrapped) + ' of ' + int(c.solved)) +
      tile('Tickets', pct(t.wrapped, t.solved), int(t.wrapped) + ' of ' + int(t.solved));
  }

  // ---- per week: stacked bars (wrapped at the base, the rest above), % as a label ------------------
  function chart(d) {
    var ws = d.weeks.slice(-12);
    if (!ws.length) { $('chart').innerHTML = '<div class="st-empty">No weeks read yet.</div>'; return; }
    if (S.table) {
      $('chart').innerHTML = '<table class="runs st-wtable"><thead><tr><th>Week of</th><th>Solved</th><th>With Wrap Up</th><th>%</th></tr></thead><tbody>' +
        ws.slice().reverse().map(function (w) { return '<tr><td>' + esc(day(w.week)) + '</td><td>' + int(w.solved) + '</td><td>' + int(w.wrapped) + '</td><td>' + pct(w.wrapped, w.solved) + '</td></tr>'; }).join('') +
        '</tbody></table>';
      return;
    }
    var W = Math.max(420, ($('chart').clientWidth || 760) - 32), H = 240, padL = 40, padB = 28, padT = 22, plotH = H - padB - padT;   // drawn at the box's own width: text at its real size
    var max = Math.max.apply(null, ws.map(function (w) { return w.solved; })) || 1;
    var step = Math.pow(10, Math.floor(Math.log10(max))), top = Math.ceil(max / step) * step;
    var slot = (W - padL) / ws.length, bw = Math.min(46, slot * 0.6);
    var y = function (v) { return padT + plotH - plotH * v / top; };
    var bar = function (x, y0, y1, color, roundTop) {        // a bar segment from y1 (top) to y0 (bottom); 4px rounded top when it's the end
      var h = Math.max(0, y0 - y1); if (!h) return '';
      if (!roundTop || h < 5) return '<rect x="' + x + '" y="' + y1 + '" width="' + bw + '" height="' + h + '" fill="' + color + '"/>';
      var r = 4;
      return '<path d="M' + x + ',' + y0 + 'V' + (y1 + r) + 'Q' + x + ',' + y1 + ' ' + (x + r) + ',' + y1 + 'H' + (x + bw - r) + 'Q' + (x + bw) + ',' + y1 + ' ' + (x + bw) + ',' + (y1 + r) + 'V' + y0 + 'Z" fill="' + color + '"/>';
    };
    var g = '';
    [0, top / 2, top].forEach(function (v) {
      g += '<line x1="' + padL + '" x2="' + W + '" y1="' + y(v) + '" y2="' + y(v) + '" class="st-grid"/>' +
        '<text x="' + (padL - 8) + '" y="' + (y(v) + 4) + '" class="st-ax" text-anchor="end">' + int(v) + '</text>';
    });
    ws.forEach(function (w, i) {
      var x = padL + slot * i + (slot - bw) / 2, base = y(0), yw = y(w.wrapped), ys = y(w.solved), rest = w.solved - w.wrapped;
      g += '<g class="st-bar" tabindex="0" data-i="' + i + '"><rect class="st-hit" x="' + (padL + slot * i) + '" y="' + padT + '" width="' + slot + '" height="' + plotH + '"/>' +
        bar(x, base, yw, C_WRAP, rest === 0) +
        bar(x, yw - (w.wrapped && rest ? 2 : 0), ys, C_REST, true) +            // 2px surface gap between the two
        '<text x="' + (x + bw / 2) + '" y="' + (ys - 6) + '" class="st-lbl" text-anchor="middle">' + pct(w.wrapped, w.solved) + '</text>' +
        '<text x="' + (x + bw / 2) + '" y="' + (H - 8) + '" class="st-ax" text-anchor="middle">' + esc(day(w.week)) + '</text></g>';
    });
    $('chart').innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" class="st-svg" role="img" aria-label="Solved tickets per week and how many had a Wrap Up note">' + g + '</svg>' +
      '<div class="st-tip" id="tip" hidden></div>';
    var tip = $('tip'), svg = $('chart').querySelector('svg');
    function show(el) {
      var w = ws[+el.getAttribute('data-i')], r = el.getBoundingClientRect(), box = $('chart').getBoundingClientRect();
      tip.innerHTML = '<b>Week of ' + esc(day(w.week)) + '</b><div><span class="st-sw" style="background:' + C_WRAP + '"></span>With Wrap Up: ' + int(w.wrapped) +
        '</div><div><span class="st-sw" style="background:' + C_REST + '"></span>Without: ' + int(w.solved - w.wrapped) + '</div><div class="muted">' + int(w.solved) + ' solved · ' + pct(w.wrapped, w.solved) + '</div>';
      tip.hidden = false;
      var left = r.left - box.left + r.width / 2 - tip.offsetWidth / 2;
      tip.style.left = Math.max(0, Math.min(box.width - tip.offsetWidth, left)) + 'px';
      tip.style.top = Math.max(0, r.top - box.top + 10) + 'px';
      [].forEach.call(svg.querySelectorAll('.st-bar'), function (b) { b.classList.toggle('dim', b !== el); });
    }
    function hide() { tip.hidden = true; [].forEach.call(svg.querySelectorAll('.st-bar'), function (b) { b.classList.remove('dim'); }); }
    [].forEach.call(svg.querySelectorAll('.st-bar'), function (el) {
      el.addEventListener('mouseenter', function () { show(el); });
      el.addEventListener('focus', function () { show(el); });
      el.addEventListener('mouseleave', hide);
      el.addEventListener('blur', hide);
    });
  }

  // ---- per agent ----------------------------------------------------------------------------------
  function meter(a, b) {
    if (!b) return '<span class="muted">—</span>';
    var p = Math.round(100 * a / b);
    return '<span class="st-meter"><span style="width:' + p + '%"></span></span> <b>' + p + '%</b>';
  }
  function agents(d) {
    $('agents').innerHTML = d.agents.length ? d.agents.map(function (a) {
      var s = a.chat.solved + a.ticket.solved, w = a.chat.wrapped + a.ticket.wrapped;
      return '<tr><td>' + esc(a.agent) + '</td>' +
        '<td class="num">' + int(a.chat.solved) + '</td><td class="num">' + int(a.chat.wrapped) + '</td><td>' + meter(a.chat.wrapped, a.chat.solved) + '</td>' +
        '<td class="num">' + int(a.ticket.solved) + '</td><td class="num">' + int(a.ticket.wrapped) + '</td><td>' + meter(a.ticket.wrapped, a.ticket.solved) + '</td>' +
        '<td>' + meter(w, s) + '</td></tr>';
    }).join('') : '<tr class="empty-row"><td colspan="8">Nothing solved in this period yet.</td></tr>';
  }

  // ---- loading ------------------------------------------------------------------------------------
  function load() {
    return api('/api/stats?period=' + S.period).then(function (d) {
      S.data = d;
      var st = d.state || {}, n = $('note');
      if (st.error) { n.hidden = false; n.textContent = 'Last round: ' + st.error; }
      else if (d.pending || st.busy) {
        n.hidden = false;
        n.textContent = 'Still reading conversations' + (d.pending ? ' — ' + int(d.pending) + ' solved ticket' + (d.pending === 1 ? '' : 's') + ' in this period not read yet' : '') +
          '. The numbers fill in as they are read (a few hundred a minute, gently on Zendesk).';
      } else n.hidden = true;
      $('stamp').textContent = st.last_ms ? 'Read ' + when(st.last_ms) + ' · every 15 min' : 'Starting…';
      $('since').textContent = 'Since ' + day(d.since);
      tiles(d); chart(d); agents(d);
    }).catch(function (e) { $('note').hidden = false; $('note').textContent = 'Could not load Statistics: ' + e.message; });
  }
  $('period').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-p]'); if (!b) return;
    S.period = b.getAttribute('data-p');
    [].forEach.call(this.children, function (c) { c.classList.toggle('active', c === b); });
    load();
  });
  $('asTable').addEventListener('click', function () {
    S.table = !S.table; this.textContent = S.table ? 'Show as chart' : 'Show as table';
    if (S.data) chart(S.data);
  });
  $('refresh').addEventListener('click', function () {
    var b = this; b.classList.add('spin');
    api('/api/stats/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(function () {})
      .then(function () { setTimeout(function () { load().then(function () { b.classList.remove('spin'); }); }, 1500); });
  });
  var rzT = 0;
  window.addEventListener('resize', function () { clearTimeout(rzT); rzT = setTimeout(function () { if (S.data && !S.table) chart(S.data); }, 150); });
  load();
  setInterval(function () { if (document.visibilityState === 'visible') load(); }, 30000);
})();
