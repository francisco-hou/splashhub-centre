"""The Price Book page's server side.

The page itself is SplashHub's own Pricebook (static/pricebook.js and
static/pbsettings.js, copied unchanged from SplashHub so the two never
drift). Inside Zendesk those files fetch through ZAF's client.request and
save through Zendesk custom objects; here a small adapter (static/prices.js)
gives them the same two things:

  fetch(url)  -> GET /api/pricebook/fetch?url=...  (only splashtop.com's
                 /page-data/ JSON -- the price feed and its page manifest)
  store       -> GET/POST /api/pricebook/store     (the saved feed link, its
                 history, and the cached prices; the settings table)

Outbound goes through the egress proxy, so www.splashtop.com must be in the
OUTBOUND_HTTP grant. Errors are worded here, never str(e) (see zendesk.py).
"""
import json, re, time, urllib.error, urllib.request

import store

ALLOWED = re.compile(r"^https://www\.splashtop\.com/page-data/[A-Za-z0-9/_.-]+\.json$")
TIMEOUT = 20
_CACHE = {}                 # url -> (fetched at, body): the scan asks for ~40 files at once
CACHE_SECONDS = 300
KEY = "pb:"                 # settings keys: pb:pricebookcfg, pb:pricebook


class PriceError(Exception):
    pass


def fetch(url):
    """The JSON body of one splashtop.com page-data file, as bytes."""
    if not ALLOWED.match(url or ""):
        raise PriceError("only splashtop.com page-data files can be fetched")
    hit = _CACHE.get(url)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "SplashHubCentre/1.0 (price book)"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        raise PriceError("splashtop.com answered HTTP %d" % e.code)
    except Exception as e:
        raise PriceError("could not reach www.splashtop.com (%s) -- is it in the OUTBOUND_HTTP grant?" % type(e).__name__)
    try:
        json.loads(body or b"null")
    except ValueError:
        raise PriceError("splashtop.com did not answer with JSON")
    _CACHE[url] = (time.time(), body)
    if len(_CACHE) > 200:
        _CACHE.clear()
    return body


def records():
    """The saved records, in the shape pricebook.js reads from Zendesk."""
    out = []
    for rid in ("pricebookcfg", "pricebook"):
        v = store.get_setting(KEY + rid, "")
        if v:
            out.append({"external_id": rid, "custom_object_fields": {"payload": v}})
    return {"custom_object_records": out}


def save(rid, payload, by="Centre admin"):
    if rid not in ("pricebookcfg", "pricebook"):
        raise PriceError("unknown record")
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) > 2000000:
        raise PriceError("too large")
    store.set_setting(KEY + rid, text, by)


def book():
    """The cached prices (what Ask AI reads), or None."""
    try:
        return json.loads(store.get_setting(KEY + "pricebook", "") or "null")
    except ValueError:
        return None
