"""Teams notifications: cards posted to a Teams channel through the channel's
"Send webhook alerts to a channel" workflow (Power Automate).

TEAMS_WEBHOOK_URL is that workflow's link -- a sealed Spluki secret: anyone with
it can post to the channel, so it is never logged, shown or sent anywhere else.
Its host must be in the OUTBOUND_HTTP grant (the platform's proxy refuses any
other). Until both are there, nothing is sent and Settings says why.

What is posted, each switched on in Settings > Notifications (all off at first):
  languages    open RR tickets in a routed language: "Hi @A and @B, there are 3
               Japanese tickets that require your assistance" + the tickets.
               The languages and the people to @mention are a table in Settings.
               A ticket's language: its Zendesk tag when it has one (Auto Tag's
               language_xx), else Spark reads it and picks one of the table's
               languages or "other" -- each ticket once, remembered. Posted when
               a new ticket joins a language's list        (checked every 30 min)
  needs_review an SOS package reviewed as Needs review              (sosscan.py)
  high_risk    an SOS package reviewed as High risk                 (sosscan.py)
  sso_verified an SSO domain's TXT record found                      (ssocheck.py)
  spike        SOS requests well above usual (24 h / 7 days)         (checked every 15 min)
  po_overdue   a PO request whose expected provision date has passed
               while its ticket is still open                        (checked every hour)
Each event is posted once. Cards carry the ticket number, the package / domain /
company and a button to open it in SplashHub Centre -- never an agent's name.
"""
import json, os, re, sys, threading, time, urllib.error, urllib.request

import store

CENTRE = (os.environ.get("CENTRE_URL") or "https://splashhub-37268f-dev.tperd.splashtop.dev").rstrip("/")
KINDS = {
    "languages": "Open RR tickets in a routed language (Language routing below)",
    "needs_review": "An SOS package is reviewed as Needs review",
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
            "last": last, "languages": lang_config()}


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


def card(title, lines, link=None, link_label="Open in SplashHub Centre", tone="attention", facts=(), mentions=()):
    """An Adaptive Card message, as the Teams workflow expects it. mentions:
    [(name, email)] -- write "<at>name</at>" in a line to @mention them."""
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
    if mentions:
        content["msteams"] = {"entities": [{"type": "mention", "text": "<at>%s</at>" % n, "mentioned": {"id": e, "name": n}}
                                           for n, e in mentions]}
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


def needs_review(scan_id, ticket_id, package, creator_domain, reasons):
    _send("needs_review", "nr:%s" % scan_id, card(
        "\U0001F7E0 SOS package needs review \u00b7 #%s" % ticket_id,
        ["**%s**%s" % (package or "Custom SOS package", (" \u00b7 creator @%s" % creator_domain) if creator_domain else "")] +
        ["\u2022 " + r for r in (reasons or [])[:3]],
        CENTRE + "/scans#%s" % scan_id, tone="warning"))


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


# ---- Language routing: open RR tickets in a routed language ---------------------------------

RR_QUERY = "type:ticket status<pending tags:assigned_by_rr -tags:survey"
LANG_DEFAULTS = [("Japanese", ["language_ja"]), ("Chinese", ["language_zh-cn", "language_zh-tw"]), ("Korean", ["language_ko"]),
                 ("French", ["language_fr"]), ("German", ["language_de"]), ("Spanish", ["language_es"]),
                 ("Italian", ["language_it"]), ("Portuguese", ["language_pt"])]


def lang_config():
    try:
        cfg = json.loads(store.get_setting("notify_lang", "") or "null")
    except ValueError:
        cfg = None
    if not cfg:
        cfg = {"query": RR_QUERY, "rows": [{"lang": l, "tags": t, "people": [], "on": False} for l, t in LANG_DEFAULTS]}
    cfg.setdefault("spark", True)
    return cfg


def _name_of(email):
    """first.last@splashtop.com -> First Last (what the @mention shows)."""
    local = email.split("@")[0]
    return " ".join(w.capitalize() for w in re.split(r"[._-]+", local) if w) or email


def set_lang_config(cfg):
    rows = []
    for r in (cfg.get("rows") or [])[:20]:
        lang = re.sub(r"\s+", " ", str(r.get("lang") or "")).strip()[:40]
        tags = [t for t in (re.sub(r"[^\w:.\-]", "", str(x)).strip() for x in (r.get("tags") or [])) if t][:6]
        people = []
        for x in (r.get("people") or [])[:12]:
            e = str(x.get("email") if isinstance(x, dict) else x).strip().lower()
            if re.fullmatch(r"[\w.+'-]+@splashtop\.com", e):
                people.append({"email": e, "name": (x.get("name") if isinstance(x, dict) and x.get("name") else _name_of(e))[:60]})
        if lang:                                  # tags are optional: Spark can read the language
            rows.append({"lang": lang, "tags": tags, "people": people, "on": bool(r.get("on"))})
    q = re.sub(r"\s+", " ", str(cfg.get("query") or RR_QUERY)).strip()[:300]
    if "type:ticket" not in q:
        raise ValueError("the queue must be a Zendesk ticket search (type:ticket ...)")
    store.set_setting("notify_lang", json.dumps({"query": q, "rows": rows, "spark": bool(cfg.get("spark", True))}), "notify")
    return lang_config()


def _queue_by_language(cfg, rows):
    """{language: [tickets]} for the given table rows: every open ticket in the
    queue, by its language tag, else by Spark's reading (once per ticket)."""
    import zendesk
    queue = [t for t in zendesk.search_tickets(cfg["query"], max_pages=5) if t.get("status") in ("new", "open")]
    by_tag = {}
    for r in rows:
        for tag in r.get("tags") or []:
            by_tag[tag.lower()] = r["lang"]
    groups, unknown = {r["lang"]: [] for r in rows}, []
    for t in queue:
        item = {"id": int(t["id"]), "subject": (t.get("subject") or "")[:120], "created": t.get("created_at") or ""}
        lang = next((by_tag[g.lower()] for g in t.get("tags") or [] if g.lower() in by_tag), None)
        if lang:
            groups[lang].append(item)
        else:
            unknown.append((item, t))
    if unknown and cfg.get("spark", True):
        names = [r["lang"] for r in rows]
        found = _spark_languages(names, [t for _, t in unknown])
        for item, t in unknown:
            lang = found.get(int(t["id"]))
            if lang in groups:
                groups[lang].append(item)
    return {k: sorted(v, key=lambda x: x["created"]) for k, v in groups.items()}


def _spark_languages(names, tickets):
    """{ticket id: one of names, or "Other"} -- Spark reads each ticket once;
    the answer is remembered (until the list of languages changes)."""
    import hashlib, spark
    sig = hashlib.sha256("|".join(sorted(n.lower() for n in names)).encode()).hexdigest()[:12]
    try:
        cache = json.loads(store.get_setting("notify_langdet", "") or "null") or {}
    except ValueError:
        cache = {}
    if cache.get("sig") != sig:
        cache = {"sig": sig, "map": {}}
    known = cache["map"]
    todo = [t for t in tickets if str(t["id"]) not in known]
    if todo and spark.available():
        allowed = {n.lower(): n for n in names}
        system = ("You sort support tickets by the language the CUSTOMER wrote in. The only answers allowed are: %s, or Other "
                  "(English, or any language not in that list). Ignore English signatures, disclaimers, quoted replies and "
                  "automatic text; judge the customer's own words. Answer with JSON only, one entry per ticket: "
                  '{"<ticket id>": "<language or Other>"}.') % ", ".join(names)
        for i in range(0, len(todo), 20):
            batch = todo[i:i + 20]
            text = "\n\n".join("Ticket %s\nSubject: %s\nMessage: %s" % (t["id"], (t.get("subject") or "")[:150],
                                                                       re.sub(r"\s+", " ", t.get("description") or "")[:600])
                                for t in batch)
            try:
                lg = {"area": "teams_languages", "tickets": [t["id"] for t in batch]}
                raw = spark.chat(system, text, max_tokens=600, log=lg)
                got = json.loads(raw[raw.find("{"):raw.rfind("}") + 1] or "{}")
            except Exception as e:                       # Spark down or an odd answer: ask again next time
                sys.stderr.write("[notify] Spark language check skipped: %s\n" % type(e).__name__)
                continue
            for t in batch:
                ans = str(got.get(str(t["id"])) or "Other").strip().lower()
                known[str(t["id"])] = allowed.get(ans, "Other")
            import sparklog
            sparklog.decide(lg.get("id"), "; ".join("#%s %s" % (t["id"], known[str(t["id"])]) for t in batch))
        cache["map"] = dict(list(known.items())[-3000:])
        store.set_setting("notify_langdet", json.dumps(cache), "notify")
    return {int(k): v for k, v in known.items()}


def _lang_card(row, tickets, test=False):
    import zendesk
    base = zendesk.base_url()
    people = row.get("people") or []
    names = ["<at>%s</at>" % p["name"] for p in people]
    hi = ("Hi " + ", ".join(names[:-1]) + " and " + names[-1] + ", ") if len(names) > 1 else          ("Hi %s, " % names[0] if names else "Hi team, ")
    n = len(tickets)
    lines = [hi + "there %s **%d %s ticket%s** that require%s your assistance." % (
        "is" if n == 1 else "are", n, row["lang"], "" if n == 1 else "s", "s" if n == 1 else "")]
    lines += ["\u2022 [#%d %s](%s/agent/tickets/%d)" % (t["id"], t["subject"].replace("[", "(").replace("]", ")"), base, t["id"])
              for t in tickets[:10]]
    if n > 10:
        lines.append("\u2026 and %d more." % (n - 10))
    return card(("\U0001F9EA Test \u00b7 " if test else "") + "\U0001F310 %s tickets waiting \u00b7 %d" % (row["lang"], n), lines,
                None, tone="warning", mentions=[(p["name"], p["email"]) for p in people])


def check_languages(force=False):
    """Post, per routed language, when a new ticket joins its list (force: post
    the current list now, for Run now). Returns what was found."""
    cfg = lang_config()
    found = []
    rows = [r for r in cfg["rows"] if r.get("on") or force]
    groups = _queue_by_language(cfg, rows) if rows else {}
    for row in rows:
        tickets = groups.get(row["lang"]) or []
        found.append({"lang": row["lang"], "n": len(tickets)})
        if not tickets:
            continue
        ids = sorted(t["id"] for t in tickets)
        if force:
            post(_lang_card(row, tickets, test=True), "languages")
            continue
        key = "lang:%s:%s" % (row["lang"], ",".join(map(str, ids)))
        new = [i for i in ids if not _seen("langt:%s:%s" % (row["lang"], i))]
        if new and enabled("languages"):
            for i in new:
                _once("langt:%s:%s" % (row["lang"], i))
            _send("languages", key, _lang_card(row, tickets))
    return found


def _seen(key):
    try:
        return key in set(json.loads(store.get_setting("notify_seen", "") or "[]"))
    except ValueError:
        return False


def run_now(kind):
    """Settings' Run now: post this alert now from real data, ignoring "posted
    once", marked as a test. Returns {"posted": n, "note": ...} or raises ValueError."""
    if not configured():
        raise ValueError("Teams isn't connected yet (no TEAMS_WEBHOOK_URL)")
    if kind == "languages":
        found = check_languages(force=True)
        n = sum(1 for f in found if f["n"])
        return {"posted": n, "note": ", ".join("%s %d" % (f["lang"], f["n"]) for f in found) or "no routed languages"}
    if kind in ("needs_review", "high_risk"):
        want = "needs_review" if kind == "needs_review" else "suspicious"
        rows = store.scans(None, want, 0, 1)["rows"]
        if not rows:
            return {"posted": 0, "note": "no request is %s right now" % ("Needs review" if kind == "needs_review" else "High risk")}
        import sosscan
        full = store.scan_get(rows[0]["id"], fresh=True) or {}
        res = json.loads(full.get("result_json") or "null") or {}
        pkg = next((f.get("value") for f in json.loads(full.get("fields_json") or "[]") if (f.get("label") or "").lower() == "package name"), "")
        msg = card(("\U0001F9EA Test \u00b7 ") + ("SOS package needs review" if kind == "needs_review" else "High-risk SOS package") +
                   " \u00b7 #%s" % full.get("ticket_id"),
                   ["**%s** \u00b7 creator @%s" % (pkg or "Custom SOS package", full.get("creator_domain") or "?")] +
                   ["\u2022 " + r for r in sosscan.review_reasons(full, res)[:3]], CENTRE + "/scans#%s" % full.get("id"), tone="warning")
        return {"posted": 0 if post(msg, kind) else 1, "note": "the latest one, #%s" % full.get("ticket_id")}
    if kind == "sso_verified":
        rows = [r for r in store.sso_list(None, "verified", 0, 1).get("rows", [])]
        if not rows:
            return {"posted": 0, "note": "no SSO request is verified yet"}
        r = rows[0]
        msg = card("\U0001F9EA Test \u00b7 SSO verified \u00b7 %s" % (r.get("domain") or "?"),
                   ["The TXT record for **%s** is in DNS (ticket #%s)." % (r.get("domain"), r.get("ticket_id"))], CENTRE + "/sso#%s" % r["id"], tone="good")
        return {"posted": 0 if post(msg, kind) else 1, "note": r.get("domain")}
    if kind == "spike":
        import sosdash
        sp = sosdash.build().get("spikes") or {}
        d, w = sp.get("day") or {}, sp.get("week") or {}
        msg = card("\U0001F9EA Test \u00b7 SOS requests vs usual", ["Last 24 h: **%s** (usual ~%s)%s" % (d.get("n"), round(d.get("usual") or 0), " \u26A1" if d.get("alert") else ""),
                                                               "Last 7 days: **%s** (usual ~%s)%s" % (w.get("n"), round(w.get("usual") or 0), " \u26A1" if w.get("alert") else "")],
                   CENTRE + "/scans", tone="warning")
        return {"posted": 0 if post(msg, kind) else 1, "note": "alert now" if d.get("alert") or w.get("alert") else "no spike right now (sent the numbers)"}
    if kind == "po_overdue":
        import po
        rows = po.search(when="overdue", per_page=10)["rows"]
        lines = ["\u2022 %s \u00b7 expected %s \u00b7 #%s" % (r.get("company") or r.get("spid") or "?", r.get("expected"), r["ticket_id"]) for r in rows] or ["None overdue right now."]
        return {"posted": 0 if post(card("\U0001F9EA Test \u00b7 Overdue PO requests \u00b7 %d" % len(rows), lines, CENTRE + "/po", tone="warning"), kind) else 1,
                "note": "%d overdue" % len(rows)}
    raise ValueError("unknown notification")


def boot():
    def loop():
        n = 0
        while True:
            time.sleep(CHECK_EVERY)
            n += 1
            for f, every in ((_check_spike, 1), (check_languages, 2), (_check_po, 4)):
                if n % every == 0:
                    try:
                        f()
                    except Exception as e:
                        sys.stderr.write("[notify] %s skipped: %s\n" % (f.__name__, type(e).__name__))
    threading.Thread(target=loop, name="notify-loop", daemon=True).start()
