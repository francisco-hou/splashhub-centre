// SplashHub Centre -- the AI chat, as one piece used in two places: the AI page
// and the PriceBook's side panel.
//
//   AiChat.mount(rootElement, { focus: 'prices' | undefined, suggestions: [...],
//                               placeholder: '...' })
//
// The conversation lives in the page only; the server (askai.py) answers with
// Spark and read-only lookups, and keeps nothing but a line in the run log.
// Answers are escaped, then given a little formatting: lists, bold, and
// #12345 as a link to the Zendesk ticket.
window.AiChat = (function () {
  'use strict';

  var STEP_NAMES = { sos_overview: 'SOS overview', sos_search: 'SOS search', sos_request: 'one SOS request',
                     sso_lookup: 'SSO requests', runs_summary: 'run log', prices: 'PriceBook',
                     plan_guide: 'plan guide', quote: 'quote' };
  var ZD = '';
  fetch('/api/scan-setup', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (x) { ZD = x.zendesk_url || ''; }).catch(function () {});

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function format(text) {
    var lines = esc(text).split('\n'), out = [], list = [];
    function flush() { if (list.length) { out.push('<ul>' + list.join('') + '</ul>'); list = []; } }
    lines.forEach(function (l) {
      var m = /^\s*(?:[-*•]|\d+\.)\s+(.*)$/.exec(l);
      if (m) { list.push('<li>' + m[1] + '</li>'); return; }
      flush();
      if (l.trim()) out.push('<p>' + l + '</p>');
    });
    flush();
    return out.join('')
      .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
      .replace(/#(\d{3,9})\b/g, function (m, n) {
        return ZD ? '<a href="' + esc(ZD) + '/agent/tickets/' + n + '" target="_blank" rel="noopener">#' + n + '</a>' : m;
      });
  }

  // ---- the wait: what is happening right now, a ticking timer, and each
  // finished lookup ticked off. Lines come from the server as they happen
  // (stream); between them -- or if a proxy holds the stream back -- the
  // message moves on by itself every couple of seconds, so it never sits still.
  var IC = {
    spark: '<path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    search: '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.6" y2="16.6"/>',
    chart: '<line x1="6" y1="20" x2="6" y2="13"/><line x1="12" y1="20" x2="12" y2="6"/><line x1="18" y1="20" x2="18" y2="10"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
    key: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2"/><path d="M16 7l3 3"/>',
    list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
    tag: '<path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8z"/><circle cx="7" cy="7" r="1.5"/>',
    book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
    calc: '<rect x="4" y="2" width="16" height="20" rx="2"/><line x1="8" y1="6" x2="16" y2="6"/><line x1="8" y1="11" x2="8.01" y2="11"/><line x1="12" y1="11" x2="12.01" y2="11"/><line x1="16" y1="11" x2="16.01" y2="11"/><line x1="8" y1="15" x2="8.01" y2="15"/><line x1="12" y1="15" x2="12.01" y2="15"/><line x1="16" y1="15" x2="16.01" y2="15"/>',
    pen: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    check: '<polyline points="20 6 9 17 4 12"/>',
    clock: '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/>'
  };
  function icon(k) { return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + IC[k] + '</svg>'; }
  var DOING = {
    sos_overview: ['chart', 'Counting SOS requests…'], sos_search: ['search', 'Searching SOS requests…'],
    sos_request: ['file', 'Opening the SOS request…'], sso_lookup: ['key', 'Checking SSO requests…'],
    runs_summary: ['list', 'Reading the run log…'], prices: ['tag', 'Opening the PriceBook…'],
    plan_guide: ['book', 'Checking the plan rules…'], quote: ['calc', 'Pricing the options…']
  };
  var FIRST = [['spark', 'Reading your question…'], ['search', 'Working out what to look up…'], ['spark', 'Asking Spark…']];
  var LATER = [['pen', 'Putting the answer together…'], ['calc', 'Double-checking the numbers…'], ['pen', 'Writing it up…']];
  function secs(ms) { return (ms / 1000).toFixed(1) + ' s'; }

  function progress(el) {
    var t0 = Date.now(), lastEv = t0, pool = FIRST, k = 0, done = [], step = null, cur = FIRST[0];
    el.innerHTML = '<div class="ask-prog"><span class="ask-now"><span class="ask-ic"></span><span class="ask-txt"></span></span>' +
      '<span class="ask-clock">' + icon('clock') + '<b>0.0 s</b></span></div><div class="ask-done"></div>';
    var ic = el.querySelector('.ask-ic'), txt = el.querySelector('.ask-txt'), clock = el.querySelector('.ask-clock b'), list = el.querySelector('.ask-done');
    function show(c) {
      cur = c;
      txt.classList.remove('ask-in'); void txt.offsetWidth; txt.classList.add('ask-in');   // replay the fade-in
      ic.innerHTML = icon(c[0]); txt.textContent = c[1];
    }
    show(cur);
    var tick = setInterval(function () {
      var now = Date.now();
      clock.textContent = secs(now - t0);
      if (!step && now - lastEv > 2400) { lastEv = now; k = (k + 1) % pool.length; show(pool[k]); }
    }, 100);
    return {
      event: function (e) {
        lastEv = Date.now();
        if (e.phase === 'step') {
          if (step) done.push(step);
          step = DOING[e.tool] || ['search', 'Looking it up…'];
          show(step);
        } else if (e.phase === 'think' && e.round > 0) {
          if (step) done.push(step);
          step = null; pool = LATER; k = 0; show(LATER[0]);
        }
        list.innerHTML = done.map(function (c) { return '<span class="ask-tick">' + icon('check') + esc(c[1].replace(/…$/, '')) + '</span>'; }).join('');
      },
      stop: function () { clearInterval(tick); return Date.now() - t0; }
    };
  }

  // The answer as a stream of JSON lines (events, then {done} or {error});
  // a plain JSON answer if anything in between doesn't stream.
  function readAnswer(r, onEvent) {
    var ct = r.headers.get('Content-Type') || '';
    if (ct.indexOf('ndjson') < 0 || !r.body || !r.body.getReader) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    }
    var reader = r.body.getReader(), dec = new TextDecoder(), buf = '', final = null;
    function line(l) {
      if (!l.trim()) return;
      var j = JSON.parse(l);
      if (j.error) throw new Error(j.error);
      if (j.done) final = j; else onEvent(j);
    }
    function pump() {
      return reader.read().then(function (x) {
        if (x.value) {
          buf += dec.decode(x.value, { stream: true });
          var parts = buf.split('\n'); buf = parts.pop();
          parts.forEach(line);
        }
        if (!x.done) return pump();
        line(buf);
        if (!final) throw new Error('the answer was cut off');
        return final;
      });
    }
    return pump();
  }

  function mount(root, opts) {
    opts = opts || {};
    var MSGS = [];
    root.classList.add('aichat');
    root.innerHTML =
      '<div class="ask-log" aria-live="polite"><div class="ask-empty"><div class="ask-empty-t">Try one of these</div>' +
        '<div class="ask-sugg">' + (opts.suggestions || []).map(function (s) { return '<button type="button">' + esc(s) + '</button>'; }).join('') + '</div></div></div>' +
      '<form class="ask-form"><textarea rows="1" placeholder="' + esc(opts.placeholder || 'Ask a question…') + '" aria-label="Your question"></textarea>' +
        '<button type="submit" class="btn btn-primary">Ask</button></form>' +
      '<div class="ask-foot">Spark can be wrong &mdash; check before acting. Nothing you ask changes anything or reaches Zendesk.</div>';
    var log = root.querySelector('.ask-log'), empty = root.querySelector('.ask-empty'),
        form = root.querySelector('.ask-form'), q = root.querySelector('textarea'), send = form.querySelector('button');

    function add(role, html, cls) {
      empty.hidden = true;
      var d = document.createElement('div');
      d.className = 'ask-msg ' + role + (cls ? ' ' + cls : '');
      d.innerHTML = html;
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
      return d;
    }
    function autosize() { q.style.height = 'auto'; q.style.height = Math.min(q.scrollHeight, 160) + 'px'; }

    function ask(text) {
      text = (text || '').trim();
      if (!text) return;
      MSGS.push({ role: 'user', content: text });
      add('user', esc(text));
      q.value = ''; autosize();
      send.disabled = true;
      var wait = add('ai', '', 'pending'), prog = progress(wait);
      log.scrollTop = log.scrollHeight;
      fetch('/api/ask', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ messages: MSGS, focus: opts.focus || null, stream: true }) })
        .then(function (r) {
          if (r.status === 401) { location.href = '/logs?next=' + encodeURIComponent(location.pathname); throw new Error('login'); }
          return readAnswer(r, function (e) { prog.event(e); log.scrollTop = log.scrollHeight; });
        })
        .then(function (r) {
          var took = prog.stop();
          MSGS.push({ role: 'assistant', content: r.answer || '' });
          var steps = (r.steps || []).map(function (s) {
            var a = s.args || {}, bits = Object.keys(a).filter(function (k) { return a[k] !== '' && a[k] != null; })
              .map(function (k) { return k + ': ' + (typeof a[k] === 'object' ? JSON.stringify(a[k]) : a[k]); });
            return '<span class="ask-step">' + esc(STEP_NAMES[s.tool] || s.tool) + (bits.length ? ' <i>(' + esc(bits.join(', ')) + ')</i>' : '') + '</span>';
          });
          wait.classList.remove('pending');
          wait.innerHTML = format(r.answer || 'No answer.') +
            '<div class="ask-steps"><span class="ask-took" title="From asking to the answer">' + icon('clock') + 'Answered in ' + secs(took) + '</span>' +
            (steps.length ? '<span class="ask-sep">·</span>Looked at: ' + steps.join('') : '<span class="ask-sep">·</span>No lookups needed') + '</div>';
          log.scrollTop = log.scrollHeight;
        })
        .catch(function (e) {
          var took = prog.stop();
          MSGS.pop();
          wait.classList.remove('pending'); wait.classList.add('err');
          wait.textContent = e.message === 'login' ? '' : 'Couldn’t answer: ' + e.message + ' (after ' + secs(took) + ')';
        })
        .then(function () { send.disabled = false; q.focus(); });
    }

    form.addEventListener('submit', function (ev) { ev.preventDefault(); ask(q.value); });
    q.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); ask(q.value); } });
    q.addEventListener('input', autosize);
    root.querySelector('.ask-sugg').addEventListener('click', function (ev) { var b = ev.target.closest('button'); if (b) ask(b.textContent); });

    return {
      reset: function () {
        MSGS = [];
        [].slice.call(log.querySelectorAll('.ask-msg')).forEach(function (n) { n.remove(); });
        empty.hidden = false; q.focus();
      },
      focus: function () { q.focus(); },
      ask: ask
    };
  }

  return { mount: mount };
})();
