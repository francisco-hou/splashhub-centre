"""Teams notifications: cards posted to a Teams channel through the channel's
"Send webhook alerts to a channel" workflow (Power Automate).

TEAMS_WEBHOOK_URL is that workflow's link -- a sealed Spluki secret: anyone with
it can post to the channel, so it is never logged, shown or sent anywhere else.
Its host must be in the OUTBOUND_HTTP grant (the platform's proxy refuses any
other). Until both are there, nothing is sent and Settings says why.

What is posted, each switched on in Settings > Notifications (all off at first):
  high_risk    an SOS package reviewed as High risk                 (sosscan.py)
  sso_verified an SSO domain's TXT record found                      (ssocheck.py)
  spike        SOS requests well above usual (24 h / 7 days)         (checked every 15 min)
  po_overdue   a PO request whose expected provision date has passed
               while its ticket is still open                        (checked every hour)
Each event is posted once. Cards carry the ticket number, the package / domain /
company and a button to open it in SplashHub Centre -- never an agent's name.
"""
import json, os, sys, threading, time, urllib.error, urllib.request

import store

CENTRE = (os.environ.get("CENTRE_URL") or "https://splashhub-37268f-dev.tperd.splashtop.dev").rstrip("/")
KINDS = {
    "high_risk": "An SOS package is reviewed as High risk",
    "sso_verified": "An SSO domain's TXT record is found (verified)",
    "spike": "SOS requests are well above usual (last 24 h or 7 days)",
    "po_overdue": "A PO request is overdue (expected provision date passed, ticket still open)",
}
CHECK_EVERY = 900
_lock = threading.Lock()


def _url():
    return (os.environ.get("TEAMS_WEBHOOK_URL") or "").strip()


def configured():
    u = _url()
    return u.startswith("https://")


def enabled(kind):
    return store.get_setting("notify_" + kind, "off") == "on"


def settings():
    last = store.get_setting("notify_last", "")
    try:
        last = json.loads(last) if last else None
    except ValueError:
        last = None
    return {"configured": configured(), "kinds": [{"key": k, "label": v, "on": enabled(k)} for k, v in KINDS.items()],
            "last": last}


def set_kind(kind, on):
    if kind not in KINDS:
        raise ValueError("unknown notification")
    if on and kind == "po_overdue" and not enabled(kind):
        # Only orders that become overdue from now on: the ones overdue today are known already.
        try:
            import po
            for r in po.search(when="overdue", per_page=1000)["rows"]:
                _once("po:%s:%s" % (r["ticket_id"], r.get("expected")))
        except Exception:
            pass
    store.set_setting("notify_" + kind, "on" if on else "off", "notify")


def _once(key):
    """True the first time an event key is seen (so each event is posted once)."""
    with _lock:
        try:
            seen = set(json.loads(store.get_setting("notify_seen", "") or "[]"))
        except ValueError:
            seen = set()
        if key in seen:
            return False
        seen.add(key)
        store.set_setting("notify_seen", json.dumps(sorted(seen)[-2000:]), "notify")
        return True


def card(title, lines, link=None, link_label="Open in SplashHub Centre", tone="attention", facts=()):
    """An Adaptive Card message, as the Teams workflow expects it."""
    body = [{"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "wrap": True,
             "color": {"attention": "Attention", "good": "Good", "warning": "Warning"}.get(tone, "Default")}]
    for l in lines:
        body.append({"type": "TextBlock", "text": l, "wrap": True, "spacing": "Small"})
    if facts:
        body.append({"type": "FactSet", "facts": [{"title": k, "value": str(v)} for k, v in facts if v not in (None, "")]})
    body.append({"type": "TextBlock", "text": "SplashHub Centre", "isSubtle": True, "size": "Small", "spacing": "Medium"})
    content = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4", "body": body}
    if link:
        content["actions"] = [{"type": "Action.OpenUrl", "title": link_label, "url": link}]
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
                                                "content": content}]}


def post(message, what="message"):
    """Send one card. Returns None, or a message that is safe to show. The
    link is never part of any message or log line."""
    if not configured():
        return "Teams isn't connected yet (no TEAMS_WEBHOOK_URL)"
    req = urllib.request.Request(_url(), data=json.dumps(message).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    err = None
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except urllib.error.HTTPError as e:
        err = "Teams answered HTTP %d%s" % (e.code, " -- is the host in the OUTBOUND_HTTP grant?" if e.code == 403 else "")
    except Exception as e:
        err = "could not reach Teams (%s)" % type(e).__name__
    store.set_setting("notify_last", json.dumps({"ms": int(time.time() * 1000), "what": what, "error": err}), "notify")
    sys.stderr.write("[notify] %s: %s\n" % (what, err or "posted"))
    return err


def _send(kind, key, message):
    """In the background, so a review or a check never waits on Teams."""
    if not (enabled(kind) and configured()) or not _once(key):
        return
    threading.Thread(target=post, args=(message, kind), name="notify-" + kind, daemon=True).start()


# ---- the events ------------------------------------------------------------------------------

def high_risk(scan_id, ticket_id, package, creator_domain, reasons):
    _send("high_risk", "hr:%s" % scan_id, card(
        "\U0001F534 High-risk SOS package · #%s" % ticket_id,
        ["**%s**%s" % (package or "Custom SOS package", (" · creator @%s" % creator_domain) if creator_domain else "")] +
        ["• " + r for r in (reasons or [])[:3]],
        CENTRE + "/scans#%s" % scan_id))


def sso_verified(sso_id, ticket_id, domain):
    _send("sso_verified", "sso:%s" % sso_id, card(
        "✅ SSO verified · %s" % (domain or "?"),
        ["The TXT record for **%s** is in DNS (ticket #%s)." % (domain or "?", ticket_id)],
        CENTRE + "/sso#%s" % sso_id, tone="good"))


def test():
    return post(card("\U0001F44B SplashHub Centre is connected",
                     ["This channel will get the alerts switched on in SplashHub Centre › Settings › Notifications."],
                     CENTRE + "/settings#notify", tone="good"), "test")


def _check_spike():
    if not (enabled("spike") and configured()):
        return
    import sosdash
    d = sosdash.build()
    sp = d.get("spikes") or {}
    for w, label in (("day", "last 24 hours"), ("week", "last 7 days")):
        s = sp.get(w) or {}
        if s.get("alert"):
            stamp = time.strftime("%Y-%m-%d" if w == "day" else "%Y-W%W", time.gmtime())
            pts = ((sp.get("spark") or {}).get("points") or [])[:3]
            _send("spike", "spike:%s:%s" % (w, stamp), card(
                "⚡ SOS request spike · %s" % label,
                ["**%s** requests vs. about %s usually." % (s.get("n"), round(s.get("usual") or 0))] + ["• " + p for p in pts],
                CENTRE + "/scans", tone="warning"))


def _check_po():
    if not (enabled("po_overdue") and configured()):
        return
    import po
    for r in po.search(when="overdue", per_page=50)["rows"]:
        first = (r.get("products") or [{}])[0]
        _send("po_overdue", "po:%s:%s" % (r["ticket_id"], r.get("expected")), card(
            "⏰ PO overdue · %s" % (r.get("company") or r.get("spid") or ("#%s" % r["ticket_id"])),
            ["Expected provision date **%s** has passed; ticket #%s is still %s." % (r.get("expected"), r["ticket_id"], r.get("status"))],
            CENTRE + "/po#%s" % r["ticket_id"], tone="warning",
            facts=[("Order type", r.get("order_type")), ("Product", (first.get("name") or "") + (" × %s" % first["qty"] if first.get("qty") else "")),
                   ("Region", r.get("region"))]))


def boot():
    def loop():
        n = 0
        while True:
            time.sleep(CHECK_EVERY)
            n += 1
            for f, every in ((_check_spike, 1), (_check_po, 4)):
                if n % every == 0:
                    try:
                        f()
                    except Exception as e:
                        sys.stderr.write("[notify] %s skipped: %s\n" % (f.__name__, type(e).__name__))
    threading.Thread(target=loop, name="notify-loop", daemon=True).start()
