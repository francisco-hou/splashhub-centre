// SplashHub Centre -- SOS Scans page.
//
// Every Custom SOS package request a Zendesk trigger sends here (or that an
// admin starts with "Scan a ticket") is brand-reviewed by the server
// (sosscan.py) and listed here; a row opens into the full review. While any
// scan is queued or running the list refreshes itself every few seconds.
(function () {
  'use strict';

  var S = { verdict: '', q: '', page: 0, open: null };
  var ZD = '';
  var LABEL = { suspicious: 'Suspicious', needs_review: 'Needs review', normal: 'Normal',
                queued: 'Queued', running: 'Scanning…', waiting: 'Waiting', held: 'AI off', past: 'Past request', skipped: 'Skipped', error: 'Error', not_applicable: 'Not applicable' };
  var REF = { none: 'No Splashtop reference', powered_by_attribution: '“Powered by Splashtop” credit',
              unmodified_default: 'Splashtop default UI visible', other_reference: 'Misleading “by Splashtop” text' };
  var CHIPS = [['', 'All'], ['flagged', 'Flagged'], ['suspicious', 'Suspicious'], ['needs_review', 'Needs review'],
               ['normal', 'Normal'], ['held', 'Not reviewed'], ['waiting', 'Waiting'], ['skipped', 'Skipped'], ['error', 'Errors']];

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function formatUsd(n) { if (!n) return '$0.00'; return n < 0.01 ? '<$0.01' : '$' + n.toFixed(n < 1 ? 3 : 2); }
  function whenTxt(ms) {
    if (!ms) return '—';
    var d = new Date(ms);
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  // An imported past request is 'held' too, but reads as what it is.
  function state(r) { return r.verdict || (r.status === 'held' && r.source === 'import' ? 'past' : r.status); }
  function pill(st) { return '<span class="vpill v-' + esc(st) + '">' + esc(LABEL[st] || st) + '</span>'; }
  function api(path, opts) {
    return fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {})).then(function (r) {
      if (r.status === 401) { location.href = '/?next=/scans'; throw new Error('login'); }
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }

  // ---- boot: same session as the Logs page (sign in there) -------------------
  fetch('/api/session', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (s) {
    if (s.required && !s.authed) { location.href = '/?next=/scans'; return; }
    $('signOut').hidden = !s.required;
    $('page').hidden = false;
    setup();
    load();
  });
  $('signOut').addEventListener('click', function () {
    fetch('/logout', { method: 'POST', credentials: 'same-origin' }).then(function () { location.href = '/'; });
  });

  function setup() {
    api('/api/scan-setup').then(function (s) {
      ZD = s.zendesk_url;
      drawSwitch(s.ai_review === 'on');
      var el = $('setup');
      if (s.ai_review !== 'on') s.missing = s.missing.filter(function (m) { return !/^AI_/.test(m); });
      if (!s.missing.length) { el.hidden = true; return; }
      el.hidden = false;
      el.innerHTML = '<b>Not fully set up.</b> Missing: ' + s.missing.map(function (m) { return '<code>' + esc(m) + '</code>'; }).join(', ') + '. ' +
        (s.can_scan ? 'Scanning works; Zendesk&rsquo;s trigger can&rsquo;t be verified until the webhook secret is set.'
                    : 'Requests from Zendesk still appear with their details and images; the AI review waits until these are in place.');
    }).catch(function () {});
  }

  // ---- the AI review switch -------------------------------------------------------
  function drawSwitch(on) {
    $('aiToggle').checked = on;
    $('aiState').textContent = on ? 'On' : 'Off';
    $('aiSwitch').classList.toggle('on', on);
    $('aiSwitch').title = on ? 'New SOS requests are reviewed by Claude as they arrive.'
                             : 'New SOS requests are listed with their details and images, without an AI review.';
  }
  $('aiToggle').addEventListener('change', function () {
    var on = this.checked;
    var ask = on
      ? 'Turn on the AI review?\n\nOnly SOS requests that arrive from now on are reviewed by Claude. Requests already on the list, and past requests, stay as they are.'
      : 'Turn off the AI review?\n\nNew SOS requests will be listed with their details and images only.';
    if (!confirm(ask)) { drawSwitch(!on); return; }
    api('/api/ai-review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on: on }) })
      .then(function (r) { drawSwitch(r.ai_review === 'on'); setup(); })
      .catch(function () { drawSwitch(!on); });
  });

  // ---- import past requests (runs on the server; this only starts and watches it)
  var impPoll = null;
  function drawImport(st) {
    var btn = $('impBtn'), msg = $('impMsg');
    btn.disabled = !!st.running;
    $('impStop').hidden = !st.running;
    $('impStop').disabled = !!st.stop;
    if (st.running) {
      msg.textContent = st.found ? 'Importing… ' + st.done + ' of ' + st.found + ' (' + st.added + ' added)' : 'Searching Zendesk…';
      clearTimeout(impPoll); impPoll = setTimeout(pollImport, 2000);
    } else if (st.error) {
      msg.textContent = 'Stopped: ' + st.error;
    } else if (st.stopped) {
      msg.textContent = 'Stopped \u2014 ' + st.added + ' added so far. Press Import again to carry on from there.';
    } else if (st.finished_ms) {
      msg.textContent = 'Done — ' + st.added + ' added, ' + st.skipped + ' already listed (' + st.found + ' found).';
    } else {
      msg.textContent = '';
    }
  }
  function pollImport() {
    api('/api/import-past').then(function (st) {
      var wasRunning = $('impBtn').disabled;
      drawImport(st);
      if (wasRunning && !st.running) { S.page = 0; load(); }      // show what arrived
    }).catch(function () {});
  }
  $('impBtn').addEventListener('click', function () {
    if (!confirm('Import past SOS requests?\n\nSplashHub Centre searches Zendesk for every past “New SOS package created by…” ticket and lists it here with copies of its images. No AI review. Tickets already listed are skipped.')) return;
    api('/api/import-past', { method: 'POST' }).then(drawImport).catch(function (e) {
      if (e.message !== 'login') $('impMsg').textContent = e.message;
    });
  });
  pollImport();   // pick up an import already running (another tab, a reload)
  $('impStop').addEventListener('click', function () {
    this.disabled = true; $('impMsg').textContent = 'Stopping after the current ticket…';
    api('/api/import-past/stop', { method: 'POST' }).then(function () { setTimeout(pollImport, 800); });
  });

  // ---- fetch missing images (server-side job, same pattern as the import)
  var refPoll = null;
  function drawRefill(st) {
    var btn = $('refBtn'), msg = $('refMsg');
    btn.disabled = !!st.running;
    $('refStop').hidden = !st.running;
    $('refStop').disabled = !!st.stop;
    if (st.running) {
      msg.textContent = st.found ? 'Fetching… ' + st.done + ' of ' + st.found + ' (' + st.fixed + ' complete)' : 'Looking for missing images…';
      clearTimeout(refPoll); refPoll = setTimeout(pollRefill, 2000);
    } else if (st.error) {
      msg.textContent = 'Stopped: ' + st.error;
    } else if (st.stopped) {
      msg.textContent = 'Stopped \u2014 ' + st.fixed + ' completed so far.';
    } else if (st.finished_ms) {
      msg.textContent = st.found ? 'Done \u2014 ' + st.fixed + ' complete, ' + st.still_missing + ' still missing images.' : 'No requests were missing images.';
    } else {
      msg.textContent = '';
    }
  }
  function pollRefill() {
    api('/api/fetch-images').then(function (st) {
      var was = $('refBtn').disabled;
      drawRefill(st);
      if (was && !st.running) { lastSig = ''; load(); }
    }).catch(function () {});
  }
  $('refBtn').addEventListener('click', function () {
    api('/api/fetch-images', { method: 'POST' }).then(drawRefill).catch(function (e) {
      if (e.message !== 'login') $('refMsg').textContent = e.message;
    });
  });
  pollRefill();
  $('refStop').addEventListener('click', function () {
    this.disabled = true; $('refMsg').textContent = 'Stopping after the current request…';
    api('/api/fetch-images/stop', { method: 'POST' }).then(function () { setTimeout(pollRefill, 800); });
  });

  // ---- list ----------------------------------------------------------------------
  // The list updates in place: no dimming, and nothing is redrawn when nothing
  // changed -- an automatic check while a request is processing should be
  // invisible unless it has news.
  var seq = 0, poll = null, lastSig = '';
  function load() {
    var my = ++seq;
    var p = 'page=' + S.page + (S.verdict ? '&verdict=' + encodeURIComponent(S.verdict) : '') + (S.q ? '&q=' + encodeURIComponent(S.q) : '');
    api('/api/scans?' + p).then(function (res) {
      if (my !== seq) return;
      var sig = JSON.stringify([p, res.total, res.counts, res.rows.map(function (r) { return [r.id, r.status, r.verdict, r.subject, r.creator_email, r.cost]; })]);
      if (sig !== lastSig) {
        lastSig = sig;
        drawChips(res.counts);
        drawRows(res);
      }
      var d = new Date();
      $('stamp').textContent = 'Updated ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
      clearTimeout(poll);
      if (res.rows.some(function (r) { return r.status === 'queued' || r.status === 'running'; })) poll = setTimeout(load, 4000);
    }).catch(function (e) { if (e.message !== 'login') $('stamp').textContent = 'Could not load: ' + e.message; });
  }

  function drawChips(counts) {
    var n = function (k) { return counts[k] || 0; };
    var total = Object.keys(counts).reduce(function (a, k) { return a + counts[k]; }, 0);
    var num = { '': total, flagged: n('suspicious') + n('needs_review'), suspicious: n('suspicious'),
                needs_review: n('needs_review'), normal: n('normal'), held: n('held'), waiting: n('waiting'), skipped: n('skipped'), error: n('error') };
    $('verdicts').innerHTML = CHIPS.map(function (c) {
      return '<button type="button" class="chip' + (S.verdict === c[0] ? ' active' : '') + (num[c[0]] ? '' : ' empty') +
        '" data-v="' + c[0] + '">' + esc(c[1]) + ' <span class="chip-n">' + num[c[0]] + '</span></button>';
    }).join('');
  }

  function drawRows(res) {
    $('count').textContent = res.total ? 'newest first · ' + res.total + (res.total === 1 ? ' scan' : ' scans') : '';
    if (!res.rows.length) {
      $('rows').innerHTML = '<tr class="empty-row"><td colspan="7">' +
        (S.verdict || S.q ? 'No scans match.' : 'No scans yet. They appear here when Zendesk sends a Custom SOS package request, or when you scan a ticket above.') +
        '</td></tr>';
    } else {
      $('rows').innerHTML = res.rows.map(function (r) {
        var who = r.creator_email ? esc(r.creator_email) : '<span class="muted">—</span>';
        return '<tr class="sc-row' + (S.open === r.id ? ' open' : '') + '" data-id="' + r.id + '" tabindex="0">' +
          '<td class="when">' + esc(whenTxt(r.requested_ms)) + '</td>' +
          '<td><a href="' + esc(ZD) + '/agent/tickets/' + r.ticket_id + '" target="_blank" rel="noopener" class="tlink">#' + r.ticket_id + '</a></td>' +
          '<td>' + pill(state(r)) + '</td>' +
          '<td class="topic" title="' + esc(r.subject || '') + '">' + esc(r.subject || (r.error && !r.subject ? r.error : '—')) + '</td>' +
          '<td>' + who + '</td>' +
          '<td>' + esc(r.source === 'webhook' ? 'Zendesk trigger' : (r.requested_by || 'Manual')) + '</td>' +
          '<td class="n">' + esc(formatUsd(r.cost)) + '</td></tr>' +
          (S.open === r.id ? '<tr class="sc-detail-row"><td colspan="7"><div class="sc-detail" id="detail">Loading…</div></td></tr>' : '');
      }).join('');
      if (S.open) loadDetail(S.open);
    }
    var pages = Math.ceil(res.total / res.per_page);
    $('pager').hidden = pages <= 1;
    $('prev').disabled = res.page <= 0;
    $('next').disabled = res.page >= pages - 1;
    $('pagerTxt').textContent = res.total ? (res.page * res.per_page + 1) + '–' + (res.page * res.per_page + res.rows.length) + ' of ' + res.total : '';
  }

  // ---- one scan, in full ----------------------------------------------------------
  // Three parts, in reading order: the request as the customer filled it in
  // (organised from the ticket's first message), every image on the ticket,
  // then the AI's review. Text from the ticket is untrusted: everything goes
  // through esc(), and links are only ever the http(s) URLs the server parsed.
  var KNOWN = { 'package name': 1, 'caption': 1, 'type': 1, 'subscription': 1, 'technician count': 1,
                'date of creation': 1, 'creator': 1, 'instruction text': 1, 'disclaimer': 1, 'screenshot': 1 };
  var LINK_NAMES = { 'download package': 'Download package', 'manage': 'Manage in ACP', 'team info': 'Team in ACP' };
  var ICON_OUT = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>';
  var LB = { items: [], i: 0 };     // the lightbox's images

  function fieldMap(req) {
    var m = {};
    ((req && req.fields) || []).forEach(function (f) { m[f.label.toLowerCase()] = f.value; });
    return m;
  }
  function dash(v) { return v ? esc(v) : '<span class="muted">—</span>'; }

  function requestCard(s) {
    var req = s.request || { fields: [], links: [] }, f = fieldMap(req);
    if (!req.fields.length && !req.links.length) return '';
    var h = '<section class="rq">';
    h += '<div class="rq-top"><div class="rq-title">' +
      '<div class="rq-name">' + (f['package name'] ? esc(f['package name']) : '<span class="muted">No package name</span>') + '</div>' +
      (f['caption'] ? '<div class="rq-cap">' + esc(f['caption']) + '</div>' : '') + '</div>' +
      '<div class="rq-badges">' + (f['type'] ? '<span class="rq-type">' + esc(f['type']) + '</span>' : '') +
      (s.verdict ? pill(s.verdict) : '') + '</div></div>';
    h += '<div class="rq-grid">' +
      '<div><span class="rq-k">Subscription</span><span class="rq-v">' + dash(f['subscription']) + '</span></div>' +
      '<div><span class="rq-k">Technicians</span><span class="rq-v">' + dash(f['technician count']) + '</span></div>' +
      '<div><span class="rq-k">Created</span><span class="rq-v">' + dash(f['date of creation']) + '</span></div>' +
      '<div><span class="rq-k">Creator</span><span class="rq-v">' + dash(f['creator'] || s.creator_email) +
        (s.creator_domain ? '<span class="rq-sub">' + esc(s.creator_domain) + '</span>' : '') + '</span></div>' +
      '</div>';
    h += '<div class="rq-sec"><div class="rq-h">What end users see</div><dl class="rq-dl">' +
      '<dt>Caption</dt><dd>' + dash(f['caption']) + '</dd>' +
      '<dt>Instruction text</dt><dd>' + dash(f['instruction text']) + '</dd>' +
      '<dt>Disclaimer</dt><dd>' + dash(f['disclaimer']) + '</dd>' +
      (f['screenshot'] ? '<dt>Screenshot</dt><dd>' + esc(f['screenshot']) + '</dd>' : '') +
      '</dl></div>';
    var other = req.fields.filter(function (x) { return !KNOWN[x.label.toLowerCase()]; });
    if (other.length) {
      h += '<div class="rq-sec"><div class="rq-h">Other details</div><dl class="rq-dl">' + other.map(function (x) {
        return '<dt>' + esc(x.label) + '</dt><dd>' + dash(x.value) + '</dd>';
      }).join('') + '</dl></div>';
    }
    h += '<div class="rq-links">' + req.links.map(function (l) {
      if (!/^https?:\/\//i.test(l.url)) return '';
      return '<a class="btn btn-sm" href="' + esc(l.url) + '" target="_blank" rel="noopener noreferrer" title="' + esc(l.url) + '">' +
        esc(LINK_NAMES[l.label.toLowerCase()] || l.label) + ICON_OUT + '</a>';
    }).join('') +
      '<a class="btn btn-sm" href="' + esc(s.zendesk_url) + '/agent/tickets/' + s.ticket_id + '" target="_blank" rel="noopener">Ticket #' + s.ticket_id + ' in Zendesk' + ICON_OUT + '</a>' +
      '</div>';
    if (s.description) {
      h += '<button type="button" class="link-btn rq-raw-btn" data-raw="1" aria-expanded="false">Show original text</button>' +
        '<pre class="rq-raw" hidden>' + esc(s.description) + '</pre>';
    }
    return h + '</section>';
  }

  // Every image on the ticket: the stored copy when there is one (always
  // loads), else Zendesk's own link -- what the trigger sent before the full
  // scan, which loads for anyone signed in to Zendesk in this browser.
  function galleryItems(s) {
    if (s.gallery && s.gallery.length) {
      return s.gallery.map(function (g) {
        var link = /^https:\/\/[^\/]+\.(zendesk\.com|zdusercontent\.com)\//i.test(g.url || '') ? g.url : '';
        return { src: g.key ? '/api/scans/' + s.id + '/image/' + g.id : link, name: g.filename, error: g.error,
                 bytes: g.bytes, reviewed: g.reviewed_index, linked: !g.key && !!link };
      });
    }
    return (s.images || []).map(function (im, i) { return { src: im.content_url, name: im.filename, reviewed: i }; });
  }
  function kb(n) { return n ? (n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB') : ''; }

  function gallery(s, items) {
    if (!items.length) return '';
    var res = s.result || {};
    var linked = items.some(function (it) { return it.linked; });
    return '<section class="gal"><div class="sec-h">Images <span class="count">' + items.length + '</span>' +
      '<span class="gal-note">' + (linked ? 'Shown from Zendesk &mdash; sign in to Zendesk in this browser if they don&rsquo;t load. Copies are kept once the full scan runs.'
                                         : 'Outlined images are the ones the AI reviewed.') + '</span></div><div class="gal-grid">' +
      items.map(function (it, i) {
        var f = it.reviewed != null ? (res.findings || []).filter(function (x) { return x.image_index === it.reviewed; })[0] : null;
        return '<figure class="gal-item' + (it.reviewed != null ? ' reviewed' : '') + '">' +
          (it.src
            ? '<button type="button" class="gal-img" data-lb="' + i + '" title="Open ' + esc(it.name) + '">' +
                '<img src="' + esc(it.src) + '" alt="' + esc(it.name) + '" loading="lazy" referrerpolicy="no-referrer"></button>'
            : '<div class="gal-img gal-missing">' + esc(it.error || 'No copy kept') + '</div>') +
          '<figcaption><span class="gal-name" title="' + esc(it.name) + '">' + esc(it.name) + '</span>' +
            '<span class="gal-meta">' + (f ? pill(f.verdict) : (it.reviewed != null ? '<span class="muted">reviewed</span>' : '')) +
            (it.bytes ? ' <span class="muted">' + kb(it.bytes) + '</span>' : '') + '</span></figcaption></figure>';
      }).join('') + '</div></section>';
  }

  function aiReview(s, items) {
    var res = s.result;
    if (!res) return '';
    var h = '<section class="air"><div class="sec-h">AI review</div>' +
      '<p class="sc-sum"><b>' + esc(LABEL[s.verdict] || s.verdict) + '.</b> ' + esc(res.overall_summary || '') + '</p>';
    (res.findings || []).forEach(function (f) {
      var it = items.filter(function (x) { return x.reviewed === f.image_index; })[0] || {};
      h += '<div class="air-row">' +
        (it.src ? '<img class="air-thumb" src="' + esc(it.src) + '" alt="" loading="lazy" referrerpolicy="no-referrer">' : '<div class="air-thumb"></div>') +
        '<div class="air-body"><div class="air-head">' + pill(f.verdict) + ' <span class="sc-file">' + esc(it.name || ('Image ' + (f.image_index + 1))) + '</span>' +
          (f.confidence != null ? ' <span class="sc-conf">' + Math.round(f.confidence * 100) + '% sure</span>' : '') + '</div>' +
          (f.summary ? '<div>' + esc(f.summary) + '</div>' : '') +
          '<div class="sc-meta">' + esc(REF[f.splashtop_reference] || f.splashtop_reference || '') +
            ((f.detected_brand_references || []).length ? ' · Brands: ' + esc(f.detected_brand_references.join(', ')) : '') + '</div>' +
          ((f.flagged_elements || []).length ? '<ul class="sc-flags">' + f.flagged_elements.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '') +
        '</div></div>';
    });
    var tr = res.ticket_review || {};
    h += '<div class="air-row air-pkg"><div class="air-body"><div class="air-head">' + pill(tr.verdict || 'not_applicable') +
      ' <span class="sc-file">Package details</span></div>' + (tr.summary ? '<div>' + esc(tr.summary) + '</div>' : '') +
      ((tr.flagged_fields || []).length ? '<ul class="sc-flags">' + tr.flagged_fields.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '') +
      '</div></div>';
    return h + '</section>';
  }

  function loadDetail(id) {
    api('/api/scans/' + id).then(function (s) {
      var box = $('detail'); if (!box) return;
      var items = galleryItems(s);
      LB.items = items.filter(function (it) { return it.src; });
      var h = '';
      if (s.error) h += '<div class="' + (s.status === 'waiting' || s.status === 'skipped' ? 'sc-info' : 'sc-err') + '">' + esc(s.error) + '</div>';
      h += requestCard(s) + gallery(s, items) + aiReview(s, items);
      h += '<div class="sc-meta sc-foot">' +
        (s.creator_source ? 'Creator from ' + esc(s.creator_source) : '') +
        (s.organization ? ' · Organization: ' + esc(s.organization) : '') +
        (s.model ? ' · ' + esc(s.model) + ' · ' + (s.input_tokens || 0).toLocaleString() + ' in / ' + (s.output_tokens || 0).toLocaleString() + ' out · ' + formatUsd(s.cost) : '') +
        '</div>';
      box.innerHTML = h;
    }).catch(function () { var box = $('detail'); if (box) box.textContent = 'Could not load this scan.'; });
  }

  // Detail interactions: original text, and the lightbox.
  $('rows').addEventListener('click', function (ev) {
    var raw = ev.target.closest('[data-raw]');
    if (raw) {
      var pre = raw.nextElementSibling, open = pre.hidden;
      pre.hidden = !open; raw.setAttribute('aria-expanded', open); raw.textContent = open ? 'Hide original text' : 'Show original text';
      ev.stopPropagation(); return;
    }
    var g = ev.target.closest('[data-lb]');
    if (g) {
      var src = g.querySelector('img').getAttribute('src');
      LB.i = Math.max(0, LB.items.findIndex(function (x) { return x.src === src; }));
      showLb(); ev.stopPropagation();
    }
  }, true);

  var lb = document.createElement('div');
  lb.className = 'lb'; lb.hidden = true; lb.setAttribute('role', 'dialog'); lb.setAttribute('aria-modal', 'true');
  lb.innerHTML = '<button type="button" class="lb-x" aria-label="Close">&times;</button>' +
    '<button type="button" class="lb-nav lb-prev" aria-label="Previous image">&#8249;</button>' +
    '<figure class="lb-fig"><img alt=""><figcaption></figcaption></figure>' +
    '<button type="button" class="lb-nav lb-next" aria-label="Next image">&#8250;</button>';
  document.body.appendChild(lb);
  function showLb() {
    var it = LB.items[LB.i]; if (!it) return;
    lb.querySelector('img').src = it.src; lb.querySelector('img').alt = it.name;
    lb.querySelector('figcaption').textContent = it.name + '  ·  ' + (LB.i + 1) + ' of ' + LB.items.length;
    lb.querySelector('.lb-prev').hidden = lb.querySelector('.lb-next').hidden = LB.items.length < 2;
    lb.hidden = false; lb.querySelector('.lb-x').focus();
  }
  function step(d) { LB.i = (LB.i + d + LB.items.length) % LB.items.length; showLb(); }
  lb.addEventListener('click', function (ev) {
    if (ev.target.closest('.lb-prev')) step(-1);
    else if (ev.target.closest('.lb-next')) step(1);
    else if (ev.target === lb || ev.target.closest('.lb-x')) lb.hidden = true;
  });
  document.addEventListener('keydown', function (ev) {
    if (lb.hidden) return;
    if (ev.key === 'Escape') lb.hidden = true;
    else if (ev.key === 'ArrowLeft') step(-1);
    else if (ev.key === 'ArrowRight') step(1);
  });

  $('rows').addEventListener('click', function (ev) {
    if (ev.target.closest('a')) return;
    var tr = ev.target.closest('.sc-row'); if (!tr) return;
    var id = +tr.getAttribute('data-id');
    // Open / close in place -- no trip back to the server for the list.
    var old = $('rows').querySelector('.sc-detail-row');
    if (old) old.remove();
    [].forEach.call($('rows').querySelectorAll('.sc-row.open'), function (r) { r.classList.remove('open'); });
    S.open = S.open === id ? null : id;
    if (S.open) {
      tr.classList.add('open');
      tr.insertAdjacentHTML('afterend', '<tr class="sc-detail-row"><td colspan="7"><div class="sc-detail" id="detail">Loading…</div></td></tr>');
      loadDetail(S.open);
    }
  });
  $('rows').addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' && ev.target.classList.contains('sc-row')) ev.target.click();
  });
  $('verdicts').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-v]'); if (!b) return;
    S.verdict = b.getAttribute('data-v'); S.page = 0; load();
  });
  var typing = null;
  $('q').addEventListener('input', function () {
    var v = this.value.trim(); clearTimeout(typing);
    typing = setTimeout(function () { S.q = v; S.page = 0; load(); }, 250);
  });
  $('refresh').addEventListener('click', function () { setup(); load(); });
  $('prev').addEventListener('click', function () { if (S.page > 0) { S.page--; load(); } });
  $('next').addEventListener('click', function () { S.page++; load(); });

  // ---- scan a ticket now ---------------------------------------------------------
  $('scanForm').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var tid = $('tid').value.trim().replace(/^#/, '');
    if (!/^\d+$/.test(tid)) { $('scanMsg').textContent = 'Enter a ticket number.'; return; }
    $('scanBtn').disabled = true; $('scanMsg').textContent = '';
    api('/api/scans', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ticket_id: tid, force: $('force').checked }) })
      .then(function (r) {
        $('scanMsg').textContent = 'Queued #' + tid + ' — it usually takes under a minute.';
        $('tid').value = ''; S.open = r.id; S.verdict = ''; S.page = 0; load();
      })
      .catch(function (e) { if (e.message !== 'login') $('scanMsg').textContent = e.message; })
      .then(function () { $('scanBtn').disabled = false; });
  });
})();
