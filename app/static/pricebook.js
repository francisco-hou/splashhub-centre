/**
 * SplashHub — Pricebook page.
 *
 * Annual list pricing for the five plans support quotes most often, plus AEM,
 * across every market we sell in.
 *
 * Where the numbers come from
 * ---------------------------
 * splashtop.com/pricing prints USD and swaps in the local currency in the
 * BROWSER a moment after load. A Zendesk proxy fetch never runs that
 * JavaScript, so scraping the page — with any ?country= value — only ever
 * returns the USD default. Scraping is a dead end here.
 *
 * The page gets its numbers from a Gatsby static-query JSON that already holds
 * every product in every currency. We read that directly, which means:
 *   - no HTML parsing, no model call, no cost
 *   - real local currency, straight from the same source the website uses
 *   - one small fetch
 *
 * The catch: the feed URL contains a content hash that changes whenever the
 * marketing site rebuilds its pricing data. So the URL is editable from the
 * Pricebook → Settings page (pbsettings.js) and saved to the shared store —
 * when it moves, whoever notices pastes the new one and it is fixed for
 * everyone. DEFAULT_URL below is only the fallback until someone does. Until
 * then the page says the feed has moved rather than presenting stale numbers
 * as current.
 *
 * Same shape as the other dashboard pages: window.PricebookPage.boot(client).
 */

window.PricebookPage = (function () {

var client = null;
var booted = false;

// Gatsby static-query payload behind splashtop.com/pricing. The digits are a
// content hash, so this is only the fallback — the live value comes from the
// Settings page. See the header note.
var DEFAULT_URL = 'https://www.splashtop.com/page-data/sq/d/4007116652.json';
var DATA_URL = DEFAULT_URL;
var CFG_ID = 'pricebookcfg';   // kept apart from the cached prices record

// Finding the feed again on its own
// --------------------------------
// The hash moves, but the page that uses it does not: every Gatsby page
// publishes a manifest at /page-data/<path>/page-data.json listing the hashes
// of every static query it loads. So when the saved link dies we read that
// manifest and try each hash until one answers with a price table. Two fixed
// URLs replace one that rots.
var PAGE_DATA_URL = 'https://www.splashtop.com/page-data/pricing/page-data.json';
var SQ_BASE = 'https://www.splashtop.com/page-data/sq/d/';
// How many candidates to fetch at once. The pricing page lists ~44 queries and
// the price one is not near the front, so one at a time would be slow and all
// at once would be rude to the proxy.
var SCAN_BATCH = 6;
// A scan is team-wide work: once one person's browser has done it the answer is
// saved for everyone, so nobody else repeats it within the hour.
var SCAN_COOLDOWN_MS = 60 * 60 * 1000;

// The proxy will only fetch hosts in the manifest's domainWhitelist, so a URL
// pointing anywhere else fails in a way that looks like a dead feed. Checked
// up front so the message names the real problem.
var ALLOWED_HOST = 'https://www.splashtop.com/';

// Markets to quote, mapped to the column holding their price. The source mixes
// zone names, country names and currency codes, so the mapping is explicit
// rather than derived.
// `code` is the country= value on splashtop.com, used for the check-it-yourself
// links at the foot of the page.
var MARKETS = [
  { label: 'USA',          col: 'Zone1',  src: ['USD_GLOBAL'], code: 'us' },
  { label: 'Canada',       col: 'Canada', code: 'ca' },
  { label: 'EU',           col: 'Zone4',  src: ['EUR_ExcludingFrance'], code: 'it' },   // euro column
  { label: 'UK',           col: 'GBP',    code: 'uk' },
  { label: 'Brazil',       col: 'BRL',    code: 'br' },
  { label: 'Mexico',       col: 'MXN',    code: 'mx' },
  { label: 'Japan',        col: 'JPY',    code: 'jp' },
  { label: 'Taiwan',       col: 'TWD',    code: 'tw' },
  { label: 'China',        col: 'Zone5',  src: ['CNY'], code: 'cn' },   // CNY
  { label: 'Switzerland',  col: 'CHF',    code: 'ch' },
  { label: 'Denmark',      col: 'DKK',    code: 'dk' },
  { label: 'Sweden',       col: 'SEK',    code: 'se' },
  { label: 'Norway',       col: 'NOK',    code: 'no' }
];

var PRICING_PAGE = 'https://www.splashtop.com/pricing?country=';
var AEM_PAGE = 'https://www.splashtop.com/autonomous-endpoint-management/pricing?country=';

// AEM is banded by endpoint count and sold on two billing terms. Paying
// monthly costs about 20% more per endpoint; the annual figures are exactly
// twelve times the annual-billing monthly rate, so the two columns are
// genuinely different deals rather than the same number restated.
// `upTo` is the top of each band, which is what decides the rate for a given
// endpoint count.
//
// Verified against the published AEM pricing table (autonomous-endpoint-
// management/pricing): tier1 covers 101-250, and everything up to 100 is the
// flat base fee - which equals exactly 100 x the tier1 rate, so the first
// band here runs to 250 and the 100-endpoint minimum (min: 100 below) makes
// sub-100 quotes come out at the flat fee to the cent. The table also
// publishes a "more than 1,000" tier, so no count needs a sales quote.
var AEM_BANDS = [
  { range: 'Up to 100 endpoints (flat fee)', upTo: 100, flat: true,
                                        monthly: 'aemmonthlybase',  yearly: 'aemannualbase' },
  { range: '101–250 endpoints',        upTo: 250,      monthly: 'aemmonthlytier1', yearly: 'aemannualtier1annual' },
  { range: '251–500 endpoints',        upTo: 500,      monthly: 'aemmonthlytier2', yearly: 'aemannualtier2annual' },
  { range: '501–1,000 endpoints',      upTo: 1000,     monthly: 'aemmonthlytier3', yearly: 'aemannualtier3annual' },
  { range: 'More than 1,000 endpoints', upTo: Infinity, monthly: 'aemmonthlytier4', yearly: 'aemannualtier4annual' }
];

// Splashtop Antivirus (Bitdefender) is monthly-only — there is no annual term
// to discount, so it carries no `yearly` row.
var BD_BANDS = [
  { range: '5–100 endpoints',      upTo: 100,  monthly: 'bitdefenderless100' },
  { range: '101–3,000 endpoints',  upTo: 3000, monthly: 'bitdefendermore101' }
];

function bandTiers(bands, term) {
  return bands.filter(function (b) { return b[term]; })
    .map(function (b) { return { range: b.range, row: b[term] }; });
}

// Column order. `row` names the row in allPricesCsv holding the ANNUAL price.
// Note SOS: the feed still calls the 300-device package "unltd" from when it
// was unlimited. The two resolve to the same pair of figures the pricing page
// prints for SOS.
var SOLO_PROMO_MARKETS = ['Zone4', 'CHF', 'SEK', 'NOK', 'DKK', 'BRL'];
// One table per product line. Splitting them this way means no section is
// wider than four columns, so nothing scrolls sideways — and it matches how
// the products are actually sold.
var SECTIONS = [
  { key: 'access',  label: 'Remote Access',
    sub: 'Annual list price per user.' },
  { key: 'support', label: 'Remote Support',
    sub: 'Annual list price per concurrent user licence.' },
  { key: 'aem',     label: 'Autonomous Endpoint Management',
    sub: 'Tier priced per endpoint; up to 100 endpoints is a flat base fee. ' +
         'Click a row for the full ladder.' },
  { key: 'av',      label: 'Antivirus',
    sub: 'Splashtop Antivirus powered by Bitdefender. Per endpoint per month.' }
];

var PLANS = [
  { key: 'solo',        label: 'Solo',        row: 'sbasoloyearly',  unit: '/year',
                                              section: 'access',
                                              promoRow: 'sbasolopromoyearly',
                                              promoMarkets: SOLO_PROMO_MARKETS,
                                              promoLabel: 'First year' },
  { key: 'pro',         label: 'Pro',         row: 'sbaproyearly',   unit: '/user /year',
                                              section: 'access' },
  { key: 'performance', label: 'Performance', row: 'sbaperfyearly',  unit: '/user /year',
                                              section: 'access' },
  { key: 'sos10',       label: 'SOS+10',      row: 'sos10yearly',    unit: '/concurrent user /year',
                                              section: 'support' },
  { key: 'sos300',      label: 'SOS+300',     row: 'sosunltdyearly', unit: '/concurrent user /year',
                                              section: 'support' },
  { key: 'aemMonthly',  label: 'AEM monthly', row: 'aemmonthlytier1',
                                              unit: '/endpoint /month, billed monthly',
                                              section: 'aem',
                                              tiers: bandTiers(AEM_BANDS, 'monthly') },
  { key: 'aemYearly',   label: 'AEM yearly',  row: 'aemannualtier1annual',
                                              unit: '/endpoint /year, billed annually',
                                              section: 'aem',
                                              tiers: bandTiers(AEM_BANDS, 'yearly') },
  { key: 'bitdefender', label: 'Bitdefender', row: 'bitdefenderless100',
                                              unit: '/endpoint /month',
                                              section: 'av',
                                              tiers: bandTiers(BD_BANDS, 'monthly') }
];

// Products the calculator can price, and the rules that differ between them.
var CALC_PRODUCTS = [
  { key: 'aem', label: 'AEM',        bands: AEM_BANDS, min: 100, hasYearly: true,
    overMsg: '' },   // every count lands in a published tier now
  { key: 'bd',  label: 'Bitdefender', bands: BD_BANDS,  min: 5,   hasYearly: false,
    overMsg: 'Published tiers stop at 3,000 endpoints — above that it is custom pricing ' +
             'from sales.' }
];

var RECORD_ID = 'pricebook';
var MAX_AGE_MS = 24 * 60 * 60 * 1000;

var BOOK = null;         // {prices: {plan: {col: str}}, tiers: {...}, when}
var ERR = '';
var SCANNED = '';        // set when this refresh found the feed again by itself
var isRunning = false;

// A feed that is gone: 404, or a page that answers but holds no prices. Either
// means the hash moved. Anything else (timeout, 5xx, no network) is the site
// being unwell and must not trigger a scan.
function feedGone(err) {
  if (!err) return false;
  if (err.status === 404) return true;
  var m = String(err.message || '');
  return /404|not found|no price rows|expected rows|unreadable/i.test(m);
}

// ---- Helpers ----------------------------------------------------------------

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function stamp(ms) {
  if (!ms) return '';
  var d = new Date(ms);
  var hm = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  var sameDay = d.toDateString() === new Date().toDateString();
  return 'Updated ' + (sameDay ? hm : (d.getMonth() + 1) + '/' + d.getDate() + ' ' + hm);
}

// Pull one row's prices for every market we show. `col` is the market's key
// (and its column in the older feed); `src` lists the column names the
// current feed uses — the first one present wins.
function cellsFor(row) {
  var cells = {};
  MARKETS.forEach(function (m) {
    var names = [m.col].concat(m.src || []), v = '';
    for (var i = 0; i < names.length; i++) {
      if (typeof row[names[i]] === 'string' && row[names[i]].trim()) { v = row[names[i]].trim(); break; }
    }
    cells[m.col] = v;
  });
  return cells;
}

// ---- Shared store -----------------------------------------------------------

// Both the saved feed URL and the cached prices come out of one read, so
// re-checking the URL on every visit costs nothing extra. That matters: an
// admin can change the feed while other agents already have the dashboard
// open, and those tabs must not go on using the old URL until they reload.
function loadStore() {
  if (typeof coListRecords !== 'function') return Promise.resolve({});
  return coListRecords().then(function (res) {
    var out = {};
    ((res && res.custom_object_records) || []).forEach(function (r) {
      var payload = null;
      try { payload = JSON.parse((r.custom_object_fields || {}).payload || 'null'); } catch (e) { return; }
      if (!payload) return;
      if (r.external_id === CFG_ID) out.cfg = payload;
      else if (r.external_id === RECORD_ID && payload.prices) out.book = payload;  // ignore older shapes
    });
    return out;
  }).catch(function () { return {}; });
}

function saveCached(book) {
  if (typeof coUpsert !== 'function') return Promise.resolve();
  return coUpsert(RECORD_ID, 'Pricebook', 'pricebook', book).catch(function () {});
}

// ---- Settings (shared with pbsettings.js) -----------------------------------

function loadConfig() {
  return loadStore().then(function (store) { return store.cfg || null; });
}

// `how`: 'manual' (typed in Settings), 'scan' (the Settings button), 'auto'
// (the Pricebook found it itself after the saved link died). Kept because when
// prices look wrong the first question is always what the feed was doing.
var HISTORY_MAX = 12;

function saveConfig(url, how) {
  if (typeof coUpsert !== 'function') return Promise.reject(new Error('no store'));
  return loadConfig().then(function (old) {
    var hist = (old && old.history) || [];
    var cfg = {
      url: url,
      when: Date.now(),
      by: (typeof USER_NAME === 'string' && USER_NAME) || '',
      how: how || 'manual',
      // A scan that confirms the link already in use is worth recording as a
      // check, not as a change, so the list stays a list of changes.
      lastScan: (how === 'scan' || how === 'auto') ? Date.now() : (old && old.lastScan) || 0,
      history: hist
    };
    if (!old || old.url !== url) {
      cfg.history = [{ url: url, when: cfg.when, by: cfg.by, how: cfg.how }]
        .concat(hist).slice(0, HISTORY_MAX);
    }
    return coUpsert(CFG_ID, 'Pricebook config', 'pricebookcfg', cfg).then(function () {
      DATA_URL = url;
      BOOK = null;         // force the next visit to Prices to re-read
      return cfg;
    });
  });
}

// Remember that a scan happened even when it changed nothing, so a dead feed
// can't have every agent walking the whole list.
function markScanned() {
  if (typeof coUpsert !== 'function') return Promise.resolve();
  return loadConfig().then(function (old) {
    var cfg = old || { url: DATA_URL, when: Date.now(), by: '', how: 'manual', history: [] };
    cfg.lastScan = Date.now();
    return coUpsert(CFG_ID, 'Pricebook config', 'pricebookcfg', cfg);
  }).catch(function () {});
}

// ---- Finding the feed -------------------------------------------------------

function fetchJson(url, timeout) {
  return client.request({
    url: url, type: 'GET', dataType: 'json', timeout: timeout || 15000
  }).then(function (res) {
    if (typeof res === 'string') {
      try { res = JSON.parse(res); } catch (e) { throw new Error('unreadable response'); }
    }
    return res;
  });
}

// A candidate counts as the price feed only if it carries a price table AND
// several of the rows this page actually reads. Requiring more than one row
// means a single renamed row can't disqualify the real feed, and a different
// query that happens to hold a `allPricesCsv` shape can't be mistaken for it.
function looksLikeBook(res) {
  var nodes = res && res.data && res.data.allPricesCsv && res.data.allPricesCsv.nodes;
  if (!nodes || !nodes.length) return false;
  var names = {};
  nodes.forEach(function (n) { if (n && n.name) names[n.name] = 1; });
  var hits = 0;
  PLANS.forEach(function (p) { if (names[p.row]) hits++; });
  return hits >= 3;
}

// Walk the hashes in batches, newest answer wins the lowest index in its batch
// so the result doesn't depend on which request happened to finish first.
function probe(hashes, onProgress) {
  var at = 0, done = 0, total = hashes.length;
  function nextBatch() {
    if (at >= hashes.length) {
      return Promise.reject({ why: 'none of the pricing page’s data files held a price table' });
    }
    var batch = hashes.slice(at, at + SCAN_BATCH);
    at += SCAN_BATCH;
    return Promise.all(batch.map(function (h) {
      var url = SQ_BASE + h + '.json';
      return fetchJson(url).then(function (res) {
        return looksLikeBook(res) ? url : null;
      }, function () { return null; }).then(function (hit) {
        done++;
        if (onProgress) { try { onProgress(done, total); } catch (e) {} }
        return hit;
      });
    })).then(function (found) {
      for (var i = 0; i < found.length; i++) { if (found[i]) return found[i]; }
      return nextBatch();
    });
  }
  return nextBatch();
}

// Resolves with the current feed URL. Rejects with {why} — the same shape
// verify() uses, so callers can print either without caring which failed.
function discover(onProgress) {
  if (!client) return Promise.reject({ why: 'the app is still starting up' });
  return fetchJson(PAGE_DATA_URL, 20000).catch(function (err) {
    throw { why: (err && err.status === 404)
      ? 'splashtop.com/pricing itself returned 404, so that page has moved too'
      : 'the pricing page could not be read' };
  }).then(function (res) {
    // Gatsby lists them at the top of page-data.json (beside `result`, not in it).
    var hashes = (res && (res.staticQueryHashes || (res.result && res.result.staticQueryHashes))) || [];
    if (!hashes.length) throw { why: 'the pricing page did not list any data files' };
    return probe(hashes.map(String), onProgress);
  });
}

// Reject a URL the proxy would refuse, with the reason, before it is saved.
function validate(url) {
  if (!url) return 'Paste the feed URL first.';
  if (url.indexOf(ALLOWED_HOST) !== 0) {
    return 'Must be a <span class="mono">www.splashtop.com</span> address.';
  }
  if (!/\.json(\?|$)/i.test(url)) {
    return 'Must be a <span class="mono">.json</span> address.';
  }
  return '';
}

// Fetch a candidate URL and confirm it really carries prices, so a saved
// setting can't quietly be wrong. Resolves with the row count.
function verify(url) {
  var was = DATA_URL;
  DATA_URL = url;
  return fetchBook()
    .then(function (book) {
      var n = Object.keys(book.prices || {}).length;
      if (!n) { DATA_URL = was; throw { why: 'it had no recognisable price rows' }; }
      // Keep what was just fetched. Without this the Prices page would find
      // the previous feed's copy still inside its 24h cache and show that
      // instead of the feed just pointed at.
      DATA_URL = url;
      BOOK = book;
      return saveCached(book).then(function () { return n; });
    })
    .catch(function (err) {
      DATA_URL = was;
      if (err && err.why) throw err;
      // fetchBook() rejects before returning when the JSON parses but holds
      // nothing we recognise — worth saying so rather than "couldn't read it",
      // since it means the wrong request was copied, not a broken URL.
      var m = String((err && err.message) || '');
      if (/no price rows|expected rows/i.test(m)) {
        throw { why: 'it had no recognisable price rows' };
      }
      throw { why: (err && err.status === 404) ? 'it returned 404' : 'it could not be read' };
    });
}

// ---- Fetch ------------------------------------------------------------------

// The red bar: what went wrong, then what to do about it. "Update the link"
// opens Settings on the Pricebook Feed panel; the second link is the live
// pricing page, for checking a number by hand in the meantime.
function errBar(title, detail) {
  return '<span class="pb-err-ico" aria-hidden="true">&#9888;</span><span>' +
    '<b>' + title + '.</b> ' + detail +
    '<span class="pb-err-act">' +
      '<button type="button" id="pbFixUrl">Update the feed link in Settings</button>' +
      '<span class="sep"> &middot; </span>' +
      '<a href="https://www.splashtop.com/pricing" target="_blank" rel="noopener">Check the pricing page</a>' +
    '</span></span>';
}
// Settings → Pricebook Feed, with the URL box focused.
function openFeedSetting() {
  var nav = document.getElementById('navLang');   // the Settings page (PAGES key "lang")
  if (nav) nav.click(); else window.location.hash = '#lang';
  setTimeout(function () {
    var item = document.querySelector('#setNav [data-sect="pricebook"]');
    if (item) item.click();
    var box = document.querySelector('#setSect-pricebook .pbs-url');
    if (box) { try { box.focus(); box.select(); } catch (e) {} box.scrollIntoView({ block: 'center' }); }
  }, 120);
}

function fetchBook() {
  if (DATA_URL.indexOf(ALLOWED_HOST) !== 0) {
    return Promise.reject({ badHost: true });
  }
  return client.request({
    url: DATA_URL,
    type: 'GET',
    dataType: 'json',
    timeout: 20000
  }).then(function (res) {
    if (typeof res === 'string') {
      try { res = JSON.parse(res); } catch (e) { throw new Error('unreadable response'); }
    }
    var nodes = res && res.data && res.data.allPricesCsv && res.data.allPricesCsv.nodes;
    if (!nodes || !nodes.length) throw new Error('no price rows in the feed');

    var byName = {};
    nodes.forEach(function (n) { if (n && n.name) byName[n.name] = n; });

    // Keep only the rows this page shows: plan -> market column -> price.
    var prices = {};
    var missing = [];
    PLANS.forEach(function (p) {
      var row = byName[p.row];
      if (!row) { missing.push(p.label); return; }
      prices[p.key] = cellsFor(row);
    });
    if (!Object.keys(prices).length) throw new Error('none of the expected rows were present');

    // Every band any column refers to, so a quote can price an endpoint count
    // on either billing term.
    var tiers = {};
    PLANS.forEach(function (p) {
      (p.tiers || []).forEach(function (t) {
        if (byName[t.row]) tiers[t.row] = cellsFor(byName[t.row]);
      });
    });

    // Promotional rows (currently just Solo's first year).
    var promos = {};
    PLANS.forEach(function (p) {
      if (p.promoRow && byName[p.promoRow]) promos[p.key] = cellsFor(byName[p.promoRow]);
    });

    return {
      prices: prices,
      tiers: tiers,
      promos: promos,
      missing: missing,
      when: Date.now(),
      by: (typeof USER_NAME === 'string' && USER_NAME) || ''
    };
  });
}

// ---- Render -----------------------------------------------------------------

function cell(plan, market) {
  var cells = BOOK.prices[plan.key];
  var value = cells && cells[market.col];
  if (!value) return '<span class="pb-none">—</span>';

  // The unit isn't printed — it would repeat down all 13 rows for no gain —
  // but it stays on hover, since "per user" vs "per licence" decides a quote.
  //
  // A first-year price sits on the same line as the price, after a dot, so the
  // discount reads as part of that price rather than a separate fact.
  // The currency lives in the column header, so cells carry digits only. The
  // full figure stays on hover in case anyone copies it out.
  var out = '<span class="pb-line"><span class="pb-price" title="' +
    escapeHtml(value + ' ' + plan.unit) + '">' +
    escapeHtml(bare(value, market.col)) + '</span>';
  if (promoFor(plan, market)) {
    out += '<span class="pb-dot">·</span>' +
      '<button type="button" class="pb-tiers pb-promo" data-plan="' + plan.key +
      '" data-col="' + escapeHtml(market.col) + '">1st year</button>';
  }
  out += '</span>';

  // AEM shows its entry band in the cell; the whole ladder opens in a popover
  // on click, rather than adding four lines to all 13 rows.
  if (plan.tiers && tiersFor(plan, market).length) {
    out += '<button type="button" class="pb-tiers" data-plan="' + plan.key +
      '" data-col="' + escapeHtml(market.col) + '">' +
      tiersFor(plan, market).length + ' tiers</button>';
  }
  return out;
}

// The currency a printed price is in: everything that isn't a digit, separator
// or space. "$72.00" → "$", "MXN 1,100.00" → "MXN", "66.00 €" → "€".
function currencyOf(s) {
  return String(s || '').replace(/[\d.,\s ]/g, '').toUpperCase();
}

// A promo price for this market, but only when it is denominated in the same
// currency as the market's regular price. Where the feed left the promo
// unlocalised the two disagree, and showing it would misquote the customer.
// The currency a market's column is printed in, taken as the one most of its
// prices agree on. It goes in the header once so the cells beneath can drop
// it: thirteen columns each repeating "SEK " is what forces the table wide.
var CURRENCY = {};
function computeCurrencies() {
  CURRENCY = {};
  if (!BOOK) return;
  MARKETS.forEach(function (m) {
    var counts = {}, best = '', top = 0;
    PLANS.forEach(function (p) {
      var v = BOOK.prices[p.key] && BOOK.prices[p.key][m.col];
      var pm = v && parseMoney(v);
      if (!pm) return;
      var affix = (pm.pre + pm.post).trim();
      if (!affix) return;
      counts[affix] = (counts[affix] || 0) + 1;
      if (counts[affix] > top) { top = counts[affix]; best = affix; }
    });
    CURRENCY[m.col] = best;
  });
}

// Strip the currency, leaving the digits exactly as printed ("SEK 1,080.00"
// becomes "1,080.00"). A value that disagrees with its column's currency is
// left whole, so a stray euro figure can never be read as kronor.
function bare(value, col) {
  var pm = parseMoney(value);
  if (!pm) return value;
  var affix = (pm.pre + pm.post).trim();
  if (!CURRENCY[col] || affix !== CURRENCY[col]) return value;
  var digits = String(value).slice(pm.pre.length, String(value).length - pm.post.length);
  // Drop a dead ".00" but never a real fraction — $1.19 and SEK 10.80 keep
  // their cents, $72.00 becomes 72.
  return digits.replace(/\.00$/, '');
}

function promoFor(plan, market) {
  if (!plan.promoRow || !BOOK || !BOOK.promos) return '';
  // Both gates must pass: the market has to run the promotion at all, and the
  // figure has to be in that market's own currency.
  if (plan.promoMarkets && plan.promoMarkets.indexOf(market.col) === -1) return '';
  var promo = BOOK.promos[plan.key] && BOOK.promos[plan.key][market.col];
  var regular = BOOK.prices[plan.key] && BOOK.prices[plan.key][market.col];
  if (!promo || !regular) return '';
  return currencyOf(promo) === currencyOf(regular) ? promo : '';
}

// Bands that actually carry a price in this market.
function tiersFor(plan, market) {
  if (!plan.tiers || !BOOK) return [];
  return plan.tiers.map(function (t) {
    var v = BOOK.tiers[t.row] && BOOK.tiers[t.row][market.col];
    return v ? { range: t.range, price: v } : null;
  }).filter(Boolean);
}

// Per-market links to the pages these prices come from, so any figure here can
// be checked against the source in one click. A slider picks WHICH source page
// the row points at — the standard pricing page or the AEM one — instead of
// stacking two near-identical link rows.
var LNK_KEY = 'splashhub.pblinks.v1';
var LNK_MODE = (function () {
  try { return localStorage.getItem(LNK_KEY) === 'aem' ? 'aem' : 'pricing'; }
  catch (e) { return 'pricing'; }
})();

function marketLinks() {
  var aem = LNK_MODE === 'aem';
  var base = aem ? AEM_PAGE : PRICING_PAGE;
  return '<div class="pb-links">' +
    '<div class="pb-links-row pb-links-onerow">' +
      '<span class="pb-slider" id="pbLnkSlider">' +
        '<span class="pb-slider-thumb" id="pbLnkThumb"></span>' +
        '<button type="button" class="pb-slider-btn' + (aem ? '' : ' active') + '" data-lnk="pricing">' +
          'Access / Remote Support Pricing</button>' +
        '<button type="button" class="pb-slider-btn' + (aem ? ' active' : '') + '" data-lnk="aem">' +
          'AEM Pricing</button>' +
      '</span>' +
      MARKETS.map(function (m) {
        return '<a href="' + base + m.code + '" target="_blank" rel="noopener">' +
          escapeHtml(m.label) + '</a>';
      }).join('') + '</div>' +
    '<div class="pb-links-note">Prices on those pages localise a moment after load.</div>' +
    '</div>';
}

// Slide the white thumb under whichever side is active. Measured, not
// hard-coded, because the two labels are different widths.
function positionLnkThumb() {
  var slider = document.getElementById('pbLnkSlider');
  var thumb = document.getElementById('pbLnkThumb');
  if (!slider || !thumb) return;
  var act = slider.querySelector('.pb-slider-btn.active');
  if (!act) return;
  thumb.style.left = act.offsetLeft + 'px';
  thumb.style.width = act.offsetWidth + 'px';
}

// Flipping the slider updates in place — active states, thumb position, and
// the links' hrefs — with no re-render, so the thumb visibly glides across.
function updateLnkUI() {
  var aem = LNK_MODE === 'aem';
  var base = aem ? AEM_PAGE : PRICING_PAGE;
  var slider = document.getElementById('pbLnkSlider');
  if (slider) {
    slider.querySelectorAll('[data-lnk]').forEach(function (b) {
      b.classList.toggle('active', (b.getAttribute('data-lnk') === 'aem') === aem);
    });
  }
  var row = document.querySelector('#pagePricebook .pb-links-onerow');
  if (row) {
    row.querySelectorAll('a').forEach(function (a, i) {
      if (MARKETS[i]) a.href = base + MARKETS[i].code;
    });
  }
  positionLnkThumb();
}

function render() {
  var box = document.getElementById('pbBody');
  if (!box) return;

  var errEl = document.getElementById('pbError');
  if (errEl) {
    errEl.innerHTML = ERR;
    errEl.style.display = ERR ? 'flex' : 'none';
    var fix = errEl.querySelector('#pbFixUrl');
    if (fix) fix.onclick = openFeedSetting;
  }
  var noteEl = document.getElementById('pbNote');
  if (noteEl) {
    var bits = [];
    // The feed moved and the page found it again on its own. Worth saying once
    // — silence would leave the team thinking the link still needs fixing.
    if (SCANNED) bits.push('The feed had moved; the current one was found and saved for everyone.');
    if (BOOK && BOOK.missing && BOOK.missing.length) {
      bits.push('No price found for: ' + BOOK.missing.join(', ') + '.');
    }
    noteEl.textContent = bits.join(' ');
    noteEl.style.display = bits.length ? 'block' : 'none';
  }

  var st = document.getElementById('pbUpdated');
  if (st) st.textContent = BOOK ? stamp(BOOK.when) : '';

  if (!BOOK) {
    box.innerHTML = ERR ? '' : (window.SplashSkel
      ? window.SplashSkel.table(2, 3, 6)
      : '<div class="pb-empty empty"><span class="spinner"></span> Loading prices…</div>');
    return;
  }

  // A refresh while the drill-in is open should refresh what it shows.
  if (DETAIL_PLAN) recalcDetail();

  computeCurrencies();

  box.innerHTML = SECTIONS.map(function (sec) {
    var plans = PLANS.filter(function (p) { return p.section === sec.key; });
    if (!plans.length) return '';

    // Markets across the top, products down the side. Each section is only a
    // row or three tall, so the width of thirteen market columns costs far
    // less than it would in one combined table.
    // Narrower again now that cells hold digits only, without dead decimals.
    var cols = 'style="grid-template-columns: 132px repeat(' + MARKETS.length +
      ', minmax(56px, 1fr)); min-width: ' + (132 + MARKETS.length * 56) + 'px"';

    var head = '<div class="pb-row pb-head" ' + cols + '><span>Product</span>' +
      MARKETS.map(function (m) {
        return '<span>' + escapeHtml(m.label) +
          (CURRENCY[m.col] ? '<span class="pb-cur">' + escapeHtml(CURRENCY[m.col]) + '</span>' : '') +
          '</span>';
      }).join('') + '</div>';

    var rows = plans.map(function (p) {
      var open = PLAN_PRODUCT[p.key] ? ' pb-row-open" data-open="' + p.key + '"' : '"';
      return '<div class="pb-row' + open + ' ' + cols + '><span class="pb-country">' +
        escapeHtml(p.label) + '</span>' +
        MARKETS.map(function (m) {
          return '<span class="pb-cell">' + cell(p, m) + '</span>';
        }).join('') + '</div>';
    }).join('');

    return '<div class="pb-sect">' +
      '<div class="pb-sect-head"><span class="pb-sect-name">' + escapeHtml(sec.label) +
      '</span><span class="pb-sect-sub">' + escapeHtml(sec.sub) + '</span></div>' +
      '<div class="card pb-table"><div class="pb-scroll">' + head + rows + '</div></div>' +
      '</div>';
  }).join('') + marketLinks();
  // The thumb is positioned by measurement, so it waits a tick for layout.
  // setTimeout, not requestAnimationFrame: rAF never fires in a hidden tab,
  // which would leave the thumb unplaced until the first click.
  setTimeout(positionLnkThumb, 0);
}

// ---- Tier popover -----------------------------------------------------------
//
// Same behaviour as the last-reply popover on My Pins: click the badge to
// open, click anywhere else (or Escape) to close. Scrolling closes it too,
// except when the scroll is inside the popover itself — otherwise reading a
// long ladder would dismiss it.

var POP = null;

function closePop() {
  if (!POP) return;
  POP.parentNode && POP.parentNode.removeChild(POP);
  POP = null;
  document.removeEventListener('mousedown', onDocDown, true);
  document.removeEventListener('keydown', onKey, true);
  window.removeEventListener('scroll', onScroll, true);
  window.removeEventListener('resize', closePop);
}

function onDocDown(ev) {
  if (POP && !POP.contains(ev.target) && !(ev.target.closest && ev.target.closest('.pb-tiers'))) {
    closePop();
  }
}
function onKey(ev) { if (ev.key === 'Escape') closePop(); }
function onScroll(ev) {
  // Ignore scrolling inside the popover itself. The target of a window-level
  // scroll isn't always an element, so check before handing it to contains().
  var t = ev && ev.target;
  if (POP && t && t.nodeType && POP.contains(t)) return;
  closePop();
}

function openPop(btn) {
  closePop();
  var plan = null;
  PLANS.forEach(function (p) { if (p.key === btn.getAttribute('data-plan')) plan = p; });
  var market = null;
  MARKETS.forEach(function (m) { if (m.col === btn.getAttribute('data-col')) market = m; });
  if (!plan || !market) return;

  // Either the promo (first year vs standard) or the tier ladder.
  var rows;
  if (btn.classList.contains('pb-promo')) {
    var promo = promoFor(plan, market);
    if (!promo) return;
    rows = [
      { range: plan.promoLabel || 'Promotional', price: promo },
      { range: 'Then, per year', price: BOOK.prices[plan.key][market.col] }
    ];
  } else {
    rows = tiersFor(plan, market).map(function (b) {
      return { range: b.range, price: b.price };
    });
  }
  if (!rows.length) return;

  POP = document.createElement('div');
  POP.className = 'pb-pop';
  POP.innerHTML =
    '<div class="pb-pop-head">' + escapeHtml(plan.label) + ' &middot; ' +
      escapeHtml(market.label) + '</div>' +
    rows.map(function (b) {
      return '<div class="pb-pop-row"><span>' + escapeHtml(b.range) + '</span>' +
        '<span class="pb-pop-price">' + escapeHtml(b.price) + '</span></div>';
    }).join('') +
    '<div class="pb-pop-foot">' + escapeHtml(plan.unit) + '</div>';
  document.body.appendChild(POP);

  // Sit under the badge, pulled back inside the viewport when it would spill.
  var r = btn.getBoundingClientRect();
  var w = POP.offsetWidth;
  var left = Math.min(r.left, window.innerWidth - w - 12);
  var top = r.bottom + 6;
  if (top + POP.offsetHeight > window.innerHeight - 8) {
    top = Math.max(8, r.top - POP.offsetHeight - 6);   // flip above
  }
  POP.style.left = Math.max(8, left) + 'px';
  POP.style.top = top + 'px';

  document.addEventListener('mousedown', onDocDown, true);
  document.addEventListener('keydown', onKey, true);
  window.addEventListener('scroll', onScroll, true);
  window.addEventListener('resize', closePop);
}

// ---- Calculator -------------------------------------------------------------
//
// Prices arrive as formatted strings ("SEK 10.80", "1.19 €", "JPY 180"), so
// arithmetic means pulling the number out and putting the currency back
// afterwards — never converting between currencies, only multiplying within
// one. Pricing is flat volume tiers: the band the TOTAL count lands in sets
// the per-endpoint rate for EVERY endpoint (per the published AEM pricing
// page, 300 endpoints are all billed at the 251–500 rate) — see slice().

function parseMoney(s) {
  var m = String(s || '').match(/[\d][\d.,]*/);
  if (!m) return null;
  var n = parseFloat(m[0].replace(/,/g, ''));
  if (!isFinite(n)) return null;
  var at = String(s).indexOf(m[0]);
  return { n: n, pre: String(s).slice(0, at), post: String(s).slice(at + m[0].length) };
}

// Re-print a number in the same currency and precision as `sample`. Yen and
// the like print without decimals, so the sample decides.
function money(sample, n) {
  var p = parseMoney(sample);
  if (!p) return '—';
  var dec = /[.,]\d\d(?!\d)/.test(String(sample)) ? 2 : 0;
  return p.pre + n.toLocaleString('en-US', {
    minimumFractionDigits: dec, maximumFractionDigits: dec
  }) + p.post;
}

function bandFor(product, count) {
  for (var i = 0; i < product.bands.length; i++) {
    if (count <= product.bands[i].upTo) return product.bands[i];
  }
  return null;                    // beyond the published bands
}

function runCalc(ids, product, market) {
  var out = document.getElementById(ids.out);
  var bandEl = document.getElementById(ids.band);
  var noteEl = document.getElementById(ids.note);
  if (!out || !BOOK) return;

  var raw = parseInt((document.getElementById(ids.count) || {}).value, 10);
  var note = '';

  // Cleared up front so the early returns below can't leave a stale ladder.
  var bandsBox = ids.bands && document.getElementById(ids.bands);
  if (bandsBox) bandsBox.innerHTML = '';

  if (!isFinite(raw) || raw < 1) {
    bandEl.style.display = '';
    bandEl.textContent = 'Enter how many endpoints.';
    out.innerHTML = '';
    noteEl.style.display = 'none';
    return;
  }

  // Below the minimum you still pay for the minimum, so quote that.
  var billed = Math.max(raw, product.min);
  if (raw < product.min) {
    note = product.label + ' starts at ' + product.min + ' endpoints, so ' + raw +
      ' is quoted as ' + product.min + '.';
  }

  var band = bandFor(product, billed);
  if (!band) {
    bandEl.style.display = '';
    bandEl.innerHTML = '<strong>Over ' +
      product.bands[product.bands.length - 1].upTo.toLocaleString('en-US') +
      ' endpoints</strong>';
    out.innerHTML = '';
    noteEl.innerHTML = escapeHtml(product.overMsg);
    noteEl.style.display = 'block';
    return;
  }

  bandEl.style.display = 'none';

  var mo = slice(product, market, billed, 'monthly');
  var yr = product.hasYearly ? slice(product, market, billed, 'yearly') : null;

  if (!mo.rows.length) {
    bandEl.style.display = '';
    bandEl.textContent = '';
    out.innerHTML = '';
    noteEl.innerHTML = 'No ' + escapeHtml(product.label) + ' price for ' +
      escapeHtml(market.label) + '.';
    noteEl.style.display = 'block';
    return;
  }

  var sample = mo.rows[0].rate;
  var moPerMonth = mo.total;
  var moPerYear = moPerMonth * 12;
  var yrPerYear = yr && yr.rows.length ? yr.total : 0;
  var saving = yrPerYear ? moPerYear - yrPerYear : 0;

  // The totals live here; the per-band working is the table underneath, so the
  // same sum isn't printed twice.
  // Without an annual term there is nothing to toggle — monthly stays chosen.
  if (!yrPerYear) CALC_TERM = 'monthly';
  out.innerHTML =
    '<button type="button" class="calc-card' + (CALC_TERM === 'monthly' ? ' sel' : '') +
      '" data-term="monthly">' +
      '<div class="calc-card-top"><span class="calc-term">Billed monthly</span>' +
      '<span class="calc-total">' + escapeHtml(money(sample, moPerMonth)) + ' /mo</span></div>' +
      '<div class="calc-math">' + escapeHtml(money(sample, moPerMonth)) +
        ' &times; 12 = <strong>' + escapeHtml(money(sample, moPerYear)) +
        '</strong> /yr</div>' +
    '</button>' +
    // Only where the product actually offers an annual term.
    (yrPerYear
      ? '<button type="button" class="calc-card best' + (CALC_TERM === 'yearly' ? ' sel' : '') +
          '" data-term="yearly">' +
          '<div class="calc-card-top"><span class="calc-term">Billed annually</span>' +
          '<span class="calc-total">' + escapeHtml(money(sample, yrPerYear)) + ' /yr</span></div>' +
          (saving > 0
            ? '<div class="calc-math calc-save">' + escapeHtml(money(sample, moPerYear)) +
              ' &minus; ' + escapeHtml(money(sample, yrPerYear)) + ' = <strong>' +
              escapeHtml(money(sample, saving)) + '</strong> saved a year</div>'
            : '') +
        '</button>'
      : '');

  noteEl.innerHTML = note ? escapeHtml(note) : '';
  noteEl.style.display = note ? 'block' : 'none';

  renderBands(ids, product, market, billed, mo, yr);
}

// Splashtop prices these as FLAT volume tiers: whichever band the total count
// lands in sets the per-endpoint rate for every endpoint — 300 endpoints are
// all billed at the 251–500 rate, not 100 at tier 1 plus 150 at tier 2 and so
// on (confirmed against the published AEM pricing page; the earlier graduated
// math here over-quoted every count above the first band). Returns the full
// ladder so the dialog can show the other tiers, with the applicable band
// carrying the whole count. rows is deliberately empty when the applicable
// band has no price for this market, so the caller shows its "no price"
// message instead of a silently wrong total.
function slice(product, market, count, term) {
  var applicable = bandFor(product, count);
  var rows = [];
  var total = 0;

  for (var i = 0; i < product.bands.length; i++) {
    var b = product.bands[i];
    var rate = b[term] ? (BOOK.tiers[b[term]] || {})[market.col] : '';
    var pm = parseMoney(rate);
    if (!pm) {
      if (b === applicable) return { rows: [], total: 0 };
      continue;   // unpriced non-applicable tier — leave it off the ladder
    }
    if (b === applicable) {
      var sub = b.flat ? pm.n : pm.n * count;
      rows.push({ range: b.range, units: count, rate: rate, subtotal: sub, flat: !!b.flat });
      total = sub;
    } else {
      rows.push({ range: b.range, units: 0, rate: rate, subtotal: 0, flat: !!b.flat });
    }
  }
  return { rows: rows, total: total };
}

// The tier ladder: every published tier's rate, with the one the count lands
// in showing the whole-count math — the working behind the total above.
function renderBands(ids, product, market, billed, mo, yr) {
  var box = ids.bands && document.getElementById(ids.bands);
  if (!box) return;
  if (!product || !market || !mo) { box.innerHTML = ''; return; }

  function table(title, s, suffix) {
    if (!s || !s.rows.length) return '';
    var lines = s.rows.map(function (r) {
      var used = r.units > 0;
      return '<div class="calc-band-row' + (used ? ' is-current' : '') + '">' +
        '<span class="calc-band-name">' + escapeHtml(r.range) + '</span>' +
        '<span class="calc-band-math">' +
          (used
            ? (r.flat
                ? 'flat fee = <strong>' + escapeHtml(money(r.rate, r.subtotal)) + '</strong>'
                : r.units.toLocaleString('en-US') + ' &times; ' + escapeHtml(r.rate) +
                  ' = <strong>' + escapeHtml(money(r.rate, r.subtotal)) + '</strong>')
            : '<span class="calc-band-idle">' + escapeHtml(r.rate) +
              (r.flat ? ' flat' : '') + ' &middot; other tier</span>') +
        '</span></div>';
    }).join('');
    return '<div class="calc-bands-title">' + title + '</div>' + lines +
      '<div class="calc-band-row calc-band-total"><span class="calc-band-name">' +
      billed.toLocaleString('en-US') + ' endpoints</span>' +
      '<span class="calc-band-math"><strong>' +
      escapeHtml(money(s.rows[0].rate, s.total)) + '</strong> ' + suffix + '</span></div>';
  }

  // One ladder at a time — whichever billing card is selected.
  if (CALC_TERM === 'yearly' && yr && yr.rows.length) {
    box.innerHTML = table('Tier pricing &mdash; billed annually', yr, '/yr');
  } else {
    box.innerHTML = table('Tier pricing &mdash; billed monthly', mo, '/mo');
  }
  // Restart the rise-in so every update is visibly an update.
  box.classList.remove('pb-anim');
  void box.offsetWidth;
  box.classList.add('pb-anim');
}

var DETAIL_IDS = { count: 'pdCount', band: 'pdBand', out: 'pdOut', note: 'pdNote',
                   bands: 'pdBands' };

// ---- Product drill-in -------------------------------------------------------

// Which calculator product a table row belongs to. Only the endpoint-priced
// rows open a drill-in; the per-user plans have no bands to explore.
var PLAN_PRODUCT = { aemMonthly: 'aem', aemYearly: 'aem', bitdefender: 'bd' };

var DETAIL_PLAN = null;
var CALC_TERM = 'monthly';   // 'monthly' | 'yearly' — which ladder shows

function planByKey(key) {
  var found = null;
  PLANS.forEach(function (p) { if (p.key === key) found = p; });
  return found;
}

function detailProduct() {
  var p = DETAIL_PLAN && PLAN_PRODUCT[DETAIL_PLAN.key];
  var found = null;
  CALC_PRODUCTS.forEach(function (x) { if (x.key === p) found = x; });
  return found;
}

function detailMarket() {
  var sel = document.getElementById('pdMarket');
  var found = null;
  MARKETS.forEach(function (m) { if (m.col === (sel && sel.value)) found = m; });
  return found || MARKETS[0];
}

function recalcDetail() {
  var product = detailProduct();
  if (product) runCalc(DETAIL_IDS, product, detailMarket());
}

function openDetail(planKey) {
  var plan = planByKey(planKey);
  if (!plan || !PLAN_PRODUCT[planKey] || !BOOK) return;
  DETAIL_PLAN = plan;
  // The row clicked decides the preselected term: the "AEM yearly" row opens
  // on annual billing, everything else starts on monthly. The card order
  // stays monthly-first either way.
  CALC_TERM = (planKey === 'aemYearly') ? 'yearly' : 'monthly';

  // The dialog covers BOTH billing terms via its toggle, so it carries the
  // product name alone — "AEM yearly" up top would contradict the monthly
  // card being selected. The clicked row only decides the preselected term.
  var isAem = PLAN_PRODUCT[planKey] === 'aem';
  document.getElementById('pdName').textContent = isAem ? 'AEM' : 'Bitdefender';
  document.getElementById('pdUnit').textContent = isAem
    ? 'per endpoint · tier priced'
    : 'per endpoint per month · tier priced';

  var sel = document.getElementById('pdMarket');
  if (sel && !sel.options.length) {
    // Alphabetical HERE only — the main table keeps its sales-order columns.
    // The default stays USA (MARKETS[0]) regardless of where it sorts to.
    sel.innerHTML = MARKETS.slice()
      .sort(function (a, b) { return a.label.localeCompare(b.label); })
      .map(function (m) {
        return '<option value="' + escapeHtml(m.col) + '">' + escapeHtml(m.label) + '</option>';
      }).join('');
    sel.value = MARKETS[0].col;
  }
  var count = document.getElementById('pdCount');
  if (count) count.value = String(detailProduct().min);

  recalcDetail();

  var ov = document.getElementById('pbCalcOverlay');
  if (ov) ov.style.display = '';
  if (count) { count.focus(); count.select(); }
}

function closeDetail() {
  DETAIL_PLAN = null;
  var ov = document.getElementById('pbCalcOverlay');
  if (ov) ov.style.display = 'none';
}


// ---- Run --------------------------------------------------------------------

function run(force) {
  if (isRunning) return;
  isRunning = true;
  ERR = '';
  SCANNED = '';   // the "found it again" note belongs to one refresh only
  var btn = document.getElementById('pbRefresh');
  if (btn) btn.disabled = true;
  render();

  loadStore()
    .then(function (store) {
      // Pick up a feed URL changed by someone else since this tab loaded.
      if (store.cfg && store.cfg.url) DATA_URL = store.cfg.url;
      var cached = store.book;
      if (cached && !force && Date.now() - (cached.when || 0) < MAX_AGE_MS) {
        BOOK = cached;
        return null;
      }
      if (cached) BOOK = cached;      // show yesterday's while today's loads
      return fetchBook().catch(function (err) {
        // The saved link died — a site rebuild moved the hash. Try the
        // built-in one, then go and find the current one. Only a missing feed
        // is worth all that: a timeout or a 5xx means the site is having a
        // moment, and walking 44 URLs would make it worse.
        if (!feedGone(err)) throw err;
        var tryDefault = (DATA_URL !== DEFAULT_URL)
          ? (function () { DATA_URL = DEFAULT_URL; return fetchBook().then(function (book) {
              return saveConfig(DEFAULT_URL, 'auto').catch(function () {}).then(function () { return book; });
            }); })()
          : Promise.reject(err);
        return tryDefault.catch(function (err2) {
          if (!feedGone(err2)) throw err2;
          var last = (store.cfg && store.cfg.lastScan) || 0;
          if (Date.now() - last < SCAN_COOLDOWN_MS) throw err2;
          return discover().then(function (url) {
            DATA_URL = url;
            return fetchBook().then(function (book) {
              return saveConfig(url, 'auto').catch(function () {}).then(function () {
                SCANNED = url;
                return book;
              });
            });
          }, function (why) {
            return markScanned().then(function () { throw why && why.why ? why : err2; });
          });
        });
      }).then(function (book) { BOOK = book; return saveCached(book); });
    })
    .catch(function (err) {
      if (err && err.badHost) {
        ERR = errBar('Pricing could not be updated from the website',
          'The feed URL points outside <span class="mono">www.splashtop.com</span>, which the app is not allowed to fetch.');
        render();
        return;
      }
      // The likeliest failure by far is the hash in the URL having moved after
      // a marketing-site rebuild, so name that rather than show a bare error.
      // By the time we get here the scan has already tried and failed, so say
      // what it found rather than repeating "the link moved".
      var moved = (err && err.status === 404) ||
        /404|not found/i.test(String((err && err.message) || ''));
      var why = (err && err.why)
        ? 'The feed moved and the current one could not be found — ' + err.why + '.'
        : moved
        ? 'The feed URL returns page not found: the marketing site rebuilt and moved it.'
        : 'The feed could not be read' + (err && err.status ? ' (HTTP ' + err.status + ')' : '') + '.';
      var shown = BOOK ? ' Showing the prices loaded ' + stamp(BOOK.when).replace(/^Updated\s*/i, '') + '.' : '';
      ERR = errBar('Pricing could not be updated from the website', why + shown);
    })
    .then(function () {
      render();
      if (btn) btn.disabled = false;
      isRunning = false;
    });
}

// ---- Boot -------------------------------------------------------------------

function boot(zafClient) {
  if (booted) { run(false); return; }
  booted = true;
  client = zafClient;

  var refresh = document.getElementById('pbRefresh');
  if (refresh) refresh.addEventListener('click', function () { run(true); });

  // The thumb's position is measured, so window resizes (label wrap) move it.
  window.addEventListener('resize', positionLnkThumb);

  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape') return;
    var d = document.getElementById('pbCalcOverlay');
    if (d && d.style.display !== 'none') closeDetail();
  });

  // Delegated, so it survives every re-render of the table.
  var body = document.getElementById('pbBody');
  if (body) body.addEventListener('click', function (ev) {
    var t = ev.target;
    if (!t || !t.closest) return;
    // Footer slider: which splashtop.com page the market links point at.
    // Updates in place (not a re-render) so the thumb animates across.
    var lnk = t.closest('[data-lnk]');
    if (lnk) {
      LNK_MODE = lnk.getAttribute('data-lnk') === 'aem' ? 'aem' : 'pricing';
      try { localStorage.setItem(LNK_KEY, LNK_MODE); } catch (e) {}
      updateLnkUI();
      return;
    }
    if (t.closest('a')) return;                       // the market links at the foot

    // Solo's first-year badge keeps its small popover; the banded products
    // now open the drill-in instead, from anywhere on the row.
    var promo = t.closest('.pb-promo');
    if (promo) {
      ev.preventDefault();
      var id = promo.getAttribute('data-col') + promo.getAttribute('data-plan');
      if (POP && POP.dataset.for === id) { closePop(); return; }
      openPop(promo);
      if (POP) POP.dataset.for = id;
      return;
    }
    var row = t.closest('[data-open]');
    if (row) { ev.preventDefault(); closePop(); openDetail(row.getAttribute('data-open')); }
  });

  var close = document.getElementById('pdClose');
  if (close) close.addEventListener('click', closeDetail);
  var pdOut = document.getElementById('pdOut');
  if (pdOut) pdOut.addEventListener('click', function (ev) {
    var card = ev.target && ev.target.closest ? ev.target.closest('[data-term]') : null;
    if (!card) return;
    CALC_TERM = card.getAttribute('data-term');
    recalcDetail();
  });
  ['pdCount', 'pdMarket'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) { el.addEventListener('input', recalcDetail); el.addEventListener('change', recalcDetail); }
  });
  // Dismiss on the dimmed backdrop, same as the dashboard's other modals.
  var ov = document.getElementById('pbCalcOverlay');
  if (ov) ov.addEventListener('mousedown', function (ev) {
    if (ev.target === ov) closeDetail();
  });

  run(false);   // run() reads the saved URL along with the cached prices
}

return {
  boot: boot,
  // Used by the Settings page.
  // Settings can save and verify a URL before anyone has opened the Pricebook,
  // in which case boot() has never run and there is no client to fetch with.
  attach: function (zafClient) { if (!client) client = zafClient; },
  loadConfig: loadConfig,
  saveConfig: saveConfig,
  validate: validate,
  verify: verify,
  // Settings' "Scan for it" button. onProgress(done, total) drives its counter.
  discover: discover,
  defaultUrl: function () { return DEFAULT_URL; }
};

})();
