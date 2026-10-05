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
      var wait = add('ai', '<span class="spin-dot" aria-hidden="true"></span> Looking it up&hellip;', 'pending');
      fetch('/api/ask', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ messages: MSGS, focus: opts.focus || null }) })
        .then(function (r) {
          if (r.status === 401) { location.href = '/?next=' + encodeURIComponent(location.pathname); throw new Error('login'); }
          return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
        })
        .then(function (r) {
          MSGS.push({ role: 'assistant', content: r.answer || '' });
          var steps = (r.steps || []).map(function (s) {
            var a = s.args || {}, bits = Object.keys(a).filter(function (k) { return a[k] !== '' && a[k] != null; })
              .map(function (k) { return k + ': ' + (typeof a[k] === 'object' ? JSON.stringify(a[k]) : a[k]); });
            return '<span class="ask-step">' + esc(STEP_NAMES[s.tool] || s.tool) + (bits.length ? ' <i>(' + esc(bits.join(', ')) + ')</i>' : '') + '</span>';
          });
          wait.classList.remove('pending');
          wait.innerHTML = format(r.answer || 'No answer.') +
            '<div class="ask-steps">' + (steps.length ? 'Looked at: ' + steps.join('') : 'Answered without looking anything up.') + '</div>';
          log.scrollTop = log.scrollHeight;
        })
        .catch(function (e) {
          MSGS.pop();
          wait.classList.remove('pending'); wait.classList.add('err');
          wait.textContent = e.message === 'login' ? '' : 'Couldn’t answer: ' + e.message;
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
