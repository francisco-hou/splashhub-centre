// SplashHub Centre -- Downloads (downloads.py). Open to everyone, signed in or not;
// adding, updating and removing need the Admin role (the server says so in
// can_manage, and refuses otherwise).
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  var ICON = {
    puzzle: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h3a1 1 0 0 0 1-1V5a2 2 0 1 1 4 0v1a1 1 0 0 0 1 1h3a1 1 0 0 1 1 1v3a1 1 0 0 0 1 1h1a2 2 0 1 1 0 4h-1a1 1 0 0 0-1 1v3a1 1 0 0 1-1 1h-3a1 1 0 0 1-1-1v-1a2 2 0 1 0-4 0v1a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a2 2 0 1 0 0-4H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1"/></svg>',
    dl: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>'
  };
  var ITEMS = [], CAN = false;

  function size(n) { return n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round((n || 0) / 1024)) + ' KB'; }
  function when(t) { return t ? new Date(t * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : ''; }
  function link(v) { return '/d/' + v.vid + '/' + encodeURIComponent(v.file); }

  function draw() {
    var q = ($('q').value || '').toLowerCase().trim();
    var rows = ITEMS.filter(function (x) { return !q || (x.name + ' ' + x.description).toLowerCase().indexOf(q) >= 0; });
    $('addBtn').hidden = !CAN;
    if (!rows.length) {
      $('list').innerHTML = '<div class="empty">' + (ITEMS.length ? 'Nothing matches &ldquo;' + esc(q) + '&rdquo;.' :
        'No extensions here yet.' + (CAN ? ' Press <b>Add extension</b> to upload the first one.' : '')) + '</div>';
      return;
    }
    $('list').innerHTML = rows.map(function (x, i) {
      var vs = x.versions || [];
      var older = vs.slice(1).map(function (v) {
        return '<div class="vrow"><div><b>' + esc(v.version ? 'v' + v.version : '—') + '</b><small>' + esc(when(v.uploaded_at)) + '</small></div>' +
          '<div>' + (v.whats_new ? esc(v.whats_new) : '<span style="color:#8a96a3">First version</span>') + '</div>' +
          '<a class="btn btn-sm" href="' + link(v) + '">' + ICON.dl + 'Download</a></div>';
      }).join('');
      return '<article class="card" style="animation-delay:' + (i * 0.05).toFixed(2) + 's">' +
        '<div class="ic">' + ICON.puzzle + '</div>' +
        '<div><div class="nm"><h3>' + esc(x.name) + '</h3>' + (x.version ? '<span class="ver">v' + esc(x.version) + '</span>' : '') + '</div>' +
          '<p class="desc">' + esc(x.description) + '</p>' +
          '<div class="meta"><span>Updated ' + esc(when(x.uploaded_at)) + '</span><span>' + esc(size(x.size)) + '</span>' +
            (x.added_by ? '<span>By ' + esc(x.added_by) + '</span>' : '') + '<span>' + esc(x.file) + '</span></div>' +
          (x.whats_new ? '<div class="new"><b>What&rsquo;s new:</b> ' + esc(x.whats_new) + '</div>' : '') +
          (x.permissions && x.permissions.length ? '<div class="perm">' + x.permissions.map(function (p) { return '<span>' + esc(p) + '</span>'; }).join('') + '</div>' : '') +
          (older ? '<details class="vers"><summary>Earlier versions (' + (vs.length - 1) + ')</summary>' + older + '</details>' : '') +
        '</div>' +
        '<div class="acts"><a class="btn btn-primary" href="' + link(vs[0] || x) + '">' + ICON.dl + 'Download</a>' +
          (CAN ? '<button type="button" class="btn btn-sm" data-upd="' + esc(x.id) + '">New version</button>' +
                 '<button type="button" class="btn btn-sm btn-danger" data-del="' + esc(x.id) + '">Remove</button>' : '') +
        '</div></article>';
    }).join('');
  }

  function load() {
    fetch('/api/downloads/list', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (d) {
      ITEMS = (d.items || []).map(function (x) { x.versions = x.versions || [x]; return x; });
      CAN = !!d.can_manage;
      draw();
    }).catch(function () { $('list').innerHTML = '<div class="empty">Couldn&rsquo;t load the list. Try again in a moment.</div>'; });
  }

  // ---- admin: add, new version, remove -------------------------------------------------
  function sheet(title, fields, url) {
    $('sheet').innerHTML = '<form class="sheet" id="up"><h3>' + esc(title) + '</h3>' +
      '<label class="fld">Package (.zip or .crx)<input type="file" name="file" accept=".zip,.crx" required></label>' + fields +
      '<div class="msg" id="upMsg" aria-live="polite"></div>' +
      '<div style="display:flex;gap:8px"><button type="submit" class="btn btn-primary">Upload</button><button type="button" class="btn" id="upX">Cancel</button></div></form>';
    $('upX').addEventListener('click', function () { $('sheet').innerHTML = ''; });
    $('up').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var f = ev.target, b = f.querySelector('[type=submit]'), msg = $('upMsg');
      msg.className = 'msg'; msg.textContent = 'Uploading…'; b.disabled = true;
      fetch(url, { method: 'POST', credentials: 'same-origin', body: new FormData(f) })
        .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; }); })
        .then(function () { $('sheet').innerHTML = ''; load(); })
        .catch(function (e) { b.disabled = false; msg.className = 'msg err'; msg.textContent = e.message; });
    });
    $('sheet').querySelector('input').focus();
  }
  var BY = '<label class="fld">Added by<input name="added_by" required maxlength="80" placeholder="Your name"></label>';
  $('addBtn').addEventListener('click', function () {
    sheet('Add an extension', '<div class="row2"><label class="fld">Name<input name="name" required maxlength="120"></label>' + BY + '</div>' +
      '<label class="fld">Description<textarea name="description" required maxlength="1000"></textarea></label>', '/api/downloads/upload');
  });
  $('list').addEventListener('click', function (ev) {
    var u = ev.target.closest('[data-upd]'), d = ev.target.closest('[data-del]');
    if (u) {
      var x = ITEMS.filter(function (i) { return i.id === u.getAttribute('data-upd'); })[0];
      sheet('New version of ' + (x ? x.name : 'this extension'), BY + '<label class="fld">What&rsquo;s new<textarea name="whats_new" required maxlength="2000"></textarea></label>',
            '/api/downloads/' + u.getAttribute('data-upd') + '/update');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    if (d) {
      var y = ITEMS.filter(function (i) { return i.id === d.getAttribute('data-del'); })[0];
      if (!confirm('Remove ' + (y ? y.name : 'this extension') + ' from Downloads?\n\nIt leaves the list; its files are kept, so it can be put back.')) return;
      fetch('/api/downloads/' + d.getAttribute('data-del') + '/delete', { method: 'POST', credentials: 'same-origin' })
        .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); }); })
        .then(load).catch(function (e) { alert(e.message); });
    }
  });
  $('q').addEventListener('input', draw);
  load();
})();
