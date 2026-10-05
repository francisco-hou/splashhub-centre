/**
 * SplashHub — Pricebook settings.
 *
 * One field: where the Pricebook reads its prices. It exists because that URL
 * carries a version hash that changes whenever splashtop.com rebuilds, and
 * that is the single thing that will break the Pricebook.
 *
 * The Pricebook now re-finds the feed by itself when the hash moves, so this
 * panel is the override rather than the repair: Scan does the same search on
 * demand, the box stays editable for setting it by hand, and the history says
 * what the feed has been and whether a person or the app last changed it.
 *
 * Saved to the shared store, so one person fixing it fixes it for everyone.
 *
 * window.PricebookSettingsPage.boot(client)
 */

window.PricebookSettingsPage = (function () {

var booted = false;

function el(id) { return document.getElementById(id); }

function say(kind, html) {
  var m = el('pbsMsg');
  if (!m) return;
  m.className = 'pbs-msg ' + kind;
  m.innerHTML = html;
  m.style.display = html ? 'block' : 'none';
}

function stampFor(cfg) {
  var s = el('pbsStamp');
  if (!s) return;
  if (!cfg || !cfg.when) { s.textContent = ''; return; }
  var d = new Date(cfg.when);
  s.textContent = 'Saved ' + (d.getMonth() + 1) + '/' + d.getDate() +
    (cfg.by ? ' by ' + cfg.by : '');
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

var HOW_LABEL = { manual: 'By hand', scan: 'Scan', auto: 'Found' };

// What the feed has been, newest first. Short, but it answers the question that
// comes up when a price looks wrong: did the feed change under us, and when?
function histFor(cfg) {
  var box = el('pbsHist');
  if (!box) return;
  var rows = (cfg && cfg.history) || [];
  if (!rows.length) { box.style.display = 'none'; box.innerHTML = ''; return; }
  box.innerHTML = '<div class="pbs-hist-h">Feed history</div>' + rows.map(function (h, i) {
    var d = new Date(h.when || 0);
    var when = (d.getMonth() + 1) + '/' + d.getDate() + ' ' +
      String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    var how = HOW_LABEL[h.how] || HOW_LABEL.manual;
    return '<div class="pbs-hist-row' + (i === 0 ? ' now' : '') + '">' +
      '<span class="pbs-hist-when">' + esc(when) + '</span>' +
      '<span class="pbs-hist-url mono" title="' + esc(h.url || '') + '">' + esc(h.url || '') + '</span>' +
      '<span class="pbs-hist-how ' + esc(h.how || 'manual') + '" title="' +
        (h.by ? esc(h.by) : 'the Pricebook itself') + '">' + esc(how) + '</span>' +
      '</div>';
  }).join('');
  box.style.display = 'block';
}

function fill() {
  if (!window.PricebookPage) return;
  PricebookPage.loadConfig().then(function (cfg) {
    var input = el('pbsUrl');
    if (input) input.value = (cfg && cfg.url) || PricebookPage.defaultUrl();
    stampFor(cfg);
    histFor(cfg);
  });
}

function busy(on) {
  ['pbsSave', 'pbsScan', 'pbsReset'].forEach(function (id) {
    var b = el(id); if (b) b.disabled = !!on;
  });
}

// Go and find the live feed. The URL stays editable throughout — the scan
// fills the box in, it doesn't take it over.
function scan() {
  busy(true);
  say('busy', 'Reading splashtop.com/pricing to find the current feed…');
  var current = String((el('pbsUrl') || {}).value || '').trim();

  PricebookPage.discover(function (done, total) {
    say('busy', 'Checking the pricing page’s data files — ' + done + ' of ' + total + '…');
  }).then(function (url) {
    var input = el('pbsUrl');
    if (input) input.value = url;
    if (url === current) {
      // Nothing to save, but the scan is still the answer to "is this right?".
      say('ok', 'The saved link is the current feed.');
      busy(false);
      return;
    }
    return PricebookPage.saveConfig(url, 'scan')
      .then(function () { return PricebookPage.verify(url); })
      .then(function (n) {
        say('ok', 'Found the current feed and saved it for everyone — ' + n + ' price rows.');
        fill();
        busy(false);
      });
  }).catch(function (err) {
    say('bad', 'Could not find the feed' + ((err && err.why) ? ' — ' + err.why : '') +
      '. The link in the box is unchanged.');
    busy(false);
  });
}

function save(url, how) {
  var problem = PricebookPage.validate(url);
  if (problem) { say('bad', problem); return; }

  busy(true);
  say('', '');

  // Save, then immediately prove the URL actually returns prices — a saved
  // setting that silently doesn't work would be worse than none at all.
  PricebookPage.saveConfig(url, how || 'manual')
    .then(function () { return PricebookPage.verify(url); })
    .then(function () {
      say('ok', 'Saved.');
      fill();
    })
    .catch(function (err) {
      // Saved either way: the admin may be pasting ahead of a site change, and
      // wiping their input on a failed check would just be annoying. The scan
      // is the way out, so point at it rather than leaving a dead end.
      say('bad', 'Saved, but that URL returned no prices' +
        ((err && err.why) ? ' — ' + err.why : '') +
        '. Try <b>Scan for the current feed</b>.');
      fill();
    })
    .then(function () { busy(false); });
}

function boot(client) {
  // Saving verifies the URL by fetching it, which needs a client — and the
  // Pricebook page itself may never have been opened.
  if (window.PricebookPage && PricebookPage.attach) PricebookPage.attach(client);
  if (booted) { fill(); return; }
  booted = true;

  var saveBtn = el('pbsSave');
  if (saveBtn) saveBtn.addEventListener('click', function () {
    save(String((el('pbsUrl') || {}).value || '').trim());
  });

  var scanBtn = el('pbsScan');
  if (scanBtn) scanBtn.addEventListener('click', scan);

  var resetBtn = el('pbsReset');
  if (resetBtn) resetBtn.addEventListener('click', function () {
    var input = el('pbsUrl');
    if (input) input.value = PricebookPage.defaultUrl();
    save(PricebookPage.defaultUrl());
  });

  // Enter saves, since the form is a single field.
  var input = el('pbsUrl');
  if (input) input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); save(String(input.value || '').trim()); }
  });

  fill();
}

return { boot: boot };

})();
