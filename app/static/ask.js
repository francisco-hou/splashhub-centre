// SplashHub Centre -- Ask AI page.
//
// A conversation with Spark about SplashHub Centre's own data (askai.py on
// the server). The conversation lives in this page only; the server keeps
// nothing but a line in the run log. Answers are escaped, then given a little
// formatting: lists, bold, and #12345 as a link to the Zendesk ticket.
(function () {
  'use strict';

  var MSGS = [];
  var ZD = '';
  var STEP_NAMES = { sos_overview: 'SOS overview', sos_search: 'SOS search', sos_request: 'one SOS request',
                     sso_lookup: 'SSO requests', runs_summary: 'run log' };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function api(path, opts) {
    return fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {})).then(function (r) {
      if (r.status === 401) { location.href = '/?next=/ask'; throw new Error('login'); }
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }

  fetch('/api/session', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (s) {
    if (s.required && !s.authed) { location.href = '/?next=/ask'; return; }
    $('signOut').hidden = !s.required;
    $('page').hidden = false;
    api('/api/scan-setup').then(function (x) { ZD = x.zendesk_url; }).catch(function () {});
    $('q').focus();
  });
  $('signOut').addEventListener('click', function () {
    fetch('/logout', { method: 'POST', credentials: 'same-origin' }).then(function () { location.href = '/'; });
  });

  // A little formatting on escaped text: "- " lists, **bold**, #12345 links.
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

  function add(role, html, cls) {
    $('empty').hidden = true;
    var d = document.createElement('div');
    d.className = 'ask-msg ' + role + (cls ? ' ' + cls : '');
    d.innerHTML = html;
    $('log').appendChild(d);
    d.scrollIntoView({ block: 'end', behavior: 'smooth' });
    return d;
  }

  function send(text) {
    text = (text || '').trim();
    if (!text) return;
    MSGS.push({ role: 'user', content: text });
    add('user', esc(text));
    $('q').value = ''; autosize();
    $('send').disabled = true;
    var wait = add('ai', '<span class="spin-dot" aria-hidden="true"></span> Looking it up&hellip;', 'pending');
    api('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: MSGS }) })
      .then(function (r) {
        MSGS.push({ role: 'assistant', content: r.answer || '' });
        var steps = (r.steps || []).map(function (s) {
          var a = s.args || {}, bits = Object.keys(a).filter(function (k) { return a[k] !== '' && a[k] != null; })
            .map(function (k) { return k + ': ' + a[k]; });
          return '<span class="ask-step">' + esc(STEP_NAMES[s.tool] || s.tool) + (bits.length ? ' <i>(' + esc(bits.join(', ')) + ')</i>' : '') + '</span>';
        });
        wait.classList.remove('pending');
        wait.innerHTML = format(r.answer || 'No answer.') +
          (steps.length ? '<div class="ask-steps">Looked at: ' + steps.join('') + '</div>' : '<div class="ask-steps">Answered without looking anything up.</div>');
      })
      .catch(function (e) {
        MSGS.pop();
        wait.classList.remove('pending'); wait.classList.add('err');
        wait.textContent = e.message === 'login' ? '' : 'Couldn’t answer: ' + e.message;
      })
      .then(function () { $('send').disabled = false; $('q').focus(); });
  }

  $('form').addEventListener('submit', function (ev) { ev.preventDefault(); send($('q').value); });
  $('q').addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); send(this.value); }
  });
  function autosize() { var t = $('q'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 160) + 'px'; }
  $('q').addEventListener('input', autosize);
  $('sugg').addEventListener('click', function (ev) { var b = ev.target.closest('button'); if (b) send(b.textContent); });
  $('newChat').addEventListener('click', function () {
    MSGS = [];
    [].slice.call($('log').querySelectorAll('.ask-msg')).forEach(function (n) { n.remove(); });
    $('empty').hidden = false; $('q').focus();
  });
})();
