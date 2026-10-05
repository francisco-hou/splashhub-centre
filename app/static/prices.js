// SplashHub Centre -- the adapter that lets SplashHub's own Pricebook run here.
//
// pricebook.js and pbsettings.js are copied unchanged from SplashHub. Inside
// Zendesk they fetch with ZAF's client.request and save with Zendesk custom
// objects (coListRecords / coUpsert, from SplashHub's dashboard.js). This file
// gives them the same three things, backed by SplashHub Centre's server
// (pricebook.py): a client whose request() fetches splashtop.com page-data
// through /api/pricebook/fetch, and the two store functions. Load it BEFORE
// pricebook.js.
(function () {
  'use strict';

  function api(path, opts) {
    return fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {})).then(function (r) {
      if (r.status === 401) { location.href = '/logs?next=' + encodeURIComponent(location.pathname); throw new Error('login'); }
      return r.json().then(function (j) {
        // ZAF rejects with an object carrying status / responseText; do the same.
        if (!r.ok) throw { status: r.status, statusText: j.error || ('HTTP ' + r.status), responseText: JSON.stringify(j) };
        return j;
      });
    });
  }

  window.CentrePriceClient = {
    request: function (opts) {
      return api('/api/pricebook/fetch?url=' + encodeURIComponent((opts && opts.url) || ''));
    }
  };

  window.coListRecords = function () { return api('/api/pricebook/store'); };
  window.coUpsert = function (externalId, name, type, payload) {
    return api('/api/pricebook/store', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                         body: JSON.stringify({ id: externalId, payload: payload }) });
  };
  window.USER_NAME = 'Centre admin';

  // pricebook.js's "fix the feed link" shortcut looks for SplashHub's Settings
  // nav item (#navLang); here it is the Settings page's Price Book section.
  document.addEventListener('DOMContentLoaded', function () {
    if (document.getElementById('navLang')) return;
    var a = document.createElement('a');
    a.id = 'navLang'; a.href = '/settings#pricebook'; a.hidden = true;
    document.body.appendChild(a);
  });
})();
