"""The live feed: takes the runs SplashHub posts to the platform's webhook intake.

SplashHub runs inside Zendesk and cannot reach a Spluki app directly (the load
balancer is default-deny), so it POSTs each run to SPLUKI_WEBHOOK_PUBLIC_URL;
the platform holds it, and this loop takes it from SPLUKI_WEBHOOK_PICKUP_URL.

Contract (spluki doc webhook-pickup-for-developers):
  POST <pickup>/poll, Authorization: Bearer <token>, no body. Held up to 25 s,
  answered the moment anything arrives: {"events": [...]}. On a 2xx call again
  at once -- the hold is the pacing. On ANY refusal honour Retry-After.
  Taking deletes, committed before the answer is written: a response that never
  arrives takes its events with it, so the client timeout must outlast the hold.
  Each event: event_id, received_at, method, headers, platform_headers, size,
  body (BASE64), body_encoding.

Verification. The intake is public and checks nothing, so every event must
carry X-SplashHub-Key equal to RUNLOG_SECRET (a sealed secret here; a secure
Zendesk setting on SplashHub's side, substituted by Zendesk's proxy so it never
reaches a browser). Anything else is discarded and counted. With no secret set
the loop does not poll at all -- taking events it cannot verify would delete
them; left untaken they wait (24 h) until the secret is in place.

Body: {"v": 1, "source": "webhook" | "zendesk-import", "runs": [<logSharedRun entry>, ...]}
Never logged: the token, the secret, request headers.
"""
import base64, hashlib, hmac, json, os, sys, threading, time, urllib.error, urllib.request
from datetime import datetime

import store

POLL_TIMEOUT = 45          # > the platform's 25 s hold, so a held answer is never cut off
MAX_RUNS_PER_EVENT = 5000
HEADER = "x-splashhub-key"
# The same intake also takes Zendesk's own webhook (SOS package scans, sosscan.py),
# told apart by Zendesk's signature header and verified with ZENDESK_WEBHOOK_SECRET.
ZD_SIG = "x-zendesk-webhook-signature"
ZD_TS = "x-zendesk-webhook-signature-timestamp"

STATUS = {
    "enabled": False, "reason": "", "polling": False,
    "last_ok_ms": None, "last_event_ms": None, "last_error": None,
    "events": 0, "runs": 0, "rejected": 0, "last_reject": None,
}
_LOCK = threading.Lock()


def _now_ms():
    return int(time.time() * 1000)


def _log(msg):
    sys.stderr.write("[feed] %s\n" % msg)


def _set(**kw):
    with _LOCK:
        STATUS.update(kw)


def status():
    with _LOCK:
        return dict(STATUS)


def _secret():
    return (os.environ.get("RUNLOG_SECRET") or "").strip()


def _header(headers, name):
    """Headers keep the spelling they arrived with; a repeat is joined."""
    for k, v in (headers or {}).items():
        if k.lower() == name:
            return v if isinstance(v, str) else ", ".join(map(str, v))
    return ""


def _received_ms(ev):
    raw = ev.get("received_at")
    try:
        return int(datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return _now_ms()


PLACEHOLDER = "{{setting.runlog_secret}}"


def check_key(given, secret):
    """'' when the key matches; otherwise why not -- worded so the log says what
    to fix, and never containing either value. Surrounding whitespace is ignored
    on both sides: a pasted secret with a trailing space is still the secret."""
    given, secret = (given or "").strip(), (secret or "").strip()
    if not given:
        return "no X-SplashHub-Key header"
    if given == PLACEHOLDER or given.startswith("{{"):
        return ("the key arrived as the literal placeholder -- Zendesk did not fill it in, so the "
                "'Run log secret' setting is empty or not saved in Admin Center")
    if not hmac.compare_digest(given.encode(), secret.encode()):
        return "the key does not match RUNLOG_SECRET -- the two values differ"
    return ""


def _body(ev):
    raw = ev.get("body") or ""
    return base64.b64decode(raw) if (ev.get("body_encoding") or "base64") == "base64" else raw.encode()


def check_zendesk_signature(ev, body):
    """Zendesk signs each webhook call: base64(HMAC-SHA256(secret, timestamp + body)),
    over the raw bytes -- which is why the body is decoded first."""
    secret = (os.environ.get("ZENDESK_WEBHOOK_SECRET") or "").strip()
    if not secret:
        return "ZENDESK_WEBHOOK_SECRET is not set, so Zendesk's calls cannot be verified"
    sig = _header(ev.get("headers"), ZD_SIG).strip()
    ts = _header(ev.get("headers"), ZD_TS).strip()
    want = base64.b64encode(hmac.new(secret.encode(), ts.encode() + body, hashlib.sha256).digest()).decode()
    if not sig or not ts or not hmac.compare_digest(sig.encode(), want.encode()):
        return "the Zendesk signature does not match ZENDESK_WEBHOOK_SECRET"
    return ""


def _zendesk_fields(body, headers):
    """The trigger's parameters. Form-encoded is preferred -- Zendesk encodes each
    value, so a description with quotes or line breaks arrives intact; a JSON
    body ({"ticket_id": "{{ticket.id}}"}, the first setup) still works."""
    from urllib.parse import parse_qs
    text = body.decode("utf-8", "replace")
    ctype = _header(headers, "content-type").lower()
    if "json" in ctype or text.lstrip().startswith("{"):
        try:
            d = json.loads(text, strict=False)
            return d if isinstance(d, dict) else {}
        except ValueError:
            pass
    return {k: v[0] for k, v in parse_qs(text, keep_blank_values=True).items()}


def handle_zendesk(ev):
    """A Zendesk trigger asking for an SOS package scan. Its parameters:
    ticket_id (required) and, so the page can show the request before
    SplashHub Centre may call Zendesk itself, subject, requester, description
    and attachments ("name|url;;name|url;;...")."""
    try:
        body = _body(ev)
    except Exception:
        return -1, "the body is not base64"
    why = check_zendesk_signature(ev, body)
    if why:
        return -1, why
    data = _zendesk_fields(body, ev.get("headers"))
    try:
        tid = int(str(data.get("ticket_id") or (data.get("ticket") or {}).get("id") or "").strip())
    except (TypeError, ValueError, AttributeError):
        return -1, "the Zendesk body has no ticket_id"
    # SSO validation requests use the same webhook: told apart by kind=sso in
    # the trigger's body, or by their subject.
    import ssocheck
    if str(data.get("kind") or "").lower() == "sso" or ssocheck.is_sso(data.get("subject")):
        ssocheck.request(tid, "webhook", data)
        _log("SSO request listed for #%d" % tid)
        return 0, ""
    import sosscan
    sosscan.request(tid, "webhook", "Zendesk trigger", pushed=sosscan.pushed_details(data))
    _log("SOS scan queued for #%d" % tid)
    return 0, ""


def handle(ev, secret):
    """One event -> (runs stored, '') or (-1, why it was rejected)."""
    if _header(ev.get("headers"), ZD_SIG):
        return handle_zendesk(ev)
    why = check_key(_header(ev.get("headers"), HEADER), secret)
    if why:
        return -1, why
    try:
        data = json.loads(_body(ev).decode("utf-8"))
    except Exception:
        return -1, "the body is not JSON"
    runs = data.get("runs") if isinstance(data, dict) else None
    if not isinstance(runs, list):
        return -1, "the body has no runs list"
    source = "zendesk-import" if data.get("source") == "zendesk-import" else "webhook"
    got = _received_ms(ev)
    clean = []
    for r in runs[:MAX_RUNS_PER_EVENT]:
        if not isinstance(r, dict):
            continue
        r = dict(r)
        r.pop("event_id", None)          # ids are derived server-side (store.run_id)
        r["source"], r["received_ms"] = source, got
        clean.append(r)
    return store.insert_many(clean), ""


def _poll_once(url, token):
    req = urllib.request.Request(url + "/poll", data=b"", method="POST",
                                 headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=POLL_TIMEOUT) as r:
            return 200, json.loads(r.read() or b"{}"), None
    except urllib.error.HTTPError as e:
        try:
            reason = (json.loads(e.read() or b"{}").get("detail") or {}).get("reason")
        except Exception:
            reason = None
        try:
            wait = int(e.headers.get("Retry-After") or 30)
        except ValueError:
            wait = 30
        return e.code, {"reason": reason}, max(1, min(wait, 600))


def run():
    url = (os.environ.get("SPLUKI_WEBHOOK_PICKUP_URL") or "").rstrip("/")
    token = os.environ.get("SPLUKI_WEBHOOK_TOKEN") or ""
    if not url or not token:
        _set(enabled=False, reason="This release has no webhook pickup (SPLUKI_WEBHOOK not bound).")
        return
    if not _secret():
        _set(enabled=False, reason="RUNLOG_SECRET is not set, so runs are left waiting at the intake (kept 24 h).")
        _log("RUNLOG_SECRET not set -- not polling")
        return
    _set(enabled=True, reason="", polling=True)
    _log("polling the webhook pickup")
    fail_wait = 5
    while True:
        try:
            code, data, retry = _poll_once(url, token)
        except Exception as e:                      # network: never print e (could quote a URL)
            _set(last_error="pickup unreachable (%s)" % type(e).__name__)
            time.sleep(fail_wait)
            fail_wait = min(fail_wait * 2, 120)
            continue
        if code != 200:
            reason = (data or {}).get("reason") or ("HTTP %d" % code)
            _set(last_error="pickup refused: %s" % reason)
            _log("pickup refused (%d %s), retrying in %ds" % (code, reason, retry))
            time.sleep(retry)
            continue
        fail_wait = 5
        events = (data or {}).get("events") or []
        secret = _secret()
        stored = rejected = 0
        for ev in events:
            try:
                n, why = handle(ev, secret)
            except Exception as e:                  # a bad row must not stop the feed
                n, why = -1, "storing failed (%s)" % type(e).__name__
            if n < 0:
                rejected += 1
                _log("rejected %s: %s" % (ev.get("event_id") or "event", why))
                with _LOCK:
                    STATUS["last_reject"] = why
            else:
                stored += n
        with _LOCK:
            STATUS["last_ok_ms"] = _now_ms()
            STATUS["last_error"] = None
            if events:
                STATUS["last_event_ms"] = _now_ms()
                STATUS["events"] += len(events)
                STATUS["runs"] += stored
                STATUS["rejected"] += rejected
        if events:
            _log("took %d event(s): %d run(s) stored, %d rejected" % (len(events), stored, rejected))
        # 2xx: call again at once -- the platform's hold paces the loop


def start():
    t = threading.Thread(target=run, name="webhook-pickup", daemon=True)
    t.start()
    return t
